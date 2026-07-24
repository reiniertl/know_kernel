# Sprint Plan: Research Brief UX — Idea & Vulnerability Detail Pages

**Status:** Ready for implementation
**Date:** 2026-06-30
**Scope:** Rewrite idea_detail and vuln_detail pages from data dumps to self-contained research briefs
**Prerequisite:** Phases 1-9 of Idea Spotter plan complete; all graph, scoring, inference infrastructure exists
**Implementation:** 2 /cb-green stages

---

## Problem Statement

The idea and vulnerability detail pages are structured as database field dumps
with link lists. When a developer enters an idea page, they see:

- A title and description (1-2 lines)
- A score table (useful but unexplained)
- "Linked Concepts" — bare links that go to generic node detail pages
- "Evidence Timeline" — table of links with dates, no content
- "Related Ideas" — more links

The vulnerability detail page is similar: CVE header, then bare `<ul>` link
dumps of "Directly Exploited Concepts" and "Propagated At-Risk Concepts" with
no explanation of why the coupling matters or what to do about it.

None of this answers the questions the developer actually has:

- **Why is this important?** (What pain does it address? What severity?)
- **What evidence supports this?** (Verbatim quotes from real sources)
- **What code is affected?** (Subsystems, modules, invariants, code examples)
- **What would change?** (Prerequisites, composition constraints)
- **What could go wrong?** (Failure modes, vulnerability exposure, blast radius)
- **How strong is the case?** (Convergence across independent sources)

### Current file state

- `src/web/routes.py` lines 563-648: `idea_detail()` — ~85 lines, shallow queries
- `src/web/routes.py` lines 780-840: `vuln_detail()` — ~60 lines, shallow queries
- `src/web/templates/idea_detail.html` — 79 lines, card layout with link lists
- `src/web/templates/vuln_detail.html` — 58 lines, bare link dump

---

## Design: Two-Layer Research Brief

Each detail page becomes a **self-contained research brief** — a document a
kernel developer reads and walks away understanding the full picture without
clicking a single link.

### Layer 1: Evidence (verbatim, unaltered)

Raw signal from original sources. Text comes directly from node attributes
and is NEVER modified, summarized, or paraphrased:

| Node kind | Attribute rendered verbatim | How it's displayed |
|-----------|---------------------------|-------------------|
| Discussion | `title` | Article/thread title with forum badge and date |
| Observation | `claim` | Factual assertion with confidence and date |
| Problem | `title` + `description` | Problem statement with severity badge |
| Benchmark | `result_summary` + `conditions` | Measurement result with conditions |
| Vulnerability | `description` | CVE description with CVSS and severity |
| Rejection | `proposal_title` + `reason` | What was rejected and why |

Source attribution (forum/source_type, URL where available, source_date)
accompanies every evidence item.

### Layer 2: Analysis (system intelligence from graph topology)

Computed server-side from SQL queries across the knowledge graph edges. No
LLM needed — this is structural analysis from the graph:

| Analysis section | Data source | Graph traversal |
|-----------------|-------------|-----------------|
| Pain narrative | `pain_score()` decomposition | Count of problems, failure modes, vulns |
| Blast radius | Prerequisite dependents | `prerequisite` edge reverse traversal |
| Invariants at risk | KernelInvariant nodes | `governed-by` edge to concept |
| Failure modes | FailureMode nodes | `triggered-by` → `governed-by` chain |
| Protocol constraints | InteractionProtocol nodes | `constrains-composition` to concept |
| Performance context | PerformanceProfile nodes | `profiled-by` to concept |
| Subsystem context | Subsystem node | `belongs-to` from concept |
| Code examples | Concept attrs | `code_examples` attribute |

---

## Specification Surface Changes

### Existing nodes to modify (4 modify-node mutations)

#### 1. ALG-KK-WEB-IDEAS-DETAIL

**Current description (verbatim from DAG):**
"GET /ideas/{idea_id} route. Fetches Opportunity or Trend node by ID. For
Opportunity: loads linked Concept via opportunity-for edge, evidence via
supported-by edges. For Trend: loads linked Concepts via trend-about edge.
Builds evidence timeline ordered by source_date ascending. Returns
idea_detail.html template with score breakdown, evidence chain, and related
ideas."

**New description:**
"GET /ideas/{idea_id} route. Fetches Opportunity or Trend node by ID. For
each linked Concept (via opportunity-for or trend-about edges), calls
build_concept_brief() to query the full graph depth: problems (identifies-problem),
vulnerabilities (exploits), failure modes (triggered-by→governed-by chain),
kernel invariants (governed-by), interaction protocols (constrains-composition),
performance profiles (profiled-by), prerequisite dependents (prerequisite
reverse), fixes (patches), observations (observes), discussions (discusses),
benchmarks (benchmarks), subsystem (belongs-to), and code examples (concept
attrs). Renders idea_detail.html as a two-layer research brief: verbatim
evidence timeline (text unmodified from node attributes, with source
attribution) + structural analysis sections (pain narrative, blast radius,
invariants, failure modes, dependencies, performance context, code examples).
Evidence ordered by source_date descending."

#### 2. INV-KK-WEB-IDEAS-EVIDENCE-CHAIN

**Current description:** "Idea detail page shows all linked evidence nodes
ordered by source_date"

