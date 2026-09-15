"""Venue storage (IFC-KK-VENUE, IFC-KK-VENUE-EDIT).

Owns every write to venue data so that the manual editor in the web layer
(ALG-KK-WEB-VENUE-EDIT, ALG-KK-WEB-VENUE-MERGE) and the one-time migration
(ALG-KK-VENUE-BACKFILL) go through one place and normalise identically.

Venue is a first-class node kind (decision D-1 Option A): a Source is linked to
its Venue by a `published-at` edge, and to at most one, per
INV-KK-VENUE-SOURCE-EDGE. The raw `Source.attrs.venue` string is retained as
provenance and as alias evidence, but it is no longer what the viewer groups on
— grouping on it produced wrong buckets, because the 34 raw strings contain
edition collisions (OSDI 2026 / OSDI 2025 / OSDI is one venue, not three).

`venue` stays out of REQUIRED_ATTRS["Source"] for the same reason the abstract
fields do: 107 Sources carry no venue, and requiring it would invalidate every
existing Source node and every add_node call in the ingest pipeline.

Two carve-outs, both deliberate and both load-bearing:

1. Source is not revalidated after a write. validate_node against Source applies
   the must-have-an-Advisory rule, which the great majority of real Sources do
   not satisfy; revalidating here would reject a good venue edit for an
   unrelated pre-existing gap. This mirrors set_abstract.

2. Edges are repointed with direct SQL rather than graph.engine.delete_edge.
   delete_edge re-runs validate_node on the edge's source node, so it would hit
   carve-out 1 through the back door and raise AdmissibilityError on a Source
   that merely lacks an Advisory. The same applies to delete_node, which is why
   merge_venues removes the drained Venue with a direct DELETE.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date

from graph.engine import add_edge, add_node, get_node, update_node_attrs
from graph.schema import ID_PREFIXES

# What kind of thing a venue is. Distinct from the `venue_type` governed by
# INV-KK-FEED-CONFIG-VENUE-TYPE, which constrains data/feed_configs.json to a
# different vocabulary, and distinct again from that file's `feed_type: "venue"`.
# Three unrelated meanings share the word; this tuple is this module's alone.
VALID_VENUE_TYPES = (
    "conference",
    "journal",
    "workshop",
    "symposium",
    "preprint-server",
    "documentation",
    "vulnerability-db",
    "other",
)

# Canonical venue for every arXiv category string (decision D-6). The four
# `arXiv cs.*` values cover 2,846 of 3,574 Sources — 82% of the corpus — and
# name arXiv categories, not venues. Collapsing them keeps the viewer showing
# real venues instead of four category rows burying the other thirty.
_ARXIV = "arXiv"

# Edition suffixes to strip: a trailing year, optionally followed by a
# parenthesised qualifier such as "(poster)".
_EDITION_RE = re.compile(r"\s+(19|20)\d{2}(\s*\([^)]*\))?\s*$")
_TRAILING_QUALIFIER_RE = re.compile(r"\s*\([^)]*\)\s*$")


def normalise_venue(raw: str) -> str:
    """Collapse a raw venue string to its canonical form.

    Pure: no database access, no I/O, no clock. Idempotent:
    normalise_venue(normalise_venue(x)) == normalise_venue(x).

    Implements INV-KK-VENUE-NORMALISED.
    """
    if raw is None:
        return ""
    name = " ".join(str(raw).split())
    if not name:
        return ""

    # D-6: every arXiv variant is one venue.
    if name.lower().startswith("arxiv"):
        return _ARXIV

    # Strip a trailing edition year, then any trailing parenthesised qualifier
    # left behind by a value like "EuroSys (poster)".
    name = _EDITION_RE.sub("", name)
    name = _TRAILING_QUALIFIER_RE.sub("", name)
    return name.strip()


@dataclass
class VenueResult:
    """IFC-KK-VENUE-EDIT: what the domain functions hand back to the routes."""

    ok: bool
    venue: str
    venue_id: str = ""
    created: bool = False
    rows: int = 0
    aliases_added: list[str] = field(default_factory=list)
    error: str | None = None


def _venue_id_for(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"{ID_PREFIXES['Venue']}{slug}"


def _find_venue_by_name(conn: sqlite3.Connection, name: str) -> str | None:
    row = conn.execute(
        "SELECT id FROM nodes WHERE kind = 'Venue' AND json_extract(attrs, '$.name') = ? LIMIT 1",
        (name,),
    ).fetchone()
    return row[0] if row else None


def resolve_or_create_venue(
    conn: sqlite3.Connection, name: str, venue_type: str = "other"
) -> tuple[str, bool]:
    """Return (venue_id, created) for a canonical venue name.

    The name must already be canonical — callers normalise first, so that
    INV-KK-VENUE-NAME-UNIQUE cannot be broken by two spellings of one venue.
    """
    if venue_type not in VALID_VENUE_TYPES:
        raise ValueError(
            f"Invalid venue type '{venue_type}'. Must be one of: "
            + ", ".join(VALID_VENUE_TYPES)
        )
    existing = _find_venue_by_name(conn, name)
    if existing is not None:
        return existing, False

    venue_id = _venue_id_for(name)
    # A different venue could already hold this id if two names slug the same
    # way; disambiguate rather than collide.
    suffix = 2
    while get_node(conn, venue_id) is not None:
        venue_id = f"{_venue_id_for(name)}-{suffix}"
        suffix += 1

    add_node(conn, venue_id, "Venue", {
        "name": name,
        "venue_type": venue_type,
        "aliases": [],
    })
    return venue_id, True


def _clear_published_at(conn: sqlite3.Connection, source_id: str) -> None:
    """Drop a Source's existing published-at edge with direct SQL.

    graph.engine.delete_edge would re-run validate_node on the Source and fail
    on the missing-Advisory rule; see carve-out 2 in the module docstring.
    """
    conn.execute(
        "DELETE FROM edges WHERE kind = 'published-at' AND source_id = ?", (source_id,)
    )


def set_venue(
    conn: sqlite3.Connection,
    source_id: str,
    venue: str,
    venue_type: str = "other",
) -> VenueResult:
    """Attach a Source to its Venue, creating the Venue if needed.

    Raises ValueError if `source_id` names no node or names a node of another
    kind, or if `venue` is empty after normalising.

    Implements ALG-KK-WEB-VENUE-EDIT. Touches exactly one Source, which is why
    INV-KK-VENUE-MUTATION-AUTHORISED requires only an authenticated user here.
    """
    canonical = normalise_venue(venue)
    if not canonical:
        raise ValueError("Venue must be non-empty")

    node = get_node(conn, source_id)
    if node is None or node["kind"] != "Source":
        raise ValueError(f"Source node '{source_id}' does not exist")

    venue_id, created = resolve_or_create_venue(conn, canonical, venue_type)

    _clear_published_at(conn, source_id)
    add_edge(conn, "published-at", source_id, venue_id)

    # Keep the raw string as provenance. Source is NOT revalidated; see
    # carve-out 1 in the module docstring.
    update_node_attrs(conn, source_id, {
        "venue": canonical,
        "venue_source": "manual",
        "venue_set_at": date.today().isoformat(),
    })

    return VenueResult(
        ok=True, venue=canonical, venue_id=venue_id, created=created, rows=1
    )


def merge_venues(conn: sqlite3.Connection, from_venue: str, to_venue: str) -> VenueResult:
    """Repoint every Source from one Venue to another and retire the source Venue.

    Idempotent: once `from_venue` no longer resolves, a repeat call is a no-op
    reporting rows=0 rather than an error.

    Raises ValueError if `to_venue` resolves to no Venue, or if the two names
    are the same after normalising.

    Implements ALG-KK-WEB-VENUE-MERGE. One call can repoint up to 897 Sources,
    which is why INV-KK-VENUE-MUTATION-AUTHORISED requires an admin here.
    """
    src_name = normalise_venue(from_venue)
    dst_name = normalise_venue(to_venue)
    if not src_name or not dst_name:
        raise ValueError("Both venue names must be non-empty")
    if src_name == dst_name:
        raise ValueError("Cannot merge a venue into itself")

    dst_id = _find_venue_by_name(conn, dst_name)
    if dst_id is None:
        raise ValueError(f"Venue '{dst_name}' does not exist")

    src_id = _find_venue_by_name(conn, src_name)
    if src_id is None:
        # Already merged. Idempotent no-op.
        return VenueResult(ok=True, venue=dst_name, venue_id=dst_id, rows=0)

    moved = conn.execute(
        "SELECT source_id FROM edges WHERE kind = 'published-at' AND target_id = ?",
        (src_id,),
    ).fetchall()
    source_ids = [r[0] for r in moved]

    for sid in source_ids:
        _clear_published_at(conn, sid)
        add_edge(conn, "published-at", sid, dst_id)
        update_node_attrs(conn, sid, {"venue": dst_name})

    # Fold the retired name into the target's aliases so the mapping survives.
    dst = get_node(conn, dst_id)
    aliases = list(dst["attrs"].get("aliases") or [])
    added = [a for a in ([src_name] + list(_alias_list(conn, src_id))) if a not in aliases]
    if added:
        aliases.extend(added)
        update_node_attrs(conn, dst_id, {"aliases": aliases})

    # Direct DELETE: graph.engine.delete_node revalidates every dependent node,
    # which would fail on Sources lacking an Advisory. See carve-out 2.
    conn.execute("DELETE FROM edges WHERE source_id = ? OR target_id = ?", (src_id, src_id))
    conn.execute("DELETE FROM nodes WHERE id = ?", (src_id,))

    return VenueResult(
        ok=True,
        venue=dst_name,
        venue_id=dst_id,
        rows=len(source_ids),
        aliases_added=added,
    )


def _alias_list(conn: sqlite3.Connection, venue_id: str) -> list[str]:
    row = conn.execute("SELECT attrs FROM nodes WHERE id = ?", (venue_id,)).fetchone()
    if not row:
        return []
    attrs = json.loads(row[0]) if isinstance(row[0], str) else (row[0] or {})
    return list(attrs.get("aliases") or [])
