import unittest

from application_security.qr_lifecycle import (
    QR_LIFECYCLE_MANIFEST,
    analyze_qr_observations,
    collect_qr_lifecycle_sample,
)


class _Driver:
    def execute_cdp_cmd(self, _name, _params):
        return {}

    def execute_script(self, _script):
        return None

    def execute_async_script(self, _script):
        return {
            "qr_observed": True,
            "comparison_count": 0,
            "change_count": 0,
            "raw_qr_content_retained": False,
            "hmac_key_or_tag_returned": False,
            "qr_decoded": False,
            "scan_performed": False,
            "login_attempted": False,
        }


class QrLifecycleTests(unittest.TestCase):
    def test_manifest_is_top_paper_and_crypto_backed(self):
        self.assertEqual(QR_LIFECYCLE_MANIFEST.paper_refs[0].venue, "USENIX Security")
        self.assertIn("session_identifier_binding", QR_LIFECYCLE_MANIFEST.crypto_elements)

    def test_refresh_observation_never_upgrades_protocol_security(self):
        result = analyze_qr_observations("example.test", [
            {"qr_observed": True, "comparison_count": 0, "change_count": 0},
            {"qr_observed": True, "comparison_count": 1, "change_count": 1},
        ])
        claims = {claim.metric_id: claim for claim in result.claims}
        self.assertEqual(claims["auth.qr.page_refresh"].value["refresh_rate"], 1.0)
        self.assertEqual(claims["auth.qr.protocol_security_variables"].verdict.value, "unknown")
        self.assertFalse(claims["auth.qr.protocol_security_variables"].value["qr_id_one_time_verified"])

    def test_output_does_not_retain_qr_or_hmac_material(self):
        result = collect_qr_lifecycle_sample(_Driver(), "example.test").to_dict()
        encoded = str(result).lower()
        self.assertNotIn("qr-content-secret", encoded)
        observation = result["evidence"][0]["observation"]
        self.assertFalse(observation["raw_qr_content_retained"])
        self.assertFalse(observation["hmac_key_or_tag_returned"])

    def test_absence_is_unknown_not_fail(self):
        result = analyze_qr_observations("example.test", [{"qr_observed": False}])
        claim = next(c for c in result.claims if c.metric_id == "auth.qr.rendered_login_code")
        self.assertEqual(claim.verdict.value, "unknown")


if __name__ == "__main__":
    unittest.main()
