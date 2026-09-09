"""受控导航：只执行明确、安全的下一步操作。"""
import json
import re
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

from signup_flow_classifier.page_detector import _element_text, classify_input_type, detect_blockers, detect_next_button


MAX_STEPS = 3
CHANGE_TIMEOUT = 5
MAX_ENTRY_CLICKS = 2

# 注册/登录入口的明确语义（避免误点）
_ENTRY_REGISTER_TEXTS = [
    "立即注册", "免费注册", "马上注册", "注册", "注册免费邮箱",
    "sign up", "create account", "register",
    "s'inscrire", "créer un compte", "registrarse", "crear cuenta", "registrieren",
    "konto erstellen", "新規登録", "会員登録", "アカウント作成", "회원가입",
    "계정 만들기", "зарегистрироваться", "создать аккаунт",
]
_ENTRY_LOGIN_TEXTS = [
    "登录", "登陆", "sign in", "log in", "login", "se connecter", "connexion",
    "iniciar sesión", "anmelden", "einloggen", "ログイン", "로그인", "войти", "вход",
]


@dataclass(frozen=True)
class NavigationOutcome:
    clicked: bool
    changed: bool
    reason: str


@dataclass(frozen=True)
class EntryTarget:
    """可跨 Shadow DOM/iframe 重新定位的安全认证入口。"""
    token: str
    frame_path: Tuple[int, ...]
    kind: str
    source: str


def _semantic_controls(driver: WebDriver) -> List[list]:
    """提取可见表单控件和弹窗摘要，避免只依赖 URL 判断 SPA 变化。"""
    controls: List[list] = []
    selector = "input, button, a, select, textarea, [role='button'], [role='dialog'], [aria-modal='true']"
    for el in driver.find_elements(By.CSS_SELECTOR, selector):
        try:
            if not el.is_displayed():
                continue
            attrs = [
                el.tag_name,
                el.get_attribute("type") or "",
                el.get_attribute("name") or "",
                el.get_attribute("id") or "",
                el.get_attribute("placeholder") or "",
                el.get_attribute("aria-label") or "",
                el.get_attribute("role") or "",
                (el.get_attribute("href") or "")[:160],
                (el.text or "")[:160],
            ]
            controls.append(attrs)
        except Exception:
            continue
    return controls


def page_fingerprint(driver: WebDriver) -> str:
    """轻量页面指纹：URL + 可见认证控件/状态签名。

    用单条 JS 在浏览器内计算（之前遍历全部 DOM + Python 序列化单次约 1.6s，
    是每步耗时十几秒的元凶；JS 版本毫秒级）。
    输入框签名能区分 SPA 视图切换（短信视图=phone+code，密码视图=username+password）。
    扫描开放 Shadow DOM 与同源 iframe；同时纳入 ``aria-expanded`` /
    ``aria-selected``，覆盖 URL 和按钮文字均不变化的 SPA tab/弹窗切换。
    不读取输入值，避免把用户数据带入内存指纹。
    """
    try:
        return driver.execute_script(
            r"""
const roots=[document],seen=new Set(),inputs=[],buttons=[],dialogs=[],frames=[];
const visible=el=>{try{const r=el.getBoundingClientRect();
 const view=el.ownerDocument?.defaultView||window,s=view.getComputedStyle(el);
 return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden';
 }catch(e){return false;}};
for(let i=0;i<roots.length&&i<100;i++){
 const root=roots[i]; if(!root||seen.has(root))continue; seen.add(root);
 for(const el of root.querySelectorAll('*'))if(el.shadowRoot)roots.push(el.shadowRoot);
 for(const el of root.querySelectorAll('input,select,textarea'))if(visible(el)){
  inputs.push([el.tagName,el.type||'',el.name||'',el.id||'',el.placeholder||'',
   el.getAttribute('aria-label')||'',el.getAttribute('autocomplete')||''].join(':'));
 }
 for(const el of root.querySelectorAll("button,a,[role='button'],[role='tab']"))if(visible(el)){
  const label=(el.innerText||el.textContent||el.getAttribute('aria-label')
   ||el.getAttribute('title')||'').replace(/\s+/g,' ').trim().slice(0,160);
  buttons.push([el.tagName,label,el.getAttribute('role')||'',
   el.getAttribute('aria-expanded')||'',el.getAttribute('aria-selected')||'',
   el.disabled?'disabled':''].join(':'));
 }
 for(const el of root.querySelectorAll("[role='dialog'],[aria-modal='true']"))if(visible(el)){
  dialogs.push((el.innerText||el.textContent||'').replace(/\s+/g,' ').trim().slice(0,200));
 }
 for(const frame of root.querySelectorAll('iframe'))if(visible(frame)){
  frames.push((frame.src||frame.id||frame.title||'').split('?')[0]);
  try{if(frame.contentDocument)roots.push(frame.contentDocument);}catch(e){}
 }
}
return JSON.stringify({u:location.href,t:document.title,i:inputs.slice(0,300).sort(),
 b:buttons.slice(0,300).sort(),d:dialogs.slice(0,30).sort(),f:frames.slice(0,100).sort()});
"""
        ) or ""
    except Exception:
        return ""


