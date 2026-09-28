"""Harvest Concepts from canonical documentation (ALG-KK-DOC-HARVEST).

THE SECOND EXTRACTION PATH, AND IT ASKS A DIFFERENT QUESTION OF A DIFFERENT
KIND OF WITNESS. ALG-KK-LLM-EXTRACT asks a PAPER "which of these known concepts
is this about" and is forbidden to mint by INV-KK-EXTRACT-CONCEPT-MATCHED. This
asks a DOCUMENT "what mechanisms does this document DEFINE" and writes them,
which INV-KK-CONCEPT-ADMISSION's fourth route made lawful on 2026-09-25.

A SEPARATE MODULE AND NOT A MODE FLAG, AND THE DISTINCTION IS STRUCTURAL. A
boolean on extract_concepts would put the paper ban and its exception inside one
function, one careless caller away from being lost. This module never imports
extract_concepts and extract_concepts never learns that documents exist.

Spec: ALG-KK-DOC-HARVEST, INV-KK-HARVEST-CONCEPT-COMPLETE,
      INV-KK-HARVEST-BATCH-REVERTIBLE, INV-KK-EXTRACT-PROVENANCE (ninth writer),
      IFC-KK-DOC-DEFINED-PROVENANCE (which source types are documentation).
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from graph.concept_vocabulary import (
    PROMOTION_REQUIRED_ATTRS,
    normalise_concept_name,
    resolve_concept_names,
    strict_match_concept,
)
from graph.engine import add_edge, add_node
from graph.rules import DOC_SOURCE_TYPES
from ingest.extractor import build_evidence_attrs
from ingest.llm_provider import DEFAULT_PROVIDER, LLMClient, default_model_for

log = logging.getLogger(__name__)

#: The only artifact_class a Concept may carry. All 97 that existed on
#: 2026-09-25 carry it, and it is a stronger filter than its name suggests: a
#: Concept is a MECHANISM described abstractly. A tunable, a sysctl, a mount
#: option and a command are none of them.
MECHANISM_CLASS = "abstracted-mechanism"

HARVEST_SYSTEM_PROMPT = """\
You are reading CANONICAL KERNEL DOCUMENTATION — a document whose purpose is to
define a mechanism for the people who maintain it. Your job is to name the
MECHANISMS THIS DOCUMENT DEFINES, so they can enter a shared, curated
vocabulary that spans many kernels and thousands of papers.

WHAT COUNTS AS A CONCEPT. An abstracted mechanism: a named technique or
structure that exists independently of this one document, that another kernel
could implement differently, and that a paper written five years from now could
still be about. Grace Period. Copy-on-Write. Work Stealing. Journaling.

WHAT DOES NOT COUNT, AND THIS IS WHERE MOST MISTAKES HAPPEN:
  - A TUNABLE OR A KNOB. max_pool_percent, vm.swappiness, a sysctl, a mount
    option, a boot parameter, a cgroup file name. These are how you configure a
    mechanism; they are not the mechanism.
  - A COMMAND OR AN API SYMBOL. mdadm, kmalloc(), struct sk_buff.
  - A FILE OR A PATH. /proc/meminfo, memory.max.
  - THE DOCUMENT ITSELF, or the subsystem it lives under as a whole.

GRANULARITY. Name the mechanism at the level another document could reuse, not
at the level of the whole subsystem. RCU is NOT one concept in this vocabulary:
Grace Period and Quiescent State Detection stand beside it as separate entries.
If a document defines three mechanisms, return three.

PREFER A NAME ALREADY IN THE VOCABULARY. You will be shown the existing concept
names. If this document defines one of them, USE THAT NAME EXACTLY — the
document becomes further evidence for an entry that already exists, which is
worth more than a new one. Only introduce a new name for a mechanism genuinely
absent from the list.

EVERY CONCEPT MUST BE COMPLETE. All six fields, every one non-empty and
substantive. A concept you cannot describe fully is one to omit. Do not pad.

Return ONLY JSON:
{
  "subsystem": "<exactly one name from the SUBSYSTEMS list, or \\"none\\">",
  "concepts": [
    {
      "name": "<the mechanism, as a general class>",
      "description": "<what it is and what problem it solves, 2-4 sentences>",
      "artifact_class": "abstracted-mechanism",
      "key_properties": ["<property>", "..."],
      "tradeoffs": ["<what it costs>", "..."],
      "design_rationale": "<why it is built this way>"
    }
  ]
}

