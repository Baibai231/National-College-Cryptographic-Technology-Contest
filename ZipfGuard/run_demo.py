"""ZipfGuard command line demo.

Examples (from the ZipfGuard directory)::

    python run_demo.py --json-out reports/demo.json --report-out reports/demo.md
    python run_demo.py --input demo_data/synthetic_counts.json
"""
from __future__ import annotations

import argparse
from pathlib import Path

from ai.pcfg_adapter import PCFGConfig
from experiments.config import load_config
from core.data import load_count_json, write_count_json
from core.rockyou import aggregate_rockyou
from experiments.pipeline import render_markdown, run_pipeline, write_json, write_report


def main() -> int:
    parser = argparse.ArgumentParser(description="ZipfGuard DP-HTPG offline demo")
    parser.add_argument("--config", type=Path, help="完整实验配置 JSON")
    parser.add_argument("--preset", choices=["quick", "full"], default="quick")
    parser.add_argument("--budgets", help="逗号分隔攻击预算")
    parser.add_argument("--source-semantics", choices=["unknown", "frequency", "unique_dictionary"], default="unknown")
    parser.add_argument("--input", type=Path, help="aggregate count JSON")
    parser.add_argument("--rockyou", type=Path, help="Rockyou-style line file; only aggregate counts are retained")
    parser.add_argument("--max-lines", type=int, default=1_000_000)
    parser.add_argument("--top-k", type=int, default=2_000)
    parser.add_argument("--json-out", type=Path, default=Path("reports/demo.json"))
    parser.add_argument("--report-out", type=Path, default=Path("reports/demo.md"))
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--bootstrap", type=int, default=None)
    parser.add_argument("--synthetic-size", type=int, default=None)
    parser.add_argument("--synthetic-exponent", type=float, default=None)
    parser.add_argument("--pcfg", action="store_true", default=None, help="启用外部 PCFG 结构化攻击器")
    parser.add_argument(
        "--pcfg-limit", type=int, default=None,
        help="PCFG 单次最大生成候选数（1..1000000）",
    )
    parser.add_argument("--pcfg-timeout", type=int, default=None, help="PCFG 训练或生成超时秒数")
    args = parser.parse_args()
    config = load_config(args.config, preset=args.preset)
    pcfg_config = PCFGConfig.workspace_default(
        generation_limit=args.pcfg_limit if args.pcfg_limit is not None else config["pcfg"]["generation_limit"],
        timeout_seconds=args.pcfg_timeout if args.pcfg_timeout is not None else config["pcfg"]["timeout_seconds"],
    )
    config["pcfg"].update(generation_limit=pcfg_config.generation_limit, timeout_seconds=pcfg_config.timeout_seconds)
    if args.budgets: config["budgets"] = [int(v) for v in args.budgets.split(",")]
    if args.input or args.rockyou: config["attackers"].pop("pcfg", None)
    if args.input and args.rockyou:
        parser.error("--input 与 --rockyou 只能选择一个")
    if args.rockyou:
        payload = aggregate_rockyou(args.rockyou, max_lines=args.max_lines, top_k=args.top_k, source_semantics=args.source_semantics)
        result = run_pipeline(
            payload, config=config, seed=args.seed, bootstrap_repetitions=args.bootstrap,
            include_pcfg=args.pcfg,
        )
    elif args.input:
        payload = load_count_json(args.input)
        result = run_pipeline(
            payload, config=config, seed=args.seed, bootstrap_repetitions=args.bootstrap,
            include_pcfg=args.pcfg,
        )
    else:
        result = run_pipeline(
            config=config, seed=args.seed,
            bootstrap_repetitions=args.bootstrap,
            synthetic_size=args.synthetic_size,
            synthetic_exponent=args.synthetic_exponent,
            include_pcfg=args.pcfg,
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
