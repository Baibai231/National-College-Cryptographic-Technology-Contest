"""Normalize non-submission password-policy evidence.

The active probe engine remains the authority for a *measured* policy.  This
module captures a separate, explicitly labelled evidence tier from HTML
constraints and human-readable rule text.  It is useful when a site exposes a
password field but only validates after another registration step.
"""

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional


_POLICY_TERMS = re.compile(
    r"password|passphrase|passwd|口令|密码|密碼", re.IGNORECASE)
_RULE_TERMS = re.compile(
    r"character|letter|digit|symbol|special|uppercase|lowercase|"
    r"length|minimum|maximum|at\s+least|at\s+most|between|must|cannot|"
    r"长度|長度|位数|位數|字符|字母|数字|數字|符号|符號|至少|至多|"
    r"必须|必須|不能|不得|不允许|不允許|组合|組合",
    re.IGNORECASE,
)


def _positive_int(value: Any) -> Optional[int]:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())[:300]


def policy_like_texts(texts: Iterable[Any], limit: int = 20) -> List[str]:
    """Return de-duplicated snippets that look like password rules."""
    output: List[str] = []
    seen = set()
    for value in texts:
        text = _clean_text(value)
        if (not text or not _POLICY_TERMS.search(text)
                or not _RULE_TERMS.search(text)):
            continue
        folded = text.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        output.append(text)
        if len(output) >= limit:
            break
    return output


