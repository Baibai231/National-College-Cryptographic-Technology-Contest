"""Passive DOM probe for public authentication protocol metadata.

The probe inspects already rendered controls. It never follows an identity
provider link, submits a form, invokes ``navigator.credentials``, sends an
OTP, or stores OAuth parameter values such as client identifiers and state.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict

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
    MFA_RBA_USENIX_2023,
    OAUTH_SECURITY_BCP_RFC9700,
    PASSKEYS_USENIX_2026,
    WEBAUTHN_LEVEL_3,
    WPSE_USENIX_2018,
)


PASSIVE_PROTOCOL_MANIFEST = ModuleManifest(
    module_id="b.passive_protocol_metadata",
    name_zh="认证协议公开元数据探针",
    research_question=(
        "在不离开当前认证页面、不提交表单的前提下，能观察到哪些OAuth/OIDC参数、"
        "Passkey控件和MFA/RBA公开提示？"
    ),
    crypto_elements=(
        "oauth_oidc_authorization_request",
        "pkce_code_challenge",
        "oidc_nonce_and_oauth_state",
        "webauthn_public_key_credential",
        "multi_factor_and_risk_based_authentication",
    ),
    paper_refs=(WPSE_USENIX_2018, PASSKEYS_USENIX_2026, MFA_RBA_USENIX_2023),
    standard_refs=(OAUTH_SECURITY_BCP_RFC9700, WEBAUTHN_LEVEL_3),
    safe_modes=(ScanMode.PASSIVE,),
    limitations=(
        "只读取当前DOM中的URL结构和控件语义，不跟随OAuth/OIDC跳转。",
        "参数未出现在静态href/action中时可能由点击后的JavaScript生成，缺失只能记为未知。",
        "可见Passkey控件不证明注册仪式、用户验证、RP ID或服务端验签配置正确。",
        "MFA/RBA文字提示不证明实际强制执行，需要授权账号对照实验。",
    ),
)


_DOM_PROBE_SCRIPT = r"""
const clean=v=>(v||'').replace(/\s+/g,' ').trim().toLowerCase();
const joseParams=new Set(['request','request_object','response','id_token','assertion','client_assertion']);
const joseObjects=[],joseKeys=new Set();
const joseProfile=p=>({id_token:'oidc_id_token',response:'jarm_response',request:'jar_request',
 request_object:'jar_request',client_assertion:'client_assertion',assertion:'assertion'}[p]||'unspecified_jwt');
const joseMeta=(raw,source,parameter)=>{
 const base={source,parameter,profile:joseProfile(parameter)};
 try{
  if(typeof raw!=='string'||raw.length>262144)return {...base,parse_error:'invalid_or_oversized_compact_jose'};
  const parts=raw.split('.');
  if(parts.length!==3||!parts[0]||!parts[1])return {...base,parse_error:'malformed_compact_jose'};
  const decode=s=>{if(!/^[A-Za-z0-9_-]+$/.test(s))throw Error('base64url');
   const b=atob(s.replace(/-/g,'+').replace(/_/g,'/')+'='.repeat((4-s.length%4)%4));
   return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(Uint8Array.from(b,c=>c.charCodeAt(0))));};
  const h=decode(parts[0]),p=decode(parts[1]);
  if(!h||Array.isArray(h)||typeof h!=='object'||!p||Array.isArray(p)||typeof p!=='object')throw Error('json');
  const crit=Array.isArray(h.crit)?h.crit.filter(x=>typeof x==='string').sort().slice(0,20):[];
  const claims=Object.keys(p).map(String).sort().slice(0,100);
  return {...base,alg:typeof h.alg==='string'?h.alg.slice(0,40):'',typ:typeof h.typ==='string'?h.typ.slice(0,80):'',
   kid_present:typeof h.kid==='string'&&!!h.kid,critical_headers:crit,
   remote_key_headers:['jku','x5u'].filter(x=>Object.prototype.hasOwnProperty.call(h,x)),
   embedded_key_headers:['jwk','x5c'].filter(x=>Object.prototype.hasOwnProperty.call(h,x)),
   claim_names:claims,binding_claims_present:['iss','sub','aud','exp','nbf','iat','jti','nonce'].filter(x=>claims.includes(x)),
   signature_present:!!parts[2],signature_bytes:parts[2]?Math.floor(parts[2].length*3/4):0};
 }catch(e){return {...base,parse_error:'malformed_compact_jose'};}
};
const inspectJoseUrl=(u,source)=>{try{for(const [name,value] of u.searchParams.entries()){
 const parameter=clean(name);if(!joseParams.has(parameter))continue;
 const meta=joseMeta(value,source,parameter),key=JSON.stringify(meta);if(!joseKeys.has(key)){joseKeys.add(key);joseObjects.push(meta);}
 }}catch(e){}};