**New description:** "Idea detail page shows ALL evidence linked to the idea's
concepts via identifies-problem, observes, discusses, benchmarks, rejected-for,
grounded-in, and exploits edges, ordered by source_date descending. Evidence
text (Discussion.title, Observation.claim, Vulnerability.description,
Benchmark.result_summary, Problem.description) is rendered verbatim — never
modified, summarized, or paraphrased. Each evidence item shows its source_date,
kind badge, and the original text with source attribution."

**Current predicate:** "forall Opportunity O displayed at /ideas/{id}. all
nodes N linked via supported-by from O are shown. forall Trend T displayed at
/ideas/{id}. all Concepts linked via trend-about from T are shown. Evidence
sorted by source_date ascending."

**New predicate:** "forall idea I at /ideas/{id}. forall concept C linked to I
via opportunity-for or trend-about. all evidence E linked to C via
identifies-problem, observes, discusses, benchmarks, rejected-for, grounded-in,
or exploits edges are shown with verbatim text from E.attrs. Evidence sorted by
source_date descending."

**New predicateNL:** "The idea detail page displays all evidence nodes linked
to every concept associated with the idea, using concept_timeline() for
traversal. Evidence text is rendered verbatim from node attributes. Evidence is
ordered by source_date descending (most recent first)."

#### 3. ALG-KK-WEB-VULNS-DETAIL

**Current description (verbatim from DAG):**
"GET /vulns/{vuln_id} route. Fetches Vulnerability node by ID. Calls
vulnerability_propagation() to find directly exploited concepts and propagated
at-risk concepts. Renders vuln_detail.html with severity badge, CVSS score,
description, directly exploited concepts, and propagated concepts grouped by
coupling type (dependents, composed_with, shared_invariant)."

**New description:**
"GET /vulns/{vuln_id} route. Fetches Vulnerability node by ID. For each
directly exploited concept (via exploits edge), calls build_concept_brief() to
query: kernel invariants at risk (governed-by), failure modes that would trigger
(triggered-by→governed-by chain), performance profiles affected (profiled-by),
prerequisite dependents (prerequisite reverse), interaction protocols constrained
(constrains-composition), related problems (identifies-problem), related fixes
(patches), subsystem context (belongs-to), and code examples. For propagated
concepts from vulnerability_propagation(), queries name, subsystem, and shared
invariants. Renders vuln_detail.html as a research brief: vulnerability
description, exploited concept briefs with invariants/failure modes/dependencies,
blast radius tree with coupling explanations, affected subsystems, related
fixes."

#### 4. INV-KK-WEB-VULN-PROPAGATION

**Current description:** "Vulnerability detail page shows propagated at-risk
concepts."

**New description:** "Vulnerability detail page shows propagated at-risk
concepts grouped by coupling type (prerequisite dependents, protocol
composition, shared invariants). For each directly exploited concept, the page
shows: the concept's name and description, subsystem context, invariants at
risk with predicate text, failure modes with symptoms, performance implications,
other open problems, and code examples. For each propagated concept: name,
subsystem, and coupling explanation."

**Current predicate:** "forall v in Vulnerability. detail_page(v) shows
vulnerability_propagation(v).propagated"

**New predicate:** "forall v in Vulnerability. detail_page(v) shows
vulnerability_propagation(v).propagated grouped by coupling type. forall c in
vulnerability_propagation(v).direct. detail_page(v) shows
build_concept_brief(c) with invariants, failure_modes, protocols, profiles,
prerequisites, problems, fixes, and code_examples."

**New predicateNL:** "The vulnerability detail page shows full concept briefs
for directly exploited concepts (invariants, failure modes, dependencies,
performance profiles, code examples) and propagated concepts with coupling type
and subsystem context."

### New invariants to add (3 add-node + 9 add-edge mutations)

#### 5. INV-KK-WEB-IDEA-BRIEF-VERBATIM (new)

**Description:** "Evidence text in the idea research brief is rendered verbatim
from node attributes (Discussion.title, Observation.claim, Problem.description,
Benchmark.result_summary, Vulnerability.description). The system never modifies,
summarizes, or paraphrases evidence text. Source attribution (forum/source_type,
URL, source_date) accompanies every evidence item."

**Predicate:** "forall evidence E shown on /ideas/{id}. displayed_text(E) ==
E.attrs[text_field] where text_field is the kind-specific verbatim attribute"

**PredicateNL:** "All evidence displayed on the idea detail page uses the exact
text from node attributes without modification. Each item includes source
attribution."

**Edges:**
- `contains` from `SUB-KK-WEB` to `INV-KK-WEB-IDEA-BRIEF-VERBATIM`
- `checked-at` from `INV-KK-WEB-IDEA-BRIEF-VERBATIM` to `stage-delivery`
- `satisfies` from `ALG-KK-WEB-IDEAS-DETAIL` to `INV-KK-WEB-IDEA-BRIEF-VERBATIM`

#### 6. INV-KK-WEB-IDEA-BRIEF-DEPTH (new)

