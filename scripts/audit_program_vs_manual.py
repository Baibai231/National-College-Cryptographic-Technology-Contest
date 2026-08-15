"""审计最终测量结果与人工记录，并输出逐站可读原因。

示例：
  .venv/bin/python scripts/audit_program_vs_manual.py \
      --results reports/sites/sites_latest.jsonl \
      --manual misc/manual_review.json \
      --report reports/archive/v3_manual_audit.md \
      --json reports/archive/v3_manual_audit.json
"""
import argparse
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.build_site_database import attach_manual, build_sites, load_records
from webapp.app import _manual_comparison, _methods_from_states


def audit(results, manual):
    groups = load_records([str(results)])
    sites = attach_manual(build_sites(groups), str(manual))
    rows = []
    for site in sites:
        if not site["manual"]["verified"]:
            continue
        signup = site["signup"]
        comparison = _manual_comparison(
            signup["flow_type"], site["manual"]["signup"],
            signup["route"], signup["fields"], signup["blockers"],
            verified=True, methods=_methods_from_states(signup["raw_states"]),
        )
        rows.append({
            "hostname": site["hostname"],
            "status": comparison["status"],
            "program_flow": signup["flow_type"],
            "program_route": signup["route"],
            "manual_signup": site["manual"]["signup"],
            "reason": comparison["reason"],
        })
    return rows


def markdown(rows, results):
    matched = [row for row in rows if row["status"] == "match"]
    mismatched = [row for row in rows if row["status"] == "mismatch"]
    inconclusive = [row for row in rows if row["status"].startswith("inconclusive_")]
    lines = [
        "# v3 程序与人工逐站审计", "",
        f"- 最终结果：`{results}`",
        f"- 已人工核验：{len(rows)}",
        f"- 核心路线一致：{len(matched)}",
        f"- 明确不一致：{len(mismatched)}",
        f"- 证据不足：{len(inconclusive)}", "",
        "## 不一致项", "",
        "| 网站 | 程序结论 | 程序路线 | 人工记录 | 差异原因 |",
        "|---|---|---|---|---|",
    ]
    for row in mismatched:
        values = [
            row["hostname"], row["program_flow"] or "error",
            row["program_route"] or "—", row["manual_signup"] or "—",
            row["reason"],
        ]
        lines.append("| " + " | ".join(str(value).replace("|", "\\|") for value in values) + " |")
    lines += [
        "", "## 一致项（为什么正确）", "",
        "| 网站 | 程序结论 | 判断依据 |",
        "|---|---|---|",
    ]
    for row in matched:
        values = [row["hostname"], row["program_flow"], row["reason"]]
        lines.append("| " + " | ".join(str(value).replace("|", "\\|") for value in values) + " |")
    lines += [
        "", "## 证据不足项（不计入正确率）", "",
        "| 网站 | 程序结论 | 人工记录 | 原因 |",
        "|---|---|---|---|",
    ]
    for row in inconclusive:
        values = [
            row["hostname"], row["program_flow"] or "error",
            row["manual_signup"] or "—", row["reason"],
        ]
        lines.append("| " + " | ".join(str(value).replace("|", "\\|") for value in values) + " |")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--manual", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--json", dest="json_output", type=Path, required=True)
    args = parser.parse_args()
    rows = audit(args.results, args.manual)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(markdown(rows, args.results), encoding="utf-8")
    args.json_output.write_text(
        json.dumps({"audits": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    matched = sum(row["status"] == "match" for row in rows)
    mismatched = sum(row["status"] == "mismatch" for row in rows)
    inconclusive = sum(row["status"].startswith("inconclusive_") for row in rows)
    print(
        f"审计 {len(rows)} 个已核验网站：一致 {matched}，"
        f"不一致 {mismatched}，证据不足 {inconclusive}"
    )


if __name__ == "__main__":
    main()