const visible=el=>{try{const r=el.getBoundingClientRect(),s=getComputedStyle(el);
 return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden';}catch(e){return false;}};
const roots=[document],seen=new Set();
for(let i=0;i<roots.length&&i<100;i++){
 const root=roots[i];if(!root||seen.has(root))continue;seen.add(root);
 for(const el of root.querySelectorAll('*'))if(el.shadowRoot)roots.push(el.shadowRoot);
 try{for(const f of root.querySelectorAll('iframe'))if(visible(f)&&f.contentDocument)roots.push(f.contentDocument);}catch(e){}
}
const authPath=/\/(login|signin|sign-in|register|signup|passport|oauth|authorize|auth|account)(\/|$)/i.test(location.pathname);
try{inspectJoseUrl(new URL(location.href),'current_url');
 const hash=(location.hash||'').replace(/^#/,'');if(hash.includes('='))inspectJoseUrl(new URL(location.origin+location.pathname+'?'+hash),'current_fragment');}catch(e){}
const authBoxes=[];let hasAuthField=false;
for(const root of roots){
 for(const box of root.querySelectorAll("[role='dialog'],[aria-modal='true'],form,[class*='login'],[class*='signin'],[class*='auth']"))
  if(visible(box))authBoxes.push(box);
 for(const input of root.querySelectorAll("input[type='password'],input[autocomplete='current-password'],input[autocomplete='new-password'],input[autocomplete='one-time-code']"))
  if(visible(input)){hasAuthField=true;break;}
}
const inAuthContext=el=>authPath||hasAuthField||authBoxes.some(box=>box===el||box.contains(el));
const endpoints=[],endpointKeys=new Set(),passkeySignals=new Set();
let passwordAutocomplete=false,otpAutocomplete=false;
for(const root of roots){
 for(const input of root.querySelectorAll('input')){
  if(!visible(input)||!inAuthContext(input))continue;
  const ac=clean(input.getAttribute('autocomplete'));
  if(ac==='current-password'||ac==='new-password')passwordAutocomplete=true;
  if(ac==='one-time-code')otpAutocomplete=true;
 }
 for(const el of root.querySelectorAll("a[href],form[action],button,[role='button'],[role='link'],[role='tab']")){
  if(!visible(el)||!inAuthContext(el))continue;
  const label=clean([el.innerText,el.value,el.getAttribute('aria-label'),el.title,
    el.id,typeof el.className==='string'?el.className:''].join(' '));
  const passkeyMatch=label.match(/passkeys?|webauthn|fido2|security key|hardware key|通行密钥|通行金[钥鑰]|安全密钥|安全金[钥鑰]|硬件密钥|硬體金鑰/i);
  if(passkeyMatch)passkeySignals.add(clean(passkeyMatch[0]));
  const raw=el.getAttribute('href')||el.getAttribute('action')||'';
  if(!raw||raw.startsWith('javascript:')||raw.startsWith('#'))continue;
  try{
   const u=new URL(raw,location.href),names=[...u.searchParams.keys()].map(clean).filter(Boolean).sort();
   inspectJoseUrl(u,'dom_url');
   const joined=(u.hostname+u.pathname+'?'+names.join('&')).toLowerCase();
   const authLike=/oauth|openid|authorize|authorization|\/auth(?:\/|$)|servicelogin/.test(joined)
     || names.some(n=>['client_id','response_type','redirect_uri','scope','state','nonce','code_challenge'].includes(n));
   if(!authLike)continue;
   const key=u.origin+u.pathname+'?'+names.join('&');if(endpointKeys.has(key))continue;endpointKeys.add(key);
   const responseType=clean(u.searchParams.get('response_type'));
   endpoints.push({
    origin:u.origin,path:u.pathname,same_origin:u.origin===location.origin,
    query_parameter_names:names,
    response_type:['code','token','id_token','code token','code id_token','id_token token'].includes(responseType)?responseType:'',
    has_state:names.includes('state'),has_nonce:names.includes('nonce'),
    has_pkce_challenge:names.includes('code_challenge'),
    has_pkce_method:names.includes('code_challenge_method')
   });
  }catch(e){}
 }
}
const textScope=authBoxes.length?authBoxes.map(x=>clean(x.innerText||x.textContent)).join(' '):(authPath?clean(document.body?.innerText):'');
const mfaIndicators=[],rbaIndicators=[];
const indicatorTests=[
 ['mfa',/multi[- ]factor|two[- ]factor|2fa|mfa|双重验证|双因素|多因素|两步验证|二次验证/i],
 ['backup_code',/backup code|recovery code|备用码|恢复码/i],
 ['risk_check',/risk[- ]based|suspicious (login|activity)|unusual (login|activity)|风险验证|异常登录|可疑登录/i],
 ['new_device',/new device|unrecognized device|新设备|陌生设备/i]
];
for(const [kind,re] of indicatorTests){if(re.test(textScope)){if(kind==='risk_check'||kind==='new_device')rbaIndicators.push(kind);else mfaIndicators.push(kind);}}
return {
 url_origin:location.origin,url_path:location.pathname,
 oauth_endpoints:endpoints.slice(0,20),passkey_signals:[...passkeySignals].slice(0,10),
 jose_objects:joseObjects.slice(0,20),
 mfa_indicators:mfaIndicators,rba_indicators:rbaIndicators,
 password_autocomplete_observed:passwordAutocomplete,
 otp_autocomplete_observed:otpAutocomplete
};
"""


def _stable_evidence_id(payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return "passive-auth-dom:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def collect_passive_protocol_metadata(driver, target: str) -> ModuleResult:
    """Inspect the current rendered authentication state without interaction."""
    try:
        observation = driver.execute_script(_DOM_PROBE_SCRIPT) or {}
        if not isinstance(observation, dict):
            observation = {}
    except Exception as exc:
        return ModuleResult(
            module_id=PASSIVE_PROTOCOL_MANIFEST.module_id,
            schema_version="passive-protocol-metadata-1.0",
            scan_mode=ScanMode.PASSIVE,
            errors=("dom_probe_failed:{}".format(type(exc).__name__),),
            limitations=PASSIVE_PROTOCOL_MANIFEST.limitations,
        )

    evidence_id = _stable_evidence_id(observation)
    evidence = Evidence(
        evidence_id=evidence_id,
        source_type="rendered_authentication_dom",
        level=EvidenceLevel.OBSERVED,
        observation=observation,
        artifact_hash=evidence_id.split(":", 1)[1],
    )
    endpoints = observation.get("oauth_endpoints") or []
    passkey_signals = observation.get("passkey_signals") or []
    mfa_indicators = observation.get("mfa_indicators") or []
    rba_indicators = observation.get("rba_indicators") or []

    def presence_claim(metric_id, crypto_property, present, paper_id, standard_id="", value=None, limitation=""):
        return Claim(
            metric_id=metric_id,
            crypto_property=crypto_property,
            verdict=Verdict.PASS if present else Verdict.UNKNOWN,
            value=value if value is not None else {"observed": bool(present)},
            evidence_ids=(evidence_id,) if present else (),
            paper_ref_ids=(paper_id,),
            standard_ref_ids=(standard_id,) if standard_id else (),
            limitations=(limitation,),
        )

    oauth_summary = [{
        "origin": item.get("origin", ""),
        "path": item.get("path", ""),
        "same_origin": bool(item.get("same_origin")),
        "query_parameter_names": item.get("query_parameter_names") or [],
        "response_type": item.get("response_type") or "",
        "state_observed": bool(item.get("has_state")),
        "nonce_observed": bool(item.get("has_nonce")),
        "pkce_challenge_observed": bool(item.get("has_pkce_challenge")),
        "pkce_method_observed": bool(item.get("has_pkce_method")),
    } for item in endpoints]
    claims = (
        presence_claim(
            "auth.oauth.public_request_metadata",
            "oauth_oidc_authorization_request",
            bool(oauth_summary),
            WPSE_USENIX_2018.reference_id,
            OAUTH_SECURITY_BCP_RFC9700.reference_id,
            {"observed": bool(oauth_summary), "endpoints": oauth_summary},
            "缺失参数可能在点击后的JavaScript或重定向中生成；未观察到不能判FAIL。",
        ),
        presence_claim(
            "auth.passkey.visible_control",
            "webauthn_public_key_credential",
            bool(passkey_signals),
            PASSKEYS_USENIX_2026.reference_id,
            WEBAUTHN_LEVEL_3.reference_id,
            {"observed": bool(passkey_signals), "matched_signals": passkey_signals},
            "只证明当前认证界面出现Passkey/WebAuthn控件，不触发认证器仪式。",
        ),
        presence_claim(
            "auth.mfa.public_notice",
            "multi_factor_authentication",
            bool(mfa_indicators),
            MFA_RBA_USENIX_2023.reference_id,
            "",
            {"observed": bool(mfa_indicators), "indicators": mfa_indicators,
             "enforcement_verified": False},
            "文字提示不能证明该账户或所有账户强制启用MFA。",
        ),
        presence_claim(
            "auth.rba.public_notice",
            "risk_based_authentication",
            bool(rba_indicators),
            MFA_RBA_USENIX_2023.reference_id,
            "",
            {"observed": bool(rba_indicators), "indicators": rba_indicators,
             "enforcement_verified": False},
            "风险或新设备提示不能替代受控账号的RBA对照实验。",
        ),
    )
    return ModuleResult(
        module_id=PASSIVE_PROTOCOL_MANIFEST.module_id,
        schema_version="passive-protocol-metadata-1.0",
        scan_mode=ScanMode.PASSIVE,
        claims=claims,
        evidence=(evidence,),
        limitations=PASSIVE_PROTOCOL_MANIFEST.limitations,
    )
