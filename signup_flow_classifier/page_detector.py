"""页面状态识别：只观察可见、可交互的注册控件。

这个模块不执行点击。真实网站上的自动操作必须经过 navigator.py 的安全检查。
"""
import re
from typing import List, Optional
from urllib.parse import urljoin, urlparse

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

from signup_flow_classifier.flow_types import PageState


_EMAIL_HINTS = [
    "email", "e-mail", "mail", "邮箱", "电子邮件", "correo electrónico",
    "adresse e-mail", "メールアドレス", "이메일", "электронная почта",
]
_PHONE_HINTS = [
    "phone", "tel", "mobile", "手机号", "手机号码", "teléfono", "téléphone",
    "telefonnummer", "電話番号", "휴대전화", "전화번호", "номер телефона",
]
_PASSWORD_HINTS = [
    "password", "passwd", "口令", "密码", "contraseña", "passwort",
    "mot de passe", "パスワード", "비밀번호", "пароль",
]
_CODE_HINTS = [
    "verification code", "verify code", "confirmation code", "确认码",
    "短信码", "验证码", "sms", "otp", "动态码",
    "código de verificación", "code de vérification", "bestätigungscode",
    "認証コード", "確認コード", "인증 코드", "код подтверждения",
]
_IDENTIFIER_HINTS = [
    "username", "user name", "账号", "账户", "login", "account", "用户名",
    "nombre de usuario", "nom d'utilisateur", "benutzername", "ユーザー名",
    "사용자 이름", "имя пользователя",
]

_SSO_PROVIDERS = {
    "google": ["google", "accounts.google.com", "servicelogin"],
    "apple": ["apple", "appleid.apple.com"],
    "wechat": ["微信", "wechat", "open.weixin.qq.com"],
    "qq": ["qq登录", "使用qq", "graph.qq.com", "qq"],
    "weibo": ["微博", "weibo"],
    "github": ["github.com/login/oauth"],  # 只认外部 OAuth 路径，站内 "github" 字样不算
    "gitee": ["gitee", "使用gitee登录"],
    "alipay": ["支付宝", "alipay"],
    "taobao": ["淘宝", "taobao"],
    "xiaomi": ["小米", "xiaomi"],
    "huawei": ["华为", "huawei"],
    "microsoft": ["microsoft", "微软", "login.microsoftonline.com"],
    "baidu": ["百度", "baidu", "openapi.baidu.com"],
    "dingtalk": ["钉钉", "dingtalk"],
    "douyin": ["抖音", "douyin", "toutiao"],
    "xiaohongshu": ["小红书", "xiaohongshu", "rednote"],
    "solana": ["solana", "phantom"],
}
_SSO_FIRST_PARTY_HOSTS = {
    "google": ["google.com"], "apple": ["apple.com"],
    "wechat": ["weixin.qq.com", "wechat.com"], "qq": ["qq.com"],
    "weibo": ["weibo.com"], "github": ["github.com"],
    "gitee": ["gitee.com"], "alipay": ["alipay.com"],
    "taobao": ["taobao.com"], "xiaomi": ["mi.com", "xiaomi.com"],
    "huawei": ["huawei.com"], "microsoft": ["microsoft.com"],
    "baidu": ["baidu.com"], "dingtalk": ["dingtalk.com"],
    "douyin": ["douyin.com"], "xiaohongshu": ["xiaohongshu.com"],
    "solana": ["solana.com"],
}
_SSO_ACTION_HINTS = [
    "sign in", "log in", "login", "continue with", "sign up with",
    "登录", "注册", "授权", "使用", "oauth", "servicelogin",
    "se connecter", "s'inscrire", "iniciar sesión", "registrarse",
    "anmelden", "einloggen", "registrieren", "ログイン", "新規登録",
    "로그인", "회원가입", "войти", "зарегистрироваться",
]
_SSO_PROVIDER_ACTIONS = {
    "google": ["使用 google", "google 登录", "sign in with google", "continue with google"],
    "apple": ["使用 apple", "apple 登录", "sign in with apple", "continue with apple"],
    "wechat": [
        "微信登录", "微信扫码", "使用微信", "扫码方式：微信", "扫码方式:微信",
        "wechat login", "login with wechat",
    ],
    "qq": ["qq登录", "使用qq", "login with qq"],
    "weibo": ["微博登录", "使用微博", "login with weibo"],
    "github": ["github 登录", "sign in with github", "continue with github"],
    "gitee": ["gitee 登录", "使用gitee", "sign in with gitee"],
    "alipay": ["支付宝登录", "使用支付宝", "alipay login"],
    "taobao": ["淘宝登录", "使用淘宝", "taobao login"],
    "xiaomi": ["小米登录", "使用小米", "xiaomi login"],
    "huawei": ["华为登录", "使用华为", "huawei login"],
    "microsoft": ["microsoft 登录", "sign in with microsoft", "continue with microsoft"],
    "baidu": ["百度登录", "使用百度", "baidu login"],
    "dingtalk": ["钉钉登录", "使用钉钉", "dingtalk login"],
    "douyin": ["抖音登录", "使用抖音", "douyin login"],
    "xiaohongshu": ["小红书登录", "使用小红书", "xiaohongshu login"],
    "solana": ["solana 登录", "connect solana", "phantom wallet"],
}

_BLOCKER_HINTS = {
    "captcha": [
        "captcha", "验证码图片", "geetest", "极验", "recaptcha", "人机验证",
        "verify you're a human", "verify you are human", "human verification",
        "i'm not a robot", "je ne suis pas un robot", "ich bin kein roboter",
        "no soy un robot", "人間であることを確認", "로봇이 아닙니다", "я не робот",
    ],
    "slide": ["滑块", "slide", "拖动", "拖动滑块"],
    # scan 只用"认证语境"短语，避免正文文章里的"扫码直达"等误判（力扣首页实测教训）。
    # 注意排除"扫码下载"：那是 App 下载引导，不是登录/注册认证（酷安/得物首页实测）。
    "scan": ["扫码登录", "扫一扫登录", "微信扫一扫", "扫码方式", "扫二维码",
             "二维码登录", "qrcode", "扫码注册"],
    "app_confirm": ["app 确认", "手机 app", "在app中", "扫一扫确认"],
}

