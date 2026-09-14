"""Paper-backed password-strength-meter evaluation and site consistency.

The dataset metrics implement Section 3 of Wang et al., USENIX Security 2023.
They are deliberately separate from the live-site consistency check: browser
probes do not provide password-population frequencies or cracked/uncracked
ground truth, so reporting the paper's *accuracy* metrics for one public site
would be scientifically invalid.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Dict, Iterable, Mapping, Sequence

from application_security.models import (
    Claim,
    Evidence,
    EvidenceLevel,
    ModuleManifest,
    ModuleResult,
    ScanMode,
    Verdict,
)
from application_security.paper_registry import PASSWORD_METERS_USENIX_2023


PASSWORD_METER_MANIFEST = ModuleManifest(
    module_id="b.password_meter_evaluation",
    name_zh="口令强度计准确性与站内一致性",
    research_question=(
        "网站口令强度计能否正确刻画口令猜测难度，以及强度提示是否与本站"
        "注册表单的接受/拒绝行为自洽？"
    ),
    crypto_elements=(
        "password_guessability",
        "online_password_guessing",
        "offline_password_cracking",
        "password_strength_meter",
    ),
    paper_refs=(PASSWORD_METERS_USENIX_2023,),
    safe_modes=(ScanMode.SAFE_INTERACTION,),
    limitations=(
        "现场模式只填写口令框并读取inline反馈，不提交表单、不创建账号。",
        "站内一致性不是强度计准确率；准确率必须有频率/排名和破解真值数据。",
        "未观察到强度标签时保持unknown，不能据此判断网站没有强度计。",
        "未观察到站内矛盾也保持unknown；有限样本不能证明提示与政策始终一致。",
    ),
)


def _finite(values: Iterable[float], name: str) -> list[float]:
    result = [float(value) for value in values]
    if not result:
        raise ValueError(f"{name} must not be empty")
    if not all(math.isfinite(value) for value in result):
        raise ValueError(f"{name} must contain finite values")
    return result


def weighted_spearman(
    reference_ranks: Sequence[float],
    meter_ranks: Sequence[float],
    frequencies: Sequence[float],
) -> float:
    r"""Return the paper's weighted rank correlation.

    .. math::

       \rho_w =
       \frac{\sum_i w_i(x_i-\bar{x}_w)(y_i-\bar{y}_w)}
       {\sqrt{\sum_i w_i(x_i-\bar{x}_w)^2
                    \sum_i w_i(y_i-\bar{y}_w)^2}}

    ``reference_ranks`` and ``meter_ranks`` must already be rank vectors.  The
    weights are password frequencies, matching the online-guessing scenario in
    Wang et al.  A negative result is retained rather than cosmetically clamped.
    """
    x = _finite(reference_ranks, "reference_ranks")
    y = _finite(meter_ranks, "meter_ranks")
    w = _finite(frequencies, "frequencies")
    if not (len(x) == len(y) == len(w)):
        raise ValueError("rank and frequency vectors must have equal length")
    if any(weight < 0 for weight in w):
        raise ValueError("frequencies must be non-negative")
    total_weight = sum(w)
    if total_weight <= 0:
        raise ValueError("at least one frequency must be positive")
    mean_x = sum(weight * value for weight, value in zip(w, x)) / total_weight
    mean_y = sum(weight * value for weight, value in zip(w, y)) / total_weight
    covariance = sum(
        weight * (value_x - mean_x) * (value_y - mean_y)
        for weight, value_x, value_y in zip(w, x, y)
    )
    variance_x = sum(
        weight * (value_x - mean_x) ** 2
        for weight, value_x in zip(w, x)
    )
    variance_y = sum(
        weight * (value_y - mean_y) ** 2
        for weight, value_y in zip(w, y)
    )
    denominator = math.sqrt(variance_x * variance_y)
    if denominator == 0:
        raise ValueError("rank vectors must both have non-zero weighted variance")
    return covariance / denominator


def kl_divergence(
    cracked_distribution: Sequence[float],
    remaining_distribution: Sequence[float],
) -> float:
    r"""Return the paper's offline ``KL(P || Q)`` distribution distance.

    ``P`` is the meter-strength distribution of cracked passwords and ``Q``
    is the distribution of remaining passwords under the same attack strategy:

    .. math:: KL(P\Vert Q)=\sum_i P(i)\log(P(i)/Q(i))

    Inputs may be probabilities or non-negative bucket counts; each vector is
    normalized independently.  A positive cracked mass where the remaining
    mass is zero has mathematically infinite divergence.  No smoothing is
    silently applied because that would change the reported experiment.
    """
    p = _finite(cracked_distribution, "cracked_distribution")
    q = _finite(remaining_distribution, "remaining_distribution")
    if len(p) != len(q):
        raise ValueError("KL distributions must have equal length")
    if any(value < 0 for value in p + q):
        raise ValueError("KL distributions must be non-negative")
    total_p, total_q = sum(p), sum(q)
    if total_p <= 0 or total_q <= 0:
        raise ValueError("both KL distributions need positive mass")
    normalized_p = [value / total_p for value in p]
    normalized_q = [value / total_q for value in q]
    total = 0.0
    for p_i, q_i in zip(normalized_p, normalized_q):
        if p_i == 0:
            continue
        if q_i == 0:
            return math.inf
        total += p_i * math.log(p_i / q_i)
    return total


def offline_kl_by_strategy(samples: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Aggregate redacted bucket labels into per-attacker KL measurements.

    Rows contain ``attack_strategy``, ``meter_bucket``, boolean ``cracked`` and
    optional positive integer ``count``.  They deliberately do not contain a
    password.  Strategies are not merged because the paper reports brute-force,
    dictionary, probability and combined attackers separately.
    """
    grouped: Dict[str, Dict[str, Dict[str, float]]] = {}
    for row in samples:
        strategy = str(row.get("attack_strategy") or "").strip()
        bucket = row.get("meter_bucket")
        cracked = row.get("cracked")
        if not strategy or bucket is None or not isinstance(cracked, bool):
            continue
        count = row.get("count", 1)
        if isinstance(count, bool) or not isinstance(count, (int, float)):
            raise ValueError("KL row count must be a positive number")
        count = float(count)
        if not math.isfinite(count) or count <= 0:
            raise ValueError("KL row count must be a positive number")
        side = "cracked" if cracked else "remaining"
        bucket_key = str(bucket)
        grouped.setdefault(strategy, {"cracked": {}, "remaining": {}})
        grouped[strategy][side][bucket_key] = (
            grouped[strategy][side].get(bucket_key, 0.0) + count)

    output: Dict[str, Dict[str, Any]] = {}
    for strategy, distributions in sorted(grouped.items()):
        buckets = sorted(set(distributions["cracked"]) | set(distributions["remaining"]))
        p = [distributions["cracked"].get(bucket, 0.0) for bucket in buckets]
        q = [distributions["remaining"].get(bucket, 0.0) for bucket in buckets]
        if not sum(p) or not sum(q):
            output[strategy] = {
                "value": None, "infinite": False, "bucket_count": len(buckets),
                "reason": "both_cracked_and_remaining_distributions_required",
            }
            continue
        value = kl_divergence(p, q)
        output[strategy] = {
            "value": None if math.isinf(value) else value,
            "infinite": math.isinf(value),
            "bucket_count": len(buckets),
            "reason": "zero_remaining_mass_on_positive_cracked_bucket"
            if math.isinf(value) else None,
        }
    return output


