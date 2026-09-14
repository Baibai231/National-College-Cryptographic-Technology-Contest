import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "analyze_webauthn_public_rounds.py"
SPEC = importlib.util.spec_from_file_location("analyze_webauthn_public_rounds", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _module(claims):
    return {"claims": claims}


def _claim(metric_id, value):
    return {"metric_id": metric_id, "value": value}


def _record(*, loaded=True, dom=False, api=False, endpoints=False):
    return {
        "browser_probe": {
            "navigation": {"loaded": loaded},
            "passive_protocol": _module([
                _claim("auth.passkey.visible_control", {"observed": dom}),
            ]),
            "webauthn_observer": _module([
                _claim("auth.webauthn.api_invocation", {
                    "observed": api,
                    "ceremonies": ["authentication"] if api else [],
                }),
                _claim("auth.webauthn.request_configuration", {
                    "invocations": [{"ceremony": "authentication"}] if api else [],
                }),
                _claim("auth.webauthn.cose_algorithm_policy", {"offered_total": 0}),
                _claim("auth.webauthn.lifecycle_sync", {"observed": False}),
                _claim("auth.webauthn.passkey_profile", {
                    "conditional_count": 1 if api else 0,
                }),
            ]),
        },
        "well_known": _module([
            _claim("auth.passkey.well_known_endpoints", {
                "resource_observed": endpoints,
            }),
            _claim("auth.webauthn.related_origins", {"resource_observed": False}),
        ]),
    }


def test_compare_reports_coverage_and_two_round_drift():
    first = {
        "a.example": _record(dom=True, api=True, endpoints=True),
        "b.example": _record(),
    }
    second = {
        "a.example": _record(dom=True, api=False, endpoints=True),
        "b.example": _record(),
    }
    result = MODULE.compare(first, second)
    assert result["paired_site_count"] == 2
    assert result["round_1"]["coverage"]["api_invocation"] == 0.5
    assert result["round_2"]["coverage"]["api_invocation"] == 0.0
    changed = next(item for item in result["sites"] if item["site_id"] == "a.example")
    assert "api_invocation" in changed["missing_in_round_2"]
    assert result["two_round_consistency"]["weighted_feature_jaccard"] < 1.0


def test_empty_feature_sets_are_consistent_not_division_by_zero():
    empty = _record(loaded=False)
    result = MODULE.compare({"a": empty}, {"a": empty})
    assert result["sites"][0]["feature_jaccard"] == 1.0
    assert result["two_round_consistency"]["binary_presence_agreement"] == 1.0


class WebAuthnPublicRoundTests(unittest.TestCase):
    def test_round_drift(self):
        test_compare_reports_coverage_and_two_round_drift()

    def test_empty_sets(self):
        test_empty_feature_sets_are_consistent_not_division_by_zero()