_NEXT_TEXTS = {
    "下一步", "继续", "next", "continue", "suivant", "continuer", "weiter",
    "continuar", "次へ", "계속", "далее", "продолжить",
}
_SEND_CODE_HINTS = [
    "发送验证码", "获取验证码", "发送短信验证码", "获取短信验证码",
    "send code", "get code", "重新发送", "resend",
    "envoyer le code", "código", "code senden", "コードを送信", "인증번호 전송",
    "отправить код",
]
_AUTO_SIGNUP_HINTS = [
    "登录/注册", "登录或注册", "注册/登录", "注册或登录", "登录即注册",
    "未注册手机验证后自动注册", "未注册手机号验证后自动注册",
]
_SUBMIT_HINTS = [
    "注册", "提交", "完成", "创建账号", "创建账户", "sign up", "register",
    "create account", "submit", "finish", "s'inscrire", "créer un compte",
    "registrarse", "crear cuenta", "registrieren", "konto erstellen",
    "新規登録", "会員登録", "アカウント作成", "회원가입", "계정 만들기",
    "зарегистрироваться", "создать аккаунт",
]

_PERFORMANCE_OPTIMIZATIONS = True


def configure_performance_optimizations(enabled: bool) -> None:
    """仅供同代码基线对照；关闭时恢复旧版每次 Fathom 全页扫描行为。"""
    global _PERFORMANCE_OPTIMIZATIONS
    _PERFORMANCE_OPTIMIZATIONS = bool(enabled)


def _match_any(text: str, keywords: List[str]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def _provider_from_semantic(semantic: str) -> Optional[str]:
    """从按钮文字/属性/链接中识别第三方身份提供商。"""
    for provider, hints in _SSO_PROVIDERS.items():
        for hint in hints:
            normalized = hint.lower()
            if (re.fullmatch(r"[a-z0-9_-]+", normalized)
                    and not re.search(
                        rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])",
                        semantic.lower(),
                    )):
                continue
            if normalized in semantic.lower():
                return provider
    return None


def _provider_is_first_party(provider: str, hostname: str) -> bool:
    host = (hostname or "").lower().split(":", 1)[0].strip(".")
    return any(
        host == domain or host.endswith("." + domain)
        for domain in _SSO_FIRST_PARTY_HOSTS.get(provider, [])
    )


def _normalize_auth_semantics(fields: List[str], blockers, methods):
    """统一扫码语义：二维码是并行方式，只有无字段时才是硬阻断。

    页面同时存在手机号、验证码或口令等自有字段时，用户可以选择字段路线，
    二维码不应让分类器提前停止；但二维码本身仍作为 ``qr`` 方式保留证据。
    """
    normalized_blockers = list(dict.fromkeys(blockers or []))
    normalized_methods = list(dict.fromkeys(methods or []))
    if "scan" in normalized_blockers:
        if "qr" not in normalized_methods:
            normalized_methods.append("qr")
        if fields:
            normalized_blockers = [b for b in normalized_blockers if b != "scan"]
    return normalized_blockers, normalized_methods


def _is_visible_enabled(el) -> bool:
    try:
        return el.is_displayed() and el.is_enabled()
    except Exception:
        return False


def _is_onscreen(driver: WebDriver, el) -> bool:
    """元素不仅有尺寸，还必须与当前视口相交。主要用于常驻验证码 iframe。"""
    try:
        return bool(driver.execute_script(
            "const r=arguments[0].getBoundingClientRect();"
            "return r.width>0&&r.height>0&&r.bottom>0&&r.right>0"
            "&&r.top<innerHeight&&r.left<innerWidth;",
            el,
        ))
    except Exception:
        return False


def _element_text(el) -> str:
    values = []
    try:
        values.append(el.text or "")
    except Exception:
        pass
    for attr in ("value", "aria-label", "title", "name", "id", "placeholder", "href"):
        try:
            values.append(el.get_attribute(attr) or "")
        except Exception:
            pass
    return " ".join(values).strip()


def _control_label(el) -> str:
    """只取用户实际看到的控件标签，不把 id/name 当成按钮文案。"""
    values = []
    try:
        values.append(el.text or "")
    except Exception:
        pass
    for attr in ("value", "aria-label", "title"):
        try:
            values.append(el.get_attribute(attr) or "")
        except Exception:
            pass
    # 同一文字经常同时出现在 innerText 和 aria-label；取第一个非空值即可。
    return next((value.strip() for value in values if value and value.strip()), "")


def _classify_combined(combined: str, t: str, visible: str = "") -> str:
    """根据 type/name/placeholder/id 组合分类输入框类型（与 classify_input_type 一致）。

    visible 传用户可见语义（placeholder/aria-label），用于纠正 name/id
    与界面文案不一致的站点（如 imooc 注册手机号框 name="email"）。
    """
    if t == "password" or _match_any(combined, _PASSWORD_HINTS):
        return "password"
    if t == "email":
        return "email"
    if t == "tel":
        return "phone"
    if _match_any(combined, _CODE_HINTS):
        return "code"
    # 用户可见语义优先：placeholder/aria-label 明确说是手机号/邮箱时，
    # 不受 name/id 里过时字段名误导（imooc 注册手机号框 name="email" 实测）。
    if visible:
        v_phone = _match_any(visible, _PHONE_HINTS)
        v_email = _match_any(visible, _EMAIL_HINTS)
        if v_phone and not v_email:
            return "phone"
        if v_email and not v_phone:
            return "email"
    # name/id 明确写 account/username 时，它可能同时接受手机和邮箱
    if _match_any(combined, _IDENTIFIER_HINTS):
        return "identifier"
    if _match_any(combined, _EMAIL_HINTS):
        return "email"
    if _match_any(combined, _PHONE_HINTS):
        return "phone"
    return "other"


