"""Reproducible statistics for B-layer measurement experiments."""

from __future__ import annotations

import math
from collections import Counter
from typing import Any, Iterable, Mapping, Sequence


def safe_ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float | None, float | None]:
    """Wilson score interval for a Bernoulli proportion."""
    if total < 0 or successes < 0 or successes > total:
        raise ValueError("invalid binomial counts")
    if total == 0:
        return None, None
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return max(0.0, center - margin), min(1.0, center + margin)


def classification_metrics(expected: Sequence[bool], observed: Sequence[bool | None]) -> dict[str, Any]:
    if len(expected) != len(observed):
        raise ValueError("expected and observed lengths differ")
    tp = fp = tn = fn = unknown = 0
    for truth, prediction in zip(expected, observed):
        if prediction is None:
            unknown += 1
        elif truth and prediction:
            tp += 1
        elif not truth and prediction:
            fp += 1
        elif not truth and not prediction:
            tn += 1
        else:
            fn += 1
    precision = safe_ratio(tp, tp + fp)
    recall = safe_ratio(tp, tp + fn)
    f1 = (2 * precision * recall / (precision + recall)) if precision is not None and recall is not None and precision + recall else None
    recall_ci = wilson_interval(tp, tp + fn)
    return {
        "tp": tp, "fp": fp, "tn": tn, "fn": fn, "unknown": unknown,
        "evaluated": tp + fp + tn + fn,
        "coverage": safe_ratio(tp + fp + tn + fn, len(expected)),
        "precision": precision, "recall": recall, "f1": f1,
        "recall_wilson_95": list(recall_ci),
        "formulas": {
            "precision": "P=TP/(TP+FP)",
            "recall": "R=TP/(TP+FN)",
            "f1": "F1=2PR/(P+R)",
        },
    }


def summarize_module_round(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [dict(item) for item in records]
    verdicts = Counter(str(item.get("verdict") or "unknown") for item in rows)
    levels = Counter(
        str(level)
        for item in rows
        for level in (item.get("evidence_levels") or [])
    )
    errors = Counter(str(item.get("error_code")) for item in rows if item.get("error_code"))
    total = len(rows)
    reachable = sum(bool(item.get("entry_reachable")) for item in rows)
    positive = sum(bool(item.get("feature_positive")) for item in rows)
    evidence = sum(bool(item.get("evidence_obtained")) for item in rows)
    unknown = verdicts.get("unknown", 0)
    return {
        "total": total,
        "entry_reachable": reachable,
        "feature_positive": positive,
        "evidence_obtained": evidence,
        "unknown": unknown,
        "entry_reach_rate": safe_ratio(reachable, total),
        "positive_rate": safe_ratio(positive, total),
        "evidence_yield": safe_ratio(evidence, total),
        "unknown_rate": safe_ratio(unknown, total),
        "verdict_distribution": dict(sorted(verdicts.items())),
        "evidence_level_distribution": dict(sorted(levels.items())),
        "error_distribution": dict(sorted(errors.items())),
        "formulas": {
            "evidence_yield": "Y_evidence=N_evidence/N_total",
            "unknown_rate": "U=N_unknown/N_total",
        },
    }


def _round_key(item: Mapping[str, Any]) -> tuple[str, str]:
    return str(item.get("module_id") or ""), str(item.get("site_id") or "")


def compare_module_rounds(
    first: Iterable[Mapping[str, Any]],
    second: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    left = {_round_key(item): dict(item) for item in first}
    right = {_round_key(item): dict(item) for item in second}
    keys = sorted(set(left) | set(right))
    paired = [key for key in keys if key in left and key in right]
    exact = 0
    verdict_equal = 0
    left_positive = set()
    right_positive = set()
    labels = ("pass", "weak", "fail", "unknown", "not_applicable")
    left_counts = Counter()
    right_counts = Counter()
    for key in paired:
        a, b = left[key], right[key]
        sa = (a.get("verdict") or "unknown", bool(a.get("feature_positive")), bool(a.get("evidence_obtained")))
        sb = (b.get("verdict") or "unknown", bool(b.get("feature_positive")), bool(b.get("evidence_obtained")))
        exact += int(sa == sb)
        verdict_equal += int(sa[0] == sb[0])
        left_counts[str(sa[0])] += 1
        right_counts[str(sb[0])] += 1
        if sa[1]:
            left_positive.add(key)
        if sb[1]:
            right_positive.add(key)
    union = left_positive | right_positive
    exact_agreement = safe_ratio(exact, len(paired))
    observed_agreement = safe_ratio(verdict_equal, len(paired))
    expected_agreement = sum(
        safe_ratio(left_counts[label], len(paired)) * safe_ratio(right_counts[label], len(paired))
        for label in labels
    ) if paired else None
    kappa = None
    if observed_agreement is not None and expected_agreement is not None and expected_agreement < 1:
        kappa = (observed_agreement - expected_agreement) / (1 - expected_agreement)
    return {
        "union_keys": len(keys), "paired_keys": len(paired),
        "missing_in_round1": len(set(right) - set(left)),
        "missing_in_round2": len(set(left) - set(right)),
        "exact_signature_matches": exact,
        "exact_agreement": exact_agreement,
        "verdict_agreement": observed_agreement,
        "positive_jaccard": len(left_positive & right_positive) / len(union) if union else 1.0,
        "cohen_kappa": kappa,
        "formulas": {
            "agreement": "A_2r=N_equal/N_paired",
            "jaccard": "J_2r=|F1 intersect F2|/|F1 union F2|",
            "kappa": "kappa=(p_o-p_e)/(1-p_e)",
        },
    }
