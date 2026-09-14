"""Passive observer for public WebAuthn requests and lifecycle signals.

The observer never calls ``navigator.credentials.create`` or ``get``.  It
wraps calls made by the page itself, records a deliberately redacted summary,
and forwards the original call unchanged.  Challenges, user handles,
credential IDs, RP IDs, HMAC comparison tags, results, and authenticator
responses never cross the browser/Python boundary.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

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
    IANA_COSE_ALGORITHMS,
    PASSKEYS_USENIX_2026,
    WEBAUTHN_LEVEL_3,
)


WEBAUTHN_OBSERVER_MANIFEST = ModuleManifest(
    module_id="b.webauthn_request_observer",
    name_zh="WebAuthn公开请求参数观察器",
    research_question=(
        "访客可达认证流程中，网站是否实际调用WebAuthn API，以及其公开请求"
        "是否暴露足够的挑战长度、RP绑定、用户验证、驻留密钥和算法证据？"
    ),
    crypto_elements=(
        "webauthn_registration_and_authentication_ceremony",
        "randomized_replay_challenge",
        "relying_party_scoped_public_key_credential",
        "user_presence_and_user_verification",
        "cose_signature_algorithm_selection",
    ),
    paper_refs=(FIDO2_IEEE_SP_2023, PASSKEYS_USENIX_2026),
    standard_refs=(WEBAUTHN_LEVEL_3, IANA_COSE_ALGORITHMS),
    safe_modes=(ScanMode.PASSIVE,),
    limitations=(
        "观察器自身不调用凭据API、不点击Passkey控件；只记录页面自己发起的调用并原样转发。",
        "若网站自动发起显式WebAuthn仪式，浏览器或系统提示属于网站行为；测量程序不会响应提示。",
        "challenge只保留字节长度；长度达到16字节仍不能证明服务端随机生成、单次使用或正确比对。",
        "RP ID只保留与当前主机的句法关系，不保存原值，也不验证related-origins或公共后缀规则。",
        "challenge相等性只在单个文档内以随机HMAC标签比较；标签和密钥均不导出，零重复不证明服务端新鲜性。",
        "COSE算法状态固定到IANA 2026-08-25注册表快照；注册表变化需显式更新代码和变更记录。",
        "生命周期signal API只证明页面调用了浏览器同步接口，不能证明服务端删除、恢复或权限校验正确。",
        "请求参数不能证明认证器性质、私钥保护、签名结果或服务端断言验证正确。",
        "新标签早期调用、iframe内调用或站点脚本主动规避包装时可能漏报；未观察到必须保持未知。",
    ),
)


# This source is intentionally self-contained so it can be registered before
# navigation with Page.addScriptToEvaluateOnNewDocument.  The page-visible
# buffer contains only the same redacted metadata eventually returned to
# Python; raw values are never added to it.
WEBAUTHN_OBSERVER_SCRIPT = r"""
(()=>{
  'use strict';
  const MARK='__cryptoscopeWebAuthnObserverV1';
  const READ='__cryptoscopeReadWebAuthnObserverV1';
  if(globalThis[MARK])return;
  const observations=[];
  const challengeTags=new Set();
  let challengeKeyPromise=null;
  const safeString=(v,allowed,fallback='')=>{
    const s=typeof v==='string'?v:'';
    return allowed.includes(s)?s:fallback;
  };
  const byteLength=v=>{
    try{
      if(v instanceof ArrayBuffer)return v.byteLength;
      if(ArrayBuffer.isView(v))return v.byteLength;
    }catch(e){}
    return null;
  };
  const count=v=>Array.isArray(v)?Math.min(v.length,1000):0;
  const timeoutBucket=v=>{
    if(!Number.isFinite(v)||v<0)return 'default_or_invalid';
    if(v<=60000)return 'up_to_60s';
    if(v<=120000)return '60_to_120s';
    return 'over_120s';
  };
  const rpRelation=rp=>{
    try{
      const host=(location.hostname||'').toLowerCase().replace(/\.$/,'');
      if(typeof rp!=='string'||!rp.trim())return 'default_current_origin';
      const candidate=rp.trim().toLowerCase().replace(/\.$/,'');
      if(candidate===host)return 'current_host';
      if(host.endsWith('.'+candidate))return 'parent_domain_candidate';
      return 'different_or_related_origin';
    }catch(e){return 'unknown';}
  };
  const rpScopeLabelsRemoved=rp=>{
    try{
      const host=(location.hostname||'').toLowerCase().replace(/\.$/,'');
      if(typeof rp!=='string'||!rp.trim())return 0;
      const candidate=rp.trim().toLowerCase().replace(/\.$/,'');
      if(candidate===host)return 0;
      if(host.endsWith('.'+candidate)){
        return Math.max(0,host.split('.').length-candidate.split('.').length);
      }
    }catch(e){}
    return null;
  };
  const extensionNames=v=>{
    try{
      if(!v||typeof v!=='object'||Array.isArray(v))return [];
      return Object.keys(v).map(String).sort().slice(0,50);
    }catch(e){return [];}
  };
  const algorithms=v=>{
    if(!Array.isArray(v))return [];
    return [...new Set(v.map(x=>x&&x.alg).filter(Number.isSafeInteger))]
      .sort((a,b)=>a-b).slice(0,50);
  };
  const summarize=(method,options)=>{
    const p=options&&typeof options==='object'&&options.publicKey&&
      typeof options.publicKey==='object'?options.publicKey:null;
    if(!p)return null;
    const selection=method==='create'&&p.authenticatorSelection&&
      typeof p.authenticatorSelection==='object'?p.authenticatorSelection:{};
    const base={
      ceremony:method==='create'?'registration':'authentication',
      challenge_bytes:byteLength(p.challenge),
      rp_id_relation:rpRelation(method==='create'?(p.rp&&p.rp.id):p.rpId),
      rp_scope_labels_removed:rpScopeLabelsRemoved(
        method==='create'?(p.rp&&p.rp.id):p.rpId),
      user_verification:safeString(
        method==='create'?selection.userVerification:p.userVerification,
        ['required','preferred','discouraged'],'default'),
      timeout_bucket:timeoutBucket(p.timeout),
      extension_names:extensionNames(p.extensions),
    };
    if(method==='create'){
      base.user_id_bytes=byteLength(p.user&&p.user.id);
      base.pub_key_algorithms=algorithms(p.pubKeyCredParams);
      base.resident_key=safeString(selection.residentKey,
        ['required','preferred','discouraged'],'default');
      base.require_resident_key=selection.requireResidentKey===true;
      base.authenticator_attachment=safeString(selection.authenticatorAttachment,
        ['platform','cross-platform'],'unspecified');
      base.attestation=safeString(p.attestation,
        ['none','indirect','direct','enterprise'],'default');
      base.exclude_credentials_count=count(p.excludeCredentials);
    }else{
      base.allow_credentials_count=count(p.allowCredentials);
      base.mediation=safeString(options.mediation,
        ['silent','optional','required','conditional'],'default');
      base.conditional_mediation=options.mediation==='conditional';
    }
    return base;
  };
  const compareChallengeInDocument=(challenge,item)=>{
    try{
      if(!globalThis.crypto||!crypto.subtle||!crypto.getRandomValues)return;
      let bytes=null;
      if(challenge instanceof ArrayBuffer)bytes=new Uint8Array(challenge).slice();
      else if(ArrayBuffer.isView(challenge)){
        bytes=new Uint8Array(
          challenge.buffer,challenge.byteOffset,challenge.byteLength).slice();
      }
      if(!bytes)return;
      if(!challengeKeyPromise){
        const randomKey=new Uint8Array(32);
        crypto.getRandomValues(randomKey);
        challengeKeyPromise=crypto.subtle.importKey(
          'raw',randomKey,{name:'HMAC',hash:'SHA-256'},false,['sign']);
      }
      challengeKeyPromise
        .then(key=>crypto.subtle.sign('HMAC',key,bytes))
        .then(tagBuffer=>{
          const tag=[...new Uint8Array(tagBuffer)]
            .map(x=>x.toString(16).padStart(2,'0')).join('');
          item.challenge_reused_in_document=challengeTags.has(tag);
          item.challenge_equality_checked=true;
          challengeTags.add(tag);
        }).catch(()=>{});
    }catch(e){}
  };
  try{
    Object.defineProperty(globalThis,MARK,{value:true,configurable:false});
    Object.defineProperty(globalThis,READ,{
      value:()=>observations.map(x=>({...x})),configurable:false
    });
  }catch(e){return;}
  const credentials=navigator&&navigator.credentials;
  if(!credentials)return;
  for(const method of ['create','get']){
    try{
      const original=credentials[method];
      if(typeof original!=='function')continue;
      const wrapped=function(options){
        try{
          const item=summarize(method,options);
          if(item&&observations.length<100){
            observations.push(item);
            compareChallengeInDocument(
              options&&options.publicKey&&options.publicKey.challenge,item);
          }
        }catch(e){}
        return Reflect.apply(original,credentials,[options]);
      };
      Object.defineProperty(credentials,method,{
        value:wrapped,writable:true,configurable:true
      });
    }catch(e){}
  }
  const publicKeyCredential=globalThis.PublicKeyCredential;
  if(publicKeyCredential){
    for(const method of [
      'signalAllAcceptedCredentials','signalUnknownCredential',
      'signalCurrentUserDetails']){
      try{
        const original=publicKeyCredential[method];
        if(typeof original!=='function')continue;
        const wrapped=function(options){
          try{
            const item={
              event_type:'lifecycle_signal',
              lifecycle_signal:method,
              rp_id_relation:rpRelation(options&&options.rpId),
              rp_scope_labels_removed:rpScopeLabelsRemoved(options&&options.rpId),
            };
            if(method==='signalAllAcceptedCredentials'){
              item.accepted_credentials_count=count(
                options&&options.allAcceptedCredentialIds);
            }
            if(observations.length<100)observations.push(item);
          }catch(e){}
          return Reflect.apply(original,publicKeyCredential,[options]);
        };
        Object.defineProperty(publicKeyCredential,method,{
          value:wrapped,writable:true,configurable:true
        });
      }catch(e){}
    }
  }
})();
"""


_READ_EXPRESSION = (
    "(()=>{try{const f=globalThis.__cryptoscopeReadWebAuthnObserverV1;"
    "return typeof f==='function'?f():[];}catch(e){return [];}})()"
)

_CEREMONY_FIELDS = {
    "registration": (
        "challenge_bytes", "rp_id_relation", "user_verification",
        "pub_key_algorithms", "resident_key",
    ),
    "authentication": (
        "challenge_bytes", "rp_id_relation", "user_verification",
        "allow_credentials_count", "mediation",
    ),
}

# Frozen IANA COSE Algorithms registry snapshot (2026-08-25).  WebAuthn
# pubKeyCredParams must describe asymmetric signature algorithms.  Unknown
# identifiers remain unknown instead of being guessed from their integer sign.
_COSE_RECOMMENDED_SIGNATURES = {
    -53: "Ed448", -52: "ESP512", -51: "ESP384",
    -50: "ML-DSA-87", -49: "ML-DSA-65", -48: "ML-DSA-44",
    -46: "HSS-LMS", -39: "PS512", -38: "PS384", -37: "PS256",
    -19: "Ed25519", -9: "ESP256",
}
_COSE_NOT_RECOMMENDED_SIGNATURES = {
    -259: "RS512", -258: "RS384", -257: "RS256", -47: "ES256K",
}
_COSE_DEPRECATED_SIGNATURES = {
    -65535: "RS1", -36: "ES512", -35: "ES384", -8: "EdDSA", -7: "ES256",
}
_COSE_SYMMETRIC_MAC_ALGORITHMS = {
    4: "HMAC 256/64", 5: "HMAC 256/256", 6: "HMAC 384/384", 7: "HMAC 512/512",
    14: "AES-MAC 128/64", 15: "AES-MAC 256/64",
    25: "AES-MAC 128/128", 26: "AES-MAC 256/128",
}


def _stable_evidence_id(target: str, observations: Sequence[Dict[str, Any]]) -> str:
    raw = json.dumps(
        {"target": target, "observations": observations},
        ensure_ascii=False, sort_keys=True, default=str,
    )
    return "webauthn-request:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _cdp_value(driver, expression: str) -> Any:
    result = driver.execute_cdp_cmd("Runtime.evaluate", {
        "expression": expression,
        "returnByValue": True,
    })
    if not isinstance(result, dict) or result.get("exceptionDetails"):
        return None
    return (result.get("result") or {}).get("value")


def install_webauthn_observer(driver) -> Tuple[str, ...]:
    """Register the observer for future documents and install it now.

    Registration is tracked per Selenium window handle because a newly opened
    tab is a distinct CDP target.  Re-running this function is safe.
    """
    errors: List[str] = []
    try:
        handle = driver.current_window_handle
    except Exception:
        handle = "unknown"
    handles = getattr(driver, "_cryptoscope_webauthn_registered_handles", set())
    if not isinstance(handles, set):
        handles = set()
    if handle not in handles:
        try:
            driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                "source": WEBAUTHN_OBSERVER_SCRIPT,
            })
            handles.add(handle)
            try:
                setattr(driver, "_cryptoscope_webauthn_registered_handles", handles)
            except Exception:
                pass
        except Exception as exc:
            errors.append("observer_registration_failed:" + type(exc).__name__)
    try:
        _cdp_value(driver, WEBAUTHN_OBSERVER_SCRIPT)
    except Exception as exc:
        errors.append("observer_current_document_failed:" + type(exc).__name__)
    return tuple(errors)


def _clean_observation(item: Any) -> Optional[Dict[str, Any]]:
    """Allow-list the browser summary again before it enters evidence."""
    if not isinstance(item, dict):
        return None
    lifecycle_signal = item.get("lifecycle_signal")
    if item.get("event_type") == "lifecycle_signal":
        if lifecycle_signal not in {
            "signalAllAcceptedCredentials",
            "signalUnknownCredential",
            "signalCurrentUserDetails",
        }:
            return None
        out: Dict[str, Any] = {
            "event_type": "lifecycle_signal",
            "lifecycle_signal": lifecycle_signal,
        }
        relation = item.get("rp_id_relation")
        out["rp_id_relation"] = relation if relation in {
            "default_current_origin", "current_host", "parent_domain_candidate",
            "different_or_related_origin", "unknown",
        } else "unknown"
        labels_removed = item.get("rp_scope_labels_removed")
        out["rp_scope_labels_removed"] = labels_removed if (
            isinstance(labels_removed, int) and not isinstance(labels_removed, bool)
            and 0 <= labels_removed <= 126
        ) else None
        if lifecycle_signal == "signalAllAcceptedCredentials":
            count = item.get("accepted_credentials_count")
            out["accepted_credentials_count"] = count if (
                isinstance(count, int) and not isinstance(count, bool)
                and 0 <= count <= 1000
            ) else None
        return out
    ceremony = item.get("ceremony")
    if ceremony not in _CEREMONY_FIELDS:
        return None
    out: Dict[str, Any] = {"ceremony": ceremony}
    integers = {"challenge_bytes", "rp_scope_labels_removed"}
    strings = {
        "rp_id_relation", "user_verification", "timeout_bucket",
    }
    booleans = {"challenge_equality_checked", "challenge_reused_in_document"}
    if ceremony == "registration":
        integers.update({"user_id_bytes", "exclude_credentials_count"})
        strings.update({
            "resident_key", "authenticator_attachment", "attestation",
        })
        booleans.add("require_resident_key")
    else:
        integers.add("allow_credentials_count")
        strings.add("mediation")
        booleans.add("conditional_mediation")
    for key in integers:
        value = item.get(key)
        out[key] = value if (
            isinstance(value, int) and not isinstance(value, bool)
            and 0 <= value <= 1_000_000
        ) else None
    allowed_strings = {
        "rp_id_relation": {
            "default_current_origin", "current_host", "parent_domain_candidate",
            "different_or_related_origin", "unknown",
        },
        "user_verification": {"required", "preferred", "discouraged", "default"},
        "timeout_bucket": {
            "default_or_invalid", "up_to_60s", "60_to_120s", "over_120s",
        },
        "resident_key": {"required", "preferred", "discouraged", "default"},
        "authenticator_attachment": {"platform", "cross-platform", "unspecified"},
        "attestation": {"none", "indirect", "direct", "enterprise", "default"},
        "mediation": {"silent", "optional", "required", "conditional", "default"},
    }
    for key in strings:
        value = item.get(key)
        out[key] = value if (
            isinstance(value, str) and value in allowed_strings[key]
        ) else ""
    for key in booleans:
        out[key] = bool(item.get(key))
    if ceremony == "registration":
        algorithms = item.get("pub_key_algorithms")
        out["pub_key_algorithms"] = sorted({
            value for value in algorithms or []
            if isinstance(value, int) and not isinstance(value, bool)
            and -(2 ** 31) <= value < 2 ** 31
        })[:50]
    extensions = item.get("extension_names")
    out["extension_names"] = sorted({
        value for value in extensions or []
        if isinstance(value, str)
        and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", value)
    })[:50]
    return out


def _classify_cose_algorithms(algorithms: Iterable[int]) -> Dict[str, Any]:
    unique = sorted(set(algorithms))
    groups: Dict[str, List[Dict[str, Any]]] = {
        "recommended": [],
        "not_recommended": [],
        "deprecated": [],
        "symmetric_or_mac_incompatible": [],
        "unknown_or_non_signature": [],
    }
    for algorithm in unique:
        if algorithm in _COSE_RECOMMENDED_SIGNATURES:
            key, name = "recommended", _COSE_RECOMMENDED_SIGNATURES[algorithm]
        elif algorithm in _COSE_NOT_RECOMMENDED_SIGNATURES:
            key, name = (
                "not_recommended", _COSE_NOT_RECOMMENDED_SIGNATURES[algorithm])
        elif algorithm in _COSE_DEPRECATED_SIGNATURES:
            key, name = "deprecated", _COSE_DEPRECATED_SIGNATURES[algorithm]
        elif algorithm in _COSE_SYMMETRIC_MAC_ALGORITHMS:
            key, name = (
                "symmetric_or_mac_incompatible",
                _COSE_SYMMETRIC_MAC_ALGORITHMS[algorithm],
            )
        else:
            key, name = "unknown_or_non_signature", "unclassified"
        groups[key].append({"id": algorithm, "name": name})
    return {
        "registry_snapshot": "2026-08-25",
        "offered_total": len(unique),
        **groups,
    }


def _authentication_mode(item: Dict[str, Any]) -> str:
    if item.get("ceremony") != "authentication":
        return "not_authentication"
    if item.get("mediation") == "conditional":
        return "conditional"
    allow_count = item.get("allow_credentials_count")
    if allow_count == 0:
        return "discoverable"
    if isinstance(allow_count, int) and allow_count > 0:
        return "non_discoverable"
    return "unknown"


def analyze_webauthn_observations(
    target: str,
    observations: Iterable[Dict[str, Any]],
    errors: Sequence[str] = (),
) -> ModuleResult:
    """Build conservative claims from already-redacted API-call summaries."""
    cleaned = tuple(filter(None, (_clean_observation(item) for item in observations)))[:100]
    ceremonies_cleaned = tuple(
        item for item in cleaned if item.get("ceremony") in _CEREMONY_FIELDS)
    lifecycle_cleaned = tuple(
        item for item in cleaned if item.get("event_type") == "lifecycle_signal")
    evidence: Tuple[Evidence, ...] = ()
    evidence_ids: Tuple[str, ...] = ()
    if cleaned:
        evidence_id = _stable_evidence_id(target, cleaned)
        evidence = (Evidence(
            evidence_id=evidence_id,
            source_type="page_initiated_webauthn_request",
            level=EvidenceLevel.OBSERVED,
            observation={
                "invocations": list(cleaned),
                "raw_challenges_retained": False,
                "user_or_credential_ids_retained": False,
                "authenticator_responses_retained": False,
            },
            artifact_hash=evidence_id.split(":", 1)[1],
        ),)
        evidence_ids = (evidence_id,)

    challenge_lengths = [
        item["challenge_bytes"] for item in ceremonies_cleaned
        if isinstance(item.get("challenge_bytes"), int)
    ]
    short_challenges = [length for length in challenge_lengths if length < 16]
    equality_checked = [
        item for item in ceremonies_cleaned
        if item.get("challenge_equality_checked") is True
    ]
    repeated_challenges = [
        item for item in equality_checked
        if item.get("challenge_reused_in_document") is True
    ]
    ceremonies = sorted({item["ceremony"] for item in ceremonies_cleaned})
    coverages = []
    for item in ceremonies_cleaned:
        fields = _CEREMONY_FIELDS[item["ceremony"]]
        observed = 0
        for field in fields:
            value = item.get(field)
            if value not in (None, "", []):
                observed += 1
        coverages.append(observed / len(fields))
    coverage = sum(coverages) / len(coverages) if coverages else 0.0

    invocation_claim = Claim(
        metric_id="auth.webauthn.api_invocation",
        crypto_property="webauthn_registration_and_authentication_ceremony",
        verdict=Verdict.PASS if ceremonies_cleaned else Verdict.UNKNOWN,
        value={
            "observed": bool(ceremonies_cleaned),
            "invocation_count": len(ceremonies_cleaned),
            "ceremonies": ceremonies,
            "observer_initiated_calls": 0,
        },
        evidence_ids=evidence_ids,
        paper_ref_ids=(FIDO2_IEEE_SP_2023.reference_id, PASSKEYS_USENIX_2026.reference_id),
        standard_ref_ids=(WEBAUTHN_LEVEL_3.reference_id,),
        limitations=(
            "PASS只表示实际观察到页面发起WebAuthn调用，不表示该调用或实现安全。",
        ),
    )
    challenge_claim = Claim(
        metric_id="auth.webauthn.challenge_length",
        crypto_property="randomized_replay_challenge",
        verdict=(
            Verdict.FAIL if repeated_challenges else
            Verdict.WEAK if short_challenges else Verdict.UNKNOWN
        ),
        value={
            "observed_lengths_bytes": challenge_lengths,
            "below_16_bytes_count": len(short_challenges),
            "equality_compared_count": len(equality_checked),
            "reused_in_document_count": len(repeated_challenges),
            "reuse_rate": (
                round(len(repeated_challenges) / len(equality_checked), 4)
                if equality_checked else None
            ),
            "reuse_formula": "R_ch=N_reused/N_compared",
            "minimum_recommended_bytes": 16,
            "randomness_verified": False,
            "freshness_verified": False,
            "server_match_verified": False,
        },
        evidence_ids=evidence_ids if challenge_lengths else (),
        paper_ref_ids=(FIDO2_IEEE_SP_2023.reference_id,),
        standard_ref_ids=(WEBAUTHN_LEVEL_3.reference_id,),
        limitations=(
            "同一文档内观察到完全相同challenge可证伪新鲜性；零重复只覆盖本次调用，不能证明全局唯一。",
            "W3C建议challenge至少16字节；长度达标只排除明显过短，不能证明熵或服务端比对。",
        ),
    )
    configuration_claim = Claim(
        metric_id="auth.webauthn.request_configuration",
        crypto_property="rp_uv_resident_key_and_cose_algorithm_configuration",
        verdict=Verdict.UNKNOWN,
        value={
            "invocations": list(ceremonies_cleaned),
            "configuration_coverage": round(coverage, 4),
            "coverage_formula": "C_WA=(1/n)*sum_i(sum_j I[o_ij observed]/|R_i|)",
            "cryptographic_verification_performed": False,
            "raw_sensitive_values_retained": False,
        },
        evidence_ids=evidence_ids,
        paper_ref_ids=(FIDO2_IEEE_SP_2023.reference_id,),
        standard_ref_ids=(WEBAUTHN_LEVEL_3.reference_id,),
        limitations=(
            "配置覆盖率衡量可见证据完整度，不是安全分数；服务端断言验证未执行，故保持UNKNOWN。",
        ),
    )
    all_algorithms = [
        algorithm
        for item in ceremonies_cleaned
        for algorithm in item.get("pub_key_algorithms", [])
    ]
    algorithm_profile = _classify_cose_algorithms(all_algorithms)
    algorithm_weak = any(algorithm_profile[key] for key in (
        "not_recommended", "deprecated", "symmetric_or_mac_incompatible",
        "unknown_or_non_signature",
    ))
    algorithm_verdict = Verdict.UNKNOWN
    if algorithm_profile["offered_total"]:
        algorithm_verdict = (
            Verdict.WEAK if algorithm_weak else Verdict.PASS)
    algorithm_claim = Claim(
        metric_id="auth.webauthn.cose_algorithm_policy",
        crypto_property="asymmetric_signature_algorithm_selection",
        verdict=algorithm_verdict,
        value={
            **algorithm_profile,
            "all_offered_algorithms_recommended": bool(
                algorithm_profile["offered_total"] and not algorithm_weak),
            "predicate_formula": "V_alg=(A!=empty) AND (A subset R_sig_recommended)",
            "actual_negotiated_algorithm_verified": False,
        },
        evidence_ids=evidence_ids if all_algorithms else (),
        paper_ref_ids=(PASSKEYS_USENIX_2026.reference_id,),
        standard_ref_ids=(
            WEBAUTHN_LEVEL_3.reference_id,
            IANA_COSE_ALGORITHMS.reference_id,
        ),
        limitations=(
            "PASS只表示观察到的注册请求算法集合全部位于固定IANA推荐签名集合，不证明认证器最终选用或服务端验证该算法。",
            "IANA状态会变化；结果必须连同registry_snapshot解释。",
        ),
    )

    rp_items = [
        item for item in cleaned
        if item.get("rp_id_relation") not in (None, "", "unknown")
    ]
    parent_scope = [
        item for item in rp_items
        if item.get("rp_id_relation") == "parent_domain_candidate"
    ]
    related_or_different = [
        item for item in rp_items
        if item.get("rp_id_relation") == "different_or_related_origin"
    ]
    narrow_scope = bool(rp_items) and not parent_scope and not related_or_different
    rp_scope_verdict = (
        Verdict.WEAK if parent_scope else
        Verdict.PASS if narrow_scope else Verdict.UNKNOWN
    )
    max_labels_removed = max(
        (item.get("rp_scope_labels_removed") or 0 for item in parent_scope),
        default=0,
    )
    rp_scope_claim = Claim(
        metric_id="auth.webauthn.rp_scope",
        crypto_property="relying_party_scoped_public_key_credential",
        verdict=rp_scope_verdict,
        value={
            "observed_total": len(rp_items),
            "narrow_current_host_count": sum(
                item.get("rp_id_relation") in {
                    "default_current_origin", "current_host"} for item in rp_items),
            "parent_scope_count": len(parent_scope),
            "different_or_related_origin_count": len(related_or_different),
            "max_host_labels_removed": max_labels_removed,
            "breadth_formula": "B_RP=max_i(host_labels_i-rp_labels_i)",
            "raw_rp_ids_retained": False,
            "related_origin_validation_performed": False,
        },
        evidence_ids=evidence_ids if rp_items else (),
        paper_ref_ids=(
            FIDO2_IEEE_SP_2023.reference_id,
            PASSKEYS_USENIX_2026.reference_id,
        ),
        standard_ref_ids=(WEBAUTHN_LEVEL_3.reference_id,),
        limitations=(
            "父域scope扩大可使用凭据的子域面，标为WEAK风险面而非已利用漏洞。",
            "different_or_related_origin可能由WebAuthn related-origins合法授权，未读取其配置时保持UNKNOWN。",
        ),
    )

    authentication_profiles = []
    for item in ceremonies_cleaned:
        if item.get("ceremony") != "authentication":
            continue
        authentication_profiles.append({
            "mode": _authentication_mode(item),
            "user_verification": item.get("user_verification", "default"),
        })
    registration_mismatches = [
        item for item in ceremonies_cleaned
        if item.get("ceremony") == "registration"
        and (
            (
                item.get("resident_key") == "required"
                and item.get("require_resident_key") is not True
            )
            or (
                item.get("resident_key") in {"preferred", "discouraged"}
                and item.get("require_resident_key") is True
            )
        )
    ]
    profile_claim = Claim(
        metric_id="auth.webauthn.passkey_profile",
        crypto_property="discoverable_credential_and_user_verification_policy",
        verdict=Verdict.WEAK if registration_mismatches else Verdict.UNKNOWN,
        value={
            "authentication_profiles": authentication_profiles,
            "conditional_count": sum(
                item["mode"] == "conditional" for item in authentication_profiles),
            "discoverable_count": sum(
                item["mode"] == "discoverable" for item in authentication_profiles),
            "non_discoverable_count": sum(
                item["mode"] == "non_discoverable" for item in authentication_profiles),
            "user_verification_discouraged_count": sum(
                item["user_verification"] == "discouraged"
                for item in authentication_profiles),
            "resident_key_required_legacy_flag_mismatch_count": len(
                registration_mismatches),
            "passwordless_or_second_factor_verified": False,
            "actual_uv_flag_verified": False,
        },
        evidence_ids=evidence_ids if authentication_profiles or registration_mismatches else (),
        paper_ref_ids=(PASSKEYS_USENIX_2026.reference_id,),
        standard_ref_ids=(WEBAUTHN_LEVEL_3.reference_id,),
        limitations=(
            "userVerification=discouraged只有与无口令路径及成功断言UV标志结合后才能判断实际风险，当前不单独判弱。",
            "请求mode不能单独证明网站把Passkey作为无口令主因子还是第二因子。",
        ),
    )

    lifecycle_types = sorted({
        item["lifecycle_signal"] for item in lifecycle_cleaned})
    lifecycle_claim = Claim(
        metric_id="auth.webauthn.lifecycle_sync",
        crypto_property="credential_lifecycle_state_synchronization",
        verdict=Verdict.PASS if lifecycle_cleaned else Verdict.UNKNOWN,
        value={
            "observed": bool(lifecycle_cleaned),
            "invocation_count": len(lifecycle_cleaned),
            "signal_types": lifecycle_types,
            "invocations": list(lifecycle_cleaned),
            "observer_initiated_calls": 0,
            "server_side_deletion_or_authorization_verified": False,
        },
        evidence_ids=evidence_ids if lifecycle_cleaned else (),
        paper_ref_ids=(PASSKEYS_USENIX_2026.reference_id,),
        standard_ref_ids=(WEBAUTHN_LEVEL_3.reference_id,),
        limitations=(
            "PASS只表示页面实际调用生命周期同步API，不表示账号恢复、删除授权或认证器状态已经安全验证。",
            "未观察到signal调用不等于网站从未调用；它可能只在登录后的设置页面执行。",
        ),
    )
    return ModuleResult(
        module_id=WEBAUTHN_OBSERVER_MANIFEST.module_id,
        schema_version="webauthn-request-observer-1.1",
        scan_mode=ScanMode.PASSIVE,
        claims=(
            invocation_claim,
            challenge_claim,
            configuration_claim,
            algorithm_claim,
            rp_scope_claim,
            profile_claim,
            lifecycle_claim,
        ),
        evidence=evidence,
        errors=tuple(errors),
        limitations=WEBAUTHN_OBSERVER_MANIFEST.limitations,
    )


def collect_webauthn_observations(
    driver,
    target: str,
    install_errors: Sequence[str] = (),
) -> ModuleResult:
    """Read the redacted observer buffer without invoking a credential API."""
    errors = list(install_errors)
    try:
        value = _cdp_value(driver, _READ_EXPRESSION)
        observations = value if isinstance(value, list) else []
    except Exception as exc:
        observations = []
        errors.append("observer_collection_failed:" + type(exc).__name__)
    return analyze_webauthn_observations(target, observations, errors)