**Description:** "The idea research brief queries the full graph depth per
linked concept: problems (identifies-problem), vulnerabilities (exploits),
failure modes (triggered-by→governed-by), invariants (governed-by), protocols
(constrains-composition), profiles (profiled-by), prerequisites (prerequisite
reverse), fixes (patches), observations (observes), discussions (discusses),
benchmarks (benchmarks), subsystem (belongs-to), code examples (concept attrs),
and all 5 scores. All available data is rendered — no graph data is omitted."

**Predicate:** "forall concept C linked to idea I. idea_detail(I) renders
build_concept_brief(C) with all 15 data categories populated from graph queries"

**PredicateNL:** "The idea detail page queries and renders the complete graph
neighborhood for each linked concept using build_concept_brief(), covering all
15 data categories."

**Edges:**
- `contains` from `SUB-KK-WEB` to `INV-KK-WEB-IDEA-BRIEF-DEPTH`
- `checked-at` from `INV-KK-WEB-IDEA-BRIEF-DEPTH` to `stage-delivery`
- `satisfies` from `ALG-KK-WEB-IDEAS-DETAIL` to `INV-KK-WEB-IDEA-BRIEF-DEPTH`

#### 7. INV-KK-WEB-VULN-BRIEF-DEPTH (new)

**Description:** "The vulnerability research brief queries the full graph depth
per exploited concept: invariants (governed-by), failure modes
(triggered-by→governed-by), protocols (constrains-composition), profiles
(profiled-by), prerequisites (prerequisite reverse), problems
(identifies-problem), fixes (patches), subsystem (belongs-to), and code
examples. Propagated concepts show their coupling reason and shared structural
elements."

**Predicate:** "forall concept C in vulnerability_propagation(v).direct.
vuln_detail(v) renders build_concept_brief(C). forall concept P in
vulnerability_propagation(v).propagated. vuln_detail(v) shows P.name,
P.subsystem, and coupling_type"

**PredicateNL:** "The vulnerability detail page renders full concept briefs for
directly exploited concepts and summary briefs (name, subsystem, coupling type)
for propagated concepts."

**Edges:**
- `contains` from `SUB-KK-WEB` to `INV-KK-WEB-VULN-BRIEF-DEPTH`
- `checked-at` from `INV-KK-WEB-VULN-BRIEF-DEPTH` to `stage-delivery`
- `satisfies` from `ALG-KK-WEB-VULNS-DETAIL` to `INV-KK-WEB-VULN-BRIEF-DEPTH`

### Total spec mutations: 4 modify-node + 3 add-node + 9 add-edge = 16 mutations

---

## Code Changes — Complete Task Breakdown

### Stage 1: build_concept_brief() + idea_detail rewrite

#### Task 1.1: Create `src/graph/briefing.py`

New module with a single public function. This is the core reusable helper
that both idea_detail and vuln_detail routes will use.

**Function signature:**
```python
def build_concept_brief(
    conn: sqlite3.Connection,
    concept_id: str,
    window_days: int = 90,
) -> dict[str, Any]:
```

**Return dict structure (all keys always present, empty lists/None if no data):**
```python
{
    "concept": {
        "id": str,
        "name": str,                # from attrs.name
        "description": str,          # from attrs.description
        "key_properties": list[str], # from attrs.key_properties
        "tradeoffs": list[str],      # from attrs.tradeoffs
        "design_rationale": str,     # from attrs.design_rationale
    },
    "subsystem": {"id": str, "name": str} | None,
    "scores": {
        "heat": float,
        "pain": float,
        "impact": float,
        "leverage": float,
        "frontier": float,
    },
    "problems": [
        {
            "id": str,
            "title": str,           # REQUIRED_ATTRS["Problem"]
            "description": str,
            "severity": str,         # "critical"|"high"|"medium"|"low"
            "status": str,           # "open"|"partially-addressed"|"resolved"
            "source_date": str,
        },
    ],
    "vulnerabilities": [
        {
            "id": str,
            "cve_id": str,           # REQUIRED_ATTRS["Vulnerability"]
            "title": str,
            "description": str,
            "severity": str,
            "cvss_score": str,
            "affected_versions": str,
            "status": str,
            "source_date": str,
        },
    ],
    "failure_modes": [
        {
            "id": str,
            "symptom": str,          # REQUIRED_ATTRS["FailureMode"]
            "blast_radius": str,
            "recoverability": str,
        },
    ],
    "invariants": [
        {
            "id": str,
            "predicate": str,        # REQUIRED_ATTRS["KernelInvariant"]
            "strength": str,
            "scope": str,
        },
    ],
    "protocols": [
        {
            "id": str,
            "rule": str,             # REQUIRED_ATTRS["InteractionProtocol"]
            "ordering": str,
            "violation_mode": str,
            "participant_concepts": [{"id": str, "name": str}],
                # ^^ other Concepts linked via constrains-composition from same protocol
        },
    ],
    "profiles": [
        {
            "id": str,
            "metric": str,           # REQUIRED_ATTRS["PerformanceProfile"]
            "complexity": str,
            "best_case": str,
            "worst_case": str,
            "typical_case": str,
            "conditions": str,
        },
    ],
    "prerequisites": {
        "depends_on": [{"id": str, "name": str}],
            # Concepts this concept depends on (prerequisite outgoing)
        "depended_on_by": [{"id": str, "name": str}],
            # Concepts that depend on this concept (prerequisite incoming)
    },
    "fixes": [
        {
            "id": str,
            "title": str,            # REQUIRED_ATTRS["Fix"]
            "commit_hash": str,
            "fix_type": str,
            "source_date": str,
            "resolves": [{"id": str, "kind": str, "title": str}],
                # ^^ nodes linked via fixes edge from this Fix
        },
    ],
    "observations": [
        {
            "id": str,
            "claim": str,            # REQUIRED_ATTRS["Observation"] — VERBATIM
            "confidence": str,
            "source_date": str,
        },
    ],
    "discussions": [
        {
            "id": str,
            "title": str,            # REQUIRED_ATTRS["Discussion"] — VERBATIM
            "forum": str,
            "participant_count": int,
            "source_date": str,
        },
    ],
    "benchmarks": [
        {
            "id": str,
            "metric": str,           # REQUIRED_ATTRS["Benchmark"]
            "result_summary": str,   # VERBATIM
            "conditions": str,
            "source_date": str,
        },
    ],
    "timeline": [
        {
            "source_date": str,
            "kind": str,             # node kind
            "id": str,
            "text": str,             # the verbatim display text for this kind
        },
    ],
    "code_examples": [               # from concept.attrs.code_examples or []
        {
            "language": str,
            "code": str,
            "description": str,
        },
    ],
}
```

