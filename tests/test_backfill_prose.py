"""ALG-KK-BACKFILL-SOURCE-PROSE: the path that stores what validate only read.

INV-KK-BACKFILL-PROSE-NOT-MARKUP is the property this whole file exists to
defend. The corpus the backfill fills is what the concept harvest will read and
what the paper extractor's vocabulary is eventually built from, so markup
stored once propagates into every concept derived from it and every paper
matched against those concepts. A poisoned document is worse than an empty one
because an empty one is visibly empty.

EVERY FETCH HERE IS INJECTED. A test that reached git.kernel.org would be a
defect in the test, not a stronger test.
"""

from __future__ import annotations

import pytest

from graph.engine import add_edge, add_node, get_node
from graph.schema import init_db
from ingest.pipeline import MAX_EVIDENCE_TEXT_CHARS
from ingest.validate_sources import (
    SUFFICIENT_CLASSIFICATIONS,
    backfill_source_prose,
    classify_content,
    looks_like_markup,
    plain_url,
    source_content_sufficient,
)

TREE = ("https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/"
        "linux.git/tree/Documentation/mm/{name}")

# A real cgit /plain/ directory listing, shortened. It matches none of the
# three /tree/ markers, which is why 16 Sources were misclassified before
# 2026-09-25.
PLAIN_DIR = (
    "<html><head><title>/Documentation/crypto/</title></head>\n<body>\n"
    "<h2>/Documentation/crypto/</h2>\n<ul>\n"
    + "".join(
        "<li><a href='/pub/scm/linux/kernel/git/torvalds/linux.git/plain/"
        f"Documentation/crypto/api-{i}.rst'>api-{i}.rst</a></li>\n"
        for i in range(40))
    + "</ul></body></html>"
)

# The cgit /tree/ page for a FILE: a whole HTML document wrapping the content.
TREE_PAGE = (
    "<!DOCTYPE html>\n<html lang='en'>\n<head>\n<title>slab.rst</title>\n"
    "</head>\n<body>\n" + "<p>navigation menu item</p>\n" * 200 + "</body></html>"
)

PROSE = (
    "Slab Allocation\n"
    "===============\n\n"
    + "The slab allocator groups objects of the same size into caches so that "
      "allocation avoids the page allocator on the fast path. " * 20
)

STUB = (".. SPDX-License-Identifier: GPL-2.0\n\nSlab Allocation\n===============\n\n"
        ".. kernel-doc:: mm/slab.h\n.. kernel-doc:: mm/slub.c\n   :internal:\n")


def _source(conn, n, url, source_type="kernel-doc", with_evidence=True):
    sid = f"src-{n}"
    add_node(conn, sid, "Source", {
        "url": url, "source_type": source_type, "license": "GPL-2.0",
        "title": f"Doc {n}"})
    if with_evidence:
        add_node(conn, f"ev-{n}", "Evidence", {
            "artifact_class": "licensed-evidence",
            "contamination_level": "strong-copyleft", "text": ""})
        add_edge(conn, "sourced-from", f"ev-{n}", sid)
    return sid


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "backfill.db")
    yield c
    c.close()


def _fetcher(mapping, calls=None):
    def fetch(url):
        if calls is not None:
            calls.append(url)
        return mapping.get(url, "")
    return fetch


# --- the URL rewrite --------------------------------------------------------


def test_a_tree_url_is_fetched_as_plain():
    """Verified against a real fetch 2026-09-25: /tree/ returns 4,475 bytes of
    text/html, /plain/ returns the raw file."""
    assert plain_url(TREE.format(name="slab.rst")).endswith(
        "/plain/Documentation/mm/slab.rst")


def test_the_stored_url_is_never_modified(conn):
    """/tree/ is the human-readable address and is what the paper page links
    to. The rewrite applies to the fetch alone."""
    url = TREE.format(name="slab.rst")
    _source(conn, "1", url)
    conn.commit()
    backfill_source_prose(conn, fetch_fn=_fetcher({plain_url(url): PROSE}),
                          rate_limit=0)
    assert get_node(conn, "src-1")["attrs"]["url"] == url


def test_a_non_kernel_url_is_left_alone():
    assert plain_url("https://arxiv.org/abs/2501.00001") == (
        "https://arxiv.org/abs/2501.00001")
    assert plain_url("https://example.com/tree/thing") == (
        "https://example.com/tree/thing")


# --- prose is stored --------------------------------------------------------


def test_prose_is_stored_on_the_evidence_node(conn):
    url = TREE.format(name="numa.rst")
    _source(conn, "1", url)
    conn.commit()
    report = backfill_source_prose(
        conn, fetch_fn=_fetcher({plain_url(url): PROSE}), rate_limit=0)
    assert report.stored == 1
    text = get_node(conn, "ev-1")["attrs"]["text"]
    assert "slab allocator groups objects" in text


