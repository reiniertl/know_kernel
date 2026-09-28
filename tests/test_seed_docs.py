"""Seeding the design documentation, and refusing the rest.

ALG-KK-SEED-DOC-SUBTREE: fetch a subtree, ingest what defines.
INV-KK-SEED-PATH-DEFINITIONAL: a path outside the design trees is refused
    BEFORE any fetch, because the only defence against a bad source is not
    harvesting it.
INV-KK-INGEST-SOURCE-HAS-ADVISORY: this is the first ingest path that conforms.

EVERY FETCH IS INJECTED. A test that reaches git.kernel.org is a defect in the
test, not a stronger test.
"""

from __future__ import annotations

import pytest

from graph.rules import (
    DOC_PATH_PREFIXES,
    check_source_has_advisory,
    path_is_definitional,
)
from graph.schema import init_db
from ingest.seed_docs import (
    KERNEL_DOC_ASSESSMENT,
    existing_source_urls,
    list_subtree,
    seed_subtree,
)

TREE = "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/"

PROSE = ("Read-Copy-Update Grace Periods\n"
         "==============================\n\n"
         + "A grace period is the interval during which every pre-existing "
           "reader must complete before a removed object may be reclaimed. " * 25)

#: A real cgit /plain/ directory listing, shortened.
def _listing(names):
    return ("<html><head><title>/Documentation/RCU/</title></head><body><ul>\n"
            + "".join(
                "<li><a href='/pub/scm/linux/kernel/git/torvalds/linux.git/"
                f"plain/Documentation/RCU/{n}'>{n}</a></li>\n" for n in names)
            + "</ul></body></html>")


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "seed.db")
    yield c
    c.close()


def _fetcher(mapping, calls=None):
    def fetch(url):
        if calls is not None:
            calls.append(url)
        return mapping.get(url, "")
    return fetch


# --- the path rule ----------------------------------------------------------


@pytest.mark.parametrize("path,expected", [
    ("Documentation/RCU/listRCU.rst", True),
    ("Documentation/locking/mutex-design.rst", True),
    ("Documentation/mm/highmem.rst", True),
    ("Documentation/core-api/cachetlb.rst", True),
    ("Documentation/scheduler/sched-deadline.rst", True),
    ("Documentation/filesystems/vfs.rst", True),
    # Refused, each for a measured reason recorded in
    # IFC-KK-DOC-DEFINED-PROVENANCE.
    ("Documentation/process/5.Posting.rst", False),       # the project, not the kernel
    ("Documentation/admin-guide/mm/ksm.rst", False),      # configuration reference
    ("Documentation/admin-guide/perf/hisi-pmu.rst", False),  # vendor PMU tables
    ("Documentation/networking/napi.rst", False),         # mixed, pending evidence
    ("Documentation/driver-api/clk.rst", False),
])
def test_only_the_design_trees_are_definitional(path, expected):
    assert path_is_definitional(TREE + path) is expected


def test_the_rule_agrees_across_both_url_forms():
    """The stored url is /tree/ and the fetched one is /plain/. A rule that
    disagreed between them would refuse exactly the documents it just
    fetched."""
    p = "Documentation/RCU/listRCU.rst"
    assert path_is_definitional(TREE + p)
    assert path_is_definitional(TREE.replace("/tree/", "/plain/") + p)


def test_a_refused_subtree_is_never_fetched(conn):
    """The rule exists to stop a bad source entering. Checking it after paying
    for the document would be theatre."""
    calls: list[str] = []
    report = seed_subtree(conn, TREE + "Documentation/process/",
                          fetch_fn=_fetcher({}, calls), rate_limit=0)
    assert calls == [], "a refused subtree was fetched anyway"
    assert report.seeded == 0
    assert report.by_reason() == {"refused-path": 1}


def test_the_prefix_tuple_is_the_one_the_spec_names():
    assert DOC_PATH_PREFIXES == (
        "Documentation/RCU/", "Documentation/core-api/",
        "Documentation/filesystems/", "Documentation/locking/",
        "Documentation/mm/", "Documentation/scheduler/",
    )


# --- listing and seeding ----------------------------------------------------


def test_the_listing_returns_tree_urls_from_a_plain_listing(conn):
    url = TREE + "Documentation/RCU/"
    mapping = {url.replace("/tree/", "/plain/"): _listing(["listRCU.rst", "rcu.rst"])}
    found = list_subtree(url, fetch_fn=_fetcher(mapping))
    assert found == [TREE + "Documentation/RCU/listRCU.rst",
                     TREE + "Documentation/RCU/rcu.rst"]


def test_a_seeded_document_gets_a_source_evidence_and_an_advisory(conn):
    """INV-KK-INGEST-SOURCE-HAS-ADVISORY: 3,531 of 3,574 Sources carry none
    because the ingest path writes none. This is the first path that conforms
    on creation."""
    url = TREE + "Documentation/RCU/"
    doc = url + "listRCU.rst"
    mapping = {url.replace("/tree/", "/plain/"): _listing(["listRCU.rst"]),
               doc.replace("/tree/", "/plain/"): PROSE}
    report = seed_subtree(conn, url, fetch_fn=_fetcher(mapping), rate_limit=0)

    assert report.seeded == 1
    sid = report.outcomes[-1].source_id
    assert check_source_has_advisory(conn, sid) is None, "no Advisory written"

    adv = conn.execute(
        "SELECT a.attrs FROM edges e JOIN nodes a ON a.id = e.target_id "
        "WHERE e.kind = 'assessed-by' AND e.source_id = ?", (sid,)).fetchone()
    import json
    assert json.loads(adv[0])["assessment"] == KERNEL_DOC_ASSESSMENT

    ev = conn.execute(
        "SELECT e.id, json_extract(e.attrs, '$.text') FROM nodes e "
        "JOIN edges x ON x.source_id = e.id AND x.kind = 'sourced-from' "
        "WHERE x.target_id = ?", (sid,)).fetchone()
    assert ev and "grace period" in ev[1].lower(), "the prose was not stored"


