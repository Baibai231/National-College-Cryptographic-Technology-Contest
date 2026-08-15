"""根据可复核的页面状态序列对注册流程分类。

数据层与展示层分离（铁律 2026-08-15）：
- aggregate_methods()：数据层格式，随测量结果写入 reports/ JSONL（原始格式）
- combo_methods()：展示层格式，仅由 webapp 在响应时计算，不落盘
"""
from typing import List, Tuple

from signup_flow_classifier.flow_types import FlowType, MethodResult, PageState, StopReason

METHOD_ZH = {
    "phone": "手机号", "email": "邮箱", "identifier": "账号/邮箱", "username": "用户名",
    "password": "账号密码", "code": "验证码", "sms": "短信验证码", "qr": "扫码",
    "sso": "第三方登录", "wechat": "微信", "qq": "QQ", "weibo": "微博",
    "google": "Google", "apple": "Apple", "github": "GitHub", "gitee": "Gitee",
    "microsoft": "Microsoft", "baidu": "百度", "dingtalk": "钉钉", "douyin": "抖音",
    "xiaohongshu": "小红书", "alipay": "支付宝", "taobao": "淘宝",
    "xiaomi": "小米", "huawei": "华为", "solana": "Solana",
    "auto_signup": "手机号自动注册",
}

# ---- 展示层（combo_methods）词表 ----
COMBO_FIELD_ZH = {"phone": "手机号", "email": "邮箱", "identifier": "账号",
                  "username": "账号", "password": "密码", "code": "验证码"}
COMBO_IDENT_FIELDS = ("identifier", "username", "email", "phone")
COMBO_SOFT_BLOCKERS = {"sms_code", "email_code", "verification_code"}
COMBO_HARD_BLOCKERS = {"captcha", "slide", "scan", "app_confirm", "tos"}
COMBO_SSO_PROVIDERS = {
    "wechat", "qq", "weibo", "gitee", "google", "apple", "github",
    "microsoft", "baidu", "dingtalk", "douyin", "xiaohongshu", "alipay",
    "taobao", "xiaomi", "huawei", "solana",
}

UI_ZH = {
    "standalone_page": "独立页", "modal": "弹窗", "drawer": "抽屉",
    "multi_step_wizard": "分步表单", "inline_widget": "内嵌挂件",
    "sso_iframe": "第三方iframe", "unknown": "未确认",
}

HARD_BLOCKERS = {
    "captcha", "slide", "scan", "app_confirm", "tos",
    "sms_code", "email_code", "verification_code",
}
# 文案语义类方法：不是独立可选入口，只算弱观察证据
SOFT_METHODS = {"auto_signup"}


def aggregate_methods(states: List[PageState], flow_type: str = "") -> List[MethodResult]:
    """把散落在状态序列里的 methods 聚合成逐方法清单（v4）。

    字段与门槛也会反推方法（password 字段 → 账号密码、code 字段 → 短信验证码）。
    每个方法判定：
      - confirmed：出现过且至少一步没有硬门槛（安全边界内可见可用）
      - blocked：  只出现在有硬门槛的步骤里（存在但被门槛挡住）
      - observed： 弱观察证据（auto_signup 等文案语义），不能算独立可用方法
    flow_type 用于主方法状态对齐：分类器已安全到达口令步骤时，即使页面另有
    滑块等门槛，主方法（password）也应标记 confirmed，与 flow_type 口径一致。
    """
    by_method: dict = {}
    for state in states:
        methods = list(state.methods or [])
        fields = set(state.fields or [])
        if "password" in fields and "password" not in methods:
            methods.append("password")
        if "code" in fields:
            if "sms" not in methods and ("phone" in fields or "sms_code" in (state.blockers or [])):
                methods.append("sms")
            elif "email_code" not in methods and "email_code" in (state.blockers or []):
                methods.append("email_code")
        # 口令路线存在时，phone/email/identifier 只是账号标识方式，不单列方法
        if "password" in fields:
            methods = [m for m in methods if m not in ("phone", "email", "identifier", "username")]
        else:
            for f in ("phone", "email", "identifier", "username"):
                if f in fields and f not in methods:
                    methods.append(f)
        for m in methods:
            by_method.setdefault(m, []).append(state)

    results: List[MethodResult] = []
    for m, mstates in by_method.items():
        steps = [s.step for s in mstates]
        blockers: List[str] = []
        hard_count = 0
        for st in mstates:
            st_blockers = set(st.blockers or [])
            for b in st_blockers:
                if b not in blockers:
                    blockers.append(b)
            if st_blockers & HARD_BLOCKERS:
                hard_count += 1

        if m in SOFT_METHODS:
            status = "observed"
        elif hard_count == len(mstates):
            status = "blocked"
        else:
            status = "confirmed"

        if len(mstates) >= 2 or any(
            "submit" in (st.available_actions or []) or "next" in (st.actions or [])
            for st in mstates
        ):
            confidence = "high"
        elif len(mstates) == 1:
            confidence = "medium"
        else:
            confidence = "low"

        route = "、".join(
            f"第{s.step}步({UI_ZH.get(s.ui_type, s.ui_type)})" for s in mstates[:4]
        )
        if status == "blocked" and blockers:
            route = f"{route}（门槛：{'、'.join(blockers)}）"

        results.append(MethodResult(
            method=m, name_zh=METHOD_ZH.get(m, m), status=status,
            confidence=confidence, blockers=blockers, route=route, steps=steps,
        ))

    if flow_type in ("direct_password", "identifier_then_password",
                     "verification_then_password", "otp_only", "email_only"):
        primary = "password" if flow_type != "otp_only" and flow_type != "email_only" else (
            "sms" if flow_type == "otp_only" else "email")
        for m in results:
            if m.method == primary:
                m.status = "confirmed"
                # 页面级门槛（短信备选 tab 的验证码等）不属于主方法本身
                m.blockers = []
                if m.route and m.route.endswith("）") and "（门槛：" in m.route:
                    m.route = m.route.split("（门槛：")[0]

    order = {"confirmed": 0, "blocked": 1, "observed": 2}
    results.sort(key=lambda x: (order.get(x.status, 3), x.name_zh))
    return results


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
    has_verification = any(
        {"sms_code", "email_code", "verification_code"} & set(s.blockers)
        for s in states)
    has_sso = any("sso" in s.methods for s in states)
    if has_password:
        return "password"
    if has_code or has_verification:
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