def extreme_bin_precision(
    cracked_low: int,
    remaining_low: int,
    cracked_high: int,
    remaining_high: int,
) -> float:
    r"""Implement Eq. (5): ``Precision=(NC_L+NR_H)/N``."""
    counts = _validate_counts(
        cracked_low, remaining_low, cracked_high, remaining_high)
    total = sum(counts)
    return (counts[0] + counts[3]) / total


def precision_security(
    cracked_low: int,
    remaining_low: int,
    cracked_high: int,
    remaining_high: int,
    beta: float = 0.8,
) -> float:
    r"""Implement the paper's reconciled Precision (Eq. 6).

    .. math::

       P_{security}=\beta W_L\frac{NC_L}{NR_L+NC_L}
       +(1-\beta)W_H\frac{NR_H}{NR_H+NC_H}

    The paper uses ``beta=0.8`` to make weak-to-strong errors four times more
    important than strong-to-weak errors.  Callers may run a sensitivity study
    with other values instead of treating 0.8 as a universal constant.
    """
    if not 0 <= beta <= 1:
        raise ValueError("beta must be between 0 and 1")
    cracked_low, remaining_low, cracked_high, remaining_high = _validate_counts(
        cracked_low, remaining_low, cracked_high, remaining_high)
    low_total = cracked_low + remaining_low
    high_total = cracked_high + remaining_high
    if low_total == 0 or high_total == 0:
        raise ValueError("both the lowest and highest meter bins need samples")
    total = low_total + high_total
    weight_low = low_total / total
    weight_high = high_total / total
    return (
        beta * weight_low * cracked_low / low_total
        + (1 - beta) * weight_high * remaining_high / high_total
    )


