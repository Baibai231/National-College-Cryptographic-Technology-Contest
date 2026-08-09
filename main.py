"""
main.py — 参赛代码入口

用法:
  python main.py https://example.com                  # auto 模式（默认）
  python main.py https://github.com https://gitea.com # 多站点并发
  python main.py -i urls.txt -c 3                     # 文件输入 + 并发控制
  python main.py --method inline https://github.com   # 强制内联验证
  python main.py --method full https://example.com    # 强制全表单提交

选项:
  --method {auto,inline,full}  密码测试方法（默认 auto）
  -i <file>                    从文件读取 URL 列表
  -c <number>                  最大并发数（默认 4）
  --no-anti-bot                禁用反自动化检测
  --no-cmp                     禁用 CMP 弹窗检测

auto 模式策略:
  先尝试 2 轮内联验证（填密码后等待 DOM 反馈），2 轮无反馈则自动切换到全表单提交方法。
"""

import sys
import os
import json
import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

# 确保参赛代码根目录在 Python path 中
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# 创建 logs 目录
os.makedirs(os.path.join(_PROJECT_ROOT, "logs"), exist_ok=True)

from utils.util_test_password import _get_new_driver
from utils.site_agnostic_tester import SitePasswordPolicyTester
from utils.login_link_discovery import LoginLinkDiscovery
from full_form_tester import FullFormPolicyTester
from config.config import Config
from signup_flow_classifier.classifier_engine import SignupFlowClassifierEngine
from loguru import logger


# ================================================================
# 方法探测 (auto 模式)
# ================================================================

def _detect_method(driver, site_url):
    """探测网站是内联验证型还是需提交型

    返回: (method, signup_url, email_xpath, password_xpath)

    注意: navigate_to_signup() 已把浏览器带到注册页，不要再次 driver.get() 以免
    页面重载导致 React/Vue 重渲染改变 DOM 结构。
    """
    import utils.util_basic as uub
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    discovery = LoginLinkDiscovery(driver)
    signup_url = discovery.navigate_to_signup(site_url)
    if not signup_url:
        return "inline", None, None, None

    email_xpath, password_xpath = discovery.find_signup_fields()
    if not password_xpath:
        return "inline", signup_url, email_xpath, password_xpath

    # navigate_to_signup 已经通过点击链接到达注册页，无需二次加载
    uub.random_sleep([1, 2])

    js_set = """
        var elm = arguments[0], txt = arguments[1];
        elm.removeAttribute('aria-invalid');
        var setter = Object.getOwnPropertyDescriptor(
            window.HTMLInputElement.prototype, 'value').set;
        setter.call(elm, txt);
        elm.dispatchEvent(new Event('input', {bubbles: true}));
        elm.dispatchEvent(new Event('change', {bubbles: true}));
    """

    for attempt in range(2):
        test_email = f"test{attempt}@example.com"
        test_pwd = "k4m2x9a7" if attempt == 0 else "n3p8r5t2"
        try:
            # 先填邮箱（很多网站需要邮箱填完后才触发密码校验）
            if email_xpath:
                try:
                    email_el = WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located((By.XPATH, email_xpath))
                    )
                    driver.execute_script(js_set, email_el, test_email)
                    time.sleep(0.3)
                except Exception:
                    pass

            # 填密码
            pwd_el = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.XPATH, password_xpath))
            )
            driver.execute_script(js_set, pwd_el, test_pwd)

            # 点击密码框触发 focus/blur 事件（部分网站依赖此事件触发校验）
            try:
                pwd_el.click()
            except Exception:
                pass

            wait_time = 3 if attempt == 0 else 5
            deadline = time.time() + wait_time
            feedback = None
            while time.time() < deadline:
                try:
                    fb = driver.execute_script(
                        "return detectPasswordFeedback(arguments[0])",
                        password_xpath,
                    )
                except Exception:
                    # JS 未注入或页面上下文丢失，回退到 aria-invalid
                    try:
                        v = pwd_el.get_attribute("aria-invalid")
                    except Exception:
                        v = None
                    fb = {
                        "hasFeedback": v is not None and v != "",
                        "rejected": v == "true",
                    }
                if fb and isinstance(fb, dict) and fb.get("hasFeedback"):
                    feedback = fb.get("type", "detected")
                    break
                time.sleep(0.5)

            if feedback is not None:
                fb_type = (fb or {}).get("type", "?") if isinstance(fb, dict) else "?"
                logger.info(f"内联反馈检测成功 ({fb_type})，使用 inline 方法")
                return "inline", signup_url, email_xpath, password_xpath
        except Exception:
            pass

    return "full", signup_url, email_xpath, password_xpath


