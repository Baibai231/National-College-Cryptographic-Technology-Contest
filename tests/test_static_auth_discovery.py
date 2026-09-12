import unittest

from utils.static_auth_discovery import (
    extract_static_auth_signals,
    preflight_priority,
)


class StaticAuthDiscoveryTest(unittest.TestCase):
    def test_extracts_signup_link_and_password_constraints(self):
        html = """
        <html><head><title>创建账户</title></head><body>
          <a class="account" href="https://accounts.example.com/register">注册</a>
          <form><input type="email" name="email">
          <input type="password" autocomplete="new-password"
                 minlength="8" maxlength="64" pattern=".+" required>
          <small>Password must be at least 8 characters</small></form>
        </body></html>
        """
        signals = extract_static_auth_signals(html, "https://www.example.com/")
        self.assertEqual(signals["password_input_count"], 1)
        self.assertEqual(signals["new_password_input_count"], 1)
        self.assertEqual(signals["email_input_count"], 1)
        self.assertEqual(
            signals["signup_candidates"][0]["url"],
            "https://accounts.example.com/register")
        self.assertEqual(signals["observed_signup_candidate_count"], 1)
        self.assertEqual(signals["static_password_constraints"][0]["minlength"], 8)
        self.assertEqual(signals["declared_password_policy"]["length_min"], 8)
        self.assertGreaterEqual(preflight_priority(signals), 150)

    def test_content_page_has_low_priority(self):
        signals = extract_static_auth_signals(
            "<html><title>News</title><body><a href='/article'>Story</a></body></html>",
            "https://example.com/",
        )
        # Generated common paths are weak evidence but should not make a
        # content-only page look directly measurable.
        self.assertLess(preflight_priority(signals), 100)
        self.assertEqual(signals["password_input_count"], 0)
        self.assertEqual(signals["observed_signup_candidate_count"], 0)


if __name__ == "__main__":
    unittest.main()
