"""Collection facade for passive authentication-security observations."""

from __future__ import annotations

from security_observers.jwt import analyze_jwt_metadata
from security_observers.maturity import build_cpam_maturity
from security_observers.mfa import analyze_mfa_evidence
from security_observers.oauth import analyze_oauth_urls
from security_observers.scoring import build_security_assessment
from security_observers.session import analyze_cookie_posture
from security_observers.transport import analyze_network_security
from security_observers.webauthn import analyze_webauthn_signals


_PAGE_SNAPSHOT_SCRIPT = r"""
return (() => {
  const urls = [];
  for (const node of Array.from(document.querySelectorAll('a[href],form[action]')).slice(0, 500)) {
    try {
      const value = node.href || node.action || '';
      if (value) urls.push(String(value).slice(0, 8192));
    } catch (_) {}
  }

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
  try { text = String(document.body ? document.body.innerText : '').slice(0, 100000); } catch (_) {}
  let autocompleteWebauthn = false;
  try {
    autocompleteWebauthn = Array.from(document.querySelectorAll('[autocomplete]')).some(node =>
      String(node.getAttribute('autocomplete') || '').toLowerCase().split(/\s+/).includes('webauthn'));
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
    mfa = analyze_mfa_evidence(states or [], methods or [], webauthn)
    session = analyze_cookie_posture(cookies, page_url)
    network = analyze_network_security(
        performance_events, page_url, snapshot.get("navigation") or {})
    analyzers = {
        "oauth_oidc": oauth,
        "jwt": jwt,
        "webauthn": webauthn,
        "mfa": mfa,
        "session_cookies": session,
        "transport_security": network["transport_security"],
        "http_security_headers": network["http_security_headers"],
    }
    observed = [name for name, report in analyzers.items()
                if report.get("status") == "observed"]
    capabilities = [name for name in ("oauth_oidc", "webauthn", "mfa")
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
            "extra_network_request_sent": False,
            "raw_urls_stored": False,
            "raw_header_values_stored": False,
            "raw_certificates_stored": False,
        },
    }
