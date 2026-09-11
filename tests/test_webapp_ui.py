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
        self.assertIn("有口令框", self.html)
        self.assertIn("reportTableHtml", self.html)
        # 用户要求删除的：主类型行、主方法、方法状态词、步骤展示、长原因
        self.assertNotIn("主类型", self.html)
        self.assertNotIn("主方法：", self.html)
        self.assertNotIn("已确认", self.html)
        self.assertNotIn("需验证", self.html)
        self.assertNotIn("方法说明", self.html)
        self.assertNotIn("comparison.reason}", self.html)
        self.assertNotIn("switchStepTab", self.html)
        self.assertNotIn("stepsHtml", self.html)

    def test_manual_review_has_structured_method_builder(self):
        # v4.2：人工提交改为结构化方法填词（勾选要素自动 + 连接）
        self.assertIn("addMethodRow('review-login')", self.html)
        self.assertIn("addMethodRow('review-signup')", self.html)
        self.assertIn("readMethodRows('review-login')", self.html)
        self.assertIn("methodElements", self.html)
        self.assertIn("手机号", self.html)
        self.assertIn("无注册界面", self.html)
        self.assertIn("无登录界面", self.html)
        # 自由文本输入与旧结构化核验已删除
        self.assertNotIn("traitForm", self.html)
        self.assertNotIn("parseMethodLines", self.html)
        self.assertNotIn("review-login\").value", self.html)

    def test_page_periodically_refreshes_without_interrupting_modals(self):
        self.assertIn("setInterval", self.html)
        self.assertIn("modalOpen", self.html)
        self.assertIn("30000", self.html)

    def test_accuracy_and_coverage_are_both_visible(self):
        self.assertIn("stat-coverage", self.html)
        self.assertIn("stat-login-coverage", self.html)

    def test_policy_result_falls_back_to_classification_table(self):
        # 无口令框或政策测试未完成时，按注册分类展示，口令政策留空
        self.assertIn("isPolicyMeasured", self.html)
        self.assertIn("classificationOnlyTableHtml", self.html)
        self.assertIn("注册与分类", self.html)
        self.assertIn("密码政策测试未完成，仅输出注册与分类结果", self.html)
        # 现场分类已改异步任务队列：口令政策任务后台执行
        self.assertIn("我的测量任务", self.html)
        self.assertIn("/api/tasks", self.html)
        self.assertIn("task-tbody", self.html)
        self.assertIn("填写上方测量口令后可查看和管理实时任务", self.html)
        self.assertIn("if (!measureTokenInput.value.trim())", self.html)

    def test_policy_result_labels_measured_method_without_method_list(self):
        # 测到口令政策时，方法清单直接写"进行密码政策测试"
        self.assertIn("进行密码政策测试", self.html)

    def test_policy_result_exposes_adaptive_probe_evidence(self):
        self.assertIn("adaptivePolicyHtml", self.html)
        self.assertIn("自适应探测证据", self.html)
        self.assertIn("此决策证据不保存候选口令原文", self.html)
        self.assertIn("probes_saved_vs_worst_case", self.html)
        self.assertIn("_adaptive_composition", self.html)
        self.assertIn("已接受的最小组合", self.html)
        self.assertIn("固定必需类", self.html)
        self.assertIn("_adaptive_conditional", self.html)
        self.assertIn("长度×组成条件政策", self.html)
        self.assertIn("阈值接受结果使用第二个同结构候选复验", self.html)

    def test_repeat_measurement_control_bypasses_database_cache(self):
        self.assertIn('id="force-retest"', self.html)
        self.assertIn("重复测试（忽略数据库，重新打开网站测量）", self.html)
        self.assertIn("force_retest: forceRetest", self.html)
        self.assertIn("点击“加入数据库”后才会覆盖正式数据", self.html)

    def test_passive_security_observations_are_labeled_with_evidence_boundary(self):
        self.assertIn("securityObservationsHtml", self.html)
        self.assertIn("安全能力被动观察", self.html)
        self.assertIn("MFA是否强制：未确定", self.html)
        self.assertIn("传输安全：", self.html)
        self.assertIn("安全响应头：", self.html)
        self.assertIn("账户恢复：", self.html)
        self.assertIn("未进入恢复流程", self.html)
        self.assertIn("不额外请求网站", self.html)
        self.assertIn("“未观察到”不等于“不支持”", self.html)
        self.assertIn("已知证据得分", self.html)
        self.assertIn("未知项不扣分", self.html)
        self.assertIn("不同覆盖率的分数不可直接比较", self.html)
        self.assertIn("CPAM：", self.html)
        self.assertIn("非完整成熟度等级", self.html)

    def test_db_policy_table_uses_two_columns_when_measured(self):
        # 实测口令政策入库后，详情表只保留"密码政策测试"两列，不加登录/注册
        self.assertIn('colspan="2" class="text-center">密码政策测试', self.html)

    def test_db_policy_table_falls_back_to_three_column_classification(self):
        # 未实测时按注册+分类展示三列：条目 + 登录 + 注册
        self.assertIn('colspan="3" class="text-center">注册与分类', self.html)
        self.assertIn("<th>登录（程序）</th><th>注册（程序）</th>", self.html)


class PolicyApiTests(unittest.TestCase):
    def test_policy_response_exposes_measured_flag(self):
        app_src = (Path(__file__).parents[1] / "webapp" / "app.py").read_text(
            encoding="utf-8")
        self.assertIn('"policy_measured": True', app_src)
        self.assertIn('response["policy_measured"] = False', app_src)


if __name__ == "__main__":
    unittest.main()
