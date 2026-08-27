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
        ok, note = tester.self_consistency_check(rp, [8, 72], tester.admissible_password)
        self.assertFalse(ok)
        self.assertIn("or_rule_likely", note)

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
        ok, _ = tester.self_consistency_check(rp, [8, 72], tester.admissible_password)
        self.assertTrue(ok)

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
        ok, _ = tester.self_consistency_check(rp, [8, 14], tester.admissible_password)
        self.assertTrue(ok)
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


if __name__ == "__main__":
    unittest.main()
