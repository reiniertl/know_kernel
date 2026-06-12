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
    store_failure_mode,
    store_interaction_protocol,
    store_kernel_invariant,
    store_performance_profile,
    store_rich_concept,
    validate_extraction_item,
    validate_failure_mode_item,
    validate_invariant_item,
    validate_performance_profile_item,
    validate_protocol_item,
    wire_relationships,
)
from ingest.gate import SessionGate, SessionViolationError


_DEFAULT_CONCEPTS = [
    {
        "name": "Page Table Walking",
        "description": "A mechanism for translating virtual addresses to physical addresses by traversing a hierarchical table structure.",
        "key_properties": ["O(log n) lookup", "hardware-assisted", "hierarchical"],
        "tradeoffs": ["TLB miss penalty"],
        "design_rationale": "Hierarchical structure balances memory overhead and lookup speed.",
        "subsystem": "Virtual Memory",
        "relationships": [],
        "invariants": [
            {"predicate": "Every virtual address resolves to at most one physical frame", "strength": "safety", "scope": "per-operation", "failure_modes": [
                {"symptom": "Multiple physical frames mapped to same virtual address", "blast_radius": "kernel-wide", "recoverability": "data-loss"},
            ]},
        ],
        "performance_profiles": [
            {
                "metric": "translation latency",
                "complexity": "O(log n)",
                "best_case": "TLB hit returns in 1 cycle",
                "worst_case": "Full 4-level walk on TLB miss",
                "typical_case": "TLB hit rate above 99%",
                "conditions": "Under normal workload with warm TLB",
            },
        ],
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
        "invariants": [
            {"predicate": "Shared pages remain unmodified until copy is triggered", "strength": "safety", "scope": "per-object", "failure_modes": [
                {"symptom": "Data corruption from concurrent write to shared page", "blast_radius": "subsystem", "recoverability": "data-loss"},
            ]},
            {"predicate": "Reference count is decremented after copy completes", "strength": "structural", "scope": "per-object", "failure_modes": []},
        ],
        "performance_profiles": [],
    },
]

_DEFAULT_PROTOCOLS = [
    {
        "rule": "Page table must be walked before copy-on-write fault can be resolved",
        "ordering": "before",
        "violation_mode": "Copy-on-write handler cannot determine physical page without translation",
        "concept_a": "Page Table Walking",
        "concept_b": "Copy-on-Write",
    },
]


