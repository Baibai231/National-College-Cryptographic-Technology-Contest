/**
 * form_detector.js — 复用 LoginFormExploration 的 Fathom 表单识别
 *
 * 用法: node form_detector.js <URL>
 * 输出: JSON { success, signup_url, email_xpath, password_xpath }
 *
 * 依赖: LoginFormExploration 项目在 ../LoginFormExploration-main 路径
 */

const fs = require('fs');
const path = require('path');

// LoginFormExploration 项目路径
const loginExplPath = process.env.LOGIN_EXPLORATION_PATH ||
    path.resolve(__dirname, '..', 'LoginFormExploration-main', 'LoginFormExploration-main');

// 将 LoginFormExploration 的 node_modules 加入搜索路径
const nodeModulesPath = path.join(loginExplPath, 'node_modules');
if (fs.existsSync(nodeModulesPath)) {
    if (!process.env.NODE_PATH) {
        process.env.NODE_PATH = nodeModulesPath;
    } else if (!process.env.NODE_PATH.includes(nodeModulesPath)) {
        process.env.NODE_PATH = nodeModulesPath + path.delimiter + process.env.NODE_PATH;
    }
    require('module').Module._initPaths();
}

// 使用 puppeteer-extra + stealth 插件绕过 GitHub 反爬检测
const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
puppeteer.use(StealthPlugin());

// 加载 Fathom 检测脚本（原始 JS 内容直接注入浏览器）
const fathomSrc = fs.readFileSync(
    path.join(loginExplPath, 'helpers', 'fathomDetect.js'), 'utf8'
);

// ================================================================
// 多语言正则（直接从 LoginFormExploration helpers/utils.js 复制）
// ================================================================
const loginRegex = /login|log in|log on|log-on|Войти|sign in|sigin|sign\/in|sign-in|sign on|sign-on|ورود|登录|Přihlásit se|Přihlaste|Авторизоваться|Авторизация|entrar|ログイン|로그인|inloggen|Συνδέσου|accedi|ログオン|Giriş Yap|登入|connecter|connectez-vous|Connexion|Вход/i;
const loginFormAttrRegex = /login|log in|log on|log-on|sign in|sigin|sign\/in|sign-in|sign on|sign-on/i;
const loginRegexExtra = /log_in|logon|log_on|signin|sign_in|sign_up|signon|sign_on|Aanmelden/i;
const combinedLoginLinkRegexSrc = [
    loginRegex.source, loginFormAttrRegex.source, loginRegexExtra.source
].join('|');

// ================================================================
// 链接发现（直接用 Puppeteer API，不依赖 utils.js 的 this 绑定）
// ================================================================

async function findLoginLinks(page) {
    /** 在页面中运行正则匹配，返回匹配元素的 XPath 列表 */
    return page.evaluate((regexSrc) => {
        const rx = new RegExp(regexSrc, 'i');
        const all = document.querySelectorAll('a, span, button, div');
        const results = [];
        for (const el of all) {
            if ((el.innerText && el.innerText.match(rx)) ||
                (el.title && el.title.match(rx)) ||
                (el.ariaLabel && el.ariaLabel.match(rx)) ||
                (el.getAttribute('href') && String(el.getAttribute('href')).match(rx)) ||
                (el.id && el.id.match(rx)) ||
                (el.className && String(el.className).match(rx))) {
                // Use Fathom's getXPath if available, otherwise DOM path
                let xpath = '';
                try {
                    xpath = (typeof fathom !== 'undefined' && fathom.getXPath)
                        ? fathom.getXPath(el) : '';
                } catch (e) { xpath = ''; }
                results.push({
                    xpath: xpath,
                    tagName: el.tagName,
                    innerText: (el.innerText || '').substring(0, 100),
                    href: el.getAttribute('href') || '',
                });
            }
        }
        return results;
    }, combinedLoginLinkRegexSrc);
}

// ================================================================
// 主流程
// ================================================================

