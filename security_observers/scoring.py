"""Explainable evidence coverage and security-posture scoring.

This is a measurement summary, not a vulnerability verdict.  Unknown controls
never receive zero points: they are excluded from the score denominator and are
reported through coverage instead.  A letter grade is withheld until weighted
evidence coverage reaches 70 percent.
"""

from __future__ import annotations


DIMENSION_WEIGHTS = {
    "password_policy": 30,
    "authentication": 20,
    "session_cookies": 15,
    "transport_security": 20,
    "http_security_headers": 15,
}

_HIGH_RISK = {
    "plaintext_final_page_observed",
    "https_to_http_downgrade_observed",
    "certificate_expired",
    "certificate_name_mismatch",
    "unsigned_algorithm_observed",
}
_MEDIUM_RISK = {
    "legacy_tls_version_observed",
    "browser_reported_insecure_transport",
    "session_like_cookie_without_secure",
    "session_like_cookie_without_http_only",
    "csp_allows_unsafe_eval",
    "observed_minimum_length_below_8",
}


def _bounded_number(value, minimum=0, maximum=100):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(minimum, min(maximum, float(value)))


def _dimension(checks, findings=None, positives=None, recommendations=None,
               coverage_multiplier=1.0):
    checks = list(checks)
    known = [item for item in checks if item.get("score") is not None]
    total = len(checks)
    raw_coverage = (100.0 * len(known) / total) if total else 0.0
    coverage = round(raw_coverage * max(0.0, min(1.0, coverage_multiplier)))
    scores = [_bounded_number(item.get("score")) for item in known]
    scores = [score for score in scores if score is not None]
    score = round(sum(scores) / len(scores)) if scores else None
    if not known:
        status = "unknown"
        posture = "unknown"
    else:
        status = "assessed" if coverage == 100 else "partial"
        posture = "strong" if score >= 85 else ("moderate" if score >= 65 else "weak")
    return {
        "status": status,
        "score": score,
        "coverage_percent": coverage,
        "posture": posture,
        "checks_evaluated": len(known),
        "checks_total": total,
        "checks": checks,
        "positive_evidence": list(dict.fromkeys(positives or [])),
        "findings": list(dict.fromkeys(findings or [])),
        "recommendations": list(dict.fromkeys(recommendations or [])),
    }


def _password_dimension(policy, measured):
    checks = [
        {"id": "minimum_length", "score": None, "observed": None},
        {"id": "maximum_length", "score": None, "observed": None},
        {"id": "breached_password_blocking", "score": None, "observed": None},
    ]
    findings, positives, recommendations = [], [], []
    if not measured or not isinstance(policy, dict):
        return _dimension(checks)

    length = policy.get("length")
    if isinstance(length, (list, tuple)) and length:
        minimum = length[0]
        if isinstance(minimum, int) and not isinstance(minimum, bool) and minimum > 0:
            checks[0]["observed"] = minimum
            checks[0]["score"] = 100 if minimum >= 15 else (
                90 if minimum >= 12 else (70 if minimum >= 8 else 25))
            if minimum >= 12:
                positives.append("minimum_length_at_least_12")
            elif minimum < 8:
                findings.append("observed_minimum_length_below_8")
                recommendations.append("review_minimum_password_length")
        maximum = length[1] if len(length) > 1 else None
        if isinstance(maximum, int) and not isinstance(maximum, bool) and maximum > 0:
            checks[1]["observed"] = maximum
            checks[1]["score"] = 100 if maximum >= 64 else (
                90 if maximum >= 32 else (70 if maximum >= 20 else (
                    50 if maximum >= 16 else 25)))
            if maximum >= 64:
                positives.append("maximum_length_at_least_64")
            elif maximum < 16:
                findings.append("observed_maximum_length_below_16")
                recommendations.append("allow_longer_passwords")

    permissive = policy.get("permissive") or {}
    breached = permissive.get("breached_password") or {}
    if isinstance(breached, dict) and isinstance(breached.get("p_br"), bool):
        blocked = breached["p_br"]
        checks[2]["observed"] = blocked
        checks[2]["score"] = 100 if blocked else 30
        if blocked:
            positives.append("breached_password_blocking_observed")
        else:
            findings.append("breached_password_blocking_not_observed_in_probe")
            recommendations.append("consider_breached_password_screening")

    limited = bool(policy.get("_inconclusive") or policy.get("_browser_dead"))
    if limited:
        findings.append("password_policy_measurement_partial")
    return _dimension(
        checks, findings, positives, recommendations,
        coverage_multiplier=0.75 if limited else 1.0)


