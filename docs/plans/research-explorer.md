# Plan: Research Explorer — Dedicated View for Novel Kernel Research Ideas

**Status:** Ready for implementation
**Date:** 2026-07-02
**Prerequisite:** actionable-idea-cards.md (all stages complete)
**Goal:** A dedicated page that surfaces concepts where active research is happening — novel ideas, improvements under exploration, and research directions not yet established — with feasibility and impact analysis per concept.

---

## Problem Statement

The current idea feed (`/ideas`) ranks Opportunity and Trend nodes by frontier
score. It's optimized to surface **problems and risks** — the frontier formula
(`heat*0.3 + pain*0.3 + leverage*0.3 - solved*10`) weights pain and leverage
equally with heat. A concept with 5 critical vulnerabilities and no recent
discussion scores the same frontier as one with intense research activity and
no known issues.

The client wants something different: a view that highlights **novel research
directions** — concepts where the knowledge graph shows active exploration,
unresolved questions, and potential for breakthrough. Not "what's broken" but
"what's being investigated and what could we gain from it."

### What the current system lacks

1. **No research-specific ranking.** Frontier score conflates "actively
   discussed" with "actively broken." A concept with high pain but no
   discussions scores well. The explorer needs to rank by research signals
   specifically: discussion density, observation recency, proposal activity,
   benchmark diversity, evidence source diversity.

2. **No feasibility assessment.** The current idea_detail shows motivation
   categories and blast radius, but doesn't assess: How hard is this to
   implement? What's the prerequisite chain depth? How many subsystems does
   it cross? Are there existing proposals or fixes that partially address it?

3. **No impact projection.** The blast radius shows what depends on a concept,
   but doesn't synthesize: If this research direction succeeds, what
   performance gains are expected? How many problems does it address? What
   failure modes does it eliminate?

4. **No research stage classification.** The graph has `implemented-in` edges
   with maturity (`production`, `experimental`, `deprecated`, `removed`) but
   this isn't surfaced. A concept in `experimental` stage in one kernel is
   a very different research signal from one in `production` everywhere.

5. **No evidence source diversity.** Trend detection counts distinct source
   URLs (strength), but this isn't visible on the detail page. A concept
   discussed by 8 independent research groups is a much stronger research
   signal than one discussed in 8 posts by the same person.

---

## Existing Infrastructure to Build On

### Scoring (src/graph/scoring.py)

| Score | Formula | Research Relevance |
|-------|---------|-------------------|
| heat | count of evidence edges (discusses, observes, benchmarks, grounded-in) in 30-day window | Direct measure of research activity |
| pain | problems*2 + failure_modes*3 + vulns*5*cvss_weight | Problem pressure, not research activity |
| impact | count of downstream nodes via transitive_impact | Size of blast radius if concept changes |
| leverage | sum of problem severity weights | How severe the problems are |
| frontier | heat*0.3 + pain*0.3 + leverage*0.3 - solved*10 | Composite, pain-biased |

**Gap:** No score for research momentum, evidence diversity, or feasibility.

### Inference (src/graph/inference.py)

- `detect_trends()` — finds concepts with >= 3 distinct source URLs in 90 days.
  Strength = distinct URL count. This is the closest thing to a "research
  activity" detector, but it's binary (created or not) and doesn't graduate.
- `detect_opportunities()` — finds concepts with frontier >= 8.0 and >= 1
  supporting evidence. Confidence = evidence_count / (evidence_count + 5).
- `generate_idea_feed()` — combines both, sorts by frontier_score desc.

**Gap:** No momentum (is heat increasing or decreasing?), no evidence type
diversity score, no feasibility scoring.

### Briefing (src/graph/briefing.py)

- `build_concept_brief()` — 17-step query returning 15-key dict with all
  evidence. Already includes source_url on every item (Stage 1 of
  actionable-idea-cards).
- `classify_motivations()` — 7 orthogonal categories with blast_radius,
  actionable, cross_links (Stage 2 of actionable-idea-cards).
- `build_argument_paragraph()` — deterministic narrative from graph data.

**Available:** All the rendering infrastructure from idea_detail can be reused.

### Edge types signaling research activity

| Edge | Source → Target | Signal |
|------|----------------|--------|
| `discusses` | Discussion → Concept | Community exploring the topic |
| `observes` | Observation → Concept | Empirical findings |
| `benchmarks` | Benchmark → Concept | Performance measurement |
| `grounded-in` | Proposal → Concept | Future work proposals |
| `resulted-in` | Discussion → Proposal/Rejection | Discussion outcomes |
| `addresses` | Proposal → Problem | Proposed solutions |
| `implemented-in` | Concept → Kernel | Maturity stage (experimental/production) |

### Edge types signaling established/mature

| Edge | Source → Target | Signal |
|------|----------------|--------|
| `fixes` | Fix → Problem/Vulnerability | Issue resolved |
| `patches` | Fix → Concept | Concept has patches |
| solved_confidence | (computed) | Ratio of resolved problems |

---

## Design

### New Scoring: Research Score

