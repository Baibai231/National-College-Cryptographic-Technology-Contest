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

from fastapi import FastAPI, HTTPException, Query
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
    (hostname, url, keywords, lf, lfzh, lr, lfields, lblockers, lfinal, lma,
     sf, sfzh, sr, sfields, sblockers, sfinal, sma,
     mlogin, msignup, mnote, mverified, match, details_json) = row
    details = json.loads(details_json or "{}")
    return {
        "hostname": hostname,
        "url": url,
        "keywords": json.loads(keywords or "[]"),
        "login": {
            "flow_type": lf, "flow_zh": lfzh or "未确认",
            "route": lr, "fields": lfields, "blockers": lblockers,
            "final_url": lfinal, "measured_at": lma,
            "steps": details.get("login_steps", []),
            "policy": details.get("login_policy", {}),
        },
        "signup": {
            "flow_type": sf, "flow_zh": sfzh or "未确认",
            "route": sr, "fields": sfields, "blockers": sblockers,
            "final_url": sfinal, "measured_at": sma,
            "steps": details.get("signup_steps", []),
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
    finally:
        conn.close()
    return {
        "total_sites": total,
        "manual_verified": verified,
        "signup_distribution": signup_dist,
        "login_distribution": login_dist,
        "flow_zh": FLOW_ZH,
    }


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
def pending_reviews():
    """待审核的人工观察提交（管理员核验用）。"""
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, hostname, login, signup, note, submitter, submitted_at "
            "FROM reviews_pending ORDER BY id DESC")
        rows = cur.fetchall()
    finally:
        conn.close()
    return {"reviews": [
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


@app.delete("/api/reviews/{review_id}")
def delete_review(review_id: int):
    """管理员核验后删除待审核记录。"""
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
    """输入网站主页 → 实时分类注册流程（复用测量工具，安全只读）。"""
    url = req.url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    kind = req.entry_kind if req.entry_kind in ("signup", "login") else "signup"
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
