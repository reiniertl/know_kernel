"""Tests for ingest.venue_store — IFC-KK-VENUE, IFC-KK-VENUE-EDIT.

Covers INV-KK-VENUE-NORMALISED, INV-KK-VENUE-NAME-UNIQUE and
INV-KK-VENUE-SOURCE-EDGE.
"""

from __future__ import annotations

import pytest

from graph.engine import add_node, get_node
from graph.schema import init_db
from ingest.venue_store import (
    VALID_VENUE_TYPES,
    merge_venues,
    normalise_venue,
    resolve_or_create_venue,
    set_venue,
)


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "venue_test.db")
    yield c
    c.close()


def _source(c, source_id, venue=None, source_type="paper"):
    attrs = {
        "url": f"https://example.com/{source_id}.pdf",
        "source_type": source_type,
        "license": "MIT",
        "title": f"Paper {source_id}",
    }
    if venue:
        attrs["venue"] = venue
    add_node(c, source_id, "Source", attrs)


# --- INV-KK-VENUE-NORMALISED ---------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        # The edition collisions from the venue distribution table.
        ("OSDI 2026", "OSDI"),
        ("OSDI 2025", "OSDI"),
        ("OSDI", "OSDI"),
        ("SOSP 2025", "SOSP"),
        ("SOSP", "SOSP"),
        ("EuroSys 2025 (poster)", "EuroSys"),
        ("EuroSys", "EuroSys"),
        ("ASPLOS 2025", "ASPLOS"),
        ("ASPLOS", "ASPLOS"),
        ("USENIX ATC 2025", "USENIX ATC"),
        ("USENIX ATC", "USENIX ATC"),
        # D-6: every arXiv variant is one venue.
        ("arXiv cs.DC", "arXiv"),
        ("arXiv cs.AR", "arXiv"),
        ("arXiv cs.CR", "arXiv"),
        ("arXiv cs.OS", "arXiv"),
        ("arXiv", "arXiv"),
        ("arXiv/PVLDB", "arXiv"),
        # Untouched values.
        ("NSDI", "NSDI"),
        ("  Middleware  ", "Middleware"),
        ("", ""),
    ],
)
def test_normalise_venue_collapses_collisions(raw, expected):
    assert normalise_venue(raw) == expected


def test_normalise_venue_is_idempotent():
    for raw in ("OSDI 2026", "arXiv cs.DC", "EuroSys 2025 (poster)", "NSDI", ""):
        once = normalise_venue(raw)
        assert normalise_venue(once) == once


def test_normalise_venue_is_pure(monkeypatch):
    """No DB access and no I/O: it must be safe to call anywhere."""
    import sqlite3

    def _explode(*a, **k):  # pragma: no cover - only runs on failure
        raise AssertionError("normalise_venue touched the database")

    monkeypatch.setattr(sqlite3, "connect", _explode)
    assert normalise_venue("OSDI 2026") == "OSDI"


# --- set_venue ------------------------------------------------------------


def test_set_venue_creates_venue_and_edge(conn):
    _source(conn, "src-1")
    result = set_venue(conn, "src-1", "OSDI 2026", "conference")
    assert result.ok and result.venue == "OSDI" and result.created is True
    assert result.rows == 1

    edge = conn.execute(
        "SELECT target_id FROM edges WHERE kind = 'published-at' AND source_id = ?",
        ("src-1",),
    ).fetchone()
    assert edge is not None
    venue = get_node(conn, edge[0])
    assert venue["kind"] == "Venue"
    assert venue["attrs"]["name"] == "OSDI"


def test_set_venue_reuses_existing_venue(conn):
    _source(conn, "src-1")
    _source(conn, "src-2")
    first = set_venue(conn, "src-1", "OSDI 2026", "conference")
    second = set_venue(conn, "src-2", "OSDI 2025", "conference")
    assert first.created is True
    assert second.created is False
    assert first.venue_id == second.venue_id


def test_set_venue_keeps_at_most_one_edge(conn):
    """INV-KK-VENUE-SOURCE-EDGE: re-editing repoints, it does not accumulate."""
    _source(conn, "src-1")
    set_venue(conn, "src-1", "OSDI", "conference")
    set_venue(conn, "src-1", "SOSP", "conference")
    edges = conn.execute(
        "SELECT target_id FROM edges WHERE kind = 'published-at' AND source_id = ?",
        ("src-1",),
    ).fetchall()
    assert len(edges) == 1
    assert get_node(conn, edges[0][0])["attrs"]["name"] == "SOSP"


def test_set_venue_rejects_non_source(conn):
    add_node(conn, "sub-1", "Subsystem", {"name": "Scheduler"})
    with pytest.raises(ValueError, match="does not exist"):
        set_venue(conn, "sub-1", "OSDI")


def test_set_venue_rejects_missing_node(conn):
    with pytest.raises(ValueError, match="does not exist"):
        set_venue(conn, "src-nope", "OSDI")


