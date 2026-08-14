"""注册流程测量平台后端 API。

功能：
- GET  /api/sites?q=关键词&limit=N   搜索站点
- GET  /api/sites/{host}             站点详情
- GET  /api/stats                    统计
- POST /api/classify {url}           输入网站主页 → 实时分类（复用测量工具）

启动:
  .venv/bin/python -m uvicorn webapp.app:app --host 0.0.0.0 --port 8000
"""
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

DB_PATH = os.environ.get(
    "SITES_DB", str(_PROJECT_ROOT / "webapp" / "sites.db"))
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="注册流程测量平台", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    return sqlite3.connect(DB_PATH)


def _row_to_site(row):
    (hostname, url, keywords, version, lf, lfzh, lr, lfields, lblockers,
     lfinal, lma, sf, sfzh, sr, sfields, sblockers, sfinal, sma,
     mlogin, msignup, mnote, mverified, match, details_json) = row
    details = json.loads(details_json or "{}")
    login_error = details.get("login_error") or ""
    signup_error = details.get("signup_error") or ""
    login_states = details.get("login_raw_states", [])
    signup_states = details.get("signup_raw_states", [])
    login_methods = _methods_from_states(login_states)
    signup_methods = _methods_from_states(signup_states)
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
            "program_reason": _program_reason(
                sf, sr, sfields, sblockers, signup_error, signup_methods),
        },
        "manual": {
            "login": mlogin, "signup": msignup,
            "note": mnote, "verified": bool(mverified),
        },
        "match_status": match,
        # 注册侧程序vs人工匹配：match/mismatch/pending（供筛选）
    }
    comparison = _manual_comparison(
        sf, msignup or "", sr or "", sfields or "", sblockers or "",
        verified=bool(mverified), methods=signup_methods,
    )
    site["signup_match"] = comparison["status"]
    site["comparison"] = comparison
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
    hostname: str
    url: str = ""
    version: str = "v3"
    login: dict = {}
    signup: dict = {}
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
    now = datetime.now(timezone.utc).isoformat()
    # 关键词：hostname + 主域名（zhihu.com → zhihu），便于部分输入搜索
    host_main = host.replace("www.", "").split(".")[0] if "." in host else host
    keywords = json.dumps([host, host_main, host.replace("www.", "")],
                          ensure_ascii=False)
    # 从 raw_states 提取字段/阻断（中文，用于详情表格）
    login_fields = _extract_states(login.get("raw_states") or login.get("steps", []), "fields")
    login_blockers = _extract_states(login.get("raw_states") or login.get("steps", []), "blockers")
    signup_fields = _extract_states(signup.get("raw_states") or signup.get("steps", []), "fields")
    signup_blockers = _extract_states(signup.get("raw_states") or signup.get("steps", []), "blockers")
    details = json.dumps({
        "login_steps": login.get("steps", []),
        "signup_steps": signup.get("steps", []),
        "login_raw_states": login.get("raw_states", []),
        "signup_raw_states": signup.get("raw_states", []),
        "login_policy": login.get("policy", {}),
        "signup_policy": signup.get("policy", {}),
    }, ensure_ascii=False)

    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT hostname FROM sites WHERE hostname = ?", (host,))
        exists = cur.fetchone() is not None
        if exists:
            cur.execute("""
                UPDATE sites SET version = ?, keywords = ?,
                    login_flow = ?, login_flow_zh = ?,
                    login_route = ?, login_fields = ?, login_blockers = ?,
                    login_final_url = ?, login_measured_at = ?,
                    signup_flow = ?, signup_flow_zh = ?, signup_route = ?,
                    signup_fields = ?, signup_blockers = ?,
                    signup_final_url = ?, signup_measured_at = ?, details_json = ?
                WHERE hostname = ?
            """, (
                req.version, keywords,
                login.get("flow_type"), login.get("flow_zh"),
                login.get("route"), login_fields, login_blockers,
                login.get("final_url"), now,
                signup.get("flow_type"), signup.get("flow_zh"),
                signup.get("route"), signup_fields, signup_blockers,
                signup.get("final_url"), now,
                details, host,
            ))
        else:
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
                host, req.url or "https://" + host, keywords, req.version,
                login.get("flow_type"), login.get("flow_zh"),
                login.get("route"), login_fields, login_blockers,
                login.get("final_url"), now,
                signup.get("flow_type"), signup.get("flow_zh"),
                signup.get("route"), signup_fields, signup_blockers,
                signup.get("final_url"), now,
                "", "", "", 0, "pending_manual", details,
            ))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True,
            "message": ("更新" if exists else "新增") + f" {host} ({req.version})"}


