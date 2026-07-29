"""Route handlers for the human-facing web API (ALG-KK-WEB-SERVE).

INV-KK-WEB-READ-ONLY: only GET endpoints are registered here.
INV-KK-WEB-FULL-ACCESS: all node kinds are served without filtering.
"""

from __future__ import annotations

import json

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from graph.diagnostics import diagnose_graph
from graph.engine import (
    compare_neighborhoods,
    list_nodes,
    match_scenarios,
    ranked_recommendations,
    transitive_impact,
)
from graph.briefing import build_concept_brief, classify_motivations
from graph.scoring import research_score


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


_DISPLAY_FIELDS: dict[str, tuple[str, int | None]] = {
    "Concept": ("name", None),
    "Source": ("url", 80),
    "Evidence": ("description", 60),
    "Advisory": ("assessment", 60),
    "Subsystem": ("name", None),
    "KernelInvariant": ("predicate", 60),
    "FailureMode": ("symptom", 60),
    "InteractionProtocol": ("rule", 60),
    "PerformanceProfile": ("metric", 40),
    "CompatibilityAssessment": ("synergy", 60),
    "OptimizationGoal": ("name", None),
    "UseCaseScenario": ("name", None),
    "ComparativeAnalysis": ("dimension", 60),
    "Kernel": ("name", None),
    "Problem": ("title", None),
    "Observation": ("claim", 60),
    "Discussion": ("title", None),
    "Benchmark": ("metric", 40),
    "Rejection": ("proposal_title", 60),
    "Vulnerability": ("cve_id", None),
    "Fix": ("title", 60),
    "Proposal": ("name", None),
    "Trend": ("title", None),
    "Opportunity": ("title", None),
}


def display_name_for_node(kind: str, attrs: dict, node_id: str) -> str:
    """Resolve a human-readable display name (ALG-KK-WEB-DISPLAY-NAME)."""
    field, max_len = _DISPLAY_FIELDS.get(kind, (None, None))
    if field:
        value = (attrs.get(field) or "").strip()
        if value:
            if max_len and len(value) > max_len:
                return value[:max_len] + "..."
            return value
    if kind == "Vulnerability":
        value = (attrs.get("title") or "").strip()
        if value:
            return value
    if kind == "Evidence":
        return f"Evidence {node_id[-8:]}"
    return node_id


def _all_kinds(conn) -> list[str]:
    """Return sorted list of distinct node kinds (ALG-KK-WEB-KIND-DROPDOWN)."""
    rows = conn.execute("SELECT DISTINCT kind FROM nodes ORDER BY kind").fetchall()
    return [r["kind"] for r in rows]


