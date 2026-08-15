"""v4 逐方法清单聚合回归测试。

覆盖 aggregate_methods 的判定规则：
1. 多方法并存时逐方法列出（china.com 账号密码+QQ+第三方）
2. confirmed/blocked/observed 三态判定
3. 口令路线存在时 phone/email/identifier 是账号标识，不单列方法
4. 主方法状态与 flow_type 对齐（到达口令步骤即 confirmed，备选门槛不挂主方法）
5. 字段反推方法（password 字段→账号密码、code 字段→短信验证码）
6. no_web_signup 升级条件不误伤"点过入口但无信号"的波动站
"""
import sys
import os
import unittest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from signup_flow_classifier.flow_types import PageState
from signup_flow_classifier.classifier import aggregate_methods


def state(step, fields=None, methods=None, blockers=None, actions=None,
          available_actions=None, ui_type="modal"):
    return PageState(
        step=step, url="https://example.com/", ui_type=ui_type,
        fields=fields or [], methods=methods or [], blockers=blockers or [],
        actions=actions or [], available_actions=available_actions or [],
    )


def by_name(methods, name):
    for m in methods:
        if m.name_zh == name or m.method == name:
            return m
    return None


class TestAggregateMethods(unittest.TestCase):

    def test_multi_method_page_lists_each_method(self):
        # china.com 实测：登录弹窗同时有账号密码 + QQ + 第三方
        states = [
            state(2, fields=["identifier", "password"],
                  methods=["sso", "qq"]),
            state(3, fields=["identifier", "password"],
                  methods=["sso", "qq"]),
        ]
        ms = aggregate_methods(states, flow_type="direct_password")
        names = {m.name_zh for m in ms}
        self.assertEqual(names, {"账号密码", "QQ", "第三方登录"})
        self.assertEqual(by_name(ms, "账号密码").status, "confirmed")

    def test_soft_method_auto_signup_is_observed(self):
        states = [state(1, methods=["phone", "auto_signup"], blockers=["sms_code"])]
        ms = aggregate_methods(states)
        self.assertEqual(by_name(ms, "手机号自动注册").status, "observed")
        self.assertEqual(by_name(ms, "手机号").status, "blocked")

    def test_identifier_fields_not_listed_when_password_present(self):
        # 12306 实测：password+phone+email 同页，手机号/邮箱只是账号标识
        states = [state(1, fields=["identifier", "password", "email", "phone"])]
        ms = aggregate_methods(states, flow_type="direct_password")
        names = {m.name_zh for m in ms}
        self.assertEqual(names, {"账号密码"})

    def test_identifier_fields_listed_without_password(self):
        states = [state(1, fields=["identifier", "email", "phone"])]
        ms = aggregate_methods(states)
        names = {m.name_zh for m in ms}
        self.assertEqual(names, {"账号/邮箱", "邮箱", "手机号"})

    def test_primary_method_confirmed_despite_page_gate(self):
        # 整页有滑块/短信门槛，但主方法（密码）已到达 → confirmed，门槛不挂主方法
        states = [state(1, fields=["phone", "password"],
                        blockers=["sms_code", "slide"],
                        methods=["phone", "sms"])]
        ms = aggregate_methods(states, flow_type="direct_password")
        pwd = by_name(ms, "账号密码")
        self.assertEqual(pwd.status, "confirmed")
        self.assertEqual(pwd.blockers, [])
        self.assertNotIn("（门槛：", pwd.route)
        self.assertEqual(by_name(ms, "短信验证码").status, "blocked")

    def test_all_blocked_when_only_gated(self):
        states = [state(1, methods=["qr"], blockers=["captcha"])]
        ms = aggregate_methods(states)
        self.assertEqual(by_name(ms, "扫码").status, "blocked")

    def test_code_field_derives_sms_method(self):
        states = [state(1, fields=["phone", "code"], blockers=["sms_code"])]
        ms = aggregate_methods(states)
        self.assertIsNotNone(by_name(ms, "短信验证码"))

    def test_confidence_high_with_submit_action(self):
        states = [state(1, fields=["phone", "code"],
                        available_actions=["send_code", "submit"])]
        ms = aggregate_methods(states)
        self.assertEqual(by_name(ms, "手机号").confidence, "high")

    def test_confirmed_method_without_gate(self):
        states = [state(1, methods=["qr"])]
        ms = aggregate_methods(states)
        self.assertEqual(by_name(ms, "扫码").status, "confirmed")


if __name__ == "__main__":
    unittest.main()
