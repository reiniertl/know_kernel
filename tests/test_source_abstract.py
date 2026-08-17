"""Tests for Source abstract storage and the manual editor.

IFC-KK-SOURCE-ABSTRACT: the three Source fields and the provenance enum.
ALG-KK-WEB-ABSTRACT-EDIT: PUT /api/abstract/{source_id}.
INV-KK-WEB-MUTATION-ALLOWLISTED: every mutating route sits on the allowlist.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from graph.engine import add_node, get_node
from graph.schema import init_db
from ingest.source_abstract import VALID_ABSTRACT_SOURCES, set_abstract
from web.app import create_app
from web.routes import WEB_MUTATION_ALLOWLIST


ABSTRACT = "We present a lock-free ring buffer with bounded producer latency."


def _seed(db_path):
    conn = init_db(db_path)
    add_node(conn, "src-plain", "Source", {
        "url": "https://example.com/plain.pdf",
        "source_type": "paper",
        "license": "MIT",
        "title": "A Paper Without An Abstract",
    })
    add_node(conn, "src-with", "Source", {
        "url": "https://example.com/with.pdf",
        "source_type": "paper",
        "license": "MIT",
        "title": "A Paper With An Abstract",
        "abstract": ABSTRACT,
        "abstract_source": "openalex",
        "abstract_fetched_at": "2026-08-17",
    })
    add_node(conn, "sub-1", "Subsystem", {"name": "Scheduler"})
    conn.commit()
    return conn


@pytest.fixture
def conn(tmp_path):
    c = _seed(tmp_path / "abstract_test.db")
    yield c
    c.close()


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "abstract_web_test.db"
    _seed(db_path).close()
    app = create_app(str(db_path))
    with TestClient(app) as c:
        yield c


# --- storage helper (IFC-KK-SOURCE-ABSTRACT) ---------------------------------


def test_set_abstract_stores_text_and_provenance(conn):
    result = set_abstract(conn, "src-plain", ABSTRACT, "arxiv")
    assert result.abstract == ABSTRACT
    assert result.abstract_source == "arxiv"
    assert result.abstract_fetched_at

    attrs = get_node(conn, "src-plain")["attrs"]
    assert attrs["abstract"] == ABSTRACT
    assert attrs["abstract_source"] == "arxiv"
    assert attrs["abstract_fetched_at"] == result.abstract_fetched_at


def test_set_abstract_strips_surrounding_whitespace(conn):
    result = set_abstract(conn, "src-plain", f"  {ABSTRACT}\n\n", "pdf")
    assert result.abstract == ABSTRACT


def test_set_abstract_rejects_whitespace_only(conn):
    with pytest.raises(ValueError, match="non-empty"):
        set_abstract(conn, "src-plain", "   \n\t ")


def test_set_abstract_rejects_unknown_provenance(conn):
    with pytest.raises(ValueError, match="Invalid abstract source"):
        set_abstract(conn, "src-plain", ABSTRACT, "wikipedia")


def test_set_abstract_rejects_non_source_node(conn):
    with pytest.raises(ValueError, match="does not exist"):
        set_abstract(conn, "sub-1", ABSTRACT)


def test_set_abstract_rejects_missing_node(conn):
    with pytest.raises(ValueError, match="does not exist"):
        set_abstract(conn, "no-such-node", ABSTRACT)


def test_set_abstract_leaves_other_attrs_intact(conn):
    set_abstract(conn, "src-plain", ABSTRACT)
    attrs = get_node(conn, "src-plain")["attrs"]
    assert attrs["url"] == "https://example.com/plain.pdf"
    assert attrs["source_type"] == "paper"
    assert attrs["license"] == "MIT"


def test_provenance_enum_is_the_documented_four():
    assert set(VALID_ABSTRACT_SOURCES) == {"arxiv", "openalex", "pdf", "manual"}


# --- manual edit round trip (ALG-KK-WEB-ABSTRACT-EDIT) -----------------------


def test_put_abstract_round_trip(client):
    resp = client.put("/api/abstract/src-plain", json={"abstract": ABSTRACT})
    assert resp.status_code == 200
    assert resp.json()["abstract"] == ABSTRACT

    page = client.get("/paper/src-plain")
    assert page.status_code == 200
    assert ABSTRACT in page.text


def test_put_abstract_forces_manual_provenance(client):
    """The caller cannot claim arXiv for text a human typed."""
    resp = client.put(
        "/api/abstract/src-plain",
        json={"abstract": ABSTRACT, "abstract_source": "arxiv"},
    )
    assert resp.status_code == 200
    assert resp.json()["abstract_source"] == "manual"

    page = client.get("/paper/src-plain")
    assert "Entered by hand." in page.text
    assert "Fetched verbatim from arXiv." not in page.text


def test_put_abstract_overwrites_and_relabels_a_fetched_abstract(client):
    resp = client.put("/api/abstract/src-with", json={"abstract": "Corrected text."})
    assert resp.status_code == 200
    assert resp.json()["abstract_source"] == "manual"

    page = client.get("/paper/src-with")
    assert "Corrected text." in page.text
    assert "inverted word index" not in page.text


def test_put_abstract_rejects_whitespace_only(client):
    resp = client.put("/api/abstract/src-plain", json={"abstract": "   \n "})
    assert resp.status_code == 422

    page = client.get("/paper/src-plain")
    assert "Entered by hand." not in page.text


def test_put_abstract_rejects_empty_string(client):
    assert client.put("/api/abstract/src-plain", json={"abstract": ""}).status_code == 422


def test_put_abstract_rejects_missing_field(client):
    resp = client.put("/api/abstract/src-plain", json={})
    assert resp.status_code == 422
    assert "abstract" in resp.json()["error"]


def test_put_abstract_404s_on_unknown_id(client):
    assert client.put("/api/abstract/no-such-node", json={"abstract": ABSTRACT}).status_code == 404


def test_put_abstract_404s_on_non_source_node(client):
    """A node of another kind is refused, not silently given an abstract."""
    resp = client.put("/api/abstract/sub-1", json={"abstract": ABSTRACT})
    assert resp.status_code == 404


# --- template rendering ------------------------------------------------------


def test_provenance_note_renders_for_source_with_abstract(client):
    page = client.get("/paper/src-with")
    assert page.status_code == 200
    assert ABSTRACT in page.text
    assert "inverted word index" in page.text
    assert "2026-08-17" in page.text


def test_openalex_provenance_is_labelled_differently_from_verbatim(client):
    """OpenAlex text is reconstructed, not verbatim — the note must say so."""
    page = client.get("/paper/src-with").text
    assert "Fetched verbatim from arXiv." not in page
    assert "Extracted from the paper PDF." not in page
    assert "may differ" in page


def test_nothing_renders_for_source_without_abstract(client):
    page = client.get("/paper/src-plain")
    assert page.status_code == 200
    assert "abstract-provenance" not in page.text
    assert "Entered by hand." not in page.text
    assert "Provenance unrecorded." not in page.text
    assert "inverted word index" not in page.text


# --- INV-KK-WEB-MUTATION-ALLOWLISTED ----------------------------------------


def test_every_mutating_route_is_on_the_allowlist(client):
    """The allowlist is the structural enforcement, so sweep the real router."""
    offenders = []
    for route in client.app.routes:
        methods = getattr(route, "methods", set()) or set()
        if not methods & {"POST", "PUT", "DELETE"}:
            continue
        path = getattr(route, "path", "")
        if not path.startswith(WEB_MUTATION_ALLOWLIST):
            offenders.append((sorted(methods & {"POST", "PUT", "DELETE"}), path))
    assert offenders == []


def test_abstract_path_is_on_the_allowlist():
    assert "/api/abstract/" in WEB_MUTATION_ALLOWLIST
