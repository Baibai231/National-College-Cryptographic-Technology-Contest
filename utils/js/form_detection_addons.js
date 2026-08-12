/**
 * form_detection_addons.js
 *
 * 从 LoginFormExploration 项目提取并改造的两个功能模块：
 *   Part A: 邮箱字段检测 (detectEmailInputs) — 来自 helpers/fathomDetect.js
 *   Part B: 登录/注册链接发现 (findLoginLinks 等) — 来自 helpers/utils.js
 *
 * 前提依赖：必须先加载 scripts.js（提供 Fathom 框架 + gPt + onTopLayer + getXPath）
 *
 * 改造要点：
 *   - 去除 Node.js/Puppeteer API，改为纯浏览器 DOM 操作
 *   - 所有函数返回 JSON 可序列化对象（xpath + 属性），直接作为 execute_script() 返回值
 *   - 使用传统 for 循环以兼容旧浏览器环境
 */

// ============================================================
// Part A: 邮箱字段检测 (Email Field Detection)
// 来源: LoginFormExploration/helpers/fathomDetect.js L2726-L2861
// ============================================================

/**
 * 返回 regex 在 string 中的匹配次数
 */
function numRegexMatches(regex, string) {
    if (string === null) {
        return 0;
    }
    return (string.match(regex) || []).length;
}

/**
 * 检查元素在给定属性列表中是否有任意属性匹配 regex
 */
function attrsMatch(element, attrs, regex) {
    var result = false;
    for (var i = 0; i < attrs.length; i++) {
        result = result || regex.test(element.getAttribute(attrs[i]));
    }
    return result;
}

/**
 * 检查与 input 元素关联的 <label> 文本是否匹配 regex
 */
function labelForInputMatches(element, regex) {
    // 1. 检查通过 for 属性正确关联的 label
    var labels = element.labels;
    if (labels) {
        for (var i = 0; i < labels.length; i++) {
            if (numRegexMatches(regex, labels[i].innerText) > 0) return true;
        }
    }
    // 2. 检查常见错误：用 name 属性而非 id 属性关联 label
    var form = element.form;
    if (element.name && element.name.length > 0 && form !== null) {
        var formLabels = form.getElementsByTagName("label");
        for (var j = 0; j < formLabels.length; j++) {
            if (formLabels[j].htmlFor && formLabels[j].htmlFor === element.name) {
                if (numRegexMatches(regex, formLabels[j].innerText) > 0) return true;
            }
        }
    }
    return false;
}

// 邮箱匹配正则
var emailRegex = /email|e-mail/gi;
var emailRegexMatchLine = /^(email|e-mail)$/i;

// Fathom 邮箱检测规则集（来自 Mozilla Firefox Password Manager）
// 3 条评分规则，使用 Fathom 监督学习特征加权
var email_detector_ruleset = ruleset(
    [
        // 候选元素：可见的文本输入框
        rule(dom("input[type=text],input[type=\"\"],input:not([type])").when(isVisible), type("email")),

        // 规则1: id/name/autocomplete 属性精确匹配 "email" 或 "e-mail"（权重 9.42）
        rule(
            type("email"),
            score(function(fnode) {
                return attrsMatch(fnode.element, ["id", "name", "autocomplete"], emailRegexMatchLine);
            }),
            {name: "inputAttrsMatchEmailExactly"}
        ),

        // 规则2: placeholder/aria-label 包含 email 关键词（权重 6.74）
        rule(
            type("email"),
            score(function(fnode) {
                return attrsMatch(fnode.element, ["placeholder", "aria-label"], emailRegex);
            }),
            {name: "inputPlaceholderMatchesEmail"}
        ),

        // 规则3: 关联的 <label> 文本包含 email 关键词（权重 10.20）
        rule(
            type("email"),
            score(function(fnode) {
                return labelForInputMatches(fnode.element, emailRegex);
            }),
            {name: "labelForInputMatchesEmail"}
        ),

        // 输出规则
        rule(type("email"), out("email")),
    ],
    new Map([
        ["inputAttrsMatchEmailExactly", 9.416913986206055],
        ["inputPlaceholderMatchesEmail", 6.740292072296143],
        ["labelForInputMatchesEmail", 10.197700500488281],
    ]),
    [["email", -3.907843589782715]]   // bias
);

/**
 * 检测页面中的邮箱输入字段
 * @param {Element} domRoot - DOM 根节点（通常传入 document）
 * @returns {Array<{xpath: string, score: number}>}
 *   score = -1 表示通过 type="email" 精确匹配
 *   score > 0.5 表示通过 Fathom ML 推断为邮箱字段
 */
function detectEmailInputs(domRoot) {
    domRoot = domRoot || document;
    var results = [];

    // 第一步：精确匹配 input[type='email']
    var typeEmailInputs = domRoot.querySelectorAll("input[type='email']");
    for (var i = 0; i < typeEmailInputs.length; i++) {
        results.push({
            xpath: (typeof getXPath === 'function') ? getXPath(typeEmailInputs[i]) : gPt(typeEmailInputs[i]),
            score: -1
        });
    }

    // 第二步：Fathom ML 检测（阈值 > 0.5）
    var detectedInputs = email_detector_ruleset.against(domRoot).get("email");
    for (var j = 0; j < detectedInputs.length; j++) {
        if (detectedInputs[j].scoreFor("email") > 0.5) {
            results.push({
                xpath: (typeof getXPath === 'function') ? getXPath(detectedInputs[j].element) : gPt(detectedInputs[j].element),
                score: detectedInputs[j].scoreFor("email")
            });
        }
    }

    return results;
}


// ============================================================
// Part B: 登录/注册链接发现 (Login/Register Link Discovery)
// 来源: LoginFormExploration/helpers/utils.js L13-L247
// ============================================================

