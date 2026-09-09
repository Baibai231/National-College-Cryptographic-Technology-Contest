"""Passive cookie posture observations without persisting cookie contents."""

from __future__ import annotations

import re
from urllib.parse import urlparse


_SESSION_NAME = re.compile(
    r"(?:^|[_-])(?:session(?:id)?|sess(?:id)?|sid|auth|token|jwt)(?:$|[_-])|"
    r"connect\.sid|jsessionid|phpsessid",
    re.IGNORECASE,
)


def analyze_cookie_posture(cookies, page_url: str = "") -> dict:
    cookies = [cookie for cookie in (cookies or []) if isinstance(cookie, dict)]
    https_observed = urlparse(page_url or "").scheme.lower() == "https"
    session_like = [
        cookie for cookie in cookies
        if _SESSION_NAME.search(str(cookie.get("name") or ""))
    ]

    def counts(items):
        same_site = {"strict": 0, "lax": 0, "none": 0, "unspecified": 0}
        for item in items:
            value = str(item.get("sameSite") or "").lower()
            same_site[value if value in same_site else "unspecified"] += 1
        return {
            "count": len(items),
            "secure_count": sum(bool(item.get("secure")) for item in items),
            "http_only_count": sum(bool(item.get("httpOnly")) for item in items),
            "same_site": same_site,
        }

    findings = []
    if https_observed and any(not item.get("secure") for item in session_like):
        findings.append("session_like_cookie_without_secure")
    if any(not item.get("httpOnly") for item in session_like):
        findings.append("session_like_cookie_without_http_only")

    return {
        "status": "observed" if cookies else "not_observed",
        "confidence": "medium" if session_like else ("low" if cookies else "low"),
        "https_page_observed": https_observed,
        "all_cookies": counts(cookies),
        "session_like_cookies": counts(session_like),
        "findings": findings,
        "raw_cookie_names_stored": False,
        "raw_cookie_values_stored": False,
        "authenticated_session_verified": False,
        "evidence_boundary": "current_pre_authentication_cookie_jar_only",
    }
