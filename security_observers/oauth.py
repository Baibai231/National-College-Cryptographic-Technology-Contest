"""Conservative OAuth/OIDC observations from already-visible URLs.

No authorization endpoint is followed and no parameter value that could carry
a secret is returned.  The analyzer reports only parameter presence and small,
allow-listed protocol enums.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse


_AUTH_PATH = re.compile(
    r"(?:^|/)(?:oauth2?|authorize|authorization|openid-connect|oidc)(?:/|$)",
    re.IGNORECASE,
)


def _response_types(values: list[str]) -> list[str]:
    observed = set()
    for value in values:
        for item in value.lower().split():
            observed.add(item if item in {"code", "token", "id_token"} else "other")
    return sorted(observed)


def analyze_oauth_urls(urls) -> dict:
    """Summarize OAuth/OIDC signals without retaining full URLs or values."""
    candidates = []
    for raw in urls or []:
        if not isinstance(raw, str) or len(raw) > 8192:
            continue
        try:
            parsed = urlparse(raw)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                continue
            query = parse_qs(parsed.query, keep_blank_values=True)
        except (TypeError, ValueError):
            continue
        looks_like_authorization = bool(_AUTH_PATH.search(parsed.path or ""))
        has_protocol_pair = "client_id" in query and "response_type" in query
        if not looks_like_authorization and not has_protocol_pair:
            continue
        candidates.append((parsed.hostname.lower().rstrip("."), query))

    if not candidates:
        return {
            "status": "not_observed",
            "confidence": "low",
            "authorization_endpoint_count": 0,
        }

    def present(name: str) -> int:
        return sum(name in query for _, query in candidates)

    def non_empty(name: str) -> int:
        return sum(
            bool(query.get(name) and any(value.strip() for value in query[name]))
            for _, query in candidates
        )

    response_types = _response_types([
        value
        for _, query in candidates
        for value in query.get("response_type", [])
    ])
    challenge_methods = set()
    for _, query in candidates:
        for value in query.get("code_challenge_method", []):
            normalized = value.upper()
            challenge_methods.add(normalized if normalized in {"S256", "PLAIN"} else "OTHER")

    return {
        "status": "observed",
        "confidence": "high" if any(
            "client_id" in query and "response_type" in query
            for _, query in candidates
        ) else "medium",
        "authorization_endpoint_count": len(candidates),
        "authorization_hosts": sorted({host for host, _ in candidates})[:20],
        "response_types": response_types,
        "state": {
            "parameter_observed": bool(present("state")),
            "non_empty_observed": bool(non_empty("state")),
        },
        "pkce": {
            "code_challenge_observed": bool(present("code_challenge")),
            "methods": sorted(challenge_methods),
        },
        "oidc": {
            "nonce_observed": bool(present("nonce")),
            "openid_scope_observed": any(
                "openid" in value.lower().split()
                for _, query in candidates
                for value in query.get("scope", [])
            ),
        },
        "redirect_uri_parameter_observed": bool(present("redirect_uri")),
        "client_id_parameter_observed": bool(present("client_id")),
        "evidence_boundary": "visible_link_and_form_metadata_only",
    }
