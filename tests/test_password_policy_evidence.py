import unittest
from unittest import mock

from utils.password_policy_evidence import (
    has_substantive_dom_evidence,
    normalize_dom_constraints,
    parse_password_policy_texts,
)
from utils.util_test_password import TestPassword


class PasswordPolicyEvidenceTests(unittest.TestCase):
    def test_parses_english_declared_policy(self):
        policy = parse_password_policy_texts([
            "Password must be between 8 and 64 characters and contain at least "
            "one uppercase letter, one lowercase letter, one number, and one symbol."
        ])
        self.assertEqual(policy["length_min"], 8)
        self.assertEqual(policy["length_max"], 64)
        self.assertEqual(
            set(policy["required_classes"]),
            {"upper", "lower", "digit", "symbol", "letter"},
        )

    def test_parses_chinese_declared_policy(self):
        policy = parse_password_policy_texts([
            "密码长度为 6-20 位，必须包含数字和字母"
        ])
        self.assertEqual(policy["length_min"], 6)
        self.assertEqual(policy["length_max"], 20)
        self.assertIn("digit", policy["required_classes"])
        self.assertIn("letter", policy["required_classes"])

    def test_ignores_password_navigation_text(self):
        policy = parse_password_policy_texts(["Forgot password", "密码登录"])
        self.assertEqual(policy["raw_texts"], [])

    def test_quantity_number_is_not_a_digit_requirement(self):
        policy = parse_password_policy_texts([
            "Password must have a minimum number of 12 characters."
        ])
        self.assertNotIn("digit", policy["charset_hints"])
        self.assertNotIn("digit", policy["required_classes"])

    def test_mixed_positive_and_negative_classes_are_scoped(self):
        policy = parse_password_policy_texts([
            "Password must include letters but cannot contain symbols."
        ])
        self.assertIn("letter", policy["required_classes"])
        self.assertIn("symbol", policy["forbidden_classes"])
        self.assertNotIn("letter", policy["forbidden_classes"])

    def test_optional_class_is_not_reported_as_required(self):
        policy = parse_password_policy_texts([
            "Password must be at least 12 characters and may contain numbers."
        ])
        self.assertIn("digit", policy["charset_hints"])
        self.assertNotIn("digit", policy["required_classes"])

    def test_recovery_phone_number_text_is_not_password_policy(self):
        policy = parse_password_policy_texts([
            "Enter your phone number ID and select Reset Password.",
            "Use SMS verification to reset your password.",
        ])
        self.assertEqual(policy["raw_texts"], [])

    def test_including_marks_declared_classes_as_required(self):
        policy = parse_password_policy_texts([
            "Password Requirements: 12 characters including a number and a special character"
        ])
        self.assertIn("digit", policy["required_classes"])
        self.assertIn("symbol", policy["required_classes"])

    def test_normalizes_dom_constraints_without_field_value(self):
        evidence = normalize_dom_constraints({
            "minlength": "12",
            "maxlength": "128",
            "pattern": "(?=.*[A-Z]).+",
            "required": True,
            "autocomplete": "new-password",
            "validity": {"valid": False, "tooShort": True},
            "texts": ["Password must contain an uppercase letter"],
            "value": "must-not-be-retained",
        })
        self.assertEqual(evidence["constraints"]["minlength"], 12)
        self.assertTrue(evidence["constraints"]["pattern_present"])
        self.assertTrue(evidence["native_validity"]["tooShort"])
        self.assertNotIn("value", str(evidence))
        self.assertTrue(has_substantive_dom_evidence(evidence))

    def test_live_dom_snapshot_is_normalized(self):
        driver = mock.MagicMock()
        element = mock.MagicMock()
        driver.find_element.return_value = element
        driver.execute_script.return_value = {
            "minlength": "10",
            "maxlength": "72",
            "pattern": "",
            "required": True,
            "autocomplete": "new-password",
            "validity": {"valid": True},
            "texts": ["Password must be at least 10 characters"],
        }
        tester = TestPassword(
            mock.MagicMock(), "example.com", driver=driver,
            password_xpath="//input[@type='password']",
        )

        evidence = tester.extract_dom_policy_evidence()

        self.assertEqual(evidence["constraints"]["minlength"], 10)
        self.assertEqual(evidence["declared_policy"]["length_min"], 10)
        driver.find_element.assert_called_once()

    def test_declared_minimum_is_prioritized_for_admissible_search(self):
        tester = TestPassword(mock.MagicMock(), "example.com")
        tester._dom_policy_evidence = normalize_dom_constraints({
            "minlength": "14",
            "texts": ["Password must be at least 14 characters"],
        })

        self.assertEqual(tester._declared_admissible_lengths(), [14])

    def test_declared_classes_order_a_matching_candidate_first(self):
        tester = TestPassword(mock.MagicMock(), "example.com")
        tester._dom_policy_evidence = normalize_dom_constraints({
            "texts": [
                "Password must contain an uppercase letter, lowercase letter, "
                "number, and symbol"
            ],
        })

        candidate = tester._declared_stratified_candidates(12)[0]

        self.assertTrue(any(char.isupper() for char in candidate))
        self.assertTrue(any(char.islower() for char in candidate))
        self.assertTrue(any(char.isdigit() for char in candidate))
        self.assertTrue(any(not char.isalnum() for char in candidate))

    def test_declared_forbidden_digit_filters_digit_candidates(self):
        tester = TestPassword(mock.MagicMock(), "example.com")
        tester._dom_policy_evidence = normalize_dom_constraints({
            "texts": ["Password must contain letters; numbers are not allowed"],
        })

        candidates = tester._declared_stratified_candidates(12)

        self.assertTrue(candidates)
        self.assertTrue(all(not any(char.isdigit() for char in value)
                            for value in candidates))


if __name__ == "__main__":
    unittest.main()
