import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from webapp import local_server


class LocalServerTests(unittest.TestCase):
    def test_launcher_records_actual_server_pid_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            pid_path = Path(tmp) / "dashboard.pid"

            def inspect_record(*args, **kwargs):
                record = json.loads(pid_path.read_text(encoding="utf-8"))
                self.assertEqual(record["pid"], local_server.os.getpid())
                self.assertEqual(
                    Path(record["project_root"]), local_server.PROJECT_ROOT)
                self.assertEqual(kwargs["host"], "127.0.0.1")
                self.assertEqual(kwargs["port"], 8123)

            with patch.object(local_server.uvicorn, "run",
                              side_effect=inspect_record):
                local_server.main([
                    "--port", "8123", "--pid-file", str(pid_path)])

            self.assertFalse(pid_path.exists())


if __name__ == "__main__":
    unittest.main()