def classify_input_type(el) -> str:
    """判断可见输入框的语义类型。"""
    input_type = (el.get_attribute("type") or "").lower()
    name = el.get_attribute("name") or ""
    placeholder = el.get_attribute("placeholder") or ""
    element_id = el.get_attribute("id") or ""
    aria_label = el.get_attribute("aria-label") or ""
    combined = f"{input_type} {name} {placeholder} {element_id} {aria_label}"
    semantic_name = f"{name} {element_id} {aria_label}"

    if input_type == "password" or _match_any(combined, _PASSWORD_HINTS):
        return "password"
    if input_type == "email":
        return "email"
    if input_type == "tel":
        return "phone"
    # code 必须先于普通文本 phone 判断；"6 digits" 不是手机号语义。
    if _match_any(combined, _CODE_HINTS):
        return "code"
    # 用户可见语义优先：placeholder/aria-label 明确说是手机号/邮箱时，
    # 不受 name/id 里过时字段名误导（imooc 注册手机号框 name="email" 实测）。
    visible = f"{placeholder} {aria_label}".strip()
    if visible:
        v_phone = _match_any(visible, _PHONE_HINTS)
        v_email = _match_any(visible, _EMAIL_HINTS)
        if v_phone and not v_email:
            return "phone"
        if v_email and not v_phone:
            return "email"
    # name/id 明确写 account/username 时，它可能同时接受手机和邮箱。
    if _match_any(semantic_name, _IDENTIFIER_HINTS):
        return "identifier"
    if _match_any(combined, _EMAIL_HINTS):
        return "email"
    if _match_any(combined, _PHONE_HINTS):
        return "phone"
    if _match_any(combined, _IDENTIFIER_HINTS):
        return "identifier"
    return "other"


def _visible_inputs(driver: WebDriver):
    inputs = []
    for el in driver.find_elements(By.TAG_NAME, "input"):
        try:
            if _is_visible_enabled(el) and (el.get_attribute("type") or "").lower() not in {
                "hidden", "submit", "button", "checkbox", "radio", "reset", "image",
            }:
                inputs.append(el)
        except Exception:
            continue
    return inputs


def detect_fields(driver: WebDriver) -> List[str]:
    fields: List[str] = []
    for el in _visible_inputs(driver):
        try:
            field_type = classify_input_type(el)
            if field_type != "other" and field_type not in fields:
                fields.append(field_type)
        except Exception:
            continue
    return fields


def _has_unchecked_tos(driver: WebDriver) -> bool:
    """只把真实可见、未勾选的协议复选框视为阻断，不按全页文字误判。"""
    hints = ["协议", "条款", "隐私", "terms", "agreement", "privacy", "同意"]
    for checkbox in driver.find_elements(By.CSS_SELECTOR, "input[type='checkbox']"):
        try:
            if not _is_visible_enabled(checkbox) or checkbox.is_selected():
                continue
            nearby = driver.execute_script(
                "return arguments[0].closest('label')?.innerText || "
                "arguments[0].parentElement?.innerText || '';",
                checkbox,
            ) or ""
            if checkbox.get_attribute("required") is not None or _match_any(nearby, hints):
                return True
        except Exception:
            continue
    return False


def detect_blockers(driver: WebDriver) -> List[str]:
    """检测当前可见页面上的验证码/滑块/扫码/一次性验证码/协议等阻断。"""
    blockers: List[str] = []
    texts: List[str] = []
    try:
        texts.append(driver.find_element(By.TAG_NAME, "body").text)
    except Exception:
        pass

    for frame in driver.find_elements(By.TAG_NAME, "iframe"):
        try:
            if frame.is_displayed() and _is_onscreen(driver, frame):
                texts.append(frame.get_attribute("src") or "")
        except Exception:
            continue

    for blocker, hints in _BLOCKER_HINTS.items():
        if any(_match_any(text, hints) for text in texts):
            blockers.append(blocker)

    # 主框架没有阻断时，检查同源 iframe 内的可见文本（CSDN 的微信扫码在 iframe 里）
    if not blockers:
        for frame in driver.find_elements(By.TAG_NAME, "iframe"):
            try:
                if not frame.is_displayed() or not _is_onscreen(driver, frame):
                    continue
                driver.switch_to.frame(frame)
                inner_text = driver.find_element(By.TAG_NAME, "body").text
                driver.switch_to.default_content()
                for blocker, hints in _BLOCKER_HINTS.items():
                    if blocker in blockers:
                        continue
                    if _match_any(inner_text, hints):
                        blockers.append(blocker)
            except Exception:
                try:
                    driver.switch_to.default_content()
                except Exception:
                    pass

    fields = detect_fields(driver)
    if "code" in fields:
        blockers.append(
            "sms_code" if "phone" in fields
            else "email_code" if "email" in fields
            else "verification_code"
        )
    else:
        for el in driver.find_elements(By.CSS_SELECTOR, "button, a, input[type='button']"):
            if _is_visible_enabled(el) and _match_any(_element_text(el), _SEND_CODE_HINTS):
                label = _element_text(el).lower()
                blockers.append(
                    "sms_code" if "phone" in fields or "短信" in label or "sms" in label
                    else "email_code" if "email" in fields
                    else "verification_code"
                )
                break

    if _has_unchecked_tos(driver):
        blockers.append("tos")
    return list(dict.fromkeys(blockers))


def _sso_provider(driver: WebDriver, el) -> Optional[str]:
    text = _element_text(el)
    href = (el.get_attribute("href") or "").strip()
    class_name = el.get_attribute("class") or ""
    semantic = " ".join((
        text, href, class_name, el.get_attribute("id") or "",
        el.get_attribute("aria-label") or "", el.get_attribute("title") or "",
    ))
    provider = _provider_from_semantic(semantic)
    if not provider:
        return None
    # 提供商自己站内的登录按钮不是第三方登录（如 gitee.com 的 Gitee 登录）。
    try:
        if _provider_is_first_party(provider, urlparse(driver.current_url).hostname or ""):
            return None
    except Exception:
        pass
    action_signal = _match_any(semantic, _SSO_ACTION_HINTS)
    auth_href = bool(re.search(
        r"oauth|authorize|connect|servicelogin|openid|passport|/auth(?:/|$)",
        href, re.I,
    ))
    try:
        provider_only_button = (
            (el.tag_name or "").lower() == "button"
            or (el.get_attribute("role") or "").lower() == "button"
        ) and 0 < len(text.strip()) <= 20
    except Exception:
        provider_only_button = False
    icon_only = not text.strip() and bool(_provider_from_semantic(semantic))
    if not (action_signal or auth_href or provider_only_button or icon_only):
        return None
    # 图标按钮常没有“登录/使用”等文字，只在 aria/title/class/id/href 中
    # 暴露 provider。提供商信号明确时允许识别；普通社交分享链接由调用方的
    # 认证上下文守卫排除。
    return provider


