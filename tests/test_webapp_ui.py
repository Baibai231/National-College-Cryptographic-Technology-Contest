import unittest
from pathlib import Path


class WebAppUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (Path(__file__).parents[1] / "webapp" / "static" / "index.html").read_text(
            encoding="utf-8")

    def test_cards_show_compact_side_badges_instead_of_long_reasons(self):
        # v4 设计：卡片只显示"登录识别正确/错误/待核验"徽标，长原因只在详情里
        self.assertIn("sideBadge('登录', s.login_match)", self.html)
        self.assertIn("sideBadge('注册', s.signup_match)", self.html)
        self.assertIn("识别正确", self.html)
        self.assertIn("识别错误", self.html)
        # 卡片不再渲染大段对照文字
        self.assertNotIn("comparison.reason}", self.html)

    def test_detail_uses_structured_program_vs_manual_table(self):
        self.assertIn("compRow('登录'", self.html)
        self.assertIn("compRow('注册'", self.html)
        self.assertIn("<th>程序</th>", self.html)
        self.assertIn("<th>人工</th>", self.html)
        self.assertIn("方法${num}", self.html)
        self.assertIn("门槛阻拦", self.html)
        self.assertIn("确认可用", self.html)
        self.assertIn("'步骤' + s + ' · '", self.html)

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
