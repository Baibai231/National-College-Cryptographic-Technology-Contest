"""Leakage-resistant classical attack baselines for the synthetic benchmark.

All candidate strings come from ZipfGuard's public synthetic grammar.  The
attackers are useful for comparing rankings under a controlled protocol; they
are not intended for attacking authentication systems or real credentials.
"""
from __future__ import annotations

import dataclasses
import math
from abc import ABC, abstractmethod
from collections import Counter, defaultdict
from typing import Any, Iterable, Mapping, Sequence

from core.metrics import evaluate_ranking
from core.synthetic import (
    candidate_space,
    passwords_for_split,
    validate_synthetic_dataset,
)

START = "\u0002"
END = "\u0003"
UNKNOWN = "\u0000"


@dataclasses.dataclass(frozen=True)
class RankingResult:
    """Common, immutable output of every baseline attacker."""

    attacker_id: str
    label: str
    version: str
    guesses: tuple[str, ...]
    parameters: Mapping[str, Any]
    selection: Mapping[str, Any]
    training_size: int
    validation_size: int

    def summary(self, *, top_n: int = 10) -> dict[str, Any]:
        return {
            "attacker_id": self.attacker_id,
            "label": self.label,
            "version": self.version,
            "candidate_count": len(self.guesses),
            "parameters": dict(self.parameters),
            "selection": dict(self.selection),
            "training_size": self.training_size,
            "validation_size": self.validation_size,
            "top_guesses": list(self.guesses[:max(0, int(top_n))]),
        }


class BaselineAttacker(ABC):
    """Uniform fit/select/rank contract for deterministic offline attackers."""

    attacker_id: str
    label: str
    version = "m2-2026.1"

    @abstractmethod
    def fit_select_rank(
        self, train: Sequence[str], validation: Sequence[str], candidates: Sequence[str],
    ) -> RankingResult:
        raise NotImplementedError


def _unique_candidates(candidates: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(candidate) for candidate in candidates))


class FrequencyAttacker(BaselineAttacker):
    attacker_id = "frequency"
    label = "训练集频次"

    def fit_select_rank(self, train, validation, candidates) -> RankingResult:
        allowed = set(_unique_candidates(candidates))
        counts = Counter(str(value) for value in train if str(value) in allowed)
        guesses = tuple(sorted(counts, key=lambda value: (-counts[value], value)))
        return RankingResult(
            self.attacker_id, self.label, self.version, guesses,
            parameters={"tie_breaker": "unicode-ascending"},
            selection={"method": "none", "split": None},
            training_size=len(train), validation_size=len(validation),
        )


class SyntheticDictionaryAttacker(BaselineAttacker):
    attacker_id = "synthetic-dictionary"
    label = "公开合成字典"

    def fit_select_rank(self, train, validation, candidates) -> RankingResult:
        guesses = tuple(_unique_candidates(candidates))
        return RankingResult(
            self.attacker_id, self.label, self.version, guesses,
            parameters={"ordering": "public-grammar-prior"},
            selection={"method": "pre-registered ordering", "split": None},
            training_size=len(train), validation_size=len(validation),
        )


@dataclasses.dataclass
class _NgramModel:
    order: int
    smoothing: float
    alphabet: tuple[str, ...]
    counts: list[dict[str, Counter[str]]]
    totals: list[Counter[str]]

    def probability(self, character: str, history: str) -> float:
        symbol = character if character in self.alphabet else UNKNOWN
        vocabulary_size = len(self.alphabet)
        base_count = self.counts[0][""][symbol]
        probability = (
            base_count + self.smoothing
        ) / (self.totals[0][""] + self.smoothing * vocabulary_size)
        for depth in range(1, self.order):
            context = history[-depth:]
            total = self.totals[depth][context]
            if not total:
                continue
            prior_strength = self.smoothing * vocabulary_size
            probability = (
                self.counts[depth][context][symbol] + prior_strength * probability
            ) / (total + prior_strength)
        return probability

    def negative_log_likelihood(self, value: str) -> float:
        history = START * (self.order - 1)
        loss = 0.0
        for character in (*str(value), END):
            loss -= math.log(self.probability(character, history))
            history += character if character in self.alphabet else UNKNOWN
        return loss


