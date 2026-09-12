"""Generate a strict, host-level coverage report for policy measurements.

Example:
  python scripts/report_policy_coverage.py reports/archive/policy.jsonl \
      --json reports/archive/policy_coverage.json \
      --markdown reports/archive/policy_coverage.md --require-complete 1000
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Iterable, List

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from utils.policy_quality import aggregate_policy_records


STAGE_LABELS = {
    "site_reachable": "站点可访问",
    "signup_entry_found": "注册入口已确认",
    "password_field_reached": "到达注册密码框",
    "active_measurement_run": "主动策略测量已运行",
    "accepted_control_observed": "观察到接受对照",
    "rejected_control_observed": "观察到拒绝对照",
    "length_complete": "长度边界完整",
    "composition_complete": "字符组成完整",
    "permissive_complete": "允许项完整",
}


def load_jsonl(paths: Iterable[Path]) -> List[Dict]:
    records: List[Dict] = []
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        "{}:{} JSON 无效: {}".format(path, line_number, exc))
                if not isinstance(item, dict):
                    raise ValueError(
                        "{}:{} 必须是 JSON object".format(path, line_number))
                records.append(item)
    return records


def render_markdown(summary: Dict, inputs: Iterable[Path]) -> str:
    lines = [
        "# 口令策略千站目标覆盖率",
        "",
        "> 完整站点必须经过主动测量，同时具备接受/拒绝对照、长度边界、",
        "> 字符组成和允许项证据；仅分类、数据库命中或页面提示不计入。",
        "",
        "- 输入文件：{}".format("、".join(str(path) for path in inputs)),
        "- 不同注册站点：{}".format(summary["distinct_signup_sites"]),
        "- 完整测量站点：{} / 1000".format(summary["complete_sites"]),
        "- 当前批次完整率：{}%".format(summary["complete_rate_percent"]),
        "- 距离目标：{} 个".format(summary["remaining_sites"]),
        "",
        "## 测量漏斗",
        "",
        "| 阶段 | 站点数 | 占输入站点 |",
        "|---|---:|---:|",
    ]
    for name, values in summary["stages"].items():
        lines.append("| {} | {} | {}% |".format(
            STAGE_LABELS.get(name, name), values["count"],
            values["rate_percent"]))
    lines.extend([
        "",
        "## 主要未完成原因",
        "",
        "| 原因 | 站点数 |",
        "|---|---:|",
    ])
    for reason, count in summary["failure_reasons"].items():
        lines.append("| `{}` | {} |".format(reason, count))
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--json", type=Path, dest="json_output")
    parser.add_argument("--markdown", type=Path, dest="markdown_output")
    parser.add_argument("--require-complete", type=int, default=0,
                        help="少于该数量时返回退出码 2，便于 CI/验收")
    args = parser.parse_args()

    summary = aggregate_policy_records(load_jsonl(args.inputs))
    payload = json.dumps(summary, ensure_ascii=False, indent=2)
    print(payload)

    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(payload + "\n", encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(
            render_markdown(summary, args.inputs), encoding="utf-8")

    if args.require_complete and summary["complete_sites"] < args.require_complete:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