def _authentication_dimension(analyzers):
    checks = [
        {"id": "oauth_state", "score": None, "observed": None},
        {"id": "oauth_pkce_for_code_flow", "score": None, "observed": None},
        {"id": "webauthn_or_passkey_available", "score": None, "observed": None},
    ]
    findings, positives, recommendations = [], [], []
    oauth = analyzers.get("oauth_oidc") or {}
    if oauth.get("status") == "observed":
        state = bool((oauth.get("state") or {}).get("non_empty_observed"))
        checks[0]["observed"] = state
        checks[0]["score"] = 100 if state else 40
        if state:
            positives.append("oauth_state_observed")
        else:
            findings.append("oauth_state_not_observed_in_visible_metadata")
            recommendations.append("verify_oauth_state_generation_manually")

        response_types = set(oauth.get("response_types") or [])
        if "code" in response_types:
            pkce = oauth.get("pkce") or {}
            challenge = bool(pkce.get("code_challenge_observed"))
            methods = {str(item).upper() for item in pkce.get("methods") or []}
            checks[1]["observed"] = "S256" if "S256" in methods else challenge
            checks[1]["score"] = 100 if "S256" in methods else (60 if challenge else 40)
            if "S256" in methods:
                positives.append("oauth_pkce_s256_observed")
            elif not challenge:
                findings.append("oauth_pkce_not_observed_in_visible_metadata")
                recommendations.append("verify_pkce_for_oauth_code_flow_manually")

    webauthn = analyzers.get("webauthn") or {}
    if webauthn.get("site_capability_observed"):
        checks[2]["observed"] = True
        checks[2]["score"] = 100
        positives.append("webauthn_or_passkey_capability_observed")

    mfa = analyzers.get("mfa") or {}
    if (mfa.get("status") == "observed"
            and mfa.get("mfa_enforcement") == "not_determined"):
        recommendations.append("mfa_enforcement_requires_authenticated_review")
    return _dimension(checks, findings, positives, recommendations)


def _session_dimension(analyzers):
    checks = [
        {"id": "session_cookie_secure", "score": None, "observed": None},
        {"id": "session_cookie_http_only", "score": None, "observed": None},
        {"id": "session_cookie_same_site", "score": None, "observed": None},
    ]
    session = analyzers.get("session_cookies") or {}
    likely = session.get("session_like_cookies") or {}
    count = likely.get("count")
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        return _dimension(
            checks,
            recommendations=["authenticated_session_cookie_review_required"])

    secure = max(0, min(count, int(likely.get("secure_count") or 0)))
    http_only = max(0, min(count, int(likely.get("http_only_count") or 0)))
    checks[0]["observed"] = {"secure": secure, "total": count}
    checks[0]["score"] = round(100 * secure / count)
    checks[1]["observed"] = {"http_only": http_only, "total": count}
    checks[1]["score"] = round(100 * http_only / count)

    same_site = likely.get("same_site") or {}
    specified = sum(int(same_site.get(name) or 0) for name in ("strict", "lax", "none"))
    if specified:
        protected = int(same_site.get("strict") or 0) + int(same_site.get("lax") or 0)
        checks[2]["observed"] = {
            "strict_or_lax": protected, "specified": specified,
        }
        checks[2]["score"] = round(100 * protected / specified)

    findings = list(session.get("findings") or [])
    recommendations = ["verify_authenticated_session_cookie_attributes"]
    if "session_like_cookie_without_secure" in findings:
        recommendations.append("set_secure_on_session_cookies")
    if "session_like_cookie_without_http_only" in findings:
        recommendations.append("set_http_only_on_session_cookies")
    positives = []
    if secure == count:
        positives.append("all_observed_session_like_cookies_secure")
    if http_only == count:
        positives.append("all_observed_session_like_cookies_http_only")
    return _dimension(checks, findings, positives, recommendations)


