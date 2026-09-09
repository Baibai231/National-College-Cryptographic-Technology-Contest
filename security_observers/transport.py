"""Passive transport and HTTP response-security observations.

The collector consumes Chrome performance events that were produced by the
browser's existing navigation.  Reports contain only bounded protocol facts and
booleans; raw URLs, response headers and certificate records are never returned.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import re
from urllib.parse import urlparse


_SAFE_PROTOCOL = re.compile(r"^[A-Za-z0-9 ._+/-]{1,64}$")
_REFERRER_POLICIES = {
    "no-referrer", "no-referrer-when-downgrade", "origin",
    "origin-when-cross-origin", "same-origin", "strict-origin",
    "strict-origin-when-cross-origin", "unsafe-url",
}
_CROSS_ORIGIN_VALUES = {
    "cross-origin-opener-policy": {"unsafe-none", "same-origin-allow-popups", "same-origin"},
    "cross-origin-embedder-policy": {"unsafe-none", "require-corp", "credentialless"},
    "cross-origin-resource-policy": {"same-site", "same-origin", "cross-origin"},
}


def _event(entry):
    """Return ``(method, params)`` for a Selenium performance-log entry."""
    if not isinstance(entry, dict):
        return "", {}
    payload = entry.get("message")
    try:
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            return "", {}
        message = payload.get("message", payload)
        if not isinstance(message, dict):
            return "", {}
        params = message.get("params") or {}
        return str(message.get("method") or ""), params if isinstance(params, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return "", {}


def _url_key(value: str) -> tuple[str, str, int | None, str, str]:
    """Build an in-memory comparison key without returning query contents."""
    try:
        parsed = urlparse(value or "")
        return (
            parsed.scheme.lower(), (parsed.hostname or "").lower().rstrip("."),
            parsed.port, parsed.path or "/", parsed.query,
        )
    except (TypeError, ValueError):
        return "", "", None, "", ""


def _scheme(value: str) -> str:
    try:
        scheme = urlparse(value or "").scheme.lower()
        return scheme if scheme in {"http", "https"} else "other"
    except (TypeError, ValueError):
        return "other"


def _host(value: str) -> str:
    try:
        return (urlparse(value or "").hostname or "").lower().rstrip(".")
    except (TypeError, ValueError):
        return ""


def _safe_protocol(value, default="unknown") -> str:
    value = str(value or "").strip()
    return value if _SAFE_PROTOCOL.fullmatch(value) else default


def _headers(response) -> dict[str, str]:
    raw = response.get("headers") if isinstance(response, dict) else {}
    if not isinstance(raw, dict):
        return {}
    result = {}
    for name, value in raw.items():
        normalized = str(name).strip().lower()
        if normalized:
            result[normalized] = str(value or "")
    return result


def _select_document(events, current_url: str):
    responses = []
    requests = []
    for entry in events if isinstance(events, list) else []:
        method, params = _event(entry)
        if method == "Network.responseReceived" and params.get("type") == "Document":
            response = params.get("response")
            if isinstance(response, dict):
                responses.append((params, response))
        elif method == "Network.requestWillBeSent" and params.get("type") == "Document":
            requests.append(params)
    if not responses:
        return None, requests

    current_key = _url_key(current_url)
    for item in reversed(responses):
        if _url_key(str(item[1].get("url") or "")) == current_key:
            return item, requests
    current_host = _host(current_url)
    for item in reversed(responses):
        if current_host and _host(str(item[1].get("url") or "")) == current_host:
            return item, requests
    # Do not attribute an unrelated popup/IdP document to the current site.
    return (responses[-1] if not current_host else None), requests


def _iso_timestamp(value):
    try:
        timestamp = float(value)
        if not math.isfinite(timestamp) or timestamp <= 0:
            return None
        return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _certificate_host_matches(subject: str, hostname: str):
    subject = (subject or "").lower().rstrip(".")
    hostname = (hostname or "").lower().rstrip(".")
    if not subject or not hostname:
        return None
    if subject.startswith("*."):
        suffix = subject[1:]
        return hostname.endswith(suffix) and hostname.count(".") == subject.count(".")
    return subject == hostname


def _certificate_names_match(details: dict, hostname: str):
    san_list = details.get("sanList")
    if isinstance(san_list, list) and san_list:
        matches = [
            _certificate_host_matches(str(name), hostname)
            for name in san_list[:100]
        ]
        known = [value for value in matches if value is not None]
        return any(known) if known else None
    return _certificate_host_matches(
        str(details.get("subjectName") or ""), hostname)


def _transport_report(selected, requests, current_url: str, navigation) -> dict:
    params, response = selected if selected else ({}, {})
    response_url = str(response.get("url") or current_url or "")
    final_scheme = _scheme(response_url)
    final_host = _host(response_url)
    loader_id = str(params.get("loaderId") or "")
    transitions = []
    for request in requests:
        if loader_id and str(request.get("loaderId") or "") != loader_id:
            continue
        redirect = request.get("redirectResponse")
        new_request = request.get("request")
        if not isinstance(redirect, dict) or not isinstance(new_request, dict):
            continue
        old_url = str(redirect.get("url") or "")
        new_url = str(new_request.get("url") or "")
        transitions.append({
            "from_scheme": _scheme(old_url),
            "to_scheme": _scheme(new_url),
            "cross_host": bool(_host(old_url) and _host(new_url)
                               and _host(old_url) != _host(new_url)),
            "status_code": int(redirect.get("status"))
            if isinstance(redirect.get("status"), (int, float)) else None,
        })

    navigation = navigation if isinstance(navigation, dict) else {}
    redirect_count = len(transitions)
    if not redirect_count:
        try:
            redirect_count = max(0, min(int(navigation.get("redirect_count") or 0), 50))
        except (TypeError, ValueError):
            redirect_count = 0
    first_scheme = transitions[0]["from_scheme"] if transitions else final_scheme
    http_protocol = _safe_protocol(
        response.get("protocol") or navigation.get("next_hop_protocol"))
    security_state = str(response.get("securityState") or "unknown").lower()
    if security_state not in {"secure", "neutral", "insecure", "info", "unknown"}:
        security_state = "other"

    details = response.get("securityDetails")
    details = details if isinstance(details, dict) else {}
    tls_version = _safe_protocol(details.get("protocol"))
    cipher = _safe_protocol(details.get("cipher"))
    key_exchange = _safe_protocol(
        details.get("keyExchangeGroup") or details.get("keyExchange"))
    valid_from = _iso_timestamp(details.get("validFrom"))
    valid_to = _iso_timestamp(details.get("validTo"))
    now = datetime.now(timezone.utc)
    expired = None
    expires_within_30_days = None
    if valid_to:
        expiry = datetime.fromisoformat(valid_to.replace("Z", "+00:00"))
        expired = expiry <= now
        expires_within_30_days = not expired and (expiry - now).days < 30
    certificate_name_match = _certificate_names_match(details, final_host)
    scts = details.get("signedCertificateTimestampList")
    sct_count = len(scts) if isinstance(scts, list) else 0

    findings = []
    if final_scheme == "http":
        findings.append("plaintext_final_page_observed")
    if any(item["from_scheme"] == "https" and item["to_scheme"] == "http"
           for item in transitions):
        findings.append("https_to_http_downgrade_observed")
    if tls_version.lower() in {"tls 1", "tls 1.0", "tls 1.1"}:
        findings.append("legacy_tls_version_observed")
    if expired is True:
        findings.append("certificate_expired")
    elif expires_within_30_days is True:
        findings.append("certificate_expires_within_30_days")
    if security_state == "insecure" and final_scheme == "https":
        findings.append("browser_reported_insecure_transport")
    if certificate_name_match is False:
        findings.append("certificate_name_mismatch")

    observed = bool(selected or final_scheme in {"http", "https"})
    return {
        "status": "observed" if observed else "not_observed",
        "confidence": "high" if selected else ("medium" if observed else "low"),
        "final_page_scheme": final_scheme,
        "https_page_observed": final_scheme == "https",
        "http_protocol": http_protocol,
        "browser_security_state": security_state,
        "redirects": {
            "count": redirect_count,
            "initial_scheme": first_scheme,
            "http_to_https_observed": any(
                item["from_scheme"] == "http" and item["to_scheme"] == "https"
                for item in transitions),
            "https_downgrade_observed": any(
                item["from_scheme"] == "https" and item["to_scheme"] == "http"
                for item in transitions),
            "cross_host_observed": any(item["cross_host"] for item in transitions),
            "status_codes": [item["status_code"] for item in transitions
                             if item["status_code"] is not None][:20],
        },
        "tls": {
            "metadata_observed": bool(details),
            "version": tls_version,
            "cipher": cipher,
            "key_exchange_group": key_exchange,
            "certificate_valid_from_utc": valid_from,
            "certificate_valid_to_utc": valid_to,
            "certificate_expired": expired,
            "certificate_expires_within_30_days": expires_within_30_days,
            "certificate_name_matches_host": certificate_name_match,
            "certificate_transparency_sct_count": min(sct_count, 1000),
        },
        "findings": findings,
        "raw_urls_stored": False,
        "raw_certificates_stored": False,
        "evidence_boundary": "existing_browser_navigation_metadata_only",
    }


def _hsts(value: str) -> dict:
    max_age_match = re.search(r"(?:^|;)\s*max-age\s*=\s*(\d+)", value, re.I)
    max_age = None
    if max_age_match:
        try:
            max_age = min(int(max_age_match.group(1)), 10 * 365 * 24 * 60 * 60)
        except ValueError:
            pass
    return {
        "present": bool(value),
        "max_age_seconds": max_age,
        "include_subdomains": bool(re.search(r"(?:^|;)\s*includesubdomains\s*(?:;|$)", value, re.I)),
        "preload": bool(re.search(r"(?:^|;)\s*preload\s*(?:;|$)", value, re.I)),
    }


def _allowlisted_header_value(headers: dict[str, str], name: str) -> str:
    value = headers.get(name, "").strip().lower()
    allowed = _CROSS_ORIGIN_VALUES[name]
    return value if value in allowed else ("other" if value else "not_observed")


def _header_report(selected, current_url: str) -> dict:
    response = selected[1] if selected else {}
    headers = _headers(response)
    if not selected:
        return {
            "status": "not_observed",
            "confidence": "low",
            "response_metadata_available": False,
            "findings": [],
            "raw_header_values_stored": False,
            "evidence_boundary": "main_document_response_headers_only",
        }

    csp = headers.get("content-security-policy", "")
    csp_report_only = headers.get("content-security-policy-report-only", "")
    csp_lower = csp.lower()
    xfo_raw = headers.get("x-frame-options", "").strip().upper()
    xfo = xfo_raw if xfo_raw in {"DENY", "SAMEORIGIN"} else (
        "other" if xfo_raw else "not_observed")
    referrer_raw = headers.get("referrer-policy", "").split(",")[0].strip().lower()
    referrer = referrer_raw if referrer_raw in _REFERRER_POLICIES else (
        "other" if referrer_raw else "not_observed")
    hsts = _hsts(headers.get("strict-transport-security", ""))
    frame_ancestors = bool(re.search(r"(?:^|;)\s*frame-ancestors\b", csp_lower))

    findings = []
    https_page = _scheme(str(response.get("url") or current_url or "")) == "https"
    if https_page and not hsts["present"]:
        findings.append("hsts_not_observed")
    if not csp:
        findings.append("content_security_policy_not_observed")
    else:
        if "'unsafe-inline'" in csp_lower:
            findings.append("csp_allows_unsafe_inline")
        if "'unsafe-eval'" in csp_lower:
            findings.append("csp_allows_unsafe_eval")
    if xfo == "not_observed" and not frame_ancestors:
        findings.append("anti_framing_policy_not_observed")
    if headers.get("x-content-type-options", "").strip().lower() != "nosniff":
        findings.append("nosniff_not_observed")
    if referrer == "not_observed":
        findings.append("referrer_policy_not_observed")

    cache_control = headers.get("cache-control", "").lower()
    return {
        "status": "observed",
        "confidence": "high",
        "response_metadata_available": True,
        "status_code": int(response.get("status"))
        if isinstance(response.get("status"), (int, float)) else None,
        "strict_transport_security": hsts,
        "content_security_policy": {
            "enforced_present": bool(csp),
            "report_only_present": bool(csp_report_only),
            "default_src_directive": bool(re.search(r"(?:^|;)\s*default-src\b", csp_lower)),
            "frame_ancestors_directive": frame_ancestors,
            "object_src_directive": bool(re.search(r"(?:^|;)\s*object-src\b", csp_lower)),
            "base_uri_directive": bool(re.search(r"(?:^|;)\s*base-uri\b", csp_lower)),
            "upgrade_insecure_requests": bool(re.search(
                r"(?:^|;)\s*upgrade-insecure-requests\s*(?:;|$)", csp_lower)),
            "unsafe_inline_observed": "'unsafe-inline'" in csp_lower,
            "unsafe_eval_observed": "'unsafe-eval'" in csp_lower,
            "nonce_or_hash_source_observed": bool(re.search(
                r"'(?:nonce-|sha(?:256|384|512)-)", csp_lower)),
        },
        "x_content_type_options_nosniff": (
            headers.get("x-content-type-options", "").strip().lower() == "nosniff"),
        "anti_framing": {
            "x_frame_options": xfo,
            "csp_frame_ancestors": frame_ancestors,
        },
        "referrer_policy": referrer,
        "permissions_policy_present": bool(headers.get("permissions-policy", "")),
        "cross_origin_opener_policy": _allowlisted_header_value(
            headers, "cross-origin-opener-policy"),
        "cross_origin_embedder_policy": _allowlisted_header_value(
            headers, "cross-origin-embedder-policy"),
        "cross_origin_resource_policy": _allowlisted_header_value(
            headers, "cross-origin-resource-policy"),
        "cache_control": {
            "no_store": bool(re.search(r"(?:^|,)\s*no-store\s*(?:,|$)", cache_control)),
            "private": bool(re.search(r"(?:^|,)\s*private\b", cache_control)),
            "pragma_no_cache": headers.get("pragma", "").strip().lower() == "no-cache",
        },
        "server_header_present": bool(headers.get("server", "")),
        "x_powered_by_header_present": bool(headers.get("x-powered-by", "")),
        "findings": findings,
        "raw_header_values_stored": False,
        "evidence_boundary": "main_document_response_headers_only",
    }


def analyze_network_security(events, current_url: str = "", navigation=None) -> dict:
    """Analyze already-captured CDP events without returning their raw contents."""
    selected, requests = _select_document(events, current_url)
    return {
        "transport_security": _transport_report(
            selected, requests, current_url, navigation or {}),
        "http_security_headers": _header_report(selected, current_url),
    }
