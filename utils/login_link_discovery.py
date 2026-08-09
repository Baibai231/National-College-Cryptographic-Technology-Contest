"""
login_link_discovery.py

通过 CDP (Chrome DevTools Protocol) 注入 LoginFormExploration 的
Fathom JS 代码，并在 Selenium 控制的浏览器中执行表单检测。

关键：使用 CDP Runtime.evaluate 而非 Selenium execute_script()，
      避免后者在动态 DOM 页面上触发 StaleElementReferenceException。
"""

import os
import time
from typing import List, Dict, Optional, Tuple

from loguru import logger


class LoginLinkDiscovery:
    """通过 CDP 注入 + Fathom ML 检测注册表单"""

    _addons_dir: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), "js")

    def __init__(self, driver):
        self.driver = driver
        self._injected = False
        self._cached_fields = {}  # 缓存检测结果

    # ------------------------------------------------------------------
    # CDP 工具方法
    # ------------------------------------------------------------------

    def _cdp_eval(self, expression: str):
        """通过 CDP Runtime.evaluate 执行 JS 并直接返回 JSON 值

        绕过 Selenium execute_script() 的返回值转换（后者在遍历
        返回值对象时会为 DOM 引用创建 WebElement，导致 stale element）。
        """
        result = self.driver.execute_cdp_cmd('Runtime.evaluate', {
            'expression': expression,
            'returnByValue': True,
        })
        if 'exceptionDetails' in result:
            err = result['exceptionDetails']
            raise Exception(
                f"JS error: {err.get('text', '')} "
                f"at line {err.get('lineNumber', '?')}"
            )
        return result['result'].get('value')

    # ------------------------------------------------------------------
    # JS 注入
    # ------------------------------------------------------------------

    def _read_js(self, filename: str) -> str:
        path = os.path.join(self._addons_dir, filename)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"JS file not found: {path}")
        with open(path, "r", encoding="utf-8") as fp:
            return fp.read()

    def inject(self) -> None:
        """通过 CDP 注册脚本（每个新页面自动在全局作用域执行）"""
        if self._injected:
            return
        for name in ["scripts.js", "form_detection_addons.js"]:
            js = self._read_js(name)
            self.driver.execute_cdp_cmd(
                'Page.addScriptToEvaluateOnNewDocument',
                {'source': js}
            )
            logger.debug(f"{name} registered via CDP")
        self._injected = True

    def check_injected(self) -> bool:
        """验证关键函数是否已注入"""
        try:
            return self._cdp_eval("typeof ruleset") == "function"
        except Exception:
            return False

    def _wait_for_page_ready(self, timeout: float = 15) -> None:
        """等待页面 document.readyState === 'complete'，超时则不等"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                state = self.driver.execute_script("return document.readyState")
                if state == "complete":
                    return
            except Exception:
                pass
            time.sleep(0.5)
        logger.debug(f"页面加载等待超时 ({timeout}s)")

    # ------------------------------------------------------------------
    # 表单字段检测（Fathom ML）
    # ------------------------------------------------------------------

    def detect_email_inputs(self) -> List[Dict]:
        """Fathom ML 检测邮箱字段"""
        return self._cdp_eval(
            "(typeof detectEmailInputs === 'function')"
            " ? detectEmailInputs(document) : []"
        )

    def find_password_fields(self) -> List[str]:
        """查找可见密码字段的 XPath"""
        return self._cdp_eval(
            "var pwds = document.querySelectorAll('input[type=password]');"
            "var r = [];"
            "for (var i = 0; i < pwds.length; i++) {"
            "  if (pwds[i].offsetHeight > 0 && !pwds[i].disabled) {"
            "    r.push(typeof getXPath === 'function' ? getXPath(pwds[i]) : gPt(pwds[i]));"
            "  }"
            "}"
            "r"
        )

    # ------------------------------------------------------------------
    # 注册页面发现
    # ------------------------------------------------------------------

    # 常见注册页面 URL 模式（按使用频率排序）
    _SIGNUP_URL_PATTERNS = [
        '/signup',
        '/register',
        '/join',
        '/sign-up',
        '/sign_up',
        '/create-account',
        '/get-started',
        '/registration',
        '/create_account',
        '/accounts/emailsignup',
        '/accounts/signup',
        '/i/flow/signup',           # Twitter / X
        '/start',
        '/try',
    ]

    # 注册关键词（多语言，含现代 SPA 用法）
    _SIGNUP_KEYWORDS = [
        # 英文
        'sign up', 'signup', 'sign-up',
        'register', 'registration',
        'create account', 'create new account', 'new account',
        'join', 'join now', 'join free',
        'get started', 'get started free',
        'try', 'try free', 'try for free',
        'start', 'start free', 'start for free',
        'continue', 'continue with email',
        # 中文
        '注册', '新账户', '创建新账户', '立即注册', '免费注册',
        '註冊', '建立帳戶',
        # 日文
        '登録', '新規登録', '無料登録', 'アカウント作成',
        # 韩文
        '가입', '회원가입',
        # 其他
        'new account', 'crée', 'cadastr', 'inschrijving',
        'zarejestruj', 'Создать', 'inscr', 'registr',
    ]

    def navigate_to_signup(self, homepage_url: str) -> Optional[str]:
        """发现注册页面 URL

        四层回退策略：
        1. CDP 注入 → getLoginLinkAttrs() 获取链接 → 点击导航
        2. 尝试常见注册 URL 模式（base + /signup, /register 等）
        3. 检测首页本身是否就是注册页（有 email+password 字段）
        4. 全部失败返回 None

        通过 CDP 注入 Fathom JS，从首页 DOM 中匹配登录/注册链接并点击导航。
        支持正则匹配（精确/宽松）和坐标位置启发式搜索。
        """
        base = homepage_url.rstrip('/')
        self.inject()

        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        # ================================================================
        # 第 1 层：CDP 链接发现 + 点击导航
        # ================================================================
        logger.info("CDP 链接发现...")
        for load_attempt in range(2):
            try:
                self.driver.get(homepage_url)
            except Exception:
                pass
            self._wait_for_page_ready(timeout=15)
            if self.check_injected():
                break
            logger.info(f"JS 未注入，尝试重新加载 ({load_attempt + 1}/2)")
        else:
            logger.warning("JS 未注入，跳过链接发现")
            # 不直接返回 — 继续尝试 URL 模式回退
            # 但需要确保至少页面已加载
            try:
                self.driver.get(homepage_url)
                self._wait_for_page_ready(timeout=10)
            except Exception:
                pass

        links = self._cdp_eval("getLoginLinkAttrs()") if self.check_injected() else []
        logger.info(f"发现 {len(links) if links else 0} 个链接")

        if links:
            signup_kw = self._SIGNUP_KEYWORDS

            def is_signup(l):
                t = (l.get('innerText', '') or '').lower()
                h = (l.get('href', '') or '').lower()
                aid = (l.get('ariaLabel', '') or '').lower()
                tid = (l.get('dataTestid', '') or '').lower()
                combined = t + ' ' + h + ' ' + aid + ' ' + tid
                return any(kw in combined for kw in signup_kw)

            sorted_links = [l for l in links if is_signup(l)] + \
                           [l for l in links if not is_signup(l)]

            logger.info(f"注册关键词匹配: {len([l for l in links if is_signup(l)])}/{len(links)}")

            # 统计已尝试的点击次数，连续失败 3 次后提前退出
            click_attempts = 0
            consecutive_no_nav = 0

            for idx, link in enumerate(sorted_links[:10]):
                xpath = link.get('xpath', '')
                text = (link.get('innerText', '') or '')[:60].replace('\n', ' ')
                href_val = (link.get('href', '') or '')
                tag_name = (link.get('tagName', '') or '').upper()

                if not xpath:
                    logger.debug(f"[{idx}] 跳过 (无 xpath): {text}")
                    continue

                # 过滤不可点击元素：只点击有 href 的链接、<button>、和 <a> 标签
                is_clickable = bool(href_val) or tag_name in ('A', 'BUTTON')
                if not is_clickable:
                    logger.debug(f"[{idx}] 跳过 (不可点击 <{tag_name}>): {text}")
                    continue

                try:
                    el = self.driver.find_element(By.XPATH, xpath)
                    if not el.is_displayed():
                        logger.debug(f"[{idx}] 跳过 (不可见): {text}")
                        continue
                    old = self.driver.current_url

                    # 点击：优先 Selenium，失败回退到 JS click
                    try:
                        el.click()
                    except Exception:
                        try:
                            self.driver.execute_script("arguments[0].click();", el)
                        except Exception:
                            logger.debug(f"[{idx}] click 失败: {text}")
                            continue

                    click_attempts += 1

                    # 等待 URL 变化（动态等待，最长 3 秒）
                    try:
                        WebDriverWait(self.driver, 3).until(
                            lambda d: d.current_url != old
                        )
                        new = self.driver.current_url
                    except Exception:
                        new = old

                    if new != old and new != homepage_url:
                        logger.info(f"导航: -> {new}")
                        self._wait_for_spa_render()
                        return new
                    else:
                        consecutive_no_nav += 1
                        logger.debug(f"[{idx}] URL 未变化: {text}")
                        # 连续 3 个可点击元素都未导航 → 提前退出
                        if consecutive_no_nav >= 3:
                            logger.debug("连续 3 个链接均未导航，提前退出")
                            break
                except Exception as e:
                    logger.debug(f"[{idx}] 异常: {type(e).__name__}: {e}")
                    continue

        # ================================================================
        # 第 2 层：尝试常见注册 URL 模式
        # ================================================================
        logger.info("尝试 URL 模式回退...")
        from urllib.parse import urljoin
        import urllib3
        urllib3.disable_warnings()

        tried_urls = set()
        for pattern in self._SIGNUP_URL_PATTERNS:
            candidate = urljoin(base + '/', pattern)  # urljoin 自动处理路径
            if candidate in tried_urls:
                continue
            tried_urls.add(candidate)

            try:
                self.driver.get(candidate)
                self._wait_for_page_ready(timeout=8)

                # 快速检查：页面是否有密码字段
                pwds = self.find_password_fields()
                if pwds:
                    logger.info(f"URL 模式命中: -> {candidate}")
                    self._wait_for_spa_render()
                    return candidate

                # 检查是否有邮箱输入框
                emails = self.detect_email_inputs()
                if emails:
                    logger.info(f"URL 模式命中 (仅邮箱): -> {candidate}")
                    self._wait_for_spa_render()
                    return candidate
            except Exception as e:
                logger.debug(f"URL 模式 {candidate} 失败: {e}")
                continue

        # ================================================================
        # 第 3 层：检测首页是否本身就是注册页
        # ================================================================
        logger.info("检测首页是否为注册页...")
        try:
            self.driver.get(homepage_url)
            self._wait_for_page_ready(timeout=10)
        except Exception:
            pass

        # 检查是否有密码字段（注册页通常有密码框）
        pwds = self.find_password_fields()
        emails = self.detect_email_inputs()

        if pwds and emails:
            logger.info(f"首页即为注册页: {homepage_url}")
            self._wait_for_spa_render()
            return homepage_url
        elif pwds:
            # 只有密码字段 — 可能是登录页，但仍值得尝试
            logger.info(f"首页含密码字段（可能为登录/注册混合页）: {homepage_url}")
            self._wait_for_spa_render()
            return homepage_url

        # ================================================================
        # 第 4 层：全部失败
        # ================================================================
        logger.warning("所有注册页面发现策略均失败")
        return None

    def find_signup_fields(self) -> Tuple[Optional[str], Optional[str]]:
        """在当前页面（含所有 iframe）用 Fathom 检测邮箱和密码字段

        优先使用跨 frame 搜索；如果失败则回退到仅搜索主页面。
        """
        # 优先：跨 frame 搜索
        try:
            email_xpath, password_xpath = self._find_signup_fields_in_frames()
            if email_xpath or password_xpath:
                self._cached_fields = {
                    'email_xpath': email_xpath,
                    'password_xpath': password_xpath
                }
                return email_xpath, password_xpath
        except Exception as e:
            logger.warning(f"跨 frame 搜索失败: {e}")

        # 回退：仅搜索主页面
        email_xpath = None
        password_xpath = None

        try:
            emails = self.detect_email_inputs()
            if emails:
                email_xpath = emails[0].get('xpath')
                logger.info(f"邮箱: {email_xpath} (score={emails[0].get('score')})")
        except Exception as e:
            logger.warning(f"邮箱检测失败: {e}")

        try:
            pwds = self.find_password_fields()
            if pwds:
                password_xpath = pwds[0]
                logger.info(f"密码: {password_xpath}")
        except Exception as e:
            logger.warning(f"密码检测失败: {e}")

        self._cached_fields = {
            'email_xpath': email_xpath,
            'password_xpath': password_xpath
        }
        return email_xpath, password_xpath

    def _find_signup_fields_in_frames(self) -> Tuple[Optional[str], Optional[str]]:
        """递归搜索主页及所有 iframe 中的邮箱和密码字段

        调用 JS 函数 detectFieldsInAllFrames(document)，
        遍历主 frame 和所有可访问的子 iframe，
        返回找到的第一对 (email_xpath, password_xpath)。
        """
        if not self.check_injected():
            logger.warning("JS 未注入，无法跨 frame 搜索")
            return None, None

        results = self._cdp_eval(
            "(typeof detectFieldsInAllFrames === 'function')"
            " ? detectFieldsInAllFrames(document) : []"
        )

        if not results or len(results) == 0:
            logger.info("跨 frame 搜索：未找到任何字段")
            return None, None

        logger.info(f"跨 frame 搜索：{len(results)} 个 frame 中有字段")

        # 优先返回同时有 email 和 password 的结果
        for frame_result in results:
            emails = frame_result.get('emailFields', [])
            pwds = frame_result.get('passwordFields', [])
            frame_url = frame_result.get('frameUrl', '(unknown)')
            if emails and pwds:
                ex = emails[0].get('xpath') if isinstance(emails[0], dict) else emails[0]
                px = pwds[0]
                logger.info(f"iframe 命中 ({frame_url}): email={ex}, pwd={px}")
                return ex, px

        # 其次：至少找到密码字段
        for frame_result in results:
            pwds = frame_result.get('passwordFields', [])
            frame_url = frame_result.get('frameUrl', '(unknown)')
            if pwds:
                px = pwds[0]
                logger.info(f"iframe 部分命中 ({frame_url}): pwd={px}")
                return None, px

        return None, None

    def _wait_for_spa_render(self, timeout: float = 5) -> None:
        """等待 SPA (React/Vue) 页面完成客户端渲染

        document.readyState === 'complete' 只表示 HTML 加载完毕，
        React/Vue 组件可能还在挂载。此方法轮询是否有可见的 input 元素出现。
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                result = self._cdp_eval(
                    "var inputs = document.querySelectorAll("
                    "  'input[type=password]:not([disabled]), "
                    "  input[type=email]:not([disabled]), "
                    "  input[name*=email i]:not([disabled]), "
                    "  input[name*=mail i]:not([disabled])'"
                    ");"
                    "for (var i = 0; i < inputs.length; i++) {"
                    "  if (inputs[i].offsetHeight > 0) return true;"
                    "}"
                    "return false;"
                )
                if result:
                    return
            except Exception:
                pass
            time.sleep(0.3)
        logger.debug(f"SPA 渲染等待超时 ({timeout}s)")

    def ensure_scripts(self) -> None:
        """兼容旧接口"""
        pass
