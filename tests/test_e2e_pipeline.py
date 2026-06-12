"""E2E integration test â€” INV-KK-E2E-PIPELINE-SOUND.

Verifies the full pipeline: ingest â†’ review â†’ extract â†’ export â†’ MCP verify.
Uses a mock LLM client to avoid real API calls.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from graph.engine import add_node
from graph.schema import init_db
from export.exporter import export_class_b_snapshot
from ingest.extractor import extract_concepts
from ingest.gate import SessionGate, SessionViolationError
from ingest.pipeline import ingest_document
from ingest.reviewer import review_source
from mcp_server.server import init_snapshot


class MockLLMClient:
    def create_message(self, model: str, system: str, user: str, max_tokens: int) -> dict:
        return {
            "text": json.dumps({
                "concepts": [
                    {
                        "name": "Virtual Address Translation",
                        "description": "A mechanism that maps process-specific virtual addresses to physical memory locations through a hierarchical lookup structure.",
                        "key_properties": ["hierarchical lookup", "hardware-assisted", "per-process isolation"],
                        "tradeoffs": ["TLB miss penalty"],
                        "design_rationale": "Indirection through page tables enables per-process address isolation without physical memory fragmentation.",
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
                        "name": "Demand Paging",
                        "description": "A lazy loading strategy that defers page allocation until the first access, reducing memory footprint for large address spaces.",
                        "key_properties": ["lazy allocation", "page fault driven", "reduced memory footprint"],
                        "tradeoffs": ["page fault latency on first access"],
                        "design_rationale": "Deferred allocation avoids wasting physical memory on unused virtual pages.",
                        "subsystem": "Virtual Memory",
                        "relationships": [
                            {"target": "Virtual Address Translation", "kind": "prerequisite", "reason": "Requires address translation infrastructure for page fault handling."},
                        ],
                        "invariants": [
                            {"predicate": "No page fault occurs for an already-resident page", "strength": "performance", "scope": "per-operation", "failure_modes": [
                                {"symptom": "Spurious page fault on resident page degrades throughput", "blast_radius": "local", "recoverability": "self-healing"},
                            ]},
                        ],
                        "performance_profiles": [],
                    },
                ],
                "interaction_protocols": [
                    {
                        "rule": "Address translation must complete before page fault resolution",
                        "ordering": "before",
                        "violation_mode": "Page fault handler cannot resolve without translated address",
                        "concept_a": "Virtual Address Translation",
                        "concept_b": "Demand Paging",
                    },
                ],
                "compatibility_assessments": [
                    {
                        "synergy": "synergistic",
                        "rationale": "Demand paging relies on virtual address translation for page fault resolution",
                        "conditions": "When both operate in the same virtual memory subsystem",
                        "concept_a": "Virtual Address Translation",
                        "concept_b": "Demand Paging",
                    },
                ],
            }),
            "prompt_tokens": 100,
            "response_tokens": 50,
        }


@pytest.fixture
def master_db(tmp_path):
    return tmp_path / "master.db"


@pytest.fixture
def snapshot_db(tmp_path):
    return tmp_path / "snapshot.db"


class TestE2EPipeline:
    def test_full_pipeline_produces_class_b_only(self, master_db, snapshot_db):
        """INV-KK-E2E-PIPELINE-SOUND: full pipeline, zero Class A leakage."""
        conn = init_db(master_db)

        # Step 1: Ingest
        doc = master_db.parent / "test_doc.txt"
        doc.write_text("MIT License. This paper describes virtual memory management and demand paging in modern kernels.")
        gate = SessionGate()
        ingest_result = ingest_document(conn, str(doc), "https://example.com/vm.txt", "paper", gate=gate)
        assert gate.is_extraction_mode

        # Step 2: Review
        review_result = review_source(
            conn, ingest_result.source_id,
            "License confirmed as MIT. No restrictions on concept extraction.",
            "weak-copyleft",
        )
        assert review_result.advisory_id.startswith("adv-")

        # Step 3: Extract (mock LLM)
        extract_result = extract_concepts(
            conn, ingest_result.evidence_id, gate,
            model="test-model", client=MockLLMClient(),
        )
        assert extract_result.concepts_created == 2
        assert all(cid.startswith("concept-") for cid in extract_result.concept_ids)

        # Auto-classification creates belongs-to edges — verify
        for cid in extract_result.concept_ids:
            edge = conn.execute(
                "SELECT 1 FROM edges WHERE kind = 'belongs-to' AND source_id = ?",
                (cid,),
            ).fetchone()
            assert edge is not None, f"Concept {cid} missing belongs-to edge"

        conn.commit()

        # Step 4: Export
        report = export_class_b_snapshot(master_db, snapshot_db)

        # Step 5: Verify snapshot contents â€” Class B only
        snap_conn = sqlite3.connect(str(snapshot_db))
        kinds = [row[0] for row in snap_conn.execute("SELECT DISTINCT kind FROM nodes").fetchall()]
        assert "Evidence" not in kinds
        assert "Source" not in kinds
        assert "Advisory" not in kinds
        assert "Concept" in kinds

        concept_count = snap_conn.execute("SELECT COUNT(*) FROM nodes WHERE kind = 'Concept'").fetchone()[0]
        assert concept_count == 2

        for row in snap_conn.execute("SELECT attrs FROM nodes WHERE kind = 'Concept'").fetchall():
            attrs = json.loads(row[0])
            assert attrs["artifact_class"] == "abstracted-mechanism"
            assert "key_properties" in attrs
            assert isinstance(attrs["key_properties"], list)
            assert len(attrs["key_properties"]) >= 1
            assert "design_rationale" in attrs

        kinv_count = snap_conn.execute("SELECT COUNT(*) FROM nodes WHERE kind = 'KernelInvariant'").fetchone()[0]
        assert kinv_count == 2

        governed_edges = snap_conn.execute(
            "SELECT COUNT(*) FROM edges WHERE kind = 'governed-by'"
        ).fetchone()[0]
        assert governed_edges == 2

        fm_count = snap_conn.execute("SELECT COUNT(*) FROM nodes WHERE kind = 'FailureMode'").fetchone()[0]
        assert fm_count == 2

        triggered_edges = snap_conn.execute(
            "SELECT COUNT(*) FROM edges WHERE kind = 'triggered-by'"
        ).fetchone()[0]
        assert triggered_edges == 2

        proto_count = snap_conn.execute("SELECT COUNT(*) FROM nodes WHERE kind = 'InteractionProtocol'").fetchone()[0]
        assert proto_count == 1

        cc_edges = snap_conn.execute("SELECT COUNT(*) FROM edges WHERE kind = 'constrains-composition'").fetchone()[0]
        assert cc_edges == 2

        profile_count = snap_conn.execute("SELECT COUNT(*) FROM nodes WHERE kind = 'PerformanceProfile'").fetchone()[0]
        assert profile_count == 1

        profiled_edges = snap_conn.execute("SELECT COUNT(*) FROM edges WHERE kind = 'profiled-by'").fetchone()[0]
        assert profiled_edges == 1

        for row in snap_conn.execute("SELECT attrs FROM nodes WHERE kind = 'PerformanceProfile'").fetchall():
            attrs = json.loads(row[0])
            assert attrs["artifact_class"] == "abstracted-mechanism"
            assert attrs["metric"] == "translation latency"

        compat_count = snap_conn.execute("SELECT COUNT(*) FROM nodes WHERE kind = 'CompatibilityAssessment'").fetchone()[0]
        assert compat_count == 1

        ac_edges = snap_conn.execute("SELECT COUNT(*) FROM edges WHERE kind = 'assesses-compatibility'").fetchone()[0]
        assert ac_edges == 2

        for row in snap_conn.execute("SELECT attrs FROM nodes WHERE kind = 'CompatibilityAssessment'").fetchall():
            attrs = json.loads(row[0])
            assert attrs["artifact_class"] == "abstracted-mechanism"
            assert attrs["synergy"] == "synergistic"

        snap_conn.close()

        # Step 6: MCP init validates Class B-only
        init_snapshot(str(snapshot_db))

    def test_session_gate_blocks_cross_mode(self, master_db):
        """SessionGate prevents proposal-mode sessions from accessing Class A."""
        conn = init_db(master_db)
        doc = master_db.parent / "test_doc2.txt"
        doc.write_text("MIT License. Some content about process scheduling.")

        gate = SessionGate()
        gate.record_proposal()

        with pytest.raises(SessionViolationError):
            ingest_document(conn, str(doc), "https://example.com/sched.txt", "paper", gate=gate)

    def test_extraction_gate_blocks_proposal_mode(self, master_db):
        """SessionGate prevents proposal-mode from extracting."""
        conn = init_db(master_db)
        doc = master_db.parent / "test_doc3.txt"
        doc.write_text("MIT License. Content about IPC mechanisms.")

        ingest_gate = SessionGate()
        result = ingest_document(conn, str(doc), "https://example.com/ipc.txt", "paper", gate=ingest_gate)
        conn.commit()

        proposal_gate = SessionGate()
        proposal_gate.record_proposal()

        with pytest.raises(SessionViolationError):
            extract_concepts(conn, result.evidence_id, proposal_gate, client=MockLLMClient())

    def test_export_excludes_all_class_a_kinds(self, master_db, snapshot_db):
        """Snapshot contains zero Evidence, Source, or Advisory nodes."""
        conn = init_db(master_db)
        doc = master_db.parent / "test_doc4.txt"
        doc.write_text("Apache License Version 2.0. Filesystem journaling techniques.")

        gate = SessionGate()
        ingest_result = ingest_document(conn, str(doc), "https://example.com/fs.txt", "paper", gate=gate)
        review_source(conn, ingest_result.source_id, "Apache 2.0 confirmed.", "weak-copyleft")
        extract_result = extract_concepts(
            conn, ingest_result.evidence_id, gate,
            client=MockLLMClient(),
        )
        conn.commit()

        export_class_b_snapshot(master_db, snapshot_db)

        snap_conn = sqlite3.connect(str(snapshot_db))
        forbidden = snap_conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE kind IN ('Evidence', 'Source', 'Advisory')"
        ).fetchone()[0]
        assert forbidden == 0

        class_b = snap_conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE kind = 'Concept'"
        ).fetchone()[0]
        assert class_b == 2
        snap_conn.close()

    def test_extraction_idempotent_in_pipeline(self, master_db):
        """Re-extraction from same Evidence skips â€” no duplicates."""
        conn = init_db(master_db)
        doc = master_db.parent / "test_doc5.txt"
        doc.write_text("MIT License. Scheduler design patterns.")

        gate = SessionGate()
        result = ingest_document(conn, str(doc), "https://example.com/sched.txt", "paper", gate=gate)
        conn.commit()

        client = MockLLMClient()
        r1 = extract_concepts(conn, result.evidence_id, gate, client=client)
        assert r1.concepts_created == 2

        r2 = extract_concepts(conn, result.evidence_id, gate, client=client)
        assert r2.concepts_created == 0
        assert r2.concepts_skipped >= 2

    def test_advisory_edge_present_after_review(self, master_db):
        """Review creates assessed-by edge from Source to Advisory."""
        conn = init_db(master_db)
        doc = master_db.parent / "test_doc6.txt"
        doc.write_text("BSD License. Memory allocator internals.")

        gate = SessionGate()
        result = ingest_document(conn, str(doc), "https://example.com/alloc.txt", "paper", gate=gate)
        review = review_source(conn, result.source_id, "BSD confirmed.", "weak-copyleft")

        edge = conn.execute(
            "SELECT 1 FROM edges WHERE kind = 'assessed-by' AND source_id = ? AND target_id = ?",
            (result.source_id, review.advisory_id),
        ).fetchone()
        assert edge is not None

    def test_concept_provenance_in_pipeline(self, master_db):
        """Every extracted Concept has extracted-from edge to Evidence."""
        conn = init_db(master_db)
        doc = master_db.parent / "test_doc7.txt"
        doc.write_text("MIT License. Lock-free data structures.")

        gate = SessionGate()
        result = ingest_document(conn, str(doc), "https://example.com/lockfree.txt", "paper", gate=gate)
        conn.commit()

        extract = extract_concepts(conn, result.evidence_id, gate, client=MockLLMClient())
        for cid in extract.concept_ids:
            edge = conn.execute(
                "SELECT 1 FROM edges WHERE kind = 'extracted-from' AND source_id = ? AND target_id = ?",
                (cid, result.evidence_id),
            ).fetchone()
            assert edge is not None

    def test_snapshot_concepts_are_class_b(self, master_db, snapshot_db):
        """All Concepts in snapshot have artifact_class=abstracted-mechanism."""
        conn = init_db(master_db)
        doc = master_db.parent / "test_doc8.txt"
        doc.write_text("MIT License. Real-time scheduling algorithms.")

        gate = SessionGate()
        result = ingest_document(conn, str(doc), "https://example.com/rt.txt", "paper", gate=gate)
        review_source(conn, result.source_id, "MIT confirmed.", "weak-copyleft")
        extract = extract_concepts(conn, result.evidence_id, gate, client=MockLLMClient())
        conn.commit()

        export_class_b_snapshot(master_db, snapshot_db)

        snap_conn = sqlite3.connect(str(snapshot_db))
        for row in snap_conn.execute("SELECT attrs FROM nodes WHERE kind = 'Concept'").fetchall():
            attrs = json.loads(row[0])
            assert attrs["artifact_class"] == "abstracted-mechanism"
        snap_conn.close()

    def test_kernel_invariants_in_pipeline(self, master_db, snapshot_db):
        """KernelInvariant nodes are created during extraction and survive export."""
        conn = init_db(master_db)
        doc = master_db.parent / "test_doc_kinv.txt"
        doc.write_text("MIT License. Concurrency control mechanisms in operating systems.")

        gate = SessionGate()
        result = ingest_document(conn, str(doc), "https://example.com/concurrency.txt", "paper", gate=gate)
        review_source(conn, result.source_id, "MIT confirmed.", "weak-copyleft")
        extract = extract_concepts(conn, result.evidence_id, gate, client=MockLLMClient())
        assert extract.invariants_created == 2
        assert extract.failure_modes_created == 2
        assert extract.protocols_created == 1
        assert extract.profiles_created == 1
        assert extract.compatibilities_created == 1
        conn.commit()

        kinv_nodes = conn.execute("SELECT id, attrs FROM nodes WHERE kind = 'KernelInvariant'").fetchall()
        assert len(kinv_nodes) == 2
        for _, attrs_json in kinv_nodes:
            attrs = json.loads(attrs_json)
            assert attrs["artifact_class"] == "abstracted-mechanism"
            assert attrs["strength"] in {"safety", "performance"}

        fm_nodes = conn.execute("SELECT COUNT(*) FROM nodes WHERE kind = 'FailureMode'").fetchone()[0]
        assert fm_nodes == 2

        export_class_b_snapshot(master_db, snapshot_db)
        snap_conn = sqlite3.connect(str(snapshot_db))
        snap_kinv = snap_conn.execute("SELECT COUNT(*) FROM nodes WHERE kind = 'KernelInvariant'").fetchone()[0]
        assert snap_kinv == 2
        snap_governed = snap_conn.execute("SELECT COUNT(*) FROM edges WHERE kind = 'governed-by'").fetchone()[0]
        assert snap_governed == 2
        snap_fm = snap_conn.execute("SELECT COUNT(*) FROM nodes WHERE kind = 'FailureMode'").fetchone()[0]
        assert snap_fm == 2
        snap_triggered = snap_conn.execute("SELECT COUNT(*) FROM edges WHERE kind = 'triggered-by'").fetchone()[0]
        assert snap_triggered == 2
        snap_conn.close()

    def test_mcp_rejects_non_class_b_snapshot(self, tmp_path):
        """MCP init_snapshot rejects a DB containing Evidence nodes."""
        bad_db = tmp_path / "bad_snapshot.db"
        conn = init_db(bad_db)
        add_node(conn, "ev-bad", "Evidence", {
            "artifact_class": "licensed-evidence",
            "contamination_level": "weak-copyleft",
        })
        conn.commit()
        conn.close()

        with pytest.raises(ValueError, match="Not a Class B-only snapshot"):
            init_snapshot(str(bad_db))
