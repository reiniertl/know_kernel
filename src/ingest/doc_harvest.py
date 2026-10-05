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

THE NAME MUST STILL MEAN ONE THING WHEN THIS DOCUMENT IS GONE. You are reading
one document; the vocabulary spans hundreds. A name that is obvious here can be
ambiguous there, and the ambiguity is invisible to you because the other
documents are not in front of you. IF THE MECHANISM BELONGS TO ONE DRIVER, BUS
OR PROTOCOL, THE NAME MUST SAY WHICH. Writing "Trace Events" for the DWC3 USB
driver's tracing, "Driver Registration" for the VME subsystem's, "Protocol
Driver" for SPI's or "Signal" for a counter's data stream produces a name that
four unrelated documents will all claim. "DWC3 Trace Events", "VME Driver
Registration", "SPI Protocol Driver" and "Counter Signal" are the same concepts,
named so they survive the company of the rest of the corpus.

This does NOT conflict with naming a general class: where the mechanism really
is general — Grace Period, Copy-on-Write, Journaling, Scatter-Gather — the bare
name is right and is what you should use. The test is whether another kernel
subsystem could define something it would also call this. If it could, qualify.

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
      "name": "<the mechanism, as a general class — qualified by its driver, bus or protocol if it belongs to one>",
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


def build_harvest_system_prompt(vocabulary: str = "", subsystems: str = "") -> str:
    """The system prompt, carrying the vocabularies (INV-KK-LLM-CACHE-STABLE-PREFIX).

    Both vocabularies are constant across a batch and were being re-sent with
    every document. Here they are part of the prefix that is identical across
    the run and can be cached once. Both default to empty so existing callers
    and tests are unaffected.
    """
    tail = "\n\n".join(part for part in (vocabulary, subsystems) if part)
    return f"{HARVEST_SYSTEM_PROMPT}\n\n{tail}" if tail else HARVEST_SYSTEM_PROMPT


def build_harvest_prompt(document_text: str) -> str:
    """The user prompt: the document, and nothing else.

    The vocabularies moved to build_harvest_system_prompt on 2026-09-28 so the
    prefix stays byte-identical across a batch.
    """
    return f"Name the mechanisms THIS DOCUMENT DEFINES:\n\n{document_text}"


#: INV-KK-HARVEST-DOCUMENT-DEFINES. How much of a document decides its genre.
#: The title and opening paragraphs; a marker further in is a mention, not a
#: subject. adding-new-filesystems.rst announces itself in its second sentence.
PROCEDURAL_OPENING_CHARS = 2000

#: INV-KK-HARVEST-DOCUMENT-DEFINES. A document ABOUT the act of contributing,
#: submitting or maintaining, rather than about a mechanism.
#:
#: MEASURED 2026-09-29 OVER ALL 245 SEEDED kernel-doc SOURCES: these refuse
#: exactly one, filesystems/adding-new-filesystems.rst, which is the one that
#: produced "Filesystem Submission Process" and "Filesystem Maintenance
#: Commitment" from inside a directory INV-KK-SEED-PATH-DEFINITIONAL sanctions.
#:
#: A FILENAME RULE WAS TRIED FIRST AND REFUSED ON PRECISION. Stems like
#: "process", "howto" and "adding-new-" refuse 4 of the 245 and 3 are wrong:
#: mm/process_addrs.rst and core-api/dma-api-howto.rst are mechanism documents
#: whose names merely read like procedures.
#:
#: SUBJECT, NOT FORM, AND "checklist" IS WHY THAT DISTINCTION IS WRITTEN DOWN.
#: RCU/checklist.rst is "Review Checklist for RCU Patches" — procedural in
#: shape — and it created SRCU (Sleepable RCU) and RCU Callbacks, both
#: legitimate. Its subject is RCU. A marker naming the FORM of a document
#: refuses good mechanisms; a marker naming the ACT it describes does not.
PROCEDURAL_OPENING_MARKERS = (
    "what is involved in adding",
    "how to submit",
    "how to contribute",
    "submitting patches",
    "submitting a patch",
    "patch submission",
    "send your patches",
    "code of conduct",
    "this document describes the process",
    "before you submit",
)