# ================================================================
# 单站点测试
# ================================================================

def test_single_site(site_url: str, method: str = "auto") -> dict:
    """测试单个站点（每个线程创建独立 WebDriver）

    Args:
        site_url: 目标网站 URL
        method: "auto" | "inline" | "full"

    Returns:
        {"url": str, "policy": dict, "error": str|None, "method_used": str,
         "flow_type": str|None}
    """
    result = {"url": site_url, "policy": {}, "error": None, "method_used": method,
              "flow_type": None}
    driver = None
    try:
        driver = _get_new_driver()

        # ================================================================
        # Phase 1: 发现注册页面
        # ================================================================
        discovery = LoginLinkDiscovery(driver)
        signup_url = discovery.navigate_to_signup(site_url)

        classification = None   # Phase 2 会填充；fallback 提前填充时跳过 Phase 2
        engine = None

        if not signup_url:
            # ── 回退：用当前页面运行分类器做最后尝试 ──
            # navigate_to_signup() 失败后 driver 停在首页（Layer 3），
            # 首页可能有登录弹窗 / 多方式切换 tab，分类器应有机会观察。
            fallback_url = driver.current_url
            logger.info("注册页发现失败，尝试对当前页分类: {}".format(fallback_url))
            try:
                engine = SignupFlowClassifierEngine(driver)
                classification = engine.classify(fallback_url, entry_kind="signup")
                result["flow_type"] = classification["flow_type"]
                if (classification["confidence"] != "low"
                        and classification["flow_type"] != "unknown"):
                    # 分类器有把握 → 使用该结果
                    if classification["should_proceed"]:
                        signup_url = fallback_url
                        logger.info(
                            "回退分类成功: {} (confidence={}), 继续测量".format(
                                classification["flow_type"],
                                classification["confidence"]))
                        # fall through 到 Phase 3（跳过 Phase 2 重复分类）
                    else:
                        result["policy"] = classification.get("policy", {})
                        result["method_used"] = "classified_only"
                        return result
                else:
                    # 分类器也无把握 → 维持原逻辑
                    result["error"] = "未发现注册页面"
                    result["flow_type"] = "no_web_signup"
                    return result
            except Exception as e:
                logger.warning("回退分类失败: {}".format(e))
                result["error"] = "未发现注册页面"
                result["flow_type"] = "no_web_signup"
                return result

        # ================================================================
        # Phase 2: 分类注册流程（NEW — 嫁接自 MyAutomaticPolicy）
        # ================================================================
        if classification is None:
            engine = SignupFlowClassifierEngine(driver)
            classification = engine.classify(signup_url, entry_kind="signup")
            result["flow_type"] = classification["flow_type"]

        # 不需要继续测量的类型（C/D/F/G/H/I）→ 通常直接返回分类结果
        if not classification["should_proceed"]:
            # 例外：分类器 low-confidence（不确定）→ 放行，尝试测量
            is_uncertain = (
                classification["confidence"] == "low"
                and classification["flow_type"] == "unknown"
            )
            if is_uncertain:
                logger.info(
                    "分类器 low-confidence ({}), 不阻止测量，继续尝试".format(
                        classification.get("stop_reason", "")
                    )
                )
            else:
                logger.info(
                    "注册流程分类: {} (confidence={}), 跳过密码政策测量".format(
                        classification["flow_type"], classification["confidence"]
                    )
                )
                result["policy"] = classification.get("policy", {})
                result["method_used"] = "classified_only"
                return result

        # 类型 E 补救：尝试 tab 切换到密码视图
        if classification["flow_type"] == "multiple_methods":
            logger.info("类型 E 检测，尝试切换到密码注册视图...")
            if not engine.try_switch_to_password_view():
                logger.info("无法切换到密码视图，跳过测量")
                result["policy"] = classification.get("policy", {})
                result["method_used"] = "classified_only"
                return result
            logger.info("成功切换到密码视图，继续测量")

        # ================================================================
        # Phase 3: 确定 inline/full 方法
        # ================================================================
        if method == "auto":
            # auto 模式：内联反馈探测决定 inline vs full
            method_used, _, email_xpath, password_xpath = \
                _detect_method(driver, site_url)
        else:
            method_used = method
            email_xpath, password_xpath = discovery.find_signup_fields()

        result["method_used"] = method_used

        # 重新检测字段（分类器可能已导航到新页面，XPath 可能失效）
        if not email_xpath or not password_xpath:
            email_xpath, password_xpath = discovery.find_signup_fields()
        if classification.get("password_reached") and not password_xpath:
            password_xpath = engine.get_current_password_field_xpath()

        # ================================================================
        # Phase 4: 执行密码政策测量
        # ================================================================
        if method_used == "inline":
            tester = SitePasswordPolicyTester(driver, site_url)
            tester.signup_url = signup_url
            tester.email_xpath = email_xpath
            tester.password_xpath = password_xpath
            if not tester.discover_form_fields():
                result["error"] = "无法检测表单字段"
                return result
            result["policy"] = tester.run_password_policy_test()
        else:
            parsed = urlparse(site_url)
            hostname = parsed.hostname or "unknown"
            tester = FullFormPolicyTester(
                driver, site_url,
                signup_url=signup_url,
                email_xpath=email_xpath or "",
                password_xpath=password_xpath or "",
                test_site=hostname,
            )
            result["policy"] = tester.run_full_test()

    except Exception as e:
        result["error"] = str(e)
        import traceback
        traceback.print_exc()
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
    return result