**Implementation details — queries to perform (in order):**

1. **Fetch concept node:**
   ```sql
   SELECT id, kind, attrs FROM nodes WHERE id = ? AND kind = 'Concept'
   ```
   Parse attrs JSON. Extract name, description, key_properties, tradeoffs,
   design_rationale, code_examples.

2. **Fetch subsystem:**
   ```sql
   SELECT n.id, json_extract(n.attrs, '$.name') as name
   FROM edges e JOIN nodes n ON e.target_id = n.id
   WHERE e.kind = 'belongs-to' AND e.source_id = ? AND n.kind = 'Subsystem'
   ```
   Take first result (a concept belongs to exactly one subsystem).

3. **Compute scores:**
   Call existing `compute_all_scores(conn, concept_id, window_days=window_days)`
   from `src/graph/scoring.py`.

4. **Fetch problems:**
   Call existing `get_linked_problems(conn, concept_id)` from
   `src/graph/scoring.py`. Each returns dict with id + all attrs from
   REQUIRED_ATTRS["Problem"]. Sort by severity (critical > high > medium > low).

5. **Fetch vulnerabilities:**
   Call existing `get_linked_vulns(conn, concept_id)` from
   `src/graph/scoring.py`. Sort by cvss_score descending.

6. **Fetch failure modes:**
   Call existing `get_linked_failure_modes(conn, concept_id)` from
   `src/graph/scoring.py`. Returns dicts with id + FailureMode attrs.

7. **Fetch invariants, protocols, profiles (via transitive_impact):**
   Call existing `transitive_impact(conn, concept_id)` from
   `src/graph/engine.py`. Returns dict with keys: invariants, failure_modes,
   protocols, profiles, goals, compatibilities, comparatives, scenarios.
   Extract invariants, protocols, profiles from this result. The failure_modes
   from transitive_impact may overlap with step 6 — deduplicate by id.

8. **Resolve protocol participant concepts:**
   For each InteractionProtocol in the result, query the other Concepts it
   constrains:
   ```sql
   SELECT n.id, json_extract(n.attrs, '$.name') as name
   FROM edges e JOIN nodes n ON e.target_id = n.id
   WHERE e.kind = 'constrains-composition' AND e.source_id = ?
     AND e.target_id != ? AND n.kind = 'Concept'
   ```
   (source_id = protocol id, exclude current concept_id)

9. **Fetch prerequisites (outgoing — what this concept depends on):**
   ```sql
   SELECT n.id, json_extract(n.attrs, '$.name') as name
   FROM edges e JOIN nodes n ON e.target_id = n.id
   WHERE e.kind = 'prerequisite' AND e.source_id = ? AND n.kind = 'Concept'
   ```

10. **Fetch prerequisites (incoming — what depends on this concept):**
    ```sql
    SELECT n.id, json_extract(n.attrs, '$.name') as name
    FROM edges e JOIN nodes n ON e.source_id = n.id
    WHERE e.kind = 'prerequisite' AND e.target_id = ? AND n.kind = 'Concept'
    ```

11. **Fetch fixes (patches edge incoming to concept):**
    ```sql
    SELECT n.id, n.attrs FROM nodes n
    JOIN edges e ON e.source_id = n.id
    WHERE e.kind = 'patches' AND e.target_id = ? AND n.kind = 'Fix'
    ```
    For each Fix, also query what it resolves:
    ```sql
    SELECT n.id, n.kind, json_extract(n.attrs, '$.title') as title,
           json_extract(n.attrs, '$.cve_id') as cve_id
    FROM edges e JOIN nodes n ON e.target_id = n.id
    WHERE e.kind = 'fixes' AND e.source_id = ?
    ```

12. **Fetch discussions:**
    ```sql
    SELECT n.id, n.attrs FROM nodes n
    JOIN edges e ON e.source_id = n.id
    WHERE e.kind = 'discusses' AND e.target_id = ? AND n.kind = 'Discussion'
    ```
    Sort by source_date descending.