def wait_page_change(driver: WebDriver, old_fingerprint: str,
                     timeout: float = CHANGE_TIMEOUT,
                     old_window_handles=None,
                     watched_context=None) -> bool:
    """等待主文档、新窗口或指定 iframe browsing context 发生变化。

    ``watched_context`` 为 ``(frame_path, old_fingerprint)``。跨域 iframe
    无法由顶层 JS 读取，点击发生在 frame 内时必须单独观察该上下文。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if page_fingerprint(driver) != old_fingerprint:
            return True
        if watched_context is not None:
            frame_path, context_fingerprint = watched_context
            try:
                if not _switch_to_frame_path(driver, frame_path):
                    return True
                changed = page_fingerprint(driver) != context_fingerprint
            except Exception:
                changed = True
            finally:
                try:
                    driver.switch_to.default_content()
                except Exception:
                    pass
            if changed:
                return True
        if old_window_handles is not None:
            try:
                if set(driver.window_handles) != set(old_window_handles):
                    return True
            except Exception:
                pass
        time.sleep(0.25)
    return False


def _visible_inputs(driver: WebDriver):
    for el in driver.find_elements(By.TAG_NAME, "input"):
        try:
            if el.is_displayed() and el.is_enabled():
                yield el
        except Exception:
            continue


def _fill_local_fixture_values(driver: WebDriver) -> None:
    """只给 file:// 本地测试页填写固定假数据，永不用于真实网站。"""
    if urlparse(driver.current_url).scheme != "file":
        raise ValueError("local fixture values are restricted to file:// pages")
    values = {
        "email": "measurement@example.com",
        "phone": "15500000000",
        "identifier": "measurement_test",
        "code": "123456",
    }
    for el in _visible_inputs(driver):
        field_type = classify_input_type(el)
        if field_type not in values:
            continue
        try:
            if not (el.get_attribute("value") or ""):
                el.send_keys(values[field_type])
        except Exception:
            continue


def _has_empty_relevant_input(driver: WebDriver) -> bool:
    for el in _visible_inputs(driver):
        try:
            if classify_input_type(el) in {"email", "phone", "identifier", "code"}:
                if not (el.get_attribute("value") or ""):
                    return True
        except Exception:
            continue
    return False


def safe_advance(driver: WebDriver, allow_local_test_values: bool = False) -> NavigationOutcome:
    """尝试一次安全前进，并说明为什么前进或停止。

    - 本地 fixture 可显式启用固定假数据。
    - 真实网站默认不填写身份信息或验证码。
    - 不使用 JavaScript 强制点击。
    """
    blockers = set(detect_blockers(driver))
    if blockers & {"captcha", "slide", "scan", "app_confirm", "tos"}:
        return NavigationOutcome(False, False, "human_blocked")
    if blockers & {"sms_code", "email_code", "verification_code"} and not allow_local_test_values:
        return NavigationOutcome(False, False, "verification_required")

    if allow_local_test_values:
        try:
            _fill_local_fixture_values(driver)
        except ValueError:
            return NavigationOutcome(False, False, "test_values_refused_for_remote_page")
    elif _has_empty_relevant_input(driver):
        return NavigationOutcome(False, False, "input_required")

    button = detect_next_button(driver)
    if button is None:
        return NavigationOutcome(False, False, "no_safe_button")

    old_fingerprint = page_fingerprint(driver)
    try:
        button.click()
    except Exception:
        return NavigationOutcome(False, False, "native_click_failed")

    changed = wait_page_change(driver, old_fingerprint)
    if not changed:
        return NavigationOutcome(True, False, "clicked_no_change")
    return NavigationOutcome(True, True, "clicked_and_changed")


def safe_click_next(driver: WebDriver, allow_local_test_values: bool = False) -> bool:
    """兼容旧调用者；新代码应优先使用 safe_advance 获取停止原因。"""
    return safe_advance(driver, allow_local_test_values).changed


def _entry_text_match(text: str, hints: List[str]) -> bool:
    """入口文本匹配：短语义（登录/sign in）精确匹配，长语义（立即注册）包含匹配。

    精确匹配按空白分词后比较，避免 _element_text 返回"文本+id"拼接
    以及正文里"登录后可见"这类文字被误匹配。
    """
    t = text.strip().lower()
    tokens = t.split()
    short_hints = (
        "登录", "登陆", "login", "sign in", "log in", "register", "connexion",
        "anmelden", "einloggen", "ログイン", "로그인", "войти", "вход", "新規登録",
        "会員登録", "회원가입", "registrieren", "registrarse", "se connecter",
        "s'inscrire", "зарегистрироваться",
    )
    for h in hints:
        hl = h.lower()
        if h in short_hints:
            if t == hl or any(tok == hl for tok in tokens):
                return True
        else:
            if hl in t:
                return True
    return False


def _same_site(url_a: str, url_b: str) -> bool:
    """判断两个 URL 是否同属一个注册域（eTLD+1）。

    passport.hupu.com 与 www.hupu.com 同属 hupu.com → 站内；
    登录弹窗/注册页常用子域名（passport/login/account），不能按主机名严格比较。
    """
    if not url_b or url_b.startswith(("#", "javascript:", "void(")):
        return True
    try:
        import tldextract
        ea = tldextract.extract(url_a)
        eb = tldextract.extract(url_b)
        if not ea.registered_domain and not eb.registered_domain:
            return True  # 本地 file:// 等无域名场景视为站内
        return bool(ea.registered_domain and ea.registered_domain == eb.registered_domain)
    except Exception:
        return False


def _is_organizational_signup(url: str) -> bool:
    """排除机构/企业/商家入驻，不把它们冒充普通用户注册路线。"""
    try:
        path = urlparse(url).path.lower().rstrip("/")
    except Exception:
        return False
    blocked = (
        "/org/signup", "/organization/signup", "/enterprise/register",
        "/business/register", "/merchant/register", "/company/register",
    )
    # 主机含 dealer（经销商，zol 的 dealer.zol.com.cn 实测）等明确机构语义时排除。
    try:
        host = urlparse(url).hostname or ""
        if any(mark in host for mark in ("dealer", "merchant", "business",
                                         "enterprise")):
            return True
    except Exception:
        pass
    return any(path.endswith(item) or item + "/" in path for item in blocked)


