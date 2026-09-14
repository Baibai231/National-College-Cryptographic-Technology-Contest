"""批量分类国内网站（login+signup），只观察不测政策。

用法:
  .venv/bin/python scripts/run_measurement.py --kinds signup,login \
      --input misc/sites_base_60.txt --input misc/sites_extra_60.txt \
      --output reports/sites/sites_latest.jsonl --workers 3
  # 续跑（跳过已有记录）
  .venv/bin/python scripts/run_measurement.py --output reports/sites/sites_latest.jsonl --resume

安全边界：与单站诊断一致——不填字段、不点发送验证码、不提交、不创建账号。
"""
import argparse
import json
import multiprocessing
import os
import queue
import signal
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

_CURRENT_VERSION = "unknown"
_version_path = os.path.join(_PROJECT_ROOT, "misc", "measure_version.txt")
if os.path.isfile(_version_path):
    with open(_version_path, encoding="utf-8") as _fh:
        _CURRENT_VERSION = _fh.read().strip() or "unknown"


def classify_one(site: str, kind: str, measure_policy: bool = False) -> dict:
    driver = None
    record = {
        "site": site,
        "hostname": urlparse(site).hostname or site,
        "entry_kind": kind,
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "version": _CURRENT_VERSION,
        "flow_type": None, "confidence": None, "stop_reason": None,
        "primary_method": None, "ui_type": None, "final_url": None,
        "states": [], "policy": {}, "evidence": [], "error": None,
    }
    try:
        if measure_policy and kind == "signup":
            # 完整流程（分类 + 密码政策测量）：复用 main.test_single_site，
            # 它内部完成注册页发现→分类→inline 密码测量→(失败时)回退仅分类。
            # 此前 classify_one 只跑分类器，从不进入密码测量，导致批量结果
            # 的 policy 恒为空、method_used 恒为 None（154 站全量验证发现
            # 0 条含有效长度政策）。
            from main import test_single_site
            result = test_single_site(site, method="auto")
            for key in (
                "flow_type", "confidence", "stop_reason", "primary_method",
                "ui_type", "final_url", "states", "methods", "policy",
                "evidence", "method_used", "note", "error",
            ):
                if key in result:
                    record[key] = result[key]
            if not record.get("start_url") and result.get("final_url"):
                record["start_url"] = result["final_url"]
            return record
        # 口令政策目前只在注册路径上安全测量。批量任务同时请求 login 时，
        # login 仍执行独立登录分类；绝不能把第二次 signup 政策结果贴上 login
        # 标签（历史批次曾因此造成两侧结果高度相同）。
        driver = _get_new_driver()
        discovery = LoginLinkDiscovery(driver)
        if kind == "login":
            entry_url = discovery.navigate_to_login(site)
        else:
            entry_url = discovery.navigate_to_signup(site)
        engine = SignupFlowClassifierEngine(driver)
        if not entry_url:
            entry_url = driver.current_url
        entry_clicked = getattr(discovery, "_entry_clicked", False)
        result = engine.classify(
            entry_url, entry_kind=kind,
            entry_already_clicked=bool(entry_clicked and kind == "signup"),
        )
        record["flow_type"] = result.get("flow_type")
        record["confidence"] = result.get("confidence")
        record["stop_reason"] = result.get("stop_reason")
        record["primary_method"] = result.get("primary_method")
        record["ui_type"] = result.get("ui_type")
        record["final_url"] = result.get("final_url")
        record["states"] = result.get("states", [])
        record["methods"] = result.get("methods", [])
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


def _classify_worker(site: str, kind: str, result_queue,
                     measure_policy: bool = False) -> None:
    """隔离单站 Selenium；父进程可在超时时安全终止此子进程。"""
    def _terminate(_signum, _frame):
        raise TimeoutError("site watchdog terminated worker")

    try:
        signal.signal(signal.SIGTERM, _terminate)
    except (AttributeError, ValueError):
        pass
    try:
        result_queue.put(classify_one(site, kind, measure_policy=measure_policy))
    except BaseException as exc:
        result_queue.put({
            "site": site,
            "hostname": urlparse(site).hostname or site,
            "entry_kind": kind,
            "error": "{}:{}".format(type(exc).__name__, str(exc)[:200]),
        })
    finally:
        # 子进程只持有写端；显式关闭可避免长批次在 macOS 上累积 semaphore。
        try:
            result_queue.close()
            result_queue.cancel_join_thread()
        except Exception:
            pass


