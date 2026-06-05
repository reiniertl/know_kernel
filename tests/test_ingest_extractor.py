"""Tests for extract_concepts — ALG-KK-LLM-EXTRACT invariants."""

from __future__ import annotations

import json

import pytest

from know_kernel.graph.engine import add_edge, add_node
from know_kernel.graph.schema import init_db
from know_kernel.ingest.extractor import (
    EXTRACTION_SYSTEM_PROMPT,
    ExtractionResult,
    extract_concepts,
)
from know_kernel.ingest.gate import SessionGate, SessionViolationError


class MockLLMClient:
    def __init__(self, concepts: list[dict] | None = None):
        self.concepts = concepts or [
            {"name": "Page Table Walking", "description": "A mechanism for translating virtual addresses to physical addresses by traversing a hierarchical table structure."},
            {"name": "Copy-on-Write", "description": "A resource management technique that defers duplication of shared memory pages until a write operation occurs."},
        ]
        self.calls: list[dict] = []

    def create_message(self, model: str, system: str, user: str, max_tokens: int) -> dict:
        self.calls.append({"model": model, "system": system, "user": user})
        return {
            "text": json.dumps(self.concepts),
            "prompt_tokens": 100,
            "response_tokens": 50,
        }


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "test.db")


@pytest.fixture
def evidence_node(conn):
    add_node(conn, "src-ext1", "Source", {
        "url": "https://example.com/paper.txt",
        "source_type": "paper",
        "license": "MIT",
    })
    add_node(conn, "ev-ext1", "Evidence", {
        "artifact_class": "licensed-evidence",
        "contamination_level": "weak-copyleft",
        "text": "This paper describes page table walking and copy-on-write mechanisms in modern kernels.",
    })
    add_edge(conn, "sourced-from", "ev-ext1", "src-ext1")
    return "ev-ext1"


class TestExtractConcepts:
    def test_successful_extraction_creates_class_b_concepts(self, conn, evidence_node):
        gate = SessionGate()
        client = MockLLMClient()
        result = extract_concepts(conn, evidence_node, gate, client=client)
        assert isinstance(result, ExtractionResult)
        assert result.concepts_created == 2
        assert len(result.concept_ids) == 2
        for cid in result.concept_ids:
            row = conn.execute("SELECT attrs FROM nodes WHERE id = ?", (cid,)).fetchone()
            attrs = json.loads(row[0])
            assert attrs["artifact_class"] == "abstracted-mechanism"

    def test_each_concept_has_extracted_from_edge(self, conn, evidence_node):
        gate = SessionGate()
        client = MockLLMClient()
        result = extract_concepts(conn, evidence_node, gate, client=client)
        for cid in result.concept_ids:
            edge = conn.execute(
                "SELECT 1 FROM edges WHERE kind = 'extracted-from' AND source_id = ? AND target_id = ?",
                (cid, evidence_node),
            ).fetchone()
            assert edge is not None

    def test_session_gate_enforced(self, conn, evidence_node):
        gate = SessionGate()
        gate.record_proposal()
        client = MockLLMClient()
        with pytest.raises(SessionViolationError):
            extract_concepts(conn, evidence_node, gate, client=client)

    def test_idempotent_second_call_skips(self, conn, evidence_node):
        gate = SessionGate()
        client = MockLLMClient()
        result1 = extract_concepts(conn, evidence_node, gate, client=client)
        assert result1.concepts_created == 2
        result2 = extract_concepts(conn, evidence_node, gate, client=client)
        assert result2.concepts_created == 0
        assert result2.concepts_skipped == 2
        assert len(client.calls) == 1

    def test_system_prompt_contains_anti_verbatim(self):
        assert "NEVER quote verbatim" in EXTRACTION_SYSTEM_PROMPT
        assert "NEVER copy sentences" in EXTRACTION_SYSTEM_PROMPT
        assert "abstract" in EXTRACTION_SYSTEM_PROMPT.lower()

    def test_nonexistent_evidence_raises(self, conn):
        gate = SessionGate()
        client = MockLLMClient()
        with pytest.raises(ValueError, match="does not exist"):
            extract_concepts(conn, "ev-nonexistent", gate, client=client)

    def test_dry_run_returns_prompt_no_api_call(self, conn, evidence_node):
        gate = SessionGate()
        client = MockLLMClient()
        result = extract_concepts(conn, evidence_node, gate, dry_run=True, client=client)
        assert result.concepts_created == 0
        assert result.prompt_tokens > 0
        assert len(client.calls) == 0

    def test_extraction_model_recorded(self, conn, evidence_node):
        gate = SessionGate()
        client = MockLLMClient()
        result = extract_concepts(conn, evidence_node, gate, model="test-model", client=client)
        assert result.extraction_model == "test-model"
