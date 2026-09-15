"""Per-paper completeness verdict (IFC-KK-PAPER-COMPLETENESS, ALG-KK-COMPLETENESS-COMPUTE).

Computes and persists a small, purely informational record of what a paper has
and has not got. One function owns the computation so that the batch pass, the
web write points and any future caller cannot disagree about what a dimension
means.

WHAT THIS IS NOT, and the two invariants that say so:

INV-KK-COMPLETENESS-ADVISORY. The verdict gates nothing. No caller may branch on
it to permit or refuse an action: not authorisation, not ingest admission, not an
HTTP status, not a filter that removes a paper from a listing. Its permitted uses
are exhaustively display, sort order and reporting. In particular links_invariant
is RECORDED AND NEVER GATING (decision D-B). If a verdict should ever start
blocking something, that is a decision taken by deleting that invariant, not a
refactor.

INV-KK-COMPLETENESS-STALENESS-TOLERATED. A verdict may lawfully disagree with the
graph it describes. There is no change tracking, no trigger and no invalidation
graph here, deliberately: the operator's requirement was explicitly that accurate,
completely up-to-date statistics are not needed, and guaranteeing currency across
a 3,500-paper corpus buys nothing this feature uses. computed_at is stamped so a
reader can see how stale a verdict is; it is not a promise that it is fresh. A
stale verdict is never a bug.

DIMENSIONS are BINARY PRESENCE (decision D-A) — never counts, never thresholds,
never scores. The first thing anyone would do with a number is compare it against
a threshold, which is what D-A ruled out.

Two measured facts about today's corpus, recorded in IFC-KK-PAPER-COMPLETENESS
and repeated here because they look like bugs and are not:

  links_subsystem is REDUNDANT with links_concept and cannot currently disagree
  with it. All 97 Concepts carry a belongs-to Subsystem, so both returned 1,433
  of 3,482 papers. No rule enforces that, which is why decision D-7 kept it as a
  separate, honestly named dimension rather than deriving or dropping it.

  links_invariant is VACUOUS for papers. Only 31 Sources reach a KernelInvariant
  and every one is source_type kernel-doc, so it is false for all 3,482 papers.

Neither is fixed by dropping a dimension or retuning a definition.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from datetime import date

from graph.engine import add_edge, add_node, get_node, update_node_attrs
from graph.schema import ID_PREFIXES

# Which Sources are papers. The other 92 of the 3,574 Sources are not, and get no
# verdict rather than a verdict full of falses.
PAPER_SOURCE_TYPES = ("preprint", "conference-paper", "conference-proceedings")

# The six binary dimensions, in the order IFC-KK-PAPER-COMPLETENESS declares them.
# summary_state is carried alongside but is NOT in here: it is the raw state
# value, not a boolean, so that a reader can tell a model-written summary from a
# human-written one without a second query.
BINARY_DIMENSIONS = (
    "has_abstract",
    "has_summary",
    "links_concept",
    "links_subsystem",
    "links_kernel",
    "links_invariant",
)


@dataclass
class CompletenessVerdict:
    """IFC-KK-PAPER-COMPLETENESS. Informational: nothing branches on this."""

    source_id: str
    computed_at: str
    has_abstract: bool = False
    has_summary: bool = False
    summary_state: str = "absent"
    links_concept: bool = False
    links_subsystem: bool = False
    links_kernel: bool = False
    links_invariant: bool = False
    verdict_id: str = ""
    created: bool = False

    def as_attrs(self) -> dict:
        d = asdict(self)
        d.pop("source_id")
        d.pop("verdict_id")
        d.pop("created")
        return d

    @property
    def dimensions(self) -> dict[str, bool]:
        return {k: getattr(self, k) for k in BINARY_DIMENSIONS}


def _verdict_id_for(source_id: str) -> str:
    stem = source_id
    for prefix in (ID_PREFIXES["Source"], "source-"):
        if stem.startswith(prefix):
            stem = stem[len(prefix):]
            break
    return f"{ID_PREFIXES['PaperCompleteness']}{stem}"


def _find_verdict_ids(conn: sqlite3.Connection, source_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT source_id FROM edges WHERE kind = 'completeness-of' AND target_id = ? "
        "ORDER BY id",
        (source_id,),
    ).fetchall()
    return [r[0] for r in rows]


def _delete_verdict(conn: sqlite3.Connection, verdict_id: str) -> None:
    """Direct SQL, for the reason paper_summary._delete_summary documents.

    graph.engine.delete_node re-runs validate_node on every dependent and
    delete_edge on the edge's source, either of which reaches
    rules.check_source_has_advisory on a Source that merely lacks an Advisory.
    """
    conn.execute(
        "DELETE FROM edges WHERE source_id = ? OR target_id = ?", (verdict_id, verdict_id)
    )
    conn.execute("DELETE FROM nodes WHERE id = ?", (verdict_id,))


def is_paper(node: dict | None) -> bool:
    return (
        node is not None
        and node["kind"] == "Source"
        and node["attrs"].get("source_type") in PAPER_SOURCE_TYPES
    )


# --- the dimensions ---------------------------------------------------------
#
# Each is an existence test and nothing more. The traversals:
#   concepts    Source <-sourced-from- Evidence <-extracted-from- Concept
#   subsystem   ... then Concept -belongs-to-> Subsystem
#   kernel      ... then Concept -implemented-in-> Kernel
#   invariant   Source <-sourced-from- Evidence <-extracted-from- KernelInvariant
# KernelInvariant hangs off Evidence directly, exactly as Concept does; it is not
# reached through a Concept.

_EXTRACTED_KIND_SQL = """
SELECT 1 FROM edges e1
  JOIN edges e2 ON e2.kind = 'extracted-from' AND e2.target_id = e1.source_id
  JOIN nodes n  ON n.id = e2.source_id AND n.kind = ?
 WHERE e1.kind = 'sourced-from' AND e1.target_id = ?
 LIMIT 1
