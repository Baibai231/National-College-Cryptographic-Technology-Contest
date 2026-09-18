import unittest

from core.attackers import CharacterNgramAttacker, FrequencyAttacker, SyntheticDictionaryAttacker
from core.synthetic import generate_synthetic_dataset, passwords_for_split
from experiments.policy_attack import run_policy_attack_experiment
from policy.engine import DEFAULT_POLICIES
from policy.response import response_candidate_space, simulate_policy_response


class PolicyResponseTests(unittest.TestCase):
    def test_response_is_deterministic_preserves_users_and_completes(self):
        dataset = generate_synthetic_dataset(size=1_000, seed=41)
        policy = next(row for row in DEFAULT_POLICIES if row.name == "diversified-phrase")
        first = simulate_policy_response(dataset, policy, seed=19)
        second = simulate_policy_response(dataset, policy, seed=19)
        self.assertEqual(first, second)
        self.assertEqual(len(first["dataset"]["records"]), len(dataset["records"]))
        self.assertEqual(
            {row["user_id"] for row in first["dataset"]["records"]},
            {row["user_id"] for row in dataset["records"]},
        )
        self.assertTrue(first["summary"]["user_count_preserved"])
        self.assertEqual(first["summary"]["overall"]["completion_rate"], 1.0)
        self.assertEqual(first["summary"]["overall"]["modification_rate"], 1.0)
        self.assertTrue(all(row["finally_accepted"] for row in first["records"]))

    def test_baseline_keeps_every_password_unchanged(self):
        dataset = generate_synthetic_dataset(size=1_000, seed=42)
        response = simulate_policy_response(dataset, DEFAULT_POLICIES[0], seed=42)
        self.assertEqual(response["summary"]["overall"]["initial_accept_rate"], 1.0)
        self.assertEqual(response["summary"]["overall"]["modification_rate"], 0.0)
        self.assertEqual(
            [row["password"] for row in response["dataset"]["records"]],
            [row["password"] for row in dataset["records"]],
        )

    def test_public_response_space_covers_every_transformed_password(self):
        dataset = generate_synthetic_dataset(size=2_000, seed=43)
        for policy in DEFAULT_POLICIES:
            response = simulate_policy_response(dataset, policy, seed=7)
            public_candidates = set(response_candidate_space(policy))
            self.assertTrue({row["password"] for row in response["records"]} <= public_candidates)

    def test_frozen_and_adaptive_protocol_is_leakage_resistant(self):
        original = generate_synthetic_dataset(size=1_000, seed=44)
        changed = {
            **original,
            "records": [
                {**row, "password": "cedar123"} if row["split"] == "test" else dict(row)
                for row in original["records"]
            ],
        }
        policy = next(row for row in DEFAULT_POLICIES if row.name == "length-8")
        attackers = (
            FrequencyAttacker(), SyntheticDictionaryAttacker(),
            CharacterNgramAttacker(orders=(3,), smoothing_values=(0.3,)),
        )
        first = run_policy_attack_experiment(
            original, (policy,), budgets=(100, 1_000), seed=9, attackers=attackers,
        )
        second = run_policy_attack_experiment(
            changed, (policy,), budgets=(100, 1_000), seed=9, attackers=attackers,
        )
        first_attacks = first["policies"][0]["attacks"]
        second_attacks = second["policies"][0]["attacks"]
        self.assertEqual(first["protocol"]["test_used_for_training_or_selection"], False)
        self.assertEqual(
            [(row["frozen"]["ranking"], row["adaptive"]["ranking"]) for row in first_attacks],
            [(row["frozen"]["ranking"], row["adaptive"]["ranking"]) for row in second_attacks],
        )
        self.assertNotEqual(
            [row["adaptive"]["evaluation"] for row in first_attacks],
            [row["adaptive"]["evaluation"] for row in second_attacks],
        )

    def test_adaptation_recovers_risk_without_dropping_users(self):
        dataset = generate_synthetic_dataset(size=2_000, seed=45)
        policy = next(row for row in DEFAULT_POLICIES if row.name == "diversified-phrase")
        result = run_policy_attack_experiment(
            dataset, (DEFAULT_POLICIES[0], policy), budgets=(100, 1_000), seed=10,
            attackers=(FrequencyAttacker(), SyntheticDictionaryAttacker()),
        )
        row = result["policies"][1]
        self.assertEqual(row["response"]["overall"]["total"], 2_000)
        self.assertEqual(row["response"]["overall"]["completion_rate"], 1.0)
        self.assertTrue(any(point["adaptation_gain"] > 0 for point in row["worst_case"]))
        self.assertEqual(
            len(passwords_for_split(dataset, "test")),
            row["attacks"][0]["adaptive"]["evaluation"]["total"],
        )


if __name__ == "__main__":
    unittest.main()
