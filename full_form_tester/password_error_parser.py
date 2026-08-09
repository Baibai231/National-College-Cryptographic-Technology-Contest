"""
password_error_parser.py — 服务端密码错误反馈解析

从提交后的页面 DOM / 网络响应 / HTML diff 中提取密码相关的错误信息，
判断密码是否被接受。

复用并扩展:
  - utils/login_policy_utils/LoginRegexes.py 的 ERROR_MESSAGE
  - utils/PasswordPolicy.py 的多层错误检测思路
"""

import difflib
import json
import re
from typing import Optional, Dict, Any, Tuple


class PasswordErrorParser:
    """密码错误反馈解析器"""

    # ================================================================
    # 多语言密码错误正则
    # ================================================================

    # 英文密码错误
    _PASSWORD_ERROR_EN: str = (
        r"(password|passwd|pwd)"
        r".{0,30}"
        r"(incorrect|invalid|wrong|not\s*match|doesn'?t\s*match|"
        r"too\s*short|too\s*long|must|require|need|"
        r"at\s*least|minimum|maximum|"
        r"contain|include|"
        r"special|digit|number|letter|uppercase|lowercase|"
        r"character|symbol|"
        r"8\s*characters|strength|weak)"
    )

    # 中文密码错误
    _PASSWORD_ERROR_CN: str = (
        r"(密码|口令|密碼)"
        r".{0,30}"
        r"(错误|不正确|无效|不对|不匹配|"
        r"太短|太長|太长|过长|过短|"
        r"必须|需要|必需|"
        r"至少|最少|最多|最长|最短|"
        r"包含|包括|含有|"
        r"数字|字母|大写|小写|特殊|符号|字符|位数|"
        r"长度|组合|复杂度)"
    )

    # 通用错误关键词（不限定 password 上下文，但只在密码字段附近出现时才算）
    _GENERIC_ERROR_KEYWORDS: str = (
        r"\b(incorrect|wrong|invalid|fail|error|"
        r"错误|不正确|无效|失败|不符合)\b"
    )

    # 编译复用
    _RE_PASSWORD_ERROR_EN: re.Pattern = re.compile(_PASSWORD_ERROR_EN, re.IGNORECASE)
    _RE_PASSWORD_ERROR_CN: re.Pattern = re.compile(_PASSWORD_ERROR_CN, re.IGNORECASE)
    _RE_GENERIC_ERROR: re.Pattern = re.compile(_GENERIC_ERROR_KEYWORDS, re.IGNORECASE)

    # 正向反馈关键词（说明注册成功 / 密码被接受）
    _SUCCESS_KEYWORDS: str = (
        r"(welcome|success|verified|activated|created|registered|"
        r"确认邮件|验证邮件|注册成功|创建成功|欢迎|"
        r"check\s*your\s*email|verify\s*your|激活|"
        r"dashboard|profile|account\s*settings)"
    )
    _RE_SUCCESS: re.Pattern = re.compile(_SUCCESS_KEYWORDS, re.IGNORECASE)

    # 密码字段附近错误元素的 CSS 选择器
    _ERROR_ELEMENT_SELECTORS: str = (
        '[class*="error"],[class*="invalid"],[class*="hint"],'
        '[class*="warning"],[class*="danger"],[class*="alert"],'
        '[class*="message"],[class*="notice"],[class*="tip"],'
        '[role="alert"],[aria-live="polite"],[aria-live="assertive"],'
        '.form-feedback,.field-error,.input-error,.form-error'
    )

    def __init__(self):
        self._last_source_before: Optional[str] = None

    # ================================================================
    # 公开 API
    # ================================================================

    def parse(self, result: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """综合解析提交后的反馈

        Args:
            result: form_submitter 返回的结果字典，包含:
                - url_changed: bool
                - new_url: str|None
                - dom_errors: list[str]
                - aria_error: str|None
                - page_alerts: list[str]
                - network_errors: list[str]
                - source_diff: list[str]|None
                - no_value: bool (多步表单超限无反馈)
                - steps_completed: int

        Returns:
            (accepted, error_text)
            - accepted=True  → 密码被接受
            - accepted=False → 密码被拒绝，error_text 包含错误描述
            - accepted=False, error_text=None → 无法判定（视为拒绝）
        """
        # Layer 0: 多步表单超限无反馈 → 无研究价值
        if result.get("no_value"):
            steps = result.get("steps_completed", 0)
            return False, f"NO_VALUE: {steps} 页表单后仍无密码反馈"

        # Layer 1: 页面跳转 → 注册成功
        if result.get("url_changed"):
            new_url = result.get("new_url", "")
            if self._is_success_url(new_url):
                return True, None

        # Layer 2: 密码字段附近的 DOM 错误
        dom_errors = result.get("dom_errors") or []
        for err in dom_errors:
            parsed = self._check_password_error(err)
            if parsed:
                return False, parsed

        # Layer 3: aria-describedby / aria-invalid
        aria_err = result.get("aria_error")
        if aria_err:
            parsed = self._check_password_error(aria_err)
            if parsed:
                return False, parsed
            # 如果是 "false" 说明没错误
            if aria_err.strip().lower() in ("false", "valid", "true"):
                return True, None

        # Layer 4: 页面级错误横幅
        page_alerts = result.get("page_alerts") or []
        for alert in page_alerts:
            parsed = self._check_password_error(alert)
            if parsed:
                return False, parsed

        # Layer 5: 网络请求响应中的错误
        network_errors = result.get("network_errors") or []
        for net_err in network_errors:
            parsed = self._check_password_error(net_err)
            if parsed:
                return False, parsed

        # Layer 6: HTML diff (提交前后差异)
        source_diff = result.get("source_diff") or []
        diff_text = "\n".join(source_diff)
        if diff_text:
            parsed = self._check_password_error(diff_text)
            if parsed:
                return False, parsed
            # diff 中存在成功关键词 → 注册成功
            if self._RE_SUCCESS.search(diff_text):
                return True, None

        # Layer 7: 页面级成功提示
        all_text = " ".join(page_alerts + dom_errors)
        if self._RE_SUCCESS.search(all_text):
            return True, None

        # 无法判定 → 视为拒绝（安全侧）
        return False, None

    def snapshot_source(self, html_source: str) -> None:
        """保存提交前的页面 HTML 快照，用于后续 diff"""
        self._last_source_before = html_source

    def diff_source(self, html_after: str) -> list:
        """与保存的快照对比，返回新增的行"""
        if self._last_source_before is None:
            return []
        before_lines = self._last_source_before.splitlines(keepends=True)
        after_lines = html_after.splitlines(keepends=True)
        differ = difflib.Differ()
        diff = list(differ.compare(before_lines, after_lines))
        # 只保留新增的行（以 '+ ' 开头）
        return [line[2:] for line in diff if line.startswith("+ ")]

    # ================================================================
    # 内部方法
    # ================================================================

    def _check_password_error(self, text: str) -> Optional[str]:
        """检测文本是否包含密码相关错误，返回匹配到的错误片段"""
        if not text:
            return None
        m = self._RE_PASSWORD_ERROR_EN.search(text)
        if m:
            return m.group(0)
        m = self._RE_PASSWORD_ERROR_CN.search(text)
        if m:
            return m.group(0)
        return None

    def _is_success_url(self, url: str) -> bool:
        """判断 URL 是否暗示注册成功"""
        success_patterns = [
            r"/dashboard", r"/profile", r"/account", r"/settings",
            r"/welcome", r"/home", r"/getting-started", r"/onboarding",
            r"success", r"verified", r"activated",
            r"/user/", r"/users/",
        ]
        url_lower = url.lower()
        return any(re.search(p, url_lower) for p in success_patterns)

    # ================================================================
    # 静态工具
    # ================================================================

    @staticmethod
    def extract_text_from_html(html: str) -> str:
        """从 HTML 中粗略提取可见文本"""
        # 移除 script/style 标签内容
        text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        # 移除标签
        text = re.sub(r'<[^>]+>', ' ', text)
        # 合并空白
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    @staticmethod
    def extract_json_errors(response_body: str) -> list:
        """从 JSON 响应体中递归搜索错误消息字段"""
        errors = []
        try:
            data = json.loads(response_body)
        except (json.JSONDecodeError, TypeError):
            return errors

        def _scan(obj, depth=0):
            if depth > 5:
                return
            if isinstance(obj, dict):
                for key, val in obj.items():
                    if isinstance(val, str) and any(
                        kw in key.lower()
                        for kw in ("error", "message", "msg", "password", "pwd")
                    ):
                        errors.append(val)
                    elif isinstance(val, (dict, list)):
                        _scan(val, depth + 1)
            elif isinstance(obj, list):
                for item in obj[:20]:  # 限制扫描范围
                    _scan(item, depth + 1)

        _scan(data)
        return errors
