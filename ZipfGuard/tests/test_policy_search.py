import unittest

from core.attackers import FrequencyAttacker, SyntheticDictionaryAttacker
from core.synthetic import generate_synthetic_dataset
from experiments.policy_search import (
    PolicySearchConfig,
    enumerate_candidate_policies,
    pareto_front,
    run_policy_search,
)


class PolicySearchTests(unittest.TestCase):
    def test_candidate_enumeration_is_deterministic_and_unique(self):
        first = enumerate_candidate_policies()
        second = enumerate_candidate_policies()
        self.assertEqual(first, second)
        self.assertGreaterEqual(len(first), 20)
        self.assertEqual(first[0].name, "baseline")
        signatures = {
            (row.min_length, row.required_classes, row.deny_features)
            for row in first
        }
        self.assertEqual(len(signatures), len(first))

    def test_pareto_front_removes_dominated_rows(self):
        rows = [
            {"name": "a", "adaptive_risk": 0.5, "costs": {"total_cost": 0.2}, "feasible": True},
            {"name": "b", "adaptive_risk": 0.6, "costs": {"total_cost": 0.3}, "feasible": True},
            {"name": "c", "adaptive_risk": 0.3, "costs": {"total_cost": 0.5}, "feasible": True},
            {"name": "d", "adaptive_risk": 0.1, "costs": {"total_cost": 0.1}, "feasible": False},
        ]
        self.assertEqual({row["name"] for row in pareto_front(rows)}, {"a", "c"})

    def test_selection_uses_validation_and_only_selected_policies_reach_test(self):
        original = generate_synthetic_dataset(size=1_000, seed=51)
        changed = {
            **original,
            "records": [
                {**row, "password": "cedar123"} if row["split"] == "test" else dict(row)
                for row in original["records"]
            ],
        }
        all_candidates = enumerate_candidate_policies()
        names = {
            "baseline", "search-l8", "search-l10", "search-l12",
            "search-l12-deny-common_word",
        }
        candidates = tuple(row for row in all_candidates if row.name in names)
        attackers = (FrequencyAttacker(), SyntheticDictionaryAttacker())
        config = PolicySearchConfig(min_security_gain=0.0)
        first = run_policy_search(
            original, seed=8, budgets=(100, 1_000), config=config,
            candidate_policies=candidates, search_attackers=attackers,
            final_attackers=attackers,
        )
        second = run_policy_search(
            changed, seed=8, budgets=(100, 1_000), config=config,
            candidate_policies=candidates, search_attackers=attackers,
            final_attackers=attackers,
        )
        first_selection = [
            (row["tier"], row["policy"]["name"], row["validation"])
            for row in first["selected_tiers"]
        ]
        second_selection = [
            (row["tier"], row["policy"]["name"], row["validation"])
            for row in second["selected_tiers"]
        ]
        self.assertEqual(first_selection, second_selection)
        self.assertFalse(first["protocol"]["test_used_for_selection"])
        selected_names = {row["policy"]["name"] for row in first["selected_tiers"]}
        final_names = {row["policy"]["name"] for row in first["final_test"]["policies"]}
        self.assertEqual(final_names, selected_names | {"baseline"})
        self.assertNotEqual(first["final_test"], second["final_test"])

    def test_default_search_returns_three_named_tiers(self):
        attackers = (FrequencyAttacker(), SyntheticDictionaryAttacker())
        result = run_policy_search(
            generate_synthetic_dataset(size=1_000, seed=52),
            seed=52, budgets=(100, 1_000),
            search_attackers=attackers, final_attackers=attackers,
        )
        self.assertGreater(result["candidate_count"], result["pareto_count"])
        self.assertEqual(
            [row["tier"] for row in result["selected_tiers"]],
            ["低摩擦", "均衡", "高防护"],
        )
        self.assertEqual(len({row["policy"]["name"] for row in result["selected_tiers"]}), 3)
        self.assertEqual(len(result["recommendations"]), 3)


if __name__ == "__main__":
    unittest.main()