def _control_in_auth_scope(driver: WebDriver, el, fields: List[str]) -> bool:
    """第三方控件必须属于当前认证区域，不能只靠整页标题/正文命中。"""
    try:
        path = urlparse(driver.current_url or "").path
        if re.search(r"/(login|signin|sign-in|register|signup|passport|oauth|auth|account)(/|$)",
                     path, re.I):
            return True
    except Exception:
        pass
    try:
        return bool(driver.execute_script(r"""
            const el=arguments[0], hasFields=arguments[1];
            if(el.closest("[role='dialog'],[aria-modal='true'],[class*='modal'],[class*='Modal'],[class*='drawer'],[class*='Drawer']")) return true;
            if(!hasFields) return false;
            let node=el;
            for(let depth=0;node&&depth<9;depth++,node=node.parentElement){
              if(node===document.body||node===document.documentElement) break;
              for(const input of node.querySelectorAll('input,textarea')){
                const r=input.getBoundingClientRect(), s=getComputedStyle(input);
                if(r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden') return true;
              }
            }
            return false;
        """, el, bool(fields)))
    except Exception:
        return False


def _is_auth_context(driver: WebDriver, fields: List[str]) -> bool:
    """当前文档是否确实处在登录/注册语境，防止把分享按钮当 SSO。"""
    if fields:
        return True
    try:
        path = urlparse(driver.current_url or "").path
        if re.search(r"/(login|signin|sign-in|register|signup|passport|oauth|auth|account)(/|$)",
                     path, re.I):
            return True
    except Exception:
        pass
    try:
        title = driver.title or ""
        if _match_any(title, ["登录", "登陆", "注册", "sign in", "log in", "sign up", "register"]):
            return True
    except Exception:
        pass
    try:
        return any(
            _is_visible_enabled(el)
            for el in driver.find_elements(
                By.CSS_SELECTOR,
                "[role='dialog'], [aria-modal='true'], [class*='modal'], [class*='Modal'], [class*='drawer']",
            )
        )
    except Exception:
        return False


def detect_methods(driver: WebDriver) -> List[str]:
    """检测自有注册字段和可见的第三方统一登录入口。"""
    methods: List[str] = []
    fields = detect_fields(driver)
    for field_type in ("email", "phone", "identifier"):
        if field_type in fields:
            methods.append(field_type)

    if not _is_auth_context(driver, fields):
        return methods

    for el in driver.find_elements(
            By.CSS_SELECTOR, "button, a, input[type='button'], input[type='submit']"):
        if _is_visible_enabled(el) and _match_any(_control_label(el), _AUTO_SIGNUP_HINTS):
            methods.append("auto_signup")
            break

    for el in driver.find_elements(By.CSS_SELECTOR, "button, a, [role='button']"):
        if not _is_visible_enabled(el):
            continue
        if not _control_in_auth_scope(driver, el, fields):
            continue
        provider = _sso_provider(driver, el)
        if provider:
            if "sso" not in methods:
                methods.append("sso")
            if provider not in methods:
                methods.append(provider)
    return methods


def _is_external_link(driver: WebDriver, el) -> bool:
    try:
        href = el.get_attribute("href") or ""
        if not href or href.startswith(("#", "javascript:")):
            return False
        current = urlparse(driver.current_url)
        target = urlparse(urljoin(driver.current_url, href))
        return bool(current.hostname and target.hostname and current.hostname != target.hostname)
    except Exception:
        return True


def _is_safe_next_text(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text).strip().lower()
    return normalized in _NEXT_TEXTS


def detect_next_button(driver: WebDriver) -> Optional[object]:
    """只返回可见、启用、同站且文字明确的下一步控件。"""
    candidates = driver.find_elements(By.CSS_SELECTOR, "button, a, input[type='button'], input[type='submit']")
    for el in candidates:
        try:
            if not _is_visible_enabled(el):
                continue
            label = _control_label(el)
            if _match_any(label, _SEND_CODE_HINTS + _SUBMIT_HINTS):
                continue
            if not _is_safe_next_text(label):
                continue
            if _is_external_link(driver, el):
                continue
            return el
        except Exception:
            continue
    return None


def detect_available_actions(driver: WebDriver) -> List[str]:
    actions: List[str] = []
    if detect_next_button(driver) is not None:
        actions.append("next")

    for el in driver.find_elements(By.CSS_SELECTOR, "button, a, input[type='button'], input[type='submit']"):
        if not _is_visible_enabled(el):
            continue
        text = _element_text(el)
        if _match_any(text, _SEND_CODE_HINTS) and "send_code" not in actions:
            actions.append("send_code")
        if _match_any(text, _SUBMIT_HINTS) and "submit" not in actions:
            actions.append("submit")
        if _sso_provider(driver, el) and "external_sso" not in actions:
            actions.append("external_sso")
    return actions


