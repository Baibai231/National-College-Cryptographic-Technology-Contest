"""Tests for passive security observations and their privacy boundary."""

import json
import unittest

from scripts.site_data_store import measurement_record
from scripts.build_site_database import build_sites
from security_observers import collect_security_observations
from security_observers.scoring import (
    attach_security_assessment, build_security_assessment,
)
from security_observers.jwt import analyze_jwt_metadata
from security_observers.mfa import analyze_mfa_evidence
from security_observers.oauth import analyze_oauth_urls
from security_observers.session import analyze_cookie_posture
from security_observers.transport import analyze_network_security
from security_observers.webauthn import analyze_webauthn_signals
from signup_flow_classifier.classifier_engine import SignupFlowClassifierEngine
from signup_flow_classifier.flow_types import FlowResult, PageState
from utils.util_test_password import _enable_passive_network_logging


class OAuthObserverTests(unittest.TestCase):
    def test_oauth_parameters_are_summarized_without_values(self):
        secret_state = "state-value-that-must-not-be-stored"
        client_id = "private-client-identifier"
        report = analyze_oauth_urls([
            "https://id.example/oauth2/authorize?client_id={}&response_type=code"
            "&state={}&code_challenge=challenge-secret&code_challenge_method=S256"
            "&redirect_uri=https%3A%2F%2Fapp.example%2Fcallback&scope=openid".format(
                client_id, secret_state),
        ])
        self.assertEqual(report["status"], "observed")
        self.assertTrue(report["state"]["non_empty_observed"])
        self.assertEqual(report["pkce"]["methods"], ["S256"])
        self.assertTrue(report["oidc"]["openid_scope_observed"])
        serialized = json.dumps(report)
        self.assertNotIn(secret_state, serialized)
        self.assertNotIn(client_id, serialized)
        self.assertNotIn("challenge-secret", serialized)

    def test_unrelated_links_are_not_oauth(self):
        report = analyze_oauth_urls(["https://example.com/articles/oauth-explained"])
        self.assertEqual(report["status"], "not_observed")


class JwtObserverTests(unittest.TestCase):
    def test_jwt_report_contains_metadata_not_token_values(self):
        report = analyze_jwt_metadata([{
            "source": "local_storage",
            "algorithm": "HS256",
            "expiration_claim": True,
            "issuer_claim": True,
            "audience_claim": False,
            "signature_segment_present": True,
            "token": "must-never-be-copied",
        }])
        self.assertEqual(report["algorithms"], ["HS256"])
        self.assertTrue(report["raw_tokens_stored"] is False)
        self.assertNotIn("must-never-be-copied", json.dumps(report))

    def test_unsigned_jwt_is_flagged_without_claiming_signature_verification(self):
        report = analyze_jwt_metadata([{
            "source": "session_storage", "algorithm": "none",
            "expiration_claim": False, "signature_segment_present": False,
        }])
        self.assertIn("unsigned_algorithm_observed", report["findings"])
        self.assertFalse(report["signature_segment_present_for_all"])


class CapabilityObserverTests(unittest.TestCase):
    def test_browser_webauthn_api_alone_is_not_site_capability(self):
        report = analyze_webauthn_signals({"public_key_credential_api": True})
        self.assertEqual(report["status"], "not_observed")
        self.assertFalse(report["site_capability_observed"])

    def test_parallel_auth_methods_are_not_reported_as_enforced_mfa(self):
        states = [{
            "fields": ["password", "phone", "code"],
            "methods": ["password", "sms"],
            "blockers": ["sms_code"],
        }]
        report = analyze_mfa_evidence(states, [], {})
        self.assertTrue(report["multiple_authentication_methods_observed"])
        self.assertEqual(report["mfa_enforcement"], "not_determined")
        self.assertFalse(report["completed_multi_factor_sequence"])

    def test_cookie_report_stores_only_aggregate_attributes(self):
        secret = "cookie-value-secret"
        report = analyze_cookie_posture([{
            "name": "sessionid", "value": secret, "secure": False,
            "httpOnly": True, "sameSite": "Lax",
        }], "https://example.com/login")
        self.assertEqual(report["session_like_cookies"]["count"], 1)
        self.assertIn("session_like_cookie_without_secure", report["findings"])
        serialized = json.dumps(report)
        self.assertNotIn(secret, serialized)
        self.assertNotIn("sessionid", serialized)


