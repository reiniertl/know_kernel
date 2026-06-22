# PoC Demo Implementation Plan

## Context Priming Header

> CONTEXT PRIMING: Read this document to prime context for the PoC demo
> implementation. The know_kernel system is a knowledge graph for kernel
> design intelligence. The core pipeline is complete: 15 node kinds, 19
> edge kinds, 336 tests passing. All three operational knowledge phases
> (KernelInvariant, FailureMode, InteractionProtocol) are implemented.
> The system has never been run against real data — only mocks.
>
> This plan covers: (A) web layer enhancements for human consumption,
> (B) MCP server enhancements for LLM consumption, (C) graph diagnostics,
> and (D) the PoC demo itself with real kernel documentation.
>
> CLI commands: kk-ingest, kk-extract, kk-review, kk-export, kk-web, kk-mcp.
> Source layout: src/graph/ (engine, schema, optimization, rules),
> src/ingest/ (pipeline, extractor, classifier, cli, cli_extract, cli_review, reviewer),
> src/export/ (exporter, cli), src/web/ (app, routes, templates/),
> src/mcp_server/ (server).

---

## Current State Summary

### What Works (tested with mocks)

- **Ingest:** `kk-ingest --db --input --url --type` → creates Source + Evidence
- **Extract:** `kk-extract --db --all-unextracted --model` → creates Concept,
  KernelInvariant, FailureMode, InteractionProtocol, PerformanceProfile,
  CompatibilityAssessment, ComparativeAnalysis + all edges
- **Review:** `kk-review --db --source-id --assessment --confirm-level`
- **Export:** `kk-export --master-db --output-db` → Class B-only snapshot
- **Web:** 6 GET routes (dashboard, concept list, concept detail, subsystems,
  sources, graph JSON) — raw JSON attrs rendering
- **MCP:** 9 tools (search_concepts, get_concept, list_subsystems,
  get_subsystem_concepts, get_impact_surface, find_concepts_for_goal,
  compare_concepts, match_workload, explore_subgraph)

### What's Missing

1. Web shows raw JSON for all node kinds — no structured rendering
2. Web has no access to advanced query functions (impact, compare, recommendations)
3. MCP `get_concept` only returns Concept/Subsystem/Proposal — can't fetch
   KernelInvariant, FailureMode, etc. by ID
4. No MCP tools for `path_exists` or `query_edges_by_attrs`
5. No graph diagnostics (orphan detection, coverage reports)
6. Never tested with real data

---

## Phase A: Web Layer Enhancements

### Goal

Transform the web interface from a raw JSON browser into a structured
knowledge graph viewer. After Phase A, a human can browse the graph
and see kind-aware detail pages, grouped edges, and advanced query results.

### A1: Kind-Aware Detail Templates

**Algorithm: ALG-KK-WEB-KIND-DETAIL**

Replaces the single `concept_detail.html` template with kind-aware rendering.
The route handler at `GET /concepts/{node_id}` inspects the node's `kind`
field and dispatches to the appropriate template section.

**How it works:**

1. Fetch node by ID (existing `_rows_to_dicts` helper)
2. Fetch all edges where node is source or target (existing query)
3. Group edges by kind into a `dict[str, list[dict]]` — e.g.,
   `{"governed-by": [...], "extracted-from": [...], "belongs-to": [...]}`
