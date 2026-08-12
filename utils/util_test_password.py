import os
import re
import stat
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from loguru import logger
from enum import Enum
import faker
import pandas as pd

import utils.util_basic as uub
import utils.util_str_generator as uusg
from config.config import Config


def _admissible_cache_path(test_site: str, strength: str = None) -> str:
    """admissible password 缓存文件路径（logs/{site}/admissible_{site}.txt），
    中断重跑时直接复用，避免从头开始找可接受密码。

    strength: 可选 "strong" | "medium" | "weak"，有值时生成
              logs/{site}/admissible_{site}_{strength}.txt 按强度分类。
    """
    import os
    site_dir = Config.PROJECT_ROOT / "logs" / test_site
    os.makedirs(str(site_dir), exist_ok=True)
    suffix = f"_{strength}" if strength else ""
    return str(site_dir / f"admissible_{test_site}{suffix}.txt")


class CR(Enum):
    LETTER_R = 0
    LOWER_R = 1
    UPPER_R = 2
    DIGIT_R = 3
    SYMBOL_R = 4


class RMB(Enum):
    R13 = 0
    R23 = 1
    R33 = 2
    R14 = 3
    R24 = 4
    R34 = 5
    R44 = 6


def get_cr(restrictive_pr):
    cr4, cr3 = 0, 0
    if restrictive_pr["r_cmb13"]:
        cr3 = 1
    elif restrictive_pr["r_cmb23"]:
        cr3 = 2
    elif restrictive_pr["r_cmb33"]:
        cr3 = 3
    else:
        cr3 = 0

    if restrictive_pr["r_cmb14"]:
        cr4 = 1
    elif restrictive_pr["r_cmb24"]:
        cr4 = 2
    elif restrictive_pr["r_cmb34"]:
        cr4 = 3
    elif restrictive_pr["r_cmb44"]:
        cr4 = 4
    else:
        cr4 = 0
    return cr4, cr3


def check_policy(tmp_pw, rp, pl):
    """

    :param pl: password length
    :param tmp_pw:
    :param rp: restrictive parameters
    """
    cr4, cr3 = get_cr(rp)
    ps = uub.get_password_structure(tmp_pw)
    if (
            len(tmp_pw) < pl[0] or
            len(tmp_pw) > pl[1] or
            ps["cr4"] < cr4 or
            ps["cr3"] < cr3 or
            ps["digit"] < rp["r_dig_min"] or
            ps["symbol"] < rp["r_sps_min"] or
            ps["lower"] < rp["r_low_min"] or
            ps["upper"] < rp["r_upp_min"] or
            (rp["r_l_start"] and not tmp_pw[0].isalpha()) or
            (rp["r_no_a_sps"] and ps["symbol"] > 0)
    ):
        # print("Coming here")
        return False
    if rp["r_2_word"]:
        if ps["letter"] < 6 or (ps["digit"] == 0 and ps["symbol"] == 0):
            return False
        pattern = re.compile(r'\b[A-Za-z]{3,}[0-9!@#$%^&*()_+}{":?><;.,]{1}[A-Za-z]{3,}\b')
        if len(pattern.findall(tmp_pw)) == 0:
            return False
    return True


def padding_pw_suitable(pw, pass_len, is_2_word, add_pw, after_pw):
    min_len = pass_len[0]
    max_len = pass_len[1]
    ret_str = ""
    if len(after_pw) == 0:
        return None
    elif len(after_pw) > max_len:
        # TODO: adjust the password to cluster the letters -- not worked
        # Adjust all letters to the begin, if 2_word is true, then change the word pass
        pw += uusg.gen_random_str_no_symbol(max_len - len(pw))
        lower_letters = ''.join(char for char in pw if pw.islower())
        upper_letters = ''.join(char for char in pw if pw.isupper())
        di_sy_letters = ''.join(char for char in pw if not pw.isalpha())

        if len(lower_letters) >= 5:
            lower_letters = lower_letters[:-4] + add_pw + lower_letters[-1]
        elif len(upper_letters) >= 4:
            upper_letters = upper_letters[:-3] + add_pw
        if is_2_word:
            ret_str = lower_letters + di_sy_letters[0] + upper_letters + di_sy_letters[1:]
        else:
            ret_str = lower_letters + di_sy_letters + upper_letters
    elif min_len <= len(after_pw) <= max_len:
        ret_str = after_pw
    else:
        ret_str = after_pw + uusg.gen_random_str_no_symbol(min_len - len(after_pw))
    return ret_str


# ==================== 共享 driver 模块级补丁 ====================
# 问题 1: ChromeDriverManager().install() 每次都去 Google CDN 查最新版本号，
#         SSL 握手在国内超时，导致整个流程卡死。
# 问题 2: test_one_password() 每测一个密码就新建一个 webdriver.Chrome() 实例，
#         GitHub DataDome 检测到短时间内多个无状态 Chrome 窗口反复打开/关闭
#         signup 页面，判定为 bot 并抛出 CAPTCHA。
# 方案: ① monkey-patch ChromeDriverManager.install() 直接返回本地缓存路径
#       ② 共享单个 Chrome driver 实例，所有密码测试复用同一个浏览器进程
#       （逻辑与 utils/browser/CAPDriver.py 的 _find_real_chromedriver 一致）

_SHARED_DRIVER = None


def _is_real_chromedriver_binary(path):
    """通过 ELF (Linux) / Mach-O (macOS) / PE (Windows) magic bytes 识别
    真正的 chromedriver 二进制，排除 THIRD_PARTY_NOTICES 等文本文件。"""
    if not path or not os.path.isfile(path):
        return False
    basename = os.path.basename(path)
    if basename not in ("chromedriver", "chromedriver.exe"):
        return False
    try:
        with open(path, "rb") as fh:
            magic = fh.read(4)
    except OSError:
        return False
    if magic[:2] == b"\x7f\x45":            # ELF
        return True
    if magic[:4] == b"\xcf\xfa\xed\xfe":   # Mach-O
        return True
    if magic[:2] == b"MZ":                 # PE
        return True
    return False


def _find_cached_chromedriver():
    """在 ~/.wdm 缓存中搜索真正的 chromedriver 二进制，自动 chmod +x"""
    candidates = []
    wdm_root = os.path.join(os.path.expanduser("~"), ".wdm", "drivers", "chromedriver")
    if os.path.isdir(wdm_root):
        for root, _dirs, files in os.walk(wdm_root):
            for f in files:
                if f in ("chromedriver", "chromedriver.exe"):
                    candidates.append(os.path.join(root, f))
    # 按文件大小降序排列——真正的 21MB 二进制远大于 1.3MB 文本文件
    for c in sorted(candidates, key=os.path.getsize, reverse=True):
        if _is_real_chromedriver_binary(c):
            st = os.stat(c)
            if not (st.st_mode & stat.S_IXUSR):
                os.chmod(c, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            return c
    return None


def _patch_chromedriver_manager():
    """Monkey-patch webdriver-manager，让 install() 直接返回本地缓存路径"""
    from webdriver_manager.chrome import ChromeDriverManager as _CDM
    chromedriver_path = _find_cached_chromedriver()
    if chromedriver_path is None:
        return  # 没找到缓存，保持原行为（让它走网络）
    _orig_install = _CDM.install

    def _cached_install(self):
        return chromedriver_path

    _CDM.install = _cached_install
    return chromedriver_path


# 模块加载时立即执行 patch
_CHROMEDRIVER_BIN = _patch_chromedriver_manager()


def _get_proxy_config():
    """从环境变量读取代理配置（供 Chrome 使用）。
    优先级：CRAWL_PROXY > HTTPS_PROXY > HTTP_PROXY。
    返回代理 URL 字符串，未配置时返回 None。"""
    for name in ("CRAWL_PROXY", "HTTPS_PROXY", "HTTP_PROXY"):
        val = os.environ.get(name)
        if val and val.strip():
            return val.strip()
    return None


def _inject_form_detection_js(driver):
    """通过 CDP 注入 form_detection_addons.js + scripts.js (Fathom)。

    每个新页面加载时自动在全局作用域执行，使 detectPasswordFeedback()
    和 detectEmailInputs() 等函数在页面上下文中可用。
    幂等：重复调用不会重复注入。
    """
    js_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "js")
    _injected_marker = "_form_detection_js_injected"

    if getattr(driver, _injected_marker, False):
        return

    for filename in ["scripts.js", "form_detection_addons.js"]:
        path = os.path.join(js_dir, filename)
        if not os.path.isfile(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            js_source = f.read()
        try:
            driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": js_source},
            )
        except Exception:
            # CDP 可能断开（浏览器崩溃/关闭），静默跳过
            pass

    setattr(driver, _injected_marker, True)


def _get_shared_driver():
    """获取共享 undetected-chromedriver 实例。

    使用 undetected-chromedriver 替代原生 Chrome WebDriver，
    自动隐藏自动化特征（navigator.webdriver / CDP Runtime
    flag 等），绕过 Cloudflare / DataDome 等 CDN 防护。

    首次调用时创建，后续调用复用同一进程。
    如果浏览器进程已死（被手动关闭/崩溃），自动重建。"""
    global _SHARED_DRIVER
    if _SHARED_DRIVER is not None:
        try:
            _SHARED_DRIVER.current_url  # 健康检查
            return _SHARED_DRIVER
        except Exception:
            _SHARED_DRIVER = None

    import undetected_chromedriver as uc

    options = Options()
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    # undetected-chromedriver 自动处理以下反检测补丁:
    #   --disable-blink-features=AutomationControlled
    #   excludeSwitches: enable-automation
    #   useAutomationExtension: false

    # 代理支持
    proxy_url = _get_proxy_config()
    if proxy_url:
        masked = proxy_url.split("@")[-1] if "@" in proxy_url else proxy_url
        logger.info(f"Chrome 使用代理: {masked}")
        options.add_argument(f"--proxy-server={proxy_url}")

    if _CHROMEDRIVER_BIN:
        _SHARED_DRIVER = uc.Chrome(options=options, driver_executable_path=_CHROMEDRIVER_BIN, version_main=150)
    else:
        _SHARED_DRIVER = uc.Chrome(options=options, version_main=150)

    _SHARED_DRIVER.maximize_window()
    _SHARED_DRIVER.set_page_load_timeout(25)

    # 注入 Fathom + 表单检测 JS（幂等，每个新页面自动执行）
    _inject_form_detection_js(_SHARED_DRIVER)

    return _SHARED_DRIVER


