import unittest

from scripts.audit_policy_funnel import audit, classify_loss, normalize_host


class PolicyFunnelAuditTests(unittest.TestCase):
    def test_host_normalization_joins_www_and_bare_hosts(self):
        self.assertEqual(normalize_host("WWW.Example.com."), "example.com")

    def test_complete_policy_requires_usable_length_and_no_inconclusive(self):
        category, _ = classify_loss({
            "method_used": "inline",
            "policy": {"length": [8, 64]},
        })
        self.assertEqual(category, "complete_policy")
        category, _ = classify_loss({
            "method_used": "inline",
            "policy": {
                "length": [8, 64],
                "_inconclusive": True,
                "_inconclusive_reason": "control drift",
            },
        })
        self.assertEqual(category, "inline_inconclusive")

    def test_password_seen_without_policy_gets_specific_loss_reason(self):
        category, _ = classify_loss({
            "flow_type": "direct_password",
            "method_used": "classified_only",
            "states": [{"fields": ["email", "password"]}],
        })
        self.assertEqual(category, "password_reached_inline_unsupported")

    def test_password_on_rejected_signup_context_is_separate(self):
        category, _ = classify_loss({
            "flow_type": "no_web_signup",
            "method_used": "classified_only",
            "states": [{"fields": ["identifier", "password"]}],
        })
        self.assertEqual(category, "password_on_unconfirmed_signup_context")

    def test_verification_gate_is_not_reported_as_no_signup(self):
        category, _ = classify_loss({
            "flow_type": "otp_only",
            "stop_reason": "verification_required",
            "states": [{
                "fields": ["phone", "code"],
                "blockers": ["sms_code"],
            }],
        })
        self.assertEqual(category, "verification_before_password")

    def test_audit_reports_denominator_and_breakdown(self):
        result = audit(["a.example", "www.b.example"], {
            "a.example": {
                "method_used": "inline",
                "policy": {"length": [8, 20]},
            },
            "b.example": {
                "flow_type": "unknown",
                "stop_reason": "unrecognized_page",
            },
        })
        self.assertEqual(result["manual_inline_total"], 2)
        self.assertEqual(result["complete_policy_total"], 1)
        self.assertEqual(result["complete_policy_rate"], 50.0)
        self.assertEqual(result["category_counts"]["password_not_reached"], 1)


if __name__ == "__main__":
    unittest.main()
