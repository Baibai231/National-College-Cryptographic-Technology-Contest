import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.run_measurement import (
    _browser_session_lost,
    _partial_checkpoint_path,
    _recover_timeout_checkpoint,
    _resume_completed_keys,
    _task_shard,
)


class RunMeasurementSchedulingTests(unittest.TestCase):
    def test_checkpoint_path_cannot_escape_logs_directory(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch(
                "scripts.run_measurement._PROJECT_ROOT", directory):
            path = Path(_partial_checkpoint_path("../../outside")).resolve()
            logs = (Path(directory) / "logs").resolve()

        self.assertEqual(path, logs / "unknown" / "policy_unknown.partial.json")

    def test_checkpoint_path_accepts_plain_hostname(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch(
                "scripts.run_measurement._PROJECT_ROOT", directory):
            path = Path(_partial_checkpoint_path("example.com")).resolve()
            expected = (Path(directory) / "logs" / "example.com" /
                        "policy_example.com.partial.json").resolve()

        self.assertEqual(path, expected)

    def test_closed_window_is_retryable_once_by_batch_wrapper(self):
        self.assertTrue(_browser_session_lost({
            "error": "Message: no such window: target window already closed"
        }))
        self.assertFalse(_browser_session_lost({"error": "dns failed"}))

    def test_timeout_recovers_only_fresh_probe_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch(
                    "scripts.run_measurement._PROJECT_ROOT", directory):
            checkpoint = Path(directory) / "logs" / "example.com" / \
                "policy_example.com.partial.json"
            checkpoint.parent.mkdir(parents=True)
            checkpoint.write_text(json.dumps({
                "url": "https://example.com/signup",
                "hostname": "example.com",
                "stage": "length_done",
                "policy": {
                    "length": [8, 64],
                    "_probe_evidence": [
                        {"password_length": 1, "outcome": "rejected"},
                        {"password_length": 8, "outcome": "accepted"},
                    ],
                },
            }), encoding="utf-8")
            started = os.path.getmtime(checkpoint)

            record = _recover_timeout_checkpoint(
                "https://example.com/", "signup", started, 300)

        self.assertEqual(record["checkpoint_stage"], "length_done")
        self.assertEqual(record["attempted_method"], "partial_timeout")
        self.assertEqual(record["partial_policy"]["length"], [8, 64])
        self.assertEqual(record["measurement_quality"]["status"], "partial")

    def test_timeout_ignores_stale_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch(
                    "scripts.run_measurement._PROJECT_ROOT", directory):
            checkpoint = Path(directory) / "logs" / "example.com" / \
                "policy_example.com.partial.json"
            checkpoint.parent.mkdir(parents=True)
            checkpoint.write_text(json.dumps({
                "policy": {"_probe_evidence": [{"outcome": "accepted"}]},
            }), encoding="utf-8")
            os.utime(checkpoint, (1, 1))

            record = _recover_timeout_checkpoint(
                "https://example.com/", "signup", 100, 300)

        self.assertNotIn("partial_policy", record)

    def test_shards_are_deterministic_and_in_range(self):
        first = _task_shard("https://example.com/", 7)
        self.assertEqual(first, _task_shard("https://example.com/path", 7))
        self.assertGreaterEqual(first, 0)
        self.assertLess(first, 7)

    def test_complete_resume_retries_partial_latest_record(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "records.jsonl"
            records = [
                {"site": "https://a.test", "entry_kind": "signup",
                 "measurement_quality": {"complete": True}},
                {"site": "https://b.test", "entry_kind": "signup",
                 "measurement_quality": {"complete": False}},
            ]
            output.write_text("".join(
                json.dumps(record) + "\n" for record in records),
                encoding="utf-8")

            complete = _resume_completed_keys(str(output), "complete")
            any_record = _resume_completed_keys(str(output), "any")

        self.assertEqual(complete, {("https://a.test", "signup")})
        self.assertEqual(len(any_record), 2)


if __name__ == "__main__":
    unittest.main()