def _get_new_driver():
    """创建全新的 undetected-chromedriver 实例（不缓存，用于并发模式）。

    每个并发 worker 线程需要独立的 WebDriver 实例，
    因此不共享全局单例。使用完毕后调用者负责 driver.quit()。

    包含反自动化检测标志 + notABot.js CDP 注入，
    与 CAPDriver 保持一致的隐身级别。
    """
    import undetected_chromedriver as uc

    options = Options()
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    # ── 反自动化检测标志 ──
    # 注意: excludeSwitches / useAutomationExtension 与 undetected-chromedriver
    #       不兼容（后者内部已处理），只保留 Chrome flag 级别选项
    options.add_argument("--disable-blink-features=AutomationControlled")

    proxy_url = _get_proxy_config()
    if proxy_url:
        masked = proxy_url.split("@")[-1] if "@" in proxy_url else proxy_url
        logger.info(f"Chrome (new) 使用代理: {masked}")
        options.add_argument(f"--proxy-server={proxy_url}")

    if _CHROMEDRIVER_BIN:
        driver = uc.Chrome(options=options, driver_executable_path=_CHROMEDRIVER_BIN)
    else:
        driver = uc.Chrome(options=options)

    driver.maximize_window()
    driver.set_page_load_timeout(30)

    # ── CDP 注入 notABot.js（与 CAPDriver 对齐） ──
    _notabot_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "js", "notABot.js"
    )
    if os.path.isfile(_notabot_path):
        try:
            with open(_notabot_path, "r", encoding="utf-8") as f:
                notabot_js = f.read()
            driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": notabot_js},
            )
        except Exception:
            pass

    # 注入 Fathom + 表单检测 JS（detectPasswordFeedback 等，幂等）
    _inject_form_detection_js(driver)

    return driver


