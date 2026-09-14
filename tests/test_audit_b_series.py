import unittest

from scripts.audit_b_series import build_audit


class AuditBSeriesTests(unittest.TestCase):
    def test_cohort_counts_and_status_boundaries_are_explicit(self):
        result = build_audit()
        self.assertTrue(all(item["match"] for item in result["cohort_integrity"].values()))
        self.assertEqual(len(result["tasks"]), 12)
        self.assertTrue(result["all_required_files_present"])
        self.assertEqual(result["stage_gate"]["competition_full_empirical_gate"], "not_met")
        self.assertEqual(
            result["empirical_baselines"]["password_inline_funnel"]["complete_policy_total"], 7)
        classification = result["empirical_baselines"]["authentication_classification"]
        self.assertEqual(classification["manual_result_overlap"], 124)
        self.assertEqual(classification["manual_without_authoritative_result"], 1)
        self.assertGreater(classification["login"]["evaluated"], 0)
        self.assertGreater(classification["signup"]["evaluated"], 0)
        self.assertEqual(
            result["empirical_baselines"]["password_full_303_snapshot"]
            ["inline_output_unique_sites"], 15)
        self.assertEqual(
            result["empirical_baselines"]["password_full_303_snapshot"]
            ["complete_policy_unique_sites"], 14)


if __name__ == "__main__":
    unittest.main()
