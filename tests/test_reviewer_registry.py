"""Tests for the reviewer roster — ALG-KK-REVIEWER-REGISTER / ALG-KK-REVIEWER-LIST."""

import pytest

from graph.engine import get_node
from graph.schema import init_db
from ingest.reviewer_registry import (
    ReviewerResult,
    find_reviewer,
    list_reviewers,
    register_reviewer,
)


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "test.db")


class TestRegisterReviewer:
    def test_happy_path(self, conn):
        result = register_reviewer(conn, "Alice Nguyen")
        assert isinstance(result, ReviewerResult)
        assert result.name == "Alice Nguyen"
        assert result.reviewer_id.startswith("rvr-")
        node = get_node(conn, result.reviewer_id)
        assert node["kind"] == "Reviewer"
        assert node["attrs"]["name"] == "Alice Nguyen"

    def test_name_is_stripped(self, conn):
        result = register_reviewer(conn, "  Bob  ")
        assert result.name == "Bob"

    def test_empty_name_rejected(self, conn):
        with pytest.raises(ValueError, match="non-empty"):
            register_reviewer(conn, "")

    def test_whitespace_name_rejected(self, conn):
        with pytest.raises(ValueError, match="non-empty"):
            register_reviewer(conn, "   ")

    def test_duplicate_rejected(self, conn):
        register_reviewer(conn, "Alice")
        with pytest.raises(ValueError, match="already registered"):
            register_reviewer(conn, "Alice")

    def test_duplicate_is_case_insensitive(self, conn):
        """INV-KK-REVIEWER-NAME-UNIQUE compares without regard to case."""
        register_reviewer(conn, "Alice")
        with pytest.raises(ValueError, match="already registered"):
            register_reviewer(conn, "ALICE")

    def test_duplicate_ignores_surrounding_whitespace(self, conn):
        register_reviewer(conn, "Alice")
        with pytest.raises(ValueError, match="already registered"):
            register_reviewer(conn, "  alice  ")

    def test_distinct_names_both_registered(self, conn):
        a = register_reviewer(conn, "Alice")
        b = register_reviewer(conn, "Bob")
        assert a.reviewer_id != b.reviewer_id
        assert len(list_reviewers(conn)) == 2


class TestFindReviewer:
    def test_finds_registered_name(self, conn):
        created = register_reviewer(conn, "Alice")
        assert find_reviewer(conn, "Alice") == created.reviewer_id

    def test_lookup_is_case_insensitive(self, conn):
        created = register_reviewer(conn, "Alice")
        assert find_reviewer(conn, "  aLiCe ") == created.reviewer_id

    def test_missing_name_returns_none(self, conn):
        register_reviewer(conn, "Alice")
        assert find_reviewer(conn, "Carol") is None


class TestListReviewers:
    def test_empty_roster(self, conn):
        assert list_reviewers(conn) == []

    def test_ordered_by_name_ignoring_case(self, conn):
        register_reviewer(conn, "carol")
        register_reviewer(conn, "Alice")
        register_reviewer(conn, "bob")
        assert [r.name for r in list_reviewers(conn)] == ["Alice", "bob", "carol"]


class TestReviewEnforcement:
    """INV-KK-REVIEW-REVIEWER-REGISTERED across both write paths."""

    @pytest.fixture
    def source(self, conn):
        from graph.engine import add_node

        add_node(conn, "src-test1", "Source", {
            "url": "https://example.com/paper.pdf",
            "source_type": "paper",
            "license": "LicenseRef-Academic",
        })
        return "src-test1"

    def test_review_paper_rejects_unregistered(self, conn, source):
        from ingest.paper_scorer import review_paper

        with pytest.raises(ValueError, match="is not registered"):
            review_paper(conn, source, "carol", 3, "accept", "Some rationale.")

    def test_review_paper_accepts_registered(self, conn, source):
        from ingest.paper_scorer import review_paper

        register_reviewer(conn, "carol")
        result = review_paper(conn, source, "carol", 3, "accept", "Some rationale.")
        assert result.reviewer == "carol"

    def test_edit_review_rejects_deregistered_reviewer(self, conn, source):
        """A review whose reviewer has left the roster can no longer be edited."""
        from ingest.paper_scorer import edit_review, review_paper

        created_reviewer = register_reviewer(conn, "carol")
        created = review_paper(conn, source, "carol", 3, "accept", "Some rationale.")
        conn.execute("DELETE FROM nodes WHERE id = ?", (created_reviewer.reviewer_id,))
        with pytest.raises(ValueError, match="is not registered"):
            edit_review(conn, created.review_id, 4, "reject", "Updated rationale.")
