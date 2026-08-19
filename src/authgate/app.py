"""The gate application — owns /login and /logout, mounts know_kernel at "/".

The parent app is the wall. It registers its own routes first, installs
ALG-KK-AUTH-GATE as the single middleware, and only then mounts the existing,
unmodified know_kernel app at "/". Explicit routes registered before the Mount
win the match, so /login resolves here and everything else falls through to the
knowledge app — already carrying an identity.

The mount is at "/" and nowhere else: the knowledge app's templates link to
absolute paths (/concepts, /api/review/...), which a sub-path mount would break.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from authgate.gate import (
    clear_auth_cookies,
    install_gate,
    safe_next,
    set_remember_cookie,
    set_session_cookie,
)
from authgate.schema import (
    REMEMBER_COOKIE,
    SESSION_COOKIE,
    auth_db_path,
    init_auth_db,
)
from authgate.store import (
    authenticate,
    create_remember,
    create_session,
    delete_remember,
    delete_session,
    purge_expired,
)

_TEMPLATES_DIR = Path(__file__).parent / "templates"

# One message for every failure mode. An unknown username and a wrong password
# are indistinguishable to the caller.
LOGIN_FAILED = "Incorrect username or password."


def create_gate_app(
    db_path: str,
    auth_path: str | None = None,
    https_only: bool = False,
) -> FastAPI:
    """Build the gate app with the know_kernel app mounted behind it."""
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    resolved_auth_path = auth_path or auth_db_path()

    from web.app import create_app

    inner = create_app(db_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # FAIL CLOSED: if auth.db cannot be opened this raises and the server
        # refuses to start. It must never come up serving unauthenticated.
        conn = init_auth_db(resolved_auth_path, check_same_thread=False)
        purge_expired(conn)
        conn.commit()
        app.state.auth_conn = conn
        # A mounted app receives no lifespan events of its own, so the child's
        # startup (which opens master.db onto its app.state.conn) is driven
        # from here. Without this the knowledge app has no connection.
        async with inner.router.lifespan_context(inner):
            yield
        conn.close()

    application = FastAPI(
        title="know_kernel gate",
        version="0.1.0",
        lifespan=lifespan,
    )

    def auth_conn(request: Request):
        return request.app.state.auth_conn

    @application.get("/healthz")
    def healthz() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @application.get("/login", response_class=HTMLResponse)
    def login_form(request: Request, next: str = "/"):
        return templates.TemplateResponse(
            request, "login.html", {"next": safe_next(next), "error": None}
        )

    @application.post("/login")
    def login(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
        remember: str | None = Form(None),
        next: str = Form("/"),
    ):
        """ALG-KK-AUTH-LOGIN."""
        conn = request.app.state.auth_conn
        destination = safe_next(next)
        user = authenticate(conn, username, password)
        if user is None:
            return templates.TemplateResponse(
                request,
                "login.html",
                {"next": destination, "error": LOGIN_FAILED},
                status_code=401,
            )

        token, _ = create_session(conn, user.username)
        remember_token = create_remember(conn, user.username) if remember else None
        conn.commit()

        response = RedirectResponse(destination, status_code=302)
        set_session_cookie(response, token, https_only)
        if remember_token is not None:
            set_remember_cookie(response, remember_token, https_only)
        return response

    @application.post("/logout")
    def logout(request: Request):
        """ALG-KK-AUTH-LOGOUT — revoke server-side, then clear the cookies."""
        conn = request.app.state.auth_conn
        delete_session(conn, request.cookies.get(SESSION_COOKIE, ""))
        remember = request.cookies.get(REMEMBER_COOKIE, "")
        if remember:
            delete_remember(conn, remember)
        conn.commit()

        response = RedirectResponse("/login", status_code=302)
        clear_auth_cookies(response)
        return response

    install_gate(application, auth_conn, https_only=https_only)

    # Registered last: a Mount at "/" matches everything, so it must not
    # shadow the routes above.
    application.mount("/", inner)

    return application


app = create_gate_app(
    os.environ.get("KNOW_KERNEL_DB", ":memory:"),
    auth_db_path(),
    https_only=os.environ.get("KNOW_KERNEL_HTTPS_ONLY", "").lower()
    in ("1", "true", "yes"),
)


def main() -> None:
    import uvicorn

    uvicorn.run("authgate.app:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
