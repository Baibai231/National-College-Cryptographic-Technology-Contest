"""Finite-support, rank-based distribution analysis for a synthetic-data demo.

Only anonymous integer counts enter this module. Models are normalized PMFs;
CDF-Zipf is a power CDF, *not* the cumulative sum of a Zipf PMF.
Inspired by Hou & Wang, TIFS 2023, DOI 10.1109/TIFS.2022.3176185.
This implementation uses deterministic likelihood fitting and finite-support
normalization, rather than claiming to reproduce the paper's stochastic GSS.
"""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np


MODEL_LABELS = {
    "zipf": "离散 Zipf",
    "cdf_zipf": "CDF-Zipf（有限支持）",
    "stretched_exponential": "Stretched-exponential RF（有限支持）",
}


def _validate_counts(counts: Sequence[int]) -> np.ndarray:
    array = np.asarray(counts, dtype=float)
    if array.ndim != 1 or len(array) < 2 or len(array) > 100_000:
        raise ValueError("频次数组须包含 2 至 100000 个类别")
    if not np.all(np.isfinite(array)) or np.any(array < 0):
        raise ValueError("频次须为有限的非负数")
    if np.any(array != np.floor(array)) or np.sum(array) < 20:
        raise ValueError("频次须为整数，总样本数至少为 20")
    if np.sum(array) > 100_000_000:
        raise ValueError("演示系统最多接受一亿个聚合样本")
    return array.astype(np.int64)


def _golden_min(function, low: float, high: float, iterations: int = 48) -> float:
    ratio = (math.sqrt(5) - 1) / 2
    a, b = low, high
    c, d = b - ratio * (b - a), a + ratio * (b - a)
    fc, fd = function(c), function(d)
    for _ in range(iterations):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - ratio * (b - a)
            fc = function(c)
        else:
            a, c, fc = c, d, fd
            d = a + ratio * (b - a)
            fd = function(d)
    candidates = [low, high, (a + b) / 2]
    return min(candidates, key=function)


def model_pmf(name: str, size: int, parameters: dict) -> np.ndarray:
    """Return a normalized decreasing probability vector on ranks 1..size."""
    if size < 2:
        raise ValueError("支持集至少有两个类别")
    ranks = np.arange(1, size + 1, dtype=float)
    if name == "zipf":
        exponent = float(parameters["s"])
        if not 0 <= exponent <= 4:
            raise ValueError("Zipf s 超出有效范围")
        probabilities = np.exp(-exponent * np.log(ranks))
    elif name == "cdf_zipf":
        exponent = float(parameters["alpha"])
        if not 0 < exponent <= 1:
            raise ValueError("CDF-Zipf alpha 须位于 (0,1]")
        cdf = np.power(ranks / size, exponent)
        probabilities = np.diff(np.r_[0.0, cdf])
    elif name == "stretched_exponential":
        exponent = float(parameters["alpha"])
        scale = float(parameters["t"])
        if not 0 < exponent <= 1 or not 0 < scale <= 3000:
            raise ValueError("Stretched-exponential 参数超出有效范围")
        # t = lambda * K**alpha. Stable integrated Weibull-bin masses:
        # exp(-t*((r-1)/K)^alpha) - exp(-t*(r/K)^alpha).
        high = scale * np.power(ranks / size, exponent)
        low = scale * np.power((ranks - 1) / size, exponent)
        probabilities = np.exp(-low) * (-np.expm1(-(high - low)))
    else:
        raise ValueError(f"未知模型：{name}")
    # Positivity keeps held-out log likelihood finite; this is below practical
    # probability precision, not an empirical smoothing parameter.
    probabilities = np.maximum(probabilities, 1e-300)
    probabilities /= probabilities.sum()
    return probabilities


