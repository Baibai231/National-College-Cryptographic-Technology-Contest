import gzip
import unittest
from unittest import mock

from scripts.preflight_targets import _decode_body, _charset, preflight_one
from utils.static_auth_discovery import extract_static_auth_signals


class PreflightTargetsTest(unittest.TestCase):
    def test_truncated_gzip_returns_decoded_prefix(self):
        original = (b"<html><body>signup</body></html>" * 1000)
        compressed = gzip.compress(original)
        decoded = _decode_body(compressed[:len(compressed) // 2], "gzip")
        self.assertTrue(decoded.startswith(b"<html>"))
        self.assertLess(len(decoded), len(original))

    def test_charset_parsing(self):
        self.assertEqual(_charset("text/html; charset=gb18030"), "gb18030")
        self.assertEqual(_charset("text/html"), "utf-8")

    def test_shallow_crawl_follows_login_then_signup(self):
        pages = {
            "https://example.com/": "<a href='/login'>Log in</a>",
            "https://example.com/login": "<a href='/signup'>Sign up</a>",
            "https://example.com/signup": (
                "<form><input type='email'><input type='password' "
                "autocomplete='new-password' minlength='12'>"
                "<small>Password must be at least 12 characters</small></form>"),
        }

        def fake_fetch(url, _timeout, _max_bytes):
            html = pages[url]
            return {
                "requested_url": url,
                "final_url": url,
                "status_code": 200,
                "content_type": "text/html",
                "bytes_read": len(html),
                "signals": extract_static_auth_signals(html, url),
            }

        with mock.patch(
                "scripts.preflight_targets._fetch_page",
                side_effect=fake_fetch) as fetch:
            result = preflight_one({
                "domain": "example.com", "url": "https://example.com/",
                "rank": 1, "source": "fixture",
            }, timeout=1, max_bytes=4096, max_pages=3)

        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(result["signals"]["pages_checked"], 3)
        self.assertEqual(
            result["signup_url_hint"], "https://example.com/signup")
        self.assertEqual(
            result["signals"]["declared_password_policy"]["length_min"], 12)

    def test_password_on_later_login_page_does_not_validate_product_cta(self):
        pages = {
            "https://example.com/": (
                "<a class='registration' href='/products'>Get started</a>"
                "<a href='/login'>Log in</a>"),
            "https://example.com/login": (
                "<form><input type='email'><input type='password'></form>"),
        }

        def fake_fetch(url, _timeout, _max_bytes):
            html = pages[url]
            return {
                "requested_url": url, "final_url": url, "status_code": 200,
                "content_type": "text/html", "bytes_read": len(html),
                "signals": extract_static_auth_signals(html, url),
            }

        with mock.patch(
                "scripts.preflight_targets._fetch_page", side_effect=fake_fetch):
            result = preflight_one({
                "domain": "example.com", "url": "https://example.com/",
                "rank": 1, "source": "fixture",
            }, timeout=1, max_bytes=4096, max_pages=3)

        self.assertNotIn("signup_url_hint", result)


if __name__ == "__main__":
    unittest.main()
