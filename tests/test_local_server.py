import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from webapp import local_server
from utils import util_test_password


class LocalServerTests(unittest.TestCase):
    def test_browser_driver_cache_can_be_kept_inside_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_uc = SimpleNamespace(Patcher=SimpleNamespace(data_path=""))
            with patch.dict("os.environ", {"SITES_DRIVER_CACHE_DIR": tmp}):
                path = util_test_password._configure_uc_data_path(fake_uc)
            self.assertEqual(path, str(Path(tmp) / "undetected_chromedriver"))
            self.assertEqual(fake_uc.Patcher.data_path, path)
            self.assertTrue(Path(path).is_dir())

    def test_explicit_edge_binary_is_discovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            edge = Path(tmp) / "msedge.exe"
            edge.touch()
            with patch.dict("os.environ", {"SITES_EDGE_BIN": str(edge)}):
                self.assertEqual(
                    util_test_password._find_browser_binary("edge"), str(edge))

    def test_server_requirements_include_python_312_distutils_shim(self):
        requirements = (
            local_server.PROJECT_ROOT / "webapp" / "requirements-server.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("setuptools>=68", requirements)

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
