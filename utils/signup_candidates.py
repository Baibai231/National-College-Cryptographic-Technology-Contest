"""Generate and rank safe signup-page URL candidates.

This module contains no networking or browser code.  The same deterministic
ranking can therefore be used by the cheap HTTP preflight and by Selenium,
and can be regression-tested without visiting a website.
"""
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional
from urllib.parse import urljoin, urlparse, urlunparse


COMMON_SIGNUP_PATHS = (
    "/signup", "/register", "/join", "/sign-up", "/sign_up",
    "/create-account", "/create_account", "/registration",
    "/account/register", "/account/signup", "/account/create",
    "/accounts/register", "/accounts/signup", "/accounts/emailsignup",
    "/users/sign_up", "/user/register", "/member/register",
    "/auth/register", "/auth/signup", "/start", "/get-started",
)

_SIGNUP_PHRASES = (
    "sign up", "signup", "sign-up", "register", "registration",
    "create account", "create-account", "new account", "join now",
    "join free", "get started", "注册", "註冊", "新用户", "新規登録",
    "会員登録", "アカウント作成", "회원가입", "계정 만들기",
    "s'inscrire", "registrarse", "registrieren", "zarejestruj",
    "зарегистрироваться",
)
_GENERIC_SIGNUP_PHRASES = {
    "join now", "join free", "get started",
}
_SIGNUP_PATH = re.compile(
    r"(?:^|[/_.-])(signup|emailsignup|sign-up|sign_up|register|registration|join|"
    r"create-account|create_account|createaccount|new-account)(?:[/_.?#-]|$)",
    re.I,
)
_AUTH_HOST = re.compile(
    r"^(accounts?|auth|id|identity|login|member|passport|profile|sso)\.", re.I)
_NEGATIVE = re.compile(
    r"(logout|log-out|signout|sign-out|delete|remove|unsubscribe|"
    r"privacy|terms|policy|career|jobs?|developer|merchant|seller|vendor|"
    r"business|enterprise|organization|organisation|product|warranty|event|"
    r"forgot|reset|recover|recovery|"
    r"机构|企业|商家|产品注册|活动报名|注销)", re.I)
_LOGIN_ONLY = re.compile(r"(?:^|[/_.-])(login|log-in|signin|sign-in)(?:[/_.?#-]|$)", re.I)
_LOGIN_PHRASES = (
    "log in", "login", "log-in", "sign in", "signin", "sign-in",
    "account", "member center", "登录", "登入", "登陆", "会员中心",
    "ログイン", "로그인", "connexion", "iniciar sesión", "anmelden",
)
_ACCOUNT_PATH = re.compile(
    r"(?:^|[/_.-])(account|member|auth|identity|passport)(?:[/_.?#-]|$)", re.I)
_NON_ACCOUNT_HOST = re.compile(
    r"(?:^|\.)(?:events?|careers?|jobs?)(?:\.|$)", re.I)
_NON_ACCOUNT_REGISTRATION = re.compile(
    r"register(?:ing)?\s+(?:a\s+)?(?:domain|device|product|warranty|event)|"
    r"(?:domain(?:\s+name)?|device|product|warranty|event)\s+registration",
    re.I,
)

# Small offline public-suffix fallback for the country suffixes most likely in
# this project.  Production environments may have tldextract installed; this
# table prevents unsafe ``co.uk``/``com.cn`` comparisons when it is not.
_COMMON_TWO_LABEL_SUFFIXES = {
    "com.cn", "net.cn", "org.cn", "gov.cn", "edu.cn",
    "com.hk", "com.tw", "com.au", "com.br", "com.mx", "com.tr",
    "co.uk", "org.uk", "ac.uk", "gov.uk",
    "co.jp", "ne.jp", "or.jp", "ac.jp",
    "co.kr", "or.kr", "co.in", "firm.in", "net.in", "org.in",
    "co.nz", "co.za", "com.sg", "com.my",
}