// --- 多语言正则常量（15+ 语言） ---
var passwordStringRegex = /password|passwort|رمز عبور|mot de passe|パスワード|비밀번호|암호|wachtwoord|senha|Пароль|parol|密码|contraseña|heslo|كلمة السر|kodeord|Κωδικός|pass code|Kata sandi|hasło|รหัสผ่าน|Şifre/i;
var passwordAttrRegex = /pw|pwd|passwd|pass/i;
var forgotStringRegex = /vergessen|vergeten|forgot|oublié|dimenticata|Esqueceu|esqueci|Забыли|忘记|找回|Zapomenuté|lost|忘れた|忘れられた|忘れの方|재설정|찾기|help|فراموشی| را فراموش کرده اید|Восстановить|Unuttu|perdus|重新設定|reset|recover|change|remind|find|request|restore|trouble/i;
var forgotHrefRegex = /forgot|reset|recover|change|lost|remind|find|request|restore/i;
var loginRegex = /login|log in|log on|log-on|Войти|sign in|sigin|sign\/in|sign-in|sign on|sign-on|ورود|登录|Přihlásit se|Přihlaste|Авторизоваться|Авторизация|entrar|ログイン|로그인|inloggen|Συνδέσου|accedi|ログオン|Giriş Yap|登入|connecter|connectez-vous|Connexion|Вход/i;
var loginFormAttrRegex = /login|log in|log on|log-on|sign in|sigin|sign\/in|sign-in|sign on|sign-on/i;
var registerStringRegex = /create[a-zA-Z\s]+account|Zugang anlegen|Angaben prüfen|Konto erstellen|register|sign up|ثبت نام|登録|注册|cadastr|Зарегистрироваться|Регистрация|Bellige alynmak|تسجيل|ΕΓΓΡΑΦΗΣ|Εγγραφή|Créer mon compte|Mendaftar|가입하기|inschrijving|Zarejestruj się|Deschideți un cont|Создать аккаунт|ร่วม|Üye Ol|registr|new account|ساخت حساب کاربری|Schrijf je/i;
var registerActionRegex = /register|signup|sign-up|create-account|account\/create|join|new_account|user\/create|sign\/up|membership\/create/i;
var registerFormAttrRegex = /signup|join|register|regform|registration|new_user|AccountCreate|create_customer|CreateAccount|CreateAcct|create-account|reg-form|newuser|new-reg|new-form|new_membership/i;
var loginRegexExtra = /log_in|logon|log_on|signin|sign_in|sign_up|signon|sign_on|Aanmelden/i;
var gEmailRegex = /e.?mail|courriel|correo.*electr(o|ó)nico|メールアドレス|Электронн(ая|ой).?Почт(а|ы)|邮件|邮箱|電子郵件|電郵地址|電子信箱|ഇ-മെയില്|ഇലക്ട്രോണിക്.?മെയിൽ|ایمیل|پست.*الکترونیک|ईमेल|इलॅक्ट्रॉनिक.?मेल|(\\b|_)eposta(\\b|_)|(?:이메일|전자.?우편|[Ee]-?mail)(.?주소)?/i;

// --- 组合正则（用于登录/注册链接匹配，同时覆盖 login 和 register 关键词） ---
var combinedLoginLinkRegexLooseSrc = [
    loginRegex.source, loginFormAttrRegex.source, loginRegexExtra.source,
    registerStringRegex.source, registerActionRegex.source, registerFormAttrRegex.source
].join('|');
var combinedLoginLinkRegexExactSrc = '^' + combinedLoginLinkRegexLooseSrc.replace(/\|/g, '$|^') + '$';

// 开关常量
var ENABLE_LOOSE_LOGIN_LINK_MATCHES = true;
var ENABLE_COORD_BASED_LINK_SEARCH = true;

/**
 * 判断元素类型是否为按钮或链接
 */
function isButtonOrLink(typeOfEl) {
    return (typeOfEl === 'BUTTON' || typeOfEl === 'A') ? 1 : 0;
}

/**
 * 检查元素是否在视口(viewport)内
 */
function isElementInViewport(el) {
    var rect = el.getBoundingClientRect();
    return (
        rect.top >= 0 &&
        rect.left >= 0 &&
        rect.bottom <= (window.innerHeight || document.documentElement.clientHeight) &&
        rect.right <= (window.innerWidth || document.documentElement.clientWidth)
    );
}

/**
 * 通过正则匹配发现登录/注册相关链接
 * 搜索元素: a, span, button, div, iframe, frame
 * 匹配属性: innerText, title, ariaLabel, href, placeholder, id, name, className
 *
 * @param {boolean} exactMatch - true=精确匹配, false=宽松匹配
 * @returns {Array<Object>} 匹配到的链接属性列表
 */
function findLoginLinks(exactMatch) {
    if (exactMatch === undefined) exactMatch = false;
    var loginRegexSrc = exactMatch ? combinedLoginLinkRegexExactSrc : combinedLoginLinkRegexLooseSrc;
    var loginRegex = new RegExp(loginRegexSrc, 'i');
    var allElements = document.querySelectorAll('a, span, button, div, iframe, frame');
    var results = [];

    for (var i = 0; i < allElements.length; i++) {
        var el = allElements[i];
        var hrefVal = el.getAttribute('href') || '';
        var placeholderVal = el.getAttribute('placeholder') || '';
        var nameVal = el.getAttribute('name') || '';
        var classNameVal = el.className || '';

        if ((el.innerText && el.innerText.match(loginRegex)) ||
            (el.title && el.title.match(loginRegex)) ||
            (el.ariaLabel && el.ariaLabel.match(loginRegex)) ||
            (hrefVal && String(hrefVal).match(loginRegex)) ||
            (placeholderVal && String(placeholderVal).match(loginRegex)) ||
            (el.id && el.id.match(loginRegex)) ||
            (nameVal && String(nameVal).match(loginRegex)) ||
            (classNameVal && String(classNameVal).match(loginRegex))) {

            var xpath = '';
            try {
                xpath = (typeof getXPath === 'function') ? getXPath(el) : gPt(el);
            } catch(e) {
                xpath = '';
            }

            results.push({
                xpath: xpath,
                tagName: el.tagName || '',
                nodeType: el.nodeType || '',
                innerText: (el.innerText || '').substring(0, 200),
                href: hrefVal,
                id: el.id || '',
                className: classNameVal,
                onTop: (typeof onTopLayer === 'function') ? onTopLayer(el) : false,
                inView: isElementInViewport(el)
            });
        }
    }
    return results;
}

/**
 * 通过坐标位置发现登录链接（基于训练数据中的登录按钮中位数坐标）
 * 仅搜索 <a> 和 <button> 元素
 *
 * @returns {Array<Object>} 距离中位数坐标最近的 5 个元素的属性列表
 */
function findLoginLinksByCoords() {
    var MAX_COORD_BASED_LINKS = 5;
    var MEDIAN_LOGIN_LINK_X = 1113;
    var MEDIAN_LOGIN_LINK_Y = 64.5;

    function distanceFromLoginLinkMedianPoint(elem) {
        var rect = elem.getBoundingClientRect();
        var centerX = rect.x + (rect.width / 2);
        var centerY = rect.y + (rect.height / 2);
        return Math.sqrt(Math.pow(centerX - MEDIAN_LOGIN_LINK_X, 2) +
                        Math.pow(centerY - MEDIAN_LOGIN_LINK_Y, 2));
    }

    var allElements = Array.prototype.slice.call(document.querySelectorAll('a, button'));
    allElements.sort(function(a, b) {
        return distanceFromLoginLinkMedianPoint(a) - distanceFromLoginLinkMedianPoint(b);
    });

    var closest = allElements.slice(0, MAX_COORD_BASED_LINKS);
    var results = [];

    for (var i = 0; i < closest.length; i++) {
        var el = closest[i];
        var xpath = '';
        try {
            xpath = (typeof getXPath === 'function') ? getXPath(el) : gPt(el);
        } catch(e) {
            xpath = '';
        }

        results.push({
            xpath: xpath,
            tagName: el.tagName || '',
            nodeType: el.nodeType || '',
            innerText: (el.innerText || '').substring(0, 200),
            href: el.getAttribute('href') || '',
            id: el.id || '',
            className: el.className || '',
            onTop: (typeof onTopLayer === 'function') ? onTopLayer(el) : false,
            inView: isElementInViewport(el)
        });
    }
    return results;
}

// ============================================================
// Part B2: 增强版入口链接发现引擎 (V2)
// 对标 MyAutomaticPolicy navigator.py _mark_entry_in_current_context
// 特性: Shadow DOM 遍历 + CSS 结构语义优先 + 多维度打分
//       + 容器惩罚 + iframe 递归搜索
// ============================================================