def _performance_event(method, params):
    return {"message": json.dumps({
        "message": {"method": method, "params": params},
    })}


class NetworkSecurityObserverTests(unittest.TestCase):
    def _events(self):
        initial = "http://app.example/login?secret=initial-url-token"
        final = "https://app.example/login?secret=final-url-token"
        return [
            _performance_event("Network.requestWillBeSent", {
                "type": "Document", "loaderId": "loader-1",
                "request": {"url": initial},
            }),
            _performance_event("Network.requestWillBeSent", {
                "type": "Document", "loaderId": "loader-1",
                "request": {"url": final},
                "redirectResponse": {"url": initial, "status": 301},
            }),
            _performance_event("Network.responseReceived", {
                "type": "Document", "loaderId": "loader-1",
                "response": {
                    "url": final, "status": 200, "protocol": "h2",
                    "securityState": "secure",
                    "headers": {
                        "Strict-Transport-Security":
                            "max-age=31536000; includeSubDomains; preload",
                        "Content-Security-Policy":
                            "default-src 'self'; frame-ancestors 'none'; "
                            "object-src 'none'; base-uri 'self'; "
                            "script-src 'nonce-super-secret-value'",
                        "X-Content-Type-Options": "nosniff",
                        "X-Frame-Options": "DENY",
                        "Referrer-Policy": "strict-origin-when-cross-origin",
                        "Permissions-Policy": "camera=(), microphone=()",
                        "Cross-Origin-Opener-Policy": "same-origin",
                        "Cache-Control": "private, no-store",
                        "Server": "secret-server-version",
                    },
                    "securityDetails": {
                        "protocol": "TLS 1.3", "cipher": "AES_256_GCM",
                        "keyExchangeGroup": "X25519",
                        # SAN must take precedence over the legacy subject CN.
                        "subjectName": "legacy-wrong.example",
                        "sanList": ["app.example", "secret-san.example"],
                        "issuer": "secret-certificate-issuer",
                        "validFrom": 1704067200,
                        "validTo": 1893456000,
                        "signedCertificateTimestampList": [{}, {}],
                    },
                },
            }),
        ]

    def test_existing_navigation_yields_tls_redirect_and_header_posture(self):
        report = analyze_network_security(
            self._events(), "https://app.example/login?secret=final-url-token")
        transport = report["transport_security"]
        headers = report["http_security_headers"]
        self.assertEqual(transport["tls"]["version"], "TLS 1.3")
        self.assertTrue(transport["tls"]["certificate_name_matches_host"])
        self.assertTrue(transport["redirects"]["http_to_https_observed"])
        self.assertEqual(transport["redirects"]["status_codes"], [301])
        self.assertTrue(headers["strict_transport_security"]["include_subdomains"])
        self.assertTrue(headers["content_security_policy"]["nonce_or_hash_source_observed"])
        self.assertTrue(headers["x_content_type_options_nosniff"])
        self.assertEqual(headers["anti_framing"]["x_frame_options"], "DENY")
        self.assertTrue(headers["cache_control"]["no_store"])

    def test_raw_network_values_are_not_returned(self):
        report = analyze_network_security(
            self._events(), "https://app.example/login?secret=final-url-token")
        serialized = json.dumps(report)
        for secret in (
                "initial-url-token", "final-url-token", "super-secret-value",
                "secret-server-version", "secret-certificate-issuer",
                "secret-san.example"):
            self.assertNotIn(secret, serialized)
        self.assertFalse(report["transport_security"]["raw_urls_stored"])
        self.assertFalse(report["http_security_headers"]["raw_header_values_stored"])

    def test_missing_header_event_is_unknown_not_a_missing_header_finding(self):
        report = analyze_network_security(
            [], "https://app.example/login",
            {"next_hop_protocol": "h2", "redirect_count": 1})
        self.assertEqual(report["transport_security"]["status"], "observed")
        self.assertEqual(report["transport_security"]["confidence"], "medium")
        self.assertEqual(report["http_security_headers"]["status"], "not_observed")
        self.assertEqual(report["http_security_headers"]["findings"], [])

    def test_unrelated_document_is_not_attributed_to_current_site(self):
        events = [_performance_event("Network.responseReceived", {
            "type": "Document", "loaderId": "foreign",
            "response": {"url": "https://idp.example/authorize",
                         "headers": {"Server": "foreign"}},
        })]
        report = analyze_network_security(events, "https://app.example/login")
        self.assertFalse(
            report["http_security_headers"]["response_metadata_available"])

    def test_actual_browser_options_enable_passive_network_metadata(self):
        class FakeOptions:
            def __init__(self):
                self.capabilities = {}
                self.experimental = {}

            def set_capability(self, name, value):
                self.capabilities[name] = value

            def add_experimental_option(self, name, value):
                self.experimental[name] = value

        options = FakeOptions()
        _enable_passive_network_logging(options)
        self.assertEqual(
            options.capabilities["goog:loggingPrefs"], {"performance": "ALL"})
        self.assertEqual(
            options.experimental["perfLoggingPrefs"], {"enableNetwork": True})