def detect_page_style(driver: WebDriver) -> str:
    """页面样式六类识别（队友提供的前端分类，2026-08-05 加入）。

    判定顺序：
      sso_iframe   → 可见 iframe 指向第三方身份提供商
      modal        → 可见 role=dialog / aria-modal=true
      multi_step   → 存在"下一步/继续"按钮
      standalone   → URL 路径含 login/register/signup 等关键词
      inline       → 有输入框但以上都不匹配
      drawer       → 有侧滑特征（类名含 drawer/slide）
      unknown      → 其他
    """
    try:
        from signup_flow_classifier.flow_types import UIType
        # 1) SSO iframe
        for f in driver.find_elements(By.TAG_NAME, "iframe"):
            src = f.get_attribute("src") or ""
            if any(k in src for k in ["accounts.google", "appleid.apple", "open.weixin",
                                      "graph.qq", "api.weibo", "login.microsoftonline"]):
                return UIType.SSO_IFRAME.value
        # 2) Modal / Dialog
        for el in driver.find_elements(By.CSS_SELECTOR, "[role='dialog'], [aria-modal='true'], [class*='modal'], [class*='Modal']"):
            try:
                if el.is_displayed():
                    return UIType.MODAL.value
            except Exception:
                continue
        # 3) 分步表单
        if detect_next_button(driver) is not None:
            return UIType.MULTI_STEP_WIZARD.value
        # 4) 独立单页（URL 关键词，按路径段精确匹配避免误伤）
        url = driver.current_url or ""
        path = urlparse(url).path.lower()
        import re as _re
        if _re.search(r"/(login|register|signup|signin|account)(/|$)", path):
            return UIType.STANDALONE_PAGE.value
        # 5) 侧边抽屉
        for el in driver.find_elements(By.CSS_SELECTOR, "[class*='drawer'], [class*='Drawer'], [class*='slide-over']"):
            try:
                if el.is_displayed():
                    return UIType.DRAWER.value
            except Exception:
                continue
        # 6) 内嵌挂件
        if detect_fields(driver):
            return UIType.INLINE_WIDGET.value
        return UIType.UNKNOWN.value
    except Exception:
        return "unknown"


def _switch_to_frame_path(driver: WebDriver, path) -> bool:
    try:
        driver.switch_to.default_content()
        for index in path:
            frames = driver.find_elements(By.TAG_NAME, "iframe")
            if index >= len(frames):
                driver.switch_to.default_content()
                return False
            driver.switch_to.frame(frames[index])
        return True
    except Exception:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass
        return False


def _visible_frame_paths(driver: WebDriver, max_depth: int = 3):
    """返回最多三层的可见认证/大尺寸 iframe 路径。"""
    auth_hints = [
        "login", "reg", "passport", "account", "oauth", "signin",
        "signup", "auth", "sso",
    ]
    paths = []

    def walk(prefix, depth):
        if depth >= max_depth or not _switch_to_frame_path(driver, prefix):
            return
        try:
            count = len(driver.find_elements(By.TAG_NAME, "iframe"))
        except Exception:
            return
        for index in range(count):
            if not _switch_to_frame_path(driver, prefix):
                return
            try:
                frames = driver.find_elements(By.TAG_NAME, "iframe")
                if index >= len(frames):
                    continue
                frame = frames[index]
                if not frame.is_displayed() or not _is_onscreen(driver, frame):
                    continue
                src = (frame.get_attribute("src") or "").lower()
                size = frame.size or {}
                large = size.get("width", 0) >= 100 and size.get("height", 0) >= 100
                if not large and not _match_any(src, auth_hints):
                    continue
            except Exception:
                continue
            path = prefix + (index,)
            paths.append(path)
            walk(path, depth + 1)

    walk(tuple(), 0)
    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    return paths


def detect_fields_all_frames(driver: WebDriver) -> List[str]:
    """主文档 + 开放 Shadow DOM + iframe 内的输入框。

    混合方案：
    1) 单条 JS 递归扫描主文档、开放 Shadow DOM 和所有**同源** iframe
       （毫秒级，避免逐个切换）
    2) JS 无结果时，Python 切换进入**尺寸较大的可见** iframe 逐个检测
       （覆盖跨域登录 iframe，如 163；小广告/统计 iframe 会被尺寸过滤跳过）
    """
    fathom_candidate_seen = False
    try:
        raw = driver.execute_script(
            "const out = [];"
            "const seen = new Set();"
            "function visible(el) {"
            "  try { const r=el.getBoundingClientRect(), s=getComputedStyle(el);"
            "    return r.width>0 && r.height>0 && s.display!=='none' && s.visibility!=='hidden';"
            "  } catch(e) { return false; }"
            "}"
            "function scan(root) {"
            "  if (!root || seen.has(root)) return; seen.add(root);"
            "  for (const el of root.querySelectorAll('input')) {"
            "    let vis = false;"
            "    try { vis = visible(el); } catch(e) {}"
            "    out.push([el.type||'', el.name||'', el.placeholder||'', el.id||'',"
            "      el.getAttribute('aria-label')||'', vis]);"
            "  }"
            "  for (const el of root.querySelectorAll('*')) {"
            "    if (el.shadowRoot) scan(el.shadowRoot);"
            "  }"
            "  for (const f of root.querySelectorAll('iframe')) {"
            "    try { if (f.contentDocument) scan(f.contentDocument); } catch(e) {}"
            "  }"
            "}"
            "scan(document);"
            "return JSON.stringify(out);"
        )
        import json as _json
        fields: List[str] = []
        for t, name, ph, el_id, aria, vis in _json.loads(raw or "[]"):
            if not vis:
                continue
            if (t or "").lower() in {"", "text"}:
                fathom_candidate_seen = True
            ft = _classify_combined(
                f"{t} {name} {ph} {el_id} {aria}", t,
                visible=f"{ph} {aria}",
            )
            if ft != "other" and ft not in fields:
                fields.append(ft)
        if fields:
            return fields
    except Exception:
        pass

    # 跨域/独立 file origin iframe 回退：递归进入认证相关或尺寸较大的可见 iframe。
    for path in _visible_frame_paths(driver):
        try:
            if not _switch_to_frame_path(driver, path):
                continue
            inner = detect_fields(driver)
            driver.switch_to.default_content()
            if inner:
                fields.extend(f for f in inner if f not in fields)
        except Exception:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass

    # Fathom ML 兜底：关键词漏掉的非标准邮箱框（type=text + label 识别，见
    # tests/fixtures/signup_flows/nonstandard_email.html 演示）
    # Fathom 会遍历整页 DOM；页面连一个可见 input 都没有时，它不可能找到邮箱框，
    # 直接跳过可让大型内容站从几十秒降到毫秒级。对有输入但关键词不明确的页面，
    # 按 URL + 可见输入签名缓存结果，DOM 变化后签名会自然失效。
    if ("email" not in fields
            and (fathom_candidate_seen or not _PERFORMANCE_OPTIMIZATIONS)):
        try:
            from utils.fathom_detector import detect_emails_fathom
            _fathom_available = True
        except ImportError:
            _fathom_available = False
        if _fathom_available:
            try:
                signature = driver.execute_script(
                    "return location.href+'|'+JSON.stringify("
                    "[...document.querySelectorAll('input')].filter(e=>{"
                    " const r=e.getBoundingClientRect(),s=getComputedStyle(e);"
                    " return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden';"
                    "}).map(e=>[e.type,e.name,e.id,e.placeholder,e.getAttribute('aria-label')]).sort());"
                ) or ""
                cache = getattr(driver, "_ap_fathom_email_cache", {})
                if not _PERFORMANCE_OPTIMIZATIONS:
                    detected = bool(detect_emails_fathom(driver))
                else:
                    if signature not in cache:
                        cache[signature] = bool(detect_emails_fathom(driver))
                        if len(cache) > 64:
                            cache.pop(next(iter(cache)))
                        setattr(driver, "_ap_fathom_email_cache", cache)
                    detected = cache[signature]
                if detected:
                    fields.append("email")
            except Exception:
                pass
    return fields


