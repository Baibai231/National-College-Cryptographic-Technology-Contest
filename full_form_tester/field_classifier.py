"""
field_classifier.py — 表单字段全量检测与类型分类

通过 CDP Runtime.evaluate 在注册页执行 JS，
检测 <form> 内所有 visible 字段并按类型规则分类。

复用:
  - utils.login_link_discovery.LoginLinkDiscovery._cdp_eval() 模式
  - utils.Regexes 字段类型正则
"""

import json
import re
from typing import List, Dict, Optional

from utils.Regexes import Regexes


# ================================================================
# 字段类型枚举
# ================================================================

FIELD_EMAIL            = "EMAIL"
FIELD_PASSWORD         = "PASSWORD"
FIELD_CONFIRM_PASSWORD = "CONFIRM_PASSWORD"
FIELD_USERNAME         = "USERNAME"
FIELD_FULL_NAME        = "FULL_NAME"
FIELD_FIRST_NAME       = "FIRST_NAME"
FIELD_LAST_NAME        = "LAST_NAME"
FIELD_PHONE            = "PHONE"
FIELD_COMPANY          = "COMPANY"
FIELD_URL              = "URL"
FIELD_ADDRESS          = "ADDRESS"
FIELD_CITY             = "CITY"
FIELD_COUNTRY          = "COUNTRY"
FIELD_ZIPCODE          = "ZIPCODE"
FIELD_STREET           = "STREET"
FIELD_BIRTHDATE        = "BIRTHDATE"
FIELD_AGE              = "AGE"
FIELD_GENDER           = "GENDER"
FIELD_BIO              = "BIO"
FIELD_CHECKBOX_TERMS   = "CHECKBOX_TERMS"
FIELD_SELECT           = "SELECT"
FIELD_CAPTCHA          = "CAPTCHA"
FIELD_UNKNOWN          = "UNKNOWN"

# 需用户交互的字段类型（checkbox）
_INTERACTIVE_TYPES = {FIELD_CHECKBOX_TERMS}

# 需跳过的字段类型
_SKIP_TYPES = {FIELD_CAPTCHA}