#: INV-KK-HARVEST-DOCUMENT-DEFINES. Above this share of non-blank lines inside
#: toctree blocks, a document is navigation rather than definition.
#:
#: MEASURED 2026-09-30 OVER ALL 1,510 kernel-doc DOCUMENTS, and the two
#: populations barely touch: navigation pages score 0.55 to 0.97 and the
#: highest-scoring real document scores 0.03. The threshold sits in a gap
#: seventeen times wider than the nearest real document's score.
NAVIGATION_TOCTREE_SHARE = 0.5


def document_is_navigation(text: str) -> bool:
    """INV-KK-HARVEST-DOCUMENT-DEFINES: is this a table of contents?

    A subtree's index.rst names its children and defines nothing. Harvested on
    2026-09-30, trace/index.rst, mm/index.rst and filesystems/index.rst
    produced nine Concepts: four correct attachments to entries they merely
    name, and FIVE creations whose only evidence is the table of contents —
    "Tracing Frameworks" and "Filesystem Support Layers" among them, which are
    directory summaries rather than mechanisms. "Ring Buffer" was another, and
    it went on to form three of that day's thirteen collision pairs: a
    navigation page does not merely add noise, it manufactures collisions.

    ALG-KK-SEED-DOC-SUBTREE claimed these were "refused as a stub". They were
    not. classify_content refuses a document for being SHORT, and a subtree
    index is not short — those three carry 2,077, 2,057 and 1,826 characters of
    genuine prose introduction before the toctree.

    IT IS DOMINANCE, NOT PRESENCE, AND THAT WAS MEASURED BEFORE IT WAS WRITTEN.
    60 of 1,510 documents contain a '.. toctree::' directive and only 24 are
    named index.rst. Refusing on the directive would discard
    mm/process_addrs.rst (47,256 characters) and mm/damon/design.rst (47,184),
    which carry a toctree near the end and are exactly the design documents
    this corpus exists for.

    IT READS THE BODY, NOT THE FILENAME, for the reason the procedural filter
    does: userspace-api/media/v4l/user-func.rst scores 0.93 and is a list of
    sub-pages exactly like an index, while process_addrs.rst is named like a
    process document and is not one.
    """
    lines = (text or "").splitlines()
    total = sum(1 for line in lines if line.strip())
    if not total:
        return False

    in_toctree = 0
    inside = False
    for line in lines:
        if ".. toctree::" in line:
            inside = True
            in_toctree += 1
            continue
        if inside:
            if not line.strip():
                continue
            # A toctree's entries and options are indented; the first
            # unindented line ends the block.
            if line[:1].isspace():
                in_toctree += 1
            else:
                inside = False
    return in_toctree / total >= NAVIGATION_TOCTREE_SHARE


def document_announces_a_procedure(text: str) -> bool:
    """INV-KK-HARVEST-DOCUMENT-DEFINES: is this document ABOUT a procedure?

    THE GAP BETWEEN TWO RULES THAT ARE BOTH CORRECT.
    INV-KK-HARVEST-NAME-IS-A-CLASS reads the SHAPE of a proposed name and
    passes "Filesystem Submission Process" — a well-formed name for a thing
    that is not a kernel mechanism, as that node says itself about "Patch
    Submission". INV-KK-SEED-PATH-DEFINITIONAL works at DIRECTORY granularity
    and cannot see one process document sitting in a design directory. Neither
    is wrong. Between them was a gap exactly one document wide.

    IT READS THE DOCUMENT'S OWN TEXT, which is the only thing that survives a
    file being moved or renamed, and it reads only the opening, because a
    mechanism document may well mention patches half way down.
    """
    if not text:
        return False
    opening = text[:PROCEDURAL_OPENING_CHARS].lower()
    return any(marker in opening for marker in PROCEDURAL_OPENING_MARKERS)


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


class ForeignEdgeError(Exception):
    """An extracted-from edge already belongs to a different harvest batch.

    Raised by _attach and caught by harvest_document, which counts it as
    attached_foreign. Not an error in the run — it is the invariant holding.
    """

    def __init__(self, owner: str) -> None:
        self.owner = owner
        super().__init__(f"edge belongs to batch {owner}")


