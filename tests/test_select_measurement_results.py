import unittest

from scripts.select_measurement_results import select
from tests.test_compare_measurement_rounds import record


class SelectMeasurementResultsTests(unittest.TestCase):
    def test_same_prefers_second_round(self):
        key = ("example.com", "signup")
        first, second = record(), record()
        first["measured_at"] = "1"
        second["measured_at"] = "2"
        chosen, decisions = select({key: first}, {key: second}, {})
        self.assertIs(chosen[key], second)
        self.assertIn("第二轮", decisions[0]["reason"])

    def test_tiebreaker_majority_selects_first(self):
        key = ("example.com", "signup")
        first = record("otp_only")
        second = record("direct_password")
        third = record("otp_only")
        chosen, decisions = select({key: first}, {key: second}, {key: third})
        self.assertIs(chosen[key], first)
        self.assertIn("两票多数", decisions[0]["reason"])

    def test_difference_without_tiebreaker_fails(self):
        key = ("example.com", "signup")
        with self.assertRaises(ValueError):
            select({key: record("otp_only")}, {key: record("unknown")}, {})

    def test_one_success_beats_two_measurement_failures(self):
        key = ("example.com", "signup")
        success = record("human_blocked")
        failure2 = record()
        failure3 = record()
        failure2["error"] = "TimeoutException: renderer timeout"
        failure3["error"] = "TimeoutException: renderer timeout"
        chosen, decisions = select(
            {key: success}, {key: failure2}, {key: failure3})
        self.assertIs(chosen[key], success)
        self.assertIn("成功记录", decisions[0]["reason"])

    def test_successful_tiebreaker_replaces_two_identical_failures(self):
        key = ("example.com", "login")
        first, second = record(), record()
        first["error"] = "WebDriverException: unsupported protocol"
        second["error"] = "WebDriverException: unsupported protocol"
        third = record("direct_password")
        chosen, decisions = select(
            {key: first}, {key: second}, {key: third})
        self.assertIs(chosen[key], third)
        self.assertIn("有效页面证据", decisions[0]["reason"])

    def test_failed_tiebreaker_never_replaces_two_successful_rounds(self):
        key = ("example.com", "signup")
        first = record("otp_only")
        second = record("direct_password")
        third = record()
        third["error"] = "TimeoutException: renderer timeout"
        chosen, decisions = select(
            {key: first}, {key: second}, {key: third})
        self.assertIs(chosen[key], second)
        self.assertIn("较新的第二轮", decisions[0]["reason"])

    def test_three_failures_keep_successful_v3_baseline(self):
        key = ("example.com", "login")
        failures = []
        for _ in range(3):
            item = record()
            item["error"] = "WebDriverException: unsupported protocol"
            failures.append(item)
        prior = record("direct_password")
        chosen, decisions = select(
            {key: failures[0]}, {key: failures[1]}, {key: failures[2]},
            {key: prior})
        self.assertIs(chosen[key], prior)
        self.assertIn("旧 v3", decisions[0]["reason"])

    def test_unknown_majority_does_not_erase_last_valid_v3_evidence(self):
        key = ("example.com", "signup")
        unknown1, unknown2 = record("unknown"), record("unknown")
        prior = record("otp_only")
        chosen, decisions = select(
            {key: unknown1}, {key: unknown2}, {}, {key: prior})
        self.assertIs(chosen[key], prior)
        self.assertIn("最后有效证据", decisions[0]["reason"])

    def test_new_conclusive_measurement_replaces_valid_baseline(self):
        key = ("example.com", "signup")
        current1, current2 = record("otp_only"), record("otp_only")
        prior = record("direct_password")
        chosen, _ = select(
            {key: current1}, {key: current2}, {}, {key: prior})
        self.assertIs(chosen[key], current2)


if __name__ == "__main__":
    unittest.main()
