"""End-to-end offline MVP pipeline for the DP-HTPG proposal."""
from __future__ import annotations

import json
import dataclasses
import tempfile
import hashlib
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from ai.pcfg_adapter import PCFGAttacker, PCFGConfig, runtime_status as pcfg_runtime_status
from core.attackers import (
    CharacterNgramAttacker,
    FrequencyAttacker,
    SyntheticDictionaryAttacker,
    default_attackers,
)
from core.data import counts_from_payload, validate_count_payload
from core.distributions import analyze_counts
from core.synthetic import (
    aggregate_synthetic_counts,
    aligned_train_validation_counts,
    generate_synthetic_dataset,
    validate_synthetic_dataset,
)
from experiments.policy_attack import run_policy_attack_experiment
from experiments.policy_search import run_policy_search, PolicySearchConfig, enumerate_candidate_policies
from experiments.config import load_config, validate_config, experiment_context
from experiments.provenance import manifest
from ai.registry import build_attackers, OptionalAttackerFailed
from ai.passllm_adapter import PassLLMConfig, runtime_status as passllm_status
from policy.engine import PasswordPolicy
from policy.engine import optimize_policies


def _run_pipeline(
    payload: Mapping[str, Any] | None = None, *, seed: int = 42,
    budgets: Sequence[int] = (100, 1_000, 10_000),
    bootstrap_repetitions: int = 120,
    synthetic_dataset: Mapping[str, Any] | None = None,
    synthetic_size: int = 20_000,
    synthetic_exponent: float = 1.08,
    include_pcfg: bool = False,
    pcfg_config: PCFGConfig | None = None,
    config=None, attack_models=None, search_attackers=None,
) -> dict[str, Any]:
    started = time.perf_counter()
    if payload is not None and synthetic_dataset is not None:
        raise ValueError("payload 与 synthetic_dataset 不能同时提供")
    if include_pcfg and payload is not None:
        raise ValueError(
            "PCFG 需要带固定 train/validation/test 划分的合成用户数据；"
            "聚合频次输入不包含可训练的明文划分"
        )

    simulation = None
    resolved_pcfg_config = pcfg_config or PCFGConfig.workspace_default()
    pcfg_status = pcfg_runtime_status(resolved_pcfg_config)
    if payload is None:
        simulation = validate_synthetic_dataset(
            synthetic_dataset or generate_synthetic_dataset(
                size=synthetic_size, seed=seed, exponent=synthetic_exponent,
            )
        )
        normalized = validate_count_payload(aggregate_synthetic_counts(simulation))
        analysis_counts, training_counts, validation_counts = aligned_train_validation_counts(simulation)
        analysis = analyze_counts(
            analysis_counts, q=config["q"], budget=int(budgets[0]),
            bootstrap_repetitions=bootstrap_repetitions, seed=seed,
            training_counts=training_counts, validation_counts=validation_counts,
        )
        candidate_rows = [PasswordPolicy(**{**p, "risk_budget": config["search"]["risk_budget"]}) for p in config["comparison_policies"]]
        policy_experiment = run_policy_attack_experiment(
            simulation, candidate_rows, budgets=budgets, seed=seed,
            attackers=attack_models,
        )
        attack_baselines = _m2_view_from_policy_experiment(policy_experiment)
        evaluated = policy_experiment["policies"]
        policy_search = run_policy_search(
            simulation, budgets=budgets, seed=seed,
            search_attackers=search_attackers,
            final_attackers=attack_models,
            config=PolicySearchConfig(**config["search"]),
            candidate_policies=[dataclasses.replace(p, risk_budget=config["search"]["risk_budget"]) for p in enumerate_candidate_policies(config["search_actions"], config["max_action_count"])],
        )
        policy_evaluation = "M3 preserved-user response with frozen/adaptive attacks"
    else:
        normalized = validate_count_payload(payload)
        counts = counts_from_payload(normalized)
        analysis = analyze_counts(
            counts, q=config["q"], budget=int(budgets[0]),
            bootstrap_repetitions=bootstrap_repetitions, seed=seed,
        )
        evaluated = []
        policy_evaluation = "not run: aggregate counts do not contain policy features"
        attack_baselines = None
        policy_experiment = None
        policy_search = None

    return {
        "reproducibility": manifest(config, simulation or normalized, attack_models or ()),
        "dataset": normalized,
        "analysis": analysis,
        "policies": evaluated,
        "attack_baselines": attack_baselines,
        "policy_experiment": policy_experiment,
        "policy_search": policy_search,
        "recommendations": (
            policy_search["recommendations"] if policy_search is not None else []
        ),
        "simulation": ({
            "dataset_id": simulation["dataset_id"],
            "metadata": simulation["metadata"],
        } if simulation is not None else None),
        "metadata": {
            "seed": seed, "budgets": [int(value) for value in budgets],
            "source": normalized.get("metadata", {}).get("source", normalized.get("metadata", {}).get("source_type", "unspecified")),
            "privacy": "local synthetic users or aggregate counts only; no authentication calls",
            "policy_evaluation": policy_evaluation,
            "attack_evaluation": (
                "train fit / validation selection / test evaluation"
                if attack_baselines is not None else
                "not run: aggregate counts do not contain split-level password strings"
            ),
            "policy_search": (
                "validation Pareto search / selected tiers tested once"
                if policy_search is not None else
                "not run: aggregate counts do not contain user-level policy features"
            ),
            "pcfg": {
                **pcfg_status,
                "requested": bool(include_pcfg),
                "enabled": bool(any(a.attacker_id == "pcfg" for a in (attack_models or ())) and simulation is not None),
                "evaluation_mode": (
                    "pure PCFG; upstream OMEN fallback disabled"
                    if any(a.attacker_id == "pcfg" for a in (attack_models or ())) and simulation is not None else
                    "not participating"
                ),
            },
            "runtime_ms": round((time.perf_counter() - started) * 1000, 2),
        },
    }


