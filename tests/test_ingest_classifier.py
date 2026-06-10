"""Tests for classifier.py — ALG-KK-CLASSIFY-RESOLVE-SUBSYSTEM,
ALG-KK-CLASSIFY-PARSE-LLM invariants."""

from __future__ import annotations

import json

import pytest

from graph.engine import add_node
from graph.schema import init_db
from ingest.classifier import (
    ClassificationResult,
    parse_classification_labels,
    resolve_subsystem,
)


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "test.db")


# --- resolve_subsystem tests (INV-KK-CLASSIFY-USES-EXISTING, INV-KK-CLASSIFY-SUBSYSTEM-HAS-NAME) ---


def test_resolve_existing_subsystem_reuses(conn):
    add_node(conn, "sub-vm", "Subsystem", {"name": "Virtual Memory"})
    result = resolve_subsystem(conn, "virtual memory")
    assert result == "sub-vm"
    count = conn.execute("SELECT COUNT(*) FROM nodes WHERE kind = 'Subsystem'").fetchone()[0]
    assert count == 1


def test_resolve_existing_subsystem_case_insensitive(conn):
    add_node(conn, "sub-sched", "Subsystem", {"name": "Scheduler"})
    assert resolve_subsystem(conn, "SCHEDULER") == "sub-sched"
    assert resolve_subsystem(conn, "scheduler") == "sub-sched"
    assert resolve_subsystem(conn, "  Scheduler  ") == "sub-sched"


def test_resolve_new_subsystem_creates(conn):
    result = resolve_subsystem(conn, "Scheduler")
    assert result.startswith("sub-")
    node = conn.execute(
        "SELECT attrs FROM nodes WHERE id = ?", (result,)
    ).fetchone()
    assert node is not None
    attrs = json.loads(node[0])
    assert attrs["name"] == "Scheduler"


def test_resolve_new_subsystem_strips_whitespace(conn):
    result = resolve_subsystem(conn, "  Filesystem  ")
    node = conn.execute(
        "SELECT attrs FROM nodes WHERE id = ?", (result,)
    ).fetchone()
    attrs = json.loads(node[0])
    assert attrs["name"] == "Filesystem"


def test_resolve_empty_label_raises(conn):
    with pytest.raises(ValueError, match="non-empty"):
        resolve_subsystem(conn, "")


def test_resolve_whitespace_label_raises(conn):
    with pytest.raises(ValueError, match="non-empty"):
        resolve_subsystem(conn, "   ")


# --- parse_classification_labels tests (ALG-KK-CLASSIFY-PARSE-LLM) ---


def test_parse_labels_extracts_subsystem():
    concepts_data = [
        {"name": "Page Tables", "description": "...", "subsystem": "Virtual Memory"},
        {"name": "CFS", "description": "...", "subsystem": "Scheduler"},
    ]
    concept_ids = ["c-1", "c-2"]
    result = parse_classification_labels(concepts_data, concept_ids)
    assert result == {"c-1": "Virtual Memory", "c-2": "Scheduler"}


def test_parse_labels_handles_missing_subsystem():
    concepts_data = [
        {"name": "Page Tables", "description": "..."},
    ]
    concept_ids = ["c-1"]
    result = parse_classification_labels(concepts_data, concept_ids)
    assert result == {"c-1": "Unclassified"}


def test_parse_labels_handles_empty_subsystem():
    concepts_data = [
        {"name": "Page Tables", "description": "...", "subsystem": ""},
        {"name": "CFS", "description": "...", "subsystem": "   "},
    ]
    concept_ids = ["c-1", "c-2"]
    result = parse_classification_labels(concepts_data, concept_ids)
    assert result == {"c-1": "Unclassified", "c-2": "Unclassified"}


def test_parse_labels_length_mismatch_more_data():
    concepts_data = [
        {"name": "A", "subsystem": "VM"},
        {"name": "B", "subsystem": "Sched"},
        {"name": "C", "subsystem": "FS"},
    ]
    concept_ids = ["c-1", "c-2"]
    result = parse_classification_labels(concepts_data, concept_ids)
    assert result == {"c-1": "VM", "c-2": "Sched"}
    assert len(result) == 2


def test_parse_labels_length_mismatch_fewer_data():
    concepts_data = [
        {"name": "A", "subsystem": "VM"},
    ]
    concept_ids = ["c-1", "c-2", "c-3"]
    result = parse_classification_labels(concepts_data, concept_ids)
    assert result == {"c-1": "VM", "c-2": "Unclassified", "c-3": "Unclassified"}


# --- ClassificationResult dataclass ---


def test_classification_result_dataclass():
    cr = ClassificationResult(
        concept_subsystem_map={"c-1": "sub-vm"},
        subsystems_created=1,
        subsystems_reused=0,
    )
    assert cr.concept_subsystem_map == {"c-1": "sub-vm"}
    assert cr.subsystems_created == 1
    assert cr.subsystems_reused == 0
