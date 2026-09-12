"""Build a reproducible large-scale target corpus from Tranco plus supplements.

Alexa Top Sites was retired in 2022.  Tranco publishes a daily, research-
oriented successor in the same ``rank,domain`` format.  This script downloads
one snapshot, records its permanent list ID, selects the leading N domains, and
then appends explicitly supplied Chinese-site lists without silently replacing
ranked domains.

Only a target list is produced; this command does not visit or measure sites.
"""
import argparse
import csv
import io
import ipaddress
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse
from urllib.request import Request, urlopen


TRANCO_CSV_URL = "https://tranco-list.eu/top-1m.csv.zip"
TRANCO_ID_URL = "https://tranco-list.eu/top-1m-id"
_DOMAIN_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$", re.I)


def normalize_domain(value: str) -> Optional[str]:
    raw = (value or "").strip()
    if not raw or raw.startswith("#"):
        return None
    if "://" in raw:
        raw = urlparse(raw).hostname or ""
    else:
        raw = raw.split("/")[0].split(":")[0]
    raw = raw.strip(".").lower()
    if raw.startswith("www."):
        raw = raw[4:]
    try:
        raw = raw.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    try:
        ipaddress.ip_address(raw)
        return None
    except ValueError:
        pass
    labels = raw.split(".")
    if len(labels) < 2 or any(not _DOMAIN_LABEL.match(label) for label in labels):
        return None
    return raw


def parse_tranco_csv(text: Iterable[str], limit: int) -> List[Tuple[int, str]]:
    selected: List[Tuple[int, str]] = []
    seen = set()
    for row in csv.reader(text):
        if len(row) < 2:
            continue
        try:
            rank = int(row[0])
        except ValueError:
            continue
        domain = normalize_domain(row[1])
        if domain is None or domain in seen:
            continue
        selected.append((rank, domain))
        seen.add(domain)
        if len(selected) >= limit:
            break
    return selected


def read_tranco_zip(content: bytes, limit: int) -> List[Tuple[int, str]]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        csv_names = [name for name in archive.namelist()
                     if name.lower().endswith(".csv")]
        if not csv_names:
            raise ValueError("Tranco 压缩包中没有 CSV")
        with archive.open(csv_names[0]) as raw:
            lines = io.TextIOWrapper(raw, encoding="utf-8", newline="")
            return parse_tranco_csv(lines, limit)


def load_supplements(paths: Iterable[Path]) -> List[Tuple[str, str]]:
    items: List[Tuple[str, str]] = []
    seen = set()
    for path in paths:
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            domain = normalize_domain(line)
            if domain and domain not in seen:
                items.append((domain, str(path)))
                seen.add(domain)
    return items


def build_entries(
    ranked: Iterable[Tuple[int, str]],
    supplements: Iterable[Tuple[str, str]],
) -> List[Dict]:
    entries: List[Dict] = []
    seen = set()
    for rank, domain in ranked:
        if domain in seen:
            continue
        entries.append({
            "domain": domain,
            "url": "https://{}/".format(domain),
            "source": "tranco",
            "rank": rank,
        })
        seen.add(domain)
    for domain, source_path in supplements:
        if domain in seen:
            continue
        entries.append({
            "domain": domain,
            "url": "https://{}/".format(domain),
            "source": "supplement",
            "source_path": source_path,
            "rank": None,
        })
        seen.add(domain)
    return entries


def _download(url: str, timeout: int) -> bytes:
    request = Request(url, headers={
        "User-Agent": "CryptoScope-Research-Corpus-Builder/1.0",
    })
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def download_snapshot(csv_url: str, id_url: str,
                      timeout: int) -> Tuple[bytes, str]:
    content = _download(csv_url, timeout)
    list_id = _download(id_url, timeout).decode("utf-8").strip()
    return content, list_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=int, default=10000,
                        help="选取 Tranco 前 N 个域名（默认 10000）")
    parser.add_argument("--supplement", action="append", default=[], type=Path,
                        help="补充中文/专题站点清单；可重复")
    parser.add_argument("--output", required=True, type=Path,
                        help="输出 run_measurement 可读取的 URL 文本")
    parser.add_argument("--metadata", required=True, type=Path,
                        help="输出来源、榜单 ID、排名和去重信息 JSON")
    parser.add_argument("--tranco-zip", type=Path,
                        help="使用本地 Tranco zip，便于离线复现")
    parser.add_argument("--tranco-id", default="",
                        help="本地 zip 对应的永久 Tranco list ID")
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()
    if args.top <= 0:
        parser.error("--top 必须大于 0")

    if args.tranco_zip:
        zip_content = args.tranco_zip.read_bytes()
        list_id = args.tranco_id or "local-unrecorded"
    else:
        zip_content, list_id = download_snapshot(
            TRANCO_CSV_URL, TRANCO_ID_URL, args.timeout)

    ranked = read_tranco_zip(zip_content, args.top)
    if len(ranked) < args.top:
        raise RuntimeError(
            "Tranco 有效域名不足: 需要 {}，得到 {}".format(args.top, len(ranked)))
    supplements = load_supplements(args.supplement)
    entries = build_entries(ranked, supplements)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.metadata.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(item["url"] + "\n" for item in entries), encoding="utf-8")
    metadata = {
        "schema_version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "selection": {
            "tranco_top": args.top,
            "supplement_count": sum(
                1 for item in entries if item["source"] == "supplement"),
            "total_distinct_domains": len(entries),
            "selection_bias_note": (
                "supplements are appended and labeled; measurement success is "
                "not used to select or remove targets"
            ),
        },
        "sources": {
            "tranco": {
                "list_id": list_id,
                "csv_url": TRANCO_CSV_URL,
                "id_url": TRANCO_ID_URL,
            },
            "supplements": [str(path) for path in args.supplement],
        },
        "entries": entries,
    }
    args.metadata.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print("生成 {} 个不同域名；Tranco ID={}；补充站点={}".format(
        len(entries), list_id,
        metadata["selection"]["supplement_count"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
