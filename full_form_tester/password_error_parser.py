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
    # 注意：已从拒绝关键词中移除 "strength" 和 "weak" ——
    # 密码强度指示器（strong/medium/weak）仅描述密码质量，不代表密码不合规。
    _PASSWORD_ERROR_EN: str = (
        r"(password|passwd|pwd)"
        r".{0,30}"
        r"(incorrect|invalid|wrong|not\s*match|doesn'?t\s*match|"
        r"too\s*short|too\s*long|must|require|need|"
        r"at\s*least|minimum|maximum|"
        r"contain|include|"
        r"special|digit|number|letter|uppercase|lowercase|"
        r"character|symbol|"
        r"8\s*characters)"
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

    # ── 非密码字段错误术语 ──
    # 这些文本明确指向姓名/邮箱/手机/用户名/验证码等字段，而非密码字段。
    # 命中任一条目 → 该错误文本不是密码错误，应被过滤。
    _NON_PASSWORD_TERMS: list = [
        # 中文
        "姓名为必填", "姓名不能为空", "请填写姓名", "请填写名字",
        "姓名长度", "姓名格式", "名字不能为空", "请输入姓名",
        "邮箱为必填", "邮箱不能为空", "请填写邮箱", "邮箱格式",
        "邮箱已注册", "邮箱已被注册", "邮箱已存在",
        "手机号为必填", "手机不能为空", "请填写手机", "手机号码",
        "手机号格式", "手机格式", "手机验证",
        "用户名为必填", "用户名不能为空", "请填写用户名",
        "昵称为必填", "昵称不能为空",
        "验证码", "图形验证码", "短信验证码", "请输入验证码",
        "手机验证码", "邮箱验证码",
        "请输入手机号", "请输入邮箱", "请输入用户名",
        "请填写手机号", "请填写手机号码",
        "手机号已被", "用户名已被", "用户名已存在",
        "手机号已注册",
        # 英文
        "name is required", "name required", "full name",
        "please enter your name", "please enter name",
        "email is required", "email required",
        "please enter your email", "please enter email",
        "phone is required", "phone required",
        "please enter your phone", "please enter phone",
        "username is required", "username required",
        "nickname is required", "nickname required",
        "captcha", "verification code",
        "please enter your username",
        "email already", "phone already", "username already",
        "name cannot be empty",
    ]

    # 编译复用
    _RE_PASSWORD_ERROR_EN: re.Pattern = re.compile(_PASSWORD_ERROR_EN, re.IGNORECASE)
    _RE_PASSWORD_ERROR_CN: re.Pattern = re.compile(_PASSWORD_ERROR_CN, re.IGNORECASE)
    _RE_GENERIC_ERROR: re.Pattern = re.compile(_GENERIC_ERROR_KEYWORDS, re.IGNORECASE)

    # 政策描述型文本（声明式 placeholder，如「密码 (6-20位字母与数字、符号组合」）
    # 这类文本是常驻的规则说明，不是拒绝信号；特征是「密码/口令 + 括号内的长度范围」。
    _POLICY_DESC_RANGE_RE: re.Pattern = re.compile(
        r"(?:密码|口令|密碼|password|pwd)\s*[（(]\s*\d+\s*[-~—至]\s*\d+\s*(?:位|个?字符|字|character|char)",
        re.IGNORECASE,
    )

    # 纯强度指示器关键词（不含实际错误语义，仅描述密码质量等级）
    _STRENGTH_ONLY_PATTERNS: list = [
        re.compile(p, re.IGNORECASE) for p in [
            r"^.*\b(?:strength|strong|medium|weak|very\s*weak|very\s*strong)\b.*$",
            r"^.*\b(?:密码强度|强度[：:]\s*(?:强|弱|中|高|低))\b.*$",
        ]
    ]

    # 真正的密码错误关键词（不包含强度描述词）
    _REAL_ERROR_KEYWORDS: list = [
        re.compile(p, re.IGNORECASE) for p in [
            r"\b(?:incorrect|invalid|wrong|error|fail)\b",
            r"\b(?:too\s*short|too\s*long|too\s*weak|too\s*common)\b",
            r"\b(?:doesn'?t\s*match|not\s*match|mismatch)\b",
            r"\b(?:must|require|need|should)\b",
            r"\b(?:at\s*least|at\s*most|minimum|maximum)\b",
            r"\b(?:contain|include)\b",
            r"(?:错误|不正确|无效|不对|不匹配)",
            r"(?:太短|太長|太长|过长|过短)",
            r"(?:必须|需要|必需)",
            r"(?:至少|最少|最多|最长|最短)",
            r"(?:包含|包括|含有)",
        ]
    ]

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
            - accepted=False, error_text=None → 无法判定（调用方记录为 inconclusive）
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
        # 逐行检查，避免把「密码框占位符 + 手机/确认密码报错」等多行拼成一段，
        # 导致占位符里的规则说明被无关的「不能为空」等动词干扰而误判为拒绝。
        source_diff = result.get("source_diff") or []
        for line in source_diff:
            parsed = self._check_password_error(line)
            if parsed:
                return False, parsed
        # diff 中存在成功关键词 → 注册成功
        if source_diff and self._RE_SUCCESS.search("\n".join(source_diff)):
            return True, None

        # Layer 7: 页面级成功提示
        all_text = " ".join(page_alerts + dom_errors)
        if self._RE_SUCCESS.search(all_text):
            return True, None

        # 无法判定：由调用方保留为独立三态，不能作为策略拒绝证据。
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
        """检测文本是否包含密码相关错误，返回匹配到的错误片段

        过滤规则（按优先级）：
          1. 命中 _NON_PASSWORD_TERMS → 非密码字段错误，返回 None
          2. 仅含强度指示器（strong/weak/密码强度）不含实际错误关键词 → 强度提示，返回 None
          3. 政策描述型文本（声明式 placeholder「密码(N-M位…组合」）→ 规则说明，返回 None
          4. 正常匹配密码错误正则
        """
        if not text:
            return None

        # 过滤 1：非密码字段错误
        if self._is_non_password_error(text):
            return None

        # 过滤 2：纯强度指示器（不含实际错误语义）
        if self._is_strength_only(text):
            return None

        # 过滤 3：政策描述型文本（声明式 placeholder 规则说明）
        if self._is_policy_description(text):
            return None

        m = self._RE_PASSWORD_ERROR_EN.search(text)
        if m:
            return m.group(0)
        m = self._RE_PASSWORD_ERROR_CN.search(text)
        if m:
            return m.group(0)
        return None

    def _is_non_password_error(self, text: str) -> bool:
        """检查文本是否明确指向非密码字段（姓名/邮箱/手机/验证码等）"""
        text_lower = text.lower()
        for term in self._NON_PASSWORD_TERMS:
            if term in text_lower:
                return True
        return False

    def _is_strength_only(self, text: str) -> bool:
        """检查文本是否仅描述密码强度等级，不含实际错误语义

        例如 "Password strength: Weak" 或 "密码强度：弱" 仅是质量描述，
        不代表密码不合规。但如果同时包含 "too short" / "至少8位" 等
        真正的错误关键词，则仍视为密码错误。
        """
        # 先检查是否包含真正的错误关键词
        for pat in self._REAL_ERROR_KEYWORDS:
            if pat.search(text):
                return False  # 有实际错误 → 不是纯强度

        # 再检查是否匹配强度模式
        for pat in self._STRENGTH_ONLY_PATTERNS:
            if pat.search(text):
                return True  # 仅有强度描述，无实际错误

        return False

    def _is_policy_description(self, text: str) -> bool:
        """检查文本是否只是「密码规则说明」而非「拒绝报错」

        占位符/帮助文本常写成「密码 (6-20位字母与数字、符号组合」这种声明式
        规则描述（密码 + 括号内长度范围 + 字符类别列举），会被中文错误正则
        误匹配（含"字母/数字/符号/组合"关键词）。真正的拒绝报错是祈使式
        （"密码太短/密码需包含…"）。区分依据：
        - 含「密码(N-M位…」声明式范围说明；
        - 且不含祈使式错误动词（错误/不正确/无效/太短/太长/必须/需/至少/不能…）。
        """
        if not self._POLICY_DESC_RANGE_RE.search(text):
            return False
        for kw in (
            "错误", "不正确", "无效", "不对", "不匹配", "不符合",
            "太短", "太长", "过长", "过短",
            "必须", "必需", "需要", "需", "应", "应当",
            "至少", "最少", "不能", "不得",
        ):
            if kw in text:
                return False
        return True

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
