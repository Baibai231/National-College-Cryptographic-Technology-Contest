"""Bounded probes for public passkey-related well-known metadata.

The endpoint set is copied from the detector published with the USENIX
Security 2026 paper *The State of Passkeys*.  Only the two WebAuthn/passkey
JSON resources are fetched.  Enrollment/management URLs and related origins
are summarized but never followed or retained verbatim.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable, Dict, List, Mapping, Tuple
from urllib.parse import urlsplit, urlunsplit

from application_security.models import (
    Claim,
    Evidence,
    EvidenceLevel,
    ModuleManifest,
    ModuleResult,
    ScanMode,
    Verdict,
)
from application_security.oidc_discovery import (
    JsonFetchResult,
    SafeFetchError,
    safe_fetch_json,
)
from application_security.paper_registry import (
    PASSKEY_ENDPOINTS_W3C,
    PASSKEYS_USENIX_2026,
    WEBAUTHN_LEVEL_3,
)


PASSKEY_WELL_KNOWN_MANIFEST = ModuleManifest(
    module_id="b.passkey_well_known_metadata",
    name_zh="Passkey Well-Known公开元数据探针",
    research_question=(
        "站点是否通过论文检测器使用的两个公开well-known资源发布"
        "Passkey管理入口或WebAuthn related-origins关系？"
    ),
    crypto_elements=(
        "relying_party_passkey_endpoint_discovery",
        "webauthn_related_origin_scope",
        "public_key_credential_management_surface",
    ),
    paper_refs=(PASSKEYS_USENIX_2026,),
    standard_refs=(PASSKEY_ENDPOINTS_W3C, WEBAUTHN_LEVEL_3),
    safe_modes=(ScanMode.PASSIVE,),
    limitations=(
        "只请求/.well-known/passkey-endpoints和/.well-known/webauthn两个JSON资源。",
        "只允许HTTPS 443公网地址；DNS固定、TLS证书验证、跳转和响应大小均有界。",
        "不访问enroll/manage链接，不保存链接或related-origin原值，只保存计数与句法结构。",
        "well-known存在只证明公开声明，不证明Passkey注册、登录或服务端验签正确。",
        "未获取可能是站点未发布、地区/网络差异或短暂故障，必须保持UNKNOWN。",
    ),
)


_SAFE_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")


def _origin_from_target(target: str) -> str:
    try:
        parsed = urlsplit(target)
        if (parsed.scheme != "https" or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443)):
            raise ValueError
        host = parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except (ValueError, UnicodeError, AttributeError) as exc:
        raise SafeFetchError("invalid_origin") from exc
    netloc = "[{}]".format(host) if ":" in host else host
    return urlunsplit(("https", netloc, "", "", ""))


def _valid_https_url(value: Any) -> Tuple[bool, str]:
    if not isinstance(value, str) or not value or len(value) > 4096:
        return False, ""
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.fragment or parsed.port not in (None, 443)):
            return False, ""
        return True, parsed.hostname.rstrip(".").lower()
    except (ValueError, AttributeError):
        return False, ""


def _summarize_endpoints(document: Mapping[str, Any], origin_host: str) -> Dict[str, Any]:
    known_present: List[str] = []
    valid_https = 0
    same_host = 0
    external_host = 0
    malformed = 0
    for key in ("enroll", "manage"):
        if key not in document:
            continue
        known_present.append(key)
        valid, host = _valid_https_url(document.get(key))
        if not valid:
            malformed += 1
            continue
        valid_https += 1
        if host == origin_host:
            same_host += 1
        else:
            external_host += 1
    extra_keys = sorted({
        key for key in document
        if isinstance(key, str) and _SAFE_KEY.fullmatch(key)
        and key not in {"enroll", "manage"}
    })[:50]
    return {
        "known_fields_present": known_present,
        "known_fields_present_count": len(known_present),
        "valid_https_endpoint_count": valid_https,
        "same_host_endpoint_count": same_host,
        "external_host_endpoint_count": external_host,
        "malformed_known_field_count": malformed,
        "extra_safe_field_names": extra_keys,
        "endpoint_urls_retained": False,
        "endpoint_urls_followed": False,
    }


def _summarize_related_origins(document: Mapping[str, Any], probe_origin: str) -> Dict[str, Any]:
    values = document.get("origins")
    if not isinstance(values, list):
        values = []
        list_shape_valid = False
    else:
        values = values[:1000]
        list_shape_valid = True
    valid_origins = set()
    malformed = 0
    for value in values:
        valid, _host = _valid_https_url(value)
        if not valid:
            malformed += 1
            continue
        parsed = urlsplit(value)
        if parsed.path not in ("", "/") or parsed.query:
            malformed += 1
            continue
        valid_origins.add(urlunsplit(("https", parsed.netloc.lower(), "", "", "")))
    return {
        "origins_list_present": list_shape_valid,
        "declared_origin_count": len(values),
        "valid_unique_origin_count": len(valid_origins),
        "malformed_origin_count": malformed,
        "includes_probe_origin": probe_origin in valid_origins,
        "origin_values_retained": False,
    }


def _evidence(kind: str, summary: Dict[str, Any]) -> Evidence:
    raw = json.dumps({"kind": kind, "summary": summary}, sort_keys=True)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return Evidence(
        evidence_id="passkey-well-known:{}:{}".format(kind, digest),
        source_type="public_passkey_well_known_" + kind,
        level=EvidenceLevel.OBSERVED,
        observation=summary,
        artifact_hash=digest,
    )


def probe_passkey_well_known(
    target: str,
    *,
    fetcher: Callable[..., JsonFetchResult] = safe_fetch_json,
) -> ModuleResult:
    """Probe two explicit public metadata paths and return redacted claims."""
    try:
        origin = _origin_from_target(target)
    except SafeFetchError as exc:
        return ModuleResult(
            module_id=PASSKEY_WELL_KNOWN_MANIFEST.module_id,
            schema_version="passkey-well-known-1.0",
            scan_mode=ScanMode.PASSIVE,
            errors=("origin:" + exc.code,),
            limitations=PASSKEY_WELL_KNOWN_MANIFEST.limitations,
        )
    origin_host = urlsplit(origin).hostname or ""
    summaries: Dict[str, Dict[str, Any]] = {}
    errors: List[str] = []
    evidences: List[Evidence] = []
    specifications = (
        ("passkey_endpoints", "/.well-known/passkey-endpoints", 64 * 1024),
        ("related_origins", "/.well-known/webauthn", 128 * 1024),
    )
    for kind, path, max_bytes in specifications:
        try:
            fetched = fetcher(
                origin + path,
                max_bytes=max_bytes,
                timeout_seconds=4.0,
                max_redirects=2,
            )
            summary = (
                _summarize_endpoints(fetched.document, origin_host)
                if kind == "passkey_endpoints"
                else _summarize_related_origins(fetched.document, origin)
            )
            summary.update({
                "resource_observed": True,
                "redirect_count": fetched.redirect_count,
                "tls_version": fetched.tls_version,
                "certificate_verified": fetched.certificate_verified,
            })
            summaries[kind] = summary
            evidences.append(_evidence(kind, summary))
        except SafeFetchError as exc:
            errors.append("{}:{}".format(kind, exc.code))
            summaries[kind] = {"resource_observed": False}

    endpoint = summaries["passkey_endpoints"]
    related = summaries["related_origins"]
    endpoint_valid = bool(
        endpoint.get("resource_observed")
        and endpoint.get("known_fields_present_count")
        and not endpoint.get("malformed_known_field_count")
    )
    endpoint_weak = bool(
        endpoint.get("resource_observed")
        and (not endpoint.get("known_fields_present_count")
             or endpoint.get("malformed_known_field_count"))
    )
    related_valid = bool(
        related.get("resource_observed")
        and related.get("origins_list_present")
        and related.get("valid_unique_origin_count")
        and not related.get("malformed_origin_count")
    )
    related_weak = bool(
        related.get("resource_observed")
        and (not related.get("origins_list_present")
             or not related.get("valid_unique_origin_count")
             or related.get("malformed_origin_count"))
    )
    evidence_by_kind = {
        item.source_type.rsplit("_", 1)[-1]: item.evidence_id
        for item in evidences
    }
    observed_count = int(bool(endpoint.get("resource_observed"))) + int(
        bool(related.get("resource_observed")))
    claims = (
        Claim(
            metric_id="auth.passkey.well_known_endpoints",
            crypto_property="relying_party_passkey_endpoint_discovery",
            verdict=(Verdict.WEAK if endpoint_weak else
                     Verdict.PASS if endpoint_valid else Verdict.UNKNOWN),
            value=endpoint,
            evidence_ids=((evidence_by_kind.get("endpoints"),)
                          if evidence_by_kind.get("endpoints") else ()),
            paper_ref_ids=(PASSKEYS_USENIX_2026.reference_id,),
            standard_ref_ids=(PASSKEY_ENDPOINTS_W3C.reference_id,),
            limitations=(
                "PASS只表示公开JSON的已知字段是有效HTTPS URL，程序不跟进链接。",
            ),
        ),
        Claim(
            metric_id="auth.webauthn.related_origins",
            crypto_property="webauthn_related_origin_scope",
            verdict=(Verdict.WEAK if related_weak else
                     Verdict.PASS if related_valid else Verdict.UNKNOWN),
            value=related,
            evidence_ids=((evidence_by_kind.get("origins"),)
                          if evidence_by_kind.get("origins") else ()),
            paper_ref_ids=(PASSKEYS_USENIX_2026.reference_id,),
            standard_ref_ids=(WEBAUTHN_LEVEL_3.reference_id,),
            limitations=(
                "PASS只表示related-origins公开文档句法可解析，不表示其中每个域均可被安全信任。",
            ),
        ),
        Claim(
            metric_id="auth.passkey.well_known_coverage",
            crypto_property="public_passkey_metadata_coverage",
            verdict=Verdict.UNKNOWN,
            value={
                "observed_resource_count": observed_count,
                "expected_resource_count": 2,
                "coverage": round(observed_count / 2, 4),
                "coverage_formula": "C_wk_X=N_observed_well_known/2",
                "security_score": False,
            },
            evidence_ids=tuple(item.evidence_id for item in evidences),
            paper_ref_ids=(PASSKEYS_USENIX_2026.reference_id,),
            standard_ref_ids=(
                PASSKEY_ENDPOINTS_W3C.reference_id,
                WEBAUTHN_LEVEL_3.reference_id,
            ),
            limitations=("C_wk_X是元数据可见性覆盖率，不是安全分数。",),
        ),
    )
    return ModuleResult(
        module_id=PASSKEY_WELL_KNOWN_MANIFEST.module_id,
        schema_version="passkey-well-known-1.0",
        scan_mode=ScanMode.PASSIVE,
        claims=claims,
        evidence=tuple(evidences),
        errors=tuple(errors),
        limitations=PASSKEY_WELL_KNOWN_MANIFEST.limitations,
    )
