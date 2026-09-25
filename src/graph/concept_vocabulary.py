"""The curated Concept vocabulary: matching against it, and what misses it.

INV-KK-CONCEPT-ADMISSION says a Concept is an established class and that
"Papers are linked to a curated vocabulary rather than minting a concept each".
This module is how a path links rather than mints.

THE MATCHER IS NOT NEW. Its three tiers — exact on the normalised name, then
prefix in either direction, then Levenshtein within a small distance — are the
ones src/ingest/claim_extractor.py has used on the discourse path since it was
written. It moved here on 2026-09-22 so the paper extractor could share it
instead of growing a second implementation; claim_extractor re-exports every
name below, so its callers and tests import exactly what they imported before.

EXACT MATCHING ALONE DOES NOT WORK, MEASURED. A matcher added to extractor.py
on 2026-09-21 required an exact normalised hit and matched 0 of 114 candidates
across two batches. Two things were wrong and only one of them was the matcher:
the model had never been SHOWN the vocabulary, so it proposed "uSTM" and
"BR-WFD Algorithm", which no amount of fuzziness rescues. Showing it the names
is build_vocabulary_context; matching loosely is what makes the showing survive
paraphrase.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

#: Levenshtein tolerance. Two edits catches plurals, a dropped hyphen and a
#: British/American spelling; it does not catch a different concept.
DEFAULT_MAX_DISTANCE = 2


def normalise_concept_name(name: str) -> str:
    """The key a concept name is matched on.

    casefold rather than lower: the corpus carries names taken from paper
    titles and the difference matters for the few that are not plain ASCII.
    """
    return " ".join(str(name or "").split()).casefold()


def levenshtein_distance(s: str, t: str) -> int:
    """Edit distance between two strings."""
    if len(s) < len(t):
        return levenshtein_distance(t, s)
    if not t:
        return len(s)
    prev = list(range(len(t) + 1))
    for i, sc in enumerate(s):
        curr = [i + 1]
        for j, tc in enumerate(t):
            cost = 0 if sc == tc else 1
            curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[-1]


def resolve_concept_names(conn: sqlite3.Connection) -> dict[str, str]:
    """normalised concept name -> node id, for every Concept in the graph."""
    rows = conn.execute(
        "SELECT id, json_extract(attrs, '$.name') FROM nodes WHERE kind = 'Concept'"
    ).fetchall()
    return {normalise_concept_name(r[1]): r[0] for r in rows if r[1]}


def fuzzy_match_concept(
    query: str, name_to_id: dict[str, str],
    max_distance: int = DEFAULT_MAX_DISTANCE,
) -> str | None:
    """Three-tier match: exact, prefix either way, then Levenshtein.

    Returns the concept node id, or None when nothing is close enough. None is
    a normal outcome and means "this is a candidate", not "this failed".
    """
    q = normalise_concept_name(query)
    if not q:
        return None
    if q in name_to_id:
        return name_to_id[q]
    for name, cid in name_to_id.items():
        if name.startswith(q) or q.startswith(name):
            return cid
    best_id, best = None, max_distance + 1
    for name, cid in name_to_id.items():
        d = levenshtein_distance(q, name)
        if d <= max_distance and d < best:
            best, best_id = d, cid
    return best_id


def build_vocabulary_context(conn: sqlite3.Connection) -> str:
    """The vocabulary, for the prompt.

    The half that was missing on 2026-09-21: a model asked to name concepts
    without being told which ones exist will name the paper's own artifact,
    and then no matcher can help. Mirrors
    claim_extractor.build_claim_extraction_context, which has always done this.
    """
    # INV-KK-VOCABULARY-EXCLUDES-RETIRED. A WHERE clause and not a post-filter:
    # this string goes into a prompt and the cost is tokens — measured
    # 2026-09-25, the vocabulary block is 595 tokens across 3,325 papers, more
    # than the paper text itself, and it grows with every harvest.
    #
    # THIS IS THE DIFFERENCE BETWEEN RETIRING A CONCEPT AND PRETENDING TO.
    # Without it a curator could retire an entry and the next extraction run
    # would put it straight back in front of the model under "choose concept
    # names from this list", collect fresh links, and rise back through the
    # admission census. COALESCE because absent is NOT retired: all 97 Concepts
    # that predate the field stay in the vocabulary.
    rows = conn.execute(
        "SELECT json_extract(attrs, '$.name') FROM nodes WHERE kind = 'Concept' "
        "AND COALESCE(json_extract(attrs, '$.curation_state'), '') != 'retired'"
    ).fetchall()
    names = sorted({r[0] for r in rows if r[0]})
    if not names:
        return "No known kernel concepts yet."
    return (
        "KNOWN KERNEL CONCEPTS — choose concept names from this list wherever "
        "the document is about one of them. Do NOT invent a name for this "
        "paper's own system, tool or algorithm; those are recorded elsewhere. "
        "If the document is about something genuinely absent from this list, "
        "name it as a general class rather than as a product.\n" + ", ".join(names)
    )


# --- the candidate queue (IFC-KK-CONCEPT-CANDIDATE) -------------------------


@dataclass
class Candidate:
    """A name the extractor proposed and the vocabulary did not contain."""
    normalised: str
    name: str
    sources: int
    evidence_ids: list[str]


def record_candidate(
    conn: sqlite3.Connection, name: str, evidence_id: str, proposed_at: str
) -> bool:
    """Queue an unmatched name against the Evidence that proposed it.

    One row per (name, Evidence) PAIR, which is what makes the distinct-Source
    count below possible — and that count is the same weight test
    INV-KK-CONCEPT-ADMISSION applies to an admitted Concept, asked before the
    node exists rather than after. Returns False when this pair is already
    queued, so a re-run does not inflate the evidence for a candidate.
    """
    key = normalise_concept_name(name)
    if not key or not evidence_id:
        return False
    cur = conn.execute(
        "INSERT OR IGNORE INTO concept_candidates "
        "(normalised, name, evidence_id, proposed_at) VALUES (?, ?, ?, ?)",
        (key, name.strip(), evidence_id, proposed_at))
    return cur.rowcount > 0


def candidate_ranking(conn: sqlite3.Connection, limit: int = 50) -> list[Candidate]:
    """Queued names, most independently-proposed first.

    A name two distinct Sources reached for on their own is worth a human
    minute. A name one paper invented for its own artifact is not, and sorts
    to the bottom where it can be ignored rather than deleted.
    """
    rows = conn.execute(
        "SELECT c.normalised, MIN(c.name), "
        "       COUNT(DISTINCT COALESCE(s.target_id, c.evidence_id)), "
        "       GROUP_CONCAT(DISTINCT c.evidence_id) "
        "FROM concept_candidates c "
        "LEFT JOIN edges s ON s.source_id = c.evidence_id "
        "                 AND s.kind = 'sourced-from' "
        "GROUP BY c.normalised ORDER BY 3 DESC, 1 LIMIT ?", (limit,)
    ).fetchall()
    return [Candidate(normalised=r[0], name=r[1], sources=r[2],
                      evidence_ids=(r[3] or "").split(",")) for r in rows]



#: Every attribute a Concept node requires. A promotion that cannot supply all
#: six is refused rather than defaulted: a Concept with an empty
#: design_rationale is exactly the thin entry the admission rule exists to keep
#: out, and a blank string would satisfy the schema while saying nothing.
PROMOTION_REQUIRED_ATTRS = (
    "name", "description", "artifact_class",
    "key_properties", "tradeoffs", "design_rationale",
)


def candidate_sources(conn: sqlite3.Connection, normalised: str) -> int:
    """How many DISTINCT Sources proposed this queued name.

    The same weight test INV-KK-CONCEPT-ADMISSION applies to an admitted
    Concept, asked before the node exists. Evidence with no sourced-from edge
    counts as its own source, matching candidate_ranking, so an orphan Evidence
    cannot quietly contribute zero and drag a candidate below the bar.
    """
    row = conn.execute(
        "SELECT COUNT(DISTINCT COALESCE(s.target_id, c.evidence_id)) "
        "FROM concept_candidates c "
        "LEFT JOIN edges s ON s.source_id = c.evidence_id AND s.kind = 'sourced-from' "
        "WHERE c.normalised = ?", (normalised,)
    ).fetchone()
    return row[0] if row else 0


def promote_candidate(
    conn: sqlite3.Connection,
    normalised: str,
    attrs: dict,
    admitted_by: str,
    seminal_source_id: str = "",
    subsystem_id: str = "",
) -> str:
    """Admit a queued candidate into the vocabulary. Returns the new Concept id.

    ALG-KK-WEB-CONCEPT-ADMIT's store half, here rather than in the route so the
    rule is testable without a router and cannot be restated by a second caller.

    THE ADMISSION RULE IS ENFORCED HERE, NOT ADVERTISED HERE
    (INV-KK-WEB-ADMIT-HONOURS-ADMISSION). A candidate below ADMISSIBLE_WEIGHT is
    refused unless the caller names the Source that defined the class. All 43
    candidates queued on 2026-09-22 sit at exactly one Source, so this branch is
    the normal path and not an edge case — which is precisely why it may not be
    softened. A promotion form that wrote a Concept on request would be a faster
    way to produce the soup the extractor was stopped from producing.

    THE MARKER IS NEVER INFERRED, per IFC-KK-CONCEPT-SEMINAL-MARKER. At weight 1
    there is exactly one proposing Source and defaulting to it would look
    helpful; it would also promote every single candidate automatically and make
    the threshold meaningless. The caller must name it, and naming something
    that is not a Source is an error rather than a silent skip.

    ONE TRANSACTION. The node, the subsystem edge, the marker and the removal of
    the queue rows either all land or none do — a half-applied promotion would
    leave a Concept that the queue still offers for admission.
    """
    from graph.engine import add_edge, add_node
    from graph.rules import ADMISSIBLE_WEIGHT

    missing = [k for k in PROMOTION_REQUIRED_ATTRS
               if attrs.get(k) in (None, "", [], {})]
    if missing:
        raise ValueError(
            "A Concept needs every required attribute; missing or blank: "
            + ", ".join(sorted(missing)))
    if not admitted_by:
        raise ValueError("A promotion must record who admitted it")

    queued = conn.execute(
        "SELECT COUNT(*) FROM concept_candidates WHERE normalised = ?", (normalised,)
    ).fetchone()[0]
    if not queued:
        raise ValueError(f"No candidate queued under '{normalised}'")

    weight = candidate_sources(conn, normalised)
    if weight < ADMISSIBLE_WEIGHT:
        if not seminal_source_id:
            raise ValueError(
                f"'{attrs['name']}' is proposed by {weight} source(s), below the "
                f"admission threshold of {ADMISSIBLE_WEIGHT}. Admitting it "
                "requires naming the Source that defined the concept "
                "(INV-KK-CONCEPT-ADMISSION, IFC-KK-CONCEPT-SEMINAL-MARKER).")
        row = conn.execute(
            "SELECT kind FROM nodes WHERE id = ?", (seminal_source_id,)).fetchone()
        if row is None or row[0] != "Source":
            raise ValueError(
                f"Seminal marker must name a Source; '{seminal_source_id}' is "
                + (f"a {row[0]}" if row else "not in the graph"))

    if normalise_concept_name(attrs["name"]) != normalised:
        raise ValueError(
            f"Name '{attrs['name']}' does not normalise to the queued "
            f"candidate '{normalised}'")
    # resolve_concept_names, not the extractor's find_concept_by_name: graph
    # must not import from ingest, and this module already owns the mapping.
    if normalised in resolve_concept_names(conn):
        raise ValueError(f"A Concept named '{attrs['name']}' already exists")

    concept_id = f"concept-{uuid4().hex[:12]}"
    add_node(conn, concept_id, "Concept", {
        **{k: attrs[k] for k in PROMOTION_REQUIRED_ATTRS},
        "admitted_by": admitted_by,
        "admitted_at": datetime.now(timezone.utc).date().isoformat(),
    })
    if subsystem_id:
        add_edge(conn, "belongs-to", concept_id, subsystem_id)
    if seminal_source_id:
        add_edge(conn, "defined-by", concept_id, seminal_source_id)
    conn.execute("DELETE FROM concept_candidates WHERE normalised = ?", (normalised,))
    return concept_id


def dismiss_candidate(conn: sqlite3.Connection, normalised: str) -> int:
    """Drop a queued name a curator judged not to be a Concept.

    Returns the number of rows removed. Dismissal is not a graph write: the
    candidate never became a node, so there is nothing to retract. It is
    deliberately not a tombstone — the extractor re-queues a name the next time
    a paper proposes it, and a permanently suppressed name would hide a concept
    that later earns admission on new evidence.
    """
    cur = conn.execute(
        "DELETE FROM concept_candidates WHERE normalised = ?", (normalised,))
    return cur.rowcount


# --- the kernel vocabulary (IFC-KK-PAPER-KERNEL) ----------------------------


def resolve_kernel_names(conn: sqlite3.Connection) -> dict[str, str]:
    """normalised kernel name -> node id, for every Kernel in the graph."""
    rows = conn.execute(
        "SELECT id, json_extract(attrs, '$.name') FROM nodes WHERE kind = 'Kernel'"
    ).fetchall()
    return {normalise_concept_name(r[1]): r[0] for r in rows if r[1]}


def build_kernel_context(conn: sqlite3.Connection) -> str:
    """The kernel vocabulary, for the prompt.

    Four names on 2026-09-22, so this costs almost nothing to include — and the
    failure of NOT including a vocabulary is already measured: a matcher added
    on 2026-09-21 required an exact name the model had never been shown and
    matched 0 of 114 candidates.

    "none" IS AN EXPLICIT, PROMINENT OPTION AND THAT IS THE POINT. This corpus
    is broad systems and security research, not kernel documentation; the
    concept vocabulary matched 0 of 43 proposed names on 2026-09-22, which is
    the same coverage gap seen from the other side. A model forced to choose
    from a four-item list would manufacture a Linux association for every paper
    that is not about a kernel at all, and those edges would be
    indistinguishable from real ones. A field empty for most papers is a true
    field.
    """
    names = sorted(
        r[0] for r in conn.execute(
            "SELECT json_extract(attrs, '$.name') FROM nodes WHERE kind = 'Kernel'"
        ).fetchall() if r[0]
    )
    if not names:
        return ""
    return (
        "KERNELS — if this document concerns one of these kernels specifically, "
        'name it EXACTLY as written here under the key "kernel". If it concerns '
        "none of them, concerns operating systems generally, or is not about a "
        'kernel at all, answer "none". Most documents are "none"; that is the '
        "expected answer and is more useful than a guess. Do NOT name a kernel "
        "that is not in this list.\n" + ", ".join(names)
    )


def match_kernel_name(conn: sqlite3.Connection, name: str) -> str | None:
    """The Kernel node id for a name the model returned, or None.

    EXACT ON THE NORMALISED NAME, deliberately unlike the concept matcher,
    which fuzzes to Levenshtein 2. The kernel vocabulary is four proper nouns
    given verbatim in the prompt, so a near-miss is not a paraphrase to be
    rescued — at distance 2 "Linux Mainline" and a hypothetical "Linux
    Mainline 6" would collide, and associating a paper with the wrong kernel is
    worse than associating it with none.

    "none", the empty string and anything absent from the table all return
    None, and the caller writes no edge. Nothing here creates a Kernel node:
    INV-KK-PAPER-KERNEL-MATCHED forbids extraction changing how many exist,
    for the same reason INV-KK-EXTRACT-CONCEPT-MATCHED forbids it for concepts.
    """
    key = normalise_concept_name(name or "")
    if not key or key == "none":
        return None
    return resolve_kernel_names(conn).get(key)

__all__ = [
    "Candidate", "DEFAULT_MAX_DISTANCE", "PROMOTION_REQUIRED_ATTRS",
    "build_kernel_context", "build_vocabulary_context", "candidate_sources",
    "dismiss_candidate", "match_kernel_name", "resolve_kernel_names",
    "promote_candidate",
    "candidate_ranking", "fuzzy_match_concept", "levenshtein_distance",
    "normalise_concept_name", "record_candidate", "resolve_concept_names",
]


# ---------------------------------------------------------------------------
# Curation state (IFC-KK-CONCEPT-CURATION-STATE)
# ---------------------------------------------------------------------------

#: The closed vocabulary for Concept.attrs["curation_state"], per
#: INV-KK-CONCEPT-CURATION-VOCABULARY. Modelled on
#: ingest.paper_summary.SUMMARY_STATES, which closes the PaperSummary state set
#: for the same reason: a value outside the set is not cosmetic, it makes every
#: question asked of the field unanswerable.
#:
#: A fourth value means amending the invariant and saying what it asserts about
#: human attention, which is the only thing this field measures.
CURATION_STATES = ("harvested", "reviewed", "retired")

#: The state a Concept is in when nobody has read it. ABSENT MEANS THIS — it is
#: not a fourth state. All 97 Concepts as of 2026-09-25 carry no curation
#: attribute at all, and "no human has reviewed this" is true of every one of
#: them, so reading absent as anything else would be reading it as false.
DEFAULT_CURATION_STATE = "harvested"

#: States that assert a human acted, and so must name which human and when.
#: An unsigned review is not a review.
SIGNED_CURATION_STATES = ("reviewed",)

#: The four optional attributes IFC-KK-CONCEPT-CURATION-STATE defines. They are
#: NOT added to schema.REQUIRED_ATTRS["Concept"] and must never be: add_node
#: rejects a Concept missing any required attribute, so a seventh requirement
#: would make all 97 existing Concepts unwritable at a stroke.
CURATION_ATTRS = ("curation_state", "harvest_batch", "reviewed_by", "reviewed_at")


def colliding_concepts(
    conn: sqlite3.Connection, max_distance: int = DEFAULT_MAX_DISTANCE
) -> set[str]:
    """Concept ids whose name matches another Concept under the real matcher.

    IFC-KK-CONCEPT-REVIEW-PRIORITY's first sort key. It uses the SAME three
    tiers fuzzy_match_concept uses — exact, prefix either way, Levenshtein —
    because a queue that flagged collisions the matcher would not actually make
    would be reporting a different program than the one that runs.

    MEASURED 2026-09-25 AND THE PLAN'S PREMISE WAS WRONG. "Zero homonyms today"
    is true of EXACT names and false of the matcher: there are FOUR collisions
    among the 97. Three are io_uring against "io_uring Asynchronous I/O",
    "io_uring Database Integration" and "io_uring Observability Tool" — real
    near-duplicates a human should merge or distinguish. The fourth is Vmalloc
    against Kmalloc, a FALSE POSITIVE at distance 1 between two different
    allocators, and it is the more important of the four: see
    ALG-KK-DOC-HARVEST for why it is a risk to the harvest specifically.

    ONE QUERY, NOT ONE PER ROW. Read once per render like seminal_concepts, for
    the reason INV-KK-WEB-QUERY-BOUNDED gives.
    """
    rows = [
        (r[0], normalise_concept_name(r[1]))
        for r in conn.execute(
            "SELECT id, json_extract(attrs, '$.name') FROM nodes "
            "WHERE kind = 'Concept'"
        ).fetchall() if r[1]
    ]
    colliding: set[str] = set()
    for i in range(len(rows)):
        id_a, a = rows[i]
        for j in range(i + 1, len(rows)):
            id_b, b = rows[j]
            if (a == b or a.startswith(b) or b.startswith(a)
                    or levenshtein_distance(a, b) <= max_distance):
                colliding.add(id_a)
                colliding.add(id_b)
    return colliding


def curation_state(attrs: dict | None) -> str:
    """The curation state of a Concept, reading absent as 'harvested'.

    The single definition of the default, so the sweep, the harvest and any
    later review surface cannot disagree about what an unmarked Concept means.
    A value outside CURATION_STATES is returned unchanged rather than corrected
    — correcting it here would hide exactly what
    check_concept_curation_state exists to report.
    """
    value = (attrs or {}).get("curation_state") or ""
    return value if value else DEFAULT_CURATION_STATE


def curation_reviewed(attrs: dict | None) -> bool:
    """Whether a human has reviewed this Concept.

    True only for a state in SIGNED_CURATION_STATES. 'retired' is deliberately
    excluded: a human did look at it, but the question every caller asks of
    this predicate is "is this entry trustworthy vocabulary", and a retired
    entry is the one answer that is not.
    """
    return curation_state(attrs) in SIGNED_CURATION_STATES
