# Quality & UX Improvement Plan

**Status:** Draft  
**Date:** 2026-06-22  
**Scope:** Web UX labels, admissibility coverage, extraction pipeline gaps, navigation & search

This plan addresses 4 categories of findings from a full-system audit. Each
category has its own specification surface (invariants, algorithms, schemas)
and implementation tasks. Categories are ordered by dependency: Phase 1 is
foundational (the display_name helper is used by every subsequent web task),
Phase 4 depends on Phase 1 endpoints existing.

---

## Phase 1 — Human-Readable Labels Everywhere

### Problem

Node IDs are `<prefix>-<12-char-hex>` (e.g. `kinv-9f42a7c2b1d3`). These IDs
appear as page titles, list rows, edge links, graph viz tooltips, and browser
tab text. A label-building chain exists in `routes.py:102-108` but is scoped
only to neighbor labels on the detail page.

### Specification Surface

#### INV-KK-WEB-DISPLAY-NAME

Every user-facing rendering of a node (list row, page heading, edge link,
graph tooltip, dashboard drill-down) MUST show a human-readable display name,
never a raw node ID, as the primary text. The node ID MAY appear as secondary
metadata (subtitle, tooltip, `data-id` attribute).

**Display name resolution order per kind:**

| Kind | Primary field | Truncation | Fallback |
|------|--------------|------------|----------|
| Concept | `attrs.name` | none | `node.id` |
| Source | `attrs.url` | 80 chars | `node.id` |
| Evidence | `attrs.description` | 60 chars | `"Evidence " + node.id[-8:]` |
| Advisory | `attrs.assessment` | 60 chars | `node.id` |
| Subsystem | `attrs.name` | none | `node.id` |
| Proposal | `attrs.name` | none | `node.id` |
| KernelInvariant | `attrs.predicate` | 60 chars | `node.id` |
| FailureMode | `attrs.symptom` | 60 chars | `node.id` |
| InteractionProtocol | `attrs.rule` | 60 chars | `node.id` |
| PerformanceProfile | `attrs.metric` | 40 chars | `node.id` |
| CompatibilityAssessment | `attrs.synergy` | 60 chars | `node.id` |
| OptimizationGoal | `attrs.name` | none | `node.id` |
| UseCaseScenario | `attrs.name` | none | `node.id` |
| ComparativeAnalysis | `attrs.dimension` | 60 chars | `node.id` |
| Kernel | `attrs.name` | none | `node.id` |

**Format:** `"{display_name} ({kind})"` when context requires disambiguation
(edge links, graph tooltips). Plain `"{display_name}"` when kind is already
shown separately (list rows with kind column, detail page with kind badge).

#### INV-KK-WEB-EVIDENCE-DESCRIPTION (new required attribute)

Evidence nodes currently have only `artifact_class` and `contamination_level`
— neither is human-readable. A new optional attribute `description` MUST be
added to Evidence nodes. The ingest pipeline MUST populate `description` with
a brief summary of the evidence content (first 120 chars of the document text
or a generated summary). If `description` is absent, the fallback
`"Evidence " + id[-8:]` applies.

**Schema change:** Add `"description"` to `REQUIRED_ATTRS["Evidence"]`.

**Migration:** Existing Evidence nodes without `description` get it set to
`""` (empty string). The display_name fallback handles this case.

### Implementation Tasks

#### P1-T1: Create `display_name_for_node()` utility

**File:** `src/web/routes.py` (new function, add before `setup_routes`)

```python
_DISPLAY_FIELDS: dict[str, tuple[str, int | None]] = {
    "Concept": ("name", None),
    "Source": ("url", 80),
    "Evidence": ("description", 60),
    "Advisory": ("assessment", 60),
    "Subsystem": ("name", None),
    "Proposal": ("name", None),
    "KernelInvariant": ("predicate", 60),
    "FailureMode": ("symptom", 60),
    "InteractionProtocol": ("rule", 60),
    "PerformanceProfile": ("metric", 40),
    "CompatibilityAssessment": ("synergy", 60),
    "OptimizationGoal": ("name", None),
    "UseCaseScenario": ("name", None),
    "ComparativeAnalysis": ("dimension", 60),
    "Kernel": ("name", None),
}

def display_name_for_node(kind: str, attrs: dict, node_id: str) -> str:
    field, max_len = _DISPLAY_FIELDS.get(kind, (None, None))
    if field:
        value = (attrs.get(field) or "").strip()
        if value:
            if max_len and len(value) > max_len:
                return value[:max_len] + "..."
            return value
    if kind == "Evidence":
        return f"Evidence {node_id[-8:]}"
    return node_id
```

**Tests:** Unit tests for each kind, truncation behavior, missing attrs fallback,
Evidence special case.

#### P1-T2: Update `concept_list.html` to show display names

**File:** `src/web/templates/concept_list.html`

Current (line 6-11):
```html
<thead><tr><th>ID</th><th>Kind</th></tr></thead>
...
<td><a href="/concepts/{{ node.id }}">{{ node.id }}</a></td>
<td>{{ node.kind }}</td>
```

