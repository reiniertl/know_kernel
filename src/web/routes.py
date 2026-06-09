"""Route handlers for the human-facing web API (ALG-KK-WEB-SERVE).

INV-KK-WEB-READ-ONLY: only GET endpoints are registered here.
INV-KK-WEB-FULL-ACCESS: all node kinds are served without filtering.
"""

from __future__ import annotations

import json

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


def _rows_to_dicts(rows) -> list[dict]:
    result = []
    for row in rows:
        d = dict(row)
        if "attrs" in d and isinstance(d["attrs"], str):
            try:
                d["attrs"] = json.loads(d["attrs"])
            except (ValueError, TypeError):
                d["attrs"] = {}
        result.append(d)
    return result


def setup_routes(app: FastAPI, templates: Jinja2Templates) -> None:
    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        conn = request.app.state.conn
        rows = conn.execute(
            "SELECT kind, COUNT(*) AS cnt FROM nodes GROUP BY kind ORDER BY kind"
        ).fetchall()
        counts = {row["kind"]: row["cnt"] for row in rows}
        total = sum(counts.values())
        edge_total = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {"counts": counts, "total": total, "edge_total": edge_total},
        )

    @app.get("/concepts", response_class=HTMLResponse)
    async def concepts_list(request: Request):
        """List all nodes in the knowledge base (all kinds — INV-KK-WEB-FULL-ACCESS)."""
        conn = request.app.state.conn
        rows = conn.execute(
            "SELECT id, kind, attrs FROM nodes ORDER BY kind, id"
        ).fetchall()
        nodes = _rows_to_dicts(rows)
        return templates.TemplateResponse(
            request,
            "concept_list.html",
            {"nodes": nodes, "title": "Knowledge Base"},
        )

    @app.get("/concepts/{node_id}", response_class=HTMLResponse)
    async def concept_detail(request: Request, node_id: str):
        conn = request.app.state.conn
        row = conn.execute(
            "SELECT id, kind, attrs FROM nodes WHERE id = ?", (node_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Node not found")
        node = _rows_to_dicts([row])[0]
        edge_rows = conn.execute(
            "SELECT kind, source_id, target_id FROM edges "
            "WHERE source_id = ? OR target_id = ? ORDER BY kind",
            (node_id, node_id),
        ).fetchall()
        edges = [dict(e) for e in edge_rows]
        return templates.TemplateResponse(
            request,
            "concept_detail.html",
            {"node": node, "edges": edges},
        )

    @app.get("/subsystems", response_class=HTMLResponse)
    async def subsystems_list(request: Request):
        conn = request.app.state.conn
        rows = conn.execute(
            "SELECT id, kind, attrs FROM nodes WHERE kind = 'Subsystem' ORDER BY id"
        ).fetchall()
        nodes = _rows_to_dicts(rows)
        return templates.TemplateResponse(
            request,
            "concept_list.html",
            {"nodes": nodes, "title": "Subsystems"},
        )

    @app.get("/sources", response_class=HTMLResponse)
    async def sources_list(request: Request):
        conn = request.app.state.conn
        rows = conn.execute(
            "SELECT id, kind, attrs FROM nodes WHERE kind = 'Source' ORDER BY id"
        ).fetchall()
        nodes = _rows_to_dicts(rows)
        return templates.TemplateResponse(
            request,
            "concept_list.html",
            {"nodes": nodes, "title": "Sources"},
        )

    @app.get("/graph")
    async def graph_json(request: Request):
        """Return the full node/edge set as JSON (INV-KK-WEB-FULL-ACCESS)."""
        conn = request.app.state.conn
        node_rows = conn.execute(
            "SELECT id, kind, attrs FROM nodes ORDER BY kind, id"
        ).fetchall()
        edge_rows = conn.execute(
            "SELECT kind, source_id, target_id FROM edges ORDER BY kind"
        ).fetchall()
        return {
            "nodes": _rows_to_dicts(node_rows),
            "edges": [dict(e) for e in edge_rows],
        }