A new pure function `research_score(conn, concept_id, window_days=90)` in
`src/graph/scoring.py` that computes a composite score optimized for
research novelty rather than problem pressure.

**Formula:**

```python
research_score = (
    discussion_density * 0.25      # Recent discussion activity
    + observation_recency * 0.20   # Fresh empirical findings
    + evidence_diversity * 0.20    # Multiple independent sources
    + proposal_activity * 0.15     # Active proposals grounded in concept
    + benchmark_coverage * 0.10    # Performance data available
    + novelty_bonus * 0.10         # Low solved ratio + no/few fixes
)
```

**Component calculations:**

1. **discussion_density** (0-∞):
   Count of Discussion nodes linked via `discusses` edge with source_date
   within window_days. Weighted by `participant_count` if available:
   ```python
   sum(min(d.participant_count, 50) / 10 for d in discussions_in_window)
   ```
   A 50-participant discussion counts 5x more than a 10-participant one.
   Capped at 50 to avoid single-thread dominance.

2. **observation_recency** (0-∞):
   Count of Observation nodes within window_days, weighted by confidence:
   ```python
   sum(o.confidence for o in observations_in_window)
   ```
   High-confidence recent observations are the strongest research signal.

3. **evidence_diversity** (0-∞):
   Count of distinct Source URLs across all evidence linked to concept.
   Uses the same provenance chain as build_concept_brief step 17:
   ```python
   distinct_sources = set()
   for ev_id in all_evidence_ids:
       url = source_urls.get(ev_id, "")
       if url:
           distinct_sources.add(url)
   diversity = len(distinct_sources)
   ```
   This directly measures independent research attention.

4. **proposal_activity** (0-∞):
   Count of Proposal nodes linked via `grounded-in` with status != "rejected":
   ```python
   sum(1 for p in proposals if p.status != "rejected") * 2.0
   ```
   Active proposals signal research direction; rejected ones don't.

5. **benchmark_coverage** (0-∞):
   Count of Benchmark nodes within window_days:
   ```python
   len(benchmarks_in_window) * 1.5
   ```
   Benchmarks signal quantitative research activity.

6. **novelty_bonus** (0-10):
   Inverse of solved_confidence, rewarding unsolved concepts:
   ```python
   solved = _solved_confidence(conn, concept_id)
   fix_count = len(get_linked_fixes(conn, concept_id))
   novelty = (1.0 - solved) * 5.0
   if fix_count == 0:
       novelty += 5.0  # No fixes at all = truly novel area
   elif fix_count <= 2:
       novelty += 2.0  # Few fixes = early exploration
   ```

**Properties:**
- Pure function, deterministic
- Same concept + same graph state = same score
- Does not call any LLM
- Returns float >= 0.0

### New Scoring: Feasibility Score

A new pure function `feasibility_score(conn, concept_id)` that estimates
how difficult it would be to implement changes to this concept.

**Formula:**

```python
feasibility_score = max(0.0, 10.0 - (
    prerequisite_depth * 1.5       # Deep dependency chain = harder
    + cross_subsystem_penalty * 2.0 # Crossing subsystems = harder
    + invariant_constraint * 1.0   # Many invariants = more constraints
    + protocol_complexity * 1.0    # Many protocols = more coordination
))
```

**Component calculations:**

1. **prerequisite_depth** (0-∞):
   Length of longest `prerequisite` chain from concept:
   ```python
   depth = 0
   visited = set()
   queue = [concept_id]
   while queue:
       next_queue = []
       for cid in queue:
           prereqs = conn.execute(
               "SELECT target_id FROM edges WHERE kind='prerequisite' AND source_id=?",
               (cid,)
           ).fetchall()
           for (tid,) in prereqs:
               if tid not in visited:
                   visited.add(tid)
                   next_queue.append(tid)
       if next_queue:
           depth += 1
       queue = next_queue
   ```
   Depth 0 = standalone concept. Depth 3+ = deeply interdependent.

2. **cross_subsystem_penalty** (0 or 1):
   Whether concept's prerequisites span multiple subsystems:
   ```python
   subsystems = set()
   for prereq in all_prerequisites:
       sub = get_subsystem(conn, prereq.id)
       if sub:
           subsystems.add(sub.name)
   penalty = 1 if len(subsystems) > 1 else 0
   ```

3. **invariant_constraint** (0-∞):
   Count of KernelInvariant nodes governed by this concept:
   ```python
   len(brief["invariants"]) * 0.5
   ```
   Each invariant is a constraint that must be preserved.

4. **protocol_complexity** (0-∞):
   Count of InteractionProtocol nodes constraining this concept:
   ```python
   len(brief["protocols"]) * 0.5
   ```

**Properties:**
- Returns float in range [0, 10]. Higher = more feasible.
- 10 = standalone concept, no constraints
- 0 = deeply interconnected, many constraints
- Pure function, deterministic

### New Scoring: Impact Projection

A new pure function `impact_projection(conn, concept_id)` that estimates
the benefit if research on this concept succeeds.

**Returns a dict:**