Change to:
```html
<thead><tr><th>Name</th><th>Kind</th><th>ID</th></tr></thead>
...
<td><a href="/concepts/{{ node.id }}">{{ node.display_name }}</a></td>
<td>{{ node.kind }}</td>
<td><code>{{ node.id }}</code></td>
```

**Routes change:** In `concepts_list()`, `subsystems_list()`, `sources_list()`,
add `display_name` to each node dict before passing to template:
```python
for n in nodes:
    n["display_name"] = display_name_for_node(n["kind"], n.get("attrs") or {}, n["id"])
```

#### P1-T3: Update `concept_detail.html` page heading

**File:** `src/web/templates/concept_detail.html`

Current (line 3):
```html
<h1>{{ node.id }}</h1>
```

Change to:
```html
<h1>{{ node.display_name }}</h1>
<p><span class="badge badge-kind">{{ node.kind }}</span> <code>{{ node.id }}</code></p>
```

**Routes change:** In `concept_detail()`, add:
```python
node["display_name"] = display_name_for_node(node["kind"], node.get("attrs") or {}, node["id"])
```

Remove the per-kind `<h2>` headings that duplicate the name (lines 10, 109,
119, 127) — the `<h1>` now shows it.

#### P1-T4: Update `node_labels` builder to use `display_name_for_node()`

**File:** `src/web/routes.py` lines 91-109

Replace the inline fallback chain with a call to the new utility:
```python
for lr in label_rows:
    lr_dict = _rows_to_dicts([lr])[0]
    attrs = lr_dict.get("attrs") or {}
    kind = lr_dict["kind"]
    label = display_name_for_node(kind, attrs, lr_dict["id"])
    node_labels[lr_dict["id"]] = f"{label} ({kind})"
```

#### P1-T5: Update graph viz tooltip

**File:** `src/web/templates/graph_viz.html` lines 70-73

Current:
```javascript
const name = d.attrs && d.attrs.name ? d.attrs.name : d.id;
return name + ' (' + d.kind + ')';
```

Change to use the same field-priority resolution client-side. Add a
`displayNameFields` lookup mirroring `_DISPLAY_FIELDS`:
```javascript
const displayFields = {
  Concept: 'name', Source: 'url', Evidence: 'description',
  Advisory: 'assessment', Subsystem: 'name', Proposal: 'name',
  KernelInvariant: 'predicate', FailureMode: 'symptom',
  InteractionProtocol: 'rule', PerformanceProfile: 'metric',
  CompatibilityAssessment: 'synergy', OptimizationGoal: 'name',
  UseCaseScenario: 'name', ComparativeAnalysis: 'dimension',
  Kernel: 'name'
};
node.append('title').text(d => {
  const field = displayFields[d.kind];
  const val = d.attrs && d.attrs[field] ? d.attrs[field] : d.id;
  const name = val.length > 60 ? val.substring(0, 60) + '...' : val;
  return name + ' (' + d.kind + ')';
});
```

#### P1-T6: Add `description` to Evidence schema

**File:** `src/graph/schema.py` line 57

Current:
```python
"Evidence": ("artifact_class", "contamination_level"),
```

Change to:
```python
"Evidence": ("artifact_class", "contamination_level", "description"),
```

**File:** `src/ingest/pipeline.py` — where Evidence nodes are created, add
`"description"` attribute populated from the first 120 chars of the evidence
text.

**Migration:** Add a one-time migration script or handle gracefully in
`display_name_for_node()` (the fallback already handles missing description).

**Note:** Making description required means existing databases fail on
`validate_graph()`. Options:
1. Make it required and backfill existing Evidence nodes.
2. Keep it optional (not in REQUIRED_ATTRS) and let display_name handle absence.

Recommendation: Option 2 — do NOT add to REQUIRED_ATTRS. Instead add it
as a new field populated during ingest. The display_name fallback handles
absence. This avoids breaking existing databases.

**Revised schema change:** No change to REQUIRED_ATTRS. Instead:
- Ingest pipeline populates `description` when creating Evidence nodes
- `display_name_for_node()` falls back to `"Evidence " + id[-8:]` when absent

---

## Phase 2 — Admissibility Rule Coverage

### Problem

Only 4 of 15 node kinds have admissibility rules (`rules.py:69-74`). 11 kinds
can be created with invalid graph structure and no validation will ever fire.
Additionally, `add_node()` and `delete_edge()` never call `validate_node()`,
creating bypass paths even for the 4 covered kinds.

### Specification Surface

#### INV-KK-RULES-FULL-COVERAGE

Every node kind in `NODE_KINDS` MUST have at least one entry in
`RULES_BY_KIND`. Node kinds where no structural constraint is meaningful
(OptimizationGoal, UseCaseScenario, Kernel) MUST have an explicit empty list
`[]` entry to document the deliberate decision.

#### INV-KK-VALIDATE-ON-MUTATION

`validate_node()` MUST be called after any mutation that could create or
destroy a structural invariant:
- After `add_node()` + its associated `add_edge()` calls complete (at ingest
  transaction boundaries, not after each individual call)
