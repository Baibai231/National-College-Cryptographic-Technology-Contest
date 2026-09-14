"""Paper- and standards-backed passive JWT/JWS/JWKS validation.

The browser path accepts *sanitized metadata only*.  The optional offline
verifier accepts a compact JWT and public JWKS in memory, performs the RFC 7515
RSASSA-PKCS1-v1_5 verification operation, and returns only a redacted report.
Neither path persists token text, claim values, signatures, or JWK material.

This is a research measurement oracle, not a production authentication
library.  Production systems should use a maintained JOSE implementation.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import re
import time
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

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
    JWS_RFC7515,
    JWT_BCP_RFC8725,
    JWT_RFC7519,
    NIST_SP_800_131A_R2,
    WPSE_USENIX_2018,
)


JOSE_MANIFEST = ModuleManifest(
    module_id="b.jose_validation",
    name_zh="JWT/JWS/JWKS密码学验证",
    research_question=(
        "公开可观察的JOSE对象是否使用明确算法和完整签名，并在有授权上下文时"
        "满足发行者、受众、时效与nonce绑定？"
    ),
    crypto_elements=(
        "rsa_signature_verification",
        "jws_algorithm_binding",
        "jwks_key_selection",
        "jwt_issuer_audience_nonce_binding",
        "jwt_replay_resistance",
    ),
    paper_refs=(FAPI_IEEE_SP_2019, WPSE_USENIX_2018),
    standard_refs=(JWS_RFC7515, JWK_RFC7517, JWT_RFC7519, JWT_BCP_RFC8725,
                   NIST_SP_800_131A_R2),
    safe_modes=(ScanMode.PASSIVE, ScanMode.AUTHORIZED_ACCOUNT),
    limitations=(
        "访客现场模式只检查当前页面URL/表单属性中已经公开的JOSE对象，不读取Cookie或Web Storage。",
        "现场证据只含alg、typ、kid是否存在和claim名称，不含令牌、签名、claim值或JWK材料。",
        "没有公开JWKS、算法白名单和预期iss/aud/nonce时，不能判定JWT密码学验证通过。",
        "内置离线验签仅覆盖RFC 7515的RS256/RS384/RS512研究复核，不替代生产JOSE库。",
    ),
)


_RSA_HASHES = {
    "RS256": (hashlib.sha256, bytes.fromhex("3031300d060960864801650304020105000420")),
    "RS384": (hashlib.sha384, bytes.fromhex("3041300d060960864801650304020205000430")),
    "RS512": (hashlib.sha512, bytes.fromhex("3051300d060960864801650304020305000440")),
}
_BINDING_CLAIMS = ("iss", "sub", "aud", "exp", "nbf", "iat", "jti", "nonce")
_REMOTE_KEY_HEADERS = ("jku", "x5u")
_EMBEDDED_KEY_HEADERS = ("jwk", "x5c")


class JoseParseError(ValueError):
    """Raised when compact JOSE input is malformed or ambiguous."""


def _b64url_decode(value: str, *, maximum: int = 131072) -> bytes:
    if not isinstance(value, str) or len(value) > maximum * 2:
        raise JoseParseError("base64url segment is invalid or too large")
    if any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for char in value):
        raise JoseParseError("base64url segment contains invalid characters")
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:
        raise JoseParseError("invalid base64url encoding") from exc
    if len(decoded) > maximum:
        raise JoseParseError("decoded segment is too large")
    canonical = base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii")
    if not hmac.compare_digest(canonical, value):
        raise JoseParseError("non-canonical base64url encoding")
    return decoded


def _unique_json(raw: bytes) -> Dict[str, Any]:
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise JoseParseError("duplicate JSON member")
            result[key] = value
        return result

    try:
        def reject_constant(value):
            raise JoseParseError("non-finite JSON number: " + value)

        parsed = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique_pairs,
            parse_constant=reject_constant,
        )
    except JoseParseError:
        raise
    except Exception as exc:
        raise JoseParseError("JOSE JSON must be a UTF-8 object") from exc
    if not isinstance(parsed, dict):
        raise JoseParseError("JOSE JSON must be an object")
    return parsed


def _parse_compact(token: str) -> Tuple[Dict[str, Any], Dict[str, Any], Tuple[str, str, str]]:
    if not isinstance(token, str) or len(token) > 262144:
        raise JoseParseError("compact token is invalid or too large")
    parts = token.split(".")
    if len(parts) != 3 or not parts[0] or not parts[1]:
        raise JoseParseError("compact JWS must have three segments")
    header = _unique_json(_b64url_decode(parts[0]))
    payload = _unique_json(_b64url_decode(parts[1]))
    return header, payload, (parts[0], parts[1], parts[2])


def _profile_for_parameter(parameter: str) -> str:
    return {
        "id_token": "oidc_id_token",
        "response": "jarm_response",
        "request": "jar_request",
        "request_object": "jar_request",
        "client_assertion": "client_assertion",
        "assertion": "assertion",
    }.get(str(parameter or "").lower(), "unspecified_jwt")


def inspect_compact_jwt(
    token: str, *, source: str = "offline", parameter: str = ""
) -> Dict[str, Any]:
    """Return non-secret structural metadata from a compact JWS/JWT."""
    header, payload, parts = _parse_compact(token)
    alg = header.get("alg") if isinstance(header.get("alg"), str) else ""
    typ = header.get("typ") if isinstance(header.get("typ"), str) else ""
    crit = header.get("crit")
    critical_names = sorted(item for item in crit if isinstance(item, str)) \
        if isinstance(crit, list) else []
    return {
        "source": str(source or "")[:80],
        "parameter": str(parameter or "")[:40],
        "profile": _profile_for_parameter(parameter),
        "alg": alg[:40],
        "typ": typ[:80],
        "kid_present": isinstance(header.get("kid"), str) and bool(header.get("kid")),
        "critical_headers": critical_names[:20],
        "remote_key_headers": [name for name in _REMOTE_KEY_HEADERS if name in header],
        "embedded_key_headers": [name for name in _EMBEDDED_KEY_HEADERS if name in header],
        "claim_names": sorted(str(name)[:100] for name in payload)[:100],
        "binding_claims_present": [name for name in _BINDING_CLAIMS if name in payload],
        "signature_present": bool(parts[2]),
        "signature_bytes": len(_b64url_decode(parts[2])) if parts[2] else 0,
    }


def inspect_jwks(jwks: Mapping[str, Any]) -> Dict[str, Any]:
    """Summarize public keys without returning key IDs or key material."""
    keys = jwks.get("keys") if isinstance(jwks, Mapping) else None
    if not isinstance(keys, list):
        raise JoseParseError("JWKS must contain a keys array")
    key_ids = [key.get("kid") for key in keys if isinstance(key, Mapping)
               and isinstance(key.get("kid"), str)]
    duplicate_kids = len(key_ids) - len(set(key_ids))
    rsa_bits = []
    algorithms = set()
    key_types = set()
    signing_keys = 0
    malformed = 0
    private_or_symmetric = 0
    algorithm_key_type_mismatches = 0
    for key in keys:
        if not isinstance(key, Mapping):
            malformed += 1
            continue
        kty = key.get("kty")
        alg = key.get("alg")
        if isinstance(kty, str):
            key_types.add(kty)
        if isinstance(alg, str):
            algorithms.add(alg)
            expected_kty = None
            if alg.startswith(("RS", "PS")):
                expected_kty = "RSA"
            elif alg.startswith("ES"):
                expected_kty = "EC"
            elif alg == "EdDSA":
                expected_kty = "OKP"
            elif alg.startswith("HS"):
                expected_kty = "oct"
            if expected_kty is not None and kty != expected_kty:
                algorithm_key_type_mismatches += 1
        private_names = {"d", "p", "q", "dp", "dq", "qi", "oth"}
        if kty == "oct" or any(name in key for name in private_names):
            private_or_symmetric += 1
        if key.get("use") in (None, "sig"):
            signing_keys += 1
        if kty == "RSA":
            try:
                modulus = int.from_bytes(_b64url_decode(str(key.get("n") or "")), "big")
                rsa_bits.append(modulus.bit_length())
            except JoseParseError:
                malformed += 1
    return {
        "key_count": len(keys),
        "signing_key_count": signing_keys,
        "key_types": sorted(key_types),
        "algorithms": sorted(algorithms),
        "rsa_modulus_bits": sorted(rsa_bits),
        "rsa_below_2048_count": sum(bits < 2048 for bits in rsa_bits),
        "duplicate_kid_count": duplicate_kids,
        "malformed_key_count": malformed,
        "private_or_symmetric_key_count": private_or_symmetric,
        "algorithm_key_type_mismatch_count": algorithm_key_type_mismatches,
    }


def _select_rsa_key(header: Mapping[str, Any], jwks: Mapping[str, Any]) -> Tuple[Optional[Mapping[str, Any]], str]:
    keys = jwks.get("keys") if isinstance(jwks, Mapping) else None
    if not isinstance(keys, list):
        return None, "jwks_missing_keys"
    alg = header.get("alg")
    kid = header.get("kid")
    compatible = []
    for key in keys:
        if not isinstance(key, Mapping) or key.get("kty") != "RSA":
            continue
        if key.get("use") not in (None, "sig"):
            continue
        if key.get("alg") not in (None, alg):
            continue
        if isinstance(kid, str) and key.get("kid") != kid:
            continue
        compatible.append(key)
    if len(compatible) == 1:
        return compatible[0], "unique_compatible_key"
    if not compatible:
        return None, "no_compatible_key"
    return None, "ambiguous_key_selection"


def _verify_rsassa_pkcs1_v1_5(
    signing_input: bytes, signature: bytes, jwk: Mapping[str, Any], alg: str
) -> bool:
    """Execute RFC 7515 Appendix A.2's RSASSA-PKCS1-v1_5 verification."""
    if alg not in _RSA_HASHES:
        raise ValueError("unsupported RSA JWS algorithm")
    try:
        n_bytes = _b64url_decode(str(jwk.get("n") or ""))
        e_bytes = _b64url_decode(str(jwk.get("e") or ""))
    except JoseParseError:
        return False
    n = int.from_bytes(n_bytes, "big")
    e = int.from_bytes(e_bytes, "big")
    if n <= 0 or e <= 1 or not signature:
        return False
    width = math.ceil(n.bit_length() / 8)
    if len(signature) != width:
        return False
    signature_integer = int.from_bytes(signature, "big")
    if signature_integer >= n:
        return False
    recovered = pow(signature_integer, e, n).to_bytes(width, "big")
    digest_fn, digest_info_prefix = _RSA_HASHES[alg]
    digest_info = digest_info_prefix + digest_fn(signing_input).digest()
    padding_length = width - len(digest_info) - 3
    if padding_length < 8:
        return False
    expected = b"\x00\x01" + b"\xff" * padding_length + b"\x00" + digest_info
    return hmac.compare_digest(recovered, expected)


