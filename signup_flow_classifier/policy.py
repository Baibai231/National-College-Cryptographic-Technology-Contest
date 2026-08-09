"""把页面状态序列归一成可统计、且不夸大证据的 policy 字段。"""
from typing import Iterable


PASSWORD_FLOWS = {
    "direct_password", "identifier_then_password", "verification_then_password"
}
PASSWORDLESS_OBSERVED_FLOWS = {"otp_only", "email_only", "sso_only"}


def _value(state, key: str):
    return state.get(key, []) if isinstance(state, dict) else getattr(state, key, [])


def summarize_policy(entry_kind: str, flow_type: str, confidence: str,
                     stop_reason: str, states: Iterable[object]) -> dict:
    states = list(states)
    fields = {item for state in states for item in _value(state, "fields")}
    blockers = {item for state in states for item in _value(state, "blockers")}
    methods = {item for state in states for item in _value(state, "methods")}
    tabs = {item for state in states for item in _value(state, "tabs")}

    password_observed = "password" in fields
    verification_blockers = {"sms_code", "email_code", "verification_code"}
    verification_observed = "code" in fields or bool(
        verification_blockers & blockers
    )
    if password_observed or flow_type in PASSWORD_FLOWS:
        password_status = "password_observed"
    elif flow_type in PASSWORDLESS_OBSERVED_FLOWS:
        password_status = "no_password_in_safely_reachable_flow"
    else:
        password_status = "not_determined"

    if flow_type == "unknown":
        measurement_status = "unknown"
    elif flow_type == "human_blocked" or blockers:
        measurement_status = "blocked_or_partial"
    else:
        measurement_status = "classified"

    observed_methods = []
    if password_observed:
        observed_methods.append("password")
    if "sms_code" in blockers or "phone" in fields or "sms_tab" in tabs:
        observed_methods.append("sms_or_otp")
    elif "email_code" in blockers:
        observed_methods.append("email_otp")
    elif verification_observed:
        observed_methods.append("one_time_code")
    if "scan" in blockers:
        observed_methods.append("qr_or_scan")
    if "sso" in methods or methods & {"wechat", "qq", "weibo", "google", "apple", "github"}:
        observed_methods.append("third_party")
    if "email" in fields:
        observed_methods.append("email")
    if "phone" in fields:
        observed_methods.append("phone")

    return {
        "schema_version": "1.0",
        "scope": entry_kind,
        "measurement": {
            "status": measurement_status,
            "confidence": confidence,
            "stop_reason": stop_reason,
            "evidence_boundary": (
                "pre_verification_only" if verification_observed else "safely_reachable_ui"
            ),
        },
        "authentication": {
            "observed_methods": list(dict.fromkeys(observed_methods)),
            "password_status": password_status,
            "password_observed": password_observed,
            "verification_observed": verification_observed,
            "phone_observed": "phone" in fields,
            "identifier_observed": bool(fields & {"identifier", "email"}),
            "blocking_factors": sorted(blockers),
        },
        "security": {
            "status": "not_observed_by_flow_classifier",
            "note": "use login_policy_observer for passive transport and input checks",
        },
    }
