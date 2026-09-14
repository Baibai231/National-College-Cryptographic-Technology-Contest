"""Passive, evidence-bounded account-recovery surface analysis."""

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
from application_security.paper_registry import PRIVATE_RECOVERY_USENIX_2024


RECOVERY_MANIFEST = ModuleManifest(
    module_id="b.account_recovery_surface",
    name_zh="账号恢复入口与密码学证据边界",
    research_question=(
        "未登录页面公开了哪些恢复入口和恢复因子，哪些令牌、撤销与隐私性质"
        "必须留给授权账号实验？"
    ),
    crypto_elements=(
        "one_time_recovery_token",
        "token_entropy_and_expiry",
        "authenticator_revocation",
        "oblivious_pseudorandom_function",
    ),
    paper_refs=(PRIVATE_RECOVERY_USENIX_2024,),
    safe_modes=(ScanMode.PASSIVE, ScanMode.AUTHORIZED_ACCOUNT),
    limitations=(
        "访客模式只读取已渲染恢复入口，不填写邮箱或手机号，也不发送恢复请求。",
        "公开入口和因子提示不能证明恢复令牌随机、一次性、有时效或会撤销旧凭据。",
        "论文的OPRF隐私协议只能在实现公开或授权对照时验证，不能凭普通邮箱恢复界面推断。",
    ),
)


_RECOVERY_DOM_SCRIPT = r"""
const clean=v=>(v||'').normalize('NFKC').replace(/\s+/g,' ').trim().toLowerCase();
const visible=el=>{try{const r=el.getBoundingClientRect(),s=getComputedStyle(el);
 return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'
   &&!el.disabled&&el.getAttribute('aria-disabled')!=='true';}catch(e){return false;}};
const recoveryRe=/(forgot|forget|reset|recover).{0,20}(password|account)|(password|account).{0,20}(reset|recovery)|忘记.{0,8}(密码|口令)|找回.{0,8}(密码|口令|账号)|重置.{0,8}(密码|口令)|帳號復原|密碼重設/i;
const recoveryPath=/\/(forgot|forget|recover|recovery|reset)([-_/](password|account))?(\/|$)/i.test(location.pathname);
const authPath=/\/(login|signin|sign-in|auth|account|forgot|forget|recover|recovery|reset)(\/|$)/i.test(location.pathname);
const authBoxes=[...document.querySelectorAll("[role='dialog'],[aria-modal='true'],form,[class*='login'],[class*='signin'],[class*='auth']")].filter(visible);
const hasAuthInput=[...document.querySelectorAll("input[type='password'],input[autocomplete='username'],input[autocomplete='current-password']")].some(visible);
const inContext=el=>authPath||hasAuthInput||authBoxes.some(box=>box===el||box.contains(el));
const controls=[];
for(const el of document.querySelectorAll("a[href],button,[role='button'],[role='link']")){
 if(!visible(el)||!inContext(el))continue;
 const label=clean([el.innerText,el.textContent,el.getAttribute('aria-label'),el.title].join(' '));
 if(!recoveryRe.test(label))continue;
 let originRelation='unknown',path='';
 const href=el.getAttribute('href')||'';
 try{if(href&&!href.startsWith('javascript:')){const u=new URL(href,location.href);
  originRelation=u.origin===location.origin?'same_origin':'cross_origin';path=u.pathname;}}
 catch(e){}
 controls.push({origin_relation:originRelation,path:path,interactive:true});
}
const scope=recoveryPath?document:[...document.querySelectorAll('form')].find(f=>visible(f)&&recoveryRe.test(clean(f.innerText||f.textContent)))||null;
const factors=new Set(); let formFieldCount=0, captchaObserved=false;
if(scope){
 for(const el of scope.querySelectorAll('input,select,textarea')){
  if(!visible(el))continue; formFieldCount++;
  const s=clean([el.type,el.name,el.id,el.placeholder,el.autocomplete,el.getAttribute('aria-label')].join(' '));
  if(/mail/.test(s))factors.add('email');
  if(/phone|mobile|tel|手机|手机号/.test(s))factors.add('sms');
  if(/security.{0,8}(question|answer)|安全问题|密保/.test(s))factors.add('security_question');
  if(/backup.{0,5}code|recovery.{0,5}code|备用码|恢复码/.test(s))factors.add('backup_code');
 }
 const t=clean(scope.innerText||scope.textContent);
 if(/trusted device|known device|可信设备|常用设备/.test(t))factors.add('trusted_device');
 if(/passkey|security key|通行密钥|安全密钥/.test(t))factors.add('passkey');
 if(/customer support|contact support|客服|人工申诉/.test(t))factors.add('customer_support');
 captchaObserved=/captcha|recaptcha|hcaptcha|人机验证|图形验证码|滑块/.test(t)
   ||!!scope.querySelector("iframe[src*='captcha'],[class*='captcha'],[id*='captcha']");
}
return {recovery_path_observed:recoveryPath,recovery_control_count:controls.length,
 recovery_controls:controls.slice(0,10),factor_hints:[...factors].sort(),
 recovery_form_field_count:formFieldCount,captcha_observed:captchaObserved,
 input_performed:false,recovery_request_sent:false,token_observed:false};
"""


