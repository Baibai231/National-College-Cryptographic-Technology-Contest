"""Security regression tests for the browser measurement control plane."""

import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException

import webapp.app as web_app


class MeasurementAccessTests(unittest.TestCase):
    def test_measurement_is_closed_when_no_access_mode_is_configured(self):
        with patch.dict(os.environ, {
            "SITES_MEASURE_TOKEN": "",
            "SITES_ADMIN_TOKEN": "",
            "SITES_ALLOW_PUBLIC_MEASUREMENT": "",
        }):
            with self.assertRaises(HTTPException) as raised:
                web_app._require_measure_access("")
        self.assertEqual(raised.exception.status_code, 503)

    def test_dedicated_measurement_token_is_checked(self):
        with patch.dict(os.environ, {
            "SITES_MEASURE_TOKEN": "correct-horse-battery-staple",
            "SITES_ADMIN_TOKEN": "different-admin-token",
            "SITES_ALLOW_PUBLIC_MEASUREMENT": "",
        }):
            web_app._require_measure_access("correct-horse-battery-staple")
            with self.assertRaises(HTTPException) as raised:
                web_app._require_measure_access("wrong")
        self.assertEqual(raised.exception.status_code, 403)

    def test_anonymous_measurement_requires_explicit_opt_in(self):
        with patch.dict(os.environ, {
            "SITES_MEASURE_TOKEN": "",
            "SITES_ADMIN_TOKEN": "",
            "SITES_ALLOW_PUBLIC_MEASUREMENT": "true",
        }):
            web_app._require_measure_access("")


class MeasurementTargetTests(unittest.TestCase):
    @patch("webapp.app.socket.getaddrinfo")
    def test_submit_rejects_hostname_resolving_to_private_address(self, resolve):
        resolve.return_value = [
            (web_app.socket.AF_INET, web_app.socket.SOCK_STREAM, 6, "",
             ("127.0.0.1", 443)),
        ]
        request = web_app.TaskSubmitRequest(url="https://attacker.example")
        with patch.dict(os.environ, {"SITES_MEASURE_TOKEN": "secret"}):
            with self.assertRaises(HTTPException) as raised:
                web_app.submit_task(request, measure_token="secret")
        self.assertEqual(raised.exception.status_code, 400)

    @patch("webapp.app._validated_classify_url")
    def test_submit_rejects_when_waiting_queue_is_full(self, validate):
        validate.return_value = ("https://example.com", "example.com")
        request = web_app.TaskSubmitRequest(url="https://example.com")
        with patch.dict(os.environ, {"SITES_MEASURE_TOKEN": "secret"}), \
                patch.object(web_app, "_TASK_QUEUE", [{"task_id": "busy"}]), \
                patch.object(web_app, "_TASK_QUEUE_MAX", 1):
            with self.assertRaises(HTTPException) as raised:
                web_app.submit_task(request, measure_token="secret")
        self.assertEqual(raised.exception.status_code, 429)
        validate.assert_called_once_with("https://example.com", resolve=True)


class TaskCompletionTests(unittest.TestCase):
    @patch("webapp.app._save_tasks")
    @patch("webapp.app._load_tasks", return_value={})
    def test_deleted_running_task_is_not_resurrected(self, _load, save):
        persisted = web_app._persist_finished_task({
            "task_id": "deleted", "status": "done", "result": {"ok": True},
        })
        self.assertFalse(persisted)
        save.assert_not_called()

    @patch("webapp.app._save_tasks")
    @patch("webapp.app._load_tasks")
    def test_timed_out_running_task_is_not_overwritten(self, load, save):
        load.return_value = {
            "stale": {"task_id": "stale", "status": "error", "_removed": True},
        }
        persisted = web_app._persist_finished_task({
            "task_id": "stale", "status": "done", "result": {"ok": True},
        })
        self.assertFalse(persisted)
        save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