4. Based on `node["kind"]`, render the appropriate detail section:

   - **Concept:** name, description, key_properties (bulleted list),
     tradeoffs (bulleted list), design_rationale (paragraph),
     subsystem (from belongs-to edge), linked invariants (from
     governed-by edges, rendered as cards with strength badge)

   - **KernelInvariant:** predicate (blockquote), strength (color-coded
     badge: red=safety, orange=liveness, blue=performance, gray=structural),
     scope (label), governed-by concept (link), failure modes (from
     triggered-by edges, rendered inline)

   - **FailureMode:** symptom (paragraph), blast_radius (severity badge:
     red=kernel-wide, orange=subsystem, green=local), recoverability
     (badge: red=data-loss, orange=requires-restart, green=self-healing),
     triggered-by invariant (link)

   - **InteractionProtocol:** rule (paragraph), ordering (badge with
     directional arrow: before→, after←, never-during⊘, must-hold-while⟳),
     violation_mode (paragraph), constrains-composition concepts (two
     linked cards showing the concept pair)

   - **PerformanceProfile:** metric, complexity, best/worst/typical case
     table, conditions, profiled-by concept link

   - **CompatibilityAssessment:** synergy rating, rationale, conditions,
     the two assessed concepts as linked cards

   - **ComparativeAnalysis:** dimension, winner (highlighted), conditions,
     quantitative_delta, the two compared concepts

   - **OptimizationGoal:** name, description, metric, direction (↑ maximize / ↓ minimize),
     contributing concepts (from contributes-to edges with direction + magnitude)

   - **UseCaseScenario:** name, description, workload_type, constraints,
     suited concepts (from suited-for edges with fitness ranking)

   - **Kernel:** name, description, kernel_type, implemented concepts
     (from implemented-in edges with maturity + since_version)

   - **Subsystem, Source, Evidence, Advisory, Proposal:** existing
     rendering preserved, edges grouped

5. All edge groups rendered as collapsible sections with count badges.
   Each edge shows the connected node as a clickable link with its kind
   as a colored tag.

**Invariant enforced: INV-KK-WEB-KIND-AWARE-DETAIL** — Every node kind in
ALLOWED_KINDS has a structured detail view that renders its REQUIRED_ATTRS
with appropriate formatting. No raw JSON dump for any ALLOWED_KIND.

**Invariant enforced: INV-KK-WEB-EDGE-GROUPED** — The detail page for any
node groups its edges by kind. Each group is a labeled section with a
count badge and clickable links to connected nodes.

**Files:** `src/web/routes.py` (modify route handler), `src/web/templates/concept_detail.html`
(rewrite with kind-aware sections), `src/web/templates/base.html` (add CSS for
badges, cards, collapsible sections).

**Tests:**
- test_web_concept_detail_renders_properties (Concept kind)
- test_web_invariant_detail_renders_strength_badge (KernelInvariant kind)
- test_web_failure_mode_detail_renders_blast_radius (FailureMode kind)
- test_web_protocol_detail_renders_ordering (InteractionProtocol kind)
- test_web_edges_grouped_by_kind (edge grouping)
- test_web_all_allowed_kinds_have_detail (parametrized over ALLOWED_KINDS)

---

### A2: Web Query Endpoints

**Algorithm: ALG-KK-WEB-QUERY-ROUTES**

Adds 4 new GET endpoints that delegate to existing engine.py query functions.
These are JSON-only endpoints (no HTML templates) consumed by the frontend
or by humans inspecting the API directly.

**How it works:**

Each endpoint is a thin wrapper: parse query parameters → call engine.py
function → serialize result as JSON. No query logic reimplemented in the
web layer.

**Routes:**

1. **`GET /api/impact/{node_id}`**
   - Delegates to: `engine.transitive_impact(conn, node_id)`
   - Returns: `{invariants: [...], failure_modes: [...], protocols: [...],
     profiles: [...], goals: [...], compatibilities: [...], comparatives: [...],
     scenarios: [...]}`
   - Use case: "Show me everything that depends on or constrains this concept"

2. **`GET /api/compare/{id_a}/{id_b}`**
   - Delegates to: `engine.compare_neighborhoods(conn, id_a, id_b, depth=1)`
   - Also fetches ComparativeAnalysis nodes that reference both concepts
   - Returns: `{diff: {shared: [...], only_a: [...], only_b: [...]},
     comparatives: [...]}`
   - Use case: "How do these two concepts differ in their graph neighborhoods?"

3. **`GET /api/recommendations/{goal_id}?limit=10`**
   - Delegates to: `engine.ranked_recommendations(conn, goal_id, limit)`
   - Returns: `[{concept_id, concept_name, score, direction, magnitude}, ...]`
   - Use case: "Which concepts best serve this optimization goal?"

4. **`GET /api/match?workload_type=...`**
   - Delegates to: `engine.match_scenarios(conn, workload_type=workload_type)`
   - Returns: `[{scenario: {...}, concepts: [{id, kind, attrs, fitness}, ...]}, ...]`
   - Use case: "Which concepts fit this workload pattern?"

