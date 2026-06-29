"""Tests for scan_license â€” INV-KK-ALL-EVIDENCE-CLASS-A and INV-KK-UNKNOWN-LICENSE-L4."""

from ingest.parser import ParsedDocument
from ingest.scanner import ArtifactClass, ContaminationLevel, ScanResult, scan_license


def _doc(text: str) -> ParsedDocument:
    return ParsedDocument(text=text, metadata={}, file_type="text", page_count=1)


class TestScanLicense:
    def test_scan_mit_license(self):
        doc = _doc("Permission is hereby granted, free of charge, MIT License terms apply.")
        result = scan_license(doc)
        assert result.contamination_level == ContaminationLevel.L1
        assert "MIT" in result.licenses_found

    def test_scan_gpl_license(self):
        doc = _doc("GNU General Public License version 2 (GPL v2) applies to this file.")
        result = scan_license(doc)
        assert result.contamination_level == ContaminationLevel.L2
        assert "GPL" in result.licenses_found

    def test_scan_public_domain(self):
        doc = _doc("This work is dedicated to the public domain under CC0 1.0 Universal.")
        result = scan_license(doc)
        assert result.contamination_level == ContaminationLevel.L0
        assert any("CC0" in lic for lic in result.licenses_found)

    def test_scan_no_license(self):
        doc = _doc("This is a technical document about kernel scheduling algorithms.")
        result = scan_license(doc)
        assert result.contamination_level == ContaminationLevel.L4
        assert result.licenses_found == []

    def test_scan_always_class_a(self):
        for text in [
            "MIT License",
            "GNU General Public License",
            "CC0",
            "No license found here.",
        ]:
            result = scan_license(_doc(text))
            assert result.artifact_class == ArtifactClass.A

    def test_scan_apache_license(self):
        doc = _doc("Licensed under the Apache License, Version 2.0 (Apache-2.0).")
        result = scan_license(doc)
        assert result.contamination_level == ContaminationLevel.L1
        assert "Apache-2.0" in result.licenses_found

    def test_scan_patent_clause(self):
        doc = _doc(
            "This agreement includes a patent retaliation clause: if you assert patent "
            "claims against contributors, your patent termination rights apply."
        )
        result = scan_license(doc)
        assert result.contamination_level == ContaminationLevel.L3
        assert any("Patent" in lic for lic in result.licenses_found)

    def test_discourse_classification(self):
        """INV-KK-SCAN-DISCOURSE: discourse sources get A/L1 regardless of text."""
        doc = _doc("GNU General Public License version 2 (GPL v2) applies.")
        result = scan_license(doc, source_type="discourse")
        assert result.artifact_class == ArtifactClass.A
        assert result.contamination_level == ContaminationLevel.L1
        assert result.licenses_found == []

    def test_discourse_empty_text(self):
        """INV-KK-SCAN-DISCOURSE: discourse classification works even with empty text."""
        doc = _doc("")
        result = scan_license(doc, source_type="discourse")
        assert result.artifact_class == ArtifactClass.A
        assert result.contamination_level == ContaminationLevel.L1

    def test_non_discourse_unchanged(self):
        """Non-discourse sources still use normal license scanning."""
        doc = _doc("MIT License")
        result = scan_license(doc, source_type="paper")
        assert result.contamination_level == ContaminationLevel.L1
        assert "MIT" in result.licenses_found

    def test_none_source_type_unchanged(self):
        """None source_type falls through to normal scanning."""
        doc = _doc("MIT License")
        result = scan_license(doc, source_type=None)
        assert result.contamination_level == ContaminationLevel.L1
        assert "MIT" in result.licenses_found
