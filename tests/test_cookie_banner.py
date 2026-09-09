"""Cookie/GDPR 横幅安全处理回归测试。"""
import unittest
from unittest.mock import patch

from signup_flow_classifier.navigator import (
    _cookie_action_kind,
    safe_dismiss_cookie_banner,
)


class CookieLabelTests(unittest.TestCase):
    def test_privacy_preserving_actions_are_recognized(self):
        cases = {
            "Only necessary cookies": "necessary_only",
            "Reject all cookies": "reject_all",
            "仅使用必要 Cookie": "necessary_only",
            "全部拒绝": "reject_all",
            "Alle ablehnen": "reject_all",
            "Tout refuser": "reject_all",
            "すべて拒否": "reject_all",
            "Close": "close",
        }
        for label, expected in cases.items():
            self.assertEqual(_cookie_action_kind(label), expected, label)

    def test_accept_and_ambiguous_actions_are_never_selected(self):
        for label in (
            "Accept all", "Allow all cookies", "同意全部", "I agree",
            "Save preferences", "Manage cookies", "Continue",
        ):
            self.assertIsNone(_cookie_action_kind(label), label)


class _Control:
    def __init__(self, label, container):
        self.label = label
        self.container = container
        self.clicked = False

    def is_displayed(self):
        return True

    def is_enabled(self):
        return True

    def get_attribute(self, name):
        return self.label if name == "aria-label" else ""

    @property
    def text(self):
        return self.label

    def click(self):
        self.clicked = True
        self.container.visible = False


class _Container:
    def __init__(self, identity, text=""):
        self.identity = identity
        self._text = text
        self.visible = True
        self.controls = []

    def is_displayed(self):
        return self.visible

    @property
    def text(self):
        return self._text

    def get_attribute(self, name):
        return self.identity if name in {"id", "class"} else ""

    def find_elements(self, _by, _selector):
        return self.controls


class _Switch:
    def default_content(self):
        pass


class _Driver:
    def __init__(self, containers):
        self.containers = containers
        self.switch_to = _Switch()

    def find_elements(self, _by, _selector):
        return self.containers


class CookieBannerInteractionTests(unittest.TestCase):
    @staticmethod
    def _run(container):
        driver = _Driver([container])
        with patch("signup_flow_classifier.navigator._frame_paths",
                   return_value=[()]), patch(
                "signup_flow_classifier.navigator._switch_to_frame_path",
                return_value=True):
            return safe_dismiss_cookie_banner(driver)

    def test_reject_is_clicked_inside_cookie_context(self):
        container = _Container("cookie-consent", "We use cookies")
        reject = _Control("Reject all", container)
        accept = _Control("Accept all", container)
        container.controls = [accept, reject]

        outcome = self._run(container)

        self.assertTrue(outcome.clicked)
        self.assertTrue(outcome.changed)
        self.assertEqual(outcome.reason, "cookie_banner_reject_all")
        self.assertTrue(reject.clicked)
        self.assertFalse(accept.clicked)

    def test_close_is_not_clicked_in_generic_agreement_dialog(self):
        container = _Container("terms-dialog", "User agreement")
        close = _Control("Close", container)
        container.controls = [close]

        outcome = self._run(container)

        self.assertFalse(outcome.clicked)
        self.assertFalse(close.clicked)


if __name__ == "__main__":
    unittest.main()