def _iter_with_site_timeout(tasks, workers: int, timeout_seconds: int,
                            measure_policy: bool = False):
    """并发执行任务并以进程级看门狗防止单站卡死整轮回归。

    Selenium 的线程无法强制中断，因此这里特意不用 ThreadPoolExecutor。
    每个子进程完成后由它自己的 finally 关闭 driver；超时时先发送 SIGTERM，
    让 worker 捕获并走 finally，然后才由父进程记录 site_timeout。
    """
    context = multiprocessing.get_context("spawn")
    pending = iter(tasks)
    active = {}
    exhausted = False

    def start_next():
        nonlocal exhausted
        if exhausted:
            return
        try:
            site, kind = next(pending)
        except StopIteration:
            exhausted = True
            return
        result_queue = context.Queue(maxsize=1)
        process = context.Process(
            target=_classify_worker,
            args=(site, kind, result_queue, measure_policy), daemon=False)
        process.start()
        active[process.pid] = {
            "process": process, "queue": result_queue, "site": site,
            "kind": kind, "started": time.monotonic(),
        }

    def stop_and_close(item):
        """Best-effort cleanup used on timeout, Ctrl-C and circuit breaking."""
        process = item["process"]
        try:
            if process.is_alive():
                process.terminate()
            process.join(timeout=5)
            if process.is_alive():
                process.kill()
                process.join(timeout=5)
        except Exception:
            pass
        try:
            item["queue"].close()
            item["queue"].join_thread()
        except Exception:
            pass
        try:
            process.close()
        except Exception:
            pass

    try:
        while len(active) < workers and not exhausted:
            start_next()

        while active:
            completed = []
            for pid, item in list(active.items()):
                process = item["process"]
                elapsed = time.monotonic() - item["started"]
                if process.is_alive() and elapsed < timeout_seconds:
                    continue

                timed_out = process.is_alive()
                if timed_out:
                    process.terminate()
                process.join(timeout=5)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=5)

                if timed_out:
                    record = {
                        "site": item["site"],
                        "hostname": urlparse(item["site"]).hostname or item["site"],
                        "entry_kind": item["kind"],
                        "error": "site_timeout:{}s".format(timeout_seconds),
                    }
                else:
                    try:
                        record = item["queue"].get(timeout=0.5)
                    except queue.Empty:
                        record = {
                            "site": item["site"],
                            "hostname": urlparse(item["site"]).hostname or item["site"],
                            "entry_kind": item["kind"],
                            "error": "worker_exited_without_result",
                        }
                stop_and_close(item)
                completed.append((pid, record))

            for pid, record in completed:
                active.pop(pid, None)
                yield record
                while len(active) < workers and not exhausted:
                    start_next()

            if not completed:
                time.sleep(0.2)
    finally:
        # Breaking the consumer loop used to leave already-started Chrome
        # workers alive.  Always reap them so a failed batch cannot keep
        # relaunching Chrome or leave stale chromedriver processes behind.
        for item in list(active.values()):
            stop_and_close(item)
        active.clear()


def _is_chrome_startup_failure(record: dict) -> bool:
    """Return True for infrastructure failures before a browser session exists."""
    error = str(record.get("error") or "").lower()
    markers = (
        "session not created",
        "cannot connect to chrome",
        "chrome not reachable",
        "failed to start chrome",
        "devtoolsactiveport file doesn't exist",
        "no such window: target window already closed",
    )
    return any(marker in error for marker in markers)


