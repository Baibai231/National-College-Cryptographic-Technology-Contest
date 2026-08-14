"""Merge a server snapshot back into the authoritative project data files."""
import argparse
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.site_data_store import merge_manual_reviews, upsert_records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", required=True, help="snapshot JSONL")
    parser.add_argument("--manual", required=True, help="snapshot manual JSON")
    parser.add_argument(
        "--target-records", default="reports/sites/sites_latest.jsonl")
    parser.add_argument(
        "--target-manual", default="misc/manual_review.json")
    args = parser.parse_args()

    records = [json.loads(line) for line in
               Path(args.records).read_text(encoding="utf-8").splitlines()
               if line.strip()]
    record_result = upsert_records(args.target_records, records)
    manual = json.loads(Path(args.manual).read_text(encoding="utf-8"))
    manual_result = merge_manual_reviews(args.target_manual, manual)
    print(
        f"回放程序记录 {len(records)} 条（总计 {record_result['total']}）；"
        f"人工核验更新 {manual_result['updated']} 站"
    )


if __name__ == "__main__":
    main()