class TestPassword(object):
    def __init__(self, my_logger, test_site, admissible_password="",
                 signup_url="", email_xpath="", password_xpath="",
                 driver=None):
        self.fake = faker.Faker()
        # 2026-08 更新：GitHub 新政策为"至少15位，或至少8位+数字+小写"，
        # 且拒绝泄露密码与连续序列。旧密码池（2023年，6-10位）已全部失效。
        # 新候选已实测通过（非泄露、非序列）。
        self.admissible_password_list = {
            "8": [
                "k4m2x9a7", "v5n3b8q1", "p7c3w6z2", "t9f4d1s6",
                "x6q1z9m3", "n2b7w4k8"
            ],
            "9": [
                "k4m2x9a7t", "v5n3b8q1w"
            ],
            "10": [
                "k4m2x9a7ty", "v5n3b8q1wf"
            ]
        }
        self.my_logger = my_logger
        self.test_site = test_site
        self.username = uusg.gen_random_email()
        self.admissible_password = admissible_password
        # 同页面复用标志：页面已加载并填好邮箱时为 True，
        # 后续测试只重填密码字段，避免每个密码都重新加载页面（减少请求量，缓解限速）
        self._signup_page_ready = False
        # 最近一次 test_one_password 成功时检测到的密码强度等级
        # 可能值: "strong" | "medium" | "weak" | None（无强度计）
        self._last_strength_level = None
        # ===== 参数化：支持任意网站的注册表单 =====
        self.signup_url = signup_url
        self.email_xpath = email_xpath
        self.password_xpath = password_xpath
        # 使用调用方传入的 driver，而非全局单例 _SHARED_DRIVER
        # 确保与分类器/链接发现使用同一浏览器实例（SPA 弹窗不丢失）
        self._driver = driver

    @logger.catch
    def find_admissible_password(self):
        """
        find the admissible password
        :return: return admissible password
        """
        self.my_logger.info(f"Begin finding the admissible password for {self.test_site}.")
        cache_path = _admissible_cache_path(self.test_site)
        if os.path.isfile(cache_path):
            cached = open(cache_path, "r", encoding="utf-8").read().strip()
            if cached:
                self.my_logger.info(f"使用缓存的 admissible password: {cached}")
                self.admissible_password = cached
                return cached
        flag = False
        # GitHub 新政策下 6-7 位密码必被拒，直接从 8 开始
        for i in range(8, 33):
            if i <= 10:
                test_pwd_list = self.admissible_password_list[str(i)]
            else:
                sub_cnt = i - 10
                sub_str = uusg.gen_random_str_no_symbol(sub_cnt)
                test_pwd_list = [
                    self.admissible_password_list["10"][0] + sub_str,
                    self.admissible_password_list["10"][1] + sub_str
                ]
            ret = False
            for pwd in test_pwd_list:
                ret = self.test_one_password(pwd, "Find the admissible name")
                if ret:
                    flag = True
                    self.admissible_password = pwd
                    break
            if ret:
                break

        if not flag:
            self.my_logger.warning("There is no admissible password available.")
        else:
            # ── 按密码强度等级分类保存 ──
            # 有强度计时按强/中/弱分类，无强度计时统一保存
            strength = getattr(self, '_last_strength_level', None)
            if strength:
                cache_path = _admissible_cache_path(self.test_site, strength)
            with open(cache_path, "w", encoding="utf-8") as f:
                f.write(self.admissible_password)
            self.my_logger.info(f"已缓存 admissible password 到 {cache_path}")
            # 同时保存一份无分类的主缓存（向后兼容）
            main_cache = _admissible_cache_path(self.test_site)
            if strength and cache_path != main_cache:
                with open(main_cache, "w", encoding="utf-8") as f:
                    f.write(self.admissible_password)
        return self.admissible_password

    def _parse_strength_level(self, strength_text: str) -> None:
        """从强度计文本解析密码强度等级，存到 self._last_strength_level。

        仅作为备注和日志输出，不参与密码接受/拒绝的决策。
        决策唯一依据是密码输入框是否变红（field-state 检查）。
        """
        if not strength_text:
            self._last_strength_level = None
            return
        _msg_lower = strength_text.lower()
        # 优先英文匹配
        if any(w in _msg_lower for w in ['very strong', 'excellent']):
            self._last_strength_level = 'strong'
        elif any(w in _msg_lower for w in ['strong', 'high', 'good', 'great']):
            self._last_strength_level = 'strong'
        elif any(w in _msg_lower for w in ['medium', 'moderate', 'fair', 'normal']):
            self._last_strength_level = 'medium'
        elif any(w in _msg_lower for w in ['weak', 'low', 'poor', 'bad']):
            self._last_strength_level = 'weak'
        # 中文匹配
        elif '强' in strength_text and '弱' not in strength_text:
            self._last_strength_level = 'strong'
        elif '中' in strength_text:
            self._last_strength_level = 'medium'
        elif '弱' in strength_text:
            self._last_strength_level = 'weak'
        else:
            self._last_strength_level = None

    @logger.catch
    def test_one_password(self, test_password, info_name="Default Name for the process."):
        """
        test whether the password will be accepted by the website
        :param test_password: the tested password
        :param info_name: the information of the testing process
        :return: True or False indicates the result
        """
        self.my_logger.info(f"Tested password: {test_password} -- {info_name}")
        self.my_logger.debug(f"Begin to simulate testing the password {test_password} for signing up an account.")
        retries = 1
        while retries <= 5:
            # 使用调用方传入的 driver（而非全局单例），
            # 确保与分类器/链接发现共享同一浏览器实例
            driver = self._driver or _get_shared_driver()
            try:
                self.my_logger.debug(f"Begin the {retries}-(st/nd/rd/th) attempt(s).")
                # 同页面复用：页面已就绪时只重填密码字段，不重新加载页面
                if not self._signup_page_ready:
                    if not self.signup_url:
                        self.my_logger.error("signup_url is not set; cannot navigate to signup page.")
                        return False
                    driver.get(self.signup_url)
                    self.my_logger.debug(f"Access the signup page: {self.signup_url}")
                    uub.random_sleep([1, 2])
                    # find the email input field and fill it (if available)
                    if self.email_xpath:
                        try:
                            email_elem = WebDriverWait(driver, 10).until(
                                EC.presence_of_element_located((By.XPATH, self.email_xpath))
                            )
                            email_elem.send_keys(self.username)
                            self.my_logger.debug(f"Fill the email field with {self.username}.")
                            uub.random_sleep([1, 2])
                        except Exception:
                            self.my_logger.warning("Email input not found via xpath, continuing without email.")
                    else:
                        self.my_logger.debug("email_xpath is not set; skipping email field fill.")
                    self._signup_page_ready = True
                if not self.password_xpath:
                    self.my_logger.warning("password_xpath is not set; cannot find password field.")
                    return False
                password_elem = driver.find_element(By.XPATH, self.password_xpath)
                # React 标准输入方式：原生 value setter + input/change 双事件。
                # 顺序很重要：先移除 aria-invalid（清掉上一轮校验残留），
                # 再清空并填入新密码，等待校验重新写入属性。
                JS_RESET_PASSWORD = """
                    var elm = arguments[0];
                    elm.removeAttribute('aria-invalid');
                    var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                    setter.call(elm, '');
                    elm.dispatchEvent(new Event('input', {bubbles: true}));
                    elm.dispatchEvent(new Event('change', {bubbles: true}));
                """
                JS_ADD_TEXT_TO_INPUT = """
                    var elm = arguments[0], txt = arguments[1];
                    var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                    setter.call(elm, txt);
                    elm.dispatchEvent(new Event('input', {bubbles: true}));
                    elm.dispatchEvent(new Event('change', {bubbles: true}));
                """
                # ── 先退出上一轮密码框状态（两次测量之间必须失焦）──
                # 用 Selenium ActionChains 真实移动鼠标到密码框右侧空白处点击，
                # 而非 JS 事件模拟。真实鼠标事件才能触发浏览器原生焦点转移。
                if self._signup_page_ready:
                    try:
                        ActionChains(driver).move_to_element(
                            password_elem
                        ).move_by_offset(
                            password_elem.size['width'] + 30, 5
                        ).click().perform()
                        time.sleep(0.2)
                    except Exception:
                        pass

                # ── 启动 MutationObserver（必须先于 DOM 变更启动）──
                # 用 MutationObserver 而非静态 detectPasswordFeedback()，
                # 避免检测到表单中已存在的其他字段的错误（如"姓名为必填项"）。
                driver.execute_script(
                    "return watchPasswordFeedback(arguments[0])",
                    self.password_xpath,
                )

                driver.execute_script(JS_RESET_PASSWORD, password_elem)
                time.sleep(0.3)
                driver.execute_script(JS_ADD_TEXT_TO_INPUT, password_elem, test_password)
                # ── focus → blur 触发内联校验 ──
                # 用 Selenium ActionChains 真实鼠标移动：先点密码框聚焦，
                # 再移动到密码框右侧空白区域点击，模拟用户"填写后点别处"。
                try:
                    password_elem.click()  # 聚焦
                    time.sleep(0.2)
                    # 移动到密码框右侧 30px 处点击空白区域
                    ActionChains(driver).move_to_element(
                        password_elem
                    ).move_by_offset(
                        password_elem.size['width'] + 30, 5
                    ).click().perform()
                except Exception:
                    pass
                self.my_logger.debug(f"Fill the password field with {test_password}.")
                # 确认字段值已写入（防止 setter 失败）
                if password_elem.get_attribute("value") != test_password:
                    self.my_logger.warning(f"Password field value mismatch, treat as rejected: {test_password}")
                    try:
                        driver.execute_script("stopWatchingFeedback()")
                    except Exception:
                        pass
                    return False

                # ── 双重检测：字段自身状态决定接受/拒绝 ──
                # 核心原则：密码输入框变红（error class / :invalid / aria-invalid）
                # 是唯一的拒绝信号。密码强度计（强/中/弱）只是信息性展示，
                # 不作为接受/拒绝的判定依据，仅记录在终端和日志中。
                fb_result = None
                _strength_note = None  # 强度计文本（仅备注，不参与决策）
                deadline = time.time() + 8
                while time.time() < deadline:
                    try:
                        # 第一层：密码字段自身状态（aria-invalid / validity / :invalid / error class）
                        # 这是唯一的"密码被拒绝"信号 —— 输入框变红 = 密码不合规
                        field_state = driver.execute_script("""
                            var el = arguments[0];
                            var state = {rejected: false, reason: null};
                            if (el.getAttribute('aria-invalid') === 'true')
                                { state.rejected = true; state.reason = 'aria-invalid=true'; }
                            if (!state.rejected && el.validity && !el.validity.valid)
                                { state.rejected = true; state.reason = 'html5-invalid: ' + (el.validationMessage || '').substring(0, 100); }
                            if (!state.rejected && el.matches && el.matches(':invalid'))
                                { state.rejected = true; state.reason = 'css-invalid'; }
                            if (!state.rejected) {
                                var cls = el.className || '';
                                if (/(?:^|\\s)(error|invalid|danger)(?:\\s|$)/i.test(cls))
                                    { state.rejected = true; state.reason = 'class: ' + cls.substring(0, 50); }
                            }
                            if (!state.rejected && el.getAttribute('aria-invalid') === 'false')
                                { state.reason = 'aria-invalid=false'; }
                            return state;
                        """, password_elem)
                        if field_state and field_state.get("rejected"):
                            fb_result = {"rejected": True, "type": "field-state",
                                         "message": field_state.get("reason", "")}
                            break
                        if field_state and field_state.get("reason") == "aria-invalid=false":
                            fb_result = {"rejected": False, "type": "field-state",
                                         "message": "aria-invalid=false"}
                            break

                        # 第二层：Observer/静态扫描反馈
                        # 只关注真正的错误消息（error-element / observer-added-el），
                        # 排除强度指示器（strength-indicator）—— 它不表示拒绝。
                        results = driver.execute_script("return getWatchedFeedback()")
                        if results and len(results) > 0:
                            _non_pwd_patterns = [
                                '姓名为必填', '姓名不能为空', '请填写姓名',
                                '邮箱为必填', '邮箱不能为空', '请填写邮箱',
                                '手机号为必填', '手机不能为空', '请填写手机',
                                '用户名为必填', '验证码',
                            ]
                            for r in results:
                                rtype = r.get("type", "")
                                msg = (r.get("message") or "").lower()
                                # 跳过非密码字段错误
                                if any(p in msg for p in _non_pwd_patterns):
                                    continue
                                # 强度指示器 → 仅记录备注，不参与 accept/reject 决策
                                if rtype == 'strength-indicator':
                                    if not _strength_note:
                                        _strength_note = r.get("message", "")
                                    continue
                                # 真正的错误消息（error-element / observer-added-el）
                                if r.get("rejected"):
                                    fb_result = r
                                    break
                            if fb_result:
                                break
                    except Exception:
                        pass
                    time.sleep(0.5)

                # 停止 observer
                try:
                    driver.execute_script("stopWatchingFeedback()")
                except Exception:
                    pass

                if fb_result is None:
                    # 既无字段级错误信号（输入框未变红），也无真正的错误消息
                    # → 密码被接受。强度计文本仅作为备注记录。
                    _strength_info = ""
                    if _strength_note:
                        _strength_info = f", strength_meter=\"{_strength_note[:80]}\""
                        self._parse_strength_level(_strength_note)
                    else:
                        self._last_strength_level = None
                    self.my_logger.success(
                        f"The tested password {test_password} appears accepted"
                        f" (no rejection signal detected{_strength_info})")
                    # 退出密码框
                    try:
                        ActionChains(driver).move_to_element(
                            password_elem
                        ).move_by_offset(
                            password_elem.size['width'] + 30, 5
                        ).click().perform()
                        time.sleep(0.2)
                    except Exception:
                        pass
                    uub.random_sleep([0.5, 1])
                    return True

                fb_type = fb_result.get("type", "unknown")
                fb_msg = fb_result.get("message", "")
                if fb_result.get("rejected"):
                    flag = False
                    self.my_logger.warning(
                        f"The tested password {test_password} is rejected ({fb_type}: {fb_msg})")
                else:
                    flag = True
                    # 强度计文本（如有）仅作为备注，不参与决策
                    _strength_info = ""
                    if _strength_note:
                        _strength_info = f", strength_meter=\"{_strength_note[:80]}\""
                        self._parse_strength_level(_strength_note)
                    else:
                        self._last_strength_level = None
                    self.my_logger.success(
                        f"The tested password {test_password} is accepted ({fb_type}{_strength_info})")
                # ── 退出密码框（为下一次测量做准备）──
                # 两次测量之间必须失焦，否则下一轮 focus→blur 不会触发新反馈
                try:
                    ActionChains(driver).move_to_element(
                        password_elem
                    ).move_by_offset(
                        password_elem.size['width'] + 30, 5
                    ).click().perform()
                    time.sleep(0.2)
                except Exception:
                    pass
                uub.random_sleep([0.5, 1])
                return flag
            except Exception as e:
                self.my_logger.error(f"Tested password {test_password} failed to process {str(e)[:120]}")
                retries += 1
                # 页面状态不可靠，下次测试重新加载页面
                self._signup_page_ready = False
                uub.random_sleep([1, 2])
                try:
                    driver.refresh()
                except Exception:
                    # browser may have been closed or disconnected;
                    # stop retrying and let caller try the next password
                    try:
                        driver.quit()
                    except Exception:
                        pass
                    break
            finally:
                self.my_logger.debug("Process end.")
                # 共享 driver 不销毁，仅刷新到空白页，等待下一个密码测试

    def check_special_symbols(self, test_password):
        """[Restrictive -- Special Symbols] 真正测试网站是否允许特殊符号。

        旧实现只检查密码池自身字符串（含不含符号），没有测试网站——
        密码池恰好不含符号时会把"允许符号"的网站误判为"禁止符号"。
        新实现：在 admissible 密码末尾追加特殊符号 @ 后提交给网站：
            - 被接受 → 特殊符号允许 → 返回 False（r_no_a_sps=False）
            - 被拒绝 → 特殊符号禁止 → 返回 True（r_no_a_sps=True）
        :param test_password: the admissible password
        :return: True 表示网站禁止特殊符号
        """
        if not test_password:
            self.my_logger.error("No admissible password available; Improper process here.")
            raise AssertionError("No admissible password available for special symbol check.")
        symbol_pw = test_password + "@"
        self.my_logger.info(f"Testing whether special symbols are allowed with: {symbol_pw}")
        if self.test_one_password(symbol_pw, "test special symbol"):
            self.my_logger.info("Special symbols are allowed by the website.")
            return False
        else:
            self.my_logger.info("Special symbols are NOT allowed by the website.")
            return True

    def change_and_test_2_word_password(self):
        """
        change the admissible password to a password that not complying with 2-word structure
        :return: return the identification result
        """
        ret_str = ""
        last_str = ""
        # len_str = len(self.admissible_password)
        self.my_logger.info("BREAKing the two-word structure begins.")
        for i in self.admissible_password:
            if i.isalpha():
                ret_str += i
            else:
                last_str += i
        ret_str = ret_str + last_str
        self.my_logger.info("BREAKing the two-word structure ends.")
        self.my_logger.info(f"The generated password is {ret_str}.")
        if self.test_one_password(ret_str, "test two word structure"):
            self.my_logger.info(f"The no-two-word structure is allowed.")
            return False
        else:
            self.my_logger.info(f"The two-word structure is required.")
            return True

    def change_and_test_letter_start_password(self, is_two_word=True):
        ret_str = ""
        self.my_logger.info(f"BREAKing the letter-start structure begins.")
        if is_two_word:
            self.my_logger.debug(f"The two-word-structure is required, and then moving the second non-alpha character.")

            cnt = 1
            for idx, i in enumerate(self.admissible_password):
                if i.isalpha():
                    continue
                else:
                    if cnt == 2:
                        ret_str = (self.admissible_password[idx]
                                   + self.admissible_password[0:idx]
                                   + self.admissible_password[idx + 1:])
                        break
                    else:
                        cnt += 1
        else:
            self.my_logger.debug(
                f"The two-word-structure is not required, and then moving the first non-alpha character.")
            for idx, i in enumerate(self.admissible_password):
                if i.isalpha():
                    continue
                else:
                    ret_str = (self.admissible_password[idx]
                               + self.admissible_password[0:idx]
                               + self.admissible_password[idx + 1:])
                    break
        self.my_logger.info(f"BREAKing the letter-start structure ends.")
        self.my_logger.info(f"The generated password is {ret_str}.")
        if self.test_one_password(ret_str, "test letter start feature"):
            self.my_logger.info(f"The no-letter-start structure is allowed.")
            return False
        else:
            self.my_logger.info(f"The no-letter-start structure is required.")
            return True

    def change_and_test_lower_upper_minimum(self, upper=True, is_no_a_sps=True):
        ret_minimum = 2
        # means check upper minimum
        if upper:
            self.my_logger.info(f"Identifying the minimum number of upper letters.")
            changed_ap = self.admissible_password.lower()
        else:
            self.my_logger.info(f"Identifying the minimum number of lower letters.")
            changed_ap = self.admissible_password.upper()

        if self.test_one_password(changed_ap, "lower/upper letter minimum with admissible password"):
            self.my_logger.info(f"Password {changed_ap} with non-tested-character can be accepted.")
            ret_minimum = 0
        else:
            self.my_logger.info(f"Password {changed_ap} with non-tested-character can not be accepted.")
            changed_dict = uub.get_each_character_num(changed_ap)
            if upper:
                index_of_first_case = next((i for i, c in enumerate(self.admissible_password) if c.isupper()), None)
            else:
                index_of_first_case = next((i for i, c in enumerate(self.admissible_password) if c.islower()), None)
            if index_of_first_case is not None:
                self.my_logger.debug("Find the first upper/lower character index for the admissible password.")
                # change the first case letter back
                modified_str = changed_ap[:index_of_first_case] + self.admissible_password[
                    index_of_first_case] + changed_ap[
                                           index_of_first_case + 1:]
            else:
                self.my_logger.debug(
                    "Failed to find the first upper/lower character index for the admissible password.")
                modified_str = self.admissible_password
            self.my_logger.info(f"The password with the tested-type character is {modified_str}")
            if changed_dict["type_num"] >= 3:
                self.my_logger.info(
                    "The character type is still larger or equal to 3 after removing one type of characters.")
                # if == 3, then add a lowercase letter, which means the rejection is not caused by combination only, or maybe the website require four types
                if self.test_one_password(modified_str, "add a lower/upper case letter in the password"):
                    self.my_logger.info("Adding one character is enough to generated an allowed password.")
                    ret_minimum = 1
                else:
                    self.my_logger.info("Adding one character is not enough to generated an allowed password.")
                    ret_minimum = 2
            elif changed_dict["type_num"] == 2:
                self.my_logger.info("The character type is 2 after removing one type of characters.")
                if is_no_a_sps:
                    self.my_logger.info("No special symbol is allowed.")
                    if self.test_one_password(modified_str, "add a lower/upper case letter in the password"):
                        self.my_logger.info("Adding one character is enough to generated an allowed password.")
                        ret_minimum = 1
                    else:
                        self.my_logger.info("Adding one character is not enough to generated an allowed password.")
                        ret_minimum = 2
                else:
                    # upper is not zero and find the last index for letter. lower is zero
                    last_letter_index = None
                    for index, char in enumerate(reversed(changed_ap)):
                        if char.isalpha():
                            last_letter_index = len(changed_ap) - index - 1
                            break
                    self.my_logger.info("Finding the index of the last letter.")
                    try:
                        self.my_logger.info("Assertion: the number of letters should not be zero.")
                        assert last_letter_index is not None, "the number of letters should not be zero"
                    except AssertionError as ae:
                        self.my_logger.error(f"Assertion error: {ae}.")
                    tmp_ap = changed_ap
                    if changed_dict["digit"] == 0:
                        tmp_char = uusg.gen_random_digit(1)
                    else:
                        tmp_char = uusg.gen_random_symbol_character(1)
                    tmp_ap = tmp_ap[:last_letter_index] + tmp_char + self.admissible_password[last_letter_index + 1:]
                    # test whether a 3 of 4 password can be accepted, true -> 0, false -> then should add a lowercase
                    self.my_logger.info("Adding a symbol/digit in the password.")
                    if self.test_one_password(tmp_ap, "add a symbol/digit character in the password"):
                        self.my_logger.info(f"Password {tmp_ap} with non-tested-character can be accepted.")
                        ret_minimum = 0
                    else:
                        if self.test_one_password(modified_str, "add a lowercase letter in case"):
                            self.my_logger.info("Adding one character is enough to generated an allowed password.")
                            ret_minimum = 1
                        else:
                            self.my_logger.info("Adding one character is not enough to generated an allowed password.")
                            ret_minimum = 2
            else:
                # then the password only contains uppercase letter
                # but this part should not happen as the safe set is constructed in a special way
                # maybe add this to add the robustness of this algorithm
                try:
                    assert changed_dict["type_num"] >= 2, "the type number should be lower than 2"
                    self.my_logger.info("Assertion: The number of character type should be larger than or equal to 2.")
                except AssertionError as ae:
                    self.my_logger.error("The number of character type is less than 2, which is not expected.")
        return ret_minimum

    def change_and_test_symbol_minimum(self, is_no_a_sps=True):
        ret_minimum = 0
        if is_no_a_sps:
            self.my_logger.info("No special symbol is required, and the minimum symbol number is zero.")
            return ret_minimum
        modified_password = ""
        index_list = []
        # change all the symbols to digits
        self.my_logger.info("Change all symbols in the admissible password into digits.")
        for idx, i in enumerate(self.admissible_password):
            if i.isalnum():
                modified_password += i
            else:
                index_list.append(idx)
                modified_password += uusg.gen_random_digit(1)
        if self.test_one_password(modified_password, "minimum for symbol characters"):
            self.my_logger.info(f"Password {modified_password} with non-tested-character can be accepted.")
            ret_minimum = 0
        else:
            changed_dict = uub.get_each_character_num(modified_password)
            if changed_dict["type_num"] >= 3:
                self.my_logger.info(f"If the remaining character type >= 3, the symbol character is required.")
                ret_minimum = 1
            elif changed_dict["type_num"] == 2:
                last_digit_index = None
                self.my_logger.info(f"The remaining character type = 2.")
                for index, char in enumerate(reversed(modified_password)):
                    if char.isdigit():
                        self.my_logger.info(
                            f"The remaining character type = 2, and find the index of the last digit character.")
                        last_digit_index = len(modified_password) - index - 1
                        break
                try:
                    assert last_digit_index is not None, "the number of digit should not be zero"
                    self.my_logger.info(f"Assertion: the number of digit should not be zero.")
                except AssertionError as ae:
                    self.my_logger.error(f"The number of digits is the unexpected zero.")
                tmp_ap = modified_password
                if changed_dict["digit"] == 0:
                    tmp_char = uusg.gen_random_digit(1)
                elif changed_dict["upper"] == 0:
                    tmp_char = uusg.gen_random_upper_character(1)
                else:
                    tmp_char = uusg.gen_random_lower_character(1)
                self.my_logger.info(f"Adding the missing character type with a random character.")
                tmp_ap = tmp_ap[:last_digit_index] + tmp_char + self.admissible_password[last_digit_index + 1:]
                # test whether a 3 of 4 password can be accepted, true -> 0, false -> then should add a lowercase
                if self.test_one_password(tmp_ap, "add a letter/digit"):
                    self.my_logger.info(f"Password {tmp_ap} with non-tested-character can be accepted.")
                    ret_minimum = 0
                else:
                    self.my_logger.info("Adding one character is enough to generated an allowed password.")
                    ret_minimum = 1
            else:
                try:
                    assert changed_dict["type_num"] >= 2, "the type number should be lower than 2"
                    self.my_logger.info("Assertion: the type number should be lower than 2.")
                except AssertionError as ae:
                    self.my_logger.error("The type number is unexpected < 2.")
            # TODO: this is due to the fact, all admissible password have one symbol after excluding the no a special symbol
        return ret_minimum

    def change_and_test_digit_minimum(self, is_no_sps):
        self.my_logger.info("Testing the minimum number of digit character.")
        ret_minimum = 0
        modified_str = ""
        if not is_no_sps:
            self.my_logger.info("There are no requirements that the password should not include special symbol.")
            self.my_logger.info("Replacing all the digits with special symbols.")
            for i in self.admissible_password:
                if i.isdigit():
                    sps = self.fake.random_element(elements=('-', '@'))
                    modified_str += sps
                else:
                    modified_str += i
            if self.test_one_password(modified_str, "minimum for digits"):
                self.my_logger.info(f"Password {modified_str} with non-tested-character can be accepted.")
                ret_minimum = 0
            else:
                changed_dict = uub.get_each_character_num(modified_str)
                index_of_first_case = next((i for i, c in enumerate(self.admissible_password) if c.isdigit()), None)
                if index_of_first_case is not None:
                    self.my_logger.debug(
                        "Find the first digit character index for the admissible password, and restore one digit character back.")
                    modified_str_plus = (modified_str[:index_of_first_case]
                                         + self.admissible_password[index_of_first_case]
                                         + modified_str[index_of_first_case + 1:])
                    if self.test_one_password(modified_str_plus, "minimum for digits"):
                        ret_minimum = 1
                    else:
                        ret_minimum = 2
        else:
            self.my_logger.info("There are requirements that the password should not include special symbol.")
            for i in self.admissible_password:
                if i.isdigit():
                    modified_str += uusg.gen_random_lower_character(1)
                else:
                    modified_str += i
            if self.test_one_password(modified_str, "minimum for digits"):
                self.my_logger.info(f"Password {modified_str} with non-tested-character can be accepted.")
                ret_minimum = 0
            else:
                flag = False
                for idx, i in enumerate(self.admissible_password):
                    if i.isdigit():
                        modified_str_plus = modified_str[:idx] + self.admissible_password[idx] + modified_str[idx + 1:]
                        if self.test_one_password(modified_str_plus, "minimum for digits"):
                            flag = True
                            break
                if flag:
                    ret_minimum = 1
                else:
                    ret_minimum = 2

        return ret_minimum

    def identify_combination_requirements_with_sum_2(self, com_r):
        ret_list = [False, False, False, False]
        modified_str_two = ""
        modified_str_first = ""
        modified_str_second = ""
        if com_r[CR.SYMBOL_R.value] == 1 and com_r[CR.LOWER_R.value] == 1:
            for i in self.admissible_password:
                if i.islower() and not i.isalnum():
                    modified_str_two += i
                    modified_str_first += i
                    modified_str_second += i
                elif i.isupper():
                    modified_str_two += i.lower()
                    modified_str_first += i.lower()
                    modified_str_second += i
                elif i.isdigit():
                    modified_str_two += self.fake.random_element(elements=('-', '@'))
                    modified_str_first += i
                    modified_str_second += self.fake.random_element(elements=('-', '@'))
            self.my_logger.info(
                f"The special symbol and lowercase letter are required, and the modified password is {modified_str_two}.")
            if self.test_one_password(modified_str_two, "Password only containing symbol and lowercase letter."):
                # r24 is true
                ret_list[RMB.R24.value] = True
            elif self.test_one_password(
                    modified_str_first,
                    "Password containing symbol, digit, and lowercase letter."
            ) or self.test_one_password(
                modified_str_second,
                "Password containing symbol, and uppercase and lowercase letter."
            ):
                ret_list[RMB.R34.value] = True
            else:
                ret_list[RMB.R44.value] = True
        elif com_r[CR.SYMBOL_R.value] == 1 and com_r[CR.UPPER_R.value] == 1:
            for i in self.admissible_password:
                if i.isupper() and not i.isalnum():
                    modified_str_two += i
                    modified_str_first += i
                    modified_str_second += i
                elif i.islower():
                    modified_str_two += i.upper()
                    modified_str_first += i.upper()
                    modified_str_second += i
                elif i.isdigit():
                    modified_str_two += self.fake.random_element(elements=('-', '@'))
                    modified_str_first += i
                    modified_str_second += self.fake.random_element(elements=('-', '@'))
            # my_logger.info(f"The special symbol and lowercase letter are required, and the modified password is {modified_str_two}.")
            if self.test_one_password(
                    modified_str_two,
                    "Password only containing symbol and uppercase letter."
            ):
                # r24 is true
                ret_list[RMB.R24.value] = True
            elif self.test_one_password(
                    modified_str_first,
                    "Password containing symbol, digit, and lowercase letter."
            ) or self.test_one_password(
                modified_str_second,
                "Password containing symbol, and uppercase and lowercase letter."
            ):
                ret_list[RMB.R34.value] = True
            else:
                ret_list[RMB.R44.value] = True
        elif com_r[CR.SYMBOL_R.value] == 1 and com_r[CR.DIGIT_R.value] == 1:
            for i in self.admissible_password:
                if i.isdigit() and not i.isalnum():
                    modified_str_two += i
                    modified_str_first += i
                    modified_str_second += i
                elif i.islower():
                    modified_str_two += uusg.gen_random_digit(1)
                    modified_str_first += uusg.gen_random_digit(1)
                    modified_str_second += i
                elif i.isdigit():
                    modified_str_two += uusg.gen_random_digit(1)
                    modified_str_first += i
                    modified_str_second += uusg.gen_random_digit(1)
            # my_logger.info(f"The special symbol and lowercase letter are required, and the modified password is {modified_str_two}.")
            if self.test_one_password(
                    modified_str_two,
                    "Password only containing symbol and digit."
            ):
                # r24 is true
                ret_list[RMB.R24.value] = True
            elif self.test_one_password(
                    modified_str_first,
                    "Password containing symbol, digit, and uppercase letter."
            ) or self.test_one_password(
                modified_str_second,
                "Password containing symbol, digit and lowercase letter."
            ):
                ret_list[RMB.R34.value] = True
            else:
                ret_list[RMB.R44.value] = True
        elif com_r[CR.LOWER_R.value] == 1 and com_r[CR.UPPER_R.value] == 1:
            for i in self.admissible_password:
                if i.islower() and i.isupper():
                    modified_str_two += i
                    modified_str_first += i
                    modified_str_second += i
                elif i.isdigit():
                    modified_str_two += uusg.gen_random_lower_character(1)
                    modified_str_first += uusg.gen_random_lower_character(1)
                    modified_str_second += i
                elif not i.isalnum():
                    modified_str_two += uusg.gen_random_lower_character(1)
                    modified_str_first += i
                    modified_str_second += uusg.gen_random_lower_character(1)
            # my_logger.info(f"The special symbol and lowercase letter are required, and the modified password is {modified_str_two}.")
            if self.test_one_password(
                    modified_str_two,
                    "Password only containing lowercase and uppercase."
            ):
                # r24 is true
                ret_list[RMB.R24.value] = True
            elif self.test_one_password(
                    modified_str_first,
                    "Password containing lowercase and uppercase and symbol."
            ) or self.test_one_password(
                modified_str_second,
                "Password containing lowercase and uppercase and digit."
            ):
                ret_list[RMB.R34.value] = True
            else:
                ret_list[RMB.R44.value] = True
        elif com_r[CR.LOWER_R.value] == 1 and com_r[CR.DIGIT_R.value] == 1:
            for i in self.admissible_password:
                if i.islower() and i.isdigit():
                    modified_str_two += i
                    modified_str_first += i
                    modified_str_second += i
                elif i.isupper():
                    modified_str_two += i.lower()
                    modified_str_first += i.lower()
                    modified_str_second += i
                elif not i.isalnum():
                    modified_str_two += uusg.gen_random_digit(1)
                    modified_str_first += i
                    modified_str_second += uusg.gen_random_digit(1)
            # my_logger.info(f"The special symbol and lowercase letter are required, and the modified password is {modified_str_two}.")
            if self.test_one_password(
                    modified_str_two,
                    "Password only containing lowercase and digit."
            ):
                # r24 is true
                ret_list[RMB.R24.value] = True
            elif self.test_one_password(
                    modified_str_first,
                    "Password containing lowercase and digit and symbol."
            ) or self.test_one_password(
                modified_str_second,
                "Password containing lowercase and uppercase and digit."
            ):
                ret_list[RMB.R34.value] = True
            else:
                ret_list[RMB.R44.value] = True
        elif com_r[CR.UPPER_R.value] == 1 and com_r[CR.DIGIT_R.value] == 1:
            for i in self.admissible_password:
                if i.isupper() and i.isdigit():
                    modified_str_two += i
                    modified_str_first += i
                    modified_str_second += i
                elif i.islower():
                    modified_str_two += i.upper()
                    modified_str_first += i.upper()
                    modified_str_second += i
                elif not i.isalnum():
                    modified_str_two += uusg.gen_random_digit(1)
                    modified_str_first += i
                    modified_str_second += uusg.gen_random_digit(1)
            # my_logger.info(f"The special symbol and lowercase letter are required, and the modified password is {modified_str_two}.")
            if self.test_one_password(
                    modified_str_two,
                    "Password only containing uppercase and digit."
            ):
                # r24 is true
                ret_list[RMB.R24.value] = True
            elif self.test_one_password(
                    modified_str_first,
                    "Password containing uppercase and digit and symbol."
            ) or self.test_one_password(
                modified_str_second,
                "Password containing lowercase and uppercase and digit."
            ):
                ret_list[RMB.R34.value] = True
            else:
                ret_list[RMB.R44.value] = True
        else:
            self.my_logger.error("This process is conducted in a unexpected way.")
        return ret_list

    def identify_combination_requirements_3_sum(self, com_r):
        """识别 3 类字符组合要求（upper, lower, digit 均已确认存在）

        当 r_no_a_sps=True（不允许特殊符号）时，实际只有 3 个可用类别，
        此时只应设置 r_cmb23 或 r_cmb33，不应设置 r_cmb34 / r_cmb44。
        否则 length_limit_initial_password() 会为满足「4 类」要求而插入 @ 等
        特殊符号，导致所有长度测试密码被拒绝，二分搜索发散到边界值。
        """
        ret_list = [False, False, False, False, False, False, False]
        modified_password_dl = ""
        modified_password_sl = ""
        no_symbols = (com_r[CR.SYMBOL_R.value] == 0)

        # ── DL section: digit/symbol 互换测试 ──
        # 仅当符号确实存在/允许时此测试才有意义。
        # 若符号计数为 0，transfer_symbol_into_digit 是空操作，
        # 返回未改动的密码→测试成功→错误推断 r_cmb34=True。
        if not no_symbols:
            if com_r[CR.DIGIT_R.value] == 0:
                modified_password_dl = uusg.transfer_digit_into_symbol(
                    self.admissible_password)
            else:
                # 符号存在 → 尝试将其转为数字
                modified_password_dl = uusg.transfer_symbol_into_digit(
                    self.admissible_password)

            if modified_password_dl != "" and self.test_one_password(modified_password_dl):
                ret_list[RMB.R34.value] = ret_list[RMB.R23.value] = True
            else:
                ret_list[RMB.R44.value] = ret_list[RMB.R33.value] = True

        # ── SL section: upper/lower 互换测试 ──
        if com_r[CR.UPPER_R.value] == 0:
            modified_password_sl = uusg.transfer_upper_into_lower(self.admissible_password)
        elif com_r[CR.LOWER_R.value] == 0:
            modified_password_sl = uusg.transfer_lower_into_upper(self.admissible_password)
        else:
            # 大小写都存在 → 尝试去掉大写（全转小写）
            modified_password_sl = uusg.transfer_upper_into_lower(self.admissible_password)

        if modified_password_sl != "" and self.test_one_password(modified_password_sl):
            # 去掉一种大小写后仍可接受 → 只需 2 类（有符号时对应3-of-4）
            ret_list[RMB.R33.value] = ret_list[RMB.R34.value] = True
        elif com_r[CR.UPPER_R.value] > 0 and com_r[CR.LOWER_R.value] > 0:
            # 大小写均存在 → 尝试另一种方向（去掉小写保留大写）
            modified_password_sl2 = uusg.transfer_lower_into_upper(self.admissible_password)
            if modified_password_sl2 and self.test_one_password(modified_password_sl2):
                ret_list[RMB.R33.value] = ret_list[RMB.R34.value] = True
            else:
                # 两种方向均失败 → 大小写都必需
                if no_symbols:
                    # 无符号 → 3 类全必需 → r_cmb33
                    ret_list[RMB.R33.value] = True
                else:
                    # 有符号 → 可能需全部 4 类 → r_cmb44
                    ret_list[RMB.R44.value] = True
        else:
            # 仅有一种大小写（或都没有），去除后失败
            if no_symbols:
                ret_list[RMB.R33.value] = True
            else:
                ret_list[RMB.R44.value] = True
        return ret_list

    def identify_combination_requirements_2_sum(self, com_r):
        self.my_logger.info("When initial sum is 2.")
        ret_list = [False, False, False, False, False, False, False]
        if com_r[CR.SYMBOL_R.value] == 1 and com_r[CR.LOWER_R.value] == 1:
            modified_str_two = uusg.transfer_upper_into_lower(
                uusg.transfer_digit_into_symbol(self.admissible_password)
            )
            self.my_logger.info(f"Modified password is {modified_str_two} with symbol and lower.")
            if self.test_one_password(modified_str_two):
                # r24 is true
                ret_list[RMB.R24.value] = ret_list[RMB.R23.value] = True
            else:
                com_r_1 = com_r_2 = com_r
                com_r_1[CR.UPPER_R.value] = 1
                com_r_2[CR.DIGIT_R.value] = 1
                ret_list_1 = self.identify_combination_requirements_3_sum(com_r_1)
                ret_list_2 = self.identify_combination_requirements_3_sum(com_r_2)
                ret_list = [a or b for a, b in zip(ret_list_1, ret_list_2)]
            return ret_list
        elif com_r[CR.SYMBOL_R.value] == 1 and com_r[CR.UPPER_R.value] == 1:
            modified_str_two = uusg.transfer_symbol_into_digit(
                uusg.transfer_lower_into_upper(self.admissible_password)
            )
            self.my_logger.info(f"Modified password is {modified_str_two} with symbol and upper.")
            if self.test_one_password(modified_str_two):
                # r24 is true
                ret_list[RMB.R24.value] = ret_list[RMB.R23.value] = True
            else:
                com_r_1 = com_r_2 = com_r
                com_r_1[CR.LOWER_R.value] = 1
                com_r_2[CR.DIGIT_R.value] = 1
                ret_list_1 = self.identify_combination_requirements_3_sum(com_r_1)
                ret_list_2 = self.identify_combination_requirements_3_sum(com_r_2)
                ret_list = [a or b for a, b in zip(ret_list_1, ret_list_2)]
            return ret_list
        elif com_r[CR.SYMBOL_R.value] == 1 and com_r[CR.DIGIT_R.value] == 1:
            modified_str_two = uusg.transfer_letter_to_digit(self.admissible_password)
            self.my_logger.info(f"Modified password is {modified_str_two} with symbol and digit.")
            if self.test_one_password(modified_str_two):
                # r24 is true
                ret_list[RMB.R24.value] = ret_list[RMB.R23.value] = True
            else:
                com_r_1 = com_r_2 = com_r
                com_r_1[CR.LOWER_R.value] = 1
                com_r_2[CR.UPPER_R.value] = 1
                ret_list_1 = self.identify_combination_requirements_3_sum(com_r_1)
                ret_list_2 = self.identify_combination_requirements_3_sum(com_r_2)
                ret_list = [a or b for a, b in zip(ret_list_1, ret_list_2)]
            return ret_list
        elif com_r[CR.LOWER_R.value] == 1 and com_r[CR.UPPER_R.value] == 1:
            modified_str_two = uusg.transfer_sth_to_letter(self.admissible_password)
            self.my_logger.info(f"Modified password is {modified_str_two} with lower and upper.")
            if self.test_one_password(modified_str_two):
                # r24 is true
                ret_list[RMB.R24.value] = ret_list[RMB.R13.value] = True
            else:
                com_r_1 = com_r_2 = com_r
                com_r_1[CR.DIGIT_R.value] = 1
                com_r_2[CR.SYMBOL_R.value] = 1
                ret_list_1 = self.identify_combination_requirements_3_sum(com_r_1)
                ret_list_2 = self.identify_combination_requirements_3_sum(com_r_2)
                ret_list = [a or b for a, b in zip(ret_list_1, ret_list_2)]
            return ret_list
        elif com_r[CR.LOWER_R.value] == 1 and com_r[CR.DIGIT_R.value] == 1:
            modified_str_two = uusg.transfer_upper_into_lower(
                uusg.transfer_symbol_into_digit(self.admissible_password)
            )
            self.my_logger.info(f"Modified password is {modified_str_two} with lower and digit.")
            if self.test_one_password(modified_str_two):
                # r24 is true
                self.my_logger.info(f"Here we go!")
                ret_list[RMB.R24.value] = ret_list[RMB.R23.value] = True
            else:
                com_r_1 = com_r_2 = com_r
                com_r_1[CR.UPPER_R.value] = 1
                com_r_2[CR.SYMBOL_R.value] = 1
                ret_list_1 = self.identify_combination_requirements_3_sum(com_r_1)
                ret_list_2 = self.identify_combination_requirements_3_sum(com_r_2)
                ret_list = [a or b for a, b in zip(ret_list_1, ret_list_2)]
            return ret_list
        elif com_r[CR.UPPER_R.value] == 1 and com_r[CR.DIGIT_R.value] == 1:
            modified_str_two = uusg.transfer_lower_into_upper(
                uusg.transfer_symbol_into_digit(self.admissible_password)
            )
            self.my_logger.info(f"Modified password is {modified_str_two} with upper and digit.")
            if self.test_one_password(modified_str_two):
                # r24 is true
                ret_list[RMB.R24.value] = ret_list[RMB.R23.value] = True
            else:
                com_r_1 = com_r_2 = com_r
                com_r_1[CR.LOWER_R.value] = 1
                com_r_2[CR.SYMBOL_R.value] = 1
                ret_list_1 = self.identify_combination_requirements_3_sum(com_r_1)
                ret_list_2 = self.identify_combination_requirements_3_sum(com_r_2)
                ret_list = [a or b for a, b in zip(ret_list_1, ret_list_2)]
            return ret_list
        else:
            self.my_logger.error("This process is conducted in a unexpected way.")
            return ret_list

    def identify_combination_requirements_1_sum(self, com_r):
        ret_list = [False, False, False, False, False, False, False]
        com_r_1 = com_r_2 = com_r_3 = com_r
        if com_r[CR.SYMBOL_R.value] == 1:
            modified_str = uusg.transfer_digit_into_symbol(
                uusg.transfer_letter_to_digit(self.admissible_password)
            )
            if self.test_one_password(modified_str):
                # r24 is true
                ret_list[RMB.R14.value] = ret_list[RMB.R13.value] = True
            else:
                com_r_1[CR.UPPER_R.value] = 1
                com_r_2[CR.LOWER_R.value] = 1
                com_r_3[CR.DIGIT_R.value] = 1
        elif com_r[CR.DIGIT_R.value] == 1:
            modified_str = uusg.transfer_symbol_into_digit(
                uusg.transfer_letter_to_digit(self.admissible_password)
            )
            if self.test_one_password(modified_str):
                # r24 is true
                ret_list[RMB.R14.value] = ret_list[RMB.R13.value] = True
            else:
                com_r_1[CR.UPPER_R.value] = 1
                com_r_2[CR.LOWER_R.value] = 1
                com_r_3[CR.SYMBOL_R.value] = 1
        elif com_r[CR.UPPER_R.value] == 1:
            modified_str = uusg.transfer_lower_into_upper(
                uusg.transfer_sth_to_letter(self.admissible_password)
            )
            if self.test_one_password(modified_str):
                # r24 is true
                ret_list[RMB.R14.value] = ret_list[RMB.R13.value] = True
            else:
                com_r_1[CR.DIGIT_R.value] = 1
                com_r_2[CR.LOWER_R.value] = 1
                com_r_3[CR.SYMBOL_R.value] = 1
        elif com_r[CR.LOWER_R.value] == 1:
            modified_str = uusg.transfer_upper_into_lower(
                uusg.transfer_sth_to_letter(self.admissible_password)
            )
            if self.test_one_password(modified_str):
                # r24 is true
                ret_list[RMB.R14.value] = ret_list[RMB.R13.value] = True
            else:
                com_r_1[CR.DIGIT_R.value] = 1
                com_r_2[CR.UPPER_R.value] = 1
                com_r_3[CR.SYMBOL_R.value] = 1
        else:
            self.my_logger.error("This process is conducted in a unexpected way.")
        ret_list_1 = self.identify_combination_requirements_2_sum(com_r_1)
        ret_list_2 = self.identify_combination_requirements_2_sum(com_r_2)
        ret_list_3 = self.identify_combination_requirements_3_sum(com_r_3)
        ret_list = [a or b or c for a, b, c in zip(ret_list_1, ret_list_2, ret_list_3)]
        return ret_list

    def identify_combination_requirements(self, restrictive_policy):
        self.my_logger.info("Identifying the composition requirements of the website BEGINs.")
        # R13 R23 R33 R14 R24 R34 R44
        ret_list = [False, False, False, False, False, False, False]
        # letter upper lower digit symbol -> number
        com_r = [0, 0, 0, 0, 0]
        self.my_logger.info("Cases identification with preliminary.")
        if restrictive_policy["r_no_a_sps"]:
            self.my_logger.debug("Symbol characters are not allowed.")
            com_r[CR.SYMBOL_R.value] = 0
        if (
                restrictive_policy["r_2_word"] or
                restrictive_policy["r_l_start"] or
                restrictive_policy["r_upp_min"] > 0 or
                restrictive_policy["r_low_min"] > 0):
            self.my_logger.debug("Letter characters are required.")
            com_r[CR.LETTER_R.value] = 1
        if restrictive_policy["r_dig_min"] > 0:
            com_r[CR.DIGIT_R.value] = 1
        if restrictive_policy["r_upp_min"] > 0:
            com_r[CR.UPPER_R.value] = 1
        if restrictive_policy["r_low_min"] > 0:
            com_r[CR.LOWER_R.value] = 1
        if restrictive_policy["r_sps_min"] > 0:
            com_r[CR.SYMBOL_R.value] = 1

        initial_sum = sum(com_r[1:])

        if initial_sum == 4:
            ret_list[RMB.R44.value] = True
            return ret_list
        elif initial_sum == 3:
            ret_list = self.identify_combination_requirements_3_sum(com_r)
        elif initial_sum == 2:
            ret_list = self.identify_combination_requirements_2_sum(com_r)
        elif initial_sum == 1:
            ret_list = self.identify_combination_requirements_1_sum(com_r)
        self.my_logger.info("Identifying the composition requirements of the website ends.")
        return ret_list

    def length_limit_initial_password(self, restrictive_p):
        initial_password = ""
        char_dict = {
            "r_dig_min": restrictive_p["r_dig_min"],
            # the minimum number of upper letters
            "r_upp_min": restrictive_p["r_upp_min"],
            # the minimum number of lower letters
            "r_low_min": restrictive_p["r_low_min"],
            # the minimum number of special symbols
            "r_sps_min": restrictive_p["r_sps_min"],
            "r_com_3": 0,
            "r_com_4": 0
        }
        if restrictive_p["r_cmb13"]:
            char_dict["r_com_3"] = 1
        elif restrictive_p["r_cmb23"]:
            char_dict["r_com_3"] = 2
        elif restrictive_p["r_cmb33"]:
            char_dict["r_com_3"] = 3
        else:
            char_dict["r_com_3"] = 0

        if restrictive_p["r_cmb14"]:
            char_dict["r_com_4"] = 1
        elif restrictive_p["r_cmb24"]:
            char_dict["r_com_4"] = 2
        elif restrictive_p["r_cmb34"]:
            char_dict["r_com_4"] = 3
        elif restrictive_p["r_cmb44"]:
            char_dict["r_com_4"] = 4
        else:
            char_dict["r_com_4"] = 0

        # ── 安全网：r_no_a_sps=True 时绝不应引入特殊符号 ──
        # 组合检测可能错误设置 r_cmb34/r_cmb44（当特殊符号不可用时），
        # 导致后续 missing-class 逻辑误判需要添加特殊字符。
        # 此处强制清零四类要求，确保长度二分搜索不受污染。
        if restrictive_p.get("r_no_a_sps", False):
            char_dict["r_com_4"] = 0
            char_dict["r_sps_min"] = 0

        flag = False
        # letter start
        if restrictive_p["r_l_start"]:
            start_letter = uusg.gen_random_lower_character(1)
            if restrictive_p["r_upp_min"] > 0 and restrictive_p["r_low_min"] == 0:
                start_letter = start_letter.upper()
                flag = True
                char_dict["r_upp_min"] = 0 if char_dict["r_upp_min"] - 1 < 0 else char_dict["r_upp_min"] - 1
            else:
                char_dict["r_low_min"] = 0 if char_dict["r_low_min"] - 1 < 0 else char_dict["r_low_min"] - 1
            initial_password += start_letter
            char_dict["r_com_3"] = 0 if char_dict["r_com_3"] - 1 < 0 else char_dict["r_com_3"] - 1

        # combination of two word
        if restrictive_p["r_2_word"]:
            if initial_password != "":
                initial_len = 2
            else:
                initial_len = 3
            sub_str = uusg.gen_random_letter_character(initial_len)
            if (
                    restrictive_p["r_no_a_sps"] or
                    (
                            restrictive_p["r_sps_min"] == 0
                            and restrictive_p["r_dig_min"] > 0
                    )
            ):
                mid_str = uusg.gen_random_digit(1)
                char_dict["r_dig_min"] = 0 if char_dict["r_dig_min"] - 1 < 0 else char_dict["r_dig_min"] - 1
            elif not restrictive_p["r_no_a_sps"] and restrictive_p["r_sps_min"] > 0 and restrictive_p["r_dig_min"] == 0:
                mid_str = self.fake.random_element(elements=('-', '@'))
                char_dict["r_sps_min"] = 0 if char_dict["r_sps_min"] - 1 < 0 else char_dict["r_sps_min"] - 1
            else:
                mid_str = uusg.gen_random_digit(1)
                char_dict["r_dig_min"] = 0 if char_dict["r_dig_min"] - 1 < 0 else char_dict["r_dig_min"] - 1
            char_dict["r_com_3"] = 0 if char_dict["r_com_3"] - 1 < 0 else char_dict["r_com_3"] - 1
            char_dict["r_com_4"] = 0 if char_dict["r_com_4"] - 1 < 0 else char_dict["r_com_4"] - 1

            if restrictive_p["r_upp_min"] == 0 and restrictive_p["r_low_min"] > 0:
                initial_password += sub_str.lower() + mid_str + uusg.gen_random_letter_character(3).lower()
                if flag:
                    minus_len = 2
                else:
                    minus_len = 1
                char_dict["r_com_4"] = 0 if char_dict["r_com_4"] - minus_len < 0 else char_dict["r_com_4"] - minus_len
            else:
                initial_password += sub_str.lower() + mid_str + uusg.gen_random_letter_character(3).upper()
                char_dict["r_com_4"] = 0 if char_dict["r_com_4"] - 2 < 0 else char_dict["r_com_4"] - 2
            char_dict["r_upp_min"] = char_dict["r_low_min"] = 0

        initial_password += uusg.gen_random_lower_character(char_dict["r_low_min"])
        initial_password += uusg.gen_random_digit(char_dict["r_dig_min"])
        initial_password += uusg.gen_random_upper_character(char_dict["r_upp_min"])
        initial_password += ''.join(self.fake.random_choices(elements=('-', '@'), length=char_dict["r_sps_min"]))
        char_dict["r_dig_min"], char_dict["r_upp_min"], char_dict["r_low_min"], char_dict["r_sps_min"] = 0, 0, 0, 0

        missing_three_class = ["l", "d", "s"]
        missing_four_class = ["l", "u", "d", "s"]
        for i in initial_password:
            if i.isalpha():
                while "l" in missing_three_class:
                    missing_three_class.remove("l")
                if i.islower():
                    while "l" in missing_four_class:
                        missing_four_class.remove("l")
                else:
                    while "u" in missing_four_class:
                        missing_four_class.remove("u")

            if i.isdigit():
                while "d" in missing_four_class:
                    missing_four_class.remove("d")
                while "d" in missing_three_class:
                    missing_three_class.remove("d")

            if not i.isalnum():
                while "s" in missing_four_class:
                    missing_four_class.remove("s")
                while "s" in missing_three_class:
                    missing_three_class.remove("s")

        # print(missing_three_class, missing_four_class)
        if "d" in missing_three_class and "d" in missing_four_class:
            add_len = 1 if char_dict["r_dig_min"] <= 1 else char_dict["r_dig_min"]
            initial_password += uusg.gen_random_digit(add_len)
            char_dict["r_dig_min"] = 0 if char_dict["r_dig_min"] - add_len < 0 else char_dict["r_dig_min"] - add_len
        elif "l" in missing_three_class and "l" not in missing_four_class and "u" not in missing_four_class:
            add_len_4l = char_dict["r_low_min"]
            add_len_4u = char_dict["r_upp_min"]
            if add_len_4u > 0:
                initial_password += uusg.gen_random_upper_character(add_len_4u)
                char_dict["r_upp_min"] = 0
            if add_len_4l > 0:
                initial_password += uusg.gen_random_lower_character(add_len_4l)
                char_dict["r_low_min"] = 0
            if add_len_4u == 0 and add_len_4l == 0:
                initial_password += uusg.gen_random_lower_character(1)
        elif "l" in missing_four_class:
            add_len = 1 if char_dict["r_low_min"] <= 1 else char_dict["r_low_min"]
            initial_password += uusg.gen_random_lower_character(add_len)
            char_dict["r_low_min"] = 0 if char_dict["r_low_min"] - add_len < 0 else char_dict["r_low_min"] - add_len
        elif "u" in missing_four_class:
            add_len = 1 if char_dict["r_upp_min"] <= 1 else char_dict["r_upp_min"]
            initial_password += uusg.gen_random_upper_character(add_len)
            char_dict["r_upp_min"] = 0 if char_dict["r_upp_min"] - add_len < 0 else char_dict["r_upp_min"] - add_len
        elif "s" in missing_three_class and "s" in missing_four_class:
            # r_no_a_sps=True 时绝不应引入特殊符号。
            # char_dict["r_sps_min"] 可能已被安全网清零，
            # 但 add_len = 1 if 0 <= 1 else 0 → 1，仍会添加 '@'。
            # 此处显式跳过特殊字符补充。
            if restrictive_p.get("r_no_a_sps", False):
                pass
            else:
                add_len = 1 if char_dict["r_sps_min"] <= 1 else char_dict["r_sps_min"]
                initial_password += ''.join(self.fake.random_choices(elements=('-', '@'), length=add_len))
                char_dict["r_sps_min"] = 0 if char_dict["r_sps_min"] - add_len < 0 else char_dict["r_sps_min"] - add_len
        else:
            pass

        return initial_password

    def binary_search_min(self, initial_password, min_interval):
        """二分搜索最小密码长度。

        从 min_interval[0]（而非 len(initial_password)）开始搜索，
        避免初始中点已超过网站最大长度而导致所有测试密码被拒绝。

        对于 mi < len(initial_password) 的情况，生成包含 initial_password
        中所有字符类别的极简密码（而非截断），避免截断丢失末尾的必需字符类型。
        对于 mi >= len(initial_password) 的情况，用随机字符扩展。

        每次测试失败时做一次验证性重试（不同的随机扩展），
        排除"随机扩展引入意外模式"导致的误判。
        """
        lo = min_interval[0]
        hi = min_interval[1]
        initial_len = len(initial_password)

        # 分析 initial_password 中的字符类别
        has_lower = any(c.islower() for c in initial_password)
        has_upper = any(c.isupper() for c in initial_password)
        has_digit = any(c.isdigit() for c in initial_password)

        self.my_logger.debug(
            f"binary_search_min: initial_password='{initial_password}' (len={initial_len}), "
            f"classes: lower={has_lower} upper={has_upper} digit={has_digit}, "
            f"search range=[{lo}, {hi}]"
        )
        while lo < hi:
            mi = (lo + hi) // 2
            if mi >= initial_len:
                modified_password = initial_password + uusg.gen_random_str_no_symbol(mi - initial_len)
            else:
                # 生成极简短密码，确保包含 initial_password 中的所有字符类别
                # （截断可能丢失末尾的必需字符类型，如大写字母在密码末尾）
                parts = []
                if has_lower:
                    parts.append(uusg.gen_random_lower_character(1))
                if has_upper:
                    parts.append(uusg.gen_random_upper_character(1))
                if has_digit:
                    parts.append(uusg.gen_random_digit(1))
                if mi > len(parts):
                    parts.append(uusg.gen_random_str_no_symbol(mi - len(parts)))
                modified_password = ''.join(parts[:mi]) if mi <= len(''.join(parts)) else ''.join(parts)
                # 确保长度正确
                if len(modified_password) < mi:
                    modified_password += uusg.gen_random_str_no_symbol(mi - len(modified_password))
                elif len(modified_password) > mi:
                    modified_password = modified_password[:mi]

            self.my_logger.debug(
                f"binary_search_min: lo={lo}, hi={hi}, mi={mi}, "
                f"testing '{modified_password}' (len={len(modified_password)})"
            )
            if self.test_one_password(modified_password):
                hi = mi
            else:
                # 验证性重试：用不同的随机扩展再测一次，
                # 排除"随机字符组合触发了非长度规则"的误判
                retry_password = self._make_test_password(
                    initial_password, mi, has_lower, has_upper, has_digit
                )
                if retry_password != modified_password:
                    self.my_logger.debug(
                        f"binary_search_min: retry at mi={mi} with different random chars"
                    )
                    if self.test_one_password(retry_password):
                        hi = mi
                        continue
                lo = mi + 1
        self.my_logger.debug(f"binary_search_min: result = {lo}")
        return lo

    def _make_test_password(self, seed, target_len, has_lower, has_upper, has_digit):
        """生成 target_len 长度的测试密码，包含 seed 中的所有字符类别。"""
        if target_len >= len(seed):
            return seed + uusg.gen_random_str_no_symbol(target_len - len(seed))
        parts = []
        if has_lower:
            parts.append(uusg.gen_random_lower_character(1))
        if has_upper:
            parts.append(uusg.gen_random_upper_character(1))
        if has_digit:
            parts.append(uusg.gen_random_digit(1))
        if target_len > len(parts):
            parts.append(uusg.gen_random_str_no_symbol(target_len - len(parts)))
        result = ''.join(parts)
        if len(result) < target_len:
            result += uusg.gen_random_str_no_symbol(target_len - len(result))
        return result[:target_len]

    def binary_search_max(self, initial_password, max_interval):
        """二分搜索最大密码长度。

        从 initial_len 和 max_interval[0] 的较大值开始，
        用随机字符扩展初始密码来测试各长度。
        每次测试失败时做一次验证性重试。
        """
        initial_len = len(initial_password)
        if initial_len > max_interval[0]:
            lo = initial_len
        else:
            lo = max_interval[0]
        hi = max_interval[1]
        self.my_logger.debug(
            f"binary_search_max: initial_password='{initial_password}' (len={initial_len}), "
            f"search range=[{lo}, {hi}]"
        )
        while lo < hi:
            mi = (lo + hi + 1) // 2
            modified_password = initial_password + uusg.gen_random_str_no_symbol(mi - initial_len)
            self.my_logger.debug(
                f"binary_search_max: lo={lo}, hi={hi}, mi={mi}, "
                f"testing '{modified_password}' (len={len(modified_password)})"
            )
            if self.test_one_password(modified_password):
                lo = mi
            else:
                # 验证性重试
                retry_password = initial_password + uusg.gen_random_str_no_symbol(mi - initial_len)
                if retry_password != modified_password:
                    self.my_logger.debug(
                        f"binary_search_max: retry at mi={mi} with different random extension"
                    )
                    if self.test_one_password(retry_password):
                        lo = mi
                        continue
                hi = mi - 1
        self.my_logger.debug(f"binary_search_max: result = {lo}")
        return lo

    def identify_min_and_max_length_limitations(self, restrictive_parameters, min_interval, max_interval):
        """
        get the length minimum and maximum of the website password composition rule
        :param max_interval:
        :param min_interval:
        :param restrictive_parameters: the restrictive parameters of the website is known
        """
        ret_min = 0
        ret_max = 0
        # 优先使用 admissible_password（已知通过所有规则的密码）作为二分搜索种子。
        # admissible_password 是通过测试确认可被接受的密码，其字符结构已被网站验证通过。
        # length_limit_initial_password 生成的密码虽然满足参数约束，
        # 但其块状字符结构（如 3 小写+1 数字+3 大写）在随机扩展后可能产生
        # 网站实际拒绝的模式（非长度原因），污染二分搜索结果。
        if self.admissible_password and len(self.admissible_password) >= 6:
            initial_password = self.admissible_password
            self.my_logger.debug(
                f"identify_min_and_max_length_limitations: using admissible_password "
                f"'{initial_password}' (len={len(initial_password)})"
            )
        else:
            initial_password = self.length_limit_initial_password(restrictive_parameters)
            self.my_logger.debug(
                f"identify_min_and_max_length_limitations: using generated initial_password "
                f"'{initial_password}' (len={len(initial_password)})"
            )
        # TODO: 2 -> padding the password to tested length
        initial_min_length = len(initial_password)
        if initial_min_length > 32:
            ret_min = initial_min_length
        ret_min = self.binary_search_min(initial_password, min_interval)
        ret_max = self.binary_search_max(initial_password, max_interval)
        # TODO: 3 -> test the password
        self.my_logger.info(
            f"Length limitation results: min={ret_min}, max={ret_max}"
        )
        return ret_min, ret_max

    def identify_permissive_characters(self, password_length):
        ret_dict = {
            # blank space
            "p_space": False,
            # unicode character
            "p_unicd": False,
            # emoji character
            "p_emoji": False,
            # .
            "p_spn1": False,
            # !
            "p_spn2": False,
            # _
            "p_spn3": False,
            # #
            "p_spn4": False
        }
        # TODO 1.0 generated password with maximum password
        max_len = password_length[1]
        len_ap = len(self.admissible_password)
        initial_password = self.admissible_password + uusg.gen_random_str_no_symbol(max_len - len_ap)
        self.my_logger.info(f"Generating the password with maximum length: {initial_password}.")
        try:
            assert len(initial_password) >= 3, "Password with maximum length should longer than 3."
            self.my_logger.info("Password with maximum length should longer than 3.")
        except AssertionError as ae:
            self.my_logger.error("The password is unexpectedly shorter than three.")

        # TODO 2.0 Replace the last but one character with space
        mp_space = initial_password[:-2] + ' ' + initial_password[-1]
        self.my_logger.info(f"[Space] Testing permitted character: {mp_space}.")
        if self.test_one_password(mp_space, "[Space] Testing the permitted character."):
            ret_dict["p_space"] = True
            self.my_logger.success(f"[Space] Testing permitted character: {mp_space} is allowed.")

        # TODO 2.1 Replace the last character with unicode character
        # When one is allowed, I consider that this is allowed.
        test_unicode_list = ['\u00E9', '\u03B1', '\u0430', '你', '\u20AC', '\u03A0', '→']
        uni_flag = False
        for i in test_unicode_list:
            mp_uni = initial_password[:-1] + i
            if self.test_one_password(mp_uni, "[Unicode] Testing the unicode password"):
                uni_flag = True
                self.my_logger.success(f"[Unicode] Testing permitted character: {mp_uni} is allowed.")
            else:
                self.my_logger.warning(f"[Unicode] Testing permitted character: {mp_uni} is not allowed.")
        if uni_flag:
            ret_dict["p_unicd"] = True

        # TODO 2.2 Replace the last character with emoji character
        test_unicode_list = ['😊', '❤️', '👍', '🚀', '😺', '☕', '🌻']
        emo_flag = False
        for i in test_unicode_list:
            mp_emo = initial_password[:-1] + i
            if self.test_one_password(mp_emo, "[Emoji] Testing the emoji password"):
                emo_flag = True
                self.my_logger.success(f"[Emoji] Testing permitted character: {mp_emo} is allowed.")
            else:
                self.my_logger.warning(f"[Emoji] Testing permitted character: {mp_emo} is not allowed.")
        if emo_flag:
            ret_dict["p_emoji"] = True

        # TODO 2.3 Replace the last character with special characters
        # . ! _ #
        mp_dot = initial_password[:-1] + '.'
        mp_em = initial_password[:-1] + '!'
        mp_ul = initial_password[:-1] + '_'
        mp_hash = initial_password[:-1] + '#'
        ret_dict["p_spn1"] = True if self.test_one_password(mp_dot) else False
        ret_dict["p_spn2"] = True if self.test_one_password(mp_em) else False
        ret_dict["p_spn3"] = True if self.test_one_password(mp_ul) else False
        ret_dict["p_spn4"] = True if self.test_one_password(mp_hash) else False
        return ret_dict

    def identify_permitted_sequences(self, rp, pass_len):
        ret_dict = {
            # repetitive sequence
            "p_rep": False
        }
        initial_password = self.length_limit_initial_password(rp)
        # TODO 1.0: repetitive characters
        repe_list = ["", "", "", ""]
        add_str_repe = ["", "", "", ""]
        for idx, i in enumerate(initial_password):
            if i.isdigit() and repe_list[CR.DIGIT_R.value - 1] == "":
                add_str_repe[CR.DIGIT_R.value - 1] = i * 3
                repe_list[CR.DIGIT_R.value - 1] = initial_password[:idx] + i * 3 + initial_password[idx + 1:]
            if i.islower() and repe_list[CR.LOWER_R.value - 1] == "":
                add_str_repe[CR.LOWER_R.value - 1] = i * 3
                repe_list[CR.LOWER_R.value - 1] = initial_password[:idx] + i * 3 + initial_password[idx + 1:]
            if i.isupper() and repe_list[CR.UPPER_R.value - 1] == "":
                add_str_repe[CR.UPPER_R.value - 1] = i * 3
                repe_list[CR.UPPER_R.value - 1] = initial_password[:idx] + i * 3 + initial_password[idx + 1:]
            if not i.isalnum() and repe_list[CR.SYMBOL_R.value - 1] == "":
                add_str_repe[CR.SYMBOL_R.value - 1] = i * 3
                repe_list[CR.SYMBOL_R.value - 1] = initial_password[:idx] + i * 3 + initial_password[idx + 1:]
            if "" not in repe_list:
                break
        for idx, i in enumerate(repe_list):
            padding_password = padding_pw_suitable(initial_password, pass_len, rp["r_2_word"], add_str_repe[idx], i)
            if (padding_password is not None and
                    self.test_one_password(padding_password, "Testing the repetitive sequence password.")):
                ret_dict["p_rep"] = True
                break
        # TODO 2.0: sequential characters
        seq_list = ["", "", ""]
        add_str_seq = ["", "", ""]
        for idx, i in enumerate(initial_password):
            if i.isdigit() and seq_list[CR.DIGIT_R.value - 1] == "":
                add_str_seq[CR.DIGIT_R.value - 1] = (i +
                                                  chr((ord(i) + 1 - 48) % 10 + 48) +
                                                  chr((ord(i) + 2 - 48) % 10 + 48))
                seq_list[CR.DIGIT_R.value - 1] = (initial_password[:idx] +
                                                  i +
                                                  chr((ord(i) + 1 - 48) % 10 + 48) +
                                                  chr((ord(i) + 2 - 48) % 10 + 48) +
                                                  initial_password[idx + 1:])
            if i.islower() and seq_list[CR.LOWER_R.value - 1] == "":
                add_str_seq[CR.LOWER_R.value - 1] = (i +
                                                     chr((ord(i) + 1 - 97) % 10 + 97) +
                                                     chr((ord(i) + 2 - 97) % 10 + 97))
                seq_list[CR.LOWER_R.value - 1] = (initial_password[:idx] +
                                                  i +
                                                  chr((ord(i) + 1 - 97) % 26 + 97) +
                                                  chr((ord(i) + 2 - 97) % 26 + 97) +
                                                  initial_password[idx + 1:])
            if i.isupper() and seq_list[CR.UPPER_R.value - 1] == "":
                add_str_seq[CR.UPPER_R.value - 1] = (i +
                                                     chr((ord(i) + 1 - 65) % 10 + 65) +
                                                     chr((ord(i) + 2 - 65) % 10 + 65))
                seq_list[CR.UPPER_R.value - 1] = (initial_password[:idx] +
                                                  i +
                                                  chr((ord(i) + 1 - 65) % 26 + 65) +
                                                  chr((ord(i) + 2 - 65) % 26 + 65) +
                                                  initial_password[idx + 1:])
            if "" not in seq_list:
                break
        for idx, i in enumerate(seq_list):
            padding_password = padding_pw_suitable(initial_password, pass_len, rp["r_2_word"], add_str_seq[idx], i)
            if (padding_password is not None and
                    self.test_one_password(padding_password, "Testing the sequential sequence password.")):
                ret_dict["p_seq"] = True
                break

        # TODO 3.0: dict characters
        dict_word_path = uub.get_absolute_dir_path() + "/../data/dictionary/dict.txt"
        with open(dict_word_path, 'r', encoding='utf-8') as file:
            lines = file.readlines()
        lines = [line.strip() for line in lines]
        for i in lines:
            tmp_pw = initial_password + i
            padding_password = padding_pw_suitable(initial_password, pass_len, rp["r_2_word"], tmp_pw, i)
            if padding_password is not None and self.test_one_password(padding_password, f"Testing dict passwords: {padding_password}"):
                ret_dict["p_dict"] = True
                break

        # TODO 4.0: id_name

        tmp_pw = initial_password + self.username[:3]
        padding_password = padding_pw_suitable(initial_password, pass_len, rp["r_2_word"], tmp_pw, self.username[:3])
        if padding_password is not None and self.test_one_password(padding_password, f"Testing dict passwords: {padding_password}"):
            ret_dict["p_info"] = True
        return ret_dict

    def identify_long_short_passwords(self, password_length):
        ret_dict = {
            "p_longd": False,
            "p_shortd": False
        }
        min_len, max_len = password_length[0], password_length[1]
        min_len_pw = uusg.gen_random_digit(min_len)
        max_len_pw = uusg.gen_random_digit(max_len)
        ret_dict["p_longd"] = True if self.test_one_password(max_len_pw) else False
        ret_dict["p_shortd"] = True if self.test_one_password(min_len_pw) else False
        return ret_dict

    def identify_breached_passwords(self, restrictive_pr, password_length):
        ret_dict = {
            "p_br": False
        }
        leaked_data_path = uub.get_absolute_dir_path() + "/../data/leakage/leakage_password.txt"
        with open(leaked_data_path, 'r', encoding='utf-8') as file:
            lines = file.readlines()
        lines = [line.strip() for line in lines]
        # 泄露密码文件有 10000 条；若网站拒绝泄露密码，遍历全文件会跑数小时。
        # 连续 N 条符合政策的泄露密码均被拒，即判定"拒绝泄露密码"并停止。
        consecutive_rejected = 0
        MAX_REJECTED_SAMPLE = 20
        for tmp_pw in lines:
            if not (check_policy(tmp_pw, restrictive_pr, password_length)):
                continue
            if self.test_one_password(tmp_pw, f"Testing breached passwords: {tmp_pw}"):
                ret_dict["p_br"] = True
                break
            consecutive_rejected += 1
            if consecutive_rejected >= MAX_REJECTED_SAMPLE:
                self.my_logger.info(
                    f"{MAX_REJECTED_SAMPLE} 条泄露密码均被拒绝，判定该网站拒绝泄露密码（停止遍历）")
                break
        return ret_dict