def _configure_browser_mode(args):
    """Choose a safe display mode for batch work and return a user note."""
    if args.headless:
        os.environ["SITES_HEADLESS"] = "1"
        return "已显式启用无头 Chrome"
    if args.headful:
        os.environ.pop("SITES_HEADLESS", None)
        if sys.platform == "darwin" and args.workers > 1:
            args.workers = 1
            return "macOS 有头 Chrome 已限制为单并发，避免 AppKit 启动崩溃"
        return "已显式启用有头 Chrome"
    if (sys.platform == "darwin" and args.workers > 1
            and not os.environ.get("SITES_HEADLESS")):
        # macOS 26 + Chrome 152 can SIGABRT in _RegisterApplication when
        # several GUI Chrome instances are launched together.  Bulk runs are
        # unattended and should mirror the server, so default them to headless.
        os.environ["SITES_HEADLESS"] = "1"
        return "macOS 并发批量任务自动使用无头 Chrome；人工观察请传 --headful"
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", action="append", default=[],
                    help="站点清单，可重复传入；自动按 hostname 去重")
    ap.add_argument("--kinds", default="signup,login",
                    help="逗号分隔入口类型")
    ap.add_argument("--output", required=True)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--resume", action="store_true",
                    help="跳过输出文件中已存在的 (site, entry_kind) 记录")
    ap.add_argument("--overwrite", action="store_true",
                    help="开始前清空输出文件；与 --resume 互斥")
    ap.add_argument("--only", default="", help="只跑逗号分隔的主机名子集")
    ap.add_argument("--measure-policy", action="store_true",
                    help="对分类出的注册口令框站点额外执行密码政策测量"
                         "（完整流程，每站 5-15 分钟；不带此开关只跑分类）")
    ap.add_argument("--retry-unknown", type=int, default=0,
                    help="主跑后对 unknown/error 记录自动重跑 N 轮并多数投票取稳定结果")
    ap.add_argument("--site-timeout", type=int, default=0,
                    help="单站进程级超时秒数；0 表示沿用线程模式。全量回归建议 90")
    display = ap.add_mutually_exclusive_group()
    display.add_argument("--headless", action="store_true",
                         help="显式使用无头 Chrome（服务器/批量回归推荐）")
    display.add_argument("--headful", action="store_true",
                         help="显式显示 Chrome；macOS 自动限制为单并发")
    ap.add_argument("--startup-failure-limit", type=int, default=3,
                    help="连续浏览器启动失败达到此数时中止整批，默认 3；0 表示不熔断")
    args = ap.parse_args()

    if args.resume and args.overwrite:
        ap.error("--resume 与 --overwrite 不能同时使用")
    browser_note = _configure_browser_mode(args)
    if browser_note:
        print("[浏览器保护] {}".format(browser_note))
    inputs = args.input or ["misc/sites_base_60.txt"]
    sites = []
    seen_hosts = set()
    for input_path in inputs:
        with open(input_path, encoding="utf-8") as handle:
            for line in handle:
                site = line.strip()
                if not site or site.lstrip().startswith("#"):
                    continue
                host = urlparse(site).hostname or site
                if host in seen_hosts:
                    continue
                seen_hosts.add(host)
                sites.append(site)
    if args.only:
        only = {h.strip() for h in args.only.split(",") if h.strip()}
        sites = [s for s in sites
                 if (urlparse(s).hostname or "") in only]

    kinds = [k.strip() for k in args.kinds.split(",") if k.strip()]
    tasks = [(s, k) for s in sites for k in kinds]

    done = set()
    if args.overwrite and os.path.isfile(args.output):
        os.remove(args.output)
    if args.resume and os.path.isfile(args.output):
        with open(args.output, encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                    # 失败记录不是完成记录；断点续跑应自动重试，而不是把
                    # session-not-created / timeout 永久当作已经测完。
                    if not r.get("error"):
                        done.add((r.get("site"), r.get("entry_kind")))
                except json.JSONDecodeError:
                    continue
        print(f"[resume] 已存在 {len(done)} 条记录，跳过")

    pending = [t for t in tasks if t not in done]
    print(f"总任务 {len(tasks)}，待跑 {len(pending)}，并发 {args.workers}")

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    fail = 0
    t0 = time.time()
    if args.site_timeout > 0:
        completed_records = _iter_with_site_timeout(
            pending, args.workers, args.site_timeout,
            measure_policy=args.measure_policy)
    else:
        def _thread_records():
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                futures = {pool.submit(
                    classify_one, s, k,
                    measure_policy=args.measure_policy): (s, k)
                    for s, k in pending}
                for future in as_completed(futures):
                    site, kind = futures[future]
                    try:
                        yield future.result()
                    except Exception as exc:
                        yield {"site": site, "entry_kind": kind,
                               "error": "{}:{}".format(type(exc).__name__, str(exc)[:200])}
        completed_records = _thread_records()

    startup_failure_streak = 0
    aborted_for_startup = False
    for i, rec in enumerate(completed_records, 1):
        site = rec.get("site") or ""
        kind = rec.get("entry_kind") or "?"
        with open(args.output, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        host = urlparse(site).hostname or site
        status = "✗" if rec.get("error") else "✓"
        print(f"[{i}/{len(pending)}] {status} {host} {kind} "
              f"-> {rec.get('flow_type')} ({rec.get('stop_reason')})")
        if rec.get("error"):
            fail += 1
        if _is_chrome_startup_failure(rec):
            startup_failure_streak += 1
        else:
            startup_failure_streak = 0
        if (args.startup_failure_limit > 0
                and startup_failure_streak >= args.startup_failure_limit):
            aborted_for_startup = True
            print(
                "[浏览器保护] 连续 {} 次 Chrome 启动失败，已中止本批；"
                "请先修复浏览器环境，再用 --resume 重试失败项。".format(
                    startup_failure_streak))
            close = getattr(completed_records, "close", None)
            if close:
                close()
            break
    elapsed = time.time() - t0
    outcome = "已因浏览器启动故障提前中止" if aborted_for_startup else "完成"
    print(f"\n{outcome}。失败 {fail}/{len(pending)}，耗时 {elapsed:.0f} 秒。"
          f"\n结果已写入 {args.output}")

    # ---- 自动稳定（2026-08-16）：unknown/error 记录多轮重跑取多数 ----
    if args.retry_unknown > 0 and not aborted_for_startup:
        _stabilize_unknown(args, sites, kinds)


def _stabilize_unknown(args, sites, kinds):
    """对输出里的 unknown/error 记录自动重跑 N 轮，多数投票取稳定结果。"""
    from collections import Counter

    def load_records():
        recs = []
        with open(args.output, encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    recs.append(json.loads(line))
        return recs

    def is_bad(rec):
        return bool(rec.get("error")) or rec.get("flow_type") in (None, "unknown", "error")

    all_keys = {(urlparse(s).hostname or s, k) for s in sites for k in kinds}
    votes = {}   # key -> list of records

    def collect_votes():
        for rec in load_records():
            key = (rec.get("hostname"), rec.get("entry_kind"))
            if key in all_keys:
                votes.setdefault(key, []).append(rec)

    collect_votes()
    unstable = [k for k in all_keys if is_bad(votes.get(k, [{}])[-1])]
    print(f"\n[稳定] 初始 unknown/error {len(unstable)} 条，自动重跑 {args.retry_unknown} 轮…")
    t1 = time.time()
    for round_idx in range(1, args.retry_unknown + 1):
        if not unstable:
            break
        tasks = unstable
        new_recs = {}
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(
                classify_one, "https://" + h + "/", k,
                measure_policy=args.measure_policy): (h, k)
                for h, k in tasks}
            for future in as_completed(futures):
                h, k = futures[future]
                try:
                    new_recs[(h, k)] = future.result()
                except Exception as exc:
                    new_recs[(h, k)] = {"hostname": h, "entry_kind": k,
                                        "error": str(exc)[:120]}
        for key, rec in new_recs.items():
            votes.setdefault(key, []).append(rec)
        # 每轮后对仍不稳定的键做多数判定
        still = []
        for key in tasks:
            recs = votes[key]
            valid = [r for r in recs if not is_bad(r)]
            if valid:
                flows = Counter(r.get("flow_type") for r in valid)
                top = max(flows.values())
                best = [f for f, n in flows.items() if n == top]
                if len(best) == 1 and top >= 2:
                    winner = next(r for r in reversed(valid)
                                  if r.get("flow_type") == best[0])
                    votes[key] = [winner]          # 稳定，只保留胜出记录
                    print(f"  [稳定] 第{round_idx}轮 {key[0]} {key[1]} "
                          f"-> {best[0]} ({top}/{len(valid)})")
                    continue
            still.append(key)
        unstable = still
    # 重写输出：仍不稳定的保留最新记录
    _write_stabilized(args.output, votes, unstable, elapsed_sec=time.time() - t1)


def _write_stabilized(output, votes, unstable, elapsed_sec=0.0):
    """按 votes 重写输出文件（保留每个 key 的选定记录）。

    必须先读旧内容再以 "w" 打开（"w" 会截断文件——2026-08-17 实测 bug：
    稳定阶段曾把第 1 轮 304 条数据清空）。
    """
    def load_records():
        recs = []
        with open(output, encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    recs.append(json.loads(line))
        return recs

    all_recs = load_records()
    final_keys = set()
    with open(output, "w", encoding="utf-8") as f:
        for rec in all_recs:
            key = (rec.get("hostname"), rec.get("entry_kind"))
            if key in votes and key not in final_keys:
                chosen = votes[key][-1]
                f.write(json.dumps(chosen, ensure_ascii=False) + "\n")
                final_keys.add(key)
            elif key not in votes:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"[稳定] 结束，剩余不稳定 {len(unstable)} 条，"
          f"共耗时 {elapsed_sec:.0f} 秒")


if __name__ == "__main__":
    main()