def _transport_dimension(analyzers):
    checks = [
        {"id": "https_final_page", "score": None, "observed": None},
        {"id": "modern_tls", "score": None, "observed": None},
        {"id": "certificate_validity", "score": None, "observed": None},
        {"id": "certificate_name_match", "score": None, "observed": None},
        {"id": "browser_transport_state", "score": None, "observed": None},
    ]
    transport = analyzers.get("transport_security") or {}
    if transport.get("status") != "observed":
        return _dimension(checks)

    scheme = transport.get("final_page_scheme")
    if scheme in {"http", "https"}:
        checks[0]["observed"] = scheme
        checks[0]["score"] = 100 if scheme == "https" else 0

    tls = transport.get("tls") or {}
    version = str(tls.get("version") or "").upper().replace("TLSV", "TLS ")
    if tls.get("metadata_observed") and version not in {"", "UNKNOWN"}:
        checks[1]["observed"] = version[:64]
        checks[1]["score"] = 100 if "1.3" in version else (
            85 if "1.2" in version else 20)
    expired = tls.get("certificate_expired")
    if isinstance(expired, bool):
        checks[2]["observed"] = not expired
        checks[2]["score"] = 0 if expired else (
            65 if tls.get("certificate_expires_within_30_days") else 100)
    name_match = tls.get("certificate_name_matches_host")
    if isinstance(name_match, bool):
        checks[3]["observed"] = name_match
        checks[3]["score"] = 100 if name_match else 0
    state = transport.get("browser_security_state")
    if state in {"secure", "neutral", "insecure"}:
        checks[4]["observed"] = state
        checks[4]["score"] = 100 if state == "secure" else (
            50 if state == "neutral" else 0)

    findings = list(transport.get("findings") or [])
    recommendations = []
    if "plaintext_final_page_observed" in findings:
        recommendations.append("serve_authentication_pages_over_https")
    if "legacy_tls_version_observed" in findings:
        recommendations.append("disable_legacy_tls_versions")
    if "certificate_expired" in findings or "certificate_expires_within_30_days" in findings:
        recommendations.append("renew_tls_certificate")
    if "certificate_name_mismatch" in findings:
        recommendations.append("fix_certificate_name_coverage")
    positives = []
    if scheme == "https":
        positives.append("https_final_page_observed")
    if checks[1]["score"] == 100:
        positives.append("tls_1_3_observed")
    return _dimension(checks, findings, positives, recommendations)


def _headers_dimension(analyzers):
    checks = [
        {"id": "strict_transport_security", "score": None, "observed": None},
        {"id": "content_security_policy", "score": None, "observed": None},
        {"id": "x_content_type_options", "score": None, "observed": None},
        {"id": "anti_framing_policy", "score": None, "observed": None},
        {"id": "referrer_policy", "score": None, "observed": None},
    ]
    headers = analyzers.get("http_security_headers") or {}
    if headers.get("status") != "observed":
        return _dimension(checks)

    hsts = headers.get("strict_transport_security") or {}
    hsts_present = bool(hsts.get("present"))
    max_age = hsts.get("max_age_seconds")
    transport = analyzers.get("transport_security") or {}
    if transport.get("https_page_observed"):
        checks[0]["observed"] = hsts_present
        checks[0]["score"] = (100 if isinstance(max_age, int) and max_age >= 15552000
                               else (70 if hsts_present else 0))

    csp = headers.get("content_security_policy") or {}
    csp_present = bool(csp.get("enforced_present"))
    csp_score = 0
    if csp_present:
        csp_score = 100
        if csp.get("unsafe_inline_observed"):
            csp_score -= 20
        if csp.get("unsafe_eval_observed"):
            csp_score -= 30
    checks[1]["observed"] = csp_present
    checks[1]["score"] = csp_score

    nosniff = bool(headers.get("x_content_type_options_nosniff"))
    checks[2]["observed"] = nosniff
    checks[2]["score"] = 100 if nosniff else 0

    framing = headers.get("anti_framing") or {}
    anti_framing = bool(framing.get("csp_frame_ancestors")) or (
        framing.get("x_frame_options") in {"DENY", "SAMEORIGIN"})
    checks[3]["observed"] = anti_framing
    checks[3]["score"] = 100 if anti_framing else 0

    referrer = headers.get("referrer_policy")
    referrer_present = bool(referrer and referrer != "not_observed")
    checks[4]["observed"] = referrer if referrer_present else False
    checks[4]["score"] = (20 if referrer == "unsafe-url"
                           else (100 if referrer_present else 0))

    findings = list(headers.get("findings") or [])
    recommendations = []
    mapping = {
        "hsts_not_observed": "consider_hsts_for_https_authentication_pages",
        "content_security_policy_not_observed": "deploy_content_security_policy",
        "csp_allows_unsafe_inline": "reduce_csp_unsafe_inline",
        "csp_allows_unsafe_eval": "remove_csp_unsafe_eval",
        "anti_framing_policy_not_observed": "deploy_anti_framing_policy",
        "nosniff_not_observed": "set_x_content_type_options_nosniff",
        "referrer_policy_not_observed": "set_referrer_policy",
    }
    for finding in findings:
        if finding in mapping:
            recommendations.append(mapping[finding])
    positives = []
    if hsts_present:
        positives.append("hsts_observed")
    if csp_present:
        positives.append("enforced_csp_observed")
    if anti_framing:
        positives.append("anti_framing_policy_observed")
    return _dimension(checks, findings, positives, recommendations)


