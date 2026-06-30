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
    get_node,
    list_nodes,
    match_scenarios,
    ranked_recommendations,
    transitive_impact,
)
from graph.briefing import build_concept_brief
from graph.scoring import compute_all_scores, heat_score, pain_score, vulnerability_propagation


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

    @app.get("/ideas", response_class=HTMLResponse)
    async def ideas_list(
        request: Request,
        min_score: float = Query(0.0, ge=0),
        window_days: int = Query(90, ge=1, le=365),
        page: int = Query(1, ge=1),
        per_page: int = Query(20, ge=5, le=100),
    ):
        """Ranked idea feed (ALG-KK-WEB-IDEAS-LIST).

        INV-KK-WEB-IDEAS-RANKED: sorted by frontier_score desc.
        INV-KK-WEB-IDEAS-FILTER: min_score + window_days filtering.
        """
        conn = request.app.state.conn

        opp_rows = conn.execute(
            "SELECT id, kind, attrs FROM nodes WHERE kind = 'Opportunity' ORDER BY id"
        ).fetchall()
        trend_rows = conn.execute(
            "SELECT id, kind, attrs FROM nodes WHERE kind = 'Trend' ORDER BY id"
        ).fetchall()

        ideas: list[dict] = []
        for row in _rows_to_dicts(opp_rows):
            attrs = row.get("attrs") or {}
            fs = attrs.get("frontier_score", 0)
            if isinstance(fs, str):
                try:
                    fs = float(fs)
                except ValueError:
                    fs = 0
            if fs < min_score:
                continue
            concept_id = None
            concept_name = None
            opp_edge = conn.execute(
                "SELECT target_id FROM edges WHERE kind = 'opportunity-for' AND source_id = ?",
                (row["id"],),
            ).fetchone()
            if opp_edge:
                concept_id = opp_edge[0]
                cn = get_node(conn, concept_id)
                if cn:
                    concept_name = (cn["attrs"] or {}).get("name", concept_id)
            ev_count = conn.execute(
                "SELECT COUNT(*) FROM edges WHERE kind = 'supported-by' AND source_id = ?",
                (row["id"],),
            ).fetchone()[0]
            scores = compute_all_scores(conn, concept_id, window_days=window_days) if concept_id else {}
            ideas.append({
                "id": row["id"],
                "type": "opportunity",
                "title": attrs.get("title", row["id"]),
                "frontier_score": fs,
                "confidence": attrs.get("confidence"),
                "concept_id": concept_id,
                "concept_name": concept_name,
                "evidence_count": ev_count,
                "scores": scores,
            })

        for row in _rows_to_dicts(trend_rows):
            attrs = row.get("attrs") or {}
            concept_id = None
            concept_name = None
            trend_edge = conn.execute(
                "SELECT target_id FROM edges WHERE kind = 'trend-about' AND source_id = ?",
                (row["id"],),
            ).fetchone()
            if trend_edge:
                concept_id = trend_edge[0]
                cn = get_node(conn, concept_id)
                if cn:
                    concept_name = (cn["attrs"] or {}).get("name", concept_id)
            scores = compute_all_scores(conn, concept_id, window_days=window_days) if concept_id else {}
            fs = scores.get("frontier", 0)
            if fs < min_score:
                continue
            ideas.append({
                "id": row["id"],
                "type": "trend",
                "title": attrs.get("title", row["id"]),
                "frontier_score": fs,
                "confidence": None,
                "concept_id": concept_id,
                "concept_name": concept_name,
                "strength": attrs.get("strength"),
                "window_start": attrs.get("window_start"),
                "window_end": attrs.get("window_end"),
                "scores": scores,
            })

        ideas.sort(key=lambda x: x["frontier_score"], reverse=True)

        offset = (page - 1) * per_page
        page_ideas = ideas[offset:offset + per_page + 1]
        has_next = len(page_ideas) > per_page
        page_ideas = page_ideas[:per_page]

        return templates.TemplateResponse(
            request,
            "ideas.html",
            {
                "ideas": page_ideas,
                "min_score": min_score,
                "window_days": window_days,
                "page": page,
                "per_page": per_page,
                "has_next": has_next,
            },
        )

    @app.get("/ideas/{idea_id}", response_class=HTMLResponse)
    async def idea_detail(request: Request, idea_id: str):
        """Idea research brief (ALG-KK-WEB-IDEAS-DETAIL).

        INV-KK-WEB-IDEAS-EVIDENCE-CHAIN: verbatim evidence, date-ordered.
        INV-KK-WEB-IDEA-BRIEF-VERBATIM: evidence text unmodified.
        INV-KK-WEB-IDEA-BRIEF-DEPTH: full graph depth per concept.
        """
        conn = request.app.state.conn
        row = conn.execute(
            "SELECT id, kind, attrs FROM nodes WHERE id = ?", (idea_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Idea not found")
        node = _rows_to_dicts([row])[0]
        if node["kind"] not in ("Opportunity", "Trend"):
            raise HTTPException(status_code=404, detail="Not an idea node")

        if node["kind"] == "Opportunity":
            edge_kind = "opportunity-for"
        else:
            edge_kind = "trend-about"
        concept_edges = conn.execute(
            "SELECT target_id FROM edges WHERE kind = ? AND source_id = ?",
            (edge_kind, idea_id),
        ).fetchall()
        concept_ids = [e[0] for e in concept_edges]

        briefs = []
        for cid in concept_ids:
            brief = build_concept_brief(conn, cid)
            briefs.append(brief)

        all_evidence: list[dict] = []
        seen_evidence_ids: set[str] = set()
        for b in briefs:
            for ev in b["timeline"]:
                if ev["id"] not in seen_evidence_ids:
                    seen_evidence_ids.add(ev["id"])
                    all_evidence.append(ev)
        all_evidence.sort(key=lambda x: x.get("source_date") or "", reverse=True)

        total_vulns = sum(len(b["vulnerabilities"]) for b in briefs)
        total_problems = sum(len(b["problems"]) for b in briefs)
        total_dependents = sum(len(b["prerequisites"]["depended_on_by"]) for b in briefs)
        critical_vulns = sum(
            1 for b in briefs for v in b["vulnerabilities"]
            if v.get("severity") == "critical"
        )
        high_vulns = sum(
            1 for b in briefs for v in b["vulnerabilities"]
            if v.get("severity") == "high"
        )

        related_ideas: list[dict] = []
        for cid in concept_ids:
            rel_rows = conn.execute(
                "SELECT n.id, n.kind, n.attrs FROM nodes n "
                "JOIN edges e ON e.source_id = n.id "
                "WHERE (e.kind = 'opportunity-for' OR e.kind = 'trend-about') "
                "AND e.target_id = ? AND n.id != ?",
                (cid, idea_id),
            ).fetchall()
            for rr in _rows_to_dicts(rel_rows):
                if not any(ri["id"] == rr["id"] for ri in related_ideas):
                    related_ideas.append(rr)

        return templates.TemplateResponse(
            request,
            "idea_detail.html",
            {
                "node": node,
                "briefs": briefs,
                "all_evidence": all_evidence,
                "total_vulns": total_vulns,
                "total_problems": total_problems,
                "total_dependents": total_dependents,
                "critical_vulns": critical_vulns,
                "high_vulns": high_vulns,
                "related_ideas": related_ideas,
            },
        )

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
            top_idea = None
            for cid in concept_ids:
                opp_rows = conn.execute(
                    "SELECT n.id, n.attrs FROM nodes n "
                    "JOIN edges e ON e.source_id = n.id "
                    "WHERE e.kind = 'opportunity-for' AND e.target_id = ? AND n.kind = 'Opportunity'",
                    (cid,),
                ).fetchall()
                for orow in opp_rows:
                    oattrs = json.loads(orow[1]) if isinstance(orow[1], str) else (orow[1] or {})
                    fs = oattrs.get("frontier_score", 0)
                    if isinstance(fs, str):
                        try:
                            fs = float(fs)
                        except ValueError:
                            fs = 0
                    if top_idea is None or fs > top_idea["frontier_score"]:
                        top_idea = {"id": orow[0], "title": oattrs.get("title", orow[0]), "frontier_score": fs}
            subsystems.append({
                "id": sub_id,
                "name": attrs.get("name", sub_id),
                "concept_count": len(concept_ids),
                "heat": total_heat,
                "pain": total_pain,
                "vuln_count": vuln_count,
                "fix_count": fix_count,
                "top_idea": top_idea,
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
            vulns.append({
                "id": row["id"],
                "cve_id": attrs.get("cve_id", row["id"]),
                "title": attrs.get("title", attrs.get("cve_id", row["id"])),
                "cvss_score": cvss,
                "severity": severity,
                "impact_count": impact_count,
                "description": attrs.get("description", ""),
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

        return templates.TemplateResponse(
            request, "vuln_detail.html",
            {
                "node": node,
                "cvss_score": cvss,
                "severity": severity,
                "direct_briefs": direct_briefs,
                "propagated_details": propagated_details,
                "coupling_labels": coupling_labels,
                "fixes": fixes,
                "affected_subsystems": affected_subsystems,
            },
        )

    @app.get("/api/ideas")
    async def api_ideas_json(
        request: Request,
        min_score: float = Query(0.0, ge=0),
        window_days: int = Query(90, ge=1, le=365),
    ):
        """JSON idea feed (ALG-KK-WEB-API-IDEAS-JSON).

        INV-KK-WEB-API-IDEAS-JSON: each entry has id, type, title, frontier_score.
        """
        conn = request.app.state.conn
        opp_rows = conn.execute(
            "SELECT id, kind, attrs FROM nodes WHERE kind = 'Opportunity' ORDER BY id"
        ).fetchall()
        trend_rows = conn.execute(
            "SELECT id, kind, attrs FROM nodes WHERE kind = 'Trend' ORDER BY id"
        ).fetchall()
        ideas: list[dict] = []
        for row in _rows_to_dicts(opp_rows):
            attrs = row.get("attrs") or {}
            fs = attrs.get("frontier_score", 0)
            if isinstance(fs, str):
                try:
                    fs = float(fs)
                except ValueError:
                    fs = 0
            if fs < min_score:
                continue
            concept_id = None
            concept_name = None
            opp_edge = conn.execute(
                "SELECT target_id FROM edges WHERE kind = 'opportunity-for' AND source_id = ?",
                (row["id"],),
            ).fetchone()
            if opp_edge:
                concept_id = opp_edge[0]
                cn = get_node(conn, concept_id)
                if cn:
                    concept_name = (cn["attrs"] or {}).get("name", concept_id)
            ev_count = conn.execute(
                "SELECT COUNT(*) FROM edges WHERE kind = 'supported-by' AND source_id = ?",
                (row["id"],),
            ).fetchone()[0]
            ideas.append({
                "id": row["id"],
                "type": "opportunity",
                "title": attrs.get("title", row["id"]),
                "frontier_score": fs,
                "confidence": attrs.get("confidence"),
                "concept_id": concept_id,
                "concept_name": concept_name,
                "evidence_count": ev_count,
            })
        for row in _rows_to_dicts(trend_rows):
            attrs = row.get("attrs") or {}
            concept_id = None
            concept_name = None
            trend_edge = conn.execute(
                "SELECT target_id FROM edges WHERE kind = 'trend-about' AND source_id = ?",
                (row["id"],),
            ).fetchone()
            if trend_edge:
                concept_id = trend_edge[0]
                cn = get_node(conn, concept_id)
                if cn:
                    concept_name = (cn["attrs"] or {}).get("name", concept_id)
            scores = compute_all_scores(conn, concept_id, window_days=window_days) if concept_id else {}
            fs = scores.get("frontier", 0)
            if fs < min_score:
                continue
            ideas.append({
                "id": row["id"],
                "type": "trend",
                "title": attrs.get("title", row["id"]),
                "frontier_score": fs,
                "confidence": None,
                "concept_id": concept_id,
                "concept_name": concept_name,
                "evidence_count": 0,
            })
        ideas.sort(key=lambda x: x["frontier_score"], reverse=True)
        return JSONResponse(ideas)

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
