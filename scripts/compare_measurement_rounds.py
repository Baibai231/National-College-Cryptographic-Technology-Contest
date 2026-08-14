"""比较两轮全量测量，输出逐站稳定性报告。

示例：
  .venv/bin/python scripts/compare_measurement_rounds.py \
      reports/archive/v3_round1.jsonl reports/archive/v3_round2.jsonl \
      --report reports/archive/v3_round_compare.md \
      --json reports/archive/v3_round_compare.json
"""
import argparse
import json
from pathlib import Path


def load_round(path):
    records = {}
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        record = json.loads(raw)
        key = (record.get("hostname"), record.get("entry_kind"))
        if not all(key):
            continue
        records[key] = record
    return records


def observed(record, key):
    return sorted({
        item
        for state in record.get("states", [])
        for item in (state.get(key) or [])
    })


def error_category(error):
    """忽略堆栈地址等噪声，只比较可行动的失败类别。"""
    if not error:
        return None
    name = str(error).split(":", 1)[0].strip()
    lower = str(error).lower()
    if "timeout" in lower:
        return "timeout"
    return name or "error"


def signature(record):
    return {
        "flow_type": record.get("flow_type"),
        "stop_reason": record.get("stop_reason"),
        "primary_method": record.get("primary_method"),
        "fields": observed(record, "fields"),
        "blockers": observed(record, "blockers"),
        "methods": observed(record, "methods"),
        "error": error_category(record.get("error")),
    }


def compare(first, second):
    keys = sorted(set(first) | set(second))
    rows = []
    for key in keys:
        a, b = first.get(key), second.get(key)
        if a is None or b is None:
            rows.append({
                "hostname": key[0], "entry_kind": key[1],
                "status": "missing", "round1": signature(a or {}),
                "round2": signature(b or {}),
            })
            continue
        sa, sb = signature(a), signature(b)
        rows.append({
            "hostname": key[0], "entry_kind": key[1],
            "status": "same" if sa == sb else "different",
            "round1": sa, "round2": sb,
        })
    return rows


def markdown(rows, path1, path2):
    same = sum(r["status"] == "same" for r in rows)
    different = [r for r in rows if r["status"] != "same"]
    lines = [
        "# v3 两轮全量回归对比", "",
        f"- 第一轮：`{path1}`", f"- 第二轮：`{path2}`",
        f"- 总记录：{len(rows)}", f"- 完全一致：{same}",
        f"- 需要复核：{len(different)}", "",
        "| 网站 | 入口 | 状态 | 第一轮 | 第二轮 |", "|---|---|---|---|---|",
    ]
    for row in different:
        a, b = row["round1"], row["round2"]
        left = f"{a.get('flow_type')} / {','.join(a.get('fields', [])) or '-'} / {','.join(a.get('blockers', [])) or '-'}"
        right = f"{b.get('flow_type')} / {','.join(b.get('fields', [])) or '-'} / {','.join(b.get('blockers', [])) or '-'}"
        lines.append(
            f"| {row['hostname']} | {row['entry_kind']} | {row['status']} | {left} | {right} |")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("round1")
    ap.add_argument("round2")
    ap.add_argument("--report", required=True)
    ap.add_argument("--json", dest="json_output", required=True)
    args = ap.parse_args()
    first, second = load_round(args.round1), load_round(args.round2)
    rows = compare(first, second)
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(
        markdown(rows, args.round1, args.round2), encoding="utf-8")
    Path(args.json_output).write_text(
        json.dumps({"comparisons": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    same = sum(r["status"] == "same" for r in rows)
    print(f"比较 {len(rows)} 条：完全一致 {same}，需复核 {len(rows) - same}")


if __name__ == "__main__":
    main()