/**
 * 清洗文本: 合并空白、trim、转小写
 */
function _cleanEntryText(str) {
    return (str || '').replace(/\s+/g, ' ').trim().toLowerCase();
}

/**
 * 检查候选元素是否可见且可交互
 */
function _isEntryVisible(el) {
    try {
        var rect = el.getBoundingClientRect();
        var style = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 &&
            style.display !== 'none' && style.visibility !== 'hidden' &&
            !el.disabled && el.getAttribute('aria-disabled') !== 'true';
    } catch(e) { return false; }
}

/**
 * 多维度入口元素打分
 *
 * 分数设计:
 *   精确文本匹配 ("注册" == "注册"): +100
 *   组合文本 (同时有"登录"+"注册"): +70
 *   强结构语义 (class/id 含 login/register/passport/登录/注册): +50
 *   弱结构语义 (class/id 含 account/member/user/账户/账号): +25
 *   辅助文本 (aria-label/title/alt/descendant): +5
 *   <button> 标签: +10
 *   <a> 标签: +8
 *   文本长度惩罚: -min(len, 40)
 *   容器惩罚 (含匹配子元素): -60
 *
 * @param {Element} el
 * @returns {number} 分数，0 表示应被过滤
 */
function computeEntryScore(el) {
    // ── 注册/登录入口文本提示词 ──
    var ENTRY_HINTS = [
        // 注册
        'sign up', 'signup', 'sign-up', 'register', 'registration',
        'create account', 'create new account', 'new account',
        'join', 'join now', 'join free', 'get started',
        '注册', '立即注册', '免费注册', '新账户', '马上注册',
        '註冊', '建立帳戶',
        '登録', '新規登録', '無料登録', 'アカウント作成',
        '가입', '회원가입',
        // 登录
        'login', 'log in', 'sign in', 'signin', 'sign-in',
        '登录', '登陆',
        'ログイン'
    ];

    // 短提示词（支持分词精确匹配，避免"登录后可见"被误匹配）
    var SHORT_HINTS = ['login', 'log in', 'sign in', 'register', 'sign up',
        '登录', '登陆', '注册'];

    var text = _cleanEntryText(el.innerText || el.textContent || '');
    var aria = _cleanEntryText(el.getAttribute('aria-label') || '');
    var title = _cleanEntryText(el.getAttribute('title') || '');
    var alt = _cleanEntryText(el.getAttribute('alt') || '');
    var cls = _cleanEntryText(typeof el.className === 'string' ? el.className : '');
    var id = _cleanEntryText(el.id || '');
    var href = _cleanEntryText(el.getAttribute('href') || '');

    // 收集后代元素的 accessible name
    var descendantTexts = [];
    try {
        var descendants = el.querySelectorAll('[aria-label],[title],img[alt]');
        for (var d = 0; d < Math.min(descendants.length, 8); d++) {
            var dt = _cleanEntryText(
                descendants[d].getAttribute('aria-label') ||
                descendants[d].getAttribute('title') ||
                descendants[d].getAttribute('alt') ||
                descendants[d].textContent || ''
            );
            descendantTexts.push(dt);
        }
    } catch(e) {}
    var descendantName = descendantTexts.join(' ');

    var semantic = [text, aria, title, alt, descendantName, cls, id, href].join(' ');

    // ── 1. 精确文本匹配 ──
    var explicitMatch = false;
    var tokens = text.split(/\s+/);
    for (var eh = 0; eh < ENTRY_HINTS.length; eh++) {
        var hint = _cleanEntryText(ENTRY_HINTS[eh]);
        // 完全匹配
        if (text === hint || aria === hint || title === hint ||
            alt === hint || descendantName === hint) {
            explicitMatch = true;
            break;
        }
        // 短提示词：支持分词匹配
        if (SHORT_HINTS.indexOf(ENTRY_HINTS[eh]) !== -1) {
            for (var tk = 0; tk < tokens.length; tk++) {
                if (tokens[tk] === hint) { explicitMatch = true; break; }
            }
            if (explicitMatch) break;
        } else {
            // 长提示词：子串包含
            if (text.indexOf(hint) !== -1) { explicitMatch = true; break; }
        }
    }

    // ── 2. 组合文本 (同时含登录+注册语义) ──
    var hasLoginTerm = /login|log in|sign in|signin|sign-in|登录|登陆|ログイン/i.test(text);
    var hasRegisterTerm = /register|signup|sign up|sign-up|注册|登録|가입|회원가입|註冊/i.test(text);
    var combined = hasLoginTerm && hasRegisterTerm;

    // ── 3. 结构语义 ──
    var strongStructuralRe = /login|signin|sign-in|register|regist|signup|sign-up|passport|登录|登陆|注册/i;
    var mediumStructuralRe = /account|member|user|profile|avatar|账户|账号|个人中心/i;
    var strongMatch = strongStructuralRe.test(semantic);
    var mediumMatch = mediumStructuralRe.test(semantic);

    // ── 4. 原生可交互检查 ──
    var tag = el.tagName;
    var role = _cleanEntryText(el.getAttribute('role') || '');
    var nativeInteractive = false;
    if (tag === 'BUTTON' || tag === 'A' || tag === 'INPUT') nativeInteractive = true;
    if (role === 'button' || role === 'link' || role === 'tab') nativeInteractive = true;
    if (el.hasAttribute('onclick') || el.hasAttribute('tabindex')) nativeInteractive = true;
    try {
        if (getComputedStyle(el).cursor === 'pointer') nativeInteractive = true;
    } catch(e) {}

    // ── div/span 必须是叶子式、可交互且文本紧凑 ──
    if (tag === 'DIV' || tag === 'SPAN') {
        if (!nativeInteractive || text.length > 40) return 0;
        // 检查子元素是否有相同文本（说明真正的点击目标是子元素）
        var children = el.children;
        for (var ch = 0; ch < children.length; ch++) {
            try {
                if (!_isEntryVisible(children[ch])) continue;
                var childText = _cleanEntryText(children[ch].innerText || children[ch].textContent || '');
                if (childText && childText === text) return 0;
            } catch(e) {}
        }
    }

    // ── 完全无信号则过滤 ──
    if (!explicitMatch && !combined && !(strongMatch && nativeInteractive)) {
        return 0;
    }

    // ── 计算分数 ──
    var score = 0;
    if (explicitMatch) score += 100;
    if (combined) score += 70;
    if (strongMatch) score += 50;
    else if (mediumMatch) score += 25;
    if (aria || title || alt || descendantName) score += 5;
    if (tag === 'BUTTON') score += 10;
    else if (tag === 'A') score += 8;
    score -= Math.min(text.length, 40);

    // ── 容器惩罚：有匹配子元素则扣分 ──
    try {
        var clickableChildren = el.querySelectorAll('a, button, [role="button"], [role="tab"]');
        for (var cc = 0; cc < clickableChildren.length; cc++) {
            var cct = _cleanEntryText(clickableChildren[cc].innerText ||
                clickableChildren[cc].textContent ||
                clickableChildren[cc].getAttribute('aria-label') || '');
            for (var eh2 = 0; eh2 < ENTRY_HINTS.length; eh2++) {
                var h2c = _cleanEntryText(ENTRY_HINTS[eh2]);
                if (cct === h2c) { score -= 60; break; }
                if (cct.split(/\s+/).indexOf(h2c) !== -1) { score -= 60; break; }
            }
            if (score < 0) break;  // 只扣一次
        }
    } catch(e) {}

    return Math.max(score, 0);
}

