"""Adaptive password-policy probes shared by inline and full-form testers.

The original measurement loop scanned every possible length and mutated
character classes in a fixed order.  That is expensive for full-form sites and
cannot distinguish symmetric N-of-M rules from individually required classes.
This module keeps an accepted password as an invariant, uses binary search for
numeric boundaries, and explores the character-class subset lattice.

Only candidate metadata is retained in the decision trace.  Candidate values
are deliberately omitted so reports stay safe to share and compare.
"""

from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple


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


CHARACTER_CLASSES = ("lower", "upper", "digit", "symbol")
_CLASS_POOLS = {
    "lower": "kqmxvzptnryfbwjchudgseio",
    "upper": "KQMXVZPTNRYFBWJCHUDGSEIO",
    "digit": "7392058164",
    "symbol": "!@#$%^&*",
}


def _character_class(char: str) -> Optional[str]:
    if char.islower():
        return "lower"
    if char.isupper():
        return "upper"
    if char.isdigit():
        return "digit"
    if not char.isalnum() and not char.isspace():
        return "symbol"
    return None


def character_class_counts(candidate: str) -> Dict[str, int]:
    """Count the four policy character classes in an ASCII probe."""
    counts = {name: 0 for name in CHARACTER_CLASSES}
    for char in candidate or "":
        kind = _character_class(char)
        if kind in counts:
            counts[kind] += 1
    return counts


def build_class_subset_candidate(
    length: int,
    classes: Sequence[str],
    rules: Optional[Dict[str, Any]] = None,
    variant: int = 0,
    template: str = "",
) -> Optional[str]:
    """Build a fixed-length candidate containing exactly ``classes``.

    The function deliberately returns ``None`` when a known structural rule
    cannot be represented by the requested subset.  Such a subset is omitted
    from inference rather than being counted as a policy rejection.
    """
    try:
        length = int(length)
    except (TypeError, ValueError):
        return None
    if length <= 0:
        return None

    rules = rules or {}
    requested = tuple(
        name for name in CHARACTER_CLASSES if name in set(classes or ()))
    if not requested:
        return None
    if rules.get("r_no_a_sps") and "symbol" in requested:
        return None

    letter_classes = [name for name in requested if name in ("lower", "upper")]
    if rules.get("r_l_start") and not letter_classes:
        return None

    template_counts = character_class_counts(template)
    counts = {
        name: (
            max(1, template_counts.get(name, 0)) if name in requested else 0
        )
        for name in CHARACTER_CLASSES
    }
    prefix = ""
    if rules.get("r_2_word"):
        separators = [name for name in requested if name in ("digit", "symbol")]
        if not letter_classes or not separators or length < 7:
            return None
        letter = letter_classes[variant % len(letter_classes)]
        separator = separators[variant % len(separators)]
        left = _take(_CLASS_POOLS[letter], 3, variant * 5)
        middle = _take(_CLASS_POOLS[separator], 1, variant * 3)
        right = _take(_CLASS_POOLS[letter], 3, variant * 7 + 3)
        prefix = left + middle + right
        counts[letter] = max(0, counts[letter] - 6)
        counts[separator] = max(0, counts[separator] - 1)

    required = len(prefix) + sum(max(0, value) for value in counts.values())
    if required > length:
        return None

    # Put all remaining capacity into a requested class.  Prefer a letter so
    # letter-start candidates remain natural and less likely to trip unrelated
    # anti-pattern checks.
    filler = next(
        (name for name in ("lower", "upper", "digit", "symbol")
         if name in requested),
        None,
    )
    if filler is None:
        return None
    counts[filler] += length - required

    parts: List[str] = [prefix]
    if rules.get("r_l_start") and not prefix:
        first = letter_classes[variant % len(letter_classes)]
        parts.append(_take(_CLASS_POOLS[first], 1, variant * 7))
        counts[first] -= 1
    for index, name in enumerate(CHARACTER_CLASSES):
        parts.append(_take(
            _CLASS_POOLS[name], max(0, counts[name]),
            length + index * 5 + variant * 11,
        ))
    candidate = "".join(parts)
    if len(candidate) != length:
        return None
    if set(candidate_profile(candidate)["classes"]) != set(requested):
        return None
    return candidate


