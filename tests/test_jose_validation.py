import base64
import json
import unittest
from unittest import mock

from application_security.jose_validation import (
    JOSE_MANIFEST,
    JoseParseError,
    analyze_jose_metadata,
    inspect_compact_jwt,
    inspect_jwks,
    verify_compact_jwt,
)


# RFC 7515 Appendix A.2 public verification vector.
RFC_TOKEN = (
    "eyJhbGciOiJSUzI1NiJ9."
    "eyJpc3MiOiJqb2UiLA0KICJleHAiOjEzMDA4MTkzODAsDQogImh0dHA6Ly9leGFt"
    "cGxlLmNvbS9pc19yb290Ijp0cnVlfQ."
    "cC4hiUPoj9Eetdgtv3hF80EGrhuB__dzERat0XF9g2VtQgr9PJbu3XOiZj5RZmh7"
    "AAuHIm4Bh-0Qc_lF5YKt_O8W2Fp5jujGbds9uJdbF9CUAr7t1dnZcAcQjbKBYNX4"
    "BAynRFdiuB--f_nZLgrnbyTyWzO75vRK5h6xBArLIARNPvkSjtQBMHlb1L07Qe7K"
    "0GarZRmB_eSN9383LcOLn6_dO--xi12jzDwusC-eOkHWEsqtFZESc6BfI7noOPqv"
    "hJ1phCnvWh6IeYI2w9QOYEUipUTI8np6LbgGY9Fs98rqVt5AXLIhWkWywlVmtVrB"
    "p0igcN_IoypGlUPQGe77Rw"
)
RFC_JWKS = {"keys": [{
    "kty": "RSA",
    "use": "sig",
    "alg": "RS256",
    "n": (
        "ofgWCuLjybRlzo0tZWJjNiuSfb4p4fAkd_wWJcyQoTbji9k0l8W26mPddx"
        "HmfHQp-Vaw-4qPCJrcS2mJPMEzP1Pt0Bm4d4QlL-yRT-SFd2lZS-pCgNMs"
        "D1W_YpRPEwOWvG6b32690r2jZ47soMZo9wGzjb_7OMg0LOL-bSf63kpaSH"
        "SXndS5z5rexMdbBYUsLA9e-KXBdQOS-UTo7WTBEMa2R2CapHg665xsmtdV"
        "MTBQY4uDZlxvb3qCo5ZwKh9kG4LT6_I5IhlJH7aGhyxXFvUK-DWNmoudF8"
        "NAco9_h9iaGNj8q2ethFkMLs91kzk2PAcDTW9gb54h4FRWyuXpoQ"
    ),
    "e": "AQAB",
}]}


def compact(header, payload, signature="eA"):
    encode = lambda value: base64.urlsafe_b64encode(
        json.dumps(value, separators=(",", ":")).encode()).rstrip(b"=").decode()
    return encode(header) + "." + encode(payload) + "." + signature