13. **Fetch observations:**
    ```sql
    SELECT n.id, n.attrs FROM nodes n
    JOIN edges e ON e.source_id = n.id
    WHERE e.kind = 'observes' AND e.target_id = ? AND n.kind = 'Observation'
    ```
    Sort by source_date descending.

14. **Fetch benchmarks:**
    ```sql
    SELECT n.id, n.attrs FROM nodes n
    JOIN edges e ON e.source_id = n.id
    WHERE e.kind = 'benchmarks' AND e.target_id = ? AND n.kind = 'Benchmark'
    ```
    Sort by source_date descending.

15. **Build unified timeline:**
    Call existing `concept_timeline(conn, concept_id)` from
    `src/graph/engine.py`. For each item in the timeline, extract the
    kind-specific verbatim text:
    - Problem → `title`
    - Observation → `claim`
    - Discussion → `title`
    - Benchmark → `result_summary`
    - Vulnerability → `description` (first 200 chars)
    - Rejection → `proposal_title`
    - Proposal → `name`
    Sort descending (reverse the ASC result from concept_timeline).

16. **Extract code examples:**
    From concept attrs `code_examples` field (list of dicts with language,
    code, description). Return as-is or empty list if absent.


#### Task 1.2: Create `tests/test_graph_briefing.py`

New test file. Fixture creates a Concept with full graph neighborhood.

**Fixture `brief_db`:**
- 1 Subsystem ("Memory Management")
- 1 Concept ("SLUB Allocator") with belongs-to edge to subsystem
- 1 Source + Evidence pair (for extracted-from provenance)
- 1 Advisory (for assessed-by provenance)
- 1 Problem ("UAF in SLUB") with identifies-problem edge to concept
- 1 Vulnerability ("CVE-TEST-001") with exploits edge to concept
- 1 KernelInvariant ("slab objects must...") with governed-by edge to concept
- 1 FailureMode ("memory corruption") with triggered-by edge to invariant
- 1 InteractionProtocol ("SLUB↔Page Allocator") with constrains-composition edges
  to concept AND a second concept ("Page Cache")
- 1 PerformanceProfile ("alloc latency") with profiled-by edge to concept
- 1 second Concept ("Page Cache") with prerequisite edge FROM concept TO it
- 1 third Concept ("Buddy Allocator") with prerequisite edge FROM it TO concept
- 1 Fix ("fix UAF") with patches edge to concept and fixes edge to problem
- 1 Discussion ("SLUB discussion") with discusses edge to concept
- 1 Observation ("SLUB observation") with observes edge to concept
- 1 Benchmark ("throughput test") with benchmarks edge to concept
- All provenance edges (extracted-from to Evidence, sourced-from to Source)

**Tests (16 tests):**

| Test name | Assertion |
|-----------|-----------|
| `test_brief_returns_all_keys` | Return dict has all 15 top-level keys |
| `test_brief_concept_fields` | concept.name, concept.description populated |
| `test_brief_subsystem` | subsystem.name == "Memory Management" |
| `test_brief_scores_all_five` | scores dict has heat, pain, impact, leverage, frontier |
| `test_brief_problems` | problems list has 1 entry with title="UAF in SLUB" |
| `test_brief_problems_sorted_by_severity` | critical before high before medium |
| `test_brief_vulnerabilities` | vulnerabilities list has 1 entry with cve_id |
| `test_brief_failure_modes` | failure_modes list has 1 entry with symptom |
| `test_brief_invariants` | invariants list has 1 entry with predicate text |
| `test_brief_protocols_with_participants` | protocols list has 1 entry with participant_concepts containing "Page Cache" |
| `test_brief_profiles` | profiles list has 1 entry with metric |
| `test_brief_prerequisites_depends_on` | depends_on has "Page Cache" |
| `test_brief_prerequisites_depended_on_by` | depended_on_by has "Buddy Allocator" |
| `test_brief_fixes_with_resolves` | fixes list has 1 entry, resolves contains the problem |
| `test_brief_discussions` | discussions list has 1 entry with title |
| `test_brief_observations` | observations list has 1 entry with claim |
| `test_brief_benchmarks` | benchmarks list has 1 entry with result_summary |
| `test_brief_timeline_sorted_desc` | timeline ordered by source_date descending |
| `test_brief_code_examples` | code_examples extracted from concept attrs |
| `test_brief_empty_concept` | Concept with no edges returns empty lists everywhere |


#### Task 1.3: Rewrite `idea_detail()` route in `src/web/routes.py` (lines 563-648)

**Replace the entire function** (lines 563-648) with:

```python
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

    # Resolve linked concept IDs
    if node["kind"] == "Opportunity":
        edge_kind = "opportunity-for"
    else:
        edge_kind = "trend-about"
    concept_edges = conn.execute(
        "SELECT target_id FROM edges WHERE kind = ? AND source_id = ?",
        (edge_kind, idea_id),
    ).fetchall()
    concept_ids = [e[0] for e in concept_edges]

    # Build full briefs for each linked concept
    briefs = []
    for cid in concept_ids:
        brief = build_concept_brief(conn, cid)
        briefs.append(brief)

    # Merge evidence timelines across all concepts, sorted desc
    all_evidence = []
    seen_evidence_ids = set()
    for b in briefs:
        for ev in b["timeline"]:
            if ev["id"] not in seen_evidence_ids:
                seen_evidence_ids.add(ev["id"])
                all_evidence.append(ev)
    all_evidence.sort(key=lambda x: x.get("source_date") or "", reverse=True)

    # Compute aggregate pain narrative
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

    # Related ideas (other Opportunity/Trend nodes on overlapping concepts)
    related_ideas = []
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
```

