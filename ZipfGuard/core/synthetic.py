"""Deterministic synthetic users shared by every ZipfGuard experiment.

The generated strings come from a small public grammar. They are not real
credentials and are safe to include in local tests. A single dataset owns the
train/validation/test split so distribution, policy, and attacker experiments
cannot silently use unrelated samples.
"""
from __future__ import annotations

import random
from collections import Counter
from typing import Any, Iterable, Mapping

import numpy as np


ROOT_WORDS = (
    "cedar", "maple", "cloud", "river", "panda", "tiger", "cobalt", "amber",
    "coral", "lunar", "forest", "meadow", "delta", "comet", "spruce", "willow",
    "harbor", "lotus", "otter", "falcon", "orchid", "silk", "pebble", "bamboo",
)
PHRASE_WORDS = (
    "birch", "ocean", "quartz", "mango", "violet", "dune", "raven", "mint",
    "opal", "brook", "linen", "plum", "snow", "fern", "cove", "reed",
)
SUFFIXES = ("123", "2026", "01", "88", "!", "7", "99", "520", "", "42", "2025", "@")
SPLITS = ("train", "validation", "test")


def candidate_space() -> list[str]:
    values: list[str] = []
    for root in ROOT_WORDS:
        for suffix in SUFFIXES:
            values.extend((root + suffix, root[0].upper() + root[1:] + suffix))
    return list(dict.fromkeys(values))


def phrase_space() -> list[str]:
    return [f"{first}-{second}-{third}" for first in PHRASE_WORDS
            for second in PHRASE_WORDS for third in PHRASE_WORDS]


def generate_synthetic_dataset(
    *, size: int = 20_000, seed: int = 42, exponent: float = 1.08,
    train_ratio: float = 0.6, validation_ratio: float = 0.2,
) -> dict[str, Any]:
    """Generate reproducible synthetic users and a fixed three-way split."""
    if isinstance(size, bool) or int(size) != size or size < 100:
        raise ValueError("size 必须是至少 100 的整数")
    if exponent <= 0:
        raise ValueError("exponent 必须为正数")
    if not 0 < train_ratio < 1 or not 0 < validation_ratio < 1:
        raise ValueError("训练集和验证集比例须位于 (0,1)")
    if train_ratio + validation_ratio >= 1:
        raise ValueError("训练集与验证集比例之和必须小于 1")

    size = int(size)
    candidates = candidate_space()
    weights = [1 / ((index + 1) ** float(exponent)) for index in range(len(candidates))]
    randomizer = random.Random(int(seed))
    passwords = randomizer.choices(candidates, weights=weights, k=size)
    train_end = int(size * train_ratio)
    validation_end = train_end + int(size * validation_ratio)
    split_counts = {
        "train": train_end,
        "validation": validation_end - train_end,
        "test": size - validation_end,
    }
    records = []
    for index, password in enumerate(passwords):
        split = "train" if index < train_end else "validation" if index < validation_end else "test"
        records.append({"user_id": f"syn-{index:07d}", "password": password, "split": split})
    dataset_id = f"synthetic_users_s{int(seed)}_n{size}"
    return {
        "dataset_id": dataset_id,
        "records": records,
        "metadata": {
            "synthetic": True,
            "seed": int(seed),
            "exponent": float(exponent),
            "candidate_count": len(candidates),
            "split": "60/20/20" if train_ratio == 0.6 and validation_ratio == 0.2 else "custom",
            "split_counts": split_counts,
            "source": "deterministic public synthetic password grammar",
        },
    }


def validate_synthetic_dataset(dataset: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(dataset, Mapping):
        raise ValueError("合成数据集必须是对象")
    records = dataset.get("records")
    if not isinstance(records, list) or len(records) < 100:
        raise ValueError("合成数据集至少需要 100 条用户记录")
    normalized_records = []
    seen_ids: set[str] = set()
    split_counts = Counter()
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise ValueError(f"records[{index}] 必须是对象")
        user_id = str(record.get("user_id", ""))
        password = str(record.get("password", ""))
        split = str(record.get("split", ""))
        if not user_id or user_id in seen_ids:
            raise ValueError("user_id 必须非空且唯一")
        if not password or any(ord(character) < 32 for character in password):
            raise ValueError("合成口令必须非空且不能包含控制字符")
        if split not in SPLITS:
            raise ValueError(f"split 必须是 {SPLITS} 之一")
        seen_ids.add(user_id)
        split_counts[split] += 1
        normalized_records.append({"user_id": user_id, "password": password, "split": split})
    if any(split_counts[name] == 0 for name in SPLITS):
        raise ValueError("train、validation 和 test 均不能为空")
    return {
        "dataset_id": str(dataset.get("dataset_id", "synthetic_users")),
        "records": normalized_records,
        "metadata": dict(dataset.get("metadata") or {}),
    }


def passwords_for_split(dataset: Mapping[str, Any], split: str) -> list[str]:
    if split not in SPLITS:
        raise ValueError(f"未知数据划分：{split}")
    normalized = validate_synthetic_dataset(dataset)
    return [record["password"] for record in normalized["records"] if record["split"] == split]


def aggregate_synthetic_counts(
    dataset: Mapping[str, Any], *, splits: Iterable[str] = SPLITS,
) -> dict[str, Any]:
    normalized = validate_synthetic_dataset(dataset)
    selected = tuple(dict.fromkeys(str(split) for split in splits))
    if not selected or any(split not in SPLITS for split in selected):
        raise ValueError("聚合划分无效")
    counts = Counter(
        record["password"] for record in normalized["records"] if record["split"] in selected
    )
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    metadata = dict(normalized["metadata"])
    metadata.update({
        "synthetic": True,
        "source": "deterministic public synthetic password grammar",
        "splits_included": list(selected),
        "plaintext_retained": False,
    })
    return {
        "dataset_id": normalized["dataset_id"],
        "total_count": sum(counts.values()),
        "items": [{"rank": index + 1, "count": count} for index, (_, count) in enumerate(ranked)],
        "metadata": metadata,
    }


def aligned_train_validation_counts(
    dataset: Mapping[str, Any],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return train+validation, train, validation counts on a frozen support."""
    normalized = validate_synthetic_dataset(dataset)
    training = Counter(record["password"] for record in normalized["records"] if record["split"] == "train")
    validation = Counter(record["password"] for record in normalized["records"] if record["split"] == "validation")
    support = sorted(set(training) | set(validation), key=lambda value: (-training[value], value))
    train_array = np.asarray([training[value] for value in support], dtype=np.int64)
    validation_array = np.asarray([validation[value] for value in support], dtype=np.int64)
    return train_array + validation_array, train_array, validation_array