def _switch_to_frame_path(driver: WebDriver, frame_path: Tuple[int, ...]) -> bool:
    try:
        driver.switch_to.default_content()
        for index in frame_path:
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


def _frame_paths(driver: WebDriver, max_depth: int = 3) -> List[Tuple[int, ...]]:
    """列出可见 iframe 路径；包含嵌套与延迟认证 iframe。"""
    paths: List[Tuple[int, ...]] = [tuple()]

    def walk(prefix: Tuple[int, ...], depth: int) -> None:
        if depth >= max_depth or not _switch_to_frame_path(driver, prefix):
            return
        try:
            frame_count = len(driver.find_elements(By.TAG_NAME, "iframe"))
        except Exception:
            return
        for index in range(frame_count):
            # 递归返回时浏览器仍位于子 iframe。每个兄弟节点都从父路径重新进入，
            # 避免复用其他 browsing context 中已经失效的 WebElement。
            if not _switch_to_frame_path(driver, prefix):
                return
            try:
                frames = driver.find_elements(By.TAG_NAME, "iframe")
                if index >= len(frames):
                    continue
                frame = frames[index]
                if not frame.is_displayed():
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


_COOKIE_CONTEXT_HINTS = (
    "cookie", "cookies", "cookiebot", "gdpr", "ccpa", "隐私偏好",
    "隐私设置", "cookie 设置", "쿠키", "クッキー", "куки", "galleta",
)


def _cookie_action_kind(label: str) -> Optional[str]:
    """识别隐私保护型 Cookie 横幅操作；有歧义或“全部接受”均不匹配。"""
    text = re.sub(r"\s+", " ", (label or "")).strip().lower()
    text = text.strip(" .,:;!！。:：")
    if not text:
        return None

    necessary_patterns = (
        r"^(?:use |accept )?(?:only )?(?:strictly )?(?:necessary|essential)"
        r"(?: cookies?)?(?: only)?$",
        r"^(?:仅|只)(?:使用|允许|接受)?(?:必要|必需)(?:的)?(?: cookie)?$",
        r"^nur notwendige(?: cookies)?$",
        r"^(?:cookies? )?strictement nécessaires(?: uniquement)?$",
        r"^solo (?:cookies? )?(?:necesarias|esenciales)$",
    )
    reject_patterns = (
        r"^(?:reject|decline|deny|refuse)(?: all)?(?: cookies?)?$",
        r"^continue without accepting$",
        r"^(?:拒绝|不同意)(?:全部|所有)?(?: cookie)?$",
        r"^(?:全部|所有)(?:拒绝|不同意)$",
        r"^(?:tout refuser|refuser tout)$",
        r"^(?:rechazar todo|rechazar todas)$",
        r"^(?:alle ablehnen|alles ablehnen)$",
        r"^(?:rifiuta tutto|rejeitar tudo|alles weigeren)$",
        r"^(?:すべて拒否|全て拒否|모두 거부|отклонить все)$",
    )
    close_labels = {
        "close", "dismiss", "close banner", "dismiss banner", "×", "✕",
        "关闭", "关闭横幅", "fermer", "cerrar", "schließen", "chiudi",
        "fechar", "閉じる", "닫기", "закрыть",
    }
    if any(re.fullmatch(pattern, text, flags=re.IGNORECASE)
           for pattern in necessary_patterns):
        return "necessary_only"
    if any(re.fullmatch(pattern, text, flags=re.IGNORECASE)
           for pattern in reject_patterns):
        return "reject_all"
    if text in close_labels:
        return "close"
    return None


def _cookie_context_is_explicit(container, action_kind: str) -> bool:
    """要求按钮位于明确 Cookie/CMP 容器内，避免误点普通协议弹窗。"""
    try:
        structural = " ".join([
            container.get_attribute("id") or "",
            container.get_attribute("class") or "",
            container.get_attribute("aria-label") or "",
            container.get_attribute("data-testid") or "",
        ]).lower()
        text = (container.text or "")[:2000].lower()
    except Exception:
        return False
    semantic = "{} {}".format(structural, text)
    if any(hint in semantic for hint in _COOKIE_CONTEXT_HINTS):
        return True
    # 一些 CMP 只在 class/id 中写 consent/cmp，界面只显示“全部拒绝”。
    # 此弱规则仅允许隐私保护型操作，绝不用于通用“关闭”。
    return (action_kind in {"necessary_only", "reject_all"}
            and any(hint in structural for hint in ("consent", "cmp")))


