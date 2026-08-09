#!/usr/bin/python

from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options as COptions
from selenium.webdriver.chrome.service import Service as CService
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from ..APDriver import APDriver

from uuid import uuid4
from pyvirtualdisplay import Display
import os
import json
import stat


def _find_real_chromedriver(driver_path):
    """webdriver-manager 4.x 存在 bug：当解压目录同时存在
    THIRD_PARTY_NOTICES.chromedriver（文本）和 chromedriver（真正的二进制）时，
    install() 可能返回前者，导致 Selenium 启动报 Exec format error。
    这里校验返回的路径，无效时在本地 .wdm 缓存中搜索真正的 chromedriver。
    同时保证二进制拥有可执行权限。Windows/Linux/macOS 通用。
    """
    def is_real_binary(p):
        if not p or not os.path.isfile(p):
            return False
        if os.path.basename(p) != "chromedriver":
            return False
        try:
            with open(p, "rb") as fh:
                magic = fh.read(4)
        except OSError:
            return False
        if magic[:2] == b"\x7f\x45":      # ELF (Linux)
            return True
        if magic[:4] == b"\xcf\xfa\xed\xfe":  # Mach-O (macOS)
            return True
        if magic[:2] == b"MZ":            # PE (Windows)
            return True
        return False

    if is_real_binary(driver_path):
        return driver_path

    candidates = []
    wdm_root = os.path.join(os.path.expanduser("~"), ".wdm", "drivers", "chromedriver")
    if os.path.isdir(wdm_root):
        for root, dirs, files in os.walk(wdm_root):
            for f in files:
                if f == "chromedriver":
                    candidates.append(os.path.join(root, f))
    for c in sorted(candidates, key=os.path.getsize, reverse=True):
        if is_real_binary(c):
            st = os.stat(c)
            if not (st.st_mode & stat.S_IXUSR):
                os.chmod(c, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            return c
    return driver_path


class CAPDriver(APDriver):
    _caller_prefix = "CAPDriver"
    _abs_path = os.path.dirname(os.path.abspath(__file__))
    _exec_path = os.path.join(_abs_path, "config/webdrivers/chromedriver")

    _abs_profiles_path = "/tmp"

    _arg_mappings = {
        "no_ssl_errors": ["--ignore-certificate-errors"],
        "disable_notifications": ["--disable-notifications"],
        "maximized": ["--start-maximized"],
        "no_default_browser_check": ["--no-default-browser-check"],
        "disable_cache": ["--disk-cache-dir=/dev/null", "--disk-cache-size=1"],
        "headless": ["--headless"]
    }

    _recoverable_crashes = ["chrome not reachable", "page crash"]

    def __init__(self, **kwargs):
        _chromeOpts = COptions()
        # _chromeOpts.add_argument("--headless")
        _chromeOpts.add_argument("--no-sandbox")
        _chromeOpts.add_argument("--enable-logging")
        _chromeOpts.add_argument("--disable-dev-shm-usage")
        _chromeOpts.add_argument("--enable-logging=stderr --v=1")
        _chromeOpts.add_argument("--start-maximized")
        _chromeOpts.add_argument("--disable--gpu")
        # --- 反自动化检测 (anti-bot) ---
        _chromeOpts.add_argument("--disable-blink-features=AutomationControlled")
        _chromeOpts.add_experimental_option("excludeSwitches", ["enable-automation"])
        _chromeOpts.add_experimental_option("useAutomationExtension", False)
        # --- CMP 弹窗处理 ---
        # _chromeOpts.add_argument("--disable-extensions")         # We need the Consent-O-Matic.crx to handle the pop-up windows
        _chromeOpts.add_extension(os.path.join(CAPDriver._abs_path, "..", "Extensions", "Consent-O-Matic.crx"))
        _chromeOpts.add_argument("--ignore-certificate-errors")
        _chromeOpts.add_argument("--lang=en")
        _chromeOpts.set_capability("goog:loggingPrefs", {"performance": "ALL"})
        _chromeOpts.add_experimental_option("perfLoggingPrefs", {"enableNetwork": True})

        if CAPDriver._base_config["browser"]["enabled"]:
            for option in CAPDriver._base_config["browser"]:
                if CAPDriver._base_config["browser"][option]:
                    for arg in CAPDriver._arg_mappings.get(option, []):
                        _chromeOpts.add_argument(arg)

        # Use ready-made profile or generate a new one
        # self._profile = CAPDriver._base_config["browser"].get("profile")
        # if not self._profile:
        #     self._profile = os.path.join(self._abs_profiles_path, "xdriver-%s" % str(uuid4()))
        #     CAPDriver._base_config["browser"]["profile"] = self._profile  # Will be used if browser is rebooted
        #
        # # Logger.spit("Setting custom profile to: %s" % self._profile, caller_prefix=CXDriver._caller_prefix)
        # _chromeOpts.add_argument("--user-data-dir=%s" % self._profile)
        # _chromeOpts.add_argument("--load-extension=" + self._current_user_directory + "/" + self._consent_o_matic_ext_path)

        self._proxy = None

        # By default, output instance to the environment `DISPLAY` (can be already set)
        os.environ['DISPLAY'] = os.environ.get('DISPLAY', ':0')
        self._virtual_display = None
        # Start virtual display, if instructed and only if not headless
        if not CAPDriver._base_config["browser"]["headless"] and CAPDriver._base_config["browser"]["virtual"]:
            self._virtual_display = Display(visible=0, size=(1920, 1080))
            self._virtual_display.start()

        # Check whether selenium is in headless mode
        all_arguments = _chromeOpts.to_capabilities()["goog:chromeOptions"]["args"]
        if "--headless" in all_arguments:
            import pyautogui
            window_height = int(pyautogui.size().height / 2)
            window_width = int(pyautogui.size().width / 2)
            _chromeOpts.add_argument(f"--window-size={window_width}x{window_height}")
            # _chromeOpts.add_argument(f"--window-size=1920x1080")
        _chromeOpts.set_capability("goog:loggingPrefs", {"performance": "ALL"})
        super(CAPDriver, self).__init__(
            service=CService(_find_real_chromedriver(ChromeDriverManager().install())),
            options=_chromeOpts,
            **kwargs)
        # super(CXDriver, self).__init__(executable_path=self._exec_path, chrome_options=_chromeOpts, **kwargs)  # Launch!
        self.add_script(
            CAPDriver._base_config["ap_driver"]["scripts"])  # Add scripts to be evaluated on each new document

        # --- 注入反自动化检测脚本 (notABot.js) ---
        _notabot_path = os.path.join(os.path.dirname(CAPDriver._abs_path), "js", "notABot.js")
        if os.path.isfile(_notabot_path):
            with open(_notabot_path, "r", encoding="utf-8") as _f:
                self.add_script(_f.read())

        # --- 注入 CMP 检测脚本 (cmpDetect.js) ---
        _cmpdetect_path = os.path.join(os.path.dirname(CAPDriver._abs_path), "js", "cmpDetect.js")
        if os.path.isfile(_cmpdetect_path):
            with open(_cmpdetect_path, "r", encoding="utf-8") as _f:
                self.add_script(_f.read())

        # --- 注入 form_detection_addons.js ---
        _addons_path = os.path.join(os.path.dirname(CAPDriver._abs_path), "js", "form_detection_addons.js")
        if os.path.isfile(_addons_path):
            with open(_addons_path, "r", encoding="utf-8") as _f:
                self.add_script(_f.read())

    # Kudos: https://stackoverflow.com/a/47298910 + black widow (https://www.cse.chalmers.se/research/group/security/black-widow/)
    def send(self, cmd, params=None):
        if params is None:
            params = {}
        resource = "/session/%s/chromium/send_command_and_get_result" % self.session_id
        url = self.command_executor._url + resource
        body = json.dumps({'cmd': cmd, 'params': params})
        response = self.command_executor._request('POST', url, body)
        return response

    def add_script(self, script):
        return self.send("Page.addScriptToEvaluateOnNewDocument", {"source": script})

    def _switch_to_window(self, window_handle):
        super(CAPDriver, self)._switch_to_window(window_handle)
        # Page.addScriptToEvaluateOnNewDocument does *not* run on new windows -- Workaround to fix this
        self.add_script(CAPDriver._base_config["xdriver"]["scripts"])
        self.refresh()
