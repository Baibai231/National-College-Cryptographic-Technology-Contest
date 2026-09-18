"""M4 constrained policy search and Pareto-front selection."""
from __future__ import annotations

import dataclasses
import hashlib
import itertools
import math
from typing import Any, Mapping, Sequence

from core.attackers import (
    BaselineAttacker,
    CharacterNgramAttacker,
    FrequencyAttacker,
    SyntheticDictionaryAttacker,
)
from core.metrics import evaluate_ranking
from core.synthetic import passwords_for_split, validate_synthetic_dataset
from experiments.policy_attack import run_policy_attack_experiment
from policy.engine import PasswordPolicy
from policy.response import response_candidate_space, simulate_policy_response


@dataclasses.dataclass(frozen=True)
class PolicySearchConfig:
    risk_budget: int = 1_000
    min_completion_rate: float = 1.0
    max_modification_rate: float = 1.0
    max_mean_attempts_per_modified: float = 4.0
    max_total_cost: float = 0.95
    min_security_gain: float = 0.005
    response_cost_weight: float = 0.85
    rule_cost_weight: float = 0.15
    version: str = "m4-2026.1"


def _canonical_name(policy: PasswordPolicy) -> str:
    parts = [f"l{policy.min_length}"]
    if policy.required_classes:
        parts.append(f"c{policy.required_classes}")
    if policy.deny_features:
        parts.append("deny-" + "+".join(sorted(policy.deny_features)))
    return "search-" + "-".join(parts)


def enumerate_candidate_policies() -> list[PasswordPolicy]:
    """Enumerate baseline plus all unique one- and two-action policies."""
    actions = (
        ("length-8", "min_length", 8),
        ("length-10", "min_length", 10),
        ("length-12", "min_length", 12),
        ("classes-2", "required_classes", 2),
        ("deny-year", "deny_feature", "year_suffix"),
        ("deny-keyboard", "deny_feature", "keyboard_walk"),
        ("deny-common", "deny_feature", "common_word"),
    )
    configurations: dict[tuple[int, int, tuple[str, ...]], PasswordPolicy] = {}
    baseline = PasswordPolicy(version="m4-2026.1")
    configurations[(0, 0, ())] = baseline
    for action_count in (1, 2):
        for selected in itertools.combinations(actions, action_count):
            min_length = 0
            required_classes = 0
            denied: set[str] = set()
            for _, field, value in selected:
                if field == "min_length":
                    min_length = max(min_length, int(value))
                elif field == "required_classes":
                    required_classes = max(required_classes, int(value))
                else:
                    denied.add(str(value))
            key = (min_length, required_classes, tuple(sorted(denied)))
            policy = PasswordPolicy(
                min_length=min_length,
                required_classes=required_classes,
                deny_features=key[2],
                allow_passphrase=True,
                risk_budget=1_000,
                version="m4-2026.1",
            )
            configurations[key] = dataclasses.replace(policy, name=_canonical_name(policy))
    rows = list(configurations.values())
    return sorted(rows, key=lambda row: (
        row.name != "baseline", row.min_length, row.required_classes,
        len(row.deny_features), row.deny_features, row.name,
    ))


def _rule_complexity(policy: PasswordPolicy) -> dict[str, Any]:
    active_rules = (
        int(policy.min_length > 0)
        + int(policy.required_classes > 0)
        + len(policy.deny_features)
        + int(policy.deny_context_overlap)
        + int(not policy.allow_passphrase)
    )
    return {
        "active_rules": active_rules,
        "normalized_cost": min(1.0, active_rules / 6.0),
    }


def _costs(
    response: Mapping[str, Any], policy: PasswordPolicy, config: PolicySearchConfig,
) -> dict[str, float]:
    validation = response["by_split"]["validation"]
    distribution = response["distribution"]["validation"]
    length_increase = max(
        0.0, distribution["after"]["mean_length"] - distribution["before"]["mean_length"]
    )
    response_cost = (
        0.65 * validation["modification_rate"]
        + 0.25 * min(1.0, validation["mean_attempts_per_user"] / 3.0)
        + 0.10 * min(1.0, length_increase / 10.0)
    )
    rule_cost = _rule_complexity(policy)["normalized_cost"]
    total_cost = (
        config.response_cost_weight * response_cost
        + config.rule_cost_weight * rule_cost
    )
    return {
        "response_cost": response_cost,
        "rule_cost": rule_cost,
        "total_cost": total_cost,
        "mean_length_increase": length_increase,
    }


def _search_attackers() -> tuple[BaselineAttacker, ...]:
    # Fixed n-gram settings make validation a policy-selection set rather than
    # repeatedly tuning a model on the same metric.  Full tuning is restored
    # for the one-time final test evaluation of selected policies.
    return (
        FrequencyAttacker(),
        SyntheticDictionaryAttacker(),
        CharacterNgramAttacker(orders=(3,), smoothing_values=(0.3,)),
    )


