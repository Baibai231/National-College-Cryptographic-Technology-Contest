import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts import run_measurement
from utils import util_test_password


class BatchBrowserSafetyTests(unittest.TestCase):
    def test_detects_chrome_startup_failures(self):
        for message in (
            "session not created: cannot connect to chrome",
            "chrome not reachable",
            "DevToolsActivePort file doesn't exist",
        ):
            self.assertTrue(run_measurement._is_chrome_startup_failure(
                {"error": message}))

    def test_does_not_mislabel_site_failures_as_startup_failures(self):
        self.assertFalse(run_measurement._is_chrome_startup_failure(
            {"error": "site_timeout:900s"}))
        self.assertFalse(run_measurement._is_chrome_startup_failure(
            {"error": None}))

    def test_parallel_macos_batch_defaults_to_headless(self):
        args = SimpleNamespace(headless=False, headful=False, workers=3)
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(run_measurement.sys, "platform", "darwin"):
            note = run_measurement._configure_browser_mode(args)
            self.assertEqual(os.environ.get("SITES_HEADLESS"), "1")
            self.assertIn("无头", note)
            self.assertEqual(args.workers, 3)

    def test_explicit_macos_headful_batch_is_single_worker(self):
        args = SimpleNamespace(headless=False, headful=True, workers=3)
        with mock.patch.dict(os.environ, {"SITES_HEADLESS": "1"}, clear=True), \
                mock.patch.object(run_measurement.sys, "platform", "darwin"):
            note = run_measurement._configure_browser_mode(args)
            self.assertNotIn("SITES_HEADLESS", os.environ)
            self.assertEqual(args.workers, 1)
            self.assertIn("单并发", note)

    def test_cached_driver_must_match_browser_major(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = (Path(tmp) / ".wdm" / "drivers" / "chromedriver" /
                    "mac64")
            old = root / "151" / "chromedriver"
            current = root / "152" / "chromedriver"
            old.parent.mkdir(parents=True)
            current.parent.mkdir(parents=True)
            # Mach-O magic makes both files valid driver candidates; the old
            # one is deliberately larger to prove size no longer wins.
            old.write_bytes(b"\xcf\xfa\xed\xfe" + b"x" * 100)
            current.write_bytes(b"\xcf\xfa\xed\xfe" + b"x" * 20)

            def fake_major(path):
                return 151 if "/151/" in str(path) else 152

            with mock.patch.dict(os.environ, {"HOME": tmp}), \
                    mock.patch.object(util_test_password,
                                      "_binary_version_major",
                                      side_effect=fake_major):
                chosen = util_test_password._find_cached_chromedriver(152)
            self.assertEqual(chosen, str(current))

    def test_version_parser(self):
        self.assertEqual(util_test_password._version_major(
            "Google Chrome 152.0.7977.76"), 152)
        self.assertEqual(util_test_password._version_major(
            "ChromeDriver 151.0.7922.138"), 151)


if __name__ == "__main__":
    unittest.main()
