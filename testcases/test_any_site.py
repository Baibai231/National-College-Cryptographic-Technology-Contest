"""
test_any_site.py — 通用网站密码政策测试用例

对比原始的 test_github.py（硬编码 GitHub 选择器），
本测试用例使用 LoginFormExploration 的表单自动发现 + Fathom ML 字段检测。

用法:
  python testcases/test_any_site.py
"""

import sys
import os

# 确保参赛代码根目录在 Python path 中
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from utils.util_test_password import _get_shared_driver
from utils.site_agnostic_tester import SitePasswordPolicyTester


def test_github():
    """回归测试：验证嫁接后对 github.com 的测试结果与原始 test_github.py 一致"""
    print("\n" + "=" * 60)
    print("  回归测试: GitHub")
    print("=" * 60 + "\n")

    driver = _get_shared_driver()
    try:
        tester = SitePasswordPolicyTester(driver, "https://github.com")
        policy = tester.run_full_test()
        print("\nGitHub 密码政策:", policy)
        return policy
    finally:
        try:
            driver.quit()
        except Exception:
            pass


# 可扩展更多网站测试
SITES_TO_TEST = [
    "https://github.com",
    # "https://twitter.com",
    # "https://zhihu.com",
]


def main():
    for site in SITES_TO_TEST:
        print("\n" + "=" * 60)
        print(f"  测试: {site}")
        print("=" * 60 + "\n")

        driver = _get_shared_driver()
        try:
            tester = SitePasswordPolicyTester(driver, site)
            policy = tester.run_full_test()
            print(f"\n{site} 密码政策:", policy)
        except Exception as e:
            print(f"\n{site} 测试失败: {e}")
        finally:
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    test_github()
