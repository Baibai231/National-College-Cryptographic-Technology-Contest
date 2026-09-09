"""注册流程分类器引擎 — 嫁接自 MyAutomaticPolicy 的 signup_flow 模块。

提供 SignupFlowClassifierEngine 类：
  - classify(signup_url, entry_kind)  → 安全探索多步注册流程并返回分类结果
  - try_switch_to_password_view()     → 类型 E 补救：尝试 tab 切换
  - get_current_password_field_xpath() → 获取当前页面密码字段 XPath

安全边界：只点击明确安全的 next/tab/entry 按钮，不填写字段或提交表单。
"""

import time
from typing import Optional, Dict
from urllib.parse import parse_qsl, urlparse

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from loguru import logger

from signup_flow_classifier.flow_types import FlowResult, FlowType, StopReason
from signup_flow_classifier.page_detector import (
    _detect_page_semantics,
    classify_input_type,
    configure_performance_optimizations,
    detect_blockers,
    detect_fields_all_frames,
    detect_page_state,
    detect_tabs_all_frames,
)
from signup_flow_classifier.navigator import (
    MAX_ENTRY_CLICKS,
    MAX_STEPS,
    detect_entry_button,
    safe_advance,
    safe_dismiss_cookie_banner,
    safe_click_entry,
    safe_click_tab,
    safe_click_auth_mode_switch,
)


def _has_auto_signup(states) -> bool:
    """状态序列是否明确表明“登录即注册/登录或注册”。"""
    return any(
        "auto_signup" in getattr(state, "methods", []) for state in states)
from signup_flow_classifier.classifier import classify, primary_method
from signup_flow_classifier.evidence import finalize, record_evidence, record_step
from signup_flow_classifier.browser_failures import (
    classify_exception,
    detect_access_block,
    detect_blank_auth_page,
    detect_server_error_page,
    is_human_challenge_marker,
)

# 这些类型 → 继续执行密码政策测量
PROCEED_FLOW_TYPES = {
    FlowType.DIRECT_PASSWORD.value,
    FlowType.IDENTIFIER_THEN_PASSWORD.value,
    FlowType.MULTIPLE_METHODS.value,  # 将尝试切换到密码视图后再决定
}

# 全视图探索的 tab 优先级：先看额外认证方式（短信/邮箱/注册/扫码），
# 主口令 tab 最后访问（口令视图通常已是默认视图）
_TAB_EXPLORE_PRIORITY = (
    "sms_tab", "email_tab", "register_tab", "qr_tab",
    "password_signup_tab", "password_tab",
)