def test_markup_is_stripped_from_what_is_stored(conn):
    url = TREE.format(name="x.rst")
    body = (".. code-block:: c\n\n    int x = kmalloc(size);\n\n"
            ":ref:`see this <other>`\n\n" + PROSE)
    _source(conn, "1", url)
    conn.commit()
    backfill_source_prose(conn, fetch_fn=_fetcher({plain_url(url): body}),
                          rate_limit=0)
    text = get_node(conn, "ev-1")["attrs"]["text"]
    assert "kmalloc" not in text, "code block survived"
    assert ":ref:" not in text, "RST role survived"
    assert "slab allocator" in text, "prose did not survive"


def test_stored_text_honours_the_same_ceiling_as_the_ingest_path(conn):
    """MAX_EVIDENCE_TEXT_CHARS is imported from ingest.pipeline rather than
    restated, so the two writers of Evidence.text cannot drift apart."""
    url = TREE.format(name="huge.rst")
    _source(conn, "1", url)
    conn.commit()
    backfill_source_prose(
        conn, fetch_fn=_fetcher({plain_url(url): "word " * 40000}), rate_limit=0)
    assert len(get_node(conn, "ev-1")["attrs"]["text"]) == MAX_EVIDENCE_TEXT_CHARS


def test_thin_prose_is_sufficient(conn):
    """Operator decision 2026-09-25. skbuff.rst carries 99 prose words and
    would be discarded by a threshold nobody would defend at 100."""
    assert source_content_sufficient("thin")
    assert SUFFICIENT_CLASSIFICATIONS == ("substantive", "thin")
    url = TREE.format(name="skbuff.rst")
    _source(conn, "1", url)
    conn.commit()
    report = backfill_source_prose(
        conn, fetch_fn=_fetcher({plain_url(url): "word " * 60}), rate_limit=0)
    assert report.stored == 1


# --- markup is NEVER stored (INV-KK-BACKFILL-PROSE-NOT-MARKUP) --------------


def test_an_html_page_is_not_stored_as_prose(conn):
    """THE HAZARD THIS PATH EXISTS TO AVOID. TREE_PAGE carries 800 words of
    navigation text, so _strip_markup leaves plenty behind and the classifier
    calls it substantive. The body shape refuses it anyway."""
    assert classify_content(TREE_PAGE).classification == "substantive", (
        "if this stops being true the test no longer tests what it claims")
    assert looks_like_markup(TREE_PAGE)
    url = TREE.format(name="slab.rst")
    _source(conn, "1", url)
    conn.commit()
    report = backfill_source_prose(
        conn, fetch_fn=_fetcher({plain_url(url): TREE_PAGE}), rate_limit=0)
    assert report.stored == 0
    assert get_node(conn, "ev-1")["attrs"]["text"] == ""
    assert report.outcomes[0].reason == "markup"
    assert get_node(conn, "src-1")["attrs"]["content_status"] == "directory"


def test_a_plain_directory_listing_is_recognised_as_a_directory(conn):
    """It matches none of the three /tree/ markers. Before 2026-09-25 this
    classified as 'unreachable' or 'thin' and could be stored as prose —
    exactly what INV-KK-INGEST-REJECTS-DIRECTORY forbids."""
    assert classify_content(PLAIN_DIR).classification == "directory"
    url = TREE.format(name="crypto")
    _source(conn, "1", url)
    conn.commit()
    report = backfill_source_prose(
        conn, fetch_fn=_fetcher({plain_url(url): PLAIN_DIR}), rate_limit=0)
    assert report.stored == 0
    assert get_node(conn, "ev-1")["attrs"]["text"] == ""


def test_a_stub_is_not_stored(conn):
    """Measured 2026-09-25: exactly one of the 43, Documentation/mm/slab.rst,
    203 bytes and 8 prose words deferring to two kernel-doc refs."""
    assert classify_content(STUB).classification == "stub"
    url = TREE.format(name="slab.rst")
    _source(conn, "1", url)
    conn.commit()
    report = backfill_source_prose(
        conn, fetch_fn=_fetcher({plain_url(url): STUB}), rate_limit=0)
    assert report.stored == 0
    assert get_node(conn, "ev-1")["attrs"]["text"] == ""


def test_a_dead_url_stores_nothing_and_overwrites_nothing(conn):
    """7 of the 43 are 404 in both forms. An existing text must survive a
    failed re-fetch — a fetch that returns nothing is not evidence that the
    document is empty."""
    url = TREE.format(name="tcp.rst")
    _source(conn, "1", url)
    conn.execute("UPDATE nodes SET attrs = json_set(attrs, '$.text', 'earlier prose') "
                 "WHERE id = 'ev-1'")
    conn.commit()
    report = backfill_source_prose(conn, fetch_fn=_fetcher({}), rate_limit=0)
    assert report.stored == 0
    assert get_node(conn, "ev-1")["attrs"]["text"] == "earlier prose"
    assert get_node(conn, "src-1")["attrs"]["content_status"] == "unreachable"


# --- what the Source records (IFC-KK-SOURCE-CONTENT-STATUS) -----------------