/**
 * 在指定文档及其 Shadow DOM 中搜索入口链接
 *
 * @param {Document} doc - 搜索根文档
 * @param {Array<number>} framePath - iframe 路径（用于标记来源）
 * @returns {Array<Object>} 排序去重后的链接列表
 */
function _searchEntryLinksInDoc(doc, framePath) {
    doc = doc || document;
    framePath = framePath || [];
    var results = [];

    // ── 1. 收集搜索根（文档 + 所有 Shadow DOM roots） ──
    var roots = [doc];
    for (var i = 0; i < roots.length && i < 200; i++) {
        try {
            var allInRoot = roots[i].querySelectorAll('*');
            for (var j = 0; j < allInRoot.length; j++) {
                if (allInRoot[j].shadowRoot) {
                    roots.push(allInRoot[j].shadowRoot);
                }
            }
        } catch(e) {}
    }

    // ── 2. 对每个 root 搜索候选元素 ──
    for (var r = 0; r < roots.length; r++) {
        var root = roots[r];

        // 结构语义 CSS 选择器（优先搜索）
        var structuralSelector = [
            // 强语义 class/id
            "[class*='login' i]", "[class*='signin' i]", "[class*='register' i]",
            "[class*='regist' i]", "[class*='signup' i]", "[class*='sign-up' i]",
            "[class*='account' i]", "[class*='profile' i]", "[class*='user' i]",
            "[class*='passport' i]", "[class*='member' i]", "[class*='avatar' i]",
            "[id*='login' i]", "[id*='register' i]", "[id*='account' i]",
            "[id*='user' i]", "[id*='signup' i]",
            // 原生交互元素
            "button", "a", "[role='button']", "[role='link']", "[role='tab']",
            "input[type='button']"
        ].join(',');

        var candidates = [];
        try {
            var structural = root.querySelectorAll(structuralSelector);
            for (var s = 0; s < structural.length; s++) {
                candidates.push(structural[s]);
            }
            // Fallback: div, span, img, svg, li（去重）
            var fallback = root.querySelectorAll('div, span, img, svg, li');
            for (var f = 0; f < fallback.length; f++) {
                if (candidates.indexOf(fallback[f]) === -1) {
                    candidates.push(fallback[f]);
                }
            }
        } catch(e) { continue; }

        // ── 3. 打分 ──
        for (var c = 0; c < candidates.length; c++) {
            var el = candidates[c];
            if (!_isEntryVisible(el)) continue;

            // 跳过 submit 按钮
            var type = (el.getAttribute('type') || '').toLowerCase();
            if (type === 'submit') continue;

            // 跳过 form 内的非链接/非 tab/非 button 元素
            try {
                if (el.closest && el.closest('form') && el.tagName !== 'A' &&
                    el.getAttribute('role') !== 'tab' && type !== 'button') {
                    continue;
                }
            } catch(e) {}

            var score = computeEntryScore(el);
            if (score <= 0) continue;

            var xpath = '';
            try {
                xpath = (typeof getXPath === 'function') ? getXPath(el) : gPt(el);
            } catch(e) { xpath = ''; }

            results.push({
                xpath: xpath,
                tagName: el.tagName || '',
                nodeType: el.nodeType || '',
                innerText: (el.innerText || '').substring(0, 200),
                href: el.getAttribute('href') || '',
                id: el.id || '',
                className: typeof el.className === 'string' ? el.className : '',
                ariaLabel: el.getAttribute('aria-label') || '',
                title: el.getAttribute('title') || '',
                onTop: (typeof onTopLayer === 'function') ? onTopLayer(el) : false,
                inView: isElementInViewport(el),
                score: score,
                framePath: framePath
            });
        }
    }

    // ── 4. 按 score 降序排序 ──
    results.sort(function(a, b) { return b.score - a.score; });

    // ── 5. 按 xpath 去重 ──
    var seen = [];
    var deduped = [];
    for (var ri = 0; ri < results.length; ri++) {
        if (seen.indexOf(results[ri].xpath) === -1) {
            seen.push(results[ri].xpath);
            deduped.push(results[ri]);
        }
    }

    return deduped;
}

/**
 * V2 入口链接发现：Shadow DOM + 结构语义打分 + iframe 递归搜索
 *
 * 先从主文档搜索，再递归搜索所有可访问的同源 iframe。
 * 返回按 score 降序排序、去重后的结果列表。
 *
 * @returns {Array<Object>} 链接属性列表（含 score, framePath 字段）
 */
function findEntryLinksV2() {
    var allResults = [];

    // ── 搜索主文档 ──
    var mainResults = _searchEntryLinksInDoc(document, []);
    for (var i = 0; i < mainResults.length; i++) {
        allResults.push(mainResults[i]);
    }

    // ── 搜索同源 iframe ──
    var iframes = document.querySelectorAll('iframe, frame');
    for (var fi = 0; fi < iframes.length; fi++) {
        try {
            var iframeDoc = iframes[fi].contentDocument || iframes[fi].contentWindow.document;
            if (!iframeDoc) continue;
            var frameResults = _searchEntryLinksInDoc(iframeDoc, [fi]);
            for (var j = 0; j < frameResults.length; j++) {
                allResults.push(frameResults[j]);
            }
        } catch(e) {
            // 跨域 iframe — 无法访问，跳过
        }
    }

    // ── 全局去重 ──
    var globalSeen = [];
    var globalDeduped = [];
    for (var ri = 0; ri < allResults.length; ri++) {
        if (globalSeen.indexOf(allResults[ri].xpath) === -1) {
            globalSeen.push(allResults[ri].xpath);
            globalDeduped.push(allResults[ri]);
        }
    }

    return globalDeduped;
}

/**
 * 三策略合并获取登录/注册链接（V2 引擎 + 精确正则 + 宽松正则 + 坐标位置）
 * V2 引擎优先，旧方法作为补充。
 * 自动去重
 *
 * @returns {Array<Object>} 排序去重后的链接属性列表（含 score 字段）
 */