def _evidence_id(observation: Dict[str, Any]) -> str:
    raw = json.dumps(observation, ensure_ascii=False, sort_keys=True, default=str)
    return "account-recovery:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def analyze_recovery_observation(target: str, observation: Dict[str, Any]) -> ModuleResult:
    """Turn a redacted DOM observation into conservative recovery claims."""
    observation = dict(observation or {})
    evidence_id = _evidence_id(observation)
    entry_observed = bool(
        observation.get("recovery_path_observed")
        or observation.get("recovery_control_count")
    )
    factors = sorted({str(item) for item in observation.get("factor_hints") or []})
    coverage_items = (
        entry_observed,
        bool(factors),
        bool(observation.get("recovery_form_field_count")),
    )
    coverage = sum(coverage_items) / len(coverage_items)
    lifecycle_checks = {
        "entropy_verified": False,
        "one_time_verified": False,
        "expiry_verified": False,
        "old_sessions_revoked_verified": False,
        "old_authenticators_revoked_verified": False,
    }
    evidence = Evidence(
        evidence_id=evidence_id,
        source_type="rendered_account_recovery_dom",
        level=EvidenceLevel.OBSERVED,
        observation=observation,
        artifact_hash=evidence_id.split(":", 1)[1],
    )
    paper_ids = (PRIVATE_RECOVERY_USENIX_2024.reference_id,)
    claims = (
        Claim(
            metric_id="auth.recovery.public_entry",
            crypto_property="account_recovery_entry",
            verdict=Verdict.PASS if entry_observed else Verdict.UNKNOWN,
            value={"observed": entry_observed,
                   "control_count": int(observation.get("recovery_control_count") or 0),
                   "recovery_path_observed": bool(observation.get("recovery_path_observed"))},
            evidence_ids=(evidence_id,) if entry_observed else (),
            paper_ref_ids=paper_ids,
            limitations=("PASS只证明公开恢复入口存在，不评价恢复安全性。",),
        ),
        Claim(
            metric_id="auth.recovery.factor_surface",
            crypto_property="recovery_factor_inventory",
            verdict=Verdict.UNKNOWN,
            value={
                "factor_hints": factors,
                "captcha_observed": bool(observation.get("captcha_observed")),
                "evidence_coverage": round(coverage, 4),
                "coverage_formula": "C_rec=(I_entry+I_factor+I_form)/3",
            },
            evidence_ids=(evidence_id,) if entry_observed else (),
            paper_ref_ids=paper_ids,
            limitations=("因子提示不证明该因子必需、充分或不会被更弱路径绕过。",),
        ),
        Claim(
            metric_id="auth.recovery.token_lifecycle",
            crypto_property="one_time_entropy_expiry_and_revocation",
            verdict=Verdict.UNKNOWN,
            value={
                **lifecycle_checks,
                "joint_formula": "V_rec=V_entropy AND V_one_time AND V_expiry AND V_session_revoke AND V_auth_revoke",
                "recovery_request_sent": bool(observation.get("recovery_request_sent")),
            },
            evidence_ids=(),
            paper_ref_ids=paper_ids,
            limitations=("访客模式不发送恢复请求，因此无法取得或重复使用恢复Token。",),
        ),
        Claim(
            metric_id="auth.recovery.private_identity_protocol",
            crypto_property="oblivious_pseudorandom_function",
            verdict=Verdict.UNKNOWN,
            value={"oprf_verified": False, "server_account_list_privacy_verified": False},
            evidence_ids=(),
            paper_ref_ids=paper_ids,
            limitations=("普通界面不能证明论文所述OPRF或服务端用户目录隐私。",),
        ),
    )
    return ModuleResult(
        module_id=RECOVERY_MANIFEST.module_id,
        schema_version="account-recovery-surface-1.0",
        scan_mode=ScanMode.PASSIVE,
        claims=claims,
        evidence=(evidence,),
        limitations=RECOVERY_MANIFEST.limitations,
    )


def collect_recovery_surface(driver, target: str) -> ModuleResult:
    try:
        observation = driver.execute_script(_RECOVERY_DOM_SCRIPT) or {}
        if not isinstance(observation, dict):
            observation = {}
    except Exception as exc:
        return ModuleResult(
            module_id=RECOVERY_MANIFEST.module_id,
            schema_version="account-recovery-surface-1.0",
            scan_mode=ScanMode.PASSIVE,
            errors=("recovery_dom_probe_failed:" + type(exc).__name__,),
            limitations=RECOVERY_MANIFEST.limitations,
        )
    return analyze_recovery_observation(target, observation)