**Invariant enforced: INV-KK-WEB-QUERY-DELEGATES** — Every web query route
delegates to the corresponding engine.py function. No reimplementation of
query logic in the web layer. The route handler's body is: parse params →
call engine function → return JSON.

**Invariant enforced: INV-KK-WEB-READ-ONLY** (existing) — All new endpoints
are GET-only.

**Files:** `src/web/routes.py` (add 4 routes), tests (add 4 integration tests).

**Tests:**
- test_web_api_impact_returns_all_categories
- test_web_api_compare_returns_diff_structure
- test_web_api_recommendations_returns_sorted
- test_web_api_match_returns_scenarios_with_concepts

---

### A3: Graph Visualization Endpoint

**Algorithm: ALG-KK-WEB-GRAPH-VIZ**

Adds a client-side interactive graph visualization to the web interface.
The existing `GET /graph` endpoint already returns the full graph as JSON.
This algorithm adds a page that renders that JSON as a force-directed graph.

**How it works:**

1. New route: `GET /viz` — serves an HTML page with embedded JavaScript
2. The page fetches `/graph` JSON on load
3. Renders nodes as circles, colored by kind (Concept=blue, KernelInvariant=red,
   FailureMode=orange, InteractionProtocol=purple, Subsystem=green, etc.)
4. Renders edges as lines, styled by kind (governed-by=dashed red,
   triggered-by=dotted orange, belongs-to=solid green, etc.)
5. Nodes are clickable — clicking navigates to `/concepts/{node_id}`
6. Uses a lightweight library (D3.js via CDN or vanilla SVG/Canvas)

**Constraint:** No npm build step. The visualization is a single HTML page
with inline or CDN-loaded JavaScript. The web layer stays zero-build.

**Files:** `src/web/templates/graph_viz.html` (new), `src/web/routes.py`
(add `/viz` route).

**Tests:**
- test_web_viz_route_returns_html
- test_web_viz_contains_graph_fetch (verify the page references /graph endpoint)

---

## Phase B: MCP Server Enhancements

### Goal

Expand the MCP tool set so an LLM can fetch any node kind by ID, check
reachability, and query edges by attributes. After Phase B, the MCP
server has 12 tools (up from 9).

### B1: Expand get_concept to All ALLOWED_KINDS

**Algorithm: Update to ALG-KK-MCP-QUERY (existing)**

The current `get_concept` tool restricts results to Concept, Subsystem,
Proposal. This is too narrow — an LLM that discovers a KernelInvariant ID
via `get_impact_surface` cannot fetch its full detail.

**How it works:**

Change the kind filter in `get_concept` from:
```python
if node["kind"] not in ("Concept", "Subsystem", "Proposal"):
    return None
```
to:
```python
if node["kind"] not in ALLOWED_KINDS:
    return None
```

This is a one-line change. The function already returns the node's attrs
and edges. ALLOWED_KINDS already excludes Evidence/Source/Advisory
(INV-KK-MCP-SNAPSHOT-ONLY is preserved).

**Invariant updated: INV-KK-MCP-TOOLS-EXPOSED** — `get_concept` now returns
detail for any ALLOWED_KIND node, not just Concept/Subsystem/Proposal.

**Files:** `src/mcp_server/server.py` (modify get_concept).

**Tests:**
- test_mcp_get_concept_returns_kernel_invariant
- test_mcp_get_concept_returns_failure_mode
- test_mcp_get_concept_returns_interaction_protocol
- test_mcp_get_concept_rejects_evidence (still blocked)

---

### B2: Add path_exists MCP Tool

**Algorithm: ALG-KK-MCP-PATH-EXISTS (new)**

Wraps `engine.path_exists()` as an MCP tool. Allows an LLM to check
reachability between two nodes — critical for composition reasoning
("does Concept A transitively constrain Concept B?").

**How it works:**

New MCP tool definition:
```
tool: check_path
args: source_id (str), target_id (str), edge_kinds (optional list[str])
returns: {reachable: bool, path_length: int | null}
```

Delegates to `engine.path_exists(conn, source_id, target_id, edge_kinds)`.
Returns `{reachable: True/False}`. If reachable, includes the hop count.
If `edge_kinds` is provided, only follows those edge kinds.

