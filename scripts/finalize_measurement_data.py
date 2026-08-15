"""Promote a completed measurement under the shared web/sync data lock."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.site_data_store import coordinated_data_lock, upsert_records


def finalize(records_path: Path | None, target: Path, *, lock_path: Path,
             profiles_dir: Path, summary: Path, database: Path) -> None:
    """Merge optional staging records, regenerate reports, then rebuild SQLite."""
    with coordinated_data_lock(lock_path):
        if records_path is not None:
            records = [
                json.loads(line) for line in
                records_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            result = upsert_records(target, records)
            print(f"合并完整测量 {len(records)} 条，权威数据共 {result['total']} 条")

        env = os.environ.copy()
        env["SITES_DATA_LOCK"] = str(lock_path)
        env["SITES_SYNC_LOCK_HELD"] = "1"
        subprocess.run([
            sys.executable, "scripts/generate_profiles.py",
            "--results", str(target),
            "--profiles-dir", str(profiles_dir),
            "--summary", str(summary),
        ], cwd=_PROJECT_ROOT, env=env, check=True)
        subprocess.run([
            sys.executable, "scripts/build_site_database.py",
            "--input", str(target), "--output", str(database),
        ], cwd=_PROJECT_ROOT, env=env, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path,
                        help="completed staging JSONL to merge")
    parser.add_argument(
        "--target", type=Path,
        default=Path("reports/sites/sites_latest.jsonl"))
    parser.add_argument(
        "--lock", type=Path,
        default=_PROJECT_ROOT / "webapp" / ".data-sync.lock")
    parser.add_argument(
        "--profiles-dir", type=Path,
        default=Path("reports/sites/profiles"))
    parser.add_argument(
        "--summary", type=Path,
        default=Path("reports/sites/sites_summary.md"))
    parser.add_argument(
        "--database", type=Path, default=Path("webapp/sites.db"))
    args = parser.parse_args()
    finalize(args.records, args.target, lock_path=args.lock,
             profiles_dir=args.profiles_dir, summary=args.summary,
             database=args.database)


if __name__ == "__main__":
    main()
