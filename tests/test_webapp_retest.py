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

    def test_task_snapshot_exposes_retest_flag_with_safe_default(self):
        self.assertFalse(web_app._task_snapshot({})["force_retest"])
        self.assertTrue(web_app._task_snapshot(
            {"force_retest": True})["force_retest"])


if __name__ == "__main__":
    unittest.main()
