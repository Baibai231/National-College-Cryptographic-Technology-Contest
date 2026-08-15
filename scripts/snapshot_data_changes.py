"""Snapshot only web-created data changes relative to the current Git HEAD."""
import argparse
import json
import subprocess
from pathlib import Path


def records_by_key(text):
    records = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        key = (record.get("hostname"), record.get("entry_kind"))
        if all(key):
            records[key] = record
    return records


def record_delta(current_text, base_text):
    current = records_by_key(current_text)
    base = records_by_key(base_text)
    return [record for key, record in current.items()
            if base.get(key) != record]


def manual_delta(current, base):
    current_sites = current.get("sites") or {}
    base_sites = base.get("sites") or {}
    changed = {hostname: entry for hostname, entry in current_sites.items()
               if base_sites.get(hostname) != entry}
    delta = {"sites": changed}
    if changed and current.get("updated_at"):
        delta["updated_at"] = current["updated_at"]
    return delta


def git_text(project_root, ref, relative_path):
    result = subprocess.run(
        ["git", "show", f"{ref}:{relative_path}"], cwd=project_root,
        check=False, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        message = (result.stderr or "git show failed").strip()
        raise RuntimeError(
            f"无法读取同步基线 {ref}:{relative_path}，为避免全量误回放已中止: "
            f"{message}"
        )
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", default="reports/sites/sites_latest.jsonl")
    parser.add_argument("--manual", default="misc/manual_review.json")
    parser.add_argument("--output-records", required=True)
    parser.add_argument("--output-manual", required=True)
    parser.add_argument("--base-ref", default="HEAD")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    records_path = Path(args.records)
    manual_path = Path(args.manual)
    current_records = records_path.read_text(encoding="utf-8")
    base_records = git_text(root, args.base_ref, args.records)
    changed_records = record_delta(current_records, base_records)

    current_manual = json.loads(manual_path.read_text(encoding="utf-8"))
    base_manual_text = git_text(root, args.base_ref, args.manual)
    base_manual = json.loads(base_manual_text) if base_manual_text.strip() else {}
    changed_manual = manual_delta(current_manual, base_manual)

    Path(args.output_records).write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n"
                for record in changed_records), encoding="utf-8")
    Path(args.output_manual).write_text(
        json.dumps(changed_manual, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print(
        f"快照网页增量：程序 {len(changed_records)} 条，"
        f"人工 {len(changed_manual['sites'])} 站"
    )


if __name__ == "__main__":
    main()