class MockLLMClient:
    def __init__(self, concepts: list[dict] | None = None, protocols: list[dict] | None = None):
        self.concepts = concepts if concepts is not None else _DEFAULT_CONCEPTS
        self.protocols = protocols if protocols is not None else _DEFAULT_PROTOCOLS
        self.calls: list[dict] = []

    def create_message(self, model: str, system: str, user: str, max_tokens: int) -> dict:
        self.calls.append({"model": model, "system": system, "user": user})
        return {
            "text": json.dumps({"concepts": self.concepts, "interaction_protocols": self.protocols}),
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
        assert result2.concepts_skipped >= 2
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


# --- E2E: extract_concepts with invariants ---


class TestExtractConceptsInvariants:
    def test_invariants_end_to_end(self, conn, evidence_node):
        gate = SessionGate()
        result = extract_concepts(conn, evidence_node, gate, client=MockLLMClient())
        assert result.invariants_created == 3
        kinv_nodes = conn.execute(
            "SELECT id, attrs FROM nodes WHERE kind = 'KernelInvariant'"
        ).fetchall()
        assert len(kinv_nodes) == 3
        attrs = json.loads(kinv_nodes[0][1])
        assert "predicate" in attrs
        assert attrs["artifact_class"] == "abstracted-mechanism"
        assert attrs["strength"] in {"safety", "structural"}

    def test_invariant_governed_by(self, conn, evidence_node):
        gate = SessionGate()
        extract_concepts(conn, evidence_node, gate, client=MockLLMClient())
        governed_edges = conn.execute(
            "SELECT source_id, target_id FROM edges WHERE kind = 'governed-by'"
        ).fetchall()
        assert len(governed_edges) == 3
        concept_ids = {r[1] for r in governed_edges}
        for cid in concept_ids:
            node = conn.execute("SELECT kind FROM nodes WHERE id = ?", (cid,)).fetchone()
            assert node[0] == "Concept"

    def test_invariants_created_count(self, conn, evidence_node):
        gate = SessionGate()
        result = extract_concepts(conn, evidence_node, gate, client=MockLLMClient())
        actual = conn.execute("SELECT COUNT(*) FROM nodes WHERE kind = 'KernelInvariant'").fetchone()[0]
        assert result.invariants_created == actual


# --- validate_failure_mode_item ---


_VALID_FM = {
    "symptom": "Data corruption visible to concurrent readers",
    "blast_radius": "kernel-wide",
    "recoverability": "data-loss",
}


class TestValidateFailureModeItem:
    def test_valid(self):
        result = validate_failure_mode_item(_VALID_FM)
        assert result is not None
        assert result["symptom"] == _VALID_FM["symptom"]
        assert result["blast_radius"] == "kernel-wide"
        assert result["recoverability"] == "data-loss"

    def test_missing_symptom(self):
        item = {k: v for k, v in _VALID_FM.items() if k != "symptom"}
        assert validate_failure_mode_item(item) is None

    def test_empty_symptom(self):
        item = {**_VALID_FM, "symptom": "   "}
        assert validate_failure_mode_item(item) is None

    def test_invalid_blast_radius(self):
        item = {**_VALID_FM, "blast_radius": "global"}
        assert validate_failure_mode_item(item) is None

    def test_invalid_recoverability(self):
        item = {**_VALID_FM, "recoverability": "fixable"}
        assert validate_failure_mode_item(item) is None

    def test_strips_strings(self):
        item = {"symptom": "  deadlock  ", "blast_radius": " subsystem ", "recoverability": " self-healing "}
        result = validate_failure_mode_item(item)
        assert result is not None
        assert result["symptom"] == "deadlock"
        assert result["blast_radius"] == "subsystem"
        assert result["recoverability"] == "self-healing"

    def test_not_dict(self):
        assert validate_failure_mode_item("not a dict") is None


# --- store_failure_mode ---


class TestStoreFailureMode:
    def test_creates_node(self, conn, evidence_node):
        cid = store_rich_concept(conn, {
            "name": "RCU", "description": "read-copy-update",
            "artifact_class": "B", "key_properties": ["lock-free"],
            "tradeoffs": [], "design_rationale": "Optimizes reads.",
        }, evidence_node)
        kinv_id = store_kernel_invariant(conn, {
            "predicate": "Test", "strength": "safety",
            "scope": "per-operation", "concept_name": "RCU",
        }, evidence_node, {"rcu": cid})
        fm_id = store_failure_mode(conn, {
            "symptom": "Data corruption", "blast_radius": "kernel-wide",
            "recoverability": "data-loss",
        }, evidence_node, kinv_id)
        node = conn.execute("SELECT kind, attrs FROM nodes WHERE id = ?", (fm_id,)).fetchone()
        assert node[0] == "FailureMode"
        attrs = json.loads(node[1])
        assert attrs["symptom"] == "Data corruption"
        assert attrs["artifact_class"] == "abstracted-mechanism"

    def test_triggered_by_edge(self, conn, evidence_node):
        cid = store_rich_concept(conn, {
            "name": "RCU", "description": "read-copy-update",
            "artifact_class": "B", "key_properties": ["lock-free"],
            "tradeoffs": [], "design_rationale": "Optimizes reads.",
        }, evidence_node)
        kinv_id = store_kernel_invariant(conn, {
            "predicate": "Test", "strength": "safety",
            "scope": "per-operation", "concept_name": "RCU",
        }, evidence_node, {"rcu": cid})
        fm_id = store_failure_mode(conn, {
            "symptom": "Deadlock", "blast_radius": "subsystem",
            "recoverability": "requires-restart",
        }, evidence_node, kinv_id)
        edge = conn.execute(
            "SELECT 1 FROM edges WHERE kind='triggered-by' AND source_id=? AND target_id=?",
            (fm_id, kinv_id),
        ).fetchone()
        assert edge is not None


# --- E2E: extract_concepts with failure modes ---


class TestExtractConceptsFailureModes:
    def test_failure_modes_end_to_end(self, conn, evidence_node):
        gate = SessionGate()
        result = extract_concepts(conn, evidence_node, gate, client=MockLLMClient())
        assert result.failure_modes_created == 2
        fm_nodes = conn.execute("SELECT COUNT(*) FROM nodes WHERE kind = 'FailureMode'").fetchone()[0]
        assert fm_nodes == 2
        triggered_edges = conn.execute("SELECT COUNT(*) FROM edges WHERE kind = 'triggered-by'").fetchone()[0]
        assert triggered_edges == 2


# --- validate_protocol_item ---


_VALID_PROTO = {
    "rule": "Page table must be walked before CoW fault resolution",
    "ordering": "before",
    "violation_mode": "CoW handler cannot resolve without translation",
    "concept_a": "Page Table Walking",
    "concept_b": "Copy-on-Write",
}
_PROTO_NAME_MAP = {"page table walking": "c1", "copy-on-write": "c2"}


class TestValidateProtocolItem:
    def test_valid(self):
        result = validate_protocol_item(_VALID_PROTO, _PROTO_NAME_MAP)
        assert result is not None
        assert result["rule"] == _VALID_PROTO["rule"]
        assert result["ordering"] == "before"

    def test_invalid_ordering(self):
        item = {**_VALID_PROTO, "ordering": "concurrent"}
        assert validate_protocol_item(item, _PROTO_NAME_MAP) is None

    def test_unknown_concept(self):
        item = {**_VALID_PROTO, "concept_a": "Unknown Mechanism"}
        assert validate_protocol_item(item, _PROTO_NAME_MAP) is None

    def test_same_concept_rejected(self):
        item = {**_VALID_PROTO, "concept_b": "Page Table Walking"}
        assert validate_protocol_item(item, _PROTO_NAME_MAP) is None

    def test_missing_rule(self):
        item = {k: v for k, v in _VALID_PROTO.items() if k != "rule"}
        assert validate_protocol_item(item, _PROTO_NAME_MAP) is None

    def test_not_dict(self):
        assert validate_protocol_item("not a dict", _PROTO_NAME_MAP) is None


# --- store_interaction_protocol ---


class TestStoreInteractionProtocol:
    def test_creates_node(self, conn, evidence_node):
        cid_a = store_rich_concept(conn, {
            "name": "PTW", "description": "page table walking",
            "artifact_class": "B", "key_properties": ["hierarchical"],
            "tradeoffs": [], "design_rationale": "Efficient translation.",
        }, evidence_node)
        cid_b = store_rich_concept(conn, {
            "name": "CoW", "description": "copy-on-write",
            "artifact_class": "B", "key_properties": ["lazy duplication"],
            "tradeoffs": [], "design_rationale": "Avoids unnecessary copies.",
        }, evidence_node)
        name_to_id = {"ptw": cid_a, "cow": cid_b}
        proto_id = store_interaction_protocol(conn, {
            "rule": "Walk before fault", "ordering": "before",
            "violation_mode": "Cannot resolve", "concept_a": "PTW", "concept_b": "CoW",
        }, evidence_node, name_to_id)
        assert proto_id is not None
        node = conn.execute("SELECT kind, attrs FROM nodes WHERE id = ?", (proto_id,)).fetchone()
        assert node[0] == "InteractionProtocol"
        attrs = json.loads(node[1])
        assert attrs["rule"] == "Walk before fault"
        assert attrs["artifact_class"] == "abstracted-mechanism"

    def test_two_constrains_composition_edges(self, conn, evidence_node):
        cid_a = store_rich_concept(conn, {
            "name": "PTW", "description": "page table walking",
            "artifact_class": "B", "key_properties": ["hierarchical"],
            "tradeoffs": [], "design_rationale": "Efficient translation.",
        }, evidence_node)
        cid_b = store_rich_concept(conn, {
            "name": "CoW", "description": "copy-on-write",
            "artifact_class": "B", "key_properties": ["lazy duplication"],
            "tradeoffs": [], "design_rationale": "Avoids unnecessary copies.",
        }, evidence_node)
        name_to_id = {"ptw": cid_a, "cow": cid_b}
        proto_id = store_interaction_protocol(conn, {
            "rule": "Walk before fault", "ordering": "before",
            "violation_mode": "", "concept_a": "PTW", "concept_b": "CoW",
        }, evidence_node, name_to_id)
        edges = conn.execute(
            "SELECT target_id FROM edges WHERE kind='constrains-composition' AND source_id=?",
            (proto_id,),
        ).fetchall()
        assert len(edges) == 2
        targets = {r[0] for r in edges}
        assert cid_a in targets
        assert cid_b in targets

    def test_provenance_edge(self, conn, evidence_node):
        cid_a = store_rich_concept(conn, {
            "name": "PTW", "description": "page table walking",
            "artifact_class": "B", "key_properties": ["hierarchical"],
            "tradeoffs": [], "design_rationale": "Efficient translation.",
        }, evidence_node)
        cid_b = store_rich_concept(conn, {
            "name": "CoW", "description": "copy-on-write",
            "artifact_class": "B", "key_properties": ["lazy duplication"],
            "tradeoffs": [], "design_rationale": "Avoids unnecessary copies.",
        }, evidence_node)
        name_to_id = {"ptw": cid_a, "cow": cid_b}
        proto_id = store_interaction_protocol(conn, {
            "rule": "Walk before fault", "ordering": "before",
            "violation_mode": "", "concept_a": "PTW", "concept_b": "CoW",
        }, evidence_node, name_to_id)
        edge = conn.execute(
            "SELECT 1 FROM edges WHERE kind='extracted-from' AND source_id=? AND target_id=?",
            (proto_id, evidence_node),
        ).fetchone()
        assert edge is not None


# --- E2E: extract_concepts with protocols ---


class TestExtractConceptsProtocols:
    def test_protocols_end_to_end(self, conn, evidence_node):
        gate = SessionGate()
        result = extract_concepts(conn, evidence_node, gate, client=MockLLMClient())
        assert result.protocols_created == 1
        proto_nodes = conn.execute("SELECT COUNT(*) FROM nodes WHERE kind = 'InteractionProtocol'").fetchone()[0]
        assert proto_nodes == 1
        cc_edges = conn.execute("SELECT COUNT(*) FROM edges WHERE kind = 'constrains-composition'").fetchone()[0]
        assert cc_edges == 2


# --- validate_performance_profile_item ---


_VALID_PROFILE = {
    "metric": "read latency",
    "complexity": "O(1)",
    "best_case": "Single atomic read with no contention",
    "worst_case": "Grace period extends to milliseconds under heavy load",
    "typical_case": "Sub-microsecond reads in common workloads",
    "conditions": "Under normal read-heavy workload with infrequent updates",
}


class TestValidatePerformanceProfileItem:
    def test_validate_profile_valid(self):
        result = validate_performance_profile_item(_VALID_PROFILE)
        assert result is not None
        assert result["metric"] == "read latency"
        assert result["complexity"] == "O(1)"
        assert result["best_case"] == "Single atomic read with no contention"
        assert result["worst_case"] == "Grace period extends to milliseconds under heavy load"
        assert result["typical_case"] == "Sub-microsecond reads in common workloads"
        assert result["conditions"] == "Under normal read-heavy workload with infrequent updates"

    def test_validate_profile_missing_metric(self):
        item = {k: v for k, v in _VALID_PROFILE.items() if k != "metric"}
        assert validate_performance_profile_item(item) is None

    def test_validate_profile_empty_metric(self):
        item = {**_VALID_PROFILE, "metric": "   "}
        assert validate_performance_profile_item(item) is None

    def test_validate_profile_missing_complexity(self):
        item = {k: v for k, v in _VALID_PROFILE.items() if k != "complexity"}
        assert validate_performance_profile_item(item) is None

    def test_validate_profile_missing_cases(self):
        for case_field in ("best_case", "worst_case", "typical_case"):
            item = {k: v for k, v in _VALID_PROFILE.items() if k != case_field}
            assert validate_performance_profile_item(item) is None, f"Should reject missing {case_field}"

    def test_validate_profile_empty_conditions(self):
        item = {**_VALID_PROFILE, "conditions": ""}
        assert validate_performance_profile_item(item) is None

    def test_validate_profile_not_dict(self):
        assert validate_performance_profile_item("not a dict") is None
        assert validate_performance_profile_item(None) is None

    def test_validate_profile_strips_strings(self):
        item = {k: f"  {v}  " for k, v in _VALID_PROFILE.items()}
        result = validate_performance_profile_item(item)
        assert result is not None
        assert result["metric"] == "read latency"
        assert result["complexity"] == "O(1)"


# --- store_performance_profile ---


class TestStorePerformanceProfile:
    def test_store_profile_creates_node(self, conn, evidence_node):
        cid = store_rich_concept(conn, {
            "name": "RCU", "description": "read-copy-update",
            "artifact_class": "B", "key_properties": ["lock-free"],
            "tradeoffs": [], "design_rationale": "Optimizes reads.",
        }, evidence_node)
        name_to_id = {"rcu": cid}
        profile_id = store_performance_profile(
            conn, _VALID_PROFILE, evidence_node, name_to_id, "RCU",
        )
        assert profile_id is not None
        node = conn.execute("SELECT kind, attrs FROM nodes WHERE id = ?", (profile_id,)).fetchone()
        assert node[0] == "PerformanceProfile"
        attrs = json.loads(node[1])
        assert attrs["metric"] == "read latency"
        assert attrs["complexity"] == "O(1)"
        assert attrs["best_case"] == "Single atomic read with no contention"
        assert attrs["worst_case"] == "Grace period extends to milliseconds under heavy load"
        assert attrs["typical_case"] == "Sub-microsecond reads in common workloads"
        assert attrs["conditions"] == "Under normal read-heavy workload with infrequent updates"
        assert attrs["artifact_class"] == "abstracted-mechanism"

    def test_store_profile_profiled_by_edge(self, conn, evidence_node):
        cid = store_rich_concept(conn, {
            "name": "RCU", "description": "read-copy-update",
            "artifact_class": "B", "key_properties": ["lock-free"],
            "tradeoffs": [], "design_rationale": "Optimizes reads.",
        }, evidence_node)
        name_to_id = {"rcu": cid}
        profile_id = store_performance_profile(
            conn, _VALID_PROFILE, evidence_node, name_to_id, "RCU",
        )
        edge = conn.execute(
            "SELECT 1 FROM edges WHERE kind='profiled-by' AND source_id=? AND target_id=?",
            (profile_id, cid),
        ).fetchone()
        assert edge is not None

    def test_store_profile_provenance_edge(self, conn, evidence_node):
        cid = store_rich_concept(conn, {
            "name": "RCU", "description": "read-copy-update",
            "artifact_class": "B", "key_properties": ["lock-free"],
            "tradeoffs": [], "design_rationale": "Optimizes reads.",
        }, evidence_node)
        name_to_id = {"rcu": cid}
        profile_id = store_performance_profile(
            conn, _VALID_PROFILE, evidence_node, name_to_id, "RCU",
        )
        edge = conn.execute(
            "SELECT 1 FROM edges WHERE kind='extracted-from' AND source_id=? AND target_id=?",
            (profile_id, evidence_node),
        ).fetchone()
        assert edge is not None

    def test_store_profile_unknown_concept(self, conn, evidence_node):
        result = store_performance_profile(
            conn, _VALID_PROFILE, evidence_node,
            {"rcu": "concept-123"}, "NonExistent",
        )
        assert result is None
        nodes = conn.execute("SELECT COUNT(*) FROM nodes WHERE kind = 'PerformanceProfile'").fetchone()[0]
        assert nodes == 0


# --- E2E: extract_concepts with profiles ---


class TestExtractConceptsProfiles:
    def test_extract_concepts_with_profiles_e2e(self, conn, evidence_node):
        gate = SessionGate()
        result = extract_concepts(conn, evidence_node, gate, client=MockLLMClient())
        assert result.profiles_created == 1
        profile_nodes = conn.execute("SELECT COUNT(*) FROM nodes WHERE kind = 'PerformanceProfile'").fetchone()[0]
        assert profile_nodes == 1
        profiled_edges = conn.execute("SELECT COUNT(*) FROM edges WHERE kind = 'profiled-by'").fetchone()[0]
        assert profiled_edges == 1
        prov_edges = conn.execute(
            "SELECT COUNT(*) FROM edges WHERE kind = 'extracted-from' AND source_id IN (SELECT id FROM nodes WHERE kind = 'PerformanceProfile')"
        ).fetchone()[0]
        assert prov_edges == 1
        profile_node = conn.execute("SELECT attrs FROM nodes WHERE kind = 'PerformanceProfile'").fetchone()
        attrs = json.loads(profile_node[0])
        assert attrs["artifact_class"] == "abstracted-mechanism"
        assert attrs["metric"] == "translation latency"
