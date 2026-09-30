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

import re
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
    # A TIE IS A REFUSAL, NOT A CHOICE. Until 2026-09-28 this returned the
    # FIRST match at the best distance, which on a tie is dict iteration order
    # — a silent coin flip that writes a real edge onto a real paper.
    # strict_match_concept has refused ties since it was written, on the
    # grounds that attaching to a coin flip is worse than creating; the two
    # matchers disagreed about the same question and only one was right.
    #
    # MEASURED 2026-09-28 over 296 concepts: a self-match test misroutes ZERO
    # of them, because the exact tier fires first, and near-misses resolve
    # correctly too — kmallocs to Kmalloc, kreff to kref. The tier earns its
    # place. Only a name equidistant from SEVERAL concepts was arbitrary:
    # "zmalloc" sits at distance 1 from Kmalloc, Vmalloc AND zsmalloc. Six of
    # 296 concepts sit in such a cluster.
    #
    # A refusal is the better outcome because it is VISIBLE: an unmatched name
    # becomes a candidate row a human sees, while a wrong link is
    # indistinguishable from a right one and survives every later pass.
    best, winners = max_distance + 1, []
    for name, cid in name_to_id.items():
        d = levenshtein_distance(q, name)
        if d > max_distance:
            continue
        if d < best:
            best, winners = d, [cid]
        elif d == best:
            winners.append(cid)
    return winners[0] if len(winners) == 1 else None


_PAREN_RE = re.compile(r"\(([^)]+)\)")


def squash_concept_name(name: str) -> str:
    """The name with every non-alphanumeric character removed.

    "Kernel Samepage Merging" and "Kernel Same-page Merging" both squash to
    "kernelsamepagemerging". MEASURED 2026-09-25: the first doc harvest created
    the former beside the existing latter, because Levenshtein 2 cannot reach
    across a hyphen plus a space. This tier is EXACT after normalisation, so it
    carries no false-positive risk — two names that squash equal differ only in
    punctuation and spacing.
    """
    return "".join(ch for ch in normalise_concept_name(name) if ch.isalnum())


def parenthetical_of(name: str) -> str:
    """The abbreviation or alias a name carries in brackets, normalised.

    "Dentry Cache (dcache)" -> "dcache". This vocabulary uses the bracketed
    suffix as an alias, so two names sharing one are the same class — it is a
    deliberate second name, not an accident of spelling. MEASURED 2026-09-25:
    "Directory Entry Cache (dcache)" was created beside "Dentry Cache
    (dcache)", which no character-distance tier could have caught.
    """
    m = _PAREN_RE.search(name or "")
    return normalise_concept_name(m.group(1)) if m else ""


def strict_match_concept(query: str, name_to_id: dict[str, str]) -> str | None:
    """Match on identity after normalisation, never on proximity.

    THE TIERS THE HARVEST NEEDED AND THE THREE-TIER MATCHER DID NOT HAVE.
    Measured 2026-09-25 over 18 documents: fuzzy_match_concept made ZERO false
    attachments — the Vmalloc/Kmalloc risk recorded in ALG-KK-DOC-HARVEST never
    fired — and MISSED six duplicates of Concepts that already existed. The
    tier that worried us was too loose while the ones that mattered were far
    too tight.

    Both tiers here are exact after a normalisation, so neither can attach two
    genuinely different mechanisms. Token containment is deliberately NOT here:
    "Huge Pages" is contained in "Transparent Huge Pages" and they are
    different, while "Transparent Huge Page Support" is contained the same way
    and is the same — nothing in the shape separates them, so containment
    surfaces in the review queue instead of acting.

    THE TIERS ARE TRIED IN ORDER AND A TIE IS BROKEN ONLY WITHIN A TIER. Until
    2026-09-30 they were not tiers at all: every form went into one flat set and
    any intersection counted, so the strongest evidence and the weakest were
    weighed together. Querying "Linux Security Module (LSM)" against a
    vocabulary CONTAINING that exact normalised name returned None — it hit
    itself by all three forms, "Linux Security Modules" by the squash form
    (squashing strips the trailing plural) and "Linux Security Modules (LSM)
    framework" by the parenthetical "lsm". Three hits, a tie, no match, while a
    unique exact hit sat in the set.

    IT COMPOUNDED, AND THAT IS HOW IT PRODUCED AN IMPOSSIBLE ROW. Every concept
    added to a family makes the family more ambiguous, so the next document is
    MORE likely to mint. Batch harvest-2026-09-30-9e2419bc created "Linux
    Security Module (LSM)" TWICE, from security/lsm-development.rst and
    security/credentials.rst — two Concepts with the identical normalised name,
    which the exact tier exists to prevent.

    Returns None on a tie WITHIN a tier, for the reason find_concept_by_name
    does: attaching to a coin flip is worse than creating. That rule was never
    the problem; applying it across tiers of different strength was.
    """
    for forms in _match_tiers(query):
        if not forms:
            continue
        hits = {
            cid for name, cid in name_to_id.items()
            if any(forms & tier for tier in _match_tiers(name))
        }
        if len(hits) == 1:
            return hits.pop()
        if hits:
            # A genuine tie at this strength. Weaker tiers cannot resolve it —
            # they are looser, so they can only add candidates.
            return None
    return None


