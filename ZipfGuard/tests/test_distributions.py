import math
import unittest

import numpy as np

from core.distributions import analyze_counts, fit_model, model_pmf, risk_threshold, top_b_mass


class DistributionTests(unittest.TestCase):
    def test_probability_laws_and_cdf_identity(self):
        for name, params in [
            ("zipf", {"s": 1.1}),
            ("cdf_zipf", {"alpha": 0.4}),
            ("stretched_exponential", {"alpha": 0.55, "t": 2.5}),
        ]:
            probabilities = model_pmf(name, 500, params)
            self.assertAlmostEqual(float(probabilities.sum()), 1)
            self.assertTrue(np.all(probabilities > 0))
            self.assertTrue(np.all(np.diff(probabilities) <= 1e-14))
        power = model_pmf("cdf_zipf", 500, {"alpha": 0.4})
        self.assertTrue(np.allclose(np.cumsum(power), (np.arange(1, 501) / 500) ** 0.4))

    def test_zipf_parameter_recovery(self):
        true = model_pmf("zipf", 500, {"s": 1.12})
        counts = np.random.default_rng(9).multinomial(1_000_000, true)
        fitted = fit_model(counts, "zipf")
        self.assertLess(abs(fitted["parameters"]["s"] - 1.12), 0.01)

    def test_stretched_parameter_recovery(self):
        true = model_pmf("stretched_exponential", 500, {"alpha": 0.55, "t": 2.5})
        fitted = fit_model(true * 10_000_000, "stretched_exponential")
        self.assertLess(abs(fitted["parameters"]["alpha"] - 0.55), 0.015)
        self.assertLess(abs(fitted["parameters"]["t"] - 2.5), 0.15)

    def test_risk_boundaries_and_majorization(self):
        self.assertEqual(risk_threshold([0.5, 0.3, 0.2], 0.8), 2)
        self.assertEqual(risk_threshold([0.5, 0.3, 0.2], 1), 3)
        self.assertEqual(top_b_mass([1, 2, 3], 0), 0)
        self.assertEqual(top_b_mass([1, 2, 3], 100), 1)
        original = np.array([0.7, 0.2, 0.1])
        transition = np.array([[0.5, 0.5, 0], [0.5, 0, 0.5], [0, 0.5, 0.5]])
        after = original @ transition
        for budget in range(1, 4):
            self.assertLessEqual(top_b_mass(after, budget, oracle=True), top_b_mass(original, budget, oracle=True) + 1e-12)

    def test_heldout_pipeline_uses_valid_finite_statistics(self):
        counts = np.random.default_rng(18).multinomial(80_000, model_pmf("zipf", 300, {"s": 1.12}))
        report = analyze_counts(counts, q=0.8, budget=20, bootstrap_repetitions=30, seed=8)
        self.assertEqual(report["selected_model"], "zipf")
        self.assertEqual(report["sample_size"], report["train_size"] + report["validation_size"])
        low, high = report["risk_threshold"]["heldout_top_b_ci95"]
        self.assertLessEqual(low, high)
        self.assertTrue(0 <= low <= 1 and 0 <= high <= 1)
        for model in report["models"]:
            self.assertTrue(math.isfinite(model["validation_log_likelihood"]))
        for comparison in report["llr_comparisons"]:
            self.assertIsNone(comparison["p_value"])

    def test_invalid_inputs_rejected(self):
        for invalid in [[], [1], [-1, 21], [math.nan, 30], [1.5, 20], [0, 0]]:
            with self.assertRaises(ValueError):
                analyze_counts(invalid)
        with self.assertRaises(ValueError):
            risk_threshold([0.5, 0.5], 0)


if __name__ == "__main__":
    unittest.main()
