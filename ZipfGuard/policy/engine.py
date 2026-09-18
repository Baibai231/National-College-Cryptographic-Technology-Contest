"""Explainable policy rules and a deterministic synthetic red-team benchmark.

The benchmark is deliberately limited to a public grammar.  It is useful for
comparing policy changes and exercising the UI; it is not a password cracker.
"""
from __future__ import annotations

import dataclasses
import re
from typing import Any, Mapping, Sequence

from core.synthetic import (
    ROOT_WORDS,
    generate_synthetic_dataset,
    validate_synthetic_dataset,
)


@dataclasses.dataclass(frozen=True)
class PasswordPolicy:
    name: str = "baseline"
    min_length: int = 0
    required_classes: int = 0
    deny_features: tuple[str, ...] = ()
    deny_context_overlap: bool = False
    allow_passphrase: bool = True
    risk_budget: int = 1000
    version: str = "dp-htpg-2026.1"

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "min_length": self.min_length, "required_classes": self.required_classes,
                "deny_features": list(self.deny_features), "deny_context_overlap": self.deny_context_overlap,
                "allow_passphrase": self.allow_passphrase, "risk_budget": self.risk_budget, "version": self.version}


DEFAULT_POLICIES = (
    PasswordPolicy(),
    PasswordPolicy("length-8", min_length=8),
    PasswordPolicy("block-year-keyboard", min_length=8, deny_features=("year_suffix", "keyboard_walk")),
    PasswordPolicy("diversified-phrase", min_length=8, deny_features=("year_suffix", "keyboard_walk", "common_word"), allow_passphrase=True),
)


def extract_features(password: str) -> dict[str, Any]:
    value = str(password)
    lower = value.lower()
    year_suffix = bool(re.search(r"(?:19|20)\d{2}$", value))
    keyboard = bool(re.search(r"(?:qwerty|asdf|zxcv|1234|4321|abcdef)", lower))
    repeated = bool(re.search(r"(.)\1{2,}", value))
    sequential_digits = bool(re.search(r"(?:0123|1234|2345|3456|4567|5678|6789|9876|8765|7654|6543|5432|4321|3210)", value))
    date_suffix = bool(re.search(r"(?:19|20)\d{2}(?:0[1-9]|1[0-2])?(?:0[1-9]|[12]\d|3[01])?$", value))
    leetspeak = bool(re.search(r"[4@]", value) and re.search(r"[3eE]", value))
    common_word = lower.rstrip("0123456789!@#$%^&*_").lower() in ROOT_WORDS
    classes = sum(bool(pattern.search(value)) for pattern in (re.compile(r"[a-z]"), re.compile(r"[A-Z]"), re.compile(r"\d"), re.compile(r"[^A-Za-z0-9]")))
    return {"length": len(value), "lowercase_only": value.islower() and value.isalpha(), "digit_ratio": sum(c.isdigit() for c in value) / max(1, len(value)), "class_count": classes, "year_suffix": year_suffix, "date_suffix": date_suffix, "keyboard_walk": keyboard, "repeated": repeated, "repeated_chars": repeated, "sequential_digits": sequential_digits, "leetspeak": leetspeak, "common_word": common_word, "word_plus_digits": bool(re.match(r"^[A-Za-z]+\d{2,}$", value)), "phrase": value.count("-") >= 2}


def evaluate_policy_rules(password: str, policy: PasswordPolicy, *, context: Sequence[str] = ()) -> dict[str, Any]:
    features = extract_features(password); reasons = []
    if features["length"] < policy.min_length: reasons.append("长度不足")
    if features["class_count"] < policy.required_classes: reasons.append("字符类别不足")
    for feature in policy.deny_features:
        if features.get(feature): reasons.append(feature)
    if policy.deny_context_overlap and any(str(item).lower() in password.lower() for item in context if item): reasons.append("上下文重叠")
    if not policy.allow_passphrase and features["phrase"]: reasons.append("不允许长短语")
    return {"accepted": not reasons, "reasons": reasons, "features": features}


def evaluate_policy(
    policy: PasswordPolicy, *, seed: int = 42,
    budgets: Sequence[int] = (100, 1000, 10000),
    dataset: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate a policy through the M3 preserved-user adaptive protocol."""
    normalized_dataset = validate_synthetic_dataset(
        dataset or generate_synthetic_dataset(size=10_000, seed=seed)
    )
    # Local import avoids a module cycle: the M3 orchestrator consumes the
    # policy type from this module and is the sole implementation of strategy
    # attack evaluation.
    from experiments.policy_attack import run_policy_attack_experiment

    policies = (policy,) if policy.name == "baseline" else (DEFAULT_POLICIES[0], policy)
    experiment = run_policy_attack_experiment(
        normalized_dataset, policies, budgets=budgets, seed=seed,
    )
    return next(row for row in experiment["policies"] if row["policy"]["name"] == policy.name)


def optimize_policies(*, seed: int = 42, budgets: Sequence[int] = (100, 1000, 10000), max_candidates: int = 12) -> list[PasswordPolicy]:
    candidates = list(DEFAULT_POLICIES)
    # Keep the full measured frontier candidates for the What-if UI. A policy
    # can be dominated on this tiny grammar and still be useful as an explicit
    # control; the report exposes its measured cost rather than hiding it.
    return candidates[:max_candidates]