@app.get("/api/export")
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

    records = []
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM sites ORDER BY hostname")
        for row in cur.fetchall():
            site = _row_to_site(row)
            for kind in ("login", "signup"):
                entry = site[kind]
                if not entry.get("flow_type"):
                    continue
                rec = {
                    "site": site.get("url") or "https://" + site["hostname"],
                    "hostname": site["hostname"],
                    "entry_kind": kind,
                    "measured_at": entry.get("measured_at"),
                    "version": site.get("version", "?"),
                    "flow_type": entry.get("flow_type"),
                    "confidence": None,
                    "stop_reason": entry.get("stop_reason"),
                    "primary_method": None,
                    "final_url": entry.get("final_url"),
                    "states": entry.get("raw_states") or entry.get("steps", []),
                    "policy": entry.get("policy", {}),
                    "evidence": [],
                    "error": None,
                }
                records.append(rec)
        # 历史版本
        cur.execute("SELECT * FROM site_history")
        for r in cur.fetchall():
            details = json.loads(r[8] or "{}")
            records.append({
                "site": "https://" + r[1],
                "hostname": r[1], "entry_kind": r[2],
                "measured_at": r[7], "version": r[3],
                "flow_type": r[4], "confidence": None,
                "stop_reason": r[5], "primary_method": r[6],
                "final_url": None,
                "states": details.get("steps", []),
                "policy": details.get("policy", {}),
                "evidence": [], "error": None,
            })
    finally:
        conn.close()
    manual = {}
    manual_path = _PROJECT_ROOT / "misc" / "manual_review.json"
    if manual_path.is_file():
        try:
            import json as _json
            with open(manual_path, encoding="utf-8") as f:
                manual = _json.load(f)
        except Exception:
            pass
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
        # 程序 vs 人工 粗匹配正确率（已核验站中，程序注册结论与人工描述一致的比例）
        cur.execute("SELECT * FROM sites WHERE manual_verified = 1")
        match = 0
        correct_sites, wrong_sites = [], []
        for row in cur.fetchall():
            site = _row_to_site(row)
            comparison = site["comparison"]
            item = {
                "hostname": site["hostname"],
                "program": site["signup"]["flow_type"],
                "manual": (site["manual"]["signup"] or "")[:100],
                "reason": comparison["reason"],
            }
            if comparison["status"] == "match":
                match += 1
                correct_sites.append(item)
            else:
                wrong_sites.append(item)
        rate = round(match / verified * 100, 1) if verified else 0.0
        cur.execute("SELECT COUNT(*) FROM reviews_pending")
        pending = cur.fetchone()[0]
    finally:
        conn.close()
    return {
        "total_sites": total,
        "manual_verified": verified,
        "pending_reviews": pending,
        "program_accuracy": {"match": match, "total": verified,
                             "rate": rate,
                             "correct_sites": correct_sites,
                             "wrong_sites": wrong_sites},
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


def _manual_traits(manual_text):
    t = (manual_text or "").lower().replace(" ", "")
    negative_pwd = any(x in t for x in (
        "无密码", "没有密码", "无需密码", "不需要密码", "无口令", "仅验证码"))
    positive_source = t
    for phrase in ("无密码", "没有密码", "无需密码", "不需要密码", "无口令"):
        positive_source = positive_source.replace(phrase, "")
    has_password = any(x in positive_source for x in (
        "密码", "口令", "password"))
    has_otp = any(x in t for x in ("验证码", "短信", "动态码", "otp", "手机验证"))
    has_scan = any(x in t for x in ("扫码", "二维码", "扫一扫", "app确认"))
    has_captcha = any(x in t for x in (
        "人机", "滑块", "captcha", "验证块", "图形验证码"))
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
    return {
        "password": has_password, "negative_password": negative_pwd,
        "otp": has_otp, "scan": has_scan, "human_gate": has_human_gate,
        "captcha": has_captcha, "tos": has_tos,
        "sso": has_sso, "no_web": no_web,
    }


def _manual_comparison(flow_type, manual_text, route="", fields="", blockers="",
                       verified=True, methods=""):
    """返回人工对照状态及可复核原因，避免把 unknown/human_blocked 一律算对。"""
    if not verified:
        return {"status": "pending", "reason": "尚无人工复核，当前只展示程序判断依据。"}
    traits = _manual_traits(manual_text)
    program_reason = _program_reason(flow_type, route, fields, blockers, methods=methods)
    matched = False
    difference = ""

    if flow_type in ("direct_password", "identifier_then_password", "verification_then_password"):
        matched = traits["password"] and not traits["negative_password"]
        difference = "程序报告可达口令框，但人工没有确认口令注册，或明确记录为无密码。"
    elif flow_type in ("otp_only", "email_only"):
        matched = not traits["password"] and (traits["otp"] or traits["negative_password"])
        difference = "程序报告未见长期口令，但人工确认注册需要设置密码。"
    elif flow_type == "sso_only":
        matched = traits["sso"] and not traits["password"] and not traits["otp"]
        difference = "程序报告仅第三方登录，但人工还观察到站点自有验证码或口令路线。"
    elif flow_type == "human_blocked":
        blocker_lower = (blockers or "").lower()
        same_gate = any((
            traits["otp"] and any(x in blocker_lower for x in ("短信", "邮箱验证码", "一次性验证码", "sms", "otp")),
            traits["scan"] and any(x in blocker_lower for x in ("扫码", "scan", "app 确认")),
            traits["captcha"] and any(x in blocker_lower for x in ("人机", "图片", "滑块", "captcha", "slide")),
            traits["tos"] and any(x in blocker_lower for x in ("协议", "条款", "tos")),
        ))
        matched = same_gate and not (traits["password"] and not traits["human_gate"])
        difference = "程序停止的具体门槛与人工记录不同，或人工已确认可直接到达口令框。"
    elif flow_type in ("unknown", "no_web_signup"):
        matched = traits["no_web"]
        difference = "程序没有确认注册流程，但人工已经观察到明确的注册方式。"
    elif flow_type == "multiple_methods":
        matched = sum(bool(traits[x]) for x in ("password", "otp", "sso", "scan")) >= 2
        difference = "程序报告多方式并存，但人工描述不足以确认两种以上方式。"
    else:
        difference = "程序未形成可与人工核验的有效结论。"

    if matched:
        return {
            "status": "match",
            "reason": f"{program_reason} 人工复核为“{manual_text or '未填写'}”，核心路线一致。",
        }
    return {
        "status": "mismatch",
        "reason": f"差异：{difference} 程序依据：{program_reason} 人工复核为“{manual_text or '未填写'}”。",
    }


def _manual_match(flow_type, manual_text):
    """兼容旧调用：使用新的结构化人工对照规则。"""
    return _manual_comparison(flow_type, manual_text)["status"] == "match"


class ClassifyRequest(BaseModel):
    url: str
    entry_kind: str = "signup"


class ReviewRequest(BaseModel):
    hostname: str
    login: str = ""
    signup: str = ""
    note: str = ""
    submitter: str = ""
    review_type: str = "manual"  # manual=人工观察提交, feedback=识别结果反馈


@app.get("/api/reviews/pending")
def pending_reviews(hostname: str = Query("", max_length=100)):
    """待审核的人工观察提交（管理员核验用）。可传 hostname 查单站。"""
    conn = _conn()
    try:
        cur = conn.cursor()
        if hostname:
            cur.execute(
                "SELECT id, hostname, login, signup, note, submitter, review_type, submitted_at "
                "FROM reviews_pending WHERE hostname = ? ORDER BY id DESC",
                (hostname,))
        else:
            cur.execute(
                "SELECT id, hostname, login, signup, note, submitter, review_type, submitted_at "
                "FROM reviews_pending ORDER BY id DESC")
        rows = cur.fetchall()
    finally:
        conn.close()
    return {"total": len(rows), "reviews": [
        {"id": r[0], "hostname": r[1], "login": r[2], "signup": r[3],
         "note": r[4], "submitter": r[5], "review_type": r[6] or "manual",
         "submitted_at": r[7]}
        for r in rows
    ]}


@app.post("/api/reviews")
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
            "submitter, review_type, submitted_at) VALUES (?,?,?,?,?,?,?)",
            (host, req.login.strip(), req.signup.strip(), req.note.strip(),
             req.submitter.strip(),
             req.review_type if req.review_type in ("manual", "feedback") else "manual",
             datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()
    kind = "识别反馈" if req.review_type == "feedback" else "人工观察"
    return {"ok": True, "message": f"已提交 {host} 的{kind}，等待管理员核验"}


@app.post("/api/reviews/{review_id}/approve")
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
            "SELECT id, hostname, login, signup, note, submitter, review_type, submitted_at "
            "FROM reviews_pending WHERE id = ?", (review_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, f"待审核记录不存在: {review_id}")
        _rid, host, login, signup, note, submitter, rtype, ts = row
        if rtype == "feedback":
            # 识别反馈：不自动合并人工核验，只删除（管理员已人工判断处理）
            cur.execute("DELETE FROM reviews_pending WHERE id = ?", (review_id,))
            conn.commit()
            return {"ok": True, "message": f"已处理 {host} 的识别反馈（未写入人工核验）"}
        # 1) 更新 sites 表（合并人工结果）
        cur.execute("""
            UPDATE sites SET manual_login = CASE WHEN ? != '' THEN ? ELSE manual_login END,
                            manual_signup = CASE WHEN ? != '' THEN ? ELSE manual_signup END,
                            manual_note = CASE WHEN ? != '' THEN ? ELSE manual_note END,
                            manual_verified = 1,
                            match_status = 'manual_verified'
            WHERE hostname = ?
        """, (login, login, signup, signup, note, note, host))
        # 2) 删除待审核记录
        cur.execute("DELETE FROM reviews_pending WHERE id = ?", (review_id,))
        conn.commit()
    finally:
        conn.close()
    # 3) 写回 misc/manual_review.json（保持数据同步，便于 git 提交）
    try:
        manual_path = _PROJECT_ROOT / "misc" / "manual_review.json"
        if manual_path.is_file():
            import json as _json
            with open(manual_path, encoding="utf-8") as f:
                manual = _json.load(f)
            sites = manual.setdefault("sites", {})
            entry = sites.setdefault(host, {})
            if login:
                entry["manual_login"] = login
            if signup:
                entry["manual_signup"] = signup
            if note:
                entry["note"] = note
            entry["verified"] = True
            entry["reviewed_from"] = f"web@{submitter or 'admin'}@{ts}"
            manual["updated_at"] = datetime.now(timezone.utc).isoformat()
            with open(manual_path, "w", encoding="utf-8") as f:
                _json.dump(manual, f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # 写回失败不影响数据库生效
    return {"ok": True, "message": f"已通过 {host} 的人工观察"}


@app.delete("/api/reviews/{review_id}")
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


@app.post("/api/classify")
def classify_site(req: ClassifyRequest):
    """输入网站主页 → 实时分类注册流程（复用测量工具，安全只读）。

    先查数据库：该域名已测过则直接返回库中结果，避免重复跑 Chrome。
    """
    url = req.url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    kind = req.entry_kind if req.entry_kind in ("signup", "login") else "signup"

    # 数据库命中：直接返回已有结果
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or "").lower()
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
                "stop_reason": None,
                "primary_method": None,
                "confidence": None,
                "final_url": entry.get("final_url"),
                "states": entry.get("steps", []),
                "evidence": [],
                "route": entry.get("route"),
                "manual": site.get("manual"),
            }

    try:
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
            }
        finally:
            try:
                driver.quit()
            except Exception:
                pass
    except Exception as exc:
        raise HTTPException(
            500, "分类失败: {}: {}".format(type(exc).__name__, str(exc)[:200]))


# 静态前端
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))
