"""
full_form_tester.py — 完整表单密码政策测试编排器

等价于 utils/util_test_password.py 的 TestPassword 类，
但适用于需要完整填表 + 提交后才能获取密码合规反馈的注册页。

复用（import，非复制）:
  - utils.login_link_discovery.LoginLinkDiscovery  注册页发现
  - utils.util_basic.random_sleep                   延迟工具
  - utils.util_str_generator                       密码/字符串生成

与原有 TestPassword 保持相同的方法签名:
  - test_one_password(password, info_name) -> bool
  - find_admissible_password() -> str
  - check_special_symbols() 等 14 项策略测试方法
"""

import os
import sys
import time
import traceback
from typing import List, Dict, Optional

from loguru import logger

import utils.util_basic as uub
import utils.util_str_generator as uusg
from utils.login_link_discovery import LoginLinkDiscovery

from .rate_controller import RateController
from .data_generator import DataGenerator
from .password_error_parser import PasswordErrorParser
from .field_classifier import (
    FieldClassifier,
    FIELD_PASSWORD, FIELD_CONFIRM_PASSWORD,
    FIELD_CHECKBOX_TERMS, FIELD_CAPTCHA,
)
from .form_submitter import FormSubmitter


def _admissible_cache_path(test_site: str) -> str:
    """返回 admissible 缓存路径，每个站点独立文件夹"""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    site_dir = os.path.join(project_root, "logs", test_site)
    os.makedirs(site_dir, exist_ok=True)
    return os.path.join(site_dir, f"admissible_{test_site}.txt")


