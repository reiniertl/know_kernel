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
    heat_score,
    impact_projection,
    is_security_only_concept,
    pain_score,
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
    async def research_feed(request: Request):
        """Daily research feed grouped by publication date."""
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
            "ORDER BY json_extract(s.attrs, '$.published_date') DESC, s.id"
        ).fetchall()

        by_date: dict[str, list] = {}
        for row in rows:
            s_attrs = json.loads(row[1]) if isinstance(row[1], str) else (row[1] or {})
            c_attrs = json.loads(row[3]) if isinstance(row[3], str) else (row[3] or {})
            pub_date = s_attrs.get("published_date", s_attrs.get("source_date", "unknown"))
            if not pub_date:
                pub_date = "unknown"
            entry = {
                "source_id": row[0],
                "title": s_attrs.get("title", row[0]),
                "url": s_attrs.get("url", ""),
                "source_type": s_attrs.get("source_type", ""),
                "concept_id": row[2],
                "concept_name": c_attrs.get("name", row[2]),
            }
            by_date.setdefault(pub_date, []).append(entry)

        return templates.TemplateResponse(
            request,
            "feed.html",
            {"by_date": by_date, "total": sum(len(v) for v in by_date.values())},
        )

    _TYPE_EMOJI = {
        "preprint": "\U0001f4dd",
        "conference-paper": "\U0001f3db️",
        "conference-proceedings": "\U0001f3a4",
        "paper": "\U0001f4d6",
    }

    def _build_card_text(date_str: str, items: list[dict]) -> str:
        lines = [f"\U0001f4e1 *Kernel Research — {date_str}*"]
        lines.append(f"\U0001f4ca {len(items)} publication{'s' if len(items) != 1 else ''}\n")
        for item in items:
            emoji = _TYPE_EMOJI.get(item["source_type"], "\U0001f4c4")
            lines.append(f"{emoji} *{item['concept']}*")
            if item.get("url"):
                lines.append(f"   \U0001f517 {item['url']}")
        lines.append(f"\n\U0001f50d Browse: /research")
        return "\n".join(lines)

    @app.get("/api/feed/card/{date_str}")
    async def feed_card_json(request: Request, date_str: str):
        """JSON card for a single day's research feed."""
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
            "AND json_extract(s.attrs, '$.published_date') = ? "
            "ORDER BY s.id",
            (date_str,),
        ).fetchall()

        items = []
        for row in rows:
            s_attrs = json.loads(row[1]) if isinstance(row[1], str) else (row[1] or {})
            c_attrs = json.loads(row[3]) if isinstance(row[3], str) else (row[3] or {})
            items.append({
                "title": s_attrs.get("title", row[0]),
                "url": s_attrs.get("url", ""),
                "source_type": s_attrs.get("source_type", ""),
                "concept": c_attrs.get("name", row[2]),
            })

        card_text = _build_card_text(date_str, items)
        return JSONResponse({
            "date": date_str,
            "count": len(items),
            "card": card_text,
            "items": items,
        })

    @app.post("/api/feed/send/{date_str}")
    async def feed_send_card(request: Request, date_str: str):
        """Execute CLI command with card text replacing <CARD> placeholder."""
        import subprocess

        body = await request.json()
        cli_template = body.get("cli_command", "")
        if not cli_template or "<CARD>" not in cli_template:
            return JSONResponse({"error": "CLI command must contain <CARD> placeholder"}, status_code=400)

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
            "AND json_extract(s.attrs, '$.published_date') = ? "
            "ORDER BY s.id",
            (date_str,),
        ).fetchall()

        items = []
        for row in rows:
            s_attrs = json.loads(row[1]) if isinstance(row[1], str) else (row[1] or {})
            c_attrs = json.loads(row[3]) if isinstance(row[3], str) else (row[3] or {})
            items.append({
                "title": s_attrs.get("title", row[0]),
                "url": s_attrs.get("url", ""),
                "source_type": s_attrs.get("source_type", ""),
                "concept": c_attrs.get("name", row[2]),
            })

        card_text = _build_card_text(date_str, items)
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

    @app.get("/radar", response_class=HTMLResponse)
    async def radar(request: Request):
        """Subsystem radar dashboard (ALG-KK-WEB-RADAR).

        INV-KK-WEB-RADAR-SUBSYSTEM: shows all subsystems with >= 1 concept.
        """
        conn = request.app.state.conn
        sub_rows = conn.execute(
            "SELECT id, kind, attrs FROM nodes WHERE kind = 'Subsystem' ORDER BY id"
        ).fetchall()

        subsystems: list[dict] = []
        for sr in _rows_to_dicts(sub_rows):
            sub_id = sr["id"]
            attrs = sr.get("attrs") or {}
            concept_rows = conn.execute(
                "SELECT e.source_id FROM edges e "
                "JOIN nodes n ON e.source_id = n.id AND n.kind = 'Concept' "
                "WHERE e.kind = 'belongs-to' AND e.target_id = ?",
                (sub_id,),
            ).fetchall()
            concept_ids = [r[0] for r in concept_rows]
            if not concept_ids:
                continue
            total_heat = 0.0
            total_pain = 0.0
            for cid in concept_ids:
                total_heat += heat_score(conn, cid)
                total_pain += pain_score(conn, cid)
            vuln_count = 0
            fix_count = 0
            for cid in concept_ids:
                vuln_count += conn.execute(
                    "SELECT COUNT(*) FROM edges WHERE kind = 'exploits' AND target_id = ?",
                    (cid,),
                ).fetchone()[0]
                fix_count += conn.execute(
                    "SELECT COUNT(*) FROM edges e "
                    "JOIN nodes n ON e.source_id = n.id AND n.kind = 'Fix' "
                    "WHERE e.kind = 'patches' AND e.target_id = ?",
                    (cid,),
                ).fetchone()[0]
            subsystems.append({
                "id": sub_id,
                "name": attrs.get("name", sub_id),
                "concept_count": len(concept_ids),
                "heat": total_heat,
                "pain": total_pain,
                "vuln_count": vuln_count,
                "fix_count": fix_count,
            })
        subsystems.sort(key=lambda x: x["pain"], reverse=True)
        return templates.TemplateResponse(
            request, "radar.html", {"subsystems": subsystems},
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