# ================================================================
# CLI
# ================================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description="密码政策自动测试工具 —— 支持多站点并发 + 多方法切换",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py https://github.com
  python main.py --method full https://gitea.com
  python main.py https://github.com https://gitea.com
  python main.py -i urls.txt -c 3
        """
    )
    parser.add_argument("urls", nargs="*", help="目标网站 URL（可多个）")
    parser.add_argument("--method", choices=["auto", "inline", "full"], default="auto",
                        help="密码测试方法: auto(自动探测) | inline(内联验证) | full(全表单提交)")
    parser.add_argument("-i", "--input-list", dest="input_list",
                        help="从文件读取 URL 列表（每行一个）")
    parser.add_argument("-c", "--crawlers", dest="num_crawlers", type=int, default=None,
                        help=f"最大并发数（默认: {Config.MAX_CONCURRENT_CRAWLERS}）")
    parser.add_argument("--no-anti-bot", dest="no_anti_bot", action="store_true",
                        help="禁用反自动化检测")
    parser.add_argument("--no-cmp", dest="no_cmp", action="store_true",
                        help="禁用 CMP 弹窗检测")
    return parser.parse_args()


def load_urls(args) -> list:
    urls = list(args.urls or [])
    if args.input_list:
        input_path = args.input_list
        if not os.path.isabs(input_path):
            input_path = os.path.join(_PROJECT_ROOT, input_path)
        if os.path.isfile(input_path):
            with open(input_path, "r", encoding="utf-8-sig") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        urls.append(line)
        else:
            print(f"[!] 文件不存在: {input_path}")
            sys.exit(1)
    normalized = []
    for u in urls:
        if not u.startswith("http"):
            u = "https://" + u
        normalized.append(u)
    return normalized


def save_result(site_url: str, result: dict):
    """保存测试结果到 logs/<hostname>/policy_<hostname>.json

    无论成功、失败还是异常，始终写入 JSON。
    """
    hostname = urlparse(site_url).hostname or "unknown"
    site_dir = os.path.join(_PROJECT_ROOT, "logs", hostname)
    os.makedirs(site_dir, exist_ok=True)
    output_path = os.path.join(site_dir, f"policy_{hostname}.json")
    payload = {
        "url": site_url,
        "hostname": hostname,
        "method_used": result.get("method_used", "?"),
        "flow_type": result.get("flow_type"),
        "error": result.get("error"),
        "policy": result.get("policy", {}),
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return output_path


def main():
    args = parse_args()
    urls = load_urls(args)

    if not urls:
        print("用法: python main.py [--method auto|inline|full] <网站URL> [URL2 ...]")
        print("      python main.py -i urls.txt [-c 并发数]")
        print("示例:")
        print("  python main.py https://github.com")
        print("  python main.py --method full https://gitea.com")
        sys.exit(1)

    num_crawlers = args.num_crawlers or Config.MAX_CONCURRENT_CRAWLERS
    num_crawlers = min(num_crawlers, len(urls), os.cpu_count() or 4)

    if args.no_anti_bot:
        Config.ENABLE_ANTI_BOT = False
    if args.no_cmp:
        Config.ENABLE_CMP_DETECTION = False

    print("=" * 60)
    print(f"  密码政策自动测试工具")
    print(f"  目标站点数: {len(urls)}")
    print(f"  测试方法: {args.method}")
    print(f"  并发数: {num_crawlers}")
    print(f"  反自动化: {'开启' if Config.ENABLE_ANTI_BOT else '关闭'}")
    print(f"  CMP 检测: {'开启' if Config.ENABLE_CMP_DETECTION else '关闭'}")
    print("=" * 60)
    print()

    for i, u in enumerate(urls, 1):
        print(f"  {i}. {u}")
    print()
    print("  Phase 2: 注册流程分类 + 密码政策测量")
    print()

    # 并发执行
    results = {}
    with ThreadPoolExecutor(max_workers=num_crawlers) as executor:
        futures = {
            executor.submit(test_single_site, url, args.method): url
            for url in urls
        }
        for future in as_completed(futures):
            url = futures[future]
            try:
                result = future.result(timeout=Config.CRAWLER_TIMEOUT_SECONDS)
                results[url] = result

                hostname = urlparse(url).hostname or url
                method_label = result.get("method_used", "?")
                flow_type_label = result.get("flow_type", "?") or "?"
                if result["error"]:
                    print(f"\n[{hostname}] ✗ 失败 ({method_label}, {flow_type_label}): {result['error']}")
                elif result["policy"]:
                    if method_label == "classified_only":
                        print(f"\n[{hostname}] ⊘ 仅分类 ({flow_type_label}) — 跳过密码测量")
                        print(json.dumps(result["policy"], indent=2, ensure_ascii=False))
                    else:
                        print(f"\n[{hostname}] ✓ 成功 ({method_label}, {flow_type_label})")
                        print(json.dumps(result["policy"], indent=2, ensure_ascii=False))
                else:
                    print(f"\n[{hostname}] ✗ 未获取到密码政策 ({method_label}, {flow_type_label})")
                # 无论成功失败都保存结果文件
                output_path = save_result(url, result)
                print(f"  结果已保存到: {output_path}")
            except Exception as e:
                results[url] = {"url": url, "policy": {}, "error": str(e),
                                "method_used": "?", "flow_type": None}
                hostname = urlparse(url).hostname or url
                print(f"\n[{hostname}] ✗ 超时或异常: {e}")
                output_path = save_result(url, results[url])
                print(f"  结果已保存到: {output_path}")

    # 汇总
    print()
    print("=" * 60)
    print("  测试汇总")
    print("=" * 60)
    success = sum(1 for r in results.values() if not r["error"] and r["policy"])
    failed = sum(1 for r in results.values() if r["error"])
    classified_only = sum(1 for r in results.values()
                          if r.get("method_used") == "classified_only")
    empty = len(results) - success - failed - classified_only
    print(f"  总计: {len(results)}  成功: {success}  仅分类: {classified_only}  "
          f"失败: {failed}  无结果: {empty}")

    # 按 flow_type 统计
    from collections import Counter
    ft_counts = Counter(r.get("flow_type") for r in results.values() if r.get("flow_type"))
    if ft_counts:
        print("\n  注册流程类型分布:")
        for ft, count in ft_counts.most_common():
            print(f"    {ft:<30} {count}")

    print("\n  输出文件:")
    for url, r in results.items():
        hostname = urlparse(url).hostname or "unknown"
        output_path = os.path.join(_PROJECT_ROOT, "logs", hostname, f"policy_{hostname}.json")
        status = "✓" if (not r["error"] and r["policy"]) else "✗"
        method_label = r.get("method_used", "?")
        ft_label = r.get("flow_type", "?") or "?"
        print(f"    {status} {output_path}  ({method_label}, {ft_label})")


if __name__ == "__main__":
    main()
