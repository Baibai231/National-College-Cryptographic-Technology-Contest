import unittest
from unittest.mock import patch

import webapp.app as web_app


class WebAppRetestTests(unittest.TestCase):
    def test_both_force_retest_skips_database_and_runs_both_sides(self):
        def live_result(url, kind):
            return {"url": url, "entry_kind": kind, "flow_type": "direct"}

        with patch.object(web_app, "_db_entry_for") as read_db, \
                patch.object(web_app, "_run_live_classification",
                             side_effect=live_result) as run_live:
            result = web_app._run_task_both(
                "https://example.com", force_retest=True)

        read_db.assert_not_called()
        self.assertEqual(run_live.call_count, 2)
        self.assertFalse(result["signup_from_database"])
        self.assertFalse(result["login_from_database"])
        self.assertEqual(result["signup"]["entry_kind"], "signup")
        self.assertEqual(result["login"]["entry_kind"], "login")

    def test_both_keeps_existing_cache_behavior_by_default(self):
        cached = {"flow_type": "direct", "flow_zh": "直接"}
        with patch.object(web_app, "_db_entry_for", return_value=cached), \
                patch.object(web_app, "_run_live_classification") as run_live:
            result = web_app._run_task_both("https://example.com")

        run_live.assert_not_called()
        self.assertTrue(result["signup_from_database"])
        self.assertTrue(result["login_from_database"])

    def test_policy_force_retest_skips_cached_policy(self):
        live = {
            "url": "https://example.com",
            "entry_kind": "signup",
            "policy": {"length": [8, 64]},
            "policy_measured": True,
        }
        with patch.object(web_app, "_db_entry_for") as read_db, \
                patch.object(web_app, "_run_live_policy",
                             return_value=live.copy()) as run_live:
            result = web_app._run_task_policy(
                "https://example.com", "auto", force_retest=True)

        read_db.assert_not_called()
        run_live.assert_called_once_with("https://example.com", "auto")
        self.assertEqual(result["hostname"], "example.com")
        self.assertNotIn("from_database", result)

    def test_incomplete_cached_policy_is_remeasured(self):
        cached = {
            "flow_type": "direct_password",
            "final_url": "https://example.com/signup",
            "pwd_method": "inline",
            "pwd_policy": {"length": [8, 64], "restrictive": {}},
        }
        live = {
            "url": "https://example.com", "policy_measured": False,
            "measurement_quality": {"complete": False, "status": "partial"},
        }
        with patch.object(web_app, "_db_entry_for", return_value=cached), \
                patch.object(web_app, "_run_live_policy",
                             return_value=live.copy()) as run_live:
            result = web_app._run_task_policy("https://example.com", "auto")

        run_live.assert_called_once_with("https://example.com", "auto")
        self.assertFalse(result["policy_measured"])

    def test_complete_cached_policy_is_reused(self):
        restrictive = {
            "r_no_a_sps": False, "r_2_word": False, "r_l_start": False,
            "r_dig_min": 0, "r_upp_min": 0, "r_low_min": 0, "r_sps_min": 0,
            "r_cmb13": False, "r_cmb23": False, "r_cmb33": False,
            "r_cmb14": False, "r_cmb24": False, "r_cmb34": False,
            "r_cmb44": False,
        }
        permissive = {
            "permitted_characters": dict.fromkeys(
                ("p_space", "p_unicd", "p_emoji", "p_spn1", "p_spn2", "p_spn3", "p_spn4"), False),
            "permitted_sequences": dict.fromkeys(
                ("p_rep", "p_seq", "p_dict", "p_info"), False),
            "short_and_long_password": {"p_longd": False, "p_shortd": False},
            "breached_password": {"p_br": True},
        }
        cached = {
            "flow_type": "direct_password",
            "final_url": "https://example.com/signup",
            "pwd_method": "inline",
            "pwd_policy": {
                "length": [8, 64], "restrictive": restrictive,
                "permissive": permissive,
                "_probe_evidence": [
                    {"outcome": "rejected"}, {"outcome": "accepted"}],
            },
        }
        with patch.object(web_app, "_db_entry_for", return_value=cached), \
                patch.object(web_app, "_run_live_policy") as run_live:
            result = web_app._run_task_policy("https://example.com", "auto")

        run_live.assert_not_called()
        self.assertTrue(result["from_database"])
        self.assertTrue(result["measurement_quality"]["complete"])

    def test_task_snapshot_exposes_retest_flag_with_safe_default(self):
        self.assertFalse(web_app._task_snapshot({})["force_retest"])
        self.assertTrue(web_app._task_snapshot(
            {"force_retest": True})["force_retest"])


if __name__ == "__main__":
    unittest.main()
