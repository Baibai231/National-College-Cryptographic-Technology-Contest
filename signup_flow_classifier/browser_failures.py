"""浏览器与访问故障分型。

把 Chrome/session 故障、网络基础设施故障和站点明确拒绝访问从普通
``unknown`` 中拆开。此模块只读取异常文本与页面标题/正文，不执行交互。
"""
from typing import Optional

from selenium.common.exceptions import (
    InvalidSessionIdException,
    NoSuchWindowException,
    SessionNotCreatedException,
    TimeoutException,
)

from signup_flow_classifier.flow_types import StopReason


_BROWSER_CRASH_MARKERS = (
    "invalid session id",
    "session deleted because of page crash",
    "chrome not reachable",
    "not connected to devtools",
    "disconnected: not connected",
    "target window already closed",
    "web view not found",
    "tab crashed",
)

_INFRASTRUCTURE_MARKERS = (
    "err_proxy_connection_failed",
    "err_tunnel_connection_failed",
    "err_name_not_resolved",
    "err_connection_refused",
    "err_connection_reset",
    "err_internet_disconnected",
    "net::err_timed_out",
)

_ACCESS_ERROR_MARKERS = (
    "err_blocked_by_client",
    "err_blocked_by_response",
    "err_access_denied",
)

_ACCESS_PAGE_MARKERS = (
    "403 forbidden",
    "access denied",
    "request blocked",
    "your request has been blocked",
    "您的访问被拒绝",
    "请求被拒绝",
    "禁止访问",
    "当前访问疑似异常",
    # 百度系整页安全验证（贴吧/百度首页实测）：整页滑块验证不是
    # 局部验证码组件，属于访问阻断。
    "百度安全验证",
    "请完成下方验证后继续操作",
    "请向右滑动完成拼图",
)

# 目标站反爬重定向的典型跳转域名；被重定向到这些站点说明不是正常认证页。
_ACCESS_REDIRECT_HOSTS = (
    "beian.mps.gov.cn",
)

_CHALLENGE_FRAME_MARKERS = (
    "captcha", "geetest", "challenge", "security-check", "verify",
    "验证码", "安全验证",
)

_CHALLENGE_URL_MARKERS = (
    "/captcha", "captcha-", "-captcha", "/challenge", "/security-check",
    "/general_page",
)

_HUMAN_CHALLENGE_MARKERS = (
    "百度安全验证", "请完成下方验证后继续操作", "请向右滑动完成拼图",
    "full_page_captcha", "human_challenge_url",
)

_SERVER_ERROR_PAGE_MARKERS = (
    "internal server error",
    "502 bad gateway",
    "503 service unavailable",
    "504 gateway timeout",
    "upstream connect error",
)


def classify_exception(exc: Exception) -> str:
    """将 WebDriver/网络异常映射为稳定停止原因。"""
    if isinstance(exc, (InvalidSessionIdException, NoSuchWindowException,
                        SessionNotCreatedException)):
        return StopReason.BROWSER_CRASHED.value
    if isinstance(exc, TimeoutException):
        return StopReason.TIMEOUT.value

    text = f"{type(exc).__name__}: {exc}".lower()
    # driver.quit()/Chrome 崩溃后，macOS Selenium 可能只报告本机 driver
    # HTTP 端口拒绝连接，而不是 InvalidSessionIdException。
    if ("httpconnectionpool" in text
            and ("localhost" in text or "127.0.0.1" in text)
            and ("connection refused" in text or "max retries exceeded" in text)):
        return StopReason.BROWSER_CRASHED.value
    if any(marker in text for marker in _BROWSER_CRASH_MARKERS):
        return StopReason.BROWSER_CRASHED.value
    if any(marker in text for marker in _ACCESS_ERROR_MARKERS):
        return StopReason.ACCESS_BLOCKED.value
    if any(marker in text for marker in _INFRASTRUCTURE_MARKERS):
        return StopReason.INFRASTRUCTURE_ERROR.value
    return StopReason.NAVIGATION_ERROR.value