# 表单内 tab 语义（如 B站/豆瓣的 密码登录/短信登录 切换）
_TAB_KINDS = {
    "password_tab": ["密码登录", "账号密码", "密码注册", "账密", "账号登录", "账号注册",
                     "使用密码验证登录", "密码验证登录", "账号密码登录", "密码登录方式"],
    "password_signup_tab": ["密码注册", "账号注册"],
    "sms_tab": ["短信登录", "验证码登录", "手机号登录", "短信验证码登录", "手机验证码登录",
                "网易手机账号登录"],
    "email_tab": ["邮箱登录", "邮箱注册", "网易邮箱账号登录", "邮箱账号登录"],
    "register_tab": [
        "立即注册", "免费注册", "注册账号", "sign up", "register",
        "s'inscrire", "registrarse", "registrieren", "新規登録", "会員登録",
        "회원가입", "зарегистрироваться",
    ],
}


def detect_tabs(driver: WebDriver) -> List[str]:
    """检测表单内的 tab 切换选项（如"密码登录/短信登录"）。

    用单条 JS 扫描可见元素：先精确文本匹配，再对短文本（≤12 字）做
    分词匹配（"短信登录 帐号登录"这种一个元素含多个 tab 名的站，
    zol 实测）。返回 tab 种类列表。
    """
    import json as _json
    try:
        payload = _json.dumps(_TAB_KINDS, ensure_ascii=False)
        found = driver.execute_script(
            "const kinds = " + payload + ";" +
            "const norm = s => s.replace(/帐/g, '账').replace(/\\s+/g, '');"
            "const roots=[document], els=[], shortTexts=[];"
            "for(let i=0;i<roots.length&&i<100;i++){"
            " for(const e of roots[i].querySelectorAll('*')) if(e.shadowRoot) roots.push(e.shadowRoot);"
            " for(const e of roots[i].querySelectorAll("
            "  \"div, span, li, a, button, [role='tab'], [class*='tab'], [class*='Tab']\")) {"
            "  const r=e.getBoundingClientRect(),s=getComputedStyle(e);"
            "  if(r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'){"
            "    const t=norm((e.textContent||'').trim());"
            "    els.push(t);"
            "    if(t.length<=12) shortTexts.push(t);"
            "  }"
            " }"
            "}"
            "const out = [];"
            "for (const kind in kinds) {"
            "  const hs = kinds[kind];"
            "  if (hs.some(h => els.includes(norm(h)))) { out.push(kind); continue; }"
            "  // 分词匹配：一个元素含多个 tab 名（zol 短信登录+帐号登录合并文本实测）"
            "  if (shortTexts.some(t => hs.some(h => t.includes(norm(h))))) out.push(kind);"
            "}"
            "return out;"
        )
        return [k for k in (found or [])]
    except Exception:
        return []


def detect_tabs_all_frames(driver: WebDriver) -> List[str]:
    """主文档 + 嵌套可见 iframe 内的 tab 检测（163 等认证弹窗）。"""
    found = detect_tabs(driver)
    if found:
        return found
    for path in _visible_frame_paths(driver):
        try:
            if not _switch_to_frame_path(driver, path):
                continue
            inner = detect_tabs(driver)
            driver.switch_to.default_content()
            if inner:
                return inner
        except Exception:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass
    return found


