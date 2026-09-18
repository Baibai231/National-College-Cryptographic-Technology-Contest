"""ZipfGuard command line demo.

Examples (from the ZipfGuard directory)::

    python run_demo.py --json-out reports/demo.json --report-out reports/demo.md
    python run_demo.py --input demo_data/synthetic_counts.json
"""
from __future__ import annotations

import argparse
from pathlib import Path

from core.data import load_count_json, write_count_json
from core.rockyou import aggregate_rockyou
from experiments.pipeline import render_markdown, run_pipeline, write_json, write_report


def main() -> int:
    parser = argparse.ArgumentParser(description="ZipfGuard DP-HTPG offline demo")
    parser.add_argument("--input", type=Path, help="aggregate count JSON")
    parser.add_argument("--rockyou", type=Path, help="Rockyou-style line file; only aggregate counts are retained")
    parser.add_argument("--max-lines", type=int, default=1_000_000)
    parser.add_argument("--top-k", type=int, default=2_000)
    parser.add_argument("--json-out", type=Path, default=Path("reports/demo.json"))
    parser.add_argument("--report-out", type=Path, default=Path("reports/demo.md"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--bootstrap", type=int, default=120)
    parser.add_argument("--synthetic-size", type=int, default=20_000)
    parser.add_argument("--synthetic-exponent", type=float, default=1.08)
    args = parser.parse_args()
    if args.input and args.rockyou:
        parser.error("--input 与 --rockyou 只能选择一个")
    if args.rockyou:
        payload = aggregate_rockyou(args.rockyou, max_lines=args.max_lines, top_k=args.top_k)
        result = run_pipeline(payload, seed=args.seed, bootstrap_repetitions=args.bootstrap)
    elif args.input:
        payload = load_count_json(args.input)
        result = run_pipeline(payload, seed=args.seed, bootstrap_repetitions=args.bootstrap)
    else:
        result = run_pipeline(
            seed=args.seed,
            bootstrap_repetitions=args.bootstrap,
            synthetic_size=args.synthetic_size,
            synthetic_exponent=args.synthetic_exponent,
        )
        payload = result["dataset"]
    if not args.input and not args.rockyou:
        write_count_json(payload, Path("demo_data/synthetic_counts.json"))
    elif args.rockyou:
        write_count_json(payload, Path("demo_data/rockyou_counts.json"))
    write_json(result, args.json_out)
    write_report(result, args.report_out)
    print(render_markdown(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
