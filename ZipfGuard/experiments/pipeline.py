"""End-to-end offline MVP pipeline for the DP-HTPG proposal."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from core.data import counts_from_payload, synthetic_counts, validate_count_payload
from core.distributions import analyze_counts
from core.metrics import cracked_at_k, risk_delta
from policy.engine import DEFAULT_POLICIES, evaluate_policy, optimize_policies


def run_pipeline(payload: Mapping[str, Any] | None = None, *, seed: int = 42,
                 budgets: Sequence[int] = (100, 1_000, 10_000),
                 bootstrap_repetitions: int = 120) -> dict[str, Any]:
    started = time.perf_counter()
    normalized = validate_count_payload(payload or synthetic_counts(seed=seed))
    counts = counts_from_payload(normalized)
    analysis = analyze_counts(counts, q=0.01, budget=int(budgets[0]),
                             bootstrap_repetitions=bootstrap_repetitions, seed=seed)
    # Aggregate counts have no password strings. Policy optimisation therefore
    # runs against the public synthetic grammar, with its source stated in output.
    candidate_rows = optimize_policies(seed=seed, budgets=budgets)
    evaluated = [evaluate_policy(policy, seed=seed, budgets=budgets) for policy in candidate_rows]
    base_curve = next(row for row in evaluated if row["policy"]["name"] == "baseline")
    for row in evaluated:
        row["risk_delta"] = risk_delta(base_curve["attack"], row["attack"])
    return {
        "dataset": normalized,
        "analysis": analysis,
        "policies": evaluated,
        "recommendations": _recommendations(evaluated),
        "metadata": {
            "seed": seed, "budgets": [int(value) for value in budgets],
            "source": normalized.get("metadata", {}).get("source", normalized.get("metadata", {}).get("source_type", "unspecified")),
            "privacy": "aggregate counts only; synthetic policy benchmark; no authentication calls",
            "runtime_ms": round((time.perf_counter() - started) * 1000, 2),
        },
    }


def _recommendations(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(rows, key=lambda row: (row.get("user_cost", 1), -row.get("security_gain", 0)))
    if not ranked:
        return []
    low = ranked[0]
    high = max(rows, key=lambda row: row.get("security_gain", 0))
    balanced = min(rows, key=lambda row: abs(row.get("user_cost", 0.5) - 0.2) + abs(row.get("security_gain", 0) - high.get("security_gain", 0)) * 0.25)
    return [{"tier": "低摩擦", "policy": low["policy"], "reason": "用户成本最低的可行候选"},
            {"tier": "均衡", "policy": balanced["policy"], "reason": "风险收益与用户成本的折中"},
            {"tier": "高防护", "policy": high["policy"], "reason": "离线红队风险下降最大"}]


def write_report(result: Mapping[str, Any], path: str | Path) -> Path:
    output = Path(path); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_markdown(result), encoding="utf-8")
    return output


def write_json(result: Mapping[str, Any], path: str | Path) -> Path:
    output = Path(path); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def render_markdown(result: Mapping[str, Any]) -> str:
    analysis = result["analysis"]
    lines = ["# ZipfGuard 离线风险评估报告", "", "## 数据与复现", "",
             f"- 数据集：`{result['dataset']['dataset_id']}`",
             f"- 总样本：{result['dataset']['total_count']}",
             f"- 数据来源：{result['dataset'].get('metadata', {}).get('source_type', result['dataset'].get('metadata', {}).get('source', '未注明'))}",
             f"- 原始行数上限：{result['dataset'].get('metadata', {}).get('source_lines_read', '未注明')}",
             f"- 头部聚合质量：{1 - result['dataset'].get('metadata', {}).get('truncated_mass', 0):.4f}",
             f"- 随机种子：`{result['metadata']['seed']}`",
             f"- 运行时间：{result['metadata']['runtime_ms']} ms", "",
             "## 模型选择", "", f"选择模型：`{analysis['selected_model']}`（{analysis['selection_method']}）", "",
             "| 模型 | 验证对数似然 | KS | BIC |", "|---|---:|---:|---:|"]
    for model in analysis["models"]:
        lines.append(f"| {model['id']} | {model['validation_log_likelihood']:.3f} | {model['validation_ks']:.4f} | {model['bic']:.3f} |")
    threshold = analysis["risk_threshold"]
    lines += ["", "## 风险预算", "", f"q={threshold['q']} 时模型头部排名：{threshold['model_rank']}；预算 B={threshold['budget']} 的实测留出 Top-B 质量：{threshold['heldout_fixed_order_top_b_mass']:.4f}。", "", "## 策略对比", "", "| 策略 | 安全收益 | 用户成本 | 攻击覆盖率 |", "|---|---:|---:|---:|"]
    for row in result["policies"]:
        lines.append(f"| {row['policy']['name']} | {row['security_gain']:.4f} | {row['user_cost']:.4f} | {row['attack_coverage']:.4f} |")
    lines += ["", "## 边界", "", "结果来自有限支持的合成候选空间和离线攻击排序，不能解释为真实口令熵或真实世界破解率。"]
    return "\n".join(lines) + "\n"