def fit_model(counts: Sequence[int], name: str) -> dict:
    """Fit probabilities by multinomial MLE on a preselected fixed rank order."""
    counts_array = np.asarray(counts, dtype=float)
    total = float(counts_array.sum())
    if total <= 0:
        raise ValueError("拟合数据不能为空")
    observed = counts_array / total
    size = len(observed)

    def loss(parameters: dict) -> float:
        return -float(np.dot(observed, np.log(model_pmf(name, size, parameters))))

    if name == "zipf":
        estimate = _golden_min(lambda s: loss({"s": s}), 0.0, 4.0)
        parameters, dimensions = {"s": estimate}, 1
    elif name == "cdf_zipf":
        estimate = _golden_min(lambda alpha: loss({"alpha": alpha}), 0.02, 1.0)
        parameters, dimensions = {"alpha": estimate, "C": size ** (-estimate)}, 1
    elif name == "stretched_exponential":
        # Multi-start alternating golden search is deterministic. Reported
        # scores are numerical fits; no global-optimality claim is made.
        candidates = []
        for initial in (0.03, 0.5, 3.0, 12.0):
            alpha, log_t = 0.5, math.log(initial)
            previous = math.inf
            for _ in range(10):
                alpha = _golden_min(
                    lambda a: loss({"alpha": a, "t": math.exp(log_t)}),
                    0.02, 1.0, 34,
                )
                log_t = _golden_min(
                    lambda t: loss({"alpha": alpha, "t": math.exp(t)}),
                    -8.0, 6.0, 34,
                )
                value = loss({"alpha": alpha, "t": math.exp(log_t)})
                if abs(previous - value) < 1e-9:
                    break
                previous = value
            candidates.append((value, alpha, math.exp(log_t)))
        _, alpha, t = min(candidates)
        parameters = {"alpha": alpha, "t": t, "lambda": t / size ** alpha}
        dimensions = 2
    else:
        raise ValueError(f"未知模型：{name}")
    pmf = model_pmf(name, size, parameters)
    cdf = np.cumsum(pmf)
    empirical_cdf = np.cumsum(observed)
    log_likelihood = float(np.dot(counts_array, np.log(pmf)))
    return {
        "id": name,
        "name": MODEL_LABELS[name],
        "parameters": {k: float(v) for k, v in parameters.items()},
        "parameter_count": dimensions,
        "log_likelihood": log_likelihood,
        "aic": 2 * dimensions - 2 * log_likelihood,
        "bic": dimensions * math.log(total) - 2 * log_likelihood,
        "ks": float(np.max(np.abs(cdf - empirical_cdf))),
        "mean_absolute_cdf_error": float(np.mean(np.abs(cdf - empirical_cdf))),
        "pmf": pmf.tolist(),
        "cdf": cdf.tolist(),
    }


def risk_threshold(probabilities: Sequence[float], q: float) -> int:
    """Smallest prefix rank whose cumulative probability reaches q."""
    if not 0 < q <= 1:
        raise ValueError("风险质量 q 须位于 (0,1]")
    array = np.asarray(probabilities, dtype=float)
    if array.ndim != 1 or not len(array) or np.any(array < 0) or not np.all(np.isfinite(array)) or array.sum() <= 0:
        raise ValueError("概率向量无效")
    cdf = np.cumsum(array / array.sum())
    return min(len(array), int(np.searchsorted(cdf, q, side="left")) + 1)


def top_b_mass(probabilities: Sequence[float], budget: int, *, oracle: bool = False) -> float:
    array = np.asarray(probabilities, dtype=float)
    if budget < 0 or int(budget) != budget or array.ndim != 1 or np.any(array < 0) or not np.all(np.isfinite(array)) or array.sum() <= 0:
        raise ValueError("概率向量或猜测预算无效")
    if oracle:
        array = np.sort(array)[::-1]
    return float(array[:int(budget)].sum() / array.sum())


def _percentile_interval(values: Sequence[float]) -> list[float]:
    return np.quantile(values, [0.025, 0.975]).astype(float).tolist()