def _detect_page_semantics(driver: WebDriver, fields: List[str]) -> dict:
    """一次浏览器内扫描合并阻断、方式、动作、tab 与页面样式。

    旧实现把成百上千个链接逐个传回 Python 再调用 is_displayed/get_attribute，
    大型内容站单个状态可耗 40--100 秒。这里让浏览器在 DOM 内完成过滤，
    只传回几个分类字符串；同时递归开放 Shadow DOM 与同源 iframe。
    """
    config = {
        "blockers": _BLOCKER_HINTS,
        "send": _SEND_CODE_HINTS,
        "auto_signup": _AUTO_SIGNUP_HINTS,
        "submit": _SUBMIT_HINTS,
        "next": list(_NEXT_TEXTS),
        "sso_actions": _SSO_ACTION_HINTS,
        "sso_providers": _SSO_PROVIDERS,
        "sso_provider_actions": _SSO_PROVIDER_ACTIONS,
        "sso_first_party": _SSO_FIRST_PARTY_HOSTS,
        "tabs": _TAB_KINDS,
    }
    script = r"""
const cfg=arguments[0], presetFields=arguments[1]||[];
const clean=v=>(v||'').replace(/\s+/g,' ').trim().toLowerCase().replace(/帐/g,'账');
const has=(text,hints)=>hints.some(h=>text.includes(clean(h)));
const providerHas=(text,hints)=>hints.some(raw=>{
 const hint=clean(raw); if(!hint)return false;
 // 中文、URL 和带空格动作短语可以可靠地做子串匹配；纯英文品牌名必须
 // 是完整 token，避免 apple 命中 apply、qq 命中任意 class 片段。
 if(/[^a-z0-9_-]/.test(hint)||hint.includes('.')||hint.includes('/'))return text.includes(hint);
 const escaped=hint.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
 return new RegExp('(^|[^a-z0-9])'+escaped+'([^a-z0-9]|$)','i').test(text);
});
const visible=el=>{try{const r=el.getBoundingClientRect(),s=getComputedStyle(el);
 return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'
   &&!el.disabled&&el.getAttribute('aria-disabled')!=='true';}catch(e){return false;}};
const onscreen=el=>{try{const r=el.getBoundingClientRect();
 return r.bottom>0&&r.right>0&&r.top<innerHeight&&r.left<innerWidth;}catch(e){return false;}};
const roots=[document], seen=new Set(), texts=[], frames=[];
for(let i=0;i<roots.length&&i<100;i++){
 const root=roots[i]; if(!root||seen.has(root))continue; seen.add(root);
 texts.push(clean(root.body?.innerText||root.textContent||''));
 for(const el of root.querySelectorAll('*')) if(el.shadowRoot) roots.push(el.shadowRoot);
 for(const f of root.querySelectorAll('iframe')){
  // 隐藏/零尺寸验证码 iframe 常驻在许多首页中；只有当前真正可见的
  // frame 才能作为“正在阻断认证”的证据，否则会在点击登录前误停。
  if(visible(f)&&onscreen(f)) frames.push(clean(f.src||f.id||f.title||''));
  try{if(visible(f)&&onscreen(f)&&f.contentDocument)roots.push(f.contentDocument);}catch(e){}
 }
}
const allText=texts.join(' '), blockerText=allText+' '+frames.join(' '),
 blockers=[], methods=[] ,actions=[], tabs=[];
for(const [kind,hints] of Object.entries(cfg.blockers)) if(has(blockerText,hints)) blockers.push(kind);
const add=(arr,value)=>{if(value&&!arr.includes(value))arr.push(value);};
for(const field of presetFields) if(['email','phone','identifier'].includes(field)) add(methods,field);
let hasDialog=false,hasDrawer=false,authTexts=[];
const sharesAuthFieldScope=el=>{
 let node=el;
 for(let depth=0;node&&depth<6;depth++,node=node.parentElement){
  if(node===document.body||node===document.documentElement)break;
  try{
   if([...node.querySelectorAll("input,textarea")].some(input=>visible(input)))return true;
  }catch(e){}
 }
 return false;
};
for(const root of roots){
 for(const el of root.querySelectorAll("[role='dialog'],[aria-modal='true'],[class*='modal'],[class*='Modal']"))
  if(visible(el)){hasDialog=true;authTexts.push(clean(el.innerText||el.textContent||''));break;}
 for(const el of root.querySelectorAll("[class*='drawer'],[class*='Drawer'],[class*='slide-over']"))
  if(visible(el)){hasDrawer=true;break;}
 // 认证上下文：有弹窗/抽屉、有输入字段、或 URL 在认证路径上。
 // 首页普通内容里的"关注微博/微信"分享链接（外部 href）不是第三方登录
 // （东方财富首页实测 sso 误判）；只有认证界面里出现才算。
 const authUrlPath=/\/(login|signin|sign-in|register|signup|passport|oauth|auth|account)(\/|$)/i.test(location.pathname);
 for(const el of root.querySelectorAll("button,a,input,[role='button'],[role='link'],[role='tab'],select,textarea,[class*='tab'],[class*='Tab'],div,span,li")){
  if(!visible(el))continue;
  const label=clean(el.innerText||el.value||el.getAttribute('aria-label')||el.title||'');
  const href=clean(el.getAttribute('href'));
  const semantic=clean([label,href,el.name,el.id,el.placeholder,
    typeof el.className==='string'?el.className:''].join(' '));
  if(has(label,cfg.send)){
   add(actions,'send_code');
   add(blockers,presetFields.includes('phone')||label.includes('短信')||label.includes('sms')
     ?'sms_code':presetFields.includes('email')?'email_code':'verification_code');
  }
   if(has(label,cfg.auto_signup))add(methods,'auto_signup');
   if(has(label,cfg.submit))add(actions,'submit');
   if(cfg.next.map(clean).includes(label))add(actions,'next');
   for(const [kind,hints] of Object.entries(cfg.tabs))
     if(hints.map(clean).includes(label))add(tabs,kind);
   // sso 只认真正的可点击元素：有外部 href 的链接，或明确 role=button/tab
   // 的控件。纯展示性 div/span（无 href 无 onclick，如"下载和关注"区的
   // 微信/微博社交关注二维码）不能算第三方登录（美团首页实测误判）。
   // 且必须在认证上下文中（弹窗/字段/认证 URL/认证标题）——首页底部的
   // "关注微博/微信"分享链接不算第三方登录（东方财富首页实测误判）。
   const isRealClickable = el.tagName==='A' || el.tagName==='BUTTON'
     || ['button','link','tab'].includes(clean(el.getAttribute('role')))
     || el.hasAttribute('onclick') || el.hasAttribute('tabindex');
   const insideAuthBox=!!el.closest("[role='dialog'],[aria-modal='true'],[class*='modal'],[class*='Modal'],[class*='drawer'],[class*='Drawer']");
   // “页面标题含登录”或“页面某处有手机号字段”都不能把整页正文变成认证区。
   // 普通页面只接受认证弹窗内、或与可见认证字段共享近邻容器的控件；
   // 独立认证 URL 才允许扫描整页。
   const inAuthContext=authUrlPath||insideAuthBox
     || (presetFields.length>0&&sharesAuthFieldScope(el));
   if(isRealClickable&&inAuthContext){
    let external=!href;
    try{if(href){const target=new URL(href,location.href);external=!target.hostname||target.hostname!==location.hostname;}}
    catch(e){}
    const actionSignal=has(semantic,cfg.sso_actions);
    const authHref=/oauth|authorize|connect|servicelogin|openid|passport|\/auth(?:\/|$)/i.test(href);
    const providerOnlyButton=(el.tagName==='BUTTON'||clean(el.getAttribute('role'))==='button')
      &&label.length>0&&label.length<=20;
    if(external)for(const [provider,hints] of Object.entries(cfg.sso_providers)){
     const firstParty=(cfg.sso_first_party[provider]||[]).some(d=>location.hostname===d||location.hostname.endsWith('.'+d));
     if(!firstParty&&providerHas(semantic,hints)&&(actionSignal||authHref||providerOnlyButton)){
      add(methods,'sso');add(methods,provider);add(actions,'external_sso');
     }
    }
    // OAuth 图标按钮常走站内 JS/中转链接，文字为空，只在 aria/title/class/id
    // 里出现 provider。认证上下文 + 真可点击 + 明确 provider 三重守卫可识别
    // 这类按钮，同时继续排除普通首页的社交分享图标。
    if(!external){
     const providerAttrs=clean([label,href,el.getAttribute('aria-label'),el.title,
       el.name,el.id,typeof el.className==='string'?el.className:''].join(' '));
     for(const [provider,hints] of Object.entries(cfg.sso_providers)){
      const firstParty=(cfg.sso_first_party[provider]||[]).some(d=>location.hostname===d||location.hostname.endsWith('.'+d));
      const iconOnly=!label&&providerHas(providerAttrs,hints);
      if(!firstParty&&providerHas(providerAttrs,hints)
          &&(actionSignal||authHref||providerOnlyButton||iconOnly)){
       add(methods,'sso');add(methods,provider);add(actions,'external_sso');
      }
     }
    }
   }
 }
 for(const box of root.querySelectorAll("input[type='checkbox']")){
  if(!visible(box)||box.checked)continue;
  const nearby=clean(box.closest('label')?.innerText||box.parentElement?.innerText||'');
  if(box.required||has(nearby,['协议','条款','隐私','terms','agreement','privacy','同意']))
    add(blockers,'tos');
 }
}
// 二维码登录页有时没有可点击的微信按钮，只有“微信登录”标题和二维码
// （人人都是产品经理等）。在明确认证文档/弹窗中，可用可见正文识别
// 第三方提供商；不在普通内容页全局匹配，避免文章正文造成误报。
const authPath=/\/(login|signin|sign-in|passport|oauth|auth)(\/|$)/i.test(location.pathname);
// 有弹窗时只读弹窗内文字，不能把遮罩后的文章正文（例如“微信教程”）
// 当成当前注册弹窗提供了微信登录。
const providerText=authTexts.length?authTexts.join(' '):(authPath?allText:'');
// scan 的词表只能在当前认证弹窗或独立认证页内生效；普通正文即使出现
// “扫码登录”等介绍性文字，也不能制造二维码认证证据。
if(blockers.includes('scan')&&!(providerText&&has(providerText,cfg.blockers.scan)))
 blockers.splice(blockers.indexOf('scan'),1);
if(providerText&&has(providerText,['登录','登陆','sign in','log in','扫码'])){
 for(const [provider,hints] of Object.entries(cfg.sso_provider_actions)){
  const firstParty=(cfg.sso_first_party[provider]||[]).some(d=>location.hostname===d||location.hostname.endsWith('.'+d));
  if(!firstParty&&has(providerText,hints)){add(methods,'sso');add(methods,provider);}
 }
}
if(presetFields.includes('code'))add(blockers,
 presetFields.includes('phone')?'sms_code':presetFields.includes('email')?'email_code':'verification_code');
let style='unknown';
if(frames.some(src=>has(src,['accounts.google','appleid.apple','open.weixin','graph.qq','api.weibo','login.microsoftonline'])))
 style='sso_iframe';
else if(hasDialog)style='modal';
else if(actions.includes('next'))style='multi_step_wizard';
else if(/\/(login|register|signup|signin|account)(\/|$)/i.test(location.pathname))style='standalone_page';
else if(hasDrawer)style='drawer';
else if(presetFields.length)style='inline_widget';
return {blockers,methods,actions,tabs,style};
"""
    try:
        return driver.execute_script(script, config, fields) or {}
    except Exception:
        return {}