def _validate_counts(*counts: int) -> tuple[int, ...]:
    normalized = tuple(int(value) for value in counts)
    if any(value < 0 for value in normalized):
        raise ValueError("counts must be non-negative")
    if sum(normalized) == 0:
        raise ValueError("at least one sample is required")
    return normalized


def evaluate_paper_metrics(
    samples: Sequence[Mapping[str, Any]], beta: float = 0.8
) -> Dict[str, Any]:
    """Evaluate paper metrics from an explicitly labelled offline dataset.

    Required fields for WSpearman are ``reference_rank``, ``meter_rank`` and
    ``frequency``.  Required fields for Precision are ``meter_bin`` (``low`` or
    ``high``) and boolean ``cracked``.  Missing families stay ``None`` rather
    than being inferred from browser acceptance.
    """
    ranked = [
        row for row in samples
        if all(key in row for key in ("reference_rank", "meter_rank", "frequency"))
    ]
    result: Dict[str, Any] = {
        "weighted_spearman": None,
        "offline_kl_divergence_by_strategy": offline_kl_by_strategy(samples),
        "extreme_bin_precision": None,
        "precision_security": None,
        "beta": beta,
    }
    if ranked:
        result["weighted_spearman"] = weighted_spearman(
            [row["reference_rank"] for row in ranked],
            [row["meter_rank"] for row in ranked],
            [row["frequency"] for row in ranked],
        )

    extreme = [row for row in samples if row.get("meter_bin") in {"low", "high"}
               and isinstance(row.get("cracked"), bool)]
    if extreme:
        cl = sum(row["meter_bin"] == "low" and row["cracked"] for row in extreme)
        rl = sum(row["meter_bin"] == "low" and not row["cracked"] for row in extreme)
        ch = sum(row["meter_bin"] == "high" and row["cracked"] for row in extreme)
        rh = sum(row["meter_bin"] == "high" and not row["cracked"] for row in extreme)
        if cl + rl and ch + rh:
            result["extreme_bin_precision"] = extreme_bin_precision(cl, rl, ch, rh)
            result["precision_security"] = precision_security(cl, rl, ch, rh, beta)
    return result