class FieldClassifier:
    """全表单字段检测与分类器"""

    # ================================================================
    # 字段类型识别规则
    # 每条规则: (field_type, regex, 匹配目标)
    # 匹配目标: "id"|"name"|"label"|"placeholder"|"autocomplete"
    # ================================================================

    _RULES = [
        # --- 自动完成属性（HTML5 标准，最可靠） ---
        ("autocomplete", FIELD_EMAIL,            r"^email$"),
        ("autocomplete", FIELD_PASSWORD,         r"^new-password$"),
        ("autocomplete", FIELD_CONFIRM_PASSWORD, r"^new-password$"),  # 同 new-password
        ("autocomplete", FIELD_USERNAME,         r"^username$"),
        ("autocomplete", FIELD_FULL_NAME,        r"^name$"),
        ("autocomplete", FIELD_FIRST_NAME,       r"^(given-name|fname)$"),
        ("autocomplete", FIELD_LAST_NAME,        r"^(family-name|lname)$"),
        ("autocomplete", FIELD_PHONE,            r"^tel"),
        ("autocomplete", FIELD_COMPANY,          r"^organization"),
        ("autocomplete", FIELD_ADDRESS,          r"^street-address"),
        ("autocomplete", FIELD_CITY,             r"^address-level2"),
        ("autocomplete", FIELD_COUNTRY,          r"^country"),
        ("autocomplete", FIELD_ZIPCODE,          r"^postal-code"),
        ("autocomplete", FIELD_BIRTHDATE,        r"^bday"),
    ]

    # ================================================================
    # 中文 regex 补充（原 Regexes 以英文为主）
    # ================================================================

    _CN_LABEL_PATTERNS = {
        FIELD_EMAIL:            r"(电子)?邮箱|邮件|e[\s\-_]?mail",
        FIELD_PASSWORD:         r"^(密码|口令|密碼)$",
        FIELD_CONFIRM_PASSWORD: r"确认密码|確認密碼|再次输入|重复密码|验证密码|密码确认",
        FIELD_USERNAME:         r"^用户名|账号|帐户|用戶名|昵称$",
        FIELD_FULL_NAME:        r"^(真实)?姓名|名称|全名$",
        FIELD_PHONE:            r"手机|电话|联系方式|联系电话",
        FIELD_COMPANY:          r"公司|企业|单位|机构|组织",
        FIELD_ADDRESS:          r"地址|住址|所在地",
        FIELD_CITY:             r"^(城市|所在城市)$",
        FIELD_ZIPCODE:          r"邮编|邮政编码",
        FIELD_BIRTHDATE:        r"生日|出生日期|出生年月",
        FIELD_GENDER:           r"性别",
        FIELD_BIO:              r"简介|个人介绍|自我介绍|签名",
        FIELD_CAPTCHA:          r"验证码|captcha|验证|校验码",
    }

    def __init__(self, cdp_eval_fn):
        """
        Args:
            cdp_eval_fn: LoginLinkDiscovery._cdp_eval 或等效的 CDP 执行函数
                        签名: fn(js_expression: str) -> Any
        """
        self._cdp_eval = cdp_eval_fn

    # ================================================================
    # 公开 API
    # ================================================================

    def detect_all_fields(self) -> List[Dict]:
        """检测注册页面上所有表单字段并分类

        Returns:
            [
                {
                    "xpath": "//*[@id='email']",
                    "field_type": "EMAIL",
                    "required": True,
                    "element_tag": "input",
                    "element_type": "email",
                    "label_text": "邮箱地址",
                    "placeholder": "请输入邮箱",
                    "name_attr": "user_email",
                },
                ...
            ]
        """
        raw = self._cdp_eval(self._build_detection_js())
        if not raw:
            print("[field_classifier] _cdp_eval returned falsy:", repr(raw))
            return []
        if isinstance(raw, str):
            try:
                raw_fields = json.loads(raw)
            except json.JSONDecodeError as e:
                print(f"[field_classifier] JSON decode failed: {e}")
                print(f"[field_classifier] raw (first 500 chars): {str(raw)[:500]}")
                return []
        else:
            raw_fields = raw
        if not raw_fields:
            print("[field_classifier] raw_fields is empty after parse")
            return []
        return [self._classify(f) for f in raw_fields]

    # ================================================================
    # JS 检测脚本
    # ================================================================

    def _build_detection_js(self) -> str:
        """构建在浏览器中执行的字段检测 JS"""
        return """
(function() {
    // 辅助: 获取 XPath
    function _xpath(el) {
        if (typeof getXPath === 'function') return getXPath(el);
        if (typeof gPt === 'function') return gPt(el);
        var parts = [];
        while (el && el.nodeType === 1) {
            var idx = 1;
            var sib = el.previousSibling;
            while (sib) {
                if (sib.nodeType === 1 && sib.tagName === el.tagName) idx++;
                sib = sib.previousSibling;
            }
            parts.unshift(el.tagName.toLowerCase() + '[' + idx + ']');
            el = el.parentNode;
        }
        return '/' + parts.join('/');
    }

    // 辅助: 获取关联 label 文本
    function _label(el) {
        // 1. <label for="id">
        if (el.id) {
            var lbl = document.querySelector('label[for="' + el.id + '"]');
            if (lbl) return (lbl.innerText || lbl.textContent || '').trim();
        }
        // 2. 父级 <label>
        var p = el.parentElement;
        while (p && p.tagName !== 'BODY') {
            if (p.tagName === 'LABEL') return (p.innerText || p.textContent || '').trim();
            p = p.parentElement;
        }
        // 3. 前一个兄弟 <label>
        var prev = el.previousElementSibling;
        if (prev && prev.tagName === 'LABEL') return (prev.innerText || prev.textContent || '').trim();
        return '';
    }

    // 辅助: 元素是否可见（非 hidden, 非 display:none, 尺寸 > 0）
    function _visible(el) {
        if (!el) return false;
        var style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
        if (el.type === 'hidden') return false;
        if (el.offsetHeight === 0 && el.offsetWidth === 0 && el.tagName !== 'SELECT') return false;
        return true;
    }

    // 主逻辑: 收集所有表单控件
    var fields = [];
    var seen = {};

    // 候选选择器: input, textarea, select, checkbox
    var candidates = document.querySelectorAll(
        'input, textarea, select, ' +
        'input[type="checkbox"], input[type="radio"]'
    );

    for (var i = 0; i < candidates.length; i++) {
        var el = candidates[i];
        if (!_visible(el) && el.type !== 'checkbox' && el.type !== 'radio') continue;

        var xp = _xpath(el);
        if (seen[xp]) continue;
        seen[xp] = true;

        var tag = (el.tagName || '').toLowerCase();
        var elType = (el.type || '').toLowerCase();
        var name = el.name || el.getAttribute('name') || '';
        var elId = el.id || '';
        var placeholder = el.placeholder || el.getAttribute('placeholder') || '';
        var autocomplete = el.getAttribute('autocomplete') || '';
        var ariaLabel = el.getAttribute('aria-label') || '';
        var labelText = _label(el);
        var required = el.required === true ||
                       el.getAttribute('required') !== null ||
                       el.getAttribute('aria-required') === 'true';
        var className = el.className || '';

        fields.push({
            xpath: xp,
            tag: tag,
            el_type: elType,
            name: name,
            id: elId,
            placeholder: placeholder,
            autocomplete: autocomplete,
            aria_label: ariaLabel,
            label_text: labelText,
            required: required,
            class_name: className
        });
    }

    // 也收集 iframe 中的字段（如果注入到顶层 frame）
    try {
        var iframes = document.querySelectorAll('iframe');
        for (var f = 0; f < iframes.length; f++) {
            try {
                var doc = iframes[f].contentDocument || iframes[f].contentWindow.document;
                if (!doc) continue;
                var subCandidates = doc.querySelectorAll('input, textarea, select');
                for (var j = 0; j < subCandidates.length; j++) {
                    var sel = subCandidates[j];
                    var sx = _xpath(sel);
                    if (seen[sx]) continue;
                    seen[sx] = true;
                    fields.push({
                        xpath: sx,
                        tag: (sel.tagName || '').toLowerCase(),
                        el_type: (sel.type || '').toLowerCase(),
                        name: sel.name || '',
                        id: sel.id || '',
                        placeholder: sel.placeholder || '',
                        autocomplete: sel.getAttribute('autocomplete') || '',
                        aria_label: sel.getAttribute('aria-label') || '',
                        label_text: _label(sel),
                        required: sel.required === true || sel.getAttribute('required') !== null,
                        class_name: sel.className || '',
                        iframe: true
                    });
                }
            } catch(e) {}
        }
    } catch(e) {}

    return JSON.stringify(fields);
})();
"""

    # ================================================================
    # 字段分类逻辑
    # ================================================================

    def _classify(self, raw: Dict) -> Dict:
        """根据属性/标签/placeholder 等识别字段类型"""
        el_type = raw.get("el_type", "")
        tag = raw.get("tag", "")
        label = raw.get("label_text", "")
        placeholder = raw.get("placeholder", "")
        name = raw.get("name", "")
        el_id = raw.get("id", "")
        autocomplete = raw.get("autocomplete", "")
        aria_label = raw.get("aria_label", "")

        # ---- Layer 1: type 属性直接判断 ----
        if el_type == "email":
            return {**raw, "field_type": FIELD_EMAIL}
        if el_type == "password":
            return {**raw, "field_type": self._distinguish_password(raw)}
        if el_type == "tel":
            return {**raw, "field_type": FIELD_PHONE}
        if el_type == "url":
            return {**raw, "field_type": FIELD_URL}
        if el_type in ("date", "datetime-local"):
            return {**raw, "field_type": FIELD_BIRTHDATE}
        if el_type == "checkbox":
            return {**raw, "field_type": self._classify_checkbox(raw)}
        if tag == "select":
            return {**raw, "field_type": self._classify_select(raw)}

        # ---- Layer 2: autocomplete 属性 ----
        if autocomplete:
            field_type = self._match_autocomplete(autocomplete)
            if field_type:
                return {**raw, "field_type": field_type}

        # ---- Layer 3: label 文本匹配（中文优先） ----
        if label:
            field_type = self._match_label(label)
            if field_type:
                return {**raw, "field_type": field_type}

        # ---- Layer 4: placeholder 文本 ----
        if placeholder:
            field_type = self._match_label(placeholder)
            if field_type:
                return {**raw, "field_type": field_type}

        # ---- Layer 5: aria-label 文本 ----
        if aria_label:
            field_type = self._match_label(aria_label)
            if field_type:
                return {**raw, "field_type": field_type}

        # ---- Layer 6: id / name 正则（复用 Regexes） ----
        combined = f"{el_id} {name} {placeholder} {label} {aria_label}".lower()
        field_type = self._match_regexes(combined)
        if field_type:
            return {**raw, "field_type": field_type}

        # ---- Layer 7: CAPTCHA 检测 ----
        if self._is_captcha(raw):
            return {**raw, "field_type": FIELD_CAPTCHA}

        # ---- Fallback ----
        return {**raw, "field_type": FIELD_UNKNOWN}

    def _distinguish_password(self, raw: Dict) -> str:
        """区分 password / confirm_password"""
        combined = " ".join([
            raw.get("label_text", ""),
            raw.get("placeholder", ""),
            raw.get("name", ""),
            raw.get("id", ""),
            raw.get("aria_label", ""),
        ]).lower()

        confirm_patterns = [
            r"confirm", r"retype", r"repeat", r"verify", r"again",
            r"确认", r"再次", r"重复", r"验证密码", r"密码确认",
            r"re-enter", r"reenter",
        ]
        for pat in confirm_patterns:
            if re.search(pat, combined, re.IGNORECASE):
                return FIELD_CONFIRM_PASSWORD
        return FIELD_PASSWORD

    def _classify_checkbox(self, raw: Dict) -> str:
        """分类 checkbox（条款 / 订阅 / 其他）"""
        combined = " ".join([
            raw.get("label_text", ""), raw.get("name", ""),
            raw.get("id", ""), raw.get("aria_label", ""),
        ]).lower()

        terms_patterns = [
            r"agree", r"terms", r"policy", r"privacy", r"accept",
            r"同意", r"条款", r"协议", r"隐私", r"接受", r"已阅读",
            r"condition", r"consent", r"gdpr", r"i have read",
        ]
        for pat in terms_patterns:
            if re.search(pat, combined, re.IGNORECASE):
                return FIELD_CHECKBOX_TERMS

        # 订阅类
        subscribe_patterns = [
            r"subscribe", r"newsletter", r"marketing", r"promotion",
            r"订阅", r"新闻", r"推广",
        ]
        for pat in subscribe_patterns:
            if re.search(pat, combined, re.IGNORECASE):
                return FIELD_CHECKBOX_TERMS

        return FIELD_CHECKBOX_TERMS  # checkbox 默认视为条款类

    def _classify_select(self, raw: Dict) -> str:
        """分类 select 元素"""
        combined = " ".join([
            raw.get("label_text", ""), raw.get("name", ""),
            raw.get("id", ""),
        ]).lower()

        country_pat = r"country|国家|国籍"
        if re.search(country_pat, combined, re.IGNORECASE):
            return FIELD_COUNTRY

        gender_pat = r"gender|sex|性别"
        if re.search(gender_pat, combined, re.IGNORECASE):
            return FIELD_GENDER

        return FIELD_SELECT

    # ================================================================
    # 匹配子方法
    # ================================================================

    def _match_autocomplete(self, autocomplete: str) -> Optional[str]:
        """根据 autocomplete 属性匹配字段类型"""
        for attr, ftype, pat in self._RULES:
            if attr == "autocomplete" and re.search(pat, autocomplete, re.IGNORECASE):
                return ftype
        return None

    def _match_label(self, text: str) -> Optional[str]:
        """根据 label/placeholder 文本匹配字段类型（中文优先）"""
        for ftype, pat in self._CN_LABEL_PATTERNS.items():
            if re.search(pat, text, re.IGNORECASE):
                return ftype
        # 尝试 Regexes 中的英文模式
        return self._match_regexes(text)

    def _match_regexes(self, text: str) -> Optional[str]:
        """使用 utils.Regexes 中的英文正则匹配"""
        text_lower = text.lower()

        # 按优先级排列
        checks = [
            (FIELD_EMAIL,    Regexes.EMAIL),
            (FIELD_PASSWORD, Regexes.PASSWORD),
            (FIELD_FULL_NAME, Regexes.FULL_NAME),
            (FIELD_FIRST_NAME, Regexes.FIRST_NAME),
            (FIELD_LAST_NAME, Regexes.LAST_NAME),
            (FIELD_USERNAME, Regexes.USERNAME),
            (FIELD_PHONE,   Regexes.PHONE),
            (FIELD_COMPANY, Regexes.COMPANY_NAME),
            (FIELD_ADDRESS, Regexes.ADDRESS),
            (FIELD_ZIPCODE, Regexes.ZIPCODE),
            (FIELD_CITY,    Regexes.CITY),
            (FIELD_COUNTRY, Regexes.COUNTRY),
            (FIELD_STREET,  Regexes.STREET),
            (FIELD_BIRTHDATE, Regexes.BIRTHDATE),
            (FIELD_AGE,     Regexes.AGE),
            (FIELD_URL,     Regexes.URL),
        ]

        for ftype, pattern in checks:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return ftype
        return None

    def _is_captcha(self, raw: Dict) -> bool:
        """判断是否为验证码字段"""
        combined = " ".join([
            raw.get("label_text", ""), raw.get("placeholder", ""),
            raw.get("name", ""), raw.get("id", ""),
            raw.get("class_name", ""), raw.get("aria_label", ""),
        ]).lower()

        captcha_patterns = [
            r"captcha", r"recaptcha", r"验证码", r"captcha",
            r"g-recaptcha", r"h-captcha", r"turnstile",
        ]
        return any(re.search(p, combined, re.IGNORECASE) for p in captcha_patterns)

    # ================================================================
    # 静态工具
    # ================================================================

    @staticmethod
    def get_fillable_fields(fields: List[Dict]) -> List[Dict]:
        """过滤出需要填充值的字段（排除 submit/reset/button/hidden/image）"""
        skip_tags = {"submit", "reset", "button", "hidden", "image"}
        return [
            f for f in fields
            if f.get("element_tag") not in skip_tags
            and f.get("el_type") not in skip_tags
        ]

    @staticmethod
    def get_required_fields(fields: List[Dict]) -> List[Dict]:
        """过滤出必填字段"""
        return [f for f in fields if f.get("required")]

    @staticmethod
    def sort_by_position(fields: List[Dict]) -> List[Dict]:
        """按 DOM 位置排序（top→bottom, left→right），但标记 CAPTCHA 放最后"""
        # 所有字段保持原始顺序（querySelectorAll 已按 DOM 序返回）
        captcha_fields = [f for f in fields if f.get("field_type") == FIELD_CAPTCHA]
        normal_fields = [f for f in fields if f.get("field_type") != FIELD_CAPTCHA]
        return normal_fields + captcha_fields
