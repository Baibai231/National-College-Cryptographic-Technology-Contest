"""注册流程测量平台后端 API。

功能：
- GET  /api/sites?q=关键词&limit=N   搜索站点
- GET  /api/sites/{host}             站点详情
- GET  /api/stats                    统计
- POST /api/classify {url}           输入网站主页 → 实时分类（复用测量工具）

启动:
  .venv/bin/python -m uvicorn webapp.app:app --host 0.0.0.0 --port 8000
"""
import ipaddress
import json
import os
import socket
import sqlite3
import sys
import threading
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from scripts.site_data_store import (
    coordinated_data_lock, measurement_record, upsert_manual_review,
    upsert_records,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

DB_PATH = os.environ.get(
    "SITES_DB", str(_PROJECT_ROOT / "webapp" / "sites.db"))
REPORTS_PATH = Path(os.environ.get(
    "SITES_REPORTS", str(_PROJECT_ROOT / "reports" / "sites" / "sites_latest.jsonl")))
MANUAL_PATH = Path(os.environ.get(
    "SITES_MANUAL", str(_PROJECT_ROOT / "misc" / "manual_review.json")))
DATA_LOCK_PATH = Path(os.environ.get(
    "SITES_DATA_LOCK", str(_PROJECT_ROOT / "webapp" / ".data-sync.lock")))
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="注册流程测量平台", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

try:
    _CLASSIFY_CONCURRENCY = max(1, int(os.environ.get(
        "SITES_CLASSIFY_CONCURRENCY", "2")))
except ValueError:
    _CLASSIFY_CONCURRENCY = 2
_CLASSIFY_SEMAPHORE = threading.BoundedSemaphore(_CLASSIFY_CONCURRENCY)

FLOW_ZH = {
    "direct_password": "直接口令", "identifier_then_password": "先标识后口令",
    "verification_then_password": "先验证后口令", "otp_only": "仅一次性验证码",
    "email_only": "仅邮箱验证码", "multiple_methods": "多方式并存",
    "sso_only": "仅第三方登录", "human_blocked": "人工阻断",
    "no_web_signup": "无网页注册", "unknown": "未确认", "error": "异常",
}


def _conn():
    if not os.path.isfile(DB_PATH):
        raise HTTPException(500, f"数据库不存在: {DB_PATH}（先运行 scripts/build_site_database.py）")
    # A short busy timeout makes a request wait for another small SQLite
    # transaction instead of surfacing a transient "database is locked" 500.
    return sqlite3.connect(DB_PATH, timeout=15)


def _serialized_data_transaction(func):
    """Keep a multi-file data operation consistent across processes.

    The same exact lock is held by ``server_sync.sh`` and standalone database
    rebuilds, so a web mutation/export cannot cross pull/replay/replace halfway.
    """
    @wraps(func)
    def wrapped(*args, **kwargs):
        with coordinated_data_lock(DATA_LOCK_PATH):
            return func(*args, **kwargs)
    return wrapped


def _states_to_objects(states):
    """把 JSON 化的状态列表转成 PageState 对象（展示层组合方法用）。"""
    from signup_flow_classifier.flow_types import PageState as _PS
    LIST_KEYS = ("fields", "actions", "blockers", "methods",
                 "available_actions", "tabs")
    out = []
    for s in states or []:
        if not isinstance(s, dict):
            continue
        kwargs = {k: s.get(k) for k in
                  ("step", "url", "ui_type", "note")}
        for k in LIST_KEYS:
            kwargs[k] = s.get(k) or []
        out.append(_PS(**kwargs))
    return out


def _row_to_site(row):
    (hostname, url, keywords, version, lf, lfzh, lr, lfields, lblockers,
     lfinal, lma, sf, sfzh, sr, sfields, sblockers, sfinal, sma,
     mlogin, msignup, mnote, mverified, match, details_json) = row
    details = json.loads(details_json or "{}")
    login_error = details.get("login_error") or ""
    signup_error = details.get("signup_error") or ""
    login_states = details.get("login_raw_states", [])
    signup_states = details.get("signup_raw_states", [])
    login_record = details.get("login_record") or {}
    signup_record = details.get("signup_record") or {}
    login_methods = _methods_from_states(login_states)
    signup_methods = _methods_from_states(signup_states)
    # 展示层：组合式方法清单只在这里计算（数据层 reports/misc 保持原始格式）
    from signup_flow_classifier.classifier import combo_methods
    login_display_methods = combo_methods(
        _states_to_objects(login_states), flow_type=lf or "")
    signup_display_methods = combo_methods(
        _states_to_objects(signup_states), flow_type=sf or "")
    site = {
        "hostname": hostname,
        "url": url,
        "keywords": json.loads(keywords or "[]"),
        "version": version or "?",
        "login": {
            "flow_type": lf, "flow_zh": lfzh or "未确认",
            "route": lr, "fields": lfields, "blockers": lblockers,
            "final_url": lfinal, "measured_at": lma,
            "steps": details.get("login_steps", []),
            "raw_states": login_states,
            "policy": details.get("login_policy", {}),
            "stop_reason": login_record.get("stop_reason"),
            "confidence": login_record.get("confidence"),
            "primary_method": login_record.get("primary_method"),
            "evidence": login_record.get("evidence", []),
            "error": login_error or login_record.get("error"),
            "methods": [m.__dict__ for m in login_display_methods],
            "program_reason": _program_reason(
                lf, lr, lfields, lblockers, login_error, login_methods),
        },
        "signup": {
            "flow_type": sf, "flow_zh": sfzh or "未确认",
            "route": sr, "fields": sfields, "blockers": sblockers,
            "final_url": sfinal, "measured_at": sma,
            "steps": details.get("signup_steps", []),
            "raw_states": signup_states,
            "policy": details.get("signup_policy", {}),
            "stop_reason": signup_record.get("stop_reason"),
            "confidence": signup_record.get("confidence"),
            "primary_method": signup_record.get("primary_method"),
            "evidence": signup_record.get("evidence", []),
            "error": signup_error or signup_record.get("error"),
            "methods": [m.__dict__ for m in signup_display_methods],
            "program_reason": _program_reason(
                sf, sr, sfields, sblockers, signup_error, signup_methods),
        },
        "manual": {
            "login": mlogin, "signup": msignup,
            "note": mnote, "verified": bool(mverified),
            "structured": details.get("manual_structured", {}),
        },
        "match_status": match,
        # 注册侧程序vs人工匹配：match/mismatch/pending（供筛选）
    }
    login_comparison = _manual_comparison(
        lf, mlogin or "", lr or "", lfields or "", lblockers or "",
        verified=bool(mverified), methods=login_methods,
        structured=details.get("manual_structured", {}).get("login"),
        method_results=[m.__dict__ for m in login_display_methods],
    )
    comparison = _manual_comparison(
        sf, msignup or "", sr or "", sfields or "", sblockers or "",
        verified=bool(mverified), methods=signup_methods,
        structured=details.get("manual_structured", {}).get("signup"),
        method_results=[m.__dict__ for m in signup_display_methods],
    )
    site["login_match"] = login_comparison["status"]
    site["login_comparison"] = login_comparison
    site["signup_match"] = comparison["status"]
    site["signup_comparison"] = comparison
    site["comparison"] = comparison
    statuses = {login_comparison["status"], comparison["status"]}
    if "mismatch" in statuses:
        site["comparison_status"] = "mismatch"
    elif statuses == {"match"}:
        site["comparison_status"] = "match"
    elif "pending" in statuses:
        site["comparison_status"] = "pending"
    else:
        site["comparison_status"] = "inconclusive"
    return site


@app.get("/api/sites")
def search_sites(q: str = Query("", max_length=100),
                 limit: int = Query(200, ge=1, le=1000)):
    conn = _conn()
    try:
        cur = conn.cursor()
        if q:
            like = f"%{q}%"
            cur.execute(
                "SELECT * FROM sites WHERE hostname LIKE ? OR url LIKE ? "
                "OR keywords LIKE ? OR login_route LIKE ? OR signup_route LIKE ? "
                "ORDER BY hostname LIMIT ?",
                (like, like, like, like, like, limit),
            )
        else:
            cur.execute("SELECT * FROM sites ORDER BY hostname LIMIT ?", (limit,))
        rows = cur.fetchall()
    finally:
        conn.close()
    return {"total": len(rows), "sites": [_row_to_site(r) for r in rows]}


@app.get("/api/sites/{host}")
def site_detail(host: str):
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM sites WHERE hostname = ?", (host,))
        row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(404, f"未找到站点: {host}")
    return _row_to_site(row)


@app.get("/api/sites/{host}/history")
def site_history(host: str):
    """该站各程序版本的历史测量结果（不含当前最新，当前在 sites 表）。"""
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT entry_kind, version, flow_type, stop_reason, "
            "primary_method, route, measured_at, details_json "
            "FROM site_history WHERE hostname = ? "
            "ORDER BY version DESC, measured_at DESC", (host,))
        rows = cur.fetchall()
    finally:
        conn.close()
    return {"total": len(rows), "history": [
        {"entry_kind": r[0], "version": r[1], "flow_type": r[2],
         "stop_reason": r[3], "primary_method": r[4], "route": r[5],
         "measured_at": r[6],
         "details": json.loads(r[7] or "{}")}
        for r in rows
    ]}