**Files:** `src/mcp_server/server.py` (add tool).

**Tests:**
- test_mcp_check_path_reachable
- test_mcp_check_path_unreachable
- test_mcp_check_path_with_edge_kind_filter

---

### B3: Add query_edges_by_attrs MCP Tool

**Algorithm: ALG-KK-MCP-QUERY-EDGES (new)**

Wraps `engine.query_edges_by_attrs()` as an MCP tool. Allows an LLM to
find edges matching attribute filters — e.g., "find all contributes-to
edges where direction=improves and magnitude=strong".

**How it works:**

New MCP tool definition:
```
tool: query_edges
args: kind (str), filters (dict[str, str])
returns: list[{edge_id, kind, source_id, target_id, attrs}]
```

Delegates to `engine.query_edges_by_attrs(conn, kind, **filters)`.
Filters results to only include edges where both source and target
are ALLOWED_KINDS (snapshot safety). Returns at most 50 results.

**Files:** `src/mcp_server/server.py` (add tool).

**Tests:**
- test_mcp_query_edges_by_kind
- test_mcp_query_edges_with_attr_filter
- test_mcp_query_edges_filters_disallowed_kinds

---

## Phase C: Graph Diagnostics

### Goal

Add diagnostic queries that audit graph quality after real data extraction.
These run as CLI commands or web endpoints and report structural issues.

### C1: Orphan Detection and Coverage Report

**Algorithm: ALG-KK-DIAG-ORPHAN-DETECT**

Finds nodes that lack expected edges. Not a validation failure (rules.py
already catches hard violations) — this is a quality report.

**How it works:**

New function: `diagnose_graph(conn) -> DiagnosticReport`

Checks:
1. **Orphan Concepts:** Concept nodes with no `belongs-to` edge to any
   Subsystem. (Should be zero if classifier runs correctly, but real
   data may produce edge cases.)
2. **Unlinked KernelInvariants:** KernelInvariant nodes with no
   `governed-by` edge. (Should be impossible given store_kernel_invariant
   logic, but validates the invariant holds.)
3. **Dangling FailureModes:** FailureMode nodes with no `triggered-by`
   edge to a KernelInvariant.
4. **Lone InteractionProtocols:** InteractionProtocol nodes with fewer
   than 2 `constrains-composition` edges.
5. **Subsystem coverage:** Count of Concepts per Subsystem. Highlights
   subsystems with fewer than 2 concepts (thin coverage).
6. **Invariant density:** Average KernelInvariants per Concept. Below
   1.0 suggests extraction prompt needs tuning.
7. **Duplicate names:** Concept nodes with identical `name` attrs
   (case-insensitive). May indicate extraction produced the same
   concept twice from different Evidence.

Returns:
```python
@dataclass
class DiagnosticReport:
    orphan_concepts: list[str]           # node IDs
    unlinked_invariants: list[str]
    dangling_failure_modes: list[str]
    lone_protocols: list[str]
    subsystem_coverage: dict[str, int]   # subsystem_name -> concept_count
    invariant_density: float             # avg invariants per concept
    duplicate_names: list[tuple[str, str]]  # (name, [ids])
    total_nodes: int
    total_edges: int
```

**Files:** `src/graph/diagnostics.py` (new module), tests.

**CLI exposure:** Add `--diagnostics` flag to `kk-export` or create a
standalone `kk-diag --db <path>` command.

**Web exposure:** `GET /api/diagnostics` returns the report as JSON.

**Tests:**
- test_diag_detects_orphan_concept
- test_diag_detects_duplicate_names
- test_diag_clean_graph_no_issues
- test_diag_subsystem_coverage_counts
- test_diag_invariant_density_calculation

---

## Phase D: PoC Demo with Real Data

### Goal

Run the full pipeline against 3-5 real kernel documentation sources.
Validate extraction quality, web rendering, and MCP query results.
Produce a gap report.

### Prerequisites

Phases A, B, C must be complete. The web renders structured detail pages,
MCP can fetch any node kind, and diagnostics can audit graph quality.

### D1: Select and Prepare Source Documents

Select 3-5 documents covering different kernel subsystems to exercise
cross-subsystem extraction and interaction protocol discovery:

