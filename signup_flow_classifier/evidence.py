"""证据记录：结构化保存测量过程（阶段 3）

安全边界：不保存真实手机号/验证码/Cookie/口令；
截图仅用于本地调试，默认关闭。
"""
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from selenium.webdriver.remote.webdriver import WebDriver

from signup_flow_classifier.flow_types import FlowResult


def _stable_url(url: str) -> str:
    """Return a navigation identity without tokens or tracking parameters.

    A few query keys are themselves the route (``?reg`` versus ``?login``), so
    they must remain distinct.  Only an allowlisted set of authentication-view
    keys is retained; all other keys and every fragment are dropped.
    """
    try:
        parsed = urlsplit(url or "")
        route_keys = {
            "action", "flow", "login", "mode", "reg", "register", "signin",
            "signup", "tab", "type", "view",
        }
        route_query = []
        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            if key.lower() not in route_keys:
                continue
            # Route values are labels rather than user data. Limit the alphabet
            # and length; otherwise retaining the key alone is sufficient.
            safe_value = value.lower() if (
                len(value) <= 40
                and all(ch.isalnum() or ch in "_-" for ch in value)
            ) else ""
            route_query.append((key.lower(), safe_value))
        return urlunsplit((
            parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/",
            urlencode(sorted(route_query)), "",
        ))
    except Exception:
        return url or ""


def semantic_state_key(state) -> tuple:
    """Build a privacy-preserving identity for one authentication UI state.

    Action history and free-form notes are deliberately excluded: they describe
    how the crawler arrived at a page, not what the page currently exposes.
    Query strings are excluded because authentication pages commonly rotate
    tracking/nonces while leaving the usable UI unchanged.
    """
    return (
        _stable_url(getattr(state, "url", "")),
        getattr(state, "ui_type", "unknown") or "unknown",
        tuple(sorted(set(getattr(state, "fields", []) or []))),
        tuple(sorted(set(getattr(state, "blockers", []) or []))),
        tuple(sorted(set(getattr(state, "methods", []) or []))),
        tuple(sorted(set(getattr(state, "available_actions", []) or []))),
        tuple(sorted(set(getattr(state, "tabs", []) or []))),
    )


def record_step(result: FlowResult, state):
    """Record a state once and return the canonical mutable state object.

    Real authentication widgets frequently oscillate between the same SMS and
    password views while alternative tabs are explored.  Repeated snapshots
    used to inflate routes and confidence.  Keep the first snapshot, attach
    later actions to it, and retain an explicit revisit evidence item.
    """
    key = semantic_state_key(state)
    for existing in result.states:
        if semantic_state_key(existing) == key:
            result.evidence.append(
                "step={};state_revisit_of={}".format(
                    getattr(state, "step", 0), getattr(existing, "step", 0)
                )
            )
            return existing
    result.states.append(state)
    return state


def record_evidence(result: FlowResult, item: str) -> None:
    """追加一条证据说明。"""
    result.evidence.append(item)


def maybe_screenshot(driver: WebDriver, result: FlowResult, path: str, enabled: bool = False) -> None:
    """可选截图（默认关闭；本地调试时开启）。"""
    if not enabled:
        return
    try:
        driver.save_screenshot(path)
        record_evidence(result, f"screenshot:{path}")
    except Exception as e:
        record_evidence(result, f"screenshot_error:{e}")


def finalize(result: FlowResult, flow_type: str, confidence: str, stop_reason: str,
             error: Optional[str] = None) -> FlowResult:
    """填充分类结论并返回（自动聚合 ui_type 与 v4 逐方法清单）。"""
    result.flow_type = flow_type
    result.confidence = confidence
    result.stop_reason = stop_reason
    result.error = error
    from signup_flow_classifier.classifier import aggregate_methods
    result.methods = aggregate_methods(result.states, flow_type=flow_type)
    from signup_flow_classifier.policy import summarize_policy
    result.policy = summarize_policy(
        result.entry_kind, flow_type, confidence, stop_reason, result.states
    )
    if not result.ui_type or result.ui_type == "unknown":
        counts: dict = {}
        for state in result.states:
            if state.ui_type and state.ui_type != "unknown":
                counts[state.ui_type] = counts.get(state.ui_type, 0) + 1
        if counts:
            result.ui_type = max(counts, key=counts.get)
    return result
