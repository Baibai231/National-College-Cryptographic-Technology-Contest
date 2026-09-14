"""Bounded public OIDC/OAuth metadata and JWKS evidence probe.

Only standard HTTPS metadata endpoints explicitly derived from observed
authorization origins (or an operator-supplied issuer) are requested.  Every
hop is DNS checked, pinned to a public address for the connection, TLS
certificate validated, size bounded, and manually redirected.  Raw metadata
and JWK material are never returned or persisted.
"""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import re
import socket
import ssl
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlsplit, urlunsplit

from application_security.jose_validation import JoseParseError, inspect_jwks
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
    FAPI_IEEE_SP_2019,
    JWK_RFC7517,
    JWT_BCP_RFC8725,
    NIST_SP_800_131A_R2,
    OAUTH_AS_METADATA_RFC8414,
    OIDC_DISCOVERY_1_0,
    WPSE_USENIX_2018,
)


OIDC_DISCOVERY_MANIFEST = ModuleManifest(
    module_id="b.oidc_discovery_jwks",
    name_zh="OIDC Discovery与JWKS公开信任链探针",
    research_question=(
        "公开认证入口所指向的OIDC/OAuth发行者是否通过标准元数据发布HTTPS端点，"
        "其issuer是否精确绑定，公开JWKS是否存在明显密钥卫生问题？"
    ),
    crypto_elements=(
        "oidc_issuer_binding",
        "tls_authenticated_metadata_retrieval",
        "jwks_public_signature_keys",
        "jws_algorithm_key_binding",
        "rsa_public_key_strength",
    ),
    paper_refs=(FAPI_IEEE_SP_2019, WPSE_USENIX_2018),
    standard_refs=(
        OIDC_DISCOVERY_1_0, OAUTH_AS_METADATA_RFC8414, JWK_RFC7517,
        JWT_BCP_RFC8725, NIST_SP_800_131A_R2,
    ),
    safe_modes=(ScanMode.PASSIVE,),
    limitations=(
        "只探测已观察授权端点的发行者origin或操作者明确提供的issuer，最多3个候选。",
        "只允许HTTPS 443；每个DNS结果必须为公网地址，连接固定到已校验IP并验证TLS证书。",
        "最多跟随2次同样受校验的公开HTTPS重定向；元数据限256KiB，JWKS限1MiB。",
        "不发送Cookie、Authorization、client_id或令牌，不读取私有端点，不保存完整元数据或JWK材料。",
        "公开JWKS快照不能证明服务端实际使用对应私钥、正确选key或正确验证每个令牌。",
        "当前只对RSA模数执行2048位门槛；EC/OKP曲线强度与证书链需后续模块验证。",
        "第三方身份提供商的公开配置只能归因于该提供商，不能当作被测网站自身实现。",
    ),
)