#: Declaration keywords stripped before matching. "struct sk_buff" is the same
#: thing as "Socket Buffer (sk_buff)" and must reach it.
_DECLARATION_RE = re.compile(r"^(struct|union|enum|class)\s+", re.IGNORECASE)


def _match_tiers(name: str) -> list[set[str]]:
    """The match forms of a name, STRONGEST FIRST, as separate tiers.

    (1) the normalised name itself; (2) the squashed name and its singular;
    (3) the name outside any brackets, and the bracketed alias alone.

    The split exists because these are not equally strong evidence. An exact
    name is identity. A squashed name is identity modulo punctuation and a
    plural. A bracketed alias is an abbreviation, which is where collisions
    live: "lsm" is shared by every concept in the LSM family. Pooling them let
    an ambiguous abbreviation veto a unique exact hit — see
    strict_match_concept for what that cost.
    """
    bare = _DECLARATION_RE.sub("", (name or "").strip())
    exact = {f for f in {normalise_concept_name(bare)} if len(f) > 2}

    squashed: set[str] = set()
    whole = squash_concept_name(bare)
    if whole:
        squashed.add(whole)
        if len(whole) > 4 and whole.endswith("ies"):
            squashed.add(whole[:-3] + "y")
        for suffix in ("ches", "shes", "xes", "ses", "zes"):
            if len(whole) > len(suffix) + 2 and whole.endswith(suffix):
                squashed.add(whole[: -len("es")])
        if len(whole) > 4 and whole.endswith("s") and not whole.endswith("ss"):
            squashed.add(whole[:-1])

    alias: set[str] = set()
    outside = squash_concept_name(_PAREN_RE.sub(" ", bare))
    if outside:
        alias.add(outside)
    inside = squash_concept_name(parenthetical_of(bare))
    if inside:
        alias.add(inside)

    # A bare form of two characters or fewer is an initialism collision waiting
    # to happen and is not worth matching on.
    return [
        exact,
        {f for f in squashed if len(f) > 2},
        {f for f in alias if len(f) > 2} - {f for f in squashed if len(f) > 2},
    ]


def _match_forms(name: str) -> set[str]:
    """Every squashed form a name can legitimately be known by.

    The whole name, the name with any bracketed alias removed, and the alias on
    its own. Two names match when any form coincides, which is what carries
    "Kernel Samepage Merging" to "KSM (Kernel Same-page Merging)": the query
    squashes to the same string as the existing name's PARENTHETICAL, not as
    the existing name itself.
    """
    bare = _DECLARATION_RE.sub("", (name or "").strip())
    forms = set()
    whole = squash_concept_name(bare)
    if whole:
        forms.add(whole)
        # A trailing plural is punctuation-level, not semantic: "Grace Periods"
        # and "Grace Period" are the same class with certainty, and a plural is
        # the most obvious duplicate a harvest can produce. Guarded so "Access"
        # does not become "Acces".
        #
        # "-es" AND "-ies" JOINED "-s" ON 2026-09-28. The harvest of that day
        # created both "Robust Futex" and "Robust Futexes" from
        # robust-futex-ABI.rst and robust-futexes.rst, because stripping one
        # "s" from "robustfutexes" gives "robustfutexe" and misses
        # "robustfutex". Measured impact was exactly ONE pair in 296 concepts
        # — small, and it recurs on every future harvest. Neither -es nor -ies
        # has another instance in this corpus; both are deterministic
        # transforms rather than guesses, so they carry no false-positive risk.
        if len(whole) > 4 and whole.endswith("ies"):
            forms.add(whole[:-3] + "y")
        for suffix in ("ches", "shes", "xes", "ses", "zes"):
            if len(whole) > len(suffix) + 2 and whole.endswith(suffix):
                forms.add(whole[: -len("es")])
        if len(whole) > 4 and whole.endswith("s") and not whole.endswith("ss"):
            forms.add(whole[:-1])
    outside = squash_concept_name(_PAREN_RE.sub(" ", bare))
    if outside:
        forms.add(outside)
    inside = squash_concept_name(parenthetical_of(bare))
    if inside:
        forms.add(inside)
    # A bare form of two characters or fewer is an initialism collision waiting
    # to happen and is not worth matching on.
    return {f for f in forms if len(f) > 2}


def contained_in(a: str, b: str) -> bool:
    """Whether a's significant words are a subset of b's.

    SURFACES A PAIR FOR REVIEW; NEVER ATTACHES ONE. See
    IFC-KK-CONCEPT-REVIEW-PRIORITY. Singularises a trailing 's' and drops
    bracketed aliases and stopwords, so "NUMA Memory Policy" is contained in
    "NUMA Topology and Memory Policy". Requires at least two significant words,
    because a single shared head noun says nothing.
    """
    ta, tb = _significant_tokens(a), _significant_tokens(b)
    return len(ta) >= 2 and ta < tb


_STOPWORDS = frozenset({"and", "of", "the", "a", "an", "for", "in", "to"})


def _significant_tokens(name: str) -> set[str]:
    bare = _PAREN_RE.sub(" ", name or "")
    out = set()
    for tok in normalise_concept_name(bare).replace("-", " ").split():
        if tok in _STOPWORDS:
            continue
        out.add(tok[:-1] if len(tok) > 3 and tok.endswith("s") else tok)
    return out


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


