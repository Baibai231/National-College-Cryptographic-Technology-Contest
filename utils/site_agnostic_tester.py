"""
site_agnostic_tester.py

嫁接核心：LoginFormExploration (Node.js/Puppeteer) 的表单发现
        + MyAutomaticPolicy (Python/Selenium) 的密码政策测试。

流程：
  1. Node.js subprocess 运行 LoginFormExploration 原生代码：
     - Puppeteer 加载页面 → Fathom ML 检测表单字段
     - 返回 JSON: { signup_url, email_xpath, password_xpath }
  2. Python 解析 JSON，用 Selenium 导航到注册页
  3. 执行 14 项密码政策突变测试
  4. 返回完整的 password_policy
"""

import sys
import time
import utils.util_basic as uub
from utils.login_link_discovery import LoginLinkDiscovery
from utils.util_test_password import TestPassword, BrowserDeadError
from utils.password_policy_evidence import has_substantive_dom_evidence


def _safe_print(message) -> None:
    """Print without crashing on legacy Windows console encodings."""
    text = str(message)
    encoding = getattr(sys.stdout, "encoding", None)
    if encoding:
        text = text.encode(encoding, errors="replace").decode(encoding)
    print(text)


class SitePasswordPolicyTester:
    """网站无关的密码政策测试器

    只需提供网站首页 URL，自动完成注册页面发现 + 表单字段识别 + 密码测试。
    """

    def __init__(self, driver, site_url: str):
        self.driver = driver
        self.site_url = site_url
        self.link_discovery = LoginLinkDiscovery(driver)

        from urllib.parse import urlparse
        parsed = urlparse(site_url)
        self.test_site = parsed.hostname or site_url

        self.signup_url = None
        self.email_xpath = None
        self.password_xpath = None
        self._tester = None

    # ------------------------------------------------------------------
    # Phase 1+2: Node.js 检测（URL + 字段一体完成）
    # ------------------------------------------------------------------

    def discover_signup_page(self) -> bool:
        """运行 Node.js 表单检测，获取注册 URL 和字段 XPath"""
        _safe_print(f"[*] Phase 1+2: Node.js 表单检测 {self.site_url} ...")

        # Node.js detector 一次性返回 URL + 字段
        self.signup_url = self.link_discovery.navigate_to_signup(self.site_url)

        if not self.signup_url:
            _safe_print("    ✗ 未发现注册页面")
            return False

        _safe_print(f"    ✓ 注册页面: {self.signup_url}")

        # 获取缓存的字段检测结果
        email_xpath, password_xpath = self.link_discovery.find_signup_fields()

        if email_xpath:
            self.email_xpath = email_xpath
            _safe_print(f"    ✓ 邮箱字段: {email_xpath}")
        else:
            _safe_print("    ✗ 未检测到邮箱字段")

        if password_xpath:
            self.password_xpath = password_xpath
            _safe_print(f"    ✓ 密码字段: {password_xpath}")
        else:
            _safe_print("    ✗ 未检测到密码字段")

        # Selenium 导航到 Node.js 发现的注册页面
        if self.signup_url:
            _safe_print(f"    Selenium 导航到: {self.signup_url}")
            try:
                self.driver.get(self.signup_url)
                time.sleep(2)
            except Exception as e:
                _safe_print(f"    ⚠ 导航警告: {e}")

        return bool(self.password_xpath)

    def discover_form_fields(self) -> bool:
        """兼容旧接口：Node.js 已一次性完成检测"""
        return bool(self.password_xpath)

    # ------------------------------------------------------------------
    # Phase 3: 密码政策测试
    # ------------------------------------------------------------------

    def _checkpoint_policy(self, policy: dict, stage: str):
        """把当前已测到的密码政策增量落盘到 logs/<host>/policy_<host>.partial.json。

        测量是分阶段进行的，尾部（permissive 字符/序列/泄露密码）可能因浏览器
        崩溃而中断。每个关键阶段后落盘，即使中途硬崩，已测出的长度/组合等核心
        政策也不会丢。写入失败不打断主流程。
        """
        try:
            import json
            import os
            # Intermediate checkpoints must carry the probe trace collected
            # so far. Previously it was attached only in the final ``finally``
            # block, so a hard watchdog timeout preserved inferred fields but
            # lost the accepted/rejected evidence needed to audit them.
            if getattr(self, "_tester", None) is not None:
                policy["_probe_evidence"] = list(
                    getattr(self._tester, "_probe_evidence", []) or [])
            host = self.test_site or "unknown"
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            site_dir = os.path.join(project_root, "logs", host)
            os.makedirs(site_dir, exist_ok=True)
            path = os.path.join(site_dir, f"policy_{host}.partial.json")
            payload = {
                "url": self.site_url,
                "hostname": host,
                "stage": stage,
                "policy": policy,
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def run_password_policy_test(self) -> dict:
        """执行完整的密码政策突变测试（14 个维度）"""
        if not self.signup_url or not self.password_xpath:
            raise RuntimeError(
                "Must call discover_signup_page() first. "
                f"signup_url={self.signup_url}, password_xpath={self.password_xpath}"
            )

        _safe_print("[*] Phase 3: 执行密码政策测试...")
        my_logger = uub.get_logger(self.test_site)

        self._tester = TestPassword(
            my_logger,
            self.test_site,
            signup_url=self.signup_url,
            email_xpath=self.email_xpath,
            password_xpath=self.password_xpath,
            driver=self.driver,
            password_frame_path=getattr(self, 'password_frame_path', None),
        )
        # 传播页面就绪标志：main.py 中 Phase 3 (_detect_method) 已在注册页上
        # 完成 inline 反馈检测，浏览器停留在注册表单页面。设置此标志防止
        # test_one_password() 内部 driver.get(signup_url) 重新加载导致
        # SPA 模态框关闭（signup_url 对 SPA 站为首页 URL，get() 会关闭弹窗）
        if getattr(self, '_signup_page_ready', False):
            self._tester._signup_page_ready = True

        password_policy = {
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
            }
        }
        password_policy["_measurement_identity"] = dict(
            getattr(self._tester, "measurement_identity", {}) or {})

        # Capture declarations before the first active mutation.  This tier is
        # kept separate from measured fields so a useful partial result does
        # not silently become a claimed complete measurement.
        try:
            dom_evidence = self._tester.extract_dom_policy_evidence()
            if (isinstance(dom_evidence, dict)
                    and has_substantive_dom_evidence(dom_evidence)):
                password_policy["_declared_policy_evidence"] = dom_evidence
        except Exception:
            pass

        try:
            # 先用明显非法的一字符密码建立负对照。若当前表单连该候选都不给出
            # 密码专属拒绝证据，就无法把后续“没变红/没报错”解释为接受。
            if not self._tester.establish_inline_control():
                password_policy["_inconclusive"] = True
                password_policy["_inconclusive_reason"] = (
                    "negative_control_not_rejected: inline 表单未对一字符密码给出"
                    "明确密码专属拒绝证据"
                )
                _safe_print("    ⚠ inline 负对照未成立，停止政策推断并回退仅分类")
                # 提示政策解析：负对照虽不成立，但页面规则提示（gamersky
                # "6-20位"等）含政策线索。先填一个短密码触发提示闪现，
                # 再扫描页面文本。
                try:
                    _hint = self._tester.extract_hint_policy()
                    if _hint.get("raw_texts"):
                        password_policy["_hint_policy"] = _hint
                        password_policy["_inconclusive_reason"] += (
                            "；页面提示政策: {}".format(_hint))
                        _safe_print(f"    页面提示政策: {_hint}")
                except Exception:
                    pass
                return password_policy

            admissible = self._tester.find_admissible_password()
            if not admissible:
                # P3 缺陷1/6 修复：admissible 找不到时不能返回"全 False 空政策"——
                # 下游会把它当成"站点无任何限制"（错误传导）。必须显式标记
                # inconclusive，让调用方知道这是"无法推断"而非"无限制"。
                password_policy["_inconclusive"] = True
                password_policy["_inconclusive_reason"] = (
                    "admissible_password_not_found: 无法找到可接受的密码")
                _safe_print("    ✗ 无法找到可接受的密码")
                # 提示政策解析：admissible 找不到（可能误判连坐拒绝），
                # 页面提示仍可作线索。
                try:
                    _hint = self._tester.extract_hint_policy()
                    if _hint.get("raw_texts"):
                        password_policy["_hint_policy"] = _hint
                        password_policy["_inconclusive_reason"] += (
                            "；页面提示政策: {}".format(_hint))
                        _safe_print(f"    页面提示政策: {_hint}")
                except Exception:
                    pass
                return password_policy
            _safe_print(f"    ✓ 可接受密码: {admissible}")
            uub.random_sleep([3, 5])

            rp = password_policy["restrictive"]

            # ── 突变阶段中间控制点（P3 缺陷4：副作用隔离）──
            # 7 个连续突变步骤会积累页面状态（残留错误/弹窗状态漂移），
            # 每 2~3 步插入一次"负对照+基准"复验，任一漂移即停止推断，
            # 避免后续步骤在污染状态下测出垃圾值。
            def _control_pair(label: str) -> bool:
                if not self._tester.establish_inline_control() or not \
                        self._tester.test_one_password(admissible, label):
                    return False
                return True

            rp["r_no_a_sps"] = self._tester.check_special_symbols(admissible)
            _safe_print(f"    r_no_a_sps: {rp['r_no_a_sps']}")

            rp["r_2_word"] = self._tester.change_and_test_2_word_password()
            _safe_print(f"    r_2_word: {rp['r_2_word']}")

            rp["r_l_start"] = self._tester.change_and_test_letter_start_password(rp["r_2_word"])
            _safe_print(f"    r_l_start: {rp['r_l_start']}")

            if not _control_pair("phase control: revalidate after letter-start"):
                password_policy["_inconclusive"] = True
                password_policy["_inconclusive_reason"] = \
                    "control_pair_drifted_after_letter_start_step"
                return password_policy

            composition = self._tester.identify_adaptive_composition(rp)
            password_policy["_adaptive_composition"] = composition
            _safe_print(
                "    字符组成(自适应): 至少{}类, 必需类={}, 探针={}, 状态={}".format(
                    composition.get("minimum_character_classes"),
                    composition.get("required_classes"),
                    composition.get("probes_used"),
                    composition.get("status"),
                ))
            if composition.get("status") == "inconclusive":
                password_policy["_inconclusive"] = True
                password_policy["_inconclusive_reason"] = (
                    "adaptive_composition_probe_inconclusive: "
                    + str(composition.get("stop_reason") or "unknown"))
                return password_policy
            if composition.get("status") == "partial":
                password_policy["_composition_partial"] = True

            # 固定顺序的连续突变可能积累页面状态或触发策略切换。进入长度阶段前
            # 重新跑“负对照 + 已知基准”配对，二者任一漂移就停止推断。
            if not _control_pair("phase control: revalidate admissible before length"):
                password_policy["_inconclusive"] = True
                password_policy["_inconclusive_reason"] = \
                    "control_pair_drifted_before_length_phase"
                return password_policy

            password_policy["length"][0], password_policy["length"][1] = \
                self._tester.identify_min_and_max_length_limitations(rp, [0, 32], [6, 128])
            adaptive = getattr(self._tester, "_adaptive_summary", None)
            if adaptive:
                password_policy["_adaptive"] = adaptive
                boundary_states = {
                    adaptive["minimum"].get("status"),
                    adaptive["maximum"].get("status"),
                }
                if "inconclusive" in boundary_states:
                    password_policy["_inconclusive"] = True
                    password_policy["_inconclusive_reason"] = (
                        "adaptive_length_probe_inconclusive: "
                        + str(adaptive.get("stop_reason") or "unknown")
                    )
                    return password_policy
            _safe_print(
                f"    长度: min={password_policy['length'][0]}, "
                f"max={password_policy['length'][1]}")
            self._checkpoint_policy(password_policy, "length_done")

            # 方案 A 联动：max 未检出（None）时，下游 permissive 测试仍需要一个可用
            # 长度来构造密码，降级为 admissible 密码长度，避免 None 传播导致崩溃。
            _eff_max = password_policy["length"][1]
            if _eff_max is None:
                _eff_max = max(password_policy["length"][0], len(admissible))
            _eff_length = [password_policy["length"][0], _eff_max]

            # 长度探测后重新验证控制对，确认页面状态没有因连续探针漂移。
            if not self._tester.establish_inline_control() or not \
                    self._tester.test_one_password(
                        admissible, "phase control: revalidate admissible after adaptive probes"):
                password_policy["_inconclusive"] = True
                password_policy["_inconclusive_reason"] = \
                    "control_pair_drifted_after_adaptive_probe_phases"
                return password_policy

            # 主动寻找“短口令要求严格组成，较长口令放宽组成”的 OR 分支。
            # 这是独立扩展维度；它的证据不足不撤销已经完成的长度/组成结论。
            _had_inconclusive_before_conditional = getattr(
                self._tester, "_had_inconclusive", False)
            conditional = self._tester.identify_adaptive_conditional_policy(
                rp, adaptive, composition)
            password_policy["_adaptive_conditional"] = conditional
            if conditional.get("status") == "detected":
                password_policy["_or_rule"] = conditional.get("rule")
                _safe_print(
                    "    条件政策: {}位起放宽为{}类({}), 探针={}".format(
                        conditional.get("relaxed_length_threshold"),
                        len(conditional.get("relaxed_subset") or []),
                        conditional.get("relaxed_subset"),
                        conditional.get("probes_used"),
                    ))
            elif conditional.get("status") == "inconclusive":
                password_policy["_conditional_inconclusive"] = True
                self._tester._had_inconclusive = \
                    _had_inconclusive_before_conditional

            if conditional.get("probes_used", 0) > 0 and not _control_pair(
                    "phase control: revalidate after conditional policy probes"):
                password_policy["_inconclusive"] = True
                password_policy["_inconclusive_reason"] = \
                    "control_pair_drifted_after_conditional_policy_phase"
                return password_policy

            # ── P3 自洽校验：用已推断约束反推密码验证模型一致性 ──
            # 模型是 AND 语义，无法表达 OR 规则（如 GitHub "≥15位 或
            # ≥8位含数字+小写"）。若反推密码与推断约束矛盾，说明模型
            # 无法解释站点行为 → 标记 inconclusive，但保留 OR 规则刻画
            # 结果（_or_rule），让消费方看到已探测到的真实行为。
            _consistent, _consistency_note, _or_rule = \
                self._tester.self_consistency_check(rp, _eff_length, admissible)
            if not _consistent:
                password_policy["_inconclusive"] = True
                password_policy["_inconclusive_reason"] = _consistency_note
                if _or_rule:
                    password_policy.setdefault("_or_rule", _or_rule)
                    _safe_print(f"    ⚠ 自洽校验失败(OR规则): {_consistency_note}")
                    _safe_print(f"    _or_rule: {_or_rule}")
                else:
                    _safe_print(f"    ⚠ 自洽校验失败: {_consistency_note}")
                return password_policy
            _safe_print(f"    自洽校验: {_consistency_note}")

            if not self._tester.establish_inline_control() or not \
                    self._tester.test_one_password(
                        admissible, "phase control: revalidate admissible before permissive"):
                password_policy["_inconclusive"] = True
                password_policy["_inconclusive_reason"] = \
                    "control_pair_drifted_before_permissive_phase"
                return password_policy

            password_policy["permissive"]["permitted_characters"] = \
                self._tester.identify_permissive_characters(_eff_length)
            self._checkpoint_policy(password_policy, "permitted_characters_done")
            password_policy["permissive"]["short_and_long_password"] = \
                self._tester.identify_long_short_passwords(_eff_length)
            password_policy["permissive"]["breached_password"] = \
                self._tester.identify_breached_passwords(rp, _eff_length)
            password_policy["permissive"]["permitted_sequences"] = \
                self._tester.identify_permitted_sequences(rp, _eff_length)

        except BrowserDeadError as e:
            _safe_print(f"    ✗ 浏览器会话终止，测量中止: {e}")
            password_policy["_browser_dead"] = True
        except Exception as e:
            _safe_print(f"    ✗ 测试过程出错: {e}")
            import traceback
            traceback.print_exc()
            if getattr(self._tester, "_browser_dead", False):
                password_policy["_browser_dead"] = True
        finally:
            password_policy["_probe_evidence"] = list(
                getattr(self._tester, "_probe_evidence", []))
            self._tester.my_logger.info(f"Policy of {self.test_site}: {password_policy}")
            self._checkpoint_policy(password_policy, "final")

        # 门控表单 + 全程未观察到任何密码专属拒绝 → "全接受"结论不可信
        if getattr(self._tester, '_gated_form', False) and \
                not getattr(self._tester, '_saw_pwd_specific_reject', False):
            password_policy["_gated_form_unverifiable"] = True
            _safe_print("    ⚠ 门控表单：全程无密码专属拒绝信号，政策可能无法据此验证")

        if getattr(self._tester, '_had_inconclusive', False):
            password_policy["_inconclusive"] = True
            password_policy.setdefault(
                "_inconclusive_reason",
                "at_least_one_password_probe_lacked_accept_or_reject_evidence",
            )
            _safe_print("    ⚠ 至少一个候选缺少明确证据，整份政策降级为无法判断")

        return password_policy

    # ------------------------------------------------------------------
    # 一键运行
    # ------------------------------------------------------------------

    def run_full_test(self) -> dict:
        """一键运行完整测试流程"""
        if not self.discover_signup_page():
            _safe_print("[!] 无法发现注册页面")
            return {}
        if not self.discover_form_fields():
            _safe_print("[!] 无法检测表单字段")
            return {}
        return self.run_password_policy_test()