def _attack_signature(*groups: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for group in groups:
        digest.update(len(group).to_bytes(8, "big"))
        for value in group:
            encoded = str(value).encode("utf-8")
            digest.update(len(encoded).to_bytes(4, "big"))
            digest.update(encoded)
    return digest.hexdigest()


def _validation_row(
    dataset: Mapping[str, Any], policy: PasswordPolicy, *, seed: int,
    budgets: Sequence[int], attackers: Sequence[BaselineAttacker],
    config: PolicySearchConfig, attack_cache: dict[str, tuple[list[dict[str, Any]], float, str]],
) -> dict[str, Any]:
    response = simulate_policy_response(dataset, policy, seed=seed)
    transformed = response["dataset"]
    train = passwords_for_split(transformed, "train")
    validation = passwords_for_split(transformed, "validation")
    candidates = response_candidate_space(policy)
    signature = _attack_signature(train, validation, candidates)
    cached = attack_cache.get(signature)
    if cached is None:
        attack_rows = []
        for attacker in attackers:
            ranking = attacker.fit_select_rank(train, validation, candidates)
            evaluation = evaluate_ranking(ranking.guesses, validation, budgets)
            attack_rows.append({
                "attacker_id": attacker.attacker_id,
                "label": attacker.label,
                "ranking": ranking.summary(),
                "evaluation": evaluation,
            })
        budget = config.risk_budget
        winner = max(
            attack_rows,
            key=lambda row: next(
                point["rate"] for point in row["evaluation"]["points"]
                if point["budget"] == budget
            ),
        )
        worst_rate = next(
            point["rate"] for point in winner["evaluation"]["points"]
            if point["budget"] == budget
        )
        worst_attacker = winner["label"]
        attack_cache[signature] = (attack_rows, worst_rate, worst_attacker)
    else:
        attack_rows, worst_rate, worst_attacker = cached
    validation_response = response["summary"]["by_split"]["validation"]
    costs = _costs(response["summary"], policy, config)
    feasible = (
        validation_response["completion_rate"] >= config.min_completion_rate
        and validation_response["modification_rate"] <= config.max_modification_rate
        and validation_response["mean_attempts_per_modified"]
        <= config.max_mean_attempts_per_modified
        and costs["total_cost"] <= config.max_total_cost
    )
    return {
        "policy": policy.to_dict(),
        "evaluation_split": "validation",
        "response": validation_response,
        "distribution": response["summary"]["distribution"]["validation"],
        "costs": costs,
        "adaptive_risk": worst_rate,
        "worst_attacker": worst_attacker,
        "candidate_count": len(candidates),
        "attacks": attack_rows,
        "feasible": feasible,
    }


def _dominates(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    left_values = (left["adaptive_risk"], left["costs"]["total_cost"])
    right_values = (right["adaptive_risk"], right["costs"]["total_cost"])
    return (
        all(a <= b + 1e-12 for a, b in zip(left_values, right_values))
        and any(a < b - 1e-12 for a, b in zip(left_values, right_values))
    )


def pareto_front(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    feasible = [row for row in rows if row["feasible"]]
    front = [
        row for row in feasible
        if not any(_dominates(other, row) for other in feasible if other is not row)
    ]
    return sorted(front, key=lambda row: (row["costs"]["total_cost"], row["adaptive_risk"]))


def _normalized_distance(
    row: Mapping[str, Any], rows: Sequence[Mapping[str, Any]],
) -> float:
    risks = [candidate["adaptive_risk"] for candidate in rows]
    costs = [candidate["costs"]["total_cost"] for candidate in rows]
    risk_span = max(risks) - min(risks)
    cost_span = max(costs) - min(costs)
    normalized_risk = (
        (row["adaptive_risk"] - min(risks)) / risk_span if risk_span else 0.0
    )
    normalized_cost = (
        (row["costs"]["total_cost"] - min(costs)) / cost_span if cost_span else 0.0
    )
    return math.sqrt(0.5 * normalized_risk ** 2 + 0.5 * normalized_cost ** 2)


def _select_tiers(
    front: Sequence[Mapping[str, Any]], all_rows: Sequence[Mapping[str, Any]],
    config: PolicySearchConfig,
) -> list[dict[str, Any]]:
    eligible = [
        row for row in front
        if row["security_gain"] >= config.min_security_gain
    ]
    if len(eligible) < 3:
        additions = sorted(
            (row for row in all_rows if row["feasible"] and row["security_gain"] >= config.min_security_gain and row not in eligible),
            key=lambda row: (_normalized_distance(row, all_rows), row["costs"]["total_cost"]),
        )
        eligible.extend(additions[:3 - len(eligible)])
    if not eligible:
        raise ValueError("约束下没有达到最低安全收益的候选策略")
    low = min(eligible, key=lambda row: (row["costs"]["total_cost"], -row["security_gain"]))
    high = min(eligible, key=lambda row: (row["adaptive_risk"], row["costs"]["total_cost"]))
    remaining = [row for row in eligible if row is not low and row is not high]
    balanced_pool = remaining or [row for row in eligible if row is not low] or [low]
    balanced = min(
        balanced_pool,
        key=lambda row: (_normalized_distance(row, eligible), row["costs"]["total_cost"]),
    )
    tiers = (("低摩擦", low), ("均衡", balanced), ("高防护", high))
    # Prefer distinct policies.  Degenerate fronts can still return fewer than
    # three distinct tiers, which is made explicit in the result metadata.
    seen = set()
    selected = []
    for tier, row in tiers:
        name = row["policy"]["name"]
        if name in seen:
            replacement = next(
                (candidate for candidate in eligible if candidate["policy"]["name"] not in seen),
                row,
            )
            row = replacement
            name = row["policy"]["name"]
        seen.add(name)
        selected.append({"tier": tier, "validation": row})
    return selected


def run_policy_search(
    dataset: Mapping[str, Any], *, seed: int = 42,
    budgets: Sequence[int] = (100, 1_000, 10_000),
    config: PolicySearchConfig | None = None,
    candidate_policies: Sequence[PasswordPolicy] | None = None,
    search_attackers: Sequence[BaselineAttacker] | None = None,
    final_attackers: Sequence[BaselineAttacker] | None = None,
) -> dict[str, Any]:
    """Search on validation and evaluate only selected tiers on test."""
    normalized = validate_synthetic_dataset(dataset)
    config = config or PolicySearchConfig()
    normalized_budgets = sorted({int(value) for value in budgets if int(value) > 0} | {config.risk_budget})
    candidates = tuple(candidate_policies or enumerate_candidate_policies())
    if not candidates:
        raise ValueError("M4 候选策略不能为空")
    development_attackers = tuple(search_attackers or _search_attackers())
    attack_cache: dict[str, tuple[list[dict[str, Any]], float, str]] = {}
    validation_rows = [
        _validation_row(
            normalized, policy, seed=seed, budgets=normalized_budgets,
            attackers=development_attackers, config=config, attack_cache=attack_cache,
        )
        for policy in candidates
    ]
    baseline = next(
        (row for row in validation_rows if row["policy"]["name"] == "baseline"),
        None,
    )
    if baseline is None:
        raise ValueError("M4 候选策略必须包含 baseline")
    for row in validation_rows:
        row["security_gain"] = baseline["adaptive_risk"] - row["adaptive_risk"]
    front = pareto_front(validation_rows)
    tiers = _select_tiers(front, validation_rows, config)
    policy_lookup = {policy.name: policy for policy in candidates}
    selected_policies = [
        policy_lookup[row["validation"]["policy"]["name"]] for row in tiers
    ]
    final_policies = [policy_lookup["baseline"]]
    final_policies.extend(
        policy for policy in selected_policies if policy.name != "baseline"
        and policy.name not in {row.name for row in final_policies}
    )
    final_test = run_policy_attack_experiment(
        normalized, final_policies, budgets=normalized_budgets, seed=seed,
        attackers=final_attackers,
    )
    test_lookup = {row["policy"]["name"]: row for row in final_test["policies"]}
    selected_tiers = []
    for tier in tiers:
        validation = tier["validation"]
        test = test_lookup[validation["policy"]["name"]]
        selected_tiers.append({
            "tier": tier["tier"],
            "policy": validation["policy"],
            "validation": {
                "adaptive_risk": validation["adaptive_risk"],
                "security_gain": validation["security_gain"],
                "worst_attacker": validation["worst_attacker"],
                "response": validation["response"],
                "costs": validation["costs"],
            },
            "test": {
                "risk_budget": test["risk_budget"],
                "frozen_risk": test["frozen_risk"],
                "adaptive_risk": test["adaptive_risk"],
                "adaptation_gain": test["adaptation_gain"],
                "security_gain": test["security_gain"],
                "attacker": test["attacker"],
                "response": test["response"]["by_split"]["test"],
            },
        })
    recommendations = [{
        "tier": row["tier"],
        "policy": row["policy"],
        "reason": (
            f"validation Pareto 选择；测试集最坏自适应风险 "
            f"{row['test']['adaptive_risk']:.4f}，修改率 {row['test']['response']['modification_rate']:.4f}"
        ),
    } for row in selected_tiers]
    return {
        "dataset_id": normalized["dataset_id"],
        "config": dataclasses.asdict(config),
        "protocol": {
            "candidate_generation": "baseline plus unique one- and two-action rule combinations",
            "selection_split": "validation",
            "selection_attackers": [attacker.attacker_id for attacker in development_attackers],
            "selection_ngram": "fixed order=3, smoothing=0.3",
            "objectives": ["minimize worst adaptive risk", "minimize total cost"],
            "constraints": [
                "completion rate", "modification rate", "mean attempts", "total cost",
            ],
            "pareto_dominance": "no worse in risk and total cost, strictly better in at least one",
            "test_policy": "test used once after tier selection; never used to rank candidates",
            "test_used_for_selection": False,
        },
        "candidate_count": len(validation_rows),
        "unique_attack_scenarios": len(attack_cache),
        "feasible_count": sum(row["feasible"] for row in validation_rows),
        "pareto_count": len(front),
        "validation_candidates": validation_rows,
        "pareto_front": [row["policy"]["name"] for row in front],
        "selected_tiers": selected_tiers,
        "final_test": final_test,
        "recommendations": recommendations,
    }
