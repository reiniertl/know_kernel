"""Tests for extract_concepts â€” ALG-KK-LLM-EXTRACT invariants."""

from __future__ import annotations

import json

import pytest

from graph.engine import add_edge, add_node
from graph.schema import init_db
from ingest.extractor import (
    CONCEPT_SCHEMA,
    EXTRACTION_SYSTEM_PROMPT,
    ExtractionResult,
    RelationshipResult,
    build_extraction_prompt,
    extract_concepts,
    store_kernel_invariant,
    store_rich_concept,
    validate_extraction_item,
    validate_invariant_item,
    wire_relationships,
)
from ingest.gate import SessionGate, SessionViolationError


class MockLLMClient:
    def __init__(self, concepts: list[dict] | None = None):
        self.concepts = concepts or [
            {
                "name": "Page Table Walking",
                "description": "A mechanism for translating virtual addresses to physical addresses by traversing a hierarchical table structure.",
                "key_properties": ["O(log n) lookup", "hardware-assisted", "hierarchical"],
                "tradeoffs": ["TLB miss penalty"],
                "design_rationale": "Hierarchical structure balances memory overhead and lookup speed.",
                "subsystem": "Virtual Memory",
                "relationships": [],
            },
            {
                "name": "Copy-on-Write",
                "description": "A resource management technique that defers duplication of shared memory pages until a write operation occurs.",
                "key_properties": ["lazy duplication", "shared pages", "write-triggered copy"],
                "tradeoffs": ["copy latency on first write"],
                "design_rationale": "Avoids unnecessary memory duplication for forked processes.",
                "subsystem": "Virtual Memory",
                "relationships": [
                    {"target": "Page Table Walking", "kind": "prerequisite", "reason": "Requires page table infrastructure for tracking shared pages."},
                ],
            },
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

    def test_extract_concepts_now_creates_belongs_to(self, conn, evidence_node):
        gate = SessionGate()
        client = MockLLMClient()
        result = extract_concepts(conn, evidence_node, gate, client=client)
        for cid in result.concept_ids:
            edge = conn.execute(
                "SELECT 1 FROM edges WHERE kind = 'belongs-to' AND source_id = ?",
                (cid,),
            ).fetchone()
            assert edge is not None, f"Concept {cid} has no belongs-to edge"

    def test_extract_concepts_subsystem_ids_populated(self, conn, evidence_node):
        gate = SessionGate()
        client = MockLLMClient()
        result = extract_concepts(conn, evidence_node, gate, client=client)
        assert len(result.subsystem_ids) > 0

    def test_extract_concepts_schema_includes_subsystem(self):
        assert "subsystem" in CONCEPT_SCHEMA["items"]["properties"]
        assert "subsystem" in CONCEPT_SCHEMA["items"]["required"]

    def test_extract_concepts_rich_end_to_end(self, conn, evidence_node):
        gate = SessionGate()
        client = MockLLMClient()
        result = extract_concepts(conn, evidence_node, gate, client=client)
        assert result.concepts_created == 2
        for cid in result.concept_ids:
            row = conn.execute("SELECT attrs FROM nodes WHERE id = ?", (cid,)).fetchone()
            attrs = json.loads(row[0])
            assert "key_properties" in attrs
            assert isinstance(attrs["key_properties"], list)
            assert len(attrs["key_properties"]) >= 1
            assert "tradeoffs" in attrs
            assert isinstance(attrs["tradeoffs"], list)
            assert "design_rationale" in attrs
            assert len(attrs["design_rationale"]) > 0
            assert attrs["artifact_class"] == "abstracted-mechanism"

    def test_extract_concepts_relationships_wired(self, conn, evidence_node):
        gate = SessionGate()
        client = MockLLMClient()
        result = extract_concepts(conn, evidence_node, gate, client=client)
        edges = conn.execute(
            "SELECT kind, source_id, target_id FROM edges WHERE kind = 'prerequisite'"
        ).fetchall()
        assert len(edges) >= 1

    def test_extract_concepts_relationships_created_count(self, conn, evidence_node):
        gate = SessionGate()
        client = MockLLMClient()
        result = extract_concepts(conn, evidence_node, gate, client=client)
        assert result.relationships_created == 1
        actual_edges = conn.execute(
            "SELECT COUNT(*) FROM edges WHERE kind IN ('refines', 'contradicts', 'prerequisite')"
        ).fetchone()[0]
        assert actual_edges == result.relationships_created


def _make_valid_item(**overrides):
    base = {
        "name": "Page Table Walking",
        "description": "A mechanism for translating virtual addresses.",
        "key_properties": ["O(log n) lookup", "hardware-assisted"],
        "tradeoffs": ["TLB miss penalty"],
        "design_rationale": "Hierarchical structure balances memory and speed.",
        "subsystem": "Virtual Memory",
    }
    base.update(overrides)
    return base


class TestValidateExtractionItem:
    def test_validate_item_valid(self):
        item = _make_valid_item()
        result = validate_extraction_item(item)
        assert result is not None
        assert result["name"] == "Page Table Walking"
        assert len(result["key_properties"]) == 2
        assert len(result["tradeoffs"]) == 1
        assert result["design_rationale"] == "Hierarchical structure balances memory and speed."
        assert result["subsystem"] == "Virtual Memory"

    def test_validate_item_missing_name(self):
        item = _make_valid_item()
        del item["name"]
        assert validate_extraction_item(item) is None

    def test_validate_item_missing_key_properties(self):
        item = _make_valid_item()
        del item["key_properties"]
        assert validate_extraction_item(item) is None

    def test_validate_item_empty_key_properties(self):
        item = _make_valid_item(key_properties=[])
        assert validate_extraction_item(item) is None

    def test_validate_item_empty_rationale(self):
        item = _make_valid_item(design_rationale="   ")
        assert validate_extraction_item(item) is None

    def test_validate_item_missing_tradeoffs(self):
        item = _make_valid_item()
        del item["tradeoffs"]
        assert validate_extraction_item(item) is None

    def test_validate_item_non_dict(self):
        assert validate_extraction_item("not a dict") is None
        assert validate_extraction_item(42) is None
        assert validate_extraction_item(None) is None

    def test_validate_item_strips_strings(self):
        item = _make_valid_item(
            name="  Page Table Walking  ",
            description="  A mechanism.  ",
            design_rationale="  Reason.  ",
        )
        result = validate_extraction_item(item)
        assert result["name"] == "Page Table Walking"
        assert result["description"] == "A mechanism."
        assert result["design_rationale"] == "Reason."

    def test_validate_item_preserves_relationships(self):
        rels = [{"target": "Copy-on-Write", "kind": "prerequisite", "reason": "needed first"}]
        item = _make_valid_item(relationships=rels)
        result = validate_extraction_item(item)
        assert result["relationships"] == rels

    def test_validate_item_empty_tradeoffs_ok(self):
        item = _make_valid_item(tradeoffs=[])
        result = validate_extraction_item(item)
        assert result is not None
        assert result["tradeoffs"] == []


class TestBuildExtractionPrompt:
    def test_build_prompt_with_text(self):
        prompt = build_extraction_prompt("This paper describes kernel mechanisms.")
        assert "This paper describes kernel mechanisms." in prompt
        assert "Extract abstract concepts" in prompt

    def test_build_prompt_empty_text(self):
        prompt = build_extraction_prompt("")
        assert "metadata only" in prompt.lower()
        assert len(prompt) > 0


class TestStoreRichConcept:
    def test_store_rich_concept_creates_node(self, conn, evidence_node):
        item = _make_valid_item()
        cid = store_rich_concept(conn, item, evidence_node)
        row = conn.execute("SELECT attrs FROM nodes WHERE id = ?", (cid,)).fetchone()
        assert row is not None
        attrs = json.loads(row[0])
        assert attrs["name"] == "Page Table Walking"
        assert attrs["description"] == "A mechanism for translating virtual addresses."
        assert attrs["key_properties"] == ["O(log n) lookup", "hardware-assisted"]
        assert attrs["tradeoffs"] == ["TLB miss penalty"]
        assert attrs["design_rationale"] == "Hierarchical structure balances memory and speed."
        assert attrs["artifact_class"] == "abstracted-mechanism"

    def test_store_rich_concept_creates_provenance(self, conn, evidence_node):
        item = _make_valid_item()
        cid = store_rich_concept(conn, item, evidence_node)
        edge = conn.execute(
            "SELECT 1 FROM edges WHERE kind = 'extracted-from' AND source_id = ? AND target_id = ?",
            (cid, evidence_node),
        ).fetchone()
        assert edge is not None

    def test_store_rich_concept_artifact_class(self, conn, evidence_node):
        item = _make_valid_item()
        cid = store_rich_concept(conn, item, evidence_node)
        row = conn.execute("SELECT attrs FROM nodes WHERE id = ?", (cid,)).fetchone()
        attrs = json.loads(row[0])
        assert attrs["artifact_class"] == "abstracted-mechanism"

    def test_store_rich_concept_returns_id(self, conn, evidence_node):
        item = _make_valid_item()
        cid = store_rich_concept(conn, item, evidence_node)
        assert cid.startswith("concept-")
        row = conn.execute("SELECT id FROM nodes WHERE id = ?", (cid,)).fetchone()
        assert row is not None
        assert row[0] == cid


def _setup_two_concepts(conn, evidence_node):
    item_a = _make_valid_item(name="Page Table Walking")
    item_b = _make_valid_item(name="Demand Paging")
    cid_a = store_rich_concept(conn, item_a, evidence_node)
    cid_b = store_rich_concept(conn, item_b, evidence_node)
    name_map = {"page table walking": cid_a, "demand paging": cid_b}
    return cid_a, cid_b, name_map


class TestWireRelationships:
    def test_wire_relationships_creates_refines_edge(self, conn, evidence_node):
        cid_a, cid_b, name_map = _setup_two_concepts(conn, evidence_node)
        concepts_data = [
            {"name": "Page Table Walking", "relationships": [
                {"target": "Demand Paging", "kind": "refines", "reason": "extends paging"}
            ]},
            {"name": "Demand Paging"},
        ]
        result = wire_relationships(conn, concepts_data, name_map)
        assert result.edges_created == 1
        edge = conn.execute(
            "SELECT 1 FROM edges WHERE kind='refines' AND source_id=? AND target_id=?",
            (cid_a, cid_b),
        ).fetchone()
        assert edge is not None

    def test_wire_relationships_creates_contradicts_edge(self, conn, evidence_node):
        cid_a, cid_b, name_map = _setup_two_concepts(conn, evidence_node)
        concepts_data = [
            {"name": "Page Table Walking", "relationships": [
                {"target": "Demand Paging", "kind": "contradicts", "reason": "conflict"}
            ]},
        ]
        result = wire_relationships(conn, concepts_data, name_map)
        assert result.edges_created == 1
        edge = conn.execute(
            "SELECT 1 FROM edges WHERE kind='contradicts' AND source_id=? AND target_id=?",
            (cid_a, cid_b),
        ).fetchone()
        assert edge is not None

    def test_wire_relationships_creates_prerequisite_edge(self, conn, evidence_node):
        cid_a, cid_b, name_map = _setup_two_concepts(conn, evidence_node)
        concepts_data = [
            {"name": "Page Table Walking", "relationships": [
                {"target": "Demand Paging", "kind": "prerequisite", "reason": "needed first"}
            ]},
        ]
        result = wire_relationships(conn, concepts_data, name_map)
        assert result.edges_created == 1

    def test_wire_relationships_skips_unknown_target(self, conn, evidence_node):
        cid_a, cid_b, name_map = _setup_two_concepts(conn, evidence_node)
        concepts_data = [
            {"name": "Page Table Walking", "relationships": [
                {"target": "Nonexistent Concept", "kind": "refines", "reason": "test"}
            ]},
        ]
        result = wire_relationships(conn, concepts_data, name_map)
        assert result.edges_created == 0
        assert result.edges_skipped == 1

    def test_wire_relationships_skips_invalid_kind(self, conn, evidence_node):
        cid_a, cid_b, name_map = _setup_two_concepts(conn, evidence_node)
        concepts_data = [
            {"name": "Page Table Walking", "relationships": [
                {"target": "Demand Paging", "kind": "depends-on", "reason": "test"}
            ]},
        ]
        result = wire_relationships(conn, concepts_data, name_map)
        assert result.edges_created == 0
        assert result.edges_skipped == 1

    def test_wire_relationships_skips_self_edge(self, conn, evidence_node):
        cid_a, cid_b, name_map = _setup_two_concepts(conn, evidence_node)
        concepts_data = [
            {"name": "Page Table Walking", "relationships": [
                {"target": "Page Table Walking", "kind": "refines", "reason": "self"}
            ]},
        ]
        result = wire_relationships(conn, concepts_data, name_map)
        assert result.edges_created == 0
        assert result.edges_skipped == 1

    def test_wire_relationships_case_insensitive(self, conn, evidence_node):
        cid_a, cid_b, name_map = _setup_two_concepts(conn, evidence_node)
        concepts_data = [
            {"name": "Page Table Walking", "relationships": [
                {"target": "Demand Paging", "kind": "refines", "reason": "test"}
            ]},
        ]
        result = wire_relationships(conn, concepts_data, name_map)
        assert result.edges_created == 1

    def test_wire_relationships_empty_relationships(self, conn, evidence_node):
        cid_a, cid_b, name_map = _setup_two_concepts(conn, evidence_node)
        concepts_data = [
            {"name": "Page Table Walking"},
            {"name": "Demand Paging"},
        ]
        result = wire_relationships(conn, concepts_data, name_map)
        assert result.edges_created == 0
        assert result.edges_skipped == 0


# --- validate_invariant_item ---


_VALID_INV = {
    "predicate": "No reader observes a partially-updated data structure",
    "strength": "safety",
    "scope": "per-operation",
    "concept_name": "Read-Copy-Update",
}


class TestValidateInvariantItem:
    def test_valid(self):
        result = validate_invariant_item(_VALID_INV)
        assert result is not None
        assert result["predicate"] == _VALID_INV["predicate"]
        assert result["strength"] == "safety"
        assert result["scope"] == "per-operation"
        assert result["concept_name"] == "Read-Copy-Update"

    def test_missing_predicate(self):
        item = {k: v for k, v in _VALID_INV.items() if k != "predicate"}
        assert validate_invariant_item(item) is None

    def test_empty_predicate(self):
        item = {**_VALID_INV, "predicate": "   "}
        assert validate_invariant_item(item) is None

    def test_invalid_strength(self):
        item = {**_VALID_INV, "strength": "critical"}
        assert validate_invariant_item(item) is None

    def test_invalid_scope(self):
        item = {**_VALID_INV, "scope": "global"}
        assert validate_invariant_item(item) is None

    def test_strips_strings(self):
        item = {
            "predicate": "  test predicate  ",
            "strength": " safety ",
            "scope": " per-object ",
            "concept_name": "  RCU  ",
        }
        result = validate_invariant_item(item)
        assert result is not None
        assert result["predicate"] == "test predicate"
        assert result["strength"] == "safety"
        assert result["scope"] == "per-object"
        assert result["concept_name"] == "RCU"

    def test_not_dict(self):
        assert validate_invariant_item("not a dict") is None

    def test_missing_concept_name(self):
        item = {k: v for k, v in _VALID_INV.items() if k != "concept_name"}
        assert validate_invariant_item(item) is None


# --- store_kernel_invariant ---


class TestStoreKernelInvariant:
    def test_creates_node(self, conn, evidence_node):
        cid = store_rich_concept(conn, {
            "name": "RCU", "description": "read-copy-update",
            "artifact_class": "B", "key_properties": ["lock-free"],
            "tradeoffs": [], "design_rationale": "Optimizes reads.",
        }, evidence_node)
        name_to_id = {"rcu": cid}
        inv_item = {
            "predicate": "No reader observes partial update",
            "strength": "safety",
            "scope": "per-operation",
            "concept_name": "RCU",
        }
        kinv_id = store_kernel_invariant(conn, inv_item, evidence_node, name_to_id)
        assert kinv_id is not None
        node = conn.execute("SELECT kind, attrs FROM nodes WHERE id = ?", (kinv_id,)).fetchone()
        assert node[0] == "KernelInvariant"
        import json
        attrs = json.loads(node[1])
        assert attrs["predicate"] == "No reader observes partial update"
        assert attrs["strength"] == "safety"
        assert attrs["scope"] == "per-operation"
        assert attrs["artifact_class"] == "abstracted-mechanism"

    def test_governed_by_edge(self, conn, evidence_node):
        cid = store_rich_concept(conn, {
            "name": "RCU", "description": "read-copy-update",
            "artifact_class": "B", "key_properties": ["lock-free"],
            "tradeoffs": [], "design_rationale": "Optimizes reads.",
        }, evidence_node)
        name_to_id = {"rcu": cid}
        inv_item = {
            "predicate": "Test", "strength": "safety",
            "scope": "per-operation", "concept_name": "RCU",
        }
        kinv_id = store_kernel_invariant(conn, inv_item, evidence_node, name_to_id)
        edge = conn.execute(
            "SELECT 1 FROM edges WHERE kind='governed-by' AND source_id=? AND target_id=?",
            (kinv_id, cid),
        ).fetchone()
        assert edge is not None

    def test_provenance_edge(self, conn, evidence_node):
        cid = store_rich_concept(conn, {
            "name": "RCU", "description": "read-copy-update",
            "artifact_class": "B", "key_properties": ["lock-free"],
            "tradeoffs": [], "design_rationale": "Optimizes reads.",
        }, evidence_node)
        name_to_id = {"rcu": cid}
        inv_item = {
            "predicate": "Test", "strength": "safety",
            "scope": "per-operation", "concept_name": "RCU",
        }
        kinv_id = store_kernel_invariant(conn, inv_item, evidence_node, name_to_id)
        edge = conn.execute(
            "SELECT 1 FROM edges WHERE kind='extracted-from' AND source_id=? AND target_id=?",
            (kinv_id, evidence_node),
        ).fetchone()
        assert edge is not None

    def test_unknown_concept_returns_none(self, conn, evidence_node):
        result = store_kernel_invariant(
            conn,
            {"predicate": "Test", "strength": "safety", "scope": "per-operation", "concept_name": "NonExistent"},
            evidence_node,
            {"rcu": "concept-123"},
        )
        assert result is None
