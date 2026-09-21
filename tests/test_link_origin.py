"""Attributing the 1,147 unmarked provenance edges to a mechanism.

INV-KK-EXTRACT-EVIDENCE-RECORDED: the three markers and why none is a legal
basis for a new edge.
INV-KK-CLAIM-EXTRACT-EVIDENCE-BARE: claim_extractor.py's links carry nothing.
ANN-KK-UNLINKED-PROVENANCE-CENSUS: the id-shape assumption this all rests on.

The whole classification is evidence from ONE source — the shape of the id at
the edge's source end — so these tests exist mostly to pin down what that
evidence does and does not support.
"""

from __future__ import annotations

import json

import pytest

from graph.engine import add_edge, add_node
from graph.link_origin import (
    CLAIM_EXTRACT_PREFIXES,
    EXTRACTOR_PREFIXES,
    MECHANISM_NOTES,
    build_origin_marker,
    classify_link_origin,
    mark_unmarked_provenance_edges,
)
from graph.rules import (
    CLAIM_EXTRACT_UNVERIFIED_BASIS,
    EXTRACTOR_PREVERDICT_BASIS,
    LEGACY_UNVERIFIED_BASIS,
    MECHANISM_UNATTRIBUTED_BASIS,
    OUT_OF_SCOPE_BASES,
    VALID_EVIDENCE_BASES,
    check_link_evidence_recorded,
)
from graph.schema import init_db


HEX12 = "0123456789ab"


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "origin.db")
    add_node(c, "src-1", "Source", {
        "url": "https://example.com/p.pdf", "source_type": "paper",
        "license": "MIT", "title": "A Paper"})
    add_node(c, "ev-1", "Evidence", {
        "artifact_class": "A", "contamination_level": "L0", "text": "body"})
    add_edge(c, "sourced-from", "ev-1", "src-1")
    c.commit()
    yield c
    c.close()


NODE_ATTRS = {
    "Observation": {"claim": "x", "confidence": "medium",
                    "source_date": "2026-09-21", "artifact_class": "B"},
    "KernelInvariant": {"predicate": "x", "strength": "safety",
                        "scope": "per-operation", "artifact_class": "B"},
    "FailureMode": {"symptom": "x", "blast_radius": "kernel-wide",
                    "recoverability": "data-loss", "artifact_class": "B"},
    "Concept": {"name": "c", "description": "x",
                "artifact_class": "abstracted-mechanism", "key_properties": [],
                "tradeoffs": [], "design_rationale": "n/a"},
}


def _link(conn, node_id, kind="Observation", attrs=None):
    add_node(conn, node_id, kind, dict(NODE_ATTRS[kind]))
    add_edge(conn, "extracted-from", node_id, "ev-1", attrs)
    conn.commit()


# --- the classifier ---------------------------------------------------------


@pytest.mark.parametrize("prefix", CLAIM_EXTRACT_PREFIXES)
def test_a_claim_extractor_minted_id_is_attributed_to_it(prefix):
    assert classify_link_origin(f"{prefix}-{HEX12}") == CLAIM_EXTRACT_UNVERIFIED_BASIS


@pytest.mark.parametrize("prefix", EXTRACTOR_PREFIXES)
def test_an_extractor_minted_id_is_attributed_to_the_pre_verdict_era(prefix):
    assert classify_link_origin(f"{prefix}-{HEX12}") == EXTRACTOR_PREVERDICT_BASIS


@pytest.mark.parametrize("node_id", [
    # Hand-written slugs. No writer in this codebase mints one.
    "obs-actplane-enforcement",
    "disc-agileos-gpu-os-layer-for-prote",
    "fm-osdi26-banakar",
    "profile-osdi26-ahn",
    "prop-lwn-bpf-token",
    "bench-lwn-eevdf-chromeos",
    # hex12 under a prefix whose minting form is nowhere in src/ history.
    f"perf-{HEX12}",
    f"fail-{HEX12}",
])
def test_an_id_no_writer_mints_is_left_unattributed(node_id):
    assert classify_link_origin(node_id) == MECHANISM_UNATTRIBUTED_BASIS