| Document | Subsystem | Why |
|----------|-----------|-----|
| kernel.org/doc/Documentation/RCU/ | Synchronization | Rich invariants (grace period, reader guarantees). Well-documented composition rules with memory allocation. |
| kernel.org/doc/Documentation/vm/ | Virtual Memory | Page table invariants, TLB coordination protocols. Cross-subsystem with locking. |
| kernel.org/doc/Documentation/scheduler/ | Scheduler | CFS invariants (vruntime monotonicity, O(log n) selection). Performance profiles. |
| kernel.org/doc/Documentation/locking/ | Locking | Spinlock invariants (no recursive hold), ordering protocols. Foundation for cross-subsystem interaction protocols. |
| kernel.org/doc/Documentation/block/ (optional) | Block I/O | Tests a less-related subsystem. Validates subsystem classification. |

**Preparation:**
1. Download documents to `data/sources/` directory
2. Verify each is plain text or PDF parseable by the ingest pipeline
3. Record the URL for each (required by kk-ingest)

### D2: Ingest Documents

```bash
# Create fresh master DB
kk-ingest --db data/master.db --input data/sources/rcu/ \
  --url "https://www.kernel.org/doc/Documentation/RCU/" --type paper

kk-ingest --db data/master.db --input data/sources/vm/ \
  --url "https://www.kernel.org/doc/Documentation/vm/" --type paper

kk-ingest --db data/master.db --input data/sources/scheduler/ \
  --url "https://www.kernel.org/doc/Documentation/scheduler/" --type paper

kk-ingest --db data/master.db --input data/sources/locking/ \
  --url "https://www.kernel.org/doc/Documentation/locking/" --type paper
```

**Verify:** Each ingest produces Source + Evidence nodes. Check
contamination levels (kernel docs are GPL — expect strong-copyleft
or public-domain depending on license scan).

### D3: Review Sources

```bash
kk-review --db data/master.db --source-id <src-rcu> \
  --assessment "Official kernel.org documentation, GPL-2.0 licensed" \
  --confirm-level weak-copyleft

# Repeat for each source
```

### D4: Extract Concepts

```bash
kk-extract --db data/master.db --all-unextracted \
  --model claude-sonnet-4-6
```

**Verify after extraction:**
- How many Concepts created per document?
- Are KernelInvariants present? Check strength distribution (expect
  mostly safety + structural for locking/RCU, performance for scheduler)
- Are FailureModes present? Check blast_radius distribution
- Are InteractionProtocols present? Do they cross subsystem boundaries?
  (e.g., "non-sleeping allocation under spinlock" should link Locking
  and Memory Management concepts)
- Are PerformanceProfiles present? Check complexity values
- Run diagnostics: `kk-diag --db data/master.db`

### D5: Export Snapshot

```bash
kk-export --master-db data/master.db --output-db data/snapshot.db
```

**Verify:**
- Zero Class A nodes in snapshot
- All ALLOWED_KINDS present
- No dangling edges
- Node and edge counts match expectations

### D6: Web Demo

```bash
kk-web  # starts on localhost:8000, uses KNOW_KERNEL_DB env var
```

**Verify checklist:**
- [ ] Dashboard shows correct node counts by kind
- [ ] Concept list shows real kernel concepts (not mock data)
- [ ] Concept detail shows key_properties, tradeoffs, design_rationale
      with structured rendering (not raw JSON)
- [ ] KernelInvariant detail shows strength badge (color-coded),
      scope label, governed-by concept link
- [ ] FailureMode detail shows blast_radius severity, recoverability
- [ ] InteractionProtocol detail shows ordering, the two constrained concepts
- [ ] Edge groups are collapsible sections with count badges
- [ ] `/api/impact/{concept_id}` returns invariants + failure modes
- [ ] `/api/compare/{a}/{b}` returns neighborhood diff
- [ ] `/viz` shows interactive graph (if implemented)
- [ ] Navigation between linked nodes works (click concept → its invariants → their failure modes)

### D7: MCP Demo

```bash
kk-mcp --db data/snapshot.db  # starts MCP server
```

**Verify the LLM reasoning chain:**

