"""Passive account/password-recovery entry analysis."""

from __future__ import annotations


_CHANNELS = {"email", "sms_or_phone", "support_or_manual"}


def _count(value, maximum=500):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(0, min(maximum, int(value)))


def analyze_recovery_signals(signals) -> dict:
    """Sanitize already-visible recovery metadata without following a flow."""
    signals = signals if isinstance(signals, dict) else {}
    entry_count = _count(signals.get("entry_count"))
    channels = sorted({
        str(item) for item in (signals.get("channel_hints") or [])
        if str(item) in _CHANNELS
    })
    same_origin = _count(signals.get("same_origin_target_count"), entry_count)
    cross_origin = _count(signals.get("cross_origin_target_count"), entry_count)
    https_targets = _count(signals.get("https_target_count"), entry_count)
    http_targets = _count(signals.get("http_target_count"), entry_count)
    target_count = min(entry_count, same_origin + cross_origin)
    findings = []
    recommendations = []
    if http_targets:
        findings.append("http_recovery_target_observed")
        recommendations.append("verify_recovery_target_redirects_to_https")

    return {
        "status": "observed" if entry_count else "not_observed",
        "confidence": (
            "high" if entry_count and target_count
            else ("medium" if entry_count else "low")
        ),
        "recovery_entry_count": entry_count,
        "same_origin_target_count": same_origin,
        "cross_origin_target_count": cross_origin,
        "https_target_count": https_targets,
        "http_target_count": http_targets,
        "channel_hints": channels,
        "findings": findings,
        "recommendations": recommendations,
        "flow_followed": False,
        "message_sent": False,
        "reset_token_validated": False,
        "original_password_disclosure_tested": False,
        "raw_urls_stored": False,
        "evidence_boundary": "visible_recovery_entry_metadata_only",
    }
