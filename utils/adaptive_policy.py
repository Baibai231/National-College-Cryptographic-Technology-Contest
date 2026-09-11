"""Adaptive password-policy probes shared by inline and full-form testers.

The original measurement loop scanned every possible length from both ends.
That is expensive for full-form sites because every observation can submit a
registration form.  This module keeps an accepted password as an invariant and
uses binary search to choose the next most informative length.

Only candidate metadata is retained in the decision trace.  Candidate values
are deliberately omitted so reports stay safe to share and compare.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


ACCEPTED = "accepted"
REJECTED = "rejected"
INCONCLUSIVE = "inconclusive"


def normalize_outcome(value: Any) -> str:
    """Normalize bool/string/Enum probe results to a three-state outcome."""
    if isinstance(value, bool):
        return ACCEPTED if value else REJECTED
    raw = getattr(value, "value", value)
    text = str(raw or "").strip().lower()
    if text in {ACCEPTED, REJECTED, INCONCLUSIVE}:
        return text
    return INCONCLUSIVE


def candidate_profile(candidate: str) -> Dict[str, Any]:
    """Return non-sensitive structural metadata for one probe candidate."""
    classes = []
    if any(char.islower() for char in candidate):
        classes.append("lower")
    if any(char.isupper() for char in candidate):
        classes.append("upper")
    if any(char.isdigit() for char in candidate):
        classes.append("digit")
    if any(not char.isalnum() and not char.isspace() for char in candidate):
        classes.append("symbol")
    if any(char.isspace() for char in candidate):
        classes.append("space")
    if any(ord(char) > 127 for char in candidate):
        classes.append("unicode")
    return {
        "length": len(candidate),
        "classes": classes,
        "starts_with_letter": bool(candidate and candidate[0].isalpha()),
    }


def _take(pool: str, count: int, offset: int = 0) -> str:
    if count <= 0:
        return ""
    rotated = pool[offset % len(pool):] + pool[:offset % len(pool)]
    return (rotated * ((count // len(rotated)) + 1))[:count]


def build_length_candidate(
    length: int,
    rules: Optional[Dict[str, Any]] = None,
    template: str = "",
    variant: int = 0,
) -> Optional[str]:
    """Build an exact-length candidate while preserving known composition.

    ``None`` means the requested length cannot represent the known rules.  In
    addition to explicit minimum counts, character classes from the already
    accepted template are retained.  This keeps length as the only intended
    independent variable and reduces false boundary detections.
    """
    try:
        length = int(length)
    except (TypeError, ValueError):
        return None
    if length < 0:
        return None

    rules = rules or {}
    counts = {
        "lower": max(0, int(rules.get("r_low_min", 0) or 0)),
        "upper": max(0, int(rules.get("r_upp_min", 0) or 0)),
        "digit": max(0, int(rules.get("r_dig_min", 0) or 0)),
        "symbol": max(0, int(rules.get("r_sps_min", 0) or 0)),
    }
    symbols_allowed = not bool(rules.get("r_no_a_sps"))
    if not symbols_allowed and counts["symbol"]:
        return None

    # Preserve every class present in the accepted anchor unless a known rule
    # explicitly prohibits symbols.
    if template:
        counts["lower"] = max(counts["lower"], int(any(c.islower() for c in template)))
        counts["upper"] = max(counts["upper"], int(any(c.isupper() for c in template)))
        counts["digit"] = max(counts["digit"], int(any(c.isdigit() for c in template)))
        if symbols_allowed:
            counts["symbol"] = max(
                counts["symbol"],
                int(any(not c.isalnum() and not c.isspace() for c in template)),
            )

    four_class_requirement = next(
        (amount for amount in (4, 3, 2, 1)
         if rules.get(f"r_cmb{amount}4")),
        0,
    )
    four_classes = ["lower", "upper", "digit"]
    if symbols_allowed:
        four_classes.append("symbol")
    for name in four_classes:
        if sum(counts[item] > 0 for item in four_classes) >= four_class_requirement:
            break
        counts[name] = max(1, counts[name])
    if sum(counts[item] > 0 for item in four_classes) < four_class_requirement:
        return None

    three_class_requirement = next(
        (amount for amount in (3, 2, 1)
         if rules.get(f"r_cmb{amount}3")),
        0,
    )

    def active_three() -> int:
        return sum((
            counts["lower"] > 0 or counts["upper"] > 0,
            counts["digit"] > 0,
            counts["symbol"] > 0,
        ))

    for name in ("lower", "digit", "symbol"):
        if active_three() >= three_class_requirement:
            break
        if name == "symbol" and not symbols_allowed:
            continue
        counts[name] = max(1, counts[name])
    if active_three() < three_class_requirement:
        return None

    two_word = bool(rules.get("r_2_word"))
    if two_word:
        counts["lower"] = max(6, counts["lower"])
        separator = "symbol" if symbols_allowed else "digit"
        counts[separator] = max(1, counts[separator])
    if rules.get("r_l_start") and not (counts["lower"] or counts["upper"]):
        counts["lower"] = 1

    required = sum(counts.values())
    if required > length:
        return None
    counts["lower"] += length - required

    pools = {
        "lower": "kqmxvzptnryfbwjchudgseio",
        "upper": "KQMXVZPTNRYFBWJCHUDGSEIO",
        "digit": "7392058164",
        "symbol": "!@#$%^&*",
    }
    parts: List[str] = []
    if two_word:
        separator_name = "symbol" if symbols_allowed else "digit"
        separator_char = "!" if separator_name == "symbol" else "7"
        parts.append("kqm" + separator_char + "xvz")
        counts["lower"] -= 6
        counts[separator_name] -= 1

    # Enforce the first-character rule before adding the remaining classes.
    if rules.get("r_l_start") and not two_word:
        first_kind = "lower" if counts["lower"] else "upper"
        parts.append(_take(pools[first_kind], 1, length + variant * 7))
        counts[first_kind] -= 1

    for index, name in enumerate(("lower", "upper", "digit", "symbol")):
        parts.append(_take(
            pools[name], counts[name], length + index * 3 + variant * 7))
    candidate = "".join(parts)
    return candidate if len(candidate) == length else None


@dataclass
class BoundaryResult:
    value: Optional[int]
    status: str
    confidence: float
    searched_to: Optional[int] = None
    reason: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "value": self.value,
            "status": self.status,
            "confidence": self.confidence,
            "searched_to": self.searched_to,
            "reason": self.reason,
        }


@dataclass
class AdaptiveLengthPlanner:
    """Budgeted binary-search planner for password length boundaries."""

    probe: Callable[[str, str], Any]
    candidate_factory: Callable[[int], Optional[str]]
    accepted_anchor: str
    minimum_range: Tuple[int, int] = (0, 32)
    maximum_range: Tuple[int, int] = (6, 128)
    probe_budget: int = 24
    known_maximum: Optional[int] = None
    confirmation_factory: Optional[Callable[[int], Optional[str]]] = None
    trace: List[Dict[str, Any]] = field(default_factory=list)
    probes_used: int = 0
    _stop_reason: str = ""

    def _observe(self, phase: str, length: int,
                 bounds: Tuple[int, int]) -> str:
        if self.probes_used >= self.probe_budget:
            self._stop_reason = "probe_budget_exhausted"
            return INCONCLUSIVE
        candidate = self.candidate_factory(length)
        if candidate is None:
            self.trace.append({
                "phase": phase,
                "target_length": length,
                "outcome": "not_constructible",
                "bounds_before": list(bounds),
                "decision": "skip: known composition cannot fit this length",
            })
            return "not_constructible"

        outcome = normalize_outcome(self.probe(
            candidate, f"adaptive {phase} length={length}"))
        self.probes_used += 1
        self.trace.append({
            "probe_index": self.probes_used,
            "phase": phase,
            "target_length": length,
            "candidate": candidate_profile(candidate),
            "outcome": outcome,
            "bounds_before": list(bounds),
            "decision": "",
        })
        if outcome == INCONCLUSIVE:
            self._stop_reason = f"{phase}_probe_inconclusive_at_{length}"
        elif outcome == REJECTED and self.confirmation_factory is not None:
            self.trace[-1]["decision"] = "rejection observed; run confirmation variant"
            confirmation = self._confirm_rejection(phase, length, bounds)
            if confirmation != REJECTED:
                outcome = INCONCLUSIVE
                self._stop_reason = f"{phase}_rejection_not_confirmed_at_{length}"
        return outcome

    def _confirm_rejection(self, phase: str, length: int,
                           bounds: Tuple[int, int]) -> str:
        if self.probes_used >= self.probe_budget:
            return INCONCLUSIVE
        candidate = self.confirmation_factory(length)
        if candidate is None:
            return INCONCLUSIVE
        outcome = normalize_outcome(self.probe(
            candidate, f"adaptive {phase} confirmation length={length}"))
        self.probes_used += 1
        self.trace.append({
            "probe_index": self.probes_used,
            "phase": f"{phase}_confirmation",
            "target_length": length,
            "candidate": candidate_profile(candidate),
            "outcome": outcome,
            "bounds_before": list(bounds),
            "decision": (
                "rejection confirmed" if outcome == REJECTED
                else "conflicting or insufficient confirmation evidence"
            ),
        })
        return outcome

    def _set_decision(self, text: str) -> None:
        if self.trace:
            self.trace[-1]["decision"] = text

    def _first_constructible(self, low: int, high: int) -> Optional[int]:
        for length in range(low, high + 1):
            if self.candidate_factory(length) is not None:
                return length
        return None

    def infer(self) -> Dict[str, Any]:
        anchor_length = len(self.accepted_anchor or "")
        if self.known_maximum is not None and int(self.known_maximum) > 0:
            anchor_length = min(anchor_length, int(self.known_maximum))
        if not anchor_length:
            minimum = maximum = BoundaryResult(
                None, "inconclusive", 0.0, reason="accepted_anchor_missing")
            return self._summary(minimum, maximum)

        min_low, _configured_min_high = map(int, self.minimum_range)
        # The accepted anchor is the actual upper invariant.  Do not truncate
        # it to a historical 32-character search ceiling: modern policies can
        # legitimately require longer passwords and binary search stays cheap.
        min_high = anchor_length
        feasible_low = self._first_constructible(min_low, min_high)
        if feasible_low is None:
            minimum = BoundaryResult(
                None, "inconclusive", 0.0,
                reason="no_constructible_candidate_below_anchor")
        else:
            low, high = feasible_low, min_high
            minimum = None
            while low < high:
                middle = (low + high) // 2
                outcome = self._observe("minimum", middle, (low, high))
                if outcome == "not_constructible":
                    low = middle + 1
                    self._set_decision(f"lower bound -> {low}")
                elif outcome == ACCEPTED:
                    high = middle
                    self._set_decision(f"accepted: upper bound -> {high}")
                elif outcome == REJECTED:
                    low = middle + 1
                    self._set_decision(f"rejected: lower bound -> {low}")
                else:
                    minimum = BoundaryResult(
                        None, "inconclusive", 0.0,
                        searched_to=middle, reason=self._stop_reason)
                    break
            if minimum is None:
                minimum = BoundaryResult(
                    low, "measured", 0.98, searched_to=anchor_length,
                    reason="binary_search_with_accepted_anchor")

        if self.known_maximum is not None and int(self.known_maximum) > 0:
            maximum = BoundaryResult(
                int(self.known_maximum), "measured", 1.0,
                searched_to=int(self.known_maximum),
                reason="html_maxlength_hard_limit")
        else:
            maximum = self._infer_maximum(anchor_length)

        return self._summary(minimum, maximum)

    def _infer_maximum(self, anchor_length: int) -> BoundaryResult:
        max_high = int(self.maximum_range[1])
        if anchor_length >= max_high:
            maximum = BoundaryResult(
                None, "not_observed_within_range", 0.75,
                searched_to=anchor_length,
                reason="accepted_anchor_reaches_search_ceiling")
        else:
            top_outcome = self._observe(
                "maximum", max_high, (anchor_length, max_high))
            if top_outcome == ACCEPTED:
                self._set_decision(
                    f"accepted at search ceiling: no maximum observed through {max_high}")
                maximum = BoundaryResult(
                    None, "not_observed_within_range", 0.85,
                    searched_to=max_high,
                    reason="search_ceiling_accepted")
            elif top_outcome == INCONCLUSIVE:
                maximum = BoundaryResult(
                    None, "inconclusive", 0.0, searched_to=max_high,
                    reason=self._stop_reason)
            elif top_outcome == "not_constructible":
                maximum = BoundaryResult(
                    None, "inconclusive", 0.0, searched_to=max_high,
                    reason="search_ceiling_candidate_not_constructible")
            else:
                self._set_decision(
                    f"rejected: confirmed upper exclusive bound {max_high}")
                low, high = anchor_length, max_high
                maximum = None
                while low + 1 < high:
                    middle = (low + high) // 2
                    outcome = self._observe("maximum", middle, (low, high))
                    if outcome == ACCEPTED:
                        low = middle
                        self._set_decision(f"accepted: lower bound -> {low}")
                    elif outcome == REJECTED:
                        high = middle
                        self._set_decision(f"rejected: upper exclusive bound -> {high}")
                    else:
                        maximum = BoundaryResult(
                            None, "inconclusive", 0.0,
                            searched_to=middle, reason=self._stop_reason)
                        break
                if maximum is None:
                    maximum = BoundaryResult(
                        low, "measured", 0.98, searched_to=max_high,
                        reason="binary_search_between_accepted_and_rejected_bounds")
        return maximum

    def _summary(self, minimum: BoundaryResult,
                 maximum: BoundaryResult) -> Dict[str, Any]:
        linear_worst_case = (
            max(0, int(self.minimum_range[1]) - int(self.minimum_range[0]) + 1)
            + max(0, int(self.maximum_range[1]) - int(self.maximum_range[0]) + 1)
        )
        return {
            "engine": "adaptive-length-v1",
            "probe_budget": self.probe_budget,
            "probes_used": self.probes_used,
            "candidate_values_stored": False,
            "anchor": candidate_profile(self.accepted_anchor or ""),
            "minimum": minimum.as_dict(),
            "maximum": maximum.as_dict(),
            "worst_case_linear_probes": linear_worst_case,
            "probes_saved_vs_worst_case": max(
                0, linear_worst_case - self.probes_used),
            "stop_reason": self._stop_reason or "completed",
            "decision_trace": self.trace,
        }