class SecurityAssessmentTests(unittest.TestCase):
    @staticmethod
    def _secure_transport():
        return {
            "status": "observed", "https_page_observed": True,
            "final_page_scheme": "https", "browser_security_state": "secure",
            "tls": {
                "metadata_observed": True, "version": "TLS 1.3",
                "certificate_expired": False,
                "certificate_expires_within_30_days": False,
                "certificate_name_matches_host": True,
            },
            "findings": [],
        }

    def test_unknown_dimensions_do_not_reduce_known_evidence_score(self):
        assessment = build_security_assessment({
            "transport_security": self._secure_transport(),
        })
        self.assertEqual(assessment["dimensions"]["transport_security"]["score"], 100)
        self.assertEqual(assessment["overall"]["score"], 100)
        self.assertTrue(assessment["overall"]["unknown_not_penalized"])
        self.assertIsNone(assessment["overall"]["grade"])
        self.assertEqual(assessment["overall"]["status"], "limited_evidence")
        self.assertIn("password_policy", assessment["unknown_dimensions"])

    def test_sixty_five_percent_coverage_still_withholds_grade(self):
        policy = {
            "length": [15, 128], "restrictive": {},
            "permissive": {"breached_password": {"p_br": True}},
        }
        headers = {
            "status": "observed",
            "strict_transport_security": {"present": True,
                                           "max_age_seconds": 31536000},
            "content_security_policy": {"enforced_present": True},
            "x_content_type_options_nosniff": True,
            "anti_framing": {"x_frame_options": "DENY",
                             "csp_frame_ancestors": False},
            "referrer_policy": "strict-origin", "findings": [],
        }
        assessment = build_security_assessment({
            "transport_security": self._secure_transport(),
            "http_security_headers": headers,
        }, policy, password_policy_measured=True)
        self.assertEqual(assessment["overall"]["coverage_percent"], 65)
        self.assertEqual(
            assessment["overall"]["grade_minimum_coverage_percent"], 70)
        self.assertIsNone(assessment["overall"]["grade"])
        self.assertEqual(assessment["overall"]["status"], "limited_evidence")

    def test_observed_missing_headers_are_scored_but_unavailable_headers_are_unknown(self):
        missing = {
            "status": "observed", "strict_transport_security": {"present": False},
            "content_security_policy": {"enforced_present": False},
            "x_content_type_options_nosniff": False,
            "anti_framing": {"x_frame_options": "not_observed",
                             "csp_frame_ancestors": False},
            "referrer_policy": "not_observed",
            "findings": ["hsts_not_observed"],
        }
        observed = build_security_assessment({
            "transport_security": self._secure_transport(),
            "http_security_headers": missing,
        })
        unavailable = build_security_assessment({
            "transport_security": self._secure_transport(),
            "http_security_headers": {"status": "not_observed", "findings": []},
        })
        self.assertEqual(
            observed["dimensions"]["http_security_headers"]["score"], 0)
        self.assertEqual(
            unavailable["dimensions"]["http_security_headers"]["status"], "unknown")
        self.assertGreater(
            observed["overall"]["coverage_percent"],
            unavailable["overall"]["coverage_percent"])

    def test_measured_password_policy_can_refresh_existing_bundle(self):
        bundle = {"analyzers": {}}
        policy = {
            "length": [15, 128], "restrictive": {},
            "permissive": {"breached_password": {"p_br": True}},
        }
        attach_security_assessment(
            bundle, policy, password_policy_measured=True)
        dimension = bundle["assessment"]["dimensions"]["password_policy"]
        self.assertEqual(dimension["coverage_percent"], 100)
        self.assertEqual(dimension["score"], 100)
        self.assertIn(
            "breached_password_blocking_observed", dimension["positive_evidence"])

    def test_confirmed_severe_transport_finding_sets_observed_risk(self):
        assessment = build_security_assessment({
            "transport_security": {
                "status": "observed", "final_page_scheme": "http",
                "https_page_observed": False, "browser_security_state": "insecure",
                "tls": {}, "findings": ["plaintext_final_page_observed"],
            },
        })
        self.assertEqual(assessment["overall"]["observed_risk_level"], "high")

    def test_result_refresh_adds_only_usable_measured_password_policy(self):
        from main import _refresh_result_security_assessment

        policy = {
            "length": [12, 64], "restrictive": {},
            "permissive": {"breached_password": {"p_br": True}},
        }
        measured = {
            "method_used": "inline", "policy": policy,
            "security_observations": {"analyzers": {}},
        }
        _refresh_result_security_assessment(measured)
        self.assertEqual(
            measured["security_observations"]["assessment"]["dimensions"]
            ["password_policy"]["status"], "assessed")

        classified_only = {
            "method_used": "classified_only", "policy": policy,
            "security_observations": {"analyzers": {}},
        }
        _refresh_result_security_assessment(classified_only)
        self.assertEqual(
            classified_only["security_observations"]["assessment"]["dimensions"]
            ["password_policy"]["status"], "unknown")


