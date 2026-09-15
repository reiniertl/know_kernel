"""One-time migration from Source.attrs.venue to Venue nodes (ALG-KK-VENUE-BACKFILL).

Reads every Source carrying a free-text venue, normalises it per
INV-KK-VENUE-NORMALISED, creates one Venue node per distinct canonical name and
one published-at edge per Source (INV-KK-VENUE-SOURCE-EDGE).

Idempotent and re-runnable: a second run creates no duplicate Venue node and no
duplicate edge. The raw Source.attrs.venue string is NOT deleted — it is kept as
provenance and as the alias evidence for IFC-KK-VENUE.aliases.

Sources carrying no venue are left untouched and get no edge; the viewer shows
them in an explicit bucket rather than dropping them.

Usage:
    python data/backfill_venues.py data/master.db [--dry-run]
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from ingest.venue_store import (
    normalise_venue,
    resolve_or_create_venue,
)

# Canonical name -> venue_type. Anything unlisted falls back to "conference",
# which is what the overwhelming majority of these venues are.
VENUE_TYPES = {
    "arXiv": "preprint-server",
    "Phoronix": "other",
    "IETF CCWG": "other",
    "Linux Plumbers Conference": "conference",
}
DEFAULT_VENUE_TYPE = "conference"


def backfill(conn: sqlite3.Connection, dry_run: bool = False) -> dict:
    rows = conn.execute(
        "SELECT id, attrs FROM nodes WHERE kind = 'Source'"
    ).fetchall()

    raw_to_sources: dict[str, list[str]] = collections.defaultdict(list)
    no_venue = 0
    for source_id, attrs_raw in rows:
        attrs = json.loads(attrs_raw) if isinstance(attrs_raw, str) else (attrs_raw or {})
        raw = attrs.get("venue")
        if not raw:
            no_venue += 1
            continue
        raw_to_sources[raw].append(source_id)

    canonical: dict[str, list[str]] = collections.defaultdict(list)
    aliases: dict[str, set[str]] = collections.defaultdict(set)
    for raw, ids in raw_to_sources.items():
        name = normalise_venue(raw)
        if not name:
            continue
        canonical[name].extend(ids)
        if raw != name:
            aliases[name].add(raw)

    stats = {
        "sources_total": len(rows),
        "sources_with_venue": sum(len(v) for v in canonical.values()),
        "sources_without_venue": no_venue,
        "raw_distinct": len(raw_to_sources),
        "canonical_distinct": len(canonical),
        "venues_created": 0,
        "edges_created": 0,
        "edges_already_present": 0,
    }

    if dry_run:
        return stats

    existing_edges = {
        r[0]
        for r in conn.execute(
            "SELECT source_id FROM edges WHERE kind = 'published-at'"
        ).fetchall()
    }

    for name, source_ids in sorted(canonical.items()):
        venue_type = VENUE_TYPES.get(name, DEFAULT_VENUE_TYPE)
        venue_id, created = resolve_or_create_venue(conn, name, venue_type)
        if created:
            stats["venues_created"] += 1

        if aliases[name]:
            node_attrs = json.loads(
                conn.execute("SELECT attrs FROM nodes WHERE id = ?", (venue_id,)).fetchone()[0]
            )
            merged = sorted(set(node_attrs.get("aliases") or []) | aliases[name])
            node_attrs["aliases"] = merged
            conn.execute(
                "UPDATE nodes SET attrs = ? WHERE id = ?",
                (json.dumps(node_attrs), venue_id),
            )

        for source_id in source_ids:
            if source_id in existing_edges:
                stats["edges_already_present"] += 1
                continue
            # Direct INSERT rather than graph.engine.add_edge: add_edge is fine
            # here, but a plain INSERT keeps the migration independent of the
            # cycle checks, and the UNIQUE (kind, source_id, target_id)
            # constraint gives idempotency for free.
            conn.execute(
                "INSERT OR IGNORE INTO edges (kind, source_id, target_id, attrs) "
                "VALUES ('published-at', ?, ?, '{}')",
                (source_id, venue_id),
            )
            stats["edges_created"] += 1

            # Normalise the retained raw string in place so the attrs value and
            # the Venue node agree.
            conn.execute(
                "UPDATE nodes SET attrs = json_set(attrs, '$.venue', ?) WHERE id = ?",
                (name, source_id),
            )

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("db", type=pathlib.Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(str(args.db))
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        stats = backfill(conn, dry_run=args.dry_run)
        if not args.dry_run:
            conn.commit()
    finally:
        conn.close()

    label = "DRY RUN" if args.dry_run else "APPLIED"
    print(f"[{label}]")
    for k, v in stats.items():
        print(f"  {k:26s} {v}")


if __name__ == "__main__":
    main()