def detect_access_block(driver) -> Optional[str]:
    """保守识别站点明确的拒绝访问页，返回脱敏命中原因。"""
    # 反爬重定向：当前 URL 已跳到备案查询等第三方拦截站
    try:
        current_host = ""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(driver.current_url)
            current_host = parsed.hostname or ""
            current_path = (parsed.path or "").lower()
        except Exception:
            pass
        if any(host in (current_host or "") for host in _ACCESS_REDIRECT_HOSTS):
            return f"redirect_to_{current_host}"
        host_label = (current_host.split(".", 1)[0] if current_host else "")
        if (host_label in {"verify", "captcha", "challenge"}
                or any(marker in current_path for marker in _CHALLENGE_URL_MARKERS)):
            return "human_challenge_url"
    except Exception:
        pass
    try:
        payload = driver.execute_script(
            "const vis=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);"
            "return r.width>0&&r.height>0&&r.bottom>0&&r.right>0"
            "&&r.top<innerHeight&&r.left<innerWidth"
            "&&s.display!=='none'&&s.visibility!=='hidden'};"
            "return {title: document.title || '', "
            "text: (document.body?.innerText || '').slice(0, 5000),"
            "controls:[...document.querySelectorAll('input,button,a,[role=button]')].filter(vis).length,"
            "frames:[...document.querySelectorAll('iframe')].filter(vis).map(f=>"
            "[f.src||'',f.title||'',Math.round(f.getBoundingClientRect().width),"
            "Math.round(f.getBoundingClientRect().height)])};"
        ) or {}
    except Exception:
        return None
    text = f"{payload.get('title', '')}\n{payload.get('text', '')}".lower()
    for marker in _ACCESS_PAGE_MARKERS:
        if marker in text:
            return marker
    # 风控页可能把所有可见内容放进跨域 captcha iframe，主文档完全空白。
    # 仅在主页面几乎无正文、无其他交互控件时认定为整页访问挑战；普通页面
    # 常驻的隐藏/局部验证码组件不会触发（学堂在线、看雪的实测反例）。
    compact_text = " ".join(text.split())
    if len(compact_text) <= 80 and not payload.get("controls"):
        for src, title, width, height in payload.get("frames", []):
            semantic = f"{src} {title}".lower()
            if (width >= 100 and height >= 100
                    and any(marker in semantic for marker in _CHALLENGE_FRAME_MARKERS)):
                return "full_page_captcha"
    return None


def is_human_challenge_marker(marker: str) -> bool:
    """Distinguish a solvable human gate from a generic access denial."""
    return any(value in (marker or "") for value in _HUMAN_CHALLENGE_MARKERS)


def detect_server_error_page(driver) -> Optional[str]:
    """保守识别服务器/上游网关故障页。

    只在标题命中，或者极短正文就是标准错误语时返回，避免把
    新闻/技术文章中提到的“Internal Server Error”误判为故障。
    """
    try:
        payload = driver.execute_script(
            "return {title: document.title || '', "
            "text: (document.body?.innerText || '').trim().slice(0, 500)};"
        ) or {}
    except Exception:
        return None
    title = str(payload.get("title", "")).strip().lower()
    body = " ".join(str(payload.get("text", "")).lower().split())
    for marker in _SERVER_ERROR_PAGE_MARKERS:
        if marker in title or (len(body) <= 200 and marker in body):
            return marker
    return None


def detect_blank_auth_page(driver) -> Optional[str]:
    """识别认证 URL 只有标题/空 app 壳、无任何可见内容的渲染失败。

    限定在 login/register/passport 等明确认证路径，并且同时要求
    无正文、无可见交互控件、无 iframe/canvas，避免将正常极简页面
    或二维码页误判为故障。
    """
    try:
        payload = driver.execute_script(
            "const vis=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);"
            "return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'};"
            "return {url:location.href,title:document.title||'',"
            "text:(document.body?.innerText||'').trim(),"
            "visible:[...document.querySelectorAll("
            "'input,button,a,[role=button],[role=dialog],iframe,canvas,svg')].filter(vis).length};"
        ) or {}
    except Exception:
        return None
    url = str(payload.get("url", "")).lower()
    auth_url = any(
        hint in url for hint in (
            "login", "signin", "sign-in", "register", "signup",
            "passport", "/auth", "/account",
        )
    )
    if (auth_url and payload.get("title")
            and not str(payload.get("text", "")).strip()
            and not payload.get("visible")):
        return "blank_auth_document"
    return None


def is_retryable_browser_failure(reason: str) -> bool:
    return reason == StopReason.BROWSER_CRASHED.value
