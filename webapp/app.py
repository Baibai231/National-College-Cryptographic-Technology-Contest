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
    return {
        "hostname": hostname,
        "url": url,
        "keywords": json.loads(keywords or "[]"),
        "version": version or "?",
        "login": {
            "flow_type": lf, "flow_zh": lfzh or "未确认",
            "route": lr, "fields": lfields, "blockers": lblockers,
            "final_url": lfinal, "measured_at": lma,
            "steps": details.get("login_steps", []),
            "raw_states": details.get("login_raw_states", []),
            "policy": details.get("login_policy", {}),
        },
        "signup": {
            "flow_type": sf, "flow_zh": sfzh or "未确认",
            "route": sr, "fields": sfields, "blockers": sblockers,
            "final_url": sfinal, "measured_at": sma,
            "steps": details.get("signup_steps", []),
            "raw_states": details.get("signup_raw_states", []),
            "policy": details.get("signup_policy", {}),
        },
        "manual": {
            "login": mlogin, "signup": msignup,
            "note": mnote, "verified": bool(mverified),
        },
        "match_status": match,
    }


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
                    login_route = ?, login_final_url = ?, login_measured_at = ?,
                    signup_flow = ?, signup_flow_zh = ?, signup_route = ?,
                    signup_final_url = ?, signup_measured_at = ?, details_json = ?
                WHERE hostname = ?
            """, (
                req.version, keywords,
                login.get("flow_type"), login.get("flow_zh"),
                login.get("route"), login.get("final_url"), now,
                signup.get("flow_type"), signup.get("flow_zh"),
                signup.get("route"), signup.get("final_url"), now,
                details, host,
            ))
        else:
            cur.execute("""
                INSERT INTO sites (hostname, url, keywords, version,
                    login_flow, login_flow_zh, login_route, login_final_url,
                    login_measured_at, signup_flow, signup_flow_zh,
                    signup_route, signup_final_url, signup_measured_at,
                    manual_login, manual_signup, manual_note,
                    manual_verified, match_status, details_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                host, req.url or "https://" + host, keywords, req.version,
                login.get("flow_type"), login.get("flow_zh"),
                login.get("route"), login.get("final_url"), now,
                signup.get("flow_type"), signup.get("flow_zh"),
                signup.get("route"), signup.get("final_url"), now,
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
        cur.execute(
            "SELECT signup_flow, manual_signup, manual_verified FROM sites "
            "WHERE manual_verified = 1")
        match = 0
        for ft, manual, _v in cur.fetchall():
            if _manual_match(ft, manual or ""):
                match += 1
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
                             "rate": rate},
        "signup_distribution": signup_dist,
        "login_distribution": login_dist,
        "flow_zh": FLOW_ZH,
    }


def _manual_match(flow_type, manual_text):
    """程序 flow_type 与人工描述文本的粗匹配。

    规则（保守）：只做"是否出现密码框"这一核心结论对比——
    程序说有密码（direct/verification/identifier）时人工文本应提到
    密码/口令；程序说无密码（otp/email/sso/unknown）时人工不应明确
    说"设置密码/密码注册"。无法判断时视为一致（不扣分）。
    """
    t = manual_text.lower()
    has_pwd_word = ("密码" in t or "口令" in t or "password" in t)
    prog_has_pwd = flow_type in (
        "direct_password", "verification_then_password",
        "identifier_then_password", "multiple_methods")
    if prog_has_pwd:
        return has_pwd_word
    if flow_type in ("otp_only", "email_only", "sso_only"):
        # 程序说无密码，人工明确说注册需设置密码 → 不一致
        return not ("设置密码" in t or "密码注册" in t or "密码框" in t
                    or "有密码" in t)
    return True  # human_blocked / unknown / no_web_signup：不判错


class ClassifyRequest(BaseModel):
    url: str
    entry_kind: str = "signup"


class ReviewRequest(BaseModel):
    hostname: str
    login: str = ""
    signup: str = ""
    note: str = ""
    submitter: str = ""


@app.get("/api/reviews/pending")
def pending_reviews(hostname: str = Query("", max_length=100)):
    """待审核的人工观察提交（管理员核验用）。可传 hostname 查单站。"""
    conn = _conn()
    try:
        cur = conn.cursor()
        if hostname:
            cur.execute(
                "SELECT id, hostname, login, signup, note, submitter, submitted_at "
                "FROM reviews_pending WHERE hostname = ? ORDER BY id DESC",
                (hostname,))
        else:
            cur.execute(
                "SELECT id, hostname, login, signup, note, submitter, submitted_at "
                "FROM reviews_pending ORDER BY id DESC")
        rows = cur.fetchall()
    finally:
        conn.close()
    return {"total": len(rows), "reviews": [
        {"id": r[0], "hostname": r[1], "login": r[2], "signup": r[3],
         "note": r[4], "submitter": r[5], "submitted_at": r[6]}
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
            "submitter, submitted_at) VALUES (?,?,?,?,?,?)",
            (host, req.login.strip(), req.signup.strip(), req.note.strip(),
             req.submitter.strip(),
             datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "message": f"已提交 {host} 的人工观察，等待管理员核验"}


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
            "SELECT id, hostname, login, signup, note, submitter, submitted_at "
            "FROM reviews_pending WHERE id = ?", (review_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, f"待审核记录不存在: {review_id}")
        _rid, host, login, signup, note, submitter, ts = row
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