def safe_dismiss_cookie_banner(driver: WebDriver) -> NavigationOutcome:
    """关闭阻挡认证入口的 Cookie/GDPR 横幅，优先保护隐私。

    仅点击“仅必要”“全部拒绝”或明确 Cookie 容器中的关闭按钮；不会点击
    “接受全部”、保存偏好、注册协议或任何表单提交控件。扫描主文档及可见
    iframe，点击后始终恢复到主文档上下文。
    """
    container_selector = (
        "[role='dialog'],[role='alertdialog'],"
        "[class*='cookie' i],[id*='cookie' i],"
        "[class*='consent' i],[id*='consent' i],"
        "[class*='gdpr' i],[id*='gdpr' i],"
        "[class*='cmp' i],[id*='cmp' i]"
    )
    control_selector = (
        "button,a,[role='button'],input[type='button'],input[type='submit']"
    )
    try:
        frame_paths = _frame_paths(driver)
    except Exception:
        frame_paths = [tuple()]

    try:
        for frame_path in frame_paths:
            if not _switch_to_frame_path(driver, frame_path):
                continue
            candidates = []
            try:
                containers = driver.find_elements(By.CSS_SELECTOR, container_selector)
            except Exception:
                containers = []
            for container in containers[:80]:
                try:
                    if not container.is_displayed():
                        continue
                    controls = container.find_elements(By.CSS_SELECTOR, control_selector)
                except Exception:
                    continue
                for control in controls[:80]:
                    try:
                        if not control.is_displayed() or not control.is_enabled():
                            continue
                        labels = [
                            control.text or "",
                            control.get_attribute("aria-label") or "",
                            control.get_attribute("title") or "",
                            control.get_attribute("value") or "",
                        ]
                    except Exception:
                        continue
                    action_kind = next(
                        (kind for kind in map(_cookie_action_kind, labels) if kind),
                        None,
                    )
                    if (not action_kind
                            or not _cookie_context_is_explicit(
                                container, action_kind)):
                        continue
                    priority = {
                        "necessary_only": 0, "reject_all": 1, "close": 2,
                    }[action_kind]
                    candidates.append((priority, action_kind, control, container))
            if not candidates:
                continue
            _, action_kind, control, container = min(
                candidates, key=lambda item: item[0])
            try:
                control.click()
            except Exception:
                return NavigationOutcome(
                    False, False, "cookie_banner_native_click_failed")
            try:
                changed = not container.is_displayed()
            except Exception:
                # 成功关闭后容器常立即从 DOM 移除并变成 stale，这本身就是变化。
                changed = True
            return NavigationOutcome(
                True, changed, "cookie_banner_{}".format(action_kind))
    except Exception:
        return NavigationOutcome(False, False, "cookie_banner_scan_failed")
    finally:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass
    return NavigationOutcome(False, False, "no_cookie_banner_action")


