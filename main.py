"""
main.py — 参赛代码入口

用法:
  python main.py https://example.com                  # auto 模式（默认）
  python main.py https://github.com https://gitea.com # 多站点并发
  python main.py -i urls.txt -c 3                     # 文件输入 + 并发控制
  python main.py --method inline https://github.com   # 强制内联验证
  python main.py --method full https://example.com    # 仅显式授权白名单可用

选项:
  --method {auto,inline,full}  密码测试方法（默认 auto）
  -i <file>                    从文件读取 URL 列表
  -c <number>                  最大并发数（默认 4）
  --no-anti-bot                禁用反自动化检测
  --no-cmp                     禁用 CMP 弹窗检测

auto 模式策略:
  只尝试安全的内联验证（填密码后等待 DOM 反馈）；无可靠反馈则回退到仅分类，
  不自动填写身份字段、不提交注册表单。
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
from utils.util_basic import get_logger
from utils.site_agnostic_tester import SitePasswordPolicyTester
from utils.login_link_discovery import LoginLinkDiscovery
from full_form_tester import FullFormPolicyTester
from config.config import Config
from signup_flow_classifier.classifier_engine import SignupFlowClassifierEngine
from loguru import logger


# ================================================================
# 流程类型 → 字母映射（与 MyAutomaticPolicy 分类体系对齐）
# ================================================================
FLOW_TYPE_TO_LETTER = {
    "direct_password": "A",
    "identifier_then_password": "B",
    "verification_then_password": "C",
    "otp_only": "D",
    "email_only": "D",
    "multiple_methods": "E",
    "sso_only": "F",
    "human_blocked": "G",
    "no_web_signup": "H",
    "unknown": "I",
}


def _full_form_authorized(site_url: str) -> bool:
    """仅允许显式开关 + 精确主机白名单同时命中的 full-form 测量。

    full-form 会填写身份字段并点击提交，不能由 ``auto`` 或公开网页默认触发。
    即使调用方显式指定 ``--method full``，也必须同时设置：

    - ``PASSWORD_POLICY_ALLOW_FULL_FORM=1``
    - ``PASSWORD_POLICY_FULL_FORM_ALLOWLIST=host1,host2``

    白名单只做规范化后的精确 hostname 匹配，不接受后缀或通配符。
    """
    enabled = os.environ.get("PASSWORD_POLICY_ALLOW_FULL_FORM", "").strip().lower()
    if enabled not in {"1", "true", "yes"}:
        return False
    host = (urlparse(site_url).hostname or "").rstrip(".").lower()
    allowed = {
        item.strip().rstrip(".").lower()
        for item in os.environ.get(
            "PASSWORD_POLICY_FULL_FORM_ALLOWLIST", ""
        ).split(",")
        if item.strip()
    }
    return bool(host and host in allowed)


# ================================================================
# 方法探测 (auto 模式)
# ================================================================

def _detect_method(driver, site_url, signup_url,
                   email_xpath=None, password_xpath=None,
                   password_frame_path=None):
    """探测网站是内联验证型还是需提交型

    Args:
        driver: Selenium WebDriver（已在注册页上）
        site_url: 网站首页 URL（仅用于日志）
        signup_url: Phase 1 已发现的注册页 URL（当前浏览器所在页面）
        email_xpath: 邮箱字段 XPath（可选，Phase 1 提供）
        password_xpath: 密码字段 XPath（可选，Phase 1 提供）
        password_frame_path: 口令框所在 iframe 路径（分类流程记录，()=主文档）

    返回: (method, signup_url, email_xpath, password_xpath)

    重要：此函数不再创建 LoginLinkDiscovery 或调用 navigate_to_signup()。
    Phase 1 已经将浏览器导航到注册页，此函数只做 inline 反馈检测。
    这避免了重复导航可能导致的不一致（不同导航路径到达不同的页面变体）。

    口令框在跨域 iframe（如 icourse163 reg.icourse163.org）时，主文档里只有
    隐藏登录框，必须切进 password_frame_path 才能命中注册口令框并观察其
    反馈；本函数切进后不恢复默认上下文，由下游接管（inline 测量重新切 frame /
    full-form 重新 driver.get）。
    """
    import utils.util_basic as uub
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.action_chains import ActionChains

    if not signup_url:
        return "inline", None, None, None

    # ── 如果 Phase 1 未提供密码字段 XPath，在当前页面查找 ──
    # 注意：只检查 password_xpath；email 是可选字段，不影响 inline 检测。
    # 原先的 OR 条件（not password_xpath or not email_xpath）在 gitee 等
    # 只检测到密码但无邮箱的站点会触发不必要的 LoginLinkDiscovery 创建和
    # CDP 调用。并发场景下 CDP 会话压力大，冗余调用可能导致超时或失败。
    if not password_xpath:
        discovery = LoginLinkDiscovery(driver)
        found_email, found_pwd = discovery.find_signup_fields()
        email_xpath = email_xpath or found_email
        password_xpath = password_xpath or found_pwd

    if not password_xpath:
        logger.info("未找到密码字段，默认使用 inline 方法")
        return "inline", signup_url, email_xpath, password_xpath

    # ── 切进口令框所在 frame（跨域注册 iframe 内联检测）──
    # 口令框藏在跨域 iframe（icourse163 reg.icourse163.org）时，主文档里只有
    # 隐藏登录框，不切进 frame 永远拿不到注册口令的反馈。分类流程已记录
    # frame_path，这里切进去后 WebDriverWait / execute_script / watchPasswordFeedback
    # 都作用于该 frame 上下文。切进后若反馈 JS 未注入则手动补注入。
    from signup_flow_classifier.page_detector import _switch_to_frame_path
    in_frame = False
    if password_frame_path:
        in_frame = _switch_to_frame_path(driver, password_frame_path)
        if in_frame:
            try:
                if driver.execute_script("return typeof watchPasswordFeedback") != "function":
                    LoginLinkDiscovery(driver).inject_feedback_into_current_frame()
            except Exception:
                pass

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

    # 探测密码序列：前两次用合规密码（能捕获强度指示器/合规提示类反馈），
    # 第三次用非法短密码 "a"。gitee 等站点对合规密码 blur 零反馈，仅在非法
    # 密码 blur 时才显示"密码长度不得低于8个字符"，必须补测非法密码才能命中 inline。
    probe_passwords = ["k4m2x9a7", "n3p8r5t2", "a"]
    for test_pwd in probe_passwords:
        try:
            # 先找到密码框
            pwd_el = WebDriverWait(driver, 5).until(
                EC.visibility_of_element_located((By.XPATH, password_xpath))
            )

            # ── 启动 MutationObserver（必须先于 DOM 变更启动）──
            observer_ok = driver.execute_script(
                "return watchPasswordFeedback(arguments[0])",
                password_xpath,
            )

            # 安全边界：inline 只操作密码框，不填写邮箱、手机号等身份字段。
            # 若网站必须先填写身份字段才校验密码，本次结果应为无法判断。

            # 填密码（键盘模拟：清空 → 聚焦 → send_keys）
            # 用户也是键盘输入，send_keys 触发真实键盘事件，能同时驱动
            # React/Vue/TANGRAM 等所有框架的校验；JS setter 只发 input/change，
            # 百度 TANGRAM 只认真实键盘事件，会导致校验不触发。失败时回退 JS。
            driver.execute_script(
                "arguments[0].value=''; "
                "arguments[0].dispatchEvent(new Event('input', {bubbles: true}));",
                pwd_el)
            try:
                pwd_el.click()
                pwd_el.send_keys(test_pwd)
            except Exception:
                driver.execute_script(js_set, pwd_el, test_pwd)

            # ── focus → blur 触发校验 ──
            # gitee、stackoverflow 等网站在密码框失去焦点（blur）时才显示
            # 内联合规反馈（如"密码长度不得低于8个字符"）。
            # 必须先 click 聚焦、再用 ActionChains 真实鼠标点击密码框右侧
            # 空白区域失焦。不能使用 document.body.click() —— SPA 模态框
            # 站点（xuetangx 等）可能将 body click 误判为"点击遮罩关闭弹窗"。
            try:
                pwd_el.click()  # 聚焦
                time.sleep(0.2)
                if in_frame:
                    # iframe 内 ActionChains 坐标计算不可靠，改用 JS blur 触发校验
                    driver.execute_script(
                        "arguments[0].blur(); "
                        "arguments[0].dispatchEvent(new Event('blur', {bubbles:true}))",
                        pwd_el)
                else:
                    # 真实鼠标移动到密码框右侧 30px 处点击（模拟"填写后点别处"）
                    ActionChains(driver).move_to_element(
                        pwd_el
                    ).move_by_offset(
                        pwd_el.size['width'] // 2 + 30, 5
                    ).click().perform()
            except Exception:
                pass

            wait_time = 5
            deadline = time.time() + wait_time
            feedback = None
            while time.time() < deadline:
                time.sleep(0.3)
                try:
                    results = driver.execute_script(
                        "return getWatchedFeedback()"
                    )
                    if results and len(results) > 0:
                        # 找第一个被拒绝的反馈
                        for r in results:
                            if r.get("rejected"):
                                feedback = r.get("type", "observer-detected")
                                break
                        if feedback:
                            break
                        # 如果有反馈但都未标记为 rejected（如强度指示器）
                        if not feedback:
                            feedback = "observer-detected"
                            break
                except Exception:
                    pass

            # 停止 observer
            try:
                driver.execute_script("stopWatchingFeedback()")
            except Exception:
                pass

            if feedback is not None:
                logger.info(f"内联反馈检测成功 ({feedback})，使用 inline 方法")
                return "inline", signup_url, email_xpath, password_xpath

            # ── 静态快照兜底（MutationObserver 未捕获反馈时） ──
            try:
                fb = driver.execute_script(
                    "return detectPasswordFeedback(arguments[0])",
                    password_xpath,
                )
                if fb and isinstance(fb, dict) and fb.get("hasFeedback"):
                    fb_type = fb.get("type", "static-fallback")
                    logger.info(f"内联反馈检测成功 ({fb_type}, 静态兜底)，使用 inline 方法")
                    return "inline", signup_url, email_xpath, password_xpath
            except Exception:
                pass

        except Exception:
            try:
                driver.execute_script("stopWatchingFeedback()")
            except Exception:
                pass

    # ── 机器人识别阻断检测：内联无反馈 + 表单级滑块/验证码组件 ──
    # icourse163 实测：注册口令框在跨域 iframe（reg.icourse163.org），表单
    # 含网易易盾滑块（input.j-nameforslide），填密码无内联反馈，full-form
    # 提交会被滑块卡死并触发 InvalidSessionIdException。此时不回落
    # full-form，而是标记 captcha_blocked，由 test_single_site 回退到只分类。
    from signup_flow_classifier.browser_failures import detect_captcha_challenge
    block_marker = detect_captcha_challenge(driver)
    if block_marker:
        logger.info(
            "内联无反馈且检测到机器人识别阻断（{}），标记 captcha_blocked".format(block_marker)
        )
        return "captcha_blocked", signup_url, email_xpath, password_xpath

    logger.info(
        "内联反馈检测未成功（3次尝试均无可靠反馈），"
        "按安全边界返回 inline_unsupported，不自动进入 full-form"
    )
    return "inline_unsupported", signup_url, email_xpath, password_xpath


# ================================================================
# 分类结果辅助
# ================================================================

def _apply_classification_to_result(result: dict, classification: dict) -> None:
    """将分类结果写入 result dict，统一设置 class_letter 等信息。"""
    flow_type = classification.get("flow_type", "unknown")
    result["flow_type"] = flow_type
    result["class_letter"] = FLOW_TYPE_TO_LETTER.get(flow_type, "?")
    result["confidence"] = classification.get("confidence", "low")
    result["stop_reason"] = classification.get("stop_reason", "")
    result["primary_method"] = classification.get("primary_method", "")
    result["ui_type"] = classification.get("ui_type", "")
    # v4 逐方法清单（aggregate_methods 数据层）：method/name_zh/status/blockers/route/steps
    result["methods"] = classification.get("methods", [])
    # 分类流程的完整证据（供 webapp 复用分类输出 / 落库用）
    result["states"] = classification.get("states", [])
    result["evidence"] = classification.get("evidence", [])
    result["final_url"] = classification.get("final_url", "")
    # 分类政策元数据（authentication/measurement），与实测口令政策
    # （length/restrictive/permissive，存 result["policy"]）区分
    result["classification_policy"] = classification.get("policy", {})


def _policy_is_usable(policy) -> bool:
    """判断 Phase 4 得到的是否是可信的实测口令政策。"""
    if not isinstance(policy, dict) or not policy:
        return False

    # 明确标记为登录表单、访问阻断、门控表单，或浏览器死亡且未测到长度时，
    # 都说明当前 policy 不能作为注册口令政策输出。
    if policy.get("_suspicious_login_form"):
        return False
    if policy.get("_access_blocked"):
        return False
    if policy.get("_gated_form_unverifiable"):
        return False
    if policy.get("_inconclusive"):
        return False
    if policy.get("_browser_dead"):
        return policy.get("length") not in (None, [0, 0])

    # 找不到可接受密码时，inline 测试器会返回一个全零的默认 policy。
    restrictive = policy.get("restrictive") or {}
    permissive = policy.get("permissive") or {}
    if (
        policy.get("length") == [0, 0]
        and not any(restrictive.values())
        and not any(permissive.values())
    ):
        return False

    return True


def _fallback_to_classification(result: dict, classification: dict, note: str = "") -> dict:
    """测量失败时，用已经完成的注册流程分类结果兜底输出。"""
    result["method_used"] = "classified_only"
    result["policy"] = classification.get("policy", {}) if classification else {}
    result["error"] = None
    if note and not result.get("note"):
        result["note"] = note
    return result


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
    # 尽早建立本站点的日志文件 sink 并绑定线程，让分类/重走/测量全程日志
    # 都落进 logs/<host>/，且并发下各站点日志互不串台（见 util_basic.get_logger）。
    _site_host = urlparse(site_url).hostname or "unknown"
    get_logger(_site_host)
    driver = None
    classification = None
    try:
        driver = _get_new_driver()

        # ================================================================
        # Phase 1: 发现注册页面
        # ================================================================
        discovery = LoginLinkDiscovery(driver)
        signup_url = discovery.navigate_to_signup(site_url)

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
                _apply_classification_to_result(result, classification)
                if (classification["confidence"] != "low"
                        and classification["flow_type"] != "unknown"):
                    # 分类器有把握 → 使用该结果
                    if classification["should_proceed"]:
                        # 分类器「全视图探索」可能已导航到真实注册页（如 SPA 的
                        # /register），而 fallback_url 是分类前捕获的首页 URL。
                        # 用分类结果里记录的 final_url（或当前实际 URL），否则
                        # Phase 4 会 driver.get(首页) 把浏览器从注册页拉回首页，
                        # 导致找不到 input[type=password] 死循环重试。
                        signup_url = classification.get("final_url") or driver.current_url
                        logger.info(
                            "回退分类成功: {} (类型{} confidence={}), 继续测量".format(
                                classification["flow_type"],
                                result.get("class_letter", "?"),
                                classification["confidence"]))
                        # fall through 到 Phase 3（跳过 Phase 2 重复分类）
                    else:
                        result["policy"] = classification.get("policy", {})
                        result["method_used"] = "classified_only"
                        logger.info(
                            "回退分类: {} (类型{}), 无需密码测量".format(
                                classification["flow_type"],
                                result.get("class_letter", "?")))
                        return result
                else:
                    return _fallback_to_classification(
                        result,
                        classification,
                        "注册页发现失败，回退分类无把握；仅输出分类结果，不推断为无网页注册。",
                    )
            except Exception as e:
                logger.warning("回退分类失败: {}".format(e))
                if classification:
                    return _fallback_to_classification(
                        result,
                        classification,
                        "注册页发现失败，回退分类异常；仅输出已有分类结果。",
                    )
                result["error"] = str(e)
                result["flow_type"] = "unknown"
                result["class_letter"] = "I"
                return result

        # ================================================================
        # Phase 2: 分类注册流程（对齐 MyAutomaticPolicy measure_flow）
        # ================================================================
        if classification is None:
            engine = SignupFlowClassifierEngine(driver)
            # 如果 navigate_to_signup 已点击过入口链接（Layer 1/2），
            # 告知 classify() 跳过入口点击阶段，避免重复点击干扰已打开的模态框
            _already_clicked = getattr(discovery, '_entry_clicked', False)
            classification = engine.classify(
                signup_url, entry_kind="signup",
                entry_already_clicked=_already_clicked)

        # 统一将分类信息写入 result
        _apply_classification_to_result(result, classification)

        # ── 测量门槛：注册上下文中是否真实出现口令框 ──
        # 不再用 flow_type（A/B/E）判断，改用 signup_password_reached。
        # 注意：不能用 password_reached——它含登录表单的口令框，会误放行
        # "仅登录站"（shimo/百度等）。
        if not classification.get("signup_password_reached"):
            logger.info(
                "注册流程分类: {} (类型{} confidence={} stop_reason={}), 无注册口令框，跳过密码政策测量".format(
                    classification["flow_type"],
                    result.get("class_letter", "?"),
                    classification["confidence"],
                    classification.get("stop_reason", ""),
                )
            )
            result["policy"] = classification.get("policy", {})
            result["method_used"] = "classified_only"
            return result

        # ── 有注册口令框：继续密码政策测量 ──
        logger.info(
            "流程类型 {}/{} ({})，注册上下文中确认口令框，继续密码政策测量".format(
                result.get("class_letter", "?"),
                classification["flow_type"],
                classification.get("primary_method", ""),
            )
        )

        # ── 重走定位口令框 ──
        # 全视图探索（classify 内）会把浏览器切到随机 tab（短信/邮箱/注册），
        # 返回时不一定停在口令视图。若当前拿不到口令字段，就复用完整分类
        # 流程重走一次（不传 entry_already_clicked，从入口发现重新开始），
        # 带 stop_at_password=True，让 classify 一直运行到口令框出现就停。
        if not engine.get_current_password_field_xpath():
            logger.info("有口令框但当前不在口令视图，重走分类流程定位口令框")
            # 捕获重走结果：stop_at_password 停在口令视图时，_done 已记录
            # password_field（XPath + iframe 路径），供 Phase 3 直接使用。
            classification = engine.classify(
                signup_url, entry_kind="signup", stop_at_password=True)

        # ================================================================
        # Phase 3: 确定 inline/full 方法
        # ================================================================
        # 对于 SPA 模态框站点，Phase 2 分类可能耗时较长导致模态框关闭。
        # 在检测字段前尝试重新打开模态框，确保注册表单可见。
        if not discovery.ensure_form_visible():
            logger.debug("无法恢复模态框，使用当前页面状态继续")

        email_xpath, password_xpath = discovery.find_signup_fields()
        # 分类流程已在 signup_password_reached 时记录口令框的 XPath + iframe 路径，
        # 优先采用它（避免 find_signup_fields 返回全视图探索后失效的旧 XPath 缓存，
        # 且 password_field 带 iframe 路径，供下游切进跨域注册 iframe）。
        password_frame_path = None
        if classification is not None:
            eng_field = classification.get("password_field")
            if eng_field:
                password_xpath = eng_field.get("xpath") or password_xpath
                password_frame_path = eng_field.get("frame_path")

        # 兜底：重走定位后仍无口令字段 → 输出分类结果（classified_only）
        if not password_xpath:
            class_letter = result.get("class_letter", "?")
            flow_type = result.get("flow_type", "unknown")
            logger.info(
                "未发现密码字段，分类结果: 类型{} ({}), 输出分类".format(
                    class_letter, flow_type
                )
            )
            result["method_used"] = "classified_only"
            result["policy"] = classification.get("policy", {}) if classification else {}
            result["note"] = (
                "注册上下文中确认有口令框，但重走分类流程后仍无法定位"
                "口令输入字段，密码政策未能测量（类型{}/{}）。".format(
                    class_letter, flow_type
                )
            )
            return result

        if method == "auto":
            # auto 模式只尝试 inline（填密码→点空白→读反馈）。
            # 无可靠反馈返回 inline_unsupported，绝不自动提交完整注册表单。
            method_used, _, email_xpath, password_xpath = \
                _detect_method(driver, site_url, signup_url,
                               email_xpath, password_xpath,
                               password_frame_path=password_frame_path)
        else:
            method_used = method

        result["method_used"] = method_used

        # ── 机器人识别阻断：注册口令框已定位，但表单级滑块/验证码
        # （网易易盾 j-nameforslide / 极验等）拦截提交，内联无反馈、
        # full-form 也会被卡死。此时直接输出已完成的分类结果，不测量。
        if method_used in {"captcha_blocked", "inline_unsupported"}:
            unsupported = method_used == "inline_unsupported"
            logger.info(
                ("inline 未建立可靠反馈对照，" if unsupported else
                 "检测到机器人识别阻断（滑块/验证码），") +
                "跳过密码政策测量，"
                "输出分类结果（类型{}/{}）".format(
                    result.get("class_letter", "?"),
                    result.get("flow_type", "unknown"),
                )
            )
            result["method_used"] = "classified_only"
            result["policy"] = classification.get("policy", {}) if classification else {}
            if not result.get("note"):
                if unsupported:
                    result["note"] = (
                        "注册口令框已定位（类型{}/{}），但 inline 未观察到可验证的"
                        "密码专属反馈；结果为无法判断，仅输出分类结果。".format(
                            result.get("class_letter", "?"),
                            result.get("flow_type", "unknown"),
                        )
                    )
                else:
                    result["note"] = (
                        "注册口令框已定位（类型{}/{}），但存在机器人识别阻断"
                        "（滑块/验证码），无法测量密码政策，仅输出分类结果。".format(
                            result.get("class_letter", "?"),
                            result.get("flow_type", "unknown"),
                        )
                    )
            return result

        # ================================================================
        # Phase 4: 执行密码政策测量
        # ================================================================
        if method_used == "inline":
            tester = SitePasswordPolicyTester(driver, site_url)
            tester.signup_url = signup_url
            tester.email_xpath = email_xpath
            tester.password_xpath = password_xpath
            if not tester.discover_form_fields():
                return _fallback_to_classification(
                    result,
                    classification,
                    "密码字段检测失败，回退输出注册流程分类结果。",
                )
            # 若当前已在注册页面，标记页面就绪，防止 test_one_password
            # 内部重新 driver.get(signup_url) 导致 SPA 模态框关闭
            try:
                cur = driver.current_url.rstrip("/")
                tgt = signup_url.rstrip("/")
                if cur == tgt:
                    tester._signup_page_ready = True
                    logger.debug("已在注册页面（URL 匹配），跳过页面重载")
            except Exception:
                pass
            # 口令框在 iframe（跨域注册 iframe，如 icourse163）时，分类流程已
            # 记录 frame_path。切进该 frame 再测量，让 TestPassword 的
            # find_element(password_xpath) 命中注册口令框而非主文档隐藏登录框。
            # 强制 _signup_page_ready=True：避免 test_one_password 首次
            # driver.get(signup_url) 把 frame 上下文重置回主文档。
            if password_frame_path:
                tester._signup_page_ready = True
            in_frame = False
            if password_frame_path:
                from signup_flow_classifier.page_detector import _switch_to_frame_path
                in_frame = _switch_to_frame_path(driver, password_frame_path)
                if in_frame:
                    try:
                        if driver.execute_script("return typeof watchPasswordFeedback") != "function":
                            LoginLinkDiscovery(driver).inject_feedback_into_current_frame()
                    except Exception:
                        pass
            try:
                result["policy"] = tester.run_password_policy_test()
            finally:
                if in_frame:
                    try:
                        driver.switch_to.default_content()
                    except Exception:
                        pass
        elif method_used == "full":
            if not _full_form_authorized(site_url):
                return _fallback_to_classification(
                    result,
                    classification,
                    "full-form 默认关闭；仅显式授权且精确主机白名单命中时可运行。",
                )
            parsed = urlparse(site_url)
            hostname = parsed.hostname or "unknown"
            tester = FullFormPolicyTester(
                driver, site_url,
                signup_url=signup_url,
                email_xpath=email_xpath or "",
                password_xpath=password_xpath or "",
                test_site=hostname,
                authorized=True,
            )
            result["policy"] = tester.run_full_test()
        else:
            return _fallback_to_classification(
                result,
                classification,
                "未知或不可用的密码政策测量方法，回退输出注册流程分类结果。",
            )

        # ── 测量结果不可信时，回退到已经完成的注册流程分类 ──
        if not _policy_is_usable(result.get("policy")):
            _fallback_to_classification(
                result,
                classification,
                "密码政策测试未得到可信结果，回退输出注册流程分类结果。",
            )

        # ── 后处理：检测异常情况 ──
        # 注意：对于 A/B/E 类网站，即使检测到疑似登录表单，
        # 也保留分类器的原始分类结果，仅标注密码数据不可信。
        if (
            isinstance(result.get("policy"), dict)
            and result["policy"].get("_suspicious_login_form")
            and not result["policy"].get("_access_blocked")
            and not result["policy"].get("_browser_dead")
        ):
            logger.warning(
                "{} 疑似登录表单（非注册页面），密码测量结果不可信，"
                "保留原始分类（类型{}/{}）".format(
                    site_url,
                    result.get("class_letter", "?"),
                    result.get("flow_type", "unknown"),
                )
            )
            # 不覆盖 flow_type！保留分类器的原始分类
            result["suspicious_login_form"] = True
            if not result.get("note"):
                result["note"] = (
                    "密码测量疑似在登录表单（而非注册表单）上执行，"
                    "密码政策数据不可信。原始分类（类型{}/{}）保持不变。".format(
                        result.get("class_letter", "?"),
                        result.get("flow_type", "unknown"),
                    )
                )
        elif isinstance(result.get("policy"), dict) and result["policy"].get(
            "_access_blocked"
        ):
            logger.warning(
                "{} 访问被阻断（机器人拦截），标记结果".format(site_url)
            )
            result["method_used"] = "access_blocked"
            result["flow_type"] = "access_blocked"
            result["class_letter"] = "G"  # 等同于 human_blocked
        elif isinstance(result.get("policy"), dict) and result["policy"].get(
            "_browser_dead"
        ):
            logger.warning(
                "{} 浏览器会话终止，标记结果".format(site_url)
            )
            _policy = result["policy"]
            _length_measured = _policy.get("length") not in (None, [0, 0])
            if _length_measured:
                # 已测出实质政策（长度/组合等）→ 保留分类，仅加说明，
                # 不降级 browser_crashed（避免丢掉 direct_password 等正确分类）
                result["method_used"] = "partial_browser_dead"
                if not result.get("note"):
                    result["note"] = (
                        "浏览器在测量尾部崩溃，核心政策（长度/组合）已测出，"
                        "但 permissive 字符/序列/泄露密码等维度未测完。"
                    )
            else:
                result["method_used"] = "browser_dead"
                result["flow_type"] = "browser_crashed"
                result["class_letter"] = "?"

    except Exception as e:
        import traceback
        traceback.print_exc()
        if classification:
            _fallback_to_classification(
                result,
                classification,
                "密码政策测试发生异常，回退输出注册流程分类结果。",
            )
        else:
            result["error"] = str(e)
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
        "class_letter": result.get("class_letter", "?"),
        "primary_method": result.get("primary_method", ""),
        "confidence": result.get("confidence", "low"),
        "stop_reason": result.get("stop_reason", ""),
        "ui_type": result.get("ui_type", ""),
        "methods": result.get("methods", []),
        "error": result.get("error"),
        "policy": result.get("policy", {}),
        "classification_policy": result.get("classification_policy", {}),
        "states": result.get("states", []),
        "evidence": result.get("evidence", []),
        "final_url": result.get("final_url", ""),
        "note": result.get("note", ""),
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    # 删除增量快照：成功收尾后不留陈旧 .partial.json（避免污染后续读取）
    partial_path = os.path.join(site_dir, f"policy_{hostname}.partial.json")
    if os.path.isfile(partial_path):
        try:
            os.remove(partial_path)
        except Exception:
            pass
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
    success = sum(1 for r in results.values()
                  if not r["error"] and r["policy"]
                  and r.get("method_used") != "classified_only")
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