```python
{
    "problems_addressed": int,       # Problems linked to concept (open)
    "vulns_mitigated": int,          # Vulnerabilities exploiting concept
    "failure_modes_eliminated": int, # FailureModes in triggered-by chain
    "dependent_components": int,     # Concepts that prerequisite this one
    "performance_metrics": int,      # PerformanceProfiles measuring concept
    "subsystems_affected": int,      # Subsystems concept touches
    "total_impact": float,           # Weighted composite
}
```

**total_impact formula:**
```python
total_impact = (
    problems_addressed * 2.0
    + vulns_mitigated * 5.0
    + failure_modes_eliminated * 3.0
    + dependent_components * 1.0
    + performance_metrics * 1.5
    + subsystems_affected * 2.0
)
```

All data is already available from `build_concept_brief()` and
`transitive_impact()`.

### New Route: `/research`

A new GET route in `src/web/routes.py` that renders the research explorer.

**Route handler: `research_explorer()`**

```python
@app.get("/research", response_class=HTMLResponse)
async def research_explorer(
    request: Request,
    min_research: float = Query(0.0, ge=0),
    min_feasibility: float = Query(0.0, ge=0),
    window_days: int = Query(90, ge=1, le=365),
    sort_by: str = Query("research", regex="^(research|feasibility|impact|frontier)$"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=5, le=100),
):
```

**Data flow:**

1. List all Concept nodes
2. For each concept, compute:
   - `research_score(conn, concept_id, window_days)`
   - `feasibility_score(conn, concept_id)`
   - `impact_projection(conn, concept_id)`
   - `compute_all_scores(conn, concept_id, window_days)` (existing 5 scores)
3. Filter by `min_research` and `min_feasibility`
4. Sort by `sort_by` parameter (default: research score desc)
5. Paginate
6. For the top concepts on the current page, also compute:
   - `build_concept_brief(conn, concept_id, window_days)`
   - `classify_motivations(brief)` — to get motivation categories
   - Maturity info from `implemented-in` edges
   - Evidence source diversity (distinct source URLs from brief)

**Template context:**

```python
{
    "concepts": [
        {
            "id": str,
            "name": str,
            "description": str,
            "subsystem": str | None,
            "research_score": float,
            "feasibility_score": float,
            "impact": {
                "problems_addressed": int,
                "vulns_mitigated": int,
                "failure_modes_eliminated": int,
                "dependent_components": int,
                "performance_metrics": int,
                "subsystems_affected": int,
                "total_impact": float,
            },
            "scores": {"heat", "pain", "impact", "leverage", "frontier"},
            "motivations": list[dict],  # from classify_motivations
            "evidence_diversity": int,   # distinct source URLs
            "maturity": str | None,      # from implemented-in edge
            "proposals": list[dict],     # Proposal nodes grounded-in concept
            "discussion_count": int,     # recent discussions
            "observation_count": int,    # recent observations
            "benchmark_count": int,      # recent benchmarks
        },
        ...
    ],
    "min_research": float,
    "min_feasibility": float,
    "window_days": int,
    "sort_by": str,
    "page": int,
    "per_page": int,
    "has_next": bool,
}
```

### New Route: `/research/{concept_id}`

A detail page for a single research concept. Reuses much of the idea_detail
infrastructure but adds research-specific sections.

**Route handler: `research_detail()`**

```python
@app.get("/research/{concept_id}", response_class=HTMLResponse)
async def research_detail(request: Request, concept_id: str):
```

**Data flow:**

1. Fetch concept node (must be kind=Concept)
2. `build_concept_brief(conn, concept_id)` — full 17-step brief
3. `classify_motivations(brief)` — 7 categories with enriched evidence
4. `build_argument_paragraph(node_attrs, [brief], motivations)` — the case
5. `research_score(conn, concept_id)` — research score
6. `feasibility_score(conn, concept_id)` — feasibility score
7. `impact_projection(conn, concept_id)` — impact projection
8. Query maturity from `implemented-in` edges:
   ```sql
   SELECT e.target_id, e.attrs FROM edges e
   WHERE e.kind='implemented-in' AND e.source_id=?
   ```
   Parse `maturity` from edge attrs.
9. Query proposals grounded in concept:
   ```sql
   SELECT n.id, n.attrs FROM nodes n
   JOIN edges e ON e.source_id=n.id
   WHERE e.kind='grounded-in' AND e.target_id=? AND n.kind='Proposal'
   ```
10. Compute evidence source diversity (distinct URLs from brief step 17)
11. Query related research concepts (concepts in same subsystem with
    research_score > 0, excluding self)

### New Template: `research.html` (list page)

Structure:

```
HEADER
  "Research Explorer"
  Filter form: min research score, min feasibility, window days, sort by

CONCEPT CARDS (one per concept on current page)
  For each concept:
    h3: Concept name (linked to /research/{id})
    Subsystem badge
    Score row: Research: X.X | Feasibility: X.X/10 | Impact: X.X | Frontier: X.X
    Maturity badge if available (experimental/production/deprecated)
    Evidence diversity: "N independent sources"
    Discussion count | Observation count | Benchmark count
    Top motivation categories (compact: icon + label, max 3)
    Proposals: "N active proposals" if any

PAGINATION
```

