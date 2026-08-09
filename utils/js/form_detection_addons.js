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

/**
 * 三策略合并获取登录/注册链接（精确正则 + 宽松正则 + 坐标位置）
 * 按优先级排序：button/link 优先 > onTop 优先 > inView 优先
 * 自动去重
 *
 * @returns {Array<Object>} 排序去重后的链接属性列表
 */
function getLoginLinkAttrs() {
    var linkAttrs = [];
    var seenXpaths = [];
    var linkMatchTypes = ["exact", "loose"];

    if (ENABLE_COORD_BASED_LINK_SEARCH) {
        linkMatchTypes.push('coords');
    }

    for (var t = 0; t < linkMatchTypes.length; t++) {
        var matchType = linkMatchTypes[t];
        var loginLinks;

        if (matchType === "coords") {
            loginLinks = findLoginLinksByCoords();
        } else {
            loginLinks = findLoginLinks(matchType === "exact");
        }

        // 标记匹配类型
        for (var i = 0; i < loginLinks.length; i++) {
            loginLinks[i].matchType = matchType;
        }

        // 排序：button/link 优先 > onTop 优先 > inView 优先
        loginLinks.sort(function(a, b) {
            if (isButtonOrLink(a.nodeType) > isButtonOrLink(b.nodeType)) return -1;
            if (isButtonOrLink(a.nodeType) < isButtonOrLink(b.nodeType)) return 1;
            if (a.onTop > b.onTop) return -1;
            if (a.onTop < b.onTop) return 1;
            if (a.inView > b.inView) return -1;
            if (a.inView < b.inView) return 1;
            return 0;
        });

        // 去重
        for (var j = 0; j < loginLinks.length; j++) {
            if (seenXpaths.indexOf(loginLinks[j].xpath) === -1) {
                linkAttrs.push(loginLinks[j]);
                if (matchType !== "coords") {
                    seenXpaths.push(loginLinks[j].xpath);
                }
            }
        }
    }

    return linkAttrs;
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

        // 搜索密码字段
        try {
            var pwdInputs = doc.querySelectorAll('input[type="password"]');
            for (var pi = 0; pi < pwdInputs.length; pi++) {
                if (pwdInputs[pi].offsetHeight > 0 && !pwdInputs[pi].disabled) {
                    pwds.push((typeof getXPath === 'function') ? getXPath(pwdInputs[pi]) : '');
                }
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
                        if (strTxt.length > 1) {
                            return {
                                hasFeedback: true, rejected: true, type: 'strength-indicator',
                                message: strTxt.substring(0, 300)
                            };
                        }
                        // 即使没有文本，存在可见的强度条也说明有反馈
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
