import unittest

from application_security.experiment_metrics import (
    classification_metrics,
    compare_module_rounds,
    summarize_module_round,
    wilson_interval,
)


class ExperimentMetricsTests(unittest.TestCase):
    def test_unknown_is_excluded_from_accuracy_but_kept_in_coverage(self):
        result = classification_metrics([True, True, False, False], [True, None, True, False])
        self.assertEqual(result["tp"], 1)
        self.assertEqual(result["fp"], 1)
        self.assertEqual(result["tn"], 1)
        self.assertEqual(result["unknown"], 1)
        self.assertEqual(result["coverage"], 0.75)
        self.assertEqual(result["precision"], 0.5)

    def test_wilson_interval_is_bounded(self):
        low, high = wilson_interval(7, 25)
        self.assertGreaterEqual(low, 0)
        self.assertLessEqual(high, 1)
        self.assertLess(low, 7 / 25)
        self.assertGreater(high, 7 / 25)

    def test_round_summary_preserves_unknown_and_errors(self):
        result = summarize_module_round([
            {"verdict": "pass", "entry_reachable": True, "feature_positive": True, "evidence_obtained": True, "evidence_levels": ["observed"]},
            {"verdict": "unknown", "entry_reachable": False, "error_code": "timeout"},
        ])
        self.assertEqual(result["unknown"], 1)
        self.assertEqual(result["error_distribution"], {"timeout": 1})

    def test_two_round_metrics_include_missing_jaccard_and_kappa(self):
        first = [
            {"module_id": "m", "site_id": "a", "verdict": "pass", "feature_positive": True, "evidence_obtained": True},
            {"module_id": "m", "site_id": "b", "verdict": "unknown", "feature_positive": False, "evidence_obtained": False},
        ]
        second = [
            {"module_id": "m", "site_id": "a", "verdict": "pass", "feature_positive": True, "evidence_obtained": True},
            {"module_id": "m", "site_id": "c", "verdict": "unknown", "feature_positive": False, "evidence_obtained": False},
        ]
        result = compare_module_rounds(first, second)
        self.assertEqual(result["paired_keys"], 1)
        self.assertEqual(result["missing_in_round1"], 1)
        self.assertEqual(result["missing_in_round2"], 1)
        self.assertEqual(result["positive_jaccard"], 1.0)


if __name__ == "__main__":
    unittest.main()