### New Template: `research_detail.html` (detail page)

Structure:

```
HEADER
  Concept name
  Subsystem badge
  Maturity badge (experimental/production/deprecated/none)

RESEARCH ASSESSMENT
  Three-column layout:
    Research Score: X.X — "Active exploration with N sources, M discussions"
    Feasibility: X.X/10 — "Standalone" or "Deeply interconnected (N prerequisites)"
    Projected Impact: X.X — "Addresses N problems, affects M components"

IF ADDRESSED (impact projection detail)
  Problems addressed: N (list with severity badges, linked)
  Vulnerabilities mitigated: N
  Failure modes eliminated: N
  Performance metrics improved: N
  Dependent components benefiting: N (linked names)

RESEARCH ACTIVITY (evidence of active exploration)
  Proposals section (if any):
    For each Proposal grounded in this concept:
      Name, description, status, source_date
      Problems it addresses (via `addresses` edges)
      Source link

  Discussion thread summary:
    Count, forums, date range
    Top discussions by participant_count

  Recent observations:
    Claims with confidence and source links

  Benchmark data:
    Metrics, results, conditions

THE CASE (argument paragraph — reused from idea_detail)

MOTIVATION CATEGORIES (reused from idea_detail — same rendering)
  Actionable framing, blast radius, source links, no truncation

SCORES (compact table — heat, pain, impact, leverage, frontier, research, feasibility)

RELATED RESEARCH
  Other concepts in same subsystem with research_score > 0
  Linked as cards with research score

EVIDENCE TIMELINE (reused from idea_detail — source link column)

DEPENDENCIES (open, linked — reused from idea_detail)
```

---

## Files Modified

### Stage 1: Research scoring functions (backend)

| File | Action | Lines |
|------|--------|-------|
| `src/graph/scoring.py` | Add `research_score()`, `feasibility_score()`, `impact_projection()` | ~120 new lines |
| `tests/test_graph_scoring.py` | Add tests for 3 new functions | ~80 new lines |

### Stage 2: Research explorer route + list template

| File | Action | Lines |
|------|--------|-------|
| `src/web/routes.py` | Add `research_explorer()` route handler | ~80 new lines |
| `src/web/templates/research.html` | New list template | ~60 new lines |
| `tests/test_web.py` | Add route tests for /research | ~40 new lines |

### Stage 3: Research detail route + template

| File | Action | Lines |
|------|--------|-------|
| `src/web/routes.py` | Add `research_detail()` route handler | ~100 new lines |
| `src/web/templates/research_detail.html` | New detail template | ~250 new lines |
| `tests/test_web.py` | Add route tests for /research/{id} | ~60 new lines |

### Stage 4: Navigation + audit

| File | Action | Lines |
|------|--------|-------|
| `src/web/templates/base.html` | Add "Research" link to nav | ~2 lines |
| `/cb-audit` | Post-implementation audit | — |

### Files NOT modified

| File | Why |
|------|-----|
| `src/graph/inference.py` | Existing Opportunity/Trend inference unchanged |
| `src/graph/briefing.py` | Reuse existing functions, no changes needed |
| `src/graph/engine.py` | Existing query functions sufficient |
| `src/graph/schema.py` | No new node/edge kinds needed |
| `src/web/templates/idea_detail.html` | Existing page unchanged |
| `src/web/templates/ideas.html` | Existing page unchanged |

---

## Spec Surface

### New nodes

#### ALG-KK-GRAPH-RESEARCH-SCORE (algorithm)
Description: `research_score(conn, concept_id, window_days=90) -> float. Computes
a composite research novelty score from 6 weighted components: discussion_density
(0.25), observation_recency (0.20), evidence_diversity (0.20), proposal_activity
(0.15), benchmark_coverage (0.10), novelty_bonus (0.10). Pure function, no LLM.
Higher score = more active research interest.`
Edges: SUB-KK-GRAPH contains, runs-at stage-delivery, satisfies new invariants

#### INV-KK-GRAPH-RESEARCH-SCORE-PURE (invariant)
Predicate: `forall concept C. research_score(conn, C, W) at T1 ==
research_score(conn, C, W) at T2 given identical graph state. No randomness,
no LLM, no external state.`

#### INV-KK-GRAPH-RESEARCH-SCORE-NON-NEGATIVE (invariant)
Predicate: `forall concept C. research_score(conn, C) >= 0.0.`

#### ALG-KK-GRAPH-FEASIBILITY-SCORE (algorithm)
Description: `feasibility_score(conn, concept_id) -> float in [0, 10]. Estimates
implementation difficulty from prerequisite_depth, cross_subsystem_penalty,
invariant_constraint, protocol_complexity. Higher = more feasible.`

#### INV-KK-GRAPH-FEASIBILITY-BOUNDED (invariant)
Predicate: `forall concept C. 0.0 <= feasibility_score(conn, C) <= 10.0.`

