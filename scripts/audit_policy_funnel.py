"""Audit the manual-inline -> complete password-policy measurement funnel.

This script is read-only unless ``--output`` is supplied. It explains where
manually confirmed inline sites are lost instead of reporting only one final
coverage percentage.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, Mapping

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from application_security.paper_registry import LOGIN_POLICIES_USENIX_2023


def normalize_host(host: str) -> str:
    value = (host or "").strip().lower().rstrip(".")
    return value[4:] if value.startswith("www.") else value


def load_manual_inline(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    sites = data.get("sites") or {}
    selected = []
    for host, item in sites.items():
        pwd = item.get("pwd_testability") or {}
        if not pwd:
            pwd = (item.get("structured") or {}).get("pwd_testability") or {}
        if pwd.get("overall") == "inline" or pwd.get("signup") == "inline":
            selected.append(normalize_host(host))
    return sorted(set(selected))


def load_signup_records(paths: Iterable[Path]) -> Dict[str, dict]:
    records: Dict[str, dict] = {}
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                item = json.loads(line)
                if item.get("entry_kind") != "signup":
                    continue
                records[normalize_host(item.get("hostname") or "")] = item
    return records


def policy_is_complete(record: Mapping) -> bool:
    policy = record.get("pwd_policy") or record.get("policy") or {}
    length = policy.get("length") if isinstance(policy, Mapping) else None
    return bool(
        record.get("method_used") == "inline"
        and isinstance(length, list)
        and len(length) == 2
        and length[0] not in (None, 0)
        and not policy.get("_inconclusive")
    )


def classify_loss(record: Mapping | None) -> tuple[str, str]:
    if not record:
        return "missing_record", "结果档案中没有该站注册侧记录"
    if record.get("error"):
        return "runtime_error", str(record.get("error"))[:200]
    if policy_is_complete(record):
        policy = record.get("pwd_policy") or record.get("policy") or {}
        return "complete_policy", "取得可信inline政策，长度={}".format(
            policy.get("length"))

    policy = record.get("pwd_policy") or record.get("policy") or {}
    note = str(record.get("note") or "")
    if record.get("method_used") == "inline" and policy.get("_inconclusive"):
        return "inline_inconclusive", str(
            policy.get("_inconclusive_reason") or "inline证据不自洽")
    flow = record.get("flow_type") or "unknown"
    stop = record.get("stop_reason") or ""
    states = record.get("states") or []
    has_password = any(
        "password" in (state.get("fields") or [])
        for state in states if isinstance(state, Mapping)
    )
    blockers = {
        blocker
        for state in states if isinstance(state, Mapping)
        for blocker in (state.get("blockers") or [])
    }
    if "未得到可信结果" in note:
        return "inline_feedback_inconclusive", note.strip()
    if flow in {"human_blocked"} or blockers & {
        "captcha", "slide", "scan", "app_confirm"
    }:
        return "human_or_access_gate", "流程受阻：{}".format(
            ",".join(sorted(blockers)) or stop)
    if not has_password and (flow in {"otp_only", "verification_then_password"}
                             or blockers & {"sms_code", "email_code",
                                            "verification_code"}):
        return "verification_before_password", "验证门槛前未取得可操作口令框"
    if has_password and flow == "no_web_signup":
        return "password_on_unconfirmed_signup_context", (
            "发现口令框，但分类器没有确认它属于注册路径；可能是登录框、"
            "入口语义错误或注册URL规则缺失")
    if not has_password and flow in {"unknown", "no_web_signup", "email_only",
                                     "sso_only"}:
        return "password_not_reached", "{} / {}".format(flow, stop)
    if has_password:
        if "页面提示政策" in note:
            return "hint_only_no_behavioral_evidence", note.strip()
        return "password_reached_inline_unsupported", (
            "已看到口令框，但负对照、反馈定位或可操作性不足")
    return "other_inconclusive", "{} / {}".format(flow, stop)


def audit(manual_hosts: Iterable[str], records: Mapping[str, dict]) -> dict:
    rows = []
    for host in sorted(set(normalize_host(item) for item in manual_hosts)):
        category, reason = classify_loss(records.get(host))
        record = records.get(host) or {}
        rows.append({
            "hostname": host,
            "category": category,
            "reason": reason,
            "flow_type": record.get("flow_type"),
            "stop_reason": record.get("stop_reason"),
            "method_used": record.get("method_used"),
            "final_url": record.get("final_url"),
        })
    counts = Counter(row["category"] for row in rows)
    total = len(rows)
    complete = counts.get("complete_policy", 0)
    return {
        "paper_ref_id": LOGIN_POLICIES_USENIX_2023.reference_id,
        "manual_inline_total": total,
        "complete_policy_total": complete,
        "complete_policy_rate": round(complete / total * 100, 1) if total else None,
        "category_counts": dict(sorted(counts.items())),
        "sites": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manual", type=Path, default=Path("misc/manual_review.json"))
    parser.add_argument(
        "--results", type=Path, action="append", required=True,
        help="测量JSONL；可重复提供，后提供的同站注册记录覆盖前者")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = audit(
        load_manual_inline(args.manual),
        load_signup_records(args.results),
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
