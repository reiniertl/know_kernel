"""Ingestion pipeline -- parse -> classify -> scan -> graph write (ALG-KK-INGEST-PIPELINE)."""

from __future__ import annotations

import logging
import sqlite3
import uuid
from dataclasses import dataclass

from graph.engine import add_edge, add_node
from graph.rules import validate_node
from ingest.gate import SessionGate
from ingest.parser import parse_document
from ingest.scanner import ArtifactClass, ScanResult, scan_license
from ingest.validate_sources import classify_content

log = logging.getLogger(__name__)

# Ceiling on the document text stored on an Evidence node. Operator decision,
# 2026-09-17, recorded by INV-KK-INGEST-CREATES-EVIDENCE.
#
# It bounds two costs at once. Storage: full document text on every Evidence
# across thousands of documents — the existing 3,325 text-bearing nodes are feed
# EXCERPTS with a median of 1,360 characters and already account for 6.6 MB of a
# 26 MB database, and a parsed paper is an order of magnitude larger than an
# excerpt. And request size: select_input hands whatever it finds straight to the
# model without truncating, so an unbounded node is an unbounded prompt.
#
# 50,000 characters is roughly 12,500 tokens and holds a typical paper close to
# whole; the p99 of what is already stored is 31,500, so nothing in the current
# corpus would have been cut. MIN_INPUT_CHARS is 100, so the floor is never in
# danger.
MAX_EVIDENCE_TEXT_CHARS = 50_000


@dataclass
class IngestResult:
    source_id: str
    evidence_id: str
    scan_result: ScanResult
    text_length: int
    file_type: str


def ingest_document(
    conn: sqlite3.Connection,
    file_path: str,
    url: str,
    source_type: str,
    gate: SessionGate | None = None,
) -> IngestResult:
    """Ingest one document: parse -> scan -> write Source + Evidence to graph.

    Creates exactly one Source node, one Evidence node, and a sourced-from edge
    (INV-KK-INGEST-CREATES-EVIDENCE). Does not create Advisory nodes
    (INV-KK-INGEST-SOURCE-HAS-ADVISORY).

    Raises FileNotFoundError if file_path does not exist.
    """
    parsed = parse_document(file_path, source_type)

    # Content sufficiency gate (INV-KK-INGEST-REJECTS-STUB, INV-KK-INGEST-REJECTS-DIRECTORY)
    classification = classify_content(parsed.text)
    if classification.classification in ("stub", "directory"):
        refs_info = ""
        if classification.kernel_doc_refs:
            refs_info = f" Kernel-doc refs: {classification.kernel_doc_refs}."
        raise ValueError(
            f"Source content is non-substantive ({classification.classification}). "
            f"Word count: {classification.word_count}.{refs_info} "
            f"Provide a URL to substantive content instead."
        )
    if classification.classification == "thin":
        log.warning(
            "Thin content for %s (%d words) -- ingesting but flagging for review",
            file_path, classification.word_count,
        )

    scan = scan_license(parsed)

    if gate is not None and scan.artifact_class is ArtifactClass.A:
        gate.record_class_a_access()

    source_id = f"src-{uuid.uuid4().hex[:12]}"
    evidence_id = f"ev-{uuid.uuid4().hex[:12]}"

    license_label = scan.licenses_found[0] if scan.licenses_found else "LicenseRef-Unknown"

    add_node(conn, source_id, "Source", {
        "url": url,
        "source_type": source_type,
        "license": license_label,
    })
    # description is the short label; text is what a later extractor reads.
    # BOTH are written and neither substitutes for the other: an earlier revision
    # stored description alone, which meant select_input found no usable basis and
    # ALG-KK-SUMMARY-EXTRACT skipped every document ingested through this path.
    # src/ingest/feed.py:85 has always written both and is the precedent.
    description = parsed.text[:120].strip() if parsed.text else ""
    add_node(conn, evidence_id, "Evidence", {
        "artifact_class": scan.artifact_class.value,
        "contamination_level": scan.contamination_level.value,
        "description": description,
        "text": parsed.text[:MAX_EVIDENCE_TEXT_CHARS] if parsed.text else "",
    })
    add_edge(conn, "sourced-from", evidence_id, source_id)

    violations = validate_node(conn, evidence_id, "Evidence")
    if violations:
        raise RuntimeError(
            f"Evidence node {evidence_id} failed validation: "
            + "; ".join(v.message for v in violations)
        )

    return IngestResult(
        source_id=source_id,
        evidence_id=evidence_id,
        scan_result=scan,
        text_length=len(parsed.text),
        file_type=parsed.file_type,
    )
