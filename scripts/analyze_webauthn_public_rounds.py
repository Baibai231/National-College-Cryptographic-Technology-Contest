#!/usr/bin/env python3
"""Compare two B-07 public Passkey observation rounds."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Set


PRESENCE_FEATURES = (
    "navigation_loaded",
    "dom_passkey_visible",
    "api_invocation",
    "request_configuration",
    "cose_algorithm_observed",
    "lifecycle_signal",
    "well_known_endpoints",
    "well_known_related_origins",
)


def _read_round(path: Path) -> Dict[str, Dict[str, Any]]:
    records = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("schema_version") != "webauthn-public-observation-1.0":
                raise ValueError("{}:{} unsupported schema".format(path, line_number))
            site_id = record.get("site_id")
            if not isinstance(site_id, str) or site_id in records:
                raise ValueError("{}:{} duplicate/invalid site".format(path, line_number))
            records[site_id] = record
    return records


def _claim(module: Mapping[str, Any], metric_id: str) -> Mapping[str, Any]:
    for claim in module.get("claims") or []:
        if claim.get("metric_id") == metric_id:
            return claim
    return {}


def _presence(record: Mapping[str, Any]) -> Dict[str, bool]:
    browser = record.get("browser_probe") or {}
    passive = browser.get("passive_protocol") or {}
    webauthn = browser.get("webauthn_observer") or {}
    well_known = record.get("well_known") or {}
    dom = _claim(passive, "auth.passkey.visible_control").get("value") or {}
    api = _claim(webauthn, "auth.webauthn.api_invocation").get("value") or {}
    config = _claim(webauthn, "auth.webauthn.request_configuration").get("value") or {}
    cose = _claim(webauthn, "auth.webauthn.cose_algorithm_policy").get("value") or {}
    lifecycle = _claim(webauthn, "auth.webauthn.lifecycle_sync").get("value") or {}
    endpoints = _claim(well_known, "auth.passkey.well_known_endpoints").get("value") or {}
    related = _claim(well_known, "auth.webauthn.related_origins").get("value") or {}
    return {
        "navigation_loaded": bool((browser.get("navigation") or {}).get("loaded")),
        "dom_passkey_visible": bool(dom.get("observed")),
        "api_invocation": bool(api.get("observed")),
        "request_configuration": bool(config.get("invocations")),
        "cose_algorithm_observed": bool(cose.get("offered_total")),
        "lifecycle_signal": bool(lifecycle.get("observed")),
        "well_known_endpoints": bool(endpoints.get("resource_observed")),
        "well_known_related_origins": bool(related.get("resource_observed")),
    }


def _feature_set(record: Mapping[str, Any]) -> Set[str]:
    presence = _presence(record)
    features = {key for key, value in presence.items() if value}
    browser = record.get("browser_probe") or {}
    webauthn = browser.get("webauthn_observer") or {}
    api = _claim(webauthn, "auth.webauthn.api_invocation").get("value") or {}
    for ceremony in api.get("ceremonies") or []:
        features.add("ceremony:" + str(ceremony))
    cose = _claim(webauthn, "auth.webauthn.cose_algorithm_policy").get("value") or {}
    for group in (
        "recommended", "not_recommended", "deprecated",
        "symmetric_or_mac_incompatible", "unknown_or_non_signature",
    ):
        if cose.get(group):
            features.add("cose_group:" + group)
    profile = _claim(webauthn, "auth.webauthn.passkey_profile").get("value") or {}
    for mode in ("conditional", "discoverable", "non_discoverable"):
        if profile.get(mode + "_count"):
            features.add("auth_mode:" + mode)
    lifecycle = _claim(webauthn, "auth.webauthn.lifecycle_sync").get("value") or {}
    for signal in lifecycle.get("signal_types") or []:
        features.add("lifecycle:" + str(signal))
    return features


def _round_summary(records: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    total = len(records)
    counts = {
        feature: sum(_presence(record)[feature] for record in records.values())
        for feature in PRESENCE_FEATURES
    }
    coverage = {
        feature: round(count / total, 4) if total else None
        for feature, count in counts.items()
    }
    visible = counts["dom_passkey_visible"]
    api_and_visible = sum(
        _presence(record)["dom_passkey_visible"]
        and _presence(record)["api_invocation"]
        for record in records.values()
    )
    return {
        "site_count": total,
        "positive_directory_claim_count": total,
        "observed_counts": counts,
        "coverage": coverage,
        "coverage_formula": "C_x=N_x/N_cohort",
        "api_given_visible_control": (
            round(api_and_visible / visible, 4) if visible else None
        ),
        "conditional_formula": "P_API|DOM=N(API and DOM)/N(DOM)",
        "unknown_boundary": (
            "No evidence on an unauthenticated public page is not evidence of no Passkey support."
        ),
    }


def compare(first: Mapping[str, Dict[str, Any]], second: Mapping[str, Dict[str, Any]]) -> Dict[str, Any]:
    common = sorted(set(first) & set(second))
    missing = {
        "only_round_1": sorted(set(first) - set(second)),
        "only_round_2": sorted(set(second) - set(first)),
    }
    per_site = []
    total_intersection = 0
    total_union = 0
    total_presence_matches = 0
    total_presence_fields = 0
    for site_id in common:
        f1 = _feature_set(first[site_id])
        f2 = _feature_set(second[site_id])
        union = f1 | f2
        intersection = f1 & f2
        jaccard = len(intersection) / len(union) if union else 1.0
        p1 = _presence(first[site_id])
        p2 = _presence(second[site_id])
        matches = sum(p1[key] == p2[key] for key in PRESENCE_FEATURES)
        total_intersection += len(intersection)
        total_union += len(union)
        total_presence_matches += matches
        total_presence_fields += len(PRESENCE_FEATURES)
        per_site.append({
            "site_id": site_id,
            "feature_jaccard": round(jaccard, 4),
            "presence_agreement": round(matches / len(PRESENCE_FEATURES), 4),
            "round_1_features": sorted(f1),
            "round_2_features": sorted(f2),
            "added_in_round_2": sorted(f2 - f1),
            "missing_in_round_2": sorted(f1 - f2),
        })
    return {
        "schema_version": "webauthn-public-round-comparison-1.0",
        "round_1": _round_summary(first),
        "round_2": _round_summary(second),
        "paired_site_count": len(common),
        "missing_sites": missing,
        "two_round_consistency": {
            "weighted_feature_jaccard": (
                round(total_intersection / total_union, 4)
                if total_union else 1.0
            ),
            "binary_presence_agreement": (
                round(total_presence_matches / total_presence_fields, 4)
                if total_presence_fields else None
            ),
            "jaccard_formula": "J_2r=sum_i|F_i1 intersect F_i2|/sum_i|F_i1 union F_i2|",
            "presence_formula": "A_2r=sum_i,j I[x_ij1=x_ij2]/(N_paired*|X|)",
        },
        "sites": per_site,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("round_1", type=Path)
    parser.add_argument("round_2", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = compare(_read_round(args.round_1), _read_round(args.round_2))
    serialized = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        if args.output.exists():
            parser.error("output already exists; choose a new comparison file")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    else:
        print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
