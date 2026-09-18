"""Deterministic synthetic user responses to password-policy rejection.

The response model is intentionally small and auditable.  It preserves every
user, tries two predictable repairs, then samples from the public phrase
grammar.  It is an experiment mechanism, not a claim about real user behavior.
"""
from __future__ import annotations

import hashlib
import random
from collections import Counter
from statistics import fmean
from typing import Any, Iterable, Mapping, Sequence

from core.synthetic import (
    PHRASE_WORDS,
    candidate_space,
    phrase_space,
    validate_synthetic_dataset,
)
from policy.engine import PasswordPolicy, evaluate_policy_rules


def _stable_random(seed: int, user_id: str) -> random.Random:
    # Common random numbers make policy comparisons lower-variance: if two
    # policies send the same user to the same response stage, that user draws
    # the same synthetic phrase under both policies.
    material = f"{int(seed)}|{user_id}".encode("utf-8")
    value = int.from_bytes(hashlib.sha256(material).digest()[:8], "big")
    return random.Random(value)


def _random_phrase(randomizer: random.Random) -> str:
    return "-".join(randomizer.choice(PHRASE_WORDS) for _ in range(3))


def _response_proposals(
    password: str, randomizer: random.Random, max_attempts: int,
) -> Iterable[tuple[str, str]]:
    if max_attempts >= 1:
        yield password + "!", "append-symbol"
    if max_attempts >= 2:
        yield password + "@7", "append-symbol-digit"
    for _ in range(max(0, max_attempts - 2)):
        yield _random_phrase(randomizer), "random-phrase"


def response_candidate_space(policy: PasswordPolicy) -> list[str]:
    """Enumerate every public response family reachable under ``policy``."""
    candidates: list[str] = []
    needs_phrase_fallback = False
    for password in candidate_space():
        if evaluate_policy_rules(password, policy)["accepted"]:
            candidates.append(password)
            continue
        repairs = (password + "!", password + "@7")
        accepted_repair = next(
            (value for value in repairs if evaluate_policy_rules(value, policy)["accepted"]),
            None,
        )
        if accepted_repair is not None:
            candidates.append(accepted_repair)
        else:
            needs_phrase_fallback = True
    if needs_phrase_fallback:
        accepted_phrases = [
            value for value in phrase_space()
            if evaluate_policy_rules(value, policy)["accepted"]
        ]
        if not accepted_phrases:
            raise ValueError(f"策略 {policy.name!r} 的短语回退没有可用候选")
        candidates.extend(accepted_phrases)
    unique = list(dict.fromkeys(candidates))
    if not unique:
        raise ValueError(f"策略 {policy.name!r} 没有可用的公开合成响应候选")
    return unique


def _distribution(values: Sequence[str]) -> dict[str, Any]:
    counts = Counter(values)
    top_count = max(counts.values(), default=0)
    total = len(values)
    return {
        "total": total,
        "unique_count": len(counts),
        "unique_ratio": len(counts) / total if total else 0.0,
        "top1_count": top_count,
        "top1_mass": top_count / total if total else 0.0,
        "mean_length": fmean(map(len, values)) if values else 0.0,
    }


def _response_summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    total = len(records)
    initial = sum(bool(record["initially_accepted"]) for record in records)
    modified = sum(bool(record["modified"]) for record in records)
    completed = sum(bool(record["finally_accepted"]) for record in records)
    total_attempts = sum(int(record["attempts"]) for record in records)
    attempts_for_modified = [int(record["attempts"]) for record in records if record["modified"]]
    return {
        "total": total,
        "initially_accepted": initial,
        "initial_accept_rate": initial / total if total else 0.0,
        "modified": modified,
        "modification_rate": modified / total if total else 0.0,
        "completed": completed,
        "completion_rate": completed / total if total else 0.0,
        "adoption_rate": completed / total if total else 0.0,
        "total_attempts": total_attempts,
        "mean_attempts_per_user": total_attempts / total if total else 0.0,
        "mean_attempts_per_modified": (
            fmean(attempts_for_modified) if attempts_for_modified else 0.0
        ),
        "max_attempts": max((int(record["attempts"]) for record in records), default=0),
        "response_kinds": dict(Counter(str(record["response_kind"]) for record in records)),
    }


def simulate_policy_response(
    dataset: Mapping[str, Any], policy: PasswordPolicy, *, seed: int = 42,
    max_attempts: int = 8,
) -> dict[str, Any]:
    """Apply one policy without deleting rejected users."""
    if max_attempts < 3:
        raise ValueError("max_attempts 至少为 3，须包含短语回退")
    normalized = validate_synthetic_dataset(dataset)
    details: list[dict[str, Any]] = []
    transformed_records: list[dict[str, str]] = []
    for record in normalized["records"]:
        password = record["password"]
        initial = evaluate_policy_rules(password, policy)
        final_password = password
        attempts = 0
        response_kind = "unchanged"
        if not initial["accepted"]:
            randomizer = _stable_random(seed, record["user_id"])
            for attempts, (proposal, kind) in enumerate(
                _response_proposals(password, randomizer, max_attempts), start=1,
            ):
                if evaluate_policy_rules(proposal, policy)["accepted"]:
                    final_password = proposal
                    response_kind = kind
                    break
            else:
                raise ValueError(
                    f"用户 {record['user_id']} 在 {max_attempts} 次内无法满足策略 {policy.name!r}"
                )
        final = evaluate_policy_rules(final_password, policy)
        detail = {
            "user_id": record["user_id"],
            "split": record["split"],
            "original_password": password,
            "password": final_password,
            "initially_accepted": bool(initial["accepted"]),
            "finally_accepted": bool(final["accepted"]),
            "modified": final_password != password,
            "attempts": attempts,
            "response_kind": response_kind,
            "initial_reasons": list(initial["reasons"]),
        }
        details.append(detail)
        transformed_records.append({
            "user_id": record["user_id"],
            "password": final_password,
            "split": record["split"],
        })

    by_split = {
        split: _response_summary([record for record in details if record["split"] == split])
        for split in ("train", "validation", "test")
    }
    distributions = {}
    for split in ("train", "validation", "test"):
        split_details = [record for record in details if record["split"] == split]
        distributions[split] = {
            "before": _distribution([record["original_password"] for record in split_details]),
            "after": _distribution([record["password"] for record in split_details]),
        }
    transformed_id = f"{normalized['dataset_id']}__policy_{policy.name}"
    return {
        "dataset": {
            "dataset_id": transformed_id,
            "records": transformed_records,
            "metadata": {
                **normalized["metadata"],
                "base_dataset_id": normalized["dataset_id"],
                "policy": policy.to_dict(),
                "response_seed": int(seed),
                "response_model": "predictable repairs then public random phrase",
                "user_count_preserved": len(transformed_records) == len(normalized["records"]),
            },
        },
        "records": details,
        "summary": {
            "overall": _response_summary(details),
            "by_split": by_split,
            "distribution": distributions,
            "user_count_preserved": len(transformed_records) == len(normalized["records"]),
            "max_allowed_attempts": int(max_attempts),
        },
    }
