"""Ingestion pipeline â€” parse â†’ scan â†’ graph write (ALG-KK-INGEST-PIPELINE)."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass

from graph.engine import add_edge, add_node
from graph.rules import validate_node
from ingest.gate import SessionGate
from ingest.parser import parse_document
from ingest.scanner import ArtifactClass, ScanResult, scan_license


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
    """Ingest one document: parse â†’ scan â†’ write Source + Evidence to graph.

    Creates exactly one Source node, one Evidence node, and a sourced-from edge
    (INV-KK-INGEST-CREATES-EVIDENCE). Does not create Advisory nodes
    (INV-KK-INGEST-SOURCE-HAS-ADVISORY).

    Raises FileNotFoundError if file_path does not exist.
    """
    parsed = parse_document(file_path, source_type)
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
    description = parsed.text[:120].strip() if parsed.text else ""
    add_node(conn, evidence_id, "Evidence", {
        "artifact_class": scan.artifact_class.value,
        "contamination_level": scan.contamination_level.value,
        "description": description,
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