def colliding_pairs(
    conn: sqlite3.Connection, max_distance: int = DEFAULT_MAX_DISTANCE
) -> list[tuple[str, str]]:
    """Every pair of Concept ids whose names collide under the review signal.

    THE PAIR AND NOT JUST THE FLAG, FROM 2026-09-28. The queue has flagged
    colliding rows since 2026-09-25 and could not say what each one collided
    WITH, so the only merge affordance it could offer was a text field — and a
    curator retyping "NUMA Topology and Memory Policy" will mistype it. Naming
    the counterpart is what makes ALG-KK-WEB-CONCEPT-MERGE pressable rather
    than typeable. colliding_concepts is now a flattening of this.

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
    # RETIRED CONCEPTS LEAVE THE SIGNAL, 2026-09-29, AND THIS WAS A PLAIN BUG.
    # build_vocabulary_context has excluded them since 2026-09-25, and this
    # generator did not — so the moment fourteen paper artifacts were retired,
    # SIX of 29 collision pairs became noise about concepts already dealt with:
    # Page Cache against the retired eBPF-Customizable Page Cache, io_uring
    # against its three retired prefixes, and two more. A queue whose first sort
    # key is 20% stale is spending the human minute it exists to direct.
    rows = [
        (r[0], normalise_concept_name(r[1]))
        for r in conn.execute(
            "SELECT id, json_extract(attrs, '$.name') FROM nodes "
            "WHERE kind = 'Concept' "
            "AND COALESCE(json_extract(attrs, '$.curation_state'), '') != 'retired'"
        ).fetchall() if r[1]
    ]
    # AND SO DO PAIRS A HUMAN HAS DECIDED AGAINST (ALG-KK-WEB-CONCEPT-DISTINCT).
    # Read ONCE for the whole sweep, not once per candidate pair, for the reason
    # INV-KK-WEB-QUERY-BOUNDED gives. Either direction suppresses: the relation
    # is symmetric in meaning and storing it twice would let the two halves drift.
    decided = {
        frozenset(r) for r in conn.execute(
            "SELECT source_id, target_id FROM edges WHERE kind = 'contradicts'"
        ).fetchall()
    }
    pairs: list[tuple[str, str]] = []
    for i in range(len(rows)):
        id_a, a = rows[i]
        for j in range(i + 1, len(rows)):
            id_b, b = rows[j]
            # Containment joined this test 2026-09-25 — see
            # IFC-KK-CONCEPT-REVIEW-PRIORITY. It surfaces the pair and never
            # acts on it: "Huge Pages" in "Transparent Huge Pages" is a
            # DIFFERENT mechanism, "Transparent Huge Page Support" in the same
            # is the SAME one, and nothing in their shape tells them apart.
            #
            # LEVENSHTEIN LEFT THIS TEST ON 2026-09-28, ON MEASURED PRECISION
            # OF ZERO. It produced 10 of 35 pairs and every one was a
            # different mechanism: Vmalloc~Kmalloc, Vmalloc~zsmalloc,
            # Kmalloc~zsmalloc, kref~kset, Slab Cache~Swap Cache,
            # Reed-Solomon Encoding~Decoding,
            # memalloc_nofs_save/restore~memalloc_noio_save/restore, and the
            # three pairings of PMD, PTE and PUD Page Table Helpers. This
            # signal's job is to direct a human minute and 29% of the queue
            # was a pair to dismiss. Tightening to distance 1 was refused: it
            # leaves Vmalloc~Kmalloc and PMD~PUD, which are the wrong pairs.
            # It is NOT removed from fuzzy_match_concept, which demonstrably
            # rescues real near-misses — one surfaces a pair, the other
            # attaches a paper, and they need not agree.
            if (a == b or a.startswith(b) or b.startswith(a)
                    or contained_in(a, b) or contained_in(b, a)):
                if frozenset((id_a, id_b)) in decided:
                    continue
                pairs.append((id_a, id_b))
    return pairs


def colliding_concepts(
    conn: sqlite3.Connection, max_distance: int = DEFAULT_MAX_DISTANCE
) -> set[str]:
    """The ids that appear in at least one colliding pair.

    A FLATTENING OF colliding_pairs AND NEVER A SECOND IMPLEMENTATION. The two
    answer different questions the review surface asks — "does this row need a
    badge" and "which specific concept does it collide with" — and a queue whose
    badge and whose merge button disagreed about what a collision is would be
    worse than either alone.
    """
    ids: set[str] = set()
    for id_a, id_b in colliding_pairs(conn, max_distance):
        ids.add(id_a)
        ids.add(id_b)
    return ids


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


def update_concept(
    conn: sqlite3.Connection,
    concept_id: str,
    attrs: dict,
    reviewed_by: str,
    reviewed_at: str = "",
) -> None:
    """A human edits a Concept, and that edit IS the review
    (ALG-KK-WEB-CONCEPT-EDIT).

    NOTHING HAS EVER BEEN ABLE TO DO THIS. Verified 2026-09-25 by sweeping
    every @app.put and @app.post in src/web/routes.py: a human could edit a
    summary, an abstract, a venue, a review, could confirm a link, could admit
    or dismiss a CANDIDATE — and could not change one word of a Concept that
    already existed. The vocabulary was the only curated surface in this
    application with no edit route.

    EDITING IS REVIEWING, IN ONE OPERATION. The six attributes and the three
    curation fields are written together. A human who fixed a description has
    read it, and making them press a second button to say so guarantees the
    state is wrong for everyone who forgets — a review field that undercounts
    is worse than none, because the queue then shows work already done.

    A SAVE THAT CHANGES NOTHING STILL MARKS IT REVIEWED. Decision 2026-09-25.
    Pressing save is an affirmative act: it says "I have read this and it is
    right as it stands", which is exactly what reviewed means and is a useful
    answer for a harvested concept the model got correct. Rendering the form is
    not — a GET asserts nothing, and this function is never called by one.

    THE SIX-ATTRIBUTE RULE IS NOT CIRCUMVENTABLE THROUGH THIS PATH.
    graph.engine.update_node_attrs refuses a merge that would leave a required
    attribute MISSING, but it cannot see a BLANK, which passes the schema and
    says nothing. So the same non-emptiness check PROMOTION_REQUIRED_ATTRS
    applies to the human promotion path is applied here: the two human routes
    onto the vocabulary must not have different standards, or the laxer one
    becomes the way in.

    Lives here rather than in the route so the rule is testable without a
    router, and so the route cannot grow a second copy of the check.
    """
    # Lazily, the way promote_candidate does: graph.engine imports from
    # graph.schema and a module-level import here would be a cycle.
    from graph.engine import get_node, update_node_attrs

    node = get_node(conn, concept_id)
    if node is None or node["kind"] != "Concept":
        raise ValueError(f"No Concept '{concept_id}'")
    if not reviewed_by:
        raise ValueError("An edit must name the human who made it")

    missing = [
        a for a in PROMOTION_REQUIRED_ATTRS
        if not _attr_supplied(attrs.get(a))
    ]
    if missing:
        raise ValueError(
            "A Concept must keep all six attributes; these arrived empty: "
            + ", ".join(missing)
        )

    update_node_attrs(conn, concept_id, {
        **{a: attrs[a] for a in PROMOTION_REQUIRED_ATTRS},
        "curation_state": "reviewed",
        "reviewed_by": reviewed_by,
        "reviewed_at": reviewed_at or datetime.now(timezone.utc).date().isoformat(),
    })


def retire_concept(
    conn: sqlite3.Connection,
    concept_id: str,
    reviewed_by: str,
    reviewed_at: str = "",
) -> None:
    """A human judges a Concept wrong (ALG-KK-WEB-CONCEPT-RETIRE).

    A STATE FLIP AND NEVER A DELETE, per INV-KK-CONCEPT-CURATION-VOCABULARY.
    EVERY EDGE IS KEPT: papers may already link to the Concept, and deleting
    the node orphans or silently destroys those links — the cleanup the
    114-Concept revert had to do by hand. A state makes the rejection visible
    to anyone reading the graph and is REVERSIBLE: a retirement taken in error
    costs one edit rather than a re-harvest.

    Two consequences, and the first is what makes it real. The Concept vanishes
    from build_vocabulary_context (INV-KK-VOCABULARY-EXCLUDES-RETIRED), because
    a retired Concept still offered to the model is a retirement that did not
    happen. And it is admissible under no route whatever its weight, which
    graph.rules.admission_state already applies as its first test.

    UN-RETIRING IS update_concept AND NOT A THIRD FUNCTION. Saving the form
    returns the state to 'reviewed', which is the honest state: a human looked
    at it and decided it belongs after all.
    """
    # Lazily, the way promote_candidate does: graph.engine imports from
    # graph.schema and a module-level import here would be a cycle.
    from graph.engine import get_node, update_node_attrs

    node = get_node(conn, concept_id)
    if node is None or node["kind"] != "Concept":
        raise ValueError(f"No Concept '{concept_id}'")
    if not reviewed_by:
        raise ValueError("A retirement must name the human who made it")

    update_node_attrs(conn, concept_id, {
        "curation_state": "retired",
        "reviewed_by": reviewed_by,
        "reviewed_at": reviewed_at or datetime.now(timezone.utc).date().isoformat(),
    })


def _attr_supplied(value) -> bool:
    """Whether an edited attribute says anything.

    A blank string satisfies REQUIRED_ATTRS and says nothing, which is exactly
    the thin entry the admission rule exists to exclude. A list may legitimately
    be empty — 78 of the 97 carry empty key_properties — so only strings are
    checked for emptiness; None and a missing key are refused for every type.
    """
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


@dataclass
class MergeResult:
    """What a merge moved, and what it could not move because it was already there."""
    ok: bool
    winner_id: str
    loser_id: str
    winner_name: str
    loser_name: str
    moved: int
    dropped: int
    weight_before: int
    weight_after: int


def merge_concepts(
    conn: sqlite3.Connection,
    loser_id: str,
    winner_id: str,
    reviewed_by: str,
    reviewed_at: str = "",
) -> MergeResult:
    """A human collapses one Concept into another and the evidence MOVES
    (ALG-KK-GRAPH-CONCEPT-MERGE).

    NOTHING HAS EVER BEEN ABLE TO DO THIS. update_concept can correct a Concept
    and retire_concept can withdraw one, and neither resolves a duplicate:
    retiring the smaller of a pair leaves its papers attached to something no
    page will ever surface again. Measured 2026-09-28, 41 Concepts collide in 25
    pairs and TWENTY of those pairs carry papers on both sides — "NUMA Memory
    Policy" with 1 paper sits beside "NUMA Topology and Memory Policy" with 72.
    Retiring the small one strands its paper. The evidence has to move.

    THE REPOINT IS BY NODE ID AND IN BOTH DIRECTIONS, NOT BY A LIST OF KINDS.
    A Concept carries EIGHT outbound edge kinds (extracted-from 2,246,
    belongs-to 233, implemented-in 94, suited-for 56, prerequisite 48,
    contributes-to 40, refines 17, alternative-to 6) and is the TARGET of
    SIXTEEN more (discusses 148, observes 122, governed-by 74, profiled-by 71,
    and twelve others). An outbound-only merge strands 148 Discussion edges
    pointing at a Concept the curator believes they just eliminated. Repointing
    by id covers an edge kind added tomorrow by construction, where a list would
    silently start stranding it — and it is SAFE because both endpoints are
    Concepts: any (kind, source, target) pair graph.schema accepts for the loser
    it accepts for the winner, so no repoint can produce an invalid edge.

    THE UNIQUE CONSTRAINT FIRES ON MOST PAIRS, NOT AS AN EDGE CASE. edges
    carries UNIQUE (kind, source_id, target_id), and SIXTEEN of the 25 colliding
    pairs already share at least one neighbour — 23 shared edges — so a plain
    UPDATE raises IntegrityError on 64% of the merges a curator would want. The
    check-then-act shape attach_existing_concept uses is copied: where the
    winner already holds the same (kind, other endpoint), the loser's edge is
    DELETED and counted as dropped, and THE WINNER'S ATTRS SURVIVE UNTOUCHED.
    Operator decision 2026-09-28: the winner is canonical by the curator's
    choice, and the loser's verdict describes a name being withdrawn. Preferring
    the newer basis was refused because it lets a machine-written evidence-text
    verdict overwrite a human-curated edge on the survivor.

    A SELF-LOOP IS DROPPED AND NEVER CREATED. prerequisite, refines and
    alternative-to run Concept to Concept, so a loser pointing at its own winner
    would repoint into a loop. Zero pairs are in that position today — measured,
    all 25 — which is exactly why it is handled before the first one appears.

    THE LOSER IS RETIRED AND NEVER DELETED, AND ONE EDGE SAYS WHICH KIND OF
    RETIREMENT IT WAS. supersedes(winner, loser) is added last. It is the reason
    'retired' can mean two shapes without a fourth state word: a retired Concept
    with an inbound supersedes edge was merged away, one without it was judged
    wrong, and that is a query rather than a convention. See the 2026-09-28
    amendment to INV-KK-CONCEPT-CURATION-VOCABULARY. ALG-KK-WEB-VENUE-MERGE
    deletes its loser outright and the record that the name existed goes with
    it; "why is there no Robust Futexes any more" has an answer here and none
    under a delete.

    IDEMPOTENCE COMES FROM THAT EDGE, NOT FROM THE LOSER VANISHING. merge_venues
    is idempotent because its second call finds no source Venue; the loser here
    survives, so the no-op test is the presence of supersedes(winner, loser) and
    a repeat call reports moved=0, dropped=0 rather than raising.
    """
    # Lazily, the way update_concept does: graph.engine imports from
    # graph.schema and a module-level import here would be a cycle.
    from graph.engine import add_edge, get_node, update_node_attrs
    from graph.rules import concept_weight

    if loser_id == winner_id:
        raise ValueError("Cannot merge a concept into itself")
    if not reviewed_by:
        raise ValueError("A merge must name the human who made it")

    for cid in (loser_id, winner_id):
        node = get_node(conn, cid)
        if node is None or node["kind"] != "Concept":
            raise ValueError(f"No Concept '{cid}'")

    loser = get_node(conn, loser_id)
    winner = get_node(conn, winner_id)
    loser_name = loser["attrs"].get("name") or loser_id
    winner_name = winner["attrs"].get("name") or winner_id
    weight_before = concept_weight(conn, winner_id)

    already = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'supersedes' "
        "AND source_id = ? AND target_id = ?", (winner_id, loser_id),
    ).fetchone()
    if already is not None:
        return MergeResult(
            ok=True, winner_id=winner_id, loser_id=loser_id,
            winner_name=winner_name, loser_name=loser_name,
            moved=0, dropped=0,
            weight_before=weight_before, weight_after=weight_before,
        )

    moved = dropped = 0

    # Outbound: loser -kind-> other.
    for kind, other in conn.execute(
        "SELECT kind, target_id FROM edges WHERE source_id = ?", (loser_id,)
    ).fetchall():
        # CARDINALITY-ONE KINDS ARE DROPPED, NOT REPOINTED, WHEN THE WINNER
        # ALREADY HAS ONE — found 2026-09-30 by a merge that produced a
        # violation. _edge_exists asks whether the winner has this edge to the
        # SAME target, which is the right test for a kind that may repeat and
        # the wrong one for a kind that may not: merging "Page Table Hierarchy"
        # (Virtual Memory) into "Hierarchical Page Tables" (Memory Management)
        # moved a SECOND belongs-to onto the winner and broke
        # INV-KK-CONCEPT-SUBSYSTEM-SINGLE.
        #
        # THE WINNER'S OWN EDGE SURVIVES, because the winner is the concept
        # that persists and its subsystem is the one a human may have set by
        # hand through ALG-KK-WEB-CONCEPT-SUBSYSTEM.
        if (kind in _CARDINALITY_ONE_OUT
                and _edge_exists_of_kind(conn, kind, winner_id)):
            conn.execute(
                "DELETE FROM edges WHERE kind = ? AND source_id = ? AND target_id = ?",
                (kind, loser_id, other))
            dropped += 1
            continue
        if other == winner_id or _edge_exists(conn, kind, winner_id, other):
            conn.execute(
                "DELETE FROM edges WHERE kind = ? AND source_id = ? AND target_id = ?",
                (kind, loser_id, other))
            dropped += 1
            continue
        conn.execute(
            "UPDATE edges SET source_id = ? WHERE kind = ? AND source_id = ? "
            "AND target_id = ?", (winner_id, kind, loser_id, other))
        moved += 1

    # Inbound: other -kind-> loser. The half the request did not name and the
    # half that carries discusses, observes and governed-by.
    for kind, other in conn.execute(
        "SELECT kind, source_id FROM edges WHERE target_id = ?", (loser_id,)
    ).fetchall():
        if other == winner_id or _edge_exists(conn, kind, other, winner_id):
            conn.execute(
                "DELETE FROM edges WHERE kind = ? AND source_id = ? AND target_id = ?",
                (kind, other, loser_id))
            dropped += 1
            continue
        conn.execute(
            "UPDATE edges SET target_id = ? WHERE kind = ? AND source_id = ? "
            "AND target_id = ?", (winner_id, kind, other, loser_id))
        moved += 1

    update_node_attrs(conn, loser_id, {
        "curation_state": "retired",
        "reviewed_by": reviewed_by,
        "reviewed_at": reviewed_at or datetime.now(timezone.utc).date().isoformat(),
    })

    # Last, so the inbound sweep above never sees it and repoints it into a loop.
    add_edge(conn, "supersedes", winner_id, loser_id)

    return MergeResult(
        ok=True, winner_id=winner_id, loser_id=loser_id,
        winner_name=winner_name, loser_name=loser_name,
        moved=moved, dropped=dropped,
        weight_before=weight_before,
        weight_after=concept_weight(conn, winner_id),
    )


#: Outbound edge kinds a Concept may have AT MOST ONE of. A merge must drop the
#: loser's rather than repoint it, or the winner ends with two.
#: belongs-to is the only one today (INV-KK-CONCEPT-SUBSYSTEM-SINGLE); the
#: tuple exists so the next such kind is one entry rather than a second bug.
_CARDINALITY_ONE_OUT = ("belongs-to",)


def _edge_exists_of_kind(
    conn: sqlite3.Connection, kind: str, source_id: str
) -> bool:
    """Whether `source_id` already has ANY edge of this kind.

    Distinct from _edge_exists, which asks about a specific target. The
    difference is exactly what a cardinality-one kind needs and what a merge
    got wrong until 2026-09-30.
    """
    return conn.execute(
        "SELECT 1 FROM edges WHERE kind = ? AND source_id = ? LIMIT 1",
        (kind, source_id),
    ).fetchone() is not None


def _edge_exists(
    conn: sqlite3.Connection, kind: str, source_id: str, target_id: str
) -> bool:
    """Whether the winner already holds the edge the loser is bringing.

    The UNIQUE (kind, source_id, target_id) test, asked BEFORE the UPDATE rather
    than caught after it: an IntegrityError arrives part way through a merge,
    with some edges moved and some not and no transaction boundary the caller
    asked for.
    """
    return conn.execute(
        "SELECT 1 FROM edges WHERE kind = ? AND source_id = ? AND target_id = ?",
        (kind, source_id, target_id),
    ).fetchone() is not None


@dataclass
class BulkRetireResult:
    """What a bulk retirement did, and what it refused before doing anything."""
    ok: bool
    retired: list[str]
    refused: dict[str, str]


def retire_concepts_bulk(
    conn: sqlite3.Connection,
    concept_ids: list[str],
    reviewed_by: str,
    reviewed_at: str = "",
) -> BulkRetireResult:
    """Retire several Concepts in one signed act (ALG-KK-WEB-CONCEPT-RETIRE-BULK).

    THE BACKLOG IS 465 AND NOT ONE ENTRY HAS BEEN REVIEWED. Measured 2026-09-29:
    curation_state is 'harvested' for 465 of 465. Edit, retire, merge, the
    priority sort and the collision badge all ship and have never been used. A
    backlog that size is worked in sittings, and the first sitting should not go
    on entries that need no reading at all.

    IT EXISTS FOR A POPULATION WHOSE EVIDENCE IS IN THE NODE ID. Fourteen
    Concepts carry zero papers, are undocumented, and were minted by the PAPER
    extractor before INV-KK-EXTRACT-CONCEPT-MATCHED stopped it minting — and
    their ids are the papers' own system names: concept-cachebpf, concept-schedcp,
    concept-xlb, concept-resystance, concept-dfuse, concept-tierbpf,
    concept-uringscope. CacheBPF, SchedCP, XLB, ReSysTance, DFUSE, TierBPF and
    UringScope are one paper's system apiece, named as though each were a
    mechanism, which is exactly what INV-KK-HARVEST-NAME-IS-A-CLASS refuses.

    IT REFUSES MORE THAN IT ACCEPTS AND THE REFUSALS ARE THE DESIGN. A DOCUMENTED
    Concept is refused whatever else is true: documentation admits it under
    INV-KK-CONCEPT-ADMISSION's reverse route, and a bulk action must not be able
    to contradict the admission rule. A Concept CARRYING PAPERS is refused,
    because that is evidence and retiring it in bulk strands it — the very thing
    merge_concepts exists to prevent.

    ALL OR NOTHING. If any id is refused, NOTHING is retired. A partial bulk
    retire is worse than none, because a caller reading a success cannot tell
    which half happened, and the obvious retry then double-signs the half that
    did.

    IT IS NOT A DIFFERENT RETIREMENT. retire_concept does every write, so the
    state flip, the signature and INV-KK-VOCABULARY-EXCLUDES-RETIRED's
    consequence have one implementation. A second copy of "what retiring means"
    is the defect this codebase keeps finding.
    """
    from graph.engine import get_node
    from graph.rules import concept_weight, documented_concepts

    if not reviewed_by:
        raise ValueError("A retirement must name the human who made it")
    if not concept_ids:
        return BulkRetireResult(ok=True, retired=[], refused={})

    documented = documented_concepts(conn)
    refused: dict[str, str] = {}
    for cid in concept_ids:
        node = get_node(conn, cid)
        if node is None or node["kind"] != "Concept":
            refused[cid] = f"No Concept '{cid}'"
        elif cid in documented:
            refused[cid] = "Documented concepts are admitted by their documentation"
        elif concept_weight(conn, cid) > 0:
            refused[cid] = "Carries papers; retiring in bulk would strand them"

    if refused:
        return BulkRetireResult(ok=False, retired=[], refused=refused)

    for cid in concept_ids:
        retire_concept(conn, cid, reviewed_by=reviewed_by, reviewed_at=reviewed_at)
    return BulkRetireResult(ok=True, retired=list(concept_ids), refused={})


def assign_subsystem(
    conn: sqlite3.Connection, concept_id: str, subsystem_id: str
) -> str:
    """A human gives a Concept the subsystem the harvest declined to guess
    (ALG-KK-WEB-CONCEPT-SUBSYSTEM).

    78 CONCEPTS HAVE NO belongs-to EDGE AND EVERY ONE CAME FROM THE HARVEST.
    That is not a gap in ALG-KK-DOC-HARVEST: build_subsystem_context offers the
    22 Subsystems and tells the model to answer "none" rather than guess, because
    a wrong subsystem is worse than no subsystem. So the 78 are the harvest
    declining, correctly, 78 times — and nothing in this application could accept
    on its behalf. Cgroup Controllers, Memory Barriers, XArray and Circular
    Buffer are among them and each has an obvious home.

    CARDINALITY ONE, SO IT REPLACES RATHER THAN ADDS. belongs-to is
    (Concept, Subsystem) and a Concept belongs to one subsystem; clearing first
    also makes the call idempotent, which a plain add_edge would not be against
    UNIQUE (kind, source_id, target_id).

    IT MAY NOT CREATE A SUBSYSTEM. A subsystem_id naming no Subsystem raises,
    for the same reason the extractor may not mint a Concept: seeding the
    taxonomy is human curation, not a side effect of using it.
    """
    from graph.engine import add_edge, get_node

    node = get_node(conn, concept_id)
    if node is None or node["kind"] != "Concept":
        raise ValueError(f"No Concept '{concept_id}'")
    sub = get_node(conn, subsystem_id)
    if sub is None or sub["kind"] != "Subsystem":
        raise ValueError(f"No Subsystem '{subsystem_id}'")

    conn.execute(
        "DELETE FROM edges WHERE kind = 'belongs-to' AND source_id = ?",
        (concept_id,))
    add_edge(conn, "belongs-to", concept_id, subsystem_id)
    return subsystem_id


def curation_progress(conn: sqlite3.Connection) -> dict[str, int]:
    """How many Concepts sit in each curation state, over the WHOLE corpus.

    THE SORT KEY CANNOT ANSWER "HOW MUCH IS LEFT". IFC-KK-CONCEPT-REVIEW-PRIORITY
    orders the queue well and says nothing about progress, and a curator working
    465 entries across sittings needs the second question answered to start the
    third sitting.

    THE CORPUS AND NEVER THE PAGE, which is the distinction ?curation= already
    draws against ?state=. A count of the page would read "50 harvested" forever
    and be worse than no count, exactly as a filter narrowing only the page was
    judged worse than none.

    ONE O(1) QUERY, AND THAT IS WHY IT DOES NOT BREACH INV-KK-WEB-QUERY-BOUNDED,
    whose predicate bounds enrichment calls PER ROW. A single GROUP BY is not
    per-row work and does not grow with per_page. Recorded rather than assumed,
    because "it is only one more query" is how a bounded route stops being one.
    """
    counts = {state: 0 for state in CURATION_STATES}
    rows = conn.execute(
        "SELECT COALESCE(NULLIF(json_extract(attrs, '$.curation_state'), ''), ?), "
        "COUNT(*) FROM nodes WHERE kind = 'Concept' GROUP BY 1",
        (DEFAULT_CURATION_STATE,),
    ).fetchall()
    for state, n in rows:
        counts[state] = counts.get(state, 0) + n
    counts["total"] = sum(counts[s] for s in CURATION_STATES)
    return counts


def mark_documentation_absent(
    conn: sqlite3.Connection,
    concept_id: str,
    reason: str,
    reviewed_by: str,
    reviewed_at: str = "",
) -> bool:
    """A curator records that a Concept's canonical documentation DOES NOT EXIST
    (ALG-KK-WEB-CONCEPT-DOCUMENTATION-ABSENT, INV-KK-CONCEPT-DOCUMENTATION-ABSENT).

    WHAT THE GRAPH COULD NOT SAY BEFORE THIS. Measured 2026-09-29: 33 of the 35
    concepts holding unreachable legacy links are undocumented, for two reasons
    the graph rendered identically. Most are waiting on a seeding run that had
    not happened — their documents exist in Documentation/ and nothing had
    fetched them. Signal Delivery is not: kernel/signal.c is the definition and
    there is no Documentation/ page for it, so no seeding will ever reach it.
    "unlinked" says nobody has linked a concept and has never been able to say
    that nothing could, and those two facts call for opposite responses.

    AN ATTRIBUTE AND NOT A FOURTH curation_state, and the reason is structural
    rather than stylistic. The two facts are ORTHOGONAL — a concept can be
    reviewed AND undocumentable — so a fourth state would make a curator choose
    which of two true things to record, and would corrupt the progress count by
    making an unread concept stop counting as unreviewed.

    THE REASON IS REQUIRED. "defined by kernel/signal.c, no Documentation/ page"
    is the entire value of the record; without it the mark is indistinguishable
    from a curator who did not look. An empty reason is refused.

    IT WRITES NO EDGE AND CHANGES NO STATE, so it cannot affect
    INV-KK-LINK-LAST-EVIDENCE-KEPT's sparing: a marked concept KEEPS its legacy
    links. Knowing the silence is permanent makes that link more necessary, not
    less. Clearing the mark is update_concept, the way un-retiring is.

    Returns whether anything was written; marking an already-marked Concept is
    a no-op reporting False.
    """
    from graph.engine import get_node, update_node_attrs

    if not (reason or "").strip():
        raise ValueError("A reason is required")
    if not (reviewed_by or "").strip():
        raise ValueError("An attribution is required")
    node = get_node(conn, concept_id)
    if node is None or node["kind"] != "Concept":
        raise ValueError(f"No Concept '{concept_id}'")
    if node["attrs"].get("documentation_absent") is True:
        return False

    update_node_attrs(conn, concept_id, {
        "documentation_absent": True,
        "documentation_absent_reason": reason.strip(),
        "reviewed_by": reviewed_by,
        "reviewed_at": reviewed_at or datetime.now(timezone.utc).date().isoformat(),
    })
    return True


def record_distinct(
    conn: sqlite3.Connection, concept_a: str, concept_b: str
) -> bool:
    """A human records that two colliding names are DIFFERENT things
    (ALG-KK-WEB-CONCEPT-DISTINCT). Returns whether an edge was written.

    A REVIEW QUEUE THAT REPEATS ITSELF IS ONE PEOPLE STOP OPENING. Eleven live
    collision pairs are not merges and nothing could record that: a curator who
    decides against Folio ~ Folio Marks today sees it again tomorrow, and again
    the day after. IFC-KK-CONCEPT-REVIEW-PRIORITY says the queue's job is to
    direct a human minute; a pair that has already had its minute is spending it
    twice.

    IT USES contradicts, WHICH THE SCHEMA ALREADY HAS AND NOTHING USES.
    contradicts is (Concept, Concept) in EDGE_VALID_PAIRS with zero instances —
    exactly where supersedes stood before the merge gave it a job. The word is
    slightly loose for what is meant: these concepts do not contradict each
    other, they are merely not the same. That looseness is recorded rather than
    hidden, because the alternative was widening EDGE_KINDS for a single use.

    THE ENGINE ALREADY TREATS contradicts AS SYMMETRIC, which was found by a test
    rather than assumed: graph.engine.add_edge writes the reverse edge itself for
    this kind and for contradicted-by, so one call leaves TWO rows and they
    cannot drift because nothing writes one without the other. The suppression
    below still tests both directions, because a reader of this function should
    not have to know that the engine does it.

    IT SUPPRESSES AND NEVER DELETES. Both concepts keep their names, their
    evidence and their place in the vocabulary; only the PAIRING stops being
    offered. A curator who changes their mind removes the edge.
    """
    from graph.engine import add_edge, get_node

    if concept_a == concept_b:
        raise ValueError("A concept cannot be distinct from itself")
    for cid in (concept_a, concept_b):
        node = get_node(conn, cid)
        if node is None or node["kind"] != "Concept":
            raise ValueError(f"No Concept '{cid}'")

    already = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'contradicts' "
        "AND ((source_id = ? AND target_id = ?) OR (source_id = ? AND target_id = ?))",
        (concept_a, concept_b, concept_b, concept_a),
    ).fetchone()
    if already is not None:
        return False
    add_edge(conn, "contradicts", concept_a, concept_b)
    return True
