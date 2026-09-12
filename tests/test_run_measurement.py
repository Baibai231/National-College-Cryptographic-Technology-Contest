import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from scripts.run_measurement import (
    _browser_session_lost,
    main as run_measurement_main,
    _partial_checkpoint_path,
    _recover_timeout_checkpoint,
    _resume_completed_keys,
    _stop_worker_process_tree,
    _task_host,
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

    def test_timeout_cleanup_stops_worker_and_browser_children(self):
        worker = mock.MagicMock()
        worker.pid = 1234
        worker.is_alive.return_value = False
        child = mock.MagicMock()
        child.is_running.return_value = True
        process_factory = mock.MagicMock()
        fake_psutil = types.SimpleNamespace(
            Process=process_factory,
            NoSuchProcess=type("NoSuchProcess", (Exception,), {}),
            AccessDenied=type("AccessDenied", (Exception,), {}),
        )
        process_factory.return_value.children.return_value = [child]
        with mock.patch.dict(sys.modules, {"psutil": fake_psutil}):
            _stop_worker_process_tree(worker, join_timeout=0.01)

        process_factory.assert_called_once_with(1234)
        child.terminate.assert_called_once_with()
        child.kill.assert_called_once_with()
        worker.terminate.assert_called_once_with()

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

    def test_task_host_normalizes_case_and_trailing_dot(self):
        self.assertEqual(_task_host("https://WWW.Example.COM./login"),
                         "www.example.com")

    def test_same_host_signup_and_login_are_serialized(self):
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "sites.txt"
            input_path.write_text("https://same.example/\n", encoding="utf-8")
            output_path = Path(directory) / "records.jsonl"
            counters = {"active": 0, "max_active": 0}
            counter_lock = threading.Lock()

            def fake_classify(site, kind, **_kwargs):
                with counter_lock:
                    counters["active"] += 1
                    counters["max_active"] = max(
                        counters["max_active"], counters["active"])
                time.sleep(0.05)
                with counter_lock:
                    counters["active"] -= 1
                return {
                    "site": site, "hostname": "same.example",
                    "entry_kind": kind, "flow_type": "no_web_signup",
                    "measurement_quality": {"status": "classified"},
                }

            argv = [
                "run_measurement.py", "--input", str(input_path),
                "--kinds", "signup,login", "--output", str(output_path),
                "--workers", "2", "--checkpoint-every", "0",
            ]
            with mock.patch.object(sys, "argv", argv), mock.patch(
                    "scripts.run_measurement.classify_one",
                    side_effect=fake_classify):
                run_measurement_main()

        self.assertEqual(counters["max_active"], 1)

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

    def test_authorization_manifest_filters_batch_and_stamps_records(self):
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "sites.txt"
            input_path.write_text(
                "https://example.com/\nhttps://other.example/\n",
                encoding="utf-8")
            scope_path = Path(directory) / "scope.txt"
            scope_path.write_text("example.com\n", encoding="utf-8")
            output_path = Path(directory) / "records.jsonl"
            fake = {
                "site": "https://example.com/",
                "hostname": "example.com",
                "entry_kind": "signup",
                "flow_type": "no_web_signup",
                "measurement_quality": {"status": "classified"},
            }
            argv = [
                "run_measurement.py", "--input", str(input_path),
                "--authorization-manifest", str(scope_path),
                "--kinds", "signup", "--output", str(output_path),
                "--workers", "1", "--checkpoint-every", "0",
            ]
            with mock.patch.object(sys, "argv", argv), mock.patch(
                    "scripts.run_measurement.classify_one",
                    return_value=fake):
                run_measurement_main()

            records = [json.loads(line) for line in output_path.read_text(
                encoding="utf-8").splitlines() if line.strip()]

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["hostname"], "example.com")
        self.assertEqual(len(records[0]["authorization_scope_id"]), 16)


if __name__ == "__main__":
    unittest.main()