- After `delete_edge()` for the source node of the deleted edge
- After `update_node_attrs()` (attrs-only rules)

This does NOT mean every `add_node()` call triggers validation immediately
(that would fail because edges haven't been wired yet). Instead, validation
is called at **transaction boundaries** — after a complete node+edges
creation sequence commits.

#### INV-KK-CYCLE-DETECTION-EDGES

Cycle detection (currently only `supersedes`) MUST also cover:
- `refines` — refinement chains must be acyclic
- `prerequisite` — prerequisite chains must be acyclic

Edges where cycles are impossible by type constraint (e.g.,
`governed-by`: KernelInvariant → Concept, different kinds) do NOT need cycle
detection.

### Proposed Rules by Kind

#### KernelInvariant
```
check_kinv_belongs_to_subsystem:
  SELECT 1 FROM edges WHERE kind='belongs-to' AND source_id=? LIMIT 1
  → Violation if missing: "KernelInvariant must belong-to at least one Subsystem"

check_kinv_governed_by_concept:
  SELECT 1 FROM edges WHERE kind='governed-by' AND source_id=? LIMIT 1
  → Violation if missing: "KernelInvariant must be governed-by at least one Concept"
```

#### FailureMode
```
check_failure_mode_trigger:
  SELECT 1 FROM edges WHERE kind='triggered-by' AND source_id=? LIMIT 1
  → Violation if missing: "FailureMode must be triggered-by at least one KernelInvariant"

check_failure_mode_provenance:
  SELECT 1 FROM edges WHERE kind='extracted-from' AND source_id=? LIMIT 1
  → Violation if missing: "FailureMode must be extracted-from at least one Evidence"
```

#### InteractionProtocol
```
check_protocol_concept_pairs:
  SELECT COUNT(DISTINCT target_id) FROM edges
    WHERE kind='constrains-composition' AND source_id=?
  → Violation if count < 2: "InteractionProtocol must constrain-composition at least 2 distinct Concepts"

check_protocol_provenance:
  SELECT 1 FROM edges WHERE kind='extracted-from' AND source_id=? LIMIT 1
  → Violation if missing: "InteractionProtocol must be extracted-from at least one Evidence"
```

#### PerformanceProfile
```
check_profile_concept:
  SELECT COUNT(*) FROM edges WHERE kind='profiled-by' AND source_id=?
  → Violation if count != 1: "PerformanceProfile must be profiled-by exactly 1 Concept"

check_profile_provenance:
  SELECT 1 FROM edges WHERE kind='extracted-from' AND source_id=? LIMIT 1
  → Violation if missing: "PerformanceProfile must be extracted-from at least one Evidence"
```

#### CompatibilityAssessment
```
check_compat_concept_pairs:
  SELECT COUNT(DISTINCT target_id) FROM edges
    WHERE kind='assesses-compatibility' AND source_id=?
  → Violation if count < 2: "CompatibilityAssessment must assess-compatibility at least 2 distinct Concepts"

check_compat_provenance:
  SELECT 1 FROM edges WHERE kind='extracted-from' AND source_id=? LIMIT 1
  → Violation if missing
```

#### ComparativeAnalysis
```
check_comparative_concept_pairs:
  SELECT COUNT(DISTINCT target_id) FROM edges WHERE kind='compares' AND source_id=?
  → Violation if count != 2: "ComparativeAnalysis must compare exactly 2 distinct Concepts"
```

#### Subsystem
```
check_subsystem_has_children:
  SELECT 1 FROM edges WHERE kind='belongs-to' AND target_id=? LIMIT 1
  → Violation if missing: "Subsystem must have at least one belongs-to incoming edge"
```

#### Advisory
```
check_advisory_has_assessor:
  SELECT 1 FROM edges WHERE kind='assessed-by' AND target_id=? LIMIT 1
  → Violation if missing: "Advisory must have an assessed-by incoming edge"
```

#### OptimizationGoal, UseCaseScenario, Kernel
```
(no structural rules — explicitly empty list in RULES_BY_KIND)
```

### Implementation Tasks

#### P2-T1: Add 13 new rule functions to `rules.py`

**File:** `src/graph/rules.py`

Add the functions listed above. Each follows the existing pattern:
- Take `(conn, node_id)` → `Violation | None`
- Single SQL query
- Return `Violation(node_id, rule_name, message)` or `None`

Update `RULES_BY_KIND`:
```python
RULES_BY_KIND = {
    "Concept": [check_concept_has_belongs_to, check_concept_has_provenance],
    "Evidence": [check_evidence_has_source],
    "Proposal": [check_proposal_grounding],
    "Source": [check_source_has_advisory],
    "KernelInvariant": [check_kinv_belongs_to_subsystem, check_kinv_governed_by_concept],
    "FailureMode": [check_failure_mode_trigger, check_failure_mode_provenance],
    "InteractionProtocol": [check_protocol_concept_pairs, check_protocol_provenance],
    "PerformanceProfile": [check_profile_concept, check_profile_provenance],
    "CompatibilityAssessment": [check_compat_concept_pairs, check_compat_provenance],
    "ComparativeAnalysis": [check_comparative_concept_pairs],
    "Subsystem": [check_subsystem_has_children],
    "Advisory": [check_advisory_has_assessor],
    "OptimizationGoal": [],
    "UseCaseScenario": [],
    "Kernel": [],
}
```

**Tests:** One test per rule — create node with required structure → passes,
remove critical edge → violation returned. Add to `tests/test_graph_rules.py`.

#### P2-T2: Add cycle detection for `refines` and `prerequisite`

**File:** `src/graph/engine.py`

Generalize `_check_supersedes_cycle` to `_check_edge_cycle(conn, kind, source_id, target_id)`:

```python
_ACYCLIC_EDGE_KINDS = {"supersedes", "refines", "prerequisite"}

def _check_edge_cycle(conn, kind, source_id, target_id):
    visited = set()
    stack = [target_id]
    while stack:
        current = stack.pop()
        if current == source_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        rows = conn.execute(
            "SELECT target_id FROM edges WHERE kind = ? AND source_id = ?",
            (kind, current),
        ).fetchall()
        stack.extend(r[0] for r in rows)
    return False
```

In `add_edge()`, replace the `supersedes`-specific check (lines 87-90) with:
```python
if kind in _ACYCLIC_EDGE_KINDS and _check_edge_cycle(conn, kind, source_id, target_id):
    raise ValueError(f"Adding {kind} edge {source_id} -> {target_id} would create a cycle")
```

**Tests:** Add cycle detection tests for `refines` and `prerequisite` to
`tests/test_graph_structural.py`.

#### P2-T3: Add post-delete-edge validation

**File:** `src/graph/engine.py`, function `delete_edge()`

After deleting the edge, validate the source node:
```python
def delete_edge(conn, edge_id):
    row = conn.execute(
        "SELECT kind, source_id, target_id FROM edges WHERE id = ?", (edge_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"Edge {edge_id} does not exist")
    edge_kind, source_id, target_id = row
    source_node = get_node(conn, source_id)

    conn.execute("SAVEPOINT delete_edge_check")
    conn.execute("DELETE FROM edges WHERE id = ?", (edge_id,))
    if edge_kind == "contradicts":
        conn.execute(
            "DELETE FROM edges WHERE kind='contradicts' AND source_id=? AND target_id=?",
            (target_id, source_id),
        )

    if source_node:
        violations = validate_node(conn, source_id, source_node["kind"])
        if violations:
            conn.execute("ROLLBACK TO SAVEPOINT delete_edge_check")
            conn.execute("RELEASE SAVEPOINT delete_edge_check")
            raise AdmissibilityError(violations)
    conn.execute("RELEASE SAVEPOINT delete_edge_check")
```

**Tests:** Test that deleting the only `sourced-from` edge from Evidence
raises AdmissibilityError. Test that deleting a redundant edge (when another
remains) succeeds.

#### P2-T4: Add transaction-boundary validation to ingest pipeline

**File:** `src/ingest/extractor.py`, `src/ingest/classifier.py`,
`src/graph/optimization.py`

After each complete node+edges creation sequence, call `validate_node()`.
This is NOT after every `add_node()` — it's after the full creation sequence
(node + all its edges) is complete.

For example, in `store_kernel_invariant()` (extractor.py:293-311), validation
happens after both `add_edge()` calls:
```python
add_node(conn, kinv_id, "KernelInvariant", {...})
add_edge(conn, "governed-by", kinv_id, concept_id)
add_edge(conn, "extracted-from", kinv_id, evidence_id)
# NOW validate:
violations = validate_node(conn, kinv_id, "KernelInvariant")
if violations:
    raise AdmissibilityError(violations)
```

Apply the same pattern to:
- `store_failure_mode()` (extractor.py:340-355)
- `store_interaction_protocol()` (extractor.py:400-414)
- `store_performance_profile()` (extractor.py:450-467)
- `store_compatibility_assessment()` (extractor.py:515-529)
- `store_comparative_analysis()` (extractor.py:573-589)
- `store_rich_concept()` (extractor.py:591-605)
- `resolve_subsystem()` (classifier.py:21-38) — validate after `assign_subsystems()` completes
- `create_optimization_goal()` (optimization.py:20-34)
- `create_use_case_scenario()` (optimization.py:58-72)
- `create_kernel()` (optimization.py:127-141)

---

## Phase 3 — Extraction Pipeline Coverage

### Problem

The extraction pipeline has dead features (Proposal nodes, `alternative-to`
and `supersedes` edges), hardcoded values (`artifact_class`), and dropped
data (`contamination_level` in Advisory).

### Specification Surface

#### INV-KK-EXTRACT-RELATIONSHIP-COVERAGE

`ALLOWED_RELATIONSHIP_KINDS` in `extractor.py:219` MUST include all
Concept-to-Concept edge kinds that the LLM can reasonably extract:
- `refines` (existing)
- `contradicts` (existing)
- `prerequisite` (existing)
- `alternative-to` (currently dead — add to whitelist and LLM prompt)
- `supersedes` (currently dead — add to whitelist and LLM prompt)

The LLM extraction prompt (`build_extraction_prompt`) MUST list all 5
relationship kinds with brief definitions so the model can distinguish them.

#### INV-KK-ADVISORY-STORES-CONTAMINATION

When `review_source()` creates an Advisory node, it MUST store the
`confirmed_level` parameter in the Advisory's attrs alongside `assessment`.

**Schema change:** Advisory REQUIRED_ATTRS becomes
`("assessment", "contamination_confirmed")`.

#### INV-KK-KINV-SUBSYSTEM-LINKAGE

The ingest pipeline MUST link KernelInvariant nodes to their governing
Concept's Subsystem via `belongs-to` edges. Currently only Concepts are
linked to Subsystems (`classifier.py:61`); KernelInvariants are orphaned
from subsystem structure despite the schema allowing
`("KernelInvariant", "Subsystem")` in EDGE_VALID_PAIRS.

#### DECISION-KK-PROPOSAL-KEEP-OR-REMOVE

Proposal nodes have full schema infrastructure (NODE_KINDS, EDGE_VALID_PAIRS,
REQUIRED_ATTRS, validation rules, export/MCP references, viz color) but zero
creation code. This plan does NOT implement Proposal creation. Instead:

**Option A (recommended):** Remove Proposal from NODE_KINDS, EDGE_VALID_PAIRS,
REQUIRED_ATTRS, RULES_BY_KIND, export ALLOWED_KINDS, MCP
`get_subsystem_concepts()` query, and graph_viz.html color map. Remove
`grounded-in` from EDGE_KINDS and EDGE_VALID_PAIRS. Remove
`check_proposal_grounding` from rules.py.

**Option B:** Keep infrastructure for future use. Document the decision with
a `# TODO: Proposal creation not yet implemented` comment in schema.py.

The user should choose. Implementation tasks below cover Option A.

#### DECISION-KK-ARTIFACT-CLASS-TAXONOMY

`artifact_class` is hardcoded to `"abstracted-mechanism"` at 7 call sites in
extractor.py. This plan does NOT implement a full taxonomy. Instead:

**Recommendation:** Add to the LLM extraction prompt a request to classify
each extracted item's `artifact_class` from a defined enum:
`{"abstracted-mechanism", "implementation-detail", "api-contract",
"data-structure", "algorithm", "protocol"}`. If the LLM returns an
unrecognized value, fall back to `"abstracted-mechanism"`.

This is lower priority than Phases 1-2 and can be deferred.

### Implementation Tasks

#### P3-T1: Expand `ALLOWED_RELATIONSHIP_KINDS` and LLM prompt

**File:** `src/ingest/extractor.py`

Line 219 — change to:
```python
ALLOWED_RELATIONSHIP_KINDS = {"refines", "contradicts", "prerequisite", "alternative-to", "supersedes"}
```

Update `build_extraction_prompt()` to include all 5 kinds with definitions:
```
relationships: A list of connections to OTHER concepts you are
extracting in this same batch. Each entry has:
  - target: The exact name of the other concept
  - kind: One of:
    - "refines" — this concept is a more specific version of the target
    - "contradicts" — this concept and the target cannot coexist
    - "prerequisite" — this concept requires the target to exist first
    - "alternative-to" — this concept and the target solve the same problem differently
    - "supersedes" — this concept replaces the target entirely
```

**Tests:** Test that `wire_relationships()` creates `alternative-to` and
`supersedes` edges when returned by the LLM.

#### P3-T2: Store `contamination_confirmed` in Advisory nodes

**File:** `src/ingest/reviewer.py` lines 65-67

Current:
```python
add_node(conn, advisory_id, "Advisory", {
    "assessment": assessment_text.strip(),
})
```

Change to:
```python
add_node(conn, advisory_id, "Advisory", {
    "assessment": assessment_text.strip(),
    "contamination_confirmed": confirmed_level,
})
```

**File:** `src/graph/schema.py` line 58

Change:
```python
"Advisory": ("assessment",),
```
To:
```python
"Advisory": ("assessment", "contamination_confirmed"),
```

**Migration:** Existing Advisory nodes need `contamination_confirmed` backfill
(set to `"L0-clean"` or the Source's Evidence contamination_level).

**Tests:** Test that `review_source()` stores contamination_confirmed, test
that creating Advisory without it raises ValueError.

#### P3-T3: Link KernelInvariants to Subsystems

**File:** `src/ingest/classifier.py`

In `assign_subsystems()`, after linking Concepts to Subsystems, also link
any KernelInvariants that `governed-by` those Concepts to the same Subsystem:

```python
# After the Concept → Subsystem belongs-to edges are created:
for concept_id, subsystem_id in concept_subsystem_pairs:
    kinv_rows = conn.execute(
        "SELECT source_id FROM edges WHERE kind='governed-by' AND target_id=?",
        (concept_id,),
    ).fetchall()
    for (kinv_id,) in kinv_rows:
        existing = conn.execute(
            "SELECT 1 FROM edges WHERE kind='belongs-to' AND source_id=? AND target_id=?",
            (kinv_id, subsystem_id),
        ).fetchone()
        if not existing:
            add_edge(conn, "belongs-to", kinv_id, subsystem_id)
```

**Tests:** Test that after `assign_subsystems()`, KernelInvariants have
`belongs-to` edges to their governing Concept's Subsystem.

#### P3-T4: Remove Proposal infrastructure (if Option A chosen)

**Files to modify:**
- `src/graph/schema.py`: Remove "Proposal" from NODE_KINDS, "grounded-in" from
  EDGE_KINDS, their entries from EDGE_VALID_PAIRS and REQUIRED_ATTRS
- `src/graph/rules.py`: Remove `check_proposal_grounding`, remove "Proposal"
  from RULES_BY_KIND
- `src/export/exporter.py`: Remove "Proposal" from ALLOWED_KINDS
- `src/mcp_server/server.py`: Remove "Proposal" from `get_subsystem_concepts()`
  query
- `src/web/templates/graph_viz.html`: Remove "Proposal" from kindColor map
- `src/ingest/gate.py`: Remove `record_proposal()` method, simplify or
  remove `is_proposal_mode` property. Keep `SessionGate` for
  `record_class_a_access()` which is still used.

**Tests:** Remove or update any test fixtures that reference Proposal nodes.
Verify `validate_graph()` still passes on existing databases.

#### P3-T5: Populate Evidence description during ingest

**File:** `src/ingest/pipeline.py`

When creating Evidence nodes, add description from the document text:
```python
description = evidence_text[:120].strip() if evidence_text else ""
add_node(conn, evidence_id, "Evidence", {
    "artifact_class": ...,
    "contamination_level": ...,
    "description": description,
})
```

This is NOT a required attribute (see P1-T6 discussion). It's populated
when available and used by `display_name_for_node()`.

---

## Phase 4 — Navigation, Search & Graph Viz

### Problem

The web UI has no search, no filtering (beyond hardcoded `/subsystems` and
`/sources`), no pagination, no breadcrumbs, no graph legend, and no HTML
wrappers for the 4 existing JSON API endpoints. HTMX is not used anywhere.
Meanwhile, the MCP server exposes `search_concepts()`, `explore_subgraph()`,
`check_path()`, and `query_edges()` — none available in the web UI.

### Specification Surface

#### INV-KK-WEB-KIND-FILTER

`GET /concepts` MUST accept an optional `kind` query parameter. When present,
only nodes of that kind are returned. When absent, all nodes are returned
(preserving INV-KK-WEB-FULL-ACCESS). The dashboard kind-count rows MUST
link to `/concepts?kind={kind}`.

#### ALG-KK-WEB-SEARCH

A new route `GET /api/search` accepts `q` (search string) and optional `kind`
(filter). It performs a SQL LIKE search on `json_extract(attrs, '$.name')`,
`json_extract(attrs, '$.description')`, and `attrs` (full-text fallback),
matching the MCP `search_concepts()` implementation but without the Class B
filter (since the web UI has INV-KK-WEB-FULL-ACCESS). Returns JSON array of
`{id, kind, attrs, display_name}`.

A search box in `base.html` nav bar uses HTMX `hx-get="/api/search"` with
`hx-trigger="keyup changed delay:300ms"` to show incremental results in a
dropdown.

#### INV-KK-WEB-GRAPH-LEGEND

The graph visualization page MUST display a legend showing:
- Node kind → color mapping for all kinds present in the current graph
- Edge kind → color/dash mapping for all edge kinds present

The legend MUST be auto-generated from the data (not hardcoded list), showing
only kinds that actually appear in the rendered graph.

#### ALG-KK-WEB-DIAGNOSTICS-PAGE

A new HTML route `GET /health` renders the diagnostics report as a
human-readable page. The dashboard MUST link to it. Categories:
- Orphan concepts (Concepts without belongs-to)
- Unlinked invariants (KernelInvariants without governed-by)
- Dangling failure modes (FailureModes without triggered-by)
- Lone protocols (InteractionProtocols with <2 constrains-composition)
- Subsystem coverage (bar chart or table)
- Invariant density ratio
- Duplicate names

#### ALG-KK-WEB-IMPACT-PAGE

A new HTML route `GET /impact/{node_id}` renders the transitive impact
surface as a human-readable page. The concept detail page MUST link to it
for Concept nodes (button: "View Impact Surface").

#### ALG-KK-WEB-COMPARE-PAGE

A new HTML route `GET /compare/{id_a}/{id_b}` renders a side-by-side
comparison of two nodes' neighborhoods. The concept detail page MAY link
to it (with a "Compare with..." picker).

#### INV-KK-WEB-PAGINATION

List pages (`/concepts`, `/subsystems`, `/sources`) MUST support pagination
via `page` and `per_page` query parameters. Default: `page=1, per_page=50`.
SQL queries use `LIMIT ? OFFSET ?`. Template shows page navigation
(previous/next links).

### Implementation Tasks

#### P4-T1: Add `?kind=` filter to `/concepts`

**File:** `src/web/routes.py`, function `concepts_list()`

```python
@app.get("/concepts", response_class=HTMLResponse)
async def concepts_list(request: Request, kind: str = Query(None)):
    conn = request.app.state.conn
    if kind:
        rows = conn.execute(
            "SELECT id, kind, attrs FROM nodes WHERE kind = ? ORDER BY kind, id",
            (kind,),
        ).fetchall()
        title = kind
    else:
        rows = conn.execute(
            "SELECT id, kind, attrs FROM nodes ORDER BY kind, id"
        ).fetchall()
        title = "Knowledge Base"
    nodes = _rows_to_dicts(rows)
    for n in nodes:
        n["display_name"] = display_name_for_node(n["kind"], n.get("attrs") or {}, n["id"])
    return templates.TemplateResponse(
        request, "concept_list.html",
        {"nodes": nodes, "title": title, "active_kind": kind},
    )
```

**File:** `src/web/templates/dashboard.html`

Change kind rows to link to filtered list:
```html
<td><a href="/concepts?kind={{ kind }}">{{ kind }}</a></td>
```

#### P4-T2: Add search endpoint and navbar search box

**File:** `src/web/routes.py` — new route:
```python
@app.get("/api/search")
async def api_search(request: Request, q: str = Query(""), kind: str = Query(None)):
    conn = request.app.state.conn
    if not q.strip():
        return []
    sql = """SELECT id, kind, attrs FROM nodes
             WHERE (json_extract(attrs, '$.name') LIKE ?
                    OR json_extract(attrs, '$.description') LIKE ?
                    OR attrs LIKE ?)"""
    params = [f"%{q}%", f"%{q}%", f"%{q}%"]
    if kind:
        sql += " AND kind = ?"
        params.append(kind)
    sql += " ORDER BY kind, id LIMIT 30"
    rows = conn.execute(sql, params).fetchall()
    results = _rows_to_dicts(rows)
    for r in results:
        r["display_name"] = display_name_for_node(r["kind"], r.get("attrs") or {}, r["id"])
    return results
```

**File:** `src/web/templates/base.html` — add search box after nav links:
```html
<div id="search-container" style="display:inline-block;position:relative;">
  <input type="text" id="search-input" placeholder="Search nodes..."
         hx-get="/api/search" hx-trigger="keyup changed delay:300ms"
         hx-target="#search-results" hx-swap="innerHTML"
         name="q" autocomplete="off">
  <div id="search-results"></div>
</div>
<script src="https://unpkg.com/htmx.org@1.9.12"></script>
```

Create a partial template `search_results.html` for HTMX response rendering.

**Tests:** Test search with matching query returns results, empty query
returns empty, kind filter works.

#### P4-T3: Add graph legend

**File:** `src/web/templates/graph_viz.html`

After the graph container, add a legend div. Populate it dynamically from the
loaded data:
```javascript
// After data loads, build legend from actually-present kinds
const presentKinds = new Set(data.nodes.map(n => n.kind));
const presentEdgeKinds = new Set(links.map(l => l.kind));

const legend = d3.select('#graph-container').append('div')
  .attr('id', 'legend')
  .style('position', 'absolute').style('top', '10px').style('right', '10px')
  .style('background', 'rgba(255,255,255,0.9)').style('padding', '8px')
  .style('border', '1px solid #ccc').style('font-size', '12px');

legend.append('div').text('Node Kinds').style('font-weight', 'bold');
presentKinds.forEach(kind => {
  const row = legend.append('div');
  row.append('span').style('display', 'inline-block')
    .style('width', '12px').style('height', '12px')
    .style('background', kindColor[kind] || 'gray')
    .style('border-radius', '50%').style('margin-right', '4px');
  row.append('span').text(kind);
});

legend.append('div').text('Edge Kinds').style('font-weight', 'bold').style('margin-top', '8px');
presentEdgeKinds.forEach(kind => {
  const row = legend.append('div');
  row.append('span').style('display', 'inline-block')
    .style('width', '20px').style('height', '2px')
    .style('background', edgeColor[kind] || '#ddd')
    .style('margin-right', '4px').style('vertical-align', 'middle');
  row.append('span').text(kind);
});
```

Also: add colors for the remaining 14 edge kinds that currently render as
`#ddd`. Assign distinct colors to at least the 8 most common edge kinds:
```javascript
const edgeColor = {
  'governed-by': '#c0392b',
  'triggered-by': '#e67e22',
  'constrains-composition': '#8e44ad',
  'belongs-to': '#27ae60',
  'extracted-from': '#bdc3c7',
  'refines': '#2980b9',
  'contradicts': '#e74c3c',
  'prerequisite': '#f39c12',
  'profiled-by': '#1abc9c',
  'assesses-compatibility': '#d35400',
  'contributes-to': '#9b59b6',
  'suited-for': '#16a085',
  'compares': '#2c3e50',
  'implemented-in': '#34495e',
  'sourced-from': '#95a5a6',
  'assessed-by': '#7f8c8d',
  'alternative-to': '#3498db',
  'supersedes': '#e67e22',
  'grounded-in': '#bdc3c7',
};
```

#### P4-T4: Add `/health` diagnostics page

**File:** `src/web/routes.py` — new route:
```python
@app.get("/health", response_class=HTMLResponse)
async def health_page(request: Request):
    import dataclasses
    conn = request.app.state.conn
    report = diagnose_graph(conn)
    return templates.TemplateResponse(
        request, "health.html", {"report": dataclasses.asdict(report)},
    )
```

**File:** `src/web/templates/health.html` — new template showing each
diagnostic category with counts, lists of affected node IDs (as links to
detail pages), and the invariant density ratio.

**File:** `src/web/templates/base.html` — add nav link:
```html
<a href="/health">Health</a>
```

**File:** `src/web/templates/dashboard.html` — add link:
```html
<p><a href="/health">View graph health diagnostics →</a></p>
```

#### P4-T5: Add `/impact/{node_id}` HTML page

**File:** `src/web/routes.py` — new route:
```python
@app.get("/impact/{node_id}", response_class=HTMLResponse)
async def impact_page(request: Request, node_id: str):
    conn = request.app.state.conn
    node = get_node(conn, node_id)  # import from graph.engine
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    impact = transitive_impact(conn, node_id)
    node["display_name"] = display_name_for_node(node["kind"], node["attrs"], node["id"])
    return templates.TemplateResponse(
        request, "impact.html", {"node": node, "impact": impact},
    )
```

**File:** `src/web/templates/impact.html` — new template showing categorized
impact surface (invariants, failure_modes, protocols, profiles, goals,
compatibilities, comparatives, scenarios) with links to each node.

**File:** `src/web/templates/concept_detail.html` — for Concept nodes, add:
```html
<a href="/impact/{{ node.id }}">View Impact Surface →</a>
```

#### P4-T6: Add pagination to list routes

**File:** `src/web/routes.py` — modify `concepts_list()`:
```python
async def concepts_list(
    request: Request,
    kind: str = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
):
    conn = request.app.state.conn
    offset = (page - 1) * per_page
    # ... SQL with LIMIT per_page+1 OFFSET offset
    # (fetch per_page+1 to know if there's a next page)
    has_next = len(rows) > per_page
    rows = rows[:per_page]
    ...
    return templates.TemplateResponse(request, "concept_list.html", {
        "nodes": nodes, "title": title,
        "page": page, "per_page": per_page, "has_next": has_next,
    })
```

**File:** `src/web/templates/concept_list.html` — add pagination controls:
```html
<div class="pagination">
  {% if page > 1 %}
    <a href="?page={{ page - 1 }}&per_page={{ per_page }}{% if active_kind %}&kind={{ active_kind }}{% endif %}">← Previous</a>
  {% endif %}
  <span>Page {{ page }}</span>
  {% if has_next %}
    <a href="?page={{ page + 1 }}&per_page={{ per_page }}{% if active_kind %}&kind={{ active_kind }}{% endif %}">Next →</a>
  {% endif %}
</div>
```

---

## Dependency Graph

```
Phase 1 (Labels)
  P1-T1 display_name_for_node()  ← foundation for everything
  P1-T2 concept_list.html        ← depends on P1-T1
  P1-T3 concept_detail.html      ← depends on P1-T1
  P1-T4 node_labels builder      ← depends on P1-T1
  P1-T5 graph_viz tooltip        ← independent (client-side)
  P1-T6 Evidence description     ← depends on P1-T1 for display

Phase 2 (Admissibility)          ← independent of Phase 1
  P2-T1 13 new rules             ← foundation
  P2-T2 cycle detection          ← independent
  P2-T3 delete_edge validation   ← depends on P2-T1
  P2-T4 ingest validation        ← depends on P2-T1

Phase 3 (Extraction)             ← independent of Phase 1; P3-T3 depends on P2-T1
  P3-T1 relationship whitelist   ← depends on P2-T2 (cycle detection for supersedes)
  P3-T2 Advisory contamination   ← independent
  P3-T3 KernelInvariant → Sub    ← depends on P2-T1 (subsystem rule must exist)
  P3-T4 Proposal removal         ← depends on P2-T1 (remove from RULES_BY_KIND)
  P3-T5 Evidence description     ← same as P1-T6 (ingest side)

Phase 4 (Navigation)             ← depends on Phase 1
  P4-T1 kind filter              ← depends on P1-T1
  P4-T2 search                   ← depends on P1-T1
  P4-T3 graph legend             ← independent (client-side)
  P4-T4 health page              ← independent
  P4-T5 impact page              ← depends on P1-T1
  P4-T6 pagination               ← depends on P4-T1
```

## Estimated Scope

| Phase | Tasks | New files | Modified files | New tests |
|-------|-------|-----------|----------------|-----------|
| 1 | 6 | 0 | 5 | ~10 |
| 2 | 4 | 0 | 3 | ~18 |
| 3 | 5 | 0 | 5 | ~8 |
| 4 | 6 | 3 templates | 4 | ~12 |
| **Total** | **21** | **3** | **~12** | **~48** |
