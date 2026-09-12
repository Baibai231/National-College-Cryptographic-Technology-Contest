"""One-click Cloudflare Radar ranking -> policy measurement pipeline.

The Cloudflare Radar API exposes an ordered top list (up to 100 domains) and
larger, unordered ranking buckets such as ``ranking_top_1000``.  This script
selects the smallest suitable source, records its provenance, runs the cheap
HTTP preflight, and optionally launches the existing browser measurement.

Safe default: without ``--measure-policy`` this command only downloads the
ranking and performs read-only preflight.  Active password probes require an
owner-provided ``--authorization-manifest`` and still inherit the project's
no-submit/no-OTP/no-CAPTCHA boundary.
"""
import argparse
import csv
import hashlib
import io
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.build_target_corpus import load_supplements, normalize_domain


RADAR_API_BASE = "https://api.cloudflare.com/client/v4"
RANKING_BUCKETS = (100, 200, 500, 1000, 2000, 5000, 10000, 20000,
                   50000, 100000, 200000, 500000, 1000000)
MAX_RESPONSE_BYTES = 64 * 1024 * 1024


def _bucket_for(top: int) -> int:
    for bucket in RANKING_BUCKETS:
        if bucket >= top:
            return bucket
    raise ValueError("Cloudflare Radar 最大支持 top 1000000")


def _download(url: str, token: str, timeout: int) -> bytes:
    request = Request(url, headers={
        "Accept": "application/json,text/plain;q=0.9,*/*;q=0.1",
        "Authorization": "Bearer " + token,
        "User-Agent": "CryptoScope-Cloudflare-Radar/1.0",
    })
    with urlopen(request, timeout=timeout) as response:
        data = response.read(MAX_RESPONSE_BYTES + 1)
    if len(data) > MAX_RESPONSE_BYTES:
        raise ValueError("Cloudflare Radar 响应超过安全大小上限")
    return data


def _parse_top_payload(payload: Mapping[str, Any], limit: int) -> List[Dict[str, Any]]:
    if payload.get("success") is False:
        errors = payload.get("errors") or []
        raise RuntimeError("Cloudflare Radar API 错误: {}".format(
            "; ".join(str(item) for item in errors)[:500]))
    result = payload.get("result") or {}
    raw_items = result.get("top_0") or []
    if not isinstance(raw_items, list):
        raise ValueError("Cloudflare Radar top_0 格式无效")
    selected: List[Dict[str, Any]] = []
    seen = set()
    for index, item in enumerate(raw_items, 1):
        if not isinstance(item, Mapping):
            continue
        domain = normalize_domain(str(item.get("domain") or ""))
        if not domain or domain in seen:
            continue
        raw_rank = item.get("rank")
        try:
            rank = int(raw_rank) if raw_rank is not None else index
        except (TypeError, ValueError):
            rank = index
        selected.append({"domain": domain, "rank": rank})
        seen.add(domain)
        if len(selected) >= limit:
            break
    if len(selected) < limit:
        raise RuntimeError(
            "Cloudflare Radar 有序榜单有效域名不足: 需要 {}, 得到 {}".format(
                limit, len(selected)))
    return selected


def _parse_dataset_payload(data: bytes, limit: int) -> List[Dict[str, Any]]:
    """Parse the documented newline dataset, tolerating CSV/JSON variants."""
    text = data.decode("utf-8-sig", errors="replace")
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, Mapping):
            items = payload.get("domains") or payload.get("top_0") or []
        elif isinstance(payload, list):
            items = payload
        else:
            items = []
        if items:
            rows = []
            for item in items:
                if isinstance(item, Mapping):
                    rows.append(str(item.get("domain") or ""))
                else:
                    rows.append(str(item))
        else:
            rows = []
    else:
        rows = []
        for row in csv.reader(io.StringIO(text)):
            if not row:
                continue
            # Accept both ``domain`` and ``rank,domain`` representations.
            value = row[1] if len(row) >= 2 and row[0].strip().isdigit() else row[0]
            if value.strip().lower() in {"domain", "domains"}:
                continue
            rows.append(value)

    selected: List[Dict[str, Any]] = []
    seen = set()
    for value in rows:
        domain = normalize_domain(value.strip())
        if not domain or domain in seen:
            continue
        # The bucket is documented as unordered.  Do not present the stable
        # file position as a popularity rank; it is only a reproducible order.
        selected.append({"domain": domain, "rank": None,
                         "bucket_position": len(selected) + 1})
        seen.add(domain)
        if len(selected) >= limit:
            break
    if len(selected) < limit:
        raise RuntimeError(
            "Cloudflare Radar 数据集有效域名不足: 需要 {}, 得到 {}".format(
                limit, len(selected)))
    return selected


