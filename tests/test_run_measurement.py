import json
import tempfile
import unittest
from pathlib import Path

from scripts.run_measurement import _resume_completed_keys, _task_shard


class RunMeasurementSchedulingTests(unittest.TestCase):
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
