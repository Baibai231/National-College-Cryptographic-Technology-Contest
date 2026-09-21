import unittest
from pathlib import Path

from core.data import synthetic_counts, validate_count_payload
from core.rockyou import aggregate_rockyou
from experiments.pipeline import run_pipeline
from policy.engine import PasswordPolicy, evaluate_policy_rules, extract_features
from ai.passllm_adapter import PassLLMConfig, runtime_status


class MvpTests(unittest.TestCase):
    def test_count_schema_is_strict_and_deterministic(self):
        payload = synthetic_counts(size=1000, categories=40, seed=4)
        self.assertEqual(payload, synthetic_counts(size=1000, categories=40, seed=4))
        self.assertEqual(validate_count_payload(payload)["total_count"], 1000)
        with self.assertRaises(ValueError):
            validate_count_payload({"items": [{"rank": 1, "count": 5}, {"rank": 2, "count": 1}]})

    def test_features_and_policy_reasons_are_explainable(self):
        features = extract_features("Cedar2026")
        self.assertTrue(features["year_suffix"])
        result = evaluate_policy_rules("Cedar2026", PasswordPolicy(min_length=12, deny_features=("year_suffix",)))
        self.assertFalse(result["accepted"])
        self.assertIn("长度不足", result["reasons"])

    def test_pipeline_contains_model_strategy_and_repro_metadata(self):
        result = run_pipeline(seed=8, synthetic_size=5_000, bootstrap_repetitions=20)
        self.assertIn(result["analysis"]["selected_model"], {"zipf", "cdf_zipf", "stretched_exponential"})
        self.assertGreaterEqual(len(result["policies"]), 3)
        self.assertEqual(result["metadata"]["seed"], 8)
        self.assertIn("privacy", result["metadata"])
        self.assertEqual(result["dataset"]["dataset_id"], result["simulation"]["dataset_id"])
        self.assertTrue(all(row["dataset_id"] == result["dataset"]["dataset_id"] for row in result["policies"]))
        self.assertEqual(result["analysis"]["split_method"], "predefined train/validation user split")
        self.assertEqual(result["attack_baselines"]["dataset_id"], result["dataset"]["dataset_id"])
        self.assertEqual(len(result["attack_baselines"]["attacks"]), 3)
        self.assertEqual(result["policy_experiment"]["dataset_id"], result["dataset"]["dataset_id"])
        self.assertTrue(all(row["accept_rate"] == 1.0 for row in result["policies"]))
        self.assertTrue(all(row["response"]["user_count_preserved"] for row in result["policies"]))
        self.assertEqual(result["policy_search"]["dataset_id"], result["dataset"]["dataset_id"])
        self.assertEqual(len(result["policy_search"]["selected_tiers"]), 3)
        self.assertEqual(len(result["recommendations"]), 3)

    def test_aggregate_only_pipeline_does_not_invent_policy_results(self):
        result = run_pipeline(
            synthetic_counts(size=1_000, categories=40, seed=4),
            seed=4,
            bootstrap_repetitions=20,
        )
        self.assertEqual(result["policies"], [])
        self.assertIsNone(result["simulation"])
        self.assertIsNone(result["attack_baselines"])
        self.assertIsNone(result["policy_experiment"])
        self.assertIsNone(result["policy_search"])
        self.assertIn("not run", result["metadata"]["policy_evaluation"])
        with self.assertRaisesRegex(ValueError, "train/validation/test"):
            run_pipeline(
                synthetic_counts(size=1_000, categories=40, seed=4),
                seed=4, bootstrap_repetitions=20, include_pcfg=True,
            )

    def test_rockyou_stream_aggregation_and_passllm_status(self):
        source = Path(__file__).resolve().parents[2] / "lab_basic_50_dicts" / "Rockyou.txt"
        if source.exists():
            payload = aggregate_rockyou(source, max_lines=10_000, top_k=50)
            self.assertEqual(payload["metadata"]["plaintext_retained"], False)
            self.assertEqual(len(payload["items"]), 50)
            self.assertGreater(payload["total_count"], 20)
        status = runtime_status(PassLLMConfig.workspace_default(Path(__file__).resolve().parents[2]))
        expected_available = (
            status["base_model_present"]
            and status["lora_present"]
            and not status["missing_packages"]
        )
        self.assertEqual(status["available"], expected_available)
        if not expected_available:
            self.assertIsNone(status["fallback"])
        self.assertFalse(status["participated"])


if __name__ == "__main__":
    unittest.main()
