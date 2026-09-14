import unittest
from unittest.mock import MagicMock, patch

from utils.login_link_discovery import LoginLinkDiscovery
from signup_flow_classifier.classifier_engine import _tab_belongs_to_entry


class EntryNavigationSplitTests(unittest.TestCase):
    def test_login_full_view_never_explores_registration_tabs(self):
        self.assertFalse(_tab_belongs_to_entry("register_tab", "login"))
        self.assertFalse(_tab_belongs_to_entry("password_signup_tab", "login"))
        self.assertTrue(_tab_belongs_to_entry("sms_tab", "login"))
        self.assertTrue(_tab_belongs_to_entry("password_tab", "login"))
        self.assertTrue(_tab_belongs_to_entry("register_tab", "signup"))

    def test_navigate_to_login_never_calls_signup_discovery(self):
        driver = MagicMock()
        driver.current_url = "https://example.com/"
        discovery = LoginLinkDiscovery(driver)
        discovery.inject = MagicMock()
        discovery._wait_for_page_ready = MagicMock()
        discovery.navigate_to_signup = MagicMock(
            side_effect=AssertionError("login must not use signup discovery"))

        result = discovery.navigate_to_login("https://example.com")

        driver.get.assert_called_once_with("https://example.com")
        discovery.navigate_to_signup.assert_not_called()
        self.assertEqual(result, "https://example.com/")
        self.assertFalse(discovery._entry_clicked)

    def test_login_renderer_timeout_keeps_original_url_not_blank_browser_url(self):
        driver = MagicMock()
        driver.get.side_effect = TimeoutError("renderer timeout")
        driver.current_url = ""
        discovery = LoginLinkDiscovery(driver)
        discovery.inject = MagicMock()

        result = discovery.navigate_to_login("https://example.com/login")

        self.assertEqual(result, "https://example.com/login")

    @patch("webapp.app._validated_classify_url")
    @patch("signup_flow_classifier.classifier_engine.SignupFlowClassifierEngine")
    @patch("utils.login_link_discovery.LoginLinkDiscovery")
    @patch("utils.util_test_password._get_new_driver")
    def test_web_login_uses_login_navigation(
        self, get_driver, discovery_cls, engine_cls, validate_url
    ):
        from webapp.app import _run_live_classification

        driver = MagicMock()
        get_driver.return_value = driver
        discovery = discovery_cls.return_value
        discovery.navigate_to_login.return_value = "https://example.com/"
        discovery.navigate_to_signup.side_effect = AssertionError(
            "login must not use signup discovery")
        engine_cls.return_value.classify.return_value = {
            "flow_type": "direct_password",
            "states": [],
        }
        validate_url.return_value = ("https://example.com/", "example.com")

        response = _run_live_classification("https://example.com", "login")

        discovery.navigate_to_login.assert_called_once_with("https://example.com")
        discovery.navigate_to_signup.assert_not_called()
        engine_cls.return_value.classify.assert_called_once_with(
            "https://example.com/",
            entry_kind="login",
            entry_already_clicked=False,
        )
        self.assertEqual(response["entry_kind"], "login")
        self.assertIn("auth_graph", response)

    @patch("main.test_single_site")
    @patch("scripts.run_measurement.SignupFlowClassifierEngine")
    @patch("scripts.run_measurement.LoginLinkDiscovery")
    @patch("scripts.run_measurement._get_new_driver")
    def test_policy_batch_does_not_label_signup_result_as_login(
        self, get_driver, discovery_cls, engine_cls, test_single_site
    ):
        from scripts.run_measurement import classify_one

        driver = MagicMock()
        get_driver.return_value = driver
        discovery = discovery_cls.return_value
        discovery.navigate_to_login.return_value = "https://example.com/"
        engine_cls.return_value.classify.return_value = {
            "flow_type": "direct_password",
            "confidence": "high",
            "states": [],
        }

        result = classify_one(
            "https://example.com", "login", measure_policy=True
        )

        test_single_site.assert_not_called()
        discovery.navigate_to_login.assert_called_once_with(
            "https://example.com")
        engine_cls.return_value.classify.assert_called_once_with(
            "https://example.com/",
            entry_kind="login",
            entry_already_clicked=False,
        )
        self.assertEqual(result["entry_kind"], "login")


if __name__ == "__main__":
    unittest.main()
