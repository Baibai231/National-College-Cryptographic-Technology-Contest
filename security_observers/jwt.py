"""Redacted JWT metadata analysis.

The browser-side collector decodes candidate headers/claims and returns only
booleans and the short algorithm label.  Token strings and claim values never
leave the page context and are never persisted.
"""

from __future__ import annotations

import re


_SAFE_ALGORITHM = re.compile(r"^[A-Za-z0-9_-]{1,24}$")


def analyze_jwt_metadata(items) -> dict:
    sanitized = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        algorithm = str(item.get("algorithm") or "unknown")
        if not _SAFE_ALGORITHM.fullmatch(algorithm):
            algorithm = "other"
        source = item.get("source")
        if source not in {"local_storage", "session_storage"}:
            source = "other"
        sanitized.append({
            "source": source,
            "algorithm": algorithm,
            "expiration_claim": bool(item.get("expiration_claim")),
            "issuer_claim": bool(item.get("issuer_claim")),
            "audience_claim": bool(item.get("audience_claim")),
            "signature_segment_present": bool(item.get("signature_segment_present")),
        })

    if not sanitized:
        return {"status": "not_observed", "confidence": "low", "token_count": 0}

    algorithms = sorted({item["algorithm"] for item in sanitized})
    findings = []
    if "none" in {algorithm.lower() for algorithm in algorithms}:
        findings.append("unsigned_algorithm_observed")
    if any(not item["expiration_claim"] for item in sanitized):
        findings.append("expiration_claim_missing_in_observed_token")
    return {
        "status": "observed",
        "confidence": "high",
        "token_count": len(sanitized),
        "algorithms": algorithms,
        "expiration_claim_present_for_all": all(
            item["expiration_claim"] for item in sanitized),
        "issuer_claim_present_for_all": all(item["issuer_claim"] for item in sanitized),
        "audience_claim_present_for_all": all(item["audience_claim"] for item in sanitized),
        "signature_segment_present_for_all": all(
            item["signature_segment_present"] for item in sanitized),
        "storage_locations": sorted({item["source"] for item in sanitized}),
        "findings": findings,
        "raw_tokens_stored": False,
        "evidence_boundary": "browser_storage_metadata_only",
    }