class SignupFlowClassifierEngine:
    """注册流程分类器引擎。

    在发现注册页面后调用 classify()，安全探索多步注册流程，
    返回分类结果 + 是否应继续密码政策测量。

    用法:
        engine = SignupFlowClassifierEngine(driver)
        result = engine.classify("https://example.com/register")
        if result["should_proceed"]:
            ...  # 继续 inline/full 密码政策测量
        else:
            ...  # 直接输出 result["flow_type"] 和 result["policy"]
    """

    def __init__(self, driver: WebDriver):
        self.driver = driver
        configure_performance_optimizations(True)

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def classify(self, signup_url: str, entry_kind: str = "signup",
                 max_steps: int = 6,
                 entry_already_clicked: bool = False,
                 stop_at_password: bool = False) -> Dict:
        """分类注册流程。

        导航到注册页 → 安全探索多步流程 → 分类 → 返回结构化结果。

        Args:
            signup_url: 注册页 URL（已由 LoginLinkDiscovery 发现）
            entry_kind: "signup"（注册）或 "login"（登录）
            max_steps: 最大探索步数
            entry_already_clicked: 上游（navigate_to_signup）已经点击过入口链接并打开了弹窗，
                                   分类器跳过首轮入口点击阶段，直接从当前页面状态分类
            stop_at_password: True 时一旦在注册上下文中确认口令框就立即返回，
                              浏览器停在口令视图（用于重走定位口令框），跳过全视图探索

        Returns:
            dict 包含以下关键字段：
            - flow_type:      A-I 分类字符串（如 "direct_password"）
            - confidence:     "high" / "medium" / "low"
            - stop_reason:    停止原因
            - primary_method: "password" / "sms" / "email_only" / "sso" / "unknown"
            - ui_type:        页面样式（modal / standalone_page / ...）
            - should_proceed: bool, 是否应继续密码政策测量
            - password_reached: bool, 是否已到达密码字段页面
            - signup_password_reached: bool, 注册上下文中确认出现口令框
                                        （推荐作为密码测量门槛，区别于
                                        password_reached 含登录框口令框）
            - policy:         标准化政策摘要（v1.0 schema）
            - states:         页面状态序列（调试用）
            - error:          错误信息（如有）
        """
        parsed_url = urlparse(signup_url)
        site = parsed_url.hostname or signup_url

        result = FlowResult(
            site=site,
            start_url=signup_url,
            final_url="",
            entry_kind=entry_kind,
        )

        # ---- 1) 导航到注册页 ----
        # 如果当前已在目标 URL（SPA 弹窗已打开，navigate_to_signup 只改变了页面状态
        # 但 URL 未变），则跳过导航以保留弹窗状态。
        try:
            current_url = self.driver.current_url.rstrip("/")
            target_url = signup_url.rstrip("/")
        except Exception:
            current_url = ""
            target_url = signup_url

        if current_url and current_url == target_url:
            # 已在目标页面，模态框/弹窗可能已打开，跳过导航
            pass
        else:
            try:
                self.driver.get(signup_url)
            except Exception as e:
                reason = classify_exception(e)
                if reason == StopReason.BROWSER_CRASHED.value:
                    raise
                return self._done(
                    result, "unknown", "low", reason,
                    error="load_failed:{}:{}".format(
                        type(e).__name__, str(e)[:100]),
                )

        # ---- 2) 检测访问阻断 / 服务器故障 ----
        access_marker = detect_access_block(self.driver)
        if access_marker:
            record_evidence(result, "access_blocked:{}".format(access_marker))
            try:
                result.final_url = self.driver.current_url
            except Exception:
                pass
            if is_human_challenge_marker(access_marker):
                from signup_flow_classifier.flow_types import PageState
                result.states.append(PageState(
                    step=0, url=result.final_url or signup_url,
                    blockers=["captcha"], note="full_page_human_challenge"))
                return self._done(
                    result, "human_blocked", "high", StopReason.HUMAN_BLOCKED.value)
            return self._done(result, "unknown", "high", StopReason.ACCESS_BLOCKED.value)

        server_error = detect_server_error_page(self.driver)
        if server_error:
            record_evidence(result, "server_error:{}".format(server_error))
            try:
                result.final_url = self.driver.current_url
            except Exception:
                pass
            return self._done(result, "unknown", "high", StopReason.INFRASTRUCTURE_ERROR.value)

        # ---- 3) 逐步安全探索 ----
        # 确保页面在顶部：某些站点（如 douban.com）在 CDP 链接点击或
        # CMP 检测后页面会滚动到底部，导致顶部的注册/登录表单被遮挡。
        try:
            self.driver.execute_script("window.scrollTo(0, 0);")
        except Exception:
            pass
        # Cookie/GDPR 横幅会遮住页头登录/注册入口，尤其影响海外站点。
        # 只执行“仅必要/全部拒绝/关闭”三类隐私保护动作，绝不接受全部。
        cookie_outcome = safe_dismiss_cookie_banner(self.driver)
        if cookie_outcome.clicked:
            record_evidence(result, cookie_outcome.reason)
            self._wait_for_page_stable(self.driver, timeout=2)
        # 空壳注册页回退：navigate 到的 signup URL 页面无任何认证内容
        # （喜马拉雅 /signup、中华会计网校 register.html 实测是空壳页），
        # 回退到站首页重新找真实入口（首页可能有登录弹窗）。
        if (entry_kind == "signup"
                and self._url_is_requested_entry(signup_url, "signup")):
            try:
                shell = not (
                    detect_fields_all_frames(self.driver)
                    or detect_tabs_all_frames(self.driver)
                    or detect_blockers(self.driver)
                )
                if shell:
                    home = "{}://{}/".format(
                        urlparse(signup_url).scheme,
                        urlparse(signup_url).netloc,
                    )
                    self.driver.get(home)
                    record_evidence(
                        result,
                        "empty_signup_url_fallback_to_home:{}".format(home))
                    self._wait_for_page_stable(self.driver, timeout=6)
                    cookie_outcome = safe_dismiss_cookie_banner(self.driver)
                    if cookie_outcome.clicked:
                        record_evidence(result, cookie_outcome.reason)
                    signup_url = home
            except Exception:
                pass
        effective_max_steps = max(1, max_steps)
        # 上游 navigate_to_signup 已点击入口 → 不再重复点击已打开的弹窗，
        # 但保留一次兜底点击机会：SPA 弹窗可能在 classify 前自动关闭
        # （bilibili 实测），此时页面为空壳，需要重新点入口。
        # 注意：signup_entry_clicked 不在这里置位——navigate 点击的可能是
        # 登录入口（百度等只有登录按钮的站），登录弹窗里的密码框不是注册
        # 证据，必须由本流程自己确认注册上下文（注册入口/注册 tab/注册 URL）。
        if entry_already_clicked and entry_kind == "signup":
            entry_clicks_left = 1
            auth_entry_clicked = True
            signup_entry_clicked = False
        else:
            entry_clicks_left = MAX_ENTRY_CLICKS
            auth_entry_clicked = False
            signup_entry_clicked = False
        tab_clicks_left = 5
        visited_tabs = set()   # 全视图探索：已切换过的 tab 种类
        auth_mode_clicks_left = 2 if entry_kind == "login" else 0
        signup_mode_switches_left = 1 if entry_kind == "signup" else 0
        step_limit = effective_max_steps
        stopped_after_changed_last_step = False
        signup_reveal_pending = False

        # 慢渲染等待：导航刚完成（SPA/代理延迟），页面认证字段可能尚未挂载
        # （GitHub /signup 实测：导航后 React 渲染可能 >5s，第一步立即检测会
        # 误判 no_password_observed）。进入主循环前先轮询等待认证信号出现，
        # 避免把"页面未渲染完"当成"页面无密码框"。
        try:
            if parsed_url.scheme != "file":
                self._wait_for_any_auth_signal(self.driver, timeout=10)
        except Exception:
            pass
        # 延迟挂载的 CMP 可能在初次检查后才出现；再安全检查一次。
        if not cookie_outcome.clicked:
            late_cookie_outcome = safe_dismiss_cookie_banner(self.driver)
            if late_cookie_outcome.clicked:
                record_evidence(result, late_cookie_outcome.reason)

        for step in range(1, effective_max_steps + 3):
            if step > step_limit:
                break

            # 页面稳定等待（本地 fixture 短，真实网站长）
            time.sleep(0.2 if parsed_url.scheme == "file" else 1.0)

            # 页面状态采样
            try:
                state = detect_page_state(self.driver, step)
            except Exception as e:
                reason = classify_exception(e)
                if reason == StopReason.BROWSER_CRASHED.value:
                    raise
                ft, conf, _ = classify(result.states)
                return self._done(
                    result, ft, conf, reason,
                    error="detect_failed:{}:{}".format(type(e).__name__, str(e)[:80]),
                )

            # 每轮重新检查访问阻断（风控 iframe 可能延迟挂载）
            access_marker = detect_access_block(self.driver)
            if access_marker:
                record_evidence(result, "access_blocked:{}".format(access_marker))
                result.final_url = state.url
                if is_human_challenge_marker(access_marker):
                    if "captcha" not in state.blockers:
                        state.blockers.append("captcha")
                    return self._done(
                        result, "human_blocked", "high", StopReason.HUMAN_BLOCKED.value)
                return self._done(result, "unknown", "high", StopReason.ACCESS_BLOCKED.value)

            # 记录本步状态
            record_step(result, state)
            result.final_url = state.url
            record_evidence(
                result,
                "step={};fields={};blockers={};methods={};actions={}".format(
                    step,
                    ",".join(state.fields) or "-",
                    ",".join(state.blockers) or "-",
                    ",".join(state.methods) or "-",
                    ",".join(state.available_actions) or "-",                ),
            )

            signup_entry_failed = False

            # ---- 整页协议弹窗处理 ----
            # 部分站（芒果TV/咪咕实测）进主界面前必须先点"我同意"协议按钮；
            # 这是安全导航（不填身份信息、不提交注册），点击后继续流程。
            # 只在页面无任何认证状态（无字段/无 tab）时处理，避免误点
            # 注册表单内的协议；不依赖 tos blocker（按钮式协议不被
            # checkbox 检测识别，mgtv 实测）。
            if (not state.fields and not state.tabs
                    and state.ui_type not in {"modal", "drawer"}):
                agree = self._try_click_agreement()
                if agree:
                    record_evidence(result, "step={};agreement={}".format(
                        step, agree))
                    state.note = agree
                    state.actions.append("agree_click")
                    if self._wait_for_any_auth_signal(
                            self.driver, timeout=6):
                        continue

            # ---- 计算登录页守卫标记 ----
            login_page_during_signup = (
                entry_kind == "signup"
                and self._url_is_requested_entry(state.url, "login")
            )

            # ---- 注册入口点击（优先于其他操作） ----
            # 注册测量优先寻找"真正的注册入口"，且严格禁止回退到登录按钮。
            # 这一步必须早于 password tab：否则首页先弹出的登录口令框会被误当成
            # "注册时直接设口令"。
            if (entry_kind == "signup" and entry_clicks_left > 0
                    and not self._url_is_requested_entry(state.url, "signup")
                    and not ("password" in state.fields
                             and signup_entry_clicked
                             and not signup_reveal_pending)
                    and not ({"scan", "captcha", "slide", "app_confirm"}
                             & set(state.blockers))
                    and detect_entry_button(
                        self.driver, "register", allow_fallback=False,
                        prefer_frames=signup_reveal_pending
                    ) is not None):
                before_handles = self.driver.window_handles
                entry_outcome = safe_click_entry(
                    self.driver, "register", allow_fallback=False,
                    prefer_frames=signup_reveal_pending,
                )
                entry_clicks_left -= 1
                state.note = entry_outcome.reason
                state.actions.append("entry_click" if entry_outcome.clicked else "none")
                record_evidence(result, "step={};entry={}".format(step, entry_outcome.reason))
                if entry_outcome.clicked:
                    auth_entry_clicked = True
                    signup_reveal_pending = False
                    if self._maybe_switch_to_new_window(self.driver, before_handles):
                        record_evidence(result, "switched_to_new_window")
                    form_fields = self._wait_for_form_fields(
                        self.driver, timeout=8)
                    # 只有点击确实改变了页面/出现表单时才算进入注册上下文；
                    # 点击了但页面没变化（10jqka 登录弹窗"注册"入口点击无效果
                    # 实测）不能置 signup_entry_clicked，否则 register_tab
                    # 会被跳过、注册视图永远进不去。
                    if entry_outcome.changed or form_fields:
                        signup_entry_clicked = True
                    if form_fields or entry_outcome.changed:
                        continue
                else:
                    signup_entry_failed = True

            # ---- Tab 切换优先于阻断检查 ----
            # 弹窗可能默认短信/扫码视图，有"密码登录"tab 时先切换再看。
            desired_password_tab = (
                "password_signup_tab" if entry_kind == "signup" else "password_tab"
            )
            # signup 优先点击"注册"tab：登录弹窗/登录页里常藏
            # "立即注册/注册账号"（百度/pan.baidu/贴吧/人民网实测），
            # 不点开就拿不到注册视图，登录密码框会被误当成注册密码框。
            # 注意：登录页可能默认就有密码框（人民网 sso 登录页实测），
            # 此时不能因"已有密码框"跳过注册 tab——那密码框是登录的。
            if (entry_kind == "signup" and tab_clicks_left > 0
                    and "register_tab" in state.tabs
                    and not signup_entry_clicked):
                # 链接型注册 tab 优先直接导航（人民网"立即注册"是
                # <a href="/u/reg">；点击在页面刚渲染时可能不触发导航）。
                # cctv 实测：弹窗刚渲染时取 href 和点击都可能落空，
                # 失败后等 1.5s 重试一次再放弃。
                import time as _t
                for _attempt in range(2):
                    if tab_clicks_left <= 0:
                        break
                    reg_href = ""
                    try:
                        from urllib.parse import urljoin
                        from signup_flow_classifier.navigator import (
                            _same_site, _is_organizational_signup,
                        )
                        reg_href = self.driver.execute_script(
                            "const t=[...document.querySelectorAll("
                            "'a,button,[role=tab],[class*=tab]')]"
                            ".find(e=>/立即注册|免费注册|注册账号|sign up|register/i"
                            ".test((e.innerText||'').trim())"
                            "&&(e.getAttribute('href')||e.getAttribute('data-href')||''));"
                            "return t?(t.getAttribute('href')||t.getAttribute('data-href')||''):'';"
                        ) or ""
                        if reg_href:
                            target_url = urljoin(
                                self.driver.current_url, reg_href)
                            # _same_site 按 eTLD+1 比较：reg.cctv.com 与
                            # www.cctv.com 同属 cctv.com → 允许安全跟随
                            if (_same_site(self.driver.current_url, target_url)
                                    and not _is_organizational_signup(target_url)):
                                self.driver.get(target_url)
                                record_evidence(
                                    result,
                                    "step={};register_href_nav={}".format(
                                        step, target_url[:50]))
                                signup_entry_clicked = True
                                signup_reveal_pending = False
                                if self._wait_for_form_fields(
                                        self.driver, timeout=8):
                                    break
                    except Exception:
                        pass
                    tab_outcome = safe_click_tab(self.driver, "register_tab")
                    visited_tabs.add("register_tab")
                    tab_clicks_left -= 1
                    state.note = tab_outcome.reason
                    state.actions.append(
                        "tab_click" if tab_outcome.clicked else "none")
                    record_evidence(
                        result, "step={};register_tab={}".format(
                            step, tab_outcome.reason))
                    if tab_outcome.clicked:
                        signup_entry_clicked = True
                        signup_reveal_pending = False
                        if (self._wait_for_form_fields(self.driver, timeout=8)
                                or tab_outcome.changed):
                            break
                        # 点击没变化（页面刚渲染）时再等一轮观察：
                        # 链接型注册 tab（人民网 /u/reg）点击后可能延迟导航。
                        if self._wait_for_any_auth_signal(
                                self.driver, timeout=6):
                            break
                    if _attempt == 0:
                        _t.sleep(1.5)
                if signup_entry_clicked:
                    continue
            if (not login_page_during_signup and not signup_entry_failed
                    and "password" not in state.fields and tab_clicks_left > 0
                    and desired_password_tab in state.tabs):
                tab_outcome = safe_click_tab(self.driver, desired_password_tab)
                tab_clicks_left -= 1
                state.note = tab_outcome.reason
                state.actions.append("tab_click" if tab_outcome.clicked else "none")
                record_evidence(result, "step={};tab={}".format(step, tab_outcome.reason))
                if tab_outcome.clicked:
                    # 轮询等待密码框出现（tab 切换可能有渲染延迟）
                    if self._wait_for_field(self.driver, "password", timeout=6):
                        continue
                    if tab_outcome.changed:
                        continue
                    break  # 点了、没变化、也没密码框 → 停止

            # 短信 tab 优先点击：弹窗默认可能是"短信登录/手机号登录"视图
            # （快手/酷狗等实测），无字段时点开才能看到手机号+验证码；
            # 不限于阻断场景，只要 tab 存在且当前无字段就尝试。
            if (tab_clicks_left > 0 and "sms_tab" in state.tabs
                    and not state.fields
                    and "code" not in state.fields):
                tab_outcome = safe_click_tab(self.driver, "sms_tab")
                visited_tabs.add("sms_tab")
                tab_clicks_left -= 1
                state.note = tab_outcome.reason
                state.actions.append(
                    "tab_click" if tab_outcome.clicked else "none")
                record_evidence(
                    result, "step={};sms_tab_open={}".format(
                        step, tab_outcome.reason))
                if (tab_outcome.clicked
                        and (self._wait_for_field(
                                self.driver, "code", timeout=6)
                             or tab_outcome.changed)):
                    continue
                # 点击失败（tab 元素刚渲染，safe_click_tab 找不到）：等一轮
                # 观察字段/tab 是否出现（快手登录弹窗渲染慢实测）。
                if (not tab_outcome.clicked
                        and self._wait_for_any_auth_signal(
                            self.driver, timeout=5)):
                    continue

            # ---- signup 通过"其他方式"展开后，必须再次确认明确注册入口 ----
            # 若只暴露出登录口令框，禁止把它当成注册口令证据。
            if (entry_kind == "signup" and signup_reveal_pending
                    and "password" in state.fields):
                result.primary_method = primary_method(result.states)
                return self._done(
                    result, "no_web_signup", "high", StopReason.NO_SIGNUP_ENTRY.value
                )

            # ---- 出现口令字段 → 优先分类并停止 ----
            # 注意：放在阻断检查之前。弹窗里的"扫码登录"等只是可选替代入口，
            # 密码框可见即视为可到达（阻断信息仍保留在 state.blockers 证据里）。
            # signup 模式守卫：登录弹窗里的密码框不是注册证据（shimo/百度/
            # B站等仅有登录界面、注册藏在 tab 里的站实测），必须点过注册
            # 入口/注册 tab 或 URL 明确是注册页，密码框才算注册密码框。
            signup_context_confirmed = (
                entry_kind == "login"
                or signup_entry_clicked
                or self._url_is_requested_entry(state.url, "signup")
                or "auto_signup" in state.methods
            )
            # signup 且有"注册"tab 但还没点过：弹窗默认可能是登录视图，
            # 先切到注册 tab 再判断密码框，避免登录密码框冒充注册证据。
            if (entry_kind == "signup" and not signup_entry_clicked
                    and "register_tab" in state.tabs
                    and tab_clicks_left > 0
                    and "password" in state.fields):
                tab_outcome = safe_click_tab(self.driver, "register_tab")
                visited_tabs.add("register_tab")
                tab_clicks_left -= 1
                state.note = tab_outcome.reason
                state.actions.append(
                    "tab_click" if tab_outcome.clicked else "none")
                record_evidence(
                    result, "step={};register_tab_after_pwd={}".format(
                        step, tab_outcome.reason))
                if tab_outcome.clicked:
                    signup_entry_clicked = True
                    signup_reveal_pending = False
                    if self._wait_for_form_fields(self.driver, timeout=6):
                        continue
            # ---- 全视图探索（v4.1 核心改进） ----
            # 已到口令视图时不立即停止：像真人一样把其他 tab（短信/邮箱/注册）
            # 也切一遍，把所有登录/注册方式都观察到（51.com 实测：账号登录
            # 默认视图外还有"手机登录"视图的 手机号+验证码，程序以前看到
            # 密码框就停，漏掉短信视图）。已访问过的 tab 不再重复切换。
            if ("password" in state.fields and not login_page_during_signup
                    and signup_context_confirmed):
                # 注册上下文中确认出现口令框：记录为可测量门槛，
                # 供 main.py 以 signup_password_reached 判断是否继续测量。
                result.signup_password_reached = True
                logger.info(
                    "全视图探索入口: fields={} tabs={} signup_ctx={} login_page={} clicks_left={}".format(
                        state.fields, state.tabs, signup_context_confirmed,
                        login_page_during_signup, tab_clicks_left))
                # stop_at_password 模式：重走定位口令框时就地停在口令视图，
                # 不再做全视图探索（否则浏览器又被切到短信/邮箱 tab）。
                if stop_at_password:
                    ft, conf, reason = classify(result.states)
                    result.primary_method = primary_method(result.states)
                    return self._done(result, ft, conf, reason)
                if tab_clicks_left > 0:
                    next_tab = None
                    for cand in _TAB_EXPLORE_PRIORITY:
                        if (cand in state.tabs and cand not in visited_tabs
                                and cand not in ("password_tab",
                                                "password_signup_tab")):
                            next_tab = cand
                            break
                    if next_tab is None:
                        # 只剩主口令 tab 未访问（罕见）：也切一次收集证据
                        for cand in ("password_tab", "password_signup_tab"):
                            if cand in state.tabs and cand not in visited_tabs:
                                next_tab = cand
                                break
                    if next_tab is not None:
                        tab_outcome = safe_click_tab(
                            self.driver, next_tab)
                        tab_clicks_left -= 1
                        visited_tabs.add(next_tab)
                        state.note = tab_outcome.reason
                        state.actions.append(
                            "tab_click" if tab_outcome.clicked else "none")
                        record_evidence(
                            result, "step={};explore_tab={}".format(
                                step, tab_outcome.reason))
                        # 点击成功即再观察一轮：React 视图切换可能延迟
                        # （icourse163 手机号登录/邮箱登录/爱课程登录 tab 实测，
                        # clicked 但 2 秒指纹窗口内视图未变，下一轮才能看到字段）
                        if tab_outcome.clicked:
                            continue
                        # 弹窗动画/渲染竞态：立即重试一次（51.com 手机登录
                        # tab 实测：检测到但瞬间点不到）
                        if not tab_outcome.clicked and tab_clicks_left > 0:
                            import time as _t
                            _t.sleep(1.5)
                            tab_outcome = safe_click_tab(
                                self.driver, next_tab)
                            tab_clicks_left -= 1
                            state.note = tab_outcome.reason
                            state.actions.append(
                                "tab_click" if tab_outcome.clicked else "none")
                            record_evidence(
                                result, "step={};explore_tab_retry={}".format(
                                    step, tab_outcome.reason))
                            if (tab_outcome.clicked
                                    and (self._wait_for_form_fields(
                                        self.driver, timeout=6)
                                        or tab_outcome.changed)):
                                continue
                # 全视图探索结束：把浏览器切回注册口令视图再返回，避免
                # main.py 拿不到口令框触发"重走"而丢失注册 tab 状态。
                if entry_kind == "signup":
                    logger.info(
                        "全视图探索结束，准备切回注册口令视图 (clicks_left={}, visited={})".format(
                            tab_clicks_left, sorted(visited_tabs)))
                    self._return_to_signup_password_view(result)
                ft, conf, reason = classify(result.states)
                result.primary_method = primary_method(result.states)
                return self._done(result, ft, conf, reason)

            # ---- 被人工阻断 → 停止（含 tab 补偿） ----
            hard_blockers = {"captcha", "slide", "scan", "app_confirm", "tos"}
            auth_url = (
                self._url_is_requested_entry(state.url, "login")
                or self._url_is_requested_entry(state.url, "signup")
            )
            auth_context = bool(
                auth_entry_clicked or state.fields or state.tabs or auth_url
                or state.ui_type in {"modal", "drawer", "sso_iframe", "standalone_page"}
            )
            if hard_blockers & set(state.blockers) and auth_context:
                # 先试 tab 补偿：弹窗刚出现时密码 tab 可能还没渲染完
                if (tab_clicks_left > 0 and "password" not in state.fields
                        and "password_tab" not in state.tabs
                        and not login_page_during_signup):
                    tab_outcome = safe_click_tab(self.driver, desired_password_tab)
                    tab_clicks_left -= 1
                    state.note = tab_outcome.reason
                    state.actions.append("tab_click" if tab_outcome.clicked else "none")
                    record_evidence(result, "step={};tab_retry={}".format(step, tab_outcome.reason))
                    if tab_outcome.clicked and self._wait_for_field(
                        self.driver, "password", timeout=6
                    ):
                        continue

                # 短信 tab 补偿：扫码默认视图下若有"短信登录/手机号注册"tab
                # （qq 首页弹窗实测 sms_tab），切过去可安全观察到手机号+验证码。
                if (tab_clicks_left > 0 and "password" not in state.fields
                        and "sms_tab" in state.tabs
                        and "code" not in state.fields):
                    tab_outcome = safe_click_tab(self.driver, "sms_tab")
                    visited_tabs.add("sms_tab")
                    tab_clicks_left -= 1
                    state.note = tab_outcome.reason
                    state.actions.append(
                        "tab_click" if tab_outcome.clicked else "none")
                    record_evidence(
                        result, "step={};sms_tab_retry={}".format(
                            step, tab_outcome.reason))
                    if (tab_outcome.clicked
                            and self._wait_for_field(
                                self.driver, "code", timeout=6)):
                        continue
                # 登录界面可能没有文字 tab，要先从二维码切到手机，再切到账号。
                if (entry_kind == "login" and auth_mode_clicks_left > 0
                        and "password" not in state.fields):
                    mode_outcome = safe_click_auth_mode_switch(self.driver)
                    if mode_outcome.clicked:
                        auth_mode_clicks_left -= 1
                        step_limit += 1
                        state.note = mode_outcome.reason
                        state.actions.append("auth_mode_click")
                        record_evidence(
                            result, "step={};auth_mode={}".format(step, mode_outcome.reason)
                        )
                        continue

                # 点击过"注册"后，二维码弹窗可能把"其他方式"藏在无文字折角中
                if (entry_kind == "signup" and signup_entry_clicked
                        and signup_mode_switches_left > 0
                        and "scan" in state.blockers):
                    mode_outcome = safe_click_auth_mode_switch(
                        self.driver, structural_only=True
                    )
                    if mode_outcome.clicked:
                        signup_mode_switches_left -= 1
                        step_limit += 1
                        signup_reveal_pending = True
                        state.note = mode_outcome.reason
                        state.actions.append("signup_mode_reveal")
                        record_evidence(
                            result,
                            "step={};signup_mode={}".format(step, mode_outcome.reason),
                        )
                        continue

                ft, conf, reason = classify(result.states)
                result.primary_method = primary_method(result.states)
                return self._done(result, ft, conf, reason)

            # ---- 请求注册流程却只到达明确的登录页 ----
            # 且没有可见注册入口：如实记为 no_web_signup
            if login_page_during_signup and "password" in state.fields:
                result.primary_method = primary_method(result.states)
                return self._done(
                    result, "no_web_signup", "low", StopReason.NO_SIGNUP_ENTRY.value
                )

            # ---- 短信验证码视图（仅 login 测量时尝试切换） ----
            # 对应 MyAutomaticPolicy L546-561
            if (entry_kind == "login" and auth_context
                    and "sms_code" in state.blockers
                    and "password" not in state.fields
                    and auth_mode_clicks_left > 0):
                mode_outcome = safe_click_auth_mode_switch(self.driver)
                if mode_outcome.clicked:
                    auth_mode_clicks_left -= 1
                    step_limit += 1
                    state.note = mode_outcome.reason
                    state.actions.append("auth_mode_click")
                    record_evidence(
                        result,
                        "step={};auth_mode={}".format(step, mode_outcome.reason),
                    )
                    continue

            # ---- 慢渲染等待 ----
            # 页面无字段、无阻断、且没有可点的入口按钮时，
            # 可能是 React 慢渲染（如 discord 约 15 秒才出表单），轮询等待信号出现。
            # 对应 MyAutomaticPolicy L563-576
            if not state.fields and not state.blockers:
                prefer0 = "register" if entry_kind == "signup" else "login"
                if detect_entry_button(self.driver, prefer0) is None:
                    wait_timeout = 2 if parsed_url.scheme == "file" else 15
                    if self._wait_for_any_signal(self.driver, timeout=wait_timeout):
                        continue

            # ---- 入口点击（首页/空页尚无字段时） ----
            # 对应 MyAutomaticPolicy L578-667
            # 弹窗已打开（有 tabs/blockers/modal 形态）时不再点入口：
            # 重复点击"登录"会把已展开的弹窗关闭（bilibili 实测，
            # 弹窗与入口按钮同源，点入口等于点遮罩）。
            need_entry_click = (
                not state.fields and not state.tabs and not state.blockers
                and state.ui_type not in {"modal", "drawer"}
            )
            if need_entry_click and entry_clicks_left > 0:
                prefer = "register" if entry_kind == "signup" else "login"
                prefer_active_frames = bool(
                    entry_kind == "signup" and signup_reveal_pending
                )
                allow_entry_fallback = not prefer_active_frames
                # 预读入口链接 href（供点击失败时"直接导航到登录页"兜底，imooc 等）
                entry_href = ""
                entry_tag = ""
                try:
                    detect_entry_button(
                        self.driver, prefer,
                        allow_fallback=allow_entry_fallback,
                        prefer_frames=prefer_active_frames,
                    )
                    entry_href = self.driver.execute_script(
                        "const el = document.querySelector('[data-ap-entry-token]');"
                        "const h = el ? (el.getAttribute('href') || '') : '';"
                        "if (el) el.removeAttribute('data-ap-entry-token');"
                        "return h;"
                    ) or ""
                except Exception:
                    pass
                # hover 菜单兜底：页面没有明确的登录/注册文本入口，或检测到的入口
                # 是无 href 的容器元素（LI/DIV，如博客园 id=navbar_login_status 的
                # hover 菜单）时，尝试 hover 头部"用户/账号"菜单展开登录链接。
                if (not entry_href and entry_clicks_left > 0
                        and not prefer_active_frames):
                    from signup_flow_classifier.navigator import (
                        detect_entry_button as _deb, safe_hover_menu,
                    )
                    hover_outcome = None
                    try:
                        _deb(self.driver, prefer, allow_fallback=False)
                        entry_info = self.driver.execute_script(
                            "const el = document.querySelector('[data-ap-entry-token]');"
                            "const h = el ? el.getAttribute('href') : '';"
                            "const t = el ? el.tagName : '';"
                            "if (el) el.removeAttribute('data-ap-entry-token');"
                            "return JSON.stringify({tag: t, href: h});"
                        ) or '{}'
                    except Exception:
                        entry_info = '{}'
                    import json as _json
                    info = _json.loads(entry_info or '{}')
                    container_entry = (
                        info.get('tag') in ('LI', 'DIV', 'SPAN')
                        and not info.get('href')
                    )
                    if (not info.get('tag') or container_entry):
                        hover_outcome = safe_hover_menu(
                            self.driver, prefer)
                        if hover_outcome and hover_outcome.changed:
                            record_evidence(
                                result,
                                "step={};hover={}".format(
                                    step, hover_outcome.reason))
                            state.note = hover_outcome.reason
                            state.actions.append("hover_click")
                            if self._wait_for_form_fields(
                                    self.driver, timeout=8):
                                continue
                            if hover_outcome.changed:
                                continue
                            break
                before_handles = self.driver.window_handles
                entry_outcome = safe_click_entry(
                    self.driver, prefer,
                    allow_fallback=allow_entry_fallback,
                    prefer_frames=prefer_active_frames,
                )
                entry_clicks_left -= 1
                state.note = entry_outcome.reason
                state.actions.append(
                    "entry_click" if entry_outcome.clicked else "none")
                record_evidence(
                    result, "step={};entry={}".format(step, entry_outcome.reason))
                if entry_outcome.clicked:
                    auth_entry_clicked = True
                    if (entry_kind == "signup"
                            and (entry_outcome.reason.startswith("register_")
                                 or prefer_active_frames)):
                        signup_entry_clicked = True
                        signup_reveal_pending = False
                    # 登录弹窗可能开在新窗口/新标签（微博），切换过去
                    if self._maybe_switch_to_new_window(
                            self.driver, before_handles):
                        record_evidence(result, "switched_to_new_window")
                    # 点击成功：轮询等待表单/弹窗渲染
                    if self._wait_for_form_fields(self.driver, timeout=8):
                        continue
                    # 慢渲染/点击抖动恢复（仅真实网站）：
                    # oschina 登录页需约 18 秒才渲染；
                    # imooc 的登录链接偶尔点击未落地。延长等待并重试一次入口点击。
                    if parsed_url.scheme != "file":
                        if self._wait_for_any_auth_signal(
                                self.driver, timeout=10):
                            continue
                        if entry_clicks_left > 0:
                            retry_outcome = safe_click_entry(
                                self.driver, prefer)
                            entry_clicks_left -= 1
                            record_evidence(
                                result,
                                "step={};entry_retry={}".format(
                                    step, retry_outcome.reason))
                            if (retry_outcome.clicked
                                    and self._wait_for_any_auth_signal(
                                        self.driver, timeout=3)):
                                continue
                        # 链接兜底：入口是站内 <a href> 且点击未出现认证状态时，
                        # 直接导航到 href（imooc 的 /user/newlogin 等）。
                        if entry_href:
                            from urllib.parse import urljoin
                            from signup_flow_classifier.navigator import \
                                _same_site
                            target_url = urljoin(
                                self.driver.current_url, entry_href)
                            if _same_site(self.driver.current_url, target_url):
                                self.driver.get(target_url)
                                record_evidence(
                                    result,
                                    "step={};entry_href_nav={}".format(
                                        step, target_url[:60]))
                                if self._wait_for_any_auth_signal(
                                        self.driver, timeout=5):
                                    continue
                    if entry_outcome.changed:
                        continue  # 页面变了但仍无表单，再走一轮
                    break  # 点过、页面没变、也没表单 → 停止

            # ---- 安全前进（点击"下一步/继续"） ----
            outcome = safe_advance(self.driver, allow_local_test_values=False)
            state.actions.append("next" if outcome.clicked else "none")
            # safe_advance performs a fresh blocker scan.  A challenge can mount
            # between state sampling and navigation; retain that evidence rather
            # than ending with an empty unknown state.
            if outcome.reason == "human_blocked" and "captcha" not in state.blockers:
                state.blockers.append("captcha")
            elif (outcome.reason == "verification_required"
                  and "verification_code" not in state.blockers):
                state.blockers.append("verification_code")
            record_evidence(
                result, "step={};navigation={}".format(step, outcome.reason))
            if not outcome.changed:
                break
            if step == effective_max_steps:
                stopped_after_changed_last_step = True

        # ---- 4) 最终分类 + 后处理检查 ----
        ft, conf, reason = classify(result.states)
        # signup 模式"仅登录界面"守卫：全程没点过注册入口/注册 tab、
        # URL 也不是注册页，但检测到了密码框——这是登录界面（shimo/
        # 百度等仅登录站的实测），不能把登录密码框当注册证据。
        auto_signup_seen = _has_auto_signup(result.states)
        if (entry_kind == "signup" and not signup_entry_clicked
                and not auto_signup_seen):
            login_only_url = any(
                self._url_is_requested_entry(getattr(s, "url", ""), "login")
                for s in result.states
            )
            if (("password" in state.fields or login_only_url)
                    and ft != "unknown"):
                return self._done(
                    result, "no_web_signup", "high",
                    StopReason.NO_SIGNUP_ENTRY.value)
        # 对应 MyAutomaticPolicy L683-699
        if ft == "unknown":
            blank_marker = detect_blank_auth_page(self.driver)
            # SPA 渲染慢的站（deeix.gaoxiaobei.top 实测）在页面加载中途
            # 可能短暂空白，被误判为渲染故障。先等页面稳定再重查一次，
            # 仍空白才确认是故障。
            if blank_marker and parsed_url.scheme != "file":
                self._wait_for_page_stable(self.driver, timeout=4)
                blank_marker = detect_blank_auth_page(self.driver)
            if blank_marker:
                record_evidence(
                    result, "rendering_failed:{}".format(blank_marker))
                result.primary_method = primary_method(result.states)
                return self._done(
                    result, "unknown", "high",
                    StopReason.INFRASTRUCTURE_ERROR.value)
        if stopped_after_changed_last_step and ft == "unknown":
            reason = StopReason.MAX_STEPS_REACHED.value
        elif (ft == "unknown"
              and any("entry_click" in getattr(s, "actions", [])
                      for s in result.states)):
            reason = StopReason.AUTH_ENTRY_NO_AUTH_STATE.value
        # v4 曾加"无认证信号+未点入口 → no_web_signup"升级，实测无头模式下
        # 大量站（aliyun/douban/ke 等 30+）弹窗不弹被误判为无入口，回退该升级。
        # no_web_signup 只保留三处有明确证据的守卫（仅登录界面/登录页冒充注册/
        # 展开后只露登录口令框），无信号一律保持 unknown 诚实记录。
        result.primary_method = primary_method(result.states)
        return self._done(result, ft, conf, reason)

    def _click_register_tab_via_cdp(self) -> bool:
        """用 CDP + Selenium 可信点击切到"注册"tab。

        safe_click_tab 只扫主文档的 div/span/li/a/button，且 register_tab
        的关键词里没有裸"注册"；而 icourse163 的"去注册"藏在 <span
        class="goReg"> 里、xuetangx 的"手机注册"也常是 label 容器。这里复用
        login_link_discovery._try_switch_to_signup_tab 的深度优先遍历 + 打分
        机制（已被 icourse163/xuetangx 实测证明能找到），找到后标记
        data-ap-signup-tab 再交给 Selenium 原生 click（可信事件）。
        """
        js = r"""
(function() {
    var KEYWORDS = [
        '注册', '去注册', '立即注册', '免费注册', '新用户注册',
        '註冊', '手机注册', '邮箱注册', '注册账号', '注册帐号',
        'sign up', 'signup', 'register', 'create account',
        'new account', 'create new account', 'get started'
    ];
    var EXCLUDE = [
        '同意', '协议', '政策', '隐私', '条款', '即表示', '视为',
        'agree', 'terms', 'policy', 'privacy', 'by clicking',
        'by registering', 'you agree', 'i agree', 'i have read'
    ];
    var TAGS = ['a', 'button', 'span', 'div', 'li', 'label'];
    function txt(el) { return (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim(); }
    function vis(el) {
        var r = el.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) return false;
        var s = getComputedStyle(el);
        if (s.display === 'none' || s.visibility === 'hidden') return false;
        if (parseFloat(s.opacity) === 0) return false;
        // 离屏元素（left 为负等）仍可能有宽高，需排除，避免选到隐藏表单里
        // 的"去注册"死链（icourse163 实测）。
        var vw = window.innerWidth || document.documentElement.clientWidth;
        var vh = window.innerHeight || document.documentElement.clientHeight;
        if (r.right <= 0 || r.bottom <= 0 || r.left >= vw || r.top >= vh) return false;
        return true;
    }
    var candidates = [];
    function walk(node) {
        if (!node || !node.tagName) return;
        var tag = node.tagName.toLowerCase();
        if (TAGS.indexOf(tag) === -1) {
            if (node.children) for (var i = 0; i < node.children.length; i++) walk(node.children[i]);
            return;
        }
        if (!vis(node)) {
            if (node.children) for (var i = 0; i < node.children.length; i++) walk(node.children[i]);
            return;
        }
        if (node.children && node.children.length > 0)
            for (var i = 0; i < node.children.length; i++) walk(node.children[i]);
        var t = txt(node).toLowerCase();
        if (t.length > 80) return;
        var excluded = false;
        for (var e = 0; e < EXCLUDE.length; e++) {
            if (t.indexOf(EXCLUDE[e].toLowerCase()) !== -1) { excluded = true; break; }
        }
        if (excluded) return;
        for (var k = 0; k < KEYWORDS.length; k++) {
            var kw = KEYWORDS[k].toLowerCase();
            if (t === kw || t.indexOf(kw) !== -1) {
                var rect = node.getBoundingClientRect();
                var area = rect.width * rect.height;
                var quality = (t === kw) ? 2 : 1;
                var shortBonus = (30 - Math.min(t.length, 30)) * 200;
                candidates.push({
                    el: node,
                    score: quality * 500000 + shortBonus - area - rect.top,
                    text: txt(node).substring(0, 50)
                });
                break;
            }
        }
    }
    var roots = [];
    var modals = document.querySelectorAll(
        '[class*=modal i],[class*=dialog i],[class*=popup i],[class*=overlay i],'
        + '[class*=panel i],[role=dialog],[role=alertdialog],[aria-modal=true]');
    for (var m = 0; m < modals.length; m++) if (vis(modals[m])) roots.push(modals[m]);
    if (roots.length === 0) roots.push(document.body);
    for (var r = 0; r < roots.length; r++) walk(roots[r]);
    if (candidates.length === 0) return {found: false};
    candidates.sort(function(a, b) { return b.score - a.score; });
    var best = candidates[0];
    best.el.setAttribute('data-ap-signup-tab', '1');
    return {found: true, text: best.text};
})();
"""
        try:
            val = self.driver.execute_cdp_cmd('Runtime.evaluate', {
                'expression': js, 'returnByValue': True, 'awaitPromise': True})
            value = (val.get('result') or {}).get('value') or {}
            if not value.get('found'):
                logger.info("切回注册 tab: 未找到注册入口元素")
                return False
            logger.info("切回注册 tab: \"{}\"".format(value.get('text', '')))
            try:
                el = self.driver.find_element(
                    By.CSS_SELECTOR, "[data-ap-signup-tab='1']")
                el.click()
            except Exception as e:
                # 原生 click 可能被模态框容器拦截（icourse163 "去注册"
                # 实测 "element click intercepted"），回退 JS 点击。
                try:
                    el = self.driver.find_element(
                        By.CSS_SELECTOR, "[data-ap-signup-tab='1']")
                    self.driver.execute_script(
                        "arguments[0].click()", el)
                except Exception:
                    logger.warning("切回注册 tab 可信点击失败: {}".format(e))
                    return False
            return True
        except Exception as e:
            logger.warning("切回注册 tab CDP 异常: {}: {}".format(type(e).__name__, e))
            return False

    def _return_to_signup_password_view(self, result) -> bool:
        """全视图探索结束后，把浏览器切回注册口令视图再返回。

        探索会把浏览器切到短信/邮箱/二维码等 tab。若不切回，
        main.py 的 get_current_password_field_xpath() 会拿到 None 或登录口令框，
        触发"重走"重新导航而丢失注册 tab 状态（icourse163"去注册"、
        xuetangx"手机注册"等"注册藏登录弹窗"站实测）。

        只切注册语义的 tab（密码注册 → 注册入口），不碰 password_tab
        （那是登录口令视图，切过去会让 get_current_password_field_xpath
        误拿登录口令框）。
        """
        # 探索若从未真正切走（safe_click_tab 扫不到短信/邮箱 tab 时），浏览器
        # 仍停在注册口令视图，此时口令框（含 iframe 里）早已可见，无需再点。
        # 用 _locate_password_field() 而非 _wait_for_field("password")：
        # 后者走 JS visible()，会漏掉 opacity:0/visibility:hidden 祖先的隐藏
        # 登录口令框（icourse163 实测误判"已在口令视图"），前者用 Selenium
        # is_displayed() 且能切进跨域注册 iframe，判断更准。
        if self._locate_password_field() is not None:
            logger.info("全视图探索结束，浏览器已在注册口令视图，无需切回")
            return True
        # 首选：复用 _try_switch_to_signup_tab 的 CDP 深搜机制（safe_click_tab
        # 扫不到裸"注册"/label 里的注册入口，icourse163/xuetangx 实测失败）。
        if self._click_register_tab_via_cdp():
            time.sleep(1.5)
            if self._locate_password_field() is not None:
                record_evidence(result, "return_to_signup_password_view:cdp")
                logger.info("全视图探索结束，切回注册口令视图: cdp_register_tab")
                return True
        # 兜底：仍走 safe_click_tab（兼容把注册 tab 渲染成标准 tab 的站）。
        for tab in ("password_signup_tab", "register_tab"):
            outcome = safe_click_tab(self.driver, tab)
            logger.info("切回注册口令视图尝试: tab={} clicked={} reason={}".format(
                tab, outcome.clicked, outcome.reason))
            if outcome.clicked:
                time.sleep(1.5)
                if self._locate_password_field() is not None:
                    record_evidence(
                        result,
                        "return_to_signup_password_view:{}".format(tab),
                    )
                    logger.info("全视图探索结束，切回注册口令视图: {}".format(tab))
                    return True
        logger.warning(
            "切回注册口令视图失败：CDP 注册 tab 与 password_signup_tab/register_tab 均未切到口令视图")
        return False

    def try_switch_to_password_view(self) -> bool:
        """类型 E 补救：尝试从多方式页面切换到邮箱+密码注册视图。

        使用 safe_click_tab 查找"密码注册"tab，再用
        safe_click_auth_mode_switch 尝试展开"其他方式"控件。

        Returns:
            True  = 切换成功，密码字段现在可见
            False = 未能切换到密码视图，应输出类型 E 并跳过测量
        """
        for _attempt in range(2):
            # 尝试密码注册 tab
            tab_outcome = safe_click_tab(self.driver, "password_signup_tab")
            if tab_outcome.clicked:
                time.sleep(1.5)
                fields = detect_fields_all_frames(self.driver)
                if "password" in fields:
                    return True

            # 尝试密码登录 tab（备选）
            tab_outcome = safe_click_tab(self.driver, "password_tab")
            if tab_outcome.clicked:
                time.sleep(1.5)
                fields = detect_fields_all_frames(self.driver)
                if "password" in fields:
                    return True

            # 尝试"其他方式"结构控件展开
            mode_outcome = safe_click_auth_mode_switch(
                self.driver, structural_only=True
            )
            if mode_outcome.clicked:
                time.sleep(1.5)
                fields = detect_fields_all_frames(self.driver)
                if "password" in fields:
                    return True

            # 第一次失败后等一下再试
            if _attempt == 0:
                time.sleep(1.0)

        return False

    def _locate_password_field(self) -> Optional[dict]:
        """定位当前可见口令框，返回 {'xpath': str, 'frame_path': tuple} 或 None。

        frame_path 为进入该口令框所需切换的 iframe 索引序列：
        () 主文档，(2,) 顶层第 3 个 iframe，(1,0) 嵌套。分类流程在确认
        "注册上下文出现口令框"时调用，随结果返回给表单填写器，避免下游
        拿到一个不含 iframe 上下文的 XPath 而误操作主文档里的隐藏登录框。

        同时支持标准 ``type=password`` 和用 ``autocomplete`` 声明用途的
        兼容型文本控件。不少站点的注册口令框藏在跨域 iframe 里（icourse163 的
        reg.icourse163.org/index_reg2_new.html 实测），主文档里只有隐藏的
        登录口令框。这里先查主文档可见口令框，查不到再逐个进入可见认证
        iframe 查（复用 page_detector 的 frame path 原语，支持嵌套）。
        """
        def visible_password_inputs():
            """同时覆盖 type=password 与 autocomplete 标注的兼容控件。"""
            try:
                candidates = self.driver.find_elements(By.TAG_NAME, "input")
            except Exception:
                return []
            matched = []
            for el in candidates:
                try:
                    if (el.is_displayed() and el.is_enabled()
                            and classify_input_type(el) == "password"):
                        matched.append(el)
                except Exception:
                    continue
            # 注册测量优先 new-password；同页同时存在登录和注册表单时，避免
            # DOM 顺序靠前的 current-password 抢占注册口令框。
            def priority(el):
                try:
                    tokens = {
                        token.lower().replace("_", "-")
                        for token in (el.get_attribute("autocomplete") or "").split()
                    }
                    if "new-password" in tokens:
                        return 0
                    if "current-password" in tokens:
                        return 2
                except Exception:
                    pass
                return 1

            return sorted(matched, key=priority)

        try:
            self.driver.switch_to.default_content()
        except Exception:
            pass
        try:
            for el in visible_password_inputs():
                return {"xpath": self._make_xpath(el), "frame_path": ()}
        except Exception:
            pass
        try:
            from signup_flow_classifier.page_detector import (
                _visible_frame_paths, _switch_to_frame_path)
            for path in _visible_frame_paths(self.driver):
                if not _switch_to_frame_path(self.driver, path):
                    continue
                try:
                    for el in visible_password_inputs():
                        return {"xpath": self._make_xpath(el), "frame_path": path}
                finally:
                    self.driver.switch_to.default_content()
        except Exception:
            try:
                self.driver.switch_to.default_content()
            except Exception:
                pass
        return None

    def get_current_password_field_xpath(self) -> Optional[str]:
        """获取当前页面第一个可见密码字段的 XPath（供 main.py 重走判断用）。

        返回不含 iframe 上下文的 XPath；需要 iframe 路径时请用
        _locate_password_field() / 分类结果里的 password_field。
        """
        field = self._locate_password_field()
        return field["xpath"] if field else None

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    @staticmethod
    def _stable_for(driver: WebDriver, tracker: dict, seconds: float) -> bool:
        """页面 ready 且轻量指纹持续不变；用于替代无条件固定等待。"""
        from signup_flow_classifier.navigator import page_fingerprint
        try:
            if driver.execute_script("return document.readyState") != "complete":
                tracker.clear()
                return False
            fingerprint = page_fingerprint(driver)
        except Exception:
            tracker.clear()
            return False
        now = time.monotonic()
        if tracker.get("fingerprint") != fingerprint:
            tracker["fingerprint"] = fingerprint
            tracker["since"] = now
            return False
        return now - tracker.get("since", now) >= seconds

    @staticmethod
    def _wait_for_page_stable(driver: WebDriver, timeout: float = 6.0) -> None:
        """等待页面 readyState complete 且指纹稳定（替代无条件 sleep）。"""
        deadline = time.time() + timeout
        stable = {}
        while time.time() < deadline:
            if SignupFlowClassifierEngine._stable_for(
                    driver, stable, seconds=2.0):
                return
            time.sleep(0.4)

    @staticmethod
    def _wait_for_any_signal(driver: WebDriver, timeout: float = 15.0) -> bool:
        """慢渲染等待：轮询是否出现输入字段（含 iframe）或可点击入口。"""
        deadline = time.time() + timeout
        stable = {}
        while time.time() < deadline:
            try:
                if detect_fields_all_frames(driver):
                    return True
                if (detect_entry_button(driver, "register") is not None
                        or detect_entry_button(driver, "login") is not None):
                    return True
            except Exception:
                pass
            if SignupFlowClassifierEngine._stable_for(driver, stable, seconds=4.0):
                return False
            time.sleep(0.5)
        return False

    @staticmethod
    def _wait_for_any_auth_signal(driver: WebDriver, timeout: float = 10.0) -> bool:
        """轮询等待认证信号出现（字段/tab/阻断），覆盖慢渲染站点（oschina 约 18s）。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if detect_fields_all_frames(driver):
                    return True
                if detect_tabs_all_frames(driver):
                    return True
                if detect_blockers(driver):
                    return True
            except Exception:
                pass
            time.sleep(0.5)
        return False

    @staticmethod
    def _url_is_requested_entry(url: str, entry_kind: str) -> bool:
        """URL 是否已经明确位于请求的登录/注册入口。

        避免把首页的登录按钮当成注册入口，也避免把测试文件名中的
        "register" 误导为注册页。
        """
        parsed = urlparse(url)
        path = parsed.path.lower()
        query_keys = {
            key.lower()
            for key, _ in parse_qsl(parsed.query, keep_blank_values=True)
        }
        if parsed.scheme == "file":
            path = path.rsplit("/", 1)[-1]
        signup_hints = ("signup", "sign-up", "sign_up", "register", "regphone")
        login_hints = ("login", "sign-in", "sign_in", "signin")
        signup_query_keys = {"reg", "register", "signup", "sign-up", "sign_up", "regphone"}
        login_query_keys = {"login", "signin", "sign-in", "sign_in"}
        # 同一路径偶尔同时带有两类词（测试页名、redirect 语义等），当前实际登录
        # 语义优先，不能因为文件名中也出现 register 就跳过注册入口。
        if entry_kind == "signup" and (
            login_query_keys & query_keys
            or any(hint in path for hint in login_hints)
        ):
            return False
        if entry_kind == "login" and (
            signup_query_keys & query_keys
            or any(hint in path for hint in signup_hints)
        ):
            return False
        if entry_kind == "signup":
            return bool(signup_query_keys & query_keys) or any(
                hint in path for hint in signup_hints
            )
        return bool(login_query_keys & query_keys) or any(
            hint in path for hint in login_hints
        )

    @staticmethod
    def _wait_for_field(driver: WebDriver, field_type: str,
                        timeout: float = 5.0) -> bool:
        """轮询等待指定类型的输入框出现（如 password），含 iframe 内字段。"""
        deadline = time.time() + timeout
        stable = {}
        while time.time() < deadline:
            try:
                if field_type in detect_fields_all_frames(driver):
                    return True
            except Exception:
                pass
            if SignupFlowClassifierEngine._stable_for(driver, stable, seconds=2.0):
                return False
            time.sleep(0.3)
        return False

    @staticmethod
    def _wait_for_form_fields(driver: WebDriver, timeout: float = 6.0) -> bool:
        """点击入口后等待字段、认证 tab 或人工阻断任一出现。"""
        deadline = time.time() + timeout
        stable = {}
        while time.time() < deadline:
            try:
                fields = detect_fields_all_frames(driver)
                semantics = _detect_page_semantics(driver, fields)
                if fields or semantics.get("blockers") or semantics.get("tabs"):
                    return True
            except Exception:
                pass
            if SignupFlowClassifierEngine._stable_for(driver, stable, seconds=6.0):
                return False
            time.sleep(0.4)
        return False

    @staticmethod
    def _maybe_switch_to_new_window(driver: WebDriver, before_handles,
                                     timeout: float = 4.0) -> bool:
        """等待并切入具有认证证据的新窗口。

        新标签刚创建时常是 about:blank 或只有认证 URL，表单由
        后续 JS 渲染。在有界等待内轮询，避免因单次瞬时采样造成时序波动；
        同时要求 URL 之外还有标题/正文/字段，不把空白失败页当成成功。
        """
        original = None
        try:
            original = driver.current_window_handle
            deadline = time.time() + timeout
            first_checked = time.time()
            saw_new_window = False
            while time.time() < deadline:
                handles = driver.window_handles
                new_handles = [h for h in handles if h not in before_handles]
                if new_handles:
                    saw_new_window = True
                elif not saw_new_window and time.time() - first_checked >= 0.5:
                    # 站内 modal 是绝大多数，没有新 handle 时快速返回
                    return False
                for h in new_handles:
                    driver.switch_to.window(h)
                    payload = driver.execute_script(
                        "const vis=e=>{const r=e.getBoundingClientRect(),"
                        "s=getComputedStyle(e);return r.width>0&&r.height>0"
                        "&&s.display!=='none'&&s.visibility!=='hidden'};"
                        "return {url:location.href,title:document.title||'',"
                        "text:(document.body?.innerText||'').slice(0,1200),"
                        "inputs:[...document.querySelectorAll('input')].filter(vis)"
                        ".map(e=>[e.type,e.name,e.placeholder,e.id])};"
                    ) or {}
                    semantic = (
                        "{} {} {}".format(
                            payload.get("url", ""),
                            payload.get("title", ""),
                            payload.get("text", ""),
                        )
                    ).lower()
                    auth_url = any(
                        hint in str(payload.get("url", "")).lower()
                        for hint in (
                            "login", "signin", "sign-in", "register", "signup",
                            "passport", "account", "oauth", "auth",
                        )
                    )
                    auth_text = any(
                        hint in semantic[:1800]
                        for hint in (
                            "登录", "注册",
                            "扫码登录", "手机号登录",
                            "sign in", "log in", "create account",
                        )
                    )
                    meaningful_page = bool(
                        payload.get("title") or payload.get("text")
                        or payload.get("inputs")
                    )
                    if payload.get("inputs") or auth_text or (
                            auth_url and meaningful_page):
                        return True
                if original in driver.window_handles:
                    driver.switch_to.window(original)
                time.sleep(0.25)
        except Exception:
            try:
                if original in driver.window_handles:
                    driver.switch_to.window(original)
            except Exception:
                pass
        return False

    @staticmethod
    def _xpath_literal(value: str) -> str:
        """把任意属性值安全编码为 XPath 字符串字面量。"""
        if "'" not in value:
            return "'{}'".format(value)
        if '"' not in value:
            return '"{}"'.format(value)
        parts = value.split("'")
        args = []
        for index, part in enumerate(parts):
            if part:
                args.append("'{}'".format(part))
            if index < len(parts) - 1:
                args.append('"\'"')
        return "concat({})".format(",".join(args))

    @staticmethod
    def _make_xpath(el) -> str:
        """为元素构造简单 XPath。

        口令框优先加 type 或 autocomplete 语义限定：部分站点把注册口令框
        误标为 name='email'（icourse163 实测），缺少限定会让 XPath 命中
        真邮箱框。所有来自页面的属性值均编码为 XPath 字面量。
        """
        try:
            input_type = (el.get_attribute("type") or "").lower()
            autocomplete = el.get_attribute("autocomplete") or ""
            ac_tokens = autocomplete.split()
            normalized_ac_tokens = [
                token.lower().replace("_", "-") for token in ac_tokens
            ]
            semantic_predicate = ""
            if input_type == "password":
                semantic_predicate = (
                    "translate(@type,'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
                    "'abcdefghijklmnopqrstuvwxyz')='password'")
            elif "new-password" in normalized_ac_tokens:
                token = ac_tokens[normalized_ac_tokens.index("new-password")]
                semantic_predicate = (
                    "contains(concat(' ',normalize-space(@autocomplete),' '),"
                    "{})".format(
                        SignupFlowClassifierEngine._xpath_literal(
                            " {} ".format(token)))
                )
            elif "current-password" in normalized_ac_tokens:
                token = ac_tokens[normalized_ac_tokens.index("current-password")]
                semantic_predicate = (
                    "contains(concat(' ',normalize-space(@autocomplete),' '),"
                    "{})".format(
                        SignupFlowClassifierEngine._xpath_literal(
                            " {} ".format(token)))
                )
            if semantic_predicate:
                val = el.get_attribute("id")
                if val:
                    return "//input[{} and @id={}]".format(
                        semantic_predicate,
                        SignupFlowClassifierEngine._xpath_literal(val),
                    )
                val = el.get_attribute("name")
                if val:
                    return "//input[{} and @name={}]".format(
                        semantic_predicate,
                        SignupFlowClassifierEngine._xpath_literal(val),
                    )
                return "//input[{}]".format(semantic_predicate)
            for attr in ("id", "name"):
                val = el.get_attribute(attr)
                if val:
                    return "//input[@{}={}]".format(
                        attr, SignupFlowClassifierEngine._xpath_literal(val))
        except Exception:
            pass
        return "//input[@type='password']"

    def _try_click_agreement(self) -> Optional[str]:
        """安全点击整页协议弹窗的"我同意/同意并继续"按钮。

        只处理站点的整页协议拦截（芒果TV/咪咕实测），不涉及注册表单内
        的协议勾选。要求按钮处于协议弹窗上下文（class/id 含
        agreement/protocol/confirm 等，或相邻文本含"协议/隐私"），
        避免误点普通页面的"同意"文字。返回点击结果原因或 None。
        """
        from selenium.webdriver.common.by import By
        hints = ["我同意", "同意并继续", "同意并进入", "同意并", "接受", "同意"]
        try:
            for el in self.driver.find_elements(
                    By.CSS_SELECTOR, "button, a, span, div"):
                try:
                    if not el.is_displayed():
                        continue
                    text = (el.text or "").strip()
                    if not text:
                        continue
                    if text.startswith("不同意"):
                        continue
                    if not any(text == h or text.startswith(h)
                               for h in hints if len(h) > 2):
                        continue
                    # 协议上下文检查：按钮自身或祖先/相邻含协议语义
                    try:
                        context = self.driver.execute_script(
                            "const el=arguments[0];"
                            "const p=el.closest('[class*=agreement i],"
                            "[class*=protocol i],[class*=confirm i],"
                            "[class*=permission i],[class*=agree i],"
                            "[class*=popup i],[class*=modal i],dialog,"
                            "[aria-modal=true]');"
                            "const near=(p||el.parentElement||document.body)"
                            ".innerText||'';"
                            "return /协议|隐私|条款|同意|服务协议|agree|"
                            "privacy|term/i.test(near.slice(0,200));",
                            el,
                        )
                    except Exception:
                        context = True
                    if context:
                        el.click()
                        return f"agreed_{text[:10]}"
                except Exception:
                    continue
        except Exception:
            pass
        return None

    def _done(self, result, flow_type, confidence, stop_reason, error=None):
        """填充分类结论并返回 dict。"""
        finalized = finalize(result, flow_type, confidence, stop_reason, error=error)
        d = finalized.to_dict()
        d["should_proceed"] = flow_type in PROCEED_FLOW_TYPES
        d["password_reached"] = any(
            "password" in (s.get("fields", []) if isinstance(s, dict) else getattr(s, "fields", []))
            for s in result.states
        )
        d["signup_password_reached"] = getattr(result, "signup_password_reached", False)
        # 注册上下文确认过口令框 → 记录其 XPath + iframe 路径，随结果返回，
        # 供 main.py 交给表单填写器（切进对应 frame 再操作），避免误用主文档
        # 里的隐藏登录框。正常路径与 stop_at_password 重走路径都从这里统一记录。
        d["password_field"] = None
        if getattr(result, "signup_password_reached", False):
            d["password_field"] = self._locate_password_field()
        # Passive-only protocol/capability observations are attached at the
        # single classification exit point so CLI, batch and web callers share
        # exactly the same evidence.  Observer failure never changes the flow
        # classification result.
        try:
            from security_observers import collect_security_observations
            d["security_observations"] = collect_security_observations(
                self.driver, states=d.get("states"), methods=d.get("methods"))
        except Exception as exc:
            d["security_observations"] = {
                "schema_version": "1.0",
                "collection_mode": "passive",
                "observed_capabilities": [],
                "analyzers": {},
                "collection_errors": ["observer:{}".format(type(exc).__name__)],
                "privacy": {"raw_tokens_stored": False,
                            "raw_cookie_values_stored": False,
                            "extra_network_request_sent": False,
                            "raw_urls_stored": False,
                            "raw_header_values_stored": False,
                            "raw_certificates_stored": False},
            }
        return d
