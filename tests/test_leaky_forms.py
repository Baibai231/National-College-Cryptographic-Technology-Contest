import unittest

from application_security.leaky_forms import (
    LEAKY_FORMS_MANIFEST,
    analyze_leaky_form_observation,
)


class LeakyFormsTests(unittest.TestCase):
    def test_manifest_operationalizes_top_paper(self):
        self.assertEqual(LEAKY_FORMS_MANIFEST.paper_refs[0].venue, "USENIX Security")
        self.assertIn("password_secret_confidentiality", LEAKY_FORMS_MANIFEST.crypto_elements)

    def test_third_party_password_attempt_is_fail_but_blocked(self):
        result = analyze_leaky_form_observation("example.test", {
            "filled_kinds": ["email", "password"], "filled_count": 2,
            "script_reads": {"email": 1, "password": 1},
            "network_attempts": [{"channel": "fetch", "destination_relation": "third_party", "kinds": ["password"], "blocked": True}],
            "submit_count": 0, "forwarded_canary_count": 0, "real_data_used": False,
        })
        claims = {claim.metric_id: claim for claim in result.claims}
        leak = claims["auth.form_secret.network_exfiltration_attempt"]
        self.assertEqual(leak.verdict.value, "fail")
        self.assertTrue(leak.value["attempts_blocked"])
        self.assertEqual(claims["auth.form_secret.safe_interaction_guard"].verdict.value, "pass")

    def test_no_attempt_is_unknown_not_pass(self):
        result = analyze_leaky_form_observation("example.test", {
            "filled_kinds": ["password"], "filled_count": 1,
            "script_reads": {"password": 1}, "network_attempts": [],
            "submit_count": 0, "forwarded_canary_count": 0, "real_data_used": False,
        })
        leak = next(c for c in result.claims if c.metric_id == "auth.form_secret.network_exfiltration_attempt")
        self.assertEqual(leak.verdict.value, "unknown")

    def test_evidence_never_contains_canary_or_payload(self):
        secret = "CS-secret-canary@example.invalid"
        result = analyze_leaky_form_observation("example.test", {
            "filled_kinds": ["email"], "filled_count": 1,
            "network_attempts": [{"channel": "xhr", "destination_relation": "third_party", "kinds": ["email"], "blocked": True, "raw": secret}],
            "submit_count": 0, "forwarded_canary_count": 0, "real_data_used": False,
        }).to_dict()
        self.assertNotIn(secret, json_string(result))
        evidence = result["evidence"][0]["observation"]
        self.assertFalse(evidence["request_payload_returned"])
        self.assertFalse(evidence["full_url_returned"])


def json_string(value):
    import json
    return json.dumps(value, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