def _batch_review_status(conn, source_ids: list[str]) -> dict[str, dict]:
    """Batch-query review status for multiple sources (ALG-KK-WEB-FEED-REVIEW-BADGE).

    INV-KK-WEB-QUERY-BOUNDED: single IN(...) query, not per-paper.
    """
    if not source_ids:
        return {}
    ph = ",".join("?" for _ in source_ids)
    rows = conn.execute(
        f"SELECT e.source_id, "
        f"json_extract(n.attrs, '$.score') as score, "
        f"json_extract(n.attrs, '$.verdict') as verdict "
        f"FROM edges e JOIN nodes n ON e.target_id = n.id "
        f"WHERE e.kind = 'reviewed-by' AND n.kind = 'HumanReview' "
        f"AND e.source_id IN ({ph})",
        source_ids,
    ).fetchall()
    agg: dict[str, dict] = {}
    for sid, score, verdict in rows:
        if sid not in agg:
            agg[sid] = {"scores": [], "verdicts": []}
        agg[sid]["scores"].append(score)
        agg[sid]["verdicts"].append(verdict)
    result: dict[str, dict] = {}
    for sid, data in agg.items():
        scores = [s for s in data["scores"] if s is not None]
        result[sid] = {
            "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
            "count": len(data["scores"]),
            "latest_verdict": data["verdicts"][0] if data["verdicts"] else None,
        }
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

    @app.get("/concepts/{node_id}", response_class=HTMLResponse)
    async def concept_detail(request: Request, node_id: str):
        conn = request.app.state.conn
        row = conn.execute(
            "SELECT id, kind, attrs FROM nodes WHERE id = ?", (node_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Node not found")
        node = _rows_to_dicts([row])[0]
        node["display_name"] = display_name_for_node(
            node["kind"], node.get("attrs") or {}, node["id"]
        )
        edge_rows = conn.execute(
            "SELECT kind, source_id, target_id FROM edges "
            "WHERE source_id = ? OR target_id = ? ORDER BY kind",
            (node_id, node_id),
        ).fetchall()
        edges = [dict(e) for e in edge_rows]
        grouped_edges: dict[str, list[dict]] = {}
        for e in edges:
            grouped_edges.setdefault(e["kind"], []).append(e)
        neighbor_ids = {
            nid
            for e in edges
            for nid in (e["source_id"], e["target_id"])
            if nid != node_id
        }
        node_labels: dict[str, str] = {}
        neighbor_dicts: list[dict] = []
        if neighbor_ids:
            placeholders = ",".join("?" for _ in neighbor_ids)
            label_rows = conn.execute(
                f"SELECT id, kind, attrs FROM nodes WHERE id IN ({placeholders})",
                tuple(neighbor_ids),
            ).fetchall()
            for lr in label_rows:
                lr_dict = _rows_to_dicts([lr])[0]
                attrs = lr_dict.get("attrs") or {}
                kind = lr_dict["kind"]
                label = display_name_for_node(kind, attrs, lr_dict["id"])
                node_labels[lr_dict["id"]] = f"{label} ({kind})"
                neighbor_dicts.append(lr_dict)

        related_code = []
        if node["kind"] in ("KernelInvariant", "InteractionProtocol"):
            for nd in neighbor_dicts:
                if nd["kind"] == "Concept":
                    nd_attrs = nd.get("attrs") or {}
                    if nd_attrs.get("code_examples"):
                        related_code.append({
                            "concept_name": nd_attrs.get("name", nd["id"]),
                            "concept_id": nd["id"],
                            "examples": nd_attrs["code_examples"],
                        })
        elif node["kind"] == "FailureMode" and not related_code:
            kinv_ids = [nd["id"] for nd in neighbor_dicts if nd["kind"] == "KernelInvariant"]
            if kinv_ids:
                kinv_ph = ",".join("?" for _ in kinv_ids)
                concept_rows = conn.execute(
                    f"SELECT DISTINCT n.id, n.kind, n.attrs FROM nodes n "
                    f"JOIN edges e ON e.source_id IN ({kinv_ph}) AND e.kind = 'governed-by' AND e.target_id = n.id "
                    f"WHERE n.kind = 'Concept'",
                    tuple(kinv_ids),
                ).fetchall()
                for cr in concept_rows:
                    cr_dict = _rows_to_dicts([cr])[0]
                    cr_attrs = cr_dict.get("attrs") or {}
                    if cr_attrs.get("code_examples"):
                        related_code.append({
                            "concept_name": cr_attrs.get("name", cr_dict["id"]),
                            "concept_id": cr_dict["id"],
                            "examples": cr_attrs["code_examples"],
                        })

        return templates.TemplateResponse(
            request,
            "concept_detail.html",
            {
                "node": node,
                "edges": edges,
                "grouped_edges": grouped_edges,
                "node_labels": node_labels,
                "related_code": related_code,
            },
        )

    @app.get("/sources", response_class=HTMLResponse)
    async def sources_list(
        request: Request,
        page: int = Query(1, ge=1),
        per_page: int = Query(50, ge=10, le=200),
    ):
        conn = request.app.state.conn
        offset = (page - 1) * per_page
        rows = conn.execute(
            "SELECT id, kind, attrs FROM nodes WHERE kind = 'Source' ORDER BY id LIMIT ? OFFSET ?",
            (per_page + 1, offset),
        ).fetchall()
        has_next = len(rows) > per_page
        rows = rows[:per_page]
        nodes = _rows_to_dicts(rows)
        for n in nodes:
            n["display_name"] = display_name_for_node(n["kind"], n.get("attrs") or {}, n["id"])
        return templates.TemplateResponse(
            request,
            "concept_list.html",
            {"nodes": nodes, "title": "Sources", "active_kind": "Source", "all_kinds": _all_kinds(conn), "page": page, "per_page": per_page, "has_next": has_next},
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

    @app.get("/api/impact/{node_id}")
    async def api_impact(request: Request, node_id: str):
        conn = request.app.state.conn
        row = conn.execute("SELECT id FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if row is None:
            return JSONResponse({"error": "Node not found"}, status_code=404)
        return transitive_impact(conn, node_id)

    @app.get("/api/compare/{id_a}/{id_b}")
    async def api_compare(request: Request, id_a: str, id_b: str):
        conn = request.app.state.conn
        for nid in (id_a, id_b):
            if conn.execute("SELECT id FROM nodes WHERE id = ?", (nid,)).fetchone() is None:
                return JSONResponse({"error": f"Node {nid} not found"}, status_code=404)
        diff = compare_neighborhoods(conn, id_a, id_b, depth=1)
        comp_rows = conn.execute(
            "SELECT n.id, n.kind, n.attrs FROM nodes n "
            "JOIN edges e1 ON e1.source_id = n.id AND e1.kind = 'compares' AND e1.target_id = ? "
            "JOIN edges e2 ON e2.source_id = n.id AND e2.kind = 'compares' AND e2.target_id = ? "
            "WHERE n.kind = 'ComparativeAnalysis'",
            (id_a, id_b),
        ).fetchall()
        comparatives = _rows_to_dicts(comp_rows)
        return {"diff": diff, "comparatives": comparatives}

    @app.get("/api/recommendations/{goal_id}")
    async def api_recommendations(request: Request, goal_id: str, limit: int = Query(10)):
        conn = request.app.state.conn
        row = conn.execute("SELECT id FROM nodes WHERE id = ?", (goal_id,)).fetchone()
        if row is None:
            return JSONResponse({"error": "Goal not found"}, status_code=404)
        return ranked_recommendations(conn, goal_id, limit)

    @app.get("/api/match")
    async def api_match(request: Request, workload_type: str = Query(None)):
        if workload_type is None:
            return JSONResponse({"error": "workload_type parameter required"}, status_code=400)
        conn = request.app.state.conn
        return match_scenarios(conn, workload_type=workload_type)

    @app.get("/api/search")
    async def api_search(request: Request, q: str = Query(""), kind: str | None = None):
        """Search nodes by name/description/attrs (ALG-KK-WEB-SEARCH, INV-KK-WEB-SEARCH-FULL-ACCESS)."""
        conn = request.app.state.conn
        if not q.strip():
            if request.headers.get("HX-Request"):
                return HTMLResponse("")
            return JSONResponse([])
        pattern = f"%{q}%"
        sql = (
            "SELECT id, kind, attrs FROM nodes"
            " WHERE (json_extract(attrs, '$.name') LIKE ?"
            " OR json_extract(attrs, '$.description') LIKE ?"
            " OR attrs LIKE ?)"
        )
        params: list[str] = [pattern, pattern, pattern]
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        sql += " ORDER BY kind, id LIMIT 30"
        rows = conn.execute(sql, params).fetchall()
        results = _rows_to_dicts(rows)
        for r in results:
            r["display_name"] = display_name_for_node(
                r["kind"], r.get("attrs") or {}, r["id"]
            )
        if request.headers.get("HX-Request"):
            return templates.TemplateResponse(
                request, "search_results.html", {"results": results}
            )
        return JSONResponse(
            [{"id": r["id"], "kind": r["kind"], "attrs": r["attrs"], "display_name": r["display_name"]} for r in results]
        )

    @app.get("/api/diagnostics")
    async def api_diagnostics(request: Request):
        import dataclasses

        conn = request.app.state.conn
        report = diagnose_graph(conn)
        return dataclasses.asdict(report)

    @app.get("/health", response_class=HTMLResponse)
    async def health_page(request: Request):
        """Render graph health diagnostics as HTML (ALG-KK-WEB-DIAGNOSTICS-PAGE)."""
        import dataclasses

        conn = request.app.state.conn
        report = diagnose_graph(conn)
        return templates.TemplateResponse(
            request, "health.html", {"report": dataclasses.asdict(report)},
        )

    @app.get("/impact/{node_id}", response_class=HTMLResponse)
    async def impact_page(request: Request, node_id: str):
        """Render transitive impact surface as HTML (ALG-KK-WEB-IMPACT-PAGE)."""
        conn = request.app.state.conn
        row = conn.execute(
            "SELECT id, kind, attrs FROM nodes WHERE id = ?", (node_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Node not found")
        node = _rows_to_dicts([row])[0]
        node["display_name"] = display_name_for_node(
            node["kind"], node.get("attrs") or {}, node["id"]
        )
        impact = transitive_impact(conn, node_id)
        for category in impact.values():
            for item in category:
                item["display_name"] = display_name_for_node(
                    item["kind"], item.get("attrs") or {}, item["id"]
                )
        return templates.TemplateResponse(
            request, "impact.html", {"node": node, "impact": impact},
        )
    @app.get("/feed", response_class=HTMLResponse)
    async def research_feed(
        request: Request,
        page: int = Query(1, ge=1),
        per_page: int = Query(50, ge=10, le=200),
    ):
        """Research feed as paginated flat table (ALG-KK-WEB-FEED-LIST).

        INV-KK-WEB-QUERY-BOUNDED: SQL-level LIMIT/OFFSET; enrichment
        only for current page's papers.
        """
        conn = request.app.state.conn

        _RESEARCH_TYPES = "('paper','preprint','conference-paper','conference-proceedings')"
        _SOURCE_WHERE = (
            "FROM nodes WHERE kind = 'Source' "
            f"AND json_extract(attrs, '$.source_type') IN {_RESEARCH_TYPES}"
        )

        total = conn.execute(f"SELECT COUNT(*) {_SOURCE_WHERE}").fetchone()[0]
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = min(page, total_pages)

        page_sources = conn.execute(
            f"SELECT id, attrs {_SOURCE_WHERE} "
            "ORDER BY json_extract(attrs, '$.published_date') DESC, id "
            "LIMIT ? OFFSET ?",
            (per_page, (page - 1) * per_page),
        ).fetchall()

        from graph.briefing import classify_source_motivations

        page_sids = [r[0] for r in page_sources]
        page_attrs_map = {}
        for r in page_sources:
            page_attrs_map[r[0]] = json.loads(r[1]) if isinstance(r[1], str) else (r[1] or {})

        concepts_by_source: dict[str, list[tuple[str, dict]]] = {sid: [] for sid in page_sids}
        if page_sids:
            ph = ",".join("?" for _ in page_sids)
            concept_rows = conn.execute(
                f"SELECT se.target_id as source_id, c.id, c.attrs "
                f"FROM edges se "
                f"JOIN nodes ev ON ev.id = se.source_id AND ev.kind = 'Evidence' "
                f"JOIN edges ce ON ce.kind = 'extracted-from' AND ce.target_id = ev.id "
                f"JOIN nodes c ON c.id = ce.source_id AND c.kind = 'Concept' "
                f"WHERE se.kind = 'sourced-from' AND se.target_id IN ({ph})",
                page_sids,
            ).fetchall()
            for src_id, cid, c_raw in concept_rows:
                c_attrs = json.loads(c_raw) if isinstance(c_raw, str) else (c_raw or {})
                concepts_by_source[src_id].append((cid, c_attrs))

        items: list[dict] = []
        for sid in page_sids:
            s_attrs = page_attrs_map[sid]
            crows = concepts_by_source.get(sid, [])

            concept_names = []
            first_cid = ""
            first_desc = ""
            subsystems: list[str] = []
            seen_cids: set[str] = set()
            for cid, c_attrs in crows:
                if cid in seen_cids:
                    continue
                seen_cids.add(cid)
                concept_names.append(c_attrs.get("name", cid))
                if not first_cid:
                    first_cid = cid
                    first_desc = c_attrs.get("description", "")
                for s in _get_concept_subsystems(conn, cid):
                    if s not in subsystems:
                        subsystems.append(s)

            items.append({
                "source_id": sid,
                "title": s_attrs.get("title", sid),
                "url": s_attrs.get("url", ""),
                "source_type": s_attrs.get("source_type", ""),
                "published_date": s_attrs.get("published_date", s_attrs.get("source_date", "")),
                "concept_id": first_cid,
                "concept_name": ", ".join(concept_names) if concept_names else "",
                "motivations": classify_source_motivations(conn, sid),
                "summary": _truncate_words(first_desc, 100),
                "subsystems": subsystems,
            })

        feed_sids = [item["source_id"] for item in items]
        review_status = _batch_review_status(conn, feed_sids)
        for item in items:
            item["review"] = review_status.get(item["source_id"])

        return templates.TemplateResponse(
            request,
            "feed.html",
            {"items": items, "total": total, "page": page, "per_page": per_page, "total_pages": total_pages},
        )

    def _truncate_words(text: str, max_words: int = 100) -> str:
        words = text.split()
        if len(words) <= max_words:
            return text
        return " ".join(words[:max_words]) + "..."

    def _get_concept_subsystems(conn, concept_id: str) -> list[str]:
        rows = conn.execute(
            "SELECT n.attrs FROM nodes n "
            "JOIN edges e ON e.kind = 'belongs-to' AND e.source_id = ? AND e.target_id = n.id "
            "WHERE n.kind = 'Subsystem'",
            (concept_id,),
        ).fetchall()
        result = []
        for r in rows:
            attrs = json.loads(r[0]) if isinstance(r[0], str) else (r[0] or {})
            name = attrs.get("name", "")
            if name:
                result.append(name)
        return result

    _TYPE_EMOJI = {
        "preprint": "\U0001f4dd",
        "conference-paper": "\U0001f3db️",
        "conference-proceedings": "\U0001f3a4",
        "paper": "\U0001f4d6",
    }

    _MOTIV_EMOJI = {
        "SECURITY": "\U0001f534",
        "STABILITY": "⚠️",
        "PERFORMANCE": "⚡",
        "SCALABILITY": "\U0001f4c8",
        "EFFICIENCY": "\U0001f4a1",
        "HARDWARE ENABLEMENT": "\U0001f527",
        "MAINTAINABILITY": "\U0001f504",
    }

    _BASE_URL = "http://10.123.102.166:8000"

    def _build_single_card_text(item: dict) -> str:
        """Build emoji card text for a single paper (ALG-KK-WEB-FEED-CARD)."""
        emoji = _TYPE_EMOJI.get(item.get("source_type", ""), "\U0001f4c4")
        lines = [f"{emoji} *{item.get('concept', '')}*"]
        motivs = item.get("motivations", [])
        if motivs:
            tags = " ".join(
                f"{_MOTIV_EMOJI.get(m, '')}{m}" for m in motivs
            )
            lines.append(f"   {tags}")
        subsystems = item.get("subsystems", [])
        if subsystems:
            sub_tags = " ".join(f"[{s}]" for s in subsystems)
            lines.append(f"   \U0001f4c2 {sub_tags}")
        summary = item.get("summary", "")
        if summary:
            lines.append(f"   _{summary}_")
        paper_url = item.get("url", "")
        if paper_url:
            lines.append(f"   \U0001f4c4 {paper_url}")
        research_card_url = item.get("research_card_url", "")
        if research_card_url:
            lines.append(f"   \U0001f517 {research_card_url}")
        return "\\n".join(lines).replace("\n", "\\n")

    @app.get("/api/feed/card/{source_id:path}")
    async def feed_card_json(request: Request, source_id: str):
        """JSON card for a single paper (ALG-KK-WEB-FEED-CARD)."""
        conn = request.app.state.conn

        row = conn.execute(
            "SELECT s.id, s.attrs, c.id as concept_id, c.attrs as concept_attrs "
            "FROM nodes s "
            "JOIN edges se ON se.kind = 'sourced-from' AND se.target_id = s.id "
            "JOIN nodes ev ON ev.id = se.source_id AND ev.kind = 'Evidence' "
            "JOIN edges ce ON ce.kind = 'extracted-from' AND ce.target_id = ev.id "
            "JOIN nodes c ON c.id = ce.source_id AND c.kind = 'Concept' "
            "WHERE s.kind = 'Source' AND s.id = ? "
            "LIMIT 1",
            (source_id,),
        ).fetchone()

        if row is None:
            return JSONResponse({"error": "Source not found"}, status_code=404)

        from graph.briefing import classify_source_motivations

        s_attrs = json.loads(row[1]) if isinstance(row[1], str) else (row[1] or {})
        c_attrs = json.loads(row[3]) if isinstance(row[3], str) else (row[3] or {})
        cid = row[2]
        item = {
            "title": s_attrs.get("title", source_id),
            "url": s_attrs.get("url", ""),
            "source_type": s_attrs.get("source_type", ""),
            "concept": c_attrs.get("name", cid),
            "concept_url": f"{_BASE_URL}/concepts/{cid}",
            "research_card_url": f"{_BASE_URL}/paper/{source_id}",
            "summary": _truncate_words(c_attrs.get("description", ""), 100),
            "subsystems": _get_concept_subsystems(conn, cid),
            "motivations": classify_source_motivations(conn, source_id),
        }

        card_text = _build_single_card_text(item)
        return JSONResponse({
            "source_id": source_id,
            "card": card_text,
            "item": item,
        })

    @app.post("/api/feed/send/{source_id:path}")
    async def feed_send_card(request: Request, source_id: str):
        """Execute CLI command with single-paper card text replacing <CARD> placeholder (ALG-KK-WEB-FEED-SEND)."""
        import subprocess

        body = await request.json()
        cli_template = body.get("cli_command", "")
        if not cli_template or "<CARD>" not in cli_template:
            return JSONResponse({"error": "CLI command must contain <CARD> placeholder"}, status_code=400)

        conn = request.app.state.conn
        row = conn.execute(
            "SELECT s.id, s.attrs, c.id as concept_id, c.attrs as concept_attrs "
            "FROM nodes s "
            "JOIN edges se ON se.kind = 'sourced-from' AND se.target_id = s.id "
            "JOIN nodes ev ON ev.id = se.source_id AND ev.kind = 'Evidence' "
            "JOIN edges ce ON ce.kind = 'extracted-from' AND ce.target_id = ev.id "
            "JOIN nodes c ON c.id = ce.source_id AND c.kind = 'Concept' "
            "WHERE s.kind = 'Source' AND s.id = ? "
            "LIMIT 1",
            (source_id,),
        ).fetchone()

        if row is None:
            return JSONResponse({"error": "Source not found"}, status_code=404)

        from graph.briefing import classify_source_motivations

        s_attrs = json.loads(row[1]) if isinstance(row[1], str) else (row[1] or {})
        c_attrs = json.loads(row[3]) if isinstance(row[3], str) else (row[3] or {})
        cid = row[2]
        item = {
            "title": s_attrs.get("title", source_id),
            "url": s_attrs.get("url", ""),
            "source_type": s_attrs.get("source_type", ""),
            "concept": c_attrs.get("name", cid),
            "concept_url": f"{_BASE_URL}/concepts/{cid}",
            "research_card_url": f"{_BASE_URL}/paper/{source_id}",
            "summary": _truncate_words(c_attrs.get("description", ""), 100),
            "subsystems": _get_concept_subsystems(conn, cid),
            "motivations": classify_source_motivations(conn, source_id),
        }

        card_text = _build_single_card_text(item)
        full_command = cli_template.replace("<CARD>", card_text)

        try:
            result = subprocess.run(
                full_command, shell=True, capture_output=True, text=True, timeout=30,
            )
            return JSONResponse({
                "status": "ok" if result.returncode == 0 else "error",
                "returncode": result.returncode,
                "stdout": result.stdout[:500],
                "stderr": result.stderr[:500],
                "command_preview": full_command[:200],
            })
        except subprocess.TimeoutExpired:
            return JSONResponse({"status": "timeout", "error": "Command timed out after 30s"}, status_code=504)
        except Exception as e:
            return JSONResponse({"status": "error", "error": str(e)}, status_code=500)

    @app.get("/paper/{source_id:path}", response_class=HTMLResponse)
    async def paper_detail(request: Request, source_id: str):
        """Paper detail page (ALG-KK-WEB-PAPER-DETAIL).

        INV-KK-WEB-PAPER-404-NON-SOURCE: 404 for missing or non-Source.
        INV-KK-WEB-PAPER-CONCEPT-CHAIN: all concepts shown with links.
        """
        conn = request.app.state.conn

        row = conn.execute(
            "SELECT id, kind, attrs FROM nodes WHERE id = ?", (source_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Paper not found")
        node = _rows_to_dicts([row])[0]
        if node["kind"] != "Source":
            raise HTTPException(status_code=404, detail="Not a Source node")
        s_attrs = node.get("attrs") or {}

        ev_rows = conn.execute(
            "SELECT ev.id, ev.attrs FROM nodes ev "
            "JOIN edges se ON se.kind = 'sourced-from' AND se.source_id = ev.id "
            "AND se.target_id = ? WHERE ev.kind = 'Evidence'",
            (source_id,),
        ).fetchall()
        evidence_ids = [r[0] for r in ev_rows]

        research_brief = None
        if evidence_ids:
            placeholders = ",".join("?" for _ in evidence_ids)
            rb_row = conn.execute(
                f"SELECT rb.attrs FROM nodes rb "
                f"JOIN edges re ON re.kind = 'extracted-from' "
                f"AND re.source_id = rb.id AND re.target_id IN ({placeholders}) "
                f"WHERE rb.kind = 'ResearchBrief' LIMIT 1",
                evidence_ids,
            ).fetchone()
            if rb_row:
                rb_attrs = json.loads(rb_row[0]) if isinstance(rb_row[0], str) else (rb_row[0] or {})
                key_ideas = rb_attrs.get("key_ideas", [])
                if isinstance(key_ideas, str):
                    try:
                        key_ideas = json.loads(key_ideas)
                    except (ValueError, TypeError):
                        key_ideas = [key_ideas]
                research_brief = {
                    "key_ideas": key_ideas,
                    "relevance": rb_attrs.get("relevance", ""),
                    "methodology": rb_attrs.get("methodology", ""),
                }

        concepts = []
        all_motivations: dict[str, dict] = {}
        all_subsystems: set[str] = set()

        if evidence_ids:
            concept_rows = conn.execute(
                f"SELECT DISTINCT c.id, c.attrs FROM nodes c "
                f"JOIN edges ce ON ce.kind = 'extracted-from' "
                f"AND ce.source_id = c.id AND ce.target_id IN ({placeholders}) "
                f"WHERE c.kind = 'Concept'",
                evidence_ids,
            ).fetchall()

            for crow in concept_rows:
                cid = crow[0]
                c_attrs = json.loads(crow[1]) if isinstance(crow[1], str) else (crow[1] or {})

                brief = build_concept_brief(conn, cid)
                motivs = classify_motivations(brief)
                rs = research_score(conn, cid)

                sub_name = ""
                if brief.get("subsystem"):
                    sub_name = brief["subsystem"].get("name", "")
                    if sub_name:
                        all_subsystems.add(sub_name)

                concepts.append({
                    "id": cid,
                    "name": c_attrs.get("name", cid),
                    "description": _truncate_words(c_attrs.get("description", ""), 100),
                    "research_score": rs,
                    "subsystem": sub_name,
                })

                for m in motivs:
                    cat = m["category"]
                    if cat not in all_motivations:
                        all_motivations[cat] = m
                    else:
                        existing = all_motivations[cat]
                        existing["evidence"] = existing.get("evidence", []) + m.get("evidence", [])
                        if m.get("blast_radius") and m["blast_radius"].get("count", 0) > 0:
                            if not existing.get("blast_radius"):
                                existing["blast_radius"] = m["blast_radius"]
                            else:
                                seen_ids = {c["id"] for c in existing["blast_radius"].get("components", [])}
                                for comp in m["blast_radius"].get("components", []):
                                    if comp["id"] not in seen_ids:
                                        existing["blast_radius"]["components"].append(comp)
                                existing["blast_radius"]["count"] = len(existing["blast_radius"]["components"])

        merged_motivations = list(all_motivations.values())

        _CLAIM_KINDS = ("Problem", "Observation", "Discussion", "Benchmark", "Proposal", "Rejection")
        _TEXT_FIELD = {
            "Problem": "title", "Observation": "claim",
            "Discussion": "title", "Benchmark": "result_summary",
            "Proposal": "name", "Rejection": "proposal_title",
        }
        paper_evidence: list[dict] = []
        if evidence_ids:
            ev_ph = ",".join("?" for _ in evidence_ids)
            ck_ph = ",".join("?" for _ in _CLAIM_KINDS)
            claim_rows = conn.execute(
                f"SELECT n.id, n.kind, n.attrs FROM nodes n "
                f"JOIN edges e ON e.kind = 'extracted-from' "
                f"AND e.source_id = n.id AND e.target_id IN ({ev_ph}) "
                f"WHERE n.kind IN ({ck_ph})",
                evidence_ids + list(_CLAIM_KINDS),
            ).fetchall()
            for cr in claim_rows:
                ca = json.loads(cr[2]) if isinstance(cr[2], str) else (cr[2] or {})
                paper_evidence.append({
                    "id": cr[0],
                    "kind": cr[1],
                    "text": ca.get(_TEXT_FIELD.get(cr[1], "title"), ""),
                    "source_date": ca.get("source_date", ""),
                })
            paper_evidence.sort(key=lambda x: x.get("source_date") or "", reverse=True)

        review_rows = conn.execute(
            "SELECT n.id, n.attrs FROM edges e JOIN nodes n ON e.target_id = n.id "
            "WHERE e.kind = 'reviewed-by' AND e.source_id = ? AND n.kind = 'HumanReview'",
            (source_id,),
        ).fetchall()
        existing_reviews = []
        for rr in review_rows:
            r_attrs = json.loads(rr[1]) if isinstance(rr[1], str) else (rr[1] or {})
            existing_reviews.append({
                "review_id": rr[0],
                "reviewer": r_attrs.get("reviewer", ""),
                "score": r_attrs.get("score", 0),
                "verdict": r_attrs.get("verdict", ""),
                "rationale": r_attrs.get("rationale", ""),
                "review_date": r_attrs.get("review_date", ""),
            })

        return templates.TemplateResponse(
            request,
            "paper_detail.html",
            {
                "source": node,
                "s_attrs": s_attrs,
                "research_brief": research_brief,
                "concepts": concepts,
                "motivations": merged_motivations,
                "subsystems": sorted(all_subsystems),
                "paper_evidence": paper_evidence,
                "existing_reviews": existing_reviews,
            },
        )

    def _classify_concept_motivations_fast(name: str, description: str, subsystem: str) -> list[str]:
        """Keyword-based motivation classification — pure Python, no DB (INV-KK-WEB-QUERY-BOUNDED)."""
        text = f"{name} {description}".lower()
        labels = []

        _PERF_KW = {"latency", "throughput", "overhead", "bottleneck", "faster", "slower",
                     "speedup", "bandwidth", "iops", "cycles", "cache miss", "tlb miss", "context switch"}
        _SCALE_KW = {"numa", "scalab", "contention", "lock contention", "per-cpu", "per-node",
                      "cache line bouncing", "false sharing", "thundering herd", "multi-socket"}
        _EFF_KW = {"memory overhead", "memory footprint", "power consumption", "energy",
                    "cpu utilization", "footprint", "bloat", "fragmentation", "metadata overhead"}
        _HW_KW = {"hardware", "cxl", "pcie", "nvme", "accelerat", "fpga", "gpu", "dpu",
                   "tdx", "sev", "persistent memory", "pmem", "ddr5", "hbm"}
        _HW_SUBS = {"Device Drivers", "Virtualization", "Storage Stack", "Firmware Interface", "Cryptography"}
        _SEC_KW = {"security", "vulnerab", "exploit", "attack", "access control", "sandbox",
                    "isolation", "seccomp", "selinux", "capability", "privilege"}

        if any(kw in text for kw in _SEC_KW) or subsystem == "Security":
            labels.append("SECURITY")
        if any(kw in text for kw in {"crash", "fault", "failure", "reliability", "stability", "recovery"}):
            labels.append("STABILITY")
        if any(kw in text for kw in _PERF_KW):
            labels.append("PERFORMANCE")
        if any(kw in text for kw in _SCALE_KW):
            labels.append("SCALABILITY")
        if any(kw in text for kw in _EFF_KW):
            labels.append("EFFICIENCY")
        if any(kw in text for kw in _HW_KW) or subsystem in _HW_SUBS:
            labels.append("HARDWARE ENABLEMENT")
        if any(kw in text for kw in {"maintainab", "complexity", "technical debt", "refactor", "modular"}):
            labels.append("MAINTAINABILITY")

        return labels

    @app.get("/radar", response_class=HTMLResponse)
    async def radar(request: Request):
        """Research radar: papers grouped by subsystem then concept (ALG-KK-WEB-RADAR).

        INV-KK-WEB-QUERY-BOUNDED: no per-paper enrichment queries.
        Motivations via keyword matching on concept attrs.
        """
        conn = request.app.state.conn

        rows = conn.execute(
            "SELECT s.id, s.attrs, c.id as concept_id, c.attrs as concept_attrs "
            "FROM nodes s "
            "JOIN edges se ON se.kind = 'sourced-from' AND se.target_id = s.id "
            "JOIN nodes ev ON ev.id = se.source_id AND ev.kind = 'Evidence' "
            "JOIN edges ce ON ce.kind = 'extracted-from' AND ce.target_id = ev.id "
            "JOIN nodes c ON c.id = ce.source_id AND c.kind = 'Concept' "
            "WHERE s.kind = 'Source' "
            "AND json_extract(s.attrs, '$.source_type') IN "
            "('paper','preprint','conference-paper','conference-proceedings') "
            "ORDER BY c.id, json_extract(s.attrs, '$.published_date') DESC"
        ).fetchall()

        all_sids = list({row[0] for row in rows})
        review_status = _batch_review_status(conn, all_sids)

        concept_ids = list({row[2] for row in rows})
        subsystem_map: dict[str, str] = {}
        if concept_ids:
            ph = ",".join("?" for _ in concept_ids)
            sub_rows = conn.execute(
                f"SELECT e.source_id, json_extract(n.attrs, '$.name') "
                f"FROM edges e JOIN nodes n ON e.target_id = n.id "
                f"WHERE e.kind = 'belongs-to' AND n.kind = 'Subsystem' "
                f"AND e.source_id IN ({ph})",
                concept_ids,
            ).fetchall()
            for cid, sname in sub_rows:
                if sname:
                    subsystem_map[cid] = sname

        by_concept: dict[str, dict] = {}
        for row in rows:
            s_attrs = json.loads(row[1]) if isinstance(row[1], str) else (row[1] or {})
            c_attrs = json.loads(row[3]) if isinstance(row[3], str) else (row[3] or {})
            cid = row[2]
            sid = row[0]
            pub_date = s_attrs.get("published_date", s_attrs.get("source_date", ""))

            if cid not in by_concept:
                sub_name = subsystem_map.get(cid, "Uncategorized")
                motivs = _classify_concept_motivations_fast(
                    c_attrs.get("name", ""), c_attrs.get("description", ""), sub_name,
                )
                by_concept[cid] = {
                    "concept_id": cid,
                    "concept_name": c_attrs.get("name", cid),
                    "subsystem": sub_name,
                    "motivations": sorted(motivs),
                    "latest_date": "",
                    "papers": [],
                }

            entry = by_concept[cid]
            if pub_date and pub_date > entry["latest_date"]:
                entry["latest_date"] = pub_date

            entry["papers"].append({
                "source_id": sid,
                "title": s_attrs.get("title", sid),
                "url": s_attrs.get("url", ""),
                "source_type": s_attrs.get("source_type", ""),
                "published_date": pub_date,
                "review": review_status.get(sid),
            })

        by_subsystem: dict[str, dict] = {}
        for c in by_concept.values():
            c["paper_count"] = len(c["papers"])
            sub_name = c["subsystem"]
            if sub_name not in by_subsystem:
                by_subsystem[sub_name] = {
                    "name": sub_name,
                    "motivations_set": set(),
                    "concepts": [],
                    "total_papers": 0,
                }
            sub = by_subsystem[sub_name]
            sub["concepts"].append(c)
            sub["total_papers"] += c["paper_count"]
            sub["motivations_set"].update(c["motivations"])

        subsystems = list(by_subsystem.values())
        for sub in subsystems:
            sub["motivations"] = sorted(sub.pop("motivations_set"))
            sub["concepts"].sort(key=lambda x: x["paper_count"], reverse=True)
        subsystems.sort(key=lambda x: x["total_papers"], reverse=True)

        total_papers = sum(s["total_papers"] for s in subsystems)
        return templates.TemplateResponse(
            request, "radar.html", {"subsystems": subsystems, "total_papers": total_papers},
        )

    @app.get("/reviews", response_class=HTMLResponse)
    async def reviews_list(
        request: Request,
        verdict: str | None = None,
        min_score: int | None = Query(None, ge=1, le=5),
        page: int = Query(1, ge=1),
        per_page: int = Query(50, ge=10, le=200),
    ):
        """Paginated review list (ALG-KK-WEB-REVIEWS-LIST).

        INV-KK-WEB-QUERY-BOUNDED: SQL LIMIT/OFFSET pagination.
        """
        conn = request.app.state.conn
        sql = (
            "SELECT n.id, n.attrs, s.id as source_id, s.attrs as source_attrs "
            "FROM nodes n "
            "JOIN edges e ON e.kind = 'reviewed-by' AND e.target_id = n.id "
            "JOIN nodes s ON s.id = e.source_id AND s.kind = 'Source' "
            "WHERE n.kind = 'HumanReview'"
        )
        params: list = []
        if verdict:
            sql += " AND json_extract(n.attrs, '$.verdict') = ?"
            params.append(verdict)
        if min_score is not None:
            sql += " AND CAST(json_extract(n.attrs, '$.score') AS INTEGER) >= ?"
            params.append(min_score)
        sql += " ORDER BY json_extract(n.attrs, '$.review_date') DESC"
        sql += " LIMIT ? OFFSET ?"
        params.extend([per_page + 1, (page - 1) * per_page])

        rows = conn.execute(sql, params).fetchall()
        has_next = len(rows) > per_page
        rows = rows[:per_page]

        reviews = []
        for r in rows:
            r_attrs = json.loads(r[1]) if isinstance(r[1], str) else (r[1] or {})
            s_attrs = json.loads(r[3]) if isinstance(r[3], str) else (r[3] or {})
            reviews.append({
                "review_id": r[0],
                "source_id": r[2],
                "paper_title": s_attrs.get("title", r[2]),
                "reviewer": r_attrs.get("reviewer", ""),
                "score": r_attrs.get("score", 0),
                "verdict": r_attrs.get("verdict", ""),
                "rationale": r_attrs.get("rationale", ""),
                "review_date": r_attrs.get("review_date", ""),
            })

        return templates.TemplateResponse(
            request,
            "reviews.html",
            {
                "reviews": reviews,
                "page": page,
                "per_page": per_page,
                "has_next": has_next,
                "verdict_filter": verdict,
                "min_score_filter": min_score,
            },
        )

    @app.get("/viz", response_class=HTMLResponse)
    async def viz(request: Request):
        return templates.TemplateResponse(request, "graph_viz.html", {})

    @app.post("/api/review/{source_id:path}")
    async def submit_review(request: Request, source_id: str):
        """Submit a human review for a paper (ALG-KK-WEB-REVIEW-SUBMIT).

        INV-KK-WEB-REVIEW-WRITE-SCOPED: only /api/review/* accepts POST/PUT.
        """
        from ingest.paper_scorer import review_paper
        import dataclasses

        conn = request.app.state.conn
        body = await request.json()
        try:
            result = review_paper(
                conn, source_id,
                body["reviewer"], body["score"],
                body["verdict"], body["rationale"],
            )
            conn.commit()
            return JSONResponse(dataclasses.asdict(result), status_code=201)
        except ValueError as exc:
            msg = str(exc)
            if "does not exist" in msg:
                return JSONResponse({"error": msg}, status_code=404)
            if "already reviewed" in msg:
                return JSONResponse({"error": msg}, status_code=409)
            return JSONResponse({"error": msg}, status_code=422)
        except KeyError as exc:
            return JSONResponse({"error": f"Missing field: {exc}"}, status_code=422)

    @app.put("/api/review/{review_id}")
    async def update_review(request: Request, review_id: str):
        """Update an existing human review (ALG-KK-WEB-REVIEW-EDIT).

        INV-KK-WEB-REVIEW-WRITE-SCOPED: only /api/review/* accepts POST/PUT.
        """
        from ingest.paper_scorer import edit_review
        import dataclasses

        conn = request.app.state.conn
        body = await request.json()
        try:
            result = edit_review(
                conn, review_id,
                body["score"], body["verdict"], body["rationale"],
            )
            conn.commit()
            return JSONResponse(dataclasses.asdict(result))
        except ValueError as exc:
            msg = str(exc)
            if "does not exist" in msg:
                return JSONResponse({"error": msg}, status_code=404)
            return JSONResponse({"error": msg}, status_code=400)
        except KeyError as exc:
            return JSONResponse({"error": f"Missing field: {exc}"}, status_code=400)

    @app.get("/api/review/{source_id:path}")
    async def review_status(request: Request, source_id: str):
        """Return existing reviews for a paper (ALG-KK-WEB-REVIEW-STATUS)."""
        conn = request.app.state.conn
        source = conn.execute(
            "SELECT id FROM nodes WHERE id = ? AND kind = 'Source'",
            (source_id,),
        ).fetchone()
        if source is None:
            return JSONResponse({"error": "Source not found"}, status_code=404)

        rows = conn.execute(
            "SELECT n.attrs FROM edges e JOIN nodes n ON e.target_id = n.id "
            "WHERE e.kind = 'reviewed-by' AND e.source_id = ? AND n.kind = 'HumanReview'",
            (source_id,),
        ).fetchall()
        reviews = []
        for r in rows:
            r_attrs = json.loads(r[0]) if isinstance(r[0], str) else (r[0] or {})
            reviews.append({
                "reviewer": r_attrs.get("reviewer", ""),
                "score": r_attrs.get("score", 0),
                "verdict": r_attrs.get("verdict", ""),
                "rationale": r_attrs.get("rationale", ""),
                "review_date": r_attrs.get("review_date", ""),
            })
        return JSONResponse(reviews)
