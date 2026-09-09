"""WebAuthn/passkey capability observations from the current page."""

from __future__ import annotations


def analyze_webauthn_signals(signals) -> dict:
    signals = signals if isinstance(signals, dict) else {}
    api = bool(signals.get("public_key_credential_api"))
    autocomplete = bool(signals.get("autocomplete_webauthn"))
    text_hint = bool(signals.get("passkey_text_hint"))
    observed = autocomplete or text_hint
    return {
        "status": "observed" if observed else "not_observed",
        "confidence": "high" if autocomplete else ("medium" if text_hint else "low"),
        "browser_api_available": api,
        "autocomplete_webauthn_observed": autocomplete,
        "passkey_or_security_key_text_observed": text_hint,
        # Browser API availability describes the browser, not the website.
        "site_capability_observed": observed,
        "registration_or_signature_verified": False,
        "evidence_boundary": "current_page_dom_only",
    }