def _stable_evidence_id(target: str, observation: Mapping[str, Any]) -> str:
    payload = json.dumps(
        {"target": target, "observation": observation},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return "password-meter:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def analyze_site_meter_consistency(
    target: str, probes: Sequence[Mapping[str, Any]]
) -> ModuleResult:
    r"""Compare a site's own meter labels with its own validation outcome.

    This operational metric is intentionally named *consistency*, not
    accuracy:

    .. math:: C_{site}=1-(N_{accepted,weak}+N_{rejected,strong})/N_{paired}

    It detects internally surprising UI behaviour.  It cannot establish real
    password guessability and therefore cannot substitute for the paper metrics.
    """
    allowed_levels = {"weak", "medium", "strong"}
    allowed_outcomes = {"accepted", "rejected"}
    sanitized = []
    for probe in probes or ():
        level = str(probe.get("strength_meter_level") or "").lower()
        outcome = str(probe.get("outcome") or "").lower()
        item = {
            "password_length": probe.get("password_length"),
            "character_profile": probe.get("character_profile") or "",
            "outcome": outcome,
            "strength_meter_level": level,
        }
        if level in allowed_levels:
            sanitized.append(item)

    paired = [item for item in sanitized if item["outcome"] in allowed_outcomes]
    accepted_weak = sum(
        item["outcome"] == "accepted" and item["strength_meter_level"] == "weak"
        for item in paired
    )
    rejected_strong = sum(
        item["outcome"] == "rejected" and item["strength_meter_level"] == "strong"
        for item in paired
    )
    disagreement = accepted_weak + rejected_strong
    consistency = (1 - disagreement / len(paired)) if paired else None
    observation = {
        "formula": "C_site = 1 - (N_accepted_weak + N_rejected_strong) / N_paired",
        "probe_total": len(probes or ()),
        "meter_labeled_total": len(sanitized),
        "paired_total": len(paired),
        "accepted_weak": accepted_weak,
        "rejected_strong": rejected_strong,
        "consistency": consistency,
        "probes": sanitized,
    }
    evidence_id = _stable_evidence_id(target, observation)
    evidence = Evidence(
        evidence_id=evidence_id,
        source_type="inline_password_meter_and_validation",
        level=EvidenceLevel.OBSERVED,
        observation=observation,
        artifact_hash=evidence_id.split(":", 1)[1],
    )
    observed = bool(sanitized)
    contradiction = bool(disagreement)
    claims = (
        Claim(
            metric_id="auth.password_meter.site_consistency",
            crypto_property="password_strength_meter",
            # A contradiction is positive evidence of an inconsistency.  Its
            # absence is not positive evidence of correctness: labels can be
            # missing and the finite probe set does not cover the policy space.
            verdict=Verdict.WEAK if contradiction else Verdict.UNKNOWN,
            value=observation,
            evidence_ids=(evidence_id,) if observed else (),
            paper_ref_ids=(PASSWORD_METERS_USENIX_2023.reference_id,),
            limitations=(
                "C_site是本站提示与本站校验的一致率，不是口令猜测准确率。",
                "weak被接受可能表示强度计仅作建议；strong被拒绝也可能违反未识别的政策。",
                "未观察到矛盾只表示当前样本内未发现问题，不能升级为pass。",
            ),
        ),
        Claim(
            metric_id="auth.password_meter.paper_accuracy_metrics",
            crypto_property="password_guessability",
            verdict=Verdict.UNKNOWN,
            value={
                "weighted_spearman": None,
                "offline_kl_divergence_by_strategy": {},
                "extreme_bin_precision": None,
                "precision_security": None,
                "reason": "live_probe_has_no_frequency_rank_or_cracking_ground_truth",
                "implemented_by": "evaluate_paper_metrics",
            },
            evidence_ids=(),
            paper_ref_ids=(PASSWORD_METERS_USENIX_2023.reference_id,),
            limitations=("需要经伦理处理的口令分布与破解实验数据后才能计算。",),
        ),
    )
    return ModuleResult(
        module_id=PASSWORD_METER_MANIFEST.module_id,
        schema_version="password-meter-evaluation-1.0",
        scan_mode=ScanMode.SAFE_INTERACTION,
        claims=claims,
        evidence=(evidence,) if observed else (),
        limitations=PASSWORD_METER_MANIFEST.limitations,
    )