1. **Discovery:** `search_concepts("RCU")` → returns Read-Copy-Update concept(s)
2. **Detail:** `get_concept(rcu_id)` → returns full attrs + edges
3. **Impact:** `get_impact_surface(rcu_id)` → returns invariants, failure modes, protocols
4. **Fetch invariant:** `get_concept(kinv_id)` → returns KernelInvariant detail
   (this verifies B1 fix — was previously blocked)
5. **Comparison:** `compare_concepts(rcu_id, spinlock_id)` → neighborhood diff
6. **Reachability:** `check_path(rcu_id, scheduler_concept_id)` → verifies
   cross-subsystem connectivity (this verifies B2)
7. **Goal query:** `find_concepts_for_goal(latency_goal_id)` → ranked concepts
8. **Workload match:** `match_workload("high-throughput")` → scenario + concepts

**Design question test:** Ask an LLM (via MCP) to answer:
> "I'm designing a kernel subsystem that needs concurrent read access to
> shared data structures with minimal latency. What mechanisms should I
> use, what invariants must I preserve, and what failure modes should I
> watch for?"

The LLM should be able to:
- Find RCU, spinlocks, and related concepts via search
- Retrieve their invariants (safety: no partial updates, liveness: bounded grace)
- Check interaction protocols (non-sleeping allocation under spinlock)
- Recommend based on optimization goals
- Produce a design that references specific graph nodes

### D8: Gap Report

After running D6 and D7, document:

1. **Extraction quality issues:** Vague predicates, wrong strength/scope
   classifications, missing invariants, hallucinated relationships
2. **Web rendering issues:** Templates that don't handle edge cases,
   missing node kinds, broken navigation
3. **MCP query issues:** Tools that return unexpected results, missing
   tools that an LLM needed but couldn't use
4. **Diagnostic findings:** Orphan nodes, thin subsystems, low invariant
   density, duplicate concepts
5. **Prompt tuning needs:** Specific changes to EXTRACTION_SYSTEM_PROMPT
   based on real output quality

This gap report becomes the input for the next sprint.

---

## Implementation Order

| # | Stage | Phase | Skill | Complexity | Dependencies |
|---|-------|-------|-------|-----------|-------------|
| 1 | Spec: web invariants + algorithms | A | /cb-green | Small | None |
| 2 | Spec: MCP updates + new algorithms | B | /cb-green | Small | None |
| 3 | Spec: diagnostics algorithm | C | /cb-green | Small | None |
| 4 | Audit: spec completeness | — | /cb-audit | Small | 1, 2, 3 |
| 5 | Code: kind-aware detail templates | A1 | /cb-green | Medium | 1 |
| 6 | Code: web query endpoints | A2 | /cb-green | Small | 1 |
| 7 | Code: graph visualization | A3 | /cb-green | Medium | 1 |
| 8 | Code: expand get_concept | B1 | /cb-green | Small | 2 |
| 9 | Code: path_exists MCP tool | B2 | /cb-green | Small | 2 |
| 10 | Code: query_edges MCP tool | B3 | /cb-green | Small | 2 |
| 11 | Code: diagnostics module | C1 | /cb-green | Medium | 3 |
| 12 | Audit: code completeness | — | /cb-audit | Small | 5-11 |
| 13 | Demo: ingest + extract real data | D1-D4 | /cb-free | Medium | 12 |
| 14 | Demo: web + MCP verification | D5-D7 | /cb-free | Medium | 13 |
| 15 | Report: gap analysis | D8 | /cb-free | Small | 14 |

**Stages 1-3 can run in parallel** (independent spec areas).
**Stages 5-7 can run in parallel** with **stages 8-10** (web vs MCP).

---

## New Spec Surface Summary

### New Invariant Nodes (4)

| ID | Subsystem | Predicate |
|----|-----------|-----------|
| INV-KK-WEB-KIND-AWARE-DETAIL | SUB-KK-WEB | Every node kind in ALLOWED_KINDS has a structured detail view that renders its REQUIRED_ATTRS with appropriate formatting — no raw JSON dump. |
| INV-KK-WEB-EDGE-GROUPED | SUB-KK-WEB | The detail page for any node groups its edges by kind. Each group is a labeled section with a count badge and clickable links to connected nodes. |
| INV-KK-WEB-QUERY-DELEGATES | SUB-KK-WEB | Every web query route delegates to the corresponding engine.py function. No reimplementation of query logic in the web layer. |
| INV-KK-DIAG-REPORT-COMPLETE | SUB-KK-GRAPH | The diagnostic report covers: orphan concepts, unlinked invariants, dangling failure modes, lone protocols, subsystem coverage, invariant density, and duplicate names. |

