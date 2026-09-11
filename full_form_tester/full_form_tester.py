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
from selenium.common.exceptions import InvalidSessionIdException, NoSuchWindowException

import utils.util_basic as uub
import utils.util_str_generator as uusg
from config.config import Config
from utils.login_link_discovery import LoginLinkDiscovery
from utils.password_candidates import (
    admissible_candidate_lengths,
    stratified_password_candidates,
)
from utils.adaptive_policy import (
    ACCEPTED,
    INCONCLUSIVE,
    REJECTED,
    AdaptiveCompositionPlanner,
    AdaptiveConditionalPolicyPlanner,
    AdaptiveLengthPlanner,
    apply_composition_to_restrictive,
    build_length_candidate,
    candidate_profile,
    normalize_outcome,
)

from .rate_controller import RateController
from .data_generator import DataGenerator
from .password_error_parser import PasswordErrorParser
from .field_classifier import (
    FieldClassifier,
    FIELD_PASSWORD, FIELD_CONFIRM_PASSWORD,
    FIELD_CHECKBOX_TERMS, FIELD_CAPTCHA,
)
from .form_submitter import FormSubmitter
from signup_flow_classifier.browser_failures import detect_access_block


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
        authorized: bool = False,
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
        self.authorized = authorized

        # 组件
        self.rate_ctrl = RateController()
        self.data_gen = DataGenerator(locale="zh_CN")
        self.error_parser = PasswordErrorParser()
        self.form_submitter = FormSubmitter(
            driver, self.rate_ctrl, self.data_gen,
            allow_submit=authorized,
        )

        # 状态
        self.admissible_password: str = ""
        self._all_fields: List[Dict] = []
        self._fields_detected: bool = False
        self._page_ready: bool = False
        self._site_no_value: bool = False  # 多步表单超限 → 无研究价值
        self._seen_specific_error: bool = False  # 是否见过明确错误消息（用于登录表单判断）
        self._browser_dead: bool = False  # 浏览器会话已终止（崩溃/被关闭）
        self._last_probe_outcome: str = INCONCLUSIVE
        self._last_probe_evidence: str = "not_started"
        self._probe_evidence: List[Dict] = []
        self._had_inconclusive: bool = False
        self._adaptive_summary: Dict = {}
        self._adaptive_composition_summary: Dict = {}
        self._adaptive_conditional_summary: Dict = {}

        # 日志
        self.my_logger = uub.get_logger(self.test_site)

        # CDP eval 函数（从 login_link_discovery 借用模式）
        self._cdp_eval = self._make_cdp_eval()

    def _record_probe(self, password: str, outcome, evidence: str,
                      purpose: str = "") -> None:
        """Store a redacted three-state observation for later audit."""
        normalized = normalize_outcome(outcome)
        self._last_probe_outcome = normalized
        self._last_probe_evidence = str(evidence or "")[:300]
        if normalized == INCONCLUSIVE:
            self._had_inconclusive = True
        if not hasattr(self, "_probe_evidence"):
            self._probe_evidence = []
        self._probe_evidence.append({
            "purpose": str(purpose or "")[:160],
            "candidate": candidate_profile(password),
            "outcome": normalized,
            "evidence": self._last_probe_evidence,
        })

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
        """确保已导航到注册页并检测字段

        如果关键字段（PASSWORD/EMAIL）位于 iframe 内，尝试直接导航到
        iframe 的 src URL，使后续 Selenium 交互无需切换 frame 即可操作。
        """
        if self._page_ready and self._fields_detected:
            return

        if not self.signup_url:
            raise RuntimeError("signup_url not set")

        # 始终导航到注册页以触发注册流程（signup modal / redirect / 等）
        # 部分网站的注册表单是由 JS 在页面加载时动态创建的
        # （如 Stack Overflow 的 signup modal），需要新鲜页面加载才能触发。
        # Phase 1 的导航可能已过时（页面状态变化、modal 关闭等）。
        try:
            self.driver.get(self.signup_url)
            time.sleep(3)  # 给 JS 渲染留足时间（2s → 3s）
        except Exception:
            pass

        # 确保 JS 注入
        self._ensure_js_injected()

        # 检测全表单字段
        classifier = FieldClassifier(self._cdp_eval)
        self._all_fields = classifier.detect_all_fields()

        # ── 异步 iframe 重试：字段过少时等待更长时间后重试 ──
        # 部分网站（如 Stack Overflow）通过 JS 在页面加载后动态创建
        # signup modal iframe。2 秒可能不足以让 iframe 完成渲染。
        # 当检测结果 ≤2 个字段且没有 iframe 标记时，等待后重试。
        retry_count = 0
        while len(self._all_fields) <= 2 and retry_count < 3:
            has_iframe_marker = any(
                f.get("cross_origin") or f.get("iframe")
                for f in self._all_fields
            )
            if has_iframe_marker:
                break  # 已检测到 iframe 标记，进入后续的 iframe 导航逻辑

            retry_count += 1
            wait_s = 2 * retry_count  # 2s → 4s → 6s
            self.my_logger.info(
                f"字段检测结果过少 ({len(self._all_fields)} 个)，"
                f"等待 {wait_s}s 后重试 ({retry_count}/3)"
            )
            time.sleep(wait_s)
            self._all_fields = classifier.detect_all_fields()

        # ── iframe 字段检测：如果关键字段在 iframe 内，导航到 iframe URL ──
        #
        # 两种触发场景：
        #   1. 密码字段在 iframe 内（同源 iframe，能够通过 contentDocument 检测到字段类型）
        #   2. 跨域 iframe 占位符（cross_origin=true, frame_src 非空）
        #      跨域 iframe 的 contentDocument 不可访问 → 无法分类字段 →
        #      所有跨域字段被标记为 UNKNOWN。但已知许多网站的注册表单
        #      就在 iframe 内（如 Stack Overflow），应直接导航到 iframe URL。
        iframe_src = None
        cross_origin = False
        trigger_field = None  # 记录触发导航的字段（用于日志）

        pw_field = next(
            (f for f in self._all_fields
             if f.get("field_type") == FIELD_PASSWORD), None
        )
        if pw_field and pw_field.get("frame_src"):
            trigger_field = pw_field
            iframe_src = pw_field["frame_src"]
            cross_origin = pw_field.get("cross_origin", False)
        elif not pw_field:
            # 未检测到密码字段，但有跨域 iframe → 表单可能在跨域 iframe 内
            cross_origin_placeholder = next(
                (f for f in self._all_fields
                 if f.get("cross_origin") and f.get("frame_src")), None
            )
            if cross_origin_placeholder:
                trigger_field = cross_origin_placeholder
                iframe_src = cross_origin_placeholder["frame_src"]
                cross_origin = True

        if iframe_src:
            # ── 同站检查：跳过跨域 iframe（analytics、tracking、ad 等）──
            # 跨域 iframe 通常是第三方统计/广告服务（如 web-stat.jpush.cn），
            # 不是注册表单。导航到这些页面会丢失真正的注册页面。
            from urllib.parse import urljoin, urlparse
            try:
                parsed_main = urlparse(self.driver.current_url)
                parsed_frame = urlparse(urljoin(self.driver.current_url, iframe_src))
                main_domain = ".".join((parsed_main.hostname or "").split(".")[-2:])
                frame_domain = ".".join((parsed_frame.hostname or "").split(".")[-2:])
                same_site = (main_domain == frame_domain)
            except Exception:
                same_site = True  # 解析失败不拦截

            if not same_site:
                self.my_logger.info(
                    f"跳过跨域 iframe ({frame_domain} != {main_domain}), "
                    f"src={iframe_src[:120]}"
                )
            else:
                self.my_logger.info(
                    f"检测到表单字段在 iframe 内 "
                    f"(frame_index={trigger_field.get('frame_index')}, "
                    f"src={iframe_src[:120]}, "
                    f"cross_origin={cross_origin})"
                )
                # 将相对 URL 解析为绝对 URL
                full_iframe_url = urljoin(self.driver.current_url, iframe_src)
                self.my_logger.info(f"导航到 iframe URL: {full_iframe_url}")
                try:
                    self.driver.get(full_iframe_url)
                    time.sleep(2)
                    # 重新检测字段（现在表单直接在顶层文档中）
                    self._all_fields = classifier.detect_all_fields()
                except Exception as e:
                    self.my_logger.warning(
                        f"无法导航到 iframe URL: {e}，回退使用原始页面字段"
                    )

        # ── Phase 1 字段回退：detect_all_fields() 遗漏字段时补充 ──
        # 部分网站的注册表单通过 JS 延迟加载（动态创建 DOM / Modal），
        # FieldClassifier.detect_all_fields() 的 Runtime.evaluate 一次执行
        # 可能捕获不到尚未渲染的元素。但 Phase 1 的 detectFieldsInAllFrames()
        # 通过 CDP 预注入 + 更宽松的等待已成功发现字段。
        # 此处将 Phase 1 已发现的字段补充到 _all_fields 中，确保后续的
        # fill_and_submit() 有完整的字段列表可操作。
        if len(self._all_fields) <= 2 and (self.password_xpath or self.email_xpath):
            existing_xpaths = {f.get("xpath", "") for f in self._all_fields}
            supplemental = []

            if self.email_xpath and self.email_xpath not in existing_xpaths:
                supplemental.append({
                    "xpath": self.email_xpath,
                    "tag": "input",
                    "el_type": "email",
                    "field_type": "TEXT",
                    "name": "email",
                    "id": "",
                    "placeholder": "",
                    "autocomplete": "email",
                    "aria_label": "",
                    "label_text": "email",
                    "required": True,
                    "class_name": "",
                    "source": "phase1_fallback",
                })

            if self.password_xpath and self.password_xpath not in existing_xpaths:
                supplemental.append({
                    "xpath": self.password_xpath,
                    "tag": "input",
                    "el_type": "password",
                    "field_type": FIELD_PASSWORD,
                    "name": "password",
                    "id": "",
                    "placeholder": "",
                    "autocomplete": "new-password",
                    "aria_label": "",
                    "label_text": "password",
                    "required": True,
                    "class_name": "",
                    "source": "phase1_fallback",
                })

            if supplemental:
                self._all_fields.extend(supplemental)
                self.my_logger.info(
                    f"Phase 1 字段回退: 补充了 {len(supplemental)} 个字段 "
                    f"(email={bool(self.email_xpath)}, pwd={bool(self.password_xpath)})"
                )

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
                    self._record_probe(
                        test_password, INCONCLUSIVE,
                        f"multi_step_form_without_password_feedback_after_{steps}_steps",
                        info_name,
                    )
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
                    self._record_probe(
                        test_password, ACCEPTED,
                        "form_or_server_feedback_accepted", info_name)
                    return True
                else:
                    reason = error_text or "no specific error detected"
                    if error_text:
                        self._seen_specific_error = True
                    self.my_logger.warning(f"Password {test_password} rejected: {reason}")
                    # A parser result without password-specific feedback is not
                    # proof of rejection; keep it as an explicit third state.
                    self._record_probe(
                        test_password,
                        REJECTED if error_text else INCONCLUSIVE,
                        error_text or "no_password_specific_feedback",
                        info_name,
                    )
                    self._reset_page()
                    self.rate_ctrl.delay_between_tests()
                    return False

            except (InvalidSessionIdException, NoSuchWindowException) as e:
                # 浏览器会话已终止 — 无法继续任何测试
                self._browser_dead = True
                self.my_logger.error(
                    f"浏览器会话终止: {type(e).__name__}，标记为 browser_dead"
                )
                self._record_probe(
                    test_password, INCONCLUSIVE,
                    f"browser_session_terminated:{type(e).__name__}", info_name)
                return False
            except Exception as e:
                self.my_logger.error(f"Test failed: {str(e)[:200]}")
                self.my_logger.error(f"Traceback: {traceback.format_exc()}")
                retries += 1
                self._reset_page()
                self.rate_ctrl.record_failure()

        self.my_logger.warning(
            f"Password {test_password}: all retries exhausted, mark as inconclusive.")
        self._record_probe(
            test_password, INCONCLUSIVE,
            "all_form_submission_retries_exhausted", info_name)
        return False

    # ================================================================
    # 寻找合法密码（与 TestPassword.find_admissible_password 兼容）
    # ================================================================

    def _quick_login_form_check(self) -> bool:
        """快速登录表单检测：尝试空密码和极短密码

        注册表单几乎不可能接受空字符串作为密码。
        如果空密码被接受，极大概率是登录表单。
        """
        try:
            if self.test_one_password("", "login form check (empty)"):
                self.my_logger.warning("Empty password accepted — likely login form!")
                return True
            self._reset_page()
            self.rate_ctrl.delay_between_tests()
            if self.test_one_password("a", "login form check (single char)"):
                self.my_logger.warning("Single-char password accepted — likely login form!")
                return True
        except Exception:
            pass
        return False

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

        # 时间预算：防止在登录表单等"无密码反馈"的页面上空转
        # （登录表单不会给注册密码反馈，逐长度试探永远被拒，只能靠时间兜底退出）
        ADMISSIBLE_DEADLINE_SECONDS = Config.ADMISSIBLE_SEARCH_SECONDS
        deadline = time.monotonic() + ADMISSIBLE_DEADLINE_SECONDS

        for length in admissible_candidate_lengths(
                Config.ADMISSIBLE_MIN_LENGTH, Config.ADMISSIBLE_MAX_LENGTH):
            for pwd in stratified_password_candidates(length):
                if time.monotonic() > deadline:
                    self.my_logger.warning(
                        f"Admissible search exceeded {ADMISSIBLE_DEADLINE_SECONDS}s budget, "
                        f"giving up early (likely a login form with no password feedback)."
                    )
                    return ""
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
        """Test symbol prohibition without accidentally changing length."""
        if any(not char.isalnum() and not char.isspace()
               for char in test_password):
            return False

        def kind(char: str) -> str:
            if char.islower():
                return "lower"
            if char.isupper():
                return "upper"
            if char.isdigit():
                return "digit"
            return "symbol"

        counts: Dict[str, int] = {}
        for char in test_password:
            counts[kind(char)] = counts.get(kind(char), 0) + 1
        replace_at = next(
            (index for index in range(len(test_password) - 1, -1, -1)
             if counts.get(kind(test_password[index]), 0) > 1),
            None,
        )
        if replace_at is None:
            self._record_probe(
                test_password, INCONCLUSIVE,
                "special_symbol_probe_has_no_redundant_character",
                "test special symbol",
            )
            return False

        symbol_candidate = (
            test_password[:replace_at] + "!" + test_password[replace_at + 1:])
        self.my_logger.info(
            f"Testing special symbol at fixed length={len(symbol_candidate)}")
        if self.test_one_password(symbol_candidate, "test special symbol at fixed length"):
            return False
        symbol_outcome = normalize_outcome(
            getattr(self, "_last_probe_outcome", INCONCLUSIVE))
        if symbol_outcome != REJECTED:
            return False

        original_kind = kind(test_password[replace_at])
        recipient_kind = next(
            (name for name in ("lower", "upper", "digit")
             if name != original_kind and counts.get(name, 0) > 0),
            None,
        )
        if recipient_kind is None:
            self._record_probe(
                test_password, INCONCLUSIVE,
                "symbol_rejected_but_lost_class_minimum_cannot_be_controlled",
                "test special symbol",
            )
            return False
        replacement = {"lower": "q", "upper": "Q", "digit": "7"}[recipient_kind]
        control_candidate = (
            test_password[:replace_at] + replacement
            + test_password[replace_at + 1:])
        if self.test_one_password(
                control_candidate, "control for fixed-length symbol mutation"):
            return True
        self._record_probe(
            test_password, INCONCLUSIVE,
            "symbol_and_non_symbol_control_both_rejected",
            "test special symbol",
        )
        return False

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

    def identify_adaptive_composition(self, rp: dict) -> dict:
        """Infer class subsets and required-class counts at a fixed length."""
        def observe(candidate: str, purpose: str):
            try:
                accepted = self.test_one_password(candidate, purpose)
                outcome = getattr(self, "_last_probe_outcome", None)
                return accepted if outcome is None else outcome
            finally:
                # Full-form probes may submit a form; retain the global pacing
                # policy even when the candidate is explicitly accepted.
                self.rate_ctrl.delay_between_tests()

        planner = AdaptiveCompositionPlanner(
            probe=observe,
            accepted_anchor=self.admissible_password,
            structural_rules=rp,
            probe_budget=24,
        )
        summary = planner.infer()
        self._adaptive_composition_summary = summary
        apply_composition_to_restrictive(rp, summary)
        self.my_logger.info(
            "Adaptive composition result: minimum_classes={} required={} "
            "probes={} status={}".format(
                summary.get("minimum_character_classes"),
                summary.get("required_classes"),
                summary.get("probes_used"),
                summary.get("status"),
            ))
        return summary

    def identify_adaptive_conditional_policy(
        self, rp: dict, length_summary: Optional[Dict] = None,
        composition_summary: Optional[Dict] = None,
    ) -> dict:
        """Detect a length-triggered relaxation of class requirements."""
        def observe(candidate: str, purpose: str):
            try:
                accepted = self.test_one_password(candidate, purpose)
                outcome = getattr(self, "_last_probe_outcome", None)
                return accepted if outcome is None else outcome
            finally:
                self.rate_ctrl.delay_between_tests()

        planner = AdaptiveConditionalPolicyPlanner(
            probe=observe,
            accepted_anchor=self.admissible_password,
            length_summary=length_summary or self._adaptive_summary,
            composition_summary=(
                composition_summary or self._adaptive_composition_summary),
            structural_rules=rp,
            probe_budget=16,
        )
        summary = planner.infer()
        self._adaptive_conditional_summary = summary
        self.my_logger.info(
            "Adaptive conditional result: status={} relaxed_threshold={} "
            "subset={} probes={}".format(
                summary.get("status"),
                summary.get("relaxed_length_threshold"),
                summary.get("relaxed_subset"),
                summary.get("probes_used"),
            ))
        return summary

    def identify_min_and_max_length_limitations(self, rp: dict, r_min: list, r_max: list) -> tuple:
        """Infer length boundaries with a budgeted adaptive search.

        Full-form observations may submit a form, so the historical linear
        scan was especially expensive.  The accepted password is used as an
        invariant and each next length halves the remaining search interval.
        """
        self.my_logger.info("Identifying length limitations with adaptive search.")

        def observe(candidate: str, purpose: str):
            accepted = self.test_one_password(candidate, purpose)
            outcome = getattr(self, "_last_probe_outcome", None)
            if normalize_outcome(outcome) != INCONCLUSIVE or outcome is not None:
                return outcome
            # Unit-test doubles and older adapters only expose bool results.
            return accepted

        known_maximum = self._read_password_maxlength()
        planner = AdaptiveLengthPlanner(
            probe=observe,
            candidate_factory=lambda length: build_length_candidate(
                length, rp, self.admissible_password),
            accepted_anchor=self.admissible_password,
            minimum_range=(int(r_min[0]), int(r_min[1])),
            maximum_range=(int(r_max[0]), int(r_max[1])),
            probe_budget=24,
            known_maximum=known_maximum,
        )
        summary = planner.infer()
        self._adaptive_summary = summary
        minimum = summary["minimum"].get("value")
        maximum = summary["maximum"].get("value")
        self.my_logger.info(
            "Adaptive length result: min={} max={} probes={} saved_vs_worst_case={}".format(
                minimum, maximum, summary["probes_used"],
                summary["probes_saved_vs_worst_case"],
            ))
        return minimum or 0, maximum

    @staticmethod
    def _length_probe_password(length: int, rp: dict) -> Optional[str]:
        """Build an exact-length candidate satisfying known non-length rules.

        A length probe must vary only length.  Returning ``None`` means that
        the requested length cannot express the already-known composition
        requirements and therefore must not be used as length evidence.
        """
        return build_length_candidate(length, rp)

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

        if not self.authorized:
            self.my_logger.warning(
                "full-form 未获得显式授权，未填写身份字段、未提交表单。")
            policy["_inconclusive"] = True
            policy["_full_form_unauthorized"] = True
            policy["_note"] = (
                "full-form 默认关闭；需要显式授权和精确主机白名单。")
            return policy

        try:
            # ── 机器人拦截检测：在登录表单预检前先检查是否被拦截 ──
            # 被拦截时页面无真实表单，空密码可能被"接受"（无拒绝逻辑），
            # 导致被误判为登录表单。必须先排除拦截，避免错误分类。
            access_marker = detect_access_block(self.driver)
            if access_marker:
                self.my_logger.warning(
                    f"检测到访问阻断: {access_marker}，跳过密码政策测量"
                )
                policy["_note"] = f"访问被阻断: {access_marker}，无法测量密码政策"
                policy["_access_blocked"] = True
                return policy

            # ── 登录表单预检：在 admissible 搜索前快速检测 ──
            # 注册表单几乎不可能接受空密码。如果空密码/极短密码被接受，
            # 极大概率是登录表单（POST 到登录接口返回"凭据不匹配"时，
            # 无字段级错误反馈，被误判为"密码通过"）。
            if self._quick_login_form_check():
                self.my_logger.warning(
                    "预检发现疑似登录表单（空/短密码被接受），跳过密码政策测量"
                )
                policy["_suspicious_login_form"] = True
                policy["_note"] = (
                    "空密码或极短密码被接受，当前页面大概率是登录表单"
                    "而非注册表单。密码政策测量结果不可信。"
                )
                return policy

            admissible = self.find_admissible_password()
            # ── 浏览器已终止检查：admissible 搜索过程中浏览器崩溃 ──
            # 此时所有后续测试都无法进行，且 _seen_specific_error 可能为 False
            # （崩溃发生在检查错误消息之前）。必须先检查此标志，避免误判为登录表单。
            if self._browser_dead:
                self.my_logger.warning(
                    "浏览器会话在 admissible 搜索期间终止，无法完成测试"
                )
                policy["_note"] = "浏览器会话终止，密码政策测量未完成"
                policy["_browser_dead"] = True
                return policy

            if not admissible:
                # ── 登录表单后检：admissible 搜索失败 + 默认策略全为零 ──
                # 重要：只有从未见过明确错误消息（如 "密码长度不得低于8个字符"）
                # 时才触发登录表单检测。如果见过错误消息，说明是真实注册表单，
                # 只是我们暂时无法通过其验证（如 checkbox、CAPTCHA 等）。
                if self._seen_specific_error:
                    self.my_logger.warning(
                        "admissible 搜索失败，但见过明确错误消息 → 真实注册表单，非登录表单"
                    )
                else:
                    # ── 无动态反馈站点降级：从静态 maxlength 提取硬上限 ──
                    # 有些站（如游民星空）密码框内联/提交都不给专属错误，无法用
                    # "填-看拒绝"测政策；但 maxlength 是浏览器强制硬上限，可作
                    # length 上界兜底，避免交全零白卷，也避免被误判为登录表单。
                    maxlen = self._read_password_maxlength()
                    if maxlen:
                        policy["length"][1] = maxlen
                        policy["_no_password_feedback"] = True
                        policy["_note"] = (
                            "密码框无动态反馈（内联/提交均无专属错误），"
                            f"仅从 maxlength 提取长度上界 {maxlen}，"
                            "其余政策无法实测。"
                        )
                        self.my_logger.warning(
                            f"无密码反馈站点：仅 maxlength={maxlen} 兜底，返回部分政策"
                        )
                        return policy
                    if self._is_likely_login_form(policy):
                        self.my_logger.warning(
                            "admissible 搜索失败且默认策略全为零，疑似登录表单"
                        )
                        policy["_suspicious_login_form"] = True
                        policy["_note"] = (
                            "无法找到合法密码且默认策略全为零，"
                            "且未检测到任何明确密码错误消息。"
                            "当前页面可能是登录表单而非注册表单。"
                            "密码政策测量结果不可信。"
                        )
                        return policy
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

            # Cached admissible candidates can expire or the form can drift
            # after structural probes.  Revalidate the exact anchor before it
            # is used as the accepted invariant by both adaptive planners.
            if not self.test_one_password(
                    admissible, "phase control: revalidate accepted anchor"):
                policy["_inconclusive"] = True
                policy["_inconclusive_reason"] = \
                    "accepted_anchor_revalidation_failed_before_adaptive_probes"
                return policy
            self.rate_ctrl.delay_between_tests()

            composition = self.identify_adaptive_composition(rp)
            policy["_adaptive_composition"] = composition
            if composition.get("status") == "inconclusive":
                policy["_inconclusive"] = True
                policy["_inconclusive_reason"] = (
                    "adaptive_composition_probe_inconclusive: "
                    + str(composition.get("stop_reason") or "unknown"))
                return policy
            if composition.get("status") == "partial":
                policy["_composition_partial"] = True

            policy["length"][0], policy["length"][1] = \
                self.identify_min_and_max_length_limitations(rp, [0, 32], [6, 128])
            if self._adaptive_summary:
                policy["_adaptive"] = self._adaptive_summary
                boundary_states = {
                    self._adaptive_summary["minimum"].get("status"),
                    self._adaptive_summary["maximum"].get("status"),
                }
                if "inconclusive" in boundary_states:
                    policy["_inconclusive"] = True
                    policy["_inconclusive_reason"] = (
                        "adaptive_length_probe_inconclusive: "
                        + str(self._adaptive_summary.get("stop_reason") or "unknown")
                    )
                    return policy

            if not self.test_one_password(
                    admissible,
                    "phase control: revalidate anchor before conditional policy"):
                policy["_inconclusive"] = True
                policy["_inconclusive_reason"] = \
                    "accepted_anchor_drifted_before_conditional_policy_phase"
                return policy
            self.rate_ctrl.delay_between_tests()

            had_inconclusive_before_conditional = self._had_inconclusive
            conditional = self.identify_adaptive_conditional_policy(
                rp, self._adaptive_summary, composition)
            policy["_adaptive_conditional"] = conditional
            if conditional.get("status") == "detected":
                policy["_or_rule"] = conditional.get("rule")
            elif conditional.get("status") == "inconclusive":
                policy["_conditional_inconclusive"] = True
                self._had_inconclusive = had_inconclusive_before_conditional

            if conditional.get("probes_used", 0) > 0:
                if not self.test_one_password(
                        admissible,
                        "phase control: revalidate after conditional policy probes"):
                    policy["_inconclusive"] = True
                    policy["_inconclusive_reason"] = \
                        "accepted_anchor_drifted_after_conditional_policy_phase"
                    return policy
                self.rate_ctrl.delay_between_tests()

            policy["permissive"]["permitted_characters"] = \
                self.identify_permissive_characters(policy["length"])
            policy["permissive"]["permitted_sequences"] = \
                self.identify_permitted_sequences(rp, policy["length"])
            policy["permissive"]["short_and_long_password"] = \
                self.identify_long_short_passwords(policy["length"])
            policy["permissive"]["breached_password"] = \
                self.identify_breached_passwords(rp, policy["length"])

            # ── 登录表单检测 ──
            if self._is_likely_login_form(policy):
                self.my_logger.warning(
                    "检测到疑似登录表单（所有密码均被接受），标记结果"
                )
                policy["_suspicious_login_form"] = True
                policy["_note"] = (
                    "所有测试密码（包括空字符串和弱密码）均被接受。"
                    "当前页面可能是登录表单而非注册表单，"
                    "密码政策测量结果不可信。"
                )

        except Exception as e:
            self.my_logger.error(f"Full-form test error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            policy["_probe_evidence"] = list(
                getattr(self, "_probe_evidence", []))
            if getattr(self, "_had_inconclusive", False):
                policy["_inconclusive"] = True
                policy.setdefault(
                    "_inconclusive_reason",
                    "at_least_one_full_form_probe_lacked_password_specific_evidence",
                )
            self.my_logger.info(f"Policy of {self.test_site}: {policy}")

        return policy

    def _is_likely_login_form(self, policy: dict) -> bool:
        """检测表单是否疑似登录表单（非注册）

        判断依据：
        1. 空字符串密码被接受（min_length == 0）
        2. 所有 restrictive 维度都没有任何限制
        3. 常见弱密码全部被接受

        注册表单几乎不可能接受空字符串作为密码。
        """
        length = policy.get("length", [None, None])
        restrictive = policy.get("restrictive", {})

        # 空密码被接受 → 高度可疑
        min_len = length[0] if length else None
        if min_len is not None and min_len <= 0:
            # 检查是否所有限制都为 0 / False
            all_zeros = True
            for k, v in restrictive.items():
                if isinstance(v, bool) and v is True:
                    all_zeros = False
                    break
                if isinstance(v, (int, float)) and v > 0:
                    all_zeros = False
                    break

            if all_zeros:
                # 检查 permissive 字符是否大部分都被允许
                permissive = policy.get("permissive", {})
                permitted_chars = permissive.get("permitted_characters", {})
                if permitted_chars:
                    true_count = sum(
                        1 for v in permitted_chars.values() if v is True
                    )
                    # 如果有 >= 3 个字符类型都被允许，且没有任何限制
                    if true_count >= 3:
                        return True

                # 另一种情况：permissive 为空（{}），但 min_len=0 且所有限制为 0
                # 这说明根本没有任何密码规则 → 极可能是登录表单
                if not permitted_chars or len(permitted_chars) == 0:
                    sequences = permissive.get("permitted_sequences", {})
                    if not sequences or len(sequences) == 0:
                        return True

        return False

    def _password_xpaths(self) -> List[str]:
        """返回密码框的候选 XPath（字段检测结果 + 显式 password_xpath，去重）"""
        xpaths: List[str] = []
        pw = next(
            (f for f in getattr(self, "_all_fields", [])
             if f.get("field_type") == FIELD_PASSWORD), None
        )
        if pw and pw.get("xpath"):
            xpaths.append(pw["xpath"])
        explicit = getattr(self, "password_xpath", "")
        if explicit and explicit not in xpaths:
            xpaths.append(explicit)
        return xpaths

    def _read_password_maxlength(self) -> Optional[int]:
        """从密码框读取 maxlength 属性（浏览器强制硬上限），无则返回 None。

        用于"无动态反馈"站点（内联/提交都不给专属错误）的降级兜底：
        maxlength 是浏览器在输入层强制执行的硬约束，属于真实政策，不是页面提示。
        """
        for xp in self._password_xpaths():
            if not xp:
                continue
            try:
                el = self.driver.find_element("xpath", xp)
                ml = el.get_attribute("maxlength")
                if ml and ml.strip().isdigit():
                    return int(ml.strip())
            except Exception:
                continue
        return None
