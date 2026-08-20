"""构建站点数据库：final JSONL + 人工复核 → SQLite。

用法:
  .venv/bin/python scripts/build_site_database.py \
      --input reports/sites/sites_latest.jsonl \
      --manual misc/manual_review.json \
      --output webapp/sites.db
"""
import argparse
import json
import os
import sqlite3
import sys
from collections import defaultdict
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.site_data_store import coordinated_data_lock

FIELD_ZH = {
    "phone": "手机号", "email": "邮箱", "identifier": "账号/邮箱",
    "password": "口令", "code": "一次性验证码",
}
FLOW_ZH = {
    "direct_password": "有口令框", "identifier_then_password": "先账号后口令框",
    "verification_then_password": "先验证后口令框", "otp_only": "仅验证码",
    "email_only": "仅邮箱", "multiple_methods": "多方式并存",
    "sso_only": "仅第三方", "human_blocked": "需人工验证",
    "no_web_signup": "无注册界面", "unknown": "未确认", "error": "异常",
}
BLOCKER_ZH = {
    "sms_code": "短信验证码", "email_code": "邮箱验证码",
    "verification_code": "一次性验证码", "scan": "扫码",
    "captcha": "图片/人机验证", "slide": "滑块验证",
    "app_confirm": "App 确认", "tos": "用户协议确认",
}


def _fields_zh(fields):
    if isinstance(fields, str):
        return fields if fields else "—"
    return "、".join(FIELD_ZH.get(f, f) for f in fields) or "—"


def _blockers_zh(blockers):
    if isinstance(blockers, str):
        return blockers if blockers else "—"
    return "、".join(BLOCKER_ZH.get(b, b) for b in blockers) or "—"


def _route(states, entry_kind):
    """从状态序列生成人话路线（登录/注册）。

    tab 切换（短信/密码等并行视图）不线性化成"→"链（36kr 实测），
    只在真正前进（next/submit/click_link）时用 → 连接；
    切换视图用"；切换视图后："。同一步内的字段与门槛合并展示。
    """
    parts = []
    for st in states or []:
        text = _step_text(st)
        if not text:
            continue
        actions = st.get("actions") or []
        if not parts:
            parts.append(text)
        elif any(a in ("tab_click", "auth_mode_click", "signup_mode_reveal")
                 for a in actions):
            parts.append("切换视图后：" + text)
        elif any(a in ("next", "submit", "click_link", "entry_click")
                 for a in actions):
            parts.append("下一步：" + text)
        else:
            parts.append(text)
    if not parts:
        return "未确认"
    return " → ".join(parts)


def _step_text(st):
    """单个状态的字段+门槛人话描述：手机号、一次性验证码（需短信验证码）。"""
    fields = _fields_zh(st.get("fields", []))
    blockers = _blockers_zh(st.get("blockers", []))
    text = fields if fields and fields != "—" else ""
    if blockers and blockers != "—":
        text += "（需" + blockers + "）"
    return text


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


def load_records(jsonl_paths):
    """加载多个 JSONL（不同版本的测量），按 (hostname, entry_kind, version) 分组。

    返回: {hostname: {"login": [...版本列表], "signup": [...]}}，
    每个版本列表按出现顺序（后出现者更新）。
    """
    groups = defaultdict(lambda: defaultdict(list))
    for path in jsonl_paths:
        if not os.path.isfile(path):
            print(f"  [warn] 结果文件不存在: {path}")
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                r = json.loads(line)
                host = r.get("hostname")
                kind = r.get("entry_kind")
                if not host or not kind:
                    continue
                groups[host][kind].append(r)
    return groups


def _pick_latest(records):
    """从同站同入口的多个版本记录里选最新（version 最大，其次 measured_at 最新）。"""
    if not records:
        return None
    if len(records) == 1:
        return records[0]

    def ver_key(r):
        v = r.get("version") or ""
        # v3 → (3, 0); v10 → (10, 0); 纯数字 → (n, 0)
        m = __import__("re").match(r"^v?(\d+)", v)
        num = int(m.group(1)) if m else 0
        return (num, r.get("measured_at") or "")

    return max(records, key=ver_key)


