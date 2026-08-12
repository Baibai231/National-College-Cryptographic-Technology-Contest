"""批量分类国内网站（login+signup），只观察不测政策。

用法:
  .venv/bin/python scripts/run_cn60_classify.py --kinds signup,login \
      --output reports/cn60_classify_20260812.jsonl --workers 3
  # 续跑（跳过已有记录）
  .venv/bin/python scripts/run_cn60_classify.py --output reports/cn60_classify_20260812.jsonl --resume

安全边界：与单站诊断一致——不填字段、不点发送验证码、不提交、不创建账号。
"""
import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.parse import urlparse

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from utils.util_test_password import _get_new_driver
from utils.login_link_discovery import LoginLinkDiscovery
from signup_flow_classifier.classifier_engine import SignupFlowClassifierEngine


def classify_one(site: str, kind: str) -> dict:
    driver = None
    record = {
        "site": site,
        "hostname": urlparse(site).hostname or site,
        "entry_kind": kind,
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "flow_type": None, "confidence": None, "stop_reason": None,
        "primary_method": None, "ui_type": None, "final_url": None,
        "states": [], "policy": {}, "evidence": [], "error": None,
    }
    try:
        driver = _get_new_driver()
        discovery = LoginLinkDiscovery(driver)
        signup_url = discovery.navigate_to_signup(site)
        engine = SignupFlowClassifierEngine(driver)
        if not signup_url:
            signup_url = driver.current_url
        entry_clicked = getattr(discovery, "_entry_clicked", False)
        result = engine.classify(
            signup_url, entry_kind=kind,
            entry_already_clicked=bool(entry_clicked and kind == "signup"),
        )
        record["flow_type"] = result.get("flow_type")
        record["confidence"] = result.get("confidence")
        record["stop_reason"] = result.get("stop_reason")
        record["primary_method"] = result.get("primary_method")
        record["ui_type"] = result.get("ui_type")
        record["final_url"] = result.get("final_url")
        record["states"] = result.get("states", [])
        record["policy"] = result.get("policy", {})
        record["evidence"] = result.get("evidence", [])
        record["start_url"] = result.get("start_url")
    except Exception as exc:
        record["error"] = "{}:{}".format(type(exc).__name__, str(exc)[:200])
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
    return record


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", default="misc/cn_sites_60.txt")
    ap.add_argument("--kinds", default="signup,login",
                    help="逗号分隔入口类型")
    ap.add_argument("--output", required=True)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--resume", action="store_true",
                    help="跳过输出文件中已存在的 (site, entry_kind) 记录")
    ap.add_argument("--only", default="", help="只跑逗号分隔的主机名子集")
    args = ap.parse_args()

    with open(args.input, encoding="utf-8") as handle:
        sites = [line.strip() for line in handle
                 if line.strip() and not line.lstrip().startswith("#")]
    if args.only:
        only = {h.strip() for h in args.only.split(",") if h.strip()}
        sites = [s for s in sites
                 if (urlparse(s).hostname or "") in only]

    kinds = [k.strip() for k in args.kinds.split(",") if k.strip()]
    tasks = [(s, k) for s in sites for k in kinds]

    done = set()
    if args.resume and os.path.isfile(args.output):
        with open(args.output, encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                    done.add((r.get("site"), r.get("entry_kind")))
                except json.JSONDecodeError:
                    continue
        print(f"[resume] 已存在 {len(done)} 条记录，跳过")

    pending = [t for t in tasks if t not in done]
    print(f"总任务 {len(tasks)}，待跑 {len(pending)}，并发 {args.workers}")

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    fail = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(classify_one, s, k): (s, k)
                   for s, k in pending}
        for i, future in enumerate(as_completed(futures), 1):
            site, kind = futures[future]
            try:
                rec = future.result()
            except Exception as exc:
                rec = {"site": site, "entry_kind": kind,
                       "error": "{}:{}".format(type(exc).__name__, str(exc)[:200])}
            with open(args.output, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            host = urlparse(site).hostname or site
            status = "✗" if rec.get("error") else "✓"
            print(f"[{i}/{len(pending)}] {status} {host} {kind} "
                  f"-> {rec.get('flow_type')} ({rec.get('stop_reason')})")
            if rec.get("error"):
                fail += 1
    elapsed = time.time() - t0
    print(f"\n完成。失败 {fail}/{len(pending)}，耗时 {elapsed:.0f} 秒。"
          f"\n结果已写入 {args.output}")


if __name__ == "__main__":
    main()
