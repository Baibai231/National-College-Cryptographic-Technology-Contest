#!/usr/bin/env python3
"""Evaluate password-strength-meter datasets with USENIX Security 2023 metrics.

Input is JSON or JSONL.  WSpearman rows contain reference_rank, meter_rank and
frequency.  Offline KL rows contain attack_strategy, meter_bucket, cracked and
optional count.  Precision rows contain meter_bin (low/high) and cracked.
Only aggregated metric values are printed; this tool never needs raw passwords.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application_security.password_meter_evaluation import (  # noqa: E402
    PASSWORD_METER_MANIFEST,
    evaluate_paper_metrics,
)


def _load_rows(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("["):
        value = json.loads(text)
        if not isinstance(value, list):
            raise ValueError("JSON input must be an array")
        return [row for row in value if isinstance(row, dict)]
    rows = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"line {line_number} is not a JSON object")
        rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(
        description="USENIX Security 2023 password-meter evaluation metrics")
    parser.add_argument("input", type=Path, help="labelled JSON/JSONL dataset")
    parser.add_argument(
        "--beta", type=float, default=0.8,
        help="PrecisionSecurity risk weight (paper default: 0.8)")
    args = parser.parse_args()
    rows = _load_rows(args.input)
    result = {
        "module": PASSWORD_METER_MANIFEST.module_id,
        "paper": PASSWORD_METER_MANIFEST.paper_refs[0].to_dict(),
        "sample_total": len(rows),
        "metrics": evaluate_paper_metrics(rows, beta=args.beta),
        "note": (
            "Weighted Spearman needs ranks+frequency; offline KL needs "
            "attack_strategy+meter_bucket+cracked; Precision metrics need "
            "low/high bins+cracked ground truth. Missing inputs remain null."
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