#### ALG-KK-GRAPH-IMPACT-PROJECTION (algorithm)
Description: `impact_projection(conn, concept_id) -> dict. Projects benefit if
research succeeds: problems_addressed, vulns_mitigated, failure_modes_eliminated,
dependent_components, performance_metrics, subsystems_affected, total_impact.`

#### ALG-KK-WEB-RESEARCH-LIST (algorithm)
Description: `GET /research route. Lists Concept nodes ranked by research_score.
Filters by min_research, min_feasibility, window_days. Supports sort_by
(research, feasibility, impact, frontier). Per concept: research_score,
feasibility_score, impact_projection, 5 standard scores, top 3 motivations,
evidence diversity, maturity, proposal count, discussion/observation/benchmark
counts.`

#### ALG-KK-WEB-RESEARCH-DETAIL (algorithm)
Description: `GET /research/{concept_id} route. Research brief for a single
concept. Shows research assessment (3 scores), impact projection detail,
proposals grounded in concept, discussion/observation/benchmark summaries,
motivation categories (reused from idea_detail), evidence timeline, dependencies,
related research concepts.`

#### INV-KK-WEB-RESEARCH-RANKED (invariant)
Predicate: `forall page P on /research. concepts are sorted by the selected
sort_by parameter in descending order.`

#### INV-KK-WEB-RESEARCH-EVIDENCE-CHAIN (invariant)
Predicate: `forall concept C on /research/{id}. all evidence linked to C is
shown in the evidence timeline with source links. No evidence omitted.`

#### INV-KK-WEB-RESEARCH-FEASIBILITY-VISIBLE (invariant)
Predicate: `forall concept C on /research/{id}. feasibility_score and its
components (prerequisite depth, cross-subsystem, invariants, protocols) are
visible in the research assessment section.`

#### INV-KK-WEB-RESEARCH-IMPACT-VISIBLE (invariant)
Predicate: `forall concept C on /research/{id}. impact projection with all
6 component counts and total_impact is visible.`

### Modified nodes

#### SUB-KK-GRAPH (module)
Add contains edges to new algorithm/invariant nodes.

#### SUB-KK-WEB (module)
Add contains edges to new web algorithm/invariant nodes.

### Edge summary

| From | Kind | To |
|------|------|----|
| SUB-KK-GRAPH | contains | ALG-KK-GRAPH-RESEARCH-SCORE |
| SUB-KK-GRAPH | contains | INV-KK-GRAPH-RESEARCH-SCORE-PURE |
| SUB-KK-GRAPH | contains | INV-KK-GRAPH-RESEARCH-SCORE-NON-NEGATIVE |
| SUB-KK-GRAPH | contains | ALG-KK-GRAPH-FEASIBILITY-SCORE |
| SUB-KK-GRAPH | contains | INV-KK-GRAPH-FEASIBILITY-BOUNDED |
| SUB-KK-GRAPH | contains | ALG-KK-GRAPH-IMPACT-PROJECTION |
| SUB-KK-WEB | contains | ALG-KK-WEB-RESEARCH-LIST |
| SUB-KK-WEB | contains | ALG-KK-WEB-RESEARCH-DETAIL |
| SUB-KK-WEB | contains | INV-KK-WEB-RESEARCH-RANKED |
| SUB-KK-WEB | contains | INV-KK-WEB-RESEARCH-EVIDENCE-CHAIN |
| SUB-KK-WEB | contains | INV-KK-WEB-RESEARCH-FEASIBILITY-VISIBLE |
| SUB-KK-WEB | contains | INV-KK-WEB-RESEARCH-IMPACT-VISIBLE |
| ALG-KK-GRAPH-RESEARCH-SCORE | runs-at | stage-delivery |
| ALG-KK-GRAPH-RESEARCH-SCORE | satisfies | INV-KK-GRAPH-RESEARCH-SCORE-PURE |
| ALG-KK-GRAPH-RESEARCH-SCORE | satisfies | INV-KK-GRAPH-RESEARCH-SCORE-NON-NEGATIVE |
| ALG-KK-GRAPH-FEASIBILITY-SCORE | runs-at | stage-delivery |
| ALG-KK-GRAPH-FEASIBILITY-SCORE | satisfies | INV-KK-GRAPH-FEASIBILITY-BOUNDED |
| ALG-KK-GRAPH-IMPACT-PROJECTION | runs-at | stage-delivery |
| ALG-KK-WEB-RESEARCH-LIST | runs-at | stage-delivery |
| ALG-KK-WEB-RESEARCH-LIST | satisfies | INV-KK-WEB-RESEARCH-RANKED |
| ALG-KK-WEB-RESEARCH-DETAIL | runs-at | stage-delivery |
| ALG-KK-WEB-RESEARCH-DETAIL | satisfies | INV-KK-WEB-RESEARCH-EVIDENCE-CHAIN |
| ALG-KK-WEB-RESEARCH-DETAIL | satisfies | INV-KK-WEB-RESEARCH-FEASIBILITY-VISIBLE |
| ALG-KK-WEB-RESEARCH-DETAIL | satisfies | INV-KK-WEB-RESEARCH-IMPACT-VISIBLE |
| INV-KK-GRAPH-RESEARCH-SCORE-PURE | checked-at | stage-delivery |
| INV-KK-GRAPH-RESEARCH-SCORE-NON-NEGATIVE | checked-at | stage-delivery |
| INV-KK-GRAPH-FEASIBILITY-BOUNDED | checked-at | stage-delivery |
| INV-KK-WEB-RESEARCH-RANKED | checked-at | stage-delivery |
| INV-KK-WEB-RESEARCH-EVIDENCE-CHAIN | checked-at | stage-delivery |
| INV-KK-WEB-RESEARCH-FEASIBILITY-VISIBLE | checked-at | stage-delivery |
| INV-KK-WEB-RESEARCH-IMPACT-VISIBLE | checked-at | stage-delivery |