def test_every_examined_source_records_its_status(conn):
    """Including the ones that yielded nothing. 'never fetched' and 'fetched
    and found to be a directory' must stay tellable apart, or a re-run repeats
    work that cannot succeed."""
    good = TREE.format(name="numa.rst")
    dirn = TREE.format(name="crypto")
    dead = TREE.format(name="tcp.rst")
    for n, u in (("1", good), ("2", dirn), ("3", dead)):
        _source(conn, n, u)
    conn.commit()
    backfill_source_prose(conn, rate_limit=0, fetch_fn=_fetcher({
        plain_url(good): PROSE, plain_url(dirn): PLAIN_DIR}))
    statuses = {sid: get_node(conn, sid)["attrs"]["content_status"]
                for sid in ("src-1", "src-2", "src-3")}
    assert statuses == {"src-1": "substantive", "src-2": "directory",
                        "src-3": "unreachable"}
    for sid in statuses:
        assert get_node(conn, sid)["attrs"]["content_checked_at"]


def test_content_status_is_optional_and_absent_on_an_unfetched_source(conn):
    """All 3,574 existing Sources carry neither attribute and must keep
    working. Absent means nobody has fetched it."""
    _source(conn, "1", TREE.format(name="x.rst"))
    conn.commit()
    assert "content_status" not in get_node(conn, "src-1")["attrs"]


# --- what it never does -----------------------------------------------------


def test_a_source_with_no_evidence_is_skipped_never_repaired(conn):
    """Minting Evidence belongs to ALG-KK-INGEST-PIPELINE. Two writers on one
    node kind is how the graph gains a second source of truth."""
    url = TREE.format(name="orphan.rst")
    _source(conn, "1", url, with_evidence=False)
    conn.commit()
    before = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    report = backfill_source_prose(
        conn, fetch_fn=_fetcher({plain_url(url): PROSE}), rate_limit=0)
    assert report.stored == 0
    assert report.outcomes[0].reason == "no-evidence"
    assert conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == before


def test_it_creates_no_node_and_no_edge(conn):
    url = TREE.format(name="numa.rst")
    _source(conn, "1", url)
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    e = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    backfill_source_prose(conn, fetch_fn=_fetcher({plain_url(url): PROSE}),
                          rate_limit=0)
    assert conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == n
    assert conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == e


# --- the bound and the dry run ---------------------------------------------


def test_a_dry_run_writes_nothing(conn):
    url = TREE.format(name="numa.rst")
    _source(conn, "1", url)
    conn.commit()
    report = backfill_source_prose(
        conn, fetch_fn=_fetcher({plain_url(url): PROSE}), rate_limit=0,
        dry_run=True)
    assert report.dry_run and report.stored == 1, (
        "a dry run still reports what it WOULD store")
    assert get_node(conn, "ev-1")["attrs"]["text"] == ""
    assert "content_status" not in get_node(conn, "src-1")["attrs"]


def test_limit_bounds_the_number_actually_fetched(conn):
    """Applied AFTER selection, matching ALG-KK-EXTRACT-CLI, so --limit 2
    means two documents fetched and not two considered."""
    calls: list[str] = []
    mapping = {}
    for n in range(6):
        u = TREE.format(name=f"d{n}.rst")
        _source(conn, str(n), u)
        mapping[plain_url(u)] = PROSE
    conn.commit()
    report = backfill_source_prose(
        conn, fetch_fn=_fetcher(mapping, calls), rate_limit=0, limit=2)
    assert report.examined == 2
    assert len(calls) == 2


def test_source_type_selects(conn):
    kd = TREE.format(name="numa.rst")
    _source(conn, "1", kd)
    _source(conn, "2", "https://arxiv.org/abs/1", source_type="preprint")
    conn.commit()
    report = backfill_source_prose(
        conn, fetch_fn=_fetcher({plain_url(kd): PROSE}), rate_limit=0,
        source_types=("kernel-doc",))
    assert [o.source_id for o in report.outcomes] == ["src-1"]


# --- the rate limit still holds (INV-KK-VALIDATE-RATE-LIMITED) --------------


def test_fetches_are_spaced_by_the_rate_limit(conn):
    import time
    for n in range(3):
        u = TREE.format(name=f"d{n}.rst")
        _source(conn, str(n), u)
    conn.commit()
    stamps: list[float] = []

    def fetch(url):
        stamps.append(time.monotonic())
        return PROSE

    backfill_source_prose(conn, fetch_fn=fetch, rate_limit=0.05)
    assert len(stamps) == 3
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    assert all(g >= 0.05 for g in gaps), gaps


def test_the_first_fetch_of_a_run_is_not_delayed(conn):
    import time
    _source(conn, "1", TREE.format(name="a.rst"))
    conn.commit()
    start = time.monotonic()
    backfill_source_prose(conn, fetch_fn=lambda u: PROSE, rate_limit=5.0)
    assert time.monotonic() - start < 1.0