function getLoginLinkAttrs() {
    var linkAttrs = [];
    var seenXpaths = [];

    // ═══ 优先：V2 引擎 (Shadow DOM + 打分 + iframe) ═══
    var v2Results = findEntryLinksV2();
    for (var i = 0; i < v2Results.length; i++) {
        v2Results[i].matchType = 'v2_scored';
        linkAttrs.push(v2Results[i]);
        seenXpaths.push(v2Results[i].xpath);
    }

    // ═══ 补充：旧版精确正则（去重追加） ═══
    if (ENABLE_LOOSE_LOGIN_LINK_MATCHES) {
        var exactLinks = findLoginLinks(true);
        for (var j = 0; j < exactLinks.length; j++) {
            if (seenXpaths.indexOf(exactLinks[j].xpath) === -1) {
                exactLinks[j].matchType = 'exact';
                exactLinks[j].score = 0;  // 旧版无打分
                linkAttrs.push(exactLinks[j]);
                seenXpaths.push(exactLinks[j].xpath);
            }
        }

        var looseLinks = findLoginLinks(false);
        for (var k = 0; k < looseLinks.length; k++) {
            if (seenXpaths.indexOf(looseLinks[k].xpath) === -1) {
                looseLinks[k].matchType = 'loose';
                looseLinks[k].score = 0;
                linkAttrs.push(looseLinks[k]);
                seenXpaths.push(looseLinks[k].xpath);
            }
        }
    }

    // ═══ 补充：坐标启发式（去重追加） ═══
    if (ENABLE_COORD_BASED_LINK_SEARCH) {
        var coordLinks = findLoginLinksByCoords();
        for (var c = 0; c < coordLinks.length; c++) {
            if (seenXpaths.indexOf(coordLinks[c].xpath) === -1) {
                coordLinks[c].matchType = 'coords';
                coordLinks[c].score = 0;
                linkAttrs.push(coordLinks[c]);
                // 坐标结果不加入去重集，允许与其他策略重复
            }
        }
    }

    return linkAttrs;
}

// ============================================================
// Part B3: CDP 原生点击 + Shadow DOM 字段检测 (tryClickAndDetect)
// 替代 Python 侧 Selenium click — 完全在 JS 上下文中执行，
// 使用 Promise + setTimeout 避免阻塞事件循环。
// ============================================================

/**
 * 在 JS 上下文中查找 xpath 元素 → 触发完整鼠标事件 → 异步轮询检测结果。
 *
 * 返回 Promise，需配合 CDP Runtime.evaluate 的 awaitPromise:true 使用。
 *
 * @param {string} xpath - 元素 XPath
 * @param {number} timeoutMs - 最大等待时间（毫秒，默认 5000）
 * @returns {Promise<Object>} {clicked, navigated, newUrl, hasPassword, passwordXpath}
 */
function tryClickAndDetect(xpath, timeoutMs) {
    timeoutMs = timeoutMs || 5000;
    return new Promise(function(resolve) {
        var result = {clicked: false, navigated: false, newUrl: '',
                      hasPassword: false, passwordXpath: ''};
        var oldUrl = window.location.href;

        // ── 1. 查找元素 ──
        var el = null;
        try {
            el = document.evaluate(
                xpath, document, null,
                XPathResult.FIRST_ORDERED_NODE_TYPE, null
            ).singleNodeValue;
        } catch(e) {}

        if (!el) { resolve(result); return; }

        // ── 2. 可见性检查 ──
        try {
            var rect = el.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) { resolve(result); return; }
            var cs = getComputedStyle(el);
            if (cs.display === 'none' || cs.visibility === 'hidden') { resolve(result); return; }
        } catch(e) { resolve(result); return; }

        // ── 3. 完整鼠标事件序列 (bubbles:true 穿透 React 合成事件委托) ──
        try {
            var mOpts = {bubbles: true, cancelable: true, view: window,
                         clientX: rect.left + rect.width/2,
                         clientY: rect.top + rect.height/2};
            el.dispatchEvent(new MouseEvent('mouseover', mOpts));
            el.dispatchEvent(new MouseEvent('mouseenter', mOpts));
            el.dispatchEvent(new MouseEvent('mousedown', mOpts));
            el.dispatchEvent(new MouseEvent('mouseup', mOpts));
            el.dispatchEvent(new MouseEvent('click', mOpts));
            // 也触发 focus + 原生 click
            try { el.focus(); } catch(e) {}
            try { el.click(); } catch(e) {}
            result.clicked = true;
        } catch(e) {}

        // ── 4. Shadow DOM 穿透搜索密码字段 ──
        function _findPasswordInShadow() {
            var SELECTORS = [
                'input[type=password]',
                'input[autocomplete=new-password]',
                'input[autocomplete=current-password]',
                'input[name*=password i]',
                'input[name*=passwd i]',
                'input[name*=pwd i]'
            ];
            var seen = new WeakSet();
            var roots = [document];
            for (var ri = 0; ri < roots.length && ri < 200; ri++) {
                for (var si = 0; si < SELECTORS.length; si++) {
                    try {
                        var nodes = roots[ri].querySelectorAll(SELECTORS[si]);
                        for (var ni = 0; ni < nodes.length; ni++) {
                            var n = nodes[ni];
                            if (seen.has(n)) continue;
                            seen.add(n);
                            if (n.offsetHeight > 0 && !n.disabled) {
                                try {
                                    return typeof getXPath === 'function' ? getXPath(n) : '';
                                } catch(e) { return ''; }
                            }
                        }
                    } catch(e) {}
                }
                try {
                    var all = roots[ri].querySelectorAll('*');
                    for (var ai = 0; ai < all.length; ai++) {
                        if (all[ai].shadowRoot && roots.indexOf(all[ai].shadowRoot) === -1) {
                            roots.push(all[ai].shadowRoot);
                        }
                    }
                } catch(e) {}
            }
            return '';
        }

        // ── 5. 异步轮询（setTimeout 让事件循环处理 React 渲染） ──
        var deadline = Date.now() + timeoutMs;
        function poll() {
            // URL 变化？
            var curUrl = window.location.href;
            if (curUrl !== oldUrl) {
                result.navigated = true;
                result.newUrl = curUrl;
                resolve(result);
                return;
            }
            // 密码字段出现？
            var pwdXp = _findPasswordInShadow();
            if (pwdXp) {
                result.hasPassword = true;
                result.passwordXpath = pwdXp;
                resolve(result);
                return;
            }
            // 超时？
            if (Date.now() >= deadline) {
                resolve(result);
                return;
            }
            setTimeout(poll, 200);
        }
        // 首次 poll 延迟 400ms 让模态框动画启动
        setTimeout(poll, 400);
    });
}

// ============================================================
// Part C: 跨 Frame 表单字段搜索 (Cross-Frame Field Detection)
// ============================================================

/**
 * 递归搜索当前页面及所有可访问的 iframe 中的邮箱和密码字段。
 * 先搜主 frame，再遍历所有子 iframe（含嵌套），任一命中即返回。
 *
 * @param {Document} optRoot - 可选的搜索根节点，默认 document
 * @returns {Array<Object>} [{frameUrl, emailFields, passwordFields}]
 */
