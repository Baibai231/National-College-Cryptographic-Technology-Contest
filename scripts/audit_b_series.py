#!/usr/bin/env python3
"""Audit B-00..B-11 implementation and empirical acceptance evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.audit_policy_funnel import (  # noqa: E402
    audit as audit_policy_funnel,
    load_manual_inline,
    load_signup_records,
    policy_is_complete,
)
from scripts.build_site_database import attach_manual, build_sites, load_records  # noqa: E402
from scripts.compare_measurement_rounds import compare, load_round  # noqa: E402
from application_security.experiment_metrics import wilson_interval  # noqa: E402
from webapp.app import _manual_comparison, _methods_from_states  # noqa: E402


TASKS = (
    ("B-00", "统一证据模型与安全模式", ("application_security/models.py", "tests/test_application_security_models.py"), "complete", "Evidence/Claim/ModuleResult及三种扫描模式已执行"),
    ("B-01", "认证入口图谱", ("application_security/auth_graph.py", "tests/test_auth_graph.py"), "partial", "代码与登录/注册分支守卫完成；人工节点准确率和路径召回率尚未形成完整实验表"),
    ("B-02", "口令政策测量", ("utils/util_test_password.py", "scripts/audit_policy_funnel.py"), "partial", "核心探针和漏斗完成；25个人工inline站完整政策仍为7，未达到12/25探索目标"),
    ("B-03", "口令强度计准确性", ("application_security/password_meter_evaluation.py", "scripts/evaluate_password_meter.py"), "partial", "论文四维方法（WSpearman/KL/Precision/PrecisionSecurity）和站内一致性完成；真实频率/破解真值基准尚未运行"),
    ("B-04", "MFA/OTP/RBA分类", ("application_security/authentication_surface.py", "application_security/passive_protocol_probe.py"), "public_complete", "访客可见因子与MFA/RBA边界完成；强制关系仍需授权账号"),
    ("B-05", "OAuth/OIDC流程测量", ("application_security/passive_protocol_probe.py", "application_security/oidc_discovery.py"), "public_complete", "公开参数与Discovery/JWKS链完成；完整授权跳转链仍需账号"),
    ("B-06", "JWT/JWS被动分析", ("application_security/jose_validation.py", "scripts/verify_jose_evidence.py"), "public_complete", "被动结构、RSA验签和上下文谓词完成；真实令牌闭环需授权输入"),
    ("B-07", "WebAuthn/Passkey测量", ("application_security/webauthn_observer.py", "application_security/webauthn_safe_interaction.py", "B07_WEBAUTHN_SAFE_INTERACTION_20260907.md"), "public_complete", "公开样本、空虚拟认证器与GitHub两轮完成；账号生命周期仍需授权"),
    ("B-08", "账号恢复机制", ("application_security/recovery_analysis.py", "scripts/smoke_recovery_analysis.py"), "public_complete", "恢复入口与因子完成；Token与撤销联合谓词保持UNKNOWN"),
    ("B-09", "二维码登录安全", ("application_security/qr_lifecycle.py", "scripts/smoke_qr_lifecycle.py"), "public_complete", "二维码存在/刷新与零解码守卫完成；扫码确认和重放不在公开模式执行"),
    ("B-10", "表单秘密泄漏", ("application_security/leaky_forms.py", "scripts/probe_leaky_forms.py", "scripts/smoke_leaky_forms.py"), "prototype_complete", "论文方法、安全阻断和合成页完成；真实站点正样本实验尚未运行"),
    ("B-11", "数据集、回归与论文实验", ("application_security/experiment_metrics.py", "config/b_layer_experiment_cohorts.json", "scripts/audit_b_series.py"), "partial", "统一统计与分层语料完成；当前代码的两轮303站全量尚未运行"),
)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _unique_hosts_jsonl(path: Path) -> int:
    return len({
        json.loads(line).get("hostname")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    })


def _classification_baseline(results_path: Path, manual_path: Path) -> dict[str, Any]:
    """Evaluate login/signup independently against the current manual corpus.

    This intentionally uses the authoritative JSONL and manual JSON rather than
    the derived SQLite database, which may lag until the next database rebuild.
    """
    sites = attach_manual(
        build_sites(load_records([str(results_path)])), str(manual_path))
    output: dict[str, Any] = {}
    overlap = 0
    for side in ("login", "signup"):
        buckets = {
            "match": 0,
            "mismatch": 0,
            "inconclusive_program": 0,
            "inconclusive_manual": 0,
        }
        verified = 0
        for site in sites:
            if not site["manual"]["verified"]:
                continue
            verified += 1
            result = site[side]
            comparison = _manual_comparison(
                result["flow_type"], site["manual"][side],
                result["route"], result["fields"], result["blockers"],
                verified=True,
                methods=_methods_from_states(result["raw_states"]),
            )
            status = comparison["status"]
            buckets[status] = buckets.get(status, 0) + 1
        overlap = max(overlap, verified)
        evaluated = buckets["match"] + buckets["mismatch"]
        interval = wilson_interval(buckets["match"], evaluated)
        output[side] = {
            **buckets,
            "manual_result_overlap": verified,
            "evaluated": evaluated,
            "accuracy": round(buckets["match"] / evaluated, 4) if evaluated else None,
            "coverage": round(evaluated / verified, 4) if verified else None,
            "accuracy_wilson_95": [
                round(value, 4) if value is not None else None for value in interval
            ],
        }
    output["manual_result_overlap"] = overlap
    output["manual_without_authoritative_result"] = max(
        0, len(_read_json(manual_path).get("sites") or {}) - overlap)
    output["boundary"] = (
        "该表衡量现有登录/注册结论与人工记录的可判定一致率；人工数据尚未标注"
        "完整图节点和逐边真值，因此不能冒充认证图节点准确率或路径召回率。"
    )
    return output


def build_audit(root: Path = ROOT) -> dict[str, Any]:
    manual_path = root / "misc/manual_review.json"
    round_path = root / "reports/archive/headless_postfix_round1_20260904.jsonl"
    manual = _read_json(manual_path)
    inline_hosts = load_manual_inline(manual_path)
    funnel = audit_policy_funnel(inline_hosts, load_signup_records([round_path]))
    inline_interval = wilson_interval(
        funnel["complete_policy_total"], funnel["manual_inline_total"])
    classification = _classification_baseline(
        root / "reports/sites/sites_latest.jsonl", manual_path)
    public_config = _read_json(root / "config/webauthn_public_cohort.json")
    smoke_files = (
        "scripts/smoke_webauthn_observer.py",
        "scripts/smoke_webauthn_safe_interaction.py",
        "scripts/smoke_recovery_analysis.py",
        "scripts/smoke_qr_lifecycle.py",
        "scripts/smoke_leaky_forms.py",
    )
    cohort_counts = {
        "A_manual_sites": len(manual.get("sites") or {}),
        "B_manual_inline_sites": len(inline_hosts),
        "C_full_sites": _unique_hosts_jsonl(round_path),
        "D_passkey_paper_positive_sites": len(public_config.get("sites") or []),
        "E_synthetic_scenarios": sum((root / item).is_file() for item in smoke_files),
    }
    expected = {
        "A_manual_sites": 125,
        "B_manual_inline_sites": 25,
        "C_full_sites": 303,
        "D_passkey_paper_positive_sites": 8,
        "E_synthetic_scenarios": 5,
    }
    cohort_integrity = {
        key: {"expected": expected[key], "actual": value, "match": expected[key] == value}
        for key, value in cohort_counts.items()
    }

    old_round = root / "reports/archive/full303_policy_20260829.jsonl"
    current_records = load_round(round_path)
    current_policy_hosts = {
        key[0] for key, record in current_records.items() if policy_is_complete(record)
    }
    current_inline_hosts = {
        key[0] for key, record in current_records.items()
        if record.get("method_used") == "inline"
    }
    current_errors = sum(bool(record.get("error")) for record in current_records.values())
    historical_rows = compare(load_round(old_round), load_round(round_path))
    historical_same = sum(row["status"] == "same" for row in historical_rows)
    tasks = []
    for task_id, name, deliverables, status, note in TASKS:
        missing = [item for item in deliverables if not (root / item).is_file()]
        tasks.append({
            "task_id": task_id,
            "name": name,
            "implementation_files_complete": not missing,
            "missing_files": missing,
            "empirical_status": status,
            "note": note,
        })

    safe_comparison = _read_json(root / "reports/archive/webauthn_safe_github_comparison_20260907.json")
    public_comparison = _read_json(root / "reports/archive/webauthn_public_comparison_20260907.json")
    return {
        "schema_version": "b-series-audit-1.0",
        "scope": "Mac-local visitor and safe-interaction stage; authorized-account claims remain explicit UNKNOWN",
        "cohort_integrity": cohort_integrity,
        "tasks": tasks,
        "all_required_files_present": all(item["implementation_files_complete"] for item in tasks),
        "empirical_baselines": {
            "authentication_classification": classification,
            "password_inline_funnel": {
                "manual_inline_total": funnel["manual_inline_total"],
                "complete_policy_total": funnel["complete_policy_total"],
                "complete_policy_rate_percent": funnel["complete_policy_rate"],
                "complete_policy_wilson_95": [
                    round(value, 4) if value is not None else None
                    for value in inline_interval
                ],
                "category_counts": funnel["category_counts"],
            },
            "password_full_303_snapshot": {
                "records": len(current_records),
                "unique_sites": len({key[0] for key in current_records}),
                "inline_output_unique_sites": len(current_inline_hosts),
                "complete_policy_unique_sites": len(current_policy_hosts),
                "complete_policy_site_rate": round(
                    len(current_policy_hosts) / len({key[0] for key in current_records}), 4),
                "runtime_error_records": current_errors,
                "boundary": "这是2026-09-04固定档案，不是当前新增B层代码的两轮验收。",
            },
            "webauthn_public_two_round": public_comparison.get("two_round_consistency"),
            "webauthn_github_safe_two_round": {
                "configuration_agreement": safe_comparison.get("configuration_agreement"),
                "matched_features": safe_comparison.get("matched_features"),
                "comparable_features": safe_comparison.get("comparable_features"),
            },
            "historical_303_round_drift_not_current_acceptance": {
                "paired_or_union_records": len(historical_rows),
                "exact_signature_same": historical_same,
                "exact_signature_agreement": historical_same / len(historical_rows) if historical_rows else None,
                "warning": "两档案代码日期不同，只作为历史漂移基线，不冒充当前代码的两轮验收",
            },
        },
        "stage_gate": {
            "implementation_gate": "pass" if all(item["implementation_files_complete"] for item in tasks) else "fail",
            "visitor_safe_interaction_gate": "partial",
            "competition_full_empirical_gate": "not_met",
            "blocking_reasons": [
                "B-01已有登录/注册人工一致率表，但人工语料缺完整图节点和逐边标签，仍不能计算节点准确率与路径召回率",
                "B-02仅7/25人工inline站形成完整政策，探索目标12/25未达到",
                "B-03缺真实频率/破解真值数据集实验",
                "B-10缺真实网站伦理正样本实验",
                "B-11缺当前固定代码的两轮303站全量",
                "B-04至B-09的账号后安全性质需要授权测试账号，访客模式不能补造",
            ],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build_audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
