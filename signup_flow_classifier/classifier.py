"""根据可复核的页面状态序列对注册流程分类。"""
from typing import List, Tuple

from signup_flow_classifier.flow_types import FlowType, PageState, StopReason


def primary_method(states: List[PageState]) -> str:
    """推断注册流程的主方式（用于结果里的 primary_method 字段）。

    规则：
      - 出现口令字段 → password
      - 出现短信/邮箱验证码 → sms / email
      - 只出现邮箱/账号标识 → email_only
      - 只有第三方登录 → sso
      - 其他 → unknown
    """
    has_password = any("password" in s.fields for s in states)
    has_code = any("code" in s.fields for s in states)
    has_phone = any("phone" in s.fields for s in states)
    has_email = any("email" in s.fields or "identifier" in s.fields for s in states)
    has_sso = any("sso" in s.methods for s in states)
    if has_password:
        return "password"
    if has_code:
        return "sms" if has_phone else "email"
    if has_email:
        return "email_only"
    if has_sso:
        return "sso"
    return "unknown"


def classify(states: List[PageState]) -> Tuple[str, str, str]:
    """返回 ``(flow_type, confidence, stop_reason)``。

    规则（v2，2026-08-05）：
      1. 人工阻断优先 → human_blocked
      2. 只有第三方登录 → sso_only
      3. 有口令字段 → 按步骤细分（direct/identifier/verification），主方式=口令
      4. 有验证码但无口令 → otp_only（终端）/ verification_required
      5. 邮箱/账号标识 + SSO（无口令无验证码）→ email_only（主方式=邮箱）
      6. 手机号 + SSO（无口令无验证码）→ multiple_methods
      7. 只有邮箱/账号标识 → email_only
      8. 只有手机号 → unknown
    """
    steps = [state for state in states if state.url]
    if not steps:
        return FlowType.UNKNOWN.value, "low", StopReason.NAVIGATION_ERROR.value

    # 口令字段可见 → 优先按口令分类（弹窗里的扫码/短信只是可选替代入口，
    # 阻断信息仍保留在 state.blockers 证据中；无口令可到达时才判 human_blocked）
    if any("password" in state.fields for state in steps):
        has_password = True
    else:
        has_password = False
        hard_blockers = {"captcha", "slide", "scan", "app_confirm", "tos"}
        if any(hard_blockers & set(state.blockers) for state in steps):
            return FlowType.HUMAN_BLOCKED.value, "high", StopReason.HUMAN_BLOCKED.value

    has_password = any("password" in state.fields for state in steps)
    has_code = any("code" in state.fields for state in steps)
    verification_blockers = {"sms_code", "email_code", "verification_code"}
    has_verification = any(
        verification_blockers & set(state.blockers) for state in steps
    )
    has_email = any("email" in state.fields for state in steps)
    has_identifier = any("identifier" in state.fields or "username" in state.fields for state in steps)
    has_phone = any("phone" in state.fields for state in steps)
    has_sso = any("sso" in state.methods for state in steps)
    has_owned = has_password or has_code or has_email or has_identifier or has_phone

    # 只有第三方统一登录，不需要也不应继续跟踪到外域身份提供商。
    if has_sso and not has_owned:
        return FlowType.SSO_ONLY.value, "high", StopReason.EXTERNAL_IDP_DETECTED.value

    # 有口令字段：主方式=口令；SSO 只是附加方式（记录在 methods，不再判 multiple_methods）
    if has_password:
        password_index = next(i for i, state in enumerate(steps) if "password" in state.fields)
        earlier_steps = steps[:password_index]
        earlier_fields = {field for state in earlier_steps for field in state.fields}
        earlier_blockers = {blocker for state in earlier_steps for blocker in state.blockers}

        # 密码步前一步是认证方式切换（如 短信登录→密码登录，或
        # 二维码→手机→账号的并行视图）：另一视图里的验证码字段不算
        # 前置条件。只有真正点击“下一步”才表示流程顺序前进。
        last_route_switch = max(
            (
                index for index, state in enumerate(earlier_steps)
                if any(
                    action in state.actions
                    for action in ("tab_click", "auth_mode_click")
                )
            ),
            default=-1,
        )
        last_progress = max(
            (
                index for index, state in enumerate(earlier_steps)
                if "next" in state.actions
            ),
            default=-1,
        )
        if last_route_switch > last_progress:
            return FlowType.DIRECT_PASSWORD.value, "high", StopReason.PASSWORD_STEP_REACHED.value

        if "code" in earlier_fields or verification_blockers & earlier_blockers:
            return (FlowType.VERIFICATION_THEN_PASSWORD.value, "high",
                    StopReason.PASSWORD_STEP_REACHED.value)
        if earlier_fields & {"email", "phone", "identifier", "username"}:
            return (FlowType.IDENTIFIER_THEN_PASSWORD.value, "high",
                    StopReason.PASSWORD_STEP_REACHED.value)
        return FlowType.DIRECT_PASSWORD.value, "high", StopReason.PASSWORD_STEP_REACHED.value

    # 有验证码但无口令
    if has_code or has_verification:
        code_steps = [
            state for state in steps
            if "code" in state.fields
            or verification_blockers & set(state.blockers)
        ]
        looks_terminal = any(
            "submit" in state.available_actions and "next" not in state.available_actions
            for state in code_steps
        )
        if looks_terminal:
            return FlowType.OTP_ONLY.value, "medium", StopReason.NO_PASSWORD_OBSERVED.value
        return FlowType.HUMAN_BLOCKED.value, "medium", StopReason.VERIFICATION_REQUIRED.value

    # 邮箱/账号标识 + SSO → email_only（WordPress 类：邮箱即账号，SSO 是附加）
    if (has_email or has_identifier) and has_sso:
        return FlowType.EMAIL_ONLY.value, "medium", StopReason.NO_PASSWORD_OBSERVED.value

    # 手机号 + SSO（无口令无验证码）→ 多种方式并存，无明确主方式
    if has_phone and has_sso:
        return FlowType.MULTIPLE_METHODS.value, "medium", StopReason.NO_SAFE_ACTION.value

    # 只有邮箱/账号标识 → 邮箱即账号
    if has_email or has_identifier:
        return FlowType.EMAIL_ONLY.value, "medium", StopReason.NO_PASSWORD_OBSERVED.value

    if has_phone:
        return FlowType.UNKNOWN.value, "low", StopReason.NO_SAFE_ACTION.value

    # 页面空白、脚本未渲染和确实无网页注册入口无法仅凭当前页区分。
    return FlowType.UNKNOWN.value, "low", StopReason.UNRECOGNIZED_PAGE.value
