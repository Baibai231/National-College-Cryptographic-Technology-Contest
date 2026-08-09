"""注册流程类型定义与测量结果结构（阶段 1）

分类体系对应 NEXT_STEPS.md 第 3 节：
    A direct_password                 当前页面直接出现邮箱/用户名和口令框
    B identifier_then_password        先填邮箱/手机号，点击下一步后才出现口令框
    C verification_then_password      先通过短信/邮箱验证码，之后才能设置口令
    D otp_only                        验证码注册，无长期静态口令
    E multiple_methods                同时提供多种注册方式
    F sso_only                        只有第三方登录
    G human_blocked                   被验证码/扫码/App 确认等人工操作挡住
    H no_web_signup                   没有可用网页注册入口或入口失效
    I unknown                         页面异常或证据不足
"""
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Optional


class FlowType(str, Enum):
    DIRECT_PASSWORD = "direct_password"
    IDENTIFIER_THEN_PASSWORD = "identifier_then_password"
    VERIFICATION_THEN_PASSWORD = "verification_then_password"
    OTP_ONLY = "otp_only"
    EMAIL_ONLY = "email_only"                  # 邮箱即账号：只需邮箱即可注册，无口令无验证
    MULTIPLE_METHODS = "multiple_methods"
    SSO_ONLY = "sso_only"
    HUMAN_BLOCKED = "human_blocked"
    NO_WEB_SIGNUP = "no_web_signup"
    UNKNOWN = "unknown"


class StopReason(str, Enum):
    """分类停止原因"""
    PASSWORD_STEP_REACHED = "password_step_reached"      # 到达口令步骤
    NO_PASSWORD_OBSERVED = "no_password_observed"        # 已走完可达步骤，未发现口令
    HUMAN_BLOCKED = "human_blocked"                      # 遇到人工阻断
    NO_SIGNUP_ENTRY = "no_signup_entry"                  # 未发现注册入口
    MAX_STEPS_REACHED = "max_steps_reached"              # 达到最大步数
    NAVIGATION_ERROR = "navigation_error"                # 导航/页面异常
    INFRASTRUCTURE_ERROR = "infrastructure_error"        # 网络、代理或驱动基础设施异常
    BROWSER_CRASHED = "browser_crashed"                  # Chrome 窗口/session 已失效
    ACCESS_BLOCKED = "access_blocked"                    # 站点明确拒绝当前访问
    TIMEOUT = "timeout"                                  # 超时
    NO_SAFE_ACTION = "no_safe_action"                    # 没有可安全执行的下一步
    VERIFICATION_REQUIRED = "verification_required"      # 需要短信/邮箱验证码
    EXTERNAL_IDP_DETECTED = "external_idp_detected"      # 检测到外部统一登录
    UNRECOGNIZED_PAGE = "unrecognized_page"              # 页面已打开但无法可靠识别
    AUTH_ENTRY_NO_AUTH_STATE = "auth_entry_no_auth_state"  # 已点击认证入口但未出现可分类认证状态


class UIType(str, Enum):
    """页面样式分类（队友提供的前端六类，2026-08-05 加入）"""
    STANDALONE_PAGE = "standalone_page"                  # 独立单页（/login /register）
    MODAL = "modal"                                      # 模态框/弹窗（点击后出现，带遮罩）
    DRAWER = "drawer"                                    # 侧边抽屉
    MULTI_STEP_WIZARD = "multi_step_wizard"              # 分步/流式表单
    INLINE_WIDGET = "inline_widget"                      # 嵌入式/浮动挂件（首页 Header 内等）
    SSO_IFRAME = "sso_iframe"                            # 跨域/第三方 OAuth（iframe 或跳转）
    UNKNOWN = "unknown"


@dataclass
class PageState:
    """单个页面状态快照"""
    step: int = 0
    url: str = ""
    ui_type: str = UIType.UNKNOWN.value                       # 页面样式六类
    fields: List[str] = field(default_factory=list)      # 识别到的可见输入框: email/phone/password/code/identifier
    actions: List[str] = field(default_factory=list)     # 执行过的动作: next/submit/click_tab/click_link/none
    blockers: List[str] = field(default_factory=list)    # 阻断因素: captcha/sms_code/email_code/verification_code/slide/scan/app_confirm/tos/other
    methods: List[str] = field(default_factory=list)     # 发现的注册方式: email/phone/sms/sso/wechat/qq/weibo/google/apple
    available_actions: List[str] = field(default_factory=list)  # 当前可见动作: next/send_code/submit/external_sso
    tabs: List[str] = field(default_factory=list)          # 表单内 tab: password_tab/password_signup_tab/sms_tab/email_tab/register_tab
    note: str = ""


@dataclass
class FlowResult:
    """单个网站的测量结果（JSON 输出结构）"""
    site: str = ""
    entry_kind: str = "signup"                             # signup=注册流程 / login=登录流程
    start_url: str = ""
    final_url: str = ""
    flow_type: str = FlowType.UNKNOWN.value
    ui_type: str = UIType.UNKNOWN.value                       # 页面样式（取状态序列中最常见的非 unknown）
    primary_method: str = ""                              # 主方式：password/email/phone/sms/sso/email_only/unknown
    confidence: str = "low"                               # high/medium/low
    states: List[PageState] = field(default_factory=list)
    stop_reason: str = StopReason.MAX_STEPS_REACHED.value
    evidence: List[str] = field(default_factory=list)     # 证据（截图路径/说明）
    policy: Dict[str, object] = field(default_factory=dict)  # 标准化政策摘要（由 finalize 生成）
    timings: Dict[str, float] = field(default_factory=dict)  # navigation/wait/detection/classification/total
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        import json
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
