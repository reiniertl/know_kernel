"""App 1: Ingestion service â€” document parsing, license scanning, LLM extraction."""

from ingest.extractor import ExtractionResult, extract_concepts
from ingest.gate import SessionGate, SessionViolationError
from ingest.parser import ParsedDocument, parse_document
from ingest.reviewer import ReviewResult, review_source
from ingest.scanner import ArtifactClass, ContaminationLevel, ScanResult, scan_license

__all__ = [
    "ArtifactClass",
    "ContaminationLevel",
    "ExtractionResult",
    "ParsedDocument",
    "ReviewResult",
    "ScanResult",
    "SessionGate",
    "SessionViolationError",
    "extract_concepts",
    "parse_document",
    "review_source",
    "scan_license",
]
