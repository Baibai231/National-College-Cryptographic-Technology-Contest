"""Strict, evidence-based quality gates for password-policy measurements.

The project stores both authentication-flow classifications and actively
measured password policies in the ``policy`` field.  This module keeps those
two concepts separate and provides one reusable definition of a *complete*
measurement.  In particular, a database hit, a page hint, or a password field
observation alone must never count towards the 1,000-site measurement goal.
"""

from typing import Any, Dict, Iterable, List, Mapping, Set, Tuple


ACTIVE_METHODS = {
    "inline", "full", "partial_browser_dead", "partial_timeout",
}

RESTRICTIVE_KEYS = {
    "r_no_a_sps", "r_2_word", "r_l_start",
    "r_dig_min", "r_upp_min", "r_low_min", "r_sps_min",
    "r_cmb13", "r_cmb23", "r_cmb33",
    "r_cmb14", "r_cmb24", "r_cmb34", "r_cmb44",
}

RESTRICTIVE_MINIMUM_KEYS = {
    "r_dig_min", "r_upp_min", "r_low_min", "r_sps_min",
}

PERMISSIVE_KEYS = {
    "permitted_characters": {
        "p_space", "p_unicd", "p_emoji",
        "p_spn1", "p_spn2", "p_spn3", "p_spn4",
    },
    "permitted_sequences": {"p_rep", "p_seq", "p_dict", "p_info"},
    "short_and_long_password": {"p_longd", "p_shortd"},
    "breached_password": {"p_br"},
}

DISQUALIFYING_POLICY_FLAGS = {
    "_access_blocked",
    "_gated_form_unverifiable",
    "_suspicious_login_form",
}


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _probe_outcomes(policy: Mapping[str, Any]) -> Set[str]:
    outcomes: Set[str] = set()
    for item in policy.get("_probe_evidence") or []:
        if not isinstance(item, Mapping):
            continue
        outcome = str(item.get("outcome") or "").strip().lower()
        if outcome in {"accepted", "rejected", "inconclusive"}:
            outcomes.add(outcome)
    return outcomes


def _valid_length(policy: Mapping[str, Any]) -> bool:
    length = policy.get("length")
    if not isinstance(length, (list, tuple)) or len(length) != 2:
        return False
    minimum, maximum = length
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum <= 0:
        return False
    if isinstance(maximum, int) and not isinstance(maximum, bool):
        return maximum >= minimum
    if maximum is not None:
        return False
    # A finite experiment cannot prove mathematical unboundedness.  It can,
    # however, completely report the registered protocol result "no maximum
    # observed through the configured ceiling".  Require the structured
    # adaptive trace; a bare null remains unknown and fails the gate.
    adaptive = _as_mapping(policy.get("_adaptive"))
    upper = _as_mapping(adaptive.get("maximum"))
    searched_to = upper.get("searched_to")
    return bool(
        upper.get("status") == "not_observed_within_range"
        and isinstance(searched_to, int)
        and not isinstance(searched_to, bool)
        and searched_to >= 128
    )


def _length_scope(policy: Mapping[str, Any]) -> str:
    length = policy.get("length")
    if not isinstance(length, (list, tuple)) or len(length) != 2:
        return "unknown"
    if isinstance(length[1], int) and not isinstance(length[1], bool):
        return "exact_maximum"
    if _valid_length(policy):
        searched_to = _as_mapping(
            _as_mapping(policy.get("_adaptive")).get("maximum")
        ).get("searched_to")
        return "no_maximum_observed_through_{}".format(searched_to)
    return "unknown"


def _complete_restrictive(policy: Mapping[str, Any]) -> bool:
    restrictive = _as_mapping(policy.get("restrictive"))
    if not RESTRICTIVE_KEYS.issubset(restrictive.keys()):
        return False
    for key in RESTRICTIVE_MINIMUM_KEYS:
        value = restrictive.get(key)
        if (not isinstance(value, int) or isinstance(value, bool)
                or value < 0):
            return False
    return all(
        isinstance(restrictive.get(key), bool)
        for key in RESTRICTIVE_KEYS - RESTRICTIVE_MINIMUM_KEYS
    )


def _complete_permissive(policy: Mapping[str, Any]) -> bool:
    permissive = _as_mapping(policy.get("permissive"))
    for section, required in PERMISSIVE_KEYS.items():
        values = _as_mapping(permissive.get(section))
        if not required.issubset(values.keys()):
            return False
        if not all(isinstance(values.get(key), bool) for key in required):
            return False
    return True


def _password_reached(record: Mapping[str, Any]) -> bool:
    if record.get("flow_type") in {
        "direct_password", "verification_then_password",
    }:
        return True
    for state in record.get("states") or []:
        if isinstance(state, Mapping) and "password" in (state.get("fields") or []):
            return True
    return False


def _entry_found(record: Mapping[str, Any]) -> bool:
    if _password_reached(record):
        return True
    flow_type = record.get("flow_type")
    return flow_type not in (None, "", "unknown", "error")


