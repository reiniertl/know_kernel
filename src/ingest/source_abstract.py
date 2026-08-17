"""Source abstract storage (IFC-KK-SOURCE-ABSTRACT).

Owns the three abstract fields on a Source node so that every writer — the
manual editor in the web layer (ALG-KK-WEB-ABSTRACT-EDIT) and, later, the
arXiv/OpenAlex fetcher — goes through one place and stamps provenance the
same way.

The fields are optional extras on Source. They are deliberately absent from
REQUIRED_ATTRS["Source"]: adding them there would invalidate every existing
Source node and every add_node call in the ingest pipeline.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

from graph.engine import get_node, update_node_attrs


# Where an abstract came from. "arxiv" and "pdf" are verbatim text; "openalex"
# is reconstructed from an inverted index and so is not word-for-word the
# published abstract; "manual" was typed or corrected by a human.
VALID_ABSTRACT_SOURCES = ("arxiv", "openalex", "pdf", "manual")


@dataclass
class AbstractResult:
    source_id: str
    abstract: str
    abstract_source: str
    abstract_fetched_at: str


def set_abstract(
    conn: sqlite3.Connection,
    source_id: str,
    text: str,
    source_label: str = "manual",
) -> AbstractResult:
    """Store an abstract on a Source node and stamp its provenance.

    Raises ValueError if `source_id` names no node or names a node of another
    kind, if `text` is empty after stripping, or if `source_label` is not one
    of VALID_ABSTRACT_SOURCES.

    Source is not revalidated after the write. validate_node against Source
    applies the must-have-an-Advisory rule, which the great majority of real
    Sources do not satisfy; revalidating here would reject a good abstract for
    an unrelated pre-existing gap. The write touches only optional attrs and
    cannot make a valid Source invalid.
    """
    if source_label not in VALID_ABSTRACT_SOURCES:
        raise ValueError(
            f"Invalid abstract source '{source_label}'. Must be one of: "
            + ", ".join(VALID_ABSTRACT_SOURCES)
        )

    cleaned = text.strip() if text else ""
    if not cleaned:
        raise ValueError("Abstract must be non-empty")

    node = get_node(conn, source_id)
    if node is None or node["kind"] != "Source":
        raise ValueError(f"Source node '{source_id}' does not exist")

    stamped = date.today().isoformat()
    update_node_attrs(conn, source_id, {
        "abstract": cleaned,
        "abstract_source": source_label,
        "abstract_fetched_at": stamped,
    })

    return AbstractResult(
        source_id=source_id,
        abstract=cleaned,
        abstract_source=source_label,
        abstract_fetched_at=stamped,
    )
