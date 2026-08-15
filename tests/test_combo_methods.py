"""展示层组合式方法测试（combo_methods，仅 webapp 展示用，不落盘）。

铁律（2026-08-15）：数据层 reports/misc 保持原始格式（aggregate_methods），
展示层 combo_methods 只由 webapp 在响应时计算。
"""
import sys
import os
import unittest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from signup_flow_classifier.flow_types import PageState
from signup_flow_classifier.classifier import combo_methods


def state(step, fields=None, methods=None, blockers=None, actions=None,
          available_actions=None, ui_type="modal"):
    return PageState(
        step=step, url="https://example.com/", ui_type=ui_type,
        fields=fields or [], methods=methods or [], blockers=blockers or [],
        actions=actions or [], available_actions=available_actions or [],
    )


def by_name(methods, name):
    for m in methods:
        if m.name_zh == name:
            return m
    return None


class TestComboMethods(unittest.TestCase):

    def test_phone_code_is_one_method(self):
        # 36kr 实测：手机号+验证码是一个方法
        states = [
            state(1, fields=["phone", "code"], blockers=["sms_code"]),
            state(2, fields=["phone", "password"]),
        ]
        ms = combo_methods(states, flow_type="direct_password")
        names = [m.name_zh for m in ms]
        self.assertIn("手机号+验证码", names)
        self.assertIn("手机号+密码", names)
        self.assertNotIn("手机号", names)
        self.assertEqual(by_name(ms, "手机号+验证码").status, "confirmed")

    def test_sms_blocker_implies_code_step(self):
        states = [state(1, fields=["phone"], blockers=["sms_code"])]
        ms = combo_methods(states, flow_type="human_blocked")
        self.assertIsNotNone(by_name(ms, "手机号+验证码"))

    def test_multi_identifier_joins_with_slash(self):
        states = [state(1, fields=["identifier", "password", "email", "phone"])]
        ms = combo_methods(states, flow_type="direct_password")
        self.assertEqual([m.name_zh for m in ms], ["账号/邮箱/手机号+密码"])

    def test_sso_grouped(self):
        states = [state(1, fields=["phone", "password"],
                        methods=["sso", "wechat", "qq"])]
        ms = combo_methods(states, flow_type="direct_password")
        self.assertIsNotNone(by_name(ms, "第三方（QQ、微信）"))

    def test_hard_gate_blocks_only_that_state(self):
        states = [state(1, fields=["phone", "password"], blockers=["captcha"])]
        ms = combo_methods(states)
        self.assertEqual(by_name(ms, "手机号+密码").status, "blocked")

    def test_primary_alignment_clears_gate(self):
        states = [state(1, fields=["phone", "password"], blockers=["slide"])]
        ms = combo_methods(states, flow_type="direct_password")
        pwd = by_name(ms, "手机号+密码")
        self.assertEqual(pwd.status, "confirmed")
        self.assertEqual(pwd.blockers, [])

    def test_identifier_alone_not_a_method(self):
        ms = combo_methods([state(1, fields=["phone"])])
        self.assertEqual(len(ms), 0)

    def test_display_route_empty(self):
        # 展示层不携带步骤/页面形态（网页已删除该信息）
        states = [state(2, fields=["phone", "password"])]
        ms = combo_methods(states)
        self.assertEqual(ms[0].route, "")

    def test_borrowed_identifier_for_password_step(self):
        states = [
            state(1, fields=["phone"], blockers=["sms_code"]),
            state(2, fields=["password"]),
        ]
        ms = combo_methods(states, flow_type="direct_password")
        self.assertIsNotNone(by_name(ms, "手机号+密码"))


if __name__ == "__main__":
    unittest.main()