def _fit_ngram(
    train: Sequence[str], order: int, smoothing: float, *, public_candidates: Sequence[str],
) -> _NgramModel:
    # The alphabet is part of the public grammar, not inferred from validation
    # or test.  Including all public symbols also keeps additive smoothing a
    # proper probability distribution when a rare symbol is absent from train.
    alphabet = tuple(sorted(
        {character for value in public_candidates for character in str(value)} | {END, UNKNOWN}
    ))
    counts: list[dict[str, Counter[str]]] = [defaultdict(Counter) for _ in range(order)]
    totals: list[Counter[str]] = [Counter() for _ in range(order)]
    for raw_value in train:
        value = str(raw_value)
        history = START * (order - 1)
        for character in (*value, END):
            for depth in range(order):
                context = history[-depth:] if depth else ""
                counts[depth][context][character] += 1
                totals[depth][context] += 1
            history += character
    return _NgramModel(order, smoothing, alphabet, counts, totals)


class CharacterNgramAttacker(BaselineAttacker):
    attacker_id = "character-ngram"
    label = "字符 n-gram"

    def __init__(
        self, *, orders: Sequence[int] = (2, 3, 4),
        smoothing_values: Sequence[float] = (0.1, 0.3, 1.0),
    ):
        normalized_orders = tuple(sorted({int(value) for value in orders}))
        normalized_smoothing = tuple(sorted({float(value) for value in smoothing_values}))
        if not normalized_orders or any(value < 1 or value > 5 for value in normalized_orders):
            raise ValueError("n-gram 阶数须位于 [1,5]")
        if not normalized_smoothing or any(value <= 0 for value in normalized_smoothing):
            raise ValueError("平滑参数必须为正数")
        self.orders = normalized_orders
        self.smoothing_values = normalized_smoothing

    def fit_select_rank(self, train, validation, candidates) -> RankingResult:
        if not train or not validation:
            raise ValueError("字符 n-gram 需要非空 train 和 validation")
        public_candidates = _unique_candidates(candidates)
        trials: list[tuple[float, int, float, _NgramModel]] = []
        validation_characters = sum(len(str(value)) + 1 for value in validation)
        for order in self.orders:
            for smoothing in self.smoothing_values:
                model = _fit_ngram(
                    train, order, smoothing, public_candidates=public_candidates,
                )
                loss = sum(model.negative_log_likelihood(str(value)) for value in validation)
                trials.append((loss / validation_characters, order, smoothing, model))
        validation_nll, order, smoothing, selected = min(
            trials, key=lambda row: (row[0], row[1], row[2])
        )
        guesses = tuple(sorted(
            public_candidates,
            key=lambda value: (selected.negative_log_likelihood(value), value),
        ))
        return RankingResult(
            self.attacker_id, self.label, self.version, guesses,
            parameters={"order": order, "smoothing": smoothing},
            selection={
                "method": "minimum validation per-character NLL",
                "split": "validation",
                "validation_nll": validation_nll,
                "trials": len(trials),
            },
            training_size=len(train), validation_size=len(validation),
        )


def default_attackers() -> tuple[BaselineAttacker, ...]:
    return FrequencyAttacker(), SyntheticDictionaryAttacker(), CharacterNgramAttacker()


def run_attack_baselines(
    dataset: Mapping[str, Any], *, budgets: Sequence[int] = (100, 1_000, 10_000),
    attackers: Sequence[BaselineAttacker] | None = None,
) -> dict[str, Any]:
    """Run all baselines with train/validation/test roles fixed by protocol."""
    normalized = validate_synthetic_dataset(dataset)
    train = passwords_for_split(normalized, "train")
    validation = passwords_for_split(normalized, "validation")
    test = passwords_for_split(normalized, "test")
    candidates = candidate_space()
    rows = []
    for attacker in attackers or default_attackers():
        ranking = attacker.fit_select_rank(train, validation, candidates)
        rows.append({
            "attacker": ranking.summary(),
            "evaluation": evaluate_ranking(ranking.guesses, test, budgets),
        })
    return {
        "dataset_id": normalized["dataset_id"],
        "protocol": {
            "fit_split": "train",
            "selection_split": "validation",
            "evaluation_split": "test",
            "candidate_source": "public synthetic grammar",
            "test_used_for_ranking": False,
            "interval": "pointwise 95% Wilson score interval",
        },
        "split_sizes": {
            "train": len(train), "validation": len(validation), "test": len(test),
        },
        "budgets": sorted({int(value) for value in budgets if int(value) > 0}),
        "attacks": rows,
    }