class _FakeDriver:
    current_url = "https://app.example/login?one-time-secret=hidden"

    def execute_script(self, _script):
        return {
            "urls": [
                "https://id.example/authorize?client_id=hidden-client&response_type=code&state=hidden-state",
            ],
            "jwt_metadata": [{
                "source": "local_storage", "algorithm": "RS256",
                "expiration_claim": True, "issuer_claim": True,
                "audience_claim": True, "signature_segment_present": True,
            }],
            "webauthn": {"autocomplete_webauthn": True,
                         "public_key_credential_api": True},
        }

    def get_cookies(self):
        return [{"name": "sessionid", "value": "hidden-cookie",
                 "secure": True, "httpOnly": True, "sameSite": "Lax"}]

    def get_log(self, _kind):
        return []


class ObservationBundleTests(unittest.TestCase):
    def test_bundle_is_passive_redacted_and_persistable(self):
        bundle = collect_security_observations(
            _FakeDriver(),
            states=[{"fields": ["password"], "methods": ["password"]}],
            methods=[{"method": "password"}],
        )
        self.assertEqual(bundle["collection_mode"], "passive")
        self.assertTrue(bundle["privacy"]["raw_tokens_stored"] is False)
        self.assertTrue(bundle["privacy"]["extra_network_request_sent"] is False)
        self.assertIn("transport_security", bundle["analyzers"])
        self.assertIn("http_security_headers", bundle["analyzers"])
        serialized = json.dumps(bundle)
        for secret in ("hidden-client", "hidden-state", "hidden-cookie", "one-time-secret"):
            self.assertNotIn(secret, serialized)

        record = measurement_record(
            "app.example", "https://app.example", "v4", "login",
            {"flow_type": "direct_password", "security_observations": bundle},
        )
        self.assertEqual(record["security_observations"], bundle)
        site = build_sites({"app.example": {"login": [record]}})[0]
        self.assertEqual(site["login"]["security_observations"], bundle)

    def test_classifier_exit_attaches_same_observation_bundle(self):
        result = FlowResult(
            site="app.example", entry_kind="login",
            states=[PageState(step=1, url="https://app.example/login",
                              fields=["password"], methods=["password"])],
        )
        output = SignupFlowClassifierEngine(_FakeDriver())._done(
            result, "direct_password", "high", "password_step_reached")
        self.assertEqual(
            output["security_observations"]["collection_mode"], "passive")
        self.assertIn(
            "mfa", output["security_observations"]["observed_capabilities"])


if __name__ == "__main__":
    unittest.main()