def parse_password_policy_texts(texts: Iterable[Any]) -> Dict[str, Any]:
    """Extract conservative multilingual hints from declared rule text.

    A hint is not an observed accept/reject result.  Ambiguous phrases are
    retained in ``raw_texts`` but do not become hard constraints.
    """
    snippets = policy_like_texts(texts)
    result: Dict[str, Any] = {
        "length_min": None,
        "length_max": None,
        "charset_hints": [],
        "required_classes": [],
        "forbidden_classes": [],
        "minimum_character_classes": None,
        "raw_texts": snippets,
    }

    minimums: List[int] = []
    maximums: List[int] = []
    required = set()
    forbidden = set()
    charset = set()

    for text in snippets:
        # Ranges: "8-64 characters", "8 至 64 位", "between 8 and 64".
        for pattern in (
            r"(?<!\d)(\d{1,3})\s*(?:-|–|—|~|～|至|到)\s*(\d{1,3})\s*(?:个?字符|位|characters?|chars?)",
            r"between\s+(\d{1,3})\s+and\s+(\d{1,3})\s+(?:characters?|chars?)",
        ):
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                minimums.append(int(match.group(1)))
                maximums.append(int(match.group(2)))
                break

        for pattern in (
            r"(?:至少|不少于|最少)\s*(\d{1,3})\s*(?:个?字符|位)",
            r"(?:at\s+least|minimum(?:\s+of)?|min\.?)\s*(\d{1,3})\s*(?:characters?|chars?)?",
            r"(\d{1,3})\s*(?:characters?|chars?)\s*(?:minimum|min\b)",
        ):
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                minimums.append(int(match.group(1)))
                break

        for pattern in (
            r"(?:至多|最多|最长|長度不得超過|不能超过|不超过)\s*(\d{1,3})\s*(?:个?字符|位)?",
            r"(?:at\s+most|maximum(?:\s+of)?|max\.?)\s*(\d{1,3})\s*(?:characters?|chars?)?",
            r"(?:no\s+more\s+than|up\s+to)\s*(\d{1,3})\s*(?:characters?|chars?)",
            r"(\d{1,3})\s*(?:characters?|chars?)\s*(?:maximum|max\b)",
        ):
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                maximums.append(int(match.group(1)))
                break

        lowered = text.casefold()
        class_patterns = {
            "upper": (r"\bupper(?:-?case)?(?:\s+letters?)?\b", r"大写", r"大寫"),
            "lower": (r"\blower(?:-?case)?(?:\s+letters?)?\b", r"小写", r"小寫"),
            "digit": (r"\bdigits?\b", r"\bnumbers?\b", r"\bnumeric(?:al)?\b", r"数字", r"數字"),
            "symbol": (r"\bsymbols?\b", r"\bspecial\s+characters?\b", r"特殊字符", r"特殊符号", r"特殊符號"),
            "letter": (r"\bletters?\b", r"字母"),
        }
        negative_pattern = re.compile(
            r"cannot|must\s+not|not\s+allowed|\bno\b|"
            r"不能|不得|禁止|不允许|不允許|不可")
        requirement_pattern = re.compile(
            r"\bmust\b|\brequir(?:e|es|ed)\b|at\s+least|"
            r"\binclud(?:e[sd]?|ing)\b|\bcontain[sd]?\b|\bneeds?\b|"
            r"必须|必須|至少|需要|包含|应含|應含")
        optional_pattern = re.compile(
            r"\bmay\b|\bcan\b|\boptional\b|\ballowed\b|"
            r"可以|可包含|允许|允許|可使用")

        def last_marker(pattern, prefix):
            matches = list(pattern.finditer(prefix))
            return matches[-1] if matches else None

        for name, patterns in class_patterns.items():
            for pattern in patterns:
                for class_match in re.finditer(pattern, lowered):
                    # In phrases such as "minimum number of 8 characters",
                    # "number" describes a quantity rather than a digit class.
                    if (name == "digit" and re.match(
                            r"numbers?\s+of\s+\d|number\s+of\s+(?:characters?|chars?|classes?|types?)",
                            lowered[class_match.start():])):
                        continue

                    charset.add(name)
                    prefix = lowered[max(0, class_match.start() - 140):class_match.start()]
                    suffix = lowered[class_match.end():class_match.end() + 40]
                    negative_marker = last_marker(negative_pattern, prefix)
                    requirement_marker = last_marker(requirement_pattern, prefix)
                    optional_marker = last_marker(optional_pattern, prefix)

                    negative_position = negative_marker.start() if negative_marker else -1
                    requirement_position = requirement_marker.start() if requirement_marker else -1
                    optional_position = optional_marker.start() if optional_marker else -1

                    # "cannot contain symbols" contains both a negative word
                    # and the otherwise-positive verb "contain".  The nearby
                    # negative still owns that verb.
                    negates_requirement = bool(
                        negative_marker and requirement_marker
                        and 0 <= requirement_position - negative_position <= 18
                    )
                    optional_requirement = bool(
                        optional_marker and requirement_marker
                        and 0 <= requirement_position - optional_position <= 12
                    )
                    forbidden_after = bool(re.match(
                        r"\s*(?:are|is)?\s*(?:not\s+allowed|forbidden|prohibited|"
                        r"不得|禁止|不允许|不允許)", suffix))

                    if (forbidden_after or negates_requirement
                            or negative_position > max(requirement_position, optional_position)):
                        forbidden.add(name)
                    elif requirement_position > optional_position and not optional_requirement:
                        required.add(name)

        classes_match = re.search(
            r"(?:at\s+least|minimum(?:\s+of)?)\s*([234])\s*(?:of|character\s+classes|types)|"
            r"至少\s*([234])\s*(?:种|種|类|類)", lowered)
        if classes_match:
            result["minimum_character_classes"] = int(
                classes_match.group(1) or classes_match.group(2))

    plausible_mins = [value for value in minimums if 1 <= value <= 256]
    plausible_maxes = [value for value in maximums if 1 <= value <= 4096]
    if plausible_mins:
        # Multiple statements can describe alternative branches.  Keep the
        # least restrictive declared lower bound and preserve all raw text.
        result["length_min"] = min(plausible_mins)
    if plausible_maxes:
        result["length_max"] = max(plausible_maxes)
    result["charset_hints"] = sorted(charset)
    result["required_classes"] = sorted(required - forbidden)
    result["forbidden_classes"] = sorted(forbidden)
    return result


def normalize_dom_constraints(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    """Build a stable, password-free DOM evidence object."""
    minimum = _positive_int(snapshot.get("minlength"))
    maximum = _positive_int(snapshot.get("maxlength"))
    pattern = _clean_text(snapshot.get("pattern"))
    validity = snapshot.get("validity")
    if not isinstance(validity, Mapping):
        validity = {}
    normalized_validity = {
        name: bool(validity.get(name))
        for name in (
            "valid", "tooShort", "tooLong", "patternMismatch",
            "customError", "valueMissing",
        )
        if name in validity
    }
    return {
        "source": "live_password_dom",
        "constraints": {
            "minlength": minimum,
            "maxlength": maximum,
            "pattern_present": bool(pattern),
            "pattern": pattern or None,
            "required": bool(snapshot.get("required")),
            "autocomplete": _clean_text(snapshot.get("autocomplete")) or None,
        },
        "native_validity": normalized_validity,
        "declared_policy": parse_password_policy_texts(
            snapshot.get("texts") or []),
    }


def has_substantive_dom_evidence(evidence: Mapping[str, Any]) -> bool:
    constraints = evidence.get("constraints") or {}
    declared = evidence.get("declared_policy") or {}
    return bool(
        constraints.get("minlength")
        or constraints.get("maxlength")
        or constraints.get("pattern_present")
        or declared.get("raw_texts")
    )
