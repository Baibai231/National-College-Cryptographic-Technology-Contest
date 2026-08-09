"""证据记录：结构化保存测量过程（阶段 3）

安全边界：不保存真实手机号/验证码/Cookie/口令；
截图仅用于本地调试，默认关闭。
"""
from typing import List, Optional

from selenium.webdriver.remote.webdriver import WebDriver

from signup_flow_classifier.flow_types import FlowResult


def record_step(result: FlowResult, state) -> None:
    """把一步的页面状态追加进结果。"""
    result.states.append(state)


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
    """填充分类结论并返回（自动聚合 ui_type：取状态序列中最常见的非 unknown 样式）。"""
    result.flow_type = flow_type
    result.confidence = confidence
    result.stop_reason = stop_reason
    result.error = error
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
