"""App 1: Ingestion service — document parsing, license scanning, LLM extraction."""

from know_kernel.ingest.gate import SessionGate, SessionViolationError
from know_kernel.ingest.parser import ParsedDocument, parse_document
from know_kernel.ingest.reviewer import ReviewResult, review_source
from know_kernel.ingest.scanner import ArtifactClass, ContaminationLevel, ScanResult, scan_license

__all__ = [
    "ArtifactClass",
    "ContaminationLevel",
    "ParsedDocument",
    "ReviewResult",
    "ScanResult",
    "SessionGate",
    "SessionViolationError",
    "parse_document",
    "review_source",
    "scan_license",
]
