"""Metrics shared by the offline strategy and red-team experiments."""
from __future__ import annotations

import math
from typing import Iterable, Mapping, Sequence


def cracked_at_k(ranking: Sequence[str], samples: Iterable[str], budgets=(100, 1_000, 10_000)) -> list[dict]:
    ranks = {value: index + 1 for index, value in enumerate(ranking)}
    values = [ranks.get(str(sample), math.inf) for sample in samples]
    total = max(1, len(values))
    return [{"budget": int(k), "cracked": sum(rank <= k for rank in values),
             "rate": sum(rank <= k for rank in values) / total} for k in budgets if k > 0]


def risk_delta(before: Sequence[Mapping], after: Sequence[Mapping]) -> list[dict]:
    right = {row["budget"]: row for row in after}
    return [{"budget": row["budget"], "before": row["rate"],
             "after": right.get(row["budget"], {}).get("rate", 0.0),
             "delta": row["rate"] - right.get(row["budget"], {}).get("rate", 0.0)} for row in before]


def percentile(values: Sequence[float], probability: float) -> float:
    if not values:
        return float("nan")
    values = sorted(float(value) for value in values)
    position = (len(values) - 1) * probability
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return values[low]
    return values[low] + (values[high] - values[low]) * (position - low)