def _mark_entry_in_current_context(driver: WebDriver, kind: str,
                                   token: str) -> Optional[str]:
    hints = _ENTRY_REGISTER_TEXTS if kind == "register" else _ENTRY_LOGIN_TEXTS
    structural = (
        ["register", "signup", "sign-up", "regist", "注册"]
        if kind == "register"
        else ["login", "signin", "sign-in", "account", "profile", "avatar",
              "user", "member", "passport", "登录", "登陆", "账户", "账号",
              "个人中心"]
    )
    payload = json.dumps({"hints": hints, "structural": structural,
                          "kind": kind, "token": token}, ensure_ascii=False)
    script = r"""
const cfg = arguments[0];
const visible = el => {
  try {
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.display !== 'none'
      && s.visibility !== 'hidden' && !el.disabled
      && el.getAttribute('aria-disabled') !== 'true'
      // 视口相交：页脚备案链接（href 含 registerSystemInfo）、正文底部的
      // "注册"相关链接即使可见也不能当入口——真正入口（顶栏/导航）必在视口内。
      && r.bottom > 0 && r.right > 0
      && r.top < innerHeight && r.left < innerWidth;
  } catch (e) { return false; }
};
const clean = value => (value || '').replace(/\s+/g, ' ').trim().toLowerCase();
const roots = [document];
for (let i = 0; i < roots.length && i < 100; i++) {
  for (const el of roots[i].querySelectorAll('*')) if (el.shadowRoot) roots.push(el.shadowRoot);
}
const all = [];
for (const root of roots) {
  for (const el of root.querySelectorAll(
    "button,a,[role='button'],[role='link'],[role='tab'],input[type='button'],"
    + "[class*='login' i],[class*='signin' i],[class*='register' i],[class*='regist' i],"
    + "[class*='account' i],[class*='profile' i],[class*='avatar' i],"
    + "[id*='login' i],[id*='register' i],[id*='account' i],[id*='user' i],"
    + "div,span,img,svg"
  )) all.push(el);
}
const rows = [];
for (const el of all) {
  if (!visible(el)) continue;
  const type = clean(el.getAttribute('type'));
  if (type === 'submit') continue;
  if (el.closest('form') && el.tagName !== 'A' && el.getAttribute('role') !== 'tab'
      && type !== 'button') continue;
  const text = clean(el.innerText || el.textContent);
  // 页脚备案/版权链接排除：京公网安备/ICP 备案不是认证入口
  // （douyin 首页实测误点导航到视频页）。
  if (/备案|公网安备|beian|mps\.gov\.cn|copyright/i.test(text)
      || /备案|beian|mps\.gov\.cn|beian\.gov\.cn/i.test(clean(el.getAttribute('href'))))
    continue;
  const aria = clean(el.getAttribute('aria-label'));
  const title = clean(el.getAttribute('title'));
  const alt = clean(el.getAttribute('alt'));
  const descendantName = clean([
    ...el.querySelectorAll('[aria-label],[title],img[alt],svg title')
  ].slice(0, 8).map(node =>
    node.getAttribute('aria-label') || node.getAttribute('title')
      || node.getAttribute('alt') || node.textContent || ''
  ).join(' '));
  const cls = clean(typeof el.className === 'string' ? el.className : '');
  const id = clean(el.id);
  const href = clean(el.getAttribute('href'));
  const semantic = [text, aria, title, alt, descendantName, cls, id, href].join(' ');
  const combinedText = text.replace(/[|｜/·]+/g, ' ').replace(/\s+/g, ' ').trim();
  const explicit = cfg.hints.some(h => {
    h = clean(h);
    return text === h || aria === h || title === h || alt === h
      || descendantName === h
      || text.split(/\s+/).includes(h);
  });
  const combined = (combinedText.includes('登录') && combinedText.includes('注册'))
    || (combinedText.includes('sign in') && combinedText.includes('sign up'));
  // 结构语义只看属性（class/id/href/aria/title/alt），不包含正文文本：
  // 文章标题里的"注册"（如 36kr"公司刚注册…"）不能当认证入口结构，
  // 文本匹配只走上面的 explicit（精确匹配）。这是弱结构词防御的前提。
  const structuralText = [cls, id, href, aria, title, alt, descendantName].join(' ');
  const structural = cfg.structural.some(h => structuralText.includes(clean(h)));
  // 明确的认证结构应始终排在普通作者头像/用户卡之前。
  // 旧打分会因为头像 img 有 alt 文本额外加分，导致正文头像
  // 压过 class 中明确带 login 的顶栏按钮。
  const strongStructural = [
    'login', 'signin', 'sign-in', 'register', 'regist', 'signup',
    'sign-up', 'passport', '登录', '登陆', '注册'
  ].some(h => structuralText.includes(h));
  const mediumStructural = [
    'account', 'member', '账户', '账号', '个人中心'
  ].some(h => semantic.includes(h));
  const nativeInteractive = ['BUTTON','A','INPUT'].includes(el.tagName)
    || ['button','link','tab'].includes(clean(el.getAttribute('role')))
    || el.hasAttribute('onclick') || el.hasAttribute('tabindex')
    || getComputedStyle(el).cursor === 'pointer';
  if (!explicit && !combined && !(structural && nativeInteractive)) continue;
  // 弱结构词防御：非"登录/注册"文本、仅靠 user/avatar/profile 等弱结构词命中的元素，
  // 若位于正文内容区（article 内或视口下半部），判定为内容卡片而非认证入口
  // （虎嗅作者卡片 class=...user 在正文区，实测反例；顶栏头像菜单在头部，保留）。
  if (!explicit && !combined && !strongStructural) {
    const r = el.getBoundingClientRect();
    const inContentArea = r.top > (innerHeight * 0.6)
      || !!el.closest('article, main, [class*="article"], [class*="content"], [class*="card"]');
    if (inContentArea) continue;
  }
  // div/span 必须是叶子式、可交互且语义紧凑，避免点击包含整页文字的大容器。
  if (['DIV','SPAN'].includes(el.tagName)) {
    // explicit 精确匹配的"登录/注册"文字不算大容器（thepaper 纯 div 登录
    // 按钮实测 cursor:auto 无 onclick，但 React 事件绑在更上层）；
    // 只有非 explicit 的 div/span 才要求 nativeInteractive。
    if (!explicit && (!nativeInteractive || text.length > 40)) continue;
    if (text.length > 40 && !explicit) continue;
    // 只有子元素是真正可点击目标（A/BUTTON 等）且文本相同时，父才是容器；
    // div>span 的"登录"按钮（36kr user-login 实测）子元素只是纯展示文本，
    // 父元素 cursor:pointer 才是真实点击目标，不能跳过。
    const clickableSameTextChild = [...el.children].filter(visible).some(c => {
      if (!['A','BUTTON','INPUT','SELECT'].includes(c.tagName)
          && clean(c.getAttribute('role')) !== 'button') return false;
      return clean(c.innerText || c.textContent) === text;
    });
    if (clickableSameTextChild) continue;
  }
  const score = (explicit ? 100 : 0) + (combined ? 70 : 0)
    + (strongStructural ? 50 : (mediumStructural ? 25 : 5))
    + (aria || title || alt || descendantName ? 5 : 0)
    + (el.tagName === 'BUTTON' ? 10 : 0)
    + (el.tagName === 'A' ? 8 : 0) - Math.min(text.length, 40);
  // 容器扣分：若元素内含有同样命中的可点击子元素（a/button），
  // 说明真正的点击目标是子元素（如 li>a 的"登录/注册"菜单），
  // 点容器往往不触发弹窗（imooc 实测）。扣分让子元素胜出。
  const clickableChild = [...el.querySelectorAll('a,button,[role="button"],[role="tab"]')]
    .some(child => {
      const ct = clean(child.innerText || child.textContent || child.getAttribute('aria-label'));
      return ct === clean(cfg.hints.join(' ')) || cfg.hints.some(h => ct === clean(h)
        || ct.split(/\s+/).includes(clean(h)));
    });
  const finalScore = score - (clickableChild ? 60 : 0);
  rows.push({el, score: finalScore, source: explicit ? 'accessible_text' : (combined ? 'combined_text' : 'structural_semantics')});
}
rows.sort((a,b) => b.score - a.score);
// 硬规则：容器（LI/DIV/SPAN 且无 href）不能压过显式的 A/BUTTON 点击目标。
// 博客园"我的博客"是 hover 菜单触发器（菜单是兄弟元素），点击容器无效，
// 而展开后的"登录"链接（A，156 分）才是真正入口——若容器比紧邻的
// 显式 A/BUTTON 高不超过 30 分，优先选 A/BUTTON。
if (rows.length > 1) {
  const top = rows[0];
  const topIsContainer = ['LI','DIV','SPAN'].includes(top.el.tagName)
    && !top.el.getAttribute('href');
  if (topIsContainer) {
    const altIndex = rows.slice(1).findIndex(r => ['A','BUTTON','INPUT'].includes(r.el.tagName)
      && (r.el.getAttribute('href') || r.el.getAttribute('onclick')));
    const alt = altIndex >= 0 ? rows[altIndex + 1] : null;
    if (alt && (top.score - alt.score) <= 30) {
      rows[altIndex + 1] = top;
      rows[0] = alt;
    }
  }
}
if (!rows.length) return null;
rows[0].el.setAttribute('data-ap-entry-token', cfg.token);
return rows[0].source;
"""
    try:
        return driver.execute_script(script, json.loads(payload))
    except Exception:
        return None