def test_a_vuln_id_is_unattributed_although_its_prefix_is_minted_in_src():
    """src/ingest/vuln_tracker.py mints vuln- ids but writes no extracted-from
    edge at all, so the node's minter is known and the EDGE's writer is not.
    The basis is named for the mechanism, not the node, for exactly this case."""
    assert classify_link_origin(f"vuln-{HEX12}") == MECHANISM_UNATTRIBUTED_BASIS


def test_a_concept_id_is_unattributed_even_though_the_extractor_mints_it():
    """store_rich_concept mints concept- ids, but every concept- provenance
    edge in this corpus came from the title-regex linker and already carries
    unverified-legacy. An UNMARKED one is ambiguous between the two, and
    claiming the extractor wrote it would assert what the evidence cannot
    place."""
    assert "concept" not in EXTRACTOR_PREFIXES
    assert classify_link_origin(f"concept-{HEX12}") == MECHANISM_UNATTRIBUTED_BASIS


def test_a_partial_hash_is_not_treated_as_minted():
    """uuid4().hex[:12] is exactly twelve lowercase hex characters. Anything
    else is somebody typing."""
    for suffix in ("0123456789a", "0123456789abc", "0123456789AB", "0123-456789"):
        assert classify_link_origin(f"obs-{suffix}") == MECHANISM_UNATTRIBUTED_BASIS


# --- what the marker carries, and what it deliberately does not -------------


def test_the_marker_carries_no_date():
    """The edges table records no creation time. Knowing WHICH program wrote an
    edge is not knowing WHEN, and a date invented per group would drag these
    edges inside INV-KK-EXTRACT-EVIDENCE-RECORDED's scope on a fiction."""
    for node_id in (f"obs-{HEX12}", f"kinv-{HEX12}", "fm-osdi26-banakar"):
        assert "checked_at" not in build_origin_marker(node_id)


def test_the_marker_names_the_mechanism_in_words():
    marker = build_origin_marker(f"obs-{HEX12}")
    assert marker["basis"] == CLAIM_EXTRACT_UNVERIFIED_BASIS
    assert "claim_extractor.py" in marker["mechanism"]
    assert marker["grounded"] is False
    assert marker["superseded"] is False


def test_an_unattributed_marker_says_it_is_not_recoverable():
    assert "not recoverable" in MECHANISM_NOTES[MECHANISM_UNATTRIBUTED_BASIS]


@pytest.mark.parametrize("basis", [
    CLAIM_EXTRACT_UNVERIFIED_BASIS,
    EXTRACTOR_PREVERDICT_BASIS,
    MECHANISM_UNATTRIBUTED_BASIS,
])
def test_no_marker_is_a_legal_basis_for_a_new_edge(basis):
    """Marking the old links must not make their mechanisms acceptable."""
    assert basis not in VALID_EVIDENCE_BASES
    assert basis in OUT_OF_SCOPE_BASES


@pytest.mark.parametrize("basis", [
    CLAIM_EXTRACT_UNVERIFIED_BASIS,
    EXTRACTOR_PREVERDICT_BASIS,
    MECHANISM_UNATTRIBUTED_BASIS,
])
def test_an_in_scope_edge_claiming_a_marker_is_a_violation(conn, basis):
    _link(conn, "obs-cheat", attrs={
        "grounded": False, "ungrounded_count": 0, "ungrounded": [],
        "basis": basis, "basis_sha256": "", "model": "", "checked_at": "2026-12-01"})
    sweep = check_link_evidence_recorded(conn)
    assert sweep.violations
    assert "not one of" in sweep.violations[0].message


# --- the sweep census -------------------------------------------------------


def test_a_marked_non_concept_edge_is_neither_conforming_nor_a_violation(conn):
    """Mirrors the Concept case. These edges are out of scope and say why."""
    _link(conn, f"obs-{HEX12}", attrs=build_origin_marker(f"obs-{HEX12}"))
    sweep = check_link_evidence_recorded(conn)
    assert sweep.marked_by_basis == {CLAIM_EXTRACT_UNVERIFIED_BASIS: 1}
    assert sweep.undated == 0
    assert sweep.conforming == 0
    assert sweep.violations == []


