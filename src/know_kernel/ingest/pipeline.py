"""Ingestion pipeline — parse → scan → graph write (ALG-KK-INGEST-PIPELINE)."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass

from know_kernel.graph.engine import add_edge, add_node
from know_kernel.graph.rules import validate_node
from know_kernel.ingest.parser import parse_document
from know_kernel.ingest.scanner import ScanResult, scan_license


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
) -> IngestResult:
    """Ingest one document: parse → scan → write Source + Evidence to graph.

    Creates exactly one Source node, one Evidence node, and a sourced-from edge
    (INV-KK-INGEST-CREATES-EVIDENCE). Does not create Advisory nodes
    (INV-KK-INGEST-SOURCE-HAS-ADVISORY).

    Raises FileNotFoundError if file_path does not exist.
    """
    parsed = parse_document(file_path, source_type)
    scan = scan_license(parsed)

    source_id = f"src-{uuid.uuid4().hex[:12]}"
    evidence_id = f"ev-{uuid.uuid4().hex[:12]}"

    license_label = scan.licenses_found[0] if scan.licenses_found else "LicenseRef-Unknown"

    add_node(conn, source_id, "Source", {
        "url": url,
        "source_type": source_type,
        "license": license_label,
    })
    add_node(conn, evidence_id, "Evidence", {
        "artifact_class": scan.artifact_class.value,
        "contamination_level": scan.contamination_level.value,
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