**Total spec mutations:**
- 6 add-node (3 algorithms + 3 invariants in SUB-KK-GRAPH)
- 6 add-node (2 algorithms + 4 invariants in SUB-KK-WEB)
- 31 add-edge (12 contains + 7 runs-at/checked-at + 7 satisfies + 5 checked-at)

---

## Test Definitions

### Stage 1 tests (add to tests/test_graph_scoring.py)

| Test | What it verifies |
|------|-----------------|
| `test_research_score_returns_float` | Returns float >= 0 |
| `test_research_score_pure` | Same inputs → same output |
| `test_research_score_zero_for_empty_concept` | Concept with no evidence → 0 |
| `test_research_score_increases_with_discussions` | More discussions → higher score |
| `test_research_score_weights_participant_count` | High-participant discussion → higher score |
| `test_research_score_rewards_evidence_diversity` | More distinct sources → higher score |
| `test_research_score_rewards_proposals` | Active proposals → higher score |
| `test_research_score_novelty_bonus` | No fixes → higher novelty bonus |
| `test_feasibility_score_bounded` | Returns float in [0, 10] |
| `test_feasibility_score_max_for_standalone` | No prerequisites → 10.0 |
| `test_feasibility_score_decreases_with_depth` | Deep prereqs → lower score |
| `test_feasibility_score_cross_subsystem_penalty` | Multi-subsystem → lower score |
| `test_impact_projection_returns_dict` | Returns dict with 7 keys |
| `test_impact_projection_counts_problems` | Counts open problems correctly |
| `test_impact_projection_total_formula` | total_impact = weighted sum |

### Stage 2 tests (add to tests/test_web.py)

| Test | What it verifies |
|------|-----------------|
| `test_research_list_returns_200` | /research returns 200 |
| `test_research_list_shows_concepts` | Response contains concept names |
| `test_research_list_shows_research_score` | Response contains research score values |
| `test_research_list_filters_by_min_research` | min_research=999 → empty or filtered |
| `test_research_list_sort_by_feasibility` | sort_by=feasibility → sorted by feasibility desc |

### Stage 3 tests (add to tests/test_web.py)

| Test | What it verifies |
|------|-----------------|
| `test_research_detail_returns_200` | /research/{id} returns 200 |
| `test_research_detail_404_for_missing` | /research/nonexistent → 404 |
| `test_research_detail_shows_research_assessment` | Response contains "Research Score" |
| `test_research_detail_shows_feasibility` | Response contains "Feasibility" |
| `test_research_detail_shows_impact_projection` | Response contains "Impact" + counts |
| `test_research_detail_shows_motivations` | Response contains motivation categories |
| `test_research_detail_shows_evidence_timeline` | Response contains evidence timeline |
| `test_research_detail_shows_source_links` | Response contains source links |

---

## Implementation Commands

### Stage 1: Research scoring functions