**New import to add at top of routes.py:**
```python
from graph.briefing import build_concept_brief
```


#### Task 1.4: Rewrite `src/web/templates/idea_detail.html` (replace all 79 lines)

Template sections in order:

**Section 1: Header**
- Back link to /ideas
- Title from node.attrs.title
- Kind badge (Opportunity or Trend)
- Frontier score and confidence (if Opportunity)

**Section 2: Why This Matters (analysis layer)**
- Pain narrative sentence: "Pain score of {score} driven by {n} active
  vulnerabilities ({critical} critical, {high} high) and {n} open problems."
- Blast radius sentence: "{n} kernel components depend on {concept_name}:
  {list of dependent names}. Changes here propagate to all of them."
- Subsystem badge
- Show only if briefs is non-empty; iterate briefs if >1 concept

**Section 3: Scores table**
- For each brief: concept name + 5 scores in a table row
- If only 1 brief, just show the 5 scores

**Section 4: Evidence Timeline (evidence layer — VERBATIM)**
- Reverse chronological list
- Each entry: date | kind badge | verbatim text
- Kind badge colors: CVE=red, Discussion=blue, Observation=green,
  Benchmark=orange, Problem=yellow
- Text field per kind:
  - Vulnerability → `"[CVE-xxx] " + description`
  - Discussion → `"[forum] " + title`
  - Observation → claim
  - Problem → `"[severity] " + title`
  - Benchmark → `metric + ": " + result_summary`
- Wrap in `{% if all_evidence %}`

**Section 5: Active Vulnerabilities (analysis layer)**
- For each brief, for each vulnerability, sorted by CVSS desc:
  - Severity badge (critical/high/medium/low)
  - CVE ID and CVSS score
  - Title — verbatim from attrs.title
  - Description — verbatim from attrs.description
  - Status and affected versions
- Wrap in `{% if brief.vulnerabilities %}`

**Section 6: Open Problems (evidence layer — VERBATIM)**
- For each brief, for each problem, sorted by severity:
  - Severity badge
  - Title — verbatim
  - Description — verbatim
  - Status
- Wrap in `{% if brief.problems %}`

**Section 7: Structural Constraints (analysis layer)**
- Sub-section "Invariants governing {concept_name}":
  - For each invariant: predicate text (verbatim from attrs), strength, scope
- Sub-section "Failure Modes":
  - For each failure mode: symptom (verbatim), blast_radius, recoverability
- Sub-section "Interaction Protocols":
  - For each protocol: rule text, participant concepts listed
- Wrap each sub-section in `{% if data %}`

**Section 8: Dependency Impact (analysis layer)**
- Tree view: "Components that depend on {concept_name}:"
  - List of depended_on_by names with subsystem context (if available from
    a second brief query — or just name)
- "Dependencies:" — list of depends_on names
- Wrap in `{% if prerequisites has data %}`

**Section 9: Performance Context (analysis layer)**
- For each profile: metric, complexity, best/worst/typical case, conditions
- Wrap in `{% if brief.profiles %}`

**Section 10: Code Examples**
- For each code example: language badge, description, code block with
  `<pre><code>` and language class for syntax highlighting
- Wrap in `{% if brief.code_examples %}`

**Section 11: Related Ideas**
- Same as current implementation but with type badge
- Wrap in `{% if related_ideas %}`

**Every section** wrapped in `{% if data %}` so absent data produces no
empty headers. Sections that have no data are completely invisible.


#### Task 1.5: Add idea_detail route tests to `tests/test_web.py`

Add to the existing `test_web.py` file, using a fixture that creates the
necessary graph data (similar to brief_db but going through export/snapshot).

| Test name | What it checks |
|-----------|---------------|
| `test_idea_detail_200` | Route returns 200 for valid Opportunity |
| `test_idea_detail_shows_scores` | Response contains score values |
| `test_idea_detail_shows_evidence_verbatim` | Evidence text matches node attr exactly |
| `test_idea_detail_shows_vuln_section` | CVE IDs appear in response |
| `test_idea_detail_shows_invariants` | Invariant predicate text appears |
| `test_idea_detail_shows_prerequisites` | Dependent concept names appear |
| `test_idea_detail_404_for_missing` | Returns 404 for nonexistent ID |
| `test_idea_detail_404_for_non_idea` | Returns 404 for Concept node |


#### Task 1.6: Spec mutations for Stage 1