def _audience_matches(value: Any, expected: str) -> bool:
    if isinstance(value, str):
        return _constant_string_equal(value, expected)
    if isinstance(value, list):
        return any(isinstance(item, str) and _constant_string_equal(item, expected)
                   for item in value)
    return False


def _constant_string_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def verify_compact_jwt(
    token: str,
    *,
    jwks: Optional[Mapping[str, Any]] = None,
    allowed_algorithms: Sequence[str] = (),
    expected_issuer: Optional[str] = None,
    expected_audience: Optional[str] = None,
    expected_nonce: Optional[str] = None,
    expected_typ: Optional[str] = None,
    now: Optional[float] = None,
    leeway_seconds: float = 0,
    source: str = "offline",
    parameter: str = "",
) -> Dict[str, Any]:
    r"""Verify a compact JWT while returning only redacted evidence.

    The formal acceptance predicate follows the token-binding conditions used
    by the FAPI analysis and the RFC 8725 validation rules:

    .. math::

       V_P=\bigwedge_{j\in R(P)}V_j

    ``R(P)`` is selected from the token profile and supplied expectations.
    Missing required context is represented by ``None`` and cannot produce PASS.
    """
    header, payload, parts = _parse_compact(token)
    metadata = inspect_compact_jwt(token, source=source, parameter=parameter)
    alg = metadata["alg"]
    allowed = tuple(dict.fromkeys(str(item) for item in allowed_algorithms))
    checks: Dict[str, Optional[bool]] = {
        "signature": None,
        "algorithm": alg in allowed if allowed else None,
        "issuer": None,
        "audience": None,
        "time": None,
        "nonce": None,
        "type": None,
    }
    reasons = []
    if alg == "none":
        checks["signature"] = False
        reasons.append("unsecured_alg_none")
    elif alg in _RSA_HASHES and jwks is not None:
        key, key_reason = _select_rsa_key(header, jwks)
        reasons.append(key_reason)
        if key is not None:
            signature = _b64url_decode(parts[2]) if parts[2] else b""
            checks["signature"] = _verify_rsassa_pkcs1_v1_5(
                (parts[0] + "." + parts[1]).encode("ascii"), signature, key, alg)
            try:
                rsa_bits = int.from_bytes(
                    _b64url_decode(str(key.get("n") or "")), "big").bit_length()
            except JoseParseError:
                rsa_bits = 0
            if rsa_bits < 2048:
                checks["algorithm"] = False
                reasons.append("rsa_modulus_below_2048")
    elif jwks is not None:
        reasons.append("algorithm_not_supported_by_research_verifier")
    else:
        reasons.append("jwks_not_supplied")

    if expected_issuer is not None:
        checks["issuer"] = isinstance(payload.get("iss"), str) and _constant_string_equal(
            payload["iss"], expected_issuer)
    if expected_audience is not None:
        checks["audience"] = _audience_matches(payload.get("aud"), expected_audience)
    if expected_nonce is not None:
        checks["nonce"] = isinstance(payload.get("nonce"), str) and _constant_string_equal(
            payload["nonce"], expected_nonce)
    if expected_typ is not None:
        checks["type"] = isinstance(header.get("typ"), str) and _constant_string_equal(
            header["typ"].lower(), expected_typ.lower())

    timestamp = float(time.time() if now is None else now)
    exp = payload.get("exp")
    nbf = payload.get("nbf")
    issued_at = payload.get("iat")
    if isinstance(exp, (int, float)) and not isinstance(exp, bool):
        time_valid = timestamp <= float(exp) + float(leeway_seconds)
        if isinstance(nbf, (int, float)) and not isinstance(nbf, bool):
            time_valid = time_valid and timestamp + float(leeway_seconds) >= float(nbf)
        if isinstance(issued_at, (int, float)) and not isinstance(issued_at, bool):
            time_valid = time_valid and timestamp + float(leeway_seconds) >= float(issued_at)
        checks["time"] = time_valid

    required = {"signature", "algorithm"}
    profile = metadata["profile"]
    if profile in {"oidc_id_token", "jarm_response", "jar_request",
                   "client_assertion"}:
        required.update(("issuer", "audience", "time"))
    if "iss" in payload or expected_issuer is not None:
        required.add("issuer")
    if "aud" in payload or expected_audience is not None:
        required.add("audience")
    if any(name in payload for name in ("exp", "nbf", "iat")):
        required.add("time")
    if "nonce" in payload or expected_nonce is not None:
        required.add("nonce")
    if header.get("typ") is not None or expected_typ is not None:
        required.add("type")
    required_order = tuple(name for name in checks if name in required)
    values = tuple(checks[name] for name in required_order)
    predicate = False if False in values else (True if all(value is True for value in values) else None)
    coverage = sum(value is not None for value in values) / len(values)
    return {
        "metadata": metadata,
        "checks": checks,
        "verification_predicate": predicate,
        "verification_coverage": coverage,
        "required_checks": list(required_order),
        "formula": "V_P=AND(j in R(P)) V_j",
        "reasons": reasons,
        "jwks": inspect_jwks(jwks) if jwks is not None else None,
    }