def registered_domain(url_or_host: str) -> str:
    parsed = urlparse(url_or_host if "://" in url_or_host
                      else "https://" + url_or_host)
    host = (parsed.hostname or "").strip(".").lower()
    parts = host.split(".") if host else []
    if len(parts) < 2:
        return host
    suffix2 = ".".join(parts[-2:])
    if suffix2 in _COMMON_TWO_LABEL_SUFFIXES and len(parts) >= 3:
        return ".".join(parts[-3:])
    return suffix2


def same_registered_site(first: str, second: str) -> bool:
    one = registered_domain(first)
    two = registered_domain(second)
    return bool(one and two and one == two)


def _normalized_http_url(base: str, target: str) -> Optional[str]:
    try:
        absolute = urljoin(base, target or "")
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None
        if parsed.username or parsed.password:
            return None
        # Fragments rarely select a different server resource and create many
        # duplicate candidates.  Query parameters are retained because some
        # identity providers route signup through them.
        return urlunparse((
            parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/",
            parsed.params, parsed.query, "",
        ))
    except Exception:
        return None


def _link_semantic(link: Mapping[str, Any]) -> str:
    values = [
        link.get("innerText"), link.get("text"), link.get("href"),
        link.get("ariaLabel"), link.get("aria-label"), link.get("title"),
        link.get("dataTestid"), link.get("id"), link.get("className"),
    ]
    return " ".join(str(value or "") for value in values).lower()


def _link_label_semantic(link: Mapping[str, Any]) -> str:
    """Link semantics excluding href/query routing noise."""
    values = [
        link.get("innerText"), link.get("text"), link.get("ariaLabel"),
        link.get("aria-label"), link.get("title"), link.get("dataTestid"),
        link.get("id"), link.get("className"),
    ]
    return " ".join(str(value or "") for value in values).lower()


def _visible_link_semantic(link: Mapping[str, Any]) -> str:
    """User-visible anchor semantics, excluding reusable CSS/analytics names."""
    values = [
        link.get("innerText"), link.get("text"), link.get("ariaLabel"),
        link.get("aria-label"), link.get("title"),
    ]
    return " ".join(str(value or "") for value in values).lower()


def _score(url: str, semantic: str, base: str, source: str,
           upstream_score: float = 0.0) -> Optional[Dict[str, Any]]:
    if not same_registered_site(base, url):
        return None
    parsed = urlparse(url)
    combined = "{} {} {}".format(semantic, parsed.netloc, parsed.path).lower()
    negative_surface = "{} {} {}".format(
        semantic, parsed.path, parsed.query).lower()
    if _NEGATIVE.search(negative_surface):
        return None

    reasons: List[str] = []
    score = min(max(float(upstream_score or 0.0), 0.0), 100.0) * 0.1
    phrase_hits = [phrase for phrase in _SIGNUP_PHRASES if phrase in combined]
    if phrase_hits:
        strong_hits = [
            phrase for phrase in phrase_hits
            if phrase not in _GENERIC_SIGNUP_PHRASES]
        if strong_hits:
            score += 90.0 + min(20.0, 4.0 * len(strong_hits))
            reasons.append("signup_semantic")
        else:
            score += 10.0
            reasons.append("generic_account_cta")
    if _SIGNUP_PATH.search(parsed.path):
        score += 85.0
        reasons.append("signup_path")
    if _AUTH_HOST.search(parsed.hostname or ""):
        score += 20.0
        reasons.append("auth_subdomain")
    if parsed.query and re.search(r"(signup|register|create|new)", parsed.query, re.I):
        score += 35.0
        reasons.append("signup_query")
    if _LOGIN_ONLY.search(parsed.path) and not phrase_hits:
        score -= 45.0
        reasons.append("login_only_penalty")
    if source == "observed_link":
        score += 15.0
        reasons.append("observed_on_page")
    elif source == "common_path":
        score += 2.0

    if score < 45.0:
        return None
    return {
        "url": url,
        "score": round(score, 2),
        "source": source,
        "reasons": reasons,
    }


