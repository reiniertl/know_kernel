"""Tests for the authentication gate — MOD-KK-AUTH.

INV-KK-AUTH-GATE-COVERS-MOUNT: nothing behind the mount is reachable anonymously.
INV-KK-AUTH-NEXT-IS-LOCAL: post-login redirects stay same-origin.
ALG-KK-AUTH-LOGIN / -LOGOUT / -SESSION-RESUME / -GATE.

Sessions are expired by writing expires_at directly, never by sleeping.
"""

from __future__ import annotations

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from authgate.app import create_gate_app
from authgate.cli import create_user_with_roster
from authgate.gate import is_exempt, safe_next
from authgate.schema import REMEMBER_COOKIE, SESSION_COOKIE, init_auth_db
from graph.engine import add_node
from graph.schema import init_db

PAST = "2000-01-01T00:00:00+00:00"


@pytest.fixture
def gated(tmp_path):
    """An anonymous TestClient over the gate app, with two seeded users."""
    master_path = tmp_path / "master.db"
    auth_path = tmp_path / "auth.db"

    master_conn = init_db(master_path)
    add_node(
        master_conn,
        "src-1",
        "Source",
        {"url": "https://example.com/p.pdf", "source_type": "paper", "license": "MIT"},
    )
    master_conn.commit()

    auth_conn = init_auth_db(auth_path)
    create_user_with_roster(auth_conn, master_conn, "boss", "boss-pw", role="admin")
    create_user_with_roster(auth_conn, master_conn, "reinier", "pw", role="user")
    auth_conn.close()
    master_conn.close()

    app = create_gate_app(str(master_path), str(auth_path))
    with TestClient(app, follow_redirects=False) as client:
        client.auth_path = str(auth_path)
        yield client


def login(client, username="reinier", password="pw", remember=False, next_="/"):
    data = {"username": username, "password": password, "next": next_}
    if remember:
        data["remember"] = "1"
    return client.post("/login", data=data)


def _expire_sessions(auth_path: str) -> None:
    conn = init_auth_db(auth_path)
    try:
        conn.execute("UPDATE sessions SET expires_at = ?", (PAST,))
        conn.commit()
    finally:
        conn.close()


# --- INV-KK-AUTH-NEXT-IS-LOCAL (pure) ---------------------------------------


@pytest.mark.parametrize(
    "raw",
    ["https://evil.example", "//evil.example", "/\\evil.example", "", None, "evil"],
)
def test_safe_next_rejects_anything_that_is_not_a_local_path(raw):
    assert safe_next(raw) == "/"


@pytest.mark.parametrize("raw", ["/", "/paper/src-1", "/concepts?kind=Concept"])
def test_safe_next_keeps_local_paths(raw):
    assert safe_next(raw) == raw


# --- AUTH_EXEMPT_PATHS ------------------------------------------------------


def test_exempt_paths_are_exactly_login_healthz_and_static():
    assert is_exempt("/login")
    assert is_exempt("/healthz")
    assert is_exempt("/static/app.css")
    assert not is_exempt("/")
    assert not is_exempt("/paper/src-1")
    assert not is_exempt("/api/search")
    assert not is_exempt("/loginish")


# --- the wall ---------------------------------------------------------------


def test_anonymous_root_redirects_to_login_with_next(gated):
    response = gated.get("/")
    assert response.status_code == 302
    assert response.headers["location"] == "/login?next=%2F"


def test_anonymous_deep_link_preserves_the_path_as_next(gated):
    response = gated.get("/paper/src-1")
    assert response.status_code == 302
    assert response.headers["location"] == "/login?next=%2Fpaper%2Fsrc-1"


def test_login_page_is_reachable_anonymously(gated):
    response = gated.get("/login")
    assert response.status_code == 200
    assert "Sign in" in response.text


def test_healthz_is_reachable_anonymously(gated):
    assert gated.get("/healthz").status_code == 200


def test_docs_and_openapi_are_gated(gated):
    assert gated.get("/docs").status_code == 302
    assert gated.get("/openapi.json").status_code == 302