class FullFormPolicyTester:
    """完整表单密码政策测试器

    与原有 TestPassword 保持相同的测试方法签名，
    便于在 main.py 中按 --method 参数切换。
    """

    def __init__(
        self,
        driver,
        site_url: str,
        signup_url: str = "",
        email_xpath: str = "",
        password_xpath: str = "",
        test_site: str = "",
    ):
        """
        Args:
            driver: Selenium WebDriver 实例
            site_url: 网站首页 URL
            signup_url: 已发现的注册页 URL
            email_xpath: 邮箱字段 XPath
            password_xpath: 密码字段 XPath
            test_site: 站点标识（用于日志/缓存）
        """
        self.driver = driver
        self.site_url = site_url
        self.signup_url = signup_url
        self.email_xpath = email_xpath
        self.password_xpath = password_xpath
        self.test_site = test_site

        # 组件
        self.rate_ctrl = RateController()
        self.data_gen = DataGenerator(locale="zh_CN")
        self.error_parser = PasswordErrorParser()
        self.form_submitter = FormSubmitter(driver, self.rate_ctrl, self.data_gen)

        # 状态
        self.admissible_password: str = ""
        self._all_fields: List[Dict] = []
        self._fields_detected: bool = False
        self._page_ready: bool = False
        self._site_no_value: bool = False  # 多步表单超限 → 无研究价值

        # 日志
        self.my_logger = uub.get_logger(self.test_site)

        # CDP eval 函数（从 login_link_discovery 借用模式）
        self._cdp_eval = self._make_cdp_eval()

    # ================================================================
    # CDP 工具
    # ================================================================

    def _make_cdp_eval(self):
        """创建 CDP eval 函数"""
        def _eval(expression: str):
            result = self.driver.execute_cdp_cmd('Runtime.evaluate', {
                'expression': expression,
                'returnByValue': True,
            })
            if 'exceptionDetails' in result:
                return None
            return result.get('result', {}).get('value')
        return _eval

    # ================================================================
    # 页面与字段准备
    # ================================================================

    def _ensure_page_ready(self) -> None:
        """确保已导航到注册页并检测字段"""
        if self._page_ready and self._fields_detected:
            return

        if not self.signup_url:
            raise RuntimeError("signup_url not set")

        try:
            self.driver.get(self.signup_url)
            time.sleep(2)
        except Exception:
            pass

        # 确保 JS 注入
        self._ensure_js_injected()

        # 检测全表单字段
        classifier = FieldClassifier(self._cdp_eval)
        self._all_fields = classifier.detect_all_fields()

        field_types = [f.get("field_type") for f in self._all_fields]
        self.my_logger.info(f"全表单字段检测完成: {len(self._all_fields)} 个字段")
        self.my_logger.info(f"字段类型: {field_types}")

        self._fields_detected = True
        self._page_ready = True

    def _ensure_js_injected(self) -> None:
        """确保 Fathom JS 文件已注入（复用 login_link_discovery 逻辑）

        CDP 会话可能在长时间测试后被浏览器关闭，此时跳过注入
        而非崩溃 —— 字段检测脚本仍可能在当前页面独立工作。
        """
        if getattr(self, '_js_inject_attempted', False):
            return  # 已尝试过，不再重复注入（避免反复触发异常）
        self._js_inject_attempted = True
        try:
            exists = self._cdp_eval("typeof ruleset")
            if exists != "function":
                discovery = LoginLinkDiscovery(self.driver)
                discovery.inject()
        except Exception:
            try:
                discovery = LoginLinkDiscovery(self.driver)
                discovery.inject()
            except Exception:
                self.my_logger.warning("JS 注入失败（CDP 会话可能已失效），跳过")

    def _reset_page(self) -> None:
        """重置页面状态（每次密码测试后）"""
        try:
            self.driver.refresh()
            time.sleep(1.5)
        except Exception:
            try:
                self.driver.get(self.signup_url)
                time.sleep(2)
            except Exception:
                pass
        self._fields_detected = False

    # ================================================================
    # 核心: 单密码测试（与 TestPassword.test_one_password 兼容）
    # ================================================================

    def test_one_password(self, test_password: str, info_name: str = "") -> bool:
        """测试单个密码是否被网站接受

        填充全表单 → 提交 → 解析服务端反馈 → 返回 True/False

        Args:
            test_password: 待测试的密码
            info_name: 测试说明（日志用）

        Returns:
            True = 密码被接受, False = 密码被拒绝
        """
        self.my_logger.info(f"Tested password: {test_password} -- {info_name}")
        self.my_logger.debug(f"Begin full-form test for password: {test_password}")

        retries = 0
        while retries < 3:
            try:
                self._ensure_page_ready()

                # 保存提交前 HTML 快照（用于 diff）
                try:
                    self.error_parser.snapshot_source(self.driver.page_source or "")
                except Exception:
                    pass

                # 填充 + 提交（支持多步表单，最多 2 页）
                submit_result = self.form_submitter.fill_and_submit(
                    fields=self._all_fields,
                    test_password=test_password,
                    email_xpath=self.email_xpath,
                )

                # 多步表单超限无反馈 → 标记站点为无研究价值，不再重试
                if submit_result.get("no_value"):
                    steps = submit_result.get("steps_completed", 0)
                    self.my_logger.warning(
                        f"NO_VALUE: 经过 {steps} 页表单仍无密码反馈，"
                        f"标记 {self.test_site} 为无研究价值")
                    self._site_no_value = True
                    return False

                # 补充 source diff
                source_diff = self.error_parser.diff_source(
                    submit_result.get("source_after", "")
                )
                submit_result["source_diff"] = source_diff

                # 解析反馈
                accepted, error_text = self.error_parser.parse(submit_result)

                if accepted:
                    self.my_logger.success(f"The tested password {test_password} is accepted.")
                    self.rate_ctrl.record_success()
                    return True
                else:
                    reason = error_text or "no specific error detected"
                    self.my_logger.warning(f"Password {test_password} rejected: {reason}")
                    self._reset_page()
                    self.rate_ctrl.delay_between_tests()
                    return False

            except Exception as e:
                self.my_logger.error(f"Test failed: {str(e)[:200]}")
                self.my_logger.error(f"Traceback: {traceback.format_exc()}")
                retries += 1
                self._reset_page()
                self.rate_ctrl.record_failure()

        self.my_logger.warning(f"Password {test_password}: all retries exhausted, treat as rejected.")
        return False

    # ================================================================
    # 寻找合法密码（与 TestPassword.find_admissible_password 兼容）
    # ================================================================

    def find_admissible_password(self) -> str:
        """在注册表单上寻找一个可被接受的密码"""
        self.my_logger.info(f"Begin finding admissible password (full-form) for {self.test_site}.")

        # 无研究价值 → 跳过
        if self._site_no_value:
            self.my_logger.warning(f"Site {self.test_site} marked as no_value, skipping admissible search.")
            return ""

        # 尝试缓存
        cache_path = _admissible_cache_path(self.test_site)
        if os.path.isfile(cache_path):
            cached = open(cache_path, "r", encoding="utf-8").read().strip()
            if cached:
                self.my_logger.info(f"Using cached admissible: {cached}")
                self.admissible_password = cached
                return cached

        # 按长度递增搜索
        admissible_list = {
            "8":  [uusg.gen_random_str_no_symbol(8), uusg.gen_random_str_no_symbol(8)],
            "9":  [uusg.gen_random_str_no_symbol(9), uusg.gen_random_str_no_symbol(9)],
            "10": [uusg.gen_random_str_no_symbol(10), uusg.gen_random_str_no_symbol(10)],
        }

        for length in range(8, 33):
            if length <= 10:
                candidates = admissible_list[str(length)]
            else:
                suffix = uusg.gen_random_str_no_symbol(length - 10)
                candidates = [
                    admissible_list["10"][0] + suffix,
                    admissible_list["10"][1] + suffix,
                ]

            for pwd in candidates:
                if self.test_one_password(pwd, "Find admissible"):
                    self.admissible_password = pwd
                    with open(cache_path, "w", encoding="utf-8") as f:
                        f.write(pwd)
                    self.my_logger.info(f"Admissible password found and cached: {pwd}")
                    return pwd

            # 测试间隔
            self.rate_ctrl.delay_between_tests()

        self.my_logger.warning("No admissible password found (full-form).")
        return ""

    # ================================================================
    # 14 项密码政策测试
    # 方法签名与 TestPassword 保持一致
    # ================================================================

    def check_special_symbols(self, test_password: str) -> bool:
        """特殊符号是否被禁止（True = 禁止）"""
        self.my_logger.info(f"Testing special symbols: {test_password}@")
        return not self.test_one_password(test_password + "@", "test special symbol")

    def change_and_test_2_word_password(self):
        """2-word 结构是否强制"""
        self.my_logger.info("Testing 2-word structure.")
        pwd = self.admissible_password
        # 随机打乱字符（破坏 word 结构但保持字符集一致）
        import random
        chars = list(pwd)
        random.shuffle(chars)
        shuffled = ''.join(chars)
        if shuffled == pwd:
            # 确保不同
            shuffled = shuffled[1:] + shuffled[:1]
        result = self.test_one_password(shuffled, "test 2-word structure")
        # True = 被接受（不强制 2-word）, False = 被拒绝（强制 2-word）
        return not result

    def change_and_test_letter_start_password(self, no_2word: bool):
        """首字母是否必须为字母"""
        self.my_logger.info("Testing letter-start requirement.")
        pwd = self.admissible_password
        # 改为数字开头
        test = "1" + pwd[1:] if len(pwd) > 1 else "1" + pwd
        return not self.test_one_password(test, "test letter start")

    def change_and_test_digit_minimum(self, no_sps: bool) -> int:
        """最少数字位数"""
        self.my_logger.info("Testing digit minimum.")
        pwd = self.admissible_password
        for cnt in range(5, 0, -1):
            test = uusg.gen_random_str_no_symbol(max(0, len(pwd) - cnt))
            if cnt > 0:
                test += uusg.gen_random_digit(cnt)
            if len(test) < 8:
                test = uusg.gen_random_str_no_symbol(8 - cnt) + uusg.gen_random_digit(cnt)
            if self.test_one_password(test, f"test digit min={cnt}"):
                return cnt
        return 0

    def change_and_test_lower_upper_minimum(self, is_upper: bool, no_sps: bool) -> int:
        """最少大写/小写字母数"""
        label = "upper" if is_upper else "lower"
        self.my_logger.info(f"Testing {label} minimum.")
        gen = uusg.gen_random_upper_character if is_upper else uusg.gen_random_lower_character
        pwd = self.admissible_password
        for cnt in range(5, 0, -1):
            test = uusg.gen_random_str_no_symbol(max(0, len(pwd) - cnt))
            test += gen(cnt)
            if len(test) < 8:
                test = uusg.gen_random_str_no_symbol(8 - cnt) + gen(cnt)
            if self.test_one_password(test, f"test {label} min={cnt}"):
                return cnt
        return 0

    def change_and_test_symbol_minimum(self, no_sps: bool) -> int:
        """最少特殊符号数"""
        self.my_logger.info("Testing symbol minimum.")
        pwd = self.admissible_password
        for cnt in range(3, 0, -1):
            test = uusg.gen_random_str_no_symbol(max(0, len(pwd) - cnt))
            test += uusg.gen_random_symbol_character(cnt)
            if len(test) < 8:
                test = uusg.gen_random_str_no_symbol(8 - cnt) + uusg.gen_random_symbol_character(cnt)
            if self.test_one_password(test, f"test symbol min={cnt}"):
                return cnt
        return 0

    def identify_combination_requirements(self, rp: dict) -> list:
        """识别字符组合要求（2/3, 3/3, 2/4, 3/4, 4/4）"""
        self.my_logger.info("Identifying combination requirements.")
        pwd = self.admissible_password
        results = []

        for combo_type in ["13", "23", "33", "14", "24", "34", "44"]:
            test = self._build_combo_password(pwd, combo_type)
            accepted = self.test_one_password(test, f"test combo {combo_type}")
            results.append(not accepted)  # True = 必须满足该组合
            self.rate_ctrl.delay_between_tests()

        return results

    def _build_combo_password(self, base: str, combo_type: str) -> str:
        """构建指定组合类型的测试密码"""
        length = max(len(base), 8)
        if combo_type == "13":  # 只有1类(如纯数字)
            return uusg.gen_random_digit(length)
        elif combo_type == "23":  # 只有2类(数字+小写, 无大写/符号)
            return uusg.gen_random_str_no_symbol(length)
        elif combo_type == "33":  # 3类(数字+小写+大写, 无符号)
            return (uusg.gen_random_lower_character(4) +
                    uusg.gen_random_upper_character(2) +
                    uusg.gen_random_digit(2))
        elif combo_type == "14":  # 只有1类(纯字母)
            return uusg.gen_random_letter_character(length)
        elif combo_type == "24":  # 只有2类(大小写字母, 无数字符号)
            return (uusg.gen_random_lower_character(4) +
                    uusg.gen_random_upper_character(4))
        elif combo_type == "34":  # 3类(大小写+数字, 无符号)
            return (uusg.gen_random_lower_character(3) +
                    uusg.gen_random_upper_character(3) +
                    uusg.gen_random_digit(2))
        elif combo_type == "44":  # 4类全部
            return (uusg.gen_random_lower_character(2) +
                    uusg.gen_random_upper_character(2) +
                    uusg.gen_random_digit(2) +
                    uusg.gen_random_symbol_character(2))
        return uusg.gen_random_str_no_symbol(length)

    def identify_min_and_max_length_limitations(self, rp: dict, r_min: list, r_max: list) -> tuple:
        """识别最小/最大长度限制"""
        self.my_logger.info("Identifying length limitations.")
        # 最小长度 → 从短到长测试
        min_len = r_min[1]
        for l in range(r_min[0], r_min[1] + 1):
            test = uusg.gen_random_str_no_symbol(l)
            if self.test_one_password(test, f"test min length {l}"):
                min_len = l
                break
            self.rate_ctrl.delay_between_tests()

        # 最大长度 → 从长到短测试
        max_len = r_max[1]
        for l in range(r_max[1], r_max[0] - 1, -1):
            test = uusg.gen_random_str_no_symbol(l)
            if self.test_one_password(test, f"test max length {l}"):
                max_len = l
                break
            self.rate_ctrl.delay_between_tests()

        return min_len, max_len

    def identify_permissive_characters(self, length: list) -> dict:
        """识别允许的字符类型（空格/Unicode/Emoji/特殊符号）"""
        self.my_logger.info("Identifying permissive characters.")
        result = {}
        tests = {
            "p_space": self.admissible_password + " ",
            "p_unicd": self.admissible_password + "中",
            "p_emoji": self.admissible_password + "\U0001f600",
            "p_spn1": self.admissible_password + "@",
            "p_spn2": self.admissible_password + "#",
            "p_spn3": self.admissible_password + "!",
            "p_spn4": self.admissible_password + "$",
        }
        for key, pwd in tests.items():
            result[key] = self.test_one_password(pwd, f"test permissive {key}")
            self.rate_ctrl.delay_between_tests()
        return result

    def identify_permitted_sequences(self, rp: dict, length: list) -> dict:
        """识别允许的序列（重复/连续/字典词）"""
        self.my_logger.info("Identifying permitted sequences.")
        result = {}
        base_len = max(length[0], 8) if length[0] > 0 else 8
        tests = {
            "p_rep": "a" * base_len,
            "p_seq": "abcdefgh"[:base_len],
            "p_dict": "password" if base_len <= 8 else "password1",
        }
        for key, pwd in tests.items():
            result[key] = self.test_one_password(pwd, f"test sequence {key}")
            self.rate_ctrl.delay_between_tests()
        return result

    def identify_long_short_passwords(self, length: list) -> dict:
        """识别极长/极短密码是否被接受"""
        self.my_logger.info("Identifying long/short password tolerance.")
        result = {}
        if length[0] > 0:
            result["p_shortd"] = self.test_one_password(
                uusg.gen_random_str_no_symbol(max(1, length[0] - 1)),
                "test short password"
            )
        else:
            result["p_shortd"] = False
        result["p_longd"] = self.test_one_password(
            uusg.gen_random_str_no_symbol(128),
            "test long password"
        )
        self.rate_ctrl.delay_between_tests()
        return result

    def identify_breached_passwords(self, rp: dict, length: list) -> dict:
        """识别是否禁止已知泄露密码"""
        self.my_logger.info("Checking breached password detection.")
        # 尝试常见的弱密码
        weak_passwords = ["password", "12345678", "qwerty123", "admin123"]
        for wp in weak_passwords:
            if len(wp) >= (length[0] or 8):
                accepted = self.test_one_password(wp, "test breached")
                self.rate_ctrl.delay_between_tests()
                return {"p_br": not accepted}
        return {"p_br": False}

    # ================================================================
    # 一键运行
    # ================================================================

    def run_full_test(self) -> dict:
        """执行完整的密码政策测试（14 项）"""
        policy = {
            "length": [0, 0],
            "restrictive": {
                "r_no_a_sps": False, "r_2_word": False, "r_l_start": False,
                "r_dig_min": 0, "r_upp_min": 0, "r_low_min": 0, "r_sps_min": 0,
                "r_cmb13": False, "r_cmb23": False, "r_cmb33": False,
                "r_cmb14": False, "r_cmb24": False, "r_cmb34": False, "r_cmb44": False,
            },
            "permissive": {
                "permitted_characters": {},
                "permitted_sequences": {},
                "short_and_long_password": {},
                "breached_password": {},
            },
        }

        try:
            admissible = self.find_admissible_password()
            if not admissible:
                self.my_logger.warning("Cannot find admissible password, returning empty policy.")
                return policy

            self.rate_ctrl.delay_between_tests()

            rp = policy["restrictive"]
            rp["r_no_a_sps"] = self.check_special_symbols(admissible)
            self.rate_ctrl.delay_between_tests()

            rp["r_2_word"] = self.change_and_test_2_word_password()
            self.rate_ctrl.delay_between_tests()

            rp["r_l_start"] = self.change_and_test_letter_start_password(rp["r_2_word"])
            self.rate_ctrl.delay_between_tests()

            rp["r_dig_min"] = self.change_and_test_digit_minimum(rp["r_no_a_sps"])
            self.rate_ctrl.delay_between_tests()

            rp["r_upp_min"] = self.change_and_test_lower_upper_minimum(True, rp["r_no_a_sps"])
            self.rate_ctrl.delay_between_tests()

            rp["r_low_min"] = self.change_and_test_lower_upper_minimum(False, rp["r_no_a_sps"])
            self.rate_ctrl.delay_between_tests()

            rp["r_sps_min"] = self.change_and_test_symbol_minimum(rp["r_no_a_sps"])
            self.rate_ctrl.delay_between_tests()

            combos = self.identify_combination_requirements(rp)
            keys = ["r_cmb13", "r_cmb23", "r_cmb33",
                    "r_cmb14", "r_cmb24", "r_cmb34", "r_cmb44"]
            for k, v in zip(keys, combos):
                rp[k] = v

            policy["length"][0], policy["length"][1] = \
                self.identify_min_and_max_length_limitations(rp, [0, 32], [6, 128])

            policy["permissive"]["permitted_characters"] = \
                self.identify_permissive_characters(policy["length"])
            policy["permissive"]["permitted_sequences"] = \
                self.identify_permitted_sequences(rp, policy["length"])
            policy["permissive"]["short_and_long_password"] = \
                self.identify_long_short_passwords(policy["length"])
            policy["permissive"]["breached_password"] = \
                self.identify_breached_passwords(rp, policy["length"])

        except Exception as e:
            self.my_logger.error(f"Full-form test error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.my_logger.info(f"Policy of {self.test_site}: {policy}")

        return policy
