"""Regression tests for cohorts whose original passwords are all rejected."""
import unittest

from core.metrics import cracked_at_k, risk_delta
from core.synthetic import generate_synthetic_dataset
from experiments.policy_attack import run_policy_attack_experiment
from policy.engine import DEFAULT_POLICIES


class InitiallyRejectedPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = generate_synthetic_dataset(size=1_000, seed=61)
        cls.policy = next(
            row for row in DEFAULT_POLICIES if row.name == "diversified-phrase"
        )
        cls.row = run_policy_attack_experiment(
            cls.dataset, (DEFAULT_POLICIES[0], cls.policy),
            budgets=(100, 1_000), seed=61,
        )["policies"][1]

    def test_initially_rejected_users_are_reselected_not_deleted(self):
        response = self.row["response"]["overall"]
        self.assertEqual(response["total"], 1_000)
        self.assertEqual(response["initial_accept_rate"], 0.0)
        self.assertEqual(response["modification_rate"], 1.0)
        self.assertEqual(response["completion_rate"], 1.0)
        self.assertTrue(self.row["response"]["user_count_preserved"])

    def test_attack_evaluation_keeps_the_full_test_cohort(self):
        for attack in self.row["attacks"]:
            self.assertEqual(attack["frozen"]["evaluation"]["total"], 200)
            self.assertEqual(attack["adaptive"]["evaluation"]["total"], 200)
        self.assertIsInstance(self.row["security_gain"], float)

    def test_empty_metric_is_distinct_from_zero_hits(self):
        empty = cracked_at_k(["a"], [], [1])[0]
        self.assertIsNone(empty["rate"])
        self.assertEqual(empty["evaluated_count"], 0)
        nonempty = cracked_at_k(["a"], ["b"], [1])[0]
        self.assertEqual(nonempty["rate"], 0)
        self.assertEqual(nonempty["evaluated_count"], 1)

    def test_missing_or_unknown_budget_is_not_zero_risk(self):
        before = [{"budget": 1, "rate": 0.5}]
        for after in ([], [{"budget": 1, "rate": None}]):
            self.assertIsNone(risk_delta(before, after)[0]["delta"])
        self.assertEqual(risk_delta(before, [{"budget": 1, "rate": 0}])[0]["delta"], 0.5)
        self.assertIsNone(risk_delta([{"budget": 1, "rate": None}], before)[0]["delta"])


if __name__ == "__main__":
    unittest.main()
