"""Tests for review_source â€” ALG-KK-REVIEW-SOURCE invariants."""

import pytest

from graph.engine import add_edge, add_node
from graph.schema import init_db
from ingest.reviewer import ReviewResult, review_source


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "test.db")


@pytest.fixture
def source_with_evidence(conn):
    """Create a Source + Evidence pair (as ingest_document would)."""
    add_node(conn, "src-test1", "Source", {
        "url": "https://example.com/doc.txt",
        "source_type": "paper",
        "license": "MIT",
    })
    add_node(conn, "ev-test1", "Evidence", {
        "artifact_class": "licensed-evidence",
        "contamination_level": "weak-copyleft",
    })
    add_edge(conn, "sourced-from", "ev-test1", "src-test1")
    return "src-test1"


class TestReviewSource:
    def test_successful_review(self, conn, source_with_evidence):
        result = review_source(conn, source_with_evidence, "License confirmed as MIT.", "weak-copyleft")
        assert isinstance(result, ReviewResult)
        assert result.source_id == source_with_evidence
        assert result.assessment_text == "License confirmed as MIT."
        assert result.contamination_confirmed == "weak-copyleft"
        advisory = conn.execute(
            "SELECT id, kind FROM nodes WHERE id = ?", (result.advisory_id,)
        ).fetchone()
        assert advisory is not None and advisory[1] == "Advisory"
        edge = conn.execute(
            "SELECT 1 FROM edges WHERE kind = 'assessed-by' AND source_id = ? AND target_id = ?",
            (source_with_evidence, result.advisory_id),
        ).fetchone()
        assert edge is not None

    def test_duplicate_review_rejected(self, conn, source_with_evidence):
        review_source(conn, source_with_evidence, "First review.", "weak-copyleft")
        with pytest.raises(ValueError, match="already has an assessed-by edge"):
            review_source(conn, source_with_evidence, "Second review.", "weak-copyleft")

    def test_nonexistent_source_raises(self, conn):
        with pytest.raises(ValueError, match="does not exist"):
            review_source(conn, "src-nonexistent", "Some assessment.", "weak-copyleft")

    def test_empty_assessment_raises(self, conn, source_with_evidence):
        with pytest.raises(ValueError, match="non-empty"):
            review_source(conn, source_with_evidence, "", "weak-copyleft")

    def test_advisory_has_assessment_attr(self, conn, source_with_evidence):
        result = review_source(conn, source_with_evidence, "Good license.", "weak-copyleft")
        row = conn.execute(
            "SELECT attrs FROM nodes WHERE id = ?", (result.advisory_id,)
        ).fetchone()
        import json
        attrs = json.loads(row[0])
        assert "assessment" in attrs
        assert attrs["assessment"] == "Good license."

    def test_advisory_stores_contamination_confirmed(self, conn, source_with_evidence):
        """INV-KK-ADVISORY-STORES-CONTAMINATION"""
        result = review_source(conn, source_with_evidence, "License OK.", "weak-copyleft")
        row = conn.execute(
            "SELECT attrs FROM nodes WHERE id = ?", (result.advisory_id,)
        ).fetchone()
        import json
        attrs = json.loads(row[0])
        assert "contamination_confirmed" in attrs
        assert attrs["contamination_confirmed"] == "weak-copyleft"

    def test_advisory_without_contamination_confirmed_fails_schema(self, conn, source_with_evidence):
        """INV-KK-ADVISORY-REQUIRES-ASSESSMENT — contamination_confirmed is required."""
        from graph.engine import add_node
        with pytest.raises(ValueError, match="contamination_confirmed"):
            add_node(conn, "adv-missing", "Advisory", {
                "assessment": "Some assessment",
            })

    def test_evidence_unchanged_after_review(self, conn, source_with_evidence):
        ev_before = conn.execute(
            "SELECT id, kind, attrs FROM nodes WHERE id = 'ev-test1'"
        ).fetchone()
        review_source(conn, source_with_evidence, "Review complete.", "weak-copyleft")
        ev_after = conn.execute(
            "SELECT id, kind, attrs FROM nodes WHERE id = 'ev-test1'"
        ).fetchone()
        assert ev_before == ev_after

    def test_invalid_contamination_level_raises(self, conn, source_with_evidence):
        with pytest.raises(ValueError, match="Invalid contamination level"):
            review_source(conn, source_with_evidence, "Review.", "invalid-level")
