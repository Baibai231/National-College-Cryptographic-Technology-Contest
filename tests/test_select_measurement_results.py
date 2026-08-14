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


if __name__ == "__main__":
    unittest.main()
