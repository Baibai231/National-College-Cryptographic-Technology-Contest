"""Privacy-conscious streaming aggregation for Rockyou-style line files.

The raw file is never copied into the ZipfGuard reports. Only ranked counts
and non-identifying metadata are written, so the distribution layer can use a
large corpus without exposing candidate strings in the UI.
"""
from __future__ import annotations

import hashlib
import heapq
from collections import Counter
from pathlib import Path
from typing import Any


def aggregate_rockyou(path: str | Path, *, max_lines: int | None = 1_000_000,
                      top_k: int = 2_000, encoding: str = "utf-8", source_semantics: str = "unknown") -> dict[str, Any]:
    if source_semantics not in ("unknown", "frequency", "unique_dictionary"):
        raise ValueError("无效来源类型")
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    if top_k < 2 or top_k > 100_000:
        raise ValueError("top_k 必须位于 [2,100000]")
    counts: Counter[str] = Counter()
    lines = 0
    with source.open("r", encoding=encoding, errors="replace", newline="") as handle:
        for raw in handle:
            if max_lines is not None and lines >= max_lines:
                break
            lines += 1
            value = raw.rstrip("\r\n")
            if not value or any(ord(char) < 32 for char in value):
                continue
            counts[value] += 1
    ranked = heapq.nlargest(top_k, counts.items(), key=lambda pair: (pair[1], pair[0]))
    ranked.sort(key=lambda pair: (-pair[1], pair[0]))
    observed = sum(counts.values())
    aggregate_total = sum(count for _, count in ranked)
    # Hash identifies the source for reproducibility without sending its path
    # or any password content to a report.
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        digest.update(handle.read(1024 * 1024))
    return {
        "dataset_id": f"rockyou_top_{top_k}",
        "total_count": int(aggregate_total),
        "items": [{"rank": index + 1, "count": int(count)} for index, (_, count) in enumerate(ranked)],
        "metadata": {
            "synthetic": False, "source_type": "authorized local Rockyou-style line corpus",
            "source_sha256_prefix": digest.hexdigest()[:16],
            "source_lines_read": lines, "observed_valid_lines": observed,
            "top_k": top_k, "truncated_mass": 1 - aggregate_total / max(1, observed),
            "plaintext_retained": False,
            "source_semantics": source_semantics,
            "input_deduplicated": True if source_semantics == "unique_dictionary" else False if source_semantics == "frequency" else None,
            "observed_unique_categories": len(counts), "retained_categories": len(ranked),
            "all_observed_counts_one": all(v == 1 for v in counts.values()),
            "frequency_interpretation": "真实频率未确认；重复行频次不等于已验证用户频率" if source_semantics != "frequency" else "用户声明原始频次；按重复行计数",
            "analysis_scope": "条件于读取范围内 top-k 的分布；不代表完整口令分布",
            "aggregation_version": "rockyou-counts-v2",
        },
    }