"""

_CONCEPT_HOP_SQL = """
SELECT 1 FROM edges e1
  JOIN edges e2 ON e2.kind = 'extracted-from' AND e2.target_id = e1.source_id
  JOIN nodes cn ON cn.id = e2.source_id AND cn.kind = 'Concept'
  JOIN edges e3 ON e3.kind = ? AND e3.source_id = cn.id
  JOIN nodes tn ON tn.id = e3.target_id AND tn.kind = ?
 WHERE e1.kind = 'sourced-from' AND e1.target_id = ?
 LIMIT 1
"""


def _exists(conn: sqlite3.Connection, sql: str, params: tuple) -> bool:
    return conn.execute(sql, params).fetchone() is not None


def compute_completeness(conn: sqlite3.Connection, source_id: str) -> CompletenessVerdict:
    """Compute the verdict for one paper without persisting it.

    Raises ValueError if `source_id` names no node, names a node of another kind,
    or names a Source that is not a paper.

    Read-only. Never raises on a paper that scores badly: an all-false verdict is
    a description, not an error (INV-KK-COMPLETENESS-ADVISORY).
    """
    from ingest.paper_summary import summary_is_present

    node = get_node(conn, source_id)
    if node is None or node["kind"] != "Source":
        raise ValueError(f"Source node '{source_id}' does not exist")
    if not is_paper(node):
        raise ValueError(
            f"Source '{source_id}' is not a paper "
            f"(source_type={node['attrs'].get('source_type')!r}); "
            "only " + ", ".join(PAPER_SOURCE_TYPES) + " carry a verdict"
        )

    summary_row = conn.execute(
        "SELECT json_extract(n.attrs, '$.state') FROM edges e "
        "JOIN nodes n ON n.id = e.source_id "
        "WHERE e.kind = 'summarizes-paper' AND e.target_id = ? ORDER BY e.id LIMIT 1",
        (source_id,),
    ).fetchone()
    state = summary_row[0] if summary_row and summary_row[0] else "absent"

    return CompletenessVerdict(
        source_id=source_id,
        computed_at=date.today().isoformat(),
        has_abstract=bool((node["attrs"].get("abstract") or "").strip()),
        has_summary=summary_is_present(state),
        summary_state=state,
        links_concept=_exists(conn, _EXTRACTED_KIND_SQL, ("Concept", source_id)),
        links_subsystem=_exists(
            conn, _CONCEPT_HOP_SQL, ("belongs-to", "Subsystem", source_id)
        ),
        links_kernel=_exists(
            conn, _CONCEPT_HOP_SQL, ("implemented-in", "Kernel", source_id)
        ),
        links_invariant=_exists(conn, _EXTRACTED_KIND_SQL, ("KernelInvariant", source_id)),
    )


def recompute_paper(conn: sqlite3.Connection, source_id: str) -> CompletenessVerdict:
    """Compute and persist the verdict for one paper.

    Implements ALG-KK-COMPLETENESS-COMPUTE. Idempotent: at most one verdict exists
    per Source, so a second run over an unchanged graph overwrites the same node
    with the same dimensions and creates no duplicate node or edge.

    The Source is not revalidated after the write, for the reason
    paper_summary and source_abstract both document: most real Sources have no
    Advisory, and revalidating would reject a good verdict for an unrelated gap.
    """
    verdict = compute_completeness(conn, source_id)
    attrs = verdict.as_attrs()

    existing = _find_verdict_ids(conn, source_id)
    if existing:
        verdict.verdict_id = existing[0]
        for extra in existing[1:]:
            _delete_verdict(conn, extra)
        update_node_attrs(conn, verdict.verdict_id, attrs)
        verdict.created = False
    else:
        verdict.verdict_id = _verdict_id_for(source_id)
        add_node(conn, verdict.verdict_id, "PaperCompleteness", attrs)
        add_edge(conn, "completeness-of", verdict.verdict_id, source_id)
        verdict.created = True

    return verdict


def get_verdict(conn: sqlite3.Connection, source_id: str) -> dict | None:
    """Return the stored verdict for a paper, or None. Never computes."""
    ids = _find_verdict_ids(conn, source_id)
    if not ids:
        return None
    return get_node(conn, ids[0])


def recompute_paper_if_present(conn: sqlite3.Connection, source_id: str) -> None:
    """Best-effort recompute for a write point.

    Used where a human has just edited one paper and expects the page to reflect
    it. Silently does nothing for a Source that is not a paper, because a
    non-paper carries no verdict and a write to one is not an error. Never raises:
    a failure to refresh an advisory verdict must not fail the edit that
    triggered it, which is INV-KK-COMPLETENESS-ADVISORY applied to this module's
    own callers.
    """
    try:
        recompute_paper(conn, source_id)
    except ValueError:
        return