def run_pipeline(payload=None, *, config=None, seed=None, budgets=None,
                 bootstrap_repetitions=None, synthetic_dataset=None,
                 synthetic_size=None, synthetic_exponent=None,
                 include_pcfg=None, pcfg_config=None):
    """Resolve one config; restart comparisons after an optional model fails.

    A failed optional model is removed from the ENTIRE experiment, including
    validation selection. This prevents policies being compared using different
    worst-attacker sets after a late adaptive or final-test failure.
    """
    cfg = load_config(preset="quick") if config is None else validate_config(config)
    if config is None:
        cfg["synthetic"]["size"] = 20_000
        cfg["bootstrap_repetitions"] = 120
    for key, value in (("seed", seed), ("budgets", budgets), ("bootstrap_repetitions", bootstrap_repetitions)):
        if value is not None:
            cfg[key] = list(value) if key == "budgets" else value
    if synthetic_size is not None: cfg["synthetic"]["size"] = synthetic_size
    if synthetic_exponent is not None: cfg["synthetic"]["exponent"] = synthetic_exponent
    if include_pcfg is True: cfg["attackers"].setdefault("pcfg", "optional")
    if include_pcfg is False: cfg["attackers"].pop("pcfg", None)
    if pcfg_config:
        cfg["pcfg"].update(generation_limit=pcfg_config.generation_limit, timeout_seconds=pcfg_config.timeout_seconds)
    cfg = validate_config(cfg)
    failures = []
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="zipfguard_run_") as temporary, experiment_context(cfg):
        resolved = pcfg_config or dataclasses.replace(PCFGConfig.workspace_default(**cfg["pcfg"]), runtime_root=Path(temporary) / "pcfg")
        while True:
            excluded = {row["attacker_id"] for row in failures}
            attacks = build_attackers(cfg, resolved, excluded=excluded)
            search = build_attackers(cfg, resolved, excluded=excluded, search=True)
            try:
                result = _run_pipeline(payload, seed=cfg["seed"], budgets=cfg["budgets"],
                    bootstrap_repetitions=cfg["bootstrap_repetitions"], synthetic_dataset=synthetic_dataset,
                    synthetic_size=cfg["synthetic"]["size"], synthetic_exponent=cfg["synthetic"]["exponent"],
                    include_pcfg="pcfg" in cfg["attackers"], pcfg_config=resolved,
                    config=cfg, attack_models=attacks, search_attackers=search)
                break
            except OptionalAttackerFailed as exc:
                if exc.attacker_id in excluded: raise
                failures.append({"attacker_id": exc.attacker_id, "reason": exc.reason,
                    "participated": False, "excluded_from_worst_case": True})
    result["metadata"].update(
        attacker_failures=failures,
        participating_attackers=[a.attacker_id for a in attacks] if result["simulation"] else [],
        comparison_complete=not failures,
        passllm=passllm_status(PassLLMConfig.workspace_default(Path(__file__).resolve().parents[2])),
        runtime_ms=round((time.perf_counter() - started) * 1000, 2),
        evaluation_scope=(
            "封闭合成候选排序；PCFG 生成后匹配候选，排名按匹配顺序计数；不是开放生成预算评测"
            if result["simulation"] else
            "公开聚合频次的分布拟合；未运行攻击、用户响应或策略搜索"
        ),
    )
    result["metadata"]["pcfg"]["failure"] = next((r["reason"] for r in failures if r["attacker_id"] == "pcfg"), None)
    return result


