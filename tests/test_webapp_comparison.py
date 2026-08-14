import unittest

from webapp.app import _manual_comparison, _manual_traits, _program_reason


class ManualComparisonTests(unittest.TestCase):
    def test_no_password_does_not_match_direct_password(self):
        result = _manual_comparison(
            "direct_password", "手机号+验证码注册，无密码",
            "手机号、一次性验证码", "手机号、一次性验证码", "短信验证码")
        self.assertEqual(result["status"], "mismatch")
        self.assertIn("差异", result["reason"])

    def test_direct_password_positive_match_has_reason(self):
        result = _manual_comparison(
            "direct_password", "手机号+密码注册",
            "手机号、口令", "手机号、口令", "—")
        self.assertEqual(result["status"], "match")
        self.assertIn("口令框", result["reason"])
        self.assertIn("一致", result["reason"])

    def test_unknown_is_not_automatically_correct(self):
        result = _manual_comparison(
            "unknown", "手机号+验证码注册", "未确认", "手机号", "—")
        self.assertEqual(result["status"], "inconclusive_program")

    def test_unknown_never_claims_correct_even_when_manual_says_no_web(self):
        result = _manual_comparison(
            "unknown", "无登录注册界面", "未确认", "—", "—")
        self.assertEqual(result["status"], "inconclusive_program")

    def test_no_web_signup_matches_explicit_manual_no_web(self):
        result = _manual_comparison(
            "no_web_signup", "无登录注册界面", "未确认", "—", "—")
        self.assertEqual(result["status"], "match")

    def test_human_blocked_matches_verification_gate(self):
        result = _manual_comparison(
            "human_blocked", "手机验证后出现密码框", "手机号 → 短信验证码",
            "手机号", "短信验证码")
        self.assertEqual(result["status"], "match")

    def test_human_blocked_requires_same_gate_type(self):
        result = _manual_comparison(
            "human_blocked", "手机号+短信验证码注册", "扫码",
            "—", "扫码")
        self.assertEqual(result["status"], "mismatch")

    def test_security_verification_text_is_a_captcha_gate(self):
        result = _manual_comparison(
            "human_blocked", "百度安全验证+扫码", "图片/人机验证",
            "—", "图片/人机验证")
        self.assertEqual(result["status"], "match")

    def test_generic_manual_verification_is_inconclusive(self):
        result = _manual_comparison(
            "human_blocked", "需验证后继续", "手机号 → 短信验证码",
            "手机号", "短信验证码")
        self.assertEqual(result["status"], "inconclusive_manual")

    def test_structured_manual_data_overrides_ambiguous_text(self):
        result = _manual_comparison(
            "direct_password", "注册表单藏在登录界面", "账号 → 口令",
            "账号、口令", "—", structured={"password": True})
        self.assertEqual(result["status"], "match")

    def test_scan_without_password_does_not_match_otp(self):
        result = _manual_comparison(
            "otp_only", "扫码/第三方注册（扫码后无需口令）",
            "手机号 → 短信验证码", "手机号、验证码", "短信验证码")
        self.assertEqual(result["status"], "mismatch")

    def test_without_manual_method_detail_is_inconclusive(self):
        result = _manual_comparison(
            "direct_password", "注册表单藏在登录界面", "账号 → 口令",
            "账号、口令", "—")
        self.assertEqual(result["status"], "inconclusive_manual")

    def test_pending_manual_is_not_called_correct(self):
        result = _manual_comparison(
            "direct_password", "", "手机号、口令", "手机号、口令", "—",
            verified=False)
        self.assertEqual(result["status"], "pending")

    def test_negative_password_trait(self):
        traits = _manual_traits("手机号+验证码注册，无密码")
        self.assertTrue(traits["negative_password"])
        self.assertFalse(traits["password"])

    def test_no_need_passphrase_is_negative_password(self):
        traits = _manual_traits("手机号验证，无需口令")
        self.assertTrue(traits["negative_password"])
        self.assertFalse(traits["password"])

    def test_program_reason_exists_for_every_flow(self):
        for flow in (
            "direct_password", "identifier_then_password",
            "verification_then_password", "otp_only", "email_only",
            "sso_only", "multiple_methods", "human_blocked",
            "no_web_signup", "unknown", "error"):
            self.assertTrue(_program_reason(flow, "测试路线", "手机号", "短信验证码"))

    def test_sso_reason_names_observed_providers(self):
        reason = _program_reason(
            "sso_only", "未确认", "—", "—", methods="Google、Solana")
        self.assertIn("Google、Solana", reason)
