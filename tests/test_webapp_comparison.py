import unittest

from scripts.audit_program_vs_manual import markdown

from webapp.app import _manual_comparison, _manual_traits, _program_reason


class ManualComparisonTests(unittest.TestCase):
    def test_no_password_does_not_match_direct_password(self):
        result = _manual_comparison(
            "direct_password", "手机号+验证码注册，无密码",
            "手机号、一次性验证码", "手机号、一次性验证码", "短信验证码")
        self.assertEqual(result["status"], "mismatch")
        self.assertIn("人工明确记录为无口令", result["reason"])

    def test_direct_password_positive_match_has_reason(self):
        result = _manual_comparison(
            "direct_password", "手机号+密码注册",
            "手机号、口令", "手机号、口令", "—")
        self.assertEqual(result["status"], "match")
        self.assertIn("口令框", result["reason"])
        # 用户要求：reason 不带"一致："前缀（结论由徽标表达）
        self.assertNotIn("一致", result["reason"])

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

    def test_offline_audit_lists_inconclusive_separately(self):
        rows = [
            {"hostname": "match.example", "status": "match",
             "program_flow": "otp_only", "program_route": "验证码",
             "manual_signup": "验证码", "reason": "一致"},
            {"hostname": "wrong.example", "status": "mismatch",
             "program_flow": "sso_only", "program_route": "第三方",
             "manual_signup": "口令", "reason": "差异"},
            {"hostname": "unknown.example", "status": "inconclusive_program",
             "program_flow": "unknown", "program_route": "未确认",
             "manual_signup": "验证码", "reason": "程序证据不足"},
        ]
        report = markdown(rows, "candidate.jsonl")
        self.assertIn("明确不一致：1", report)
        self.assertIn("证据不足：1", report)
        self.assertIn("证据不足项（不计入正确率）", report)
        self.assertIn("unknown.example", report)

    def test_missing_methods_noted_in_match_reason(self):
        # 分类口径（2026-08-16）：方法缺失并入 match，缺失方法以文字注明
        result = _manual_comparison(
            "direct_password", "手机号+验证码\n账号+密码\n第三方",
            "手机号、口令", "手机号、口令", "—",
            verified=True, structured={"password": True, "otp": True, "sso": True},
            method_results=[{"name_zh": "手机号+验证码"}, {"name_zh": "账号+密码"}])
        self.assertEqual(result["status"], "match")
        self.assertIn("第三方", result["reason"])
        self.assertIn("方法识别不全", result["reason"])

    def test_complete_methods_stay_match(self):
        result = _manual_comparison(
            "direct_password", "手机号+验证码\n第三方",
            "手机号、口令", "手机号、口令", "—",
            verified=True, structured={"password": True, "otp": True, "sso": True},
            method_results=[{"name_zh": "手机号+验证码"},
                            {"name_zh": "账号+密码"},
                            {"name_zh": "第三方（微信）"}])
        self.assertEqual(result["status"], "match")
