"""跨 Shadow DOM、iframe 与 SPA 状态的覆盖回归。"""
import json
import os
import sys
import unittest
from unittest.mock import patch


_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from signup_flow_classifier import navigator, page_detector
from signup_flow_classifier.browser_failures import is_retryable_browser_failure
from signup_flow_classifier.flow_types import StopReason
from scripts.run_measurement import _is_retry_candidate


class _Frame:
    size = {"width": 420, "height": 520}

    def is_displayed(self):
        return True

    def get_attribute(self, name):
        return "https://identity.example/login" if name == "src" else ""


class _Switch:
    def __init__(self, driver):
        self.driver = driver

    def default_content(self):
        self.driver.context = "root"

    def frame(self, _frame):
        self.driver.context = "frame"


class _CrossFrameFieldDriver:
    """主文档有邮箱框，跨域 frame 有密码框的最小 WebDriver 桩。"""

    current_url = "https://www.example.test/"

    def __init__(self):
        self.context = "root"
        self.frame = _Frame()
        self.switch_to = _Switch(self)

    def find_elements(self, by, value):
        if value == "iframe" and self.context == "root":
            return [self.frame]
        return []

    def execute_script(self, script, *args):
        if args:  # _is_onscreen(frame)
            return True
        if "JSON.stringify(out)" in script:
            if self.context == "root":
                return json.dumps([
                    ["email", "email", "", "", "", "", "", "", True]
                ])
            return json.dumps([
                ["password", "password", "", "", "", "", "", "", True]
            ])
        return ""


class CrossFrameFieldTests(unittest.TestCase):
    def test_main_field_does_not_hide_cross_origin_password(self):
        fields = page_detector.detect_fields_all_frames(_CrossFrameFieldDriver())
        self.assertEqual(fields, ["email", "password"])

    def test_page_state_aggregates_frame_even_when_root_has_blocker(self):
        class Driver:
            current_url = "https://www.example.test/"

            def __init__(self):
                self.context = "root"
                self.switch_to = _Switch(self)

        driver = Driver()

        def switch(_driver, path):
            driver.context = "frame" if path else "root"
            return True

        def semantics(_driver, _fields):
            if driver.context == "root":
                return {
                    "blockers": ["tos"], "methods": ["email"],
                    "actions": [], "tabs": [], "style": "modal",
                }
            return {
                "blockers": ["captcha"], "methods": ["google"],
                "actions": ["external_sso"], "tabs": ["password_tab"],
                "style": "standalone_page",
            }

        with patch.object(page_detector, "detect_fields_all_frames",
                          return_value=["email", "password"]), \
             patch.object(page_detector, "_visible_frame_paths",
                          return_value=[(0,)]), \
             patch.object(page_detector, "_switch_to_frame_path",
                          side_effect=switch), \
             patch.object(page_detector, "_detect_fields_deep_current_context",
                          return_value=(["password"], False)), \
             patch.object(page_detector, "_detect_page_semantics",
                          side_effect=semantics):
            state = page_detector.detect_page_state(driver, 1)

        self.assertEqual(state.ui_type, "modal")
        self.assertEqual(state.fields, ["email", "password"])
        self.assertEqual(state.blockers, ["tos", "captcha"])
        self.assertEqual(state.methods, ["email", "google"])
        self.assertEqual(state.available_actions, ["external_sso"])
        self.assertEqual(state.tabs, ["password_tab"])
        self.assertEqual(driver.context, "root")


class SpaFingerprintTests(unittest.TestCase):
    def test_fingerprint_script_scans_shadow_and_aria_state(self):
        class Driver:
            script = ""

            def execute_script(self, script):
                self.script = script
                return "fingerprint"

        driver = Driver()
        self.assertEqual(navigator.page_fingerprint(driver), "fingerprint")
        self.assertIn("shadowRoot", driver.script)
        self.assertIn("aria-expanded", driver.script)
        self.assertIn("contentDocument", driver.script)

    def test_wait_detects_cross_origin_frame_change(self):
        class Driver:
            def __init__(self):
                self.context = "root"
                self.switch_to = _Switch(self)

        driver = Driver()

        def switch(_driver, path):
            driver.context = "frame" if path else "root"
            return True

        def fingerprint(_driver):
            return "frame-new" if driver.context == "frame" else "main-old"

        with patch.object(navigator, "_switch_to_frame_path", side_effect=switch), \
             patch.object(navigator, "page_fingerprint", side_effect=fingerprint):
            changed = navigator.wait_page_change(
                driver, "main-old", timeout=0.1,
                watched_context=((0,), "frame-old"),
            )
        self.assertTrue(changed)
        self.assertEqual(driver.context, "root")


class RetryPolicyTests(unittest.TestCase):
    def test_transient_reasons_are_retryable(self):
        for reason in (
            StopReason.BROWSER_CRASHED.value,
            StopReason.INFRASTRUCTURE_ERROR.value,
            StopReason.TIMEOUT.value,
            StopReason.NAVIGATION_ERROR.value,
            StopReason.UNRECOGNIZED_PAGE.value,
            StopReason.AUTH_ENTRY_NO_AUTH_STATE.value,
        ):
            self.assertTrue(is_retryable_browser_failure(reason), reason)

    def test_deterministic_or_human_gates_are_not_retryable(self):
        for reason in (
            StopReason.ACCESS_BLOCKED.value,
            StopReason.HUMAN_BLOCKED.value,
            StopReason.NO_SIGNUP_ENTRY.value,
            StopReason.NO_SAFE_ACTION.value,
        ):
            self.assertFalse(is_retryable_browser_failure(reason), reason)

    def test_record_retry_uses_stop_reason(self):
        self.assertTrue(_is_retry_candidate({
            "flow_type": "unknown", "stop_reason": "infrastructure_error",
        }))
        self.assertFalse(_is_retry_candidate({
            "flow_type": "unknown", "stop_reason": "access_blocked",
        }))
        self.assertTrue(_is_retry_candidate({"error": "site_timeout:90s"}))
        self.assertFalse(_is_retry_candidate({"flow_type": "direct_password"}))


if __name__ == "__main__":
    unittest.main()
