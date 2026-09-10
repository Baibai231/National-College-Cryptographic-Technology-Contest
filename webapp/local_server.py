"""Local-only Uvicorn launcher with an owner-verifiable PID record."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

import uvicorn


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _pid_record():
    return {
        "pid": os.getpid(),
        "project_root": str(PROJECT_ROOT),
        "executable": sys.executable,
        "base_executable": getattr(sys, "_base_executable", sys.executable),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the local CryptoScope dashboard")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--pid-file", required=True)
    args = parser.parse_args(argv)

    pid_path = Path(args.pid_file).resolve()
    record = _pid_record()
    pid_path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    try:
        uvicorn.run("webapp.app:app", host="127.0.0.1", port=args.port)
    finally:
        try:
            current = json.loads(pid_path.read_text(encoding="utf-8"))
            if current.get("pid") == record["pid"]:
                pid_path.unlink(missing_ok=True)
        except (OSError, ValueError, TypeError):
            pass


if __name__ == "__main__":
    main()
