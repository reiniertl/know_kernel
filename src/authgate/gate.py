"""The authentication middleware — ALG-KK-AUTH-GATE.

One HTTP middleware on the parent gate app, registered before the Mount of the
know_kernel app at "/". A middleware rather than per-route dependencies because
a dependency has to be remembered for every new route, while a middleware gates
by default — and because the auto-generated /docs, /redoc and /openapi.json
have no route function to hang a dependency on.

Identity crosses the Mount through ``request.state``: Starlette stores it in
``scope["state"]``, the Mount passes the same scope to the child app, and the
child reads ``request.state.user`` back out. No token ever travels in a URL.
"""

from __future__ import annotations

from typing import Callable
from urllib.parse import quote

from fastapi import FastAPI
from fastapi.responses import RedirectResponse, Response

from authgate.schema import (
    REMEMBER_COOKIE,
    REMEMBER_TTL,
    SESSION_COOKIE,
    SESSION_TTL,
)
from authgate.store import (
    UserRecord,
    consume_remember,
    create_session,
    resolve_session,
    slide_session,
)

# INV-KK-AUTH-GATE-COVERS-MOUNT: this tuple IS the structural enforcement.
# Every path not matching one of these prefixes must carry a resolved identity
# before it reaches the mounted app. Admitting a new unauthenticated path means
# adding its prefix here — the invariant itself does not move.
AUTH_EXEMPT_PATHS = (
    "/login",
    "/healthz",
    "/static/",
)


def is_exempt(path: str) -> bool:
    """True if *path* may be served without an identity."""
    for prefix in AUTH_EXEMPT_PATHS:
        if path == prefix or path.startswith(
            prefix if prefix.endswith("/") else prefix + "/"
        ):
            return True
    return False


def safe_next(raw: str | None) -> str:
    """INV-KK-AUTH-NEXT-IS-LOCAL — reduce *raw* to a same-origin path.

    Anything that is not a local path — an absolute URL, a scheme-relative
    ``//host``, a backslash variant of it, or an empty value — collapses to
    "/", so the login page cannot be turned into an open redirect.
    """
    if not raw:
        return "/"
    candidate = raw.strip()
    if not candidate.startswith("/"):
        return "/"
    if candidate.startswith("//") or candidate.startswith("/\\"):
        return "/"
    return candidate


def identity_of(user: UserRecord) -> dict[str, str]:
    """Project a user row onto IFC-KK-IDENTITY.

    ``reviewer`` is a separate key from ``username`` even though the two are
    equal today: review attribution reads ``reviewer``, so a display name can
    be introduced later without touching a single call site.
    """
    return {
        "username": user.username,
        "role": user.role,
        "reviewer": user.username,
    }


def set_session_cookie(response: Response, token: str, https_only: bool) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=https_only,
        path="/",
    )


def set_remember_cookie(response: Response, token: str, https_only: bool) -> None:
    response.set_cookie(
        REMEMBER_COOKIE,
        token,
        max_age=int(REMEMBER_TTL.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=https_only,
        path="/",
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(REMEMBER_COOKIE, path="/")


def install_gate(
    app: FastAPI,
    auth_conn_getter: Callable[..., object],
    https_only: bool = False,
) -> None:
    """Register ALG-KK-AUTH-GATE on *app*.

    *auth_conn_getter* is called with the request and returns the auth.db
    connection, so the middleware never captures a connection that the
    lifespan may later replace.
    """

    @app.middleware("http")
    async def gate(request, call_next):  # noqa: ANN001 — Starlette signature
        path = request.url.path
        if is_exempt(path):
            return await call_next(request)

        conn = auth_conn_getter(request)
        token = request.cookies.get(SESSION_COOKIE, "")
        user = resolve_session(conn, token)
        issued: tuple[str, str] | None = None

        if user is not None:
            slide_session(conn, token)
            conn.commit()
        else:
            # ALG-KK-AUTH-SESSION-RESUME — an expired session with a live
            # remember token is refreshed inline, so the operator sees nothing.
            remembered = consume_remember(
                conn, request.cookies.get(REMEMBER_COOKIE, "")
            )
            if remembered is not None:
                user, new_remember = remembered
                new_session, _ = create_session(conn, user.username)
                conn.commit()
                issued = (new_session, new_remember)
            else:
                conn.commit()  # persist the expired-row cleanup

        if user is None:
            # htmx swaps a 302's HTML body into the target element, so the
            # search dropdown would fill with the login page. HX-Redirect
            # makes htmx navigate instead.
            if request.headers.get("HX-Request"):
                return Response(
                    status_code=401, headers={"HX-Redirect": "/login"}
                )
            destination = path
            if request.url.query:
                destination = f"{path}?{request.url.query}"
            return RedirectResponse(
                f"/login?next={quote(safe_next(destination), safe='')}",
                status_code=302,
            )

        request.state.user = identity_of(user)
        response = await call_next(request)
        if issued is not None:
            set_session_cookie(response, issued[0], https_only)
            set_remember_cookie(response, issued[1], https_only)
        return response