@pytest.mark.parametrize("bad", ["", "   ", None])
def test_set_venue_rejects_empty(conn, bad):
    _source(conn, "src-1")
    with pytest.raises(ValueError, match="non-empty"):
        set_venue(conn, "src-1", bad)


def test_set_venue_rejects_unknown_venue_type(conn):
    _source(conn, "src-1")
    with pytest.raises(ValueError, match="Invalid venue type"):
        set_venue(conn, "src-1", "OSDI", "not-a-type")


def test_set_venue_stamps_provenance(conn):
    _source(conn, "src-1")
    set_venue(conn, "src-1", "OSDI 2026", "conference")
    attrs = get_node(conn, "src-1")["attrs"]
    assert attrs["venue"] == "OSDI"
    assert attrs["venue_source"] == "manual"
    assert attrs["venue_set_at"]


def test_set_venue_does_not_revalidate_the_source(conn):
    """The carve-out, proven.

    check_source_has_advisory requires every Source to have an Advisory, which
    this one does not. Re-running validate_node after the write would reject a
    perfectly good venue edit for that unrelated pre-existing gap.
    """
    from graph.rules import validate_node

    _source(conn, "src-no-advisory")
    assert validate_node(conn, "src-no-advisory", "Source"), (
        "fixture precondition: this Source must be failing validation already"
    )
    result = set_venue(conn, "src-no-advisory", "OSDI 2026", "conference")
    assert result.ok


# --- merge_venues ---------------------------------------------------------


def _two_venues(conn):
    _source(conn, "src-a")
    _source(conn, "src-b")
    _source(conn, "src-c")
    set_venue(conn, "src-a", "OSDI", "conference")
    set_venue(conn, "src-b", "OSDI", "conference")
    set_venue(conn, "src-c", "SOSP", "conference")


def test_merge_venues_repoints_and_reports_rows(conn):
    _two_venues(conn)
    result = merge_venues(conn, "SOSP", "OSDI")
    assert result.ok
    assert result.rows == 1
    assert result.venue == "OSDI"

    target = conn.execute(
        "SELECT target_id FROM edges WHERE kind = 'published-at' AND source_id = ?",
        ("src-c",),
    ).fetchone()[0]
    assert get_node(conn, target)["attrs"]["name"] == "OSDI"


def test_merge_venues_retires_the_drained_venue(conn):
    _two_venues(conn)
    merge_venues(conn, "SOSP", "OSDI")
    remaining = conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE kind = 'Venue' AND json_extract(attrs, '$.name') = 'SOSP'"
    ).fetchone()[0]
    assert remaining == 0


def test_merge_venues_records_the_alias(conn):
    _two_venues(conn)
    result = merge_venues(conn, "SOSP", "OSDI")
    assert "SOSP" in result.aliases_added
    target = conn.execute(
        "SELECT attrs FROM nodes WHERE kind = 'Venue' AND json_extract(attrs, '$.name') = 'OSDI'"
    ).fetchone()[0]
    import json

    assert "SOSP" in json.loads(target)["aliases"]


def test_merge_venues_is_idempotent(conn):
    _two_venues(conn)
    first = merge_venues(conn, "SOSP", "OSDI")
    second = merge_venues(conn, "SOSP", "OSDI")
    assert first.rows == 1
    assert second.rows == 0
    assert second.ok
    total = conn.execute(
        "SELECT COUNT(*) FROM edges WHERE kind = 'published-at'"
    ).fetchone()[0]
    assert total == 3


def test_merge_venues_rejects_self_merge(conn):
    _two_venues(conn)
    with pytest.raises(ValueError, match="into itself"):
        merge_venues(conn, "OSDI", "OSDI 2026")


def test_merge_venues_rejects_unknown_target(conn):
    _two_venues(conn)
    with pytest.raises(ValueError, match="does not exist"):
        merge_venues(conn, "OSDI", "NoSuchVenue")


# --- INV-KK-VENUE-NAME-UNIQUE --------------------------------------------


def test_venue_name_uniqueness_rule_catches_a_duplicate(conn):
    from graph.rules import validate_node

    resolve_or_create_venue(conn, "OSDI", "conference")
    add_node(conn, "venue-osdi-dup", "Venue", {"name": "OSDI", "venue_type": "conference"})
    violations = validate_node(conn, "venue-osdi-dup", "Venue")
    assert any(v.rule == "venue-name-unique" for v in violations)


def test_resolve_or_create_venue_never_duplicates_a_name(conn):
    a, created_a = resolve_or_create_venue(conn, "OSDI", "conference")
    b, created_b = resolve_or_create_venue(conn, "OSDI", "conference")
    assert a == b and created_a and not created_b


def test_valid_venue_types_are_distinct_from_feed_config_vocabulary():
    """IFC-KK-VENUE records the collision; this pins it.

    INV-KK-FEED-CONFIG-VENUE-TYPE governs a different venue_type, in
    data/feed_configs.json. The two vocabularies are allowed to diverge and
    must not be silently unified.
    """
    assert "preprint-server" in VALID_VENUE_TYPES
    assert "aggregator" not in VALID_VENUE_TYPES