@dataclass
class DocHarvestResult:
    """What one document yielded."""

    evidence_id: str
    concepts_created: list[str] = field(default_factory=list)
    concepts_attached: list[str] = field(default_factory=list)
    rejected_not_mechanism: int = 0
    rejected_incomplete: int = 0
    rejected_not_a_class: int = 0
    #: THE NAMES BEHIND rejected_not_a_class, NOT JUST HOW MANY.
    #: Measured 2026-10-05: userspace-api rejected 299 names over 408 documents
    #: against driver-api's 32 over 196, and NOTHING RECORDED WHAT THEY WERE. A
    #: count without its subjects cannot distinguish a gate working hard on an
    #: ABI reference manual from a gate that has started refusing good names —
    #: the two look identical, which is the null-indistinguishable-from-absence
    #: shape this project keeps finding. The question was answerable only by
    #: grouping documents by subdirectory and inferring; with the names it is a
    #: one-line read. Bounded so a pathological batch cannot bloat the report.
    rejected_names: list[str] = field(default_factory=list)
    attached_foreign: int = 0
    subsystem_id: str = ""
    subsystem_unmatched: str = ""
    dry_run: bool = False
    prompt_chars: int = 0
    cached_tokens: int = 0


#: How many refused names one document's result keeps. A document proposing
#: more than this is already pathological and the count still tells the truth;
#: the names are a diagnostic, not a ledger.
MAX_REJECTED_NAMES_RECORDED = 12


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

    system_prompt = build_harvest_system_prompt(vocabulary, subsystem_context)
    user_prompt = build_harvest_prompt(document_text)
    result.prompt_chars = len(system_prompt) + len(user_prompt)

    # BEFORE any client work. A dry run must size the batch for someone
    # deciding whether to pay for the real one.
    if dry_run:
        return result

    if client is None:
        raise ValueError("harvest_document needs a client unless dry_run")

    response = client.create_message(
        model=model or default_model_for(DEFAULT_PROVIDER),
        system=system_prompt,
        user=user_prompt,
        max_tokens=4096,
    )
    # INV-KK-LLM-CACHE-REPORTED. The first run since the vocabulary moved
    # into the system prompt; a zero here is a finding, not a detail.
    result.cached_tokens = int(response.get("cached_tokens", 0) or 0)
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
            try:
                _attach(conn, existing, evidence_id, batch_id, document_text,
                        model, item.get("description", ""))
            except ForeignEdgeError:
                # The edge belongs to an earlier batch and stays with it.
                result.attached_foreign += 1
                continue
            result.concepts_attached.append(existing)
            continue

        # INV-KK-HARVEST-NAME-IS-A-CLASS, AFTER matching and never before.
        if not name_is_a_class(name, subsystems):
            result.rejected_not_a_class += 1
            if len(result.rejected_names) < MAX_REJECTED_NAMES_RECORDED:
                result.rejected_names.append(name)
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

    # INV-KK-HARVEST-READ-RECORDED. The read is recorded EVEN WHEN IT YIELDED
    # NOTHING, which is the whole point: the only prior evidence of a read was
    # a Concept edge, and a null answer writes none. Batch 9e2419bc read 99
    # documents and 10 defined no reusable mechanism, so those ten looked
    # untouched and were offered straight back to the next run.
    #
    # The BATCH ID and not merely a flag, because INV-KK-HARVEST-BATCH-REVERTIBLE
    # makes the batch the unit of undo — and a run that produced little is the
    # one most likely to be repeated by someone who assumes it never ran.
    mark_evidence_read(conn, evidence_id, batch_id)
    return result


