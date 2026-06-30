"""Tests for trend detection (ALG-KK-INFER-TREND)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from graph.engine import add_edge, add_node, get_node
from graph.inference import detect_trends
from graph.schema import init_db


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    db = tmp_path / "test.db"
    c = init_db(db)
    yield c
    c.close()


def _add_concept(conn: sqlite3.Connection, name: str, cid: str | None = None) -> str:
    cid = cid or f"concept-{name.lower().replace(' ', '-')}"
    add_node(conn, cid, "Concept", {
        "name": name,
        "description": f"Test concept {name}",
        "artifact_class": "abstracted-mechanism",
        "key_properties": ["test"],
        "tradeoffs": [],
        "design_rationale": "test",
    })
    return cid


def _add_source(conn: sqlite3.Connection, url: str, tag: str = "") -> str:
    sid = f"src-{tag or url.split('/')[-1]}"
    add_node(conn, sid, "Source", {
        "url": url,
        "source_type": "discourse",
        "license": "CC-BY",
    })
    return sid


def _add_evidence(conn: sqlite3.Connection, source_id: str, tag: str = "") -> str:
    eid = f"ev-{tag or source_id}"
    add_node(conn, eid, "Evidence", {
        "artifact_class": "B",
        "contamination_level": "none",
    })
    add_edge(conn, "sourced-from", eid, source_id)
    return eid


def _add_discussion_with_source(
    conn: sqlite3.Connection, concept_id: str, source_date: str,
    source_url: str, tag: str = "",
) -> str:
    sid = _add_source(conn, source_url, tag=f"s-{tag}")
    eid = _add_evidence(conn, sid, tag=f"e-{tag}")
    did = f"disc-{tag}"
    add_node(conn, did, "Discussion", {
        "title": f"Discussion {tag}",
        "forum": "lkml",
        "participant_count": 5,
        "source_date": source_date,
        "artifact_class": "B",
    })
    add_edge(conn, "extracted-from", did, eid)
    add_edge(conn, "discusses", did, concept_id)
    return did


def _recent_date(days_ago: int = 0) -> str:
    return (datetime.now(tz=None) - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def _old_date(days_ago: int = 120) -> str:
    return (datetime.now(tz=None) - timedelta(days=days_ago)).strftime("%Y-%m-%d")


class TestDetectTrends:
    def test_trend_detected_with_min_evidence(self, conn):
        """3 independent sources → trend detected."""
        cid = _add_concept(conn, "RCU")
        _add_discussion_with_source(conn, cid, _recent_date(5), "https://lkml.org/1", "a1")
        _add_discussion_with_source(conn, cid, _recent_date(10), "https://lwn.net/2", "a2")
        _add_discussion_with_source(conn, cid, _recent_date(15), "https://phoronix.com/3", "a3")
        trends = detect_trends(conn, window_days=90, min_evidence=3)
        assert len(trends) == 1
        assert trends[0]["concept_id"] == cid
        assert trends[0]["strength"] == 3

    def test_no_trend_below_threshold(self, conn):
        """2 sources < min_evidence=3 → no trend."""
        cid = _add_concept(conn, "Slab")
        _add_discussion_with_source(conn, cid, _recent_date(5), "https://lkml.org/b1", "b1")
        _add_discussion_with_source(conn, cid, _recent_date(10), "https://lwn.net/b2", "b2")
        trends = detect_trends(conn, window_days=90, min_evidence=3)
        assert len(trends) == 0

    def test_outside_window(self, conn):
        """Sources outside window → no trend."""
        cid = _add_concept(conn, "VFS")
        _add_discussion_with_source(conn, cid, _old_date(150), "https://a.com/1", "c1")
        _add_discussion_with_source(conn, cid, _old_date(160), "https://b.com/2", "c2")
        _add_discussion_with_source(conn, cid, _old_date(170), "https://c.com/3", "c3")
        trends = detect_trends(conn, window_days=90, min_evidence=3)
        assert len(trends) == 0

    def test_window_start_end_from_source_date(self, conn):
        """INV-KK-TREND-WINDOW: window bounds from earliest/latest source_date."""
        cid = _add_concept(conn, "Net")
        d1 = _recent_date(30)
        d2 = _recent_date(20)
        d3 = _recent_date(10)
        _add_discussion_with_source(conn, cid, d1, "https://x.com/1", "d1")
        _add_discussion_with_source(conn, cid, d2, "https://y.com/2", "d2")
        _add_discussion_with_source(conn, cid, d3, "https://z.com/3", "d3")
        trends = detect_trends(conn, window_days=90, min_evidence=3)
        assert len(trends) == 1
        assert trends[0]["window_start"] == d1
        assert trends[0]["window_end"] == d3

    def test_strength_is_distinct_urls(self, conn):
        """INV-KK-TREND-INDEPENDENT: same URL doesn't double-count."""
        cid = _add_concept(conn, "MM")
        _add_discussion_with_source(conn, cid, _recent_date(5), "https://same.com/1", "e1")
        _add_discussion_with_source(conn, cid, _recent_date(10), "https://same.com/1", "e2")
        _add_discussion_with_source(conn, cid, _recent_date(15), "https://diff.com/2", "e3")
        _add_discussion_with_source(conn, cid, _recent_date(20), "https://other.com/3", "e4")
        trends = detect_trends(conn, window_days=90, min_evidence=3)
        assert len(trends) == 1
        assert trends[0]["strength"] == 3  # same.com counted once

    def test_artifact_class_b(self, conn):
        """INV-KK-TREND-CLASS-B: artifact_class always 'B'."""
        cid = _add_concept(conn, "Sched")
        _add_discussion_with_source(conn, cid, _recent_date(5), "https://a.com/1", "f1")
        _add_discussion_with_source(conn, cid, _recent_date(10), "https://b.com/2", "f2")
        _add_discussion_with_source(conn, cid, _recent_date(15), "https://c.com/3", "f3")
        trends = detect_trends(conn, window_days=90, min_evidence=3)
        trend_node = get_node(conn, trends[0]["trend_id"])
        assert trend_node["attrs"]["artifact_class"] == "B"

    def test_trend_node_created(self, conn):
        """Trend node exists in DB after detection."""
        cid = _add_concept(conn, "Block")
        _add_discussion_with_source(conn, cid, _recent_date(5), "https://a.com/g1", "g1")
        _add_discussion_with_source(conn, cid, _recent_date(10), "https://b.com/g2", "g2")
        _add_discussion_with_source(conn, cid, _recent_date(15), "https://c.com/g3", "g3")
        trends = detect_trends(conn, window_days=90, min_evidence=3)
        node = get_node(conn, trends[0]["trend_id"])
        assert node is not None
        assert node["kind"] == "Trend"
        assert "Convergence" in node["attrs"]["title"]

    def test_trend_edge_created(self, conn):
        """trend-about edge links Trend to Concept."""
        cid = _add_concept(conn, "Crypto")
        _add_discussion_with_source(conn, cid, _recent_date(5), "https://a.com/h1", "h1")
        _add_discussion_with_source(conn, cid, _recent_date(10), "https://b.com/h2", "h2")
        _add_discussion_with_source(conn, cid, _recent_date(15), "https://c.com/h3", "h3")
        trends = detect_trends(conn, window_days=90, min_evidence=3)
        edges = conn.execute(
            "SELECT target_id FROM edges WHERE kind = 'trend-about' AND source_id = ?",
            (trends[0]["trend_id"],),
        ).fetchall()
        assert len(edges) == 1
        assert edges[0][0] == cid

    def test_multiple_concepts_independent_trends(self, conn):
        """Two concepts each with enough evidence → two trends."""
        cid1 = _add_concept(conn, "ConcA", "concept-conca")
        cid2 = _add_concept(conn, "ConcB", "concept-concb")
        for i in range(3):
            _add_discussion_with_source(conn, cid1, _recent_date(5+i), f"https://s{i}.com/1", f"m1-{i}")
            _add_discussion_with_source(conn, cid2, _recent_date(5+i), f"https://t{i}.com/2", f"m2-{i}")
        trends = detect_trends(conn, window_days=90, min_evidence=3)
        assert len(trends) == 2
        concept_ids = {t["concept_id"] for t in trends}
        assert concept_ids == {cid1, cid2}

    def test_empty_graph(self, conn):
        """No evidence → no trends."""
        trends = detect_trends(conn, window_days=90, min_evidence=3)
        assert trends == []

    def test_custom_min_evidence(self, conn):
        """min_evidence=2 allows detection with 2 sources."""
        cid = _add_concept(conn, "DRM")
        _add_discussion_with_source(conn, cid, _recent_date(5), "https://a.com/j1", "j1")
        _add_discussion_with_source(conn, cid, _recent_date(10), "https://b.com/j2", "j2")
        assert len(detect_trends(conn, window_days=90, min_evidence=3)) == 0
        assert len(detect_trends(conn, window_days=90, min_evidence=2)) == 1