async function main() {
    const url = process.argv[2];
    if (!url) {
        console.error('用法: node form_detector.js <URL>');
        process.exit(1);
    }

    const homepageUrl = url.startsWith('http') ? url : 'https://' + url;
    console.error(`[*] 目标: ${homepageUrl}`);

    const browser = await puppeteer.launch({
        headless: 'new',
        args: ['--no-sandbox', '--disable-dev-shm-usage']
    });

    let signupUrl = null;
    let emailXpath = null;
    let passwordXpath = null;

    try {
        const page = await browser.newPage();
        await page.setUserAgent(
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' +
            '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
        );
        await page.setViewport({ width: 1440, height: 812 });
        // 注入 Fathom 检测脚本（每个新页面自动执行）
        await page.evaluateOnNewDocument(fathomSrc);

        const base = homepageUrl.replace(/\/$/, '');
        const signupPatterns = [
            '/signup', '/register', '/join', '/sign_up',
            '/create-account', '/get-started', '/sign-up'
        ];

        // ================================================================
        // 策略 1: 直接尝试常见注册 URL
        // ================================================================
        console.error('[*] 策略 1: 直接 URL 尝试...');
        for (const pattern of signupPatterns) {
            const tryUrl = base + pattern;
            try {
                await page.goto(tryUrl, { timeout: 15000, waitUntil: 'domcontentloaded' });
                await page.waitForTimeout(2000);

                const fieldCount = await page.evaluate(() => {
                    const pwds = document.querySelectorAll('input[type=password]').length;
                    const emails = document.querySelectorAll('input[type=email]').length;
                    const emailById = document.getElementById('email') ? 1 : 0;
                    // Check for text inputs that look like email fields
                    const textInputs = document.querySelectorAll('input[type=text],input:not([type])');
                    let emailLike = 0;
                    for (const inp of textInputs) {
                        const attrs = (inp.id || '') + (inp.name || '') + (inp.getAttribute('autocomplete') || '');
                        if (/email|e-mail|mail/i.test(attrs)) emailLike++;
                    }
                    return pwds + emails + emailById + emailLike;
                });
                if (fieldCount > 0) {
                    signupUrl = tryUrl;
                    console.error(`    ✓ 命中: ${tryUrl} (${fieldCount} 相关字段)`);
                    break;
                } else {
                    console.error(`    - ${tryUrl}: 无密码字段`);
                }
            } catch (e) {
                console.error(`    ✗ ${tryUrl}: ${e.message.substring(0, 60)}`);
            }
        }

        // ================================================================
        // 策略 2: 首页链接发现
        // ================================================================
        if (!signupUrl) {
            console.error('[*] 策略 2: 首页链接发现...');
            try {
                await page.goto(homepageUrl, { timeout: 15000, waitUntil: 'domcontentloaded' });
            } catch (e) {
                console.error(`    首页加载失败: ${e.message}`);
            }
            await page.waitForTimeout(2000);

            const links = await findLoginLinks(page);
            console.error(`    发现 ${links.length} 个链接`);

            // 优先注册相关链接
            const signupKW = ['sign up', 'signup', 'register', 'create account',
                             'get started', 'join', 'Sign up', 'Sign Up'];
            const isSignup = (l) => signupKW.some(kw =>
                (l.innerText || '').includes(kw) || (l.href || '').includes(kw));
            const sorted = [...links.filter(isSignup), ...links.filter(l => !isSignup(l))];

            for (const link of sorted.slice(0, 10)) {
                if (!link.xpath) continue;
                try {
                    const el = await page.$('xpath/' + link.xpath);
                    if (!el) continue;
                    const oldUrl = page.url();
                    await el.click();
                    await page.waitForTimeout(2000);
                    const newUrl = page.url();
                    if (newUrl !== oldUrl && newUrl !== homepageUrl) {
                        signupUrl = newUrl;
                        console.error(`    ✓ 导航: -> ${newUrl} (${link.innerText})`);
                        break;
                    }
                } catch (e) {
                    // continue
                }
            }
        }

        if (!signupUrl) {
            console.log(JSON.stringify({ success: false, error: 'No signup page found' }));
            await browser.close();
            process.exit(0);
        }

        // ================================================================
        // Fathom 字段检测
        // ================================================================
        console.error('[*] Fathom 字段检测...');

        // 邮箱字段
        emailXpath = await page.evaluate(() => {
            const results = [];
            if (typeof fathom !== 'undefined' && fathom.detectEmailInputs) {
                for (const f of fathom.detectEmailInputs(document)) {
                    results.push({ xpath: f.xpath, score: f.score });
                }
            }
            return results.length > 0 ? results[0].xpath : null;
        });

        // 密码字段
        passwordXpath = await page.evaluate(() => {
            const pwds = document.querySelectorAll('input[type=password]');
            for (const pwd of pwds) {
                if (pwd.offsetHeight > 0 && !pwd.disabled) {
                    return (typeof fathom !== 'undefined' && fathom.getXPath)
                        ? fathom.getXPath(pwd) : '';
                }
            }
            return null;
        });

        console.error(`    邮箱: ${emailXpath || '未检测到'}`);
        console.error(`    密码: ${passwordXpath || '未检测到'}`);

        console.log(JSON.stringify({
            success: true,
            signup_url: signupUrl,
            email_xpath: emailXpath,
            password_xpath: passwordXpath,
        }));

    } finally {
        await browser.close();
    }
}

main().catch(e => {
    console.error(e);
    console.log(JSON.stringify({ success: false, error: e.message }));
    process.exit(1);
});
