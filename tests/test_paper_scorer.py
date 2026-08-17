"""Tests for review_paper and edit_review — ALG-KK-REVIEW-PAPER / ALG-KK-REVIEW-EDIT invariants."""

import pytest

from graph.engine import add_node, get_node
from graph.schema import init_db
from ingest.paper_scorer import PaperReviewResult, review_paper, edit_review


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "test.db")


@pytest.fixture
def source(conn):
    add_node(conn, "src-test1", "Source", {
        "url": "https://example.com/paper.pdf",
        "source_type": "paper",
        "license": "LicenseRef-Academic",
    })
    return "src-test1"


@pytest.fixture
def second_source(conn):
    add_node(conn, "src-test2", "Source", {
        "url": "https://example.com/paper2.pdf",
        "source_type": "preprint",
        "license": "LicenseRef-Academic",
    })
    return "src-test2"


class TestReviewPaper:
    def test_happy_path(self, conn, source):
        result = review_paper(conn, source, "alice", 4, "accept", "High impact on scheduler design.")
        assert isinstance(result, PaperReviewResult)
        assert result.source_id == source
        assert result.reviewer == "alice"
        assert result.score == 4
        assert result.verdict == "accept"
        assert result.rationale == "High impact on scheduler design."
        assert result.review_id.startswith("hrev-")
        node = conn.execute(
            "SELECT id, kind FROM nodes WHERE id = ?", (result.review_id,)
        ).fetchone()
        assert node is not None and node[1] == "HumanReview"
        edge = conn.execute(
            "SELECT 1 FROM edges WHERE kind = 'reviewed-by' AND source_id = ? AND target_id = ?",
            (source, result.review_id),
        ).fetchone()
        assert edge is not None

    def test_score_range_invalid(self, conn, source):
        with pytest.raises(ValueError, match="Score must be 1-5"):
            review_paper(conn, source, "alice", 0, "accept", "Some rationale.")
        with pytest.raises(ValueError, match="Score must be 1-5"):
            review_paper(conn, source, "alice", 6, "accept", "Some rationale.")

    def test_verdict_invalid(self, conn, source):
        with pytest.raises(ValueError, match="Invalid verdict"):
            review_paper(conn, source, "alice", 3, "maybe", "Some rationale.")

    def test_verdict_skip_retired(self, conn, source):
        """INV-KK-REVIEW-VERDICT-ENUM: skip is no longer an admissible verdict."""
        with pytest.raises(ValueError, match="Invalid verdict"):
            review_paper(conn, source, "alice", 3, "skip", "Some rationale.")

    def test_rationale_empty(self, conn, source):
        with pytest.raises(ValueError, match="non-empty"):
            review_paper(conn, source, "alice", 3, "accept", "")
        with pytest.raises(ValueError, match="non-empty"):
            review_paper(conn, source, "alice", 3, "accept", "   ")

    def test_source_not_found(self, conn):
        with pytest.raises(ValueError, match="does not exist"):
            review_paper(conn, "src-nonexistent", "alice", 3, "accept", "Some rationale.")

    def test_duplicate_reviewer(self, conn, source, second_source):
        review_paper(conn, source, "alice", 4, "accept", "First review.")
        with pytest.raises(ValueError, match="already reviewed by"):
            review_paper(conn, source, "alice", 2, "reject", "Second review.")
        result = review_paper(conn, source, "bob", 3, "reject", "Different reviewer.")
        assert result.reviewer == "bob"
        result2 = review_paper(conn, second_source, "alice", 5, "accept", "Same reviewer, different source.")
        assert result2.source_id == second_source


class TestEditReview:
    def test_happy_path(self, conn, source):
        created = review_paper(conn, source, "alice", 4, "accept", "Initial rationale.")
        result = edit_review(conn, created.review_id, 2, "reject", "Updated rationale.")
        assert isinstance(result, PaperReviewResult)
        assert result.review_id == created.review_id
        assert result.score == 2
        assert result.verdict == "reject"
        assert result.rationale == "Updated rationale."
        assert result.reviewer == "alice"
        assert result.source_id == source
        node = get_node(conn, created.review_id)
        assert node["attrs"]["score"] == 2
        assert node["attrs"]["verdict"] == "reject"
        assert node["attrs"]["reviewer"] == "alice"

    def test_nonexistent_review(self, conn):
        with pytest.raises(ValueError, match="does not exist"):
            edit_review(conn, "hrev-nonexistent", 3, "accept", "Rationale.")

    def test_invalid_score(self, conn, source):
        created = review_paper(conn, source, "alice", 4, "accept", "Rationale.")
        with pytest.raises(ValueError, match="Score must be 1-5"):
            edit_review(conn, created.review_id, 0, "accept", "Rationale.")

    def test_invalid_verdict(self, conn, source):
        created = review_paper(conn, source, "alice", 4, "accept", "Rationale.")
        with pytest.raises(ValueError, match="Invalid verdict"):
            edit_review(conn, created.review_id, 3, "maybe", "Rationale.")

    def test_verdict_skip_retired(self, conn, source):
        """INV-KK-REVIEW-VERDICT-ENUM: skip is no longer an admissible verdict."""
        created = review_paper(conn, source, "alice", 4, "accept", "Rationale.")
        with pytest.raises(ValueError, match="Invalid verdict"):
            edit_review(conn, created.review_id, 3, "skip", "Rationale.")

    def test_empty_rationale(self, conn, source):
        created = review_paper(conn, source, "alice", 4, "accept", "Rationale.")
        with pytest.raises(ValueError, match="non-empty"):
            edit_review(conn, created.review_id, 3, "accept", "")

    def test_reviewer_immutable(self, conn, source):
        created = review_paper(conn, source, "alice", 4, "accept", "Rationale.")
        result = edit_review(conn, created.review_id, 2, "reject", "Changed mind.")
        assert result.reviewer == "alice"
        node = get_node(conn, created.review_id)
        assert node["attrs"]["reviewer"] == "alice"