function detectFieldsInAllFrames(optRoot) {
    var root = optRoot || document;
    var results = [];

    /**
     * 在给定文档中搜索邮箱和密码字段
     * @param {Document} doc
     * @param {string} frameUrl
     */
    function _searchDoc(doc, frameUrl) {
        var emails = [];
        var pwds = [];

        // 搜索邮箱字段（Fathom ML）
        try {
            if (typeof detectEmailInputs === 'function') {
                emails = detectEmailInputs(doc);
            }
        } catch(e) {}

        // 如果 Fathom 未找到，检查 type=email
        if (!emails || emails.length === 0) {
            try {
                var typeEmailInputs = doc.querySelectorAll('input[type="email"]');
                for (var ei = 0; ei < typeEmailInputs.length; ei++) {
                    var xp = '';
                    try { xp = (typeof getXPath === 'function') ? getXPath(typeEmailInputs[ei]) : ''; } catch(e) {}
                    emails.push({xpath: xp, score: -1});
                }
            } catch(e) {}
        }

        // 搜索密码字段（使用完整的可见性检查，而非仅 offsetHeight）
        // offsetHeight>0 无法过滤 visibility:hidden 或 opacity:0 的元素，
        // 导致 SPA 模态框切换 tab 后仍返回隐藏的登录表单密码字段。
        try {
            var pwdInputs = doc.querySelectorAll('input[type="password"]');
            for (var pi = 0; pi < pwdInputs.length; pi++) {
                var el = pwdInputs[pi];
                if (el.disabled) continue;
                // getBoundingClientRect: display:none → width/height=0
                var rect = el.getBoundingClientRect();
                if (rect.width <= 0 || rect.height <= 0) continue;
                // 检查祖先链上是否有隐藏元素
                var style = getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden') continue;
                if (parseFloat(style.opacity) === 0) continue;
                // 检查祖先可见性
                var ancestor = el.parentElement;
                var ancestorHidden = false;
                while (ancestor) {
                    try {
                        var as = getComputedStyle(ancestor);
                        if (as.display === 'none' || as.visibility === 'hidden') {
                            ancestorHidden = true;
                            break;
                        }
                    } catch(e) { break; }
                    ancestor = ancestor.parentElement;
                }
                if (ancestorHidden) continue;
                pwds.push((typeof getXPath === 'function') ? getXPath(pwdInputs[pi]) : '');
            }
        } catch(e) {}

        if (emails.length > 0 || pwds.length > 0) {
            results.push({
                frameUrl: frameUrl,
                emailFields: emails,
                passwordFields: pwds
            });
        }
    }

    // 1. 搜索主 frame
    _searchDoc(root, window.location.href);

    // 2. 如果主 frame 找到，直接返回
    if (results.length > 0 && results[0].emailFields.length > 0 && results[0].passwordFields.length > 0) {
        return results;
    }

    // 3. 递归搜索子 iframe
    try {
        var iframes = root.querySelectorAll('iframe');
        for (var i = 0; i < iframes.length; i++) {
            try {
                var innerDoc = iframes[i].contentDocument || iframes[i].contentWindow.document;
                if (!innerDoc) continue;

                var frameUrl = '';
                try { frameUrl = innerDoc.location.href; } catch(e) { frameUrl = 'iframe#' + i; }

                _searchDoc(innerDoc, frameUrl);

                // 如果找到完整结果，提前返回
                if (results.length > 0) {
                    var last = results[results.length - 1];
                    if (last.emailFields.length > 0 && last.passwordFields.length > 0) {
                        return results;
                    }
                }

                // 递归搜索嵌套 iframe
                var nestedResults = detectFieldsInAllFrames(innerDoc);
                for (var n = 0; n < nestedResults.length; n++) {
                    results.push(nestedResults[n]);
                }
            } catch(e) {
                // 跨域 iframe 无法访问，跳过
            }
        }
    } catch(e) {}

    return results;
}

