"""Shared evidence models for B-layer authentication measurements.

The old classifier stores free-form evidence strings and ``high/medium/low``
confidence. New modules use explicit evidence levels and immutable records.
They can coexist while the project migrates incrementally.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, Tuple


class ScanMode(str, Enum):
    """Maximum interaction authority granted to a measurement."""

    PASSIVE = "passive"
    SAFE_INTERACTION = "safe_interaction"
    AUTHORIZED_ACCOUNT = "authorized_account"


class EvidenceLevel(str, Enum):
    """How directly a conclusion is supported by captured evidence."""

    VERIFIED = "verified"
    OBSERVED = "observed"
    INFERRED = "inferred"
    DOCUMENTED = "documented"
    UNKNOWN = "unknown"


class Verdict(str, Enum):
    PASS = "pass"
    WEAK = "weak"
    FAIL = "fail"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class ResearchReference:
    """A paper or standard supporting a detector's research method."""

    reference_id: str
    title: str
    venue: str
    year: int
    url: str
    kind: str = "paper"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModuleManifest:
    """Admission contract for a B-layer detector.

    Core detectors must declare both a cryptographic element and a paper.
    Standards may supplement a paper but cannot replace it in the competition
    core.
    """

    module_id: str
    name_zh: str
    research_question: str
    crypto_elements: Tuple[str, ...]
    paper_refs: Tuple[ResearchReference, ...]
    standard_refs: Tuple[ResearchReference, ...] = ()
    safe_modes: Tuple[ScanMode, ...] = (ScanMode.PASSIVE,)
    limitations: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.module_id.strip():
            raise ValueError("module_id must not be empty")
        if not self.crypto_elements:
            raise ValueError("core module must declare a cryptographic element")
        if not any(ref.kind == "paper" for ref in self.paper_refs):
            raise ValueError("core module must cite at least one paper")

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["safe_modes"] = [mode.value for mode in self.safe_modes]
        return data


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    source_type: str
    level: EvidenceLevel
    observation: Dict[str, Any]
    captured_at: str = ""
    artifact_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["level"] = self.level.value
        return data


@dataclass(frozen=True)
class Claim:
    metric_id: str
    crypto_property: str
    verdict: Verdict
    value: Any
    evidence_ids: Tuple[str, ...]
    paper_ref_ids: Tuple[str, ...]
    standard_ref_ids: Tuple[str, ...] = ()
    limitations: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["verdict"] = self.verdict.value
        return data


@dataclass(frozen=True)
class ModuleResult:
    module_id: str
    schema_version: str
    scan_mode: ScanMode
    claims: Tuple[Claim, ...] = ()
    evidence: Tuple[Evidence, ...] = ()
    errors: Tuple[str, ...] = ()
    limitations: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "module_id": self.module_id,
            "schema_version": self.schema_version,
            "scan_mode": self.scan_mode.value,
            "claims": [item.to_dict() for item in self.claims],
            "evidence": [item.to_dict() for item in self.evidence],
            "errors": list(self.errors),
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True)
class AuthNode:
    node_id: str
    kind: str
    label_zh: str
    entry_kind: str = ""
    step: int = 0
    url: str = ""
    evidence_level: EvidenceLevel = EvidenceLevel.OBSERVED
    attributes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["evidence_level"] = self.evidence_level.value
        return data


@dataclass(frozen=True)
class AuthEdge:
    source: str
    target: str
    relation: str
    evidence_level: EvidenceLevel = EvidenceLevel.OBSERVED
    action: str = ""

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["evidence_level"] = self.evidence_level.value
        return data


@dataclass(frozen=True)
class AuthGraph:
    """Multi-route authentication view derived from legacy state sequences."""

    target: str
    schema_version: str = "auth-graph-1.0"
    nodes: Tuple[AuthNode, ...] = ()
    edges: Tuple[AuthEdge, ...] = ()
    evidence: Tuple[Evidence, ...] = ()
    paper_ref_ids: Tuple[str, ...] = ()
    limitations: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target": self.target,
            "schema_version": self.schema_version,
            "nodes": [item.to_dict() for item in self.nodes],
            "edges": [item.to_dict() for item in self.edges],
            "evidence": [item.to_dict() for item in self.evidence],
            "paper_ref_ids": list(self.paper_ref_ids),
            "limitations": list(self.limitations),
        }
