import json
import unittest
from pathlib import Path
from unittest import mock

import main


class MainFallbackTests(unittest.TestCase):
    def test_policy_is_usable_rejects_incomplete_measurements(self):
        self.assertFalse(main._policy_is_usable({}))
        self.assertFalse(main._policy_is_usable(None))
        self.assertFalse(
            main._policy_is_usable(
                {
                    "length": [0, 0],
                    "restrictive": {
                        "r_no_a_sps": False,
                        "r_dig_min": 0,
                    },
                    "permissive": {
                        "permitted_characters": {},
                        "permitted_sequences": {},
                    },
                }
            )
        )
        self.assertFalse(main._policy_is_usable({"_suspicious_login_form": True}))
        self.assertFalse(main._policy_is_usable({"_access_blocked": True}))
        self.assertFalse(main._policy_is_usable({"_inconclusive": True}))
        self.assertFalse(main._policy_is_usable({"_browser_dead": True, "length": [0, 0]}))

    def test_policy_is_usable_keeps_measured_policies(self):
        self.assertTrue(
            main._policy_is_usable(
                {
                    "length": [8, 32],
                    "restrictive": {"r_dig_min": 1, "r_no_a_sps": False},
                    "permissive": {"permitted_characters": {"space": True}},
                }
            )
        )
        self.assertTrue(
            main._policy_is_usable({"_browser_dead": True, "length": [8, 32]})
        )

    def test_full_form_requires_switch_and_exact_hostname_allowlist(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertFalse(main._full_form_authorized("https://example.com"))
        with mock.patch.dict(
            "os.environ",
            {
                "PASSWORD_POLICY_ALLOW_FULL_FORM": "1",
                "PASSWORD_POLICY_FULL_FORM_ALLOWLIST": "safe.example,example.com.evil",
            },
            clear=True,
        ):
            self.assertTrue(main._full_form_authorized("https://safe.example/signup"))
            self.assertFalse(main._full_form_authorized("https://www.safe.example/signup"))
            self.assertFalse(main._full_form_authorized("https://example.com/signup"))

    def test_fallback_to_classification_restores_classification_result(self):
        classification = {
            "policy": {
                "schema_version": "1.0",
                "authentication": {"observed_methods": ["password"]},
            }
        }
        result = {"method_used": "inline", "policy": {}, "error": "boom"}

        returned = main._fallback_to_classification(
            result,
            classification,
            "回退说明",
        )

        self.assertIs(returned, result)
        self.assertEqual(result["method_used"], "classified_only")
        self.assertIsNone(result["error"])
        self.assertEqual(result["policy"], classification["policy"])
        self.assertEqual(result["note"], "回退说明")

    def test_save_result_preserves_classification_evidence(self):
        result = {
            "method_used": "classified_only",
            "flow_type": "direct_password",
            "class_letter": "A",
            "primary_method": "password",
            "confidence": "high",
            "stop_reason": "password_step_reached",
            "ui_type": "standalone_page",
            "methods": [],
            "error": None,
            "policy": {"schema_version": "1.0"},
            "classification_policy": {"schema_version": "1.0"},
            "states": [{"step": 1, "fields": ["password"]}],
            "evidence": ["step=1;fields=password"],
            "final_url": "https://example.com/signup",
            "note": "分类结果",
        }

        with mock.patch("main._PROJECT_ROOT", Path(main._PROJECT_ROOT).parent / "__tmp_fallback_test__"):
            output = main.save_result("https://91.com", result)
            try:
                with open(output, encoding="utf-8") as handle:
                    saved = json.load(handle)
                self.assertEqual(saved["method_used"], "classified_only")
                self.assertEqual(saved["classification_policy"], {"schema_version": "1.0"})
                self.assertEqual(saved["states"], result["states"])
                self.assertEqual(saved["evidence"], result["evidence"])
                self.assertEqual(saved["final_url"], result["final_url"])
                self.assertEqual(saved["ui_type"], "standalone_page")
                self.assertEqual(saved["note"], "分类结果")
            finally:
                import shutil
                shutil.rmtree(Path(main._PROJECT_ROOT).parent / "__tmp_fallback_test__", ignore_errors=True)

    def test_test_single_site_falls_back_when_inline_policy_is_unusable(self):
        classification = {
            "flow_type": "direct_password",
            "confidence": "high",
            "stop_reason": "password_step_reached",
            "primary_method": "password",
            "ui_type": "standalone_page",
            "methods": [],
            "states": [{"step": 1, "fields": ["password"]}],
            "evidence": ["step=1;fields=password"],
            "final_url": "https://example.com/signup",
            "policy": {"schema_version": "1.0", "authentication": {"password_status": "observed"}},
            "signup_password_reached": True,
            "password_field": None,
            "should_proceed": True,
        }

        driver = mock.MagicMock()
        driver.current_url = "https://example.com/signup"
        discovery = mock.MagicMock()
        discovery.navigate_to_signup.return_value = "https://example.com/signup"
        discovery._entry_clicked = False
        discovery.ensure_form_visible.return_value = True
        discovery.find_signup_fields.return_value = ("//input[@type='email']", "//input[@type='password']")
        engine = mock.MagicMock()
        engine.classify.return_value = classification
        engine.get_current_password_field_xpath.return_value = "//input[@type='password']"
        tester = mock.MagicMock()
        tester.discover_form_fields.return_value = True
        tester.run_password_policy_test.return_value = {
            "length": [0, 0],
            "restrictive": {"r_no_a_sps": False, "r_dig_min": 0},
            "permissive": {"permitted_characters": {}, "permitted_sequences": {}},
        }

        with mock.patch.object(main, "_get_new_driver", return_value=driver), \
                mock.patch.object(main, "LoginLinkDiscovery", return_value=discovery), \
                mock.patch.object(main, "SignupFlowClassifierEngine", return_value=engine), \
                mock.patch.object(main, "SitePasswordPolicyTester", return_value=tester):
            result = main.test_single_site("https://example.com", "inline")

        self.assertEqual(result["method_used"], "classified_only")
        self.assertIsNone(result["error"])
        self.assertEqual(result["flow_type"], "direct_password")
        self.assertEqual(result["policy"], classification["policy"])
        self.assertIn("回退输出注册流程分类结果", result["note"])

    def test_live_password_target_is_handed_off_without_reopening_form(self):
        classification = {
            "flow_type": "direct_password", "confidence": "high",
            "stop_reason": "password_step_reached", "primary_method": "password",
            "ui_type": "modal", "methods": [],
            "states": [{"step": 1, "fields": ["password"]}],
            "evidence": ["original-classification"],
            "final_url": "https://example.com/", "policy": {"schema_version": "1.0"},
            "signup_password_reached": True, "password_field": None,
            "should_proceed": True,
        }
        live_target = {"xpath": "//input[@id='live-password']", "frame_path": (2,)}
        usable_policy = {
            "length": [8, 64],
            "restrictive": {"r_dig_min": 1},
            "permissive": {"permitted_characters": {}, "permitted_sequences": {}},
        }
        driver = mock.MagicMock()
        driver.current_url = "https://example.com/"
        discovery = mock.MagicMock()
        discovery.navigate_to_signup.return_value = "https://example.com/"
        discovery._entry_clicked = True
        engine = mock.MagicMock()
        engine.classify.return_value = classification
        engine.get_current_password_field.return_value = live_target
        tester = mock.MagicMock()
        tester.discover_form_fields.return_value = True
        tester.run_password_policy_test.return_value = usable_policy

        with mock.patch.object(main, "_get_new_driver", return_value=driver), \
                mock.patch.object(main, "LoginLinkDiscovery", return_value=discovery), \
                mock.patch.object(main, "SignupFlowClassifierEngine", return_value=engine), \
                mock.patch.object(main, "SitePasswordPolicyTester", return_value=tester), \
                mock.patch.object(
                    main, "_detect_method",
                    return_value=("inline", "https://example.com/", None, live_target["xpath"]),
                ) as detect_method:
            result = main.test_single_site("https://example.com", "auto")

        self.assertEqual(result["method_used"], "inline")
        self.assertEqual(result["policy"], usable_policy)
        discovery.ensure_form_visible.assert_not_called()
        discovery.find_signup_fields.assert_not_called()
        engine.classify.assert_called_once()
        self.assertEqual(tester.password_xpath, live_target["xpath"])
        self.assertEqual(tester.password_frame_path, (2,))
        self.assertEqual(detect_method.call_args.kwargs["password_frame_path"], (2,))

    def test_relocation_does_not_replace_original_classification_evidence(self):
        original = {
            "flow_type": "direct_password", "confidence": "high",
            "stop_reason": "password_step_reached", "primary_method": "password",
            "ui_type": "modal", "methods": [{"method": "password"}],
            "states": [{"step": 1, "fields": ["password"], "tabs": ["sms_tab"]}],
            "evidence": ["original-full-view"],
            "final_url": "https://example.com/", "policy": {"schema_version": "1.0"},
            "signup_password_reached": True, "password_field": None,
            "should_proceed": True,
        }
        relocated = dict(original)
        relocated.update({
            "states": [{"step": 1, "fields": ["password"]}],
            "evidence": ["short-relocation"],
            "password_field": {"xpath": "//input[@id='relocated']", "frame_path": ()},
        })
        usable_policy = {
            "length": [8, 32], "restrictive": {"r_dig_min": 1},
            "permissive": {"permitted_characters": {}, "permitted_sequences": {}},
        }
        driver = mock.MagicMock()
        driver.current_url = "https://example.com/"
        discovery = mock.MagicMock()
        discovery.navigate_to_signup.return_value = "https://example.com/"
        discovery._entry_clicked = True
        engine = mock.MagicMock()
        engine.classify.side_effect = [original, relocated]
        engine.get_current_password_field.return_value = None
        tester = mock.MagicMock()
        tester.discover_form_fields.return_value = True
        tester.run_password_policy_test.return_value = usable_policy

        with mock.patch.object(main, "_get_new_driver", return_value=driver), \
                mock.patch.object(main, "LoginLinkDiscovery", return_value=discovery), \
                mock.patch.object(main, "SignupFlowClassifierEngine", return_value=engine), \
                mock.patch.object(main, "SitePasswordPolicyTester", return_value=tester), \
                mock.patch.object(
                    main, "_detect_method",
                    return_value=("inline", "https://example.com/", None, "//input[@id='relocated']"),
                ):
            result = main.test_single_site("https://example.com", "auto")

        self.assertEqual(result["states"], original["states"])
        self.assertEqual(result["methods"], original["methods"])
        self.assertIn("original-full-view", result["evidence"])
        self.assertIn("measurement_context_relocated", result["evidence"])
        self.assertNotIn("short-relocation", result["evidence"])
        discovery.ensure_form_visible.assert_not_called()

    def test_no_signup_fallback_unknown_becomes_classified_only(self):
        classification = {
            "flow_type": "unknown",
            "confidence": "low",
            "stop_reason": "unrecognized_page",
            "primary_method": "unknown",
            "ui_type": "unknown",
            "methods": [],
            "states": [{"step": 1, "url": "https://91.com/", "methods": [], "fields": []}],
            "evidence": ["step=1;entry=no_entry_button"],
            "final_url": "https://91.com/",
            "policy": {"schema_version": "1.0", "measurement": {"status": "unknown"}},
            "signup_password_reached": False,
            "should_proceed": False,
        }

        driver = mock.MagicMock()
        driver.current_url = "https://91.com/"
        discovery = mock.MagicMock()
        discovery.navigate_to_signup.return_value = None
        discovery._entry_clicked = False
        engine = mock.MagicMock()
        engine.classify.return_value = classification

        with mock.patch.object(main, "_get_new_driver", return_value=driver), \
                mock.patch.object(main, "LoginLinkDiscovery", return_value=discovery), \
                mock.patch.object(main, "SignupFlowClassifierEngine", return_value=engine):
            result = main.test_single_site("https://91.com", "inline")

        self.assertEqual(result["method_used"], "classified_only")
        self.assertIsNone(result["error"])
        self.assertEqual(result["flow_type"], "unknown")
        self.assertEqual(result["class_letter"], "I")
        self.assertEqual(result["policy"], classification["policy"])
        self.assertIn("不推断为无网页注册", result["note"])

    def test_no_signup_fallback_keeps_explicit_no_web_signup(self):
        classification = {
            "flow_type": "no_web_signup",
            "confidence": "high",
            "stop_reason": "no_signup_entry",
            "primary_method": "unknown",
            "ui_type": "unknown",
            "methods": [],
            "states": [],
            "evidence": ["login_page_during_signup"],
            "final_url": "https://example.com/",
            "policy": {"schema_version": "1.0"},
            "signup_password_reached": False,
            "should_proceed": False,
        }

        driver = mock.MagicMock()
        driver.current_url = "https://example.com/"
        discovery = mock.MagicMock()
        discovery.navigate_to_signup.return_value = None
        discovery._entry_clicked = False
        engine = mock.MagicMock()
        engine.classify.return_value = classification

        with mock.patch.object(main, "_get_new_driver", return_value=driver), \
                mock.patch.object(main, "LoginLinkDiscovery", return_value=discovery), \
                mock.patch.object(main, "SignupFlowClassifierEngine", return_value=engine):
            result = main.test_single_site("https://example.com", "inline")

        self.assertEqual(result["method_used"], "classified_only")
        self.assertEqual(result["flow_type"], "no_web_signup")
        self.assertEqual(result["class_letter"], "H")
        self.assertEqual(result["policy"], classification["policy"])

    def test_no_signup_fallback_classifier_error_is_not_forged_as_no_web(self):
        driver = mock.MagicMock()
        driver.current_url = "https://91.com/"
        discovery = mock.MagicMock()
        discovery.navigate_to_signup.return_value = None
        discovery._entry_clicked = False
        engine = mock.MagicMock()
        engine.classify.side_effect = RuntimeError("classifier failed")

        with mock.patch.object(main, "_get_new_driver", return_value=driver), \
                mock.patch.object(main, "LoginLinkDiscovery", return_value=discovery), \
                mock.patch.object(main, "SignupFlowClassifierEngine", return_value=engine):
            result = main.test_single_site("https://91.com", "inline")

        self.assertNotEqual(result["flow_type"], "no_web_signup")
        self.assertEqual(result["flow_type"], "unknown")
        self.assertEqual(result["class_letter"], "I")
        self.assertIsNotNone(result["error"])


if __name__ == "__main__":
    unittest.main()