def _resolve_marked_entry(driver: WebDriver, token: str):
    script = r"""
const token = arguments[0], roots = [document];
for (let i = 0; i < roots.length && i < 100; i++) {
  const found = roots[i].querySelector(`[data-ap-entry-token="${token}"]`);
  if (found) return found;
  for (const el of roots[i].querySelectorAll('*')) if (el.shadowRoot) roots.push(el.shadowRoot);
}
return null;
"""
    try:
        return driver.execute_script(script, token)
    except Exception:
        return None


def detect_entry_button(
    driver: WebDriver, prefer: str = "register", allow_fallback: bool = True,
    prefer_frames: bool = False,
):
    """找到站内的"登录/注册"入口按钮或链接（如页头、登录页的"立即注册"）。

    先按 prefer 的语义找（注册优先时找"注册"，找不到再回退找"登录"——
    首页可能只有"登录"按钮，点进去的弹窗里才有注册入口，如 B站）。
    用 JS 查找并返回**文本最短**的匹配元素（叶子优先，避免点到包含子标签的父容器）。
    选择器覆盖 div 型按钮（B站的 header-login-entry 就是 div）。

    安全边界：
    - 只返回站内链接/按钮（同主机），不点外部链接
    - 必须可见可交互
    - 短语义精确匹配，避免误点正文文字
    - 返回 WebElement 或 None
    """
    if allow_fallback:
        order = ["register", "login"] if prefer == "register" else ["login", "register"]
    else:
        order = [prefer]
    base_url = driver.current_url
    for kind in order:
        frame_paths = _frame_paths(driver)
        if prefer_frames:
            frame_paths.sort(key=lambda path: (not bool(path), len(path)))
        for sequence, frame_path in enumerate(frame_paths):
            if not _switch_to_frame_path(driver, frame_path):
                continue
            token = f"{int(time.time() * 1000)}-{kind}-{sequence}"
            source = _mark_entry_in_current_context(driver, kind, token)
            if not source:
                continue
            element = _resolve_marked_entry(driver, token)
            href = element.get_attribute("href") if element is not None else ""
            target_url = urljoin(base_url, href) if href else ""
            if (href and not _same_site(base_url, target_url)) or (
                    kind == "register" and target_url
                    and _is_organizational_signup(target_url)):
                try:
                    driver.execute_script(
                        "arguments[0].removeAttribute('data-ap-entry-token')", element
                    )
                except Exception:
                    pass
                continue
            try:
                driver.switch_to.default_content()
            except Exception:
                pass
            return EntryTarget(token, frame_path, kind, source)
    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    return None


def safe_click_entry(
    driver: WebDriver, prefer: str = "register", allow_fallback: bool = True,
    prefer_frames: bool = False,
) -> NavigationOutcome:
    """点击"登录/注册"入口并等待页面变化。返回 NavigationOutcome。"""
    target = detect_entry_button(
        driver, prefer, allow_fallback=allow_fallback,
        prefer_frames=prefer_frames,
    )
    if target is None:
        return NavigationOutcome(False, False, "no_entry_button")
    old_fp = page_fingerprint(driver)
    old_target_fp = None
    try:
        old_window_handles = driver.window_handles
    except Exception:
        old_window_handles = None
    try:
        if not _switch_to_frame_path(driver, target.frame_path):
            return NavigationOutcome(False, False, "entry_frame_missing")
        btn = _resolve_marked_entry(driver, target.token)
        if btn is None:
            driver.switch_to.default_content()
            return NavigationOutcome(False, False, "entry_target_missing")
        old_target_fp = page_fingerprint(driver)
        # 用 ActionChains 点击（真实鼠标事件）：React hover 型登录弹窗
        # （掘金/力扣实测）只响应真实鼠标，原生 click 后弹窗不保持打开。
        # iframe 内元素先切回主文档再按坐标点击，避免 iframe 上下文
        # ActionChains 定位失败。
        try:
            from selenium.webdriver import ActionChains
            ActionChains(driver).move_to_element(btn).click().perform()
        except Exception:
            try:
                btn.click()
            except Exception:
                driver.switch_to.default_content()
                raise
        # 保留 data-ap-entry-token 供调用方做"链接 href 兜底导航"读取，
        # 读取方负责清理；这里不再移除。
        driver.switch_to.default_content()
    except Exception:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass
        return NavigationOutcome(False, False, "entry_native_click_failed")
    changed = wait_page_change(
        driver, old_fp, old_window_handles=old_window_handles,
        watched_context=(target.frame_path, old_target_fp)
        if target.frame_path and old_target_fp is not None else None,
    )
    if not changed:
        return NavigationOutcome(True, False, "entry_clicked_no_change")
    return NavigationOutcome(
        True, True, f"{target.kind}_{target.source}_clicked_and_changed"
    )


def detect_hover_candidate(driver: WebDriver) -> Optional[object]:
    """在头部区域找"用户/账号类"可悬停元素（hover 菜单型登录入口，如博客园"我的博客"）。

    安全边界：只返回头部区域（视口上半部）、可见、class/id 含 user/avatar/member/
    account/login/navbar 等语义的可交互元素；返回 WebElement 或 None。
    """
    hints = ["user", "avatar", "member", "account", "login", "navbar", "profile",
             "用户", "账号", "头像", "我的"]
    try:
        for el in driver.find_elements(By.CSS_SELECTOR,
                                       "header *, nav *, [class*='nav' i], [class*='header' i], li, div, a"):
            try:
                if not el.is_displayed():
                    continue
                r = el.rect
                if r['y'] < 0 or r['y'] > (driver.get_window_size()['height'] * 0.5):
                    continue
                semantic = " ".join([
                    el.get_attribute("class") or "",
                    el.get_attribute("id") or "",
                    el.get_attribute("aria-label") or "",
                    el.text or "",
                ]).lower()
                if not any(h in semantic for h in hints):
                    continue
                # 元素本身可交互（有子链接/按钮 或 cursor:pointer 或有 onclick）
                interactive = el.get_attribute("onclick") is not None \
                    or el.get_attribute("tabindex") is not None \
                    or el.find_elements(By.CSS_SELECTOR, "a, button").__len__() > 0
                if interactive:
                    return el
            except Exception:
                continue
    except Exception:
        return None
    return None


