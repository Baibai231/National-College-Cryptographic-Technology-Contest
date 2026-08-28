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
        self._reinjected_handle = None  # 已注册 addScriptToEvaluateOnNewDocument 的新标签句柄

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

    def inject_feedback_into_current_frame(self) -> None:
        """在当前 frame 上下文注入反馈检测 JS（跨域 iframe 内联检测用）。

        Page.addScriptToEvaluateOnNewDocument 理论上会向每个新 frame 注入，
        但已存在的 iframe 或注入时序不保证覆盖；切进跨域 iframe 后若
        watchPasswordFeedback 不存在，调用本方法手动补注入 form_detection_addons.js
        （watchPasswordFeedback / getWatchedFeedback / stopWatchingFeedback /
        detectPasswordFeedback 均在该文件内自包含，不依赖 scripts.js 的 Fathom）。
        """
        js = self._read_js("form_detection_addons.js")
        try:
            self.driver.execute_script(js)
        except Exception:
            logger.warning("当前 frame 反馈 JS 注入失败（跨域 iframe 内联检测可能失效）")

    def reinject_into_current_tab(self) -> None:
        """切到新标签页后，向当前页面重新注入两个 JS 文件。

        Page.addScriptToEvaluateOnNewDocument 只对注册脚本时的 target 生效；
        注册入口 target=_blank 打开的新标签是新的 target，脚本不会自动跟随，
        导致新标签页里 ruleset/getXPath/detectEmailInputs 等全部 undefined
        （163.com「注册免费邮箱」新标签实测）。此处用 execute_script 向当前
        已加载页面手动补注入。scripts.js 必须先注入，因为 form_detection_addons.js
        里的 XPath 生成依赖 getXPath/gPt。
        """
        try:
            handle = self.driver.current_window_handle
        except Exception:
            handle = None
        # 每个新标签只需注册一次 addScriptToEvaluateOnNewDocument；
        # 重复注册会导致脚本在新文档里执行多遍（脚本含顶层 var/function 声明，
        # 幂等但浪费）。用句柄去重。
        first_time = (handle is not None and handle != self._reinjected_handle)
        for name in ["scripts.js", "form_detection_addons.js"]:
            js = self._read_js(name)
            try:
                # 用 Runtime.evaluate 而非 execute_script：execute_script 会把脚本
                # 包进一个函数作用域，导致顶层 function 声明（ruleset/getXPath/
                # watchPasswordFeedback/detectFieldsInAllFrames 等）变成局部变量、
                # 挂不到全局，字段/反馈检测 JS 全部 undefined。Runtime.evaluate 以
                # 全局作用域执行，行为与 Page.addScriptToEvaluateOnNewDocument 一致。
                self.driver.execute_cdp_cmd('Runtime.evaluate', {
                    'expression': js,
                    'returnByValue': True,
                })
                # 新标签是新的 CDP target，addScriptToEvaluateOnNewDocument 不会
                # 从原 target 跟随；在此新 target 上重新注册，覆盖全视图探索等
                # 后续页面导航（否则导航后 ruleset/detectFieldsInAllFrames 又
                # 变 undefined，出现「JS 未注入，无法跨 frame 搜索」）。
                if first_time:
                    self.driver.execute_cdp_cmd(
                        'Page.addScriptToEvaluateOnNewDocument',
                        {'source': js},
                    )
            except Exception:
                logger.warning(f"新标签页注入 {name} 失败")
        if handle is not None:
            self._reinjected_handle = handle
        logger.debug("新标签页已重新注入 scripts.js + form_detection_addons.js")

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

    # 站点直通注册页 URL（按注册域 eTLD+1 作 key）：
    # 通用入口发现/点击导航对该站不可靠时，直接导航到已确认的真实注册页。
    # 仅用于「定位注册页」；密码政策仍从该页真实表单测量（不填身份、不提交）。
    _KNOWN_SIGNUP_URLS = {
        "163.com": "https://mail.163.com/register/index.htm#/pn",
    }

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
        # 第 -1 层：站点直通注册页 URL（先于一切通用发现）
        # ================================================================
        # 部分站点（如 163.com）的注册入口是「复合文本 + href 为空 +
        # window.open」的组合，通用入口检测（detect_entry_button 精确文本/
        # 结构语义匹配）与点击导航（可信点击被覆盖层挡、不可信点击触发
        # window.open 被弹窗拦截）均不可靠。这里按注册域直通已确认的真实
        # 注册页；密码政策仍从该页真实表单测量（不填身份、不提交）。
        _reg_domain = self._registered_domain(homepage_url)
        _known_url = self._KNOWN_SIGNUP_URLS.get(_reg_domain)
        if _known_url:
            logger.info(f"站点直通注册页命中 [{_reg_domain}] -> {_known_url}")
            try:
                self.driver.get(_known_url)
                self._wait_for_spa_render(timeout=8)
                pwds = self.find_password_fields()
                if pwds:
                    self._entry_clicked = True
                    logger.info("站点直通成功：到达密码字段")
                    self._try_switch_to_signup_tab()
                    return self.driver.current_url
                logger.warning("站点直通未发现密码字段，回退通用四层策略")
            except Exception as e:
                logger.warning(
                    f"站点直通导航异常 (回退通用策略): {type(e).__name__}: {e}")
            # 直通失败：回到首页，交给通用四层策略继续
            try:
                self.driver.get(homepage_url)
            except Exception:
                pass

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
                    # 点击触发导航时 JS 上下文销毁，CDP awaitPromise 会超时/报错。
                    # 这是成功信号：用 current_url 判断是否真的导航走了。
                    try:
                        _cur = (self.driver.current_url or "").split("?")[0]
                        _old = (homepage_url or "").split("?")[0]
                        if _cur and _old and _cur != _old:
                            logger.info(f"[{idx}] CDP 点击触发导航(上下文销毁): -> {_cur}")
                            self._entry_clicked = True
                            self._wait_for_spa_render()
                            return _cur
                    except Exception:
                        pass
                    logger.debug(f"[{idx}] CDP click 异常: {type(e).__name__}: {e}")
                    consecutive_no_nav += 1
                    if consecutive_no_nav >= 3:
                        logger.debug("连续 3 个链接均未导航，提前退出")
                        break
                    continue

                if not click_result.get('clicked'):
                    # clicked=false 也可能是导航销毁上下文导致 Promise 未 resolve。
                    # 用 current_url 兜底：URL 变了就是导航成功。
                    try:
                        _cur = (self.driver.current_url or "").split("?")[0]
                        _old = (homepage_url or "").split("?")[0]
                        # 规范化比较（去尾斜杠）：仍在首页不算导航成功
                        _cur_norm = (_cur or "").rstrip("/")
                        _old_norm = (_old or "").rstrip("/")
                        if (_cur and _old and _cur != _old
                                and _cur_norm != _old_norm):
                            self._wait_for_spa_render()
                            if self._page_has_auth_signal():
                                logger.info(f"[{idx}] 链接已点击(导航成功): -> {_cur}")
                                self._entry_clicked = True
                                return _cur
                            logger.debug(
                                f"[{idx}] 导航到 {_cur} 但无认证信号，回退重试下一个链接")
                            try:
                                self.driver.get(homepage_url)
                                self._wait_for_page_ready(timeout=10)
                            except Exception:
                                pass
                            consecutive_no_nav += 1
                            continue
                    except Exception:
                        pass
                    logger.debug(f"[{idx}] 未找到或不可见: {text}")
                    continue

                click_attempts += 1

                # ── 结果处理 ──
                if click_result.get('navigated'):
                    new = click_result.get('newUrl', '')
                    if new and new != homepage_url:
                        # 规范化比较（去尾斜杠/query）：new 与首页相同说明
                        # 点击未真正离开首页（如锚点/重定向回首页），不当作
                        # 导航成功，继续试下一个链接。
                        _new_norm = (new or "").split("?")[0].rstrip("/")
                        _home_norm = (homepage_url or "").split("?")[0].rstrip("/")
                        if _new_norm == _home_norm:
                            logger.debug(f"[{idx}] 点击后仍在首页，跳过: -> {new}")
                            consecutive_no_nav += 1
                            continue
                        if not self._is_same_site(homepage_url, new):
                            logger.debug(f"[{idx}] 跨站链接，跳过: -> {new}")
                            self.driver.get(homepage_url)
                            consecutive_no_nav += 1
                            continue
                        logger.info(f"导航: -> {new}")
                        self._wait_for_spa_render()
                        # 导航后验证新页确实含认证信号（input/注册入口）。
                        # 否则可能点到同名链接（GitHub 无头实测：header 的
                        # "Sign up" 未命中，先点到 MCP Registry 的 "Sign up"
                        # → /mcp 空壳页），回退首页继续试下一个链接。
                        if self._page_has_auth_signal():
                            self._entry_clicked = True
                            return new
                        logger.debug(
                            f"[{idx}] 导航到 {new} 但无认证信号，回退重试下一个链接")
                        try:
                            self.driver.get(homepage_url)
                            self._wait_for_page_ready(timeout=10)
                        except Exception:
                            pass
                        consecutive_no_nav += 1
                        continue

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
                #
                # 但指纹变化也可能是「合成点击对普通 <a> 链接无效」导致的假阳性：
                # dispatchEvent(MouseEvent) 不触发浏览器默认的 <a> 导航（isTrusted:false），
                # 点击后页面其实没跳转，只是 hover 下拉 / 广告 iframe 加载造成指纹漂移
                # （163.com「注册免费邮箱」实测）。所以先补一次真实点击验证是否真的
                # 导航了，确实导航才返回注册页 URL；否则才按「弹窗已打开」处理。
                if old_fp and self._page_fingerprint() != old_fp:
                    try:
                        el = self.driver.find_element(By.XPATH, xpath)
                        if el:
                            _before = self.driver.window_handles
                            try:
                                el.click()
                            except Exception:
                                # 链接被覆盖层挡住（163.com「注册免费邮箱」在右上角
                                # (902,21) 被遮挡，Selenium click 抛
                                # ElementClickInterceptedException）→ JS click 绕过
                                try:
                                    self.driver.execute_script(
                                        "arguments[0].click()", el)
                                except Exception:
                                    pass
                            time.sleep(1.5)
                            # 真实点击可能开新标签页（163.com 注册入口 target 为空
                            # 但 JS 触发 window.open 实测）：优先切到带认证内容的新标签。
                            _new_handles = [
                                h for h in self.driver.window_handles
                                if h not in _before
                            ]
                            if _new_handles:
                                self.driver.switch_to.window(_new_handles[0])
                                self._wait_for_spa_render()
                                # 新标签是新的 CDP target，addScriptToEvaluateOnNewDocument
                                # 不会跟随注入，手动补注入，否则字段检测 JS 全部 undefined
                                self.reinject_into_current_tab()
                                _new_url = self.driver.current_url
                                if (self._is_same_site(homepage_url, _new_url)
                                        and _new_url.rstrip('/')
                                        != homepage_url.rstrip('/')
                                        and _new_url.startswith(
                                            ("http://", "https://"))):
                                    logger.info(
                                        f"[{idx}] 指纹变化后真实点击开新标签: "
                                        f"-> {_new_url}")
                                    self._entry_clicked = True
                                    return _new_url
                                # 新标签非本站认证页，切回原页继续走同标签判断
                                if _before:
                                    self.driver.switch_to.window(_before[0])
                            # 同标签页导航
                            _new_url = self.driver.current_url
                            if (_new_url.rstrip('/')
                                    != homepage_url.rstrip('/')):
                                if self._is_same_site(homepage_url, _new_url):
                                    logger.info(
                                        f"[{idx}] 指纹变化后真实点击导航: -> {_new_url}")
                                    self._entry_clicked = True
                                    self._wait_for_spa_render()
                                    return _new_url
                                self.driver.get(homepage_url)
                            # 点击仍无导航（覆盖层拦截 + JS click 因 isTrusted=false
                            # 被 preventDefault）→ 直接按 href 导航。链接 href 已在
                            # CDP 发现阶段拿到，无需依赖点击坐标/事件信任。
                            _href = (link.get('href') or '').strip()
                            if (_href and _href != '#'
                                    and not _href.lower().startswith('javascript:')):
                                from urllib.parse import urljoin
                                _target = urljoin(self.driver.current_url, _href)
                                if (_target.startswith(('http://', 'https://'))
                                        and self._is_same_site(homepage_url, _target)
                                        and _target.rstrip('/')
                                        != homepage_url.rstrip('/')):
                                    logger.info(
                                        f"[{idx}] 覆盖层拦截，直接按 href 导航: "
                                        f"-> {_target}")
                                    self.driver.get(_target)
                                    self._entry_clicked = True
                                    self._wait_for_spa_render()
                                    return _target
                    except Exception:
                        pass
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
        # 第 1.5 层：登录入口 → 注册链接兜底
        # ================================================================
        # 主界面只有登录表单的站（pan.baidu/百度实测）：首页没有注册链接，
        # 注册藏在"去登录/登录"点击后打开的登录页/弹窗里（"立即注册"等）。
        # 注册链接发现为 0 或全部点击失败后，先点登录入口，再在登录视图里
        # 找注册链接并点击，验证密码框出现才算到达注册界面。
        if not self._entry_clicked:
            logger.info("尝试登录入口 → 注册链接兜底...")
            try:
                self.driver.get(homepage_url)
                self._wait_for_page_ready(timeout=8)
            except Exception:
                pass
            # 快速预检：页面没有可见登录入口文本时直接跳过兜底
            # （无弹窗站实测：登录兜底白白耗时 3s+SPA渲染+找字段 ~15s，
            # 且会拖慢全量回归导致 site_timeout）。
            try:
                _has_login_entrance = bool(self._cdp_eval(
                    "(function() {"
                    "  var K = ['去登录', '立即登录', '登录', 'sign in', 'log in', 'login'];"
                    "  var els = document.querySelectorAll('a,button,div,span,[role=button]');"
                    "  for (var i = 0; i < els.length && i < 300; i++) {"
                    "    var e = els[i];"
                    "    if (e.children.length > 0) continue;"
                    "    var t = (e.innerText || '').trim();"
                    "    if (t.length > 0 && t.length <= 8"
                    "      && K.some(function(k) { return t === k || t.indexOf(k) === 0; })) {"
                    "      var r = e.getBoundingClientRect();"
                    "      if (r.width > 0 && r.height > 0) return true;"
                    "    }"
                    "  }"
                    "  return false;"
                    "})();"
                ))
            except Exception:
                _has_login_entrance = True  # 检测失败不拦截
            if _has_login_entrance:
                if self._login_to_signup_fallback():
                    return self.driver.current_url
            else:
                logger.debug("登录入口兜底: 页面无可见登录入口，跳过")

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

    def _login_to_signup_fallback(self) -> bool:
        """登录入口 → 注册链接兜底（主界面只有登录表单的站）。

        流程（pan.baidu/百度实测）：
          1. 找可见登录入口（"去登录/登录/立即登录/sign in/log in/login"，
             DIV/SPAN/A/BUTTON 都算，不限于 <a> 链接）；
          2. CDP 事件序列点击（可能触发导航到登录页或打开弹窗）；
          3. 等待页面稳定后调用 _try_switch_to_signup_tab 找"立即注册/去注册"
             等注册链接并点击；
          4. 验证出现密码框才算到达注册界面（登录密码框不算注册证据，
             必须点过注册入口）。

        Returns:
            True  = 到达注册界面（含密码框）
            False = 未找到登录入口或注册链接
        """
        import time
        LOGIN_KEYWORDS = (
            "去登录", "立即登录", "登录", "sign in", "log in", "login",
        )

        def _click_first(expression: str) -> bool:
            try:
                r = self.driver.execute_cdp_cmd('Runtime.evaluate', {
                    'expression': expression,
                    'returnByValue': True,
                })
                return bool((r.get('result') or {}).get('value'))
            except Exception:
                return False

        # 1) 找登录入口
        login_click_js = """
            (function() {
              var KEYWORDS = ["去登录", "立即登录", "登录", "sign in", "log in", "login"];
              var els = document.querySelectorAll('a,button,div,span,[role=button]');
              for (var i = 0; i < els.length; i++) {
                var e = els[i];
                if (e.children.length > 0) continue;
                var t = (e.innerText || '').trim();
                if (t.length > 0 && t.length <= 8
                    && KEYWORDS.some(function(k) { return t === k || t.indexOf(k) === 0; })) {
                  var r = e.getBoundingClientRect();
                  if (r.width > 0 && r.height > 0) {
                    var opts = {bubbles: true, cancelable: true, view: window,
                                clientX: r.left + r.width/2, clientY: r.top + r.height/2};
                    e.dispatchEvent(new MouseEvent('mouseover', opts));
                    e.dispatchEvent(new MouseEvent('mousedown', opts));
                    e.dispatchEvent(new MouseEvent('mouseup', opts));
                    e.dispatchEvent(new MouseEvent('click', opts));
                    try { e.click(); } catch (err) {}
                    return true;
                  }
                }
              }
              return false;
            })();
        """
        if not _click_first(login_click_js):
            logger.debug("登录入口兜底: 未找到可见登录入口")
            return False
        logger.info("登录入口兜底: 已点击登录入口，等待注册链接出现...")
        time.sleep(1.5)
        try:
            self._wait_for_page_ready(timeout=6)
        except Exception:
            pass
        # 轮询等待认证信号（慢渲染站：阿里云/京东/链家等无头下登录弹窗
        # 渲染可能 >5s，固定 sleep 会误判 auth_entry_no_auth_state）。
        # 检查输入框(密码/邮箱/手机)或弹窗出现，最多 8s。
        try:
            deadline = time.time() + 8
            while time.time() < deadline:
                if self._page_has_auth_signal():
                    break
                time.sleep(0.5)
        except Exception:
            pass
        try:
            self._wait_for_spa_render(timeout=3)
        except Exception:
            pass

        # 2) 登录视图里找注册链接并点击（复用注册 tab 切换逻辑）
        if not self._try_switch_to_signup_tab():
            logger.debug("登录入口兜底: 登录视图未找到注册链接")
            return False

        # 3) 验证密码框出现（注册界面的密码框）
        try:
            self._wait_for_spa_render(timeout=3)
        except Exception:
            pass
        pwds = self.find_password_fields()
        if pwds:
            logger.info(f"登录入口兜底: 到达注册界面 -> {self.driver.current_url[:80]}")
            self._entry_clicked = True
            return True
        logger.debug("登录入口兜底: 点击注册后仍无密码框")
        return False

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
            # 部分登录弹窗（百度通行证）先渲染密码框，后渲染底部“立即注册”
            # 链接。若立即扫描会漏掉该链接，导致永远停留登录视图。
            time.sleep(2.0)
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
        // 离屏元素（如隐藏登录表单里 left 为负的"去注册"a.goreg，icourse163
        // 实测）rect 仍有宽高，但完全落在视口外，不视为可见，否则会抢在
        // 可见的 span.goReg 前面被选中，导致点到死链而切不到注册 tab。
        var vw = window.innerWidth || document.documentElement.clientWidth;
        var vh = window.innerHeight || document.documentElement.clientHeight;
        if (rect.right <= 0 || rect.bottom <= 0 || rect.left >= vw || rect.top >= vh) return false;
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
    // 始终把 document.body 作为兜底搜索根。
    // 部分站点的 class 里会出现无关的 panel/overlay，让上面的模态框
    // 选择器误命中这些非认证容器；如果因此跳过 body，真正的登录弹窗
    // 里的“立即注册”就永远找不到。
    searchRoots.push(document.body);

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
                from selenium.webdriver.common.by import By
                before_handles = self.driver.window_handles
                el = self.driver.find_element(
                    By.CSS_SELECTOR, "[data-ap-signup-tab='1']")
                try:
                    el.click()
                except Exception as e:
                    # 原生 click 可能被模态框容器拦截（icourse163 "去注册"
                    # 实测 "element click intercepted"）。回退 JS 点击：
                    # jQuery/原生 handler 仍会响应，绕过覆盖层拦截。
                    logger.debug(
                        "注册 tab 原生点击失败({})，回退 JS 点击 el=<{} class={}>".format(
                            type(e).__name__, el.tag_name,
                            el.get_attribute("class")))
                    try:
                        self.driver.execute_script(
                            "arguments[0].click()", el)
                    except Exception as je:
                        logger.debug("注册 tab JS 点击失败: {}".format(je))

                time.sleep(2.0)

                # ── 新窗口/新标签页处理 ──
                # 百度通行证的“立即注册”不是同页 SPA 切换，而是打开新的
                # passport.baidu.com 注册窗口。旧逻辑只检查当前窗口，
                # 因此永远看不到新窗口里的注册密码框。
                new_handles = [
                    h for h in self.driver.window_handles
                    if h not in before_handles
                ]
                if new_handles:
                    try:
                        self.driver.switch_to.window(new_handles[0])
                        self._wait_for_page_ready(timeout=15)
                        # 新标签是新的 CDP target，字段检测脚本不会自动跟随。
                        self.reinject_into_current_tab()
                        pwds = self.find_password_fields()
                        if pwds:
                            self._entry_clicked = True
                            logger.info(
                                "注册入口打开新标签页，密码字段可见: "
                                f"{self.driver.current_url}"
                            )
                            return True
                    except Exception as e:
                        logger.debug(
                            "新标签页注册表单检测失败: {}:{}".format(
                                type(e).__name__, e))
                    # 新标签没有注册密码框：切回原窗口继续按同页切换处理
                    if before_handles:
                        try:
                            self.driver.switch_to.window(before_handles[0])
                        except Exception:
                            pass

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
            # 自愈：分类器「全视图探索」可能导航到新文档或切换 frame/window，
            # 导致 ruleset/detectFieldsInAllFrames 丢失。这里向当前页面补注入后再试。
            logger.warning("JS 未注入，尝试重新注入后再跨 frame 搜索")
            try:
                self.reinject_into_current_tab()
            except Exception as e:
                logger.warning(f"重新注入失败: {e}")
            if not self.check_injected():
                logger.warning("JS 重新注入失败，无法跨 frame 搜索")
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
    def _registered_domain(url: str) -> str:
        """返回 URL 的注册域（eTLD+1），如 passport.163.com → 163.com。"""
        try:
            from urllib.parse import urlparse
            host = urlparse(url).hostname or ""
            parts = host.split(".")
            if len(parts) >= 2:
                return ".".join(parts[-2:])
            return host
        except Exception:
            return ""

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
            return LoginLinkDiscovery._registered_domain(url_a) == \
                LoginLinkDiscovery._registered_domain(url_b)
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
                    "(function() {"
                    "  var inputs = document.querySelectorAll("
                    "    'input[type=password]:not([disabled]), "
                    "    input[type=email]:not([disabled]), "
                    "    input[name*=email i]:not([disabled]), "
                    "    input[name*=mail i]:not([disabled])'"
                    "  );"
                    "  for (var i = 0; i < inputs.length; i++) {"
                    "    if (inputs[i].offsetHeight > 0) return true;"
                    "  }"
                    "  return false;"
                    "})();"
                )
                if result:
                    return
            except Exception:
                pass
            time.sleep(0.3)
        logger.debug(f"SPA 渲染等待超时 ({timeout}s)")

    def _page_has_auth_signal(self) -> bool:
        """导航到新 URL 后检查页面是否含认证信号。

        点击注册链接可能命中同名但非认证的页面（GitHub 无头实测：先点到
        MCP Registry 的 "Sign up" → /mcp 空壳页）。检查可见的认证输入框
        （password/email/tel）或 URL 注册路径。注意：不能把页面上任意
        "Sign up/登录" 链接文本当信号——GitHub 全站 header 常驻 Sign up
        链接，mcp 等非注册页也有，会误放行。
        """
        try:
            if self._cdp_eval(
                "(function() {"
                "  var vis = function(e) {"
                "    var r = e.getBoundingClientRect();"
                "    var s = getComputedStyle(e);"
                "    return r.width > 0 && r.height > 0"
                "      && s.display !== 'none' && s.visibility !== 'hidden';"
                "  };"
                "  var inputs = document.querySelectorAll("
                "    'input[type=password]:not([disabled]), "
                "    input[type=email]:not([disabled]), "
                "    input[name*=email i]:not([disabled]), "
                "    input[name*=mail i]:not([disabled]), "
                "    input[type=tel]:not([disabled])'"
                "  );"
                "  for (var i = 0; i < inputs.length; i++) {"
                "    if (vis(inputs[i])) return true;"
                "  }"
                "  return false;"
                "})();"
            ):
                return True
        except Exception:
            return True  # 检测失败不拦截（保守放行）
        # URL 路径含注册字样也算（如 /signup、/register、/reg）
        try:
            from urllib.parse import urlparse
            path = (urlparse(self.driver.current_url).path or "").lower()
            if any(m in path for m in ("/signup", "/register", "/reg", "/sign-up")):
                return True
        except Exception:
            pass
        return False

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
