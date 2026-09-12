import unittest

from utils.policy_quality import (
    aggregate_policy_records,
    evaluate_policy_record,
)


def complete_record(host="example.com"):
    return {
        "site": "https://" + host,
        "hostname": host,
        "entry_kind": "signup",
        "measured_at": "2026-09-11T00:00:00+00:00",
        "flow_type": "direct_password",
        "final_url": "https://" + host + "/signup",
        "method_used": "inline",
        "error": None,
        "states": [{"fields": ["email", "password"]}],
        "policy": {
            "length": [8, 64],
            "restrictive": {
                "r_no_a_sps": False, "r_2_word": False,
                "r_l_start": False, "r_dig_min": 1,
                "r_upp_min": 0, "r_low_min": 0, "r_sps_min": 0,
                "r_cmb13": False, "r_cmb23": False,
                "r_cmb33": False, "r_cmb14": False,
                "r_cmb24": False, "r_cmb34": True,
                "r_cmb44": False,
            },
            "permissive": {
                "permitted_characters": {
                    "p_space": True, "p_unicd": True, "p_emoji": True,
                    "p_spn1": True, "p_spn2": True,
                    "p_spn3": True, "p_spn4": True,
                },
                "permitted_sequences": {
                    "p_rep": True, "p_seq": True,
                    "p_dict": True, "p_info": True,
                },
                "short_and_long_password": {
                    "p_longd": True, "p_shortd": False,
                },
                "breached_password": {"p_br": False},
            },
            "_probe_evidence": [
                {"outcome": "rejected", "password_length": 1},
                {"outcome": "accepted", "password_length": 12},
            ],
        },
    }


class PolicyQualityTest(unittest.TestCase):
    def test_complete_active_measurement_passes(self):
        quality = evaluate_policy_record(complete_record())
        self.assertTrue(quality["complete"])
        self.assertEqual(quality["status"], "complete")
        self.assertEqual(quality["reasons"], [])

    def test_classification_policy_never_counts_as_complete(self):
        record = complete_record()
        record["method_used"] = "classified_only"
        record["policy"] = {
            "measurement": {"status": "classified"},
            "authentication": {"password_observed": True},
        }
        quality = evaluate_policy_record(record)
        self.assertFalse(quality["complete"])
        self.assertIn("active_policy_measurement_not_run", quality["reasons"])

    def test_hint_without_controls_is_partial_not_complete(self):
        record = complete_record()
        record["policy"].pop("_probe_evidence")
        record["policy"]["_hint_policy"] = {"minimum_length": 8}
        quality = evaluate_policy_record(record)
        self.assertFalse(quality["complete"])
        self.assertIn("accepted_control_missing", quality["reasons"])
        self.assertIn("rejected_control_missing", quality["reasons"])

    def test_partial_policy_is_evaluated_after_classification_fallback(self):
        record = complete_record()
        measured = record["policy"]
        measured["_inconclusive"] = True
        record["policy"] = {"schema_version": "1.0"}
        record["partial_policy"] = measured
        record["method_used"] = "classified_only"
        record["attempted_method"] = "inline"
        quality = evaluate_policy_record(record)
        self.assertEqual(quality["status"], "partial")
        self.assertTrue(quality["stages"]["active_measurement_run"])
        self.assertIn("policy_marked_inconclusive", quality["reasons"])

    def test_inconclusive_measurement_is_rejected(self):
        record = complete_record()
        record["policy"]["_inconclusive"] = True
        quality = evaluate_policy_record(record)
        self.assertFalse(quality["complete"])
        self.assertIn("policy_marked_inconclusive", quality["reasons"])

    def test_protocol_scoped_no_maximum_is_complete(self):
        record = complete_record()
        record["policy"]["length"] = [8, None]
        record["policy"]["_adaptive"] = {
            "maximum": {
                "status": "not_observed_within_range",
                "searched_to": 128,
                "reason": "search_ceiling_accepted",
            }
        }
        quality = evaluate_policy_record(record)
        self.assertTrue(quality["complete"])
        self.assertEqual(
            quality["length_scope"], "no_maximum_observed_through_128")

    def test_bare_null_maximum_remains_incomplete(self):
        record = complete_record()
        record["policy"]["length"] = [8, None]
        quality = evaluate_policy_record(record)
        self.assertFalse(quality["complete"])
        self.assertIn("length_boundary_incomplete", quality["reasons"])

    def test_aggregate_counts_latest_signup_record_once_per_host(self):
        old = complete_record("one.example")
        old["measured_at"] = "2026-09-10T00:00:00+00:00"
        new = complete_record("one.example")
        new["measured_at"] = "2026-09-11T00:00:00+00:00"
        login = complete_record("two.example")
        login["entry_kind"] = "login"
        summary = aggregate_policy_records([old, new, login])
        self.assertEqual(summary["distinct_signup_sites"], 1)
        self.assertEqual(summary["complete_sites"], 1)
        self.assertEqual(summary["remaining_sites"], 999)


if __name__ == "__main__":
    unittest.main()
