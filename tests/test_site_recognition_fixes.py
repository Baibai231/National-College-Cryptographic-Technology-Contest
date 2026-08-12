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

from signup_flow_classifier.page_detector import _classify_combined, classify_input_type
from signup_flow_classifier.navigator import _is_organizational_signup


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