def detect_page_state(driver: WebDriver, step: int) -> PageState:
    state = PageState(step=step)
    try:
        state.url = driver.current_url
    except Exception:
        pass
    state.fields = detect_fields_all_frames(driver)
    if not _PERFORMANCE_OPTIMIZATIONS:
        state.ui_type = detect_page_style(driver)
        state.blockers = detect_blockers(driver)
        state.methods = detect_methods(driver)
        state.blockers, state.methods = _normalize_auth_semantics(
            state.fields, state.blockers, state.methods)
        state.available_actions = detect_available_actions(driver)
        state.tabs = detect_tabs_all_frames(driver)
        return state
    semantics = _detect_page_semantics(driver, state.fields)
    # 浏览器 JS 受同源策略限制，跨域认证 iframe 的文字需由 WebDriver 切入后
    # 再执行同一条快速扫描（例如什么值得买的扫码登录 iframe）。
    if semantics and not semantics.get("blockers"):
        for path in _visible_frame_paths(driver):
            try:
                if not _switch_to_frame_path(driver, path):
                    continue
                inner_fields = detect_fields(driver)
                inner = _detect_page_semantics(driver, inner_fields)
                for key in ("blockers", "methods", "actions", "tabs"):
                    current = semantics.setdefault(key, [])
                    for item in inner.get(key, []):
                        if item not in current:
                            current.append(item)
                if (semantics.get("style") == "unknown"
                        and inner.get("style") != "unknown"):
                    semantics["style"] = inner["style"]
            except Exception:
                continue
        try:
            driver.switch_to.default_content()
        except Exception:
            pass
    if semantics:
        state.ui_type = semantics.get("style", "unknown")
        state.blockers = semantics.get("blockers", [])
        state.methods = semantics.get("methods", [])
        state.available_actions = semantics.get("actions", [])
        state.tabs = semantics.get("tabs", [])
    else:
        # 保留旧函数作为脚本受 CSP/浏览器异常影响时的兼容回退。
        state.ui_type = detect_page_style(driver)
        state.blockers = detect_blockers(driver)
        state.methods = detect_methods(driver)
        state.available_actions = detect_available_actions(driver)
        state.tabs = detect_tabs_all_frames(driver)
    state.blockers, state.methods = _normalize_auth_semantics(
        state.fields, state.blockers, state.methods)
    return state