def build_class_count_candidate(
    template: str,
    target_class: str,
    target_count: int,
    rules: Optional[Dict[str, Any]] = None,
    variant: int = 0,
) -> Optional[str]:
    """Reduce one class count in an accepted template without changing length.

    All removed characters are replaced with another class already present in
    the template.  Consequently the target count is the only intended policy
    variable; the candidate never introduces a new character class.
    """
    if target_class not in CHARACTER_CLASSES or not template:
        return None
    try:
        target_count = int(target_count)
    except (TypeError, ValueError):
        return None
    counts = character_class_counts(template)
    current = counts[target_class]
    if target_count < 0 or target_count > current:
        return None
    if target_count == current:
        return template

    rules = rules or {}
    # A generic character replacement cannot prove that an arbitrary site's
    # passphrase/word-boundary condition was preserved.  Keep a conservative
    # lower bound instead of attributing that rejection to the class count.
    if rules.get("r_2_word"):
        return None
    recipients = [
        name for name in CHARACTER_CLASSES
        if name != target_class and counts[name] > 0
        and not (name == "symbol" and rules.get("r_no_a_sps"))
    ]
    if not recipients:
        return None

    chars = list(template)
    target_positions = [
        index for index, char in enumerate(chars)
        if _character_class(char) == target_class
    ]
    keep = set(target_positions[:target_count])
    # When the target is the starting letter class, retain position zero if it
    # can be retained.  For target_count=0 another existing letter must replace
    # it, otherwise the known structural rule is no longer controlled.
    if rules.get("r_l_start") and target_positions and target_positions[0] == 0:
        if target_count == 0 and not any(
                name in ("lower", "upper") for name in recipients):
            return None

    replace_positions = [index for index in target_positions if index not in keep]
    for offset, position in enumerate(replace_positions):
        choices = recipients
        if position == 0 and rules.get("r_l_start"):
            choices = [name for name in recipients if name in ("lower", "upper")]
            if not choices:
                return None
        recipient = choices[(offset + variant) % len(choices)]
        chars[position] = _take(
            _CLASS_POOLS[recipient], 1, position + variant * 13)
    candidate = "".join(chars)
    return candidate if character_class_counts(candidate)[target_class] == target_count else None