class SafeFetchError(RuntimeError):
    """A stable, non-sensitive public fetch failure code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class JsonFetchResult:
    requested_url: str
    final_url: str
    document: Mapping[str, Any]
    content_type: str
    redirect_count: int
    tls_version: str
    certificate_verified: bool = True


_SAFE_NAME = re.compile(r"^[A-Za-z0-9_+./:-]{1,100}$")
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_JSON_CONTENT_TYPES = {"application/json", "application/jwk-set+json"}


def _require_public_address(address: str) -> str:
    candidate = address.split("%", 1)[0]
    try:
        parsed = ipaddress.ip_address(candidate)
    except ValueError as exc:
        raise SafeFetchError("invalid_resolved_address") from exc
    if not parsed.is_global:
        raise SafeFetchError("non_public_address")
    return candidate


def validate_public_https_url(
    url: str,
    *,
    resolver: Callable[..., Sequence[Tuple[Any, ...]]] = socket.getaddrinfo,
) -> Tuple[str, Tuple[str, ...]]:
    """Validate one fetch URL and return normalized URL plus pinned IPs."""
    if not isinstance(url, str) or not url or len(url) > 4096:
        raise SafeFetchError("invalid_url")
    if "\\" in url or any(ord(char) < 32 or ord(char) == 127 for char in url):
        raise SafeFetchError("invalid_url")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise SafeFetchError("https_required")
    if parsed.username is not None or parsed.password is not None:
        raise SafeFetchError("userinfo_forbidden")
    if parsed.fragment:
        raise SafeFetchError("fragment_forbidden")
    try:
        port = parsed.port
    except ValueError as exc:
        raise SafeFetchError("invalid_port") from exc
    if port not in (None, 443):
        raise SafeFetchError("standard_https_port_required")
    try:
        host = parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except (UnicodeError, AttributeError) as exc:
        raise SafeFetchError("invalid_hostname") from exc
    if not host or host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise SafeFetchError("local_hostname_forbidden")
    literal = None
    try:
        literal = _require_public_address(host)
    except SafeFetchError as exc:
        if exc.code != "invalid_resolved_address":
            raise
    if literal:
        addresses = (literal,)
    else:
        try:
            answers = resolver(host, 443, type=socket.SOCK_STREAM)
        except (OSError, socket.gaierror) as exc:
            raise SafeFetchError("dns_resolution_failed") from exc
        address_set = {
            _require_public_address(answer[4][0]) for answer in answers
            if isinstance(answer, tuple) and len(answer) >= 5 and answer[4]
        }
        addresses = tuple(sorted(
            address_set,
            key=lambda value: (ipaddress.ip_address(value).version, value),
        ))
        if not addresses:
            raise SafeFetchError("dns_resolution_failed")
    display_host = "[{}]".format(host) if ":" in host else host
    path = parsed.path or "/"
    normalized = urlunsplit(("https", display_host, path, parsed.query, ""))
    return normalized, addresses


def _redacted_public_url(url: str) -> str:
    """Keep only public origin/path; query values never enter evidence."""
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        host = "[{}]".format(host) if ":" in host else host
        return urlunsplit((parsed.scheme, host, parsed.path or "/", "", ""))
    except Exception:
        return ""


def _loads_unique_json(raw: bytes) -> Mapping[str, Any]:
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise SafeFetchError("duplicate_json_member")
            result[key] = value
        return result

    def reject_constant(_value):
        raise SafeFetchError("non_finite_json_number")

    try:
        document = json.loads(
            raw.decode("utf-8"), object_pairs_hook=unique_pairs,
            parse_constant=reject_constant,
        )
    except SafeFetchError:
        raise
    except Exception as exc:
        raise SafeFetchError("invalid_json_document") from exc
    if not isinstance(document, dict):
        raise SafeFetchError("json_object_required")
    return document


def safe_fetch_json(
    url: str,
    *,
    max_bytes: int,
    timeout_seconds: float = 4.0,
    max_redirects: int = 2,
    resolver: Callable[..., Sequence[Tuple[Any, ...]]] = socket.getaddrinfo,
) -> JsonFetchResult:
    """Fetch bounded JSON over certificate-verified, DNS-pinned HTTPS."""
    if not isinstance(max_bytes, int) or not 1 <= max_bytes <= 2 * 1024 * 1024:
        raise ValueError("max_bytes outside safe bound")
    requested = url
    current = url
    tls_versions: List[str] = []
    for redirect_count in range(max_redirects + 1):
        normalized, addresses = validate_public_https_url(current, resolver=resolver)
        parsed = urlsplit(normalized)
        host = parsed.hostname or ""
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        connection = http.client.HTTPSConnection(
            host, 443, timeout=timeout_seconds, context=ssl.create_default_context())
        pinned_address = addresses[0]
        connection._create_connection = (  # type: ignore[attr-defined]
            lambda _address, timeout=None, source_address=None:
            socket.create_connection(
                (pinned_address, 443), timeout or timeout_seconds, source_address)
        )
        try:
            connection.request("GET", path, headers={
                "Accept": "application/json, application/jwk-set+json",
                "Accept-Encoding": "identity",
                "Cache-Control": "no-cache",
                "User-Agent": "CryptoScope-Research-Metadata-Probe/4",
            })
            response = connection.getresponse()
            if connection.sock is not None:
                version = connection.sock.version()
                if isinstance(version, str):
                    tls_versions.append(version[:20])
            status = response.status
            if status in _REDIRECT_STATUSES:
                location = response.getheader("Location")
                if not location:
                    raise SafeFetchError("redirect_without_location")
                if redirect_count >= max_redirects:
                    raise SafeFetchError("redirect_limit_exceeded")
                current = urljoin(normalized, location)
                continue
            if status != 200:
                raise SafeFetchError("http_status_{}".format(status))
            content_length = response.getheader("Content-Length")
            if content_length:
                try:
                    if int(content_length) > max_bytes:
                        raise SafeFetchError("response_too_large")
                except ValueError as exc:
                    raise SafeFetchError("invalid_content_length") from exc
            encoding = (response.getheader("Content-Encoding") or "identity").lower()
            if encoding not in {"", "identity"}:
                raise SafeFetchError("encoded_response_forbidden")
            content_type = (response.getheader("Content-Type") or "").split(";", 1)[0].strip().lower()
            if content_type not in _JSON_CONTENT_TYPES and not content_type.endswith("+json"):
                raise SafeFetchError("json_content_type_required")
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise SafeFetchError("response_too_large")
            document = _loads_unique_json(body)
            return JsonFetchResult(
                requested_url=_redacted_public_url(requested),
                final_url=_redacted_public_url(normalized),
                document=document,
                content_type=content_type,
                redirect_count=redirect_count,
                tls_version=tls_versions[-1] if tls_versions else "",
                certificate_verified=True,
            )
        except SafeFetchError:
            raise
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            raise SafeFetchError("network_or_tls_error") from exc
        finally:
            connection.close()
    raise SafeFetchError("redirect_limit_exceeded")


def _issuer_candidate(value: Any) -> Optional[str]:
    if isinstance(value, Mapping):
        value = value.get("issuer") or value.get("origin")
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.query
                or parsed.fragment or parsed.username is not None
                or parsed.password is not None or parsed.port not in (None, 443)):
            return None
        host = parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except (ValueError, UnicodeError, AttributeError):
        return None
    netloc = "[{}]".format(host) if ":" in host else host
    path = parsed.path.rstrip("/")
    return urlunsplit(("https", netloc, path, "", ""))


def _metadata_url(issuer: str, kind: str) -> str:
    parsed = urlsplit(issuer)
    if kind == "openid":
        return issuer.rstrip("/") + "/.well-known/openid-configuration"
    suffix = "/.well-known/oauth-authorization-server"
    return urlunsplit(("https", parsed.netloc, suffix + (parsed.path or ""), "", ""))


def _safe_string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return sorted({item for item in value[:100]
                   if isinstance(item, str) and _SAFE_NAME.fullmatch(item)})


def _https_shape(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        return bool(
            parsed.scheme == "https" and parsed.hostname
            and parsed.username is None and parsed.password is None
            and parsed.port in (None, 443) and not parsed.fragment
        )
    except ValueError:
        return False


def _provider_summary(
    issuer: str,
    role: str,
    fetch_json: Callable[..., JsonFetchResult],
) -> Dict[str, Any]:
    errors: List[str] = []
    metadata_result: Optional[JsonFetchResult] = None
    metadata_kind = ""
    for kind in ("openid", "oauth"):
        try:
            metadata_result = fetch_json(
                _metadata_url(issuer, kind), max_bytes=256 * 1024)
            metadata_kind = kind
            break
        except SafeFetchError as exc:
            errors.append(kind + "_metadata:" + exc.code)
            # The RFC 8414 location is a compatibility fallback for a server
            # that definitively does not expose the OIDC location.  Retrying
            # the same unreachable origin after DNS/TLS/timeout failures only
            # doubles latency and cannot add evidence.
            if not (kind == "openid" and exc.code in {
                    "http_status_400", "http_status_404", "http_status_405"}):
                break
    if metadata_result is None:
        return {
            "issuer": issuer,
            "role": role,
            "metadata_observed": False,
            "chain_predicate": None,
            "chain_coverage": 0.0,
            "errors": errors,
        }

    metadata = metadata_result.document
    returned_issuer = metadata.get("issuer")
    issuer_match = isinstance(returned_issuer, str) and returned_issuer == issuer
    jwks_uri = metadata.get("jwks_uri")
    jwks_https = _https_shape(jwks_uri)
    oidc_requires_jwks = metadata_kind == "openid"
    if not issuer_match:
        errors.append("issuer_mismatch")
    if oidc_requires_jwks and not jwks_uri:
        errors.append("openid_jwks_uri_missing")
    elif jwks_uri and not jwks_https:
        errors.append("jwks_uri_not_https")

    jwks_summary = None
    jwks_result = None
    if issuer_match and jwks_https:
        try:
            jwks_result = fetch_json(jwks_uri, max_bytes=1024 * 1024)
            jwks_summary = inspect_jwks(jwks_result.document)
        except SafeFetchError as exc:
            errors.append("jwks:" + exc.code)
        except JoseParseError:
            errors.append("jwks:invalid_jwks")

    jwks_requirement: Optional[bool]
    if jwks_uri:
        jwks_requirement = jwks_https
    elif oidc_requires_jwks:
        jwks_requirement = False
    else:
        jwks_requirement = None
    jwks_fetched: Optional[bool]
    if jwks_result is not None and jwks_summary is not None:
        jwks_fetched = True
    elif jwks_https:
        jwks_fetched = None
    elif jwks_requirement is False:
        jwks_fetched = False
    else:
        jwks_fetched = None
    checks: Dict[str, Optional[bool]] = {
        "tls_certificate": metadata_result.certificate_verified,
        "issuer_exact_match": issuer_match,
        "jwks_uri_https": jwks_requirement,
        "jwks_fetched": jwks_fetched,
    }
    values = tuple(checks.values())
    predicate = False if False in values else (
        True if all(value is True for value in values) else None)
    coverage = sum(value is not None for value in values) / len(values)
    metadata_algorithms = _safe_string_list(
        metadata.get("id_token_signing_alg_values_supported")
        or metadata.get("token_endpoint_auth_signing_alg_values_supported"))
    jwks_algorithms = (jwks_summary or {}).get("algorithms") or []
    if metadata_algorithms and jwks_algorithms:
        algorithm_overlap = sorted(set(metadata_algorithms) & set(jwks_algorithms))
        algorithm_binding: Optional[bool] = bool(algorithm_overlap)
    else:
        algorithm_overlap = []
        algorithm_binding = None
    return {
        "issuer": issuer,
        "role": role,
        "metadata_observed": True,
        "metadata_kind": metadata_kind,
        "metadata_url": metadata_result.final_url,
        "metadata_redirect_count": metadata_result.redirect_count,
        "metadata_tls_version": metadata_result.tls_version,
        "issuer_exact_match": issuer_match,
        "authorization_endpoint_https": _https_shape(
            metadata.get("authorization_endpoint")),
        "token_endpoint_https": _https_shape(metadata.get("token_endpoint"))
            if metadata.get("token_endpoint") else None,
        "jwks_uri_https": jwks_requirement,
        "jwks_uri": _redacted_public_url(jwks_uri) if jwks_https else "",
        "jwks_fetched": jwks_fetched,
        "jwks_redirect_count": jwks_result.redirect_count if jwks_result else 0,
        "jwks_tls_version": jwks_result.tls_version if jwks_result else "",
        "id_token_signing_algorithms": metadata_algorithms,
        "metadata_jwks_algorithm_overlap": algorithm_overlap,
        "metadata_jwks_algorithm_binding": algorithm_binding,
        "none_algorithm_advertised": "none" in metadata_algorithms,
        "pkce_methods": _safe_string_list(metadata.get("code_challenge_methods_supported")),
        "signed_metadata_present": isinstance(metadata.get("signed_metadata"), str),
        "jwks_summary": jwks_summary,
        "chain_checks": checks,
        "chain_predicate": predicate,
        "chain_coverage": round(coverage, 4),
        "errors": errors,
    }


def probe_oidc_discovery(
    target: str,
    candidates: Iterable[Any],
    *,
    fetch_json: Optional[Callable[..., JsonFetchResult]] = None,
) -> ModuleResult:
    """Probe up to three public issuer candidates and return redacted evidence."""
    fetch = fetch_json or safe_fetch_json
    normalized: List[Tuple[str, str]] = []
    seen = set()
    for candidate in candidates or ():
        issuer = _issuer_candidate(candidate)
        if not issuer or issuer in seen:
            continue
        seen.add(issuer)
        explicit_role = candidate.get("role") if isinstance(candidate, Mapping) else ""
        if explicit_role in {"site_origin", "external_provider", "operator_supplied"}:
            role = explicit_role
        else:
            same_origin = bool(candidate.get("same_origin")) \
                if isinstance(candidate, Mapping) else True
            role = "site_origin" if same_origin else "external_provider"
        normalized.append((issuer, role))
        if len(normalized) >= 3:
            break
    provider_items = []
    for issuer, role in normalized:
        try:
            provider_items.append(_provider_summary(issuer, role, fetch))
        except Exception as exc:
            # This detector is additive.  An unexpected metadata parser or
            # network-stack failure must never discard the site's primary
            # classification result.
            provider_items.append({
                "issuer": issuer,
                "role": role,
                "metadata_observed": False,
                "chain_predicate": None,
                "chain_coverage": 0.0,
                "errors": ["probe_internal_error:" + type(exc).__name__],
            })
    providers = tuple(provider_items)
    metadata_count = sum(bool(item.get("metadata_observed")) for item in providers)
    predicates = [item.get("chain_predicate") for item in providers
                  if item.get("metadata_observed")]
    if False in predicates:
        chain_verdict = Verdict.FAIL
    elif predicates and all(value is True for value in predicates):
        chain_verdict = Verdict.PASS
    else:
        chain_verdict = Verdict.UNKNOWN

    hygiene_issues = {
        "private_or_symmetric_keys": 0,
        "rsa_below_2048": 0,
        "duplicate_kids": 0,
        "malformed_keys": 0,
        "algorithm_key_type_mismatches": 0,
        "metadata_jwks_no_algorithm_overlap": 0,
        "none_algorithm_advertised": 0,
    }
    for provider in providers:
        summary = provider.get("jwks_summary") or {}
        hygiene_issues["private_or_symmetric_keys"] += int(
            summary.get("private_or_symmetric_key_count") or 0)
        hygiene_issues["rsa_below_2048"] += int(summary.get("rsa_below_2048_count") or 0)
        hygiene_issues["duplicate_kids"] += int(summary.get("duplicate_kid_count") or 0)
        hygiene_issues["malformed_keys"] += int(summary.get("malformed_key_count") or 0)
        hygiene_issues["algorithm_key_type_mismatches"] += int(
            summary.get("algorithm_key_type_mismatch_count") or 0)
        hygiene_issues["metadata_jwks_no_algorithm_overlap"] += int(
            provider.get("metadata_jwks_algorithm_binding") is False)
        hygiene_issues["none_algorithm_advertised"] += int(
            bool(provider.get("none_algorithm_advertised")))
    severe_hygiene = hygiene_issues["private_or_symmetric_keys"]
    other_hygiene = sum(hygiene_issues.values()) - severe_hygiene
    hygiene_verdict = Verdict.FAIL if severe_hygiene else (
        Verdict.WEAK if other_hygiene else Verdict.UNKNOWN)

    aggregate = {
        "candidate_count": len(normalized),
        "metadata_observed_count": metadata_count,
        "providers": list(providers),
        "chain_formula": "V_chain=V_TLS AND V_issuer AND V_jwks_https AND V_jwks_fetch",
        "hygiene_issues": hygiene_issues,
        "raw_metadata_retained": False,
        "raw_jwk_material_retained": False,
    }
    evidence: Tuple[Evidence, ...] = ()
    evidence_ids: Tuple[str, ...] = ()
    if providers:
        raw = json.dumps({"target": target, "aggregate": aggregate},
                         sort_keys=True, ensure_ascii=False, default=str)
        evidence_id = "oidc-discovery:" + hashlib.sha256(
            raw.encode("utf-8")).hexdigest()[:16]
        evidence = (Evidence(
            evidence_id=evidence_id,
            source_type="public_oidc_oauth_metadata_and_jwks",
            level=EvidenceLevel.OBSERVED,
            observation=aggregate,
            artifact_hash=evidence_id.split(":", 1)[1],
        ),)
        evidence_ids = (evidence_id,)

    claims = (
        Claim(
            metric_id="auth.oidc.discovery_metadata",
            crypto_property="standard_authorization_server_metadata",
            verdict=Verdict.PASS if metadata_count else Verdict.UNKNOWN,
            value={"observed": bool(metadata_count),
                   "candidate_count": len(normalized),
                   "metadata_observed_count": metadata_count},
            evidence_ids=evidence_ids if metadata_count else (),
            paper_ref_ids=(FAPI_IEEE_SP_2019.reference_id, WPSE_USENIX_2018.reference_id),
            standard_ref_ids=(OIDC_DISCOVERY_1_0.reference_id,
                              OAUTH_AS_METADATA_RFC8414.reference_id),
            limitations=("PASS只表示标准公开元数据可读取，不表示被测网站自身安全。",),
        ),
        Claim(
            metric_id="auth.oidc.issuer_jwks_chain",
            crypto_property="tls_issuer_and_jwks_binding",
            verdict=chain_verdict,
            value=aggregate,
            evidence_ids=evidence_ids,
            paper_ref_ids=(FAPI_IEEE_SP_2019.reference_id,),
            standard_ref_ids=(OIDC_DISCOVERY_1_0.reference_id,
                              OAUTH_AS_METADATA_RFC8414.reference_id,
                              JWK_RFC7517.reference_id),
            limitations=(
                "该谓词验证公开元数据链；没有实际令牌时不证明JWT签名与上下文验证。",
            ),
        ),
        Claim(
            metric_id="auth.oidc.jwks_hygiene",
            crypto_property="public_signing_key_hygiene",
            verdict=hygiene_verdict,
            value={"issues": hygiene_issues,
                   "clean_snapshot_is_security_pass": False},
            evidence_ids=evidence_ids if metadata_count else (),
            paper_ref_ids=(FAPI_IEEE_SP_2019.reference_id,),
            standard_ref_ids=(JWK_RFC7517.reference_id,
                              JWT_BCP_RFC8725.reference_id,
                              NIST_SP_800_131A_R2.reference_id),
            limitations=(
                "未发现当前覆盖范围内问题仍保持UNKNOWN，不能从一次公钥快照推出完整安全。",
            ),
        ),
    )
    return ModuleResult(
        module_id=OIDC_DISCOVERY_MANIFEST.module_id,
        schema_version="oidc-discovery-jwks-1.0",
        scan_mode=ScanMode.PASSIVE,
        claims=claims,
        evidence=evidence,
        limitations=OIDC_DISCOVERY_MANIFEST.limitations,
    )
