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
from signup_flow_classifier.classifier import classify, primary_method
from signup_flow_classifier.evidence import finalize, record_evidence, record_step
from signup_flow_classifier.browser_failures import (
    classify_exception,
    detect_access_block,
    detect_blank_auth_page,
    detect_server_error_page,
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
        effective_max_steps = max(1, max_steps)
        # 上游 navigate_to_signup 已点击入口 → 不再重复点击已打开的弹窗，
        # 但保留一次兜底点击机会：SPA 弹窗可能在 classify 前自动关闭
        # （bilibili 实测），此时页面为空壳，需要重新点入口。
        if entry_already_clicked and entry_kind == "signup":
            entry_clicks_left = 1
            auth_entry_clicked = True
            signup_entry_clicked = True
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
                    ",".join(state.available_actions) or "-",
                ),
            )

            signup_entry_failed = False

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
                    signup_entry_clicked = True
                    signup_reveal_pending = False
                    if self._maybe_switch_to_new_window(self.driver, before_handles):
                        record_evidence(result, "switched_to_new_window")
                    if (self._wait_for_form_fields(self.driver, timeout=8)
                            or entry_outcome.changed):
                        continue
                else:
                    signup_entry_failed = True

            # ---- Tab 切换优先于阻断检查 ----
            # 弹窗可能默认短信/扫码视图，有"密码登录"tab 时先切换再看。
            desired_password_tab = (
                "password_signup_tab" if entry_kind == "signup" else "password_tab"
            )
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

            # ---- signup 通过"其他方式"展开后，必须再次确认明确注册入口 ----
            # 若只暴露出登录口令框，禁止把它当成注册口令证据。
            if (entry_kind == "signup" and signup_reveal_pending
                    and "password" in state.fields):
                result.primary_method = primary_method(result.states)
                return self._done(
                    result, "unknown", "high", StopReason.NO_SIGNUP_ENTRY.value
                )

            # ---- 出现口令字段 → 优先分类并停止 ----
            # 注意：放在阻断检查之前。弹窗里的"扫码登录"等只是可选替代入口，
            # 密码框可见即视为可到达（阻断信息仍保留在 state.blockers 证据里）
            if "password" in state.fields and not login_page_during_signup:
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
            # 且没有可见注册入口：如实记为 no_signup_entry
            if login_page_during_signup and "password" in state.fields:
                result.primary_method = primary_method(result.states)
                return self._done(
                    result, "unknown", "low", StopReason.NO_SIGNUP_ENTRY.value
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
            record_evidence(
                result, "step={};navigation={}".format(step, outcome.reason))
            if not outcome.changed:
                break
            if step == effective_max_steps:
                stopped_after_changed_last_step = True

        # ---- 4) 最终分类 + 后处理检查 ----
        ft, conf, reason = classify(result.states)
        # 对应 MyAutomaticPolicy L683-699
        if ft == "unknown":
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
