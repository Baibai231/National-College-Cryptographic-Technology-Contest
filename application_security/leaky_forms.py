"""Safe-interaction measurement of pre-submit form-secret handling."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable

from application_security.models import (
    Claim,
    Evidence,
    EvidenceLevel,
    ModuleManifest,
    ModuleResult,
    ScanMode,
    Verdict,
)
from application_security.paper_registry import LEAKY_FORMS_USENIX_2022


LEAKY_FORMS_MANIFEST = ModuleManifest(
    module_id="b.pre_submit_secret_exposure",
    name_zh="表单秘密提交前访问与外传探针",
    research_question="合成邮箱或口令在用户提交表单前是否被脚本读取或尝试发送到第一方/第三方？",
    crypto_elements=(
        "password_secret_confidentiality",
        "synthetic_canary_derivation",
        "pre_submit_data_flow_integrity",
    ),
    paper_refs=(LEAKY_FORMS_USENIX_2022,),
    safe_modes=(ScanMode.SAFE_INTERACTION,),
    limitations=(
        "只填写随机合成标记，不使用真人邮箱、账号或口令，且绝不提交表单。",
        "命中合成标记的外发尝试会在浏览器内记录后阻断；因此测到的是尝试而非服务端实际接收。",
        "未观察到不等于站点从不采集；探针只覆盖本次页面、等待窗口和已包装通道。",
        "脚本读取输入值不等于外传，必须与网络命中分开报告。",
    ),
)


_INSTALL_SCRIPT = r"""
(()=>{if(window.__cryptoscopeLeakyForms)return;
 const state={markers:[],filled:[],reads:{email:0,password:0},attempts:[],submitCount:0,forwardedCanary:0};
 const nativeValue=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value');
 const relation=url=>{try{return new URL(url,location.href).origin===location.origin?'first_party':'third_party';}catch(e){return 'unknown';}};
 const bytesToB64=bytes=>btoa(String.fromCharCode(...bytes));
 const utf8=v=>new TextEncoder().encode(v);
 const valueForms=async value=>{
  const digest=await crypto.subtle.digest('SHA-256',utf8(value));
  const hex=[...new Uint8Array(digest)].map(x=>x.toString(16).padStart(2,'0')).join('');
  return [value,value.toLowerCase(),encodeURIComponent(value),bytesToB64(utf8(value)),hex];
 };
 const stringify=v=>{try{
  if(v==null)return '';if(typeof v==='string')return v;
  if(v instanceof URLSearchParams)return v.toString();
  if(v instanceof FormData){let out='';for(const [k,x] of v.entries())if(typeof x==='string')out+=k+'='+x+'&';return out;}
  if(v instanceof ArrayBuffer)return new TextDecoder().decode(v);
  if(ArrayBuffer.isView(v))return new TextDecoder().decode(v);
  return JSON.stringify(v);
 }catch(e){return '';}};
 const detect=(channel,url,payload)=>{
  const hay=(String(url||'')+' '+stringify(payload));const hits=[];
  for(const marker of state.markers){if(marker.forms.some(f=>f&&hay.includes(f)))hits.push(marker.kind);}
  if(!hits.length)return false;
  state.attempts.push({channel:channel,destination_relation:relation(url),kinds:[...new Set(hits)].sort(),blocked:true});
  return true;
 };
 Object.defineProperty(HTMLInputElement.prototype,'value',{
  configurable:nativeValue.configurable,enumerable:nativeValue.enumerable,
  get:function(){const value=nativeValue.get.call(this);const kind=this.dataset?.cryptoscopeCanaryKind;
   if(kind&&(kind==='email'||kind==='password'))state.reads[kind]++;return value;},
  set:function(v){return nativeValue.set.call(this,v);}
 });
 const originalFetch=window.fetch;
 window.fetch=function(input,init){const url=typeof input==='string'?input:(input&&input.url)||'';
  if(detect('fetch',url,init&&init.body))return Promise.reject(new DOMException('synthetic canary blocked','AbortError'));
  return originalFetch.apply(this,arguments);};
 const open=XMLHttpRequest.prototype.open,send=XMLHttpRequest.prototype.send;
 XMLHttpRequest.prototype.open=function(method,url){this.__cryptoscopeUrl=url;return open.apply(this,arguments);};
 XMLHttpRequest.prototype.send=function(body){if(detect('xhr',this.__cryptoscopeUrl,body)){try{this.abort();}catch(e){}return;}return send.apply(this,arguments);};
 const beacon=navigator.sendBeacon&&navigator.sendBeacon.bind(navigator);
 if(beacon)navigator.sendBeacon=function(url,data){if(detect('beacon',url,data))return false;return beacon(url,data);};
 const submit=HTMLFormElement.prototype.submit,requestSubmit=HTMLFormElement.prototype.requestSubmit;
 HTMLFormElement.prototype.submit=function(){state.submitCount++;if(detect('form',this.action,new FormData(this)))return;return submit.apply(this,arguments);};
 if(requestSubmit)HTMLFormElement.prototype.requestSubmit=function(){state.submitCount++;if(detect('form',this.action,new FormData(this)))return;return requestSubmit.apply(this,arguments);};
 window.__cryptoscopeLeakyForms={
  fill:async()=>{
   const rand=new Uint8Array(16);crypto.getRandomValues(rand);const suffix=[...rand].map(x=>x.toString(16).padStart(2,'0')).join('');
   const values={email:'cs-'+suffix+'@example.invalid',password:'CS!'+suffix+'aZ9'};
   const visible=el=>{try{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'&&!el.disabled;}catch(e){return false;}};
   for(const kind of ['email','password']){
    const selector=kind==='password'?"input[type='password']":"input[type='email'],input[autocomplete='email']";
    const el=[...document.querySelectorAll(selector)].find(visible);if(!el)continue;
    state.markers.push({kind:kind,forms:await valueForms(values[kind])});
    el.dataset.cryptoscopeCanaryKind=kind;nativeValue.set.call(el,values[kind]);state.filled.push(kind);
    el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));el.dispatchEvent(new Event('blur',{bubbles:true}));
   }
   return {filled_kinds:[...state.filled],filled_count:state.filled.length,real_data_used:false,form_submit_performed:false,canary_value_returned:false};
  },
  collect:()=>({filled_kinds:[...state.filled],filled_count:state.filled.length,
   script_reads:{email:state.reads.email,password:state.reads.password},
   network_attempts:state.attempts.map(x=>({...x})),submit_count:state.submitCount,
   forwarded_canary_count:state.forwardedCanary,real_data_used:false,
   canary_value_returned:false,request_payload_returned:false,full_url_returned:false})
 };
})();
"""

_FILL_SCRIPT = r"""
const done=arguments[arguments.length-1];
(async()=>{try{done(await window.__cryptoscopeLeakyForms.fill());}catch(e){done({error:'fill_failed'});}})();
"""

_COLLECT_SCRIPT = "return window.__cryptoscopeLeakyForms ? window.__cryptoscopeLeakyForms.collect() : {error:'observer_not_installed'};"


def install_leaky_forms_observer(driver) -> tuple[str, ...]:
    errors = []
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": _INSTALL_SCRIPT})
    except Exception as exc:
        errors.append("leaky_install_cdp:" + type(exc).__name__)
    try:
        driver.execute_script(_INSTALL_SCRIPT)
    except Exception as exc:
        errors.append("leaky_install_current:" + type(exc).__name__)
    return tuple(errors)


def _evidence_id(observation: Dict[str, Any]) -> str:
    raw = json.dumps(observation, ensure_ascii=False, sort_keys=True, default=str)
    return "pre-submit-secret:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def analyze_leaky_form_observation(
    target: str,
    observation: Dict[str, Any],
    errors: Iterable[str] = (),
) -> ModuleResult:
    observation = dict(observation or {})
    filled_count = int(observation.get("filled_count") or 0)
    attempts = [item for item in observation.get("network_attempts") or [] if isinstance(item, dict)]
    third_party = sum(item.get("destination_relation") == "third_party" for item in attempts)
    first_party = sum(item.get("destination_relation") == "first_party" for item in attempts)
    password_attempts = sum("password" in (item.get("kinds") or []) for item in attempts)
    email_attempts = sum("email" in (item.get("kinds") or []) for item in attempts)
    reads = observation.get("script_reads") if isinstance(observation.get("script_reads"), dict) else {}
    rate = len(attempts) / filled_count if filled_count else None
    sanitized = {
        "filled_kinds": sorted({str(x) for x in observation.get("filled_kinds") or []}),
        "filled_count": filled_count,
        "script_reads": {"email": int(reads.get("email") or 0), "password": int(reads.get("password") or 0)},
        "network_attempt_count": len(attempts),
        "first_party_attempt_count": first_party,
        "third_party_attempt_count": third_party,
        "email_attempt_count": email_attempts,
        "password_attempt_count": password_attempts,
        "channels": sorted({str(item.get("channel")) for item in attempts if item.get("channel")}),
        "all_matching_attempts_blocked": bool(attempts) and all(item.get("blocked") for item in attempts),
        "submit_count": int(observation.get("submit_count") or 0),
        "forwarded_canary_count": int(observation.get("forwarded_canary_count") or 0),
        "real_data_used": bool(observation.get("real_data_used")),
        "canary_value_returned": False,
        "request_payload_returned": False,
        "full_url_returned": False,
    }
    guard = bool(filled_count) and sanitized["submit_count"] == 0 and sanitized["forwarded_canary_count"] == 0 and not sanitized["real_data_used"]
    evidence_id = _evidence_id(sanitized)
    evidence = Evidence(
        evidence_id=evidence_id,
        source_type="blocked_pre_submit_synthetic_canary_flow",
        level=EvidenceLevel.OBSERVED,
        observation=sanitized,
        artifact_hash=evidence_id.split(":", 1)[1],
    )
    if third_party and password_attempts:
        verdict = Verdict.FAIL
    elif third_party:
        verdict = Verdict.WEAK
    else:
        verdict = Verdict.UNKNOWN
    paper_ids = (LEAKY_FORMS_USENIX_2022.reference_id,)
    claims = (
        Claim(
            metric_id="auth.form_secret.script_access",
            crypto_property="pre_submit_secret_access",
            verdict=Verdict.UNKNOWN,
            value={"reads": sanitized["script_reads"], "filled_count": filled_count},
            evidence_ids=(evidence_id,) if filled_count else (),
            paper_ref_ids=paper_ids,
            limitations=("脚本读取可能来自合法表单逻辑，不能单独判定外传。",),
        ),
        Claim(
            metric_id="auth.form_secret.network_exfiltration_attempt",
            crypto_property="pre_submit_secret_confidentiality",
            verdict=verdict,
            value={
                "attempt_count": len(attempts),
                "first_party_attempt_count": first_party,
                "third_party_attempt_count": third_party,
                "email_attempt_count": email_attempts,
                "password_attempt_count": password_attempts,
                "channels": sanitized["channels"],
                "attempt_rate": round(rate, 4) if rate is not None else None,
                "formula": "E_pre=N_detected_pre_submit/N_filled_fields",
                "attempts_blocked": sanitized["all_matching_attempts_blocked"],
            },
            evidence_ids=(evidence_id,) if attempts else (),
            paper_ref_ids=paper_ids,
            limitations=("FAIL仅用于提交前第三方口令标记外发尝试；请求被探针阻断，未证明服务端收到。",),
        ),
        Claim(
            metric_id="auth.form_secret.safe_interaction_guard",
            crypto_property="measurement_non_interference",
            verdict=Verdict.PASS if guard else Verdict.UNKNOWN,
            value={
                "guard_passed": guard,
                "formula": "I_leak_guard=I[N_submit=0 AND N_forwarded_canary=0 AND N_real_data=0]",
                "form_submit_count": sanitized["submit_count"],
                "forwarded_canary_count": sanitized["forwarded_canary_count"],
                "real_data_used": sanitized["real_data_used"],
            },
            evidence_ids=(evidence_id,) if filled_count else (),
            paper_ref_ids=paper_ids,
            limitations=("守卫通过只说明本轮没有提交、真实数据或已转发的合成标记。",),
        ),
    )
    return ModuleResult(
        module_id=LEAKY_FORMS_MANIFEST.module_id,
        schema_version="pre-submit-secret-exposure-1.0",
        scan_mode=ScanMode.SAFE_INTERACTION,
        claims=claims,
        evidence=(evidence,),
        errors=tuple(str(item) for item in errors),
        limitations=LEAKY_FORMS_MANIFEST.limitations,
    )


def run_leaky_forms_safe_interaction(driver, target: str) -> ModuleResult:
    errors = list(install_leaky_forms_observer(driver))
    observation: Dict[str, Any] = {}
    try:
        fill = driver.execute_async_script(_FILL_SCRIPT) or {}
        if isinstance(fill, dict) and fill.get("error"):
            errors.append("leaky_fill:" + str(fill["error"]))
        observation = driver.execute_script(_COLLECT_SCRIPT) or {}
        if not isinstance(observation, dict):
            observation = {}
    except Exception as exc:
        errors.append("leaky_runtime:" + type(exc).__name__)
    return analyze_leaky_form_observation(target, observation, errors)
