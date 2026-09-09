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
    _normalize_auth_semantics, _provider_from_semantic,
    _provider_is_first_party, _SEND_CODE_HINTS, _AUTO_SIGNUP_HINTS,
)
from signup_flow_classifier.navigator import (
    _is_organizational_signup, _entry_text_match, _ENTRY_REGISTER_TEXTS,
    _ENTRY_LOGIN_TEXTS, detect_hover_candidate, safe_hover_menu,
)
from signup_flow_classifier.browser_failures import (
    _ACCESS_PAGE_MARKERS, _ACCESS_REDIRECT_HOSTS, detect_access_block,
    is_human_challenge_marker,
)
from signup_flow_classifier.classifier_engine import _has_auto_signup
from signup_flow_classifier.flow_types import PageState
from signup_flow_classifier.classifier import primary_method


class FakeElement:
    """最小 WebElement 桩：只提供 classify_input_type 需要的属性。"""

    def __init__(self, input_type="", name="", placeholder="", element_id="",
                 aria_label="", autocomplete="", inputmode="",
                 accessible_name=""):
        self._attrs = {
            "type": input_type,
            "name": name,
            "placeholder": placeholder,
            "id": element_id,
            "aria-label": aria_label,
            "autocomplete": autocomplete,
            "inputmode": inputmode,
        }
        self.accessible_name = accessible_name

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

    def test_autocomplete_exposes_text_password_widget(self):
        el = FakeElement(input_type="text", name="credential",
                         autocomplete="new-password")
        self.assertEqual(classify_input_type(el), "password")

    def test_autocomplete_username_is_identifier(self):
        el = FakeElement(input_type="text", name="account",
                         autocomplete="section-signup username")
        self.assertEqual(classify_input_type(el), "identifier")

    def test_tel_otp_is_code_not_phone(self):
        el = FakeElement(input_type="tel", name="mobile",
                         placeholder="短信验证码")
        self.assertEqual(classify_input_type(el), "code")

    def test_one_time_code_overrides_tel_keyboard_hint(self):
        el = FakeElement(input_type="tel", name="mobile",
                         autocomplete="one-time-code", inputmode="numeric")
        self.assertEqual(classify_input_type(el), "code")

    def test_inputmode_email_is_email(self):
        el = FakeElement(input_type="text", name="identity", inputmode="email")
        self.assertEqual(classify_input_type(el), "email")

    def test_accessible_name_from_associated_label(self):
        el = FakeElement(input_type="text", name="identity",
                         accessible_name="Email address")
        self.assertEqual(classify_input_type(el), "email")

    def test_search_input_is_not_auth_field(self):
        el = FakeElement(input_type="search", name="login_search",
                         placeholder="搜索账号")
        self.assertEqual(classify_input_type(el), "other")

    def test_type_email_wins_over_identifier_name(self):
        self.assertEqual(
            _classify_combined("email username", "email"), "email")


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

    def test_normal_footer_beian_text_is_not_global_access_marker(self):
        self.assertNotIn("公安备案", _ACCESS_PAGE_MARKERS)
        self.assertNotIn("备案查询", _ACCESS_PAGE_MARKERS)

    def test_beian_redirect_host(self):
        self.assertIn("beian.mps.gov.cn", _ACCESS_REDIRECT_HOSTS)

    def test_baidu_security_verification_marker(self):
        for m in ("百度安全验证", "请完成下方验证后继续操作", "请向右滑动完成拼图"):
            self.assertIn(m, _ACCESS_PAGE_MARKERS, m)

    def test_challenge_marker_is_distinct_from_generic_access_denial(self):
        self.assertTrue(is_human_challenge_marker("human_challenge_url"))
        self.assertTrue(is_human_challenge_marker("百度安全验证"))
        self.assertFalse(is_human_challenge_marker("access denied"))

    def test_challenge_url_is_detected_without_site_specific_hostname(self):
        class Driver:
            current_url = "https://verify.example.com/v2/app/general_page"

            @staticmethod
            def execute_script(_script):
                return {"title": "", "text": "", "controls": 0, "frames": []}

        self.assertEqual(detect_access_block(Driver()), "human_challenge_url")


class UrlPatternBudgetTests(unittest.TestCase):
    """URL 模式探测预算（避免 404 页逐个开浏览器浪费几分钟）。"""

    def test_pattern_budget_constant(self):
        from utils.login_link_discovery import LoginLinkDiscovery
        self.assertTrue(hasattr(LoginLinkDiscovery, "_SIGNUP_URL_PATTERNS"))
        self.assertGreater(len(LoginLinkDiscovery._SIGNUP_URL_PATTERNS), 0)


