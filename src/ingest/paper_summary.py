"""Paper summary storage (IFC-KK-PAPER-SUMMARY, ALG-KK-SUMMARY-SET).

Owns every write to a PaperSummary so that the LLM extractor, the web editor and
any future importer go through one place, validate against one vocabulary, and
stamp provenance the same way. The completeness verdict reads the state rather
than the text, so a summary written past this module with an unvetted state
would make that verdict unanswerable rather than merely untidy.

A PaperSummary is its own node kind (decision D-F), linked to the paper it
describes by a `summarizes-paper` edge, and there is AT MOST ONE per Source.
That cardinality is what makes `set_summary` idempotent: a repeat call updates
the node already attached rather than creating a second one.

SUPERSEDES ResearchBrief (decision D-9). An earlier revision of this module held
that the two kinds were distinct permanently, on the reasoning that a brief
summarises a *Concept* while a summary summarises a paper. Measurement overturned
that: every one of the 458 brief-bearing papers carried exactly one brief, so the
brief was per-paper in practice, and 935 of its 937 summarizes-for edges were
derivable from the Source <-Evidence <-Concept chain the graph already holds while
the other 2 dangled. They were one concept modelled twice. The brief's key_ideas,
relevance and methodology now live here as optional fields, and the brief kind is
retired.

`summary` is deliberately absent from REQUIRED_ATTRS["Source"], for the reason
the abstract fields are: requiring it would invalidate every existing Source node
and every add_node call in the ingest pipeline.

Two carve-outs, both mandatory and both already proven necessary elsewhere:

1. The Source is NOT revalidated after a write. validate_node against Source
   applies rules.check_source_has_advisory, which the great majority of real
   Sources do not satisfy; revalidating here would reject a good summary for an
   unrelated pre-existing gap. src/ingest/source_abstract.py documents the same
   carve-out, and tests/test_paper_summary.py proves it rather than asserting it.

2. Summary nodes and edges are removed with direct SQL, never with
   graph.engine.delete_edge or graph.engine.delete_node. Both re-run
   validate_node internally — delete_edge on the edge's source node, delete_node
   on every dependent — so either would reach carve-out 1 through the back door
   and raise AdmissibilityError on a Source that merely lacks an Advisory.
   venue_store._clear_published_at exists for exactly this reason.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

from graph.engine import add_edge, add_node, get_node, update_node_attrs
from graph.schema import ID_PREFIXES

# Decision D-E. FROZEN and ORDERED, and the order is load-bearing because
# IFC-KK-PAPER-COMPLETENESS reads the state.
#
# The first four run by increasing human warrant:
#     absent < llm-extracted < human-reviewed < human-authored
#
# "rejected" sits deliberately OUTSIDE that order. A human looked at the text and
# refused it, which says more than never having had one, but it still leaves the
# paper without a usable summary — so for the presence test it ranks with
# "absent", not above it. Adding a sixth value means amending
# INV-KK-SUMMARY-STATE-VOCABULARY and saying which side of PRESENT_STATES it
# falls on; the vocabulary is closed, not open.
SUMMARY_STATES = (
    "absent",
    "llm-extracted",
    "human-reviewed",
    "human-authored",
    "rejected",
)

# The exact presence test read by the completeness verdict.
PRESENT_STATES = ("llm-extracted", "human-reviewed", "human-authored")

# States that assert a human acted, and so must name which human.
REVIEWED_STATES = ("human-reviewed", "human-authored")


def summary_is_present(state: str | None) -> bool:
    """Whether a state counts as the paper having a summary.

    The single definition of the presence test, so the store, the verdict and the
    web layer cannot disagree about what "has a summary" means.
    """
    return state in PRESENT_STATES


@dataclass
class SummaryResult:
    """What the domain functions hand back to their callers."""

    ok: bool
    source_id: str
    summary_id: str = ""
    state: str = ""
    text: str = ""
    created: bool = False
    rows: int = 0
    error: str | None = None


def _summary_id_for(source_id: str) -> str:
    """One summary per Source, so the Source id determines the summary id."""
    stem = source_id
    for prefix in (ID_PREFIXES["Source"], "source-"):
        if stem.startswith(prefix):
            stem = stem[len(prefix):]
            break
    return f"{ID_PREFIXES['PaperSummary']}{stem}"


def _find_summary_ids(conn: sqlite3.Connection, source_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT source_id FROM edges WHERE kind = 'summarizes-paper' AND target_id = ? "
        "ORDER BY id",
        (source_id,),
    ).fetchall()
    return [r[0] for r in rows]


def _delete_summary(conn: sqlite3.Connection, summary_id: str) -> None:
    """Remove a summary node and its edges with direct SQL.

    graph.engine.delete_node would re-run validate_node on every dependent of the
    node, and graph.engine.delete_edge would re-run it on the edge's source; both
    reach the missing-Advisory rule on the Source. See carve-out 2 in the module
    docstring.
    """
    conn.execute(
        "DELETE FROM edges WHERE source_id = ? OR target_id = ?", (summary_id, summary_id)
    )
    conn.execute("DELETE FROM nodes WHERE id = ?", (summary_id,))


def get_summary(conn: sqlite3.Connection, source_id: str) -> dict | None:
    """Return the PaperSummary attached to a Source, or None."""
    ids = _find_summary_ids(conn, source_id)
    if not ids:
        return None
    return get_node(conn, ids[0])


def set_summary(
    conn: sqlite3.Connection,
    source_id: str,
    text: str,
    state: str,
    model: str = "",
    reviewed_by: str = "",
    recompute: bool = False,
    key_ideas: list[str] | None = None,
    relevance: str = "",
    methodology: str = "",
) -> SummaryResult:
    """Create or replace the single PaperSummary attached to a Source.

    Implements ALG-KK-SUMMARY-SET. Idempotent: because at most one PaperSummary
    exists per Source, a repeat call updates that node and creates no second one.

    Raises ValueError if `state` is outside SUMMARY_STATES, if `source_id` names
    no node or names a node of another kind, if a state in PRESENT_STATES is
    given empty text, if the state is "absent" but text was supplied, or if a
    state in REVIEWED_STATES names no reviewer.

    The Source is not revalidated after the write; see carve-out 1.

    `key_ideas`, `relevance` and `methodology` are the three optional fields
    absorbed from ResearchBrief under D-9. Each is written only when supplied, so
    a row from the single-key extractor is not given empty placeholders for
    fields it never had, and a caller that omits them on an update does not erase
    what a previous call stored. None of the three carries prose, so none of them
    satisfies the non-empty-text rule that PRESENT_STATES imposes - which is why a
    migrated brief lands at state "absent" under D-10 option (b).

    `recompute` refreshes the paper's completeness verdict, defaulting to OFF
    for the reason set_abstract documents: bulk writers end with one batch
    pass, the single-paper web editor passes True.
    """
    if state not in SUMMARY_STATES:
        raise ValueError(
            f"Invalid summary state '{state}'. Must be one of: " + ", ".join(SUMMARY_STATES)
        )

    cleaned = text.strip() if text else ""
    if state in PRESENT_STATES and not cleaned:
        raise ValueError(f"Summary must be non-empty for state '{state}'")
    # A summary that is "absent" and yet carries text would make the state and the
    # content disagree, and the verdict trusts the state.
    if state == "absent" and cleaned:
        raise ValueError("State 'absent' cannot carry summary text")
    if state in REVIEWED_STATES and not reviewed_by:
        raise ValueError(f"State '{state}' requires reviewed_by")

    node = get_node(conn, source_id)
    if node is None or node["kind"] != "Source":
        raise ValueError(f"Source node '{source_id}' does not exist")

    attrs = {
        "text": cleaned,
        "state": state,
        "model": model,
        "reviewed_by": reviewed_by,
        "set_at": date.today().isoformat(),
    }
    # Written only when supplied. update_node_attrs merges, so omitting a field
    # here leaves whatever a previous call stored rather than blanking it.
    if key_ideas:
        attrs["key_ideas"] = list(key_ideas)
    if relevance:
        attrs["relevance"] = relevance
    if methodology:
        attrs["methodology"] = methodology

    existing = _find_summary_ids(conn, source_id)
    if existing:
        summary_id = existing[0]
        # Defensive: the cardinality is a design rule, not a database constraint.
        # If a second summary ever appears, drop it rather than let the reader pick
        # one arbitrarily. Direct SQL per carve-out 2.
        for extra in existing[1:]:
            _delete_summary(conn, extra)
        update_node_attrs(conn, summary_id, attrs)
        created = False
    else:
        summary_id = _summary_id_for(source_id)
        add_node(conn, summary_id, "PaperSummary", attrs)
        add_edge(conn, "summarizes-paper", summary_id, source_id)
        created = True

    if recompute:
        from ingest.paper_completeness import recompute_paper_if_present

        recompute_paper_if_present(conn, source_id)

    return SummaryResult(
        ok=True,
        source_id=source_id,
        summary_id=summary_id,
        state=state,
        text=cleaned,
        created=created,
        rows=1,
    )


def clear_summary(conn: sqlite3.Connection, source_id: str) -> SummaryResult:
    """Remove the PaperSummary attached to a Source, if there is one.

    Idempotent: a call for a Source with no summary reports rows=0 rather than
    raising. Uses direct SQL per carve-out 2.
    """
    ids = _find_summary_ids(conn, source_id)
    for summary_id in ids:
        _delete_summary(conn, summary_id)
    return SummaryResult(ok=True, source_id=source_id, rows=len(ids))
