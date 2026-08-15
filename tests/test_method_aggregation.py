"""v4 组合式方法清单聚合回归测试。

覆盖 aggregate_methods 的组合式判定规则（用户反馈 2026-08-15）：
1. 字段组合成方法：手机号+验证码 是一个方法，不拆成"手机号"和"短信验证码"
2. 密码/验证码 + 多个标识符：账号/邮箱/手机号+密码
3. 短信验证码属于方法本身（软门槛），不因 sms_code 把方法标"需验证"
4. 硬门槛（人机/滑块/扫码确认/App确认/协议）才使方法标"需验证"
5. 第三方提供商合并为一个方法：第三方（微信、QQ）
6. 主方法与 flow_type 对齐（到达口令步骤即 confirmed）
7. 只有标识符无验证要素不算完整方法
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
        if m.name_zh == name:
            return m
    return None


class TestAggregateMethods(unittest.TestCase):

    def test_phone_code_is_one_method_not_two(self):
        # 36kr 实测：手机号+验证码是一个方法，不能拆成"手机号"+"短信验证码"
        states = [
            state(1, fields=["phone", "code"], blockers=["sms_code"]),
            state(2, fields=["phone", "password"]),
        ]
        ms = aggregate_methods(states, flow_type="direct_password")
        names = [m.name_zh for m in ms]
        self.assertIn("手机号+验证码", names)
        self.assertIn("手机号+密码", names)
        self.assertNotIn("手机号", names)
        self.assertNotIn("短信验证码", names)
        # sms_code 是方法本身的要素，不使方法变"需验证"
        self.assertEqual(by_name(ms, "手机号+验证码").status, "confirmed")

    def test_sms_blocker_implies_code_step(self):
        # zhihu 实测：只拍到手机号 + sms_code 门槛，仍应组合为 手机号+验证码
        states = [state(1, fields=["phone"], blockers=["sms_code"])]
        ms = aggregate_methods(states, flow_type="human_blocked")
        self.assertIsNotNone(by_name(ms, "手机号+验证码"))

    def test_multi_identifier_joins_with_slash(self):
        # 12306 实测：账号/邮箱/手机号 + 密码
        states = [state(1, fields=["identifier", "password", "email", "phone"])]
        ms = aggregate_methods(states, flow_type="direct_password")
        names = [m.name_zh for m in ms]
        self.assertEqual(names, ["账号/邮箱/手机号+密码"])

    def test_sso_providers_grouped(self):
        states = [state(1, fields=["phone", "password"],
                        methods=["sso", "wechat", "qq"])]
        ms = aggregate_methods(states, flow_type="direct_password")
        sso = by_name(ms, "第三方（QQ、微信）")
        self.assertIsNotNone(sso)
        self.assertEqual(sso.status, "confirmed")

    def test_hard_gate_marks_blocked(self):
        states = [state(1, fields=["phone", "password"],
                        blockers=["captcha"])]
        ms = aggregate_methods(states)
        self.assertEqual(by_name(ms, "手机号+密码").status, "blocked")

    def test_soft_gate_not_blocking(self):
        states = [state(1, fields=["phone", "code"], blockers=["sms_code"])]
        ms = aggregate_methods(states)
        self.assertEqual(by_name(ms, "手机号+验证码").status, "confirmed")

    def test_primary_alignment_clears_gate(self):
        # flow_type 已到达口令步骤，即使页面有滑块，主方法仍 confirmed
        states = [state(1, fields=["phone", "password"], blockers=["slide"])]
        ms = aggregate_methods(states, flow_type="direct_password")
        pwd = by_name(ms, "手机号+密码")
        self.assertEqual(pwd.status, "confirmed")
        self.assertEqual(pwd.blockers, [])

    def test_identifier_alone_not_a_method(self):
        states = [state(1, fields=["phone"])]
        ms = aggregate_methods(states)
        self.assertEqual(len(ms), 0)

    def test_qr_and_auto_signup(self):
        states = [state(1, fields=["phone", "code"],
                        methods=["qr", "auto_signup"])]
        ms = aggregate_methods(states)
        self.assertEqual(by_name(ms, "扫码").status, "confirmed")
        self.assertEqual(by_name(ms, "登录即注册").status, "observed")

    def test_borrowed_identifier_for_password_step(self):
        # 先手机号，后密码（第二步无标识符）→ 借用 → 手机号+密码
        states = [
            state(1, fields=["phone"], blockers=["sms_code"]),
            state(2, fields=["password"]),
        ]
        ms = aggregate_methods(states, flow_type="direct_password")
        self.assertIsNotNone(by_name(ms, "手机号+密码"))


if __name__ == "__main__":
    unittest.main()
