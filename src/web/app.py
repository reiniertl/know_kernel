"""FastAPI application factory â€” ALG-KK-WEB-SERVE."""

from __future__ import annotations

import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

from graph.schema import SCHEMA_SQL

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_app(db_path: str) -> FastAPI:
    """Create and return the FastAPI application.

    Opens (or creates) the SQLite DB at *db_path* during startup and closes
    it on shutdown. The connection is available as ``request.app.state.conn``.
    """
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA_SQL)
        app.state.conn = conn
        yield
        conn.close()

    application = FastAPI(
        title="know_kernel",
        version="0.1.0",
        lifespan=lifespan,
    )

    from web.routes import setup_routes
    setup_routes(application, templates)

    return application


app = create_app(os.environ.get("KNOW_KERNEL_DB", ":memory:"))


def main() -> None:
    import uvicorn
    uvicorn.run("web.app:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
