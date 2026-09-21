"""M3 user-response and frozen-versus-adaptive attack experiment."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from core.attackers import BaselineAttacker, RankingResult, default_attackers
from core.metrics import evaluate_ranking
from core.synthetic import candidate_space, passwords_for_split, validate_synthetic_dataset
from experiments.config import active_section
from policy.engine import PasswordPolicy
from policy.response import response_candidate_space, simulate_policy_response


def _point(evaluation: Mapping[str, Any], budget: int) -> Mapping[str, Any]:
    return next(point for point in evaluation["points"] if point["budget"] == budget)


def _attack_delta(
    frozen: Mapping[str, Any], adaptive: Mapping[str, Any], budgets: Sequence[int],
) -> list[dict[str, Any]]:
    return [{
        "budget": budget,
        "frozen_rate": _point(frozen, budget)["rate"],
        "adaptive_rate": _point(adaptive, budget)["rate"],
        "rate_delta": _point(adaptive, budget)["rate"] - _point(frozen, budget)["rate"],
        "cracked_delta": _point(adaptive, budget)["cracked"] - _point(frozen, budget)["cracked"],
    } for budget in budgets]


def _worst_case(attacks: Sequence[Mapping[str, Any]], budgets: Sequence[int]) -> list[dict[str, Any]]:
    rows = []
    for budget in budgets:
        frozen_winner = max(
            attacks, key=lambda row: (_point(row["frozen"]["evaluation"], budget)["rate"], row["attacker_id"])
        )
        adaptive_winner = max(
            attacks, key=lambda row: (_point(row["adaptive"]["evaluation"], budget)["rate"], row["attacker_id"])
        )
        frozen_rate = _point(frozen_winner["frozen"]["evaluation"], budget)["rate"]
        adaptive_rate = _point(adaptive_winner["adaptive"]["evaluation"], budget)["rate"]
        rows.append({
            "budget": budget,
            "frozen_rate": frozen_rate,
            "frozen_attacker": frozen_winner["label"],
            "adaptive_rate": adaptive_rate,
            "adaptive_attacker": adaptive_winner["label"],
            "adaptation_gain": adaptive_rate - frozen_rate,
        })
    return rows


def run_policy_attack_experiment(
    dataset: Mapping[str, Any], policies: Sequence[PasswordPolicy], *,
    budgets: Sequence[int] = (100, 1_000, 10_000), seed: int = 42,
    attackers: Sequence[BaselineAttacker] | None = None,
) -> dict[str, Any]:
    """Preserve all users and compare frozen with policy-aware attackers."""
    normalized = validate_synthetic_dataset(dataset)
    normalized_budgets = sorted({int(value) for value in budgets if int(value) > 0})
    if not normalized_budgets:
        raise ValueError("M3 至少需要一个正攻击预算")
    attack_models = tuple(attackers or default_attackers())
    original_train = passwords_for_split(normalized, "train")
    original_validation = passwords_for_split(normalized, "validation")
    original_candidates = candidate_space()
    frozen_rankings: dict[str, RankingResult] = {}
    for attacker in attack_models:
        if attacker.attacker_id in frozen_rankings:
            raise ValueError(f"攻击器 ID 重复：{attacker.attacker_id}")
        frozen_rankings[attacker.attacker_id] = attacker.fit_select_rank(
            original_train, original_validation, original_candidates,
        )

    policy_rows = []
    for policy in policies:
        response = simulate_policy_response(normalized, policy, seed=seed)
        transformed = response["dataset"]
        train = passwords_for_split(transformed, "train")
        validation = passwords_for_split(transformed, "validation")
        test = passwords_for_split(transformed, "test")
        candidates = response_candidate_space(policy)
        unchanged_response = (
            response["summary"]["overall"]["modification_rate"] == 0.0
            and candidates == original_candidates
        )
        attack_rows = []
        for attacker in attack_models:
            frozen_ranking = frozen_rankings[attacker.attacker_id]
            adaptive_ranking = (
                frozen_ranking if unchanged_response else
                attacker.fit_select_rank(train, validation, candidates)
            )
            frozen_evaluation = evaluate_ranking(frozen_ranking.guesses, test, normalized_budgets)
            adaptive_evaluation = evaluate_ranking(adaptive_ranking.guesses, test, normalized_budgets)
            attack_rows.append({
                "attacker_id": attacker.attacker_id,
                "label": attacker.label,
                "frozen": {
                    "ranking": frozen_ranking.summary(),
                    "evaluation": frozen_evaluation,
                },
                "adaptive": {
                    "ranking": adaptive_ranking.summary(),
                    "evaluation": adaptive_evaluation,
                },
                "adaptive_minus_frozen": _attack_delta(
                    frozen_evaluation, adaptive_evaluation, normalized_budgets,
                ),
            })
        overall = response["summary"]["overall"]
        worst_case = _worst_case(attack_rows, normalized_budgets)
        policy_rows.append({
            "policy": policy.to_dict(),
            "dataset_id": normalized["dataset_id"],
            "transformed_dataset_id": transformed["dataset_id"],
            "response": response["summary"],
            "candidate_count": len(candidates),
            "attacks": attack_rows,
            "worst_case": worst_case,
            # Compatibility fields for the existing UI.  M3 exposes the full
            # definitions above; user_cost is a modification-rate proxy until M4.
            "accept_rate": overall["completion_rate"],
            "initial_accept_rate": overall["initial_accept_rate"],
            "modification_rate": overall["modification_rate"],
            "user_cost": overall["modification_rate"],
        })

    baseline = next(
        (row for row in policy_rows if row["policy"]["name"] == "baseline"),
        policy_rows[0] if policy_rows else None,
    )
    if baseline is not None:
        baseline_risk = {row["budget"]: row["adaptive_rate"] for row in baseline["worst_case"]}
        for row in policy_rows:
            for point in row["worst_case"]:
                point["risk_reduction_vs_baseline"] = (
                    baseline_risk[point["budget"]] - point["adaptive_rate"]
                )
            target_budget = int(row["policy"].get("risk_budget", normalized_budgets[0]))
            target = next(
                (point for point in row["worst_case"] if point["budget"] == target_budget),
                row["worst_case"][0],
            )
            row["risk_budget"] = target["budget"]
            row["frozen_risk"] = target["frozen_rate"]
            row["adaptive_risk"] = target["adaptive_rate"]
            row["adaptation_gain"] = target["adaptation_gain"]
            row["security_gain"] = target["risk_reduction_vs_baseline"]
            row["attacker"] = target["adaptive_attacker"]

    return {
        "dataset_id": normalized["dataset_id"],
        "budgets": normalized_budgets,
        "protocol": {
            "user_response": active_section("response") or {"order": ["append-symbol", "append-symbol-digit", "random-phrase"], "max_attempts": 8},
            "user_count_preserved": True,
            "frozen_attack": "ranking trained on original train and evaluated on transformed test",
            "adaptive_attack": "ranking retrained on transformed train; parameters selected on transformed validation",
            "evaluation_split": "transformed test only",
            "test_used_for_training_or_selection": False,
            "user_cost_proxy": "modification rate; full response metrics retained for M4",
        },
        "policies": policy_rows,
    }