def analyze_counts(
    counts: Sequence[int], *, q: float = 0.8, budget: int = 100,
    bootstrap_repetitions: int = 120, seed: int = 20260916,
) -> dict:
    """Return a JSON-safe analysis from anonymous counts.

    70/30 account split: learn rank order and parameters on training accounts,
    compare predictions on held-out accounts with that order frozen. The
    support is known in this synthetic experiment; unseen-support risk is not
    estimated. Percentile bootstrap intervals condition on this support.
    """
    original = _validate_counts(counts)
    if not 0 < q <= 1:
        raise ValueError("风险质量 q 须位于 (0,1]")
    if int(budget) != budget or budget < 0:
        raise ValueError("猜测预算须为非负整数")
    if not 20 <= bootstrap_repetitions <= 2000:
        raise ValueError("Bootstrap 重复次数须介于 20 与 2000")
    rng = np.random.default_rng(seed)
    training = rng.binomial(original, 0.7)
    validation = original - training
    if training.sum() == 0 or validation.sum() == 0:
        raise ValueError("样本不足以划分训练集和验证集")
    # Stable tie order is selected without looking at validation frequencies.
    order = np.argsort(-training, kind="stable")
    training, validation = training[order], validation[order]
    train_n, validation_n = int(training.sum()), int(validation.sum())
    total, size = int(original.sum()), len(original)
    empirical = np.sort(original)[::-1] / total
    validation_probabilities = validation / validation_n
    models = []
    for name in MODEL_LABELS:
        model = fit_model(training, name)
        probabilities = np.asarray(model["pmf"])
        model["validation_log_likelihood"] = float(np.dot(validation, np.log(probabilities)))
        model["validation_cross_entropy_bits"] = -model["validation_log_likelihood"] / validation_n / math.log(2)
        model["validation_ks"] = float(np.max(np.abs(np.cumsum(validation_probabilities) - np.asarray(model["cdf"]))))
        model["risk_rank"] = risk_threshold(probabilities, q)
        models.append(model)
    # Model selection follows the proposal: BIC is the first screen; when the
    # evidence is close, choose the model with the smaller error at the actual
    # risk budget rather than treating a tiny likelihood difference as truth.
    models.sort(key=lambda item: (item["bic"], item["validation_ks"]))
    selection_method = "minimum BIC"
    best = models[0]
    if len(models) > 1 and models[1]["bic"] - models[0]["bic"] < 10:
        validation_cdf_at_budget = float(np.cumsum(validation_probabilities)[min(int(budget), size) - 1]) if budget else 0.0
        best = min(models, key=lambda item: abs(item["cdf"][min(int(budget), size) - 1] - validation_cdf_at_budget) if budget else item["validation_ks"])
        selection_method = "BIC 初筛后按预算点 CDF 误差"
    bootstrap_counts = rng.multinomial(validation_n, validation_probabilities, size=bootstrap_repetitions)
    baseline = next(model for model in models if model["id"] == "cdf_zipf")
    baseline_log = np.log(baseline["pmf"])
    comparisons = []
    for model in models:
        if model["id"] == "cdf_zipf":
            continue
        differences = np.log(model["pmf"]) - baseline_log
        bootstrap_means = bootstrap_counts @ differences / validation_n
        comparisons.append({
            "model": model["id"],
            "baseline": "cdf_zipf",
            "log_likelihood_ratio": model["validation_log_likelihood"] - baseline["validation_log_likelihood"],
            "mean_log_ratio": float(np.dot(validation_probabilities, differences)),
            "mean_log_ratio_ci95": _percentile_interval(bootstrap_means),
            "method": "held-out account-weighted LLR with paired multinomial percentile bootstrap",
            "p_value": None,
        })
    # Quantile uncertainty estimates the ranked empirical functional. Re-ranking
    # each resample includes sampling-induced rank changes, but cannot discover
    # categories absent from the finite support.
    empirical_bootstrap = rng.multinomial(total, empirical, size=bootstrap_repetitions)
    ranked_bootstrap = np.sort(empirical_bootstrap, axis=1)[:, ::-1]
    threshold_samples = np.minimum(size, np.sum(np.cumsum(ranked_bootstrap, axis=1) / total < q, axis=1) + 1)
    top_mass_samples = np.sum(ranked_bootstrap[:, :budget], axis=1) / total
    frozen_top_mass = top_b_mass(validation_probabilities, budget)
    fixed_mass_samples = np.sum(bootstrap_counts[:, :budget], axis=1) / validation_n
    dkw_epsilon = math.sqrt(math.log(2 / 0.05) / (2 * validation_n))
    # Keep endpoints and log-spaced ranks for responsive vector charts.
    chart_indices = np.unique(np.r_[np.arange(min(30, size)), np.geomspace(1, size, min(size, 160)).astype(int) - 1, size - 1])
    training_probabilities = training / train_n
    curves = []
    for i in chart_indices:
        point = {
            "rank": int(i + 1),
            "empirical_probability": float(training_probabilities[i]),
            "empirical_cdf": float(np.cumsum(training_probabilities)[i]),
            "validation_cdf": float(np.cumsum(validation_probabilities)[i]),
        }
        for model in models:
            point[model["id"] + "_cdf"] = model["cdf"][i]
            point[model["id"] + "_probability"] = model["pmf"][i]
        curves.append(point)
    summary_models = [{k: v for k, v in model.items() if k not in ("pmf", "cdf")} for model in models]
    return {
        "sample_size": total,
        "support_size": size,
        "observed_categories": int(np.sum(original > 0)),
        "train_size": train_n,
        "validation_size": validation_n,
        "seed": seed,
        "selected_model": best["id"],
        "selection_method": selection_method,
        "models": summary_models,
        "curves": curves,
        "llr_comparisons": comparisons,
        "risk_threshold": {
            "q": q,
            "empirical_rank": risk_threshold(empirical, q),
            "model_rank": best["risk_rank"],
            "bootstrap_ci95": _percentile_interval(threshold_samples),
            "budget": budget,
            "effective_budget": min(budget, size),
            "oracle_top_b_mass": top_b_mass(empirical, budget),
            "oracle_top_b_ci95": _percentile_interval(top_mass_samples),
            "heldout_fixed_order_top_b_mass": frozen_top_mass,
            "heldout_top_b_ci95": _percentile_interval(fixed_mass_samples),
            "heldout_dkw_epsilon95": dkw_epsilon,
            "heldout_dkw_interval95": [max(0, frozen_top_mass - dkw_epsilon), min(1, frozen_top_mass + dkw_epsilon)],
        },
        "bootstrap": {"repetitions": bootstrap_repetitions, "confidence": 0.95, "type": "multinomial percentile; finite-support conditional"},
        "sample_size_effect": [
            {"n": n, "dkw_epsilon95": math.sqrt(math.log(40) / (2 * n)), "observed_model_ks": best["validation_ks"]}
            for n in [100, 500, 1000, 5000, 10000, 50000, 100000, 1000000]
        ],
        "limitations": [
            "所有模型仅描述当前有限支持集；不能由此推断真实世界未观测口令的风险。",
            "CDF-Zipf 使用 F(r)=(r/K)^alpha，C=K^(-alpha)；这是有限支持约束版本。",
            "采用归一化离散概率和 MLE，未复刻原论文的随机采样 GSS 全流程。",
            "LLR 按账号频次加权且在冻结排名的留出集比较；非嵌套模型不报告卡方 LRT p 值。",
            "DKW 界要求独立同分布的留出账号及预先冻结的排序；样本量图展示界的尺度，不是拟合优度 p 值。",
            "Bootstrap 条件于支持集，置信区间为探索性结果；模型选择后的区间未作选择校正。",
        ],
    }


if __name__ == "__main__":
    import json
    generated = np.random.default_rng(20260916).multinomial(20_000, model_pmf("stretched_exponential", 600, {"alpha": 0.55, "t": 2.5}))
    print(json.dumps(analyze_counts(generated), ensure_ascii=False, indent=2))