### New Algorithm Nodes (5)

| ID | Subsystem | What It Does |
|----|-----------|-------------|
| ALG-KK-WEB-KIND-DETAIL | SUB-KK-WEB | Route handler inspects node kind, dispatches to kind-specific template section. Groups edges by kind. Renders REQUIRED_ATTRS with badges, cards, and links. |
| ALG-KK-WEB-QUERY-ROUTES | SUB-KK-WEB | 4 GET endpoints (/api/impact, /api/compare, /api/recommendations, /api/match) that delegate to engine.py functions and return JSON. |
| ALG-KK-WEB-GRAPH-VIZ | SUB-KK-WEB | Client-side graph visualization: fetches /graph JSON, renders force-directed SVG with kind-colored nodes and kind-styled edges. Zero build step. |
| ALG-KK-MCP-PATH-EXISTS | SUB-KK-MCP | MCP tool wrapping engine.path_exists(). Args: source_id, target_id, optional edge_kinds. Returns {reachable: bool}. |
| ALG-KK-MCP-QUERY-EDGES | SUB-KK-MCP | MCP tool wrapping engine.query_edges_by_attrs(). Args: kind, filters dict. Returns list of matching edges. Filters to ALLOWED_KINDS endpoints. Max 50 results. |

### Updated Spec Nodes (3)

| ID | Change |
|----|--------|
| IF-KK-WEB-API | Fill in predicate: "The web API exposes: dashboard (GET /), node browse (GET /concepts, /concepts/{id}, /subsystems, /sources), graph JSON (GET /graph), query endpoints (GET /api/impact/{id}, /api/compare/{a}/{b}, /api/recommendations/{goal_id}, /api/match), and visualization (GET /viz)." |
| IF-KK-MCP-TOOL-SET | Update from 9 tools to 11: add check_path, query_edges. |
| INV-KK-MCP-TOOLS-EXPOSED | Update tool count from 9 to 11. Update get_concept description to note it returns any ALLOWED_KIND. |

### New Interface Node (1)

| ID | Subsystem | What It Defines |
|----|-----------|----------------|
| IF-KK-DIAGNOSTIC-REPORT | SUB-KK-GRAPH | The DiagnosticReport dataclass schema: orphan_concepts, unlinked_invariants, dangling_failure_modes, lone_protocols, subsystem_coverage, invariant_density, duplicate_names, total_nodes, total_edges. |

**Total new spec surface: 4 INV + 5 ALG + 1 IF = 10 new nodes, 3 updated nodes.**

---

## File Inventory

| File | Phase | Action |
|------|-------|--------|
| `spec.db` | A, B, C | MODIFY — new + updated spec nodes |
| `src/web/routes.py` | A1, A2, A3 | MODIFY — kind-aware detail, query endpoints, viz route |
| `src/web/templates/concept_detail.html` | A1 | REWRITE — kind-aware sections |
| `src/web/templates/base.html` | A1 | MODIFY — add CSS for badges, cards |
| `src/web/templates/graph_viz.html` | A3 | NEW — interactive graph page |
| `src/mcp_server/server.py` | B1, B2, B3 | MODIFY — expand get_concept, add 2 tools |
| `src/graph/diagnostics.py` | C1 | NEW — diagnose_graph function |
| `tests/test_web_routes.py` | A1, A2 | MODIFY — add kind-aware + query tests |
| `tests/test_mcp_server.py` | B1, B2, B3 | MODIFY — add expanded kind + new tool tests |
| `tests/test_graph_diagnostics.py` | C1 | NEW — diagnostic tests |
| `data/sources/` | D1 | NEW — real kernel documentation |
| `data/master.db` | D2-D4 | NEW — master DB with real data |
| `data/snapshot.db` | D5 | NEW — Class B snapshot for MCP |
