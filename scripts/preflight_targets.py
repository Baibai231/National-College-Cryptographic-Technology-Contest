"""Cheap bounded-page preflight before Selenium measurement.

The preflight downloads at most ``--max-bytes`` per page and ``--max-pages``
per domain, extracts authentication signals and ranked signup URLs, then
writes candidates in descending priority.  It never fills or submits a form.
"""
import argparse
import ipaddress
import json
import socket
import ssl
import sys
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from utils.static_auth_discovery import extract_static_auth_signals, preflight_priority
from utils.signup_candidates import same_registered_site


def _public_addresses(host: str) -> List[str]:
    addresses = []
    for info in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP):
        value = info[4][0]
        ip = ipaddress.ip_address(value)
        if any((ip.is_private, ip.is_loopback, ip.is_link_local,
                ip.is_multicast, ip.is_reserved, ip.is_unspecified)):
            raise ValueError("non_public_address")
        if value not in addresses:
            addresses.append(value)
    if not addresses:
        raise ValueError("dns_no_address")
    return addresses


class _SafeRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urljoin(req.full_url, newurl)
        parsed = urlparse(target)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("unsafe_redirect_scheme")
        _public_addresses(parsed.hostname)
        return super().redirect_request(req, fp, code, msg, headers, target)


def _decode_body(data: bytes, encoding: str) -> bytes:
    encoding = (encoding or "").lower()
    try:
        if "gzip" in encoding:
            # The response is intentionally capped at max_bytes, so a gzip
            # stream is often missing its trailer.  decompressobj accepts the
            # useful prefix without requiring an end-of-stream marker.
            return zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(
                data, 524288)
        if "deflate" in encoding:
            return zlib.decompressobj().decompress(data, 524288)
    except (EOFError, OSError, zlib.error):
        return data
    return data


def _charset(content_type: str) -> str:
    for piece in (content_type or "").split(";")[1:]:
        if piece.strip().lower().startswith("charset="):
            return piece.split("=", 1)[1].strip(" \"'") or "utf-8"
    return "utf-8"


