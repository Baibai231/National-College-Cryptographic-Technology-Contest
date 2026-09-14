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

    def test_probe_evidence_records_meter_bin_without_password_plaintext(self):
        tester = TestPassword(mock.MagicMock(), "example.com")
        tester._current_probe_purpose = "meter comparison"
        tester._last_strength_level = "strong"
        tester._record_probe("Aa3!secret", ProbeOutcome.ACCEPTED, "paired control")

        evidence = tester._probe_evidence[-1]
        self.assertEqual(evidence["strength_meter_level"], "strong")
        self.assertEqual(evidence["character_profile"], "lower+upper+digit+symbol")
        self.assertEqual(evidence["probe_purpose"], "meter comparison")
        self.assertNotIn("Aa3!secret", str(evidence))

    def test_chinese_medium_meter_text_is_not_misread_as_strong(self):
        tester = TestPassword(mock.MagicMock(), "example.com")
        tester._parse_strength_level("密码强度中等，强度要求：")
        self.assertEqual(tester._last_strength_level, "medium")

    def test_chinese_strong_and_weak_meter_texts_are_normalized(self):
        tester = TestPassword(mock.MagicMock(), "example.com")
        tester._parse_strength_level("密码强度强，强度要求：")
        self.assertEqual(tester._last_strength_level, "strong")
        tester._parse_strength_level("口令强度：较弱")
        self.assertEqual(tester._last_strength_level, "weak")

    def test_repeated_rejection_inside_stated_range_is_non_discriminating(self):
        tester = TestPassword(mock.MagicMock(), "example.com")
        message = "请输入4-20个字符，支持数字、字母和符号的组合"
        for password in ("k4m2x9a7", "Aa3kqmxv", "a3!kqmxv", "Aa3!kqmx"):
            tester._rejected_probe_observations.append({
                "password_length": len(password),
                "character_profile": tester._candidate_profile(password),
                "message": message,
            })

        reason = tester._non_discriminating_rejection_reason()

        self.assertIn("non_discriminating_rejection_feedback", reason)
        self.assertNotIn("k4m2x9a7", reason)

    def test_repeated_minimum_length_rejection_does_not_abort_early(self):
        tester = TestPassword(mock.MagicMock(), "example.com")
        message = "Password must contain 12-32 characters"
        for password in ("k4m2x9a7", "Aa3kqmxv", "a3!kqmxv", "Aa3!kqmx"):
            tester._rejected_probe_observations.append({
                "password_length": len(password),
                "character_profile": tester._candidate_profile(password),
                "message": message,
            })

        self.assertEqual(tester._non_discriminating_rejection_reason(), "")

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

    # ── P3 自洽校验：OR 规则检测 ──
    def test_self_consistency_detects_or_rule_when_single_class_rejected(self):
        tester = TestPassword(mock.MagicMock(), "example.com")
        tester.admissible_password = "k4m2x9a7tyIQRY0zOtPptdYGO"
        # GitHub 式政策：模型推断"无类要求 + 至少1类(r_cmb14)"，
        # 但最小长度单类密码实际被拒（8 位需数字+小写）
        tester.test_one_password = mock.MagicMock(return_value=False)
        rp = {
            "r_no_a_sps": False, "r_2_word": False, "r_l_start": False,
            "r_dig_min": 0, "r_upp_min": 0, "r_low_min": 0, "r_sps_min": 0,
            "r_cmb13": False, "r_cmb23": False, "r_cmb33": False,
            "r_cmb14": True, "r_cmb24": False, "r_cmb34": False, "r_cmb44": False,
        }
        ok, note, or_rule = tester.self_consistency_check(
            rp, [8, 72], tester.admissible_password)
        self.assertFalse(ok)
        self.assertIn("or_rule_likely", note)
        # OR 规则刻画已探测：单类被拒、两两组合有接受、长度替代分支
        self.assertIsNotNone(or_rule)
        self.assertEqual(or_rule.get("min_length"), 8)

    def test_self_consistency_passes_when_single_class_accepted(self):
        tester = TestPassword(mock.MagicMock(), "example.com")
        tester.admissible_password = "k4m2x9a7"
        # 宽松站点：8 位纯数字可接受 → 模型与行为一致
        tester.test_one_password = mock.MagicMock(return_value=True)
        rp = {
            "r_no_a_sps": False, "r_2_word": False, "r_l_start": False,
            "r_dig_min": 0, "r_upp_min": 0, "r_low_min": 0, "r_sps_min": 0,
            "r_cmb13": False, "r_cmb23": False, "r_cmb33": False,
            "r_cmb14": False, "r_cmb24": False, "r_cmb34": False, "r_cmb44": False,
        }
        ok, _, or_rule = tester.self_consistency_check(
            rp, [8, 72], tester.admissible_password)
        self.assertTrue(ok)
        self.assertIsNone(or_rule)

    def test_self_consistency_skips_probe_when_classes_required(self):
        tester = TestPassword(mock.MagicMock(), "example.com")
        tester.admissible_password = "k4m2x9a7"
        # 百度式政策：已推断数字最少 1 个 + 组合要求 → 模型明确，
        # 不触发单类探针（探针只在"模型预测任意单类即可"时运行）
        tester.test_one_password = mock.MagicMock(return_value=True)
        rp = {
            "r_no_a_sps": False, "r_2_word": False, "r_l_start": False,
            "r_dig_min": 1, "r_upp_min": 0, "r_low_min": 0, "r_sps_min": 0,
            "r_cmb13": False, "r_cmb23": False, "r_cmb33": False,
            "r_cmb14": False, "r_cmb24": False, "r_cmb34": True, "r_cmb44": False,
        }
        ok, _, or_rule = tester.self_consistency_check(
            rp, [8, 14], tester.admissible_password)
        self.assertTrue(ok)
        self.assertIsNone(or_rule)
        # len(admissible)==lo → 前缀探针也跳过，只调用了负对照验证前的调用
        tester.test_one_password.assert_not_called()

    # ── P3 符号鸡生蛋：无冗余字符回退消歧 ──
    def test_check_special_symbols_no_redundant_char_with_dual_probe(self):
        tester = TestPassword(mock.MagicMock(), "example.com")
        # 无冗余字符的 admissible（每类恰好 1 个）：无法等长替换加符号
        tester.admissible_password = "aB3"
        # 符号探针(@替换位置0)被拒，但对照(其他类替换)被接受 → 禁止符号
        tester.test_one_password = mock.MagicMock(
            side_effect=lambda pw, *a, **k: not pw.startswith("@"))
        self.assertTrue(tester.check_special_symbols("aB3"))

    def test_check_special_symbols_no_redundant_char_symbol_allowed(self):
        tester = TestPassword(mock.MagicMock(), "example.com")
        tester.admissible_password = "aB3"
        # 符号探针被接受 → 允许符号
        tester.test_one_password = mock.MagicMock(return_value=True)
        self.assertFalse(tester.check_special_symbols("aB3"))

    # ── main.py: or_rule_likely 政策保留 ──
    def test_policy_is_usable_keeps_or_rule_likely_with_length(self):
        from main import _policy_is_usable
        policy = {
            "length": [8, 72],
            "restrictive": {"r_cmb14": True},
            "permissive": {},
            "_inconclusive": True,
            "_inconclusive_reason": (
                "or_rule_likely: 最小长度单类密码被拒但模型未推断任何字符类要求"),
        }
        self.assertTrue(_policy_is_usable(policy))

    def test_policy_is_usable_drops_other_inconclusive(self):
        from main import _policy_is_usable
        policy = {
            "length": [8, 72],
            "restrictive": {},
            "permissive": {},
            "_inconclusive": True,
            "_inconclusive_reason": "negative_control_not_rejected",
        }
        self.assertFalse(_policy_is_usable(policy))

    def test_policy_diagnostic_preserves_reason_without_promoting_hint(self):
        from main import _policy_diagnostic
        policy = {
            "length": [0, 0],
            "_inconclusive": True,
            "_inconclusive_reason": "non_discriminating_rejection_feedback",
            "_hint_policy": {"length_min": 8, "length_max": 16},
            "_probe_evidence": [{"password_length": 8, "outcome": "rejected"}],
        }

        diagnostic = _policy_diagnostic(policy)

        self.assertEqual(diagnostic["status"], "inconclusive")
        self.assertIn("non_discriminating", diagnostic["reason"])
        self.assertEqual(diagnostic["hint_policy"]["length_min"], 8)
        self.assertNotIn("length", diagnostic)


if __name__ == "__main__":
    unittest.main()
