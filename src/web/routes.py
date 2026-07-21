"""Route handlers for the human-facing web API (ALG-KK-WEB-SERVE).

INV-KK-WEB-READ-ONLY: only GET endpoints are registered here.
INV-KK-WEB-FULL-ACCESS: all node kinds are served without filtering.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from graph.diagnostics import diagnose_graph
from graph.engine import (
    compare_neighborhoods,
    get_node,
    list_nodes,
    match_scenarios,
    ranked_recommendations,
    transitive_impact,
)
from graph.briefing import build_argument_paragraph, build_concept_brief, classify_motivations
from graph.scoring import (
    compute_all_scores,
    feasibility_score,
    impact_projection,
    is_security_only_concept,
    research_score,
    vulnerability_propagation,
)


_RESEARCH_SOURCE_TYPES = ("conference-paper", "conference-proceedings", "preprint", "article")


def _has_research_source(conn, concept_id: str) -> bool:
    """Check if concept has at least one evidence chain to a research-type source."""
    activity_nodes = conn.execute(
        "SELECT e.source_id FROM edges e JOIN nodes n ON e.source_id = n.id "
        "WHERE e.target_id = ? AND e.kind IN ('discusses', 'observes', 'benchmarks', 'grounded-in') "
        "AND n.kind IN ('Discussion', 'Observation', 'Benchmark', 'Proposal')",
        (concept_id,),
    ).fetchall()
    for (node_id,) in activity_nodes:
        ev_row = conn.execute(
            "SELECT target_id FROM edges WHERE kind = 'extracted-from' AND source_id = ? LIMIT 1",
            (node_id,),
        ).fetchone()
        if not ev_row:
            continue
        src_type = conn.execute(
            "SELECT json_extract(n.attrs, '$.source_type') FROM edges e "
            "JOIN nodes n ON e.target_id = n.id "
            "WHERE e.kind = 'sourced-from' AND e.source_id = ? AND n.kind = 'Source' LIMIT 1",
            (ev_row[0],),
        ).fetchone()
        if src_type and src_type[0] in _RESEARCH_SOURCE_TYPES:
            return True
    return False


def _strip_non_research_urls(conn, brief: dict) -> None:
    """Strip source_url from all brief items where the source is not research-type."""
    _url_cache: dict[str, bool] = {}

    def _is_research_url(url: str) -> bool:
        if url in _url_cache:
            return _url_cache[url]
        row = conn.execute(
            "SELECT json_extract(attrs, '$.source_type') FROM nodes "
            "WHERE kind = 'Source' AND json_extract(attrs, '$.url') = ? LIMIT 1",
            (url,),
        ).fetchone()
        result = bool(row and row[0] in _RESEARCH_SOURCE_TYPES)
        _url_cache[url] = result
        return result

    collections = (
        "problems", "vulnerabilities", "failure_modes", "invariants",
        "protocols", "profiles", "fixes", "observations", "discussions",
        "benchmarks", "timeline",
    )
    for key in collections:
        for item in brief.get(key, []):
            url = item.get("source_url")
            if url and not _is_research_url(url):
                item["source_url"] = None


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
    async def concepts_list(
        request: Request,
        kind: str | None = None,
        page: int = Query(1, ge=1),
        per_page: int = Query(50, ge=10, le=200),
    ):
        """List nodes with pagination (INV-KK-WEB-KIND-FILTER, INV-KK-WEB-PAGINATION)."""
        conn = request.app.state.conn
        offset = (page - 1) * per_page
        if kind:
            rows = conn.execute(
                "SELECT id, kind, attrs FROM nodes WHERE kind = ? ORDER BY kind, id LIMIT ? OFFSET ?",
                (kind, per_page + 1, offset),
            ).fetchall()
            title = kind
        else:
            rows = conn.execute(
                "SELECT id, kind, attrs FROM nodes ORDER BY kind, id LIMIT ? OFFSET ?",
                (per_page + 1, offset),
            ).fetchall()
            title = "Knowledge Base"
        has_next = len(rows) > per_page
        rows = rows[:per_page]
        nodes = _rows_to_dicts(rows)
        for n in nodes:
            n["display_name"] = display_name_for_node(n["kind"], n.get("attrs") or {}, n["id"])
        return templates.TemplateResponse(
            request,
            "concept_list.html",
            {
                "nodes": nodes,
                "title": title,
                "active_kind": kind,
                "all_kinds": _all_kinds(conn),
                "page": page,
                "per_page": per_page,
                "has_next": has_next,
            },
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

    @app.get("/subsystems", response_class=HTMLResponse)
    async def subsystems_list(
        request: Request,
        page: int = Query(1, ge=1),
        per_page: int = Query(50, ge=10, le=200),
    ):
        conn = request.app.state.conn
        offset = (page - 1) * per_page
        rows = conn.execute(
            "SELECT id, kind, attrs FROM nodes WHERE kind = 'Subsystem' ORDER BY id LIMIT ? OFFSET ?",
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
            {"nodes": nodes, "title": "Subsystems", "active_kind": "Subsystem", "all_kinds": _all_kinds(conn), "page": page, "per_page": per_page, "has_next": has_next},
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

    @app.get("/code-examples", response_class=HTMLResponse)
    async def code_examples_page(request: Request):
        """Browsable page of all code examples grouped by subsystem (ALG-KK-WEB-CODE-BROWSE)."""
        conn = request.app.state.conn
        rows = conn.execute(
            "SELECT id, kind, attrs FROM nodes "
            "WHERE kind = 'Concept' AND json_extract(attrs, '$.code_examples') IS NOT NULL "
            "ORDER BY json_extract(attrs, '$.name')"
        ).fetchall()
        concepts = _rows_to_dicts(rows)

        concept_ids = [c["id"] for c in concepts]
        subsystem_map: dict[str, str] = {}
        if concept_ids:
            placeholders = ",".join("?" for _ in concept_ids)
            sub_rows = conn.execute(
                f"SELECT e.source_id, json_extract(s.attrs, '$.name') as sub_name "
                f"FROM edges e "
                f"JOIN nodes s ON e.target_id = s.id AND s.kind = 'Subsystem' "
                f"WHERE e.kind = 'belongs-to' AND e.source_id IN ({placeholders})",
                tuple(concept_ids),
            ).fetchall()
            for sr in sub_rows:
                subsystem_map[sr["source_id"]] = sr["sub_name"]

        grouped: dict[str, list[dict]] = {}
        for c in concepts:
            sub_name = subsystem_map.get(c["id"], "Uncategorized")
            c["display_name"] = display_name_for_node(c["kind"], c.get("attrs") or {}, c["id"])
            grouped.setdefault(sub_name, []).append(c)

        sorted_groups = dict(sorted(grouped.items()))

        return templates.TemplateResponse(
            request,
            "code_examples.html",
            {"grouped_concepts": sorted_groups, "total_concepts": len(concepts)},
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
    @app.get("/research", response_class=HTMLResponse)
    async def research_explorer(
        request: Request,
        min_research: float = Query(0.0, ge=0),
        min_feasibility: float = Query(0.0, ge=0),
        window_days: int = Query(90, ge=1, le=365),
        sort_by: str = Query("latest_activity"),
        page: int = Query(1, ge=1),
        per_page: int = Query(20, ge=5, le=100),
    ):
        """Research explorer list (ALG-KK-WEB-RESEARCH-LIST).

        INV-KK-WEB-RESEARCH-RANKED: sorted by sort_by param desc.
        INV-KK-WEB-RESEARCH-FILTERED: min_research + min_feasibility filtering.
        """
        conn = request.app.state.conn
        if sort_by not in ("research", "feasibility", "impact", "frontier", "latest_activity"):
            sort_by = "latest_activity"

        concept_rows = conn.execute(
            "SELECT id, kind, attrs FROM nodes WHERE kind = 'Concept' ORDER BY id"
        ).fetchall()

        scored: list[dict] = []
        for row in _rows_to_dicts(concept_rows):
            cid = row["id"]
            attrs = row.get("attrs") or {}
            rs = research_score(conn, cid, window_days=window_days)
            fs = feasibility_score(conn, cid)
            ip = impact_projection(conn, cid)
            scores = compute_all_scores(conn, cid, window_days=window_days)
            if rs < min_research or fs < min_feasibility:
                continue
            if is_security_only_concept(conn, cid):
                continue
            if not _has_research_source(conn, cid):
                continue
            latest_date_row = conn.execute(
                "SELECT MAX(json_extract(n.attrs, '$.source_date')) "
                "FROM edges e JOIN nodes n ON e.source_id = n.id "
                "WHERE e.target_id = ? AND e.kind IN ('discusses', 'observes', 'benchmarks') "
                "AND n.kind IN ('Discussion', 'Observation', 'Benchmark')",
                (cid,),
            ).fetchone()
            latest_activity_date = (latest_date_row[0] or "") if latest_date_row else ""
            scored.append({
                "id": cid,
                "name": attrs.get("name", cid),
                "description": attrs.get("description", ""),
                "research_score": rs,
                "feasibility_score": fs,
                "impact": ip,
                "scores": scores,
                "latest_activity_date": latest_activity_date,
            })

        sort_key_map = {
            "research": lambda x: x["research_score"],
            "feasibility": lambda x: x["feasibility_score"],
            "impact": lambda x: x["impact"]["total_impact"],
            "frontier": lambda x: x["scores"].get("frontier", 0),
            "latest_activity": lambda x: x["latest_activity_date"],
        }
        scored.sort(key=sort_key_map[sort_by], reverse=True)

        offset = (page - 1) * per_page
        page_items = scored[offset:offset + per_page + 1]
        has_next = len(page_items) > per_page
        page_items = page_items[:per_page]

        for item in page_items:
            cid = item["id"]
            brief = build_concept_brief(conn, cid, window_days=window_days)
            motivations = classify_motivations(brief)
            item["motivations"] = motivations[:3]

            sub_row = conn.execute(
                "SELECT n.attrs FROM nodes n "
                "JOIN edges e ON e.target_id = n.id "
                "WHERE e.kind = 'belongs-to' AND e.source_id = ? AND n.kind = 'Subsystem' "
                "LIMIT 1",
                (cid,),
            ).fetchone()
            if sub_row:
                sub_attrs = json.loads(sub_row[0]) if isinstance(sub_row[0], str) else (sub_row[0] or {})
                item["subsystem"] = sub_attrs.get("name", "")
            else:
                item["subsystem"] = None

            mat_row = conn.execute(
                "SELECT attrs FROM edges WHERE kind = 'implemented-in' AND source_id = ? LIMIT 1",
                (cid,),
            ).fetchone()
            if mat_row:
                mat_attrs = json.loads(mat_row[0]) if isinstance(mat_row[0], str) else (mat_row[0] or {})
                item["maturity"] = mat_attrs.get("maturity")
            else:
                item["maturity"] = None

            source_urls = set()
            for ev in brief.get("timeline", []):
                url = ev.get("source_url", "")
                if url:
                    source_urls.add(url)
            item["evidence_diversity"] = len(source_urls)

            item["discussion_count"] = conn.execute(
                "SELECT COUNT(*) FROM edges e JOIN nodes n ON e.source_id = n.id "
                "WHERE e.kind = 'discusses' AND e.target_id = ? AND n.kind = 'Discussion'",
                (cid,),
            ).fetchone()[0]
            item["observation_count"] = conn.execute(
                "SELECT COUNT(*) FROM edges e JOIN nodes n ON e.source_id = n.id "
                "WHERE e.kind = 'observes' AND e.target_id = ? AND n.kind = 'Observation'",
                (cid,),
            ).fetchone()[0]
            item["benchmark_count"] = conn.execute(
                "SELECT COUNT(*) FROM edges e JOIN nodes n ON e.source_id = n.id "
                "WHERE e.kind = 'benchmarks' AND e.target_id = ? AND n.kind = 'Benchmark'",
                (cid,),
            ).fetchone()[0]

            proposal_count = conn.execute(
                "SELECT COUNT(*) FROM edges e JOIN nodes n ON e.source_id = n.id "
                "WHERE e.kind = 'grounded-in' AND e.target_id = ? AND n.kind = 'Proposal'",
                (cid,),
            ).fetchone()[0]
            item["proposal_count"] = proposal_count

        return templates.TemplateResponse(
            request,
            "research.html",
            {
                "concepts": page_items,
                "min_research": min_research,
                "min_feasibility": min_feasibility,
                "window_days": window_days,
                "sort_by": sort_by,
                "page": page,
                "per_page": per_page,
                "has_next": has_next,
            },
        )

    @app.get("/research/{concept_id}", response_class=HTMLResponse)
    async def research_detail(request: Request, concept_id: str):
        """Research brief for a single concept (ALG-KK-WEB-RESEARCH-DETAIL).

        INV-KK-WEB-RESEARCH-404-NON-CONCEPT: 404 for missing or non-Concept.
        INV-KK-WEB-RESEARCH-EVIDENCE-CHAIN: full evidence timeline with source links.
        INV-KK-WEB-RESEARCH-FEASIBILITY-VISIBLE: feasibility score rendered.
        INV-KK-WEB-RESEARCH-IMPACT-VISIBLE: impact projection rendered.
        """
        conn = request.app.state.conn
        row = conn.execute(
            "SELECT id, kind, attrs FROM nodes WHERE id = ?", (concept_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Concept not found")
        node = _rows_to_dicts([row])[0]
        if node["kind"] != "Concept":
            raise HTTPException(status_code=404, detail="Not a Concept node")
        attrs = node.get("attrs") or {}

        brief = build_concept_brief(conn, concept_id)
        _strip_non_research_urls(conn, brief)
        motivations = classify_motivations(brief)
        argument = build_argument_paragraph(attrs, [brief], motivations)
        rs = research_score(conn, concept_id)
        fs = feasibility_score(conn, concept_id)
        ip = impact_projection(conn, concept_id)
        scores = compute_all_scores(conn, concept_id)

        mat_row = conn.execute(
            "SELECT attrs FROM edges WHERE kind = 'implemented-in' AND source_id = ? LIMIT 1",
            (concept_id,),
        ).fetchone()
        if mat_row:
            mat_attrs = json.loads(mat_row[0]) if isinstance(mat_row[0], str) else (mat_row[0] or {})
            maturity = mat_attrs.get("maturity")
        else:
            maturity = None

        proposal_rows = conn.execute(
            "SELECT n.id, n.attrs FROM nodes n JOIN edges e ON e.source_id = n.id "
            "WHERE e.kind = 'grounded-in' AND e.target_id = ? AND n.kind = 'Proposal'",
            (concept_id,),
        ).fetchall()
        proposals = []
        for pr in proposal_rows:
            pa = json.loads(pr[1]) if isinstance(pr[1], str) else (pr[1] or {})
            problem_rows = conn.execute(
                "SELECT n.id, n.attrs FROM nodes n JOIN edges e ON e.source_id = n.id "
                "WHERE e.kind = 'addresses' AND e.target_id = ? AND n.kind = 'Problem'",
                (pr[0],),
            ).fetchall()
            problems = []
            for prb in problem_rows:
                prb_a = json.loads(prb[1]) if isinstance(prb[1], str) else (prb[1] or {})
                problems.append({"id": prb[0], "title": prb_a.get("title", prb[0])})
            source_url = None
            ev_row = conn.execute(
                "SELECT e.target_id FROM edges e "
                "WHERE e.kind = 'extracted-from' AND e.source_id = ? LIMIT 1",
                (pr[0],),
            ).fetchone()
            if ev_row:
                src_row = conn.execute(
                    "SELECT json_extract(n.attrs, '$.url') FROM nodes n "
                    "JOIN edges e ON e.target_id = n.id "
                    "WHERE e.kind = 'sourced-from' AND e.source_id = ? LIMIT 1",
                    (ev_row[0],),
                ).fetchone()
                if src_row:
                    source_url = src_row[0]
            proposals.append({
                "id": pr[0],
                "name": pa.get("name", pr[0]),
                "description": pa.get("description", ""),
                "status": pa.get("status"),
                "source_date": pa.get("source_date"),
                "source_url": source_url,
                "problems": problems,
            })

        source_urls = set()
        for ev in brief.get("timeline", []):
            url = ev.get("source_url", "")
            if url:
                source_urls.add(url)
        evidence_diversity = len(source_urls)

        sub_name = None
        sub_row = conn.execute(
            "SELECT n.id, n.attrs FROM nodes n "
            "JOIN edges e ON e.target_id = n.id "
            "WHERE e.kind = 'belongs-to' AND e.source_id = ? AND n.kind = 'Subsystem' LIMIT 1",
            (concept_id,),
        ).fetchone()
        if sub_row:
            sub_attrs = json.loads(sub_row[1]) if isinstance(sub_row[1], str) else (sub_row[1] or {})
            sub_name = sub_attrs.get("name", "")
            sub_id = sub_row[0]

            related_rows = conn.execute(
                "SELECT n.id, n.attrs FROM nodes n "
                "JOIN edges e ON e.source_id = n.id "
                "WHERE e.kind = 'belongs-to' AND e.target_id = ? AND n.kind = 'Concept' AND n.id != ? "
                "LIMIT 5",
                (sub_id, concept_id),
            ).fetchall()
            related_research = []
            for rr in related_rows:
                rr_attrs = json.loads(rr[1]) if isinstance(rr[1], str) else (rr[1] or {})
                rr_rs = research_score(conn, rr[0])
                if rr_rs > 0:
                    related_research.append({
                        "id": rr[0],
                        "name": rr_attrs.get("name", rr[0]),
                        "research_score": rr_rs,
                    })
        else:
            related_research = []

        _RESEARCH_TIMELINE_KINDS = ("Discussion", "Observation", "Benchmark", "Proposal", "Problem")
        all_evidence = [
            ev for ev in brief.get("timeline", [])
            if ev.get("kind") in _RESEARCH_TIMELINE_KINDS
        ]
        for ev in all_evidence:
            if ev.get("source_url"):
                src_check = conn.execute(
                    "SELECT json_extract(attrs, '$.source_type') FROM nodes "
                    "WHERE kind = 'Source' AND json_extract(attrs, '$.url') = ? LIMIT 1",
                    (ev["source_url"],),
                ).fetchone()
                if not src_check or src_check[0] not in _RESEARCH_SOURCE_TYPES:
                    ev["source_url"] = None
            if not ev.get("source_url") and ev.get("id"):
                ev_row = conn.execute(
                    "SELECT e.target_id FROM edges e "
                    "WHERE e.kind = 'extracted-from' AND e.source_id = ? LIMIT 1",
                    (ev["id"],),
                ).fetchone()
                if ev_row:
                    src_row = conn.execute(
                        "SELECT json_extract(n.attrs, '$.url'), json_extract(n.attrs, '$.source_type') "
                        "FROM nodes n JOIN edges e ON e.target_id = n.id "
                        "WHERE e.kind = 'sourced-from' AND e.source_id = ? AND n.kind = 'Source' LIMIT 1",
                        (ev_row[0],),
                    ).fetchone()
                    if src_row and src_row[0] and src_row[1] in _RESEARCH_SOURCE_TYPES:
                        ev["source_url"] = src_row[0]
        all_evidence.sort(key=lambda x: x.get("source_date") or "", reverse=True)

        discussion_count = conn.execute(
            "SELECT COUNT(*) FROM edges e JOIN nodes n ON e.source_id = n.id "
            "WHERE e.kind = 'discusses' AND e.target_id = ? AND n.kind = 'Discussion'",
            (concept_id,),
        ).fetchone()[0]
        observation_count = conn.execute(
            "SELECT COUNT(*) FROM edges e JOIN nodes n ON e.source_id = n.id "
            "WHERE e.kind = 'observes' AND e.target_id = ? AND n.kind = 'Observation'",
            (concept_id,),
        ).fetchone()[0]
        benchmark_count = conn.execute(
            "SELECT COUNT(*) FROM edges e JOIN nodes n ON e.source_id = n.id "
            "WHERE e.kind = 'benchmarks' AND e.target_id = ? AND n.kind = 'Benchmark'",
            (concept_id,),
        ).fetchone()[0]

        return templates.TemplateResponse(
            request,
            "research_detail.html",
            {
                "concept": node,
                "brief": brief,
                "motivations": motivations,
                "argument": argument,
                "research_score": rs,
                "feasibility_score": fs,
                "impact": ip,
                "maturity": maturity,
                "proposals": proposals,
                "evidence_diversity": evidence_diversity,
                "related_research": related_research,
                "all_evidence": all_evidence,
                "scores": scores,
                "sub_name": sub_name,
                "stale_cutoff": (date.today() - timedelta(days=180)).isoformat(),
                "discussion_count": discussion_count,
                "observation_count": observation_count,
                "benchmark_count": benchmark_count,
            },
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
            "concept_url": f"{_BASE_URL}/research/{cid}",
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
            "concept_url": f"{_BASE_URL}/research/{cid}",
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
            },
        )

    @app.get("/radar", response_class=HTMLResponse)
    async def radar(request: Request):
        """Research radar: papers grouped by subsystem then concept (ALG-KK-WEB-RADAR)."""
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

        from graph.briefing import classify_source_motivations

        by_concept: dict[str, dict] = {}
        for row in rows:
            s_attrs = json.loads(row[1]) if isinstance(row[1], str) else (row[1] or {})
            c_attrs = json.loads(row[3]) if isinstance(row[3], str) else (row[3] or {})
            cid = row[2]
            sid = row[0]
            pub_date = s_attrs.get("published_date", s_attrs.get("source_date", ""))

            if cid not in by_concept:
                subs = _get_concept_subsystems(conn, cid)
                by_concept[cid] = {
                    "concept_id": cid,
                    "concept_name": c_attrs.get("name", cid),
                    "subsystem": subs[0] if subs else "Uncategorized",
                    "motivations_set": set(),
                    "latest_date": "",
                    "papers": [],
                }

            entry = by_concept[cid]
            motivs = classify_source_motivations(conn, sid)
            entry["motivations_set"].update(motivs)

            if pub_date and pub_date > entry["latest_date"]:
                entry["latest_date"] = pub_date

            entry["papers"].append({
                "source_id": sid,
                "title": s_attrs.get("title", sid),
                "url": s_attrs.get("url", ""),
                "source_type": s_attrs.get("source_type", ""),
                "published_date": pub_date,
            })

        by_subsystem: dict[str, dict] = {}
        for c in by_concept.values():
            c["motivations"] = sorted(c.pop("motivations_set"))
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

    @app.get("/vulns", response_class=HTMLResponse)
    async def vulns_list(
        request: Request,
        page: int = Query(1, ge=1),
        per_page: int = Query(50, ge=10, le=200),
    ):
        """Vulnerability list (ALG-KK-WEB-VULNS-LIST).

        INV-KK-WEB-VULN-SEVERITY: sorted by cvss_score descending.
        """
        conn = request.app.state.conn
        rows = conn.execute(
            "SELECT id, kind, attrs FROM nodes WHERE kind = 'Vulnerability' ORDER BY id"
        ).fetchall()
        vulns: list[dict] = []
        for row in _rows_to_dicts(rows):
            attrs = row.get("attrs") or {}
            cvss = attrs.get("cvss_score", 0)
            if isinstance(cvss, str):
                try:
                    cvss = float(cvss)
                except ValueError:
                    cvss = 0
            severity = "low"
            if cvss >= 9.0:
                severity = "critical"
            elif cvss >= 7.0:
                severity = "high"
            elif cvss >= 4.0:
                severity = "medium"
            prop = vulnerability_propagation(conn, row["id"])
            impact_count = len(prop["direct"])
            for v in prop["propagated"].values():
                impact_count += len(v.get("dependents", []))
                impact_count += len(v.get("composed_with", []))
                impact_count += len(v.get("shared_invariant", []))
            source_url = None
            ev_row = conn.execute(
                "SELECT target_id FROM edges WHERE kind = 'extracted-from' AND source_id = ? LIMIT 1",
                (row["id"],),
            ).fetchone()
            if ev_row:
                src_row = conn.execute(
                    "SELECT json_extract(n.attrs, '$.url') FROM edges e "
                    "JOIN nodes n ON e.target_id = n.id "
                    "WHERE e.kind = 'sourced-from' AND e.source_id = ? AND n.kind = 'Source' LIMIT 1",
                    (ev_row[0],),
                ).fetchone()
                if src_row and src_row[0]:
                    source_url = src_row[0]
            vulns.append({
                "id": row["id"],
                "cve_id": attrs.get("cve_id", row["id"]),
                "title": attrs.get("title", attrs.get("cve_id", row["id"])),
                "cvss_score": cvss,
                "severity": severity,
                "impact_count": impact_count,
                "description": attrs.get("description", ""),
                "source_url": source_url,
            })
        vulns.sort(key=lambda x: x["cvss_score"], reverse=True)
        offset = (page - 1) * per_page
        page_vulns = vulns[offset:offset + per_page + 1]
        has_next = len(page_vulns) > per_page
        page_vulns = page_vulns[:per_page]
        return templates.TemplateResponse(
            request, "vulns.html",
            {"vulns": page_vulns, "page": page, "per_page": per_page, "has_next": has_next},
        )

    @app.get("/vulns/{vuln_id}", response_class=HTMLResponse)
    async def vuln_detail(request: Request, vuln_id: str):
        """Vulnerability research brief (ALG-KK-WEB-VULNS-DETAIL).

        INV-KK-WEB-VULN-PROPAGATION: propagated concepts with coupling context.
        INV-KK-WEB-VULN-BRIEF-DEPTH: full graph depth per exploited concept.
        """
        conn = request.app.state.conn
        row = conn.execute(
            "SELECT id, kind, attrs FROM nodes WHERE id = ?", (vuln_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Vulnerability not found")
        node = _rows_to_dicts([row])[0]
        if node["kind"] != "Vulnerability":
            raise HTTPException(status_code=404, detail="Not a vulnerability node")
        attrs = node.get("attrs") or {}
        cvss = attrs.get("cvss_score", 0)
        if isinstance(cvss, str):
            try:
                cvss = float(cvss)
            except ValueError:
                cvss = 0
        severity = "low"
        if cvss >= 9.0:
            severity = "critical"
        elif cvss >= 7.0:
            severity = "high"
        elif cvss >= 4.0:
            severity = "medium"

        prop = vulnerability_propagation(conn, vuln_id)

        direct_briefs = []
        for cid in prop["direct"]:
            brief = build_concept_brief(conn, cid)
            brief["motivations"] = classify_motivations(brief)
            direct_briefs.append(brief)

        propagated_details: list[dict] = []
        seen_ids: set[str] = set(prop["direct"])
        for cid, coupling in prop["propagated"].items():
            for group_key in ("dependents", "composed_with", "shared_invariant"):
                for pid in coupling.get(group_key, []):
                    if pid in seen_ids:
                        continue
                    seen_ids.add(pid)
                    cn = get_node(conn, pid)
                    if not cn:
                        continue
                    cn_attrs = cn.get("attrs") or {}
                    sub_row = conn.execute(
                        "SELECT json_extract(n.attrs, '$.name') FROM edges e "
                        "JOIN nodes n ON e.target_id = n.id "
                        "WHERE e.kind = 'belongs-to' AND e.source_id = ? AND n.kind = 'Subsystem'",
                        (pid,),
                    ).fetchone()
                    propagated_details.append({
                        "id": pid,
                        "name": cn_attrs.get("name", pid),
                        "description": cn_attrs.get("description", ""),
                        "subsystem": sub_row[0] if sub_row else None,
                        "coupling_type": group_key,
                        "coupled_to": cid,
                    })

        coupling_labels = {
            "dependents": "Prerequisite dependency",
            "composed_with": "Protocol composition",
            "shared_invariant": "Shared invariant governance",
        }

        fix_rows = conn.execute(
            "SELECT n.id, n.attrs FROM nodes n "
            "JOIN edges e ON e.source_id = n.id "
            "WHERE e.kind = 'fixes' AND e.target_id = ? AND n.kind = 'Fix'",
            (vuln_id,),
        ).fetchall()
        fixes = []
        for fr in fix_rows:
            fa = json.loads(fr[1]) if isinstance(fr[1], str) else (fr[1] or {})
            fixes.append({
                "id": fr[0],
                "title": fa.get("title", fr[0]),
                "commit_hash": fa.get("commit_hash", ""),
                "fix_type": fa.get("fix_type", ""),
                "source_date": fa.get("source_date", ""),
            })

        affected_subsystems: list[dict] = []
        seen_subs: set[str] = set()
        for b in direct_briefs:
            if b["subsystem"] and b["subsystem"]["id"] not in seen_subs:
                seen_subs.add(b["subsystem"]["id"])
                affected_subsystems.append(b["subsystem"])
        for pd in propagated_details:
            if pd["subsystem"] and pd["subsystem"] not in [s["name"] for s in affected_subsystems]:
                affected_subsystems.append({"id": None, "name": pd["subsystem"]})

        source_url = None
        ev_row = conn.execute(
            "SELECT target_id FROM edges WHERE kind = 'extracted-from' AND source_id = ? LIMIT 1",
            (vuln_id,),
        ).fetchone()
        if ev_row:
            src_row = conn.execute(
                "SELECT json_extract(n.attrs, '$.url') FROM edges e "
                "JOIN nodes n ON e.target_id = n.id "
                "WHERE e.kind = 'sourced-from' AND e.source_id = ? AND n.kind = 'Source' LIMIT 1",
                (ev_row[0],),
            ).fetchone()
            if src_row and src_row[0]:
                source_url = src_row[0]

        return templates.TemplateResponse(
            request, "vuln_detail.html",
            {
                "node": node,
                "cvss_score": cvss,
                "severity": severity,
                "source_url": source_url,
                "direct_briefs": direct_briefs,
                "propagated_details": propagated_details,
                "coupling_labels": coupling_labels,
                "fixes": fixes,
                "affected_subsystems": affected_subsystems,
            },
        )

    @app.get("/api/vuln-impact/{vuln_id}")
    async def api_vuln_impact(request: Request, vuln_id: str):
        """JSON vulnerability propagation (ALG-KK-WEB-API-VULN-IMPACT).

        INV-KK-WEB-API-VULN-JSON: returns {direct, propagated}.
        """
        conn = request.app.state.conn
        row = conn.execute(
            "SELECT id, kind FROM nodes WHERE id = ?", (vuln_id,)
        ).fetchone()
        if row is None or row["kind"] != "Vulnerability":
            return JSONResponse({"error": "Vulnerability not found"}, status_code=404)
        return JSONResponse(vulnerability_propagation(conn, vuln_id))

    @app.get("/viz", response_class=HTMLResponse)
    async def viz(request: Request):
        return templates.TemplateResponse(request, "graph_viz.html", {})
