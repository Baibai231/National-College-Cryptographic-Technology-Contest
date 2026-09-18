"""Metrics shared by the offline strategy and red-team experiments."""
from __future__ import annotations

import math
from typing import Iterable, Mapping, Sequence


def cracked_at_k(ranking: Sequence[str], samples: Iterable[str], budgets=(100, 1_000, 10_000)) -> list[dict]:
    ranks = {value: index + 1 for index, value in enumerate(ranking)}
    values = [ranks.get(str(sample), math.inf) for sample in samples]
    total = len(values)
    return [{"budget": int(k), "cracked": sum(rank <= k for rank in values),
             "rate": sum(rank <= k for rank in values) / total if total else None,
             "evaluated_count": total} for k in budgets if k > 0]


def wilson_interval(successes: int, total: int, z: float = 1.95996398454) -> tuple[float, float]:
    """Return a two-sided Wilson score interval (95% by default)."""
    if isinstance(successes, bool) or isinstance(total, bool):
        raise ValueError("successes 和 total 必须是整数")
    if int(successes) != successes or int(total) != total:
        raise ValueError("successes 和 total 必须是整数")
    successes, total = int(successes), int(total)
    if total < 0 or successes < 0 or successes > total:
        raise ValueError("须满足 0 <= successes <= total")
    if z <= 0:
        raise ValueError("z 必须为正数")
    if total == 0:
        return (0.0, 1.0)
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    radius = z * math.sqrt(
        proportion * (1 - proportion) / total + z * z / (4 * total * total)
    ) / denominator
    return max(0.0, center - radius), min(1.0, center + radius)


def evaluate_ranking(
    ranking: Sequence[str], samples: Iterable[str], budgets=(100, 1_000, 10_000),
) -> dict:
    """Evaluate one frozen ranking without changing or clipping requested budgets."""
    unique_ranking = list(dict.fromkeys(str(value) for value in ranking))
    sample_values = [str(sample) for sample in samples]
    normalized_budgets = sorted({int(value) for value in budgets if int(value) > 0})
    if not normalized_budgets:
        raise ValueError("至少需要一个正攻击预算")
    ranks = {value: index + 1 for index, value in enumerate(unique_ranking)}
    actual_ranks = [ranks.get(value, math.inf) for value in sample_values]
    total = len(actual_ranks)
    covered = sum(math.isfinite(rank) for rank in actual_ranks)

    def interval(successes: int) -> dict[str, float]:
        lower, upper = wilson_interval(successes, total)
        return {"level": 0.95, "lower": lower, "upper": upper}

    points = []
    for budget in normalized_budgets:
        cracked = sum(rank <= budget for rank in actual_ranks)
        points.append({
            "budget": budget,
            "cracked": cracked,
            "rate": cracked / total if total else 0.0,
            "interval": interval(cracked),
        })
    return {
        "total": total,
        "candidate_count": len(unique_ranking),
        "covered": covered,
        "uncovered": total - covered,
        "coverage": covered / total if total else 0.0,
        "coverage_interval": interval(covered),
        "points": points,
    }


def risk_delta(before: Sequence[Mapping], after: Sequence[Mapping]) -> list[dict]:
    right = {row["budget"]: row for row in after}
    return [{"budget": row["budget"], "before": row["rate"],
             "after": right.get(row["budget"], {}).get("rate"),
             "delta": (row["rate"] - right[row["budget"]]["rate"]
                       if row["rate"] is not None
                       and right.get(row["budget"], {}).get("rate") is not None
                       else None)} for row in before]


def percentile(values: Sequence[float], probability: float) -> float:
    if not values:
        return float("nan")
    values = sorted(float(value) for value in values)
    position = (len(values) - 1) * probability
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return values[low]
    return values[low] + (values[high] - values[low]) * (position - low)
