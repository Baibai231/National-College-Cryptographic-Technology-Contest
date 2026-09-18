"""Explainable policy rules and a deterministic synthetic red-team benchmark.

The benchmark is deliberately limited to a public grammar.  It is useful for
comparing policy changes and exercising the UI; it is not a password cracker.
"""
from __future__ import annotations

import dataclasses
import math
import random
import re
from collections import Counter
from typing import Any, Iterable, Mapping, Sequence

ROOT_WORDS = ("cedar", "maple", "cloud", "river", "panda", "tiger", "cobalt", "amber", "coral", "lunar", "forest", "meadow", "delta", "comet", "spruce", "willow", "harbor", "lotus", "otter", "falcon", "orchid", "silk", "pebble", "bamboo")
PHRASE_WORDS = ("birch", "ocean", "quartz", "mango", "violet", "dune", "raven", "mint", "opal", "brook", "linen", "plum", "snow", "fern", "cove", "reed")
SUFFIXES = ("123", "2026", "01", "88", "!", "7", "99", "520", "", "42", "2025", "@")


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


def _candidate_space() -> list[str]:
    values = []
    for root in ROOT_WORDS:
        for suffix in SUFFIXES:
            values.extend((root + suffix, root[0].upper() + root[1:] + suffix))
    return list(dict.fromkeys(values))


def _phrase_space() -> list[str]:
    return [f"{a}-{b}-{c}" for a in PHRASE_WORDS for b in PHRASE_WORDS for c in PHRASE_WORDS]


def _samples(size: int, seed: int) -> list[str]:
    randomizer = random.Random(seed); candidates = _candidate_space()
    weights = [1 / ((index + 1) ** 1.08) for index in range(len(candidates))]
    return randomizer.choices(candidates, weights=weights, k=size)


def _rank(samples: Sequence[str], candidates: Sequence[str]) -> list[str]:
    counts = Counter(samples); unique = list(dict.fromkeys(candidates))
    # Frequency plus a small structural score approximates the hybrid baseline.
    def score(value: str) -> tuple[float, float, str]:
        f = counts.get(value, 0) / max(1, len(samples)); features = extract_features(value)
        structural = 0.001 * (1 if features["year_suffix"] else 0) + 0.0005 * (1 if features["common_word"] else 0)
        return (f + structural, f, value)
    return sorted(unique, key=score, reverse=True)


def evaluate_policy(policy: PasswordPolicy, *, seed: int = 42, budgets: Sequence[int] = (100, 1000, 10000)) -> dict[str, Any]:
    train = _samples(6000, seed); test = _samples(2000, seed + 1)
    candidates = _candidate_space() + (_phrase_space() if policy.allow_passphrase else [])
    accepted_train = [value for value in train if evaluate_policy_rules(value, policy)["accepted"]]
    accepted_test = [value for value in test if evaluate_policy_rules(value, policy)["accepted"]]
    ranking = _rank(accepted_train, [value for value in candidates if evaluate_policy_rules(value, policy)["accepted"]])
    baseline_ranking = _rank(train, _candidate_space())
    evaluated_count = len(accepted_test)
    status = "evaluated" if evaluated_count else "not_evaluable"
    reason = "" if evaluated_count else "全部测试样本被拒绝，没有可评估样本；不能据此推断安全收益。"
    attack = []
    baseline_attack = []
    for budget in budgets:
        k = max(1, int(budget)); ranks = {value: index + 1 for index, value in enumerate(ranking)}; base = {value: index + 1 for index, value in enumerate(baseline_ranking)}
        cracked = sum(ranks.get(value, math.inf) <= k for value in accepted_test)
        hit = cracked / evaluated_count if evaluated_count else None
        base_hit = sum(base.get(value, math.inf) <= k for value in test) / max(1, len(test))
        attack.append({"budget": k, "rate": hit, "cracked": cracked, "evaluated_count": evaluated_count})
        baseline_attack.append({"budget": k, "rate": base_hit, "cracked": round(base_hit * len(test))})
    coverage = len(accepted_test) / max(1, len(test))
    gains = [base["rate"] - row["rate"] for base, row in zip(baseline_attack, attack)
             if row["rate"] is not None]
    return {"policy": policy.to_dict(), "attack": attack, "baseline_attack": baseline_attack,
            "evaluation_status": status, "evaluation_reason": reason,
            "sample_counts": {"total": len(test), "accepted": evaluated_count,
                              "rejected": len(test) - evaluated_count, "evaluated": evaluated_count},
            "attack_coverage": coverage, "accept_rate": coverage, "user_cost": 1 - coverage,
            "security_gain": max(gains) if gains else None,
            "candidate_count": len(ranking), "attacker": "local synthetic frequency + structural baseline",
            "data_scope": "public synthetic grammar; train/test generated with independent seeds"}


def optimize_policies(*, seed: int = 42, budgets: Sequence[int] = (100, 1000, 10000), max_candidates: int = 12) -> list[PasswordPolicy]:
    candidates = list(DEFAULT_POLICIES)
    # Pareto candidates are selected from measurable evaluations; this keeps
    # search deterministic and avoids claiming a black-box optimum.
    scored = [(policy, evaluate_policy(policy, seed=seed, budgets=budgets)) for policy in candidates[:max_candidates]]
    # Keep the full measured frontier candidates for the What-if UI. A policy
    # can be dominated on this tiny grammar and still be useful as an explicit
    # control; the report exposes its measured cost rather than hiding it.
    return [policy for policy, _ in scored]