def _sanitize_observation(item: Mapping[str, Any]) -> Dict[str, Any]:
    if not any(key in item for key in (
        "metadata", "alg", "profile", "parameter", "claim_names",
        "verification_predicate", "parse_error",
    )):
        return {}
    allowed = {
        "source", "parameter", "profile", "alg", "typ", "kid_present",
        "critical_headers", "remote_key_headers", "embedded_key_headers",
        "claim_names", "binding_claims_present", "signature_present",
        "signature_bytes", "checks", "verification_predicate",
        "verification_coverage", "formula", "reasons", "jwks", "parse_error",
        "required_checks",
    }
    clean = {key: item[key] for key in allowed if key in item}
    if "metadata" in item and isinstance(item["metadata"], Mapping):
        clean.update(_sanitize_observation(item["metadata"]))
    safe_identifier = re.compile(r"^[A-Za-z0-9_+./:-]{1,100}$")
    for key in ("alg", "typ", "profile"):
        value = clean.get(key)
        clean[key] = value if isinstance(value, str) and safe_identifier.fullmatch(value) else ""
    clean["source"] = clean.get("source") if clean.get("source") in {
        "offline", "current_url", "current_fragment", "dom_url"
    } else "other"
    clean["parameter"] = clean.get("parameter") if clean.get("parameter") in {
        "request", "request_object", "response", "id_token", "assertion",
        "client_assertion", ""
    } else "other"
    clean["kid_present"] = clean.get("kid_present") is True
    if "signature_present" in clean:
        clean["signature_present"] = clean.get("signature_present") is True
    if "signature_bytes" in clean:
        value = clean.get("signature_bytes")
        clean["signature_bytes"] = min(value, 1048576) \
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
    if "verification_coverage" in clean:
        value = clean.get("verification_coverage")
        clean["verification_coverage"] = value \
            if isinstance(value, (int, float)) and math.isfinite(value) and 0 <= value <= 1 else None
    for key in ("critical_headers", "remote_key_headers", "embedded_key_headers",
                "claim_names", "binding_claims_present", "reasons", "required_checks"):
        values = clean.get(key)
        if isinstance(values, list):
            clean[key] = [value for value in values[:100]
                          if isinstance(value, str) and safe_identifier.fullmatch(value)]
    checks = clean.get("checks")
    if isinstance(checks, Mapping):
        clean["checks"] = {
            name: checks.get(name)
            if isinstance(checks.get(name), bool) or checks.get(name) is None else None
            for name in ("signature", "algorithm", "issuer", "audience",
                         "time", "nonce", "type")
        }
    jwks = clean.get("jwks")
    if isinstance(jwks, Mapping):
        clean["jwks"] = {
            name: jwks.get(name)
            for name in (
                "key_count", "signing_key_count", "key_types", "algorithms",
                "rsa_modulus_bits", "rsa_below_2048_count", "duplicate_kid_count",
                "malformed_key_count", "private_or_symmetric_key_count",
                "algorithm_key_type_mismatch_count",
            )
        }
        for name in ("key_types", "algorithms"):
            values = clean["jwks"].get(name)
            clean["jwks"][name] = [value for value in (values or [])[:100]
                                        if isinstance(value, str)
                                        and safe_identifier.fullmatch(value)] \
                if isinstance(values, list) else []
    elif "jwks" in clean:
        clean["jwks"] = None
    clean["parse_error"] = "malformed_or_unsupported_compact_jose" \
        if clean.get("parse_error") else ""
    clean["formula"] = "V_P=AND(j in R(P)) V_j" \
        if "formula" in clean else clean.get("formula")
    return clean


