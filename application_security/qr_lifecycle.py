"""Privacy-preserving passive lifecycle observation for QR-code login."""

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
from application_security.paper_registry import QR_LOGIN_USENIX_2025


QR_LIFECYCLE_MANIFEST = ModuleManifest(
    module_id="b.qr_login_lifecycle",
    name_zh="二维码登录生成与生命周期公开测量",
    research_question=(
        "未扫码访客能否观察到二维码登录及其页内刷新，哪些QrId、SessionID与Token"
        "安全性质必须留给授权实验？"
    ),
    crypto_elements=(
        "qr_identifier_unpredictability",
        "session_identifier_binding",
        "one_time_token_lifecycle",
        "authentication_token_integrity",
    ),
    paper_refs=(QR_LOGIN_USENIX_2025,),
    safe_modes=(ScanMode.PASSIVE, ScanMode.AUTHORIZED_ACCOUNT),
    limitations=(
        "公开模式不解码二维码、不扫码、不修改请求、不重放QrId，也不尝试登录。",
        "页面内二维码变化只证明展示对象刷新，不证明QrId随机、不可控、一次性或绑定SessionID。",
        "扫码后的身份校验、用户确认、pc_token完整性与隐私只能在授权账号模式验证。",
    ),
)


_INSTALL_SCRIPT = r"""
(()=>{if(window.__cryptoscopeQrLifecycle)return;
 const state={samples:0,comparisons:0,changes:0,previous:null,key:null,keyError:false};
 state.key=crypto.subtle.generateKey({name:'HMAC',hash:'SHA-256'},false,['sign'])
   .catch(()=>{state.keyError=true;return null;});
 const clean=v=>(v||'').normalize('NFKC').replace(/\s+/g,' ').trim().toLowerCase();
 const visible=el=>{try{const r=el.getBoundingClientRect(),s=getComputedStyle(el);
  return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden';}catch(e){return false;}};
 const semanticRe=/scan.{0,20}(qr|code).{0,20}(login|sign in)|qr.{0,10}(login|sign in)|扫码.{0,8}(登录|登陆)|二维码.{0,8}(登录|登陆)|掃碼.{0,8}(登入|登錄)/i;
 const rawFor=el=>{try{
  if(el.tagName==='CANVAS')return 'canvas:'+el.width+'x'+el.height+':'+el.toDataURL('image/png');
  if(el.tagName==='IMG')return 'img:'+(el.currentSrc||el.src||'')+':'+el.naturalWidth+'x'+el.naturalHeight;
  if(el.tagName==='SVG')return 'svg:'+new XMLSerializer().serializeToString(el);
  const bg=getComputedStyle(el).backgroundImage||'';return 'background:'+bg;
 }catch(e){return '';}};
 const findCandidates=()=>{
  const roots=[];
  for(const el of document.querySelectorAll("[role='dialog'],[aria-modal='true'],form,section,main,div")){
   if(!visible(el))continue; const text=clean(el.innerText||el.textContent);
   if(text.length<=600&&semanticRe.test(text))roots.push(el);
  }
  const out=[],seen=new Set();
  for(const root of roots){
   for(const el of root.querySelectorAll("img,canvas,svg,[class*='qr'],[id*='qr'],[class*='Qr'],[id*='Qr']")){
    if(!visible(el)||seen.has(el))continue; const raw=rawFor(el); if(!raw)continue;
    seen.add(el);out.push({el,raw});
   }
  }
  return out;
 };
 const hmac=async raw=>{
  const key=await state.key;if(!key)return '';
  const bytes=new TextEncoder().encode(raw),sig=await crypto.subtle.sign('HMAC',key,bytes);
  return [...new Uint8Array(sig)].map(x=>x.toString(16).padStart(2,'0')).join('');
 };
 window.__cryptoscopeQrLifecycle={sample:async()=>{
  const candidates=findCandidates(),tags=[];
  for(const item of candidates){const tag=await hmac(item.raw);if(tag)tags.push(tag);}
  tags.sort(); const current=tags.join('|'); let changed=false,compared=false;
  if(state.previous!==null&&current&&state.previous){state.comparisons++;compared=true;
   changed=current!==state.previous;if(changed)state.changes++;}
  if(current)state.previous=current;state.samples++;
  return {qr_observed:tags.length>0,qr_element_count:tags.length,sample_count:state.samples,
   comparison_count:state.comparisons,change_count:state.changes,
   compared_with_previous:compared,changed_since_previous:changed,
   crypto_hmac_available:!state.keyError&&!!(await state.key),
   raw_qr_content_retained:false,hmac_key_or_tag_returned:false,
   qr_decoded:false,scan_performed:false,login_attempted:false};
 }};
})();
"""

_SAMPLE_SCRIPT = r"""
const done=arguments[arguments.length-1];
(async()=>{try{
 if(!window.__cryptoscopeQrLifecycle){done({error:'observer_not_installed'});return;}
 done(await window.__cryptoscopeQrLifecycle.sample());
}catch(e){done({error:'sample_failed'});}})();
"""


def install_qr_lifecycle_observer(driver) -> tuple[str, ...]:
    errors = []
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument", {"source": _INSTALL_SCRIPT})
    except Exception as exc:
        errors.append("qr_install_cdp:" + type(exc).__name__)
    try:
        driver.execute_script(_INSTALL_SCRIPT)
    except Exception as exc:
        errors.append("qr_install_current:" + type(exc).__name__)
    return tuple(errors)


