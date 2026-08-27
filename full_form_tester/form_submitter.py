"""
form_submitter.py — 表单填充、提交、反馈捕获

职责:
  1. 按 DOM 顺序填充所有非密码字段（拟人化逐字输入）
  2. 填充密码 + 确认密码字段
  3. 勾选 required checkbox (条款)
  4. 定位并点击提交按钮
  5. 等待页面响应，捕获反馈信息
  6. 多步表单支持：最多 2 页，超限标记为无研究价值
"""

import time
from typing import List, Dict, Optional, Tuple

from .rate_controller import RateController
from .data_generator import DataGenerator
from .field_classifier import (
    FIELD_PASSWORD, FIELD_CONFIRM_PASSWORD,
    FIELD_CHECKBOX_TERMS, FIELD_CAPTCHA, FIELD_SELECT,
    FieldClassifier,
)

# 多步表单最大页数（超过此限制仍无密码反馈 → 标记为无研究价值）
MAX_FORM_STEPS = 2


class FormSubmitter:
    """表单填充与提交器"""

    # 提交按钮定位关键词（多语言）
    _SUBMIT_KEYWORDS_EN = [
        "sign up", "signup", "register", "create account",
        "get started", "join", "continue", "next", "submit",
        "create my account", "start", "sign me up", "proceed",
    ]
    _SUBMIT_KEYWORDS_CN = [
        "注册", "提交", "创建账户", "创建帐号", "下一步",
        "立即注册", "免费注册", "马上注册", "确认", "确定",
        "同意并注册", "提交注册", "完成",
    ]

    _SUBMIT_SELECTORS = [
        'button[type="submit"]',
        'input[type="submit"]',
        'input[type="button"]',
        'button',
        'a[role="button"]',
    ]

    def __init__(self, driver, rate_ctrl: RateController, data_gen: DataGenerator,
                 allow_submit: bool = False):
        """
        Args:
            driver: Selenium WebDriver 实例
            rate_ctrl: 节奏控制器
            data_gen: 数据生成器
        """
        self._driver = driver
        self._rate = rate_ctrl
        self._data = data_gen
        self._allow_submit = allow_submit

        # 跨测试共享的填充数据（同一身份，避免每次生成不同数据）
        self._cached_field_values: Dict[str, str] = {}

    # ================================================================
    # 公开 API
    # ================================================================

    def fill_and_submit(
        self,
        fields: List[Dict],
        test_password: str,
        email_xpath: Optional[str] = None,
        max_steps: int = MAX_FORM_STEPS,
    ) -> Dict:
        """填充全表单、提交、捕获反馈（支持多步表单）

        Args:
            fields: FieldClassifier.detect_all_fields() 返回的字段列表
            test_password: 此次测试的密码
            email_xpath: 已知的邮箱字段 XPath（来自 login_link_discovery）
            max_steps: 最大表单页数（超过此值仍无反馈 → 标记为 no_value）

        Returns:
            {
                "submitted": bool,        # 是否成功提交
                "url_changed": bool,      # URL 是否变化
                "new_url": str|None,      # 新 URL
                "dom_errors": list[str],  # DOM 错误文本列表
                "aria_error": str|None,   # aria-invalid / aria-describedby
                "page_alerts": list[str], # 页面级错误横幅
                "network_errors": list,   # CDP 网络响应中的错误
                "source_before": str,     # 提交前页面源码
                "source_after": str,      # 提交后页面源码
                "no_value": bool,         # 多步表单超限仍无反馈
                "steps_completed": int,   # 完成的表单页数
            }
        """
        accumulated = {
            "submitted": False,
            "url_changed": False,
            "new_url": None,
            "dom_errors": [],
            "aria_error": None,
            "page_alerts": [],
            "network_errors": [],
            "source_before": "",
            "source_after": "",
            "no_value": False,
            "steps_completed": 0,
        }

        # 保存初始页面源码（用于全流程 diff）
        try:
            accumulated["source_before"] = self._driver.page_source or ""
        except Exception:
            pass

        current_fields = fields

        for step in range(1, max_steps + 1):
            # 填充当前页 + 提交
            page_result = self._fill_page(current_fields, test_password)

            # 合并结果
            accumulated["steps_completed"] = step
            if page_result.get("submitted"):
                accumulated["submitted"] = True
            if page_result.get("url_changed"):
                accumulated["url_changed"] = True
                accumulated["new_url"] = page_result.get("new_url")
            accumulated["dom_errors"].extend(page_result.get("dom_errors") or [])
            accumulated["page_alerts"].extend(page_result.get("page_alerts") or [])
            if page_result.get("aria_error"):
                accumulated["aria_error"] = page_result.get("aria_error")

            # 检查是否有密码相关反馈
            if self._has_password_feedback(page_result):
                break

            # 无反馈 → 检查是否有下一页（新字段出现）
            if step < max_steps:
                try:
                    time.sleep(1.5)  # 等待下一页渲染
                except Exception:
                    pass
                new_fields = self._detect_new_fields_on_page()
                pw_fields = [f for f in new_fields
                             if f.get("field_type") in (FIELD_PASSWORD, FIELD_CONFIRM_PASSWORD)]
                if pw_fields or len(new_fields) >= 2:
                    # 有新字段 → 继续填下一页
                    current_fields = new_fields
                    continue

            # 无新字段 → 停止
            break
        else:
            # 循环完整执行完（达到 max_steps）仍无反馈
            if not accumulated["dom_errors"] and not accumulated["page_alerts"] \
                    and not accumulated["aria_error"] and not accumulated["url_changed"]:
                accumulated["no_value"] = True

        # 最终保存提交后源码
        try:
            accumulated["source_after"] = self._driver.page_source or ""
        except Exception:
            pass

        self._rate.record_submission()
        return accumulated

    def _fill_page(self, fields: List[Dict], test_password: str) -> Dict:
        """填充单页表单并提交，返回页面级结果"""
        result = {
            "submitted": False,
            "url_changed": False,
            "new_url": None,
            "dom_errors": [],
            "aria_error": None,
            "page_alerts": [],
        }

        # 1. 排序字段
        ordered = FieldClassifier.sort_by_position(fields)

        # 2. 逐字段填充
        password_field = None
        for field in ordered:
            ftype = field.get("field_type", "")
            if ftype == FIELD_CAPTCHA:
                continue

            xpath = field.get("xpath", "")
            if not xpath:
                continue

            try:
                el = self._find_element(xpath, field)
                if el is None:
                    continue

                if ftype == FIELD_PASSWORD:
                    password_field = el
                    self._fill_password(el, test_password)
                elif ftype == FIELD_CONFIRM_PASSWORD:
                    self._fill_password(el, test_password)
                elif ftype == FIELD_CHECKBOX_TERMS:
                    self._check_checkbox(el)
                elif ftype == FIELD_SELECT or field.get("tag") == "select":
                    self._fill_select(el)
                else:
                    value = self._get_or_generate(field, ftype)
                    self._human_type(el, value)

                self._rate.delay_between_fields()

            except Exception:
                continue

        # 3. 提交前等待
        if not self._allow_submit:
            result["submission_blocked"] = True
            return result

        self._rate.delay_before_submit()

        # 4. 找到并点击提交按钮
        old_url = self._driver.current_url
        try:
            submit_btn = self._find_submit_button()
            if submit_btn:
                old_timeout = None
                try:
                    old_timeout = self._driver.timeouts.page_load
                except Exception:
                    pass
                try:
                    self._driver.set_page_load_timeout(10)
                except Exception:
                    pass
                try:
                    self._js_click(submit_btn)
                    result["submitted"] = True
                finally:
                    if old_timeout is not None:
                        try:
                            self._driver.set_page_load_timeout(old_timeout)
                        except Exception:
                            pass
        except Exception:
            pass

        # 5. 等待响应
        time.sleep(2.0)
        try:
            new_url = self._driver.current_url
            if new_url != old_url:
                result["url_changed"] = True
                result["new_url"] = new_url
        except Exception:
            pass

        # 6. 捕获 DOM 反馈
        result["dom_errors"] = self._capture_dom_errors(password_field)
        result["aria_error"] = self._capture_aria_error(password_field)
        result["page_alerts"] = self._capture_page_alerts()

        return result

    def _has_password_feedback(self, page_result: Dict) -> bool:
        """快速判断页面结果中是否包含密码相关的反馈"""
        dom_errors = page_result.get("dom_errors") or []
        page_alerts = page_result.get("page_alerts") or []
        aria_error = page_result.get("aria_error")

        if aria_error and aria_error.strip().lower() not in ("", "false", "valid"):
            return True
        if dom_errors:
            return True
        if page_alerts:
            return True
        if page_result.get("url_changed"):
            return True
        return False

    def _detect_new_fields_on_page(self) -> List[Dict]:
        """检测当前页面上是否有新的表单字段（用于多步表单）"""
        try:
            # 通过 CDP 执行 JS 检测当前页面可见输入字段
            result = self._driver.execute_cdp_cmd("Runtime.evaluate", {
                "expression": """
                    (function() {
                        var fields = [];
                        var inputs = document.querySelectorAll(
                            'input:not([type="hidden"]), textarea, select');
                        for (var i = 0; i < inputs.length; i++) {
                            var el = inputs[i];
                            if (el.offsetParent === null) continue;  // 不可见
                            fields.push({
                                tag: el.tagName.toLowerCase(),
                                type: el.type || '',
                                name: el.name || '',
                                id: el.id || '',
                                placeholder: el.placeholder || '',
                                autocomplete: el.autocomplete || '',
                                required: el.required || el.getAttribute('aria-required') === 'true',
                                xpath: (function(e) {
                                    if (e.id) return '//*[@id=\"' + e.id + '\"]';
                                    var parts = [];
                                    while (e && e.nodeType === 1) {
                                        var idx = 1;
                                        var sib = e.previousSibling;
                                        while (sib) {
                                            if (sib.nodeType === 1 && sib.tagName === e.tagName) idx++;
                                            sib = sib.previousSibling;
                                        }
                                        parts.unshift(e.tagName.toLowerCase() + '[' + idx + ']');
                                        e = e.parentNode;
                                    }
                                    return '/' + parts.join('/');
                                })(el)
                            });
                        }
                        return JSON.stringify(fields);
                    })()
                """,
                "returnByValue": True,
            })
            import json
            raw = result.get("result", {}).get("value", "[]")
            if isinstance(raw, str):
                return json.loads(raw)
            return raw if isinstance(raw, list) else []
        except Exception:
            return []

    # ================================================================
    # 字段填充
    # ================================================================

    def _find_element(self, xpath: str, field_info: Dict = None):
        """通过 XPath 查找元素，支持 iframe 内元素

        如果字段来自 iframe（field_info 中有 frame_index >= 0），
        先切换到对应 iframe 再查找，完成后切换回默认 context。
        如果 `_ensure_page_ready()` 已将 iframe URL 直接导航到顶层，
        frame_index 可能仍有值但 iframe 已不在 DOM 中，此时回退到直接查找。
        """
        from selenium.webdriver.common.by import By
        frame_index = -1
        if field_info and isinstance(field_info, dict):
            frame_index = field_info.get("frame_index", -1)

        try:
            if frame_index >= 0:
                # 尝试切换到 iframe
                iframes = self._driver.find_elements(By.TAG_NAME, "iframe")
                if frame_index < len(iframes):
                    try:
                        self._driver.switch_to.frame(iframes[frame_index])
                        el = self._driver.find_element(By.XPATH, xpath)
                        self._driver.switch_to.default_content()
                        return el
                    except Exception:
                        # 如果切换 iframe 失败，回退到默认 context 后继续
                        try:
                            self._driver.switch_to.default_content()
                        except Exception:
                            pass

            # 直接查找（主 frame 或 iframe 已通过 _ensure_page_ready 导航到顶层）
            return self._driver.find_element(By.XPATH, xpath)
        except Exception:
            return None

    def _fill_password(self, el, password: str) -> None:
        """使用 JS value setter + input/change 事件填充密码字段"""
        js_set = """
            var elm = arguments[0], txt = arguments[1];
            elm.removeAttribute('aria-invalid');
            var setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value').set;
            setter.call(elm, txt);
            elm.dispatchEvent(new Event('input', {bubbles: true}));
            elm.dispatchEvent(new Event('change', {bubbles: true}));
        """
        try:
            self._driver.execute_script(js_set, el, password)
        except Exception:
            pass

    def _human_type(self, el, text: str) -> None:
        """逐字符输入（模拟人类打字节奏）"""
        try:
            el.clear()
        except Exception:
            pass

        js_set = """
            var elm = arguments[0], txt = arguments[1];
            var setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value').set;
            setter.call(elm, txt);
            elm.dispatchEvent(new Event('input', {bubbles: true}));
            elm.dispatchEvent(new Event('change', {bubbles: true}));
        """
        try:
            self._driver.execute_script(js_set, el, text)
        except Exception:
            pass

        self._rate.delay_between_keystrokes()

    def _check_checkbox(self, el) -> None:
        """勾选 checkbox 或 radio"""
        try:
            if not el.is_selected():
                el.click()
        except Exception:
            try:
                self._driver.execute_script("arguments[0].click();", el)
            except Exception:
                pass

    def _fill_select(self, el) -> None:
        """随机选择一个非空非禁用 option"""
        from selenium.webdriver.support.ui import Select
        try:
            sel = Select(el)
            options = [o for o in sel.options if o.get_attribute("value")]
            if options:
                import random
                choice = random.choice(options)
                sel.select_by_value(choice.get_attribute("value"))
        except Exception:
            pass

    def _get_or_generate(self, field: Dict, field_type: str) -> str:
        """获取字段的填充值（优先缓存，避免同一身份生成不一致数据）"""
        cache_key = field.get("name") or field.get("id") or field.get("xpath", "")
        if cache_key in self._cached_field_values:
            return self._cached_field_values[cache_key]

        value = self._data.generate(field_type)
        self._cached_field_values[cache_key] = value
        return value

    # ================================================================
    # 提交按钮定位
    # ================================================================

    def _find_submit_button(self):
        """定位注册表单的提交按钮"""
        from selenium.webdriver.common.by import By

        # 策略 1: 按 CSS 选择器搜索
        for selector in self._SUBMIT_SELECTORS:
            try:
                elements = self._driver.find_elements(By.CSS_SELECTOR, selector)
                for el in elements:
                    if self._is_submit_button(el):
                        return el
            except Exception:
                continue

        # 策略 2: 搜索所有 <a> 标签
        try:
            elements = self._driver.find_elements(By.TAG_NAME, "a")
            for el in elements:
                if self._is_submit_button(el):
                    return el
        except Exception:
            pass

        return None

    def _is_submit_button(self, el) -> bool:
        """判断元素是否为提交/注册按钮"""
        try:
            if not el.is_displayed():
                return False
            if not el.is_enabled():
                return False
        except Exception:
            return False

        try:
            text = (el.text or el.get_attribute("value") or el.get_attribute("innerText") or "").strip().lower()
        except Exception:
            return False

        # 英文关键词匹配
        for kw in self._SUBMIT_KEYWORDS_EN:
            if kw in text:
                return True

        # 中文关键词匹配
        for kw in self._SUBMIT_KEYWORDS_CN:
            if kw in text:
                return True

        return False

    def _js_click(self, el) -> None:
        """通过 JS 点击元素（绕过 Selenium 点击拦截）"""
        try:
            el.click()
        except Exception:
            try:
                self._driver.execute_script("arguments[0].click();", el)
            except Exception:
                pass

    # ================================================================
    # 反馈捕获
    # ================================================================

    def _capture_dom_errors(self, password_el) -> List[str]:
        """捕获密码字段附近的 DOM 错误元素文本

        关键：搜索范围限定在密码字段的 ancestor chain 和最近 form 内，
        而非整个页面。避免将姓名/邮箱/手机等其他字段的错误误判为密码错误。
        """
        errors = []
        # 如果有关联的 aria-describedby，提取其文本
        if password_el:
            try:
                describedby = password_el.get_attribute("aria-describedby")
                if describedby:
                    for desc_id in describedby.split():
                        try:
                            desc_el = self._driver.find_element("id", desc_id)
                            text = (desc_el.text or "").strip()
                            if text:
                                errors.append(text)
                        except Exception:
                            pass
            except Exception:
                pass

        # ── 构建 scoped 搜索根：password_el 的 ancestor chain + 最近 form ──
        search_roots = []
        if password_el:
            try:
                # 通过 JS 收集 ancestor 元素（向上 4 层 + form 容器）
                # 这些将作为 CSS 选择器搜索的限定范围
                search_roots.append(password_el)
                parent = password_el
                for _ in range(4):
                    try:
                        parent = parent.find_element("xpath", "..")
                        search_roots.append(parent)
                    except Exception:
                        break
                # 最近的 form
                try:
                    form = password_el.find_element("xpath", "./ancestor::form[1]")
                    if form not in search_roots:
                        search_roots.append(form)
                except Exception:
                    pass
            except Exception:
                pass

        # 搜索 error/invalid 类元素（限定在 search_roots 范围内）
        error_selectors = [
            '[class*="error"]', '[class*="invalid"]', '[class*="warning"]',
            '[class*="danger"]', '[role="alert"]', '[aria-live="polite"]',
            '.form-feedback', '.field-error', '.input-error', '.form-error',
            '.help-block', '.help-inline',
        ]
        from selenium.webdriver.common.by import By

        # 如果没有有效的 search_roots，回退到整个文档搜索
        roots = search_roots if search_roots else [self._driver]
        for sel in error_selectors:
            try:
                for root in roots:
                    try:
                        elements = root.find_elements(By.CSS_SELECTOR, sel)
                        for el in elements[:5]:  # 限制数量
                            try:
                                if el.is_displayed():
                                    text = (el.text or "").strip()
                                    if text and len(text) > 2:
                                        errors.append(text)
                            except Exception:
                                pass
                    except Exception:
                        pass
            except Exception:
                pass

        return errors

    def _capture_aria_error(self, password_el) -> Optional[str]:
        """捕获密码字段的 aria-invalid 状态"""
        if not password_el:
            return None
        try:
            v = password_el.get_attribute("aria-invalid")
            return v
        except Exception:
            return None

    def _capture_page_alerts(self) -> List[str]:
        """捕获页面级错误横幅"""
        alerts = []
        from selenium.webdriver.common.by import By
        alert_selectors = [
            '.alert', '.notice', '.message', '.notification',
            '.toast', '.flash', '.banner',
            '[class*="alert"]', '[class*="notice"]', '[class*="message"]',
        ]
        for sel in alert_selectors:
            try:
                elements = self._driver.find_elements(By.CSS_SELECTOR, sel)
                for el in elements[:5]:
                    try:
                        if el.is_displayed():
                            text = (el.text or "").strip()
                            if text and len(text) > 2:
                                alerts.append(text)
                    except Exception:
                        pass
            except Exception:
                pass
        return alerts