If the document defines no reusable mechanism, return {"subsystem": "none",
"concepts": []}. That is a correct and useful answer. An empty list is far
better than a list of tunables.
"""


def build_subsystem_context(conn: sqlite3.Connection) -> str:
    """The Subsystem vocabulary, for the prompt.

    THE THIRD USE OF A MECHANISM THIS CODEBASE ALREADY HAS TWICE —
    build_vocabulary_context for Concepts, build_kernel_context for Kernels.
    A path table was considered and refused on measurement: the 18 documents
    carrying prose on 2026-09-25 sit in six directories, and
    Documentation/admin-guide/ alone holds cgroup-v2.rst, efi-stub.rst and
    md.rst — Process Management, Firmware Interface and Storage Stack. A table
    maps 13 of 18 and is wrong or empty on the rest.
    """
    names = sorted(
        r[0] for r in conn.execute(
            "SELECT json_extract(attrs, '$.name') FROM nodes WHERE kind = 'Subsystem'"
        ).fetchall() if r[0]
    )
    if not names:
        return ""
    return (
        "SUBSYSTEMS — name the one this document belongs to, EXACTLY as written "
        'here, under the key "subsystem". If none of them fits, answer "none"; '
        "a wrong subsystem is worse than no subsystem. Do NOT invent a name "
        "that is not in this list.\n" + ", ".join(names)
    )


def resolve_subsystem_names(conn: sqlite3.Connection) -> dict[str, str]:
    """normalised Subsystem name -> node id."""
    return {
        normalise_concept_name(r[1]): r[0]
        for r in conn.execute(
            "SELECT id, json_extract(attrs, '$.name') FROM nodes "
            "WHERE kind = 'Subsystem'"
        ).fetchall() if r[1]
    }


def match_subsystem_name(subsystems: dict[str, str], name: str) -> str | None:
    """The Subsystem id for a name the model returned, or None.

    EXACT ON THE NORMALISED NAME, like match_kernel_name and deliberately
    unlike the concept matcher. The list is 18 short proper nouns given
    verbatim in the prompt, so a near-miss is not a paraphrase to rescue; at
    Levenshtein 2 "Virtual Memory" and "Memory Management" stay apart but
    "NUMA" would collide with too much, and a wrong belongs-to edge is worse
    than none. Nothing here creates a Subsystem.
    """
    key = normalise_concept_name(name or "")
    if not key or key == "none":
        return None
    return subsystems.get(key)


def build_harvest_prompt(
    document_text: str, vocabulary: str = "", subsystems: str = ""
) -> str:
    """The user prompt: three vocabularies, then the document."""
    head = ""
    if vocabulary:
        head += f"{vocabulary}\n\n"
    if subsystems:
        head += f"{subsystems}\n\n"
    return (
        f"{head}Name the mechanisms THIS DOCUMENT DEFINES:\n\n{document_text}"
    )


#: INV-KK-HARVEST-NAME-IS-A-CLASS. A declaration is not a class.
_DECLARATION_RE = re.compile(r"\b(struct|union|enum)\s", re.IGNORECASE)

#: A bare C identifier: skb_clone, __free_pages. Not a class either.
_IDENTIFIER_RE = re.compile(r"^_*[a-z][a-z0-9]*(_[a-z0-9]+)+$")


def name_is_a_class(name: str, subsystems: dict[str, str] | None = None) -> bool:
    """Whether a proposed name has the SHAPE of a class.

    THE CHECK THAT REPLACED A VACUOUS ONE. INV-KK-HARVEST-CONCEPT-COMPLETE
    compared the model's self-declared artifact_class against a constant, which
    tests whether the model will assert the string the prompt asked for — it
    always will. Measured 2026-09-25 over 18 documents: rejected_not_mechanism
    was ZERO while the batch created "struct sk_buff", "skb_clone" and
    "shared sk_buff". The system prompt names struct sk_buff as its literal
    example of what must never become a Concept.

    The NAME is the part a model cannot assert its way past: a C identifier
    looks like a C identifier whatever label is attached to it.

    IT RUNS AFTER MATCHING AND NEVER BEFORE. io_uring is a bare lowercase
    identifier with an underscore AND an established Concept here. A name that
    matches something already admitted has been judged by a human once and
    attaches; only an unmatched name reaches this test.
    """
    raw = (name or "").strip()
    if not raw:
        return False
    if _DECLARATION_RE.search(raw):
        return False
    if "(" in raw and ")" in raw and "()" in raw.replace(" ", ""):
        return False
    if _IDENTIFIER_RE.match(normalise_concept_name(raw).replace(" ", "")):
        return False
    # "shared sk_buff" — a phrase starting mid-sentence is a description, not a
    # name. A SINGLE lowercase word is allowed, because io_uring and ext4 are
    # legitimately spelled that way.
    if len(raw.split()) > 1 and not raw[0].isupper():
        return False
    # A Concept sharing a Subsystem's name makes every belongs-to edge
    # ambiguous to a reader. The batch produced "Virtual Memory".
    if subsystems and normalise_concept_name(raw) in subsystems:
        return False
    return True


@dataclass
class DocHarvestResult:
    """What one document yielded."""

    evidence_id: str
    concepts_created: list[str] = field(default_factory=list)
    concepts_attached: list[str] = field(default_factory=list)
    rejected_not_mechanism: int = 0
    rejected_incomplete: int = 0
    rejected_not_a_class: int = 0
    subsystem_id: str = ""
    subsystem_unmatched: str = ""
    dry_run: bool = False
    prompt_chars: int = 0


def new_batch_id() -> str:
    """The id every Concept and every edge of one run carries.

    Dated so a human reading the graph can tell when a batch ran without
    joining anything, and suffixed so two runs on one day stay distinct.
    """
    return (
        "harvest-"
        + datetime.now(timezone.utc).date().isoformat()
        + "-"
        + uuid.uuid4().hex[:8]
    )


def _proposal_is_complete(item: dict) -> bool:
    """INV-KK-HARVEST-CONCEPT-COMPLETE: all six, none blank.

    add_node already rejects a MISSING required attribute. What this forbids is
    the DEFAULTED one — an empty design_rationale passes the schema and says
    nothing, and is exactly the thin entry the admission rule exists to
    exclude. The same standard concept_vocabulary.PROMOTION_REQUIRED_ATTRS sets
    for the human promotion path; the two routes into the vocabulary must not
    have different bars, or the cheaper one becomes the way in.
    """
    for attr in PROMOTION_REQUIRED_ATTRS:
        value = item.get(attr)
        if value is None:
            return False
        if isinstance(value, str) and not value.strip():
            return False
        if isinstance(value, (list, tuple)) and not value:
            return False
    return True


def _parse_response(response: dict) -> tuple[str, list[dict]]:
    """Subsystem name and concept proposals, tolerating a fenced reply.

    Same unfencing extract_concepts does, and the same refusal to raise: a
    malformed reply yields nothing rather than aborting a batch.
    """
    try:
        text = response["text"].strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        parsed = json.loads(text)
    except (json.JSONDecodeError, KeyError, IndexError, TypeError, AttributeError):
        return "", []
    if isinstance(parsed, list):
        return "", [p for p in parsed if isinstance(p, dict)]
    if not isinstance(parsed, dict):
        return "", []
    concepts = parsed.get("concepts", [])
    if not isinstance(concepts, list):
        concepts = []
    return str(parsed.get("subsystem", "") or ""), [
        p for p in concepts if isinstance(p, dict)
    ]


def harvest_document(
    conn: sqlite3.Connection,
    evidence_id: str,
    batch_id: str,
    client: LLMClient | None = None,
    model: str = "",
    dry_run: bool = False,
    vocabulary: str = "",
    subsystem_context: str = "",
    subsystems: dict[str, str] | None = None,
) -> DocHarvestResult:
    """Harvest one document's Evidence node.

    Returns BEFORE touching the client when dry_run, so a dry run needs no
    credential — the same property ALG-KK-EXTRACT-CLI's contract requires and
    its tests pin.
    """
    result = DocHarvestResult(evidence_id=evidence_id, dry_run=dry_run)

    row = conn.execute(
        "SELECT attrs FROM nodes WHERE id = ? AND kind = 'Evidence'", (evidence_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"No Evidence node '{evidence_id}'")
    attrs = json.loads(row[0]) if row[0] else {}
    document_text = attrs.get("text", "") or ""

    if vocabulary == "" and subsystem_context == "":
        from graph.concept_vocabulary import build_vocabulary_context

        vocabulary = build_vocabulary_context(conn)
        subsystem_context = build_subsystem_context(conn)
    if subsystems is None:
        subsystems = resolve_subsystem_names(conn)

    user_prompt = build_harvest_prompt(document_text, vocabulary, subsystem_context)
    result.prompt_chars = len(user_prompt)

    # BEFORE any client work. A dry run must size the batch for someone
    # deciding whether to pay for the real one.
    if dry_run:
        return result

    if client is None:
        raise ValueError("harvest_document needs a client unless dry_run")

    response = client.create_message(
        model=model or default_model_for(DEFAULT_PROVIDER),
        system=HARVEST_SYSTEM_PROMPT,
        user=user_prompt,
        max_tokens=4096,
    )
    subsystem_name, proposals = _parse_response(response)

    subsystem_id = match_subsystem_name(subsystems, subsystem_name)
    if subsystem_id:
        result.subsystem_id = subsystem_id
    elif subsystem_name and normalise_concept_name(subsystem_name) != "none":
        result.subsystem_unmatched = subsystem_name

    known = resolve_concept_names(conn)

    for item in proposals:
        name = str(item.get("name", "") or "").strip()
        if not name:
            result.rejected_incomplete += 1
            continue

        # The artifact_class filter, per INV-KK-HARVEST-CONCEPT-COMPLETE. A
        # tunable is dropped and COUNTED, never relabelled: the 43 names in
        # concept_candidates are what happens when nothing enforces this on a
        # path that writes.
        if str(item.get("artifact_class", "")).strip() != MECHANISM_CLASS:
            result.rejected_not_mechanism += 1
            continue

        # MATCH FIRST, CREATE SECOND — the whole dedup strategy. Identity after
        # normalisation, never proximity: measured 2026-09-25, the fuzzy
        # matcher made zero false attachments over 18 documents and MISSED six
        # real duplicates. On this path a false match SUPPRESSES a legitimate
        # concept, so the Levenshtein tier is not used here. The paper path
        # keeps it unchanged.
        existing = strict_match_concept(name, known)
        if existing:
            _attach(conn, existing, evidence_id, batch_id, document_text, model,
                    item.get("description", ""))
            result.concepts_attached.append(existing)
            continue

        # INV-KK-HARVEST-NAME-IS-A-CLASS, AFTER matching and never before.
        if not name_is_a_class(name, subsystems):
            result.rejected_not_a_class += 1
            continue

        if not _proposal_is_complete(item):
            result.rejected_incomplete += 1
            continue

        concept_id = _create(conn, item, evidence_id, batch_id, document_text,
                             model, subsystem_id)
        result.concepts_created.append(concept_id)
        # So a document proposing the same name twice attaches the second time
        # rather than creating a duplicate within its own response.
        known[normalise_concept_name(name)] = concept_id

    return result


def _attach(
    conn: sqlite3.Connection, concept_id: str, evidence_id: str, batch_id: str,
    document_text: str, model: str, description: str,
) -> None:
    """The ninth provenance writer, attaching branch.

    THE BATCH ID GOES ON THE EDGE AND THAT IS NOT SYMMETRY FOR ITS OWN SAKE. An
    attachment writes an edge and no node, so reverting must remove the edge and
    must NOT remove the Concept, which predates the batch. Without the id here
    the attachments would be unrevertible or catastrophically over-reverted.

    Updates rather than inserts when the link already exists, for the reason
    attach_existing_concept does: edges carries UNIQUE (kind, source_id,
    target_id) and a plain insert would raise part way through a paid run.
    """
    edge_attrs = build_evidence_attrs(description or "", document_text, model)
    edge_attrs["harvest_batch"] = batch_id
    existing = conn.execute(
        "SELECT id FROM edges WHERE kind = 'extracted-from' "
        "AND source_id = ? AND target_id = ?", (concept_id, evidence_id)
    ).fetchone()
    if existing:
        conn.execute("UPDATE edges SET attrs = ? WHERE id = ?",
                     (json.dumps(edge_attrs), existing[0]))
        return
    add_edge(conn, "extracted-from", concept_id, evidence_id, edge_attrs)


def _create(
    conn: sqlite3.Connection, item: dict, evidence_id: str, batch_id: str,
    document_text: str, model: str, subsystem_id: str,
) -> str:
    """The ninth provenance writer, creating branch. Whole or not at all."""
    concept_id = f"concept-{uuid.uuid4().hex[:12]}"
    add_node(conn, concept_id, "Concept", {
        "name": item["name"],
        "description": item["description"],
        "artifact_class": MECHANISM_CLASS,
        "key_properties": item["key_properties"],
        "tradeoffs": item["tradeoffs"],
        "design_rationale": item["design_rationale"],
        # IFC-KK-CONCEPT-CURATION-STATE. 'harvested' means a machine wrote it
        # and nobody has read it, which is the truth about every one of these.
        "curation_state": "harvested",
        "harvest_batch": batch_id,
        "reviewed_by": "",
        "reviewed_at": "",
    })
    edge_attrs = build_evidence_attrs(item["description"], document_text, model)
    edge_attrs["harvest_batch"] = batch_id
    add_edge(conn, "extracted-from", concept_id, evidence_id, edge_attrs)
    if subsystem_id:
        add_edge(conn, "belongs-to", concept_id, subsystem_id,
                 {"harvest_batch": batch_id})
    return concept_id


def select_doc_evidence(
    conn: sqlite3.Connection, source_types: tuple[str, ...] | None = None
) -> tuple[list[str], list[str]]:
    """Evidence of canonical documents, split into usable and empty.

    Returns (with_text, skipped_empty). The empty ones are filtered BEFORE the
    limit is applied, so --limit 10 means ten documents actually sent — the
    241-empty lesson from ALG-KK-EXTRACT-CLI, which this follows rather than
    inventing a third convention.
    """
    types = source_types or DOC_SOURCE_TYPES
    placeholders = ", ".join("?" for _ in types)
    rows = conn.execute(
        "SELECT e.id, COALESCE(json_extract(e.attrs, '$.text'), '') FROM nodes e "
        "JOIN edges s ON s.source_id = e.id AND s.kind = 'sourced-from' "
        "JOIN nodes src ON src.id = s.target_id "
        "WHERE e.kind = 'Evidence' "
        f"AND json_extract(src.attrs, '$.source_type') IN ({placeholders}) "
        "ORDER BY e.id",
        types,
    ).fetchall()
    with_text = [r[0] for r in rows if r[1].strip()]
    skipped = [r[0] for r in rows if not r[1].strip()]
    return with_text, skipped


# ---------------------------------------------------------------------------
# Revert (INV-KK-HARVEST-BATCH-REVERTIBLE)
#
# THE SAFETY PROPERTY THAT REPLACES THE HUMAN GATE. The operator directed that
# bulk harvest proceed without approval; what made approval safe was that
# nothing entered the vocabulary unexamined. What replaces it is not review —
# review is per-concept and arrives later — it is the ability to undo a whole
# bad run in one move, before the vocabulary the PAPER extractor matches
# against carries junk into paper links on the next extraction run.
# ---------------------------------------------------------------------------

#: A batch's Concept is skipped, entirely untouched, for one of these reasons.
SKIP_REVIEWED = "human-reviewed"
SKIP_RETIRED = "human-retired"
SKIP_LINKED = "linked-outside-batch"


@dataclass
class RevertSkip:
    concept_id: str
    name: str
    reason: str
    detail: str = ""


@dataclass
class RevertReport:
    batch_id: str
    concepts_deleted: list[str] = field(default_factory=list)
    edges_detached: int = 0
    skipped: list[RevertSkip] = field(default_factory=list)
    dry_run: bool = False

    @property
    def clean(self) -> bool:
        """Whether the batch came out whole. The CLI exits non-zero when not."""
        return not self.skipped


def _batch_concepts(conn: sqlite3.Connection, batch_id: str) -> list[tuple[str, dict]]:
    rows = conn.execute(
        "SELECT id, attrs FROM nodes WHERE kind = 'Concept' "
        "AND json_extract(attrs, '$.harvest_batch') = ? ORDER BY id", (batch_id,)
    ).fetchall()
    return [(r[0], json.loads(r[1]) if r[1] else {}) for r in rows]


def _foreign_links(conn: sqlite3.Connection, concept_id: str, batch_id: str) -> int:
    """extracted-from edges on this Concept that the batch did NOT write.

    What a later paper run leaves behind when it matches a harvested name. It is
    work this batch does not own, and deleting the Concept would destroy it.
    """
    rows = conn.execute(
        "SELECT attrs FROM edges WHERE kind = 'extracted-from' AND source_id = ?",
        (concept_id,),
    ).fetchall()
    foreign = 0
    for (raw,) in rows:
        attrs = json.loads(raw) if raw else {}
        if attrs.get("harvest_batch") != batch_id:
            foreign += 1
    return foreign


def revert_batch(
    conn: sqlite3.Connection, batch_id: str, dry_run: bool = False
) -> RevertReport:
    """Undo one harvest batch, and nothing else.

    PER-CONCEPT SKIP WITH A LOUD REPORT. Operator decision 2026-09-25. A
    Concept is left entirely intact if a human has reviewed or retired it, or
    if it has gained an extracted-from edge the batch did not write. Everything
    untouched is removed.

    REFUSING THE WHOLE BATCH WAS CONSIDERED AND REFUSED: one linked Concept out
    of two hundred would block the revert entirely, which is precisely the
    situation a revert exists for. CASCADING WAS ALSO REFUSED: it restores the
    node count exactly and destroys a human's review and paper links a later
    run computed and paid for — work that is not the batch's to delete.

    Two passes, and the order matters. Attachments to PRE-EXISTING Concepts are
    detached first: those edges carry the batch id while their source node does
    not, so they must be found by the edge and never by the node, or reverting
    would either miss them or delete a Concept belonging to the original 97.
    """
    report = RevertReport(batch_id=batch_id, dry_run=dry_run)
    batch_ids = {cid for cid, _ in _batch_concepts(conn, batch_id)}

    # Pass 1 — edges the batch wrote onto Concepts it did not create.
    edge_rows = conn.execute(
        "SELECT id, source_id, attrs FROM edges WHERE kind = 'extracted-from'"
    ).fetchall()
    detach: list[int] = []
    for edge_id, source_id, raw in edge_rows:
        attrs = json.loads(raw) if raw else {}
        if attrs.get("harvest_batch") == batch_id and source_id not in batch_ids:
            detach.append(edge_id)

    # Pass 2 — the Concepts the batch created.
    delete: list[str] = []
    for concept_id, attrs in _batch_concepts(conn, batch_id):
        state = attrs.get("curation_state") or "harvested"
        name = attrs.get("name", "")
        if state == "reviewed":
            report.skipped.append(RevertSkip(
                concept_id, name, SKIP_REVIEWED,
                f"reviewed by {attrs.get('reviewed_by') or 'unknown'} "
                f"on {attrs.get('reviewed_at') or 'unknown date'}"))
            continue
        if state == "retired":
            report.skipped.append(RevertSkip(
                concept_id, name, SKIP_RETIRED,
                "a human judged this concept wrong; the judgement outlives the batch"))
            continue
        foreign = _foreign_links(conn, concept_id, batch_id)
        if foreign:
            report.skipped.append(RevertSkip(
                concept_id, name, SKIP_LINKED,
                f"{foreign} extracted-from edge(s) this batch did not write"))
            continue
        delete.append(concept_id)

    report.edges_detached = len(detach)
    report.concepts_deleted = delete

    if dry_run:
        return report

    for edge_id in detach:
        conn.execute("DELETE FROM edges WHERE id = ?", (edge_id,))
    for concept_id in delete:
        conn.execute("DELETE FROM edges WHERE source_id = ? OR target_id = ?",
                     (concept_id, concept_id))
        conn.execute("DELETE FROM nodes WHERE id = ?", (concept_id,))
    conn.commit()
    return report


def format_revert_report(report: RevertReport) -> str:
    """Loud rather than silent. The skipped list is the point of the report."""
    head = "Revert" + (" (DRY RUN — nothing deleted)" if report.dry_run else "")
    lines = [
        f"{head} of batch {report.batch_id}",
        f"  concepts deleted  {len(report.concepts_deleted)}",
        f"  edges detached    {report.edges_detached}",
    ]
    if report.skipped:
        lines.append(f"  SKIPPED           {len(report.skipped)} "
                     "— these were NOT reverted:")
        for s in report.skipped:
            lines.append(f"    {s.concept_id}  {s.name}")
            lines.append(f"      {s.reason}: {s.detail}")
        lines.append("  This batch did NOT come out whole. Exit code 1.")
    return "\n".join(lines)
