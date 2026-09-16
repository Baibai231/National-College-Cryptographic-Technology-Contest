"""Data contracts and deterministic synthetic data for the ZipfGuard demo.

The public pipeline accepts aggregate counts by default.  The small synthetic
generator is intentionally public and deterministic so the demo can run
without importing real credentials or contacting an authentication service.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np


def validate_count_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError("数据必须是 JSON 对象")
    items = payload.get("items")
    if not isinstance(items, list) or len(items) < 2:
        raise ValueError("items 必须包含至少两个聚合类别")
    ranks, counts = [], []
    for index, item in enumerate(items, 1):
        if not isinstance(item, Mapping) or "count" not in item:
            raise ValueError(f"items[{index - 1}] 缺少 count")
        rank = item.get("rank", index)
        count = item["count"]
        if isinstance(rank, bool) or int(rank) != rank or rank < 1:
            raise ValueError("rank 必须是正整数")
        if isinstance(count, bool) or int(count) != count or count < 0:
            raise ValueError("count 必须是非负整数")
        ranks.append(int(rank)); counts.append(int(count))
    if len(set(ranks)) != len(ranks) or sorted(ranks) != list(range(1, len(ranks) + 1)):
        raise ValueError("rank 必须从 1 连续编号")
    if sum(counts) < 20:
        raise ValueError("总样本数至少为 20")
    if any(counts[i] < counts[i + 1] for i in range(len(counts) - 1)):
        raise ValueError("聚合频次必须按降序排列")
    declared_total = payload.get("total_count", sum(counts))
    if isinstance(declared_total, bool) or int(declared_total) != declared_total or int(declared_total) != sum(counts):
        raise ValueError("total_count 必须等于 items.count 的总和")
    metadata = dict(payload.get("metadata") or {})
    return {
        "dataset_id": str(payload.get("dataset_id", "anonymous_counts")),
        "total_count": int(declared_total),
        "items": [{"rank": rank, "count": count} for rank, count in zip(ranks, counts)],
        "metadata": metadata,
    }


def load_count_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return validate_count_payload(json.load(handle))


def counts_from_payload(payload: Mapping[str, Any]) -> np.ndarray:
    normalized = validate_count_payload(payload)
    return np.asarray([item["count"] for item in normalized["items"]], dtype=np.int64)


def synthetic_counts(*, size: int = 20_000, categories: int = 600,
                     exponent: float = 1.12, seed: int = 42) -> dict[str, Any]:
    if size < 20 or categories < 2 or exponent <= 0:
        raise ValueError("size、categories 和 exponent 参数无效")
    rng = np.random.default_rng(seed)
    ranks = np.arange(1, categories + 1, dtype=float)
    probabilities = ranks ** (-float(exponent)); probabilities /= probabilities.sum()
    counts = np.sort(rng.multinomial(int(size), probabilities))[::-1]
    return {
        "dataset_id": f"synthetic_zipf_{seed}",
        "total_count": int(counts.sum()),
        "items": [{"rank": i + 1, "count": int(value)} for i, value in enumerate(counts)],
        "metadata": {
            "synthetic": True, "seed": int(seed), "exponent": float(exponent),
            "source": "deterministic finite-support synthetic distribution",
        },
    }


def write_count_json(payload: Mapping[str, Any], path: str | Path) -> Path:
    normalized = validate_count_payload(payload)
    output = Path(path); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output
