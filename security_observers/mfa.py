"""Conservative authentication-factor summary based on classifier evidence."""

from __future__ import annotations


_PROVIDERS = {
    "sso", "wechat", "qq", "weibo", "google", "apple", "github",
    "gitee", "microsoft", "baidu", "dingtalk", "douyin", "xiaohongshu",
    "alipay", "taobao", "xiaomi", "huawei", "solana",
}


def _items(state, key: str):
    if isinstance(state, dict):
        return state.get(key) or []
    return getattr(state, key, []) or []


def analyze_mfa_evidence(states, methods, webauthn=None) -> dict:
    states = list(states or [])
    method_names = {
        str(item.get("method")) if isinstance(item, dict) else str(getattr(item, "method", ""))
        for item in (methods or [])
    }
    fields = {item for state in states for item in _items(state, "fields")}
    blockers = {item for state in states for item in _items(state, "blockers")}
    state_methods = {item for state in states for item in _items(state, "methods")}
    all_methods = method_names | state_methods

    capabilities = []
    if "password" in fields or "password" in all_methods:
        capabilities.append("password")
    if "sms" in all_methods or "sms_code" in blockers or (
            "code" in fields and "phone" in fields):
        capabilities.append("sms_otp")
    if "email_code" in blockers or (
            "code" in fields and "email" in fields and "sms_code" not in blockers):
        capabilities.append("email_otp")
    if "qr" in all_methods or "scan" in blockers:
        capabilities.append("qr_or_app_confirmation")
    if all_methods & _PROVIDERS:
        capabilities.append("federated_identity")
    if isinstance(webauthn, dict) and webauthn.get("site_capability_observed"):
        capabilities.append("webauthn_or_passkey")

    return {
        "status": "observed" if capabilities else "not_observed",
        "confidence": "medium" if capabilities else "low",
        "factor_capabilities": list(dict.fromkeys(capabilities)),
        "multiple_authentication_methods_observed": len(set(capabilities)) >= 2,
        # Safe exploration does not complete a login, OTP, or WebAuthn ceremony.
        # Parallel login choices must never be reported as enforced MFA.
        "mfa_enforcement": "not_determined",
        "completed_multi_factor_sequence": False,
        "evidence_boundary": "pre_authentication_ui_only",
    }
