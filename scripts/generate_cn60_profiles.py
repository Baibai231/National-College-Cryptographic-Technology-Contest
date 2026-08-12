"""从批量分类 JSONL 生成国内网站逐站认证档案 + 汇总表。

用法:
  .venv/bin/python scripts/generate_cn60_profiles.py \
      --results reports/cn60_classify_20260812.jsonl \
      --profiles-dir reports/cn60_profiles
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

FIELD_ORDER = ("phone", "email", "identifier", "password", "code")
BLOCKER_ORDER = (
    "sms_code", "email_code", "verification_code", "scan", "captcha",
    "slide", "app_confirm", "tos",
)
PROVIDERS = ("wechat", "qq", "weibo", "google", "apple", "github")

FIELD_ZH = {
    "phone": "手机号", "email": "邮箱", "identifier": "账号/邮箱",
    "password": "口令", "code": "一次性验证码",
}
METHOD_ZH = {
    "password": "口令", "phone": "手机号", "email": "邮箱",
    "identifier": "账号/邮箱", "sms": "短信验证码",
    "email_otp": "邮箱验证码", "one_time_code": "一次性验证码",
    "qr": "扫码", "sso": "第三方认证", "third_party": "第三方认证",
    "wechat": "微信", "qq": "QQ", "weibo": "微博", "google": "Google",
    "apple": "Apple", "github": "GitHub",
}
UI_ZH = {
    "standalone_page": "独立页面", "modal": "弹窗", "drawer": "抽屉",
    "multi_step_wizard": "分步页面", "inline_widget": "内嵌组件",
    "sso_iframe": "认证 iframe", "unknown": "未确认",
}
BLOCKER_ZH = {
    "sms_code": "短信验证码", "email_code": "邮箱验证码",
    "verification_code": "一次性验证码", "scan": "扫码",
    "captcha": "图片/人机验证", "slide": "滑块验证",
    "app_confirm": "App 确认", "tos": "用户协议确认",
}
ACTION_ZH = {
    "entry_click": "点击认证入口", "tab_click": "切换认证页签",
    "next": "进入下一步", "none": "未继续交互",
    "auth_mode_click": "切换登录方式", "hover_click": "hover 菜单点击",
    "signup_mode_reveal": "展开其他注册方式",
}
PASSWORD_STATE_ZH = {
    "observed_before_verification": "验证前已出现口令框",
    "observed_alongside_verification": "口令与验证码在同一可达界面出现",
    "observed_after_identifier_step": "先到账号标识步骤，后到口令步骤",
    "observed_after_verification_screen": "口令在先前验证界面之后出现",
    "not_observed_before_verification": "验证前未观察到口令；验证后情况未确认",
    "not_observed_in_safely_reachable_flow": "安全可达范围内未观察到长期口令",
    "multiple_observed_routes": "观察到多条路线，各路线口令位置见下表",
    "not_determined": "证据不足，未确认口令位置",
}
FLOW_ZH = {
    "direct_password": "直接口令",
    "identifier_then_password": "先标识后口令",
    "verification_then_password": "先验证后口令",
    "otp_only": "仅一次性验证码",
    "email_only": "仅邮箱验证码",
    "multiple_methods": "多方式并存",
    "sso_only": "仅第三方登录",
    "human_blocked": "人工阻断",
    "no_web_signup": "无网页注册",
    "unknown": "未确认",
}


def _ordered(values: Iterable[str], preferred=()) -> list:
    values = list(dict.fromkeys(value for value in values if value))
    order = {value: index for index, value in enumerate(preferred)}
    return sorted(values, key=lambda value: (order.get(value, len(order)), value))


def load_records(paths: Iterable[Path]) -> dict:
    latest = {}
    for path in paths:
        if not path.is_file():
            print(f"  [warn] 结果文件不存在: {path}")
            continue
        with path.open(encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    site_key = record.get("hostname") or record.get("site") or ""
                    site_key = site_key.rstrip("/")
                    key = (site_key, record.get("entry_kind"))
                except (json.JSONDecodeError, KeyError) as exc:
                    print(f"  [warn] {path}:{number} 记录无效: {exc}")
                    continue
                if all(v is not None for v in key):
                    latest[key] = record
    return latest


def _sets(record: dict) -> tuple:
    states = record.get("states", [])
    fields = {item for state in states for item in state.get("fields", [])}
    blockers = {item for state in states for item in state.get("blockers", [])}
    methods = {item for state in states for item in state.get("methods", [])}
    tabs = {item for state in states for item in state.get("tabs", [])}
    return states, fields, blockers, methods, tabs


def _observed_methods(fields: set, blockers: set, methods: set, tabs: set) -> list:
    observed = []
    if "password" in fields:
        observed.append("password")
    for field in ("phone", "email", "identifier"):
        if field in fields:
            observed.append(field)
    if "sms_code" in blockers or "sms_tab" in tabs or (
            "phone" in fields and "code" in fields):
        observed.append("sms")
    if "email_code" in blockers:
        observed.append("email_otp")
    elif "verification_code" in blockers or (
            "code" in fields and not {"sms_code", "email_code"} & blockers):
        observed.append("one_time_code")
    if "scan" in blockers:
        observed.append("qr")
    providers = [provider for provider in PROVIDERS if provider in methods]
    if "sso" in methods or providers:
        observed.append("third_party")
        observed.extend(providers)
    return _ordered(observed, (
        "password", "phone", "email", "identifier", "sms", "email_otp",
        "one_time_code", "qr", "third_party", *PROVIDERS,
    ))


def _verification_methods(fields: set, blockers: set, methods: set,
                          tabs: set) -> list:
    values = []
    if "sms_code" in blockers or "sms_tab" in tabs or (
            "phone" in fields and "code" in fields):
        values.append("sms")
    if "email_code" in blockers:
        values.append("email_otp")
    if "verification_code" in blockers or (
            "code" in fields and not {"sms_code", "email_code"} & blockers):
        values.append("one_time_code")
    if "scan" in blockers:
        values.append("qr")
    return _ordered(values, ("sms", "email_otp", "one_time_code", "qr"))


def _password_state(states: list, fields: set, blockers: set) -> str:
    if "password" not in fields:
        verification = bool(
            "code" in fields
            or blockers & {"sms_code", "email_code", "verification_code", "scan"}
        )
        return (
            "not_observed_before_verification" if verification
            else "not_observed_in_safely_reachable_flow"
        )
    password_index = next(
        index for index, state in enumerate(states)
        if "password" in state.get("fields", [])
    )
    password_state = states[password_index]
    same_fields = set(password_state.get("fields", []))
    same_blockers = set(password_state.get("blockers", []))
    same_verification = (
        "code" in same_fields
        or bool(same_blockers & {"sms_code", "email_code", "verification_code"})
    )
    if same_verification:
        return "observed_alongside_verification"
    earlier = states[:password_index]
    earlier_fields = {item for state in earlier for item in state.get("fields", [])}
    earlier_blockers = {item for state in earlier for item in state.get("blockers", [])}
    if "code" in earlier_fields or earlier_blockers & {
            "sms_code", "email_code", "verification_code"}:
        return "observed_after_verification_screen"
    if earlier_fields & {"phone", "email", "identifier"}:
        return "observed_after_identifier_step"
    return "observed_before_verification"


def _safe_stop_description(record: dict, password_state: str,
                           verification: list, blockers: set) -> str:
    if password_state.startswith("observed_"):
        return "已到达口令输入界面，未提交表单"
    if verification:
        names = "、".join(_method_zh(value) for value in verification)
        return f"安全测量停在{names}步骤，验证后页面未访问"
    reason = record.get("stop_reason", "")
    if reason in {"infrastructure_error", "navigation_error", "timeout"}:
        return "页面或浏览器基础设施异常，本次证据不完整"
    if reason == "access_blocked":
        return "站点拒绝当前访问，未继续交互"
    if blockers:
        return "已记录页面阻断因素，未继续交互"
    return "已走完当前安全可达范围"


def _route_summary(methods: list, password_state: str,
                   verification: list) -> str:
    parts = []
    identifiers = [value for value in methods if value in {"phone", "email", "identifier"}]
    if identifiers:
        parts.append("/".join(_method_zh(value) for value in identifiers))
    if verification:
        parts.append("/".join(_method_zh(value) for value in verification))
    if password_state.startswith("observed_"):
        parts.append("口令")
    if not parts:
        method_names = [_method_zh(value) for value in methods]
        parts.extend(method_names or ["未确认具体方式"])
    return " → ".join(dict.fromkeys(parts))


def _step_profile(state: dict) -> dict:
    return {
        "step": state.get("step"),
        "url": state.get("url", ""),
        "ui_type": state.get("ui_type", "unknown"),
        "fields": _ordered(state.get("fields", []), FIELD_ORDER),
        "methods": _ordered(state.get("methods", [])),
        "blockers": _ordered(state.get("blockers", []), BLOCKER_ORDER),
        "actions": list(state.get("actions", [])),
        "tabs": list(state.get("tabs", [])),
        "note": state.get("note", ""),
    }


def _significant_state(state: dict) -> bool:
    return bool(
        state.get("fields") or state.get("blockers") or state.get("methods")
        or state.get("tabs")
    )


def _state_signature(state: dict) -> tuple:
    return (
        tuple(sorted(state.get("fields", []))),
        tuple(sorted(state.get("blockers", []))),
        tuple(sorted(state.get("methods", []))),
        tuple(sorted(state.get("tabs", []))),
        state.get("ui_type", "unknown"),
    )


def _route_segments(states: list) -> list:
    segments = []
    current = []
    for state in states:
        if not _significant_state(state):
            continue
        if not current or _state_signature(current[-1]) != _state_signature(state):
            current.append(state)
        if "tab_click" in state.get("actions", []):
            segments.append(current)
            current = []
    if current:
        segments.append(current)
    return segments


def _route_profile(states: list, route_number: int, record: dict) -> dict:
    synthetic = {"states": states}
    _, fields, blockers, methods, tabs = _sets(synthetic)
    observed_methods = _observed_methods(fields, blockers, methods, tabs)
    verification = _verification_methods(fields, blockers, methods, tabs)
    password_state = _password_state(states, fields, blockers)
    ui_types = _ordered([
        state.get("ui_type") for state in states
        if state.get("ui_type") not in {None, "unknown"}
    ])
    return {
        "route_id": f"automatic_route_{route_number}",
        "step_numbers": [state.get("step") for state in states],
        "summary": _route_summary(observed_methods, password_state, verification),
        "fields_observed": _ordered(fields, FIELD_ORDER),
        "methods_observed": observed_methods,
        "verification_observed": verification,
        "password_state": password_state,
        "ui_types": ui_types,
        "safe_stop": _safe_stop_description(
            record, password_state, verification, blockers
        ),
    }


def build_automatic_entry(record: Optional[dict]) -> dict:
    if record is None:
        return {
            "status": "missing", "observed_route": "缺少测量记录",
            "observed_routes": [], "fields_observed": [],
            "methods_observed": [], "verification_observed": [],
            "password_state": "not_determined", "ui_types": [],
            "safe_stop": "未运行", "limitations": ["缺少记录"],
            "steps": [], "raw_result": None, "policy": {}, "error": None,
        }
    if record.get("error"):
        return {
            "status": "error", "observed_route": "本次测量异常",
            "observed_routes": [], "fields_observed": [],
            "methods_observed": [], "verification_observed": [],
            "password_state": "not_determined", "ui_types": [],
            "safe_stop": f"错误: {record.get('error', '')[:120]}",
            "limitations": ["测量异常，证据不完整"], "steps": [],
            "raw_result": {"flow_type": record.get("flow_type"),
                           "stop_reason": record.get("stop_reason"),
                           "error": record.get("error")},
            "policy": record.get("policy", {}), "error": record.get("error"),
        }

    states, fields, blockers, methods, tabs = _sets(record)
    observed_methods = _observed_methods(fields, blockers, methods, tabs)
    verification = _verification_methods(fields, blockers, methods, tabs)
    observed_routes = [
        _route_profile(segment, number, record)
        for number, segment in enumerate(_route_segments(states), 1)
    ]
    if not observed_routes and states:
        observed_routes = [_route_profile(states, 1, record)]
    route_password_states = _ordered([
        route["password_state"] for route in observed_routes
    ])
    password_state = (
        route_password_states[0] if len(route_password_states) == 1
        else "multiple_observed_routes"
    )
    ui_types = _ordered(
        [state.get("ui_type") for state in states if state.get("ui_type") not in {None, "unknown"}]
        or ([record.get("ui_type")] if record.get("ui_type") not in {None, "unknown"} else [])
    )
    limitations = []
    if any(
            route["password_state"] == "not_observed_before_verification"
            for route in observed_routes):
        limitations.append(
            "验证后情况未确认：需要完成身份验证后才能确认后续口令政策"
        )
    if record.get("confidence") in {"low", "medium"}:
        limitations.append(f"程序置信度为 {record.get('confidence')}")
    if record.get("flow_type") == "unknown":
        limitations.append("当前自动证据不足以确认完整路线")

    return {
        "status": "observed",
        "start_url": record.get("start_url", ""),
        "final_url": record.get("final_url", ""),
        "observed_route": "；备选：".join(
            route["summary"] for route in observed_routes
        ) if observed_routes else "未确认具体方式",
        "observed_routes": observed_routes,
        "fields_observed": _ordered(fields, FIELD_ORDER),
        "methods_observed": observed_methods,
        "verification_observed": verification,
        "password_state": password_state,
        "ui_types": ui_types,
        "safe_stop": "；".join(dict.fromkeys(
            route["safe_stop"] for route in observed_routes
        )) if observed_routes else _safe_stop_description(
            record, password_state, verification, blockers
        ),
        "limitations": limitations,
        "steps": [_step_profile(state) for state in states],
        "measurement": {
            "confidence": record.get("confidence", "low"),
            "measured_at": record.get("measured_at"),
            "raw_flow_type": record.get("flow_type"),
            "raw_stop_reason": record.get("stop_reason"),
        },
        "raw_result": {
            "flow_type": record.get("flow_type"),
            "stop_reason": record.get("stop_reason"),
            "primary_method": record.get("primary_method"),
        },
        "policy": record.get("policy", {}),
        "error": record.get("error"),
    }


def build_site_profile(site: dict, records: dict) -> dict:
    login = build_automatic_entry(records.get((site["id"], "login")))
    signup = build_automatic_entry(records.get((site["id"], "signup")))
    return {
        "id": site["id"],
        "name": site.get("name", site["id"]),
        "category": site.get("category", "待补充"),
        "automatic": {"login": login, "signup": signup},
    }


def _method_zh(value: str) -> str:
    if value == "app_confirm":
        return "App 确认"
    if value == "human_challenge":
        return "人机验证"
    return METHOD_ZH.get(value, value)


def _list_zh(values: list, mapping: Optional[dict] = None) -> str:
    if not values:
        return "未观察到"
    mapping = mapping or METHOD_ZH
    return "、".join(mapping.get(value, value) for value in values)


def _step_summary(step: dict) -> str:
    parts = []
    if step["fields"]:
        parts.append("字段：" + _list_zh(step["fields"], FIELD_ZH))
    if step["methods"]:
        parts.append("页面方式：" + _list_zh(step["methods"]))
    if step["blockers"]:
        parts.append("停止因素：" + _list_zh(step["blockers"], BLOCKER_ZH))
    if step["actions"]:
        parts.append("安全动作：" + _list_zh(step["actions"], ACTION_ZH))
    return "；".join(parts) or "页面已打开，尚未出现可分类控件"


def _policy_summary(policy: dict, record: dict) -> str:
    """从分类器政策摘要 + 原始结果给出政策一览。"""
    if not policy:
        ft = record.get("flow_type")
        if ft == "unknown":
            return "未确认"
        return "未生成政策摘要（仅分类）"
    auth = policy.get("authentication", {})
    parts = []
    if auth.get("password_observed"):
        parts.append("已观察到口令框")
    if auth.get("password_status") and auth["password_status"] != "not_determined":
        parts.append("口令状态：" + str(auth["password_status"]))
    if auth.get("verification_observed"):
        parts.append("存在验证环节")
    if auth.get("blocking_factors"):
        parts.append("阻断：" + _list_zh(auth["blocking_factors"], BLOCKER_ZH))
    meas = policy.get("measurement", {})
    if meas.get("status"):
        status_zh = {
            "measured": "已测量", "blocked_or_partial": "阻断/部分",
            "unknown": "未确认", "not_reachable": "不可达",
        }
        parts.append("测量状态：" + status_zh.get(meas["status"], meas["status"]))
    return "；".join(parts) or "未生成政策摘要"


def _profile_stem(site_id: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", site_id).strip(".-")
    if not stem:
        raise ValueError("站点 id 不能生成安全的档案文件名")
    return stem


def render_markdown(payload: dict) -> str:
    lines = [
        f"# {payload.get('report_title', '网站登录/注册认证档案')}",
        "",
        "> 自动观察只来自程序证据；不填写身份信息、不发送验证码、不扫码、",
        "> 不提交登录/注册、不创建账号。人工核对请用普通浏览器对照下表。",
        "",
        f"> 本次自动结果来源：{'、'.join(payload.get('automatic_result_sources', []))}",
        "",
        "## 阅读口径",
        "",
        "- “验证前未观察到口令”不等于“该网站不使用口令”；验证后页面没有访问就明确写未确认。",
        "- 单次安全路线不声称穷尽所有备选登录方式。",
        "",
    ]
    for index, site in enumerate(payload["sites"], 1):
        login = site["automatic"]["login"]
        signup = site["automatic"]["signup"]
        lines.extend([
            f"## {index}. {site['name']}",
            "",
            f"- 站点 ID：`{site['id']}`",
            "",
            "### 自动观察档案",
            "",
            "| 维度 | 登录 | 注册 |",
            "|---|---|---|",
            f"| 分类 | {FLOW_ZH.get(login['raw_result'].get('flow_type') if login['raw_result'] else '', '未测')} | {FLOW_ZH.get(signup['raw_result'].get('flow_type') if signup['raw_result'] else '', '未测')} |",
            f"| 实际到达路线 | {login['observed_route']} | {signup['observed_route']} |",
            f"| 可见字段 | {_list_zh(login['fields_observed'], FIELD_ZH)} | {_list_zh(signup['fields_observed'], FIELD_ZH)} |",
            f"| 观察到的方式 | {_list_zh(login['methods_observed'])} | {_list_zh(signup['methods_observed'])} |",
            f"| 观察到的验证 | {_list_zh(login['verification_observed'])} | {_list_zh(signup['verification_observed'])} |",
            f"| 口令位置 | {PASSWORD_STATE_ZH[login['password_state']]} | {PASSWORD_STATE_ZH[signup['password_state']]} |",
            f"| 页面形态 | {_list_zh(login['ui_types'], UI_ZH)} | {_list_zh(signup['ui_types'], UI_ZH)} |",
            f"| 政策摘要 | {_policy_summary(login['policy'], login['raw_result'] or {})} | {_policy_summary(signup['policy'], signup['raw_result'] or {})} |",
            f"| 安全测量到达处 | {login['safe_stop']} | {signup['safe_stop']} |",
            f"| 未确认项 | {'；'.join(login['limitations']) or '无额外未确认项'} | {'；'.join(signup['limitations']) or '无额外未确认项'} |",
            "",
        ])
        for label, entry in (("登录", login), ("注册", signup)):
            lines.extend([
                f"#### {label}自动观察路线",
                "",
                "| 路线 | 涉及步骤 | 实际路径 | 验证 | 口令位置 | 安全到达处 |",
                "|---|---|---|---|---|---|",
            ])
            if entry["observed_routes"]:
                for route in entry["observed_routes"]:
                    lines.append(
                        f"| `{route['route_id']}` | "
                        f"{','.join(str(value) for value in route['step_numbers'])} | "
                        f"{route['summary']} | "
                        f"{_list_zh(route['verification_observed'])} | "
                        f"{PASSWORD_STATE_ZH[route['password_state']]} | "
                        f"{route['safe_stop']} |"
                    )
            else:
                lines.append("| - | - | 缺少测量记录 | - | - | - |")
            lines.extend([
                "",
                f"#### {label}步骤证据",
                "",
                "| 步骤 | 页面形态 | 观察摘要 |",
                "|---:|---|---|",
            ])
            if entry["steps"]:
                for step in entry["steps"]:
                    lines.append(
                        f"| {step['step']} | {UI_ZH.get(step['ui_type'], step['ui_type'])} | "
                        f"{_step_summary(step)} |"
                    )
            else:
                lines.append("| - | - | 缺少测量记录 |")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_summary_table(payloads: list) -> str:
    lines = [
        "# 国内网站认证档案汇总表",
        "",
        "> 自动观察只来自程序证据。人工核对用普通浏览器对照本表。",
        "",
        "| 网站 | 登录分类 | 注册分类 | 登录路线 | 注册路线 | 注册口令位置 | 注册政策摘要 | 注册安全到达处 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for payload in sorted(payloads, key=lambda value: value["sites"][0]["id"]):
        site = payload["sites"][0]
        login = site["automatic"]["login"]
        signup = site["automatic"]["signup"]
        login_ft = (login["raw_result"] or {}).get("flow_type")
        signup_ft = (signup["raw_result"] or {}).get("flow_type")
        lines.append(
            f"| [{site['name']}]({_profile_stem(site['id'])}.md) | "
            f"{FLOW_ZH.get(login_ft, '未测')} | {FLOW_ZH.get(signup_ft, '未测')} | "
            f"{login['observed_route']} | {signup['observed_route']} | "
            f"{PASSWORD_STATE_ZH[signup['password_state']]} | "
            f"{_policy_summary(signup['policy'], signup['raw_result'] or {})} | "
            f"{signup['safe_stop']} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="生成国内网站逐站认证档案")
    parser.add_argument("--results", action="append", required=True,
                        help="JSONL 结果文件，可多个（后者覆盖前者）")
    parser.add_argument("--profiles-dir", default="reports/cn60_profiles")
    parser.add_argument("--summary", default="reports/cn60_summary.md")
    args = parser.parse_args()

    records = load_records([Path(p) for p in args.results])
    print(f"加载 {len(records)} 条测量记录")

    sites_by_id = {}
    for (site, kind), record in records.items():
        hostname = record.get("hostname") or site
        hostname = hostname.rstrip("/")
        if "//" in hostname and not hostname.startswith("http"):
            hostname = hostname
        sites_by_id.setdefault(hostname, {"id": hostname, "name": hostname,
                                          "category": "待补充"})
    if not sites_by_id:
        print("没有可用记录，退出")
        return

    output_dir = Path(args.profiles_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    payloads = []
    for site_id, site in sorted(sites_by_id.items()):
        payload = {
            "schema_version": "1.2",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "report_title": f"{site['name']} 登录/注册认证档案",
            "automatic_result_sources": [str(p) for p in args.results],
            "safety": {
                "identity_information_filled": False,
                "verification_code_sent": False,
                "captcha_bypassed": False,
                "login_or_signup_submitted": False,
                "account_created": False,
            },
            "sites": [build_site_profile(site, records)],
        }
        payloads.append(payload)
        stem = _profile_stem(site_id)
        (output_dir / f"{stem}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (output_dir / f"{stem}.md").write_text(
            render_markdown(payload), encoding="utf-8")
    (output_dir / "index.md").write_text(
        _render_summary_table(payloads), encoding="utf-8")
    summary = Path(args.summary)
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(_render_summary_table(payloads), encoding="utf-8")
    print(f"已生成 {len(payloads)} 个档案到 {output_dir}/，汇总表 {summary}")


if __name__ == "__main__":
    main()
