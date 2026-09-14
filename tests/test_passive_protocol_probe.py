import unittest
from unittest import mock

from application_security.passive_protocol_probe import (
    PASSIVE_PROTOCOL_MANIFEST,
    collect_passive_protocol_metadata,
)


class PassiveProtocolProbeTests(unittest.TestCase):
    def test_probe_reports_only_parameter_names_and_presence(self):
        driver = mock.MagicMock()
        driver.execute_script.return_value = {
            "url_origin": "https://example.com",
            "url_path": "/login",
            "oauth_endpoints": [{
                "origin": "https://idp.example",
                "path": "/oauth/authorize",
                "same_origin": False,
                "query_parameter_names": [
                    "client_id", "code_challenge", "code_challenge_method",
                    "redirect_uri", "response_type", "state",
                ],
                "response_type": "code",
                "has_state": True,
                "has_nonce": False,
                "has_pkce_challenge": True,
                "has_pkce_method": True,
            }],
            "passkey_signals": ["passkey"],
            "mfa_indicators": ["mfa"],
            "rba_indicators": [],
            "password_autocomplete_observed": True,
            "otp_autocomplete_observed": False,
            "jose_objects": [{
                "source": "dom_url", "parameter": "request",
                "profile": "jar_request", "alg": "RS256", "typ": "JWT",
                "kid_present": True, "claim_names": ["aud", "iss"],
                "binding_claims_present": ["iss", "aud"],
                "signature_present": True, "signature_bytes": 256,
            }],
        }

        result = collect_passive_protocol_metadata(
            driver, "example.com").to_dict()
        claims = {claim["metric_id"]: claim for claim in result["claims"]}

        oauth = claims["auth.oauth.public_request_metadata"]
        self.assertEqual(oauth["verdict"], "pass")
        self.assertTrue(oauth["value"]["endpoints"][0]["state_observed"])
        self.assertTrue(oauth["value"]["endpoints"][0]["pkce_challenge_observed"])
        serialized = str(result)
        self.assertNotIn("client-secret-value", serialized)
        self.assertEqual(claims["auth.passkey.visible_control"]["verdict"], "pass")
        self.assertEqual(claims["auth.mfa.public_notice"]["verdict"], "pass")
        self.assertFalse(
            claims["auth.mfa.public_notice"]["value"]["enforcement_verified"])
        self.assertEqual(claims["auth.rba.public_notice"]["verdict"], "unknown")
        observation = result["evidence"][0]["observation"]
        self.assertEqual(observation["jose_objects"][0]["alg"], "RS256")

    def test_probe_failure_is_reported_without_fabricated_claims(self):
        driver = mock.MagicMock()
        driver.execute_script.side_effect = RuntimeError("session closed")

        result = collect_passive_protocol_metadata(
            driver, "example.com").to_dict()

        self.assertEqual(result["claims"], [])
        self.assertEqual(result["errors"], ["dom_probe_failed:RuntimeError"])

    def test_manifest_meets_core_admission_rule(self):
        self.assertTrue(PASSIVE_PROTOCOL_MANIFEST.crypto_elements)
        self.assertTrue(PASSIVE_PROTOCOL_MANIFEST.paper_refs)
        self.assertTrue(PASSIVE_PROTOCOL_MANIFEST.standard_refs)


if __name__ == "__main__":
    unittest.main()
