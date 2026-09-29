"""Route handlers for the human-facing web API (ALG-KK-WEB-SERVE).

INV-KK-WEB-FULL-ACCESS: all node kinds are served without filtering.
INV-KK-WEB-MUTATION-ALLOWLISTED: state-changing endpoints are confined to the
prefixes in WEB_MUTATION_ALLOWLIST below.

This docstring used to carry a read-only invariant claiming that only GET
endpoints were registered here. That stopped being true when the review
endpoints landed and was never retired; eight mutating endpoints live in this
file today. It was never a node in the spec graph either. The real constraint on
mutation is INV-KK-WEB-MUTATION-ALLOWLISTED, which IS a node, is enforced
structurally by the tuple below, and is tested. The retired id is deliberately
not spelled out here — test_every_spec_id_cited_in_src_web_exists_in_the_dag
treats any spec id written in this directory as a live citation.
"""

from __future__ import annotations

import json
import os

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from graph.diagnostics import diagnose_graph
from graph.engine import (
    compare_neighborhoods,
    list_nodes,
    match_scenarios,
    ranked_recommendations,
    transitive_impact,
)
from graph.briefing import build_concept_brief
from graph.rules import concept_weight, not_superseded
from graph.scoring import research_score


# INV-KK-WEB-MUTATION-ALLOWLISTED: this tuple IS the structural enforcement.
# Every POST/PUT/DELETE route registered in setup_routes must have a path
# starting with one of these prefixes. Admitting a new mutating endpoint means
# adding its prefix here — the invariant itself does not move.
# IFC-KK-PAPER-COMPLETENESS, in the order the interface declares them. Label and
# one line of plain English per dimension, so the page explains what it shows
# rather than printing six raw attribute names.
# The canonical paper vocabulary as a SQL tuple literal, shared by every list
# view. Hoisted from inside the research-list route on 2026-09-18 when the intake
# view needed it: a third copy of the literal would have worked directly against
# INV-KK-PAPER-SOURCE-TYPE-VOCABULARY, which exists because three modules
# previously carried their own and two disagreed.
_RESEARCH_TYPES = "('preprint','conference-paper','conference-proceedings')"

COMPLETENESS_DIMENSION_LABELS = (
    ("has_abstract", "Abstract", "The paper's abstract is stored."),
    ("has_summary", "Summary", "A usable summary exists, model-written or human."),
    ("links_concept", "Concepts", "At least one Concept was extracted from this paper."),
    ("links_subsystem", "Subsystem", "An extracted Concept belongs to a kernel subsystem."),
    ("links_kernel", "Kernel", "An extracted Concept is implemented in a named kernel."),
    ("title_verified", "Title checked",
     ("The title was checked against the document its identifier resolves to, and "
      "the authority answered. It does NOT mean the record is about what it says: "
      "nothing here attests that, and only a person reading the record could.")),
    ("links_invariant", "Kernel invariant",
     ("A kernel invariant was extracted from this paper. Recorded only \u2014 it never "
      "gates anything, and today no paper in the corpus has one.")),
    ("links_confirmed", "Links confirmed",
     ("A person read every concept link on this paper and agreed with it. False "
      "when the paper has no links at all, so it never reads complete by having "
      "nothing to check. It gates nothing, and today it is true of no paper.")),
)

# INV-KK-WEB-SUMMARY-STATE-AUTHORITY: the states a human may set through the web.
# "llm-extracted" is deliberately absent — only the extractor writes it.
WEB_WRITABLE_SUMMARY_STATES = ("human-authored", "human-reviewed", "rejected")

WEB_MUTATION_ALLOWLIST = (
    "/api/review/",
    "/api/reviewers",
    "/api/abstract/",
    "/api/venue/",  # covers both the single-Source edit and the merge
    "/api/summary/",
    "/api/feed/send/",  # side-effecting shell-out, not a graph write
    "/api/link-confirm/",
    "/api/concept-admit/",   # promote a queued candidate into the vocabulary
    "/api/concept-dismiss/",  # drop a queued name that is not a concept
    "/api/concept/",          # edit an existing Concept — the review mechanism
    "/api/concept-retire/",   # a state flip, never a delete
    "/api/concept-merge/",    # collapse a duplicate; the evidence moves
    "/api/concept-retire-bulk",  # one signed act over several ids
    "/api/concept-subsystem/",   # the taxonomy edge the harvest declined to guess
    "/api/concept-distinct/",    # two colliding names are different things
)


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


#: Which page renders which kind (INV-KK-WEB-SEARCH-RESULT-ROUTED). Only
#: Source has a page of its own; every other kind is rendered by the per-kind
#: node view at /concepts/{id} (ALG-KK-WEB-NODE-DETAIL).
_ROUTE_FOR_KIND = {
    "Source": "/paper/",
}
_DEFAULT_ROUTE = "/concepts/"


def route_for_node(kind: str, node_id: str) -> str:
    """The page that renders this node (INV-KK-WEB-SEARCH-RESULT-ROUTED).

    TOTAL, like display_name_for_node beside it: a kind absent from the table
    gets the node view rather than a broken link or none. That totality is the
    point — the search box has to return something clickable for every kind
    the graph holds, and a KeyError here would be a blank result row.

    Resolution lives on the server so no template can reintroduce the defect
    this replaced: search_results.html hardcoded /concepts/{id} for every row,
    so a paper linked to a page of raw edges instead of to /paper/{id}.
    """
    return _ROUTE_FOR_KIND.get(kind, _DEFAULT_ROUTE) + node_id


#: Papers behind a concept, in the order the admission rule counts them.
#: INV-KK-CONCEPT-ADMISSION walks concept -extracted-from-> Evidence
#: -sourced-from-> Source, so this is the same traversal concept_weight makes.
#: DISTINCT on the Source: two Evidence nodes from one paper are one paper, and
#: rendering it twice would overstate the evidence the badge is claiming.
_CONCEPT_PAPERS_SQL = (
    "SELECT DISTINCT s.id, s.attrs FROM edges e "
    "JOIN edges se ON se.source_id = e.target_id AND se.kind = 'sourced-from' "
    "JOIN nodes s ON s.id = se.target_id AND s.kind = 'Source' "
    "WHERE e.kind = 'extracted-from' AND e.source_id = ? "
    # A RETIRED LINK IS NOT EVIDENCE AND MUST NOT BE LISTED HERE. This page is
    # the evidence for the badge concept_weight computes, so the two share
    # graph.rules.not_superseded rather than each carrying the clause.
    + not_superseded("e") + " "
    "ORDER BY s.id LIMIT ? OFFSET ?"
)


def _concept_papers(conn, concept_id: str, limit: int, offset: int = 0) -> list[dict]:
    """One bounded page of the papers behind a concept.

    ALG-KK-WEB-CONCEPT-PAPERS. Every row routes through route_for_node, so a
    paper row goes to /paper/{id} and never back into /concepts/{id}
    (INV-KK-WEB-SEARCH-RESULT-ROUTED). LIMIT is always passed by the caller;
    there is no unbounded overload, because Scheduling Classes carries 440
    papers and a default of "all" would be an unbounded render waiting to be
    used by accident.
    """
    rows = conn.execute(_CONCEPT_PAPERS_SQL, (concept_id, limit, offset)).fetchall()
    papers = []
    for source_id, raw in rows:
        attrs = json.loads(raw) if isinstance(raw, str) else (raw or {})
        papers.append({
            "source_id": source_id,
            "title": attrs.get("title") or source_id,
            "venue": attrs.get("venue") or "",
            "source_type": attrs.get("source_type") or "",
            "url": attrs.get("url") or "",
            "route": route_for_node("Source", source_id),
        })
    return papers



def _concept_subsystem(conn, concept_id: str) -> str:
    """The subsystem a concept belongs-to, or "" — one query, one row."""
    row = conn.execute(
        "SELECT json_extract(n.attrs, '$.name') FROM edges e "
        "JOIN nodes n ON n.id = e.target_id AND n.kind = 'Subsystem' "
        "WHERE e.kind = 'belongs-to' AND e.source_id = ? LIMIT 1",
        (concept_id,),
    ).fetchone()
    return (row[0] if row else "") or ""


