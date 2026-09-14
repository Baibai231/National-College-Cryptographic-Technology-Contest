import base64
import json
import socket
import unittest
from unittest import mock

from application_security.oidc_discovery import (
    JsonFetchResult,
    OIDC_DISCOVERY_MANIFEST,
    SafeFetchError,
    probe_oidc_discovery,
    safe_fetch_json,
    validate_public_https_url,
)


def public_rsa_jwks(bits=2048):
    modulus = bytes([0x80]) + bytes(bits // 8 - 1)
    encoded = base64.urlsafe_b64encode(modulus).rstrip(b"=").decode()
    return {"keys": [{
        "kty": "RSA", "use": "sig", "alg": "RS256", "kid": "key-1",
        "n": encoded, "e": "AQAB",
    }]}


class FakeFetcher:
    def __init__(self, documents):
        self.documents = documents
        self.calls = []

    def __call__(self, url, *, max_bytes):
        self.calls.append((url, max_bytes))
        value = self.documents.get(url)
        if isinstance(value, Exception):
            raise value
        if value is None:
            raise SafeFetchError("http_status_404")
        return JsonFetchResult(
            requested_url=url,
            final_url=url,
            document=value,
            content_type="application/json",
            redirect_count=0,
            tls_version="TLSv1.3",
            certificate_verified=True,
        )


class OidcDiscoveryTests(unittest.TestCase):
    def test_manifest_declares_top_paper_and_direct_standards(self):
        self.assertEqual(
            OIDC_DISCOVERY_MANIFEST.paper_refs[0].venue,
            "IEEE Symposium on Security and Privacy",
        )
        standard_ids = {item.reference_id
                        for item in OIDC_DISCOVERY_MANIFEST.standard_refs}
        self.assertIn("openid-connect-discovery-1.0-errata2", standard_ids)
        self.assertIn("oauth-authorization-server-metadata-rfc8414", standard_ids)

    def test_complete_public_chain_is_bound_but_hygiene_stays_unknown(self):
        issuer = "https://issuer.example"
        discovery = issuer + "/.well-known/openid-configuration"
        jwks_url = issuer + "/keys"
        jwks = public_rsa_jwks()
        fetcher = FakeFetcher({
            discovery: {
                "issuer": issuer,
                "authorization_endpoint": issuer + "/authorize",
                "token_endpoint": issuer + "/token",
                "jwks_uri": jwks_url,
                "id_token_signing_alg_values_supported": ["RS256"],
                "code_challenge_methods_supported": ["S256"],
            },
            jwks_url: jwks,
        })
        result = probe_oidc_discovery(
            "site.example", [{"origin": issuer, "same_origin": False}],
            fetch_json=fetcher,
        ).to_dict()
        self.assertEqual(result["claims"][0]["verdict"], "pass")
        self.assertEqual(result["claims"][1]["verdict"], "pass")
        self.assertEqual(result["claims"][2]["verdict"], "unknown")
        provider = result["claims"][1]["value"]["providers"][0]
        self.assertEqual(provider["role"], "external_provider")
        self.assertTrue(provider["issuer_exact_match"])
        self.assertTrue(provider["jwks_fetched"])
        self.assertEqual(provider["jwks_summary"]["rsa_modulus_bits"], [2048])
        self.assertTrue(provider["metadata_jwks_algorithm_binding"])
        self.assertEqual(provider["metadata_jwks_algorithm_overlap"], ["RS256"])
        self.assertFalse(
            result["claims"][2]["value"]["clean_snapshot_is_security_pass"])
        serialized = json.dumps(result)
        self.assertNotIn(jwks["keys"][0]["n"], serialized)
        self.assertNotIn("key-1", serialized)

    def test_issuer_mismatch_fails_and_jwks_is_not_fetched(self):
        issuer = "https://issuer.example"
        discovery = issuer + "/.well-known/openid-configuration"
        jwks_url = "https://attacker.example/keys"
        fetcher = FakeFetcher({
            discovery: {
                "issuer": "https://attacker.example",
                "authorization_endpoint": issuer + "/authorize",
                "jwks_uri": jwks_url,
            },
            jwks_url: public_rsa_jwks(),
        })
        result = probe_oidc_discovery(
            "site.example", [issuer], fetch_json=fetcher).to_dict()
        self.assertEqual(result["claims"][1]["verdict"], "fail")
        provider = result["claims"][1]["value"]["providers"][0]
        self.assertFalse(provider["issuer_exact_match"])
        self.assertFalse(provider["jwks_fetched"])
        self.assertEqual([call[0] for call in fetcher.calls], [discovery])

    def test_public_jwks_with_symmetric_key_is_fail_without_key_material(self):
        issuer = "https://issuer.example"
        discovery = issuer + "/.well-known/openid-configuration"
        jwks_url = issuer + "/keys"
        secret = "do-not-publish-this-key"
        fetcher = FakeFetcher({
            discovery: {
                "issuer": issuer,
                "authorization_endpoint": issuer + "/authorize",
                "jwks_uri": jwks_url,
                "id_token_signing_alg_values_supported": ["HS256"],
            },
            jwks_url: {"keys": [{
                "kty": "oct", "use": "sig", "alg": "HS256", "k": secret,
            }]},
        })
        result = probe_oidc_discovery(
            "site.example", [issuer], fetch_json=fetcher).to_dict()
        self.assertEqual(result["claims"][2]["verdict"], "fail")
        self.assertEqual(
            result["claims"][2]["value"]["issues"]["private_or_symmetric_keys"], 1)
        self.assertNotIn(secret, json.dumps(result))

    def test_weak_rsa_and_none_algorithm_are_reported_weak(self):
        issuer = "https://issuer.example"
        discovery = issuer + "/.well-known/openid-configuration"
        jwks_url = issuer + "/keys"
        fetcher = FakeFetcher({
            discovery: {
                "issuer": issuer,
                "authorization_endpoint": issuer + "/authorize",
                "jwks_uri": jwks_url,
                "id_token_signing_alg_values_supported": ["none", "RS256"],
            },
            jwks_url: public_rsa_jwks(1024),
        })
        result = probe_oidc_discovery(
            "site.example", [issuer], fetch_json=fetcher).to_dict()
        self.assertEqual(result["claims"][2]["verdict"], "weak")
        issues = result["claims"][2]["value"]["issues"]
        self.assertEqual(issues["rsa_below_2048"], 1)
        self.assertEqual(issues["none_algorithm_advertised"], 1)

    def test_declared_algorithm_and_key_type_mismatch_is_weak(self):
        issuer = "https://issuer.example"
        discovery = issuer + "/.well-known/openid-configuration"
        jwks_url = issuer + "/keys"
        fetcher = FakeFetcher({
            discovery: {
                "issuer": issuer,
                "authorization_endpoint": issuer + "/authorize",
                "jwks_uri": jwks_url,
                "id_token_signing_alg_values_supported": ["RS256"],
            },
            jwks_url: {"keys": [{
                "kty": "EC", "use": "sig", "alg": "RS256",
                "kid": "wrong-kty", "crv": "P-256", "x": "eA", "y": "eQ",
            }]},
        })
        result = probe_oidc_discovery(
            "site.example", [issuer], fetch_json=fetcher).to_dict()
        self.assertEqual(result["claims"][2]["verdict"], "weak")
        issues = result["claims"][2]["value"]["issues"]
        self.assertEqual(issues["algorithm_key_type_mismatches"], 1)
        self.assertEqual(issues["metadata_jwks_no_algorithm_overlap"], 0)

    def test_private_literal_and_private_dns_answers_are_rejected(self):
        with self.assertRaises(SafeFetchError) as literal:
            validate_public_https_url("https://127.0.0.1/keys")
        self.assertEqual(literal.exception.code, "non_public_address")

        def private_resolver(_host, _port, **_kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                     ("10.0.0.8", 443))]

        with self.assertRaises(SafeFetchError) as resolved:
            validate_public_https_url(
                "https://metadata.example/keys", resolver=private_resolver)
        self.assertEqual(resolved.exception.code, "non_public_address")

    def test_redirect_to_private_address_is_revalidated_and_blocked(self):
        class RedirectResponse:
            status = 302

            @staticmethod
            def getheader(name):
                return "https://127.0.0.1/internal" if name == "Location" else None

        class FakeConnection:
            sock = None

            def __init__(self, *_args, **_kwargs):
                pass

            def request(self, *_args, **_kwargs):
                pass

            def getresponse(self):
                return RedirectResponse()

            def close(self):
                pass

        def public_resolver(_host, _port, **_kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                     ("93.184.216.34", 443))]

        with mock.patch(
                "application_security.oidc_discovery.http.client.HTTPSConnection",
                FakeConnection):
            with self.assertRaises(SafeFetchError) as ctx:
                safe_fetch_json(
                    "https://public.example/discovery", max_bytes=1024,
                    resolver=public_resolver)
        self.assertEqual(ctx.exception.code, "non_public_address")

    def test_candidate_limit_and_no_candidate_remain_unknown(self):
        no_candidate = probe_oidc_discovery(
            "site.example", [], fetch_json=FakeFetcher({})).to_dict()
        self.assertTrue(all(claim["verdict"] == "unknown"
                            for claim in no_candidate["claims"]))

        fetcher = FakeFetcher({})
        result = probe_oidc_discovery(
            "site.example",
            ["https://one.example", "https://two.example",
             "https://three.example", "https://four.example"],
            fetch_json=fetcher,
        ).to_dict()
        self.assertEqual(result["claims"][0]["value"]["candidate_count"], 3)

    def test_network_failure_does_not_repeat_same_origin_with_oauth_fallback(self):
        issuer = "https://issuer.example"
        discovery = issuer + "/.well-known/openid-configuration"
        fetcher = FakeFetcher({
            discovery: SafeFetchError("network_or_tls_error"),
        })
        result = probe_oidc_discovery(
            "site.example", [issuer], fetch_json=fetcher).to_dict()
        self.assertEqual(len(fetcher.calls), 1)
        self.assertEqual(result["claims"][1]["verdict"], "unknown")

    def test_additive_probe_failure_never_discards_primary_result(self):
        def broken_fetcher(_url, *, max_bytes):
            raise RuntimeError("unexpected parser failure")

        result = probe_oidc_discovery(
            "site.example", ["https://issuer.example"],
            fetch_json=broken_fetcher,
        ).to_dict()
        self.assertEqual(result["claims"][0]["verdict"], "unknown")
        provider = result["claims"][1]["value"]["providers"][0]
        self.assertEqual(provider["errors"], ["probe_internal_error:RuntimeError"])


if __name__ == "__main__":
    unittest.main()