# ==================== 展示层：组合式方法（仅 webapp 计算，不落盘） ====================

def _combo_name(fields, seen_ids, blockers):
    """字段组合 → (方法id, 展示名)。手机号+密码、邮箱+验证码、账号/邮箱+密码…"""
    f = set(fields or [])
    idents = [x for x in COMBO_IDENT_FIELDS if x in f]
    if not idents:
        idents = [x for x in seen_ids if x in COMBO_IDENT_FIELDS][:2]
    has_code = "code" in f or bool(set(blockers or []) & COMBO_SOFT_BLOCKERS)
    has_pwd = "password" in f
    if not has_code and not has_pwd:
        return None
    id_parts = list(idents)
    if has_code:
        id_parts.append("code")
    if has_pwd:
        id_parts.append("password")
    zh = ["/".join(COMBO_FIELD_ZH[x] for x in idents)] if idents else []
    if has_code:
        zh.append("验证码")
    if has_pwd:
        zh.append("密码")
    return "_".join(id_parts), "+".join(zh)


def combo_methods(states: List[PageState], flow_type: str = "") -> List[MethodResult]:
    """展示层：把状态序列聚合成"用户视角登录方式清单"（组合式）。

    一个方法 = 完整登录方式：手机号+验证码、邮箱+密码、第三方（微信、QQ）、
    扫码、登录即注册。短信验证码属于方法本身（软门槛），只有人机/滑块/
    扫码确认/App确认/协议等硬门槛才标 blocked（需验证）。
    仅由 webapp 展示层调用，不写入 reports/ JSONL。
    """
    by_method: dict = {}
    seen_ids: List[str] = []
    for state in states:
        fields = state.fields or []
        for x in COMBO_IDENT_FIELDS:
            if x in fields and x not in seen_ids:
                seen_ids.append(x)

        combo = _combo_name(fields, seen_ids, state.blockers)
        if combo is not None:
            by_method.setdefault(combo[0], []).append(state)

        for m in (state.methods or []):
            if m in COMBO_SSO_PROVIDERS:
                by_method.setdefault("sso_providers", []).append(state)
            elif m == "qr":
                by_method.setdefault("qr", []).append(state)
            elif m in ("auto_signup",):
                by_method.setdefault("auto_signup", []).append(state)

    results: List[MethodResult] = []
    for m, mstates in by_method.items():
        steps = [s.step for s in mstates]
        blockers: List[str] = []
        hard_count = 0
        for st in mstates:
            st_blockers = set(st.blockers or [])
            for b in st_blockers:
                if b not in blockers:
                    blockers.append(b)
            if st_blockers & COMBO_HARD_BLOCKERS:
                hard_count += 1

        if m == "auto_signup":
            status = "observed"
        elif hard_count == len(mstates):
            status = "blocked"
        else:
            status = "confirmed"

        if len(mstates) >= 2 or any(
            "submit" in (st.available_actions or []) or "next" in (st.actions or [])
            for st in mstates
        ):
            confidence = "high"
        elif len(mstates) == 1:
            confidence = "medium"
        else:
            confidence = "low"

        if m == "sso_providers":
            providers = set()
            for st in mstates:
                providers.update(
                    p for p in (st.methods or []) if p in COMBO_SSO_PROVIDERS)
            zhs = [METHOD_ZH.get(p, p) for p in sorted(providers)]
            name = "第三方" + ("（" + "、".join(zhs) + "）" if zhs else "")
        elif m == "qr":
            name = "扫码"
        elif m == "auto_signup":
            name = "登录即注册"
        else:
            tokens = m.split("_")
            zh = []
            idents = [t for t in tokens if t in COMBO_FIELD_ZH
                      and t not in ("password", "code")]
            if idents:
                zh.append("/".join(COMBO_FIELD_ZH[t] for t in idents))
            if "code" in tokens:
                zh.append("验证码")
            if "password" in tokens:
                zh.append("密码")
            name = "+".join(zh)

        results.append(MethodResult(
            method=m, name_zh=name, status=status,
            confidence=confidence, blockers=blockers,
            route="", steps=steps,
        ))

    # 主方法状态对齐：flow_type 已确认到达口令/验证码步骤，主方法升为 confirmed
    if flow_type in ("direct_password", "identifier_then_password",
                     "verification_then_password", "otp_only", "email_only"):
        primary_token = "password" if flow_type not in ("otp_only", "email_only") else (
            "code" if flow_type == "otp_only" else "email")
        for m in results:
            if m.method in ("sso", "qr", "auto_signup"):
                continue
            if primary_token in m.method.split("_"):
                m.status = "confirmed"
                m.blockers = []

    order = {"confirmed": 0, "blocked": 1, "observed": 2}
    results.sort(key=lambda x: (order.get(x.status, 3), x.name_zh))
    return results