def analyze_jose_metadata(
    target: str, observations: Sequence[Mapping[str, Any]]
) -> ModuleResult:
    """Turn public/sanitized JOSE observations into evidence-bounded claims."""
    sanitized = [_sanitize_observation(item) for item in observations or ()
                 if isinstance(item, Mapping)]
    sanitized = [item for item in sanitized if item]
    parse_errors = sum(bool(item.get("parse_error")) for item in sanitized)
    unsecured = sum(bool(item.get("alg") == "none" or
                         (item.get("alg") and
                          item.get("signature_present") is False))
                    for item in sanitized)
    remote_keys = sum(bool(item.get("remote_key_headers")) for item in sanitized)
    verified = sum(item.get("verification_predicate") is True for item in sanitized)
    failed = sum(item.get("verification_predicate") is False for item in sanitized)
    algorithms = sorted({str(item.get("alg")) for item in sanitized if item.get("alg")})
    aggregate = {
        "formula": "V_P=AND(j in R(P)) V_j",
        "observed_total": len(sanitized),
        "algorithms": algorithms,
        "parse_error_total": parse_errors,
        "unsecured_total": unsecured,
        "remote_key_header_total": remote_keys,
        "fully_verified_total": verified,
        "failed_verification_total": failed,
        "observations": sanitized,
        "token_values_retained": False,
    }
    evidence_id = "jose:" + hashlib.sha256(json.dumps(
        {"target": target, "aggregate": aggregate}, sort_keys=True,
        ensure_ascii=False, default=str).encode("utf-8")).hexdigest()[:16]
    has_evidence = bool(sanitized)
    evidence = Evidence(
        evidence_id=evidence_id,
        source_type="public_jose_metadata_or_offline_verification",
        level=EvidenceLevel.OBSERVED,
        observation=aggregate,
        artifact_hash=evidence_id.split(":", 1)[1],
    )
    if failed:
        verdict = Verdict.FAIL
    elif unsecured or parse_errors:
        verdict = Verdict.WEAK
    elif sanitized and verified == len(sanitized):
        verdict = Verdict.PASS
    else:
        verdict = Verdict.UNKNOWN
    claims = (
        Claim(
            metric_id="auth.jose.validation_predicate",
            crypto_property="jwt_jws_signature_and_context_binding",
            verdict=verdict,
            value=aggregate,
            evidence_ids=(evidence_id,) if has_evidence else (),
            paper_ref_ids=(FAPI_IEEE_SP_2019.reference_id, WPSE_USENIX_2018.reference_id),
            standard_ref_ids=(JWS_RFC7515.reference_id, JWK_RFC7517.reference_id,
                              JWT_RFC7519.reference_id, JWT_BCP_RFC8725.reference_id,
                              NIST_SP_800_131A_R2.reference_id),
            limitations=(
                "只有令牌用途R(P)要求的检查全部有上下文并验证成功才可pass。",
                "jku/x5u只作为远程密钥风险信号；未验证服务端是否白名单化时不直接判错。",
            ),
        ),
    )
    return ModuleResult(
        module_id=JOSE_MANIFEST.module_id,
        schema_version="jose-validation-1.0",
        scan_mode=ScanMode.PASSIVE,
        claims=claims,
        evidence=(evidence,) if has_evidence else (),
        limitations=JOSE_MANIFEST.limitations,
    )