def test_htmx_request_gets_401_with_hx_redirect(gated):
    response = gated.get("/api/search?q=lock", headers={"HX-Request": "true"})
    assert response.status_code == 401
    assert response.headers["HX-Redirect"] == "/login"


# --- ALG-KK-AUTH-LOGIN ------------------------------------------------------


def test_valid_login_redirects_and_sets_a_session_cookie(gated):
    response = login(gated)
    assert response.status_code == 302
    assert response.headers["location"] == "/"
    assert gated.cookies.get(SESSION_COOKIE)


def test_login_redirects_to_the_requested_next(gated):
    response = login(gated, next_="/paper/src-1")
    assert response.headers["location"] == "/paper/src-1"


def test_login_discards_an_offsite_next(gated):
    assert login(gated, next_="https://evil.example").headers["location"] == "/"
    assert login(gated, next_="//evil.example").headers["location"] == "/"


def test_invalid_password_is_401_with_one_generic_message_and_no_cookie(gated):
    response = login(gated, password="wrong")
    assert response.status_code == 401
    assert "Incorrect username or password." in response.text
    assert gated.cookies.get(SESSION_COOKIE) is None


def test_unknown_user_is_indistinguishable_from_a_wrong_password(gated):
    unknown = login(gated, username="nobody", password="pw")
    wrong = login(gated, password="wrong")
    assert unknown.status_code == wrong.status_code == 401
    assert "Incorrect username or password." in unknown.text


def test_login_without_remember_sets_no_remember_cookie(gated):
    login(gated)
    assert gated.cookies.get(REMEMBER_COOKIE) is None


def test_login_with_remember_sets_a_remember_cookie(gated):
    login(gated, remember=True)
    assert gated.cookies.get(REMEMBER_COOKIE)


def test_authenticated_request_reaches_the_mounted_app(gated):
    login(gated)
    response = gated.get("/")
    assert response.status_code == 200
    assert "Dashboard" in response.text


def test_admin_can_log_in_too(gated):
    assert login(gated, username="boss", password="boss-pw").status_code == 302
    assert gated.get("/").status_code == 200


# --- ALG-KK-AUTH-LOGOUT -----------------------------------------------------


def test_logout_clears_the_cookie_and_re_gates(gated):
    login(gated)
    response = gated.post("/logout")

    assert response.status_code == 302
    assert response.headers["location"] == "/login"
    assert not gated.cookies.get(SESSION_COOKIE)
    assert gated.get("/").status_code == 302


def test_logout_is_idempotent_for_an_anonymous_caller(gated):
    assert gated.post("/logout").status_code == 302


# --- ALG-KK-AUTH-SESSION-RESUME ---------------------------------------------


def test_expired_session_with_a_remember_cookie_resumes_silently(gated):
    login(gated, remember=True)
    first_session = gated.cookies.get(SESSION_COOKIE)
    _expire_sessions(gated.auth_path)

    response = gated.get("/")

    assert response.status_code == 200
    assert gated.cookies.get(SESSION_COOKIE) not in (None, first_session)


def test_expired_session_without_a_remember_cookie_bounces_to_login(gated):
    login(gated)
    _expire_sessions(gated.auth_path)

    assert gated.get("/").status_code == 302


def test_resume_rotates_the_remember_cookie(gated):
    login(gated, remember=True)
    first_remember = gated.cookies.get(REMEMBER_COOKIE)
    _expire_sessions(gated.auth_path)

    gated.get("/")

    assert gated.cookies.get(REMEMBER_COOKIE) not in (None, first_remember)


# --- identity injection across the Mount ------------------------------------


def test_identity_crosses_the_mount(gated):
    """IFC-KK-IDENTITY reaches the child app through the ASGI scope state."""
    seen = {}

    inner = [r for r in gated.app.routes if hasattr(r, "app")][-1].app

    @inner.get("/__identity_probe")
    def probe(request: Request):  # pragma: no cover - via the client
        seen.update(request.state.user)
        return {"ok": True}

    login(gated)
    response = gated.get("/__identity_probe")

    assert response.status_code == 200
    assert seen == {"username": "reinier", "role": "user", "reviewer": "reinier"}
