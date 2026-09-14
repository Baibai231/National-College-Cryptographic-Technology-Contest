import unittest

from application_security.oidc_discovery import JsonFetchResult, SafeFetchError
from application_security.passkey_well_known import (
    PASSKEY_WELL_KNOWN_MANIFEST,
    probe_passkey_well_known,
)


def _result(url, document):
    return JsonFetchResult(
        requested_url=url,
        final_url=url,
        document=document,
        content_type="application/json",
        redirect_count=0,
        tls_version="TLSv1.3",
        certificate_verified=True,
    )


def _claims(result):
    return {claim.metric_id: claim for claim in result.claims}


def test_manifest_binds_top_paper_and_both_w3c_methods():
    assert PASSKEY_WELL_KNOWN_MANIFEST.paper_refs[0].venue == "USENIX Security"
    assert {
        reference.reference_id
        for reference in PASSKEY_WELL_KNOWN_MANIFEST.standard_refs
    } == {"passkey-endpoints-w3c", "webauthn-level-3"}


def test_valid_documents_are_summarized_without_retaining_urls_or_origins():
    secret_endpoint = "https://accounts.example.com/private/passkey?token=secret"
    secret_origin = "https://login.example.net"

    def fetcher(url, **_kwargs):
        if url.endswith("passkey-endpoints"):
            return _result(url, {
                "enroll": secret_endpoint,
                "manage": "https://example.com/security",
            })
        return _result(url, {"origins": ["https://example.com", secret_origin]})

    result = probe_passkey_well_known("https://example.com/login", fetcher=fetcher)
    claims = _claims(result)
    assert claims["auth.passkey.well_known_endpoints"].verdict.value == "pass"
    assert claims["auth.webauthn.related_origins"].verdict.value == "pass"
    assert claims["auth.passkey.well_known_coverage"].value["coverage"] == 1.0
    serialized = str(result.to_dict())
    assert secret_endpoint not in serialized
    assert secret_origin not in serialized
    assert "token=secret" not in serialized
    assert claims["auth.passkey.well_known_endpoints"].value[
        "external_host_endpoint_count"] == 1
    assert claims["auth.webauthn.related_origins"].value[
        "valid_unique_origin_count"] == 2


def test_malformed_observed_documents_are_weak_not_absent():
    def fetcher(url, **_kwargs):
        if url.endswith("passkey-endpoints"):
            return _result(url, {"enroll": "http://example.com/setup"})
        return _result(url, {"origins": "https://example.com"})

    claims = _claims(probe_passkey_well_known(
        "https://example.com", fetcher=fetcher))
    assert claims["auth.passkey.well_known_endpoints"].verdict.value == "weak"
    assert claims["auth.webauthn.related_origins"].verdict.value == "weak"


def test_fetch_failure_stays_unknown_and_has_stable_error_codes():
    def fetcher(url, **_kwargs):
        raise SafeFetchError("http_status_404")

    result = probe_passkey_well_known("https://example.com", fetcher=fetcher)
    claims = _claims(result)
    assert claims["auth.passkey.well_known_endpoints"].verdict.value == "unknown"
    assert claims["auth.webauthn.related_origins"].verdict.value == "unknown"
    assert result.errors == (
        "passkey_endpoints:http_status_404",
        "related_origins:http_status_404",
    )


def test_non_https_target_is_rejected_without_fetching():
    called = False

    def fetcher(_url, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError

    result = probe_passkey_well_known("http://localhost:8000", fetcher=fetcher)
    assert result.errors == ("origin:invalid_origin",)
    assert not called


class PasskeyWellKnownTests(unittest.TestCase):
    def test_manifest(self):
        test_manifest_binds_top_paper_and_both_w3c_methods()

    def test_valid_documents(self):
        test_valid_documents_are_summarized_without_retaining_urls_or_origins()

    def test_malformed_documents(self):
        test_malformed_observed_documents_are_weak_not_absent()

    def test_fetch_failure(self):
        test_fetch_failure_stays_unknown_and_has_stable_error_codes()

    def test_non_https_target(self):
        test_non_https_target_is_rejected_without_fetching()
