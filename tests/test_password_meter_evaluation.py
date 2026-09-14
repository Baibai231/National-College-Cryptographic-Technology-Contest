import unittest

from application_security.password_meter_evaluation import (
    PASSWORD_METER_MANIFEST,
    analyze_site_meter_consistency,
    evaluate_paper_metrics,
    extreme_bin_precision,
    kl_divergence,
    offline_kl_by_strategy,
    precision_security,
    weighted_spearman,
)


class PasswordMeterEvaluationTests(unittest.TestCase):
    def test_manifest_declares_crypto_and_top_tier_paper(self):
        self.assertIn("password_guessability", PASSWORD_METER_MANIFEST.crypto_elements)
        self.assertEqual(PASSWORD_METER_MANIFEST.paper_refs[0].venue, "USENIX Security")

    def test_weighted_spearman_matches_identical_and_reversed_ranks(self):
        self.assertAlmostEqual(
            weighted_spearman([1, 2, 3], [1, 2, 3], [5, 2, 1]), 1.0)
        self.assertAlmostEqual(
            weighted_spearman([1, 2, 3], [3, 2, 1], [5, 2, 1]), -1.0)

    def test_precision_equations_match_paper_counts(self):
        # NC_L=8, NR_L=2, NC_H=1, NR_H=9
        self.assertAlmostEqual(extreme_bin_precision(8, 2, 1, 9), 17 / 20)
        expected = 0.8 * 0.5 * 0.8 + 0.2 * 0.5 * 0.9
        self.assertAlmostEqual(precision_security(8, 2, 1, 9), expected)

    def test_kl_divergence_matches_paper_equation_without_hidden_smoothing(self):
        self.assertAlmostEqual(kl_divergence([1, 1], [1, 1]), 0.0)
        self.assertAlmostEqual(
            kl_divergence([3, 1], [1, 3]), 0.5 * __import__("math").log(3))
        self.assertEqual(kl_divergence([1, 1], [0, 1]), float("inf"))

    def test_offline_kl_is_separated_by_attack_strategy_and_needs_no_password(self):
        result = offline_kl_by_strategy([
            {"attack_strategy": "dictionary", "meter_bucket": "low", "cracked": True, "count": 3},
            {"attack_strategy": "dictionary", "meter_bucket": "high", "cracked": True},
            {"attack_strategy": "dictionary", "meter_bucket": "low", "cracked": False},
            {"attack_strategy": "dictionary", "meter_bucket": "high", "cracked": False, "count": 3},
            {"attack_strategy": "combined", "meter_bucket": "low", "cracked": True},
        ])
        self.assertAlmostEqual(result["dictionary"]["value"], 0.5 * __import__("math").log(3))
        self.assertIsNone(result["combined"]["value"])
        self.assertNotIn("password", repr(result).lower())

    def test_evaluate_paper_metrics_requires_real_labels(self):
        samples = [
            {"reference_rank": 1, "meter_rank": 1, "frequency": 10,
             "meter_bin": "low", "meter_bucket": "low",
             "attack_strategy": "dictionary", "cracked": True},
            {"reference_rank": 2, "meter_rank": 2, "frequency": 3,
             "meter_bin": "low", "meter_bucket": "low",
             "attack_strategy": "dictionary", "cracked": False},
            {"reference_rank": 3, "meter_rank": 3, "frequency": 1,
             "meter_bin": "high", "meter_bucket": "high",
             "attack_strategy": "dictionary", "cracked": False},
        ]
        result = evaluate_paper_metrics(samples)
        self.assertAlmostEqual(result["weighted_spearman"], 1.0)
        self.assertAlmostEqual(result["extreme_bin_precision"], 2 / 3)
        self.assertIsNotNone(result["precision_security"])
        self.assertFalse(
            result["offline_kl_divergence_by_strategy"]["dictionary"]["infinite"])
        self.assertIsNotNone(
            result["offline_kl_divergence_by_strategy"]["dictionary"]["value"])

    def test_live_site_reports_consistency_not_accuracy(self):
        result = analyze_site_meter_consistency("example.com", [
            {"password_length": 8, "character_profile": "lower+digit",
             "outcome": "accepted", "strength_meter_level": "weak"},
            {"password_length": 14, "character_profile": "lower+upper+digit+symbol",
             "outcome": "rejected", "strength_meter_level": "strong"},
            {"password_length": 10, "outcome": "inconclusive",
             "strength_meter_level": "medium"},
        ]).to_dict()
        claims = {item["metric_id"]: item for item in result["claims"]}
        consistency = claims["auth.password_meter.site_consistency"]
        accuracy = claims["auth.password_meter.paper_accuracy_metrics"]
        self.assertEqual(consistency["verdict"], "weak")
        self.assertEqual(consistency["value"]["paired_total"], 2)
        self.assertEqual(consistency["value"]["consistency"], 0.0)
        self.assertEqual(accuracy["verdict"], "unknown")
        self.assertIsNone(accuracy["value"]["weighted_spearman"])
        self.assertNotIn("password", result["evidence"][0]["observation"]["probes"][0])

    def test_missing_meter_is_unknown(self):
        result = analyze_site_meter_consistency("example.com", [
            {"password_length": 8, "outcome": "accepted"},
        ]).to_dict()
        claim = result["claims"][0]
        self.assertEqual(claim["verdict"], "unknown")
        self.assertEqual(result["evidence"], [])

    def test_no_observed_conflict_does_not_become_pass(self):
        result = analyze_site_meter_consistency("example.com", [
            {"password_length": 14, "outcome": "accepted",
             "strength_meter_level": "strong"},
            {"password_length": 3, "outcome": "rejected",
             "strength_meter_level": "weak"},
        ]).to_dict()
        claim = result["claims"][0]
        self.assertEqual(claim["verdict"], "unknown")
        self.assertEqual(claim["value"]["consistency"], 1.0)

    def test_invalid_inputs_are_rejected(self):
        with self.assertRaises(ValueError):
            weighted_spearman([1], [1, 2], [1])
        with self.assertRaises(ValueError):
            precision_security(1, 0, 0, 0)
        with self.assertRaises(ValueError):
            precision_security(1, 1, 1, 1, beta=1.1)


if __name__ == "__main__":
    unittest.main()
