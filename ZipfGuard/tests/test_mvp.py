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
        result = run_pipeline(synthetic_counts(size=5000, categories=80, seed=8), seed=8, bootstrap_repetitions=20)
        self.assertIn(result["analysis"]["selected_model"], {"zipf", "cdf_zipf", "stretched_exponential"})
        self.assertGreaterEqual(len(result["policies"]), 3)
        self.assertEqual(result["metadata"]["seed"], 8)
        self.assertIn("privacy", result["metadata"])

    def test_rockyou_stream_aggregation_and_passllm_status(self):
        source = Path(__file__).resolve().parents[2] / "lab_basic_50_dicts" / "Rockyou.txt"
        if source.exists():
            payload = aggregate_rockyou(source, max_lines=10_000, top_k=50)
            self.assertEqual(payload["metadata"]["plaintext_retained"], False)
            self.assertEqual(len(payload["items"]), 50)
            self.assertGreater(payload["total_count"], 20)
        status = runtime_status(PassLLMConfig.workspace_default(Path(__file__).resolve().parents[2]))
        self.assertTrue(status["base_model_present"])
        self.assertTrue(status["lora_present"])


if __name__ == "__main__":
    unittest.main()
