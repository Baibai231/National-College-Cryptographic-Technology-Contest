"""Streaming offline feature extraction; never exports plaintext passwords.

Run from ZipfGuard: python -m experiments.extract_htpg_features --help
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack
import gzip
import hashlib
import json
from pathlib import Path
import platform
import time

from core.counted_corpus import parse_counted_line
from core.htpg_features import FEATURE_NAMES, HTPGFeatureExtractor


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: dict):
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def render_report(summary: dict, metadata: dict) -> str:
    audit = summary["audit"]
    lines = ["# HTPG 特征提取结果（程序自动生成）", "",
             "这是特征提取阶段：不在这里划分头尾、不生成修改建议、不执行猜测攻击。", "",
             f"- 完整读取文件：{audit['complete_file']}；输入行数：{audit['source_rows']:,}；输入计数：{audit['source_mass']:,}。",
             f"- 非空记录：{audit['nonempty_rows']:,}；对应计数：{audit['nonempty_mass']:,}。",
             f"- 排除空口令：{audit['empty_rows']:,} 行 / {audit['empty_mass']:,} 次。",
             f"- UTF-8 可解释：{audit['decoded_rows']:,} 行；无法解释：{audit['invalid_utf8_rows']:,} 行 / {audit['invalid_utf8_mass']:,} 次（九项均记未知，未伪装成否）。",
             f"- 首尾空白：{audit['boundary_whitespace_rows']:,} 行；控制字节：{audit['control_byte_rows']:,} 行；均保留。",
             f"- 输入已按频次降序：{audit['counts_nonincreasing']}。本工具不合并重复记录；种类比例需输入预先去重聚合。", "",
             "## 特征分布", "",
             "记录比例以所有非空记录为分母；频次比例以所有非空记录的计数之和为分母。未知项也保留在分母中。", "",
             "| 特征 | 值 | 记录数 | 记录比例 | 频次之和 | 频次比例 |",
             "| --- | --- | ---: | ---: | ---: | ---: |"]
    for name in FEATURE_NAMES:
        for entry in summary["features"][name]["values"]:
            lines.append(f"| {name} | {entry['value']} | {entry['rows']:,} | {entry['row_fraction']:.4%} | {entry['mass']:,} | {entry['mass_fraction']:.4%} |")
        other = summary["features"][name]["other"]
        if other["rows"]:
            lines.append(f"| {name} | 其他（汇总） | {other['rows']:,} | {other['row_fraction']:.4%} | {other['mass']:,} | {other['mass_fraction']:.4%} |")
    lines += ["", "## 复现边界", "",
              "- LSD 是有顺序的连续字符段，不是只统计字母、数字、符号各有多少。",
              "- Lowercase 是边界孤立小写字母，不是是否存在任意小写字母。",
              "- 特殊字符可同时出现在多个位置，本实现保留位置集合，属于对原文四类描述的明确扩展。",
              "- 日期、键盘判定采用文档规定的可测试启发式，不是作者未公开的原始代码。",
              "- WordType/Lastname 使用注明来源的替代词典；命中仅表示字典子串匹配，不能证明实际语义或用户身份。",
              "- Unicode 按码点处理、不做规范化；非 UTF-8 数据不猜测编码。",
              "- 逐条特征虽无明文，仍可关联原语料，属于敏感本地产物，不应上传公开仓库。", "",
              f"特征版本：`{metadata['feature_version']}`；词典 SHA-256：`{metadata['lexicons']['sha256']}`。", ""]
    return "\n".join(lines)


def run_extraction(source: Path, output: Path, extractor: HTPGFeatureExtractor, *,
                   max_lines: int | None = None, write_records: bool = False,
                   progress_every: int = 500_000) -> dict:
    source, output = Path(source), Path(output)
    if max_lines is not None and max_lines < 1:
        raise ValueError("max_lines must be positive")
    if progress_every < 0:
        raise ValueError("progress_every must be nonnegative")
    initial = source.stat()
    output.mkdir(parents=True, exist_ok=False)
    marker = output / "INCOMPLETE"
    marker.write_text("Incomplete run. Do not consume until manifest.json says complete.\n", encoding="utf-8")
    start = time.monotonic()
    digest = hashlib.sha256()
    audit = dict.fromkeys(("source_rows", "source_mass", "processed_bytes", "nonempty_rows", "nonempty_mass",
                          "empty_rows", "empty_mass", "decoded_rows", "decoded_mass", "invalid_utf8_rows",
                          "invalid_utf8_mass", "boundary_whitespace_rows", "control_byte_rows"), 0)
    audit.update({"complete_file": False, "counts_nonincreasing": True, "duplicate_check": "not_performed"})
    hist = {name: (Counter(), Counter()) for name in FEATURE_NAMES}
    previous_count = None
    with ExitStack() as stack:
        reader = stack.enter_context(source.open("rb"))
        records = None
        if write_records:
            handle = stack.enter_context((output / "features.jsonl.gz").open("xb"))
            records = stack.enter_context(gzip.GzipFile(filename="", mode="wb", fileobj=handle, compresslevel=1, mtime=0))
        while max_lines is None or audit["source_rows"] < max_lines:
            raw = reader.readline()
            if not raw:
                audit["complete_file"] = True
                break
            digest.update(raw)
            audit["processed_bytes"] += len(raw)
            audit["source_rows"] += 1
            count, password = parse_counted_line(raw, audit["source_rows"])
            audit["source_mass"] += count
            if previous_count is not None and count > previous_count:
                audit["counts_nonincreasing"] = False
            previous_count = count
            if not password:
                audit["empty_rows"] += 1
                audit["empty_mass"] += count
                continue
            audit["nonempty_rows"] += 1
            audit["nonempty_mass"] += count
            audit["boundary_whitespace_rows"] += int(password[:1] in b" \t\r\v\f" or password[-1:] in b" \t\r\v\f")
            audit["control_byte_rows"] += int(any(c < 32 or c == 127 for c in password))
            try:
                value = password.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                audit["invalid_utf8_rows"] += 1
                audit["invalid_utf8_mass"] += count
                features = dict.fromkeys(FEATURE_NAMES)
                status = "invalid_utf8"
            else:
                audit["decoded_rows"] += 1
                audit["decoded_mass"] += count
                features = extractor.extract(value).to_dict()
                status = "decoded"
            for name, value in features.items():
                key = "unknown" if value is None else "true" if value is True else "false" if value is False else str(value)
                hist[name][0][key] += 1
                hist[name][1][key] += count
            if records is not None:
                row = {"source_line": audit["source_rows"], "nonempty_index": audit["nonempty_rows"],
                       "count": count, "status": status, "features": features}
                records.write((json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
            if progress_every and audit["source_rows"] % progress_every == 0:
                print(json.dumps({"processed_rows": audit["source_rows"], "elapsed_seconds": round(time.monotonic() - start, 1)}), flush=True)
        if not audit["complete_file"]:
            audit["complete_file"] = reader.read(1) == b""
    final = source.stat()
    if (initial.st_size, initial.st_mtime_ns, initial.st_ino) != (final.st_size, final.st_mtime_ns, final.st_ino):
        raise RuntimeError("source changed during extraction; output is incomplete")
    if audit["nonempty_rows"] == 0:
        raise ValueError("no nonempty records; output is not evaluable")
    assert audit["source_mass"] == audit["empty_mass"] + audit["nonempty_mass"]
    assert audit["nonempty_rows"] == audit["decoded_rows"] + audit["invalid_utf8_rows"]
    assert audit["nonempty_mass"] == audit["decoded_mass"] + audit["invalid_utf8_mass"]
    summary = {"schema_version": 1, "audit": audit, "features": {}}

    def entry(key, rows, mass):
        return {"value": key, "rows": rows, "mass": mass,
                "row_fraction": rows / audit["nonempty_rows"], "mass_fraction": mass / audit["nonempty_mass"]}

    for name, (rows, mass) in hist.items():
        assert sum(rows.values()) == audit["nonempty_rows"]
        assert sum(mass.values()) == audit["nonempty_mass"]
        # Bounded summary; exact per-row features remain in the optional private file.
        keys = sorted(rows, key=lambda k: (-mass[k], k))[:30]
        if "unknown" in rows and "unknown" not in keys:
            keys.append("unknown")
        summary["features"][name] = {
            "distinct_values": len(rows), "values": [entry(k, rows[k], mass[k]) for k in keys],
            "other": entry("other", audit["nonempty_rows"] - sum(rows[k] for k in keys),
                           audit["nonempty_mass"] - sum(mass[k] for k in keys)),
        }
    metadata = extractor.metadata()
    write_json(output / "summary.json", summary)
    (output / "report.md").write_text(render_report(summary, metadata), encoding="utf-8")
    files = {p.name: {"sha256": file_sha256(p), "bytes": p.stat().st_size}
             for p in sorted(output.iterdir()) if p.is_file() and p != marker}
    root = Path(__file__).resolve().parents[1]
    manifest = {
        "status": "complete", "schema_version": 1, "python_version": platform.python_version(),
        "elapsed_seconds": round(time.monotonic() - start, 3),
        "source": {"size_bytes": initial.st_size, "processed_bytes_sha256": digest.hexdigest(),
                   "full_file_sha256": digest.hexdigest() if audit["complete_file"] else None},
        "parameters": {"max_lines": max_lines, "write_records": write_records, "line_framing": "LF only; CR preserved as password data"},
        "extractor": metadata, "files": files,
        "code_sha256": {p: file_sha256(root / p) for p in ("core/htpg_features.py", "core/counted_corpus.py", "experiments/extract_htpg_features.py")},
        "privacy": "No plaintext or per-password hash exported. Row features remain sensitive and linkable; keep local.",
        "scope": "features_only; no head/tail classification, IGR, recommendations or attack evaluation",
    }
    write_json(output / "manifest.json", manifest)
    marker.unlink()
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="must not already exist")
    parser.add_argument("--lexicons", type=Path, help="without this, WordType and Lastname are unknown")
    parser.add_argument("--max-lines", type=int)
    parser.add_argument("--write-records", action="store_true", help="save sensitive per-record features locally")
    parser.add_argument("--progress-every", type=int, default=500_000)
    args = parser.parse_args()
    extractor = HTPGFeatureExtractor.from_profile(args.lexicons) if args.lexicons else HTPGFeatureExtractor()
    summary = run_extraction(args.input, args.output, extractor, max_lines=args.max_lines,
                             write_records=args.write_records, progress_every=args.progress_every)
    print(json.dumps({"status": "complete", "audit": summary["audit"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