def evaluate_policy_record(record: Mapping[str, Any]) -> Dict[str, Any]:
    """Evaluate one JSONL/task record against the strict completion gate.

    The returned object is deliberately small so it can be embedded in batch
    records and aggregated without retaining passwords or raw page content.
    """
    partial_policy = _as_mapping(record.get("partial_policy"))
    policy = partial_policy or _as_mapping(record.get("policy"))
    method = str(
        record.get("attempted_method") or record.get("method_used") or "")
    outcomes = _probe_outcomes(policy)
    reasons: List[str] = []

    no_error = not bool(record.get("error"))
    active_measurement = method in ACTIVE_METHODS
    reached = _password_reached(record)
    accepted_control = "accepted" in outcomes
    rejected_control = "rejected" in outcomes
    feedback_control = accepted_control and rejected_control
    length_complete = _valid_length(policy)
    composition_complete = _complete_restrictive(policy)
    permissive_complete = _complete_permissive(policy)
    disqualified = any(bool(policy.get(flag)) for flag in DISQUALIFYING_POLICY_FLAGS)
    inconclusive = bool(policy.get("_inconclusive"))

    if not no_error:
        reasons.append("infrastructure_error")
    if not _entry_found(record):
        reasons.append("signup_entry_not_confirmed")
    if not reached:
        reasons.append("password_field_not_reached")
    if not active_measurement:
        reasons.append("active_policy_measurement_not_run")
    if not rejected_control:
        reasons.append("rejected_control_missing")
    if not accepted_control:
        reasons.append("accepted_control_missing")
    if not length_complete:
        reasons.append("length_boundary_incomplete")
    if not composition_complete:
        reasons.append("composition_policy_incomplete")
    if not permissive_complete:
        reasons.append("permissive_policy_incomplete")
    if disqualified:
        reasons.append("policy_disqualified")
    if inconclusive:
        reasons.append("policy_marked_inconclusive")

    complete = all((
        no_error,
        reached,
        active_measurement,
        feedback_control,
        length_complete,
        composition_complete,
        permissive_complete,
        not disqualified,
        not inconclusive,
    ))

    if complete:
        status = "complete"
    elif active_measurement or reached:
        status = "partial"
    elif _entry_found(record):
        status = "classified_only"
    else:
        status = "unreached"

    return {
        "schema_version": "1.0",
        "status": status,
        "complete": complete,
        "stages": {
            "site_reachable": no_error and bool(record.get("final_url") or record.get("site") or record.get("url")),
            "signup_entry_found": _entry_found(record),
            "password_field_reached": reached,
            "active_measurement_run": active_measurement,
            "accepted_control_observed": accepted_control,
            "rejected_control_observed": rejected_control,
            "length_complete": length_complete,
            "composition_complete": composition_complete,
            "permissive_complete": permissive_complete,
        },
        "length_scope": _length_scope(policy),
        "reasons": reasons,
    }


def aggregate_policy_records(records: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """Return a host-level funnel; only signup records count towards the goal."""
    latest: Dict[str, Tuple[str, Mapping[str, Any]]] = {}
    for record in records:
        if record.get("entry_kind", "signup") != "signup":
            continue
        host = str(record.get("hostname") or record.get("site") or record.get("url") or "")
        if not host:
            continue
        measured_at = str(record.get("measured_at") or "")
        current = latest.get(host)
        if current is None or measured_at >= current[0]:
            latest[host] = (measured_at, record)

    stage_names = [
        "site_reachable", "signup_entry_found", "password_field_reached",
        "active_measurement_run", "accepted_control_observed",
        "rejected_control_observed", "length_complete",
        "composition_complete", "permissive_complete",
    ]
    stage_counts = {name: 0 for name in stage_names}
    statuses: Dict[str, int] = {}
    reasons: Dict[str, int] = {}
    complete_hosts: List[str] = []

    for host, (_, record) in sorted(latest.items()):
        quality = evaluate_policy_record(record)
        statuses[quality["status"]] = statuses.get(quality["status"], 0) + 1
        if quality["complete"]:
            complete_hosts.append(host)
        for name, passed in quality["stages"].items():
            if passed:
                stage_counts[name] += 1
        for reason in quality["reasons"]:
            reasons[reason] = reasons.get(reason, 0) + 1

    total = len(latest)
    return {
        "schema_version": "1.0",
        "goal_complete_sites": 1000,
        "distinct_signup_sites": total,
        "complete_sites": len(complete_hosts),
        "remaining_sites": max(0, 1000 - len(complete_hosts)),
        "complete_rate_percent": round(
            (len(complete_hosts) / total * 100.0) if total else 0.0, 2),
        "stages": {
            name: {
                "count": stage_counts[name],
                "rate_percent": round(
                    (stage_counts[name] / total * 100.0) if total else 0.0, 2),
            }
            for name in stage_names
        },
        "statuses": dict(sorted(statuses.items())),
        "failure_reasons": dict(sorted(
            reasons.items(), key=lambda item: (-item[1], item[0]))),
        "complete_hosts": complete_hosts,
    }