class AddSiteRequest(BaseModel):
    """现场分类结果 → 写入数据库。"""
    hostname: str = Field(max_length=253)
    url: str = Field("", max_length=2048)
    version: Literal["v3", "v4"] = "v4"
    login: dict = Field(default_factory=dict)
    signup: dict = Field(default_factory=dict)
    admin_token: str = ""


_FIELD_ZH = {
    "phone": "手机号", "email": "邮箱", "identifier": "账号/邮箱",
    "password": "口令", "code": "一次性验证码",
}
_BLOCKER_ZH = {
    "sms_code": "短信验证码", "email_code": "邮箱验证码",
    "verification_code": "一次性验证码", "scan": "扫码",
    "captcha": "图片/人机验证", "slide": "滑块验证",
    "app_confirm": "App 确认", "tos": "用户协议确认",
}


def _extract_states(states, key):
    """从 raw_states 提取字段/阻断：英文码→中文，转中文串（供表格显示）。"""
    if not states:
        return ""
    seen = []
    for st in states:
        items = st.get(key) or []
        if isinstance(items, str):
            items = [items]
        for it in items:
            zh = (_FIELD_ZH if key == "fields" else _BLOCKER_ZH).get(it, it)
            if zh not in seen:
                seen.append(zh)
    return "、".join(seen)


