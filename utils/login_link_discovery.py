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
        self._entry_clicked = False  # navigate_to_signup 是否点击了入口链接

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
            exc_text = err.get('exception', {}).get('description', '')
            raise Exception(
                f"JS error: {err.get('text', '')} "
                f"at line {err.get('lineNumber', '?')} "
                f"{str(exc_text)[:200]}"
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
        """Fathom ML 检测邮箱字段

        对 JS 异常容错：URL 模式探测经常落到 404 页，Fathom 在这些
        页面上可能抛 Uncaught 异常（51cto 实测）；404 页没有邮箱字段
        是正常情况，不应让 JS 错误中断整个注册页发现流程。
        """
        try:
            return self._cdp_eval(
                "(typeof detectEmailInputs === 'function')"
                " ? detectEmailInputs(document) : []"
            )
        except Exception as exc:
            logger.debug(f"detect_email_inputs JS 异常: {type(exc).__name__}: {exc}")
            return []

    def find_password_fields(self) -> List[str]:
        """查找可见密码字段的 XPath（含 Shadow DOM 穿透搜索）

        使用完整的可见性检查（getBoundingClientRect + getComputedStyle），
        而非仅 offsetHeight。后者无法过滤 visibility:hidden 或 opacity:0
        的元素，导致 SPA 模态框切换 tab 后仍返回隐藏的登录表单密码字段。
        """
        try:
            return self._cdp_eval("""
(function() {
    var r = [];
    var seen = new WeakSet();
    var SELECTORS = [
        'input[type=password]',
        'input[autocomplete=new-password]',
        'input[autocomplete=current-password]',
        'input[name*=password i]',
        'input[name*=passwd i]',
        'input[name*=pwd i]'
    ];

    function _isTrulyVisible(el) {
        if (!el || el.disabled) return false;
        var rect = el.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) return false;
        var style = getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
        if (parseFloat(style.opacity) === 0) return false;
        // 检查祖先可见性
        var ancestor = el.parentElement;
        while (ancestor) {
            try {
                var as = getComputedStyle(ancestor);
                if (as.display === 'none' || as.visibility === 'hidden') return false;
            } catch(e) { break; }
            ancestor = ancestor.parentElement;
        }
        return true;
    }

    function searchRoot(root) {
        if (!root || !root.querySelectorAll) return;
        for (var s = 0; s < SELECTORS.length; s++) {
            try {
                var nodes = root.querySelectorAll(SELECTORS[s]);
                for (var i = 0; i < nodes.length; i++) {
                    var el = nodes[i];
                    if (seen.has(el)) continue;
                    seen.add(el);
                    if (_isTrulyVisible(el)) {
                        r.push(typeof getXPath === 'function' ? getXPath(el) : (typeof gPt === 'function' ? gPt(el) : ''));
                    }
                }
            } catch(e) {}
        }
    }

    // 收集所有 Shadow DOM roots
    var roots = [document];
    for (var ri = 0; ri < roots.length && ri < 200; ri++) {
        searchRoot(roots[ri]);
        try {
            var all = roots[ri].querySelectorAll('*');
            for (var j = 0; j < all.length; j++) {
                if (all[j].shadowRoot && roots.indexOf(all[j].shadowRoot) === -1) {
                    roots.push(all[j].shadowRoot);
                }
            }
        } catch(e) {}
    }

    return r;
})();
        """)
        except Exception as exc:
            # 404/SPA 兜底页上 JS 可能抛 Uncaught（51cto 实测），
            # 没有密码字段是正常情况，不应中断流程。
            logger.debug(f"find_password_fields JS 异常: {type(exc).__name__}: {exc}")
            return []

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
        # 第 0 层：Selenium 可信点击入口检测（对齐 MyAutomaticPolicy）
        # ================================================================
        # Chinese SPA 站点（juejin.cn 等）的 React 事件处理器只响应
        # 浏览器原生信任的点击事件，CDP dispatchEvent 合成事件无效。
        # 先用 detect_entry_button + safe_click_entry 尝试可信点击，
        # 失败再回退到 CDP 链接发现。
        try:
            from signup_flow_classifier.navigator import (
                detect_entry_button, safe_click_entry, page_fingerprint,
            )

            entry_target = detect_entry_button(
                self.driver, "register", allow_fallback=False)
            if entry_target is not None:
                logger.info("第 0 层（Selenium 可信点击）检测到注册入口")
                old_fp = page_fingerprint(self.driver)
                entry_outcome = safe_click_entry(
                    self.driver, "register", allow_fallback=False)
                if entry_outcome.clicked:
                    self._wait_for_spa_render(timeout=3)
                    # 检查是否到达密码字段
                    pwds = self.find_password_fields()
                    if pwds:
                        self._entry_clicked = True
                        logger.info(
                            "第 0 层成功：Selenium 可信点击到达密码字段")
                        self._try_switch_to_signup_tab()
                        return self.driver.current_url
                    # 检查是否有 URL 导航
                    new_url = self.driver.current_url.rstrip("/")
                    if new_url != base:
                        self._entry_clicked = True
                        logger.info(f"第 0 层成功：导航到 {new_url}")
                        return new_url
                    # 页面指纹变化 → SPA 弹窗（可能不含密码字段，
                    # 如 douban.com 的手机验证码注册弹窗）
                    # 不设 _entry_clicked：让分类器自行重新点击入口并分类
                    if page_fingerprint(self.driver) != old_fp:
                        logger.info("第 0 层：页面指纹变化（弹窗），让分类器自行判断")
                        self._try_switch_to_signup_tab()
                        return self.driver.current_url
                    logger.debug("第 0 层：点击成功但无密码字段/导航")
                else:
                    logger.debug(
                        f"第 0 层：未点击 ({entry_outcome.reason})")
        except Exception as e:
            logger.debug(f"第 0 层异常 (回退到 CDP): {type(e).__name__}: {e}")

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
            # 确保页面在顶部：部分站点页面加载后会自行滚动，
            # 导致顶部注册/登录入口被遮挡
            try:
                self.driver.execute_script("window.scrollTo(0, 0);")
            except Exception:
                pass
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

            # 按 JS 引擎 score 降序排列（signup 关键词额外加分确保最前）
            def link_priority(l):
                score = l.get('score', 0) or 0
                if is_signup(l):
                    score += 200
                return score

            sorted_links = sorted(links, key=link_priority, reverse=True)

            logger.info(f"注册关键词匹配: {len([l for l in links if is_signup(l)])}/{len(links)}")

            # 统计已尝试的点击次数，连续失败 3 次后提前退出
            click_attempts = 0
            consecutive_no_nav = 0
            # 链接点击层总时间预算：tryClickAndDetect 每个链接最多轮询 5 秒，
            # 10 个链接全不命中最坏 50 秒；限制总预算避免卡死（脉脉实测）。
            click_budget_deadline = time.time() + 25

            for idx, link in enumerate(sorted_links[:10]):
                if time.time() > click_budget_deadline:
                    logger.debug("链接点击层达到时间预算，退出")
                    break
                xpath = link.get('xpath', '')
                text = (link.get('innerText', '') or '')[:60].replace('\n', ' ')
                score = link.get('score', 0) or 0

                if not xpath:
                    logger.debug(f"[{idx}] 跳过 (无 xpath): {text}")
                    continue

                # ── 排除页脚备案/版权链接 ──
                # 京公网安备/ICP 备案链接文本或 href 含备案关键词（douyin
                # 首页实测被 CDP 链接发现误点，导航到 /jingxuan 视频页）。
                # 备案链接不是认证入口，必须在关键词匹配之前排除。
                _record_text = (text or "").lower()
                _record_href = (link.get('href', '') or '').lower()
                if ("备案" in _record_text or "公网安备" in _record_text
                        or "copyright" in _record_text
                        or "beian" in _record_href
                        or "mps.gov.cn" in _record_href
                        or "beian.gov.cn" in _record_href
                        or "police" in _record_href and "register" in _record_href):
                    logger.debug(f"[{idx}] 跳过备案/版权链接: {text}")
                    continue

                # ── 排除机构/企业/商家注册路线 ──
                # 与 navigator.detect_entry_button 的 _is_organizational_signup 一致；
                # 避免把"注册机构号"（zhihu /org/signup 等）当成普通用户注册入口。
                try:
                    from urllib.parse import urljoin
                    from signup_flow_classifier.navigator import (
                        _is_organizational_signup,
                    )
                    link_href = link.get('href', '') or ''
                    target_url = urljoin(
                        self.driver.current_url, link_href) if link_href else ""
                    if target_url and _is_organizational_signup(target_url):
                        logger.debug(
                            f"[{idx}] 跳过机构/企业注册链接: {text} -> {target_url[:60]}")
                        continue
                except Exception:
                    pass

                # ── CDP 原生点击 + 异步轮询 ──
                # tryClickAndDetect() 完全在 JS 上下文中执行：
                #   1. document.evaluate(xpath) 查找元素
                #   2. 完整鼠标事件序列 (mouseover→mousedown→mouseup→click)
                #      全部 bubbles:true，穿透 React 合成事件委托
                #   3. setTimeout 轮询（不阻塞事件循环）检测：
                #      a) URL 是否变化（Selenium 导航）
                #      b) 密码字段是否出现（SPA 模态框）
                # 返回 Promise，CDP awaitPromise:true 等待完成。
                old_fp = self._page_fingerprint()
                try:
                    xpath_escaped = xpath.replace('\\', '\\\\').replace("'", "\\'")
                    cdp_result = self.driver.execute_cdp_cmd('Runtime.evaluate', {
                        'expression': (
                            "typeof tryClickAndDetect === 'function'"
                            " ? tryClickAndDetect('" + xpath_escaped + "', 5000)"
                            " : Promise.resolve({clicked:false, navigated:false,"
                            "   newUrl:'', hasPassword:false, passwordXpath:''})"
                        ),
                        'returnByValue': True,
                        'awaitPromise': True,
                    })
                    click_result = (cdp_result.get('result') or {}).get('value') or {}
                except Exception as e:
                    logger.debug(f"[{idx}] CDP click 异常: {type(e).__name__}: {e}")
                    consecutive_no_nav += 1
                    if consecutive_no_nav >= 3:
                        logger.debug("连续 3 个链接均未导航，提前退出")
                        break
                    continue

                if not click_result.get('clicked'):
                    logger.debug(f"[{idx}] 未找到或不可见: {text}")
                    continue

                click_attempts += 1

                # ── 结果处理 ──
                if click_result.get('navigated'):
                    new = click_result.get('newUrl', '')
                    if new and new != homepage_url:
                        if not self._is_same_site(homepage_url, new):
                            logger.debug(f"[{idx}] 跨站链接，跳过: -> {new}")
                            self.driver.get(homepage_url)
                            consecutive_no_nav += 1
                            continue
                        logger.info(f"导航: -> {new}")
                        self._entry_clicked = True
                        self._wait_for_spa_render()
                        return new

                if click_result.get('hasPassword'):
                    logger.info(
                        f"[{idx}] SPA 模态框检测到密码字段 (CDP): "
                        f"{click_result.get('passwordXpath', '')}")
                    # 检测是否为登录 tab，尝试切换到注册 tab
                    self._entry_clicked = True
                    self._try_switch_to_signup_tab()
                    return self.driver.current_url

                # ── 指纹变化检测 (page_fingerprint) ──
                # tryClickAndDetect 的 setTimeout 轮询只检测 URL 变化和密码字段，
                # 无法感知「弹窗打开了但默认是 SMS/QR 视图」的情况。
                # 用轻量指纹（可见 input + button + dialog 等）补充判断。
                if old_fp and self._page_fingerprint() != old_fp:
                    logger.info(
                        f"[{idx}] 页面指纹变化 (CDP 未检测到密码字段但页面已变): "
                        f"\"{text}\"")
                    self._entry_clicked = True
                    return self.driver.current_url

                # ── CDP 合成事件无效 → 多层点击回退 ──
                # CDP dispatchEvent(MouseEvent) 对部分非 React 站点（如 juejin.cn）
                # 不触发实际的事件处理器。依次尝试：
                #   1. Selenium el.click() — 真实的浏览器点击
                #   2. JS execute_script click — 绕过覆盖层拦截
                old_fp = self._page_fingerprint()  # 也可能因 CDP 尝试已变化
                try:
                    el = self.driver.find_element(By.XPATH, xpath)
                    if el:
                        logger.debug(f"[{idx}] CDP 无效，尝试多层回退: {text}")
                        clicked = False
                        # 第 1 级：Selenium 原生点击
                        try:
                            el.click()
                            clicked = True
                        except Exception:
                            # 第 2 级：JS click 绕过覆盖层
                            try:
                                self.driver.execute_script(
                                    "arguments[0].click()", el)
                                clicked = True
                            except Exception:
                                pass
                        if clicked:
                            time.sleep(1.5)
                            new_url = self.driver.current_url
                            home_norm = homepage_url.rstrip('/')
                            new_norm = new_url.rstrip('/')
                            if new_norm != home_norm:
                                # 真正的 URL 变化（路径不同，不仅 trailing slash）
                                if not self._is_same_site(homepage_url, new_url):
                                    logger.debug(f"[{idx}] 回退点击跨站: -> {new_url}")
                                    self.driver.get(homepage_url)
                                else:
                                    logger.info(f"回退点击导航: -> {new_url}")
                                    self._entry_clicked = True
                                    self._wait_for_spa_render()
                                    return new_url
                            else:
                                # 同 URL — SPA 模态框可能已打开
                                pwds = self.find_password_fields()
                                if pwds:
                                    logger.info("回退点击检测到密码字段")
                                    self._entry_clicked = True
                                    self._try_switch_to_signup_tab()
                                    return self.driver.current_url
                                # 指纹变化检测（无密码字段但页面已变）
                                if old_fp and self._page_fingerprint() != old_fp:
                                    logger.info(
                                        f"[{idx}] 回退点击后指纹变化: \"{text}\"")
                                    self._entry_clicked = True
                                    return self.driver.current_url
                except Exception as _se:
                    logger.debug(f"多层回退失败: {type(_se).__name__}")

                # 既无导航也无密码字段
                consecutive_no_nav += 1
                logger.debug(f"[{idx}] 未触发: score={score} \"{text}\"")
                if consecutive_no_nav >= 3:
                    logger.debug("连续 3 个链接均未触发，提前退出")
                    break

        # ================================================================
        # 第 2 层：尝试常见注册 URL 模式
        # ================================================================
        logger.info("尝试 URL 模式回退...")
        from urllib.parse import urljoin
        import urllib3
        urllib3.disable_warnings()

        tried_urls = set()
        # 模式探测预算：只试前几个最常见模式（/signup、/register、/join）。
        # 全部 14 个模式都开真实浏览器会浪费几分钟（贴吧/脉脉等不支持
        # 常见模式的站点实测）；前缀顺序即按使用频率排列。
        pattern_budget = 3
        for pattern in self._SIGNUP_URL_PATTERNS:
            if pattern_budget <= 0:
                break
            candidate = urljoin(base + '/', pattern)  # urljoin 自动处理路径
            if candidate in tried_urls:
                continue
            tried_urls.add(candidate)
            pattern_budget -= 1

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

    def _try_switch_to_signup_tab(self) -> bool:
        """在已打开的 SPA 模态框中寻找并点击"注册"tab。

        部分站点（icourse163.org、xuetangx.com）的登录/注册模态框默认展示
        登录 tab。用户需要点击"去注册"/"立即注册"等标签才能切换到注册表单。
        此方法用 CDP 在页面中查找注册 tab 并点击切换。

        Returns:
            True  = 找到并点击了注册 tab，密码字段仍然可见
            False = 未找到注册 tab 或切换后密码字段消失
        """
        import time
        try:
            result = self.driver.execute_cdp_cmd('Runtime.evaluate', {
                'expression': '''
(function() {
    var KEYWORDS = [
        '注册', '去注册', '立即注册', '免费注册', '新用户注册',
        '註冊', '手机注册', '邮箱注册', '注册账号', '注册帐号',
        'sign up', 'signup', 'register', 'create account',
        'new account', 'create new account', 'get started'
    ];
    // 排除包含这些词的元素（即使命中关键词也是协议/政策文本）
    var EXCLUDE = [
        '同意', '协议', '政策', '隐私', '条款', '即表示', '视为',
        'agree', 'terms', 'policy', 'privacy', 'by clicking',
        'by registering', 'you agree', 'i agree', 'i have read'
    ];
    var TAGS = ['a', 'button', 'span', 'div', 'li', 'label'];

    function getVisibleText(el) {
        return (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
    }

    function isVisible(el) {
        var rect = el.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) return false;
        var style = getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
        if (parseFloat(style.opacity) === 0) return false;
        return true;
    }

    // 收集候选元素，按「更可能是注册 tab」偏好排序：
    //   - 文本精确匹配  >  文本包含且短  >  文本包含且长
    //   - 元素越小越优先（tab 通常是小标签）
    //   - 越靠近页面顶部越优先
    var candidates = [];

    function walk(node) {
        if (!node || !node.tagName) return;
        var tag = node.tagName.toLowerCase();
        if (TAGS.indexOf(tag) === -1) {
            if (node.children) {
                for (var i = 0; i < node.children.length; i++) walk(node.children[i]);
            }
            return;
        }
        if (!isVisible(node)) {
            if (node.children) {
                for (var i = 0; i < node.children.length; i++) walk(node.children[i]);
            }
            return;
        }
        // ── 先深入子元素（深度优先），再检查当前节点 ──
        // 确保叶子 tab（如 <span>去注册</span>）先于容器
        //（如 <div>手机登录 邮箱登录 去注册...</div>）被收集。
        // 短文本 + 高分叶子元素会自然排在容器前面。
        if (node.children && node.children.length > 0) {
            for (var i = 0; i < node.children.length; i++) walk(node.children[i]);
        }
        var text = getVisibleText(node).toLowerCase();
        if (text.length > 80) {
            // 文本过长（容器级），跳过（子元素已递归遍历）
            return;
        }
        // 排除协议/政策文本
        var excluded = false;
        for (var e = 0; e < EXCLUDE.length; e++) {
            if (text.indexOf(EXCLUDE[e].toLowerCase()) !== -1) {
                excluded = true; break;
            }
        }
        if (excluded) return;  // 子元素已递归遍历
        for (var k = 0; k < KEYWORDS.length; k++) {
            var kw = KEYWORDS[k].toLowerCase();
            if (text === kw || text.indexOf(kw) !== -1) {
                var rect = node.getBoundingClientRect();
                var area = rect.width * rect.height;
                // matchQuality: exact=2, partial=1（exact 得分更高）
                var matchQuality = (text === kw) ? 2 : 1;
                // 短文本奖励：tab 标签短小（"注册" 2字 > "注册即表示..." 长句）
                var shortBonus = (30 - Math.min(text.length, 30)) * 200;
                candidates.push({
                    el: node,
                    score: matchQuality * 500000 + shortBonus - area - rect.top,
                    text: getVisibleText(node).substring(0, 50)
                });
                // 不 return — 子元素已递归遍历，继续检查其他关键词
                break;
            }
        }
    }

    // 优先在模态框/弹窗内搜索
    var modalSelectors = [
        '[class*=modal i]', '[class*=dialog i]', '[class*=popup i]',
        '[class*=overlay i]', '[class*=panel i]', '[role=dialog]',
        '[role=alertdialog]', '[aria-modal=true]'
    ];
    var searchRoots = [];
    for (var s = 0; s < modalSelectors.length; s++) {
        try {
            var modals = document.querySelectorAll(modalSelectors[s]);
            for (var m = 0; m < modals.length; m++) {
                if (isVisible(modals[m])) searchRoots.push(modals[m]);
            }
        } catch(e) {}
    }
    if (searchRoots.length === 0) searchRoots.push(document.body);

    for (var r = 0; r < searchRoots.length; r++) walk(searchRoots[r]);

    if (candidates.length === 0) return {found: false};

    // 按 score 降序排列
    candidates.sort(function(a, b) { return b.score - a.score; });

    var best = candidates[0];
    // 标记元素供 Selenium 可信点击使用（不再用 CDP 合成事件，
    // Chinese SPA 站点的 React 事件处理器只响应可信点击）
    best.el.setAttribute('data-ap-signup-tab', '1');
    return {found: true, text: best.text};
})();
                ''',
                'returnByValue': True,
                'awaitPromise': True,
            })
            value = (result.get('result') or {}).get('value') or {}
            if value.get('found'):
                logger.info(f"切换到注册 tab: \"{value.get('text', '')}\"")

                # ── Selenium 可信点击（非 CDP 合成事件）──
                # Chinese SPA 站点（163、xuetangx）的 React 事件处理器
                # 只响应浏览器原生信任的点击事件
                try:
                    from selenium.webdriver.common.by import By
                    el = self.driver.find_element(
                        By.CSS_SELECTOR, "[data-ap-signup-tab='1']")
                    el.click()
                except Exception:
                    pass

                time.sleep(1.5)
                pwds = self.find_password_fields()
                if pwds:
                    logger.info("注册 tab 切换成功，密码字段可见")
                    return True
                else:
                    logger.debug("注册 tab 已点击但密码字段消失")
                    return False
            return False
        except Exception as e:
            logger.debug(f"切换注册 tab 异常: {type(e).__name__}: {e}")
            return False

    def ensure_form_visible(self, max_attempts: int = 5) -> bool:
        """轻量级重新打开注册模态框/弹窗。

        Phase 2 分类可能耗时较长导致模态框自动关闭。
        此方法依次尝试：
          1. CDP tryClickAndDetect() 合成事件（兼容传统站点）
          2. Selenium el.click() 可信点击（兼容 React SPA 站点）

        Returns:
            True 如果检测到密码字段（模态框已恢复）
        """
        from selenium.webdriver.common.by import By

        # 先检查是否已有可见密码字段
        try:
            pwds = self.find_password_fields()
            if pwds:
                logger.debug("密码字段已可见，无需重开模态框")
                return True
        except Exception:
            pass

        links = self._cdp_eval("getLoginLinkAttrs()") if self.check_injected() else []
        if not links:
            return False

        # 按 score 降序，取前 N 个
        sorted_links = sorted(
            links,
            key=lambda l: (l.get('score', 0) or 0),
            reverse=True
        )

        for idx, link in enumerate(sorted_links[:max_attempts]):
            xpath = link.get('xpath', '')
            if not xpath:
                continue
            text = (link.get('innerText', '') or '')[:50]

            # 排除机构/企业/商家注册路线（与 navigate_to_signup 一致）
            try:
                from urllib.parse import urljoin
                from signup_flow_classifier.navigator import (
                    _is_organizational_signup,
                )
                link_href = link.get('href', '') or ''
                target_url = urljoin(
                    self.driver.current_url, link_href) if link_href else ""
                if target_url and _is_organizational_signup(target_url):
                    logger.debug(
                        f"[{idx}] 跳过机构/企业注册链接: {text} -> {target_url[:60]}")
                    continue
            except Exception:
                pass

            # ── 策略 1：CDP tryClickAndDetect 合成事件 ──
            try:
                xpath_escaped = xpath.replace('\\', '\\\\').replace("'", "\\'")
                cdp_result = self.driver.execute_cdp_cmd('Runtime.evaluate', {
                    'expression': (
                        "typeof tryClickAndDetect === 'function'"
                        " ? tryClickAndDetect('" + xpath_escaped + "', 3000)"
                        " : Promise.resolve({hasPassword:false})"
                    ),
                    'returnByValue': True,
                    'awaitPromise': True,
                })
                click_result = (cdp_result.get('result') or {}).get('value') or {}
                if click_result.get('hasPassword'):
                    logger.info(
                        f"模态框已重开 (CDP link {idx}): \"{text}\" "
                        f"-> {click_result.get('passwordXpath', '')}")
                    self._try_switch_to_signup_tab()
                    return True
                if click_result.get('navigated'):
                    logger.info(f"模态框重开触发了导航: {click_result.get('newUrl', '')}")
                    try:
                        self._wait_for_spa_render(timeout=2)
                        pwds = self.find_password_fields()
                        if pwds:
                            return True
                    except Exception:
                        pass
                    return False
            except Exception as e:
                logger.debug(f"重开模态框 CDP link {idx} 失败: {type(e).__name__}")

            # ── 策略 2：Selenium 可信点击（React SPA 站点需要）──
            # CDP dispatchEvent(MouseEvent) 对 React 事件处理器无效。
            # 用 Selenium find_element + click() 产生浏览器原生信任事件。
            try:
                el = self.driver.find_element(By.XPATH, xpath)
                if el and el.is_displayed():
                    old_url = self.driver.current_url
                    el.click()
                    time.sleep(1.5)
                    pwds = self.find_password_fields()
                    if pwds:
                        logger.info(
                            f"模态框已重开 (Selenium link {idx}): \"{text}\"")
                        self._try_switch_to_signup_tab()
                        return True
                    # 检查 URL 变化（如跳转到独立注册页）
                    if self.driver.current_url.rstrip("/") != old_url.rstrip("/"):
                        try:
                            self._wait_for_spa_render(timeout=2)
                            pwds = self.find_password_fields()
                            if pwds:
                                return True
                        except Exception:
                            pass
            except Exception:
                pass

        return False

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

    @staticmethod
    def _is_same_site(url_a: str, url_b: str) -> bool:
        """判断两个 URL 是否属于同一注册域。

        passport.example.com 与 www.example.com 视为同站。
        javascript: / void(0) / # / mailto: 等非导航链接视为站内。
        跨域 iframe 链接（blob:, data:, about:）也视为站内。
        """
        if not url_b or url_b.startswith(("#", "javascript:", "void(", "mailto:",
                                          "blob:", "data:", "about:")):
            return True
        try:
            from urllib.parse import urlparse
            pa = urlparse(url_a)
            pb = urlparse(url_b)

            def registered_domain(parsed):
                host = parsed.hostname or ""
                parts = host.split(".")
                if len(parts) >= 2:
                    return ".".join(parts[-2:])
                return host

            return registered_domain(pa) == registered_domain(pb)
        except Exception:
            return True  # 解析失败不拦截

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

    def _page_fingerprint(self) -> str:
        """轻量页面指纹，用于检测 SPA 模态框/视图切换。

        复制自 MyAutomaticPolicy page_fingerprint()：
        用单条 JS 在浏览器内计算 URL + 标题 + 可见输入框签名 +
        按钮/弹窗数量，毫秒级。能区分"无弹窗→弹窗打开"和
        "短信视图→密码视图"等变化。
        """
        try:
            return self._cdp_eval("""
JSON.stringify({
    u: location.href,
    t: document.title,
    i: [...document.querySelectorAll('input')].filter(e=>e.offsetParent!==null)
       .map(e=>(e.type||'')+':'+(e.name||'')+':'+(e.placeholder||'')).sort(),
    b: [...document.querySelectorAll('button,a,[role=button]')]
       .filter(e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);
         return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'})
       .map(e=>(e.innerText||e.getAttribute('aria-label')||e.getAttribute('title')||'').trim())
       .sort(),
    d: document.querySelectorAll('[role=dialog]').length,
    f: [...document.querySelectorAll('iframe')].filter(e=>e.offsetParent!==null)
       .map(e=>(e.src||e.id||'').split('?')[0]).sort()
});
            """) or ""
        except Exception:
            return ""

    def ensure_scripts(self) -> None:
        """兼容旧接口"""
        pass
