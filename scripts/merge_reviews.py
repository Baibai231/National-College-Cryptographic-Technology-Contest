"""审核合并：组员提交的人工观察 → manual_review.json → 重建数据库。

用法:
  1. 在平台上查看 /api/reviews/pending 的待审核提交
  2. 人工核验内容无误后：
     .venv/bin/python scripts/merge_reviews.py --db webapp/sites.db \
         --manual misc/manual_review.json --apply
  3. 重建数据库并重启服务：
     .venv/bin/python scripts/build_site_database.py
     ./webapp/run_server.sh 8000

--apply 才会真正合并；不带 --apply 只打印待审核内容供核验。
"""
import argparse
import json
import sqlite3
from datetime import datetime, timezone


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="webapp/sites.db")
    ap.add_argument("--manual", default="misc/manual_review.json")
    ap.add_argument("--apply", action="store_true",
                    help="真正合并并删除待审核记录")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, hostname, login, signup, note, submitter, submitted_at "
        "FROM reviews_pending ORDER BY id")
    rows = cur.fetchall()
    if not rows:
        print("没有待审核的人工观察")
        return

    print(f"待审核 {len(rows)} 条:")
    for r in rows:
        print(f"  [{r[0]}] {r[1]} 提交者:{r[5]} {r[6]}")
        if r[2]:
            print(f"      登录: {r[2][:60]}")
        if r[3]:
            print(f"      注册: {r[3][:60]}")
        if r[4]:
            print(f"      备注: {r[4][:60]}")

    if not args.apply:
        print("\n[预览模式] 核验内容后加 --apply 真正合并")
        return

    with open(args.manual, encoding="utf-8") as f:
        manual = json.load(f)
    sites = manual["sites"]
    merged = 0
    for rid, host, login, signup, note, submitter, ts in rows:
        entry = sites.setdefault(host, {})
        if login:
            entry["manual_login"] = login
        if signup:
            entry["manual_signup"] = signup
        if note:
            entry["note"] = note
        entry["verified"] = True
        entry["reviewed_from"] = f"{submitter}@{ts}"
        merged += 1
        cur.execute("DELETE FROM reviews_pending WHERE id = ?", (rid,))
    manual["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(args.manual, "w", encoding="utf-8") as f:
        json.dump(manual, f, ensure_ascii=False, indent=2)
    conn.commit()
    conn.close()
    print(f"已合并 {merged} 条到 {args.manual}")
    print("下一步: .venv/bin/python scripts/build_site_database.py && ./webapp/run_server.sh 8000")


if __name__ == "__main__":
    main()
