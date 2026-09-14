"""Guarded Passkey-control interaction backed by an empty virtual authenticator.

This module is intentionally narrower than a generic browser clicker.  It only
clicks one exact, operator-approved Passkey label on an approved HTTPS host.
The WebAuthn domain is redirected to a fresh virtual authenticator containing
zero credentials, and public-key credential creation is blocked before any
site document runs.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlsplit

from application_security.models import (
    Claim,
    Evidence,
    EvidenceLevel,
    ModuleManifest,
    ModuleResult,
    ScanMode,
    Verdict,
)
from application_security.paper_registry import (
    FIDO2_IEEE_SP_2023,
    PASSKEYS_USENIX_2026,
    WEBAUTHN_LEVEL_3,
)


WEBAUTHN_SAFE_INTERACTION_MANIFEST = ModuleManifest(
    module_id="b.webauthn_safe_interaction",
    name_zh="WebAuthn虚拟认证器受控触发探针",
    research_question=(
        "在不提供账号、不预置凭据和不使用真实认证器时，公开页上"
        "明确的Passkey登录控件是否真正触发WebAuthn认证仪式？"
    ),
    crypto_elements=(
        "webauthn_authentication_ceremony",
        "virtual_ctap2_authenticator",
        "challenge_and_rp_request_observation",
        "user_presence_and_user_verification_emulation",
    ),
    paper_refs=(PASSKEYS_USENIX_2026, FIDO2_IEEE_SP_2023),
    standard_refs=(WEBAUTHN_LEVEL_3,),
    safe_modes=(ScanMode.SAFE_INTERACTION,),
    limitations=(
        "只允许操作者预先白名单的HTTPS主机和精确Passkey登录文本，每轮最多点1次。",
        "虚拟认证器不预置凭据；无匹配凭据时认证应失败，不尝试登录成功。",
        "注册create在文档脚本之前被拒绝，防止意外创建虚拟凭据或回传注册响应。",
        "只保留脱敏WebAuthn请求摘要和计数；不保存challenge、RP ID、credential ID或认证器响应。",
        "PASS只表示控件到认证请求的触发链可观察，不证明服务端验签、账号绑定或恢复安全。",
    ),
)


BLOCK_PUBLIC_KEY_CREATE_SCRIPT = r"""
(()=>{
  'use strict';
  const MARK='__cryptoscopeBlockWebAuthnRegistrationV1';
  if(globalThis[MARK])return;
  try{Object.defineProperty(globalThis,MARK,{value:true,configurable:false});}
  catch(e){return;}
  try{
    const credentials=navigator&&navigator.credentials;
    if(!credentials||typeof credentials.create!=='function')return;
    const original=credentials.create;
    const blocked=function(options){
      try{
        if(options&&typeof options==='object'&&options.publicKey){
          return Promise.reject(new DOMException(
            'Public-key registration disabled by measurement safety guard',
            'NotAllowedError'));
        }
      }catch(e){}
      return Reflect.apply(original,credentials,[options]);
    };
    Object.defineProperty(credentials,'create',{
      value:blocked,writable:true,configurable:true
    });
  }catch(e){}
})();
"""


def install_registration_blocker(driver) -> Tuple[str, ...]:
    """Install the create blocker before navigation and in the current document."""
    errors = []
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": BLOCK_PUBLIC_KEY_CREATE_SCRIPT,
        })
    except Exception as exc:
        errors.append("registration_blocker_registration_failed:" + type(exc).__name__)
    try:
        result = driver.execute_cdp_cmd("Runtime.evaluate", {
            "expression": BLOCK_PUBLIC_KEY_CREATE_SCRIPT,
            "returnByValue": True,
        })
        if isinstance(result, dict) and result.get("exceptionDetails"):
            errors.append("registration_blocker_current_document_failed")
    except Exception as exc:
        errors.append("registration_blocker_current_document_failed:" + type(exc).__name__)
    return tuple(errors)


def add_empty_virtual_authenticator(driver) -> Tuple[Optional[str], Optional[int], Tuple[str, ...]]:
    """Enable WebAuthn interception and return an empty authenticator handle.

    Credential objects returned by CDP are never returned to the caller; only
    their count crosses this function boundary.
    """
    errors = []
    authenticator_id: Optional[str] = None
    credential_count: Optional[int] = None
    try:
        driver.execute_cdp_cmd("WebAuthn.enable", {"enableUI": False})
        response = driver.execute_cdp_cmd("WebAuthn.addVirtualAuthenticator", {
            "options": {
                "protocol": "ctap2",
                "ctap2Version": "ctap2_1",
                "transport": "internal",
                "hasResidentKey": True,
                "hasUserVerification": True,
                "automaticPresenceSimulation": True,
                "isUserVerified": True,
            },
        })
        value = response.get("authenticatorId") if isinstance(response, dict) else None
        if not isinstance(value, str) or not value:
            raise RuntimeError("missing authenticator id")
        authenticator_id = value
        credential_count = virtual_credential_count(driver, authenticator_id)
        if credential_count != 0:
            errors.append("virtual_authenticator_not_empty")
    except Exception as exc:
        errors.append("virtual_authenticator_setup_failed:" + type(exc).__name__)
    return authenticator_id, credential_count, tuple(errors)


def virtual_credential_count(driver, authenticator_id: Optional[str]) -> Optional[int]:
    if not authenticator_id:
        return None
    try:
        response = driver.execute_cdp_cmd("WebAuthn.getCredentials", {
            "authenticatorId": authenticator_id,
        })
        values = response.get("credentials") if isinstance(response, dict) else None
        return len(values) if isinstance(values, list) else None
    except Exception:
        return None


def remove_virtual_authenticator(driver, authenticator_id: Optional[str]) -> Tuple[str, ...]:
    errors = []
    if authenticator_id:
        try:
            driver.execute_cdp_cmd("WebAuthn.removeVirtualAuthenticator", {
                "authenticatorId": authenticator_id,
            })
        except Exception as exc:
            errors.append("virtual_authenticator_remove_failed:" + type(exc).__name__)
    try:
        driver.execute_cdp_cmd("WebAuthn.disable", {})
    except Exception as exc:
        errors.append("webauthn_disable_failed:" + type(exc).__name__)
    return tuple(errors)


def _normalized_label(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", " ", value).strip().casefold()


def click_exact_passkey_control(
    driver,
    *,
    allowed_host: str,
    expected_labels: Sequence[str],
) -> Dict[str, Any]:
    """Click exactly one visible enabled approved control, or do nothing."""
    result: Dict[str, Any] = {
        "host_guard_passed": False,
        "label_match_count": 0,
        "visible_label_match_count": 0,
        "exact_match_count": 0,
        "clicked": False,
        "click_count": 0,
        "control_kind": "",
        "label_value_retained": False,
    }
    try:
        parsed = urlsplit(driver.current_url)
        current_host = (parsed.hostname or "").rstrip(".").lower()
        allowed = allowed_host.rstrip(".").lower()
        if (parsed.scheme != "https" or not current_host
                or not (current_host == allowed or current_host.endswith("." + allowed))):
            result["error"] = "host_guard_failed"
            return result
    except Exception:
        result["error"] = "host_guard_failed"
        return result
    result["host_guard_passed"] = True

    approved = {_normalized_label(item) for item in expected_labels}
    approved.discard("")
    if not approved or len(approved) > 5:
        result["error"] = "invalid_expected_labels"
        return result
    label_matches = 0
    visible_label_matches = 0
    matches = []
    try:
        elements = driver.find_elements(
            "css selector",
            "button,a,[role='button'],input[type='button'],input[type='submit']",
        )
        for element in elements[:500]:
            try:
                candidates = (
                    getattr(element, "text", ""),
                    element.get_attribute("innerText"),
                    element.get_attribute("textContent"),
                    element.get_attribute("aria-label"),
                    element.get_attribute("value"),
                )
                if not any(_normalized_label(value) in approved for value in candidates):
                    continue
                label_matches += 1
                if not element.is_displayed():
                    continue
                visible_label_matches += 1
                if element.is_enabled():
                    matches.append(element)
            except Exception:
                continue
    except Exception as exc:
        result["error"] = "control_enumeration_failed:" + type(exc).__name__
        return result
    result["label_match_count"] = label_matches
    result["visible_label_match_count"] = visible_label_matches
    result["exact_match_count"] = len(matches)
    if len(matches) != 1:
        result["error"] = "exact_control_not_unique"
        return result
    element = matches[0]
    try:
        tag_name = str(getattr(element, "tag_name", "")).lower()
        result["control_kind"] = tag_name if tag_name in {
            "button", "a", "input"
        } else "other_interactive"
        element.click()
        result["clicked"] = True
        result["click_count"] = 1
    except Exception as exc:
        result["error"] = "control_click_failed:" + type(exc).__name__
    return result


def _claim_value(module_result: Mapping[str, Any], metric_id: str) -> Mapping[str, Any]:
    for claim in module_result.get("claims") or []:
        if claim.get("metric_id") == metric_id:
            value = claim.get("value")
            return value if isinstance(value, Mapping) else {}
    return {}


def analyze_safe_interaction(
    target: str,
    *,
    control: Mapping[str, Any],
    webauthn_result: Mapping[str, Any],
    credentials_before: Optional[int],
    credentials_after: Optional[int],
    pre_click_authentication_count: int = 0,
    setup_errors: Iterable[str] = (),
    input_count: int = 0,
) -> ModuleResult:
    """Build explicit trigger and safety claims from redacted measurements."""
    configuration = _claim_value(
        webauthn_result, "auth.webauthn.request_configuration")
    invocations = configuration.get("invocations") or []
    if not isinstance(invocations, list):
        invocations = []
    authentication_count = sum(
        isinstance(item, Mapping) and item.get("ceremony") == "authentication"
        for item in invocations
    )
    registration_count = sum(
        isinstance(item, Mapping) and item.get("ceremony") == "registration"
        for item in invocations
    )
    click_count = control.get("click_count")
    click_count = click_count if isinstance(click_count, int) else 0
    if (not isinstance(pre_click_authentication_count, int)
            or pre_click_authentication_count < 0):
        pre_click_authentication_count = 0
    click_attributed_authentication_count = max(
        0, authentication_count - pre_click_authentication_count)
    yield_rate = (
        round(click_attributed_authentication_count / click_count, 4)
        if click_count else None
    )
    guard_values = {
        "input_count": input_count,
        "probe_initiated_credential_calls": 0,
        "seeded_virtual_credentials": credentials_before,
        "virtual_credentials_after": credentials_after,
        "real_authenticator_used": False,
        "registration_calls_observed_and_blocked": registration_count,
        "registration_response_forwarded_to_server": False,
    }
    checks_known = credentials_before is not None and credentials_after is not None
    guard_passed = bool(
        checks_known and input_count == 0 and credentials_before == 0
        and credentials_after == 0
    )
    guard_failed = bool(
        input_count != 0
        or (credentials_before is not None and credentials_before != 0)
        or (credentials_after is not None and credentials_after != 0)
    )
    summary = {
        "control": dict(control),
        "authentication_invocation_count": authentication_count,
        "pre_click_authentication_count": pre_click_authentication_count,
        "click_attributed_authentication_count": click_attributed_authentication_count,
        "registration_invocation_count": registration_count,
        "trigger_yield": yield_rate,
        "trigger_formula": "Y_WA=N_observed_get/N_explicit_click",
        "guard": guard_values,
        "guard_passed": guard_passed,
        "guard_formula": (
            "I_guard=I[N_input=0 AND N_probe_cred=0 AND N_seed=0 "
            "AND N_after=0 AND N_real_auth=0]"
        ),
        "login_success_attempted": False,
        "server_assertion_verification_observed": False,
    }
    raw = json.dumps({"target": target, "summary": summary}, sort_keys=True)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    evidence_id = "webauthn-safe-interaction:" + digest
    evidence = Evidence(
        evidence_id=evidence_id,
        source_type="explicit_passkey_control_with_empty_virtual_authenticator",
        level=EvidenceLevel.OBSERVED,
        observation=summary,
        artifact_hash=digest,
    )
    trigger_verdict = (
        Verdict.WEAK if registration_count else
        Verdict.PASS if click_count == 1 and click_attributed_authentication_count >= 1 else
        Verdict.UNKNOWN
    )
    guard_verdict = (
        Verdict.FAIL if guard_failed else
        Verdict.PASS if guard_passed else Verdict.UNKNOWN
    )
    claims = (
        Claim(
            metric_id="auth.webauthn.explicit_control_trigger",
            crypto_property="webauthn_authentication_ceremony",
            verdict=trigger_verdict,
            value={
                "explicit_click_count": click_count,
                "authentication_invocation_count": authentication_count,
                "pre_click_authentication_count": pre_click_authentication_count,
                "click_attributed_authentication_count": click_attributed_authentication_count,
                "registration_invocation_count": registration_count,
                "trigger_yield": yield_rate,
                "trigger_formula": "Y_WA=N_observed_get/N_explicit_click",
            },
            evidence_ids=(evidence_id,),
            paper_ref_ids=(PASSKEYS_USENIX_2026.reference_id,),
            standard_ref_ids=(WEBAUTHN_LEVEL_3.reference_id,),
            limitations=(
                "PASS只证明明确Passkey控件触发了WebAuthn认证请求，不证明登录成功或安全。",
            ),
        ),
        Claim(
            metric_id="auth.webauthn.pre_click_authentication",
            crypto_property="conditional_webauthn_authentication_ceremony",
            verdict=(Verdict.PASS if pre_click_authentication_count
                     else Verdict.UNKNOWN),
            value={
                "observed": bool(pre_click_authentication_count),
                "authentication_invocation_count": pre_click_authentication_count,
                "explicit_click_count_before_observation": 0,
                "formula": "I_pre=I[N_get_before_click>0]",
            },
            evidence_ids=(evidence_id,),
            paper_ref_ids=(PASSKEYS_USENIX_2026.reference_id,),
            standard_ref_ids=(WEBAUTHN_LEVEL_3.reference_id,),
            limitations=(
                "PASS只表示页面在明确点击前自动发起认证仪式，不证明有可用凭据或登录成功。",
            ),
        ),
        Claim(
            metric_id="auth.webauthn.safe_interaction_guard",
            crypto_property="virtual_authenticator_isolation",
            verdict=guard_verdict,
            value={**guard_values, "guard_passed": guard_passed,
                   "guard_formula": summary["guard_formula"]},
            evidence_ids=(evidence_id,),
            paper_ref_ids=(
                PASSKEYS_USENIX_2026.reference_id,
                FIDO2_IEEE_SP_2023.reference_id,
            ),
            standard_ref_ids=(WEBAUTHN_LEVEL_3.reference_id,),
            limitations=(
                "PASS只证明本轮空虚拟认证器与零输入守卫成立，不证明目标站点安全。",
            ),
        ),
    )
    return ModuleResult(
        module_id=WEBAUTHN_SAFE_INTERACTION_MANIFEST.module_id,
        schema_version="webauthn-safe-interaction-1.0",
        scan_mode=ScanMode.SAFE_INTERACTION,
        claims=claims,
        evidence=(evidence,),
        errors=tuple(setup_errors),
        limitations=WEBAUTHN_SAFE_INTERACTION_MANIFEST.limitations,
    )
