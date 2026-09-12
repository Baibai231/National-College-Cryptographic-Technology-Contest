"""Low-cost authentication signals extracted from an HTML document."""
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from utils.signup_candidates import (
    rank_auth_entry_candidates,
    rank_signup_candidates,
)
from utils.password_policy_evidence import parse_password_policy_texts


def _positive_int(value: Optional[str]) -> Optional[int]:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


class _AuthHTMLParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.links: List[Dict[str, Any]] = []
        self.password_inputs: List[Dict[str, Any]] = []
        self.email_input_count = 0
        self.phone_input_count = 0
        self.form_count = 0
        self._anchor: Optional[Dict[str, Any]] = None
        self._title_depth = 0
        self._title_parts: List[str] = []
        self._body_parts: List[str] = []
        self._body_length = 0
        self.text_snippets: List[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        values = {str(key).lower(): str(value or "") for key, value in attrs}
        tag = tag.lower()
        if tag == "form":
            self.form_count += 1
        elif tag == "input":
            input_type = values.get("type", "text").lower()
            semantic = " ".join((
                input_type, values.get("name", ""), values.get("id", ""),
                values.get("placeholder", ""), values.get("aria-label", ""),
                values.get("autocomplete", ""),
            )).lower()
            password_like = (
                input_type == "password"
                or values.get("autocomplete", "").lower() == "new-password"
                or any(word in semantic for word in ("password", "passwd", "pwd", "密码"))
            )
            if password_like:
                self.password_inputs.append({
                    "type": input_type,
                    "autocomplete": values.get("autocomplete") or None,
                    "minlength": _positive_int(values.get("minlength")),
                    "maxlength": _positive_int(values.get("maxlength")),
                    "pattern_present": bool(values.get("pattern")),
                    "required": "required" in values,
                })
            if input_type == "email" or "email" in semantic or "邮箱" in semantic:
                self.email_input_count += 1
            if input_type == "tel" or any(
                    word in semantic for word in ("phone", "mobile", "手机")):
                self.phone_input_count += 1
        elif tag == "a":
            href = values.get("href", "").strip()
            if href:
                self._anchor = {
                    "href": urljoin(self.base_url, href),
                    "innerText": "",
                    "ariaLabel": values.get("aria-label", ""),
                    "title": values.get("title", ""),
                    "dataTestid": values.get("data-testid", ""),
                    "id": values.get("id", ""),
                    "className": values.get("class", ""),
                }
        elif tag == "title":
            self._title_depth += 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "a" and self._anchor is not None:
            self._anchor["innerText"] = self._anchor["innerText"].strip()[:300]
            self.links.append(self._anchor)
            self._anchor = None
        elif tag == "title" and self._title_depth:
            self._title_depth -= 1

    def handle_data(self, data: str) -> None:
        clean = " ".join((data or "").split())
        if not clean:
            return
        if self._anchor is not None:
            self._anchor["innerText"] += " " + clean
        if self._title_depth:
            self._title_parts.append(clean)
        if self._body_length < 20000:
            self._body_parts.append(clean)
            self._body_length += len(clean) + 1
        if len(clean) <= 500 and len(self.text_snippets) < 2000:
            self.text_snippets.append(clean)

    @property
    def title(self) -> str:
        return " ".join(self._title_parts)[:500]

    @property
    def body_text(self) -> str:
        return " ".join(self._body_parts)[:20000]


def extract_static_auth_signals(html: str, page_url: str) -> Dict[str, Any]:
    parser = _AuthHTMLParser(page_url)
    try:
        parser.feed(html or "")
    except Exception:
        # Real-world markup is frequently malformed. HTMLParser is tolerant,
        # and a partial signal set is more useful than discarding the page.
        pass
    candidates = rank_signup_candidates(page_url, parser.links, limit=12)
    auth_entries = rank_auth_entry_candidates(page_url, parser.links, limit=12)
    observed_candidates = [
        item for item in candidates if item.get("source") == "observed_link"]
    password_inputs = parser.password_inputs
    text = parser.body_text.lower()
    auth_terms = (
        "sign up", "signup", "register", "create account", "new account",
        "注册", "註冊", "新規登録", "회원가입",
    )
    declared_policy = parse_password_policy_texts(parser.text_snippets)
    return {
        "title": parser.title,
        "form_count": parser.form_count,
        "password_input_count": len(password_inputs),
        "new_password_input_count": sum(
            1 for item in password_inputs
            if item.get("autocomplete") == "new-password"),
        "email_input_count": parser.email_input_count,
        "phone_input_count": parser.phone_input_count,
        "signup_text_observed": any(term in text for term in auth_terms),
        "signup_candidates": candidates,
        "auth_entry_candidates": auth_entries,
        "observed_signup_candidate_count": len(observed_candidates),
        "static_password_constraints": password_inputs,
        "declared_password_policy": declared_policy,
    }


def preflight_priority(signals: Dict[str, Any]) -> int:
    """Prioritize likely measurable sites without claiming measurement."""
    score = 0
    if signals.get("new_password_input_count"):
        score += 120
    elif signals.get("password_input_count"):
        score += 75
    candidates = signals.get("signup_candidates") or []
    observed_count = int(signals.get("observed_signup_candidate_count") or 0)
    if observed_count and candidates:
        score += 35 + min(45, int(float(candidates[0].get("score") or 0) / 4))
    elif candidates:
        # Common generated paths are useful for the browser fallback, but do
        # not prove that this particular domain has accounts.
        score += 5
    if signals.get("email_input_count"):
        score += 12
    if signals.get("form_count"):
        score += 8
    if signals.get("signup_text_observed"):
        score += 10
    declared = signals.get("declared_password_policy") or {}
    if declared.get("raw_texts"):
        score += 30
    if (declared.get("length_min") or declared.get("length_max")
            or declared.get("required_classes")):
        score += 30
    return score