def _concept_kernels(conn, concept_id: str) -> list[str]:
    """The kernels a concept is implemented-in.

    This is the signal that will let the vocabulary escape the Linux monopoly:
    a concept present in two unrelated kernels is established by a different
    argument than one present in 440 Linux papers. 94 implemented-in edges
    exist over 65 concepts as of 2026-09-22, 25 of them in two or more kernels.
    """
    return [
        r[0] for r in conn.execute(
            "SELECT json_extract(n.attrs, '$.name') FROM edges e "
            "JOIN nodes n ON n.id = e.target_id AND n.kind = 'Kernel' "
            "WHERE e.kind = 'implemented-in' AND e.source_id = ? ORDER BY 1",
            (concept_id,),
        ).fetchall() if r[0]
    ]

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

    #: How many papers the concept detail page shows before linking out.
    #: Small deliberately: the detail page is about the concept, and the full
    #: list has its own paginated route.
    CONCEPT_PAPERS_PREVIEW = 5

    @app.get("/concepts", response_class=HTMLResponse)
    async def concepts_list(
        request: Request,
        state: str | None = None,
        curation: str | None = None,
        q: str | None = None,
        page: int = Query(1, ge=1),
        per_page: int = Query(50, ge=10, le=200),
    ):
        """The vocabulary, paginated (ALG-KK-WEB-CONCEPTS-LIST).

        THIS ROUTE IS THE REASON A CONCEPT CAN EXIST AT ALL. The extractor stopped
        minting on 2026-09-22 (INV-KK-EXTRACT-CONCEPT-MATCHED) and store_rich_concept
        became unreachable, so until this page and its admission path shipped the
        vocabulary was frozen at 97 with no way in but hand-written SQL.

        INV-KK-WEB-QUERY-BOUNDED: LIMIT per_page + 1 to detect a next page without a
        second COUNT, the seminal set read ONCE for the whole page, and enrichment
        strictly per row. check_concept_admission is deliberately NOT called here —
        it sweeps every Concept, which is the unbounded per-render cost this
        invariant exists to forbid. graph.rules.admission_state classifies one row,
        and the sweep tallies that same function, so page and invariant cannot drift.
        """
        from graph.concept_vocabulary import (
            CURATION_STATES,
            DEFAULT_CURATION_STATE,
            colliding_pairs,
            curation_progress,
            curation_state as read_curation_state,
        )
        from graph.rules import admission_state, seminal_concepts

        conn = request.app.state.conn
        sql = "SELECT id, attrs FROM nodes WHERE kind = 'Concept'"
        params: list = []
        if q:
            sql += " AND lower(json_extract(attrs, '$.name')) LIKE ?"
            params.append(f"%{q.lower()}%")

        # THE CURATION FILTER IS A WHERE CLAUSE AND THE ADMISSION FILTER BELOW
        # IS NOT, and the difference is the whole point. Admission state is
        # COMPUTED per row and is not a column, so ?state= can only narrow the
        # rows already fetched. curation_state IS a stored attribute, so
        # ?curation= filters the whole corpus and returns rows from beyond the
        # first page. A review queue that inherited the admission filter's
        # limitation would show a curator 50 of 3,000 harvested concepts and
        # call it the backlog.
        #
        # ABSENT COUNTS AS 'harvested', matching concept_vocabulary.
        # curation_state: absent asserts the same thing — nobody has reviewed
        # this — and it is true of all 97 Concepts that predate the field. A
        # queue that showed empty while 97 unreviewed concepts sat in the
        # corpus would be wrong in the most misleading direction.
        if curation in CURATION_STATES:
            if curation == DEFAULT_CURATION_STATE:
                sql += (" AND COALESCE(json_extract(attrs, '$.curation_state'), '')"
                        " IN ('', ?)")
            else:
                sql += " AND json_extract(attrs, '$.curation_state') = ?"
            params.append(curation)

        sql += " ORDER BY json_extract(attrs, '$.name') LIMIT ? OFFSET ?"
        params.extend([per_page + 1, (page - 1) * per_page])

        rows = conn.execute(sql, params).fetchall()
        has_next = len(rows) > per_page
        rows = rows[:per_page]

        # Both read ONCE for the whole page, never once per row —
        # INV-KK-WEB-QUERY-BOUNDED.
        seminal = seminal_concepts(conn)
        # The PAIRS and not just the flag, from 2026-09-28. The badge could say
        # "name collides" and not what it collided WITH, so the only merge
        # affordance the page could offer was a text field — and a curator
        # retyping "NUMA Topology and Memory Policy" will mistype it. ONE sweep
        # still, per INV-KK-WEB-QUERY-BOUNDED; the map is built from its result.
        collides_with: dict[str, list[str]] = {}
        for id_a, id_b in colliding_pairs(conn):
            collides_with.setdefault(id_a, []).append(id_b)
            collides_with.setdefault(id_b, []).append(id_a)
        # Names for the counterparts in ONE query, not one per counterpart:
        # a counterpart may sit on any page, so it cannot come from `rows`.
        counterpart_names = dict(conn.execute(
            "SELECT id, json_extract(attrs, '$.name') FROM nodes "
            "WHERE kind = 'Concept'").fetchall()) if collides_with else {}
        concepts = []
        for concept_id, raw in rows:
            attrs = json.loads(raw) if isinstance(raw, str) else (raw or {})
            concepts.append({
                "id": concept_id,
                "name": attrs.get("name") or concept_id,
                "description": attrs.get("description") or "",
                "subsystem": _concept_subsystem(conn, concept_id),
                "papers": concept_weight(conn, concept_id),
                "kernels": _concept_kernels(conn, concept_id),
                "state": admission_state(conn, concept_id, seminal),
                "curation": read_curation_state(attrs),
                "collides": concept_id in collides_with,
                "collides_with": [
                    {"id": other, "name": counterpart_names.get(other) or other}
                    for other in collides_with.get(concept_id, [])
                ],
            })

        # Filtering AFTER classification is deliberate and is a known limit: the
        # state is not a column, so it cannot be a WHERE clause without either
        # denormalising it or running the corpus sweep. The filter therefore
        # narrows the current page rather than the corpus, and the template says
        # so, because a filter that silently lied about completeness would be
        # worse than no filter.
        if state:
            concepts = [c for c in concepts if c["state"] == state]

        # IFC-KK-CONCEPT-REVIEW-PRIORITY: collisions first, then paper count
        # descending, then name. A collision is rare, actionable and it
        # COMPOUNDS — an unmerged duplicate splits all future evidence between
        # two entries forever — while a wrong description on a concept 440
        # papers point at misleads the most readers. Applied after the state
        # filter so the order is the order of what is shown.
        concepts.sort(key=lambda c: (not c["collides"], -c["papers"], c["name"]))

        # IFC-KK-CONCEPT-REVIEW-PRIORITY, 2026-09-29. The sort key answers "which
        # item next" and nothing about "how much is left", and the backlog is
        # 465. ONE O(1) GROUP BY, which is why it does not breach
        # INV-KK-WEB-QUERY-BOUNDED — that predicate bounds enrichment calls PER
        # ROW and this does not grow with per_page. Over the CORPUS and never the
        # page: a page count would read "50 harvested" forever.
        progress = curation_progress(conn)

        return templates.TemplateResponse(
            request, "concepts_list.html",
            {
                "concepts": concepts,
                "progress": progress,
                "state_filter": state or "",
                "curation_filter": curation or "",
                "curation_states": list(CURATION_STATES),
                "q": q or "",
                "page": page,
                "per_page": per_page,
                "has_next": has_next,
                "candidate_count": conn.execute(
                    "SELECT COUNT(DISTINCT normalised) FROM concept_candidates"
                ).fetchone()[0],
            },
        )

    @app.get("/concepts/candidates", response_class=HTMLResponse)
    async def concept_candidates_page(
        request: Request,
        page: int = Query(1, ge=1),
        per_page: int = Query(50, ge=10, le=200),
    ):
        """The admission queue (ALG-KK-WEB-CONCEPT-ADMIT, read half).

        Names the extractor proposed that the vocabulary did not contain,
        ordered by how many DISTINCT Sources reached for them independently —
        candidate_ranking's order, which is the same weight test
        INV-KK-CONCEPT-ADMISSION applies to an admitted Concept, asked before
        the node exists.

        Registered BEFORE /concepts/{node_id}: "candidates" is a literal path
        segment and would otherwise be read as a node id and 404.
        """
        from graph.concept_vocabulary import candidate_ranking
        from graph.rules import ADMISSIBLE_WEIGHT

        conn = request.app.state.conn
        ranked = candidate_ranking(conn, limit=per_page + 1)
        has_next = len(ranked) > per_page
        ranked = ranked[:per_page]

        candidates = []
        for cand in ranked:
            # The papers that proposed it: the curator needs them to name a
            # seminal Source, and at weight 1 there is exactly one to choose.
            proposing = conn.execute(
                "SELECT DISTINCT s.id, json_extract(s.attrs, '$.title') "
                "FROM concept_candidates c "
                "JOIN edges se ON se.source_id = c.evidence_id AND se.kind = 'sourced-from' "
                "JOIN nodes s ON s.id = se.target_id AND s.kind = 'Source' "
                "WHERE c.normalised = ? LIMIT 10",
                (cand.normalised,),
            ).fetchall()
            candidates.append({
                "normalised": cand.normalised,
                "name": cand.name,
                "sources": cand.sources,
                "needs_marker": cand.sources < ADMISSIBLE_WEIGHT,
                "papers": [{"id": r[0], "title": r[1] or r[0],
                            "route": route_for_node("Source", r[0])}
                           for r in proposing],
            })

        return templates.TemplateResponse(
            request, "concept_candidates.html",
            {
                "candidates": candidates,
                "threshold": ADMISSIBLE_WEIGHT,
                "subsystems": [
                    {"id": r[0], "name": r[1]} for r in conn.execute(
                        "SELECT id, json_extract(attrs, '$.name') FROM nodes "
                        "WHERE kind = 'Subsystem' ORDER BY 2").fetchall() if r[1]
                ],
                "page": page,
                "per_page": per_page,
                "has_next": has_next,
            },
        )

    @app.post("/api/concept-admit/{normalised:path}")
    async def api_concept_admit(request: Request, normalised: str):
        """A human promotes a queued candidate into the vocabulary.

        ALG-KK-WEB-CONCEPT-ADMIT. THE ONLY WRITER OF A Concept once the
        extractor stopped minting, and the first writer of a defined-by edge in
        this corpus.

        INV-KK-WEB-MUTATION-ALLOWLISTED: /api/concept-admit/ is on
        WEB_MUTATION_ALLOWLIST.
        INV-KK-REVIEW-ATTRIBUTION-FROM-SESSION: the admitting curator is the
        logged-in user. An admitted_by field in the body is ignored, so no
        request can file an admission under someone else's name.
        INV-KK-WEB-ADMIT-HONOURS-ADMISSION: the store refuses a below-threshold
        promotion with no seminal marker. This route does not re-check the rule
        — one implementation, in promote_candidate, which is testable without a
        router.
        """
        from graph.concept_vocabulary import promote_candidate

        identity = getattr(request.state, "user", None)
        if identity is None:
            # Defensive: the gate never lets an anonymous request this far.
            return JSONResponse({"error": "Not authenticated"}, status_code=401)

        conn = request.app.state.conn
        try:
            body = await request.json()
        except Exception:
            body = {}

        try:
            concept_id = promote_candidate(
                conn, normalised,
                attrs={
                    "name": (body.get("name") or "").strip(),
                    "description": (body.get("description") or "").strip(),
                    "artifact_class": (body.get("artifact_class") or "").strip(),
                    "key_properties": body.get("key_properties") or [],
                    "tradeoffs": body.get("tradeoffs") or [],
                    "design_rationale": (body.get("design_rationale") or "").strip(),
                },
                admitted_by=identity["reviewer"],
                seminal_source_id=(body.get("seminal_source_id") or "").strip(),
                subsystem_id=(body.get("subsystem_id") or "").strip(),
            )
        except ValueError as exc:
            status = 404 if "No candidate queued" in str(exc) else 422
            return JSONResponse({"error": str(exc)}, status_code=status)

        conn.commit()
        return JSONResponse({
            "concept_id": concept_id,
            "normalised": normalised,
            "admitted_by": identity["reviewer"],
        })

    @app.put("/api/concept/{concept_id}")
    async def api_concept_edit(request: Request, concept_id: str):
        """A human edits a Concept — the review mechanism (ALG-KK-WEB-CONCEPT-EDIT).

        NOTHING HAS EVER BEEN ABLE TO DO THIS. Every other curated surface in
        this file has an edit route; the vocabulary did not, and after
        ALG-KK-DOC-HARVEST most Concepts are machine-written, which makes this
        the difference between a curated vocabulary and an unedited dump.

        EDITING IS REVIEWING. The six attributes and curation_state /
        reviewed_by / reviewed_at are written in ONE operation, because a human
        who fixed a description has read it and a second button would guarantee
        the state is wrong for everyone who forgets.

        INV-KK-REVIEW-ATTRIBUTION-FROM-SESSION: the editor is
        request.state.user["reviewer"]. A reviewed_by in the body is IGNORED,
        not rejected, matching api_concept_admit — so no request can file a
        review under someone else's name.
        INV-KK-WEB-MUTATION-ALLOWLISTED: /api/concept/ is on the allowlist.

        The completeness rule is NOT re-checked here — one implementation, in
        update_concept, testable without a router.
        """
        from graph.concept_vocabulary import update_concept

        identity = getattr(request.state, "user", None)
        if identity is None:
            # Defensive: the gate never lets an anonymous request this far.
            return JSONResponse({"error": "Not authenticated"}, status_code=401)

        conn = request.app.state.conn
        try:
            body = await request.json()
        except Exception:
            body = {}

        try:
            update_concept(
                conn, concept_id,
                attrs={
                    "name": body.get("name"),
                    "description": body.get("description"),
                    "artifact_class": body.get("artifact_class"),
                    "key_properties": body.get("key_properties"),
                    "tradeoffs": body.get("tradeoffs"),
                    "design_rationale": body.get("design_rationale"),
                },
                reviewed_by=identity["reviewer"],
            )
        except ValueError as exc:
            status = 404 if str(exc).startswith("No Concept") else 422
            return JSONResponse({"error": str(exc)}, status_code=status)

        conn.commit()
        return JSONResponse({
            "concept_id": concept_id,
            "curation_state": "reviewed",
            "reviewed_by": identity["reviewer"],
        })

    @app.post("/api/concept-retire/{concept_id}")
    async def api_concept_retire(request: Request, concept_id: str):
        """A human judges a Concept wrong (ALG-KK-WEB-CONCEPT-RETIRE).

        A STATE FLIP AND NEVER A DELETE. Every edge is kept: papers may already
        link to it, and deleting the node destroys links that are not this
        decision's to destroy. The Concept then vanishes from the vocabulary the
        extractor is shown (INV-KK-VOCABULARY-EXCLUDES-RETIRED) and is
        admissible under no route (INV-KK-CONCEPT-ADMISSION).

        SEPARATE FROM THE EDIT ROUTE BECAUSE IT IS A DIFFERENT CLAIM. An edit
        says "this is right, here is the correction"; a retirement says "this
        should not be in the vocabulary at all". A seventh field on the edit
        form would make the most consequential action the easiest to take by
        accident. Un-retiring is the edit route, which returns it to 'reviewed'.
        """
        from graph.concept_vocabulary import retire_concept

        identity = getattr(request.state, "user", None)
        if identity is None:
            return JSONResponse({"error": "Not authenticated"}, status_code=401)

        conn = request.app.state.conn
        try:
            retire_concept(conn, concept_id, reviewed_by=identity["reviewer"])
        except ValueError as exc:
            status = 404 if str(exc).startswith("No Concept") else 422
            return JSONResponse({"error": str(exc)}, status_code=status)

        conn.commit()
        return JSONResponse({
            "concept_id": concept_id,
            "curation_state": "retired",
            "reviewed_by": identity["reviewer"],
        })

    @app.post("/api/concept-retire-bulk")
    async def api_concept_retire_bulk(request: Request):
        """Retire several Concepts in one signed act
        (ALG-KK-WEB-CONCEPT-RETIRE-BULK).

        INV-KK-WEB-MUTATION-ALLOWLISTED: /api/concept-retire-bulk is allowlisted.
        INV-KK-REVIEW-ATTRIBUTION-FROM-SESSION: every retirement is signed from
        the gate-resolved identity; a reviewer field in the body is ignored.

        ALL OR NOTHING, AND THE REFUSALS COME BACK NAMED. A partial bulk retire
        is worse than none — a caller reading a success cannot tell which half
        happened — so a single refused id refuses the call and the response says
        which id and why. 422 rather than 404 even for an unknown id, because the
        request as a whole is what was rejected.
        """
        from graph.concept_vocabulary import retire_concepts_bulk
        import dataclasses

        identity = getattr(request.state, "user", None)
        if identity is None:
            return JSONResponse({"error": "Not authenticated"}, status_code=401)

        conn = request.app.state.conn
        try:
            body = await request.json()
        except Exception:
            body = {}
        ids = body.get("ids")
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            return JSONResponse(
                {"error": "Body must carry an 'ids' list of concept ids"},
                status_code=422)

        try:
            result = retire_concepts_bulk(
                conn, ids, reviewed_by=identity["reviewer"])
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)

        if not result.ok:
            return JSONResponse(dataclasses.asdict(result), status_code=422)
        conn.commit()
        return JSONResponse(dataclasses.asdict(result))

    @app.post("/api/concept-subsystem/{concept_id}/{subsystem_id}")
    async def api_concept_subsystem(
        request: Request, concept_id: str, subsystem_id: str
    ):
        """Give a Concept the subsystem the harvest declined to guess
        (ALG-KK-WEB-CONCEPT-SUBSYSTEM).

        INV-KK-WEB-MUTATION-ALLOWLISTED: /api/concept-subsystem/ is allowlisted.
        INV-KK-REVIEW-ATTRIBUTION-FROM-SESSION: an anonymous caller is refused.

        A SEPARATE ROUTE AND NOT A SEVENTH FIELD ON THE EDIT FORM. The edit route
        writes six attributes and has never touched an edge; teaching it to would
        make every save re-assert a belongs-to, and a save that changes nothing
        already means "reviewed". Assigning a subsystem is a different claim from
        correcting a description.

        IT DOES NOT MARK THE CONCEPT REVIEWED, deliberately. Classifying is not
        reading: a curator who files XArray under Data Structures has not
        necessarily checked its description, and a review state that overcounts
        is the mirror of the undercount ALG-KK-WEB-CONCEPT-EDIT was built to
        avoid.
        """
        from graph.concept_vocabulary import assign_subsystem

        identity = getattr(request.state, "user", None)
        if identity is None:
            return JSONResponse({"error": "Not authenticated"}, status_code=401)

        conn = request.app.state.conn
        try:
            assign_subsystem(conn, concept_id, subsystem_id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)

        conn.commit()
        return JSONResponse({
            "concept_id": concept_id, "subsystem_id": subsystem_id,
        })

    @app.post("/api/concept-distinct/{concept_a}/{concept_b}")
    async def api_concept_distinct(request: Request, concept_a: str, concept_b: str):
        """Record that two colliding names are different things
        (ALG-KK-WEB-CONCEPT-DISTINCT).

        INV-KK-WEB-MUTATION-ALLOWLISTED: /api/concept-distinct/ is allowlisted.
        INV-KK-REVIEW-ATTRIBUTION-FROM-SESSION: an anonymous caller is refused.

        THE DECISION THIS RECORDS IS THE ONE THAT PREVENTS THE UNRECOVERABLE
        ERROR. Every one of these pairs would have been a WRONG merge, and a
        wrong merge is the single mistake in this vocabulary nothing ever finds
        again — the evidence of the merged-away concept is now attached to the
        survivor and no later reader can tell. Huge Pages against Transparent
        Huge Pages is hugetlbfs against THP; Folio against Folio Marks is a page
        against its flags; Mutex against Mutex Waiters Tree is a lock against a
        field inside it.

        IT DOES NOT MARK EITHER CONCEPT REVIEWED, for the reason the subsystem
        route does not: deciding two names are different is not the same as
        having read and approved either entry.
        """
        from graph.concept_vocabulary import record_distinct

        identity = getattr(request.state, "user", None)
        if identity is None:
            return JSONResponse({"error": "Not authenticated"}, status_code=401)

        conn = request.app.state.conn
        try:
            written = record_distinct(conn, concept_a, concept_b)
        except ValueError as exc:
            status = 404 if str(exc).startswith("No Concept") else 422
            return JSONResponse({"error": str(exc)}, status_code=status)

        conn.commit()
        return JSONResponse({
            "concept_a": concept_a, "concept_b": concept_b, "written": written,
        })

    @app.post("/api/concept-merge/{loser_id}/{winner_id}")
    async def api_concept_merge(request: Request, loser_id: str, winner_id: str):
        """A human collapses one Concept into another (ALG-KK-WEB-CONCEPT-MERGE).

        THE VERB THE REVIEW SURFACE WAS MISSING. Editing corrects a Concept and
        retiring withdraws one; neither resolves a duplicate, because retiring
        the smaller of a pair leaves its papers attached to an entry no page
        will ever surface again. Measured 2026-09-28, twenty of the 25 colliding
        pairs carry papers on BOTH sides.

        INV-KK-WEB-MUTATION-ALLOWLISTED: /api/concept-merge/ is on
        WEB_MUTATION_ALLOWLIST.

        INV-KK-REVIEW-ATTRIBUTION-FROM-SESSION: reviewed_by comes from the
        gate-resolved identity. This route reads no body at all, so a reviewer
        field cannot even be offered.

        AUTHENTICATED AND NOT ADMIN, AND THE VENUE PRECEDENT IS DELIBERATELY NOT
        FOLLOWED. Operator decision 2026-09-28. INV-KK-VENUE-MUTATION-AUTHORISED
        gates POST /api/venue/merge on admin because one call repoints up to 897
        Sources. A concept merge moves at most ~72 papers plus inbound edges and
        it sits INSIDE the review queue: IFC-KK-CONCEPT-REVIEW-PRIORITY sorts
        collisions to page one precisely so a curator resolves them, and an admin
        gate would make page one's whole signal unactionable by the person it was
        built for. It matches /api/concept/ and /api/concept-retire/, which is
        the surface it belongs to. The blast-radius principle is honoured by
        measuring the radius, not by copying the answer.

        The loser comes FIRST in the path because that is the order the sentence
        reads on the page — merge this into that — and mixing them up is the one
        mistake a curator cannot undo from the UI.
        """
        from graph.concept_vocabulary import merge_concepts
        import dataclasses

        identity = getattr(request.state, "user", None)
        if identity is None:
            return JSONResponse({"error": "Not authenticated"}, status_code=401)

        conn = request.app.state.conn
        try:
            result = merge_concepts(
                conn, loser_id, winner_id, reviewed_by=identity["reviewer"])
        except ValueError as exc:
            status = 404 if str(exc).startswith("No Concept") else 422
            return JSONResponse({"error": str(exc)}, status_code=status)

        conn.commit()
        return JSONResponse(dataclasses.asdict(result))

    @app.post("/api/concept-dismiss/{normalised:path}")
    async def api_concept_dismiss(request: Request, normalised: str):
        """Drop a queued name a curator judged not to be a Concept.

        INV-KK-WEB-MUTATION-ALLOWLISTED: /api/concept-dismiss/ is allowlisted.
        Not a graph write — the candidate never became a node — and deliberately
        not a tombstone: the extractor re-queues the name if another paper
        proposes it, and permanent suppression would hide a concept that later
        earns admission on new evidence.
        """
        from graph.concept_vocabulary import dismiss_candidate

        identity = getattr(request.state, "user", None)
        if identity is None:
            return JSONResponse({"error": "Not authenticated"}, status_code=401)

        conn = request.app.state.conn
        removed = dismiss_candidate(conn, normalised)
        if not removed:
            return JSONResponse({"error": f"No candidate queued under '{normalised}'"},
                                status_code=404)
        conn.commit()
        return JSONResponse({"normalised": normalised, "rows_removed": removed})

    @app.get("/concepts/{concept_id}/papers", response_class=HTMLResponse)
    async def concept_papers(
        request: Request,
        concept_id: str,
        page: int = Query(1, ge=1),
        per_page: int = Query(50, ge=10, le=200),
    ):
        """Every paper behind one concept (ALG-KK-WEB-CONCEPT-PAPERS).

        The same traversal concept_weight walks, so this page is the evidence for
        the admission badge rather than a restatement of it — a reader who
        distrusts the number can count the rows.

        A DEDICATED ROUTE, not an inline section: Scheduling Classes has 440
        papers and Linux Security Modules 358, and rendering those inside the
        detail page is the unbounded render INV-KK-WEB-QUERY-BOUNDED forbids.
        Same page/per_page bounds as the list, so one mechanism serves both.
        """
        from graph.rules import admission_state, seminal_concepts

        conn = request.app.state.conn
        row = conn.execute(
            "SELECT attrs FROM nodes WHERE id = ? AND kind = 'Concept'", (concept_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Concept not found")
        attrs = json.loads(row[0]) if isinstance(row[0], str) else (row[0] or {})

        papers = _concept_papers(conn, concept_id, per_page + 1, (page - 1) * per_page)
        has_next = len(papers) > per_page
        papers = papers[:per_page]

        return templates.TemplateResponse(
            request, "concept_papers.html",
            {
                "concept_id": concept_id,
                "concept_name": attrs.get("name") or concept_id,
                "papers": papers,
                "total": concept_weight(conn, concept_id),
                "state": admission_state(conn, concept_id, seminal_concepts(conn)),
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
        if node["kind"] == "Source":
            # ALG-KK-WEB-NODE-DETAIL: a paper has a page of its own. Redirecting
            # HERE rather than fixing each caller fixes every entry point at
            # once — health.html, impact.html, feed.html, radar.html,
            # link_review.html and this view's own neighbour links all send ids
            # to this route, and a Source arriving at a raw edge dump was the
            # whole complaint. Existing links keep working and start going
            # somewhere useful.
            return RedirectResponse(route_for_node("Source", node["id"]), status_code=302)
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

        # The papers behind a Concept, bounded to a preview with a link to the
        # full paginated route (ALG-KK-WEB-CONCEPT-PAPERS). Only for Concepts:
        # this view renders every node kind, and the traversal is meaningless
        # for the rest.
        concept_papers_preview: list[dict] = []
        concept_paper_total = 0
        concept_state = ""
        concept_collides_with: list[dict] = []
        if node["kind"] == "Concept":
            from graph.concept_vocabulary import colliding_pairs
            from graph.rules import admission_state, seminal_concepts
            concept_papers_preview = _concept_papers(
                conn, node_id, CONCEPT_PAPERS_PREVIEW)
            concept_paper_total = concept_weight(conn, node_id)
            concept_state = admission_state(conn, node_id, seminal_concepts(conn))
            # THE MERGE AFFORDANCE NAMES THE COUNTERPART AND NEVER ASKS FOR A
            # TYPED NAME (ALG-KK-WEB-CONCEPT-MERGE). A curator retyping "NUMA
            # Topology and Memory Policy" will mistype it, and a mistyped merge
            # is a 404 at best and the wrong merge at worst. Both directions are
            # offered because which of a pair is the winner is the curator's
            # judgement and not the queue's — the 72-paper entry is usually
            # right, and "Huge Pages" against "Transparent Huge Pages" is not a
            # merge at all.
            for id_a, id_b in colliding_pairs(conn):
                other = (id_b if id_a == node_id
                         else id_a if id_b == node_id else None)
                if other is None:
                    continue
                row = conn.execute(
                    "SELECT json_extract(attrs, '$.name'), "
                    "json_extract(attrs, '$.curation_state') FROM nodes "
                    "WHERE id = ?", (other,)).fetchone()
                if row is None or row[1] == "retired":
                    # A counterpart already retired or merged away is not a
                    # merge a curator should be offered twice.
                    continue
                concept_collides_with.append({
                    "id": other, "name": row[0] or other,
                    "papers": concept_weight(conn, other)})

        subsystems: list[dict] = []
        if node["kind"] == "Concept":
            # ALG-KK-WEB-CONCEPT-SUBSYSTEM. The 22 Subsystems, offered as a
            # choice — this route may not create one, so the select IS the
            # complete set of valid answers.
            subsystems = [
                {"id": r[0], "name": r[1] or r[0]}
                for r in conn.execute(
                    "SELECT id, json_extract(attrs, '$.name') FROM nodes "
                    "WHERE kind = 'Subsystem' ORDER BY 2").fetchall()
            ]

        return templates.TemplateResponse(
            request,
            "concept_detail.html",
            {
                "node": node,
                "subsystems": subsystems,
                "edges": edges,
                "grouped_edges": grouped_edges,
                "node_labels": node_labels,
                "related_code": related_code,
                "concept_papers": concept_papers_preview,
                "concept_paper_total": concept_paper_total,
                "concept_state": concept_state,
                "concept_collides_with": concept_collides_with,
                "papers_preview_size": CONCEPT_PAPERS_PREVIEW,
            },
        )

    @app.get("/venues", response_class=HTMLResponse)
    async def venues(request: Request):
        """Papers grouped by venue (ALG-KK-WEB-VENUES).

        Replaces the retired /sources listing. Groups on the Venue node reached
        by the published-at edge, never on the raw Source.attrs.venue string:
        the raw values carry edition collisions, so OSDI 2026 / OSDI 2025 / OSDI
        would otherwise render as three entries instead of one
        (INV-KK-VENUE-NORMALISED).

        INV-KK-WEB-QUERY-BOUNDED: exactly three queries regardless of corpus
        size — one join for the Source/Venue pairs, one for the venue-less
        remainder, one batched review-status lookup. No per-paper enrichment
        inside the grouping loop, which is where /feed goes wrong.
        """
        conn = request.app.state.conn

        # 1. Sources joined to their Venue.
        rows = conn.execute(
            "SELECT v.id, json_extract(v.attrs, '$.name'), "
            "json_extract(v.attrs, '$.venue_type'), s.id, s.attrs "
            "FROM nodes v "
            "JOIN edges e ON e.kind = 'published-at' AND e.target_id = v.id "
            "JOIN nodes s ON s.id = e.source_id AND s.kind = 'Source' "
            "WHERE v.kind = 'Venue'"
        ).fetchall()

        # 2. Sources with no venue at all. Explicitly surfaced, never dropped —
        # this page's job is coverage of the corpus.
        orphan_rows = conn.execute(
            "SELECT s.id, s.attrs FROM nodes s "
            "WHERE s.kind = 'Source' AND s.id NOT IN "
            "(SELECT source_id FROM edges WHERE kind = 'published-at')"
        ).fetchall()

        # 3. Review badges for everything on the page, in one IN(...) query.
        all_sids = [r[3] for r in rows] + [r[0] for r in orphan_rows]
        review_status = _batch_review_status(conn, all_sids)

        def _paper(sid: str, attrs_raw) -> dict:
            a = json.loads(attrs_raw) if isinstance(attrs_raw, str) else (attrs_raw or {})
            return {
                "source_id": sid,
                "title": a.get("title", sid),
                "url": a.get("url", ""),
                "source_type": a.get("source_type", ""),
                "published_date": a.get("published_date", a.get("source_date", "")),
                "review": review_status.get(sid),
            }

        by_venue: dict[str, dict] = {}
        for venue_id, name, venue_type, sid, s_attrs in rows:
            entry = by_venue.get(venue_id)
            if entry is None:
                entry = by_venue[venue_id] = {
                    "venue_id": venue_id,
                    "name": name or venue_id,
                    "venue_type": venue_type or "other",
                    "papers": [],
                }
            entry["papers"].append(_paper(sid, s_attrs))

        venue_list = list(by_venue.values())
        for v in venue_list:
            v["paper_count"] = len(v["papers"])
            v["papers"].sort(key=lambda p: p["published_date"] or "", reverse=True)
        venue_list.sort(key=lambda v: (-v["paper_count"], v["name"]))

        unattributed = [_paper(sid, a) for sid, a in orphan_rows]
        unattributed.sort(key=lambda p: p["published_date"] or "", reverse=True)

        total_papers = sum(v["paper_count"] for v in venue_list) + len(unattributed)
        return templates.TemplateResponse(
            request,
            "venues.html",
            {
                "venues": venue_list,
                "unattributed": unattributed,
                "total_papers": total_papers,
            },
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
        # Kind PRIORITY, not kind name. "ORDER BY kind" is alphabetical and
        # Source is 21st of 26, while Evidence — 3,566 nodes carrying the full
        # paper text, which the attrs LIKE above matches against — is 5th. A
        # topical query therefore filled all 30 rows with Evidence bodies and
        # never reached the paper the reader was looking for.
        #
        # INV-KK-WEB-SEARCH-FULL-ACCESS is NOT weakened by this: no kind is
        # excluded, no WHERE clause is added, and the 30-row cap remains the
        # only thing that removes a match. Ordering decides which matches fall
        # off the far side of that cap, which is what ordering does.
        # INV-KK-WEB-QUERY-BOUNDED is satisfied because the ordering is in SQL
        # — no row is fetched or enriched beyond the cap.
        sql += (
            " ORDER BY CASE kind"
            "   WHEN 'Source' THEN 0"
            "   WHEN 'Concept' THEN 1"
            "   WHEN 'Evidence' THEN 8"
            "   ELSE 4 END,"
            " kind, id LIMIT 30"
        )
        rows = conn.execute(sql, params).fetchall()
        results = _rows_to_dicts(rows)
        for r in results:
            r["display_name"] = display_name_for_node(
                r["kind"], r.get("attrs") or {}, r["id"]
            )
            r["url"] = route_for_node(r["kind"], r["id"])
        if request.headers.get("HX-Request"):
            return templates.TemplateResponse(
                request, "search_results.html", {"results": results}
            )
        return JSONResponse(
            [{"id": r["id"], "kind": r["kind"], "attrs": r["attrs"],
              "display_name": r["display_name"], "url": r["url"]} for r in results]
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
                "concept_description": _truncate_words(first_desc, 100),
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

    # INV-KK-FEED-CARD-LINK-ABSOLUTE. The card is read on another machine —
    # POST /api/feed/send hands it to an external consumer — so a loopback
    # address would resolve to the reader's own host. Which host serves this
    # application is a deployment fact, not a property of the link, so the
    # base is configured rather than written into the specification. The
    # default is the address that was hardcoded here before 2026-09-18, so no
    # running deployment changes behaviour.
    _BASE_URL = os.environ.get(
        "KK_BASE_URL", "http://10.123.102.166:8000").rstrip("/")

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
        concept_description = item.get("concept_description", "")
        if concept_description:
            lines.append(f"   _{concept_description}_")
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
            "concept_description": _truncate_words(c_attrs.get("description", ""), 100),
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
            "concept_description": _truncate_words(c_attrs.get("description", ""), 100),
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
        # Shared by the concept query below. It used to be computed inside the
        # removed brief block, which is why deleting that block broke this.
        placeholders = ",".join("?" for _ in evidence_ids)

        concepts = []
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

        # IFC-KK-PAPER-SUMMARY and IFC-KK-PAPER-COMPLETENESS: one query each,
        # outside every loop, so the cost does not move with concept count.
        summary_row = conn.execute(
            "SELECT n.attrs FROM edges e JOIN nodes n ON n.id = e.source_id "
            "WHERE e.kind = 'summarizes-paper' AND e.target_id = ? "
            "ORDER BY e.id LIMIT 1",
            (source_id,),
        ).fetchone()
        paper_summary = None
        if summary_row:
            sm = json.loads(summary_row[0]) if isinstance(summary_row[0], str) else (summary_row[0] or {})
            # A row is worth rendering if it carries prose or a state that says
            # something. Under D-15a there is nothing else it could carry: the
            # enrichment clause that used to sit here existed because a migrated
            # row had empty text and state "absent" yet still held key_ideas,
            # relevance and methodology. Those fields are gone, so such a row now
            # holds nothing and correctly renders nothing — which is also what
            # removes the contradiction that started this work, where the page
            # printed "No summary yet." underneath rendered content.
            if (sm.get("text") or "").strip() or sm.get("state") not in (None, "", "absent"):
                paper_summary = sm

        verdict_row = conn.execute(
            "SELECT n.attrs FROM edges e JOIN nodes n ON n.id = e.source_id "
            "WHERE e.kind = 'completeness-of' AND e.target_id = ? "
            "ORDER BY e.id LIMIT 1",
            (source_id,),
        ).fetchone()
        completeness = None
        if verdict_row:
            completeness = (
                json.loads(verdict_row[0])
                if isinstance(verdict_row[0], str)
                else (verdict_row[0] or {})
            )

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
                "concepts": concepts,
                "subsystems": sorted(all_subsystems),
                "paper_evidence": paper_evidence,
                "existing_reviews": existing_reviews,
                "paper_summary": paper_summary,
                "completeness": completeness,
                "completeness_dimensions": COMPLETENESS_DIMENSION_LABELS,
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
            "('preprint','conference-paper','conference-proceedings') "
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

    @app.get("/intake", response_class=HTMLResponse)
    async def intake_list(
        request: Request,
        missing: str | None = None,
        summary_state: str | None = None,
        page: int = Query(1, ge=1),
        per_page: int = Query(50, ge=10, le=200),
    ):
        """Papers and their intake completeness verdict (ALG-KK-WEB-INTAKE-LIST).

        Reads verdicts ALG-KK-COMPLETENESS-COMPUTE already wrote. Computes
        nothing, fetches nothing, calls no model.

        INV-KK-WEB-QUERY-BOUNDED: SQL LIMIT/OFFSET pagination.
        INV-KK-COMPLETENESS-ADVISORY: `missing` defaults to None and the
        unfiltered view shows every paper. A filter is something the operator
        asks for, never something the page does on its own.
        """
        conn = request.app.state.conn
        dimensions = [key for key, _label, _explanation in COMPLETENESS_DIMENSION_LABELS]

        # LEFT JOIN, deliberately: a paper with NO verdict node at all is exactly
        # the kind most likely to be broken, and an inner join would hide it.
        sql = (
            "SELECT s.id, s.attrs, v.attrs FROM nodes s "
            "LEFT JOIN edges e ON e.kind = 'completeness-of' AND e.target_id = s.id "
            "LEFT JOIN nodes v ON v.id = e.source_id "
            f"WHERE s.kind = 'Source' AND json_extract(s.attrs, '$.source_type') IN {_RESEARCH_TYPES}"
        )
        params: list = []
        if missing == "verdict":
            sql += " AND v.id IS NULL"
        elif missing in dimensions:
            # NULL (no verdict) counts as missing the dimension.
            sql += f" AND COALESCE(json_extract(v.attrs, '$.{missing}'), 0) = 0"
        elif missing == "any":
            clauses = " AND ".join(
                f"COALESCE(json_extract(v.attrs, '$.{d}'), 0) = 0" for d in dimensions
            )
            sql += f" AND ({clauses})"
        if summary_state:
            sql += " AND json_extract(v.attrs, '$.summary_state') = ?"
            params.append(summary_state)
        sql += " ORDER BY s.id LIMIT ? OFFSET ?"
        params.extend([per_page + 1, (page - 1) * per_page])

        rows = conn.execute(sql, params).fetchall()
        has_next = len(rows) > per_page
        rows = rows[:per_page]

        papers = []
        for source_id, source_attrs, verdict_attrs in rows:
            s_attrs = json.loads(source_attrs) if isinstance(source_attrs, str) else (source_attrs or {})
            v_attrs = (
                json.loads(verdict_attrs) if isinstance(verdict_attrs, str) else verdict_attrs
            ) or None
            papers.append({
                "source_id": source_id,
                "title": s_attrs.get("title") or source_id,
                "venue": s_attrs.get("venue") or "",
                "source_type": s_attrs.get("source_type") or "",
                "verdict": v_attrs,
                # Carried separately from has_summary: every summary in the corpus
                # is llm-extracted and none has been read by a person, so a green
                # tick must not be allowed to read as endorsement.
                "summary_state": (v_attrs or {}).get("summary_state") or "",
                "computed_at": (v_attrs or {}).get("computed_at") or "",
            })

        return templates.TemplateResponse(
            request,
            "intake.html",
            {
                "papers": papers,
                "dimensions": COMPLETENESS_DIMENSION_LABELS,
                "missing_filter": missing or "",
                "summary_state_filter": summary_state or "",
                "page": page,
                "per_page": per_page,
                "has_next": has_next,
            },
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

    @app.get("/links/review", response_class=HTMLResponse)
    async def link_review(
        request: Request,
        state: str = "unreviewed",
        page: int = Query(1, ge=1),
        per_page: int = Query(25, ge=5, le=100),
    ):
        """One screen per link: concept, paper and stored verdict together
        (ALG-KK-WEB-LINK-REVIEW).

        Reads what ALG-KK-LLM-EXTRACT already stored on the edge. It does not
        re-run the grounding check, call a model, or alter a verdict.

        INV-KK-COMPLETENESS-ADVISORY: `state` defaults to unreviewed because
        that is the work queue, but every other value is reachable and no link
        is ever withheld. The legacy title-regex links are INCLUDED — 191 of
        them are known wrong and this is where a person would find that out.

        INV-KK-WEB-QUERY-BOUNDED: SQL LIMIT/OFFSET.
        """
        from ingest.link_confirmation import count_confirmations
        from ingest.reviewer_registry import list_reviewers

        conn = request.app.state.conn

        where = {
            "unreviewed": "AND json_extract(e.attrs, '$.confirmation') IS NULL",
            "confirmed": "AND json_extract(e.attrs, '$.confirmation') = 'confirmed'",
            "rejected": "AND json_extract(e.attrs, '$.confirmation') = 'rejected'",
        }.get(state, "")

        rows = conn.execute(
            "SELECT c.id, c.attrs, ev.id, s.id, s.attrs, e.attrs "
            "FROM edges e "
            "JOIN nodes c  ON c.id = e.source_id AND c.kind = 'Concept' "
            "JOIN nodes ev ON ev.id = e.target_id AND ev.kind = 'Evidence' "
            "LEFT JOIN edges se ON se.kind = 'sourced-from' AND se.source_id = ev.id "
            "LEFT JOIN nodes s ON s.id = se.target_id AND s.kind = 'Source' "
            f"WHERE e.kind = 'extracted-from' {where} "
            "ORDER BY c.id, ev.id LIMIT ? OFFSET ?",
            (per_page, (page - 1) * per_page),
        ).fetchall()

        links = []
        for cid, c_raw, ev_id, src_id, s_raw, e_raw in rows:
            c_attrs = json.loads(c_raw) if isinstance(c_raw, str) else (c_raw or {})
            s_attrs = json.loads(s_raw) if isinstance(s_raw, str) else (s_raw or {})
            e_attrs = json.loads(e_raw) if isinstance(e_raw, str) else (e_raw or {})
            links.append({
                "concept_id": cid,
                "concept_name": c_attrs.get("name", cid),
                "concept_description": c_attrs.get("description", ""),
                "evidence_id": ev_id,
                "source_id": src_id or "",
                "paper_title": s_attrs.get("title", src_id or "(no paper)"),
                "paper_url": s_attrs.get("url", ""),
                "basis": e_attrs.get("basis", ""),
                "grounded": e_attrs.get("grounded"),
                "ungrounded_count": e_attrs.get("ungrounded_count"),
                # Shown deliberately: `grounded` is false essentially everywhere
                # on this corpus, so a bare red flag teaches a reader nothing
                # while the phrases let them judge the paraphrase themselves.
                "ungrounded": e_attrs.get("ungrounded", []),
                "confirmation": e_attrs.get("confirmation"),
                "confirmed_by": e_attrs.get("confirmed_by", ""),
                "confirmed_at": e_attrs.get("confirmed_at", ""),
                "confirmation_note": e_attrs.get("confirmation_note", ""),
            })

        return templates.TemplateResponse(
            request, "link_review.html",
            {
                "links": links,
                "counts": count_confirmations(conn),
                "state_filter": state,
                "page": page,
                "per_page": per_page,
                "reviewers": [
                    {"reviewer_id": r.reviewer_id, "name": r.name}
                    for r in list_reviewers(conn)
                ],
            },
        )

    @app.put("/api/link-confirm/{concept_id}/{evidence_id}")
    async def api_link_confirm(request: Request, concept_id: str, evidence_id: str):
        """Record or clear one person's judgement of one link.

        INV-KK-WEB-MUTATION-ALLOWLISTED: /api/link-confirm/ is on the allowlist.
        INV-KK-LINK-CONFIRMATION-STATE: a confirmation with no reviewer is an
        anonymous assertion and is refused by the store, not by this route.
        """
        from ingest.link_confirmation import clear_confirmation, set_confirmation
        from ingest.paper_completeness import recompute_paper_if_present

        conn = request.app.state.conn
        try:
            body = await request.json()
        except Exception:
            body = {}

        confirmation = (body.get("confirmation") or "").strip()
        source_id = conn.execute(
            "SELECT target_id FROM edges WHERE kind = 'sourced-from' AND source_id = ?",
            (evidence_id,),
        ).fetchone()

        try:
            if not confirmation:
                cleared = clear_confirmation(conn, concept_id, evidence_id)
                if not cleared:
                    return JSONResponse(
                        {"error": "No confirmation to clear"}, status_code=404)
                result = {"confirmation": None}
            else:
                r = set_confirmation(
                    conn, concept_id, evidence_id, confirmation,
                    body.get("reviewer_id", ""), body.get("note", ""))
                result = {
                    "confirmation": r.confirmation,
                    "confirmed_by": r.confirmed_by,
                    "confirmed_at": r.confirmed_at,
                    "note": r.note,
                }
        except ValueError as exc:
            status = 404 if "does not exist" in str(exc) or "No extracted-from" in str(exc) else 422
            return JSONResponse({"error": str(exc)}, status_code=status)

        # The verdict's links_confirmed dimension moved; keep the paper page
        # honest rather than waiting for the next batch recompute.
        if source_id:
            recompute_paper_if_present(conn, source_id[0])
        conn.commit()
        return JSONResponse({"concept_id": concept_id,
                             "evidence_id": evidence_id, **result})

    @app.get("/reviewers", response_class=HTMLResponse)
    async def reviewers_page(request: Request):
        """Reviewer roster page (ALG-KK-WEB-REVIEWERS-PAGE)."""
        from ingest.reviewer_registry import list_reviewers

        conn = request.app.state.conn
        roster = [
            {"reviewer_id": r.reviewer_id, "name": r.name}
            for r in list_reviewers(conn)
        ]
        return templates.TemplateResponse(
            request, "reviewers.html", {"reviewers": roster},
        )

    @app.post("/api/reviewers")
    async def create_reviewer(request: Request):
        """Register a reviewer name (ALG-KK-WEB-REVIEWER-CREATE).

        INV-KK-WEB-MUTATION-ALLOWLISTED: /api/reviewers is on
        WEB_MUTATION_ALLOWLIST.
        """
        from ingest.reviewer_registry import register_reviewer
        import dataclasses

        conn = request.app.state.conn
        body = await request.json()
        try:
            result = register_reviewer(conn, body["name"])
            conn.commit()
            return JSONResponse(dataclasses.asdict(result), status_code=201)
        except ValueError as exc:
            msg = str(exc)
            if "already registered" in msg:
                return JSONResponse({"error": msg}, status_code=409)
            return JSONResponse({"error": msg}, status_code=422)
        except KeyError as exc:
            return JSONResponse({"error": f"Missing field: {exc}"}, status_code=422)

    @app.put("/api/summary/{source_id:path}")
    async def edit_summary(request: Request, source_id: str):
        """Set one paper's summary text and state by hand (ALG-KK-WEB-SUMMARY-EDIT).

        INV-KK-WEB-MUTATION-ALLOWLISTED: /api/summary/ is on
        WEB_MUTATION_ALLOWLIST.
        INV-KK-WEB-SUMMARY-STATE-AUTHORITY: the endpoint writes only human
        states, and attribution comes from the session. A reviewed_by field in
        the body is ignored, so no request can attribute a summary to someone
        else, and llm-extracted is refused outright — a person may not launder
        their own text as a model's.
        INV-KK-VENUE-MUTATION-AUTHORISED's blast-radius rule: this touches one
        Source, so an authenticated user is enough and no role check is added.
        """
        from ingest.paper_summary import set_summary
        import dataclasses

        identity = getattr(request.state, "user", None)
        if identity is None:
            # Defensive: the gate never lets an anonymous request this far.
            return JSONResponse({"error": "Not authenticated"}, status_code=401)

        conn = request.app.state.conn
        body = await request.json()
        state = body.get("state", "human-authored")
        if state not in WEB_WRITABLE_SUMMARY_STATES:
            return JSONResponse(
                {"error": f"State '{state}' is not settable by hand. Choose one of: "
                          + ", ".join(WEB_WRITABLE_SUMMARY_STATES)},
                status_code=422,
            )
        try:
            result = set_summary(
                conn, source_id, body.get("text", ""), state,
                reviewed_by=identity["reviewer"],
                recompute=True,
            )
            conn.commit()
            return JSONResponse(dataclasses.asdict(result))
        except ValueError as exc:
            msg = str(exc)
            if "does not exist" in msg:
                return JSONResponse({"error": msg}, status_code=404)
            return JSONResponse({"error": msg}, status_code=422)

    @app.post("/api/review/{source_id:path}")
    async def submit_review(request: Request, source_id: str):
        """Submit a human review for a paper (ALG-KK-WEB-REVIEW-SUBMIT).

        INV-KK-WEB-MUTATION-ALLOWLISTED: /api/review/ is on
        WEB_MUTATION_ALLOWLIST.
        INV-KK-REVIEW-ATTRIBUTION-FROM-SESSION: the author is the logged-in
        user. A reviewer field in the body is ignored, so no request can file
        a review under someone else's name.
        """
        from ingest.paper_scorer import review_paper
        import dataclasses

        identity = getattr(request.state, "user", None)
        if identity is None:
            # Defensive: the gate never lets an anonymous request this far.
            return JSONResponse({"error": "Not authenticated"}, status_code=401)
        reviewer = identity["reviewer"]

        conn = request.app.state.conn
        body = await request.json()
        try:
            result = review_paper(
                conn, source_id,
                reviewer, body["score"],
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

        INV-KK-WEB-MUTATION-ALLOWLISTED: /api/review/ is on
        WEB_MUTATION_ALLOWLIST.
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

    @app.delete("/api/review/{review_id}")
    async def remove_review(request: Request, review_id: str):
        """Delete an existing human review (ALG-KK-WEB-REVIEW-DELETE).

        INV-KK-WEB-MUTATION-ALLOWLISTED: /api/review/ is on
        WEB_MUTATION_ALLOWLIST.
        """
        from ingest.paper_scorer import delete_review
        import dataclasses

        conn = request.app.state.conn
        try:
            result = delete_review(conn, review_id)
            conn.commit()
            return JSONResponse(dataclasses.asdict(result))
        except ValueError as exc:
            msg = str(exc)
            if "does not exist" in msg:
                return JSONResponse({"error": msg}, status_code=404)
            return JSONResponse({"error": msg}, status_code=400)

    @app.put("/api/abstract/{source_id:path}")
    async def edit_abstract(request: Request, source_id: str):
        """Set a Source abstract by hand (ALG-KK-WEB-ABSTRACT-EDIT).

        INV-KK-WEB-MUTATION-ALLOWLISTED: /api/abstract/ is on
        WEB_MUTATION_ALLOWLIST.

        The provenance label is forced to "manual" — a human typed it, whatever
        the caller claims (IFC-KK-SOURCE-ABSTRACT).
        """
        from ingest.source_abstract import set_abstract
        import dataclasses

        conn = request.app.state.conn
        body = await request.json()
        try:
            # recompute=True: one paper, a human is watching, and the page
            # should reflect the edit. Bulk callers leave it off.
            result = set_abstract(
                conn, source_id, body["abstract"], "manual", recompute=True
            )
            conn.commit()
            return JSONResponse(dataclasses.asdict(result))
        except ValueError as exc:
            msg = str(exc)
            if "does not exist" in msg:
                return JSONResponse({"error": msg}, status_code=404)
            return JSONResponse({"error": msg}, status_code=422)
        except KeyError as exc:
            return JSONResponse({"error": f"Missing field: {exc}"}, status_code=422)

    @app.put("/api/venue/{source_id:path}")
    async def edit_venue(request: Request, source_id: str):
        """Set one Source's venue by hand (ALG-KK-WEB-VENUE-EDIT).

        INV-KK-WEB-MUTATION-ALLOWLISTED: /api/venue/ is on
        WEB_MUTATION_ALLOWLIST.

        INV-KK-VENUE-MUTATION-AUTHORISED: this touches exactly one Source, so an
        authenticated user is enough. The merge endpoint below is the one that
        needs an admin.
        """
        from ingest.venue_store import set_venue
        import dataclasses

        conn = request.app.state.conn
        body = await request.json()
        try:
            result = set_venue(
                conn, source_id, body["venue"], body.get("venue_type", "other")
            )
            conn.commit()
            return JSONResponse(dataclasses.asdict(result))
        except ValueError as exc:
            msg = str(exc)
            if "does not exist" in msg:
                return JSONResponse({"error": msg}, status_code=404)
            return JSONResponse({"error": msg}, status_code=422)
        except KeyError as exc:
            return JSONResponse({"error": f"Missing field: {exc}"}, status_code=422)

    @app.post("/api/venue/merge")
    async def merge_venue(request: Request):
        """Merge one venue into another (ALG-KK-WEB-VENUE-MERGE).

        INV-KK-WEB-MUTATION-ALLOWLISTED: /api/venue/ is on
        WEB_MUTATION_ALLOWLIST.

        INV-KK-VENUE-MUTATION-AUTHORISED: admin only. One call can repoint up to
        897 Sources — the largest blast radius in this module, against one row
        for the abstract editor — so this is deliberately stricter than the
        single-Source edit above.
        """
        from ingest.venue_store import merge_venues
        import dataclasses

        identity = getattr(request.state, "user", None)
        if not identity or identity.get("role") != "admin":
            return JSONResponse(
                {"error": "Administrator access required"}, status_code=403
            )

        conn = request.app.state.conn
        body = await request.json()
        try:
            result = merge_venues(conn, body["from"], body["to"])
            conn.commit()
            return JSONResponse(dataclasses.asdict(result))
        except ValueError as exc:
            msg = str(exc)
            if "does not exist" in msg:
                return JSONResponse({"error": msg}, status_code=404)
            return JSONResponse({"error": msg}, status_code=422)
        except KeyError as exc:
            return JSONResponse({"error": f"Missing field: {exc}"}, status_code=422)

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
