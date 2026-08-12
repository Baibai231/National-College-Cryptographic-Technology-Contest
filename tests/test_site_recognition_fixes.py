"""回归测试：真实站识别问题修复（2026-08-12）。

覆盖：
1. 慕课网 imooc 注册手机号框（name="email" 但 placeholder="请输入注册手机号"）
   不能被误判为 email 字段 —— 用户可见语义（placeholder/aria-label）
   优先于结构属性（name/id）。
2. 知乎 zhihu "注册机构号"（/org/signup）不能作为普通用户注册入口 ——
   LoginLinkDiscovery 的 CDP 链接发现与 detect_entry_button 一致排除机构注册。
"""
import sys
import os
import unittest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from signup_flow_classifier.page_detector import (
    _classify_combined, classify_input_type, _BLOCKER_HINTS, _EMAIL_HINTS,
    _PHONE_HINTS, _PASSWORD_HINTS, _CODE_HINTS, _IDENTIFIER_HINTS,
)
from signup_flow_classifier.navigator import (
    _is_organizational_signup, _entry_text_match, _ENTRY_REGISTER_TEXTS,
    _ENTRY_LOGIN_TEXTS, detect_hover_candidate, safe_hover_menu,
)
from signup_flow_classifier.browser_failures import (
    _ACCESS_PAGE_MARKERS, _ACCESS_REDIRECT_HOSTS, detect_access_block,
)


class FakeElement:
    """最小 WebElement 桩：只提供 classify_input_type 需要的属性。"""

    def __init__(self, input_type="", name="", placeholder="", element_id="",
                 aria_label=""):
        self._attrs = {
            "type": input_type,
            "name": name,
            "placeholder": placeholder,
            "id": element_id,
            "aria-label": aria_label,
        }

    def get_attribute(self, key):
        return self._attrs.get(key, "")


class FieldSemanticPriorityTests(unittest.TestCase):
    """用户可见语义优先于 name/id 结构属性（imooc 手机号框修复）。"""

    def test_imooc_phone_field_not_email(self):
        # 慕课注册弹窗实测：name="email" 但 placeholder 是"请输入注册手机号"
        el = FakeElement(input_type="text", name="email",
                         placeholder="请输入注册手机号")
        self.assertEqual(classify_input_type(el), "phone")

    def test_combined_imooc_phone_field_not_email(self):
        # JS 侧走 _classify_combined，visible 传 placeholder+aria-label
        combined = "text email 请输入注册手机号  "
        ft = _classify_combined(combined, "text", visible="请输入注册手机号 ")
        self.assertEqual(ft, "phone")

    def test_normal_email_unchanged(self):
        el = FakeElement(input_type="text", name="email",
                         placeholder="请输入邮箱")
        self.assertEqual(classify_input_type(el), "email")

    def test_mixed_phone_email_keeps_structural(self):
        # "请输入登录手机号/邮箱" 同时含两类语义 → 保留原结构判定
        el = FakeElement(input_type="text", name="email",
                         placeholder="请输入登录手机号/邮箱")
        self.assertEqual(classify_input_type(el), "email")

    def test_code_not_phone(self):
        el = FakeElement(input_type="text", name="code",
                         placeholder="请输入短信验证码")
        self.assertEqual(classify_input_type(el), "code")

    def test_phone_hint_via_aria_label(self):
        # aria-label 也是用户可见语义
        el = FakeElement(input_type="text", name="email",
                         aria_label="请输入注册手机号")
        self.assertEqual(classify_input_type(el), "phone")

    def test_type_tel_still_phone(self):
        el = FakeElement(input_type="tel", name="email")
        self.assertEqual(classify_input_type(el), "phone")

    def test_type_email_still_email(self):
        el = FakeElement(input_type="email", name="email",
                         placeholder="user@example.com")
        self.assertEqual(classify_input_type(el), "email")