def build_sites(groups):
    sites = []
    for host in sorted(h for h in groups if h):
        kinds = groups[host]
        login = _pick_latest(kinds.get("login"))
        signup = _pick_latest(kinds.get("signup"))
        login_flow = "error" if (login or {}).get("error") else (login or {}).get("flow_type")
        signup_flow = "error" if (signup or {}).get("error") else (signup or {}).get("flow_type")
        site = {
            "hostname": host,
            "url": (login or signup or {}).get("site", "https://" + host),
            "version": (signup or login or {}).get("version", ""),
            "login": {
                "flow_type": login_flow,
                "flow_zh": FLOW_ZH.get(login_flow, "未确认"),
                "stop_reason": (login or {}).get("stop_reason"),
                "route": _route((login or {}).get("states", []), "login"),
                "fields": _fields_zh(
                    {f for s in (login or {}).get("states", []) for f in s.get("fields", [])}),
                "blockers": _blockers_zh(
                    {b for s in (login or {}).get("states", []) for b in s.get("blockers", [])}),
                "final_url": (login or {}).get("final_url", ""),
                "steps": _summary((login or {}).get("states", [])),
                "raw_states": (login or {}).get("states", []),
                "measured_at": (login or {}).get("measured_at", ""),
                "policy": (login or {}).get("policy", {}),
                "pwd_policy": (login or {}).get("pwd_policy", {}),
                "error": (login or {}).get("error"),
                "record": login or {},
            },
            "signup": {
                "flow_type": signup_flow,
                "flow_zh": FLOW_ZH.get(signup_flow, "未确认"),
                "stop_reason": (signup or {}).get("stop_reason"),
                "route": _route((signup or {}).get("states", []), "signup"),
                "fields": _fields_zh(
                    {f for s in (signup or {}).get("states", []) for f in s.get("fields", [])}),
                "blockers": _blockers_zh(
                    {b for s in (signup or {}).get("states", []) for b in s.get("blockers", [])}),
                "final_url": (signup or {}).get("final_url", ""),
                "steps": _summary((signup or {}).get("states", [])),
                "raw_states": (signup or {}).get("states", []),
                "measured_at": (signup or {}).get("measured_at", ""),
                "policy": (signup or {}).get("policy", {}),
                "pwd_policy": (signup or {}).get("pwd_policy", {}),
                "error": (signup or {}).get("error"),
                "record": signup or {},
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
                "structured": m.get("structured", {}),
                "pwd_testability": m.get("pwd_testability", {}),
            }
            # 程序 vs 人工 匹配状态
            site["match_status"] = _match_status(site)
        else:
            site["manual"] = {
                "login": "", "signup": "", "note": "", "verified": False,
                "structured": {},
                "pwd_testability": {},
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


def build_history(groups, sites):
    """提取历史版本记录（非当前最新），用于 site_history 表。"""
    latest = {}
    for s in sites:
        latest[s["hostname"]] = s.get("version", "")
    history = []
    for host, kinds in groups.items():
        for kind, recs in kinds.items():
            cur_ver = latest.get(host, "")
            for r in recs:
                v = r.get("version", "")
                # 跳过与当前版本相同的（sites 表已有）
                if v == cur_ver:
                    continue
                history.append({
                    "hostname": host,
                    "entry_kind": kind,
                    "version": v or "?",
                    "flow_type": r.get("flow_type"),
                    "stop_reason": r.get("stop_reason"),
                    "primary_method": r.get("primary_method"),
                    "route": _route(r.get("states", []), kind),
                    "measured_at": r.get("measured_at", ""),
                    "details_json": json.dumps({
                        "steps": _summary(r.get("states", [])),
                        "policy": r.get("policy", {}),
                    }, ensure_ascii=False),
                })
    return history


def create_db(sites, db_path, history=None):
    # SQLite 是可重建索引，但待审核提交只存在其中。重建前先完整备份，
    # 避免定时 pull/rebuild 把尚未处理的人工提交清空。
    pending_rows = []
    if os.path.exists(db_path):
        try:
            with sqlite3.connect(db_path, timeout=15) as old:
                old.row_factory = sqlite3.Row
                table = old.execute(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type='table' AND name='reviews_pending'"
                ).fetchone()
                if table:
                    pending_rows = [dict(row) for row in old.execute(
                        "SELECT * FROM reviews_pending ORDER BY id")]
        except sqlite3.DatabaseError as exc:
            # Pending reviews exist only in SQLite.  If they cannot be read,
            # fail closed and keep the old database for manual recovery.
            raise RuntimeError(
                f"无法备份旧数据库中的待审核记录，已取消重建: {exc}"
            ) from exc
    # 始终在旁路文件中完整构建；只有全部 SQL 成功后才原子替换服务索引。
    # 构建异常时旧数据库仍可继续服务，下一次运行会清理残留 building 文件。
    build_path = os.fspath(db_path) + ".building"
    if os.path.exists(build_path):
        os.remove(build_path)
    conn = sqlite3.connect(build_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE sites (
            hostname TEXT PRIMARY KEY,
            url TEXT,
            keywords TEXT,
            version TEXT,
            login_flow TEXT, login_flow_zh TEXT, login_route TEXT,
            login_fields TEXT, login_blockers TEXT, login_final_url TEXT,
            login_measured_at TEXT,
            signup_flow TEXT, signup_flow_zh TEXT, signup_route TEXT,
            signup_fields TEXT, signup_blockers TEXT, signup_final_url TEXT,
            signup_measured_at TEXT,
            manual_login TEXT, manual_signup TEXT, manual_note TEXT,
            manual_verified INTEGER, match_status TEXT,
            login_pwd_test TEXT, signup_pwd_test TEXT, overall_pwd_test TEXT,
            details_json TEXT
        )
    """)
    # 程序各版本历史结果（同站同入口可多条，按 version 区分）
    cur.execute("""
        CREATE TABLE IF NOT EXISTS site_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hostname TEXT NOT NULL,
            entry_kind TEXT NOT NULL,
            version TEXT,
            flow_type TEXT, stop_reason TEXT, primary_method TEXT,
            route TEXT, measured_at TEXT,
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
            review_type TEXT DEFAULT 'manual',
            submitted_at TEXT,
            structured_json TEXT DEFAULT '{}'
        )
    """)
    for s in sites:
        details = {
            "login_steps": s["login"]["steps"],
            "signup_steps": s["signup"]["steps"],
            "login_raw_states": s["login"]["raw_states"],
            "signup_raw_states": s["signup"]["raw_states"],
            "login_policy": s["login"]["policy"],
            "signup_policy": s["signup"]["policy"],
            "login_pwd_policy": s["login"].get("pwd_policy", {}),
            "signup_pwd_policy": s["signup"].get("pwd_policy", {}),
            "login_error": s["login"].get("error"),
            "signup_error": s["signup"].get("error"),
            "login_record": s["login"].get("record", {}),
            "signup_record": s["signup"].get("record", {}),
            "manual_structured": s["manual"].get("structured", {}),
        }
        cur.execute("""
            INSERT INTO sites VALUES (
                ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
            )
        """, (
            s["hostname"], s["url"], json.dumps(s["keywords"], ensure_ascii=False),
            s.get("version", ""),
            s["login"]["flow_type"], s["login"]["flow_zh"], s["login"]["route"],
            s["login"]["fields"], s["login"]["blockers"], s["login"]["final_url"],
            s["login"]["measured_at"],
            s["signup"]["flow_type"], s["signup"]["flow_zh"], s["signup"]["route"],
            s["signup"]["fields"], s["signup"]["blockers"], s["signup"]["final_url"],
            s["signup"]["measured_at"],
            s["manual"]["login"], s["manual"]["signup"], s["manual"]["note"],
            int(s["manual"]["verified"]), s["match_status"],
            s["manual"]["pwd_testability"].get("login", ""),
            s["manual"]["pwd_testability"].get("signup", ""),
            s["manual"]["pwd_testability"].get("overall", ""),
            json.dumps(details, ensure_ascii=False),
        ))
    cur.execute(
        "CREATE INDEX idx_hostname ON sites(hostname);"
    )
    if history:
        cur.executemany(
            "INSERT INTO site_history (hostname, entry_kind, version, flow_type, "
            "stop_reason, primary_method, route, measured_at, details_json) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            [(h["hostname"], h["entry_kind"], h["version"], h["flow_type"],
              h["stop_reason"], h["primary_method"], h["route"],
              h["measured_at"], h["details_json"])
             for h in history],
        )
    if pending_rows:
        columns = (
            "id", "hostname", "login", "signup", "note", "submitter",
            "review_type", "submitted_at", "structured_json")
        cur.executemany(
            "INSERT INTO reviews_pending (" + ",".join(columns) + ") "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            [tuple(row.get(column, "{}" if column == "structured_json" else "")
                   for column in columns)
             for row in pending_rows],
        )
    conn.commit()
    conn.close()
    os.replace(build_path, db_path)


def _load_old_db_records(db_path):
    """把旧 SQLite sites 表里的完整原记录（details_json.login_record 等）
    取回作为历史候选，使版本升级后旧版结果能进 site_history 表。"""
    if not os.path.exists(db_path):
        return []
    records = []
    try:
        with sqlite3.connect(db_path, timeout=15) as old:
            old.row_factory = sqlite3.Row
            rows = old.execute(
                "SELECT hostname, details_json FROM sites").fetchall()
            for row in rows:
                details = json.loads(row["details_json"] or "{}")
                for kind in ("login", "signup"):
                    rec = details.get(kind + "_record")
                    if isinstance(rec, dict) and rec.get("hostname"):
                        rec.setdefault("entry_kind", kind)
                        records.append(rec)
    except (sqlite3.DatabaseError, json.JSONDecodeError):
        pass
    return records


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", action="append", default=[],
                    help="JSONL 结果文件（可多个：后传入的视为更新版本）")
    ap.add_argument("--manual", default="misc/manual_review.json")
    ap.add_argument("--keywords", default="misc/site_keywords.json")
    ap.add_argument("--output", default="webapp/sites.db")
    args = ap.parse_args()

    # server_sync.sh already owns this lock and advertises that via the env;
    # direct/manual rebuilds take it here so pending submissions cannot arrive
    # between the backup read and atomic database replacement.
    lock_path = Path(os.environ.get(
        "SITES_DATA_LOCK", str(_PROJECT_ROOT / "webapp" / ".data-sync.lock")))
    lock = (nullcontext() if os.environ.get("SITES_SYNC_LOCK_HELD") == "1"
            else coordinated_data_lock(lock_path))
    with lock:
        inputs = args.input or ["reports/sites/sites_latest.jsonl"]
        # 自动加载 reports/archive/v*_official_*.jsonl 官方历史版本，
        # 使版本升级后旧版全量结果能完整进入 site_history 表
        import glob as _glob
        for path in sorted(_glob.glob(
                os.path.join(_PROJECT_ROOT, "reports", "archive",
                             "v*_official_*.jsonl"))):
            if path not in inputs:
                inputs.append(path)
        groups = load_records(inputs)
        for rec in _load_old_db_records(args.output):
            groups[rec["hostname"]][rec["entry_kind"]].append(rec)
        print(f"加载 {sum(len(k) for h in groups for k in groups[h].values())} 条测量记录（{len(inputs)} 个文件）")
        sites = attach_manual(build_sites(groups), args.manual, args.keywords)
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        history = build_history(groups, sites)
        create_db(sites, args.output, history=history)
        verified = sum(1 for s in sites if s["match_status"] == "manual_verified")
        print(f"已写入 {args.output}: {len(sites)} 站，人工已核验 {verified} 站，"
              f"历史版本 {len(history)} 条")


if __name__ == "__main__":
    main()