def safe_hover_menu(driver: WebDriver, prefer: str = "login") -> NavigationOutcome:
    """hover 用户/账号菜单，展开后找登录/注册入口并点击。

    返回 NavigationOutcome。安全边界：只 hover + 点击明确的登录/注册链接。
    """
    from selenium.webdriver import ActionChains
    candidate = detect_hover_candidate(driver)
    if candidate is None:
        return NavigationOutcome(False, False, "no_hover_candidate")
    try:
        ActionChains(driver).move_to_element(candidate).perform()
    except Exception:
        return NavigationOutcome(False, False, "hover_failed")
    try:
        wait_page_change(driver, page_fingerprint(driver), timeout=3)
    except Exception:
        pass
    target = detect_entry_button(driver, prefer)
    if target is None:
        return NavigationOutcome(False, False, "hover_no_entry")
    old_fp = page_fingerprint(driver)
    try:
        if not _switch_to_frame_path(driver, target.frame_path):
            return NavigationOutcome(False, False, "hover_frame_missing")
        btn = _resolve_marked_entry(driver, target.token)
        if btn is None:
            driver.switch_to.default_content()
            return NavigationOutcome(False, False, "hover_target_missing")
        btn.click()
        driver.switch_to.default_content()
    except Exception:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass
        return NavigationOutcome(False, False, "hover_click_failed")
    changed = wait_page_change(driver, old_fp)
    if not changed:
        return NavigationOutcome(True, False, "hover_clicked_no_change")
    return NavigationOutcome(True, True, f"hover_{target.kind}_clicked_and_changed")


def safe_click_tab(driver: WebDriver, kind: str) -> NavigationOutcome:
    """点击表单内的切换 tab（如 password_tab → "密码登录"）。

    JS 查找精确文本匹配的可见元素，并向上找到真正可交互的 React/SPA tab
    容器，再用 **Selenium 原生 click**（可信事件；部分网站如 163 只响应
    可信事件，JS el.click() 无效）。先查主框架，找不到再进 iframe 找。
    点击后用页面指纹确认视图是否真的切换，避免过去永远返回 changed=False。
    """
    from signup_flow_classifier.page_detector import _TAB_KINDS
    hints = [h.rstrip("!") for h in _TAB_KINDS.get(kind, [])]
    if not hints:
        return NavigationOutcome(False, False, f"no_{kind}")
    js = r"""
const targets=arguments[0];
const norm=s=>(s||'').replace(/帐/g,'账').replace(/\s+/g,'');
const visible=e=>{try{const r=e.getBoundingClientRect();
 const view=e.ownerDocument?.defaultView||window,s=view.getComputedStyle(e);
 return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'
  &&!e.disabled&&e.getAttribute('aria-disabled')!=='true';}catch(err){return false;}};
const tokenMatch=(text,tn)=>{const normed=norm(text);if(normed===tn)return true;
 if(normed.includes(tn))return true;
 const toks=(text||'').split(/[\s,，、/·|:：]+/).map(norm).filter(Boolean);
 return toks.some(t=>t===tn||t.includes(tn));};
const roots=[document],els=[];
for(let i=0;i<roots.length&&i<100;i++){
 const root=roots[i];
 for(const el of root.querySelectorAll('*'))if(el.shadowRoot)roots.push(el.shadowRoot);
 for(const el of root.querySelectorAll(
  "div,span,li,a,button,[role='tab'],[role='button'],[class*='tab'],[class*='Tab']"))els.push(el);
}
for(const text of targets){const targetText=norm(text);
 const matches=els.filter(el=>visible(el)&&tokenMatch(el.textContent||'',targetText));
 if(matches.length){const leaf=matches.sort((a,b)=>a.children.length-b.children.length)[0];
  const target=leaf.closest("button,a,[role='tab'],[role='button'],li")||leaf;
  target.scrollIntoView({block:'center'});return target;}}
return null;
"""

    def _trusted_click(frame_path: Tuple[int, ...]) -> NavigationOutcome:
        try:
            if not _switch_to_frame_path(driver, frame_path):
                return NavigationOutcome(False, False, f"no_{kind}")
            element = driver.execute_script(js, hints)
            if element is None:
                driver.switch_to.default_content()
                return NavigationOutcome(False, False, f"no_{kind}")
            old_context_fp = page_fingerprint(driver)
            if frame_path:
                driver.switch_to.default_content()
                old_main_fp = page_fingerprint(driver)
                if not _switch_to_frame_path(driver, frame_path):
                    return NavigationOutcome(False, False, f"no_{kind}")
            else:
                old_main_fp = old_context_fp
            element.click()
            driver.switch_to.default_content()
            changed = wait_page_change(
                driver, old_main_fp, timeout=2.0,
                watched_context=(frame_path, old_context_fp) if frame_path else None,
            )
            reason = f"{kind}_clicked_and_changed" if changed else f"{kind}_clicked_no_change"
            return NavigationOutcome(True, changed, reason)
        except Exception:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass
            return NavigationOutcome(False, False, f"{kind}_native_click_failed")

    for frame_path in _frame_paths(driver):
        outcome = _trusted_click(frame_path)
        if outcome.clicked:
            if frame_path:
                suffix = "_and_changed" if outcome.changed else "_no_change"
                return NavigationOutcome(
                    True, outcome.changed, f"{kind}_clicked_in_iframe{suffix}"
                )
            return outcome
    return NavigationOutcome(False, False, f"no_{kind}")