def _fetch_page(url: str, timeout: int, max_bytes: int) -> Dict[str, Any]:
    """Fetch one bounded public page and extract static auth signals."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("invalid_http_url")
    _public_addresses(parsed.hostname)
    opener = build_opener(_SafeRedirects())
    request = Request(url, headers={
        "User-Agent": "CryptoScope-Policy-Research/1.0",
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
        "Accept-Encoding": "gzip, deflate",
        "Range": "bytes=0-{}".format(max_bytes - 1),
    })
    with opener.open(request, timeout=timeout) as response:
        data = response.read(max_bytes + 1)[:max_bytes]
        final_url = response.geturl()
        content_type = response.headers.get("Content-Type", "")
        data = _decode_body(data, response.headers.get("Content-Encoding", ""))
        signals: Dict[str, Any] = {}
        if "html" in content_type.lower() or data.lstrip().startswith(b"<"):
            try:
                text = data.decode(_charset(content_type), errors="replace")
            except LookupError:
                text = data.decode("utf-8", errors="replace")
            signals = extract_static_auth_signals(text, final_url)
        return {
            "requested_url": url,
            "final_url": final_url,
            "status_code": response.getcode(),
            "content_type": content_type.split(";", 1)[0].lower(),
            "bytes_read": len(data),
            "signals": signals,
        }


def _merge_page_signals(pages: List[Mapping[str, Any]]) -> Dict[str, Any]:
    if not pages:
        return {}
    merged = dict(pages[0].get("signals") or {})
    signup_best: Dict[str, Dict[str, Any]] = {}
    auth_best: Dict[str, Dict[str, Any]] = {}
    constraints = []
    declared = []
    for page in pages:
        signals = page.get("signals") or {}
        for key in (
            "password_input_count", "new_password_input_count",
            "email_input_count", "phone_input_count", "form_count",
        ):
            merged[key] = max(
                int(merged.get(key) or 0), int(signals.get(key) or 0))
        merged["signup_text_observed"] = bool(
            merged.get("signup_text_observed")
            or signals.get("signup_text_observed"))
        constraints.extend(signals.get("static_password_constraints") or [])
        policy = signals.get("declared_password_policy") or {}
        if policy.get("raw_texts"):
            declared.append(policy)
        for key, destination in (
            ("signup_candidates", signup_best),
            ("auth_entry_candidates", auth_best),
        ):
            for candidate in signals.get(key) or []:
                url = candidate.get("url")
                if (url and (url not in destination
                             or float(candidate.get("score") or 0)
                             > float(destination[url].get("score") or 0))):
                    destination[url] = dict(candidate)
    merged["signup_candidates"] = sorted(
        signup_best.values(),
        key=lambda value: (-float(value.get("score") or 0), value["url"]),
    )[:20]
    merged["auth_entry_candidates"] = sorted(
        auth_best.values(),
        key=lambda value: (-float(value.get("score") or 0), value["url"]),
    )[:20]
    merged["observed_signup_candidate_count"] = sum(
        1 for item in merged["signup_candidates"]
        if item.get("source") == "observed_link")
    merged["static_password_constraints"] = constraints[:20]
    if declared:
        merged["declared_password_policy"] = max(
            declared, key=lambda value: (
                bool(value.get("length_min")) + bool(value.get("length_max"))
                + len(value.get("required_classes") or []),
                len(value.get("raw_texts") or []),
            ))
    merged["pages_checked"] = len(pages)
    return merged


def preflight_one(item: Mapping[str, Any], timeout: int,
                  max_bytes: int, max_pages: int = 1) -> Dict[str, Any]:
    url = str(item.get("url") or "")
    result = {
        "domain": item.get("domain") or urlparse(url).hostname,
        "url": url,
        "rank": item.get("rank"),
        "source": item.get("source"),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "reachable": False,
        "final_url": None,
        "status_code": None,
        "content_type": None,
        "bytes_read": 0,
        "priority": 0,
        "signals": {},
        "error": None,
    }
    try:
        first = _fetch_page(url, timeout, max_bytes)
        result.update({
            "reachable": True,
            "final_url": first["final_url"],
            "status_code": first["status_code"],
            "content_type": first["content_type"],
            "bytes_read": first["bytes_read"],
        })
        pages: List[Dict[str, Any]] = [first]
        first["intent"] = "homepage"
        visited = {first["final_url"].split("#", 1)[0]}
        pending = list(
            (first.get("signals") or {}).get("auth_entry_candidates") or [])
        while pending and len(pages) < max(1, max_pages):
            candidate = pending.pop(0)
            candidate_url = str(candidate.get("url") or "")
            if (not candidate_url or candidate_url in visited
                    or not same_registered_site(first["final_url"], candidate_url)):
                continue
            visited.add(candidate_url)
            try:
                page = _fetch_page(candidate_url, timeout, max_bytes)
            except (HTTPError, URLError, TimeoutError, socket.timeout,
                    ssl.SSLError, ValueError, OSError):
                continue
            if not same_registered_site(first["final_url"], page["final_url"]):
                continue
            page["intent"] = candidate.get("intent") or "account"
            pages.append(page)
            for discovered in (
                    page.get("signals") or {}).get(
                        "auth_entry_candidates") or []:
                if discovered.get("url") not in visited:
                    pending.append(discovered)
            pending.sort(key=lambda value: -float(value.get("score") or 0))

        signals = _merge_page_signals(pages)
        result["signals"] = signals
        result["priority"] = max(
            [preflight_priority(page.get("signals") or {}) for page in pages]
            or [0]) + min(15, 5 * (len(pages) - 1))
        result["pages"] = [{
            "requested_url": page.get("requested_url"),
            "final_url": page.get("final_url"),
            "intent": page.get("intent"),
            "status_code": page.get("status_code"),
            "priority": preflight_priority(page.get("signals") or {}),
        } for page in pages]
        for page in pages[1:]:
            # Keep evidence scoped to the fetched page.  A password field on a
            # later login/event page must not be borrowed to validate an
            # unrelated earlier CTA merely because signals are merged below.
            page_signals = page.get("signals") or {}
            signup_form_signal = bool(
                page_signals.get("new_password_input_count")
                or (
                    page_signals.get("password_input_count")
                    and (page_signals.get("email_input_count")
                         or page_signals.get("signup_text_observed"))
                )
                or (page_signals.get("signup_text_observed")
                    and page_signals.get("form_count"))
            )
            if (page.get("intent") == "signup"
                    and page.get("status_code") in range(200, 400)
                    and signup_form_signal):
                result["signup_url_hint"] = page.get("final_url")
                break
        if not result.get("signup_url_hint"):
            observed = [
                candidate for candidate in signals.get("signup_candidates") or []
                if candidate.get("source") == "observed_link"]
            if observed:
                result["signup_url_hint"] = observed[0].get("url")
    except HTTPError as exc:
        result["status_code"] = exc.code
        result["error"] = "http_error:{}".format(exc.code)
    except (URLError, TimeoutError, socket.timeout, ssl.SSLError,
            ValueError, OSError) as exc:
        result["error"] = "{}:{}".format(type(exc).__name__, str(exc)[:160])
    return result


def load_targets(path: Path, limit: int = 0) -> List[Dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload.get("entries") or []
    if not isinstance(entries, list):
        raise ValueError("metadata.entries 必须是数组")
    return entries[:limit or None]


def _load_completed(path: Path) -> set:
    completed = set()
    if not path.exists():
        return completed
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            domain = item.get("domain")
            if domain:
                completed.add(domain)
    return completed


def _write_candidates(records: Iterable[Mapping[str, Any]], path: Path) -> int:
    prioritized = sorted(
        (record for record in records if record.get("reachable")),
        key=lambda item: (-int(item.get("priority") or 0),
                          item.get("rank") or 10**12),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in prioritized:
            signals = record.get("signals") or {}
            candidates = signals.get("signup_candidates") or []
            observed = [
                item for item in candidates
                if item.get("source") == "observed_link"]
            selected_url = (record.get("signup_url_hint")
                            or (observed[0]["url"] if observed else ""))
            handle.write(json.dumps({
                "site": record["url"],
                "hostname": record["domain"],
                "rank": record.get("rank"),
                "priority": record.get("priority"),
                "signup_url_hint": selected_url,
                # Only observed URLs become browser hints.  Generated common
                # paths remain useful inside browser discovery, but passing
                # eight unverified paths here would waste one navigation each.
                "signup_url_candidates": list(dict.fromkeys(
                    ([selected_url] if selected_url else []) + [
                        item["url"] for item in observed
                    ]))[:8],
                "signals": {
                    "password_input_count": signals.get("password_input_count", 0),
                    "new_password_input_count": signals.get("new_password_input_count", 0),
                    "observed_signup_candidate_count": len(observed),
                    "pages_checked": signals.get("pages_checked", 1),
                    "static_password_constraints": signals.get(
                        "static_password_constraints", []),
                    "declared_password_policy": signals.get(
                        "declared_password_policy", {}),
                },
            }, ensure_ascii=False) + "\n")
    return len(prioritized)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--candidates", required=True, type=Path,
                        help="按优先级输出供浏览器阶段读取的 JSONL")
    parser.add_argument("--workers", type=int, default=48)
    parser.add_argument("--timeout", type=int, default=12)
    parser.add_argument("--max-bytes", type=int, default=524288)
    parser.add_argument("--max-pages", type=int, default=3,
                        help="每个域最多读取的公开页面数（首页+认证入口，默认3）")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--resume", action="store_true",
                        help="跳过 output 中已完成域名，可安全续跑长批次")
    args = parser.parse_args()
    if args.workers <= 0 or args.max_bytes <= 0 or args.max_pages <= 0:
        parser.error("--workers、--max-bytes 和 --max-pages 必须大于 0")

    all_targets = load_targets(args.metadata, args.limit)
    completed = _load_completed(args.output) if args.resume else set()
    targets = [item for item in all_targets if item.get("domain") not in completed]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if args.resume and args.output.exists() else "w"
    with args.output.open(mode, encoding="utf-8") as handle:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(
                    preflight_one, item, args.timeout, args.max_bytes,
                    args.max_pages): item
                for item in targets
            }
            for index, future in enumerate(as_completed(futures), 1):
                try:
                    record = future.result()
                except BaseException as exc:
                    item = futures[future]
                    record = {
                        "domain": item.get("domain"),
                        "url": item.get("url"),
                        "rank": item.get("rank"),
                        "source": item.get("source"),
                        "reachable": False,
                        "priority": 0,
                        "signals": {},
                        "error": "worker_error:{}:{}".format(
                            type(exc).__name__, str(exc)[:160]),
                    }
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                handle.flush()
                if index % 500 == 0:
                    print("预筛 {}/{}（已跳过 {}）".format(
                        index, len(targets), len(completed)))

    records = []
    with args.output.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(json.loads(line))
    candidate_count = _write_candidates(records, args.candidates)
    print("预筛完成：新增 {}，累计 {}，可访问 {}，候选文件 {}".format(
        len(targets), len(records), candidate_count, args.candidates))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
