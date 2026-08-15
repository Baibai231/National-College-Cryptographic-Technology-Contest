"""离线重聚合方法清单：从 JSONL 记录里的 states 重新计算 methods。

用于聚合逻辑升级（v4 组合式方法）后无需重跑浏览器全量，
只更新正式 JSONL 的 methods 字段（其余字段原样保留）。
用法:
  .venv/bin/python3 scripts/reaggregate_methods.py reports/sites/sites_latest.jsonl
"""
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from signup_flow_classifier.flow_types import PageState
from signup_flow_classifier.classifier import aggregate_methods


def to_state(d):
    return PageState(
        step=d.get("step", 0), url=d.get("url", ""), ui_type=d.get("ui_type", ""),
        fields=d.get("fields") or [], actions=d.get("actions") or [],
        blockers=d.get("blockers") or [], methods=d.get("methods") or [],
        available_actions=d.get("available_actions") or [], tabs=d.get("tabs") or [],
        note=d.get("note", ""),
    )


def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1
                else "reports/sites/sites_latest.jsonl")
    lines = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()
             if l.strip()]
    changed = 0
    for record in lines:
        new_methods = [
            m.__dict__ if hasattr(m, "__dict__") else dict(m)
            for m in aggregate_methods(
                [to_state(s) for s in record.get("states") or []],
                flow_type=record.get("flow_type") or "",
            )
        ]
        if new_methods != record.get("methods"):
            record["methods"] = new_methods
            changed += 1
    with open(path, "w", encoding="utf-8") as f:
        for record in lines:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"更新 {changed}/{len(lines)} 条记录的 methods（组合式）")


if __name__ == "__main__":
    main()