```
/cb-green — Research scoring: research_score, feasibility_score, impact_projection

CONTEXT PRIMER: This is know_kernel — a Linux kernel knowledge graph with a
Flask web UI. We are building a Research Explorer feature. The plan doc is at
docs/plans/research-explorer.md — read the "New Scoring" sections for exact
formulas. The spec surface is in combobul/spec/spec.db.

This stage adds 3 new scoring functions to src/graph/scoring.py:

WHAT:
  1. research_score(conn, concept_id, window_days=90) -> float
     Composite of 6 weighted components: discussion_density (0.25),
     observation_recency (0.20), evidence_diversity (0.20),
     proposal_activity (0.15), benchmark_coverage (0.10), novelty_bonus (0.10).
     See plan for exact formulas per component. Pure function, >= 0.

  2. feasibility_score(conn, concept_id) -> float in [0, 10]
     10 minus penalties: prerequisite_depth * 1.5 + cross_subsystem * 2.0
     + invariants * 1.0 + protocols * 1.0. Higher = more feasible.

  3. impact_projection(conn, concept_id) -> dict with 7 keys
     problems_addressed, vulns_mitigated, failure_modes_eliminated,
     dependent_components, performance_metrics, subsystems_affected,
     total_impact (weighted composite). Uses existing build_concept_brief
     and transitive_impact data.

  4. Add 15 tests to tests/test_graph_scoring.py.

SPEC AREAS:
  NEW: ALG-KK-GRAPH-RESEARCH-SCORE, INV-KK-GRAPH-RESEARCH-SCORE-PURE,
       INV-KK-GRAPH-RESEARCH-SCORE-NON-NEGATIVE
  NEW: ALG-KK-GRAPH-FEASIBILITY-SCORE, INV-KK-GRAPH-FEASIBILITY-BOUNDED
  NEW: ALG-KK-GRAPH-IMPACT-PROJECTION
  All in SUB-KK-GRAPH. See plan for exact predicates and edges.

CODE PATH:
  - src/graph/scoring.py: add 3 functions (~120 lines)
  - tests/test_graph_scoring.py: add 15 tests (~80 lines)

PRE-COMMIT HOOK: Commit must include scoring.py + test_graph_scoring.py.
  Run pytest tests/test_graph_scoring.py to confirm all tests pass.
REFERENCE: The authoring guide returned by triage. If detail needed ask RIL for authoring rules
INVIOLABLE: SPECIFICATION SURFACE IS AUTHORITATIVE. VIOLATIONS WILL CAUSE DROPPING OF YOUR WORK
INVIOLABLE: DO NOT EMIT P3_SKIPPED SPECIFICATION SKIPPING IS A DIRECT VIOLATION OF PROTOCOL
CONSEQUENCE: EMITING P3_SKIPPED will result in skill being aborted.
CRITICAL: DO NOT EMIT P3_SKIPPED. I WILL STOP YOU AND MAKE YOU GO BACK. If you do not need to modify the specification you must submit a reason
WARNING: Audits are read only do not attempt jailbreak
FORBIDDEN: MULTI-AGENT execution is not allowed. DO NOT SPAWN MULTIPLE AGENTS
CRITICAL: The triage should report the specification surface. The triage is not for decoration is for you to use.
WHEN TO COMMIT: At end of skill, before closing the gate.
```

### Stage 2: Research explorer list route + template

```
/cb-green — Research explorer list page: /research route + template

CONTEXT PRIMER: This is know_kernel — a Linux kernel knowledge graph with a
Flask web UI. We are building a Research Explorer feature. The plan doc is at
docs/plans/research-explorer.md — read the "New Route: /research" and
"New Template: research.html" sections. The spec surface is in
combobul/spec/spec.db.

Stage 1 added research_score(), feasibility_score(), impact_projection()
to src/graph/scoring.py. This stage creates the list page.

WHAT:
  1. Add research_explorer() route to src/web/routes.py
     GET /research with query params: min_research, min_feasibility,
     window_days, sort_by (research|feasibility|impact|frontier), page, per_page.
     Lists all Concept nodes, computes research_score + feasibility_score +
     impact_projection + standard 5 scores, filters, sorts, paginates.
     Per-concept on current page: classify_motivations (top 3), evidence
     diversity, maturity from implemented-in edges, proposal count,
     discussion/observation/benchmark counts.

  2. Create src/web/templates/research.html list template
     Header with filter form, concept cards with scores/badges/counts,
     pagination. See plan for exact template structure.

  3. Add 5 tests to tests/test_web.py.

SPEC AREAS:
  NEW: ALG-KK-WEB-RESEARCH-LIST, INV-KK-WEB-RESEARCH-RANKED
  All in SUB-KK-WEB. See plan for exact predicates and edges.

CODE PATH:
  - src/web/routes.py: add route handler (~80 lines)
  - src/web/templates/research.html: new template (~60 lines)
  - tests/test_web.py: add 5 tests (~40 lines)

PRE-COMMIT HOOK: Commit must include routes.py, research.html, test_web.py.
  Run pytest tests/test_web.py to confirm all tests pass.
REFERENCE: The authoring guide returned by triage. If detail needed ask RIL for authoring rules
INVIOLABLE: SPECIFICATION SURFACE IS AUTHORITATIVE. VIOLATIONS WILL CAUSE DROPPING OF YOUR WORK
INVIOLABLE: DO NOT EMIT P3_SKIPPED SPECIFICATION SKIPPING IS A DIRECT VIOLATION OF PROTOCOL
CONSEQUENCE: EMITING P3_SKIPPED will result in skill being aborted.
CRITICAL: DO NOT EMIT P3_SKIPPED. I WILL STOP YOU AND MAKE YOU GO BACK. If you do not need to modify the specification you must submit a reason
WARNING: Audits are read only do not attempt jailbreak
FORBIDDEN: MULTI-AGENT execution is not allowed. DO NOT SPAWN MULTIPLE AGENTS
CRITICAL: The triage should report the specification surface. The triage is not for decoration is for you to use.
WHEN TO COMMIT: At end of skill, before closing the gate.
```

### Stage 3: Research detail route + template

