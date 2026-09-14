import unittest

from application_security.recovery_analysis import (
    RECOVERY_MANIFEST,
    analyze_recovery_observation,
    collect_recovery_surface,
)


class _Driver:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def execute_script(self, _script):
        if self.error:
            raise self.error
        return self.result


class RecoveryAnalysisTests(unittest.TestCase):
    def test_manifest_is_paper_backed_and_crypto_scoped(self):
        self.assertTrue(RECOVERY_MANIFEST.paper_refs)
        self.assertIn("oblivious_pseudorandom_function", RECOVERY_MANIFEST.crypto_elements)

    def test_public_entry_does_not_upgrade_token_security(self):
        result = analyze_recovery_observation("example.test", {
            "recovery_path_observed": False,
            "recovery_control_count": 1,
            "recovery_controls": [{"origin_relation": "same_origin", "path": "/reset"}],
            "factor_hints": ["email"],
            "recovery_form_field_count": 0,
            "captcha_observed": False,
            "input_performed": False,
            "recovery_request_sent": False,
            "token_observed": False,
        })
        claims = {claim.metric_id: claim for claim in result.claims}
        self.assertEqual(claims["auth.recovery.public_entry"].verdict.value, "pass")
        self.assertEqual(claims["auth.recovery.token_lifecycle"].verdict.value, "unknown")
        self.assertFalse(claims["auth.recovery.token_lifecycle"].value["entropy_verified"])

    def test_absence_stays_unknown(self):
        result = analyze_recovery_observation("example.test", {})
        claim = next(c for c in result.claims if c.metric_id == "auth.recovery.public_entry")
        self.assertEqual(claim.verdict.value, "unknown")

    def test_driver_error_is_isolated(self):
        result = collect_recovery_surface(_Driver(error=RuntimeError()), "example.test")
        self.assertEqual(result.claims, ())
        self.assertEqual(result.errors, ("recovery_dom_probe_failed:RuntimeError",))


if __name__ == "__main__":
    unittest.main()
