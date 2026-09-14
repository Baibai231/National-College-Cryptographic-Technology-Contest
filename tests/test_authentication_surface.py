import unittest
from unittest import mock

from application_security.authentication_surface import (
    AUTHENTICATION_SURFACE_MANIFEST,
    analyze_authentication_surface,
)
from signup_flow_classifier.page_detector import _detect_page_semantics


class AuthenticationSurfaceTests(unittest.TestCase):
    def _entries(self):
        return {
            "login": {
                "states": [{
                    "step": 1,
                    "url": "https://example.com/login",
                    "fields": ["identifier", "password"],
                    "methods": ["identifier", "password", "passkey", "sso", "github", "qr"],
                    "blockers": [],
                    "actions": ["none"],
                }],
            },
            "signup": {
                "states": [{
                    "step": 1,
                    "url": "https://example.com/signup",
                    "fields": ["phone", "code"],
                    "methods": ["phone"],
                    "blockers": ["sms_code"],
                    "actions": ["none"],
                }],
            },
        }

    def test_manifest_has_crypto_papers_and_standards(self):
        self.assertTrue(AUTHENTICATION_SURFACE_MANIFEST.crypto_elements)
        self.assertGreaterEqual(len(AUTHENTICATION_SURFACE_MANIFEST.paper_refs), 5)
        self.assertGreaterEqual(len(AUTHENTICATION_SURFACE_MANIFEST.standard_refs), 3)

    def test_surface_reports_capabilities_but_keeps_mfa_and_rba_unknown(self):
        result = analyze_authentication_surface("example.com", self._entries()).to_dict()
        claims = {claim["metric_id"]: claim for claim in result["claims"]}

        self.assertEqual(claims["auth.passkey.public_offer"]["verdict"], "pass")
        self.assertEqual(claims["auth.qr.public_offer"]["verdict"], "pass")
        self.assertEqual(claims["auth.federation.public_offer"]["verdict"], "pass")
        self.assertEqual(
            claims["auth.federation.public_offer"]["value"]["providers"],
            ["github"],
        )
        self.assertEqual(claims["auth.mfa.enforcement"]["verdict"], "unknown")
        self.assertFalse(
            claims["auth.mfa.enforcement"]["value"]["combination_enforcement_verified"])
        self.assertEqual(claims["auth.rba.enforcement"]["verdict"], "unknown")

    def test_absence_is_unknown_not_failure(self):
        result = analyze_authentication_surface("empty.example", {}).to_dict()
        claims = {claim["metric_id"]: claim for claim in result["claims"]}
        self.assertEqual(claims["auth.passkey.public_offer"]["verdict"], "unknown")
        self.assertFalse(claims["auth.passkey.public_offer"]["value"]["observed"])

    def test_page_semantics_passes_passkey_vocabulary_to_browser_scan(self):
        driver = mock.MagicMock()
        captured = {}

        def execute_script(_script, config, _fields):
            captured.update(config)
            return {"methods": ["passkey"], "actions": ["public_key_auth"]}

        driver.execute_script.side_effect = execute_script
        result = _detect_page_semantics(driver, ["identifier"])

        self.assertIn("passkey", captured)
        self.assertIn("webauthn", captured["passkey"])
        self.assertEqual(result["methods"], ["passkey"])


if __name__ == "__main__":
    unittest.main()