def test_legacy_is_counted_both_in_its_own_field_and_in_the_census(conn):
    """legacy_marked is kept separate because it is the one population whose
    mechanism is known to be WRONG rather than merely unrecorded."""
    _link(conn, "concept-legacy", kind="Concept", attrs={
        "basis": LEGACY_UNVERIFIED_BASIS, "grounded": False, "superseded": False})
    _link(conn, f"obs-{HEX12}", attrs=build_origin_marker(f"obs-{HEX12}"))
    sweep = check_link_evidence_recorded(conn)
    assert sweep.legacy_marked == 1
    assert sweep.marked == 2
    assert sweep.marked_by_basis[LEGACY_UNVERIFIED_BASIS] == 1


def test_an_unmarked_edge_is_still_undated_and_distinguishable(conn):
    _link(conn, f"obs-{HEX12}", attrs=build_origin_marker(f"obs-{HEX12}"))
    _link(conn, "obs-bare", attrs=None)
    sweep = check_link_evidence_recorded(conn)
    assert (sweep.undated, sweep.marked) == (1, 1)


# --- the marking pass -------------------------------------------------------


def test_the_pass_marks_every_bare_edge_and_says_what_it_did(conn):
    _link(conn, f"obs-{HEX12}")
    _link(conn, f"kinv-{HEX12}", kind="KernelInvariant")
    _link(conn, "fm-osdi26-banakar", kind="FailureMode")
    result = mark_unmarked_provenance_edges(conn)
    conn.commit()
    assert result.marked == 3
    assert result.by_basis == {
        CLAIM_EXTRACT_UNVERIFIED_BASIS: 1,
        EXTRACTOR_PREVERDICT_BASIS: 1,
        MECHANISM_UNATTRIBUTED_BASIS: 1,
    }
    assert check_link_evidence_recorded(conn).undated == 0


def test_the_pass_is_idempotent(conn):
    _link(conn, f"obs-{HEX12}")
    mark_unmarked_provenance_edges(conn)
    conn.commit()
    again = mark_unmarked_provenance_edges(conn)
    assert (again.marked, again.already_marked) == (0, 1)


def test_the_pass_does_not_overwrite_a_legacy_marker(conn):
    """Re-marking would replace a known mechanism with a weaker guess: a
    concept- id classifies as unattributed, which is less than 'title regex'."""
    _link(conn, "concept-legacy", kind="Concept", attrs={
        "basis": LEGACY_UNVERIFIED_BASIS, "grounded": False,
        "superseded": False, "mechanism": "title regex"})
    result = mark_unmarked_provenance_edges(conn)
    conn.commit()
    assert (result.marked, result.already_marked) == (0, 1)
    row = conn.execute(
        "SELECT attrs FROM edges WHERE source_id = 'concept-legacy'").fetchone()
    assert json.loads(row[0])["basis"] == LEGACY_UNVERIFIED_BASIS


def test_the_pass_refuses_to_touch_an_in_scope_edge(conn):
    """Marking an edge that carries a real verdict would be relabelling to make
    a rule pass, which CLAUDE.md rule 2 forbids."""
    real = {"grounded": False, "ungrounded_count": 2, "ungrounded": ["a b"],
            "basis": "evidence-text", "basis_sha256": "ab" * 32,
            "model": "claude-sonnet-4-6", "checked_at": "2026-09-21"}
    _link(conn, f"obs-{HEX12}", attrs=real)
    result = mark_unmarked_provenance_edges(conn)
    conn.commit()
    assert (result.marked, result.in_scope_skipped) == (0, 1)
    row = conn.execute(
        f"SELECT attrs FROM edges WHERE source_id = 'obs-{HEX12}'").fetchone()
    assert json.loads(row[0])["basis"] == "evidence-text"


def test_a_dry_run_writes_nothing(conn):
    _link(conn, f"obs-{HEX12}")
    result = mark_unmarked_provenance_edges(conn, dry_run=True)
    assert result.marked == 1
    assert check_link_evidence_recorded(conn).undated == 1
