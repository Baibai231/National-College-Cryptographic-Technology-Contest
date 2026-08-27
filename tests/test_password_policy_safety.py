import unittest
from unittest import mock

from full_form_tester.full_form_tester import FullFormPolicyTester
from utils.site_agnostic_tester import SitePasswordPolicyTester
from utils.util_test_password import ProbeOutcome, TestPassword


class PasswordPolicySafetyTests(unittest.TestCase):
    def test_stratified_candidates_cover_common_character_classes(self):
        candidates = TestPassword._stratified_candidates(15)
        self.assertTrue(all(len(candidate) == 15 for candidate in candidates))
        self.assertTrue(any(any(c.isupper() for c in p) for p in candidates))
        self.assertTrue(any(any(not c.isalnum() for c in p) for p in candidates))
        self.assertTrue(any(
            any(c.isupper() for c in p) and any(not c.isalnum() for c in p)
            for p in candidates
        ))

    def test_probe_outcome_records_inconclusive(self):
        tester = TestPassword(mock.MagicMock(), "example.com")
        tester._record_probe("candidate", ProbeOutcome.INCONCLUSIVE, "no evidence")
        self.assertEqual(tester._last_probe_outcome, ProbeOutcome.INCONCLUSIVE)
        self.assertTrue(tester._had_inconclusive)
        self.assertEqual(tester._probe_evidence[-1]["outcome"], "inconclusive")

    def test_inline_policy_stops_when_negative_control_is_not_rejected(self):
        driver = mock.MagicMock()
        policy_tester = SitePasswordPolicyTester(driver, "https://example.com")
        policy_tester.signup_url = "https://example.com/signup"
        policy_tester.password_xpath = "//input[@type='password']"
        fake_probe = mock.MagicMock()
        fake_probe.establish_inline_control.return_value = False
        fake_probe._probe_evidence = [{
            "password_length": 1,
            "outcome": "inconclusive",
            "evidence": "no rejection",
        }]

        with mock.patch(
            "utils.site_agnostic_tester.TestPassword", return_value=fake_probe
        ):
            policy = policy_tester.run_password_policy_test()

        self.assertTrue(policy["_inconclusive"])
        self.assertIn("negative_control_not_rejected", policy["_inconclusive_reason"])
        fake_probe.find_admissible_password.assert_not_called()

    def test_full_form_tester_is_inert_without_explicit_authorization(self):
        tester = FullFormPolicyTester(
            mock.MagicMock(),
            "https://example.com",
            signup_url="https://example.com/signup",
            test_site="example.com",
        )
        policy = tester.run_full_test()
        self.assertTrue(policy["_full_form_unauthorized"])
        self.assertTrue(policy["_inconclusive"])


if __name__ == "__main__":
    unittest.main()