@dataclass
class AdaptiveCompositionPlanner:
    """Infer character-class constraints with a bounded subset lattice.

    First, all constructible subsets are tested by increasing cardinality.  At
    the first cardinality that contains accepted candidates, the complete level
    is retained so symmetric N-of-M rules and asymmetric required classes stay
    distinguishable.  Only classes shared by every accepted minimal set are
    then eligible for a count-boundary search.
    """

    probe: Callable[[str, str], Any]
    accepted_anchor: str
    structural_rules: Optional[Dict[str, Any]] = None
    probe_budget: int = 24
    trace: List[Dict[str, Any]] = field(default_factory=list)
    probes_used: int = 0
    _stop_reason: str = ""

    def _universe(self) -> List[str]:
        universe = list(CHARACTER_CLASSES)
        if (self.structural_rules or {}).get("r_no_a_sps"):
            universe.remove("symbol")
        return universe

    def _append_observation(
        self, phase: str, candidate: str, outcome: str, **metadata: Any
    ) -> None:
        item = {
            "probe_index": self.probes_used,
            "phase": phase,
            "candidate": candidate_profile(candidate),
            "outcome": outcome,
            "decision": "",
        }
        item.update(metadata)
        self.trace.append(item)

    def _observe_subset(self, classes: Tuple[str, ...]) -> str:
        anchor_classes = tuple(
            name for name in CHARACTER_CLASSES
            if character_class_counts(self.accepted_anchor).get(name, 0) > 0
        )
        if set(classes) == set(anchor_classes):
            self.trace.append({
                "phase": "class_subset",
                "target_classes": list(classes),
                "candidate": candidate_profile(self.accepted_anchor),
                "outcome": ACCEPTED,
                "decision": "accepted anchor invariant; no additional probe",
            })
            return ACCEPTED
        if self.probes_used >= self.probe_budget:
            self._stop_reason = "probe_budget_exhausted"
            return INCONCLUSIVE
        candidate = build_class_subset_candidate(
            len(self.accepted_anchor), classes, self.structural_rules,
            template=self.accepted_anchor,
        )
        if candidate is None:
            self.trace.append({
                "phase": "class_subset",
                "target_classes": list(classes),
                "outcome": "not_constructible",
                "decision": "skip: known structural rules cannot fit this subset",
            })
            return "not_constructible"
        outcome = normalize_outcome(self.probe(
            candidate, "adaptive composition subset={}".format("+".join(classes))))
        self.probes_used += 1
        self._append_observation(
            "class_subset", candidate, outcome,
            target_classes=list(classes),
        )
        if outcome == INCONCLUSIVE:
            self._stop_reason = "class_subset_probe_inconclusive_at_{}".format(
                "+".join(classes))
        return outcome

    def _observe_count(self, target_class: str, count: int) -> str:
        if self.probes_used >= self.probe_budget:
            self._stop_reason = "probe_budget_exhausted"
            return INCONCLUSIVE
        candidate = build_class_count_candidate(
            self.accepted_anchor, target_class, count,
            self.structural_rules,
        )
        if candidate is None:
            return "not_constructible"
        outcome = normalize_outcome(self.probe(
            candidate,
            f"adaptive composition {target_class} minimum candidate={count}",
        ))
        self.probes_used += 1
        self._append_observation(
            "class_minimum", candidate, outcome,
            target_class=target_class, target_count=count,
        )
        if outcome == INCONCLUSIVE:
            self._stop_reason = (
                f"{target_class}_minimum_probe_inconclusive_at_{count}")
        return outcome

    def _infer_required_minimum(self, target_class: str) -> Dict[str, Any]:
        accepted_count = character_class_counts(
            self.accepted_anchor).get(target_class, 0)
        if accepted_count <= 0:
            return {
                "value": None, "status": "inconclusive", "confidence": 0.0,
                "reason": "required_class_missing_from_accepted_anchor",
            }
        if accepted_count == 1:
            return {
                "value": 1, "status": "measured", "confidence": 0.96,
                "reason": "absence_rejected_and_single_occurrence_anchor_accepted",
            }

        low, high = 1, accepted_count
        while low < high:
            middle = (low + high) // 2
            outcome = self._observe_count(target_class, middle)
            if outcome == ACCEPTED:
                high = middle
                self.trace[-1]["decision"] = f"accepted: upper bound -> {high}"
            elif outcome == REJECTED:
                low = middle + 1
                self.trace[-1]["decision"] = f"rejected: lower bound -> {low}"
            elif outcome == "not_constructible":
                return {
                    "value": 1, "status": "lower_bound_only", "confidence": 0.72,
                    "reason": "count_mutation_not_constructible",
                }
            else:
                return {
                    "value": None, "status": "inconclusive", "confidence": 0.0,
                    "reason": self._stop_reason,
                }
        return {
            "value": low, "status": "measured", "confidence": 0.94,
            "reason": "binary_search_with_accepted_anchor",
        }

    def infer(self) -> Dict[str, Any]:
        universe = self._universe()
        anchor_profile = candidate_profile(self.accepted_anchor or "")
        anchor_classes = [
            name for name in universe if name in anchor_profile["classes"]
        ]
        if not self.accepted_anchor or not anchor_classes:
            self._stop_reason = "accepted_anchor_missing_or_unclassified"
            return self._summary(
                universe, None, [], [], {}, "inconclusive")

        accepted_sets: List[List[str]] = []
        minimum_classes: Optional[int] = None
        for size in range(1, len(universe) + 1):
            level_accepted: List[List[str]] = []
            level_had_constructible = False
            for subset in combinations(universe, size):
                outcome = self._observe_subset(subset)
                if outcome == "not_constructible":
                    continue
                level_had_constructible = True
                if outcome == INCONCLUSIVE:
                    return self._summary(
                        universe, None, [], [], {}, "inconclusive")
                if outcome == ACCEPTED:
                    level_accepted.append(list(subset))
            if level_accepted:
                minimum_classes = size
                accepted_sets = level_accepted
                if self.trace:
                    self.trace[-1]["decision"] = (
                        f"first accepted lattice level={size}; stop larger subsets")
                break
            if not level_had_constructible:
                continue

        if minimum_classes is None:
            self._stop_reason = self._stop_reason or "no_accepted_subset_observed"
            return self._summary(
                universe, None, [], [], {}, "inconclusive")

        required = set(accepted_sets[0])
        for accepted in accepted_sets[1:]:
            required.intersection_update(accepted)
        required_classes = [name for name in universe if name in required]

        minima: Dict[str, Dict[str, Any]] = {}
        for name in universe:
            if name in required_classes:
                minima[name] = self._infer_required_minimum(name)
            else:
                minima[name] = {
                    "value": 0,
                    "status": "not_individually_required",
                    "confidence": 0.92,
                    "reason": "absent_from_at_least_one_accepted_minimal_set",
                }
        overall = (
            "partial" if any(item["status"] in {
                "inconclusive", "lower_bound_only"} for item in minima.values())
            else "measured"
        )
        self._stop_reason = self._stop_reason or (
            "class_minimum_partially_identified"
            if overall == "partial" else "completed")
        return self._summary(
            universe, minimum_classes, accepted_sets,
            required_classes, minima, overall)

    def _summary(
        self,
        universe: List[str],
        minimum_classes: Optional[int],
        accepted_sets: List[List[str]],
        required_classes: List[str],
        minima: Dict[str, Dict[str, Any]],
        status: str,
    ) -> Dict[str, Any]:
        return {
            "engine": "adaptive-composition-v1",
            "status": status,
            "confidence": {
                "measured": 0.94,
                "partial": 0.72,
                "inconclusive": 0.0,
            }.get(status, 0.0),
            "probe_budget": self.probe_budget,
            "probes_used": self.probes_used,
            "candidate_values_stored": False,
            "anchor": candidate_profile(self.accepted_anchor or ""),
            "universe": universe,
            "minimum_character_classes": minimum_classes,
            "accepted_minimal_sets": accepted_sets,
            "required_classes": required_classes,
            "class_minimums": minima,
            "structural_conditions": {
                "letter_start": bool((self.structural_rules or {}).get("r_l_start")),
                "two_word": bool((self.structural_rules or {}).get("r_2_word")),
                "symbols_prohibited": bool(
                    (self.structural_rules or {}).get("r_no_a_sps")),
            },
            "assumptions": [
                "character-class acceptance is monotonic at a fixed length",
                "the accepted anchor remains valid during this probe phase",
            ],
            "stop_reason": self._stop_reason or "completed",
            "decision_trace": self.trace,
        }


def apply_composition_to_restrictive(
    restrictive: Dict[str, Any], summary: Dict[str, Any]
) -> Dict[str, Any]:
    """Project rich composition evidence onto the legacy policy fields."""
    class_fields = {
        "lower": "r_low_min",
        "upper": "r_upp_min",
        "digit": "r_dig_min",
        "symbol": "r_sps_min",
    }
    for name, field_name in class_fields.items():
        item = (summary.get("class_minimums") or {}).get(name) or {}
        value = item.get("value")
        restrictive[field_name] = (
            int(value) if item.get("status") == "measured" and value is not None
            else 0
        )
    for key in (
        "r_cmb13", "r_cmb23", "r_cmb33",
        "r_cmb14", "r_cmb24", "r_cmb34", "r_cmb44",
    ):
        restrictive[key] = False
    minimum_classes = summary.get("minimum_character_classes")
    if summary.get("status") in {"measured", "partial"} and minimum_classes in (1, 2, 3, 4):
        restrictive[f"r_cmb{minimum_classes}4"] = True
    return restrictive


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
