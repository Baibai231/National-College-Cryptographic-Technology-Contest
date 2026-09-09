"""Collection facade for passive authentication-security observations."""

from __future__ import annotations

from security_observers.jwt import analyze_jwt_metadata
from security_observers.maturity import build_cpam_maturity
from security_observers.mfa import analyze_mfa_evidence
from security_observers.oauth import analyze_oauth_urls
from security_observers.recovery import analyze_recovery_signals
from security_observers.scoring import build_security_assessment
from security_observers.session import analyze_cookie_posture
from security_observers.transport import analyze_network_security
from security_observers.webauthn import analyze_webauthn_signals


_PAGE_SNAPSHOT_SCRIPT = r"""
return (() => {
  const roots = [document], seenRoots = new Set();
  const visible = node => {
    try {
      const rect = node.getBoundingClientRect();
      const view = node.ownerDocument.defaultView || window;
      const style = view.getComputedStyle(node);
      return rect.width > 0 && rect.height > 0 && style.display !== 'none' &&
        style.visibility !== 'hidden';
    } catch (_) { return false; }
  };
  for (let index = 0; index < roots.length && index < 100; index++) {
    const root = roots[index];
    if (!root || seenRoots.has(root)) continue;
    seenRoots.add(root);
    for (const node of root.querySelectorAll('*')) {
      if (node.shadowRoot) roots.push(node.shadowRoot);
    }
    for (const frame of root.querySelectorAll('iframe')) {
      try {
        if (visible(frame) && frame.contentDocument) roots.push(frame.contentDocument);
      } catch (_) {}
    }
  }

  const urls = [];
  for (const root of roots) {
    for (const node of root.querySelectorAll('a[href],form[action]')) {
      if (urls.length >= 500) break;
      try {
        const value = node.href || node.action || '';
        if (value) urls.push(String(value).slice(0, 8192));
      } catch (_) {}
    }
  }

  const recovery = {
    entry_count: 0, same_origin_target_count: 0,
    cross_origin_target_count: 0, https_target_count: 0,
    http_target_count: 0, channel_hints: []
  };
  const recoveryChannels = new Set();
  const recoveryText = /忘记密码|忘了密码|找回密码|重置密码|密码找回|无法登录|forgot\s+(?:your\s+)?password|reset\s+password|password\s+reset|recover\s+(?:your\s+)?password|can't\s+(?:log|sign)\s+in/i;
  const recoveryPath = /\/(?:forgot|recover|reset)[-_/]?(?:password|passwd|account)|\/(?:password|passwd)[-_/]?(?:forgot|recover|reset)/i;
  for (const root of roots) {
    for (const node of root.querySelectorAll("a,button,[role='button'],form")) {
      if (recovery.entry_count >= 100 || !visible(node) || node.closest('article')) continue;
      const label = String(node.innerText || node.textContent ||
        node.getAttribute('aria-label') || node.getAttribute('title') || '')
        .replace(/\s+/g, ' ').trim().slice(0, 160);
      const rawTarget = node.href || node.action || node.getAttribute('href') ||
        node.getAttribute('action') || '';
      let target = null;
      try { if (rawTarget) target = new URL(rawTarget, location.href); } catch (_) {}
      // 普通登录 form 会包含“忘记密码”子按钮；只计按钮/链接本身，
      // form 只有 action 明确指向恢复路径时才单独计数，避免父子重复。
      const labelMatches = node.tagName !== 'FORM' && recoveryText.test(label);
      if (!labelMatches && !(target && recoveryPath.test(target.pathname))) continue;
      recovery.entry_count++;
      if (target) {
        if (target.origin === location.origin) recovery.same_origin_target_count++;
        else recovery.cross_origin_target_count++;
        if (target.protocol === 'https:') recovery.https_target_count++;
        else if (target.protocol === 'http:') recovery.http_target_count++;
      }
      const nearby = String(node.closest('form')?.innerText ||
        node.parentElement?.innerText || label).slice(0, 500);
      if (/邮箱|邮件|email|e-mail|mail/i.test(nearby)) recoveryChannels.add('email');
      if (/手机|短信|手机号|phone|mobile|sms/i.test(nearby)) recoveryChannels.add('sms_or_phone');
      if (/客服|人工|申诉|support|help\s*desk|contact/i.test(nearby)) recoveryChannels.add('support_or_manual');
    }
  }
  recovery.channel_hints = Array.from(recoveryChannels).sort();

  const jwtMetadata = [];
  function decodePart(part) {
    const normalized = part.replace(/-/g, '+').replace(/_/g, '/');
    const padded = normalized + '='.repeat((4 - normalized.length % 4) % 4);
    return JSON.parse(atob(padded));
  }
  function inspectStorage(storage, source) {
    if (!storage) return;
    const limit = Math.min(storage.length, 200);
    for (let index = 0; index < limit; index++) {
      try {
        const value = storage.getItem(storage.key(index));
        if (typeof value !== 'string' || value.length > 20000) continue;
        const parts = value.split('.');
        if (parts.length !== 3 || !/^eyJ[A-Za-z0-9_-]+$/.test(parts[0]) ||
            !/^eyJ[A-Za-z0-9_-]+$/.test(parts[1])) continue;
        const header = decodePart(parts[0]);
        const claims = decodePart(parts[1]);
        jwtMetadata.push({
          source,
          algorithm: typeof header.alg === 'string' ? header.alg.slice(0, 24) : 'unknown',
          expiration_claim: Object.prototype.hasOwnProperty.call(claims, 'exp'),
          issuer_claim: Object.prototype.hasOwnProperty.call(claims, 'iss'),
          audience_claim: Object.prototype.hasOwnProperty.call(claims, 'aud'),
          signature_segment_present: parts[2].length > 0
        });
      } catch (_) {}
    }
  }
  try { inspectStorage(window.localStorage, 'local_storage'); } catch (_) {}
  try { inspectStorage(window.sessionStorage, 'session_storage'); } catch (_) {}

  let text = '';
  try {
    text = roots.map(root => String(root.body ? root.body.innerText : root.textContent || ''))
      .join(' ').slice(0, 100000);
  } catch (_) {}
  let autocompleteWebauthn = false;
  try {
    autocompleteWebauthn = roots.some(root =>
      Array.from(root.querySelectorAll('[autocomplete]')).some(node =>
        String(node.getAttribute('autocomplete') || '').toLowerCase()
          .split(/\s+/).includes('webauthn')));
  } catch (_) {}
  let navigation = {};
  try {
    const entry = performance.getEntriesByType('navigation')[0];
    if (entry) navigation = {
      next_hop_protocol: String(entry.nextHopProtocol || '').slice(0, 64),
      redirect_count: Number.isFinite(entry.redirectCount) ? entry.redirectCount : 0
    };
  } catch (_) {}
  return {
    urls,
    jwt_metadata: jwtMetadata,
    navigation,
    recovery,
    webauthn: {
      public_key_credential_api: typeof window.PublicKeyCredential === 'function',
      autocomplete_webauthn: autocompleteWebauthn,
      passkey_text_hint: /passkey|security\s*key|通行密钥|通行金钥|安全密钥|安全金钥/i.test(text)
    }
  };
})();
"""


