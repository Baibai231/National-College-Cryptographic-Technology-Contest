"""构建站点数据库：final JSONL + 人工复核 → SQLite。

用法:
  .venv/bin/python scripts/build_site_database.py \
      --input reports/final/cn60_final_20260813.jsonl \
      --manual misc/manual_review.json \
      --output webapp/sites.db
"""
import argparse
import json
import os
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

FIELD_ZH = {
    "phone": "手机号", "email": "邮箱", "identifier": "账号/邮箱",
    "password": "口令", "code": "一次性验证码",
}
FLOW_ZH = {
    "direct_password": "直接口令", "identifier_then_password": "先标识后口令",
    "verification_then_password": "先验证后口令", "otp_only": "仅一次性验证码",
    "email_only": "仅邮箱验证码", "multiple_methods": "多方式并存",
    "sso_only": "仅第三方登录", "human_blocked": "人工阻断",
    "no_web_signup": "无网页注册", "unknown": "未确认", "error": "异常",
}
BLOCKER_ZH = {
    "sms_code": "短信验证码", "email_code": "邮箱验证码",
    "verification_code": "一次性验证码", "scan": "扫码",
    "captcha": "图片/人机验证", "slide": "滑块验证",
    "app_confirm": "App 确认", "tos": "用户协议确认",
}


def _fields_zh(fields):
    return "、".join(FIELD_ZH.get(f, f) for f in fields) or "—"


def _blockers_zh(blockers):
    return "、".join(BLOCKER_ZH.get(b, b) for b in blockers) or "—"


def _route(states, entry_kind):
    """从状态序列生成人话路线（登录/注册）。"""
    parts = []
    for st in states:
        if st.get("fields"):
            parts.append(_fields_zh(st["fields"]))
        if st.get("blockers"):
            parts.append(_blockers_zh(st["blockers"]))
    if not parts:
        return "未确认"
    # 去重保序
    seen = []
    for p in parts:
        if p not in seen:
            seen.append(p)
    return " → ".join(seen)


def _summary(states):
    """步骤摘要，给详情页展示。"""
    steps = []
    for st in states:
        steps.append({
            "step": st.get("step"),
            "url": st.get("url", ""),
            "fields": _fields_zh(st.get("fields", [])),
            "blockers": _blockers_zh(st.get("blockers", [])),
            "actions": st.get("actions", []),
            "note": st.get("note", ""),
        })
    return steps


def load_records(jsonl_path):
    records = {}
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            key = (r.get("hostname"), r.get("entry_kind"))
            records[key] = r
    return records


def build_sites(records):
    by_host = defaultdict(dict)
    for (host, kind), r in records.items():
        by_host[host][kind] = r

    sites = []
    for host in sorted(h for h in by_host if h):
        login = by_host[host].get("login")
        signup = by_host[host].get("signup")
        site = {
            "hostname": host,
            "url": (login or signup or {}).get("site", "https://" + host),
            "login": {
                "flow_type": (login or {}).get("flow_type"),
                "flow_zh": FLOW_ZH.get((login or {}).get("flow_type"), "未确认"),
                "stop_reason": (login or {}).get("stop_reason"),
                "route": _route((login or {}).get("states", []), "login"),
                "fields": _fields_zh(
                    {f for s in (login or {}).get("states", []) for f in s.get("fields", [])}),
                "blockers": _blockers_zh(
                    {b for s in (login or {}).get("states", []) for b in s.get("blockers", [])}),
                "final_url": (login or {}).get("final_url", ""),
                "steps": _summary((login or {}).get("states", [])),
                "measured_at": (login or {}).get("measured_at", ""),
                "policy": (login or {}).get("policy", {}),
            },
            "signup": {
                "flow_type": (signup or {}).get("flow_type"),
                "flow_zh": FLOW_ZH.get((signup or {}).get("flow_type"), "未确认"),
                "stop_reason": (signup or {}).get("stop_reason"),
                "route": _route((signup or {}).get("states", []), "signup"),
                "fields": _fields_zh(
                    {f for s in (signup or {}).get("states", []) for f in s.get("fields", [])}),
                "blockers": _blockers_zh(
                    {b for s in (signup or {}).get("states", []) for b in s.get("blockers", [])}),
                "final_url": (signup or {}).get("final_url", ""),
                "steps": _summary((signup or {}).get("states", [])),
                "measured_at": (signup or {}).get("measured_at", ""),
                "policy": (signup or {}).get("policy", {}),
            },
        }
        sites.append(site)
    return sites