@app.post("/api/sites")
@_serialized_data_transaction
def add_site(req: AddSiteRequest):
    """管理员把现场分类结果写入数据库（新增或更新站点）。

    需要 SITES_ADMIN_TOKEN 匹配。只写入程序结果，人工核验仍走待审核流程。
    """
    expected = os.environ.get("SITES_ADMIN_TOKEN", "")
    if not expected:
        raise HTTPException(403, "服务器未设置 SITES_ADMIN_TOKEN，无法写入")
    if req.admin_token != expected:
        raise HTTPException(403, "管理员口令错误")
    host = req.hostname.strip()
    if not host:
        raise HTTPException(400, "hostname 不能为空")

    login = req.login or {}
    signup = req.signup or {}
    if not login and not signup:
        raise HTTPException(400, "至少需要一侧登录或注册结果")
    now = datetime.now(timezone.utc).isoformat()
    # 关键词：hostname + 主域名（zhihu.com → zhihu），便于部分输入搜索
    host_main = host.replace("www.", "").split(".")[0] if "." in host else host
    keywords = json.dumps([host, host_main, host.replace("www.", "")],
                          ensure_ascii=False)
    site_url = req.url or "https://" + host
    records = []
    if login:
        records.append(measurement_record(
            host, site_url, req.version, "login", login, now))
    if signup:
        records.append(measurement_record(
            host, site_url, req.version, "signup", signup, now))

    # reports 是权威数据源。先原子落盘，再更新可重建的 SQLite 服务索引。
    try:
        report_result = upsert_records(REPORTS_PATH, records)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(500, f"写入 reports 失败，数据库未改动: {exc}") from exc

    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT details_json FROM sites WHERE hostname = ?", (host,))
        old_row = cur.fetchone()
        exists = old_row is not None
        details_obj = json.loads(old_row[0] or "{}") if old_row else {}
        for record in records:
            kind = record["entry_kind"]
            states = record.get("states") or []
            details_obj[f"{kind}_steps"] = states
            details_obj[f"{kind}_raw_states"] = states
            details_obj[f"{kind}_policy"] = record.get("policy") or {}
            details_obj[f"{kind}_error"] = record.get("error")
            details_obj[f"{kind}_record"] = record
        details = json.dumps(details_obj, ensure_ascii=False)
        if exists:
            cur.execute(
                "UPDATE sites SET url = ?, version = ?, keywords = ?, details_json = ? "
                "WHERE hostname = ?",
                (site_url, req.version, keywords, details, host))
            for record in records:
                kind = record["entry_kind"]
                states = record.get("states") or []
                fields = _extract_states(states, "fields")
                blockers = _extract_states(states, "blockers")
                cur.execute(f"""
                    UPDATE sites SET {kind}_flow = ?, {kind}_flow_zh = ?,
                        {kind}_route = ?, {kind}_fields = ?, {kind}_blockers = ?,
                        {kind}_final_url = ?, {kind}_measured_at = ?
                    WHERE hostname = ?
                """, (
                    record.get("flow_type"),
                    login.get("flow_zh") if kind == "login" else signup.get("flow_zh"),
                    (login.get("route") if kind == "login" else signup.get("route")) or "未确认",
                    fields, blockers, record.get("final_url"),
                    record.get("measured_at"), host,
                ))
        else:
            by_kind = {record["entry_kind"]: record for record in records}
            def values(kind):
                record = by_kind.get(kind, {})
                entry = login if kind == "login" else signup
                states = record.get("states") or []
                return (
                    record.get("flow_type"), entry.get("flow_zh"),
                    entry.get("route") or ("未确认" if record else None),
                    _extract_states(states, "fields"),
                    _extract_states(states, "blockers"), record.get("final_url"),
                    record.get("measured_at"),
                )
            login_values = values("login")
            signup_values = values("signup")
            cur.execute("""
                INSERT INTO sites (hostname, url, keywords, version,
                    login_flow, login_flow_zh, login_route, login_fields,
                    login_blockers, login_final_url,
                    login_measured_at, signup_flow, signup_flow_zh,
                    signup_route, signup_fields, signup_blockers,
                    signup_final_url, signup_measured_at,
                    manual_login, manual_signup, manual_note,
                    manual_verified, match_status, details_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                host, site_url, keywords, req.version,
                *login_values, *signup_values,
                "", "", "", 0, "pending_manual", details,
            ))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True,
            "message": ("更新" if exists else "新增") +
                       f" {host} ({req.version})，已同步到 reports",
            "reports": report_result}


@app.get("/api/export")
@_serialized_data_transaction
def export_data(admin_token: str = Header("", alias="X-Admin-Token")):
    """导出全量站点数据（供 Mac 拉回合并，保持数据一致）。

    返回：
      records: 与 run_measurement 输出同格式的测量记录列表
      manual:  manual_review.json 内容
    """
    expected = os.environ.get("SITES_ADMIN_TOKEN", "")
    if not expected:
        raise HTTPException(403, "服务器未设置 SITES_ADMIN_TOKEN")
    if admin_token != expected:
        raise HTTPException(403, "管理员口令错误")

    try:
        records = [
            json.loads(line) for line in
            REPORTS_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        manual = (json.loads(MANUAL_PATH.read_text(encoding="utf-8"))
                  if MANUAL_PATH.is_file() else {"sites": {}})
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            500, f"权威数据文件读取失败，导出已中止: {exc}") from exc
    return {"records": records, "manual": manual}


@app.get("/api/stats")
def stats():
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM sites")
        total = cur.fetchone()[0]
        cur.execute("SELECT signup_flow, COUNT(*) FROM sites GROUP BY signup_flow")
        signup_dist = {r[0] or "error": r[1] for r in cur.fetchall()}
        cur.execute("SELECT login_flow, COUNT(*) FROM sites GROUP BY login_flow")
        login_dist = {r[0] or "error": r[1] for r in cur.fetchall()}
        cur.execute("SELECT COUNT(*) FROM sites WHERE manual_verified = 1")
        verified = cur.fetchone()[0]
        # 登录、注册分别统计；正确率只使用可判定样本，另报覆盖率，
        # 避免把 unknown 或人工描述不足硬算成错误/正确。
        cur.execute("SELECT * FROM sites WHERE manual_verified = 1")
        side_items = {"login": [], "signup": []}
        for row in cur.fetchall():
            site = _row_to_site(row)
            for side in ("login", "signup"):
                comparison = site[f"{side}_comparison"]
                side_items[side].append({
                    "hostname": site["hostname"],
                    "program": site[side]["flow_type"],
                    "manual": (site["manual"][side] or "")[:100],
                    "status": comparison["status"],
                    "reason": comparison["reason"],
                })

        def summarize(items):
            buckets = {
                status: [item for item in items if item["status"] == status]
                for status in ("match", "mismatch", "inconclusive_program",
                               "inconclusive_manual")
            }
            evaluated = len(buckets["match"]) + len(buckets["mismatch"])
            return {
                "match": len(buckets["match"]),
                "mismatch": len(buckets["mismatch"]),
                "evaluated": evaluated,
                "verified": verified,
                "rate": round(len(buckets["match"]) / evaluated * 100, 1)
                        if evaluated else 0.0,
                "coverage_rate": round(evaluated / verified * 100, 1)
                                 if verified else 0.0,
                "inconclusive_program": len(buckets["inconclusive_program"]),
                "inconclusive_manual": len(buckets["inconclusive_manual"]),
                "correct_sites": buckets["match"],
                "wrong_sites": buckets["mismatch"],
                "inconclusive_sites": (
                    buckets["inconclusive_program"] + buckets["inconclusive_manual"]),
            }

        login_accuracy = summarize(side_items["login"])
        signup_accuracy = summarize(side_items["signup"])
        cur.execute("SELECT COUNT(*) FROM reviews_pending")
        pending = cur.fetchone()[0]
    finally:
        conn.close()
    return {
        "total_sites": total,
        "manual_verified": verified,
        "pending_reviews": pending,
        # 兼容旧网页/API 调用：program_accuracy 仍代表注册侧，但 total
        # 改为可判定样本数；新调用应读取 accuracy.login/signup。
        "program_accuracy": {
            **signup_accuracy, "total": signup_accuracy["evaluated"]},
        "accuracy": {"login": login_accuracy, "signup": signup_accuracy},
        "signup_distribution": signup_dist,
        "login_distribution": login_dist,
        "flow_zh": FLOW_ZH,
    }


_METHOD_ZH = {
    "phone": "手机号", "email": "邮箱", "identifier": "账号/邮箱",
    "qr": "扫码", "sso": "第三方登录", "wechat": "微信", "qq": "QQ",
    "weibo": "微博", "google": "Google", "apple": "Apple",
    "github": "GitHub", "gitee": "Gitee", "microsoft": "Microsoft",
    "baidu": "百度", "dingtalk": "钉钉", "douyin": "抖音",
    "xiaohongshu": "小红书", "alipay": "支付宝", "taobao": "淘宝",
    "xiaomi": "小米", "huawei": "华为", "solana": "Solana",
    "auto_signup": "登录即注册",
}


def _methods_from_states(states):
    seen = []
    for state in states or []:
        for method in state.get("methods") or []:
            name = _METHOD_ZH.get(method, method)
            if name not in seen:
                seen.append(name)
    return "、".join(seen)


def _program_reason(flow_type, route="", fields="", blockers="", error="", methods=""):
    """把程序证据转换为可直接展示的判断依据。"""
    route = route if route and route != "—" else "未记录到可辨认路线"
    blocker_text = blockers if blockers and blockers != "—" else "未记录到人工门槛"
    method_text = methods or "未记录到具体方式"
    reasons = {
        "direct_password": f"安全可达页面已出现口令框；观测路线：{route}。",
        "identifier_then_password": f"先看到账号标识，安全点击下一步后出现口令框；观测路线：{route}。",
        "verification_then_password": f"状态序列先出现验证码步骤，之后出现口令框；观测路线：{route}。",
        "otp_only": f"安全可达范围只看到一次性验证码，未看到长期口令框；观测路线：{route}。",
        "email_only": f"安全可达范围只确认邮箱路线，未看到长期口令框；观测路线：{route}。",
        "sso_only": f"只确认到第三方登录入口（{method_text}），没有发现站点自有账号字段；观测路线：{route}。",
        "multiple_methods": f"页面同时提供多种可见认证方式（{method_text}）；观测路线：{route}。",
        "human_blocked": f"程序遇到{blocker_text}，遵守安全边界停止；停止前路线：{route}。",
        "no_web_signup": "没有发现可用的网页注册入口。",
        "unknown": f"在安全点击范围内没有取得足够证据，暂不猜测；观测路线：{route}。",
        "error": (
            "目标页面渲染超时，程序没有形成分类结论。"
            if "timeout" in error.lower()
            else "测量发生异常，程序没有形成可靠分类结论。"
        ),
    }
    return reasons.get(flow_type, f"程序根据可见字段和状态序列判断；观测路线：{route}。")


def _manual_traits(manual_text, structured=None):
    t = (manual_text or "").lower().replace(" ", "")
    negative_pwd = any(x in t for x in (
        "无密码", "没有密码", "无需密码", "不需要密码", "无口令", "无需口令",
        "不需要口令", "仅验证码"))
    positive_source = t
    for phrase in ("无密码", "没有密码", "无需密码", "不需要密码", "无口令",
                   "无需口令", "不需要口令"):
        positive_source = positive_source.replace(phrase, "")
    has_password = any(x in positive_source for x in (
        "密码", "口令", "password"))
    has_otp = any(x in t for x in ("验证码", "短信", "动态码", "otp", "手机验证"))
    has_scan = any(x in t for x in ("扫码", "二维码", "扫一扫", "app确认"))
    has_captcha = any(x in t for x in (
        "人机", "滑块", "captcha", "验证块", "图形验证码", "安全验证"))
    has_tos = any(x in t for x in ("协议", "条款", "隐私", "同意"))
    has_human_gate = has_otp or has_scan or has_captcha or any(
        x in t for x in (
            "需验证", "验证后", "手机验证"))
    has_sso = any(x in t for x in (
        "第三方", "sso", "oauth", "微信", "qq", "微博", "gitee", "google",
        "solana", "支付宝", "淘宝", "华为", "小米", "小红书", "企业微信"))
    no_web = any(x in t for x in (
        "无登录注册", "无注册界面", "无独立注册", "无网页注册", "无法登录",
        "无登录", "无注册选项", "没有注册", "仅登录界面"))
    traits = {
        "password": has_password, "negative_password": negative_pwd,
        "otp": has_otp, "scan": has_scan, "human_gate": has_human_gate,
        "captcha": has_captcha, "tos": has_tos,
        "sso": has_sso, "no_web": no_web,
    }
    provided = set()
    structured = structured if isinstance(structured, dict) else {}
    for key in ("password", "otp", "scan", "captcha", "tos", "sso", "no_web"):
        if isinstance(structured.get(key), bool):
            traits[key] = structured[key]
            provided.add(key)
    if structured.get("password") is False:
        traits["negative_password"] = True
    elif structured.get("password") is True:
        traits["negative_password"] = False
    # 旧数据也记录“文本实际明确了什么”，供证据不足状态判断。
    text_flags = {
        "password": has_password or negative_pwd, "otp": has_otp,
        "scan": has_scan, "captcha": has_captcha, "tos": has_tos,
        "sso": has_sso, "no_web": no_web,
    }
    provided.update(key for key, value in text_flags.items() if value)
    traits["_provided"] = sorted(provided)
    return traits


def _method_set_note(program_methods, structured):
    """程序观察到的方法 vs 人工结构化勾选的方法，生成对照说明。"""
    prog = [m.get("name_zh") or m.get("method") for m in (program_methods or [])]
    man = set()
    if isinstance(structured, dict):
        for key, zh in (("password", "口令"), ("otp", "验证码"), ("scan", "扫码"),
                        ("captcha", "人机"), ("tos", "协议"), ("sso", "第三方"),
                        ("no_web", "无入口")):
            if structured.get(key) is True:
                man.add(zh)
    if not prog and not man:
        return ""
    parts = []
    if prog:
        parts.append("程序观察到方法：" + ("、".join(prog)))
    if man:
        parts.append("人工勾选方法：" + "、".join(sorted(man)))
    elif isinstance(structured, dict) and structured:
        parts.append("人工结构化均未勾选")
    return "；".join(parts) + "。"


def _manual_comparison(flow_type, manual_text, route="", fields="", blockers="",
                       verified=True, methods="", structured=None,
                       method_results=None):
    """Return match/mismatch/inconclusive status with auditable reasoning."""
    if not verified:
        return {"status": "pending", "reason": "尚无人工复核，当前只展示程序判断依据。"}
    traits = _manual_traits(manual_text, structured)
    provided = set(traits.pop("_provided", []))
    program_reason = _program_reason(flow_type, route, fields, blockers, methods=methods)

    def result(status, explanation):
        manual_reason = manual_text or "结构化选项（未填写补充文字）"
        prefix = {
            "match": "",
            "mismatch": "",
            "inconclusive_program": "程序证据不足：",
            "inconclusive_manual": "人工证据不足：",
        }[status]
        reason = f"{prefix}{explanation} 程序依据：{program_reason} 人工复核为“{manual_reason}”。"
        note = _method_set_note(method_results, structured)
        if note:
            reason += f" {note}"
        return {
            "status": status,
            "reason": reason,
        }

    if flow_type in (None, "", "unknown", "error"):
        return result("inconclusive_program", "程序尚未形成可核验的明确分类，不能计为正确或错误。")

    if flow_type in ("direct_password", "identifier_then_password", "verification_then_password"):
        if traits["password"] and not traits["negative_password"]:
            return result("match", "程序和人工都确认安全可达口令路线。")
        if "password" in provided:
            return result("mismatch", "程序报告可达口令框，但人工明确记录为无口令。")
        return result("inconclusive_manual", "人工记录没有说明是否存在口令，暂不能比较。")
    elif flow_type in ("otp_only", "email_only"):
        if traits["password"] and not traits["negative_password"]:
            return result("mismatch", "程序报告只见一次性验证码，但人工确认还需长期口令。")
        if traits["otp"]:
            return result("match", "程序和人工都确认一次性验证码路线，且未确认长期口令。")
        if traits["scan"] or traits["sso"]:
            return result("mismatch", "程序报告一次性验证码路线，但人工确认的是扫码或第三方认证路线。")
        return result("inconclusive_manual", "人工记录没有明确验证码或口令状态。")
    elif flow_type == "sso_only":
        if traits["password"] or traits["otp"]:
            return result("mismatch", "程序报告仅第三方登录，但人工观察到站点自有验证码或口令路线。")
        if traits["sso"]:
            return result("match", "程序和人工都只确认第三方认证路线。")
        return result("inconclusive_manual", "人工记录没有明确是否存在第三方认证。")
    elif flow_type == "human_blocked":
        blocker_lower = (blockers or "").lower()
        program_gates = {
            "otp": any(x in blocker_lower for x in ("短信", "邮箱验证码", "一次性验证码", "sms", "otp")),
            "scan": any(x in blocker_lower for x in ("扫码", "scan", "app 确认")),
            "captcha": any(x in blocker_lower for x in ("人机", "图片", "滑块", "captcha", "slide")),
            "tos": any(x in blocker_lower for x in ("协议", "条款", "tos")),
        }
        program_specific = {key for key, value in program_gates.items() if value}
        manual_specific = {key for key in ("otp", "scan", "captcha", "tos") if traits[key]}
        if not program_specific:
            return result("inconclusive_program", "程序只报告被阻断，但没有记录可比较的具体门槛。")
        if not manual_specific:
            return result("inconclusive_manual", "人工只写了笼统的“需验证”或未说明具体门槛。")
        if program_specific & manual_specific:
            return result("match", "程序停止的具体门槛与人工观察一致。")
        return result("mismatch", "程序停止的具体门槛与人工观察到的门槛不同。")
    elif flow_type == "no_web_signup":
        if traits["no_web"]:
            return result("match", "程序和人工都未发现网页注册入口。")
        if provided & {"password", "otp", "scan", "sso"}:
            return result("mismatch", "程序报告无网页入口，但人工已观察到明确认证路线。")
        return result("inconclusive_manual", "人工记录未明确网页入口是否存在。")
    elif flow_type == "multiple_methods":
        count = sum(bool(traits[x]) for x in ("password", "otp", "sso", "scan"))
        if count >= 2:
            return result("match", "程序和人工都确认至少两种认证方式并存。")
        if provided:
            return result("mismatch", "程序报告多方式并存，但人工只确认一种方式。")
        return result("inconclusive_manual", "人工描述不足以确认认证方式数量。")
    return result("inconclusive_program", "程序分类缺少对应的人工比较规则。")


def _manual_match(flow_type, manual_text):
    """兼容旧调用：使用新的结构化人工对照规则。"""
    return _manual_comparison(flow_type, manual_text)["status"] == "match"


class ClassifyRequest(BaseModel):
    url: str = Field(max_length=2048)
    entry_kind: Literal["signup", "login"] = "signup"


class ReviewRequest(BaseModel):
    hostname: str = Field(max_length=253)
    login: str = Field("", max_length=4000)
    signup: str = Field("", max_length=4000)
    note: str = Field("", max_length=8000)
    submitter: str = Field("", max_length=200)
    review_type: Literal["manual", "feedback"] = "manual"
    structured: dict = Field(default_factory=dict)


@app.get("/api/reviews/pending")
def pending_reviews(hostname: str = Query("", max_length=253),
                    admin_token: str = Header("", alias="X-Admin-Token")):
    """待审核提交；匿名只能查单站数量，完整内容仅管理员可读。"""
    expected = os.environ.get("SITES_ADMIN_TOKEN", "")
    is_admin = bool(expected and admin_token == expected)
    if not hostname and not is_admin:
        raise HTTPException(403, "完整待审核列表仅管理员可查看")
    conn = _conn()
    try:
        cur = conn.cursor()
        if hostname:
            cur.execute(
                "SELECT id, hostname, login, signup, note, submitter, review_type, submitted_at, structured_json "
                "FROM reviews_pending WHERE hostname = ? ORDER BY id DESC",
                (hostname,))
        else:
            cur.execute(
                "SELECT id, hostname, login, signup, note, submitter, review_type, submitted_at, structured_json "
                "FROM reviews_pending ORDER BY id DESC")
        rows = cur.fetchall()
    finally:
        conn.close()
    if not is_admin:
        return {"total": len(rows), "reviews": []}
    return {"total": len(rows), "reviews": [
        {"id": r[0], "hostname": r[1], "login": r[2], "signup": r[3],
         "note": r[4], "submitter": r[5], "review_type": r[6] or "manual",
         "submitted_at": r[7], "structured": json.loads(r[8] or "{}")}
        for r in rows
    ]}


@app.post("/api/reviews")
@_serialized_data_transaction
def submit_review(req: ReviewRequest):
    """组员提交人工观察（进入待审核表，管理员核验后合并进 final）。"""
    host = req.hostname.strip()
    if not host:
        raise HTTPException(400, "hostname 不能为空")
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO reviews_pending (hostname, login, signup, note, "
            "submitter, review_type, submitted_at, structured_json) VALUES (?,?,?,?,?,?,?,?)",
            (host, req.login.strip(), req.signup.strip(), req.note.strip(),
             req.submitter.strip(),
             req.review_type if req.review_type in ("manual", "feedback") else "manual",
             datetime.now(timezone.utc).isoformat(),
             json.dumps(req.structured or {}, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()
    kind = "识别反馈" if req.review_type == "feedback" else "人工观察"
    return {"ok": True, "message": f"已提交 {host} 的{kind}，等待管理员核验"}


@app.post("/api/reviews/{review_id}/approve")
@_serialized_data_transaction
def approve_review(review_id: int,
                   admin_token: str = Header("", alias="X-Admin-Token")):
    """管理员核验通过：合并人工观察进 sites 表 + manual_review.json。

    需要 SITES_ADMIN_TOKEN 环境变量（服务器部署时设置）匹配才允许。
    """
    expected = os.environ.get("SITES_ADMIN_TOKEN", "")
    if not expected:
        raise HTTPException(403, "服务器未设置 SITES_ADMIN_TOKEN，无法审核")
    if admin_token != expected:
        raise HTTPException(403, "管理员口令错误")
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, hostname, login, signup, note, submitter, review_type, submitted_at, structured_json "
            "FROM reviews_pending WHERE id = ?", (review_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, f"待审核记录不存在: {review_id}")
        _rid, host, login, signup, note, submitter, rtype, ts, structured_json = row
        structured = json.loads(structured_json or "{}")
        if rtype == "feedback":
            # 识别反馈：不自动合并人工核验，只删除（管理员已人工判断处理）
            cur.execute("DELETE FROM reviews_pending WHERE id = ?", (review_id,))
            conn.commit()
            return {"ok": True, "message": f"已处理 {host} 的识别反馈（未写入人工核验）"}
        # 1) 更新 sites 表（合并人工结果）
        cur.execute("SELECT details_json FROM sites WHERE hostname = ?", (host,))
        site_row = cur.fetchone()
        if not site_row:
            raise HTTPException(404, f"站点不存在，无法合并人工核验: {host}")
        details = json.loads(site_row[0] or "{}")
        previous_structured = details.get("manual_structured") or {}
        for side in ("login", "signup"):
            if isinstance(structured.get(side), dict) and structured[side]:
                previous_structured[side] = structured[side]
        details["manual_structured"] = previous_structured
        # JSON 是人工核验权威数据。先原子写入；失败则不提交 SQLite 事务。
        try:
            upsert_manual_review(
                MANUAL_PATH, host, login=login, signup=signup, note=note,
                structured=previous_structured,
                reviewed_from=f"web@{submitter or 'admin'}@{ts}",
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(
                500, f"写入人工核验文件失败，审核未生效: {exc}") from exc
        cur.execute("""
            UPDATE sites SET manual_login = CASE WHEN ? != '' THEN ? ELSE manual_login END,
                            manual_signup = CASE WHEN ? != '' THEN ? ELSE manual_signup END,
                            manual_note = CASE WHEN ? != '' THEN ? ELSE manual_note END,
                            manual_verified = 1,
                            match_status = 'manual_verified', details_json = ?
            WHERE hostname = ?
        """, (login, login, signup, signup, note, note,
              json.dumps(details, ensure_ascii=False), host))
        # 2) 删除待审核记录
        cur.execute("DELETE FROM reviews_pending WHERE id = ?", (review_id,))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "message": f"已通过 {host} 的人工观察"}


@app.delete("/api/reviews/{review_id}")
@_serialized_data_transaction
def delete_review(review_id: int,
                  admin_token: str = Header("", alias="X-Admin-Token")):
    """管理员核验后删除待审核记录（拒绝该提交）。"""
    expected = os.environ.get("SITES_ADMIN_TOKEN", "")
    if not expected:
        raise HTTPException(403, "服务器未设置 SITES_ADMIN_TOKEN，无法审核")
    if admin_token != expected:
        raise HTTPException(403, "管理员口令错误")
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM reviews_pending WHERE id = ?", (review_id,))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


def _validated_classify_url(raw_url: str, *, resolve: bool) -> tuple[str, str]:
    """Accept only public HTTP(S) targets for the public browser endpoint."""
    url = raw_url.strip()
    if not url:
        raise HTTPException(400, "url 不能为空")
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(400, "只支持有效的 http/https 网站地址")
    if parsed.username or parsed.password:
        raise HTTPException(400, "网站地址不能包含用户名或口令")
    try:
        port = parsed.port
    except ValueError as exc:
        raise HTTPException(400, "网站端口格式无效") from exc
    if port not in (None, 80, 443):
        raise HTTPException(400, "实时分类只允许标准网页端口 80/443")

    host = parsed.hostname.rstrip(".").lower()

    def require_global(address: str):
        address = address.split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return False
        if not ip.is_global:
            raise HTTPException(400, "实时分类不允许访问本机、内网或保留地址")
        return True

    if require_global(host):
        return url, host
    if host in ("localhost", "localhost.localdomain") or host.endswith(".local"):
        raise HTTPException(400, "实时分类不允许访问本机或内网主机")
    if resolve:
        try:
            addresses = {
                item[4][0] for item in socket.getaddrinfo(
                    host, port or (443 if parsed.scheme == "https" else 80),
                    type=socket.SOCK_STREAM)
            }
        except socket.gaierror as exc:
            raise HTTPException(400, "网站域名当前无法解析") from exc
        if not addresses:
            raise HTTPException(400, "网站域名当前无法解析")
        for address in addresses:
            require_global(address)
    return url, host


def _run_live_classification(url: str, kind: str) -> dict:
    """Run one live Chrome classification; caller owns the concurrency slot."""
    from utils.util_test_password import _get_new_driver
    from utils.login_link_discovery import LoginLinkDiscovery
    from signup_flow_classifier.classifier_engine import SignupFlowClassifierEngine

    driver = _get_new_driver()
    try:
        discovery = LoginLinkDiscovery(driver)
        signup_url = discovery.navigate_to_signup(url)
        engine = SignupFlowClassifierEngine(driver)
        if not signup_url:
            signup_url = driver.current_url
        # Re-check the post-navigation target before the classifier performs
        # any further safe clicks. This also blocks a public URL redirecting
        # the browser onto a private host from being explored further.
        signup_url, _redirect_host = _validated_classify_url(
            signup_url, resolve=True)
        entry_clicked = getattr(discovery, "_entry_clicked", False)
        result = engine.classify(
            signup_url, entry_kind=kind,
            entry_already_clicked=bool(entry_clicked and kind == "signup"),
        )
        return {
            "url": url,
            "entry_kind": kind,
            "flow_type": result.get("flow_type"),
            "flow_zh": FLOW_ZH.get(result.get("flow_type"), "未确认"),
            "stop_reason": result.get("stop_reason"),
            "primary_method": result.get("primary_method"),
            "confidence": result.get("confidence"),
            "final_url": result.get("final_url"),
            "states": result.get("states", []),
            "evidence": result.get("evidence", []),
            "policy": result.get("policy", {}),
            "error": result.get("error"),
            "measured_at": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        try:
            driver.quit()
        except Exception:
            pass


@app.post("/api/classify")
def classify_site(req: ClassifyRequest):
    """输入网站主页 → 实时分类注册流程（复用测量工具，安全只读）。

    先查数据库：该域名已测过则直接返回库中结果，避免重复跑 Chrome。
    """
    url, host = _validated_classify_url(req.url, resolve=False)
    kind = req.entry_kind

    # 数据库命中：直接返回已有结果
    if host:
        conn = _conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM sites WHERE hostname = ?", (host,))
            row = cur.fetchone()
        finally:
            conn.close()
        if row:
            site = _row_to_site(row)
            entry = site[kind]
            return {
                "url": url,
                "entry_kind": kind,
                "from_database": True,
                "hostname": host,
                "flow_type": entry.get("flow_type"),
                "flow_zh": entry.get("flow_zh"),
                "stop_reason": entry.get("stop_reason"),
                "primary_method": entry.get("primary_method"),
                "confidence": entry.get("confidence"),
                "final_url": entry.get("final_url"),
                "states": entry.get("raw_states") or entry.get("steps", []),
                "evidence": entry.get("evidence", []),
                "policy": entry.get("policy", {}),
                "error": entry.get("error"),
                "measured_at": entry.get("measured_at"),
                "route": entry.get("route"),
                "manual": site.get("manual"),
            }

    # Only live navigation needs DNS resolution. Cached public results remain
    # available during a transient resolver outage. Reserve the bounded slot
    # before DNS as well, so a burst of slow lookups cannot exhaust all API
    # worker threads ahead of the Chrome concurrency guard.
    if not _CLASSIFY_SEMAPHORE.acquire(blocking=False):
        raise HTTPException(429, "服务器正在执行其他实时分类，请稍后重试")
    try:
        _validated_classify_url(url, resolve=True)
        return _run_live_classification(url, kind)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            500, "分类失败: {}: {}".format(type(exc).__name__, str(exc)[:200]))
    finally:
        _CLASSIFY_SEMAPHORE.release()


# 静态前端
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))
