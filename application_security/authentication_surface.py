"""Evidence-backed, passive assessment of the public authentication surface.

This module derives claims from states the classifier already observed. It
does not click OAuth providers, trigger a passkey prompt, send an OTP, or infer
post-login enforcement from the presence or absence of public controls.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Mapping, Set

from application_security.auth_graph import build_auth_graph
from application_security.models import (
    Claim,
    ModuleManifest,
    ModuleResult,
    ScanMode,
    Verdict,
)
from application_security.paper_registry import (
    LOGIN_POLICIES_USENIX_2023,
    MFA_RBA_USENIX_2023,
    NIST_SP_800_63B,
    OAUTH_SECURITY_BCP_RFC9700,
    PASSKEYS_USENIX_2026,
    QR_LOGIN_USENIX_2025,
    WEBAUTHN_LEVEL_3,
    WPSE_USENIX_2018,
)


AUTHENTICATION_SURFACE_MANIFEST = ModuleManifest(
    module_id="b.authentication_surface",
    name_zh="公开认证能力与证据边界",
    research_question=(
        "未登录访客能够观察到哪些口令、OTP、联合登录、二维码和通行密钥路径，"
        "哪些安全性质仍必须保持未知？"
    ),
    crypto_elements=(
        "password_authenticator",
        "one_time_password",
        "oauth_oidc_token_protocol",
        "out_of_band_qr_authentication",
        "webauthn_public_key_credential",
        "risk_based_authentication",
    ),
    paper_refs=(
        LOGIN_POLICIES_USENIX_2023,
        MFA_RBA_USENIX_2023,
        WPSE_USENIX_2018,
        QR_LOGIN_USENIX_2025,
        PASSKEYS_USENIX_2026,
    ),
    standard_refs=(NIST_SP_800_63B, OAUTH_SECURITY_BCP_RFC9700, WEBAUTHN_LEVEL_3),
    safe_modes=(ScanMode.PASSIVE,),
    limitations=(
        "公开出现多个认证方式通常表示替代路线，不证明登录时强制组合为MFA。",
        "未观察到Passkey、MFA或RBA不等于网站不支持；能力可能只在账号内出现。",
        "观察到OAuth入口不证明state、nonce、PKCE、redirect_uri或令牌验证实现正确。",
        "观察到二维码入口不证明二维码内容、会话绑定、确认语义或重放防护安全。",
    ),
)


_IDENTIFIERS = {"phone", "email", "identifier", "username", "auto_signup"}
_GENERIC_METHODS = {"password", "sms", "email_code", "qr", "sso", "passkey"}


def _factor_family(method: str) -> str:
    if method == "password":
        return "knowledge_password"
    if method in {"sms", "email_code"}:
        return "possession_otp"
    if method == "passkey":
        return "public_key_passkey"
    if method == "qr":
        return "out_of_band_qr"
    if method == "sso":
        return "federated_identity"
    return ""


def analyze_authentication_surface(
    target: str,
    entries: Mapping[str, Mapping[str, Any] | None],
) -> ModuleResult:
    """Create passive claims from the additive authentication graph."""
    graph = build_auth_graph(target, entries)
    state_evidence = {
        node.node_id: node.attributes.get("evidence_id")
        for node in graph.nodes
        if node.kind == "page_state" and node.attributes.get("evidence_id")
    }
    observed: Dict[str, Dict[str, Set[str]]] = defaultdict(
        lambda: {"entries": set(), "evidence_ids": set()})

    for node in graph.nodes:
        if node.kind != "authentication_method" or ":method:" not in node.node_id:
            continue
        method = node.node_id.split(":method:", 1)[1]
        observed[method]["entries"].add(node.entry_kind)
        for state_id in node.attributes.get("observed_at", []):
            evidence_id = state_evidence.get(state_id)
            if evidence_id:
                observed[method]["evidence_ids"].add(evidence_id)

    def evidence_for(*methods: str) -> tuple[str, ...]:
        return tuple(sorted({
            evidence_id
            for method in methods
            for evidence_id in observed.get(method, {}).get("evidence_ids", set())
        }))

    methods_by_entry: Dict[str, list[str]] = {"login": [], "signup": []}
    for method, item in sorted(observed.items()):
        for entry_kind in sorted(item["entries"]):
            methods_by_entry.setdefault(entry_kind, []).append(method)

    providers = sorted(
        method for method in observed
        if method not in _IDENTIFIERS | _GENERIC_METHODS
    )
    factors = sorted({
        family for method in observed
        for family in (_factor_family(method),) if family
    })
    all_evidence = tuple(sorted({
        evidence_id
        for item in observed.values()
        for evidence_id in item["evidence_ids"]
    }))

    claims = [Claim(
        metric_id="auth.methods.publicly_observed",
        crypto_property="authentication_mechanism_inventory",
        verdict=Verdict.UNKNOWN,
        value={
            "by_entry": methods_by_entry,
            "factor_families": factors,
            "third_party_providers": providers,
        },
        evidence_ids=all_evidence,
        paper_ref_ids=(LOGIN_POLICIES_USENIX_2023.reference_id,),
        limitations=("该清单只覆盖访客安全可达的页面状态。",),
    )]

    capability_specs = (
        ("passkey", "auth.passkey.public_offer", "webauthn_public_key_credential",
         PASSKEYS_USENIX_2026.reference_id, WEBAUTHN_LEVEL_3.reference_id),
        ("qr", "auth.qr.public_offer", "out_of_band_qr_authentication",
         QR_LOGIN_USENIX_2025.reference_id, ""),
        ("sso", "auth.federation.public_offer", "oauth_oidc_federation",
         WPSE_USENIX_2018.reference_id, OAUTH_SECURITY_BCP_RFC9700.reference_id),
    )
    for method, metric_id, crypto_property, paper_id, standard_id in capability_specs:
        present = method in observed
        claims.append(Claim(
            metric_id=metric_id,
            crypto_property=crypto_property,
            verdict=Verdict.PASS if present else Verdict.UNKNOWN,
            value={
                "observed": present,
                "entries": sorted(observed.get(method, {}).get("entries", set())),
                "providers": providers if method == "sso" else [],
            },
            evidence_ids=evidence_for(method),
            paper_ref_ids=(paper_id,),
            standard_ref_ids=(standard_id,) if standard_id else (),
            limitations=(
                "PASS只表示公开入口被观察到，不表示协议实现或账户配置已经通过安全验证。"
                if present else "未观察到不等于不支持，不能据此给出FAIL。",
            ),
        ))

    claims.extend((
        Claim(
            metric_id="auth.mfa.enforcement",
            crypto_property="multi_factor_authentication",
            verdict=Verdict.UNKNOWN,
            value={
                "public_factor_families": factors,
                "combination_enforcement_verified": False,
            },
            evidence_ids=all_evidence,
            paper_ref_ids=(MFA_RBA_USENIX_2023.reference_id,),
            standard_ref_ids=(NIST_SP_800_63B.reference_id,),
            limitations=("多个公开方式可能只是互斥登录选项，不能当作MFA。",),
        ),
        Claim(
            metric_id="auth.rba.enforcement",
            crypto_property="risk_based_authentication",
            verdict=Verdict.UNKNOWN,
            value={"observable_without_account": False},
            evidence_ids=(),
            paper_ref_ids=(MFA_RBA_USENIX_2023.reference_id,),
            limitations=("RBA通常需要受控账号和风险条件对照实验，访客模式不作推断。",),
        ),
    ))

    return ModuleResult(
        module_id=AUTHENTICATION_SURFACE_MANIFEST.module_id,
        schema_version="authentication-surface-1.0",
        scan_mode=ScanMode.PASSIVE,
        claims=tuple(claims),
        evidence=graph.evidence,
        limitations=AUTHENTICATION_SURFACE_MANIFEST.limitations,
    )
