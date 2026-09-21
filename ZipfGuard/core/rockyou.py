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


def aggregate_rockyou_withcount(
    path: str | Path, *, top_k: int = 100_000,
    max_lines: int | None = None,
) -> dict[str, Any]:
    """Aggregate ``frequency password`` rows without retaining plaintext.

    The parser works on bytes, so passwords are never decoded, returned, or
    written to a report. A complete pass is still required after the top-k
    rows have been found because the denominator must include the frequency
    mass in the truncated tail.
    """
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    if isinstance(top_k, bool) or not 2 <= int(top_k) <= 1_000_000:
        raise ValueError("top_k 必须位于 [2,1000000]")
    if max_lines is not None and (
        isinstance(max_lines, bool) or int(max_lines) < 2
    ):
        raise ValueError("max_lines 必须为空或至少为 2")

    retained: list[int] = []
    digest = hashlib.sha256()
    lines = valid_rows = blank_rows = invalid_rows = 0
    control_password_rows = empty_password_rows = 0
    frequency_total = 0
    previous_frequency: int | None = None
    order_increases = 0
    reached_eof = True
    with source.open("rb") as handle:
        for raw in handle:
            if max_lines is not None and lines >= int(max_lines):
                reached_eof = False
                break
            lines += 1
            digest.update(raw)
            stripped = raw.rstrip(b"\r\n")
            if not stripped.strip():
                blank_rows += 1
                continue
            cursor = 0
            while cursor < len(stripped) and stripped[cursor] in (9, 32):
                cursor += 1
            frequency_start = cursor
            while cursor < len(stripped) and 48 <= stripped[cursor] <= 57:
                cursor += 1
            if (
                cursor == frequency_start
                or cursor >= len(stripped)
                or stripped[cursor] > 32
            ):
                invalid_rows += 1
                continue
            frequency = int(stripped[frequency_start:cursor])
            # Consume the single format separator. Any remaining whitespace is
            # part of the original password field, though it is never retained.
            password = stripped[cursor + 1:]
            if frequency <= 0:
                invalid_rows += 1
                continue
            # Password bytes never leave this function, so unusual control
            # bytes can safely contribute their documented frequency mass.
            # Retain only the count and expose the row count for audit.
            if any(byte < 32 for byte in password):
                control_password_rows += 1
            if not password.strip():
                empty_password_rows += 1
            valid_rows += 1
            frequency_total += frequency
            if previous_frequency is not None and frequency > previous_frequency:
                order_increases += 1
            previous_frequency = frequency
            if len(retained) < int(top_k):
                heapq.heappush(retained, frequency)
            elif frequency > retained[0]:
                heapq.heapreplace(retained, frequency)

    if valid_rows < 2:
        raise ValueError("带频率语料至少需要两行有效的“频次 口令”记录")
    counts = sorted(retained, reverse=True)
    retained_total = sum(counts)
    scan_label = "full" if reached_eof else f"first_{lines}_lines"
    return {
        "dataset_id": f"rockyou_withcount_{scan_label}_top_{len(counts)}_{digest.hexdigest()[:12]}",
        # The count contract describes the retained conditional distribution.
        "total_count": int(retained_total),
        "items": [
            {"rank": index + 1, "count": int(count)}
            for index, count in enumerate(counts)
        ],
        "metadata": {
            "synthetic": False,
            "source_type": "operator-supplied local RockYou frequency corpus",
            "source_semantics": "frequency_counts",
            "input_deduplicated": "source-declared; not independently verified",
            "source_declares_unique_passwords": True,
            "source_file_size": source.stat().st_size,
            "source_sha256": digest.hexdigest() if reached_eof else None,
            "scanned_prefix_sha256": digest.hexdigest(),
            "hash_scope": "complete file" if reached_eof else "scanned prefix only",
            "source_lines_read": lines,
            "observed_valid_lines": valid_rows,
            "blank_lines": blank_rows,
            "invalid_lines": invalid_rows,
            "password_control_byte_lines": control_password_rows,
            "empty_or_whitespace_password_lines": empty_password_rows,
            "frequency_order_increases": order_increases,
            "observed_frequency_total": int(frequency_total),
            "retained_frequency_total": int(retained_total),
            "retained_categories": len(counts),
            "top_k": len(counts),
            "truncated_mass": 1 - retained_total / frequency_total,
            "plaintext_retained": False,
            "all_observed_counts_one": all(count == 1 for count in counts),
            "frequency_interpretation": "每行首字段作为该条目在公开语料中的出现次数；未独立核验为用户级频率",
            "analysis_scope": (
                "完整语料的频次质量" if reached_eof else "文件前缀的频次质量"
            ) + "；模型拟合条件于保留的 top-k 类别",
            "aggregation_version": "rockyou-withcount-v1",
        },
    }