Write spec-author envelope with these mutations:
- `modify-node` ALG-KK-WEB-IDEAS-DETAIL (new description per above)
- `modify-node` INV-KK-WEB-IDEAS-EVIDENCE-CHAIN (new description, predicate, predicateNL)
- `add-node` INV-KK-WEB-IDEA-BRIEF-VERBATIM
- `add-edge` contains SUB-KK-WEB → INV-KK-WEB-IDEA-BRIEF-VERBATIM
- `add-edge` checked-at INV-KK-WEB-IDEA-BRIEF-VERBATIM → stage-delivery
- `add-edge` satisfies ALG-KK-WEB-IDEAS-DETAIL → INV-KK-WEB-IDEA-BRIEF-VERBATIM
- `add-node` INV-KK-WEB-IDEA-BRIEF-DEPTH
- `add-edge` contains SUB-KK-WEB → INV-KK-WEB-IDEA-BRIEF-DEPTH
- `add-edge` checked-at INV-KK-WEB-IDEA-BRIEF-DEPTH → stage-delivery
- `add-edge` satisfies ALG-KK-WEB-IDEAS-DETAIL → INV-KK-WEB-IDEA-BRIEF-DEPTH

Total: 2 modify-node + 2 add-node + 6 add-edge = 10 mutations


### Stage 2: vuln_detail rewrite

#### Task 2.1: Rewrite `vuln_detail()` route in `src/web/routes.py` (lines 780-840)

**Replace the entire function** with:

```python
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

    # Full propagation analysis
    prop = vulnerability_propagation(conn, vuln_id)

    # Build full briefs for each directly exploited concept
    direct_briefs = []
    for cid in prop["direct"]:
        brief = build_concept_brief(conn, cid)
        direct_briefs.append(brief)

    # For propagated concepts: lighter query — name, subsystem, coupling type
    propagated_details = []
    seen_ids = set(prop["direct"])
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
                    "coupled_to": cid,  # which direct concept this is coupled to
                })

    # Coupling type labels for template
    coupling_labels = {
        "dependents": "Prerequisite dependency",
        "composed_with": "Protocol composition",
        "shared_invariant": "Shared invariant governance",
    }

    # Fixes for this vulnerability
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

    # Affected subsystems (deduplicated)
    affected_subsystems = []
    seen_subs = set()
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
```


#### Task 2.2: Rewrite `src/web/templates/vuln_detail.html` (replace all 58 lines)

Template sections in order:

**Section 1: Header**
- Back link to /vulns
- CVE ID as h1
- Severity badge (colored: critical=red, high=orange, medium=yellow, low=gray)
- CVSS score, status, affected versions, disclosure date

**Section 2: Description (evidence layer — VERBATIM)**
- Full description text from attrs.description, unmodified
- Wrap in `{% if attrs.description %}`

**Section 3: Affected Subsystems**
- Simple list of affected subsystem names
- Wrap in `{% if affected_subsystems %}`

**Section 4: Directly Exploited Concepts (one section per concept)**
For each `direct_brief` in `direct_briefs`:
- Concept name as h2, subsystem badge
- Concept description (from brief.concept.description)
- Sub-section "Invariants at Risk":
  - For each invariant: predicate text, strength, scope
- Sub-section "Failure Modes if Exploited":
  - For each failure mode: symptom, blast_radius, recoverability
- Sub-section "Performance Implications":
  - For each profile: metric, complexity, worst_case
- Sub-section "Other Open Problems":
  - For each problem: severity badge, title, description
- Sub-section "Code Context":
  - For each code example: language badge, code block
- Sub-section "Dependencies":
  - depended_on_by list with names

All sub-sections wrapped in `{% if data %}`.

**Section 5: Blast Radius**
- "N additional concepts at risk through coupling"
- Group by coupling_type using coupling_labels:
  - "Prerequisite dependency" → list of concept names + subsystems
  - "Protocol composition" → list of concept names + subsystems
  - "Shared invariant governance" → list of concept names + subsystems
- Each entry shows: concept name, subsystem, "coupled to {direct_concept_name}"
- Wrap in `{% if propagated_details %}`

