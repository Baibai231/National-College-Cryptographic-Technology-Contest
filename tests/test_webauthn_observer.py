import json
import unittest

from application_security.webauthn_observer import (
    WEBAUTHN_OBSERVER_MANIFEST,
    WEBAUTHN_OBSERVER_SCRIPT,
    analyze_webauthn_observations,
    collect_webauthn_observations,
    install_webauthn_observer,
)


class FakeDriver:
    def __init__(self, observations=None):
        self.current_window_handle = "window-1"
        self.observations = observations or []
        self.commands = []

    def execute_cdp_cmd(self, command, params):
        self.commands.append((command, params))
        if command == "Runtime.evaluate" and "cryptoscopeRead" in params["expression"]:
            return {"result": {"value": self.observations}}
        return {"result": {"value": None}}


class WebAuthnObserverTests(unittest.TestCase):
    @staticmethod
    def claim(result, metric_id):
        return next(item for item in result["claims"] if item["metric_id"] == metric_id)

    def test_manifest_uses_top_conference_paper_and_final_standard(self):
        self.assertEqual(
            WEBAUTHN_OBSERVER_MANIFEST.paper_refs[0].venue,
            "IEEE Symposium on Security and Privacy",
        )
        self.assertEqual(
            WEBAUTHN_OBSERVER_MANIFEST.standard_refs[0].venue,
            "W3C Recommendation",
        )
        self.assertEqual(WEBAUTHN_OBSERVER_MANIFEST.standard_refs[0].year, 2026)
        self.assertEqual(
            WEBAUTHN_OBSERVER_MANIFEST.standard_refs[1].venue,
            "IANA COSE Registry",
        )

    def test_observer_source_wraps_but_never_initiates_credential_api(self):
        self.assertIn("Reflect.apply(original,credentials,[options])", WEBAUTHN_OBSERVER_SCRIPT)
        self.assertNotIn("navigator.credentials.create(", WEBAUTHN_OBSERVER_SCRIPT)
        self.assertNotIn("navigator.credentials.get(", WEBAUTHN_OBSERVER_SCRIPT)
        self.assertIn("crypto.subtle.sign('HMAC'", WEBAUTHN_OBSERVER_SCRIPT)
        self.assertIn("signalAllAcceptedCredentials", WEBAUTHN_OBSERVER_SCRIPT)
        self.assertIn(
            "method==='create'?selection.userVerification:p.userVerification",
            WEBAUTHN_OBSERVER_SCRIPT,
        )
        self.assertIn("observer_initiated_calls", analyze_webauthn_observations(
            "example.com", []).to_dict()["claims"][-1]["value"])

    def test_redacted_registration_configuration_is_retained(self):
        raw = {
            "ceremony": "registration",
            "challenge_bytes": 32,
            "rp_id_relation": "current_host",
            "user_verification": "required",
            "user_id_bytes": 16,
            "pub_key_algorithms": [-257, -7],
            "resident_key": "preferred",
            "require_resident_key": False,
            "authenticator_attachment": "platform",
            "attestation": "none",
            "exclude_credentials_count": 2,
            "timeout_bucket": "up_to_60s",
            "extension_names": ["credProps"],
            "challenge": "do-not-retain",
            "user_id": "alice",
            "credential_ids": ["secret-credential"],
            "rp_id": "example.com",
        }
        result = analyze_webauthn_observations("example.com", [raw]).to_dict()
        serialized = json.dumps(result)
        invocation = result["claims"][0]
        config = result["claims"][2]["value"]
        self.assertEqual(invocation["verdict"], "pass")
        self.assertEqual(config["configuration_coverage"], 1.0)
        self.assertEqual(config["invocations"][0]["pub_key_algorithms"], [-257, -7])
        self.assertNotIn("do-not-retain", serialized)
        self.assertNotIn("alice", serialized)
        self.assertNotIn("secret-credential", serialized)
        self.assertNotIn(
            "example.com", json.dumps(result["evidence"][0]["observation"])
        )

    def test_short_challenge_is_weak_but_long_challenge_is_not_pass(self):
        short = analyze_webauthn_observations("example.com", [{
            "ceremony": "authentication",
            "challenge_bytes": 8,
            "rp_id_relation": "current_host",
            "user_verification": "preferred",
            "allow_credentials_count": 0,
            "mediation": "conditional",
        }]).to_dict()["claims"][1]
        long = analyze_webauthn_observations("example.com", [{
            "ceremony": "authentication",
            "challenge_bytes": 32,
            "rp_id_relation": "current_host",
            "user_verification": "required",
            "allow_credentials_count": 1,
            "mediation": "required",
        }]).to_dict()["claims"][1]
        self.assertEqual(short["verdict"], "weak")
        self.assertEqual(long["verdict"], "unknown")
        self.assertFalse(long["value"]["randomness_verified"])
        self.assertFalse(long["value"]["server_match_verified"])

    def test_same_document_challenge_reuse_is_fail_but_zero_reuse_is_not_pass(self):
        base = {
            "ceremony": "authentication",
            "challenge_bytes": 32,
            "challenge_equality_checked": True,
            "rp_id_relation": "current_host",
            "rp_scope_labels_removed": 0,
            "user_verification": "preferred",
            "allow_credentials_count": 0,
            "mediation": "conditional",
        }
        result = analyze_webauthn_observations("example.com", [
            {**base, "challenge_reused_in_document": False},
            {**base, "challenge_reused_in_document": True},
        ]).to_dict()
        claim = self.claim(result, "auth.webauthn.challenge_length")
        self.assertEqual(claim["verdict"], "fail")
        self.assertEqual(claim["value"]["reused_in_document_count"], 1)
        self.assertEqual(claim["value"]["reuse_rate"], 0.5)

        clean = analyze_webauthn_observations(
            "example.com", [{**base, "challenge_reused_in_document": False}]
        ).to_dict()
        self.assertEqual(
            self.claim(clean, "auth.webauthn.challenge_length")["verdict"],
            "unknown",
        )

    def test_cose_registry_snapshot_flags_deprecated_symmetric_and_unknown(self):
        raw = {
            "ceremony": "registration",
            "challenge_bytes": 32,
            "rp_id_relation": "current_host",
            "rp_scope_labels_removed": 0,
            "user_verification": "required",
            "user_id_bytes": 16,
            "pub_key_algorithms": [-65535, -37, 5, 123456],
            "resident_key": "required",
            "require_resident_key": True,
        }
        result = analyze_webauthn_observations("example.com", [raw]).to_dict()
        claim = self.claim(result, "auth.webauthn.cose_algorithm_policy")
        self.assertEqual(claim["verdict"], "weak")
        self.assertEqual(claim["value"]["registry_snapshot"], "2026-08-25")
        self.assertEqual(claim["value"]["recommended"][0]["id"], -37)
        self.assertEqual(claim["value"]["deprecated"][0]["name"], "RS1")
        self.assertEqual(
            claim["value"]["symmetric_or_mac_incompatible"][0]["id"], 5)
        self.assertEqual(
            claim["value"]["unknown_or_non_signature"][0]["id"], 123456)

    def test_only_recommended_cose_signatures_passes_narrow_algorithm_claim(self):
        result = analyze_webauthn_observations("example.com", [{
            "ceremony": "registration",
            "challenge_bytes": 32,
            "rp_id_relation": "current_host",
            "user_verification": "required",
            "pub_key_algorithms": [-37, -19],
            "resident_key": "preferred",
        }]).to_dict()
        claim = self.claim(result, "auth.webauthn.cose_algorithm_policy")
        self.assertEqual(claim["verdict"], "pass")
        self.assertTrue(claim["value"]["all_offered_algorithms_recommended"])
        self.assertFalse(claim["value"]["actual_negotiated_algorithm_verified"])

    def test_parent_rp_scope_is_weak_while_related_origin_stays_unknown(self):
        base = {
            "ceremony": "authentication",
            "challenge_bytes": 32,
            "user_verification": "required",
            "allow_credentials_count": 0,
            "mediation": "required",
        }
        parent = analyze_webauthn_observations("login.example.com", [{
            **base,
            "rp_id_relation": "parent_domain_candidate",
            "rp_scope_labels_removed": 1,
        }]).to_dict()
        parent_claim = self.claim(parent, "auth.webauthn.rp_scope")
        self.assertEqual(parent_claim["verdict"], "weak")
        self.assertEqual(parent_claim["value"]["max_host_labels_removed"], 1)

        related = analyze_webauthn_observations("login.example.com", [{
            **base,
            "rp_id_relation": "different_or_related_origin",
        }]).to_dict()
        self.assertEqual(
            self.claim(related, "auth.webauthn.rp_scope")["verdict"],
            "unknown",
        )

    def test_passkey_mode_does_not_mislabel_uv_discouraged_without_factor_context(self):
        result = analyze_webauthn_observations("example.com", [{
            "ceremony": "authentication",
            "challenge_bytes": 32,
            "rp_id_relation": "current_host",
            "user_verification": "discouraged",
            "allow_credentials_count": 0,
            "mediation": "conditional",
        }]).to_dict()
        claim = self.claim(result, "auth.webauthn.passkey_profile")
        self.assertEqual(claim["verdict"], "unknown")
        self.assertEqual(claim["value"]["conditional_count"], 1)
        self.assertEqual(claim["value"]["user_verification_discouraged_count"], 1)
        self.assertFalse(claim["value"]["passwordless_or_second_factor_verified"])

    def test_resident_key_and_legacy_flag_conflict_is_weak(self):
        result = analyze_webauthn_observations("example.com", [{
            "ceremony": "registration",
            "challenge_bytes": 32,
            "rp_id_relation": "current_host",
            "user_verification": "required",
            "pub_key_algorithms": [-37],
            "resident_key": "preferred",
            "require_resident_key": True,
        }]).to_dict()
        claim = self.claim(result, "auth.webauthn.passkey_profile")
        self.assertEqual(claim["verdict"], "weak")
        self.assertEqual(
            claim["value"]["resident_key_required_legacy_flag_mismatch_count"],
            1,
        )

    def test_lifecycle_signal_is_observed_without_retaining_identifiers(self):
        raw = {
            "event_type": "lifecycle_signal",
            "lifecycle_signal": "signalAllAcceptedCredentials",
            "rp_id_relation": "current_host",
            "rp_scope_labels_removed": 0,
            "accepted_credentials_count": 3,
            "rpId": "example.com",
            "userId": "private-user",
            "allAcceptedCredentialIds": ["secret-one", "secret-two"],
        }
        result = analyze_webauthn_observations("example.com", [raw]).to_dict()
        claim = self.claim(result, "auth.webauthn.lifecycle_sync")
        self.assertEqual(claim["verdict"], "pass")
        self.assertEqual(claim["value"]["invocation_count"], 1)
        self.assertEqual(
            claim["value"]["invocations"][0]["accepted_credentials_count"], 3)
        serialized = json.dumps(result)
        self.assertNotIn("private-user", serialized)
        self.assertNotIn("secret-one", serialized)

    def test_install_is_idempotent_per_window_and_collection_uses_redacted_data(self):
        driver = FakeDriver([{
            "ceremony": "authentication",
            "challenge_bytes": 32,
            "rp_id_relation": "default_current_origin",
            "user_verification": "default",
            "allow_credentials_count": 0,
            "mediation": "conditional",
            "conditional_mediation": True,
            "timeout_bucket": "default_or_invalid",
            "extension_names": [],
        }])
        self.assertEqual(install_webauthn_observer(driver), ())
        self.assertEqual(install_webauthn_observer(driver), ())
        registrations = [command for command, _ in driver.commands
                         if command == "Page.addScriptToEvaluateOnNewDocument"]
        self.assertEqual(len(registrations), 1)
        result = collect_webauthn_observations(driver, "example.com").to_dict()
        self.assertEqual(result["claims"][0]["value"]["invocation_count"], 1)
        self.assertEqual(result["claims"][0]["value"]["observer_initiated_calls"], 0)

    def test_no_observation_stays_unknown(self):
        result = analyze_webauthn_observations("example.com", []).to_dict()
        self.assertEqual(result["claims"][0]["verdict"], "unknown")
        self.assertEqual(result["claims"][1]["verdict"], "unknown")
        self.assertEqual(result["claims"][2]["verdict"], "unknown")
        self.assertEqual(result["claims"][3]["verdict"], "unknown")
        self.assertEqual(result["claims"][4]["verdict"], "unknown")
        self.assertEqual(result["claims"][5]["verdict"], "unknown")
        self.assertEqual(result["claims"][6]["verdict"], "unknown")
        self.assertEqual(result["evidence"], [])


if __name__ == "__main__":
    unittest.main()
