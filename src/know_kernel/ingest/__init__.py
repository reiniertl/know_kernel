"""App 1: Ingestion service — document parsing, license scanning, LLM extraction."""

from know_kernel.ingest.parser import ParsedDocument, parse_document
from know_kernel.ingest.scanner import ArtifactClass, ContaminationLevel, ScanResult, scan_license

__all__ = [
    "ArtifactClass",
    "ContaminationLevel",
    "ParsedDocument",
    "ScanResult",
    "parse_document",
    "scan_license",
]
