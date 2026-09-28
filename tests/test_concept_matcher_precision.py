"""The matcher rescues near-misses; it must not guess between neighbours.

INV-KK-EXTRACT-CONCEPT-MATCHED: fuzzy_match_concept refuses a tie rather than
    taking the first match by dict iteration order.
IFC-KK-CONCEPT-REVIEW-PRIORITY: the collision signal drops the Levenshtein
    tier, on measured precision of zero.

MEASURED 2026-09-28 AGAINST THE 296-CONCEPT VOCABULARY, and the measurement
narrowed the claim that prompted the change. The concern raised was that a
paper about zsmalloc could be linked to Vmalloc. A self-match test misroutes
ZERO of 296, because the exact tier fires first. The real defect was only that
a name equidistant from SEVERAL concepts was decided arbitrarily.
"""

from __future__ import annotations

import pytest

from graph.concept_vocabulary import (
    colliding_concepts,
    fuzzy_match_concept,
    normalise_concept_name,
    strict_match_concept,
)
from graph.engine import add_node
from graph.schema import init_db

#: The names that made the 2026-09-28 measurement, verbatim.
NEIGHBOURS = [
    "Kmalloc", "Vmalloc", "zsmalloc", "kref", "kset",
    "Slab Cache", "Swap Cache",
    "Reed-Solomon Encoding", "Reed-Solomon Decoding",
    "PMD Page Table Helpers", "PTE Page Table Helpers", "PUD Page Table Helpers",
    "memalloc_nofs_save/restore", "memalloc_noio_save/restore",
    # the true pairs, which must survive
    "Folio", "Folio Marks", "Mutex", "Mutex Waiters Tree",
    "NAPI", "NAPI (New API) Polling",
    "Robust Futex", "Robust Futexes",
    "io_uring", "io_uring Asynchronous I/O",
    "Grace Period", "Sequence Counters",
]


def _table(names):
    return {normalise_concept_name(n): f"id::{n}" for n in names}


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "matcher.db")
    for n in NEIGHBOURS:
        add_node(c, f"concept-{abs(hash(n))%10**9}", "Concept", {
            "name": n, "description": "d", "artifact_class": "abstracted-mechanism",
            "key_properties": [], "tradeoffs": [], "design_rationale": "r"})
    c.commit()
    yield c
    c.close()


# --- the tier earns its place ----------------------------------------------


@pytest.mark.parametrize("probe,expected", [
    ("kmallocs", "Kmalloc"),
    ("kreff", "kref"),
    ("slab caches", "Slab Cache"),
    ("krep", "kref"),          # kref at 1, kset at 2 — closer, not a tie
])
def test_a_near_miss_is_still_rescued(probe, expected):
    """The tier is NOT removed from matching. A self-match test over 296 names
    misroutes zero of them and these near-misses resolve correctly, so the
    tier does real work."""
    assert fuzzy_match_concept(probe, _table(NEIGHBOURS)) == f"id::{expected}"


def test_every_real_name_resolves_to_itself():
    """Zero of 296 misrouted, because the exact tier fires first. This is why
    the original worry — a paper about zsmalloc linking to Vmalloc — does not
    happen for a correctly written name."""
    table = _table(NEIGHBOURS)
    for n in NEIGHBOURS:
        assert fuzzy_match_concept(n, table) == f"id::{n}"


# --- but it refuses to guess ------------------------------------------------


@pytest.mark.parametrize("probe", [
    "zmalloc",              # distance 1 from Kmalloc, Vmalloc AND zsmalloc
    "smalloc",
    "Reed-Solomon Coding",  # equidistant from Encoding and Decoding
    "PTD Page Table Helpers",
])
def test_a_tie_refuses_rather_than_picking_by_dict_order(probe):
    """Until 2026-09-28 this returned the FIRST match at the best distance,
    which on a tie is dict iteration order — a silent coin flip writing a real
    edge onto a real paper. strict_match_concept has always refused ties; the
    two matchers disagreed and only one was right."""
    assert fuzzy_match_concept(probe, _table(NEIGHBOURS)) is None


def test_the_two_matchers_now_agree_about_ties():
    table = _table(NEIGHBOURS)
    assert fuzzy_match_concept("zmalloc", table) is None
    assert strict_match_concept("zmalloc", table) is None


def test_a_refusal_is_visible_where_a_wrong_link_is_not():
    """An unmatched name becomes a candidate row a human sees. This asserts the
    contract, not the queue: None is the value the caller routes on."""
    assert fuzzy_match_concept("zmalloc", _table(NEIGHBOURS)) is None


# --- plurals ----------------------------------------------------------------


@pytest.mark.parametrize("plural,singular", [
    ("Robust Futexes", "Robust Futex"),      # the -es case, created as a duplicate
    ("Grace Periods", "Grace Period"),       # -s, already worked
    ("Sequence Counters", "Sequence Counter"),
    ("Policies", "Policy"),                  # -ies, no instance in the corpus yet
])
def test_plural_forms_match_their_singular(plural, singular):
    assert strict_match_concept(plural, _table([singular])) == f"id::{singular}"


def test_a_double_s_is_not_stripped():
    """Guarded so "Access" does not become "Acces"."""
    assert strict_match_concept("Access", _table(["Acces"])) is None


# --- the collision signal ---------------------------------------------------


@pytest.mark.parametrize("a,b", [
    ("Vmalloc", "Kmalloc"), ("Vmalloc", "zsmalloc"), ("Kmalloc", "zsmalloc"),
    ("kref", "kset"), ("Slab Cache", "Swap Cache"),
    ("Reed-Solomon Encoding", "Reed-Solomon Decoding"),
    ("PMD Page Table Helpers", "PTE Page Table Helpers"),
    ("PMD Page Table Helpers", "PUD Page Table Helpers"),
    ("PTE Page Table Helpers", "PUD Page Table Helpers"),
    ("memalloc_nofs_save/restore", "memalloc_noio_save/restore"),
])
def test_the_ten_false_pairs_no_longer_reach_the_review_queue(conn, a, b):
    """All ten came from the Levenshtein tier and every one is a different
    mechanism — 29% of the queue was a pair to dismiss. The signal's job is to
    direct a human minute."""
    col = colliding_concepts(conn)
    names = {r[0]: r[1] for r in conn.execute(
        "SELECT id, json_extract(attrs, '$.name') FROM nodes WHERE kind = 'Concept'")}
    flagged = {names[i] for i in col}
    assert not (a in flagged and b in flagged), f"{a} ~ {b} still collides"


@pytest.mark.parametrize("a,b", [
    ("Folio", "Folio Marks"),
    ("Mutex", "Mutex Waiters Tree"),
    ("NAPI", "NAPI (New API) Polling"),
    ("Robust Futex", "Robust Futexes"),
    ("io_uring", "io_uring Asynchronous I/O"),
])
def test_the_true_pairs_still_reach_the_review_queue(conn, a, b):
    """Prefix and containment keep the 25 pairs worth a human look."""
    col = colliding_concepts(conn)
    names = {r[0]: r[1] for r in conn.execute(
        "SELECT id, json_extract(attrs, '$.name') FROM nodes WHERE kind = 'Concept'")}
    flagged = {names[i] for i in col}
    assert a in flagged and b in flagged, f"{a} ~ {b} stopped colliding"


def test_matching_keeps_levenshtein_while_the_signal_drops_it():
    """One SURFACES a pair for a human, the other ATTACHES a paper. They serve
    different purposes and need not agree."""
    assert fuzzy_match_concept("kreff", _table(["kref"])) == "id::kref"
