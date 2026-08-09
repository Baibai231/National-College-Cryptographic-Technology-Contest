"""
test_sites.py — 对 GitHub / Gitea / GitLab 执行密码政策测试

用法:
  python test_sites.py              # 测试全部三个站点（串行）
  python test_sites.py --site github # 只测试指定站点
  python test_sites.py --concurrent  # 并发测试全部站点

测试结果以覆盖写入方式存放在:
  logs/github/policy_github.com.json
  logs/gitea/policy_gitea.com.json
  logs/gitlab/policy_gitlab.com.json
"""

import sys
import os
import json
import time
import argparse
from datetime import datetime
from urllib.parse import urlparse

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from utils.util_test_password import _get_new_driver, _get_shared_driver
from utils.site_agnostic_tester import SitePasswordPolicyTester

# ============================================================
# 测试目标站点配置
# ============================================================

SITES = {
    "github": {
        "url": "https://github.com",
        "name": "GitHub",
    },
    "gitea": {
        "url": "https://gitea.com",
        "name": "Gitea",
    },
    "gitlab": {
        "url": "https://gitlab.com",
        "name": "GitLab",
    },
}


def get_output_dir(site_key: str) -> str:
    """获取站点对应的日志输出目录，确保存在"""
    d = os.path.join(_PROJECT_ROOT, "logs", site_key)
    os.makedirs(d, exist_ok=True)
    return d


def get_output_path(site_key: str, site_url: str) -> str:
    """获取策略 JSON 输出路径"""
    hostname = urlparse(site_url).hostname or site_key
    return os.path.join(get_output_dir(site_key), f"policy_{hostname}.json")


def test_single_site(site_key: str, site_info: dict) -> dict:
    """测试单个站点，返回结果字典。

    结果覆盖写入 logs/<site_key>/policy_<hostname>.json
    """
    site_url = site_info["url"]
    site_name = site_info["name"]
    output_path = get_output_path(site_key, site_url)

    result = {
        "site": site_key,
        "name": site_name,
        "url": site_url,
        "timestamp": datetime.now().isoformat(),
        "policy": {},
        "error": None,
        "output_path": output_path,
        "elapsed_seconds": 0,
    }

    print()
    print("=" * 70)
    print(f"  测试站点: {site_name} ({site_url})")
    print(f"  输出路径: {output_path}")
    print("=" * 70)

    driver = None
    t0 = time.time()
    try:
        driver = _get_new_driver()
        tester = SitePasswordPolicyTester(driver, site_url)
        policy = tester.run_full_test()
        result["policy"] = policy

        # 覆盖写入结果
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(policy, f, indent=2, ensure_ascii=False)

        print(f"\n  ✓ {site_name} 测试完成")
        print(f"  结果已保存到: {output_path}")

    except Exception as e:
        result["error"] = str(e)
        # 写入错误信息
        error_result = {"error": str(e), "timestamp": result["timestamp"]}
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(error_result, f, indent=2, ensure_ascii=False)
        print(f"\n  ✗ {site_name} 测试失败: {e}")
        import traceback
        traceback.print_exc()

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

    result["elapsed_seconds"] = round(time.time() - t0, 1)
    print(f"  耗时: {result['elapsed_seconds']} 秒")
    return result


def print_summary(results: dict):
    """打印测试汇总"""
    print()
    print("=" * 70)
    print("  测试汇总")
    print("=" * 70)
    total = len(results)
    success = sum(1 for r in results.values() if not r["error"] and r["policy"])
    failed = sum(1 for r in results.values() if r["error"])
    empty = total - success - failed

    print(f"  {'站点':<15} {'结果':<8} {'耗时':<10} {'输出'}")
    print(f"  {'-'*15} {'-'*8} {'-'*10} {'-'*30}")
    for key, r in results.items():
        status = "✓ 成功" if (not r["error"] and r["policy"]) else ("✗ 失败" if r["error"] else "⚠ 无结果")
        print(f"  {r['name']:<15} {status:<8} {r['elapsed_seconds']}s{'':>5} {r['output_path']}")

    print(f"\n  总计: {total}  成功: {success}  失败: {failed}  无结果: {empty}")
    total_time = sum(r["elapsed_seconds"] for r in results.values())
    print(f"  总耗时: {round(total_time, 1)} 秒")


def main():
    parser = argparse.ArgumentParser(description="GitHub / Gitea / GitLab 密码政策测试")
    parser.add_argument("--site", choices=["github", "gitea", "gitlab"],
                        help="只测试指定站点")
    parser.add_argument("--concurrent", action="store_true",
                        help="并发测试（默认串行，更稳定）")
    args = parser.parse_args()

    # 筛选站点
    if args.site:
        targets = {args.site: SITES[args.site]}
    else:
        targets = SITES

    print("=" * 70)
    print(f"  密码政策测试 — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  目标站点: {', '.join(t['name'] for t in targets.values())}")
    print(f"  模式: {'并发' if args.concurrent else '串行'}")
    print("=" * 70)

    results = {}

    if args.concurrent and len(targets) > 1:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        max_workers = min(len(targets), 3)
        print(f"\n  并发数: {max_workers}")
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(test_single_site, key, info): key
                for key, info in targets.items()
            }
            for future in as_completed(futures):
                key = futures[future]
                try:
                    results[key] = future.result(timeout=600)
                except Exception as e:
                    results[key] = {
                        "site": key, "name": targets[key]["name"], "url": targets[key]["url"],
                        "timestamp": datetime.now().isoformat(), "policy": {},
                        "error": f"超时: {e}", "output_path": get_output_path(key, targets[key]["url"]),
                        "elapsed_seconds": 600,
                    }
    else:
        for key, info in targets.items():
            results[key] = test_single_site(key, info)

    print_summary(results)

    # 返回退出码
    failed = sum(1 for r in results.values() if r["error"])
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