**Section 6: Related Fixes**
- For each fix: commit hash (monospace), fix type badge, title, date
- If no fixes: "No fixes for this vulnerability yet."
- Always show this section (it's informative even when empty)


#### Task 2.3: Add vuln_detail route tests to `tests/test_web.py`

| Test name | What it checks |
|-----------|---------------|
| `test_vuln_detail_200` | Route returns 200 for valid Vulnerability |
| `test_vuln_detail_shows_concept_brief` | Exploited concept name + description appear |
| `test_vuln_detail_shows_invariants_at_risk` | Invariant predicate text appears |
| `test_vuln_detail_shows_blast_radius` | Propagated concept names appear |
| `test_vuln_detail_shows_coupling_type` | Coupling type labels appear |
| `test_vuln_detail_shows_fixes` | Fix commit hash appears |
| `test_vuln_detail_shows_subsystems` | Affected subsystem names appear |
| `test_vuln_detail_404_for_missing` | Returns 404 for nonexistent ID |
| `test_vuln_detail_404_for_non_vuln` | Returns 404 for Concept node |


#### Task 2.4: Spec mutations for Stage 2

Write spec-author envelope with these mutations:
- `modify-node` ALG-KK-WEB-VULNS-DETAIL (new description per above)
- `modify-node` INV-KK-WEB-VULN-PROPAGATION (new description, predicate, predicateNL)
- `add-node` INV-KK-WEB-VULN-BRIEF-DEPTH
- `add-edge` contains SUB-KK-WEB → INV-KK-WEB-VULN-BRIEF-DEPTH
- `add-edge` checked-at INV-KK-WEB-VULN-BRIEF-DEPTH → stage-delivery
- `add-edge` satisfies ALG-KK-WEB-VULNS-DETAIL → INV-KK-WEB-VULN-BRIEF-DEPTH

Total: 2 modify-node + 1 add-node + 3 add-edge = 6 mutations

---

## Files NOT Modified

| File | Why untouched |
|------|--------------|
| `src/web/templates/ideas.html` | List page confirmed good by user |
| `src/web/templates/vulns.html` | List page confirmed good by user |
| `src/web/templates/radar.html` | Not in scope |
| `src/web/templates/dashboard.html` | Not in scope |
| `src/graph/scoring.py` | All scoring functions exist: `compute_all_scores()`, `get_linked_problems()`, `get_linked_vulns()`, `get_linked_failure_modes()`, `pain_score()`, `heat_score()`, `vulnerability_propagation()` |
| `src/graph/engine.py` | All graph queries exist: `concept_timeline()`, `transitive_impact()`, `get_node()` |
| `src/graph/schema.py` | No schema changes needed |
| `src/graph/inference.py` | No inference changes needed |
| `src/mcp_server/server.py` | MCP tools unaffected |
| `src/export/exporter.py` | Export unaffected |
| `src/ingest/*.py` | Ingestion unaffected |

---

## Existing Functions Reused (no new graph code needed)

| Function | Module | Lines | What it provides |
|----------|--------|-------|-----------------|
| `compute_all_scores(conn, cid, window_days)` | scoring.py:188-200 | 12 | All 5 scores dict |
| `get_linked_problems(conn, cid)` | scoring.py:43-53 | 10 | Problem nodes via identifies-problem |
| `get_linked_vulns(conn, cid)` | scoring.py:70-80 | 10 | Vulnerability nodes via exploits |
| `get_linked_failure_modes(conn, cid)` | scoring.py:56-67 | 11 | FailureModes via triggered-by→governed-by |
| `transitive_impact(conn, cid)` | engine.py:379-429 | 50 | invariants, protocols, profiles, failure_modes, goals, compatibilities, comparatives, scenarios |
| `concept_timeline(conn, cid)` | engine.py:542-559 | 17 | All evidence ordered by source_date ASC |
| `vulnerability_propagation(conn, vid)` | scoring.py:227-293 | 66 | Direct + propagated concepts with coupling |
| `display_name_for_node(kind, attrs, id)` | routes.py:68-83 | 15 | Human-readable names |
| `get_node(conn, id)` | engine.py | — | Single node fetch |

---

## Dependency Graph

```
Stage 1:
  Task 1.1  build_concept_brief()        ← foundation for both stages
  Task 1.2  briefing tests               ← validates 1.1
  Task 1.3  idea_detail() route rewrite  ← depends on 1.1
  Task 1.4  idea_detail.html template    ← depends on 1.3 (needs template context)
  Task 1.5  idea route tests             ← depends on 1.3 + 1.4
  Task 1.6  spec mutations               ← independent (submit before impl)

Stage 2:
  Task 2.1  vuln_detail() route rewrite  ← depends on 1.1 (reuses build_concept_brief)
  Task 2.2  vuln_detail.html template    ← depends on 2.1
  Task 2.3  vuln route tests             ← depends on 2.1 + 2.2
  Task 2.4  spec mutations               ← independent (submit before impl)
```

---

## Estimated Effort

| Stage | Tasks | New files | Modified files | New tests | Est. lines |
|-------|-------|-----------|----------------|-----------|------------|
| 1 | 6 | 2 (briefing.py, test_graph_briefing.py) | 2 (routes.py, idea_detail.html) | ~20 | ~500 |
| 2 | 4 | 0 | 2 (routes.py, vuln_detail.html) | ~9 | ~300 |
| **Total** | **10** | **2** | **4** | **~29** | **~800** |

---

## Implementation Commands

Stage 1:
```
/cb-green — Research Brief UX Stage 1: build_concept_brief() helper + idea_detail rewrite

Create src/graph/briefing.py with build_concept_brief() function that queries
the full graph depth for a concept (15 data categories: problems, vulns, failure
modes, invariants, protocols, profiles, prerequisites, fixes, discussions,
observations, benchmarks, subsystem, scores, timeline, code examples). Rewrite
idea_detail() route in src/web/routes.py to call build_concept_brief() per
linked concept. Rewrite src/web/templates/idea_detail.html as a research brief
with sections: Why This Matters, Scores, Evidence Timeline (verbatim), Active
Vulnerabilities, Open Problems, Structural Constraints, Dependency Impact,
Performance Context, Code Examples, Related Ideas. See
docs/plans/research-brief-ux-sprint.md for complete specification.
```

Stage 2:
```
/cb-green — Research Brief UX Stage 2: vuln_detail rewrite

Rewrite vuln_detail() route in src/web/routes.py to call build_concept_brief()
for directly exploited concepts and lighter queries for propagated concepts.
Rewrite src/web/templates/vuln_detail.html as a research brief with sections:
Description, Affected Subsystems, Directly Exploited Concepts (with invariants,
failure modes, dependencies, performance, code), Blast Radius (propagated
concepts grouped by coupling type with explanations), Related Fixes. See
docs/plans/research-brief-ux-sprint.md for complete specification.
```
