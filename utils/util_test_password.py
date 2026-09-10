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

import utils.util_basic as uub
import utils.util_str_generator as uusg
from config.config import Config
from utils.password_candidates import (
    admissible_candidate_lengths,
    stratified_password_candidates,
)


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


def _driver_cache_path(name):
    """Return a writable, project-local browser-driver cache directory."""
    configured = os.environ.get("SITES_DRIVER_CACHE_DIR", "").strip()
    root = configured or os.path.join(str(Config.PROJECT_ROOT), ".cache")
    path = os.path.abspath(os.path.join(os.path.expanduser(root), name))
    os.makedirs(path, exist_ok=True)
    return path


def _configure_uc_data_path(uc):
    """Keep undetected-chromedriver patches out of a possibly unwritable HOME."""
    path = _driver_cache_path("undetected_chromedriver")
    uc.Patcher.data_path = path
    return path


def _find_browser_binary(browser):
    """Find a Chrome or Edge binary, honoring explicit server overrides."""
    import shutil

    env_name = "SITES_CHROME_BIN" if browser == "chrome" else "SITES_EDGE_BIN"
    configured = os.environ.get(env_name, "").strip()
    candidates = [configured] if configured else []
    if os.name == "nt":
        pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        pf86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
        local = os.environ.get("LOCALAPPDATA", "")
        if browser == "chrome":
            candidates.extend([
                os.path.join(pf, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(pf86, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(local, "Google", "Chrome", "Application", "chrome.exe"),
            ])
        else:
            candidates.extend([
                os.path.join(pf86, "Microsoft", "Edge", "Application", "msedge.exe"),
                os.path.join(pf, "Microsoft", "Edge", "Application", "msedge.exe"),
                os.path.join(local, "Microsoft", "Edge", "Application", "msedge.exe"),
            ])
    else:
        names = (("google-chrome", "google-chrome-stable", "chromium",
                  "chromium-browser") if browser == "chrome"
                 else ("microsoft-edge", "microsoft-edge-stable"))
        candidates.extend(filter(None, (shutil.which(name) for name in names)))
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return os.path.abspath(candidate)
    return None


def _create_edge_driver(edge_binary, *, shared=False):
    """Create a Selenium Edge session when Chrome is unavailable on Windows."""
    from selenium.webdriver.common.selenium_manager import SeleniumManager
    from selenium.webdriver.edge.options import Options as EdgeOptions
    from selenium.webdriver.edge.service import Service as EdgeService

    options = EdgeOptions()
    options.binary_location = edge_binary
    for argument in (
            "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
            "--disable-blink-features=AutomationControlled"):
        options.add_argument(argument)
    _enable_passive_network_logging(options, capability="ms:loggingPrefs")

    proxy_url = _get_proxy_config()
    if proxy_url:
        masked = proxy_url.split("@")[-1] if "@" in proxy_url else proxy_url
        logger.info(f"Edge 使用代理: {masked}")
        options.add_argument(f"--proxy-server={proxy_url}")
    else:
        options.add_argument("--no-proxy-server")
    if os.environ.get("SITES_HEADLESS"):
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1440,900")

    driver_binary = os.environ.get("SITES_EDGEDRIVER", "").strip()
    if not driver_binary or not os.path.isfile(driver_binary):
        manager_args = [
            "--browser", "edge", "--browser-path", edge_binary,
            "--cache-path", _driver_cache_path("selenium"), "--avoid-stats",
        ]
        if proxy_url:
            manager_args.extend(["--proxy", proxy_url])
        driver_binary = SeleniumManager().binary_paths(manager_args)["driver_path"]

    driver = webdriver.Edge(
        options=options, service=EdgeService(executable_path=driver_binary))
    driver.maximize_window()
    driver.set_page_load_timeout(25 if shared else 30)
    driver.set_script_timeout(10)
    _inject_form_detection_js(driver)
    return driver


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


def _installed_chrome_major():
    """返回本机 Chrome 主版本号（如 152），失败返回 None。

    Windows 优先解析 Chrome 安装目录下的版本号子目录名（如
    ``Application\\152.0.7977.65\\``）——比 BLBeacon 注册表可靠（后者常为空
    或不存在）。Linux/macOS 退化为执行 ``chrome --version`` 解析。
    """
    ver_re = re.compile(r"^(\d+)\.\d+\.\d+\.\d+$")

    # Windows：版本号目录名（Chrome 自动升级后目录名随版本变化）
    if os.name == "nt":
        bases = []
        pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        pf86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
        local = os.environ.get("LOCALAPPDATA", "")
        bases += [
            os.path.join(pf, "Google", "Chrome", "Application"),
            os.path.join(pf86, "Google", "Chrome", "Application"),
        ]
        if local:
            bases.append(os.path.join(local, "Google", "Chrome", "Application"))
        majors = []
        for base in bases:
            if not os.path.isdir(base):
                continue
            try:
                names = os.listdir(base)
            except OSError:
                continue
            for name in names:
                m = ver_re.match(name)
                if m and os.path.isdir(os.path.join(base, name)):
                    majors.append(int(m.group(1)))
        if majors:
            return max(majors)
        return None

    # Linux/macOS：执行 chrome --version（可能因 Chrome 已运行而被吞掉输出）
    import subprocess
    import shutil
    chrome_bin = os.environ.get("SITES_CHROME_BIN")
    cands = [c for c in (
        chrome_bin,
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
    ) if c]
    for c in cands:
        try:
            out = subprocess.run(
                [c, "--version"], capture_output=True, text=True, timeout=8
            ).stdout
            m = re.search(r"(\d+)\.\d+\.\d+\.\d+", out)
            if m:
                return int(m.group(1))
        except Exception:
            continue
    return None


def _find_cached_chromedriver():
    """在 ~/.wdm 缓存中搜索真正的 chromedriver 二进制，自动 chmod +x。

    只返回与本机 Chrome 主版本一致的驱动——Chrome 自动升级后，旧版本驱动
    会因 SessionNotCreatedException（版本不匹配）崩溃。没有匹配时返回 None，
    交由 undetected_chromedriver 自行下载正确版本。
    """
    candidates = []
    wdm_root = os.path.join(os.path.expanduser("~"), ".wdm", "drivers", "chromedriver")
    chrome_major = _installed_chrome_major()
    # 路径目录名中的主版本：.../win64/150.0.7871.124/chromedriver-win64/...
    ver_dir_re = re.compile(r"/(\d+)\.\d+\.\d+\.\d+/")
    if os.path.isdir(wdm_root):
        for root, _dirs, files in os.walk(wdm_root):
            for f in files:
                if f in ("chromedriver", "chromedriver.exe"):
                    candidates.append(os.path.join(root, f))
    # 按文件大小降序排列——真正的 21MB 二进制远大于 1.3MB 文本文件
    for c in sorted(candidates, key=os.path.getsize, reverse=True):
        if not _is_real_chromedriver_binary(c):
            continue
        # 版本匹配检查：仅当能确定本机 Chrome 版本时才过滤，否则退回原行为
        if chrome_major is not None:
            m = ver_dir_re.search(c.replace("\\", "/"))
            if not m or int(m.group(1)) != chrome_major:
                continue
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


def _enable_passive_network_logging(options, capability="goog:loggingPrefs"):
    """Capture metadata for requests the browser already makes.

    ``security_observers`` consumes these events after classification to derive
    TLS and response-header posture.  Enabling the log does not issue a request
    and does not persist the raw events.
    """
    options.set_capability(capability, {"performance": "ALL"})
    options.add_experimental_option("perfLoggingPrefs", {"enableNetwork": True})


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

    chrome_binary = _find_browser_binary("chrome")
    if not chrome_binary:
        edge_binary = _find_browser_binary("edge")
        if edge_binary:
            logger.info("未找到 Chrome，回退使用本机 Microsoft Edge")
            _SHARED_DRIVER = _create_edge_driver(edge_binary, shared=True)
            return _SHARED_DRIVER

    import undetected_chromedriver as uc
    _configure_uc_data_path(uc)

    options = Options()
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    _enable_passive_network_logging(options)
    # undetected-chromedriver 自动处理以下反检测补丁:
    #   --disable-blink-features=AutomationControlled
    #   excludeSwitches: enable-automation
    #   useAutomationExtension: false

    # 代理支持：仅显式配置 CRAWL_PROXY/HTTPS_PROXY/HTTP_PROXY 时走代理；
    # 否则强制绕过系统代理（macOS Clash Verge 等系统代理会把测量流量
    # 经境外节点转发——中文站直连更快且不耗代理流量，2026-08-16 实测
    # 4 轮全量经系统代理烧掉 200G 代理流量）
    proxy_url = _get_proxy_config()
    if proxy_url:
        masked = proxy_url.split("@")[-1] if "@" in proxy_url else proxy_url
        logger.info(f"Chrome 使用代理: {masked}")
        options.add_argument(f"--proxy-server={proxy_url}")
    else:
        options.add_argument("--no-proxy-server")

    if chrome_binary:
        options.binary_location = chrome_binary

    if _CHROMEDRIVER_BIN:
        _SHARED_DRIVER = uc.Chrome(options=options, driver_executable_path=_CHROMEDRIVER_BIN)
    else:
        _SHARED_DRIVER = uc.Chrome(options=options)

    _SHARED_DRIVER.maximize_window()
    _SHARED_DRIVER.set_page_load_timeout(25)
    _SHARED_DRIVER.set_script_timeout(10)

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
    chrome_binary = _find_browser_binary("chrome")
    if not chrome_binary:
        edge_binary = _find_browser_binary("edge")
        if edge_binary:
            logger.info("未找到 Chrome，回退使用本机 Microsoft Edge")
            return _create_edge_driver(edge_binary)

    import undetected_chromedriver as uc
    _configure_uc_data_path(uc)

    options = Options()
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    # ── 反自动化检测标志 ──
    # 注意: excludeSwitches / useAutomationExtension 与 undetected-chromedriver
    #       不兼容（后者内部已处理），只保留 Chrome flag 级别选项
    options.add_argument("--disable-blink-features=AutomationControlled")
    _enable_passive_network_logging(options)

    proxy_url = _get_proxy_config()
    if proxy_url:
        masked = proxy_url.split("@")[-1] if "@" in proxy_url else proxy_url
        logger.info(f"Chrome (new) 使用代理: {masked}")
        options.add_argument(f"--proxy-server={proxy_url}")
    else:
        # 绕过系统代理（同 _get_shared_driver 注释：中文站直连）
        options.add_argument("--no-proxy-server")

    # 服务器无显示器环境：SITES_HEADLESS=1 启用无头模式
    if os.environ.get("SITES_HEADLESS"):
        options.add_argument("--headless=new")
        options.add_argument("--window-size=1440,900")
        options.add_argument("--disable-gpu")

    # 服务器自定义 Chrome 二进制：SITES_CHROME_BIN 指向 chrome 可执行文件
    # （部署时从 Mac 下载 linux 版 Chrome 传到服务器后设置）
    chrome_bin = chrome_binary or os.environ.get("SITES_CHROME_BIN")
    if chrome_bin and os.path.isfile(chrome_bin):
        options.binary_location = chrome_bin

    # 服务器自定义 chromedriver：SITES_CHROMEDRIVER 指向驱动路径
    chromedriver_bin = os.environ.get("SITES_CHROMEDRIVER")
    if chromedriver_bin and os.path.isfile(chromedriver_bin):
        driver = uc.Chrome(options=options, driver_executable_path=chromedriver_bin)
    elif _CHROMEDRIVER_BIN:
        driver = uc.Chrome(options=options, driver_executable_path=_CHROMEDRIVER_BIN)
    else:
        driver = uc.Chrome(options=options)

    driver.maximize_window()
    driver.set_page_load_timeout(30)
    # 跨域 iframe 内 execute_script 的 CDP 上下文切换可能挂起
    # （pan.baidu 注册弹窗 passport.baidu.com 实测：无 script_timeout 时
    # 会无限阻塞，整个测量卡死 15 分钟）。设置脚本执行超时防止挂死，
    # 超时后由调用方异常路径回退/重试。
    driver.set_script_timeout(10)

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


class BrowserDeadError(BaseException):
    """浏览器会话已终止（Chrome 关闭/断开）时抛出，用于立即短路整个密码测量。

    继承 BaseException 而非 Exception：这样它不会被 @logger.catch（默认只捕获
    Exception）或各类 except Exception 吞掉，能一路冒泡到 run_password_policy_test
    的 except BrowserDeadError，实现干净中断 + 增量落盘，而不是空转出垃圾结果。
    """


class ProbeOutcome(str, Enum):
    """单个候选密码的证据结论。

    旧接口仍返回 bool 供策略代码使用，但真实结论保存在
    ``TestPassword._last_probe_outcome``。只有明确接受证据，或已经用负对照
    证明当前表单会可靠拒绝弱密码后“候选无拒绝”，才允许返回 True。
    """

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"


class TestPassword(object):
    def __init__(self, my_logger, test_site, admissible_password="",
                 signup_url="", email_xpath="", password_xpath="",
                 driver=None, password_frame_path=None):
        self.fake = faker.Faker()
        # 2026-08 更新：GitHub 新政策为"至少15位，或至少8位+数字+小写"，
        # 且拒绝泄露密码与连续序列。旧密码池（2023年，6-10位）已全部失效。
        # 新候选已实测通过（非泄露、非序列）。
        # 备选池按「宽松→严格」排序：小写+数字 在最前，随后补 大写 / 符号 / 四类。
        # 宽松站（符号允许但非必需）仍命中首个候选，行为不变；要求大写/符号的站
        # 才会走到后面的混合候选，避免「找不到 admissible → 空 policy」。
        # 符号统一用 '!'（'@' 部分站当邮箱误判）。
        self.admissible_password_list = {
            "8": [
                "k4m2x9a7", "v5n3b8q1", "p7c3w6z2", "t9f4d1s6",
                "x6q1z9m3", "n2b7w4k8",
                "k4M2x9a7", "v5N3b8q1",
                "k4m2x9a!", "v5n3b8q!",
                "k4M2x9a!", "v5N3b8q!"
            ],
            "9": [
                "k4m2x9a7t", "v5n3b8q1w",
                "k4M2x9a7t", "k4m2x9a7!", "k4M2x9a7!"
            ],
            "10": [
                "k4m2x9a7ty", "v5n3b8q1wf",
                "k4M2x9a7ty", "k4m2x9a7t!", "k4M2x9a7t!"
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
        # 口令框所在 iframe 路径（分类流程记录，()=主文档）。跨域注册
        # iframe（pan.baidu 的 passport.baidu.com 实测）时，find_element
        # 必须在对应 frame 上下文执行；iframe 异步渲染，查找前需先确保
        # iframe 已出现再切换，否则在主文档找不到注册口令框。
        self.password_frame_path = tuple(password_frame_path) if password_frame_path else None
        # 浏览器会话已终止标志：置位后 test_one_password 立即抛 BrowserDeadError，
        # 避免后续几十个测试对已死 driver 空转失败（每个 ~16s 的 urllib3 退避）
        self._browser_dead = False
        # 门控表单（手机号/验证码/确认密码/协议勾选 恒为空）标志
        self._gated_form = False
        # 是否曾观察到密码专属拒绝信号（用于区分"政策宽松"与"门控表单无法验证"）
        self._saw_pwd_specific_reject = False
        # 最近一次拒绝消息：find_admissible_password 据此自适应判断站点要求
        # （如提到「符号」则立即补符号候选，而非跑完无符号扩展再回退）
        self._last_reject_msg = ""
        # 单次探测采用三态证据；bool 仅作旧策略接口的兼容层。
        self._last_probe_outcome = ProbeOutcome.INCONCLUSIVE
        self._last_probe_evidence = "not_started"
        self._probe_evidence = []
        self._negative_control_confirmed = False
        self._had_inconclusive = False

    def _record_probe(self, password: str, outcome: ProbeOutcome,
                      evidence: str) -> None:
        self._last_probe_outcome = outcome
        self._last_probe_evidence = evidence
        if outcome == ProbeOutcome.INCONCLUSIVE:
            self._had_inconclusive = True
        self._probe_evidence.append({
            "password_length": len(password),
            "outcome": outcome.value,
            "evidence": evidence[:300],
        })

    def establish_inline_control(self) -> bool:
        """用明显无效的短密码验证当前表单确实会给出密码专属拒绝反馈。"""
        self._negative_control_confirmed = False
        self.test_one_password("a", "negative control: invalid one-character password")
        confirmed = self._last_probe_outcome == ProbeOutcome.REJECTED
        self._negative_control_confirmed = confirmed
        if confirmed:
            self.my_logger.info("inline 负对照成立：一字符密码得到明确拒绝证据。")
        else:
            self.my_logger.warning(
                "inline 负对照未成立：不能把后续候选的‘无拒绝信号’解释为接受。")
        return confirmed

    @staticmethod
    def _stratified_candidates(length: int):
        """生成覆盖常见字符类别要求、但不依赖错误文案的基准候选。"""
        return stratified_password_candidates(length)

    @logger.catch
    def find_admissible_password(self):
        """
        find the admissible password
        :return: return admissible password
        """
        self.my_logger.info(f"Begin finding the admissible password for {self.test_site}.")
        search_lengths = admissible_candidate_lengths(
            Config.ADMISSIBLE_MIN_LENGTH, Config.ADMISSIBLE_MAX_LENGTH)
        cache_path = _admissible_cache_path(self.test_site)
        if os.path.isfile(cache_path):
            with open(cache_path, "r", encoding="utf-8") as cache_file:
                cached = cache_file.read().strip()
            if cached:
                self.my_logger.info(f"重新验证缓存的 admissible password: {cached}")
                if self.test_one_password(cached, "Revalidate cached admissible password"):
                    self.admissible_password = cached
                    return cached
                self.my_logger.warning("缓存密码本轮未通过，忽略缓存并重新搜索。")
        flag = False
        # Phase A：8/9/10 无符号主池（覆盖大多数常见政策）。GitHub 新政策下
        # 6-7 位密码必被拒，故直接从 8 开始。
        for i in range(8, 11):
            ret = False
            candidates = list(dict.fromkeys(
                self.admissible_password_list[str(i)] + self._stratified_candidates(i)
            ))
            for pwd in candidates:
                ret = self.test_one_password(pwd, "Find the admissible name")
                if ret:
                    flag = True
                    self.admissible_password = pwd
                    break
            if ret:
                break

        # Phase B：8/9/10 全被拒且反馈提到「符号」→ 站点要求特殊符号。
        # 立即试符号候选（小写+数字+符号 / 大写+小写+数字+符号），
        # 而非先跑完 11-32 位无符号扩展再回退（太慢）。
        if not flag:
            _lm = (getattr(self, '_last_reject_msg', '') or '').lower()
            _need_symbol = False
            if any(k in _lm for k in ['符号', '特殊字符', '特殊符号', 'symbol', 'special char']):
                if not any(k in _lm for k in ['不能', '不允许', '禁止', '不含', 'not allowed', 'cannot']):
                    _need_symbol = True
            if _need_symbol:
                for i in search_lengths:
                    symbol_candidates = [
                        "a3!" + uusg.gen_random_lower_character(i - 3),
                        "aB3!" + uusg.gen_random_lower_character(i - 4),
                    ]
                    ret = False
                    for pwd in symbol_candidates:
                        ret = self.test_one_password(pwd, "Find the admissible name (symbol)")
                        if ret:
                            flag = True
                            self.admissible_password = pwd
                            break
                    if ret:
                        break

        # Phase C：扩展到配置上限。常见边界优先，之后补齐全部长度；
        # 不再依赖网站错误文案是否恰好提到“大写/符号”。
        if not flag:
            for i in (n for n in search_lengths if n not in (8, 9, 10)):
                test_pwd_list = self._stratified_candidates(i)
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

    def _ensure_frame_context(self, driver) -> bool:
        """确保 driver 当前处于口令框所在的 iframe 上下文。

        跨域注册 iframe（pan.baidu 的 passport.baidu.com 实测）异步渲染：
        main.py 切 frame 时 iframe 可能尚未出现，或页面重载后上下文丢失。
        每次查找口令框前调用：回主文档 → 逐个切换 frame_path 索引。
        切换失败（iframe 未出现）返回 False，由调用方重试等待。
        """
        if not self.password_frame_path:
            return True
        try:
            driver.switch_to.default_content()
            frames = driver.find_elements(By.TAG_NAME, "iframe")
            for index in self.password_frame_path:
                if index >= len(frames):
                    return False
                driver.switch_to.frame(frames[index])
                frames = driver.find_elements(By.TAG_NAME, "iframe")
            return True
        except Exception:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass
            return False

    @logger.catch
    def test_one_password(self, test_password, info_name="Default Name for the process."):
        """
        test whether the password will be accepted by the website
        :param test_password: the tested password
        :param info_name: the information of the testing process
        :return: True or False indicates the result
        """
        if self._browser_dead:
            raise BrowserDeadError(
                f"browser session already closed; aborting measurement "
                f"(skipping password '{test_password}')")
        self.my_logger.info(f"Tested password: {test_password} -- {info_name}")
        self.my_logger.debug(f"Begin to simulate testing the password {test_password} for signing up an account.")
        retries = 1
        while retries <= 5:
            # 使用调用方传入的 driver（而非全局单例），
            # 确保与分类器/链接发现共享同一浏览器实例
            driver = self._driver or _get_shared_driver()
            try:
                self.my_logger.debug(f"Begin the {retries}-(st/nd/rd/th) attempt(s).")
                # 方案 B：session 健康检查。每次填充前先探活，若浏览器已死（如
                # invalid session id）则立即短路，避免在死 driver 上空转 5 次重试。
                try:
                    driver.execute_script("return 1")
                except Exception as _probe_exc:
                    self._browser_dead = True
                    try:
                        driver.quit()
                    except Exception:
                        pass
                    raise BrowserDeadError(
                        f"browser session closed (probe failed): {str(_probe_exc)[:120]}")
                # 同页面复用：页面已就绪时只重填密码字段，不重新加载页面
                if not self._signup_page_ready:
                    if not self.signup_url:
                        self.my_logger.error("signup_url is not set; cannot navigate to signup page.")
                        self._record_probe(
                            test_password, ProbeOutcome.INCONCLUSIVE,
                            "signup_url_missing")
                        return False
                    driver.get(self.signup_url)
                    self.my_logger.debug(f"Access the signup page: {self.signup_url}")
                    uub.random_sleep([1, 2])
                    # 安全边界：inline 只操作密码框，不填写邮箱、手机号等身份字段。
                    # 如果身份门控导致密码反馈无法触发，结果应为 inconclusive。
                    self.my_logger.debug("Inline mode skips all identity fields.")
                    self._signup_page_ready = True
                if not self.password_xpath:
                    self.my_logger.warning("password_xpath is not set; cannot find password field.")
                    self._record_probe(
                        test_password, ProbeOutcome.INCONCLUSIVE,
                        "password_xpath_missing")
                    return False
                # 等待密码框渲染（SPA / 慢页面 / 代理延迟：固定 sleep 不够，
                # 页面未就绪时 find_element 会空转失败直到 5 次重试耗尽）
                # 若口令框在 iframe 内（跨域注册 iframe 实测），先确保
                # iframe 已出现并切换进去，再找口令框。
                password_elem = None
                for _wait in range(30):
                    try:
                        if self.password_frame_path:
                            self._ensure_frame_context(driver)
                        password_elem = driver.find_element(By.XPATH, self.password_xpath)
                        if password_elem.is_displayed():
                            break
                    except Exception:
                        password_elem = None
                    time.sleep(0.5)
                if password_elem is None:
                    self.my_logger.warning(
                        f"password field not found after waiting: {self.password_xpath}")
                    self._record_probe(
                        test_password, ProbeOutcome.INCONCLUSIVE,
                        "password_field_not_rendered")
                    return False
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
                            password_elem.size['width'] // 2 + 30, 5
                        ).click().perform()
                        time.sleep(0.2)
                    except Exception:
                        pass

                # ── 先清空并失焦，让上一轮的校验错误先清除 ──
                # 关键顺序：observer 必须在 reset+失焦之后、fill 之前启动。
                # Element UI 的错误提示只在 blur 时才清除；若 observer 在 reset
                # 之前启动，会记录到"清空字段"触发的残留错误，导致后续合法密码
                # 被误判为拒绝（长度二分搜索因此每一步都被拒 → 测出 max=32）。
                driver.execute_script(JS_RESET_PASSWORD, password_elem)
                time.sleep(0.3)
                try:
                    ActionChains(driver).move_to_element(
                        password_elem
                    ).move_by_offset(
                        password_elem.size['width'] // 2 + 30, 5
                    ).click().perform()
                    time.sleep(0.2)
                except Exception:
                    pass

                # ── 启动 MutationObserver（reset 之后、fill 之前，只观察本次填充）──
                # 用 MutationObserver 而非静态 detectPasswordFeedback()，
                # 避免检测到表单中已存在的其他字段的错误（如"姓名为必填项"）。
                driver.execute_script(
                    "return watchPasswordFeedback(arguments[0])",
                    self.password_xpath,
                )

                # ── 填密码：键盘模拟（聚焦 → send_keys）──
                # 用户也是键盘输入，send_keys 触发真实键盘事件，能同时驱动
                # React/Vue/TANGRAM 等所有框架的校验；JS setter 只发 input/change，
                # 百度 TANGRAM 只认真实键盘事件，会导致校验不触发。失败时回退 JS。
                try:
                    password_elem.click()  # send_keys 前必须先聚焦
                    password_elem.send_keys(test_password)
                except Exception:
                    driver.execute_script(JS_ADD_TEXT_TO_INPUT, password_elem, test_password)
                # 等待 React 受控组件完成状态同步（send_keys 后立即 blur，
                # GitHub 等 React 站点可能因 onChange 未处理完而清空字段值）
                time.sleep(0.5)
                # ── blur 触发内联校验 ──
                # gitee 等站点在密码框失去焦点（blur）时才显示拒绝反馈，必须失焦。
                # 用 Selenium ActionChains 真实鼠标移动：移动到密码框右侧空白区域点击。
                # 无头模式下 ActionChains 坐标点击可能不触发 blur 校验
                # （gitee 无头实测：inline 探针 3 次全无反馈），点击后再补一次
                # JS blur 兜底，确保校验触发。
                try:
                    time.sleep(0.2)
                    ActionChains(driver).move_to_element(
                        password_elem
                    ).move_by_offset(
                        password_elem.size['width'] // 2 + 30, 5
                    ).click().perform()
                except Exception:
                    pass
                try:
                    driver.execute_script(
                        "arguments[0].blur(); "
                        "arguments[0].dispatchEvent(new Event('blur', {bubbles:true}))",
                        password_elem)
                except Exception:
                    pass
                # ── 等待边框 CSS 过渡结束 ──
                # 百度等站点 blur 后先移除 error class，但边框颜色红→灰有约 0.5s
                # 过渡，中间态(如 rgb(254,90,90))会被 isErrorBorder 误判成拒绝红。
                # 等过渡结束再采样，让「变红」=「稳定红」，符合「以密码框变红为准」。
                time.sleep(0.6)
                self.my_logger.debug(f"Fill the password field with {test_password}.")
                # 确认字段值已写入（防止 setter 失败）
                _actual_value = ""
                try:
                    _actual_value = password_elem.get_attribute("value") or ""
                except Exception:
                    pass
                if _actual_value != test_password:
                    # 字段值被站点改写/清空：站点拒绝保留该输入（GitHub 实测：
                    # 填 1 字符密码 "a" 后字段值被清空/改写）。这是"站点拒收
                    # 该密码"的强信号，判为拒绝而非 inconclusive。
                    _cleared = (not _actual_value
                                or len(_actual_value) < len(test_password))
                    if _cleared:
                        try:
                            driver.execute_script("stopWatchingFeedback()")
                        except Exception:
                            pass
                        self.my_logger.warning(
                            f"Password field value cleared/rewritten by site "
                            f"({_actual_value!r} != {test_password!r}); "
                            f"treated as REJECTED (site refuses to keep input)")
                        self._record_probe(
                            test_password, ProbeOutcome.REJECTED,
                            f"field_value_cleared_by_site: got={_actual_value!r}")
                        return False
                    self.my_logger.warning(
                        f"Password field value mismatch, outcome is inconclusive: {test_password}")
                    try:
                        driver.execute_script("stopWatchingFeedback()")
                    except Exception:
                        pass
                    self._record_probe(
                        test_password, ProbeOutcome.INCONCLUSIVE,
                        "password_field_value_mismatch")
                    return False

                # ── 双重检测：字段自身状态决定接受/拒绝 ──
                # 密码框错误状态与密码专属错误文本均可作为拒绝证据；强度计
                # （强/中/弱）只是信息性展示，不作为接受/拒绝的判定依据。
                fb_result = None
                _strength_note = None  # 强度计文本（仅备注，不参与决策）
                # 门控表单检测：注册表单除密码外还有手机号/验证码/确认密码/协议
                # 等恒为空的必填字段。此时密码框的 aria-invalid=true / error class
                # 可能只是"整表未完成"的连带结果，与密码内容无关，必须降级为软信号。
                gated_form = False
                try:
                    gated_form = bool(driver.execute_script(
                        "return (typeof _isGatedForm === 'function') && _isGatedForm(arguments[0])",
                        password_elem))
                except Exception:
                    gated_form = False
                if gated_form:
                    self._gated_form = True
                # 门控表单下等待时长可缩短（密码专属错误在 blur 后 1~2s 内渲染）
                deadline = time.time() + (3 if gated_form else 8)
                _probe_start = time.time()
                while time.time() < deadline:
                    try:
                        # 第一层：密码字段自身状态（validity / :invalid / aria-invalid / class）
                        # 原生 HTML5 内容校验（validity/:invalid）始终是硬拒绝；
                        # aria-invalid / error class 在门控表单下降级为软信号，
                        # 交由第二层密码专属错误消息佐证。
                        field_state = driver.execute_script("""
                            var el = arguments[0];
                            var gated = arguments[1] === true;
                            var state = {rejected: false, reason: null, gated: gated, soft: false,
                                         pending: false};
                            function isErrorBorder(c) {
                                var m = (c || '').match(/rgba?\\(\\s*(\\d+)\\s*,\\s*(\\d+)\\s*,\\s*(\\d+)(?:\\s*,\\s*([\\d.]+))?/);
                                if (!m) return false;
                                var r = +m[1], g = +m[2], b = +m[3];
                                var a = (m[4] !== undefined && m[4] !== '') ? parseFloat(m[4]) : 1.0;
                                if (a < 0.6) return false;
                                // 「纯红」判定：红通道高、绿蓝通道都低且彼此接近（g≈b）。
                                // 橙色（focus/品牌高亮）的 g 明显高于 b，据此排除，避免把
                                // gitee 的 focus 橙（rgba(243,155,84,.61)）误判成错误红。
                                return r >= 170 && (r - g) >= 80 && (r - b) >= 80 && Math.abs(g - b) <= 40;
                            }
                            // 异步校验瞬态（GitHub "Verifying…" 实测）：
                            // 必须在 validity 检查之前判定——Verifying… 会同时
                            // 触发 html5-invalid，如果不提前返回 pending 就会被
                            // 直接误判为 rejected
                            var vm = el.validationMessage || '';
                            if (/verif|checking|check|validating|process|wait|pending/i.test(vm) && vm.length < 30
                                && !/must|should|at least|at most|contain|required/i.test(vm)) {
                                return {rejected: false, soft: false, gated: gated,
                                        pending: true,
                                        reason: 'async-verifying: ' + vm.substring(0, 60)};
                            }
                            // GitHub 异步校验的通用失败消息 "Validation failed"：
                            // 对合法密码是瞬态（服务端校验中），对非法密码是
                            // 最终态。无法仅凭消息区分：首次出现标 pending，
                            // Python 轮询层若 2 秒后仍稳定则判 rejected。
                            if (/^validation failed$/i.test(vm.trim())
                                && !/must|should|at least|at most|contain|required/i.test(vm)) {
                                return {rejected: false, soft: false, gated: gated,
                                        pending: true,
                                        reason: 'async-validating-failed-state: ' + vm.substring(0, 60)};
                            }
                            if (el.validity && !el.validity.valid)
                                { state.rejected = true; state.reason = 'html5-invalid: ' + (el.validationMessage || '').substring(0, 100); }
                            else if (el.matches && el.matches(':invalid'))
                                { state.rejected = true; state.reason = 'css-invalid'; }
                            else if (el.getAttribute('aria-invalid') === 'true') {
                                if (gated) { state.soft = true; state.reason = 'aria-invalid=true (soft, gated)'; }
                                else { state.rejected = true; state.reason = 'aria-invalid=true'; }
                            }
                            if (!state.rejected && !state.soft) {
                                var cls = el.className || '';
                                if (/\\b(error|invalid|danger)\\b/i.test(cls)) {
                                    if (gated) { state.soft = true; state.reason = 'class (soft, gated): ' + cls.substring(0, 50); }
                                    else { state.rejected = true; state.reason = 'class: ' + cls.substring(0, 50); }
                                }
                            }
                            // ── 密码框变红检测（核心拒绝信号）──
                            // gitee 等站点对「太长/太短/字符不足」不在 input 自身写
                            // error class，而是给密码框的外层容器（如 .field）加 error
                            // class、并把边框染红。检查 input 自身 + 祖先链（往上 3 层）
                            // 的 error/invalid/danger class 与边框变红。
                            // 门控表单降级：aistudy666 实测——blur 时整表校验连坐，
                            // 错误样式可能加到 lv>=2 的容器（form/大容器），密码本身
                            // 合法也会变红。lv=1（密码框直接父容器）仍视为密码专属
                            // 硬拒绝；lv>=2 降级 soft 交由错误消息佐证。
                            if (!state.rejected && !state.soft) {
                                var node = el;
                                for (var lv = 0; lv < 4 && node; lv++) {
                                    var ncls = '';
                                    try {
                                        ncls = (typeof node.className === 'string')
                                            ? node.className
                                            : (node.className && node.className.baseVal) || '';
                                    } catch (e) {}
                                    if (/\\b(error|invalid|danger)\\b/i.test(ncls)) {
                                        if (gated && lv >= 2) {
                                            state.soft = true;
                                            state.reason = 'ancestor-error-class(soft,gated,lv=' + lv + '): ' + ncls.substring(0, 50);
                                        } else {
                                            state.rejected = true;
                                            state.reason = 'ancestor-error-class(lv=' + lv + '): ' + ncls.substring(0, 50);
                                        }
                                        break;
                                    }
                                    var ncs = null;
                                    try { ncs = getComputedStyle(node); } catch (e) {}
                                    if (ncs && isErrorBorder(ncs.borderColor)) {
                                        if (gated && lv >= 2) {
                                            state.soft = true;
                                            state.reason = 'ancestor-red-border(soft,gated,lv=' + lv + '): border=' + ncs.borderColor;
                                        } else {
                                            state.rejected = true;
                                            state.reason = 'ancestor-red-border(lv=' + lv + '): border=' + ncs.borderColor;
                                        }
                                        break;
                                    }
                                    node = node.parentElement;
                                }
                            }
                            if (!state.rejected && !state.soft && el.getAttribute('aria-invalid') === 'false')
                                { state.reason = 'aria-invalid=false'; }
                            return state;
                        """, password_elem, gated_form)
                        if field_state and field_state.get("rejected"):
                            fb_result = {"rejected": True, "type": "field-state",
                                         "message": field_state.get("reason", "")}
                            break
                        # aria-invalid=false 只是"无错误标记"，不等于校验通过
                        # （Discord 实测：blur 不校验时"a"也保持 false，误判为
                        # 接受 → 负对照不可信 → 整站无法测）。不在此 break，
                        # 继续轮询等 observer/错误文本证据；若始终无信号，
                        # 由"负对照差分"逻辑在轮询结束后判定。
                        # 已过 3 秒仍无任何信号 → 提前结束轮询走差分判定
                        # （避免 aria-invalid=false 的站每测等满 8 秒）。
                        # 负对照阶段（负对照未建立时）不提前 break：GitHub
                        # 的 "a" 拒绝靠 observer 捕获（"Password is too
                        # short"），提前退出会漏捕获导致负对照不成立。
                        if (field_state and field_state.get("reason") == "aria-invalid=false"
                                and self._negative_control_confirmed
                                and time.time() - _probe_start > 3.0):
                            break
                        # pending 状态（async-verifying）不 break，继续轮询等真实结果
                        # GitHub "Validation failed" 稳定判定：首次出现是
                        # pending（可能瞬态），但持续 2 秒以上未变 valid →
                        # 服务端校验已完成且失败 → 判 rejected（"a" 实测
                        # Validation failed 稳定 12 秒是最终拒绝态）。
                        if (field_state and field_state.get("pending")
                                and "validating-failed-state" in (field_state.get("reason") or "")
                                and time.time() - _probe_start > 2.0):
                            fb_result = {"rejected": True, "type": "field-state",
                                         "message": "html5-invalid: Validation failed (stable)"}
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
                                # 用户名/账号格式错误（12306 实测："6-30位
                                # 字母、数字或_,字母开头"是用户名框提示，
                                # 含"开头/下划线"特征词且无"密码"字样）
                                if (('用户名' in msg or '账号' in msg or '昵称' in msg)
                                        and ('开头' in msg or '下划线' in msg
                                             or '格式' in msg or '昵称' in msg)
                                        and '密码' not in msg and '口令' not in msg):
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

                # ── 拒绝信号最终复验（防异步校验瞬态误判）──
                # GitHub 等服务端异步校验的站点：密码框可能先进入 invalid 状态
                # （validationMessage="Verifying…"/"Validation failed"），服务端
                # 校验完成后才回到 valid。observer/field-state 可能把瞬态记成
                # 拒绝。轮询结束后再读一次字段最终状态：若此时 valid=true 且
                # 不再处于瞬态消息，则改判接受。
                # 复验条件（全部满足才改判）：
                #   1. 类型是 field-state / html5-validity / observer-aria-invalid
                #      / observer-class-change —— 这些是"字段自身状态"信号，
                #      可能被异步校验瞬态污染
                #   2. 消息不含具体要求（"长度为8~14个字符"/"至少包含…"等）——
                #      具体要求的拒绝消息（百度 error-element）是真实拒绝证据
                #   3. 轮询结束时字段 valid=true 且不在瞬态消息状态
                if (fb_result is not None and fb_result.get("rejected")
                        and fb_result.get("type") in (
                            "html5-validity", "field-state",
                            "observer-aria-invalid", "observer-class-change")):
                    try:
                        _fb_msg_lower = (fb_result.get("message") or "").lower()
                        _has_specific_requirement = any(
                            kw in _fb_msg_lower for kw in (
                                "must", "should", "at least", "at most", "contain",
                                "required", "too", "characters", "letters", "digits",
                                "长度", "至少", "包含", "不能", "不允许",
                                "字母", "数字", "符号", "密码",
                            )
                        )
                        _final_state = driver.execute_script("""
                            var el = arguments[0];
                            var vm = (el.validationMessage || '').trim();
                            var transient = /(verif|checking|validating|process|wait|pending)/i.test(vm)
                                || /^validation failed$/i.test(vm);
                            // 字段必须完全干净才算瞬态解除：
                            // gitee 等自定义校验站拒绝时红边框/error class 常驻，
                            // 即使 validity.valid=true 也是真实拒绝，绝不能改判。
                            function isErrorBorder(c) {
                                var m = (c || '').match(/rgba?\\(\\s*(\\d+)\\s*,\\s*(\\d+)\\s*,\\s*(\\d+)(?:\\s*,\\s*([\\d.]+))?/);
                                if (!m) return false;
                                var r = +m[1], g = +m[2], b = +m[3];
                                return r >= 170 && (r - g) >= 80 && (r - b) >= 80 && Math.abs(g - b) <= 40;
                            }
                            var dirty = false;
                            var cls = el.className || '';
                            if (/\\b(error|invalid|danger)\\b/i.test(cls)) dirty = true;
                            if (!dirty) {
                                var node = el;
                                for (var lv = 0; lv < 4 && node; lv++) {
                                    var ncls = '';
                                    try { ncls = (typeof node.className === 'string') ? node.className : ''; } catch(e) {}
                                    if (/\\b(error|invalid|danger)\\b/i.test(ncls)) { dirty = true; break; }
                                    try {
                                        var ncs = getComputedStyle(node);
                                        if (ncs && isErrorBorder(ncs.borderColor)) { dirty = true; break; }
                                    } catch(e) {}
                                    node = node.parentElement;
                                }
                            }
                            return {
                                valid: !el.validity || el.validity.valid,
                                transient: transient,
                                dirty: dirty,
                                vm: vm.substring(0, 60)
                            };
                        """, password_elem)
                        if (not _has_specific_requirement
                                and _final_state and _final_state.get("valid")
                                and not _final_state.get("transient")
                                and not _final_state.get("dirty")):
                            self.my_logger.info(
                                f"拒绝信号 {fb_result.get('type')}:{fb_result.get('message','')[:50]} "
                                f"复验为异步瞬态（最终 valid=true），改判接受。")
                            fb_result = {"rejected": False, "type": "final-revalidation",
                                         "message": "async transient resolved: field valid at poll end"}
                    except Exception:
                        pass

                if fb_result is None:
                    # “无拒绝信号”本身不是接受证据。只有本轮同一表单先用一字符
                    # 负对照得到明确拒绝，才能把候选的无拒绝解释为差分接受。
                    _strength_info = ""
                    if _strength_note:
                        _strength_info = f", strength_meter=\"{_strength_note[:80]}\""
                        self._parse_strength_level(_strength_note)
                    else:
                        self._last_strength_level = None
                    if self._negative_control_confirmed:
                        self.my_logger.success(
                            f"The tested password {test_password} appears accepted"
                            f" (paired negative control rejected; no candidate rejection"
                            f" signal{_strength_info})")
                        self._record_probe(
                            test_password, ProbeOutcome.ACCEPTED,
                            "paired_negative_control_rejected_and_candidate_no_rejection")
                    else:
                        self.my_logger.warning(
                            f"The tested password {test_password} is inconclusive"
                            f" (no rejection signal and no validated negative control"
                            f"{_strength_info})")
                        self._record_probe(
                            test_password, ProbeOutcome.INCONCLUSIVE,
                            "no_rejection_signal_without_validated_negative_control")
                    # 退出密码框
                    try:
                        ActionChains(driver).move_to_element(
                            password_elem
                        ).move_by_offset(
                            password_elem.size['width'] // 2 + 30, 5
                        ).click().perform()
                        time.sleep(0.2)
                    except Exception:
                        pass
                    uub.random_sleep([0.5, 1])
                    return self._last_probe_outcome == ProbeOutcome.ACCEPTED

                fb_type = fb_result.get("type", "unknown")
                fb_msg = fb_result.get("message", "")
                if fb_result.get("rejected"):
                    flag = False
                    self._saw_pwd_specific_reject = True
                    self._last_reject_msg = fb_msg
                    self._record_probe(
                        test_password, ProbeOutcome.REJECTED,
                        f"{fb_type}: {fb_msg}")
                    self.my_logger.warning(
                        f"The tested password {test_password} is rejected ({fb_type}: {fb_msg})")
                else:
                    flag = True
                    self._record_probe(
                        test_password, ProbeOutcome.ACCEPTED,
                        f"{fb_type}: {fb_msg or 'explicit_non_rejected_state'}")
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
                        password_elem.size['width'] // 2 + 30, 5
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
                    # 浏览器已被关闭/断开：后续所有测试都会对已死 driver 空转失败，
                    # 立即终止整个测量（由 run_password_policy_test 捕获并落盘）。
                    self._browser_dead = True
                    try:
                        driver.quit()
                    except Exception:
                        pass
                    raise BrowserDeadError(
                        f"browser session closed: {str(e)[:120]}")
            finally:
                self.my_logger.debug("Process end.")
                # 共享 driver 不销毁，仅刷新到空白页，等待下一个密码测试

        self._record_probe(
            test_password, ProbeOutcome.INCONCLUSIVE,
            "probe_retries_exhausted")
        return False

    def check_special_symbols(self, test_password):
        """[Restrictive -- Special Symbols] 真正测试网站是否允许特殊符号。

        旧实现只检查密码池自身字符串（含不含符号），没有测试网站——
        密码池恰好不含符号时会把"允许符号"的网站误判为"禁止符号"。
        新实现：保持密码长度不变，把一个冗余字符替换为特殊符号 @：
            - 被接受 → 特殊符号允许 → 返回 False（r_no_a_sps=False）
            - 被拒绝 → 特殊符号禁止 → 返回 True（r_no_a_sps=True）
        :param test_password: the admissible password
        :return: True 表示网站禁止特殊符号
        """
        if not test_password:
            self.my_logger.error("No admissible password available; Improper process here.")
            raise AssertionError("No admissible password available for special symbol check.")
        if any(not char.isalnum() for char in test_password):
            self.my_logger.info("可接受基准密码本身含特殊符号，已证明网站允许符号。")
            return False

        def char_kind(char):
            if char.islower():
                return "lower"
            if char.isupper():
                return "upper"
            if char.isdigit():
                return "digit"
            return "symbol"

        counts = {}
        for char in test_password:
            kind = char_kind(char)
            counts[kind] = counts.get(kind, 0) + 1
        replace_at = next(
            (idx for idx in range(len(test_password) - 1, -1, -1)
             if counts.get(char_kind(test_password[idx]), 0) > 1),
            None,
        )
        if replace_at is None:
            # P3 缺陷2 修复：无冗余字符时不能直接返回 False(=允许符号)——
            # 那是把 INCONCLUSIVE 误报成"允许"。回退：替换位置 0 为 @，
            # 并用"替换位置 0 为另一类字符（不含符号）"作对照消歧：
            #   - @ 探针被接受 → 允许符号（返回 False）
            #   - @ 探针被拒 且 对照被接受 → 符号是拒绝原因 → 禁止符号（返回 True）
            #   - @ 探针被拒 且 对照也被拒 → 是"丢失原字符类别"导致的拒绝，
            #     与符号无关，符号状态无法判定 → 保持 False 但记录标记，
            #     让下游知道符号结论不可信（避免误报"允许"）。
            self.my_logger.warning(
                "admissible 无冗余字符可替换，改用位置0替换 + 对照消歧。")
            symbol_pw = "@" + test_password[1:]
            self.my_logger.info(
                f"Testing whether special symbols are allowed with: {symbol_pw}")
            if self.test_one_password(symbol_pw, "test special symbol (fallback)"):
                self.my_logger.info("Special symbols are allowed by the website.")
                return False
            # 对照：把位置 0 换成与原字符不同的另一类字符（不含符号）
            _kinds = {
                "lower": "a", "upper": "A", "digit": "3",
            }
            orig_kind = char_kind(test_password[0])
            control_char = next(
                (c for k, c in _kinds.items() if k != orig_kind), "a")
            control_pw = control_char + test_password[1:]
            self.my_logger.info(
                f"Control probe (no symbol) with: {control_pw}")
            if self.test_one_password(control_pw, "control: replace with other class"):
                self.my_logger.info(
                    "Symbol probe rejected but control accepted: symbols NOT allowed.")
                return True
            self.my_logger.warning(
                "符号判定 inconclusive：@ 探针与对照均被拒，无法区分"
                "『禁止符号』与『丢失字符类别』。按允许处理但记录标记。")
            self._record_probe(
                test_password, ProbeOutcome.INCONCLUSIVE,
                "special_symbol_inconclusive_ambiguous_rejection")
            return False
        symbol_pw = test_password[:replace_at] + "@" + test_password[replace_at + 1:]
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
                        # 用安全定值符号：gen_random_symbol_character(1) 会从 string.punctuation
                        # 随机取到 ' 或 \ 等字符，可能弄坏 163 内联校验提示导致假接受。
                        # permissive 测试已确认 ! 是合法标点且不会破坏提示。
                        tmp_char = '!'
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
            self.my_logger.info("Replacing all the digits with lowercase letters.")
            for i in self.admissible_password:
                if i.isdigit():
                    sps = uusg.gen_random_lower_character(1)
                    modified_str += sps
                else:
                    modified_str += i
            if self.test_one_password(modified_str, "minimum for digits"):
                self.my_logger.info(f"Password {modified_str} with non-tested-character can be accepted.")
                ret_minimum = 0
            else:
                changed_dict = uub.get_each_character_num(modified_str)
                if changed_dict["type_num"] == 2:
                    # 数字被替换后类别掉到 2 类：拒绝可能源于「类别数不足」而非「缺数字」。
                    # 用安全定值符号 '!' 替换最后一个字母，得到「3 类但无数字」再测：
                    # 接受 → 数字并非必需（如 3-of-4）→ 0；拒绝 → 数字确实必需 → 走补回数字逻辑。
                    # （与 change_and_test_lower_upper_minimum 的 disambiguate 逻辑一致）
                    last_letter_index = None
                    for index, char in enumerate(reversed(modified_str)):
                        if char.isalpha():
                            last_letter_index = len(modified_str) - index - 1
                            break
                    if last_letter_index is not None:
                        tmp_ap = (modified_str[:last_letter_index] + '!'
                                  + modified_str[last_letter_index + 1:])
                        self.my_logger.info("Adding a symbol to disambiguate the digit minimum.")
                        if self.test_one_password(tmp_ap, "add a symbol to disambiguate the digit minimum"):
                            self.my_logger.info(
                                f"Password {tmp_ap} without digit can be accepted; digit is not required.")
                            ret_minimum = 0
                            return ret_minimum
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

    @staticmethod
    def _reduce_combo_flags(*ret_lists):
        """把多个组合标志列表归约为「细粒度 4 类维 one-hot」的单一结果。

        4 类维 {R14,R24,R34,R44} 取最大 N：同维内 r_cmb34 与 r_cmb44
        不会同真（取更强要求的 r_cmb44）。粗粒度 3 类维已废弃，不再参与归约。
        """
        out = [False] * 7
        order = (RMB.R14.value, RMB.R24.value, RMB.R34.value, RMB.R44.value)
        n = 0
        for i, idx in enumerate(order):
            if any(r[idx] for r in ret_lists):
                n = i + 1
        if n:
            out[order[n - 1]] = True
        return out

    def identify_combination_requirements_3_sum(self, com_r):
        """识别「3 类已 individually required」时第 4 类是否也必需。

        initial_sum == 3，即 LOWER/UPPER/DIGIT/SYMBOL 中恰有 3 类 = 1，
        有且仅有一个缺失类。按缺失类分支逐一探测，每支 early return，
        消除原 DL/SL 段串联执行、互相覆盖导致的标志堆积。

        只报告细粒度 4 类维（r_cmb34 / r_cmb44）；粗粒度 3 类维已废弃。
        """
        ret_list = [False, False, False, False, False, False, False]

        # ── 缺失 digit：lower+upper+symbol 必需，探 digit 是否也必需 ──
        if com_r[CR.DIGIT_R.value] == 0:
            modified_password = uusg.transfer_digit_into_symbol(self.admissible_password)
            if modified_password != "" and self.test_one_password(modified_password):
                # digit 可被 symbol 替换 → 非必需 → 3 of 4
                ret_list[RMB.R34.value] = True
            else:
                # digit 也必需 → 4 of 4
                ret_list[RMB.R44.value] = True
            return ret_list

        # ── 缺失 symbol：lower+upper+digit 必需，symbol 本就可选 → 3 of 4 ──
        if com_r[CR.SYMBOL_R.value] == 0:
            ret_list[RMB.R34.value] = True
            return ret_list

        # ── 缺失 upper：lower+digit+symbol 必需，探 upper 是否也必需 ──
        if com_r[CR.UPPER_R.value] == 0:
            # 用符号替换大写（而非 .lower()）：保持 3 类（lower+digit+symbol），
            # 避免 .lower() 把类别塌缩成 2 类（lower+digit）被 3-of-4 站点误拒，
            # 进而误判为 4-of-4。
            modified_password = uusg.transfer_upper_into_symbol(self.admissible_password)
            if modified_password != "" and self.test_one_password(modified_password):
                # upper 可去掉 → 非必需 → 3 of 4
                ret_list[RMB.R34.value] = True
            else:
                # upper 也必需 → 4 of 4
                ret_list[RMB.R44.value] = True
            return ret_list

        # ── 缺失 lower：upper+digit+symbol 必需，探 lower 是否也必需 ──
        if com_r[CR.LOWER_R.value] == 0:
            modified_password = uusg.transfer_lower_into_symbol(self.admissible_password)
            if modified_password != "" and self.test_one_password(modified_password):
                # lower 可去掉 → 非必需 → 3 of 4
                ret_list[RMB.R34.value] = True
            else:
                # lower 也必需 → 4 of 4
                ret_list[RMB.R44.value] = True
            return ret_list

        # initial_sum == 3 时必有且仅有一个缺失类，理论上不会走到这里。
        self.my_logger.error("This process is conducted in a unexpected way.")
        return ret_list

    def identify_combination_requirements_0_sum(self, com_r):
        """识别「无个体必需类别，但可能存在 N-of-M 组合要求」的政策。

        initial_sum == 0：LOWER/UPPER/DIGIT/SYMBOL 均非 individually required
        （各自 minimum 均为 0），但密码仍可能要求「任意 N 类」（如 163 的 3-of-4）。
        依次探测「1 类 / 2 类 / 3 类」密码是否可接受，确定 N：
        - 1 类接受 → 1 of 4（r_cmb14）
        - 2 类接受 → 2 of 4（r_cmb24）
        - 3 类接受 → 3 of 4（r_cmb34）
        - 均拒 → 4 of 4（r_cmb44）
        """
        ret_list = [False, False, False, False, False, False, False]

        # 1 类：全部压成单一字符类（小写）
        one_class = uusg.transfer_upper_into_lower(
            uusg.transfer_sth_to_letter(self.admissible_password)
        )
        self.my_logger.info(f"0_sum: test 1-class password {one_class}.")
        if self.test_one_password(one_class):
            ret_list[RMB.R14.value] = True
            return ret_list

        # 2 类：lower + digit（大写→小写，符号→数字）
        two_class = uusg.transfer_upper_into_lower(
            uusg.transfer_symbol_into_digit(self.admissible_password)
        )
        self.my_logger.info(f"0_sum: test 2-class password {two_class}.")
        if self.test_one_password(two_class):
            ret_list[RMB.R24.value] = True
            return ret_list

        # 3 类：admissible 本身为 lower+upper+digit（3 细类），已由
        # find_admissible_password 确认可接受。到达此处说明 1/2 类均被拒、
        # 3 类被接受 → 3 of 4。
        self.my_logger.info("0_sum: 1/2-class rejected while admissible (3-class) accepted -> 3 of 4.")
        ret_list[RMB.R34.value] = True
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
                ret_list[RMB.R24.value] = True
            else:
                com_r_1 = com_r.copy()
                com_r_2 = com_r.copy()
                com_r_1[CR.UPPER_R.value] = 1
                com_r_2[CR.DIGIT_R.value] = 1
                ret_list_1 = self.identify_combination_requirements_3_sum(com_r_1)
                ret_list_2 = self.identify_combination_requirements_3_sum(com_r_2)
                ret_list = self._reduce_combo_flags(ret_list_1, ret_list_2)
            return ret_list
        elif com_r[CR.SYMBOL_R.value] == 1 and com_r[CR.UPPER_R.value] == 1:
            modified_str_two = uusg.transfer_symbol_into_digit(
                uusg.transfer_lower_into_upper(self.admissible_password)
            )
            self.my_logger.info(f"Modified password is {modified_str_two} with symbol and upper.")
            if self.test_one_password(modified_str_two):
                # r24 is true
                ret_list[RMB.R24.value] = True
            else:
                com_r_1 = com_r.copy()
                com_r_2 = com_r.copy()
                com_r_1[CR.LOWER_R.value] = 1
                com_r_2[CR.DIGIT_R.value] = 1
                ret_list_1 = self.identify_combination_requirements_3_sum(com_r_1)
                ret_list_2 = self.identify_combination_requirements_3_sum(com_r_2)
                ret_list = self._reduce_combo_flags(ret_list_1, ret_list_2)
            return ret_list
        elif com_r[CR.SYMBOL_R.value] == 1 and com_r[CR.DIGIT_R.value] == 1:
            modified_str_two = uusg.transfer_letter_to_digit(self.admissible_password)
            self.my_logger.info(f"Modified password is {modified_str_two} with symbol and digit.")
            if self.test_one_password(modified_str_two):
                # r24 is true
                ret_list[RMB.R24.value] = True
            else:
                com_r_1 = com_r.copy()
                com_r_2 = com_r.copy()
                com_r_1[CR.LOWER_R.value] = 1
                com_r_2[CR.UPPER_R.value] = 1
                ret_list_1 = self.identify_combination_requirements_3_sum(com_r_1)
                ret_list_2 = self.identify_combination_requirements_3_sum(com_r_2)
                ret_list = self._reduce_combo_flags(ret_list_1, ret_list_2)
            return ret_list
        elif com_r[CR.LOWER_R.value] == 1 and com_r[CR.UPPER_R.value] == 1:
            modified_str_two = uusg.transfer_sth_to_letter(self.admissible_password)
            self.my_logger.info(f"Modified password is {modified_str_two} with lower and upper.")
            if self.test_one_password(modified_str_two):
                # r24 is true
                ret_list[RMB.R24.value] = True
            else:
                com_r_1 = com_r.copy()
                com_r_2 = com_r.copy()
                com_r_1[CR.DIGIT_R.value] = 1
                com_r_2[CR.SYMBOL_R.value] = 1
                ret_list_1 = self.identify_combination_requirements_3_sum(com_r_1)
                ret_list_2 = self.identify_combination_requirements_3_sum(com_r_2)
                ret_list = self._reduce_combo_flags(ret_list_1, ret_list_2)
            return ret_list
        elif com_r[CR.LOWER_R.value] == 1 and com_r[CR.DIGIT_R.value] == 1:
            modified_str_two = uusg.transfer_upper_into_lower(
                uusg.transfer_symbol_into_digit(self.admissible_password)
            )
            self.my_logger.info(f"Modified password is {modified_str_two} with lower and digit.")
            if self.test_one_password(modified_str_two):
                # r24 is true
                self.my_logger.info(f"Here we go!")
                ret_list[RMB.R24.value] = True
            else:
                com_r_1 = com_r.copy()
                com_r_2 = com_r.copy()
                com_r_1[CR.UPPER_R.value] = 1
                com_r_2[CR.SYMBOL_R.value] = 1
                ret_list_1 = self.identify_combination_requirements_3_sum(com_r_1)
                ret_list_2 = self.identify_combination_requirements_3_sum(com_r_2)
                ret_list = self._reduce_combo_flags(ret_list_1, ret_list_2)
            return ret_list
        elif com_r[CR.UPPER_R.value] == 1 and com_r[CR.DIGIT_R.value] == 1:
            modified_str_two = uusg.transfer_lower_into_upper(
                uusg.transfer_symbol_into_digit(self.admissible_password)
            )
            self.my_logger.info(f"Modified password is {modified_str_two} with upper and digit.")
            if self.test_one_password(modified_str_two):
                # r24 is true
                ret_list[RMB.R24.value] = True
            else:
                com_r_1 = com_r.copy()
                com_r_2 = com_r.copy()
                com_r_1[CR.LOWER_R.value] = 1
                com_r_2[CR.SYMBOL_R.value] = 1
                ret_list_1 = self.identify_combination_requirements_3_sum(com_r_1)
                ret_list_2 = self.identify_combination_requirements_3_sum(com_r_2)
                ret_list = self._reduce_combo_flags(ret_list_1, ret_list_2)
            return ret_list
        else:
            self.my_logger.error("This process is conducted in a unexpected way.")
            return ret_list

    def identify_combination_requirements_1_sum(self, com_r):
        """识别「1 类 individually required」时实际需几类。

        initial_sum == 1，即 LOWER/UPPER/DIGIT/SYMBOL 中恰有 1 类 = 1。
        先探「仅此 1 类是否足够」；不足则枚举其余 3 类作为「第 2 必需类」，
        分别交给 _2_sum（其内部再递归 _3_sum 覆盖 3-of-4 / 4-of-4）。
        """
        ret_list = [False, False, False, False, False, False, False]

        if com_r[CR.SYMBOL_R.value] == 1:
            modified_str = uusg.transfer_digit_into_symbol(
                uusg.transfer_letter_to_digit(self.admissible_password)
            )
            extras = (CR.UPPER_R.value, CR.LOWER_R.value, CR.DIGIT_R.value)
        elif com_r[CR.DIGIT_R.value] == 1:
            modified_str = uusg.transfer_symbol_into_digit(
                uusg.transfer_letter_to_digit(self.admissible_password)
            )
            extras = (CR.UPPER_R.value, CR.LOWER_R.value, CR.SYMBOL_R.value)
        elif com_r[CR.UPPER_R.value] == 1:
            modified_str = uusg.transfer_lower_into_upper(
                uusg.transfer_sth_to_letter(self.admissible_password)
            )
            extras = (CR.DIGIT_R.value, CR.LOWER_R.value, CR.SYMBOL_R.value)
        elif com_r[CR.LOWER_R.value] == 1:
            modified_str = uusg.transfer_upper_into_lower(
                uusg.transfer_sth_to_letter(self.admissible_password)
            )
            extras = (CR.DIGIT_R.value, CR.UPPER_R.value, CR.SYMBOL_R.value)
        else:
            self.my_logger.error("This process is conducted in a unexpected way.")
            return ret_list

        if self.test_one_password(modified_str):
            # 只需 1 类 → 1 of 4
            ret_list[RMB.R14.value] = True
            return ret_list

        # 需要更多类 → 枚举其余 3 类作为「第 2 必需类」的假设
        com_r_1 = com_r.copy()
        com_r_2 = com_r.copy()
        com_r_3 = com_r.copy()
        com_r_1[extras[0]] = 1
        com_r_2[extras[1]] = 1
        com_r_3[extras[2]] = 1
        ret_list_1 = self.identify_combination_requirements_2_sum(com_r_1)
        ret_list_2 = self.identify_combination_requirements_2_sum(com_r_2)
        ret_list_3 = self.identify_combination_requirements_2_sum(com_r_3)
        return self._reduce_combo_flags(ret_list_1, ret_list_2, ret_list_3)

    def identify_combination_requirements(self, restrictive_policy, eff_length=None):
        # ── 已知局限（暂不修复，记录备查）──
        # 引擎的组合模型是「至少 N 个数字/大写/小写/符号 + N-of-M 组合」，
        # 无法表达「字母/数字/标点 **至少 2 类**」这类「N-of-M 但不区分具体哪类」策略。
        # 后果（以百度为例，实际策略为「≥2 of {字母,数字,标点}」）：
        #   - 把数字全换成小写得到纯字母（仅 1 类）→ 被拒，引擎误读成 r_dig_min=1；
        #   - 把「≥2 of 3 类」误判成 r_cmb34=True（3 of 4）。
        # 这两项均非百度真实政策，属策略模型覆盖盲区，留待后续扩展「≥N 类」维度。
        # 组合测试在长度测试之后执行（P3 修复缺陷3：组合先于长度会误判），
        # eff_length=[min, max] 用于记录/保护：admissible 长度超出上限时组合
        # 测试的密码必然被长度拒绝，此时结果不可信。
        if eff_length is not None:
            try:
                _ad = self.admissible_password or ""
                _lo, _hi = eff_length[0], eff_length[1]
                if _ad and _hi is not None and len(_ad) > _hi:
                    self.my_logger.warning(
                        f"admissible 长度 {len(_ad)} 超出组合阶段长度上限 {_hi}，"
                        f"组合测试结果可能被长度拒绝污染。")
            except Exception:
                pass
        self.my_logger.info("Identifying the composition requirements of the website BEGINs.")
        # R13 R23 R33 R14 R24 R34 R44 —— 粗粒度前 3 项已废弃，恒 False
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
            # 4-of-4：细粒度 lower/upper/digit/symbol 四类全必需。
            # 粗粒度 3 类维已废弃，仅报细粒度。
            ret_list[RMB.R44.value] = True
            return ret_list
        elif initial_sum == 3:
            ret_list = self.identify_combination_requirements_3_sum(com_r)
        elif initial_sum == 2:
            ret_list = self.identify_combination_requirements_2_sum(com_r)
        elif initial_sum == 1:
            ret_list = self.identify_combination_requirements_1_sum(com_r)
        else:
            ret_list = self.identify_combination_requirements_0_sum(com_r)
        self.my_logger.info("Identifying the composition requirements of the website ends.")
        return ret_list

    def self_consistency_check(self, restrictive_policy, eff_length, admissible):
        """P3 自洽校验：用已推断的约束反推密码验证模型一致性。

        引擎模型是 AND 语义（长度 + 各类最少数量 + N-of-M 组合）。真实站点
        常有 OR 语义（如 GitHub「≥15 位 或 ≥8 位且含数字+小写」），模型无法
        表达，导致推断出的约束与实际行为不一致而不自知。本方法用两类反推
        密码探测模型与站点行为是否自洽：

          1. 最小长度单类密码（全数字）：当模型预测"任意单类即可"时（无
             类要求或仅 r_cmb14），站点若拒绝 → OR 规则/缺失约束信号，
             模型无法解释该行为 → 返回 (False, note, or_rule)
          2. 最小长度 + admissible 同类结构密码（截断）：模型预测接受，
             站点若拒绝 → 最小长度下需要更多类别（OR 规则的分支）→ 返回
             (False, note, or_rule)

        :return: (ok: bool, note: str, or_rule: dict|None)  ok=False 表示
                 发现模型无法解释的行为；or_rule 为已刻画的 OR 规则结构
                 （identify_or_rule 探测结果），调用方据此输出而非丢弃
        """
        note = ""
        or_rule = None
        lo = eff_length[0] if eff_length else None
        hi = eff_length[1] if eff_length else None
        if not lo or lo < 4 or not admissible:
            return True, "skip: min length insufficient for probing", None
        rp = restrictive_policy
        inferred_classes = 0
        if rp.get("r_dig_min", 0) > 0:
            inferred_classes += 1
        if rp.get("r_upp_min", 0) > 0:
            inferred_classes += 1
        if rp.get("r_low_min", 0) > 0:
            inferred_classes += 1
        if rp.get("r_sps_min", 0) > 0:
            inferred_classes += 1
        cmb = any(rp.get(k, False) for k in (
            "r_cmb13", "r_cmb23", "r_cmb33",
            "r_cmb14", "r_cmb24", "r_cmb34", "r_cmb44"))
        # 模型预测"任意单类字符即可"：无类要求，或仅要求"至少1类"
        single_class_enough = (
            inferred_classes == 0 and (not cmb or rp.get("r_cmb14", False)))

        # 1) 最小长度单类密码（全数字，无重复/连续，避免"禁止重复/顺序"
        #    规则的干扰——"99999999" 可能因重复被拒而非类别问题）
        if single_class_enough and lo >= 4:
            probe_pw = ("9630852741" * 2)[:lo]
            self.my_logger.info(
                f"自洽校验: 最小长度单类密码 {probe_pw} (len={lo})")
            if not self.test_one_password(
                    probe_pw, "consistency: single-class at min length"):
                note = (
                    "or_rule_likely: 最小长度单类密码被拒但模型未推断任何"
                    "字符类要求（可能为 OR 规则或缺失约束），政策可能失真")
                self.my_logger.warning(note)
                # 刻画 OR 规则分支（最少字符类 + 长度替代分支）
                or_rule = self.identify_or_rule(
                    eff_length, admissible,
                    r_no_a_sps=bool(rp.get("r_no_a_sps", False)))
                return False, note, or_rule

        # 2) 最小长度 + admissible 同类结构（截断保留类别）
        if len(admissible) > lo:
            probe_pw = admissible[:lo]
            if probe_pw != admissible:
                self.my_logger.info(
                    f"自洽校验: 最小长度同类结构密码 {probe_pw} (len={lo})")
                if not self.test_one_password(
                        probe_pw, "consistency: admissible prefix at min length"):
                    note = (
                        "or_rule_likely: 最小长度下 admissble 前缀被拒，"
                        "站点可能在短长度要求更多字符类别（OR 规则分支），"
                        "政策可能失真")
                    self.my_logger.warning(note)
                    return False, note, None
        return True, "consistent", None

    def identify_or_rule(self, eff_length, admissible, r_no_a_sps=False):
        """P3 OR 规则刻画：探测并输出结构化的 OR 规则描述。

        在自洽校验发现 OR 规则后调用，探测两类信息（探针有界，约 5~7 个）：
          1. 最小长度下的最少字符类要求：单类密码（lower/upper/digit）逐一
             探测哪些类不足；再用两两组合探测"几类才够"。
          2. 长度替代分支：单类密码从 lo+2 起向上探测，找到单类即可被接受
             的长度阈值（GitHub 实测 15 位即可任意组合）。

        :return: dict（可直接作为 policy["_or_rule"]）或 None（探测不足）
        """
        lo = eff_length[0] if eff_length else None
        hi = eff_length[1] if eff_length else None
        if not lo or lo < 4:
            return None
        or_rule = {
            "min_length": lo,
            "single_class_rejected": ["digit"],
            "single_class_accepted": [],
            "pair_classes": {},
            "length_alternative": None,
        }
        lower_pool = "kqmavzptnryfbwjcxldgsehuio"
        upper_pool = lower_pool.upper()
        digit_pool = "9630852741"

        def _probe(pool: str, length: int) -> bool:
            pw = (pool * 3)[:length]
            return bool(self.test_one_password(
                pw, f"or-rule probe: {pool[:3]}... len={length}"))

        # 1) 单类探测（digit 已在自洽校验确认被拒）
        single_map = {
            "lower": lower_pool, "upper": upper_pool, "digit": digit_pool,
        }
        single_accepted = []
        for name, pool in single_map.items():
            if name == "digit":
                continue  # 已确认被拒
            if _probe(pool, lo):
                single_accepted.append(name)
        or_rule["single_class_rejected"] = [
            n for n in ("digit", "lower", "upper")
            if n not in single_accepted
        ]
        or_rule["single_class_accepted"] = single_accepted

        # 2) 两两组合探测（排除禁止符号，且单类不够时才需要）
        pairs = [("lower", "upper"), ("lower", "digit"), ("upper", "digit")]
        for a, b in pairs:
            pa, pb = single_map[a], single_map[b]
            pw = (pa[:5] + pb[:5])[:lo]
            pw = (pw * 3)[:lo]
            accepted = bool(self.test_one_password(
                pw, f"or-rule probe: {a}+{b} len={lo}"))
            or_rule["pair_classes"][f"{a}+{b}"] = accepted

        # 3) 长度替代分支：单类密码从 lo 起向上探测
        # 若 hi 存在，限制探测范围避免撞上最大长度。
        # 步进 1 并在命中后回溯确认边界（GitHub 实测：阈值 15 但步进 2
        # 会测成 16，偏 1；回溯测 length-1 确认精确边界）。
        max_len = min(hi, lo + 12) if hi else lo + 12
        for length in range(lo + 1, max_len + 1):
            if _probe(digit_pool, length):
                # 回溯确认：length-1 被拒才是精确阈值
                if length > lo + 1 and not _probe(digit_pool, length - 1):
                    or_rule["length_alternative"] = length
                else:
                    or_rule["length_alternative"] = length
                break
        return or_rule

    def extract_hint_policy(self) -> dict:
        """解析页面上的密码规则提示文本，提取政策线索。

        inline 反馈无法建立（gamersky 等瞬时闪现提示/提交时才校验的站）
        时，页面常驻/闪现的规则提示（"密码不能带有中文，并且个数在6-20
        位！"）本身含政策信息。解析长度区间与字符类要求作为「线索政策」
        （_hint_policy），标注为提示而非实测，让用户至少看到站点自述规则。

        提示可能在填密码后才闪现（gamersky 实测），扫描前先填一个短密码
        并 blur 触发。

        :return: {"length_min": int|None, "length_max": int|None,
                  "charset_hints": [str], "raw_texts": [str]}
        """
        import re as _re
        hint = {"length_min": None, "length_max": None,
                "charset_hints": [], "raw_texts": []}
        try:
            driver = self._driver or _get_shared_driver()
            # 填短密码触发提示闪现（gamersky 等站提示只在 blur 后出现）
            try:
                if self.password_xpath:
                    el = driver.find_element(By.XPATH, self.password_xpath)
                    if el.is_displayed():
                        driver.execute_script(
                            "arguments[0].value='';"
                            "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));"
                            "arguments[0].focus();", el)
                        try:
                            el.send_keys("a")
                        except Exception:
                            pass
                        time.sleep(0.4)
                        driver.execute_script(
                            "arguments[0].blur();"
                            "arguments[0].dispatchEvent(new Event('blur',{bubbles:true}));", el)
                        time.sleep(1.0)
            except Exception:
                pass
            texts = driver.execute_script("""
                var out = [];
                var scan = function(doc) {
                  doc.querySelectorAll('div,span,p,em,label,li,small').forEach(function(e) {
                    var t = (e.innerText || '').trim();
                    if (t && t.length >= 4 && t.length < 100
                        && /密码|口令|password|passwd/i.test(t)
                        && e.children.length === 0) out.push(t);
                  });
                };
                scan(document);
                // 遍历可见 iframe（caixin u.caixinglobal.com 注册页实测：
                // 密码框和提示在 iframe 内，主文档扫描不到）
                document.querySelectorAll('iframe').forEach(function(f) {
                  try {
                    if (f.contentDocument && f.contentDocument.body) scan(f.contentDocument);
                  } catch(e) {}
                });
                return out.slice(0, 20);
            """)
            if not texts:
                # 跨域 iframe（caixin u.caixinglobal.com 实测）：JS 无法
                # 访问 contentDocument。若口令框在 iframe 内，切进去再扫。
                # 优先 password_frame_path，否则遍历所有可见 iframe。
                _scanned = False
                if self.password_frame_path:
                    if self._ensure_frame_context(driver):
                        texts = driver.execute_script("""
                            var out = [];
                            document.querySelectorAll('div,span,p,em,label,li,small').forEach(function(e) {
                              var t = (e.innerText || '').trim();
                              if (t && t.length >= 4 && t.length < 100
                                  && /密码|口令|password|passwd/i.test(t)
                                  && e.children.length === 0) out.push(t);
                            });
                            return out.slice(0, 20);
                        """)
                        _scanned = True
                        try:
                            driver.switch_to.default_content()
                        except Exception:
                            pass
                if not _scanned or not texts:
                    # 遍历所有可见 iframe 扫描（无 frame_path 时兜底）
                    try:
                        driver.switch_to.default_content()
                        _frames = driver.find_elements(By.TAG_NAME, "iframe")
                        for _f in _frames:
                            try:
                                driver.switch_to.frame(_f)
                                _it = driver.execute_script("""
                                    var out = [];
                                    document.querySelectorAll('div,span,p,em,label,li,small').forEach(function(e) {
                                      var t = (e.innerText || '').trim();
                                      if (t && t.length >= 4 && t.length < 100
                                          && /密码|口令|password|passwd/i.test(t)
                                          && e.children.length === 0) out.push(t);
                                    });
                                    return out.slice(0, 20);
                                """)
                                if _it:
                                    texts = _it
                                    break
                            except Exception:
                                continue
                            finally:
                                try:
                                    driver.switch_to.default_content()
                                except Exception:
                                    pass
                    except Exception:
                        pass
            if not texts:
                return hint
            for t in texts:
                # 过滤纯导航/链接文本（"密码登录/忘记密码/密码重置"无规则信息）
                if not _re.search(
                        r'长度|位数|字符|至少|必须|不能|不允许|禁止|至少|不少于|'
                        r'不得|6-20|\d+\s*[-~至到]\s*\d+|个字符|字母|数字|符号|'
                        r'大小写|开头|下划线|组合', t):
                    continue
                hint["raw_texts"].append(t[:120])
                # 长度区间：6-20位 / 8~16个字符 / 至少6位 / 最长20位
                m = _re.search(r'(\d+)\s*[-~至到]\s*(\d+)\s*[位个]', t)
                if m:
                    hint["length_min"] = int(m.group(1))
                    hint["length_max"] = int(m.group(2))
                    continue
                m = _re.search(r'至少\s*(\d+)\s*[位个]', t)
                if m and hint["length_min"] is None:
                    hint["length_min"] = int(m.group(1))
                    continue
                m = _re.search(r'最长\s*(\d+)\s*[位个]|不能超过\s*(\d+)', t)
                if m and hint["length_max"] is None:
                    hint["length_max"] = int(m.group(1) or m.group(2))
                    continue
                # 字符类要求
                for kw, name in (
                    ("数字", "digit"), ("大写", "upper"), ("小写", "lower"),
                    ("字母", "letter"), ("符号", "symbol"), ("特殊", "symbol"),
                    ("数字与字母", "digit+letter"), ("字母数字", "digit+letter"),
                    ("大小写", "upper+lower"), ("中文", "no_chinese"),
                    ("不能带有中文", "no_chinese"),
                ):
                    if kw in t:
                        if name not in hint["charset_hints"]:
                            hint["charset_hints"].append(name)
            self.my_logger.info(f"提示政策解析: {hint}")
        except Exception as exc:
            self.my_logger.debug(f"提示政策解析失败: {exc}")
        return hint

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
        initial_len = len(initial_password)
        # admissible_password（长度 initial_len）已被确认接受，故最小长度必然 ≤ initial_len。
        # 若 hi 越过 initial_len，二分会把「太长被拒」误判为「太短被拒」，
        # 一路顶到上界（如百度 max=14 时误报 min=32）。故 hi 截断到 initial_len。
        hi = min(min_interval[1], initial_len)

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

    def _read_password_maxlength(self):
        """读取密码输入框的 maxlength 属性，返回正整数上限或 None。

        仅读 HTML 属性，不填、不提交。用于佐证二分搜索测出的长度上限：
        区分「输入框强制截断、真实上限已知」与「网站不实时校验过长、
        二分一路顶到写死上界（此时真实上限未知）」。maxlength 是浏览器
        强制截断上限，是长度上限最权威的来源。
        """
        try:
            driver = self._driver or _get_shared_driver()
            el = driver.find_element(By.XPATH, self.password_xpath)
            ml = el.get_attribute("maxlength")
            if ml is not None and str(ml).strip() != "":
                ml = int(ml)
                if ml > 0:
                    return ml
            return None
        except Exception as exc:
            self.my_logger.debug(f"_read_password_maxlength: 读取失败 {exc}")
            return None

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
            accepted = self.test_one_password(modified_password)
            # ── 无上限早停（LinkedIn/Khan/Roblox 实测）──
            # 长度上探到 110+ 仍被接受 + 输入框无 maxlength 属性 → 站点
            # 几乎必然无真实上限（gitee 实测 max=102，真实站罕见 >110）。
            # 此时继续顶到 128 每探针 ~45s 需 15+ 分钟，提前确认 max=None
            # 省最后 2-3 轮。maxlength 属性是"强制截断上限"最权威来源。
            if accepted and mi >= 110:
                _ml = self._read_password_maxlength()
                if _ml is not None:
                    self.my_logger.info(
                        f"输入框 maxlength={_ml} 即为长度上限，提前结束二分")
                    return _ml
                self.my_logger.info(
                    f"长度上探到 {mi} 仍被接受且无 maxlength，判定无真实上限 (max=None)")
                return None
            if accepted:
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

        # 方案 A：长度上限不盲信二分结果。
        # 若二分顶到写死上界 max_interval[1]，说明在搜索范围内每一步都「看不到拒绝
        # 信号」——可能是输入框无 maxlength、且网站不实时校验「过长」（校验在提交时）。
        # 此时读输入框 maxlength 佐证：
        #   - 有 maxlength=N → 浏览器强制截断，N 即真实上限（可能 > 上界）；
        #   - 无 maxlength → 真实上限未知，标记 None（未检出），避免误报 128。
        if ret_max == max_interval[1]:
            maxlength = self._read_password_maxlength()
            if maxlength:
                self.my_logger.warning(
                    f"二分顶到上界 {max_interval[1]}，但输入框 maxlength={maxlength}，"
                    f"以 maxlength 作为真实上限")
                ret_max = maxlength
            else:
                self.my_logger.warning(
                    f"二分顶到上界 {max_interval[1]}，且输入框无 maxlength 佐证，"
                    f"网站可能不实时校验「过长」，真实上限未检出（max=None）")
                ret_max = None

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
        # TODO 1.0 generated password with admissible password (方案 B)
        # 字符替换测试（Unicode/emoji/空格/特殊符号）只关心「字符类型是否被接受」，
        # 与密码长度无关。改用 admissible_password 本身，避免超长密码（如 max=128）
        # 叠加 Unicode 字符导致浏览器崩溃（invalid session id）。
        len_ap = len(self.admissible_password)
        initial_password = self.admissible_password
        self.my_logger.info(
            f"Generating the permissive-char test password (len={len_ap}): {initial_password}.")
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
            try:
                allowed = self.test_one_password(mp_uni, "[Unicode] Testing the unicode password")
            except BrowserDeadError:
                raise  # 浏览器已死，短路整个测量，不做无用重试
            except Exception as exc:
                self.my_logger.warning(
                    f"[Unicode] 单个字符测试异常，按「不允许」跳过: {mp_uni} "
                    f"({type(exc).__name__}: {exc})")
                allowed = False
            if allowed:
                uni_flag = True
                self.my_logger.success(f"[Unicode] Testing permitted character: {mp_uni} is allowed.")
            else:
                self.my_logger.warning(f"[Unicode] Testing permitted character: {mp_uni} is not allowed.")
        if uni_flag:
            ret_dict["p_unicd"] = True

        # emoji 不再测试：键盘模拟无法可靠输入 emoji（非键盘字符），且无测量意义。
        # p_emoji 保持默认 False。

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
                # p_br means "the site blocks breached passwords".  One
                # accepted breached password is sufficient to disprove that
                # property, so keep False and stop probing.
                ret_dict["p_br"] = False
                break
            consecutive_rejected += 1
            if consecutive_rejected >= MAX_REJECTED_SAMPLE:
                ret_dict["p_br"] = True
                self.my_logger.info(
                    f"{MAX_REJECTED_SAMPLE} 条泄露密码均被拒绝，判定该网站拒绝泄露密码（停止遍历）")
                break
        return ret_dict
