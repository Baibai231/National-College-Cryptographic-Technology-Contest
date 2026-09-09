"""Evidence-bounded CPAM maturity summary.

The engineering proposal defines a seven-level ladder, but the current crawler
stops before authentication.  This module therefore separates a contiguous
evidence-supported level from higher, non-contiguous capabilities.  It never
infers password storage, enforced MFA, risk-based authentication, or zero-trust
architecture from a login page alone.
"""

from __future__ import annotations


_LEVEL_NAMES = {
    0: "no_password_protection",
    1: "basic_password_authentication",
    2: "secure_password_storage",
    3: "multi_factor_authentication",
    4: "risk_based_authentication",
    5: "public_key_authentication",
    6: "zero_trust_authentication",
}


def _level(level, status="unknown", evidence=None, limitation=None):
    item = {
        "level": level,
        "name": _LEVEL_NAMES[level],
        "status": status,
        "evidence": list(dict.fromkeys(evidence or [])),
    }
    if limitation:
        item["limitation"] = limitation
    return item


def build_cpam_maturity(analyzers, password_policy=None,
                        password_policy_measured=False) -> dict:
    """Build a CPAM ladder without promoting unknown controls.

    ``evidence_supported_level`` is contiguous and conservative.  A Passkey
    control may set ``highest_observed_capability_level`` to 5 while the
    evidence-supported level remains 1, because server-side password storage,
    enforced MFA, and risk authentication were not verified.
    """
    analyzers = analyzers if isinstance(analyzers, dict) else {}
    mfa = analyzers.get("mfa") or {}
    webauthn = analyzers.get("webauthn") or {}
    factors = set(mfa.get("factor_capabilities") or [])

    password_evidence = []
    if "password" in factors:
        password_evidence.append("password_authentication_ui_observed")
    if password_policy_measured and isinstance(password_policy, dict):
        password_evidence.append("password_policy_probe_completed")

    levels = [
        _level(
            0,
            "not_assigned" if password_evidence or factors else "unknown",
            limitation="absence_of_visible_password_is_not_proof_of_no_protection",
        ),
        _level(
            1,
            "observed" if password_evidence else "unknown",
            password_evidence,
            "authentication_capability_observed_not_server_implementation_verified"
            if password_evidence else None,
        ),
        _level(
            2,
            limitation="password_storage_is_server_side_and_not_observable_pre_authentication",
        ),
    ]

    completed_mfa = bool(mfa.get("completed_multi_factor_sequence"))
    enforced_mfa = mfa.get("mfa_enforcement") in {
        "observed", "confirmed", "enforced",
    }
    if completed_mfa and enforced_mfa:
        level3_status = "observed"
        level3_evidence = ["completed_enforced_multi_factor_sequence"]
        level3_limit = None
    elif len(factors) >= 2:
        level3_status = "unverified"
        level3_evidence = ["multiple_pre_authentication_factor_choices_observed"]
        level3_limit = "parallel_authentication_choices_do_not_prove_enforced_mfa"
    else:
        level3_status = "unknown"
        level3_evidence = []
        level3_limit = "mfa_enforcement_requires_authenticated_observation"
    levels.append(_level(
        3, level3_status, level3_evidence, level3_limit,
    ))
    levels.append(_level(
        4,
        limitation="risk_based_authentication_requires_longitudinal_authenticated_evidence",
    ))

    if webauthn.get("registration_or_signature_verified"):
        level5_status = "observed"
        level5_evidence = ["webauthn_registration_or_signature_verified"]
        level5_limit = None
    elif webauthn.get("site_capability_observed"):
        level5_status = "capability_observed"
        level5_evidence = ["webauthn_or_passkey_ui_capability_observed"]
        level5_limit = "webauthn_ceremony_not_completed"
    else:
        level5_status = "unknown"
        level5_evidence = []
        level5_limit = "not_observed_does_not_mean_unsupported"
    levels.append(_level(
        5, level5_status, level5_evidence, level5_limit,
    ))
    levels.append(_level(
        6,
        limitation="zero_trust_architecture_cannot_be_inferred_from_pre_authentication_ui",
    ))

    level_by_number = {item["level"]: item for item in levels}
    supported = 1 if level_by_number[1]["status"] == "observed" else None
    # Level 2 is intentionally unknown in the present passive evidence model,
    # so no higher level can become part of the contiguous supported ladder.
    highest = max(
        (item["level"] for item in levels
         if item["status"] in {"observed", "capability_observed"}),
        default=None,
    )
    missing_prerequisites = []
    if highest and highest > 1:
        missing_prerequisites = [
            item["level"] for item in levels
            if 2 <= item["level"] < highest and item["status"] != "observed"
        ]

    return {
        "schema_version": "1.0",
        "model": "cpam_evidence_ladder_v1",
        "overall": {
            "status": "limited_evidence" if highest is not None
            else "insufficient_evidence",
            "evidence_supported_level": supported,
            "highest_observed_capability_level": highest,
            "complete_maturity_rating": False,
            "higher_capability_is_not_contiguous_maturity": bool(
                highest is not None and (supported is None or highest > supported)
            ),
            "unknown_prerequisite_levels": missing_prerequisites,
        },
        "levels": levels,
        "limitations": [
            "pre_authentication_evidence_only",
            "server_side_password_storage_not_inferred",
            "parallel_factors_do_not_prove_enforced_mfa",
            "risk_authentication_and_zero_trust_require_authorized_longitudinal_review",
            "highest_observed_capability_is_not_a_complete_maturity_rating",
        ],
    }