def attach_manual(sites, manual_path, keywords_path=None):
    manual = {}
    if manual_path and os.path.isfile(manual_path):
        with open(manual_path, encoding="utf-8") as f:
            manual = json.load(f).get("sites", {})
    keywords = {}
    if keywords_path and os.path.isfile(keywords_path):
        with open(keywords_path, encoding="utf-8") as f:
            keywords = json.load(f).get("sites", {})
    for site in sites:
        m = manual.get(site["hostname"])
        if m:
            site["manual"] = {
                "login": m.get("manual_login", ""),
                "signup": m.get("manual_signup", ""),
                "note": m.get("note", ""),
                "verified": bool(m.get("verified")),
            }
            # 程序 vs 人工 匹配状态
            site["match_status"] = _match_status(site)
        else:
            site["manual"] = {
                "login": "", "signup": "", "note": "", "verified": False,
            }
            site["match_status"] = "pending_manual"
        # 中文关键词：hostname 去掉 www. 前缀匹配
        host_key = site["hostname"].replace("www.", "")
        site["keywords"] = keywords.get(host_key, [site["hostname"]])
    return sites


def _match_status(site):
    """程序 vs 人工粗对比：均无人工时 pending；有且文本近似时 matched。"""
    m = site.get("manual", {})
    if not m.get("verified"):
        return "pending_manual"
    return "manual_verified"


def create_db(sites, db_path):
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE sites (
            hostname TEXT PRIMARY KEY,
            url TEXT,
            keywords TEXT,
            login_flow TEXT, login_flow_zh TEXT, login_route TEXT,
            login_fields TEXT, login_blockers TEXT, login_final_url TEXT,
            login_measured_at TEXT,
            signup_flow TEXT, signup_flow_zh TEXT, signup_route TEXT,
            signup_fields TEXT, signup_blockers TEXT, signup_final_url TEXT,
            signup_measured_at TEXT,
            manual_login TEXT, manual_signup TEXT, manual_note TEXT,
            manual_verified INTEGER, match_status TEXT,
            details_json TEXT
        )
    """)
    # 组员提交的人工观察（待审核）
    cur.execute("""
        CREATE TABLE IF NOT EXISTS reviews_pending (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hostname TEXT NOT NULL,
            login TEXT DEFAULT '',
            signup TEXT DEFAULT '',
            note TEXT DEFAULT '',
            submitter TEXT DEFAULT '',
            submitted_at TEXT
        )
    """)
    for s in sites:
        details = {
            "login_steps": s["login"]["steps"],
            "signup_steps": s["signup"]["steps"],
            "login_policy": s["login"]["policy"],
            "signup_policy": s["signup"]["policy"],
        }
        cur.execute("""
            INSERT INTO sites VALUES (
                ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
            )
        """, (
            s["hostname"], s["url"], json.dumps(s["keywords"], ensure_ascii=False),
            s["login"]["flow_type"], s["login"]["flow_zh"], s["login"]["route"],
            s["login"]["fields"], s["login"]["blockers"], s["login"]["final_url"],
            s["login"]["measured_at"],
            s["signup"]["flow_type"], s["signup"]["flow_zh"], s["signup"]["route"],
            s["signup"]["fields"], s["signup"]["blockers"], s["signup"]["final_url"],
            s["signup"]["measured_at"],
            s["manual"]["login"], s["manual"]["signup"], s["manual"]["note"],
            int(s["manual"]["verified"]), s["match_status"],
            json.dumps(details, ensure_ascii=False),
        ))
    cur.execute(
        "CREATE INDEX idx_hostname ON sites(hostname);"
    )
    conn.commit()
    conn.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", default="reports/final/cn60_final_20260813.jsonl")
    ap.add_argument("--manual", default="misc/manual_review.json")
    ap.add_argument("--keywords", default="misc/site_keywords.json")
    ap.add_argument("--output", default="webapp/sites.db")
    args = ap.parse_args()

    records = load_records(args.input)
    print(f"加载 {len(records)} 条测量记录")
    sites = attach_manual(build_sites(records), args.manual, args.keywords)
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    create_db(sites, args.output)
    verified = sum(1 for s in sites if s["match_status"] == "manual_verified")
    print(f"已写入 {args.output}: {len(sites)} 站，人工已核验 {verified} 站")


if __name__ == "__main__":
    main()