def rank_signup_candidates(
    homepage_url: str,
    links: Iterable[Mapping[str, Any]] = (),
    common_paths: Iterable[str] = COMMON_SIGNUP_PATHS,
    limit: int = 12,
) -> List[Dict[str, Any]]:
    """Return de-duplicated same-site candidates in descending confidence."""
    best: Dict[str, Dict[str, Any]] = {}
    for link in links or ():
        href = str(link.get("href") or "").strip()
        url = _normalized_http_url(homepage_url, href)
        if not url:
            continue
        candidate = _score(
            url, _link_semantic(link), homepage_url, "observed_link",
            float(link.get("score") or 0.0),
        )
        if candidate and (
                url not in best or candidate["score"] > best[url]["score"]):
            best[url] = candidate

    parsed = urlparse(homepage_url)
    origin = urlunparse((parsed.scheme or "https", parsed.netloc, "/", "", "", ""))
    for path in common_paths:
        url = _normalized_http_url(origin, path)
        if not url:
            continue
        candidate = _score(url, path, homepage_url, "common_path")
        if candidate and (
                url not in best or candidate["score"] > best[url]["score"]):
            best[url] = candidate

    ranked = sorted(
        best.values(), key=lambda item: (-item["score"], item["url"]))
    return ranked[:max(0, limit)]


def rank_auth_entry_candidates(
    homepage_url: str,
    links: Iterable[Mapping[str, Any]] = (),
    limit: int = 12,
) -> List[Dict[str, Any]]:
    """Rank observed signup/login/account links for one shallow crawl hop.

    Login pages are valuable preflight targets because many sites place their
    only registration link inside the login UI.  This function never invents
    URLs and never returns a cross-site target.
    """
    best: Dict[str, Dict[str, Any]] = {}
    for link in links or ():
        href = str(link.get("href") or "").strip()
        url = _normalized_http_url(homepage_url, href)
        if not url or not same_registered_site(homepage_url, url):
            continue
        semantic = _link_label_semantic(link)
        visible_semantic = _visible_link_semantic(link)
        parsed = urlparse(url)
        negative_surface = "{} {} {}".format(
            semantic, parsed.path, parsed.query).lower()
        if (_NEGATIVE.search(negative_surface)
                or _NON_ACCOUNT_HOST.search(parsed.hostname or "")
                or _NON_ACCOUNT_REGISTRATION.search(visible_semantic)):
            continue

        combined = "{} {} {}".format(
            semantic, parsed.netloc, parsed.path).lower()
        signup_hits = [
            phrase for phrase in _SIGNUP_PHRASES
            if phrase in visible_semantic
        ]
        strong_signup_hits = [
            phrase for phrase in signup_hits
            if phrase not in _GENERIC_SIGNUP_PHRASES]
        login_hits = [phrase for phrase in _LOGIN_PHRASES if phrase in combined]
        signup_path = bool(_SIGNUP_PATH.search(parsed.path))
        login_path = bool(_LOGIN_ONLY.search(parsed.path))
        account_path = bool(_ACCOUNT_PATH.search(parsed.path))
        auth_host = bool(_AUTH_HOST.search(parsed.hostname or ""))
        if not any((strong_signup_hits, login_hits, signup_path, login_path,
                    account_path, auth_host)):
            continue

        if strong_signup_hits or signup_path:
            intent = "signup"
            score = 150.0 + 5.0 * len(strong_signup_hits)
        elif login_hits or login_path:
            intent = "login"
            score = 95.0 + 3.0 * len(login_hits)
        else:
            intent = "account"
            score = 60.0
        if auth_host:
            score += 20.0
        if account_path:
            score += 10.0
        score += min(max(float(link.get("score") or 0.0), 0.0), 100.0) * 0.1
        candidate = {
            "url": url,
            "score": round(score, 2),
            "source": "observed_link",
            "intent": intent,
        }
        if url not in best or candidate["score"] > best[url]["score"]:
            best[url] = candidate
    return sorted(
        best.values(), key=lambda item: (-item["score"], item["url"])
    )[:max(0, limit)]
