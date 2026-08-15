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
import os
import sqlite3
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.site_data_store import coordinated_data_lock, upsert_manual_review


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="webapp/sites.db")
    ap.add_argument("--manual", default="misc/manual_review.json")
    ap.add_argument("--apply", action="store_true",
                    help="真正合并并删除待审核记录")
    args = ap.parse_args()

    lock_path = Path(os.environ.get(
        "SITES_DATA_LOCK", str(_PROJECT_ROOT / "webapp" / ".data-sync.lock")))
    with coordinated_data_lock(lock_path):
        conn = sqlite3.connect(args.db, timeout=15)
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, hostname, login, signup, note, submitter, "
                "review_type, submitted_at, structured_json "
                "FROM reviews_pending ORDER BY id")
            rows = cur.fetchall()
            if not rows:
                print("没有待审核的人工观察")
                return

            print(f"待审核 {len(rows)} 条:")
            for row in rows:
                (rid, host, login, signup, note, submitter, review_type,
                 submitted_at, _structured_json) = row
                print(f"  [{rid}] {host} 类型:{review_type or 'manual'} "
                      f"提交者:{submitter} {submitted_at}")
                if login:
                    print(f"      登录: {login[:60]}")
                if signup:
                    print(f"      注册: {signup[:60]}")
                if note:
                    print(f"      备注: {note[:60]}")

            if not args.apply:
                print("\n[预览模式] 核验内容后加 --apply 真正合并")
                return

            merged = feedback = 0
            for row in rows:
                (rid, host, login, signup, note, submitter, review_type,
                 submitted_at, structured_json) = row
                if review_type == "feedback":
                    feedback += 1
                else:
                    structured = json.loads(structured_json or "{}")
                    upsert_manual_review(
                        args.manual, host, login=login, signup=signup,
                        note=note, structured=structured,
                        reviewed_from=f"cli@{submitter or 'admin'}@{submitted_at}",
                    )
                    merged += 1
                cur.execute("DELETE FROM reviews_pending WHERE id = ?", (rid,))
            conn.commit()
        finally:
            conn.close()
    print(f"已合并 {merged} 条到 {args.manual}")
    if feedback:
        print(f"已标记处理 {feedback} 条识别反馈（未写入人工核验）")
    print("下一步: .venv/bin/python scripts/build_site_database.py && ./webapp/run_server.sh 8000")


if __name__ == "__main__":
    main()