def fetch_ranking(token: str, top: int, ranking_type: str = "POPULAR",
                  location: str = "", timeout: int = 60
                  ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Fetch a ranking and return domains plus auditable provenance."""
    if top <= 0:
        raise ValueError("top 必须大于 0")
    ranking_type = ranking_type.upper()
    if ranking_type not in {"POPULAR", "TRENDING_RISE", "TRENDING_STEADY"}:
        raise ValueError("不支持的 Cloudflare Radar ranking_type")
    location = (location or "").strip().upper()
    if top <= 100:
        query = {"name": "top", "limit": str(top),
                 "rankingType": ranking_type, "format": "JSON"}
        if location:
            query["location"] = location
        url = RADAR_API_BASE + "/radar/ranking/top?" + urlencode(query)
        body = _download(url, token, timeout)
        payload = json.loads(body.decode("utf-8"))
        domains = _parse_top_payload(payload, top)
        provenance = {
            "kind": "ordered_top",
            "endpoint": url,
            "ranking_type": ranking_type,
            "location": location or None,
            "requested_top": top,
            "ordered_rank": True,
        }
    else:
        if ranking_type != "POPULAR" or location:
            raise ValueError(
                "Cloudflare Radar 大于100的 bucket 仅支持全球 POPULAR 排行")
        bucket = _bucket_for(top)
        url = RADAR_API_BASE + "/radar/datasets/ranking_top_{}".format(bucket)
        body = _download(url, token, timeout)
        domains = _parse_dataset_payload(body, top)
        provenance = {
            "kind": "unordered_bucket",
            "endpoint": url,
            "ranking_type": ranking_type,
            "location": None,
            "requested_top": top,
            "dataset_bucket": bucket,
            "ordered_rank": False,
            "ordering_note": "bucket 数据集按文档为无序；bucket_position 不是流行度排名",
        }
    provenance["response_sha256"] = hashlib.sha256(body).hexdigest()
    provenance["retrieved_at"] = datetime.now(timezone.utc).isoformat()
    return domains, provenance


def build_radar_entries(ranked: Iterable[Mapping[str, Any]],
                       supplements: Iterable[Tuple[str, str]] = ()) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    seen = set()
    for item in ranked:
        domain = normalize_domain(str(item.get("domain") or ""))
        if not domain or domain in seen:
            continue
        entry: Dict[str, Any] = {
            "domain": domain,
            "url": "https://{}/".format(domain),
            "source": "cloudflare_radar",
            "rank": item.get("rank"),
        }
        if item.get("bucket_position") is not None:
            entry["bucket_position"] = item["bucket_position"]
        entries.append(entry)
        seen.add(domain)
    for domain, source_path in supplements:
        if domain in seen:
            continue
        entries.append({
            "domain": domain,
            "url": "https://{}/".format(domain),
            "source": "supplement",
            "source_path": source_path,
            "rank": None,
        })
        seen.add(domain)
    return entries


def _write_targets(output_dir: Path, entries: Sequence[Mapping[str, Any]],
                   provenance: Mapping[str, Any], supplements: Sequence[Path]) -> Dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    targets = output_dir / "targets.txt"
    metadata = output_dir / "targets.json"
    snapshot = output_dir / "radar_snapshot.json"
    targets.write_text("".join(str(item["url"]) + "\n" for item in entries),
                       encoding="utf-8")
    payload = {
        "schema_version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sources": {"cloudflare_radar": dict(provenance),
                    "supplements": [str(path) for path in supplements]},
        "selection": {
            "total_distinct_domains": len(entries),
            "ranking_domains": sum(
                1 for item in entries if item.get("source") == "cloudflare_radar"),
            "supplement_domains": sum(
                1 for item in entries if item.get("source") == "supplement"),
        },
        "entries": list(entries),
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    metadata.write_text(text, encoding="utf-8")
    snapshot.write_text(json.dumps({
        "schema_version": "1.0",
        "provenance": dict(provenance),
        "ranked": [dict(item) for item in entries
                   if item.get("source") == "cloudflare_radar"],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"targets": targets, "metadata": metadata, "snapshot": snapshot}


def _run_stage(label: str, command: Sequence[str], dry_run: bool = False) -> None:
    print("\n[{}] {}".format(label, " ".join(command)))
    if not dry_run:
        subprocess.run(list(command), cwd=str(_PROJECT_ROOT), check=True)


def _load_snapshot(path: Path) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    ranked = payload.get("ranked")
    provenance = payload.get("provenance") or {}
    if not isinstance(ranked, list) or not isinstance(provenance, Mapping):
        raise ValueError("Radar snapshot 格式无效")
    return [dict(item) for item in ranked], dict(provenance)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=int, default=1000,
                        help="目标域名数；>100 自动使用 Radar ranking bucket（默认1000）")
    parser.add_argument("--ranking-type", default="POPULAR",
                        choices=("POPULAR", "TRENDING_RISE", "TRENDING_STEADY"))
    parser.add_argument("--location", default="",
                        help="Top 100 地区 alpha-2 代码，例如 CN；bucket 模式不支持")
    parser.add_argument("--supplement", action="append", default=[], type=Path,
                        help="补充域名清单，可重复")
    parser.add_argument("--output-dir", type=Path,
                        default=Path(".cache/target-corpora/cloudflare-radar"))
    parser.add_argument("--snapshot", type=Path,
                        help="离线复用此前生成的 radar_snapshot.json，不访问 Radar API")
    parser.add_argument("--api-token-env", default="CLOUDFLARE_API_TOKEN",
                        help="读取 Cloudflare API Token 的环境变量名")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--preflight-workers", type=int, default=16)
    parser.add_argument("--browser-workers", type=int, default=2)
    parser.add_argument("--site-timeout", type=int, default=900)
    parser.add_argument("--max-pages", type=int, default=3)
    parser.add_argument("--min-priority", type=int, default=0)
    parser.add_argument("--max-sites", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--measure-policy", action="store_true",
                        help="预筛后启动主动口令策略测量；必须同时提供授权清单")
    parser.add_argument("--authorization-manifest", default="",
                        help="站点所有者授权清单；主动测量必填")
    parser.add_argument("--headed", action="store_true",
                        help="禁用无头浏览器（默认无头）")
    parser.add_argument("--resume", action="store_true",
                        help="复用 preflight/policy JSONL 中的已完成记录")
    parser.add_argument("--skip-preflight", action="store_true",
                        help="跳过预筛，要求 output-dir 中已有 candidates.jsonl")
    parser.add_argument("--require-complete", type=int, default=0,
                        help="报告少于该完整站点数时返回2；例如1000")
    parser.add_argument("--dry-run", action="store_true",
                        help="只生成榜单文件并打印后续命令，不启动预筛/浏览器")
    args = parser.parse_args(argv)

    if args.top <= 0 or args.timeout <= 0 or args.preflight_workers <= 0 \
            or args.browser_workers <= 0 or args.site_timeout <= 0 \
            or args.max_pages <= 0 or args.min_priority < 0 \
            or args.max_sites < 0:
        parser.error("top、timeout、workers、site-timeout、max-pages 必须大于0；其余规模参数不能为负")
    if args.shard_count <= 0 or args.shard_index < 0 \
            or args.shard_index >= args.shard_count:
        parser.error("shard-index 必须位于 0 到 shard-count-1")
    if args.measure_policy and not args.authorization_manifest:
        parser.error("--measure-policy 必须同时指定 --authorization-manifest")
    authorization_manifest = None
    if args.authorization_manifest:
        authorization_manifest = Path(args.authorization_manifest)
        if not authorization_manifest.is_absolute():
            authorization_manifest = _PROJECT_ROOT / authorization_manifest
    if args.measure_policy and not authorization_manifest.is_file():
        parser.error("授权范围文件不存在: {}".format(authorization_manifest))
    snapshot_path = None
    if args.snapshot:
        snapshot_path = args.snapshot if args.snapshot.is_absolute() \
            else _PROJECT_ROOT / args.snapshot
        if not snapshot_path.is_file():
            parser.error("snapshot 文件不存在: {}".format(snapshot_path))
    if args.skip_preflight and snapshot_path is None:
        parser.error("--skip-preflight 必须同时指定 --snapshot，以避免榜单更新后复用不匹配的候选")

    output_dir = args.output_dir
    if not output_dir.is_absolute():
        output_dir = _PROJECT_ROOT / output_dir
    supplement_paths = [
        path if path.is_absolute() else _PROJECT_ROOT / path
        for path in args.supplement
    ]
    for path in supplement_paths:
        if not path.is_file():
            parser.error("补充清单不存在: {}".format(path))

    if snapshot_path:
        ranked, provenance = _load_snapshot(snapshot_path)
    else:
        token = os.environ.get(args.api_token_env, "").strip()
        if not token:
            parser.error("未找到 {}；请将 Cloudflare API Token 放入环境变量，不要写进命令行或代码"
                         .format(args.api_token_env))
        try:
            ranked, provenance = fetch_ranking(
                token, args.top, args.ranking_type, args.location, args.timeout)
        except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
            parser.error("获取 Cloudflare Radar 排行榜失败: {}".format(exc))

    if len(ranked) < args.top:
        parser.error("snapshot 中有效域名不足: 需要{}，得到{}".format(args.top, len(ranked)))
    ranked = ranked[:args.top]
    supplements = load_supplements(supplement_paths)
    entries = build_radar_entries(ranked, supplements)
    paths = _write_targets(output_dir, entries, provenance, supplement_paths)
    print("生成 {} 个不同域名；Radar 来源={}；输出目录={}".format(
        len(entries), provenance.get("kind"), output_dir))

    preflight = output_dir / "preflight.jsonl"
    candidates = output_dir / "candidates.jsonl"
    policy = output_dir / "policy.jsonl"
    coverage_json = output_dir / "coverage.json"
    coverage_md = output_dir / "coverage.md"

    if not args.skip_preflight:
        command = [sys.executable, str(_PROJECT_ROOT / "scripts" / "preflight_targets.py"),
                   "--metadata", str(paths["metadata"]), "--output", str(preflight),
                   "--candidates", str(candidates), "--workers", str(args.preflight_workers),
                   "--max-pages", str(args.max_pages)]
        if args.resume:
            command.append("--resume")
        _run_stage("preflight", command, args.dry_run)
    elif not candidates.is_file() and not args.dry_run:
        parser.error("--skip-preflight 时找不到 candidates.jsonl: {}".format(candidates))

    if not args.measure_policy:
        print("\n预筛完成；未启动主动口令策略测量。需要在授权范围内继续时，追加：")
        print("  --measure-policy --authorization-manifest <scope.json>")
        return 0

    command = [sys.executable, str(_PROJECT_ROOT / "scripts" / "run_measurement.py"),
               "--preflight-candidates", str(candidates), "--kinds", "signup",
               "--measure-policy", "--authorization-manifest",
               str(authorization_manifest), "--output", str(policy),
               "--workers", str(args.browser_workers), "--site-timeout",
               str(args.site_timeout), "--checkpoint-every", "25"]
    if not args.headed:
        command.append("--headless")
    if args.resume:
        command.extend(["--resume", "--resume-mode", "complete"])
    if args.min_priority:
        command.extend(["--min-priority", str(args.min_priority)])
    if args.max_sites:
        command.extend(["--max-sites", str(args.max_sites)])
    if args.shard_count != 1:
        command.extend(["--shard-count", str(args.shard_count),
                        "--shard-index", str(args.shard_index)])
    _run_stage("policy", command, args.dry_run)

    report = [sys.executable, str(_PROJECT_ROOT / "scripts" / "report_policy_coverage.py"),
              str(policy), "--json", str(coverage_json), "--markdown", str(coverage_md)]
    if args.require_complete:
        report.extend(["--require-complete", str(args.require_complete)])
    if args.dry_run:
        _run_stage("coverage", report, True)
        return 0
    result = subprocess.run(report, cwd=str(_PROJECT_ROOT), check=False)
    if result.returncode not in (0, 2):
        return result.returncode
    if result.returncode == 2:
        print("[coverage] 当前完整站点数尚未达到 require-complete，结果已保留，可用 --resume 续跑")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
