import unittest

from scripts.analyze_webauthn_safe_rounds import _normalize_result, compare_rounds


class WebAuthnSafeRoundTests(unittest.TestCase):
    def test_comparison_reports_exact_feature_agreement(self):
        sample_raw = {
            "navigation": {"loaded": True},
            "control": {"click_count": 0, "error": "page_initiated_before_click"},
            "virtual_authenticator": {"credentials_before": 0, "credentials_after": 0},
            "webauthn_observer": {
                "claims": [
                    {"metric_id": "auth.webauthn.api_invocation", "value": {
                        "ceremonies": ["authentication"]}},
                    {"metric_id": "auth.webauthn.request_configuration", "value": {
                        "invocations": [{
                            "challenge_bytes": 32,
                            "rp_id_relation": "current_host",
                            "user_verification": "required",
                            "allow_credentials_count": 0,
                            "mediation": "conditional",
                        }]}}
                ]
            },
            "safe_interaction": {
                "claims": [
                    {"metric_id": "auth.webauthn.safe_interaction_guard", "verdict": "pass"},
                    {"metric_id": "auth.webauthn.pre_click_authentication", "verdict": "pass"},
                ]
            },
        }
        sample = _normalize_result(sample_raw)
        result = compare_rounds(sample, sample)
        self.assertEqual(result["configuration_agreement"], 1.0)
        self.assertEqual(result["matched_features"], result["comparable_features"])
        self.assertNotIn("challenge_bytes", result)


if __name__ == "__main__":
    unittest.main()