def _m2_view_from_policy_experiment(experiment: Mapping[str, Any]) -> dict[str, Any]:
    baseline = next(
        row for row in experiment["policies"] if row["policy"]["name"] == "baseline"
    )
    split_counts = baseline["response"]["by_split"]
    return {
        "dataset_id": experiment["dataset_id"],
        "protocol": {
            "fit_split": "train",
            "selection_split": "validation",
            "evaluation_split": "test",
            "candidate_source": "public synthetic grammar",
            "test_used_for_ranking": False,
            "interval": "pointwise 95% Wilson score interval",
            "reused_by_m3": True,
        },
        "split_sizes": {
            split: int(split_counts[split]["total"])
            for split in ("train", "validation", "test")
        },
        "budgets": list(experiment["budgets"]),
        "attacks": [{
            "attacker": attack["frozen"]["ranking"],
            "evaluation": attack["frozen"]["evaluation"],
        } for attack in baseline["attacks"]],
    }


def write_report(result: Mapping[str, Any], path: str | Path) -> Path:
    output = Path(path); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_markdown(result), encoding="utf-8")
    return output


def write_json(result: Mapping[str, Any], path: str | Path) -> Path:
    output = Path(path); output.parent.mkdir(parents=True, exist_ok=True)
    content = (json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    output.write_bytes(content)
    output.with_suffix(output.suffix + ".sha256").write_text(hashlib.sha256(content).hexdigest() + "  " + output.name + "\n", encoding="utf-8")
    return output


def render_markdown(result: Mapping[str, Any]) -> str:
    analysis = result["analysis"]
    source_metadata = result["dataset"].get("metadata", {})
    total_label = (
        "Top-K 保留频次" if source_metadata.get("source_semantics") == "frequency_counts"
        else "总样本"
    )
    lines = ["# ZipfGuard 离线风险评估报告", "", "## 数据与复现", "",
             f"- 数据集：`{result['dataset']['dataset_id']}`",
             f"- {total_label}：{result['dataset']['total_count']}",
             f"- 数据来源：{result['dataset'].get('metadata', {}).get('source_type', result['dataset'].get('metadata', {}).get('source', '未注明'))}",
             f"- 原始行数上限：{result['dataset'].get('metadata', {}).get('source_lines_read', '未注明')}",
             f"- 头部聚合质量：{1 - result['dataset'].get('metadata', {}).get('truncated_mass', 0):.4f}",
             f"- 随机种子：`{result['metadata']['seed']}`",
             f"- 运行时间：{result['metadata']['runtime_ms']} ms", "",
             "## 模型选择", "", f"选择模型：`{analysis['selected_model']}`（{analysis['selection_method']}）", "",
             "| 模型 | 验证对数似然 | KS | BIC |", "|---|---:|---:|---:|"]
    if source_metadata.get("source_semantics") == "frequency_counts":
        lines[9:9] = [
            f"- 完整扫描总频次：{source_metadata.get('observed_frequency_total', '未注明')}",
            f"- 有效/空白/异常行：{source_metadata.get('observed_valid_lines', '未注明')}/"
            f"{source_metadata.get('blank_lines', '未注明')}/"
            f"{source_metadata.get('invalid_lines', '未注明')}",
            "- 用途：公开泄露语料的聚合分布外部验证；不运行攻击、用户响应或策略搜索。",
        ]
    if result.get("simulation"):
        split_counts = result["simulation"].get("metadata", {}).get("split_counts", {})
        lines[8:8] = [
            f"- 数据划分：train={split_counts.get('train', '未注明')}，validation={split_counts.get('validation', '未注明')}，test={split_counts.get('test', '未注明')}",
            "- 用途：train/validation 用于分布拟合验证；攻击器使用 train 拟合、validation 选参、test 评价；M3 在三个划分内独立模拟用户响应",
        ]
    for model in analysis["models"]:
        lines.append(f"| {model['id']} | {model['validation_log_likelihood']:.3f} | {model['validation_ks']:.4f} | {model['bic']:.3f} |")
    threshold = analysis["risk_threshold"]
    lines += ["", "## 风险预算", "", f"q={threshold['q']} 时模型头部排名：{threshold['model_rank']}；预算 B={threshold['budget']} 的实测留出 Top-B 质量：{threshold['heldout_fixed_order_top_b_mass']:.4f}。"]
    attack_baselines = result.get("attack_baselines")
    lines += ["", "## M2 攻击基线", ""]
    if attack_baselines:
        budgets = attack_baselines["budgets"]
        header = ["攻击器", "候选数", "覆盖率（95% CI）"] + [f"cracked@{budget:,}（95% CI）" for budget in budgets]
        lines += ["| " + " | ".join(header) + " |", "|" + "---|" + "---:|" * (len(header) - 1)]
        for row in attack_baselines["attacks"]:
            evaluation = row["evaluation"]
            coverage_interval = evaluation["coverage_interval"]
            values = [
                row["attacker"]["label"],
                str(evaluation["candidate_count"]),
                f"{evaluation['coverage']:.4f} [{coverage_interval['lower']:.4f}, {coverage_interval['upper']:.4f}]",
            ]
            by_budget = {point["budget"]: point for point in evaluation["points"]}
            for budget in budgets:
                point = by_budget[budget]
                interval = point["interval"]
                values.append(f"{point['rate']:.4f} [{interval['lower']:.4f}, {interval['upper']:.4f}]")
            lines.append("| " + " | ".join(values) + " |")
        lines += [
            "",
            "协议：攻击器只用 train 拟合，参数只用 validation 选择，以上指标只在 test 计算；区间为逐点 95% Wilson 区间。",
        ]
    else:
        lines.append("未运行攻击基线：聚合频次不包含固定划分的口令字符串。")
    lines += ["", "## M3 用户响应", ""]
    if result["policies"]:
        lines += [
            "| 策略 | 初始接受率 | 最终完成率 | 修改率 | 修改用户平均尝试数 |",
            "|---|---:|---:|---:|---:|",
        ]
        for row in result["policies"]:
            response = row["response"]["overall"]
            lines.append(
                f"| {row['policy']['name']} | {response['initial_accept_rate']:.4f} | "
                f"{response['completion_rate']:.4f} | {response['modification_rate']:.4f} | "
                f"{response['mean_attempts_per_modified']:.3f} |"
            )
        lines += [
            "",
            "最终完成率以原用户总数为分母；被拒用户会重新选择口令，不会从评估样本中删除。",
            "",
            "## M3 冻结与自适应攻击",
            "",
        ]
        budgets = result["policy_experiment"]["budgets"]
        headers = ["策略", "攻击器"] + [f"@{budget:,} 冻结 / 自适应 / 差值" for budget in budgets]
        lines += ["| " + " | ".join(headers) + " |", "|" + "---|" * 2 + "---:|" * len(budgets)]
        for policy_row in result["policies"]:
            for attack in policy_row["attacks"]:
                values = [policy_row["policy"]["name"], attack["label"]]
                for point in attack["adaptive_minus_frozen"]:
                    values.append(
                        f"{point['frozen_rate']:.4f} / {point['adaptive_rate']:.4f} / {point['rate_delta']:+.4f}"
                    )
                lines.append("| " + " | ".join(values) + " |")
        lines += [
            "",
            "冻结攻击沿用原始 train 上的排名；自适应攻击在策略响应后的 train 上重新拟合，并仅用响应后的 validation 选参。正差值表示攻击者适应策略后恢复了更多破解能力；各点的 Wilson 区间保存在 JSON 报告中。",
            "",
            "## M3 最坏攻击者风险",
            "",
            "| 策略 | 预算 | 最坏冻结风险 | 最坏自适应风险 | 适应增益 | 相对基线风险下降 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for row in result["policies"]:
            for point in row["worst_case"]:
                lines.append(
                    f"| {row['policy']['name']} | {point['budget']:,} | {point['frozen_rate']:.4f} | "
                    f"{point['adaptive_rate']:.4f} | {point['adaptation_gain']:+.4f} | "
                    f"{point['risk_reduction_vs_baseline']:+.4f} |"
                )
    else:
        lines.append("未运行策略实验：聚合频次不包含口令结构或用户响应信息。")
    policy_search = result.get("policy_search")
    lines += ["", "## M4 策略搜索与 Pareto 前沿", ""]
    if policy_search:
        lines += [
            f"- validation 候选：{policy_search['candidate_count']}",
            f"- 去重后的攻击场景：{policy_search['unique_attack_scenarios']}",
            f"- 满足成本约束：{policy_search['feasible_count']}",
            f"- Pareto 前沿：{policy_search['pareto_count']}",
            f"- 选择预算：{policy_search['config']['risk_budget']:,}",
            "- 选择阶段不读取 test 指标；仅选中的档位进入一次最终 test 评价。",
            "",
            "| Pareto 策略 | validation 自适应风险 | validation 安全收益 | 修改率 | 响应成本 | 规则成本 | 总成本 |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        by_name = {
            row["policy"]["name"]: row
            for row in policy_search["validation_candidates"]
        }
        for name in policy_search["pareto_front"]:
            row = by_name[name]
            lines.append(
                f"| {name} | {row['adaptive_risk']:.4f} | {row['security_gain']:+.4f} | "
                f"{row['response']['modification_rate']:.4f} | {row['costs']['response_cost']:.4f} | "
                f"{row['costs']['rule_cost']:.4f} | {row['costs']['total_cost']:.4f} |"
            )
        lines += [
            "",
            "## M4 三档最终建议",
            "",
            "| 档位 | 策略 | validation 风险 | test 最坏自适应风险 | test 风险下降 | test 修改率 |",
            "|---|---|---:|---:|---:|---:|",
        ]
        for row in policy_search["selected_tiers"]:
            lines.append(
                f"| {row['tier']} | {row['policy']['name']} | "
                f"{row['validation']['adaptive_risk']:.4f} | {row['test']['adaptive_risk']:.4f} | "
                f"{row['test']['security_gain']:+.4f} | {row['test']['response']['modification_rate']:.4f} |"
            )
    else:
        lines.append("未运行 M4：聚合频次不包含用户响应和策略搜索所需信息。")
    boundary = (
        "结果来自有限支持的合成候选空间、规则化用户响应和离线攻击排序，不能解释为真实口令熵、真实用户行为或真实世界破解率。M3 已避免删除被拒用户；M4 建议仅是当前候选集、成本权重和合成响应模型下的 Pareto 选择，真实部署前仍须通过授权用户研究校准。"
        if result.get("simulation") else
        "结果只描述公开聚合语料中保留 Top-K 类别的条件频率分布；没有独立攻击训练/测试划分，也没有用户响应信息，不能解释为策略实施后的真实破解率。"
    )
    lines += ["", "## 边界", "", boundary]
    lines += ["", "## 实验参与与复现清单", "",
              "- 实际参与：" + ", ".join(result["metadata"].get("participating_attackers", [])),
              "- PassLLM：环境可检测；尚未接入主评估；当前实验未使用。",
              "- 评测范围：" + result["metadata"].get("evaluation_scope", ""),
              "- 可选模型失败后从整次比较排除，不使用替代模型冒充。"]
    for failure in result["metadata"].get("attacker_failures", []):
        lines.append(f"- 未参与最坏攻击者比较：{failure['attacker_id']}；{failure['reason']}")
    lines += ["", "完整配置、环境和源码哈希：", "", "```json",
              json.dumps(result.get("reproducibility", {}), ensure_ascii=False, indent=2), "```", "",
              "结果 JSON 的精确文件 SHA-256 见同名 .json.sha256 文件（网页下载同时提供校验文件）。"]
    return "\n".join(lines) + "\n"
