import unittest

from scripts.compare_measurement_rounds import compare, signature


def record(flow="otp_only", fields=None, blockers=None, methods=None):
    return {
        "flow_type": flow, "stop_reason": "no_password_observed",
        "primary_method": "sms", "error": None,
        "states": [{"fields": fields or ["phone", "code"],
                    "blockers": blockers or ["sms_code"],
                    "methods": methods or ["phone"]}],
    }


class RoundComparisonTests(unittest.TestCase):
    def test_order_does_not_change_signature(self):
        a = record(fields=["phone", "code"], methods=["phone", "qr"])
        b = record(fields=["code", "phone"], methods=["qr", "phone"])
        self.assertEqual(signature(a), signature(b))

    def test_semantic_difference_is_reported(self):
        first = {("example.com", "signup"): record("human_blocked", blockers=["scan"])}
        second = {("example.com", "signup"): record("otp_only", blockers=["sms_code"])}
        rows = compare(first, second)
        self.assertEqual(rows[0]["status"], "different")

    def test_missing_record_is_reported(self):
        rows = compare({("example.com", "login"): record()}, {})
        self.assertEqual(rows[0]["status"], "missing")

    def test_timeout_stack_noise_is_ignored(self):
        first = record()
        second = record()
        first["error"] = "TimeoutException: renderer timeout\nstack 0x111"
        second["error"] = "TimeoutException: renderer timeout\nstack 0x222"
        self.assertEqual(signature(first), signature(second))


if __name__ == "__main__":
    unittest.main()
