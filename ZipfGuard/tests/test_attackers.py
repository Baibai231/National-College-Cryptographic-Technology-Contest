import unittest

from core.attackers import (
    CharacterNgramAttacker,
    FrequencyAttacker,
    RankingResult,
    SyntheticDictionaryAttacker,
    run_attack_baselines,
)
from core.metrics import evaluate_ranking, wilson_interval
from core.synthetic import candidate_space, generate_synthetic_dataset, passwords_for_split


class AttackBaselineTests(unittest.TestCase):
    def test_common_interface_is_deterministic_and_unique(self):
        dataset = generate_synthetic_dataset(size=1_000, seed=23)
        train = passwords_for_split(dataset, "train")
        validation = passwords_for_split(dataset, "validation")
        candidates = candidate_space()
        attackers = (
            FrequencyAttacker(), SyntheticDictionaryAttacker(),
            CharacterNgramAttacker(orders=(2, 3), smoothing_values=(0.3,)),
        )
        for attacker in attackers:
            first = attacker.fit_select_rank(train, validation, candidates)
            second = attacker.fit_select_rank(train, validation, candidates)
            self.assertIsInstance(first, RankingResult)
            self.assertEqual(first, second)
            self.assertEqual(len(first.guesses), len(set(first.guesses)))
            self.assertEqual(first.training_size, 600)
            self.assertEqual(first.validation_size, 200)

    def test_evaluation_keeps_requested_budgets_and_wilson_intervals(self):
        evaluation = evaluate_ranking(["a", "b"], ["a", "c", "a", "b"], (1, 10, 1_000))
        self.assertEqual([row["budget"] for row in evaluation["points"]], [1, 10, 1_000])
        self.assertEqual([row["cracked"] for row in evaluation["points"]], [2, 3, 3])
        self.assertEqual(evaluation["covered"], 3)
        self.assertAlmostEqual(evaluation["coverage"], 0.75)
        lower, upper = wilson_interval(3, 4)
        self.assertAlmostEqual(evaluation["coverage_interval"]["lower"], lower)
        self.assertAlmostEqual(evaluation["coverage_interval"]["upper"], upper)

    def test_suite_uses_fixed_splits_and_test_does_not_change_rankings(self):
        original = generate_synthetic_dataset(size=1_000, seed=31)
        changed = {
            **original,
            "records": [
                {**row, "password": "cedar123"} if row["split"] == "test" else dict(row)
                for row in original["records"]
            ],
        }
        attackers = (
            FrequencyAttacker(), SyntheticDictionaryAttacker(),
            CharacterNgramAttacker(orders=(2,), smoothing_values=(0.3,)),
        )
        first = run_attack_baselines(original, attackers=attackers)
        second = run_attack_baselines(changed, attackers=attackers)
        self.assertEqual(first["protocol"]["test_used_for_ranking"], False)
        self.assertEqual(first["split_sizes"], {"train": 600, "validation": 200, "test": 200})
        self.assertEqual(
            [row["attacker"] for row in first["attacks"]],
            [row["attacker"] for row in second["attacks"]],
        )
        self.assertNotEqual(
            [row["evaluation"] for row in first["attacks"]],
            [row["evaluation"] for row in second["attacks"]],
        )

    def test_default_suite_reports_required_metrics(self):
        result = run_attack_baselines(
            generate_synthetic_dataset(size=2_000, seed=7),
            budgets=(100, 1_000, 10_000),
        )
        self.assertEqual(result["budgets"], [100, 1_000, 10_000])
        self.assertEqual(
            [row["attacker"]["attacker_id"] for row in result["attacks"]],
            ["frequency", "synthetic-dictionary", "character-ngram"],
        )
        for row in result["attacks"]:
            evaluation = row["evaluation"]
            self.assertIn("coverage", evaluation)
            self.assertIn("coverage_interval", evaluation)
            self.assertEqual([point["budget"] for point in evaluation["points"]], [100, 1_000, 10_000])
            self.assertTrue(all("interval" in point for point in evaluation["points"]))


if __name__ == "__main__":
    unittest.main()
