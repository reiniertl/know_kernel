"""App 1: Ingestion service — document parsing, license scanning, LLM extraction."""

from know_kernel.ingest.parser import ParsedDocument, parse_document

__all__ = ["ParsedDocument", "parse_document"]