def _grade(score):
    if score is None:
        return None
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "E"


def build_security_assessment(analyzers, password_policy=None,
                              password_policy_measured=False) -> dict:
    """Build a transparent assessment over only the evidence that exists."""
    analyzers = analyzers if isinstance(analyzers, dict) else {}
    dimensions = {
        "password_policy": _password_dimension(
            password_policy, bool(password_policy_measured)),
        "authentication": _authentication_dimension(analyzers),
        "session_cookies": _session_dimension(analyzers),
        "transport_security": _transport_dimension(analyzers),
        "http_security_headers": _headers_dimension(analyzers),
    }

    evidence_weight = 0.0
    weighted_score = 0.0
    for name, weight in DIMENSION_WEIGHTS.items():
        dimension = dimensions[name]
        usable_weight = weight * dimension["coverage_percent"] / 100.0
        if dimension["score"] is not None:
            evidence_weight += usable_weight
            weighted_score += dimension["score"] * usable_weight
    coverage = round(evidence_weight)
    score = round(weighted_score / evidence_weight) if evidence_weight else None

    all_findings = list(dict.fromkeys(
        finding
        for dimension in dimensions.values()
        for finding in dimension["findings"]
    ))
    # JWT findings are relevant even though JWT does not receive a separate
    # numerical dimension: the token was only observed pre-authentication.
    all_findings.extend(
        finding for finding in (analyzers.get("jwt") or {}).get("findings", [])
        if finding not in all_findings)
    if any(item in _HIGH_RISK for item in all_findings):
        risk = "high"
    elif any(item in _MEDIUM_RISK for item in all_findings):
        risk = "medium"
    elif all_findings:
        risk = "review"
    elif evidence_weight:
        risk = "none_observed"
    else:
        risk = "unknown"

    sufficient = coverage >= 70
    return {
        "schema_version": "1.0",
        "model": "evidence_weighted_dimensions_v1",
        "overall": {
            "status": "assessed" if sufficient else (
                "limited_evidence" if evidence_weight else "insufficient_evidence"),
            "score": score,
            "grade": _grade(score) if sufficient else None,
            "coverage_percent": coverage,
            "confidence": "high" if coverage >= 80 else (
                "medium" if sufficient else "low"),
            "observed_risk_level": risk,
            "unknown_not_penalized": True,
            "grade_minimum_coverage_percent": 70,
            "score_denominator": "observed_evidence_only",
        },
        "dimension_weights": dict(DIMENSION_WEIGHTS),
        "dimensions": dimensions,
        "unknown_dimensions": [
            name for name, value in dimensions.items()
            if value["status"] == "unknown"
        ],
        "limitations": [
            "score_covers_only_observed_evidence",
            "unknown_controls_are_excluded_not_scored_as_failures",
            "pre_authentication_observation_is_not_a_security_audit",
            "compare_scores_only_with_similar_coverage",
        ],
    }


def attach_security_assessment(bundle, password_policy=None,
                               password_policy_measured=False) -> dict:
    """Attach or refresh the score and evidence-bounded maturity summary."""
    if not isinstance(bundle, dict):
        return bundle
    bundle["assessment"] = build_security_assessment(
        bundle.get("analyzers") or {}, password_policy,
        password_policy_measured=password_policy_measured)
    from security_observers.maturity import build_cpam_maturity
    bundle["maturity"] = build_cpam_maturity(
        bundle.get("analyzers") or {}, password_policy,
        password_policy_measured=password_policy_measured)
    return bundle