// ================================================================
// detectPasswordFeedback — 多维度密码反馈检测
// ================================================================
// 用尽所有前端常见的密码错误反馈机制检测输入的密码是否被拒绝。
// 返回: { hasFeedback: bool, rejected: bool, type: string, message: string }
//
// 检测顺序 (任意一项命中即返回):
//   1. aria-invalid 属性
//   2. HTML5 Constraint Validation API (validity.valid / validationMessage)
//   3. :invalid CSS 伪类
//   4. 密码字段 class 变化 (error / invalid / danger)
//   5. aria-describedby 指向的错误元素
//   6. 兄弟/父级可见 error / hint / warning 元素文本
//   7. 表单级密码强度指示器
// ================================================================
function detectPasswordFeedback(passwordXPath) {
    var DEFAULT_RESULT = { hasFeedback: false, rejected: false, type: null, message: null };

    // 解析 XPath 定位密码元素
    var el = null;
    try {
        var result = document.evaluate(
            passwordXPath, document, null,
            XPathResult.FIRST_ORDERED_NODE_TYPE, null
        );
        el = result.singleNodeValue;
    } catch(e) {
        return DEFAULT_RESULT;
    }
    if (!el || el.nodeType !== 1) return DEFAULT_RESULT;

    // ---- 1. aria-invalid ----
    var ariaInv = el.getAttribute('aria-invalid');
    if (ariaInv !== null && ariaInv !== '') {
        if (ariaInv === 'true') {
            return { hasFeedback: true, rejected: true, type: 'aria-invalid', message: 'aria-invalid=true' };
        }
        if (ariaInv === 'false') {
            return { hasFeedback: true, rejected: false, type: 'aria-invalid', message: 'aria-invalid=false' };
        }
        // 其他非空值 (如 "grammar") — 视为有反馈但不确定是否拒绝
        return { hasFeedback: true, rejected: true, type: 'aria-invalid', message: String(ariaInv) };
    }

    // ---- 2. HTML5 Constraint Validation API ----
    try {
        if (typeof el.validity !== 'undefined' && el.validity !== null) {
            if (!el.validity.valid) {
                var vMsg = el.validationMessage || '';
                return {
                    hasFeedback: true, rejected: true, type: 'html5-validity',
                    message: vMsg.substring(0, 300)
                };
            }
        }
    } catch(e) {}

    // 单独检查 setCustomValidity 设置的消息（即使 validity.valid 可能为 true）
    try {
        var customMsg = el.validationMessage;
        if (customMsg && customMsg.length > 0) {
            return {
                hasFeedback: true, rejected: true, type: 'html5-custom-validity',
                message: customMsg.substring(0, 300)
            };
        }
    } catch(e) {}

    // ---- 3. :invalid CSS 伪类 ----
    try {
        if (el.matches && el.matches(':invalid')) {
            return { hasFeedback: true, rejected: true, type: 'css-invalid', message: 'matches :invalid' };
        }
    } catch(e) {}

    // ---- 4. 密码字段自身 class 变化 ----
    try {
        var cls = el.className || '';
        if (/error|invalid|danger|err/i.test(cls)) {
            return { hasFeedback: true, rejected: true, type: 'input-class', message: 'class contains error/invalid/danger' };
        }
    } catch(e) {}

    // ---- 5. aria-describedby 指向的元素 ----
    try {
        var describedby = el.getAttribute('aria-describedby');
        if (describedby) {
            var ids = describedby.split(/\s+/);
            for (var di = 0; di < ids.length; di++) {
                var descEl = document.getElementById(ids[di]);
                if (descEl && descEl.offsetParent !== null) {
                    var descText = (descEl.textContent || '').trim();
                    if (descText.length > 1) {
                        return {
                            hasFeedback: true, rejected: true, type: 'aria-describedby',
                            message: descText.substring(0, 300)
                        };
                    }
                }
            }
        }
    } catch(e) {}

    // ---- 6. 兄弟/父级可见 error / hint / warning 元素 ----
    var ERROR_SELECTORS = [
        '[class*="error"]', '[class*="invalid"]', '[class*="hint"]',
        '[class*="warning"]', '[class*="danger"]', '[class*="alert"]',
        '[role="alert"]', '[aria-live="polite"]', '[aria-live="assertive"]',
        '.form-feedback', '.field-error', '.input-error', '.form-error',
        '.help-block', '.help-inline', '.error-message', '.err-msg',
        '[class*="err-"]', '.text-error', '.text-danger',
        '.v-messages',               // Vuetify
        '.MuiFormHelperText-root',   // Material-UI
        '.ant-form-item-explain',    // Ant Design
        '.el-form-item__error',      // Element UI
        '.invalid-feedback',         // Bootstrap 4+
        '.parsley-errors-list',      // Parsley.js
        '.help-block'                // Bootstrap 3
    ];

    // 搜索范围: 先看密码字段的父级容器，再看整个 form
    var searchRoots = [];
    var parent = el.parentElement;
    for (var level = 0; level < 4 && parent; level++) {
        searchRoots.push(parent);
        parent = parent.parentElement;
    }
    var form = el.closest('form');
    if (form) searchRoots.push(form);
    // 去重 (用 tagName + level 近似)
    var seen = {};
    var uniqueRoots = [];
    for (var ri = 0; ri < searchRoots.length; ri++) {
        var key = (searchRoots[ri].id || '') + '_' + searchRoots[ri].tagName + '_' + ri;
        if (!seen[key]) {
            uniqueRoots.push(searchRoots[ri]);
            seen[key] = true;
        }
    }

    for (var si = 0; si < ERROR_SELECTORS.length; si++) {
        for (var rootIdx = 0; rootIdx < uniqueRoots.length; rootIdx++) {
            try {
                var errEls = uniqueRoots[rootIdx].querySelectorAll(ERROR_SELECTORS[si]);
                for (var ei = 0; ei < errEls.length && ei < 3; ei++) {
                    var errEl = errEls[ei];
                    if (errEl.offsetParent !== null) {  // visible
                        var txt = (errEl.textContent || '').trim();
                        if (txt.length > 1) {
                            // ── 过滤非密码字段错误 ──
                            // gitee 等网站在密码框 blur 时会触发表单级校验，
                            // "姓名为必填项"等错误与密码字段无关，不应视为密码反馈。
                            var _txtLower = txt.toLowerCase();
                            var _nonPwdTerms = [
                                '姓名为必填', '姓名不能为空', '请填写姓名',
                                '邮箱为必填', '邮箱不能为空', '请填写邮箱',
                                '手机号为必填', '手机不能为空', '请填写手机',
                                '用户名为必填', '验证码',
                                'name is required', 'name required',
                                'email is required', 'email required',
                                'phone is required', 'phone required',
                                'username is required', 'nickname is required',
                                'captcha', 'verification code',
                                'please enter your name', 'please enter name',
                                'please enter your email',
                                'please enter your phone',
                            ];
                            var _isNonPwd = false;
                            for (var _ni = 0; _ni < _nonPwdTerms.length; _ni++) {
                                if (_txtLower.indexOf(_nonPwdTerms[_ni]) !== -1) {
                                    _isNonPwd = true;
                                    break;
                                }
                            }
                            if (_isNonPwd) continue;  // 跳过非密码字段错误
                            return {
                                hasFeedback: true, rejected: true, type: 'error-element',
                                message: txt.substring(0, 300)
                            };
                        }
                    }
                }
            } catch(e) {}
        }
    }

    // ---- 7. 表单级密码强度指示器 ----
    try {
        var strengthSelectors = [
            '.password-strength', '.js-validity-check',
            '[data-testid*="password"]', '[data-testid*="pwd"]',
            '[class*="password-strength"]', '[class*="strength-meter"]',
            '[class*="pw-strength"]', '[id*="password-strength"]',
            '.progress-bar', '[role="progressbar"]'
        ];
        for (var si2 = 0; si2 < strengthSelectors.length; si2++) {
            try {
                var strEls = document.querySelectorAll(strengthSelectors[si2]);
                for (var sei = 0; sei < strEls.length && sei < 3; sei++) {
                    if (strEls[sei].offsetParent !== null) {
                        var strTxt = (strEls[sei].textContent || '').trim();
                        // ── 密码强度指示器 ≠ 拒绝 ──
                        // 强度计显示"强/中/弱"等评级是对密码质量的描述，
                        // 不是"密码不合规"错误。只要密码能被强度计评级，
                        // 就说明它通过了基本验证。rejected 应为 false。
                        if (strTxt.length > 1) {
                            return {
                                hasFeedback: true, rejected: false, type: 'strength-indicator',
                                message: strTxt.substring(0, 300)
                            };
                        }
                        // 即使没有文本，存在可见的强度条也说明密码已被接受
                        return {
                            hasFeedback: true, rejected: false, type: 'strength-indicator',
                            message: 'visible strength indicator (no text)'
                        };
                    }
                }
            } catch(e) {}
        }
    } catch(e) {}

    return DEFAULT_RESULT;
}

// ================================================================
// watchPasswordFeedback — 异步持续反馈监听 (MutationObserver)
// ================================================================
// 安装 MutationObserver 持续监听 DOM 变化，捕获异步渲染的反馈。
// 比 detectPasswordFeedback() 更可靠，因为 React/Vue 等 SPA 框架
// 的错误反馈是异步插入 DOM 的，静态快照查询无法捕获。
//
// 监听目标:
//   - 新增的 DOM 节点匹配 error/hint/warning CSS 选择器
//   - 密码字段的 class 属性变化 (error/invalid/danger 类)
//   - 密码字段的 aria-invalid 属性变化
//   - 密码字段所在容器的子节点变化
//
// 结果存储在全局变量 __pwdFeedbackResults 中，
// Python 端通过 getWatchedFeedback() 轮询读取。
// ================================================================

var __pwdFeedbackWatcher = null;
var __pwdFeedbackResults = [];
var __pwdFeedbackPasswordEl = null;
var __pwdFeedbackWatchingXPath = null;  // 保存原始 XPath（密码字段可能在 iframe 内，document.evaluate 找不到时用于兜底）

var WATCH_ERROR_SELECTORS = [
    '[class*="error"]', '[class*="invalid"]', '[class*="warning"]',
    '[class*="danger"]', '[class*="alert"]', '[class*="hint"]',
    '[class*="success"]', '[class*="weak"]', '[class*="strong"]',
    '[role="alert"]', '[aria-live="polite"]', '[aria-live="assertive"]',
    '.form-feedback', '.field-error', '.input-error', '.form-error',
    '.help-block', '.help-inline', '.error-message', '.err-msg',
    '[class*="err-"]', '.text-error', '.text-danger', '.text-success',
    '.v-messages', '.MuiFormHelperText-root', '.ant-form-item-explain',
    '.el-form-item__error', '.invalid-feedback', '.parsley-errors-list',
    '.help-block', '[class*="feedback"]', '[class*="message"]',
    '[class*="tip"]', '[class*="notification"]', '[class*="toast"]',
    // 中文常见 class
    '[class*="提示"]', '[class*="错误"]', '[class*="校验"]',
    '[class*="tip"]', '[class*="msg"]',
    // Gitee 风格
    '.field-error', '.form-tip', '.ui.red.pointing',
    // 通用 — 任何可见的小文字块，如果出现在密码字段附近
    '[class*="helper"]', '[class*="description"]', '[class*="note"]'
];