```
/cb-green — Research detail page: /research/{concept_id} route + template

CONTEXT PRIMER: This is know_kernel — a Linux kernel knowledge graph with a
Flask web UI. We are building a Research Explorer feature. The plan doc is at
docs/plans/research-explorer.md — read the "New Route: /research/{concept_id}"
and "New Template: research_detail.html" sections. The spec surface is in
combobul/spec/spec.db.

Stages 1-2 added scoring functions and the /research list page. This stage
creates the detail page for individual research concepts.

WHAT:
  1. Add research_detail() route to src/web/routes.py
     GET /research/{concept_id}. Fetches concept, builds full brief via
     build_concept_brief(), classifies motivations, builds argument paragraph,
     computes research_score + feasibility_score + impact_projection, queries
     maturity from implemented-in edges, queries proposals via grounded-in,
     computes evidence diversity, queries related research concepts in same
     subsystem. Returns 404 for missing/non-Concept nodes.

  2. Create src/web/templates/research_detail.html
     Research assessment (3-score header), impact projection detail, proposals
     section, research activity summary, the case (argument paragraph),
     motivation categories (reuse idea_detail rendering with actionable/blast
     radius/source links), scores table, related research, evidence timeline,
     dependencies. See plan for exact template structure.

  3. Add 8 tests to tests/test_web.py.

SPEC AREAS:
  NEW: ALG-KK-WEB-RESEARCH-DETAIL, INV-KK-WEB-RESEARCH-EVIDENCE-CHAIN,
       INV-KK-WEB-RESEARCH-FEASIBILITY-VISIBLE, INV-KK-WEB-RESEARCH-IMPACT-VISIBLE
  All in SUB-KK-WEB. See plan for exact predicates and edges.

CODE PATH:
  - src/web/routes.py: add route handler (~100 lines)
  - src/web/templates/research_detail.html: new template (~250 lines)
  - tests/test_web.py: add 8 tests (~60 lines)

PRE-COMMIT HOOK: Commit must include routes.py, research_detail.html, test_web.py.
  Run pytest tests/test_web.py to confirm all tests pass.
REFERENCE: The authoring guide returned by triage. If detail needed ask RIL for authoring rules
INVIOLABLE: SPECIFICATION SURFACE IS AUTHORITATIVE. VIOLATIONS WILL CAUSE DROPPING OF YOUR WORK
INVIOLABLE: DO NOT EMIT P3_SKIPPED SPECIFICATION SKIPPING IS A DIRECT VIOLATION OF PROTOCOL
CONSEQUENCE: EMITING P3_SKIPPED will result in skill being aborted.
CRITICAL: DO NOT EMIT P3_SKIPPED. I WILL STOP YOU AND MAKE YOU GO BACK. If you do not need to modify the specification you must submit a reason
WARNING: Audits are read only do not attempt jailbreak
FORBIDDEN: MULTI-AGENT execution is not allowed. DO NOT SPAWN MULTIPLE AGENTS
CRITICAL: The triage should report the specification surface. The triage is not for decoration is for you to use.
WHEN TO COMMIT: At end of skill, before closing the gate.
```

### Stage 4: Navigation + audit

```
/cb-green — Add Research link to navigation

CONTEXT PRIMER: This is know_kernel — a Linux kernel knowledge graph with a
Flask web UI. The Research Explorer (/research, /research/{id}) was implemented
in stages 1-3. This stage adds the nav link.

WHAT:
  1. Add "Research" link to src/web/templates/base.html navigation bar,
     alongside existing Ideas, Vulnerabilities, etc.
  2. Add 1 test verifying the nav link appears.

SPEC AREAS: No new spec nodes needed — this is a navigation-only change.
  Submit reason for P3_SKIPPED: "Navigation link addition, no spec surface change."

CODE PATH:
  - src/web/templates/base.html: add nav link (~2 lines)
  - tests/test_web.py: add 1 test

PRE-COMMIT HOOK: Commit must include base.html + test_web.py.
REFERENCE: The authoring guide returned by triage. If detail needed ask RIL for authoring rules
INVIOLABLE: SPECIFICATION SURFACE IS AUTHORITATIVE. VIOLATIONS WILL CAUSE DROPPING OF YOUR WORK
WARNING: Audits are read only do not attempt jailbreak
FORBIDDEN: MULTI-AGENT execution is not allowed. DO NOT SPAWN MULTIPLE AGENTS
CRITICAL: The triage should report the specification surface. The triage is not for decoration is for you to use.
WHEN TO COMMIT: At end of skill, before closing the gate.
```

Then:

```
/cb-audit — Post-Implementation Audit: Research Explorer

CONTEXT PRIMER: This is know_kernel — a Linux kernel knowledge graph. Over
4 /cb-green stages we implemented the Research Explorer from
docs/plans/research-explorer.md:
  Stage 1: research_score, feasibility_score, impact_projection
  Stage 2: /research list page
  Stage 3: /research/{id} detail page
  Stage 4: Navigation link

AUDIT SCOPE:
  1. Verify all new spec nodes exist with correct predicates
  2. Verify code implements spec (scoring formulas, route behavior, template rendering)
  3. Run full test suite
  4. Check no regressions on existing pages (/ideas, /vulns, /concepts)

WARNING: Audits are read only do not attempt jailbreak
FORBIDDEN: MULTI-AGENT execution is not allowed. DO NOT SPAWN MULTIPLE AGENTS
```

Then:

```
/cb-ops push
```