def collect_security_observations(driver, *, states=None, methods=None) -> dict:
    """Collect a best-effort, non-interactive security observation bundle.

    Failures are represented as unavailable evidence and never fail the parent
    authentication classification.
    """
    errors = []
    snapshot = {}
    page_url = ""
    cookies = []
    performance_events = []
    try:
        page_url = str(driver.current_url or "")
    except Exception as exc:
        errors.append("current_url:{}".format(type(exc).__name__))
    try:
        snapshot = driver.execute_script(_PAGE_SNAPSHOT_SCRIPT) or {}
        if not isinstance(snapshot, dict):
            snapshot = {}
    except Exception as exc:
        errors.append("page_snapshot:{}".format(type(exc).__name__))
    try:
        cookies = driver.get_cookies() or []
    except Exception as exc:
        errors.append("cookies:{}".format(type(exc).__name__))
    try:
        performance_events = driver.get_log("performance") or []
        if not isinstance(performance_events, list):
            performance_events = []
    except Exception as exc:
        errors.append("performance_log:{}".format(type(exc).__name__))

    oauth = analyze_oauth_urls(snapshot.get("urls") or [])
    jwt = analyze_jwt_metadata(snapshot.get("jwt_metadata") or [])
    webauthn = analyze_webauthn_signals(snapshot.get("webauthn") or {})
    recovery = analyze_recovery_signals(snapshot.get("recovery") or {})
    mfa = analyze_mfa_evidence(states or [], methods or [], webauthn)
    session = analyze_cookie_posture(cookies, page_url)
    network = analyze_network_security(
        performance_events, page_url, snapshot.get("navigation") or {})
    analyzers = {
        "oauth_oidc": oauth,
        "jwt": jwt,
        "webauthn": webauthn,
        "mfa": mfa,
        "account_recovery": recovery,
        "session_cookies": session,
        "transport_security": network["transport_security"],
        "http_security_headers": network["http_security_headers"],
    }
    observed = [name for name, report in analyzers.items()
                if report.get("status") == "observed"]
    capabilities = [name for name in (
        "oauth_oidc", "webauthn", "mfa", "account_recovery",
    )
                    if analyzers[name].get("status") == "observed"]
    return {
        "schema_version": "1.0",
        "collection_mode": "passive",
        "evidence_boundary": "current_safely_reachable_pre_authentication_page",
        "observed_capabilities": capabilities,
        "observers_with_evidence": observed,
        "analyzers": analyzers,
        "assessment": build_security_assessment(analyzers),
        "maturity": build_cpam_maturity(analyzers),
        "collection_errors": errors,
        "privacy": {
            "raw_tokens_stored": False,
            "raw_cookie_values_stored": False,
            "authorization_followed": False,
            "verification_message_sent": False,
            "recovery_flow_followed": False,
            "extra_network_request_sent": False,
            "raw_urls_stored": False,
            "raw_header_values_stored": False,
            "raw_certificates_stored": False,
        },
    }
