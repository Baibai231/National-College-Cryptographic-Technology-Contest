import unittest
from pathlib import Path


class WebAppUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (Path(__file__).parents[1] / "webapp" / "static" / "index.html").read_text(
            encoding="utf-8")

    def test_cards_proactively_show_mismatch_reason(self):
        self.assertIn("为什么错误", self.html)
        self.assertIn("s.login_match", self.html)
        self.assertIn("status === 'mismatch'", self.html)

    def test_cards_show_login_and_signup_reasons_independently(self):
        self.assertIn("sideReason('登录', s.login_match", self.html)
        self.assertIn("sideReason('注册', s.signup_match", self.html)

    def test_manual_review_has_structured_inputs(self):
        self.assertIn("结构化核验", self.html)
        self.assertIn("traitForm('review-signup')", self.html)
        self.assertIn('${prefix}-password', self.html)

    def test_page_periodically_refreshes_without_interrupting_modals(self):
        self.assertIn("setInterval", self.html)
        self.assertIn("modalOpen", self.html)
        self.assertIn("30000", self.html)

    def test_accuracy_and_coverage_are_both_visible(self):
        self.assertIn("stat-coverage", self.html)
        self.assertIn("stat-login-coverage", self.html)


if __name__ == "__main__":
    unittest.main()