def safe_click_auth_mode_switch(
    driver: WebDriver, structural_only: bool = False
) -> NavigationOutcome:
    """在已经打开的登录界面中切换到另一种安全认证方式。

    只识别两类窄语义控件：明确的“使用手机登录/账号”入口，以及常见的
    二维码模式切换结构（如 ``qrcode-change``）。不填写字段，不点击发送
    验证码、协议、注册或最终提交；带 href 的控件还必须留在同一站点。

    调用方必须先确认当前确实处在认证上下文中，并限制调用次数。
    ``structural_only=True`` 时只允许无文字的二维码“其他方式”结构控件，
    供 signup 展开选项后再次寻找明确注册入口；不会点击“账号/手机登录”。
    """
    base_url = driver.current_url
    config = {
        "labels": [] if structural_only else [
            "使用手机登录", "手机登录", "账号", "账户",
            "账号登录", "账户登录",
        ],
        "structural": [
            "qrcode-change", "qr-code-change", "qrcode-switch",
            "qr-switch", "login-mode-switch", "mode-switch",
        ],
        "forbidden": [
            "发送验证码", "获取验证码", "重新发送", "登录", "立即登录",
            "注册", "立即注册", "提交", "完成", "同意", "协议",
            "send code", "get code", "submit", "register", "sign up",
        ],
    }
    script = r"""
const cfg=arguments[0];
const clean=v=>(v||'').replace(/帐/g,'账').replace(/\s+/g,'').trim().toLowerCase();
const visible=el=>{try{const r=el.getBoundingClientRect(),s=getComputedStyle(el);
 return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'
  &&!el.disabled&&el.getAttribute('aria-disabled')!=='true';}catch(e){return false;}};
const roots=[document], rows=[];
for(let i=0;i<roots.length&&i<100;i++){
 const root=roots[i];
 for(const el of root.querySelectorAll('*'))if(el.shadowRoot)roots.push(el.shadowRoot);
 for(const el of root.querySelectorAll("a,button,[role='button'],[role='tab'],div,span")){
  if(!visible(el))continue;
  const type=clean(el.getAttribute('type'));
  if(type==='submit'||type==='image')continue;
  const label=clean(el.innerText||el.textContent||el.getAttribute('aria-label')||el.title||'');
  const href=el.getAttribute('href')||'';
  const semantic=clean([typeof el.className==='string'?el.className:'',el.id,
    el.getAttribute('data-type'),el.getAttribute('data-action')].join(' '));
  if(cfg.forbidden.some(x=>label===clean(x)))continue;
  const explicitIndex=cfg.labels.map(clean).indexOf(label);
  const structural=cfg.structural.some(x=>semantic.includes(clean(x)));
  if(explicitIndex<0&&!structural)continue;
  // 有些站把“账号”方式的普通 <a> 放在登录 form 内。只放行精确语义
  // 的站内链接、tab 或明确 type=button 的按钮；默认 submit 按钮和
  // 无文字结构控件在 form 内仍一律拒绝。
  if(el.closest('form')&&!(explicitIndex>=0&&(
    el.tagName==='A'||clean(el.getAttribute('role'))==='tab'
      ||(el.tagName==='BUTTON'&&type==='button')
  )))continue;
  const nativeInteractive=['A','BUTTON'].includes(el.tagName)
    ||['button','tab'].includes(clean(el.getAttribute('role')))
    ||el.hasAttribute('onclick')||el.hasAttribute('tabindex')
    ||getComputedStyle(el).cursor==='pointer';
  if(!nativeInteractive&&!structural)continue;
  // 容器有符合条件的可点击后代时只保留后代，避免点大块弹窗容器。
  if(['DIV','SPAN'].includes(el.tagName)&&!structural){
    if(label.length>12)continue;
    if([...el.querySelectorAll('a,button,[role="button"],[role="tab"]')]
      .some(child=>visible(child)&&cfg.labels.map(clean).includes(clean(child.innerText||child.textContent))))continue;
  }
  const score=(explicitIndex>=0?120-explicitIndex*5:70)
    +(el.tagName==='A'?10:0)+(el.tagName==='BUTTON'?8:0)-Math.min(label.length,20);
  rows.push({el,score,href,reason:explicitIndex>=0?'text':'structural'});
 }
}
rows.sort((a,b)=>b.score-a.score);
if(!rows.length)return null;
const row=rows[0];
return {element:row.el,href:row.href,reason:row.reason};
"""

    old_main_fp = page_fingerprint(driver)
    for frame_path in _frame_paths(driver):
        try:
            if not _switch_to_frame_path(driver, frame_path):
                continue
            marked = driver.execute_script(script, config)
            if not marked:
                continue
            element = marked.get("element")
            if element is None:
                continue
            href = marked.get("href") or ""
            target_url = urljoin(base_url, href) if href else ""
            if href and not _same_site(base_url, target_url):
                continue
            old_context_fp = page_fingerprint(driver)
            element.click()
            driver.switch_to.default_content()
            changed = wait_page_change(
                driver, old_main_fp, timeout=3.0,
                watched_context=(frame_path, old_context_fp)
                if frame_path else None,
            )
            suffix = "and_changed" if changed else "no_change"
            return NavigationOutcome(
                True, changed,
                f"auth_mode_{marked.get('reason', 'unknown')}_clicked_{suffix}",
            )
        except Exception:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass
    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    return NavigationOutcome(False, False, "no_safe_auth_mode_switch")


def _match_any(text: str, hints: List[str]) -> bool:
    t = text.lower()
    return any(h.lower() in t for h in hints)
