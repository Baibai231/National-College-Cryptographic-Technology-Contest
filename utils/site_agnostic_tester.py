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

import time
import utils.util_basic as uub
from utils.login_link_discovery import LoginLinkDiscovery
from utils.util_test_password import TestPassword, BrowserDeadError


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
        print(f"[*] Phase 1+2: Node.js 表单检测 {self.site_url} ...")

        # Node.js detector 一次性返回 URL + 字段
        self.signup_url = self.link_discovery.navigate_to_signup(self.site_url)

        if not self.signup_url:
            print("    ✗ 未发现注册页面")
            return False

        print(f"    ✓ 注册页面: {self.signup_url}")

        # 获取缓存的字段检测结果
        email_xpath, password_xpath = self.link_discovery.find_signup_fields()

        if email_xpath:
            self.email_xpath = email_xpath
            print(f"    ✓ 邮箱字段: {email_xpath}")
        else:
            print(f"    ✗ 未检测到邮箱字段")

        if password_xpath:
            self.password_xpath = password_xpath
            print(f"    ✓ 密码字段: {password_xpath}")
        else:
            print(f"    ✗ 未检测到密码字段")

        # Selenium 导航到 Node.js 发现的注册页面
        if self.signup_url:
            print(f"    Selenium 导航到: {self.signup_url}")
            try:
                self.driver.get(self.signup_url)
                time.sleep(2)
            except Exception as e:
                print(f"    ⚠ 导航警告: {e}")

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

        print(f"[*] Phase 3: 执行密码政策测试...")
        my_logger = uub.get_logger(self.test_site)

        self._tester = TestPassword(
            my_logger,
            self.test_site,
            signup_url=self.signup_url,
            email_xpath=self.email_xpath,
            password_xpath=self.password_xpath,
            driver=self.driver,
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

        try:
            admissible = self._tester.find_admissible_password()
            if not admissible:
                print("    ✗ 无法找到可接受的密码")
                return password_policy
            print(f"    ✓ 可接受密码: {admissible}")
            uub.random_sleep([3, 5])

            rp = password_policy["restrictive"]

            rp["r_no_a_sps"] = self._tester.check_special_symbols(admissible)
            print(f"    r_no_a_sps: {rp['r_no_a_sps']}")

            rp["r_2_word"] = self._tester.change_and_test_2_word_password()
            print(f"    r_2_word: {rp['r_2_word']}")

            rp["r_l_start"] = self._tester.change_and_test_letter_start_password(rp["r_2_word"])
            print(f"    r_l_start: {rp['r_l_start']}")

            rp["r_dig_min"] = self._tester.change_and_test_digit_minimum(rp["r_no_a_sps"])
            print(f"    r_dig_min: {rp['r_dig_min']}")

            rp["r_upp_min"] = self._tester.change_and_test_lower_upper_minimum(True, rp["r_no_a_sps"])
            print(f"    r_upp_min: {rp['r_upp_min']}")

            rp["r_low_min"] = self._tester.change_and_test_lower_upper_minimum(False, rp["r_no_a_sps"])
            print(f"    r_low_min: {rp['r_low_min']}")

            rp["r_sps_min"] = self._tester.change_and_test_symbol_minimum(rp["r_no_a_sps"])
            print(f"    r_sps_min: {rp['r_sps_min']}")

            [
                rp["r_cmb13"], rp["r_cmb23"], rp["r_cmb33"],
                rp["r_cmb14"], rp["r_cmb24"], rp["r_cmb34"], rp["r_cmb44"]
            ] = self._tester.identify_combination_requirements(rp)
            print(f"    组合(细粒度): 14={rp['r_cmb14']} 24={rp['r_cmb24']} "
                  f"34={rp['r_cmb34']} 44={rp['r_cmb44']}")

            password_policy["length"][0], password_policy["length"][1] = \
                self._tester.identify_min_and_max_length_limitations(rp, [0, 32], [6, 128])
            print(f"    长度: min={password_policy['length'][0]}, max={password_policy['length'][1]}")
            self._checkpoint_policy(password_policy, "length_done")

            password_policy["permissive"]["permitted_characters"] = \
                self._tester.identify_permissive_characters(password_policy["length"])
            self._checkpoint_policy(password_policy, "permitted_characters_done")
            password_policy["permissive"]["short_and_long_password"] = \
                self._tester.identify_long_short_passwords(password_policy["length"])
            password_policy["permissive"]["breached_password"] = \
                self._tester.identify_breached_passwords(rp, password_policy["length"])
            password_policy["permissive"]["permitted_sequences"] = \
                self._tester.identify_permitted_sequences(rp, password_policy["length"])

        except BrowserDeadError as e:
            print(f"    ✗ 浏览器会话终止，测量中止: {e}")
            password_policy["_browser_dead"] = True
        except Exception as e:
            print(f"    ✗ 测试过程出错: {e}")
            import traceback
            traceback.print_exc()
            if getattr(self._tester, "_browser_dead", False):
                password_policy["_browser_dead"] = True
        finally:
            self._tester.my_logger.info(f"Policy of {self.test_site}: {password_policy}")
            self._checkpoint_policy(password_policy, "final")

        return password_policy

    # ------------------------------------------------------------------
    # 一键运行
    # ------------------------------------------------------------------

    def run_full_test(self) -> dict:
        """一键运行完整测试流程"""
        if not self.discover_signup_page():
            print("[!] 无法发现注册页面")
            return {}
        if not self.discover_form_fields():
            print("[!] 无法检测表单字段")
            return {}
        return self.run_password_policy_test()