def _evidence_id(observation: Dict[str, Any]) -> str:
    raw = json.dumps(observation, ensure_ascii=False, sort_keys=True, default=str)
    return "qr-lifecycle:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def analyze_qr_observations(
    target: str,
    observations: Iterable[Dict[str, Any]],
    errors: Iterable[str] = (),
) -> ModuleResult:
    samples = [dict(item) for item in observations if isinstance(item, dict)]
    qr_observed = any(item.get("qr_observed") for item in samples)
    comparisons = max((int(item.get("comparison_count") or 0) for item in samples), default=0)
    changes = max((int(item.get("change_count") or 0) for item in samples), default=0)
    refresh_rate = (changes / comparisons) if comparisons else None
    safe_guard = bool(samples) and all(
        not item.get("raw_qr_content_retained")
        and not item.get("hmac_key_or_tag_returned")
        and not item.get("qr_decoded")
        and not item.get("scan_performed")
        and not item.get("login_attempted")
        for item in samples
    )
    observation = {
        "qr_observed": qr_observed,
        "sample_count": len(samples),
        "comparison_count": comparisons,
        "change_count": changes,
        "refresh_rate": round(refresh_rate, 4) if refresh_rate is not None else None,
        "raw_qr_content_retained": False,
        "hmac_key_or_tag_returned": False,
        "qr_decoded": False,
        "scan_performed": False,
        "login_attempted": False,
    }
    evidence_id = _evidence_id(observation)
    evidence = Evidence(
        evidence_id=evidence_id,
        source_type="browser_local_qr_equality_observation",
        level=EvidenceLevel.OBSERVED,
        observation=observation,
        artifact_hash=evidence_id.split(":", 1)[1],
    )
    paper_ids = (QR_LOGIN_USENIX_2025.reference_id,)
    unknown_security = {
        "session_id_bound_to_qr_id_verified": False,
        "qr_id_unpredictable_verified": False,
        "qr_id_server_generated_verified": False,
        "qr_id_one_time_verified": False,
        "identity_token_binding_verified": False,
        "explicit_mobile_confirmation_verified": False,
        "post_confirmation_privacy_verified": False,
    }
    claims = (
        Claim(
            metric_id="auth.qr.rendered_login_code",
            crypto_property="qr_login_generation_phase",
            verdict=Verdict.PASS if qr_observed else Verdict.UNKNOWN,
            value={"observed": qr_observed, "sample_count": len(samples)},
            evidence_ids=(evidence_id,) if qr_observed else (),
            paper_ref_ids=paper_ids,
            limitations=("PASS只证明认证语境中存在二维码展示对象。",),
        ),
        Claim(
            metric_id="auth.qr.page_refresh",
            crypto_property="qr_identifier_display_lifecycle",
            verdict=Verdict.UNKNOWN,
            value={
                "comparison_count": comparisons,
                "change_count": changes,
                "refresh_rate": round(refresh_rate, 4) if refresh_rate is not None else None,
                "formula": "R_QR=N_changed/N_compared",
            },
            evidence_ids=(evidence_id,) if comparisons else (),
            paper_ref_ids=paper_ids,
            limitations=("刷新与否均不能单独证明QrId随机性、过期或一次性。",),
        ),
        Claim(
            metric_id="auth.qr.protocol_security_variables",
            crypto_property="qr_session_token_binding_and_freshness",
            verdict=Verdict.UNKNOWN,
            value={
                **unknown_security,
                "joint_formula": "V_QR=V_bind AND V_random AND V_server_gen AND V_one_time AND V_token_bind AND V_confirm",
            },
            evidence_ids=(),
            paper_ref_ids=paper_ids,
            limitations=("论文六类缺陷需要授权流量与人工确认；公开模式不执行动态攻击测试。",),
        ),
        Claim(
            metric_id="auth.qr.passive_safety_guard",
            crypto_property="measurement_non_interference",
            verdict=Verdict.PASS if safe_guard else Verdict.UNKNOWN,
            value={
                "guard_passed": safe_guard,
                "formula": "I_QR_guard=I[N_decode=N_scan=N_replay=N_login=N_raw_return=0]",
            },
            evidence_ids=(evidence_id,) if samples else (),
            paper_ref_ids=paper_ids,
            limitations=("守卫通过只说明本探针没有执行扫码、解码、重放或登录。",),
        ),
    )
    return ModuleResult(
        module_id=QR_LIFECYCLE_MANIFEST.module_id,
        schema_version="qr-login-lifecycle-1.0",
        scan_mode=ScanMode.PASSIVE,
        claims=claims,
        evidence=(evidence,),
        errors=tuple(str(item) for item in errors),
        limitations=QR_LIFECYCLE_MANIFEST.limitations,
    )


def collect_qr_lifecycle_sample(driver, target: str, install: bool = True) -> ModuleResult:
    errors = list(install_qr_lifecycle_observer(driver) if install else ())
    observations = []
    try:
        item = driver.execute_async_script(_SAMPLE_SCRIPT) or {}
        if isinstance(item, dict) and item.get("error"):
            errors.append("qr_sample:" + str(item["error"]))
        elif isinstance(item, dict):
            observations.append(item)
    except Exception as exc:
        errors.append("qr_sample:" + type(exc).__name__)
    return analyze_qr_observations(target, observations, errors)
