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
    # INVERTED 2026-09-29, EXPLICITLY AND NOT SILENTLY. These four asserted
    # False because DOC_PATH_PREFIXES held six directories. The operator
    # admitted eight more that day on the 76%-versus-1.2% yield measurement
    # and the 35 concepts whose only evidence is a discredited title-regex;
    # see INV-KK-SEED-PATH-DEFINITIONAL, which records the decision and the
    # admin-guide objection that was weighed and overridden rather than
    # answered. What defends these documents is now
    # INV-KK-HARVEST-DOCUMENT-DEFINES, per document, not the path alone.
    ("Documentation/admin-guide/mm/ksm.rst", True),
    ("Documentation/admin-guide/perf/hisi-pmu.rst", True),
    ("Documentation/networking/napi.rst", True),
    ("Documentation/driver-api/clk.rst", True),
    # STILL REFUSED, and this one is the whole reason the rule exists.
    ("Documentation/process/5.Posting.rst", False),       # the project, not the kernel
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
    """WIDENED 2026-09-29 from six directories to fourteen. The tuple is
    pinned rather than merely spot-checked so that adding a directory is a
    decision someone has to write down here as well as in the spec — which is
    what INV-KK-SEED-PATH-DEFINITIONAL means by "every addition is a decision
    with evidence, not a configuration change"."""
    assert DOC_PATH_PREFIXES == (
        "Documentation/RCU/",
        "Documentation/admin-guide/",
        "Documentation/block/",
        "Documentation/core-api/",
        "Documentation/driver-api/",
        "Documentation/filesystems/",
        "Documentation/locking/",
        "Documentation/mm/",
        "Documentation/networking/",
        "Documentation/scheduler/",
        "Documentation/security/",
        "Documentation/trace/",
        "Documentation/userspace-api/",
        "Documentation/virt/",
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


# ---------------------------------------------------------------------------
# list_subtree RECURSION, fixed 2026-09-29.
#
# The fixtures below reproduce the SHAPE of a real cgit /plain/ listing,
# measured against Documentation/filesystems/ on 2026-09-29: a subdirectory
# renders with NO trailing slash on its visible name and a trailing slash in
# its HREF, and it sits beside files that also have no extension-bearing
# slash. Nothing here touches the network.
# ---------------------------------------------------------------------------

def _mixed_listing(path, entries):
    """entries: (name, is_dir). Mirrors cgit — the href carries the slash."""
    base = f"/pub/scm/linux/kernel/git/torvalds/linux.git/plain/{path}"
    rows = [f"<li><a href='{base.rsplit('/', 2)[0]}/'>../</a></li>"]
    for name, is_dir in entries:
        href = f"{base}/{name}/" if is_dir else f"{base}/{name}"
        rows.append(f"<li><a href='{href}'>{name}</a></li>")
    return "<html><body><ul>\n" + "\n".join(rows) + "\n</ul></body></html>"


def _tree_fixture():
    """filesystems/ with xfs/ beneath it — the exact case the bug missed."""
    p = "Documentation/filesystems"
    return {
        TREE.replace("/tree/", "/plain/") + p: _mixed_listing(p, [
            ("9p.rst", False),
            ("path-lookup.txt", False),   # a FILE with no trailing slash
            ("xfs", True),                # a DIRECTORY, also no trailing slash
        ]),
        TREE.replace("/tree/", "/plain/") + p + "/xfs": _mixed_listing(
            p + "/xfs", [("xfs-online-fsck-design.rst", False),
                         ("xfs-self-describing-metadata.rst", False)]),
    }


def test_the_listing_reaches_documents_in_a_subdirectory():
    """THE BUG: Documentation/filesystems/ keeps XFS's documentation in xfs/,
    the 2026-09-29 run seeded 78 flat files and reported success, and XFS
    Filesystem ended it exactly as evidence-free as it began."""
    found = list_subtree(TREE + "Documentation/filesystems",
                         fetch_fn=_fetcher(_tree_fixture()))
    assert found == [
        TREE + "Documentation/filesystems/9p.rst",
        TREE + "Documentation/filesystems/xfs/xfs-online-fsck-design.rst",
        TREE + "Documentation/filesystems/xfs/xfs-self-describing-metadata.rst",
    ]


def test_a_directory_is_told_from_a_file_by_its_href_and_not_its_name():
    """MEASURED AGAINST THE LIVE LISTING: ext4, xfs and nfs render with no
    trailing slash on the visible name, exactly like path-lookup.txt beside
    them. Only the href carries one. A rule reading the name would get
    path-lookup.txt right by accident and break on the first extensionless
    file the kernel adds."""
    found = list_subtree(TREE + "Documentation/filesystems",
                         fetch_fn=_fetcher(_tree_fixture()))
    assert not any(u.endswith("path-lookup.txt") for u in found), \
        "a .txt file was walked as a directory"
    assert any("/xfs/" in u for u in found), "a directory was read as a file"


def test_the_walk_is_bounded_by_depth():
    p = "Documentation/mm"
    plain = TREE.replace("/tree/", "/plain/")
    mapping = {
        plain + p: _mixed_listing(p, [("a.rst", False), ("one", True)]),
        plain + p + "/one": _mixed_listing(p + "/one",
                                           [("b.rst", False), ("two", True)]),
        plain + p + "/one/two": _mixed_listing(p + "/one/two",
                                               [("c.rst", False)]),
    }
    assert len(list_subtree(TREE + p, fetch_fn=_fetcher(mapping),
                            max_depth=0)) == 1
    assert len(list_subtree(TREE + p, fetch_fn=_fetcher(mapping),
                            max_depth=1)) == 2
    assert len(list_subtree(TREE + p, fetch_fn=_fetcher(mapping),
                            max_depth=2)) == 3


def test_an_unlistable_subdirectory_costs_only_itself():
    """One unreachable subdirectory must not lose the documents beside it."""
    p = "Documentation/mm"
    plain = TREE.replace("/tree/", "/plain/")

    def fetch(url):
        if url.endswith("/broken"):
            raise OSError("listing unavailable")
        return {plain + p: _mixed_listing(
            p, [("good.rst", False), ("broken", True)])}.get(url, "")

    found = list_subtree(TREE + p, fetch_fn=fetch)
    assert found == [TREE + p + "/good.rst"]


def test_a_subtree_whose_own_listing_fails_raises():
    """THE TOP LEVEL MUST BE LOUD.

    REWRITTEN 2026-09-29 AND THE REASON IS THE POINT. The first version passed
    a fetcher that RAISED OSError, and it was green while the real code lost 37
    documents — because validate_sources._default_fetch CATCHES every httpx
    error and returns an EMPTY STRING. The guard under test could never fire in
    production. A test whose fixture behaves better than the code it stands for
    proves only that the fixture behaves well, which is the same mistake the
    artifact_class filter made.

    So this now uses a fetcher that behaves EXACTLY as _default_fetch does.
    """
    def fetch_like_default_fetch(url):
        return ""          # what _default_fetch returns on 503, 404, timeout

    with pytest.raises(RuntimeError):
        list_subtree(TREE + "Documentation/mm", fetch_fn=fetch_like_default_fetch)


def test_an_unreadable_subdirectory_is_reported_and_not_silent():
    """INV-KK-SEED-LISTING-ACCOUNTED. git.kernel.org 503s under sustained
    listing; the subtree must still say what it could not read."""
    p = "Documentation/driver-api"
    plain = TREE.replace("/tree/", "/plain/")
    listing = {plain + p: _mixed_listing(p, [("vfio.rst", False), ("usb", True)])}

    def fetch(url):
        return listing.get(url, "")    # usb/ comes back empty, like a 503

    failures: list[str] = []
    found = list_subtree(TREE + p, fetch_fn=fetch, failures=failures)
    assert found == [TREE + p + "/vfio.rst"]
    assert failures == [TREE + p + "/usb"], "an unreadable directory vanished"


def test_the_seed_report_counts_a_failed_listing(conn):
    """A run that silently returns fewer documents is indistinguishable from a
    subtree that had fewer. The 37 lost on 2026-09-29 were driver-api/usb/,
    driver-api/driver-model/ and driver-api/thermal/ — exactly the documents a
    later prompt planned to discharge link debt with."""
    p = "Documentation/mm"
    plain = TREE.replace("/tree/", "/plain/")
    listing = {
        plain + p + "/": _mixed_listing(p, [("highmem.rst", False), ("slub", True)]),
        plain + p + "/highmem.rst": PROSE,
    }
    # The trailing slash matters: path_is_definitional matches the prefix
    # "Documentation/mm/", so the bare directory name is refused before any fetch.
    report = seed_subtree(conn, TREE + p + "/",
                          fetch_fn=_fetcher(listing), rate_limit=0)
    assert report.by_reason().get("listing-failed") == 1
    assert report.seeded == 1


def test_a_directory_that_really_holds_no_rst_is_not_a_failure():
    """The discriminator is the PARENT ANCHOR, not the .rst count. A real cgit
    listing always carries '../'; only a page with no anchors at all is
    unreadable."""
    p = "Documentation/mm"
    plain = TREE.replace("/tree/", "/plain/")
    listing = {
        plain + p: _mixed_listing(p, [("a.rst", False), ("images", True)]),
        plain + p + "/images": _mixed_listing(p + "/images", [("diagram.svg", False)]),
    }
    failures: list[str] = []
    found = list_subtree(TREE + p, fetch_fn=_fetcher(listing), failures=failures)
    assert found == [TREE + p + "/a.rst"]
    assert failures == [], "an empty-of-rst directory was called unreadable"


def test_the_newly_admitted_directories_are_definitional():
    """The eight added 2026-09-29. Recorded as a test so a later edit to
    DOC_PATH_PREFIXES that drops one is visible rather than silent."""
    for d in ("trace", "block", "security", "networking",
              "userspace-api", "driver-api", "virt", "admin-guide"):
        assert path_is_definitional(TREE + f"Documentation/{d}/x.rst"), d


def test_process_is_still_refused_after_the_widening():
    """The widening must not have admitted the directory the whole rule was
    written against."""
    assert not path_is_definitional(
        TREE + "Documentation/process/submitting-patches.rst")
    assert not path_is_definitional(TREE + "Documentation/x.rst")


# --- titles (ALG-KK-SEED-DOC-SUBTREE) ---------------------------------------
#
# ALL 1,510 kernel-doc SOURCES HAD NO TITLE, measured 2026-09-30, because the
# seeder never captured one. The concept page renders an untitled Source as its
# node id, so a curator reading Block Groups saw "src-462ab441d987" where
# blockgroup.rst belonged.

def test_rst_title_reads_an_overlined_heading():
    from ingest.seed_docs import rst_title
    assert rst_title(
        "=====================\n"
        "Transparent Hugepage\n"
        "=====================\n\nBody.") == "Transparent Hugepage"


def test_rst_title_reads_an_underlined_heading():
    from ingest.seed_docs import rst_title
    assert rst_title("NAPI\n====\n\nBody.") == "NAPI"


def test_rst_title_skips_the_licence_line_and_directives():
    """Every kernel document opens with an SPDX comment, and a title taken
    from line one would be "SPDX-License-Identifier: GPL-2.0" on all 1,510."""
    from ingest.seed_docs import rst_title
    assert rst_title(
        ".. SPDX-License-Identifier: GPL-2.0\n\n"
        "Block Groups\n============\n\nBody.") == "Block Groups"


def test_rst_title_falls_back_when_the_adornments_were_stripped():
    """41 OF 1,510 HAD NO ADORNMENTS LEFT. transhuge.rst, cgroup-v2.rst,
    vfs.rst and napi.rst all reached the graph with their rules removed, so
    the adornment rule alone recovers 1,469 and reports nothing for the rest —
    a null result that looks exactly like a document with no title. The
    fallback takes it to 1,484 of the 1,485 that carry text at all."""
    from ingest.seed_docs import rst_title
    assert rst_title(
        ".. SPDX-License-Identifier: GPL-2.0\n\n"
        "Overview of the Linux Virtual File System\n\n"
        "Original author: ...") == "Overview of the Linux Virtual File System"


def test_rst_title_is_empty_when_there_is_nothing_to_read():
    """25 Evidence nodes carry no text. An empty string is the honest answer
    and the caller writes no title rather than writing a wrong one."""
    from ingest.seed_docs import rst_title
    assert rst_title("") == ""
    assert rst_title("\n\n   \n") == ""


def test_a_bullet_list_is_not_an_adornment():
    """Three or more characters, not one: "-" under a line is a bullet."""
    from ingest.seed_docs import rst_title
    assert rst_title("Real Title\n==========\n\n- a\n- b\n") == "Real Title"
