import unittest
from unittest import mock

from full_form_tester.full_form_tester import FullFormPolicyTester
from utils.adaptive_policy import (
    ACCEPTED,
    INCONCLUSIVE,
    AdaptiveCompositionPlanner,
    AdaptiveLengthPlanner,
    apply_composition_to_restrictive,
    build_class_count_candidate,
    build_class_subset_candidate,
    build_length_candidate,
    candidate_profile,
    character_class_counts,
)


class AdaptivePolicyTests(unittest.TestCase):
    @staticmethod
    def _rules():
        return {
            "r_no_a_sps": False,
            "r_2_word": False,
            "r_l_start": False,
            "r_dig_min": 1,
            "r_upp_min": 1,
            "r_low_min": 1,
            "r_sps_min": 1,
            "r_cmb13": False,
            "r_cmb23": False,
            "r_cmb33": False,
            "r_cmb14": False,
            "r_cmb24": False,
            "r_cmb34": False,
            "r_cmb44": True,
        }

    def test_length_candidate_is_exact_and_preserves_known_classes(self):
        candidate = build_length_candidate(12, self._rules(), "Valid7!A")
        self.assertEqual(len(candidate), 12)
        profile = candidate_profile(candidate)
        self.assertEqual(
            set(profile["classes"]), {"lower", "upper", "digit", "symbol"})

    def test_impossible_length_is_not_constructed(self):
        self.assertIsNone(
            build_length_candidate(3, self._rules(), "Valid7!A"))

    def test_adaptive_search_finds_exact_boundaries_with_few_probes(self):
        tested_values = []

        def probe(candidate, _purpose):
            tested_values.append(candidate)
            return 8 <= len(candidate) <= 16

        planner = AdaptiveLengthPlanner(
            probe=probe,
            candidate_factory=lambda length: build_length_candidate(
                length, self._rules(), "ValidPass7!"),
            accepted_anchor="ValidPass7!",  # length 11, already accepted
        )
        result = planner.infer()

        self.assertEqual(result["minimum"]["value"], 8)
        self.assertEqual(result["maximum"]["value"], 16)
        self.assertLess(result["probes_used"], 16)
        self.assertGreater(result["probes_saved_vs_worst_case"], 100)
        # Reports retain only structure, never the generated candidate value.
        for candidate in tested_values:
            self.assertNotIn(candidate, str(result["decision_trace"]))

    def test_search_ceiling_acceptance_reports_no_observed_maximum(self):
        planner = AdaptiveLengthPlanner(
            probe=lambda candidate, _purpose: len(candidate) >= 8,
            candidate_factory=lambda length: build_length_candidate(length),
            accepted_anchor="kqmxvzpt",
        )
        result = planner.infer()
        self.assertIsNone(result["maximum"]["value"])
        self.assertEqual(
            result["maximum"]["status"], "not_observed_within_range")
        self.assertEqual(result["maximum"]["searched_to"], 128)

    def test_inconclusive_observation_does_not_become_a_boundary(self):
        planner = AdaptiveLengthPlanner(
            probe=lambda _candidate, _purpose: INCONCLUSIVE,
            candidate_factory=lambda length: build_length_candidate(length),
            accepted_anchor="kqmxvzpt",
        )
        result = planner.infer()
        self.assertEqual(result["minimum"]["status"], "inconclusive")
        self.assertEqual(result["maximum"]["status"], "inconclusive")

    def test_html_maxlength_skips_active_maximum_probes(self):
        purposes = []

        def probe(candidate, purpose):
            purposes.append(purpose)
            return ACCEPTED if len(candidate) >= 8 else "rejected"

        planner = AdaptiveLengthPlanner(
            probe=probe,
            candidate_factory=lambda length: build_length_candidate(length),
            accepted_anchor="kqmxvzpt",
            known_maximum=64,
        )
        result = planner.infer()
        self.assertEqual(result["maximum"]["value"], 64)
        self.assertEqual(result["maximum"]["confidence"], 1.0)
        self.assertFalse(any("maximum" in purpose for purpose in purposes))

    def test_minimum_search_uses_long_accepted_anchor_beyond_legacy_ceiling(self):
        planner = AdaptiveLengthPlanner(
            probe=lambda candidate, _purpose: len(candidate) >= 40,
            candidate_factory=lambda length: build_length_candidate(length),
            accepted_anchor="k" * 48,
            minimum_range=(0, 32),
            known_maximum=64,
        )
        result = planner.infer()
        self.assertEqual(result["minimum"]["value"], 40)
        self.assertEqual(result["maximum"]["value"], 64)

    def test_conflicting_rejection_confirmation_stops_inference(self):
        def probe(candidate, purpose):
            if "confirmation" in purpose:
                return ACCEPTED
            return len(candidate) >= 8

        planner = AdaptiveLengthPlanner(
            probe=probe,
            candidate_factory=lambda length: build_length_candidate(length),
            confirmation_factory=lambda length: build_length_candidate(
                length, variant=1),
            accepted_anchor="kqmxvzpt",
        )
        result = planner.infer()
        self.assertEqual(result["minimum"]["status"], "inconclusive")
        self.assertIn("rejection_not_confirmed", result["stop_reason"])

    def test_full_form_length_measurement_uses_shared_adaptive_planner(self):
        tester = FullFormPolicyTester.__new__(FullFormPolicyTester)
        tester.my_logger = mock.MagicMock()
        tester.rate_ctrl = mock.MagicMock()
        tester.admissible_password = "ValidPass7!"
        tester._read_password_maxlength = mock.MagicMock(return_value=None)
        tester.test_one_password = mock.MagicMock(
            side_effect=lambda candidate, _purpose: 8 <= len(candidate) <= 16)

        result = tester.identify_min_and_max_length_limitations(
            self._rules(), [0, 32], [6, 128])

        self.assertEqual(result, (8, 16))
        self.assertLess(tester.test_one_password.call_count, 16)
        self.assertEqual(tester._adaptive_summary["engine"], "adaptive-length-v1")

    def test_full_form_non_specific_feedback_is_inconclusive(self):
        tester = FullFormPolicyTester.__new__(FullFormPolicyTester)
        tester.my_logger = mock.MagicMock()
        tester.driver = mock.MagicMock(page_source="<form></form>")
        tester._all_fields = []
        tester.email_xpath = ""
        tester._ensure_page_ready = mock.MagicMock()
        tester._reset_page = mock.MagicMock()
        tester.rate_ctrl = mock.MagicMock()
        tester.form_submitter = mock.MagicMock()
        tester.form_submitter.fill_and_submit.return_value = {
            "source_after": "<form></form>"
        }
        tester.error_parser = mock.MagicMock()
        tester.error_parser.diff_source.return_value = []
        tester.error_parser.parse.return_value = (False, None)
        tester._probe_evidence = []
        tester._had_inconclusive = False

        accepted = tester.test_one_password("ValidPass7!", "adaptive minimum")

        self.assertFalse(accepted)
        self.assertEqual(tester._last_probe_outcome, INCONCLUSIVE)
        self.assertTrue(tester._had_inconclusive)
        self.assertEqual(
            tester._probe_evidence[-1]["evidence"],
            "no_password_specific_feedback",
        )

    def test_subset_candidate_preserves_anchor_counts_for_present_classes(self):
        candidate = build_class_subset_candidate(
            12, ("lower", "digit"), template="kqmxVZ739!@a")
        self.assertEqual(len(candidate), 12)
        self.assertEqual(
            set(candidate_profile(candidate)["classes"]), {"lower", "digit"})
        self.assertGreaterEqual(character_class_counts(candidate)["digit"], 3)

    def test_count_candidate_changes_only_target_count_and_keeps_length(self):
        template = "kqmxVZ739!@a"
        candidate = build_class_count_candidate(template, "digit", 2)
        self.assertEqual(len(candidate), len(template))
        self.assertEqual(character_class_counts(candidate)["digit"], 2)
        self.assertEqual(
            set(candidate_profile(candidate)["classes"]),
            set(candidate_profile(template)["classes"]),
        )
        self.assertIsNone(build_class_count_candidate(
            template, "digit", 1, {"r_2_word": True}))

    def test_composition_planner_recognizes_symmetric_two_of_four(self):
        tested = []

        def probe(candidate, _purpose):
            tested.append(candidate)
            return len(candidate_profile(candidate)["classes"]) >= 2

        result = AdaptiveCompositionPlanner(
            probe=probe,
            accepted_anchor="kqmxVZ73!@",
        ).infer()

        self.assertEqual(result["status"], "measured")
        self.assertEqual(result["minimum_character_classes"], 2)
        self.assertEqual(result["required_classes"], [])
        self.assertEqual(len(result["accepted_minimal_sets"]), 6)
        self.assertLessEqual(result["probes_used"], 10)
        for candidate in tested:
            self.assertNotIn(candidate, str(result["decision_trace"]))

    def test_composition_planner_finds_asymmetric_required_classes(self):
        def probe(candidate, _purpose):
            counts = character_class_counts(candidate)
            return counts["lower"] >= 1 and counts["digit"] >= 1

        result = AdaptiveCompositionPlanner(
            probe=probe,
            accepted_anchor="kqmxVZ73!@",
        ).infer()

        self.assertEqual(result["minimum_character_classes"], 2)
        self.assertEqual(
            result["accepted_minimal_sets"], [["lower", "digit"]])
        self.assertEqual(result["required_classes"], ["lower", "digit"])
        self.assertEqual(result["class_minimums"]["lower"]["value"], 1)
        self.assertEqual(result["class_minimums"]["digit"]["value"], 1)

    def test_composition_planner_binary_searches_required_class_count(self):
        def probe(candidate, _purpose):
            counts = character_class_counts(candidate)
            return counts["lower"] >= 1 and counts["digit"] >= 2

        result = AdaptiveCompositionPlanner(
            probe=probe,
            accepted_anchor="kqmxVZ739!@",
        ).infer()

        self.assertEqual(result["required_classes"], ["lower", "digit"])
        self.assertEqual(result["class_minimums"]["digit"]["value"], 2)
        self.assertEqual(result["class_minimums"]["digit"]["status"], "measured")

    def test_composition_planner_excludes_prohibited_symbols(self):
        result = AdaptiveCompositionPlanner(
            probe=lambda candidate, _purpose: (
                len(candidate_profile(candidate)["classes"]) >= 2),
            accepted_anchor="kqmxVZ739",
            structural_rules={"r_no_a_sps": True},
        ).infer()
        self.assertEqual(result["universe"], ["lower", "upper", "digit"])
        self.assertTrue(all(
            "symbol" not in classes
            for classes in result["accepted_minimal_sets"]
        ))

    def test_composition_inconclusive_does_not_become_a_policy(self):
        result = AdaptiveCompositionPlanner(
            probe=lambda _candidate, _purpose: INCONCLUSIVE,
            accepted_anchor="kqmxVZ73!@",
        ).infer()
        self.assertEqual(result["status"], "inconclusive")
        self.assertIsNone(result["minimum_character_classes"])
        self.assertIn("inconclusive", result["stop_reason"])

    def test_composition_projection_populates_legacy_fields(self):
        restrictive = self._rules()
        summary = AdaptiveCompositionPlanner(
            probe=lambda candidate, _purpose: (
                len(candidate_profile(candidate)["classes"]) >= 2),
            accepted_anchor="kqmxVZ73!@",
        ).infer()
        apply_composition_to_restrictive(restrictive, summary)
        self.assertTrue(restrictive["r_cmb24"])
        self.assertFalse(restrictive["r_cmb44"])
        self.assertEqual(restrictive["r_dig_min"], 0)

    def test_full_form_composition_measurement_uses_shared_planner(self):
        tester = FullFormPolicyTester.__new__(FullFormPolicyTester)
        tester.my_logger = mock.MagicMock()
        tester.rate_ctrl = mock.MagicMock()
        tester.admissible_password = "kqmxVZ73!@"
        tester.test_one_password = mock.MagicMock(
            side_effect=lambda candidate, _purpose: (
                len(candidate_profile(candidate)["classes"]) >= 2))
        restrictive = self._rules()

        result = tester.identify_adaptive_composition(restrictive)

        self.assertEqual(result["engine"], "adaptive-composition-v1")
        self.assertEqual(result["minimum_character_classes"], 2)
        self.assertTrue(restrictive["r_cmb24"])


if __name__ == "__main__":
    unittest.main()