def mark_evidence_read(
    conn: sqlite3.Connection, evidence_id: str, batch_id: str
) -> None:
    """Record that the harvest READ this Evidence (INV-KK-HARVEST-READ-RECORDED).

    AN ATTRIBUTE AND NOT AN EDGE. A marker edge would need EDGE_KINDS and
    EDGE_VALID_PAIRS widened for a single use, which ALG-KK-WEB-CONCEPT-DISTINCT
    records as having been refused once already — it reused the unused
    `contradicts` kind rather than widen the metamodel. An edge also needs a
    source node, and a no-yield read has none.

    THE WRITE IS SAFE HERE AND THAT WAS CHECKED RATHER THAN ASSUMED.
    update_node_attrs re-checks only REQUIRED_ATTRS, and Evidence's two —
    artifact_class and contamination_level — are always present on a seeded
    document. There is no revalidation trap of the kind that forced
    venue_store's direct-SQL carve-out, where re-running validate_node on a
    Source would have failed on an unrelated missing Advisory.
    """
    from graph.engine import update_node_attrs

    update_node_attrs(conn, evidence_id, {
        "harvest_read_batch": batch_id,
        "harvest_read_at": datetime.now(timezone.utc).date().isoformat(),
    })


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
        "SELECT id, attrs FROM edges WHERE kind = 'extracted-from' "
        "AND source_id = ? AND target_id = ?", (concept_id, evidence_id)
    ).fetchone()
    if existing:
        prior = json.loads(existing[1]) if existing[1] else {}
        owner = prior.get("harvest_batch")
        if owner and owner != batch_id:
            # A BATCH NEVER TAKES OWNERSHIP OF ANOTHER BATCH'S EDGE.
            # Operator decision 2026-09-28, and this is what makes
            # INV-KK-HARVEST-BATCH-REVERTIBLE structural rather than dependent
            # on the caller selecting correctly. Overwriting here would move
            # the edge into this batch, so reverting THIS batch would delete an
            # edge the earlier one created — leaving its Concept with no
            # provenance, and leaving the earlier revert unable to reclaim it.
            # Left exactly as found and counted by the caller.
            raise ForeignEdgeError(owner)
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
    conn: sqlite3.Connection,
    source_types: tuple[str, ...] | None = None,
    include_harvested: bool = False,
    path_prefixes: tuple[str, ...] | None = None,
) -> tuple[list[str], list[str], list[str], list[str], list[str]]:
    """Evidence of canonical documents, split four ways.

    Returns (with_text, skipped_empty, skipped_harvested, skipped_procedural,
    skipped_navigation).

    PROCEDURAL DOCUMENTS ARE REFUSED HERE AND NOT IN harvest_document, per
    INV-KK-HARVEST-DOCUMENT-DEFINES, because refusing at selection costs no
    tokens — the document never reaches a prompt and no client is constructed
    for it. The refused ids are RETURNED rather than dropped, for the same
    reason rejected_not_a_class is counted separately from the other two: a
    filter that discarded silently would be indistinguishable from a document
    that defined nothing.

    The empty ones are
    filtered BEFORE the limit is applied, so --limit 10 means ten documents
    actually sent — the 241-empty lesson from ALG-KK-EXTRACT-CLI, which this
    follows rather than inventing a third convention.

    ALREADY-READ DOCUMENTS ARE EXCLUDED BY DEFAULT, from 2026-09-28. The old
    behaviour returned every document carrying text, so the obvious command
    re-read the 17 already harvested — and _attach UPDATES an existing edge
    rather than inserting a second one, so a re-read rewrote harvest_batch on
    edges the PREVIOUS batch had written and made both batches' reverts lossy.
    See INV-KK-HARVEST-BATCH-REVERTIBLE. include_harvested restores the old
    behaviour for a deliberate re-read; _attach refuses to take ownership
    either way, so the property does not depend on this flag.

    THE kind = 'Concept' FILTER IS LOAD-BEARING. Evidence carries
    extracted-from edges from PerformanceProfile, KernelInvariant, FailureMode
    and InteractionProtocol too. Measured 2026-09-28: 17 of the 132 doc
    Evidence nodes carry a Concept edge and 18 carry ANY extracted-from edge.
    The difference is Documentation/core-api/kernel-api.rst, which the old
    pre-verdict extractor read and this harvest never did — a filter on "any
    extracted-from edge" would skip it permanently. The same conflation has
    produced a wrong count three times in this project.
    """
    types = source_types or DOC_SOURCE_TYPES
    placeholders = ", ".join("?" for _ in types)
    params: list[str] = list(types)

    # A PATH FILTER ON SELECTION, NOT ON ADMISSION. INV-KK-SEED-PATH-DEFINITIONAL
    # decides what may ENTER the graph and is enforced at seeding; this decides
    # what one RUN reads from what is already there, so it can never admit
    # anything the seed rule refused. It exists because --limit applies AFTER
    # this query, which orders by Evidence id — a hash — so a bound of 99
    # returned an arbitrary 99 documents drawn from every subtree at once. A
    # batch that mixes trace/ with userspace-api/media/ cannot be read, and
    # INV-KK-HARVEST-BATCH-REVERTIBLE makes that one batch the unit of undo.
    path_clause = ""
    if path_prefixes:
        path_clause = " AND (" + " OR ".join(
            "json_extract(src.attrs, '$.url') LIKE ?" for _ in path_prefixes
        ) + ")"
        params.extend(f"%{prefix}%" for prefix in path_prefixes)

    rows = conn.execute(
        "SELECT e.id, COALESCE(json_extract(e.attrs, '$.text'), '') FROM nodes e "
        "JOIN edges s ON s.source_id = e.id AND s.kind = 'sourced-from' "
        "JOIN nodes src ON src.id = s.target_id "
        "WHERE e.kind = 'Evidence' "
        f"AND json_extract(src.attrs, '$.source_type') IN ({placeholders})"
        + path_clause +
        " ORDER BY e.id",
        params,
    ).fetchall()
    skipped = [r[0] for r in rows if not r[1].strip()]
    # INV-KK-HARVEST-DOCUMENT-DEFINES, before anything else looks at the list.
    # --include-harvested does NOT restore a procedural document: that flag
    # exists to re-read a document deliberately, and a document this rule
    # refuses is one nothing should read at all.
    procedural = [
        r[0] for r in rows if r[1].strip() and document_announces_a_procedure(r[1])
    ]
    # INV-KK-HARVEST-DOCUMENT-DEFINES' second genre. Counted SEPARATELY from
    # procedural, for the reason listing-failed is counted separately from
    # unreachable: two refusals with different causes that report as one number
    # are a number nobody can act on.
    navigation = [
        r[0] for r in rows
        if r[1].strip() and r[0] not in set(procedural)
        and document_is_navigation(r[1])
    ]
    refused = set(procedural) | set(navigation)
    with_text = [
        r[0] for r in rows if r[1].strip() and r[0] not in refused
    ]

    if include_harvested:
        return with_text, skipped, [], procedural, navigation

    # A CONCEPT EDGE IS NOT THE SAME SET AS "HAS BEEN READ", and conflating
    # them cost a repeat read of 10 documents in 99 (INV-KK-HARVEST-READ-RECORDED).
    # The union of both is what "already harvested" means: an edge written by
    # any batch, OR an explicit record that some batch read it and the document
    # defined nothing.
    harvested = {
        r[0] for r in conn.execute(
            "SELECT DISTINCT x.target_id FROM edges x "
            "JOIN nodes n ON n.id = x.source_id AND n.kind = 'Concept' "
            "WHERE x.kind = 'extracted-from'"
        ).fetchall()
    }
    harvested |= {
        r[0] for r in conn.execute(
            "SELECT id FROM nodes WHERE kind = 'Evidence' "
            "AND json_extract(attrs, '$.harvest_read_batch') IS NOT NULL"
        ).fetchall()
    }
    unread = [e for e in with_text if e not in harvested]
    already = [e for e in with_text if e in harvested]
    return unread, skipped, already, procedural, navigation


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

    # INV-KK-HARVEST-READ-RECORDED: clear the read marks this batch wrote, so a
    # reverted document becomes selectable again. Without this the undo would be
    # nearly complete — the concepts gone but the documents still counted as
    # read, which is the worst of both states.
    #
    # Direct SQL and not update_node_attrs, because there is no "remove an
    # attribute" on that path and re-writing the whole attrs dict to drop two
    # keys is a wider blast radius than a targeted json_remove.
    conn.execute(
        "UPDATE nodes SET attrs = json_remove(attrs, '$.harvest_read_batch', "
        "'$.harvest_read_at') WHERE kind = 'Evidence' "
        "AND json_extract(attrs, '$.harvest_read_batch') = ?",
        (batch_id,),
    )
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