class MultilingualCapabilityTests(unittest.TestCase):
    """从旧分支移植的多语言词表（8/8-8/9 工作），合入新仓库后保持一致。"""

    def test_field_hints_cover_major_language_groups(self):
        cases = [
            ("correo electrónico", "email", _EMAIL_HINTS),
            ("mot de passe", "password", _PASSWORD_HINTS),
            ("電話番号", "phone", _PHONE_HINTS),
            ("인증 코드", "code", _CODE_HINTS),
            ("имя пользователя", "identifier", _IDENTIFIER_HINTS),
        ]
        for keyword, expected, hints in cases:
            self.assertIn(keyword, hints, f"{keyword} 应存在于 {expected} hints")

    def test_multilingual_field_classification(self):
        cases = [
            ("请输入注册手机号", "phone"),
            ("correo electrónico", "email"),
            ("mot de passe", "password"),
            ("電話番号", "phone"),
            ("인증 코드", "code"),
            ("имя пользователя", "identifier"),
        ]
        for keyword, expected in cases:
            el = FakeElement(input_type="text", placeholder=keyword)
            self.assertEqual(classify_input_type(el), expected, keyword)

    def test_captcha_blocker_multilingual(self):
        # 词表本身存储小写开头；_match_any 匹配时大小写不敏感
        for keyword in ["verify you're a human", "je ne suis pas un robot",
                        "no soy un robot", "я не робот"]:
            self.assertIn(keyword, _BLOCKER_HINTS["captcha"], keyword)

    def test_entry_texts_cover_major_language_groups(self):
        for keyword in ["新規登録", "会員登録", "회원가입", "зарегистрироваться",
                        "s'inscrire", "registrarse", "konto erstellen"]:
            self.assertIn(keyword, _ENTRY_REGISTER_TEXTS, keyword)
        for keyword in ["se connecter", "anmelden", "ログイン", "로그인", "войти"]:
            self.assertIn(keyword, _ENTRY_LOGIN_TEXTS, keyword)

    def test_multilingual_entry_text_match(self):
        for keyword in ["新規登録", "회원가입", "s'inscrire"]:
            self.assertTrue(
                _entry_text_match(keyword, _ENTRY_REGISTER_TEXTS), keyword)
        for keyword in ["anmelden", "ログイン", "connexion"]:
            self.assertTrue(
                _entry_text_match(keyword, _ENTRY_LOGIN_TEXTS), keyword)

    def test_hover_functions_present(self):
        # hover 菜单能力随 navigator 一起移植，函数必须存在且可导入
        self.assertTrue(callable(detect_hover_candidate))
        self.assertTrue(callable(safe_hover_menu))


class AccessBlockDetectionTests(unittest.TestCase):
    """反爬重定向/整页验证识别（beian 跳转、百度安全验证、36kr 整页挑战）。"""

    def test_beian_redirect_marker(self):
        self.assertTrue(any("mps.gov.cn" in m for m in _ACCESS_PAGE_MARKERS))

    def test_beian_redirect_host(self):
        self.assertIn("beian.mps.gov.cn", _ACCESS_REDIRECT_HOSTS)

    def test_baidu_security_verification_marker(self):
        for m in ("百度安全验证", "请完成下方验证后继续操作", "请向右滑动完成拼图"):
            self.assertIn(m, _ACCESS_PAGE_MARKERS, m)


class UrlPatternBudgetTests(unittest.TestCase):
    """URL 模式探测预算（避免 404 页逐个开浏览器浪费几分钟）。"""

    def test_pattern_budget_constant(self):
        from utils.login_link_discovery import LoginLinkDiscovery
        self.assertTrue(hasattr(LoginLinkDiscovery, "_SIGNUP_URL_PATTERNS"))
        self.assertGreater(len(LoginLinkDiscovery._SIGNUP_URL_PATTERNS), 0)


class OrganizationalSignupExclusionTests(unittest.TestCase):
    """机构/企业/商家注册不能冒充普通用户注册入口（zhihu /org/signup 修复）。"""

    def test_zhihu_org_signup_excluded(self):
        self.assertTrue(_is_organizational_signup("https://www.zhihu.com/org/signup"))

    def test_zhihu_org_signup_with_query_excluded(self):
        self.assertTrue(
            _is_organizational_signup("https://www.zhihu.com/org/signup?next=1"))

    def test_imooc_user_signup_kept(self):
        self.assertFalse(_is_organizational_signup(
            "https://www.imooc.com/user/newsignup"))

    def test_zhihu_home_kept(self):
        self.assertFalse(_is_organizational_signup("https://www.zhihu.com/"))

    def test_github_signup_kept(self):
        self.assertFalse(_is_organizational_signup("https://github.com/signup"))

    def test_enterprise_register_excluded(self):
        self.assertTrue(_is_organizational_signup(
            "https://example.com/enterprise/register"))


if __name__ == "__main__":
    unittest.main()
