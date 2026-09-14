#!/usr/bin/env python3
"""Compare two B-07 safe-interaction rounds without exposing secret material."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


FEATURE_PATHS = (
    ("navigation", "loaded"),
    ("control", "click_count"),
    ("control", "error"),
    ("virtual_authenticator", "credentials_before"),
    ("virtual_authenticator", "credentials_after"),
    ("normalized", "authentication_invocations"),
    ("normalized", "registration_invocations"),
    ("normalized", "challenge_bytes"),
    ("normalized", "rp_id_relation"),
    ("normalized", "user_verification"),
    ("normalized", "allow_credentials_count"),
    ("normalized", "mediation"),
    ("normalized", "pre_click_verdict"),
    ("normalized", "guard_verdict"),
)


def _read_one(path: Path) -> dict[str, Any]:
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(records) != 1:
        raise ValueError(f"expected exactly one JSONL record in {path}, got {len(records)}")
    record = records[0]
    result = record.get("result")
    if not isinstance(result, dict):
        raise ValueError(f"missing result object in {path}")
    return _normalize_result(result)


def _claim(claims: Any, metric_id: str) -> dict[str, Any]:
    for claim in claims if isinstance(claims, list) else []:
        if isinstance(claim, dict) and claim.get("metric_id") == metric_id:
            return claim
    return {}


def _normalize_result(result: dict[str, Any]) -> dict[str, Any]:
    observer = result.get("webauthn_observer") or {}
    safe = result.get("safe_interaction") or {}
    api = _claim(observer.get("claims"), "auth.webauthn.api_invocation")
    config = _claim(observer.get("claims"), "auth.webauthn.request_configuration")
    config_value = config.get("value") if isinstance(config.get("value"), dict) else {}
    invocations = config_value.get("invocations") or []
    invocation = invocations[0] if invocations and isinstance(invocations[0], dict) else {}
    ceremonies = (api.get("value") or {}).get("ceremonies") if isinstance(api.get("value"), dict) else []
    return {
        "navigation": result.get("navigation") or {},
        "control": result.get("control") or {},
        "virtual_authenticator": result.get("virtual_authenticator") or {},
        "normalized": {
            "authentication_invocations": ceremonies.count("authentication"),
            "registration_invocations": ceremonies.count("registration"),
            "challenge_bytes": invocation.get("challenge_bytes"),
            "rp_id_relation": invocation.get("rp_id_relation"),
            "user_verification": invocation.get("user_verification"),
            "allow_credentials_count": invocation.get("allow_credentials_count"),
            "mediation": invocation.get("mediation"),
            "pre_click_verdict": _claim(
                safe.get("claims"), "auth.webauthn.pre_click_authentication"
            ).get("verdict"),
            "guard_verdict": _claim(
                safe.get("claims"), "auth.webauthn.safe_interaction_guard"
            ).get("verdict"),
        },
    }


def _get(data: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def compare_rounds(round1: dict[str, Any], round2: dict[str, Any]) -> dict[str, Any]:
    comparisons = []
    matched = 0
    observed = 0
    for path in FEATURE_PATHS:
        left = _get(round1, path)
        right = _get(round2, path)
        comparable = left is not None or right is not None
        equal = comparable and left == right
        if comparable:
            observed += 1
            matched += int(equal)
        comparisons.append(
            {
                "feature": ".".join(path),
                "round1": left,
                "round2": right,
                "comparable": comparable,
                "equal": equal,
            }
        )

    return {
        "schema_version": "webauthn-safe-round-comparison-v1",
        "formula": "A_cfg = sum_i I[x_i^(1)=x_i^(2)] / N_comparable",
        "matched_features": matched,
        "comparable_features": observed,
        "configuration_agreement": round(matched / observed, 4) if observed else None,
        "guard_statuses": {
            "safe_interaction_guard": [
                _get(round1, ("normalized", "guard_verdict")),
                _get(round2, ("normalized", "guard_verdict")),
            ],
            "pre_click_authentication": [
                _get(round1, ("normalized", "pre_click_verdict")),
                _get(round2, ("normalized", "pre_click_verdict")),
            ],
        },
        "features": comparisons,
        "privacy_note": "Only redacted derived features are compared; no challenge bytes or credential material are retained.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("round1", type=Path)
    parser.add_argument("round2", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = compare_rounds(_read_one(args.round1), _read_one(args.round2))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