class JoseValidationTests(unittest.TestCase):
    def test_manifest_declares_crypto_paper_and_standards(self):
        self.assertIn("rsa_signature_verification", JOSE_MANIFEST.crypto_elements)
        self.assertEqual(JOSE_MANIFEST.paper_refs[0].venue,
                         "IEEE Symposium on Security and Privacy")
        self.assertGreaterEqual(len(JOSE_MANIFEST.standard_refs), 4)

    def test_inspection_never_returns_token_or_claim_values(self):
        token = compact(
            {"alg": "RS256", "typ": "JWT", "kid": "private-key-name"},
            {"iss": "secret-issuer", "aud": "secret-audience", "sub": "alice"},
        )
        result = inspect_compact_jwt(token, parameter="id_token")
        serialized = json.dumps(result)
        self.assertEqual(result["profile"], "oidc_id_token")
        self.assertTrue(result["kid_present"])
        self.assertIn("aud", result["binding_claims_present"])
        self.assertNotIn(token, serialized)
        self.assertNotIn("secret-issuer", serialized)
        self.assertNotIn("secret-audience", serialized)
        self.assertNotIn("private-key-name", serialized)

    def test_rfc7515_rs256_vector_is_cryptographically_verified(self):
        report = verify_compact_jwt(
            RFC_TOKEN,
            jwks=RFC_JWKS,
            allowed_algorithms=["RS256"],
            expected_issuer="joe",
            now=1300000000,
        )
        self.assertTrue(report["checks"]["signature"])
        self.assertTrue(report["checks"]["algorithm"])
        self.assertTrue(report["checks"]["issuer"])
        self.assertTrue(report["checks"]["time"])
        self.assertTrue(report["verification_predicate"])
        self.assertEqual(report["required_checks"],
                         ["signature", "algorithm", "issuer", "time"])
        self.assertAlmostEqual(report["verification_coverage"], 1.0)
        self.assertNotIn(RFC_TOKEN, json.dumps(report))

    def test_tampered_signature_is_rejected(self):
        head, payload, signature = RFC_TOKEN.split(".")
        replacement = "d" if signature[0] != "d" else "e"
        tampered = head + "." + payload + "." + replacement + signature[1:]
        report = verify_compact_jwt(
            tampered, jwks=RFC_JWKS, allowed_algorithms=["RS256"],
            expected_issuer="joe", now=1300000000)
        self.assertFalse(report["checks"]["signature"])
        self.assertFalse(report["verification_predicate"])

    def test_jwks_summary_reports_strength_without_material(self):
        result = inspect_jwks(RFC_JWKS)
        self.assertEqual(result["key_count"], 1)
        self.assertEqual(result["rsa_modulus_bits"], [2048])
        self.assertEqual(result["rsa_below_2048_count"], 0)
        self.assertEqual(result["private_or_symmetric_key_count"], 0)
        self.assertEqual(result["algorithm_key_type_mismatch_count"], 0)
        self.assertNotIn(RFC_JWKS["keys"][0]["n"], json.dumps(result))

    def test_none_algorithm_is_reported_as_weak_not_pass(self):
        token = compact({"alg": "none"}, {"iss": "joe"}, signature="")
        metadata = inspect_compact_jwt(token, parameter="id_token")
        result = analyze_jose_metadata("example.com", [metadata]).to_dict()
        self.assertEqual(result["claims"][0]["verdict"], "weak")
        self.assertEqual(
            result["claims"][0]["value"]["unsecured_total"], 1)

    def test_full_predicate_is_required_for_pass(self):
        partial = {
            "alg": "RS256", "signature_present": True,
            "verification_predicate": None,
        }
        complete = {
            "alg": "RS256", "signature_present": True,
            "verification_predicate": True,
            "checks": {name: True for name in
                       ("signature", "algorithm", "issuer", "audience",
                        "time", "nonce", "type")},
        }
        self.assertEqual(analyze_jose_metadata(
            "example.com", [partial]).to_dict()["claims"][0]["verdict"], "unknown")
        self.assertEqual(analyze_jose_metadata(
            "example.com", [complete]).to_dict()["claims"][0]["verdict"], "pass")
        mixed = analyze_jose_metadata(
            "example.com", [complete, partial]).to_dict()["claims"][0]
        self.assertEqual(mixed["verdict"], "unknown")

    def test_missing_algorithm_stays_unknown(self):
        result = analyze_jose_metadata("example.com", [{
            "source": "dom_url", "parameter": "request",
            "signature_present": True,
        }]).to_dict()
        self.assertEqual(result["claims"][0]["verdict"], "unknown")

    def test_duplicate_json_members_are_rejected(self):
        encode = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
        token = encode(b'{"alg":"RS256","alg":"none"}') + "." + \
            encode(b'{"iss":"joe"}') + ".eA"
        with self.assertRaises(JoseParseError):
            inspect_compact_jwt(token)

    def test_live_web_helper_attaches_redacted_jose_result(self):
        from webapp.app import _attach_live_protocol_probe

        driver = mock.MagicMock()
        driver.execute_script.return_value = {
            "url_origin": "https://example.com",
            "url_path": "/login",
            "oauth_endpoints": [],
            "jose_objects": [{
                "source": "dom_url", "parameter": "request",
                "profile": "jar_request", "alg": "none", "typ": "JWT",
                "kid_present": False, "claim_names": ["aud", "iss"],
                "binding_claims_present": ["iss", "aud"],
                "signature_present": False, "signature_bytes": 0,
            }],
            "passkey_signals": [], "mfa_indicators": [], "rba_indicators": [],
        }
        response = _attach_live_protocol_probe({}, driver, "example.com")
        jose = response["application_security"]["jose_validation"]["result"]
        self.assertEqual(jose["claims"][0]["verdict"], "weak")
        self.assertFalse(
            jose["claims"][0]["value"]["token_values_retained"])
        self.assertIn("oidc_discovery", response["application_security"])
        oidc = response["application_security"]["oidc_discovery"]["result"]
        self.assertEqual(oidc["claims"][0]["verdict"], "unknown")


if __name__ == "__main__":
    unittest.main()