def test_the_stored_url_is_the_tree_form_while_the_fetch_used_plain(conn):
    url = TREE + "Documentation/RCU/"
    doc = url + "listRCU.rst"
    calls: list[str] = []
    mapping = {url.replace("/tree/", "/plain/"): _listing(["listRCU.rst"]),
               doc.replace("/tree/", "/plain/"): PROSE}
    seed_subtree(conn, url, fetch_fn=_fetcher(mapping, calls), rate_limit=0)

    stored = conn.execute(
        "SELECT json_extract(attrs, '$.url') FROM nodes WHERE kind = 'Source'"
    ).fetchone()[0]
    assert stored == doc, "the stored url is not the human-readable /tree/ form"
    assert all("/plain/" in c for c in calls), "something fetched /tree/"


def test_an_index_is_refused_for_insufficient_content_and_counted(conn):
    """Each subtree carries an index.rst that is a table of contents.

    ingest_document's own gate raises on 'stub' and 'directory' but NOT on
    'unreachable', so a toctree index would otherwise be seeded as a Source
    with no usable text — the exact state ALG-KK-BACKFILL-SOURCE-PROSE was
    written to repair on 43 existing Sources. The seeder applies
    INV-KK-SOURCE-CONTENT-SUFFICIENT itself, and COUNTS the refusal: a seed
    that silently skipped them would look identical to a subtree with none."""
    url = TREE + "Documentation/RCU/"
    mapping = {
        url.replace("/tree/", "/plain/"): _listing(["index.rst", "listRCU.rst"]),
        (url + "index.rst").replace("/tree/", "/plain/"):
            ".. toctree::\n   listRCU\n   rcu\n",
        (url + "listRCU.rst").replace("/tree/", "/plain/"): PROSE,
    }
    report = seed_subtree(conn, url, fetch_fn=_fetcher(mapping), rate_limit=0)
    assert report.seeded == 1
    assert report.by_reason().get("unreachable") == 1, report.by_reason()
    assert conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE kind = 'Source'").fetchone()[0] == 1


def test_a_dead_document_is_counted_and_writes_nothing(conn):
    url = TREE + "Documentation/RCU/"
    mapping = {url.replace("/tree/", "/plain/"): _listing(["gone.rst"])}
    report = seed_subtree(conn, url, fetch_fn=_fetcher(mapping), rate_limit=0)
    assert report.by_reason() == {"unreachable": 1}
    assert conn.execute(
        "SELECT COUNT(*) FROM nodes").fetchone()[0] == 0


def test_a_rerun_does_not_duplicate_an_existing_source(conn):
    """Four of the 133 targeted files are already seeded, and a partial failure
    must be resumable."""
    url = TREE + "Documentation/RCU/"
    doc = url + "listRCU.rst"
    mapping = {url.replace("/tree/", "/plain/"): _listing(["listRCU.rst"]),
               doc.replace("/tree/", "/plain/"): PROSE}
    first = seed_subtree(conn, url, fetch_fn=_fetcher(mapping), rate_limit=0)
    assert first.seeded == 1
    before = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]

    second = seed_subtree(conn, url, fetch_fn=_fetcher(mapping), rate_limit=0)
    assert second.seeded == 0
    assert second.by_reason() == {"already-seeded": 1}
    assert conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == before
    assert existing_source_urls(conn) == {doc}


def test_a_dry_run_writes_nothing(conn):
    url = TREE + "Documentation/RCU/"
    doc = url + "listRCU.rst"
    mapping = {url.replace("/tree/", "/plain/"): _listing(["listRCU.rst"]),
               doc.replace("/tree/", "/plain/"): PROSE}
    report = seed_subtree(conn, url, fetch_fn=_fetcher(mapping), rate_limit=0,
                          dry_run=True)
    assert report.dry_run and report.by_reason() == {"dry-run": 1}
    assert conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 0


def test_limit_applies_after_the_already_seeded_filter(conn):
    """--limit 1 means one document actually fetched, not one considered —
    matching ALG-KK-EXTRACT-CLI rather than inventing a third convention."""
    url = TREE + "Documentation/RCU/"
    names = [f"doc{i}.rst" for i in range(5)]
    mapping = {url.replace("/tree/", "/plain/"): _listing(names)}
    for n in names:
        mapping[(url + n).replace("/tree/", "/plain/")] = PROSE
    calls: list[str] = []
    report = seed_subtree(conn, url, fetch_fn=_fetcher(mapping, calls),
                          rate_limit=0, limit=1)
    assert report.seeded == 1
    # one listing fetch plus exactly one document fetch
    assert len(calls) == 2
