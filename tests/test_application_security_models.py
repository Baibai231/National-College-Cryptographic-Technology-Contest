import unittest
from dataclasses import FrozenInstanceError

from application_security.models import (
    Evidence,
    EvidenceLevel,
    ModuleManifest,
    ResearchReference,
    ScanMode,
)


PAPER = ResearchReference(
    reference_id="paper-1",
    title="A Measurement Paper",
    venue="USENIX Security",
    year=2023,
    url="https://example.com/paper",
)


class ApplicationSecurityModelTests(unittest.TestCase):
    def test_core_manifest_requires_crypto_element(self):
        with self.assertRaises(ValueError):
            ModuleManifest(
                module_id="b.invalid",
                name_zh="无密码学对象",
                research_question="test",
                crypto_elements=(),
                paper_refs=(PAPER,),
            )

    def test_core_manifest_requires_paper(self):
        standard = ResearchReference(
            reference_id="standard-1",
            title="A Standard",
            venue="IETF",
            year=2025,
            url="https://example.com/standard",
            kind="standard",
        )
        with self.assertRaises(ValueError):
            ModuleManifest(
                module_id="b.invalid",
                name_zh="只有标准",
                research_question="test",
                crypto_elements=("digital_signature",),
                paper_refs=(standard,),
            )

    def test_manifest_serializes_scan_modes_as_strings(self):
        manifest = ModuleManifest(
            module_id="b.valid",
            name_zh="有效模块",
            research_question="test",
            crypto_elements=("digital_signature",),
            paper_refs=(PAPER,),
            safe_modes=(ScanMode.PASSIVE, ScanMode.SAFE_INTERACTION),
        )
        self.assertEqual(
            manifest.to_dict()["safe_modes"],
            ["passive", "safe_interaction"],
        )

    def test_evidence_records_are_immutable(self):
        evidence = Evidence(
            evidence_id="e1",
            source_type="browser_page_state",
            level=EvidenceLevel.OBSERVED,
            observation={"fields": ["password"]},
        )
        with self.assertRaises(FrozenInstanceError):
            evidence.level = EvidenceLevel.INFERRED


if __name__ == "__main__":
    unittest.main()