class ScanBlockerTests(unittest.TestCase):
    """扫码阻断词表：'扫码下载'是 App 下载引导不是认证（酷安/得物修复）。"""

    def test_scan_download_not_blocker(self):
        self.assertNotIn("扫码下载", _BLOCKER_HINTS["scan"])

    def test_scan_login_kept(self):
        for kw in ("扫码登录", "扫一扫登录", "微信扫一扫", "扫码注册"):
            self.assertIn(kw, _BLOCKER_HINTS["scan"], kw)

    def test_scan_with_visible_fields_is_method_not_blocker(self):
        blockers, methods = _normalize_auth_semantics(
            ["phone", "code"], ["scan", "sms_code"], ["phone"])
        self.assertNotIn("scan", blockers)
        self.assertIn("sms_code", blockers)
        self.assertIn("qr", methods)

    def test_scan_without_fields_remains_hard_blocker(self):
        blockers, methods = _normalize_auth_semantics([], ["scan"], [])
        self.assertIn("scan", blockers)
        self.assertIn("qr", methods)

    def test_non_scan_blockers_are_unchanged(self):
        blockers, methods = _normalize_auth_semantics(
            ["phone"], ["captcha", "tos"], ["phone"])
        self.assertEqual(blockers, ["captcha", "tos"])
        self.assertEqual(methods, ["phone"])


class ThirdPartyProviderTests(unittest.TestCase):
    """图标型第三方入口识别，同时排除提供商自己站内的一方登录。"""

    def test_icon_only_provider_semantics(self):
        cases = {
            "icon-login-wechat": "wechat",
            "oauth-btn qq": "qq",
            "third-party-weibo": "weibo",
            "auth-gitee": "gitee",
            "login-alipay": "alipay",
            "wallet phantom": "solana",
            "xiaohongshu-login": "xiaohongshu",
        }
        for semantic, expected in cases.items():
            self.assertEqual(_provider_from_semantic(semantic), expected)

    def test_first_party_provider_hosts(self):
        self.assertTrue(_provider_is_first_party("gitee", "passport.gitee.com"))
        self.assertTrue(_provider_is_first_party("qq", "www.qq.com"))
        self.assertFalse(_provider_is_first_party("gitee", "www.oschina.net"))

    def test_ascii_provider_names_require_token_boundaries(self):
        self.assertIsNone(_provider_from_semantic("apply-button request-query"))
        self.assertEqual(_provider_from_semantic("apple-login-button"), "apple")


class AutomaticSignupSemanticsTests(unittest.TestCase):
    def test_sms_button_phrases_are_covered(self):
        self.assertIn("获取短信验证码", _SEND_CODE_HINTS)
        self.assertIn("发送短信验证码", _SEND_CODE_HINTS)

    def test_login_register_combined_labels_are_covered(self):
        for text in ("登录/注册", "登录或注册", "登录即注册"):
            self.assertIn(text, _AUTO_SIGNUP_HINTS)

    def test_auto_signup_state_confirms_signup_context(self):
        self.assertTrue(_has_auto_signup([
            PageState(url="https://example.com/signin", methods=["auto_signup"])]))
        self.assertFalse(_has_auto_signup([
            PageState(url="https://example.com/signin", methods=["phone"])]))

    def test_send_code_button_without_code_field_is_still_sms_primary(self):
        states = [PageState(
            url="https://example.com/signin", fields=["phone"],
            blockers=["sms_code"], methods=["phone", "sso", "wechat"])]
        self.assertEqual(primary_method(states), "sms")


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


class FakeImgElement:
    """模拟 <img alt="微信"> 第三方图标元素。"""

    def __init__(self, alt="", title=""):
        self._alt = alt
        self._title = title
        self.tag_name = "img"

    def get_attribute(self, name):
        return {"alt": self._alt, "title": self._title}.get(name, "")


from unittest.mock import patch, MagicMock


class TestSsoProviderAltSemantic(unittest.TestCase):
    """v4.3 核心：_sso_provider 读取 img alt/title（cctv/52pojie 实测）。"""

    def _driver(self, url="https://www.cctv.com/"):
        d = MagicMock()
        d.current_url = url
        return d

    def test_alt_only_wechat_recognized(self):
        from signup_flow_classifier.page_detector import _sso_provider
        el = FakeImgElement(alt="微信")
        self.assertEqual(_sso_provider(self._driver(), el), "wechat")

    def test_title_only_qq_recognized(self):
        from signup_flow_classifier.page_detector import _sso_provider
        el = FakeImgElement(title="QQ")
        self.assertEqual(_sso_provider(self._driver(), el), "qq")

    def test_first_party_host_not_treated_as_sso(self):
        from signup_flow_classifier.page_detector import _sso_provider
        # gitee.com 上的 Gitee 登录不是第三方
        el = FakeImgElement(alt="Gitee")
        self.assertIsNone(_sso_provider(self._driver("https://gitee.com/"), el))
