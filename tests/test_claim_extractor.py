"""Tests for claim extraction from discourse sources (ALG-KK-CLAIM-EXTRACT)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from graph.engine import add_edge, add_node
from graph.schema import init_db
from ingest.claim_extractor import (
    CLAIM_EXTRACTION_PROMPT,
    ClaimExtractionResult,
    build_claim_extraction_context,
    build_claim_user_prompt,
    extract_claims,
    parse_llm_response,
    validate_benchmark,
    validate_discussion,
    validate_observation,
    validate_problem,
    validate_proposal,
    validate_rejection,
)


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    db = tmp_path / "test.db"
    c = init_db(db)
    yield c
    c.close()


def _add_concept(conn: sqlite3.Connection, name: str) -> str:
    cid = f"concept-test-{name.lower().replace(' ', '-')}"
    add_node(conn, cid, "Concept", {
        "name": name,
        "description": f"Test concept {name}",
        "artifact_class": "abstracted-mechanism",
        "key_properties": ["test"],
        "tradeoffs": [],
        "design_rationale": "test",
    })
    return cid


def _add_evidence(conn: sqlite3.Connection, text: str = "test content") -> str:
    eid = "ev-test-001"
    add_node(conn, eid, "Evidence", {
        "artifact_class": "licensed-evidence",
        "contamination_level": "weak-copyleft",
        "text": text,
    })
    return eid


def _make_mock_client(response_data: dict) -> MagicMock:
    client = MagicMock()
    client.create_message.return_value = {
        "text": json.dumps(response_data),
        "prompt_tokens": 100,
        "response_tokens": 200,
    }
    return client


# ── Prompt tests (INV-KK-CLAIM-PROMPT-DISCOURSE) ──


class TestPromptDiscourse:
    def test_prompt_is_distinct_from_concept_extraction(self):
        from ingest.extractor import EXTRACTION_SYSTEM_PROMPT
        assert CLAIM_EXTRACTION_PROMPT != EXTRACTION_SYSTEM_PROMPT

    def test_prompt_targets_discourse_categories(self):
        assert "problems" in CLAIM_EXTRACTION_PROMPT
        assert "observations" in CLAIM_EXTRACTION_PROMPT
        assert "proposals" in CLAIM_EXTRACTION_PROMPT
        assert "benchmarks" in CLAIM_EXTRACTION_PROMPT
        assert "rejections" in CLAIM_EXTRACTION_PROMPT
        assert "discussion" in CLAIM_EXTRACTION_PROMPT

    def test_prompt_not_about_abstract_concepts(self):
        assert "NOT extracting abstract concepts" in CLAIM_EXTRACTION_PROMPT

    def test_prompt_has_anti_hallucination(self):
        assert "Do not hallucinate" in CLAIM_EXTRACTION_PROMPT
        assert "ACTUALLY SAYS" in CLAIM_EXTRACTION_PROMPT


# ── Concept context tests (INV-KK-CLAIM-CONCEPT-CONTEXT) ──


class TestConceptContext:
    def test_context_includes_all_concept_names(self, conn):
        _add_concept(conn, "RCU")
        _add_concept(conn, "Slab Allocator")
        _add_concept(conn, "Page Tables")
        context = build_claim_extraction_context(conn)
        assert "RCU" in context
        assert "Slab Allocator" in context
        assert "Page Tables" in context

    def test_context_empty_db(self, conn):
        context = build_claim_extraction_context(conn)
        assert "No known kernel concepts" in context

    def test_context_names_sorted(self, conn):
        _add_concept(conn, "Zebra")
        _add_concept(conn, "Alpha")
        _add_concept(conn, "Middle")
        context = build_claim_extraction_context(conn)
        idx_a = context.index("Alpha")
        idx_m = context.index("Middle")
        idx_z = context.index("Zebra")
        assert idx_a < idx_m < idx_z

    def test_user_prompt_includes_context(self, conn):
        _add_concept(conn, "RCU")
        context = build_claim_extraction_context(conn)
        prompt = build_claim_user_prompt("Some article text", context)
        assert "RCU" in prompt
        assert "Some article text" in prompt


# ── Validation tests (INV-KK-CLAIM-JSON-SCHEMA) ──


class TestValidateProblem:
    def test_valid_problem(self):
        result = validate_problem({
            "title": "TLB shootdowns",
            "description": "Excessive TLB shootdowns on large NUMA systems",
            "severity": "high",
            "related_concepts": ["Virtual Memory"],
        })
        assert result is not None
        assert result["title"] == "TLB shootdowns"
        assert result["severity"] == "high"

    def test_missing_title(self):
        assert validate_problem({"description": "x", "severity": "high"}) is None

    def test_invalid_severity(self):
        assert validate_problem({"title": "x", "description": "y", "severity": "extreme"}) is None

    def test_not_a_dict(self):
        assert validate_problem("string") is None

    def test_empty_title(self):
        assert validate_problem({"title": "", "description": "y", "severity": "low"}) is None


class TestValidateObservation:
    def test_valid_observation(self):
        result = validate_observation({
            "claim": "NUMA locality affects throughput by 30%",
            "confidence": 0.8,
            "related_concepts": ["NUMA"],
        })
        assert result is not None
        assert result["confidence"] == 0.8

    def test_confidence_clamped(self):
        result = validate_observation({
            "claim": "test", "confidence": 1.5,
        })
        assert result["confidence"] == 1.0

    def test_missing_claim(self):
        assert validate_observation({"confidence": 0.5}) is None

    def test_non_numeric_confidence(self):
        assert validate_observation({"claim": "x", "confidence": "high"}) is None


class TestValidateProposal:
    def test_valid_proposal(self):
        result = validate_proposal({
            "name": "NUMA-aware folio alloc",
            "description": "Allocate folios based on NUMA locality",
            "status": "under-review",
            "related_concepts": ["Large Folios"],
            "addresses_problems": ["TLB shootdowns"],
        })
        assert result is not None
        assert result["status"] == "under-review"
        assert result["addresses_problems"] == ["TLB shootdowns"]

    def test_invalid_status_defaults_to_draft(self):
        result = validate_proposal({
            "name": "test", "description": "test", "status": "unknown",
        })
        assert result["status"] == "draft"

    def test_missing_name(self):
        assert validate_proposal({"description": "x", "status": "draft"}) is None


class TestValidateBenchmark:
    def test_valid_benchmark(self):
        result = validate_benchmark({
            "metric": "throughput",
            "result_summary": "17% improvement on 128 cores",
            "conditions": "Intel Xeon 4th gen, 512GB RAM",
            "related_concepts": ["Scheduler"],
        })
        assert result is not None
        assert result["metric"] == "throughput"

    def test_missing_result_summary(self):
        assert validate_benchmark({"metric": "x", "conditions": "y"}) is None


class TestValidateRejection:
    def test_valid_rejection(self):
        result = validate_rejection({
            "proposal_title": "Remove GIL",
            "reason": "Too much complexity for marginal gain",
            "rejector": "Linus Torvalds",
            "related_concepts": ["Scheduler"],
        })
        assert result is not None
        assert result["rejector"] == "Linus Torvalds"

    def test_missing_reason(self):
        assert validate_rejection({"proposal_title": "x", "rejector": "y"}) is None


class TestValidateDiscussion:
    def test_valid_discussion(self):
        result = validate_discussion({
            "title": "Folios and Large Pages",
            "forum": "lwn",
            "participant_count": 15,
            "related_concepts": ["Large Folios"],
        })
        assert result is not None
        assert result["forum"] == "lwn"
        assert result["participant_count"] == 15

    def test_invalid_forum_defaults_to_other(self):
        result = validate_discussion({
            "title": "test", "forum": "reddit",
        })
        assert result["forum"] == "other"

    def test_missing_title(self):
        assert validate_discussion({"forum": "lwn"}) is None

    def test_non_int_participant_count(self):
        result = validate_discussion({
            "title": "test", "forum": "lkml", "participant_count": "many",
        })
        assert result["participant_count"] == 0


# ── LLM response parsing ──


class TestParseLlmResponse:
    def test_valid_json(self):
        result = parse_llm_response('{"problems": []}')
        assert result == {"problems": []}

    def test_markdown_wrapped(self):
        result = parse_llm_response('```json\n{"problems": []}\n```')
        assert result == {"problems": []}

    def test_invalid_json(self):
        assert parse_llm_response("not json") == {}

    def test_non_dict_json(self):
        assert parse_llm_response("[1, 2, 3]") == {}


# ── Full extraction tests ──


class TestExtractClaims:
    def test_dry_run(self, conn):
        eid = _add_evidence(conn)
        result = extract_claims(conn, eid, source_date="2026-06-15", dry_run=True)
        assert result.evidence_id == eid
        assert result.problems_created == 0
        assert result.prompt_tokens > 0

    def test_nonexistent_evidence_raises(self, conn):
        with pytest.raises(ValueError, match="does not exist"):
            extract_claims(conn, "ev-nonexistent", source_date="2026-06-15")

    def test_extracts_problems(self, conn):
        eid = _add_evidence(conn, "Article about TLB issues")
        _add_concept(conn, "Virtual Memory")
        client = _make_mock_client({
            "problems": [{
                "title": "TLB shootdowns",
                "description": "Excessive shootdowns on NUMA",
                "severity": "high",
                "related_concepts": ["Virtual Memory"],
            }],
        })
        result = extract_claims(conn, eid, source_date="2026-06-15", client=client)
        assert result.problems_created == 1
        assert result.concepts_matched == 1
        prob = conn.execute(
            "SELECT attrs FROM nodes WHERE kind = 'Problem'"
        ).fetchone()
        attrs = json.loads(prob[0])
        assert attrs["source_date"] == "2026-06-15"
        assert attrs["artifact_class"] == "B"

    def test_extracts_observations(self, conn):
        eid = _add_evidence(conn)
        client = _make_mock_client({
            "observations": [{
                "claim": "NUMA locality matters",
                "confidence": 0.9,
                "related_concepts": [],
            }],
        })
        result = extract_claims(conn, eid, source_date="2026-06-10", client=client)
        assert result.observations_created == 1
        obs = conn.execute(
            "SELECT attrs FROM nodes WHERE kind = 'Observation'"
        ).fetchone()
        attrs = json.loads(obs[0])
        assert attrs["source_date"] == "2026-06-10"

    def test_extracts_proposals_with_addresses(self, conn):
        eid = _add_evidence(conn)
        _add_concept(conn, "Large Folios")
        client = _make_mock_client({
            "problems": [{
                "title": "Folio sizing",
                "description": "Fixed sizes cause waste",
                "severity": "medium",
                "related_concepts": ["Large Folios"],
            }],
            "proposals": [{
                "name": "Adaptive folio sizing",
                "description": "Size folios based on workload",
                "status": "draft",
                "related_concepts": ["Large Folios"],
                "addresses_problems": ["Folio sizing"],
            }],
        })
        result = extract_claims(conn, eid, source_date="2026-06-20", client=client)
        assert result.problems_created == 1
        assert result.proposals_created == 1
        addr_edges = conn.execute(
            "SELECT * FROM edges WHERE kind = 'addresses'"
        ).fetchall()
        assert len(addr_edges) == 1

    def test_extracts_benchmarks(self, conn):
        eid = _add_evidence(conn)
        client = _make_mock_client({
            "benchmarks": [{
                "metric": "throughput",
                "result_summary": "17% improvement",
                "conditions": "128 cores",
                "related_concepts": [],
            }],
        })
        result = extract_claims(conn, eid, source_date="2026-06-15", client=client)
        assert result.benchmarks_created == 1

    def test_extracts_rejections(self, conn):
        eid = _add_evidence(conn)
        client = _make_mock_client({
            "rejections": [{
                "proposal_title": "Remove GIL",
                "reason": "Too complex",
                "rejector": "maintainer",
                "related_concepts": [],
            }],
        })
        result = extract_claims(conn, eid, source_date="2026-06-15", client=client)
        assert result.rejections_created == 1

    def test_extracts_discussion(self, conn):
        eid = _add_evidence(conn)
        _add_concept(conn, "RCU")
        client = _make_mock_client({
            "discussion": {
                "title": "RCU grace periods",
                "forum": "lkml",
                "participant_count": 8,
                "related_concepts": ["RCU"],
            },
        })
        result = extract_claims(conn, eid, source_date="2026-06-15", client=client)
        assert result.discussions_created == 1
        assert result.concepts_matched == 1
        disc = conn.execute(
            "SELECT attrs FROM nodes WHERE kind = 'Discussion'"
        ).fetchone()
        attrs = json.loads(disc[0])
        assert attrs["forum"] == "lkml"

    def test_full_extraction_all_categories(self, conn):
        eid = _add_evidence(conn, "Full article with everything")
        _add_concept(conn, "Scheduler")
        _add_concept(conn, "RCU")
        client = _make_mock_client({
            "problems": [{"title": "P1", "description": "d", "severity": "high", "related_concepts": ["Scheduler"]}],
            "observations": [{"claim": "O1", "confidence": 0.7, "related_concepts": ["RCU"]}],
            "proposals": [{"name": "PR1", "description": "d", "status": "draft", "related_concepts": ["Scheduler"]}],
            "benchmarks": [{"metric": "m", "result_summary": "r", "conditions": "c", "related_concepts": []}],
            "rejections": [{"proposal_title": "R1", "reason": "r", "rejector": "j", "related_concepts": []}],
            "discussion": {"title": "D1", "forum": "lwn", "participant_count": 5, "related_concepts": ["RCU", "Scheduler"]},
        })
        result = extract_claims(conn, eid, source_date="2026-06-15", client=client)
        assert result.problems_created == 1
        assert result.observations_created == 1
        assert result.proposals_created == 1
        assert result.benchmarks_created == 1
        assert result.rejections_created == 1
        assert result.discussions_created == 1
        assert result.concepts_matched == 5
        assert len(result.node_ids) == 6

    def test_source_date_inherited(self, conn):
        """INV-KK-CLAIM-SOURCE-DATE: all nodes get the feed item's published date."""
        eid = _add_evidence(conn)
        client = _make_mock_client({
            "problems": [{"title": "P", "description": "d", "severity": "low", "related_concepts": []}],
            "observations": [{"claim": "C", "confidence": 0.5, "related_concepts": []}],
        })
        result = extract_claims(conn, eid, source_date="2025-12-01", client=client)
        for nid in result.node_ids:
            row = conn.execute("SELECT attrs FROM nodes WHERE id = ?", (nid,)).fetchone()
            attrs = json.loads(row[0])
            assert attrs["source_date"] == "2025-12-01"

    def test_concept_matching_case_insensitive(self, conn):
        eid = _add_evidence(conn)
        _add_concept(conn, "Virtual Memory")
        client = _make_mock_client({
            "problems": [{
                "title": "P", "description": "d", "severity": "low",
                "related_concepts": ["virtual memory"],
            }],
        })
        result = extract_claims(conn, eid, source_date="2026-06-15", client=client)
        assert result.concepts_matched == 1
        edges = conn.execute(
            "SELECT * FROM edges WHERE kind = 'identifies-problem'"
        ).fetchall()
        assert len(edges) == 1

    def test_unmatched_concepts_skipped(self, conn):
        eid = _add_evidence(conn)
        client = _make_mock_client({
            "problems": [{
                "title": "P", "description": "d", "severity": "low",
                "related_concepts": ["Nonexistent Concept"],
            }],
        })
        result = extract_claims(conn, eid, source_date="2026-06-15", client=client)
        assert result.concepts_matched == 0
        edges = conn.execute(
            "SELECT * FROM edges WHERE kind = 'identifies-problem'"
        ).fetchall()
        assert len(edges) == 0

    def test_empty_response(self, conn):
        eid = _add_evidence(conn)
        client = _make_mock_client({})
        result = extract_claims(conn, eid, source_date="2026-06-15", client=client)
        assert result.problems_created == 0
        assert result.observations_created == 0
        assert result.proposals_created == 0
        assert len(result.node_ids) == 0

    def test_invalid_items_skipped(self, conn):
        eid = _add_evidence(conn)
        client = _make_mock_client({
            "problems": [
                {"title": "Valid", "description": "d", "severity": "low", "related_concepts": []},
                {"title": "", "description": "d", "severity": "low"},
                "not a dict",
                {"description": "missing title"},
            ],
        })
        result = extract_claims(conn, eid, source_date="2026-06-15", client=client)
        assert result.problems_created == 1

    def test_extracted_from_edges(self, conn):
        eid = _add_evidence(conn)
        client = _make_mock_client({
            "problems": [{"title": "P", "description": "d", "severity": "low", "related_concepts": []}],
            "observations": [{"claim": "C", "confidence": 0.5, "related_concepts": []}],
        })
        result = extract_claims(conn, eid, source_date="2026-06-15", client=client)
        ef_edges = conn.execute(
            "SELECT * FROM edges WHERE kind = 'extracted-from' AND target_id = ?",
            (eid,),
        ).fetchall()
        assert len(ef_edges) == 2

    def test_all_artifact_class_b(self, conn):
        """All created evidence nodes are Class B."""
        eid = _add_evidence(conn)
        client = _make_mock_client({
            "problems": [{"title": "P", "description": "d", "severity": "low", "related_concepts": []}],
        })
        result = extract_claims(conn, eid, source_date="2026-06-15", client=client)
        for nid in result.node_ids:
            row = conn.execute("SELECT attrs FROM nodes WHERE id = ?", (nid,)).fetchone()
            attrs = json.loads(row[0])
            assert attrs["artifact_class"] == "B"