function watchPasswordFeedback(passwordXPath) {
    // 停止已有监听器
    if (__pwdFeedbackWatcher) {
        __pwdFeedbackWatcher.disconnect();
        __pwdFeedbackWatcher = null;
    }
    __pwdFeedbackResults = [];
    __pwdFeedbackPasswordEl = null;
    __pwdFeedbackWatchingXPath = passwordXPath;  // 保存原始 XPath 供兜底使用

    // 解析 XPath 定位密码元素
    try {
        var xpr = document.evaluate(
            passwordXPath, document, null,
            XPathResult.FIRST_ORDERED_NODE_TYPE, null
        );
        __pwdFeedbackPasswordEl = xpr.singleNodeValue;
    } catch(e) {
        return false;
    }

    if (!__pwdFeedbackPasswordEl || __pwdFeedbackPasswordEl.nodeType !== 1) {
        return false;
    }

    // 标记密码字段
    __pwdFeedbackPasswordEl.setAttribute('data-pwd-feedback-watching', 'true');

    function recordFeedback(feedback) {
        // 跳过明显不是密码字段相关的错误（如"姓名为必填项"、"email is required"等）
        var msg = (feedback.message || '').toLowerCase();
        var nonPasswordTerms = [
            '姓名为必填', '姓名不能为空', 'name is required', 'name required',
            '邮箱为必填', '邮箱不能为空', 'email is required', 'email required',
            '手机号为必填', '手机不能为空', 'phone is required', 'phone required',
            '用户名为必填', 'username is required', 'nickname is required',
            '验证码', 'captcha', 'verification code',
            '请填写姓名', 'please enter your name', 'please enter name',
            '请填写邮箱', 'please enter your email',
            '请填写手机', 'please enter your phone',
        ];
        for (var ti = 0; ti < nonPasswordTerms.length; ti++) {
            if (msg.indexOf(nonPasswordTerms[ti]) !== -1) {
                return;  // 非密码字段错误，忽略
            }
        }
        // 按 message 去重
        for (var i = 0; i < __pwdFeedbackResults.length; i++) {
            if (__pwdFeedbackResults[i].message === feedback.message) {
                return;
            }
        }
        __pwdFeedbackResults.push(feedback);
    }

    var observer = new MutationObserver(function(mutations) {
        for (var mi = 0; mi < mutations.length; mi++) {
            var mutation = mutations[mi];

            // ---- 新增节点 ----
            if (mutation.type === 'childList' && mutation.addedNodes.length > 0) {
                for (var ai = 0; ai < mutation.addedNodes.length; ai++) {
                    var node = mutation.addedNodes[ai];
                    if (node.nodeType !== 1) continue;

                    // 检查新增节点自身
                    for (var si = 0; si < WATCH_ERROR_SELECTORS.length; si++) {
                        try {
                            if (node.matches && node.matches(WATCH_ERROR_SELECTORS[si])) {
                                var txt = (node.textContent || '').trim();
                                if (txt.length > 0 && node.offsetParent !== null) {
                                    if (recordFeedback({
                                        hasFeedback: true, rejected: true,
                                        type: 'observer-added-el',
                                        message: txt.substring(0, 300)
                                    })) return;
                                }
                            }
                        } catch(e) {}
                    }

                    // 检查新增节点的后代
                    for (var si2 = 0; si2 < WATCH_ERROR_SELECTORS.length; si2++) {
                        try {
                            var descendants = node.querySelectorAll(WATCH_ERROR_SELECTORS[si2]);
                            for (var di = 0; di < descendants.length && di < 3; di++) {
                                var dTxt = (descendants[di].textContent || '').trim();
                                if (dTxt.length > 0 && descendants[di].offsetParent !== null) {
                                    if (recordFeedback({
                                        hasFeedback: true, rejected: true,
                                        type: 'observer-descendant-el',
                                        message: dTxt.substring(0, 300)
                                    })) return;
                                }
                            }
                        } catch(e) {}
                    }
                }
            }

            // ---- 属性变化 ----
            if (mutation.type === 'attributes' && mutation.target === __pwdFeedbackPasswordEl) {
                var attrName = mutation.attributeName;

                if (attrName === 'aria-invalid') {
                    var ariaVal = __pwdFeedbackPasswordEl.getAttribute('aria-invalid');
                    if (ariaVal === 'true') {
                        if (recordFeedback({
                            hasFeedback: true, rejected: true,
                            type: 'observer-aria-invalid', message: 'aria-invalid=true'
                        })) return;
                    }
                }

                if (attrName === 'class') {
                    var cls = __pwdFeedbackPasswordEl.className || '';
                    if (/error|invalid|danger|err|success/.test(cls)) {
                        if (recordFeedback({
                            hasFeedback: true, rejected: !/success/.test(cls),
                            type: 'observer-class-change',
                            message: 'class: ' + cls.substring(0, 100)
                        })) return;
                    }
                }
            }
        }
    });

    // 在 document.body 上监听子树变化
    observer.observe(document.body, {
        childList: true,
        subtree: true
    });

    // 在密码字段上监听属性变化
    if (__pwdFeedbackPasswordEl) {
        observer.observe(__pwdFeedbackPasswordEl, {
            attributes: true,
            attributeFilter: ['class', 'aria-invalid', 'aria-describedby']
        });

        // 在密码字段的父级链上监听子节点变化
        var parent = __pwdFeedbackPasswordEl.parentElement;
        for (var level = 0; level < 5 && parent; level++) {
            try {
                observer.observe(parent, { childList: true, subtree: false });
            } catch(e) {}
            parent = parent.parentElement;
        }
    }

    __pwdFeedbackWatcher = observer;
    return true;
}

function getWatchedFeedback() {
    // 静态快照兜底：仅在 MutationObserver 未捕获到任何反馈时启用。
    // Observer 已捕获反馈时不再调用 detectPasswordFeedback()，
    // 避免将其他字段（如姓名字段）的预存错误误报为密码反馈。
    if (__pwdFeedbackResults.length === 0) {
        // 优先用标记属性 XPath，找不到元素时用保存的原始 XPath
        var fallbackXPath = __pwdFeedbackPasswordEl
            ? '//*[@data-pwd-feedback-watching="true"]'
            : __pwdFeedbackWatchingXPath;
        if (fallbackXPath) {
            try {
                var staticResult = detectPasswordFeedback(fallbackXPath);
                if (staticResult && staticResult.hasFeedback) {
                    __pwdFeedbackResults.push(staticResult);
                }
            } catch(e) {}
        }
    }
    return __pwdFeedbackResults.slice();
}

function stopWatchingFeedback() {
    if (__pwdFeedbackWatcher) {
        __pwdFeedbackWatcher.disconnect();
        __pwdFeedbackWatcher = null;
    }
    if (__pwdFeedbackPasswordEl) {
        __pwdFeedbackPasswordEl.removeAttribute('data-pwd-feedback-watching');
        __pwdFeedbackPasswordEl = null;
    }
    var saved = __pwdFeedbackResults.slice();
    __pwdFeedbackResults = [];
    return saved;
}
