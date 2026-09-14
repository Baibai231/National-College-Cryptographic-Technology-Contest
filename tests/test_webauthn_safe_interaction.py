import unittest

from application_security.webauthn_safe_interaction import (
    BLOCK_PUBLIC_KEY_CREATE_SCRIPT,
    WEBAUTHN_SAFE_INTERACTION_MANIFEST,
    add_empty_virtual_authenticator,
    analyze_safe_interaction,
    click_exact_passkey_control,
    install_registration_blocker,
    remove_virtual_authenticator,
)


class FakeElement:
    def __init__(self, text, *, displayed=True, enabled=True, tag_name="button"):
        self.text = text
        self.displayed = displayed
        self.enabled = enabled
        self.tag_name = tag_name
        self.clicked = 0

    def is_displayed(self):
        return self.displayed

    def is_enabled(self):
        return self.enabled

    def get_attribute(self, name):
        if name in {"innerText", "textContent"}:
            return self.text
        return "" if name in {"aria-label", "value"} else None

    def click(self):
        self.clicked += 1


class FakeDriver:
    def __init__(self, elements=()):
        self.current_url = "https://github.com/login"
        self.elements = list(elements)
        self.commands = []
        self.credentials = []

    def execute_cdp_cmd(self, command, params):
        self.commands.append((command, params))
        if command == "WebAuthn.addVirtualAuthenticator":
            return {"authenticatorId": "virtual-secret-handle"}
        if command == "WebAuthn.getCredentials":
            return {"credentials": list(self.credentials)}
        return {"result": {"value": None}}

    def find_elements(self, by, selector):
        self.commands.append(("find", {"by": by, "selector": selector}))
        return self.elements


def _webauthn_result(ceremonies):
    return {
        "claims": [{
            "metric_id": "auth.webauthn.request_configuration",
            "value": {"invocations": [
                {"ceremony": ceremony} for ceremony in ceremonies
            ]},
        }],
    }


class WebAuthnSafeInteractionTests(unittest.TestCase):
    def test_manifest_uses_top_papers_and_safe_interaction_mode(self):
        self.assertEqual(
            {reference.venue for reference in WEBAUTHN_SAFE_INTERACTION_MANIFEST.paper_refs},
            {"USENIX Security", "IEEE Symposium on Security and Privacy"},
        )
        self.assertEqual(
            WEBAUTHN_SAFE_INTERACTION_MANIFEST.safe_modes[0].value,
            "safe_interaction",
        )

    def test_registration_blocker_rejects_public_key_create_without_calling_it(self):
        self.assertIn("Public-key registration disabled", BLOCK_PUBLIC_KEY_CREATE_SCRIPT)
        self.assertIn("NotAllowedError", BLOCK_PUBLIC_KEY_CREATE_SCRIPT)
        self.assertNotIn("navigator.credentials.create(", BLOCK_PUBLIC_KEY_CREATE_SCRIPT)
        driver = FakeDriver()
        self.assertEqual(install_registration_blocker(driver), ())
        self.assertEqual(driver.commands[0][0], "Page.addScriptToEvaluateOnNewDocument")

    def test_virtual_authenticator_is_ctap21_empty_and_material_never_returned(self):
        driver = FakeDriver()
        authenticator_id, count, errors = add_empty_virtual_authenticator(driver)
        self.assertEqual(authenticator_id, "virtual-secret-handle")
        self.assertEqual(count, 0)
        self.assertEqual(errors, ())
        options = next(
            params["options"] for command, params in driver.commands
            if command == "WebAuthn.addVirtualAuthenticator"
        )
        self.assertEqual(options["protocol"], "ctap2")
        self.assertEqual(options["ctap2Version"], "ctap2_1")
        self.assertTrue(options["hasResidentKey"])
        self.assertTrue(options["hasUserVerification"])

    def test_exact_unique_control_is_clicked_once_and_label_not_returned(self):
        target = FakeElement("  Sign in with a PASSKEY  ")
        driver = FakeDriver([target, FakeElement("Sign in")])
        result = click_exact_passkey_control(
            driver,
            allowed_host="github.com",
            expected_labels=["Sign in with a passkey"],
        )
        self.assertTrue(result["clicked"])
        self.assertEqual(result["click_count"], 1)
        self.assertEqual(target.clicked, 1)
        self.assertNotIn("Sign in with", str(result))

    def test_ambiguous_or_wrong_host_fails_closed(self):
        driver = FakeDriver([
            FakeElement("Sign in with a passkey"),
            FakeElement("Sign in with a passkey"),
        ])
        result = click_exact_passkey_control(
            driver, allowed_host="github.com",
            expected_labels=["Sign in with a passkey"])
        self.assertFalse(result["clicked"])
        self.assertEqual(result["error"], "exact_control_not_unique")
        driver.current_url = "https://evil.example/login"
        result = click_exact_passkey_control(
            driver, allowed_host="github.com",
            expected_labels=["Sign in with a passkey"])
        self.assertFalse(result["clicked"])
        self.assertEqual(result["error"], "host_guard_failed")

    def test_trigger_and_guard_pass_only_for_authentication_with_empty_device(self):
        result = analyze_safe_interaction(
            "github.com",
            control={"clicked": True, "click_count": 1},
            webauthn_result=_webauthn_result(["authentication"]),
            credentials_before=0,
            credentials_after=0,
        ).to_dict()
        claims = {item["metric_id"]: item for item in result["claims"]}
        self.assertEqual(
            claims["auth.webauthn.explicit_control_trigger"]["verdict"], "pass")
        self.assertEqual(
            claims["auth.webauthn.safe_interaction_guard"]["verdict"], "pass")
        self.assertEqual(
            claims["auth.webauthn.explicit_control_trigger"]["value"]["trigger_yield"],
            1.0,
        )

    def test_unexpected_registration_is_weak_and_nonempty_device_fails_guard(self):
        result = analyze_safe_interaction(
            "github.com",
            control={"clicked": True, "click_count": 1},
            webauthn_result=_webauthn_result(["registration"]),
            credentials_before=0,
            credentials_after=1,
        ).to_dict()
        claims = {item["metric_id"]: item for item in result["claims"]}
        self.assertEqual(
            claims["auth.webauthn.explicit_control_trigger"]["verdict"], "weak")
        self.assertEqual(
            claims["auth.webauthn.safe_interaction_guard"]["verdict"], "fail")

    def test_pre_click_authentication_is_separate_from_click_yield(self):
        result = analyze_safe_interaction(
            "github.com",
            control={"clicked": False, "click_count": 0},
            webauthn_result=_webauthn_result(["authentication"]),
            credentials_before=0,
            credentials_after=0,
            pre_click_authentication_count=1,
        ).to_dict()
        claims = {item["metric_id"]: item for item in result["claims"]}
        self.assertEqual(
            claims["auth.webauthn.pre_click_authentication"]["verdict"], "pass")
        self.assertEqual(
            claims["auth.webauthn.explicit_control_trigger"]["verdict"], "unknown")
        self.assertIsNone(
            claims["auth.webauthn.explicit_control_trigger"]["value"]["trigger_yield"])

    def test_cleanup_removes_authenticator_then_disables_domain(self):
        driver = FakeDriver()
        self.assertEqual(remove_virtual_authenticator(driver, "auth-1"), ())
        self.assertEqual(
            [command for command, _params in driver.commands],
            ["WebAuthn.removeVirtualAuthenticator", "WebAuthn.disable"],
        )


if __name__ == "__main__":
    unittest.main()
