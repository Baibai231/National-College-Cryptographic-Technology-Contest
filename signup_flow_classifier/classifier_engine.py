"""注册流程分类器引擎 — 嫁接自 MyAutomaticPolicy 的 signup_flow 模块。

提供 SignupFlowClassifierEngine 类：
  - classify(signup_url, entry_kind)  → 安全探索多步注册流程并返回分类结果
  - try_switch_to_password_view()     → 类型 E 补救：尝试 tab 切换
  - get_current_password_field_xpath() → 获取当前页面密码字段 XPath

安全边界：只点击明确安全的 next/tab/entry 按钮，不填写字段或提交表单。
"""

import time
from typing import Optional, Dict
from urllib.parse import urlparse

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

from signup_flow_classifier.flow_types import FlowResult, FlowType, StopReason
from signup_flow_classifier.page_detector import (
    _detect_page_semantics,
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
                 max_steps: int = MAX_STEPS,
                 entry_already_clicked: bool = False) -> Dict:
        """分类注册流程。

        导航到注册页 → 安全探索多步流程 → 分类 → 返回结构化结果。

        Args:
            signup_url: 注册页 URL（已由 LoginLinkDiscovery 发现）
            entry_kind: "signup"（注册）或 "login"（登录）
            max_steps: 最大探索步数
            entry_already_clicked: 上游（navigate_to_signup）已经点击过入口链接并打开了弹窗，
                                   分类器跳过首轮入口点击阶段，直接从当前页面状态分类

        Returns:
            dict 包含以下关键字段：
            - flow_type:      A-I 分类字符串（如 "direct_password"）
            - confidence:     "high" / "medium" / "low"
            - stop_reason:    停止原因
            - primary_method: "password" / "sms" / "email_only" / "sso" / "unknown"
            - ui_type:        页面样式（modal / standalone_page / ...）
            - should_proceed: bool, 是否应继续密码政策测量
            - password_reached: bool, 是否已到达密码字段页面
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
        tab_clicks_left = 2
        auth_mode_clicks_left = 2 if entry_kind == "login" else 0
        signup_mode_switches_left = 1 if entry_kind == "signup" else 0
        step_limit = effective_max_steps
        stopped_after_changed_last_step = False
        signup_reveal_pending = False

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
                                continue
                except Exception:
                    pass
                tab_outcome = safe_click_tab(self.driver, "register_tab")
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
                        continue
                    # 点击没变化（页面刚渲染）时再等一轮观察：
                    # 链接型注册 tab（人民网 /u/reg）点击后可能延迟导航。
                    if self._wait_for_any_auth_signal(
                            self.driver, timeout=6):
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
            if ("password" in state.fields and not login_page_during_signup
                    and signup_context_confirmed):
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

    def get_current_password_field_xpath(self) -> Optional[str]:
        """获取当前页面第一个可见密码字段的 XPath。

        分类器已导航到密码页面后，可用此方法获取 XPath 给 form filler 使用。
        """
        try:
            pwds = self.driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
            for el in pwds:
                if el.is_displayed() and el.is_enabled():
                    return self._make_xpath(el)
        except Exception:
            pass
        return None

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
        if parsed.scheme == "file":
            path = path.rsplit("/", 1)[-1]
        signup_hints = ("signup", "sign-up", "sign_up", "register", "regphone")
        login_hints = ("login", "sign-in", "sign_in", "signin")
        # 同一路径偶尔同时带有两类词（测试页名、redirect 语义等），当前实际登录
        # 语义优先，不能因为文件名中也出现 register 就跳过注册入口。
        if entry_kind == "signup" and any(hint in path for hint in login_hints):
            return False
        if entry_kind == "login" and any(hint in path for hint in signup_hints):
            return False
        hints = signup_hints if entry_kind == "signup" else login_hints
        return any(hint in path for hint in hints)

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
    def _make_xpath(el) -> str:
        """为元素构造简单 XPath。"""
        try:
            for attr in ("id", "name"):
                val = el.get_attribute(attr)
                if val:
                    return "//input[@{}='{}']".format(attr, val)
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
        return d
