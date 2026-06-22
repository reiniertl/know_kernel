# Phase 1: KernelInvariant Extraction — Detailed Implementation Plan

## Vision: Why KernelInvariant Matters for the Knowledge Base

The know_kernel knowledge base currently captures **what mechanisms are** (Concept
nodes) and **how they relate** (refines, contradicts, prerequisite edges). Rich
concept extraction added structured properties (key_properties, tradeoffs,
design_rationale) and inter-concept relationships. But the graph still cannot
answer the most critical question for kernel design intelligence:

> "What rules must hold for this mechanism to be correct?"

KernelInvariant nodes close that gap. They elevate informal invariant-like
statements — currently buried as unstructured strings in `key_properties` — into
first-class graph citizens that are:

- **Queryable:** "What invariants constrain RCU?" returns a structured list.
- **Classified:** Each invariant has a `strength` (safety/liveness/performance/
  structural) and `scope` (per-operation/per-object/system-wide), enabling
  severity-aware reasoning.
- **Linked:** Every invariant connects to its governing Concept via a
  `governed-by` edge and to its source Evidence via `extracted-from`.
- **Composable:** Future extensions (Phase 2 FailureMode, Phase 3
  InteractionProtocol) build directly on KernelInvariant nodes.

### How the LLM Uses KernelInvariants

When an LLM queries the graph to design or modify a kernel subsystem, the
reasoning chain becomes:

```
1. Query relevant Concepts          → "What mechanisms exist?"
2. Follow relationship edges        → "How do they relate statically?"
3. Query KernelInvariants           → "What must hold per mechanism?"
   via governed-by edges
4. Classify by strength + scope     → "Which rules are non-negotiable?"
5. Generate design that:
     preserves: [safety invariants — absolute blockers]
     benchmarks: [performance invariants — measure after implementation]
     documents: [structural invariants — design consistency checks]
```

Without KernelInvariants, the LLM has no structured correctness knowledge. It
either treats everything as equally important (overly cautious) or ignores
constraints entirely (dangerous). The strength classification enables nuanced
tradeoff reasoning.

### Examples of KernelInvariants (Abstract, Implementation-Agnostic)

These are universal kernel design rules, not tied to any specific kernel:

| Concept | Invariant Predicate | Strength | Scope |
|---------|-------------------|----------|-------|
| Read-Copy-Update | "No reader can observe a partially-updated data structure" | safety | per-operation |
| Read-Copy-Update | "All pre-existing readers complete within a bounded grace period" | liveness | per-object |
| CFS Red-Black Tree | "Task selection completes in O(log n) time" | performance | system-wide |
| CFS Red-Black Tree | "Every runnable task appears in exactly one runqueue" | structural | system-wide |
| Slab Allocator | "kmalloc returns naturally-aligned memory for the requested size" | safety | per-operation |
| Slab Allocator | "Total allocated slabs never exceed the zone high watermark" | performance | system-wide |
| Page Table Hierarchy | "A valid virtual address maps to exactly one physical frame" | safety | per-operation |
| Spinlock | "No thread holds the same spinlock it already holds" | safety | per-operation |

---

## Specification Surface

### New Invariant Spec Nodes (4 nodes, under SUB-KK-INGEST)

These are the spec-level invariants that govern how KernelInvariant nodes
must be constructed in the application graph. They are checked at stage-delivery
and enforced by the algorithms that create KernelInvariant nodes.

#### INV-KK-KINV-HAS-PREDICATE

- **Predicate:** Every KernelInvariant node created by extraction has a non-empty
  `predicate` string in its attrs.
- **Rationale:** The predicate is the core content — a clear, checkable statement
  of what must be true. An invariant without a predicate is meaningless.
- **Enforcement:** `validate_invariant_item()` rejects items where predicate is
  missing, not a string, or whitespace-only. `store_kernel_invariant()` stores
  the validated predicate as a node attribute.
- **Test coverage:** `test_validate_invariant_missing_predicate`,
  `test_validate_invariant_empty_predicate`, `test_store_invariant_creates_node`.

#### INV-KK-KINV-HAS-STRENGTH

- **Predicate:** Every KernelInvariant node created by extraction has a `strength`
  value in the set {safety, liveness, performance, structural}.
- **Rationale:** Strength classification is what enables severity-aware reasoning.
  Without it, an LLM cannot distinguish between "violating this causes data
  corruption" and "violating this causes a 5% regression."
- **Enforcement:** `validate_invariant_item()` checks `strength in VALID_STRENGTHS`.
  Rejects any value outside the allowed set.
- **Test coverage:** `test_validate_invariant_invalid_strength`,
  `test_store_invariant_creates_node`.

#### INV-KK-KINV-GOVERNED-BY

- **Predicate:** Every KernelInvariant node has exactly one `governed-by` edge
  to a Concept node.
- **Rationale:** An invariant must be anchored to the mechanism it constrains.
  Floating invariants are unqueryable — there's no way to ask "what constrains
  this concept?" without the edge. Exactly one Concept per invariant keeps the
  graph clean; if the same rule applies to multiple mechanisms, each gets its
  own KernelInvariant node with a governed-by edge.
- **Enforcement:** `store_kernel_invariant()` creates the governed-by edge
  as part of the storage transaction. If the concept_name doesn't match a
  concept in the current batch, the function returns None and no node is created.
- **Test coverage:** `test_store_invariant_governed_by_edge`,
  `test_store_invariant_unknown_concept_returns_none`.

#### INV-KK-KINV-PROVENANCE

- **Predicate:** Every KernelInvariant node has an `extracted-from` edge to the
  same Evidence node as its governing Concept.
- **Rationale:** Provenance traceability. Every piece of extracted knowledge must
  link back to the source material it was derived from. This enables auditing:
  "where did this invariant come from?" and supports future re-extraction when
  source material is updated.
- **Enforcement:** `store_kernel_invariant()` creates the extracted-from edge
  using the same evidence_id passed to the extraction orchestrator.
- **Test coverage:** `test_store_invariant_provenance_edge`.

### New Algorithm Spec Nodes (2 nodes, under SUB-KK-INGEST)

#### ALG-KK-EXTRACT-VALIDATE-INVARIANT

- **Function:** `validate_invariant_item(item) -> dict | None`
- **Location:** `src/ingest/extractor.py`
- **Hoare triple:**
  - **Pre:** `item` is a value from the LLM JSON `invariants` array. Expected to
    be a dict but may be anything if LLM output is malformed.
  - **Post:** Returns a sanitized dict if ALL of the following hold:
    - `item` is a dict
    - Required keys present: `predicate`, `strength`, `scope`, `concept_name`
    - `predicate` is a non-empty string after strip
    - `strength` is in VALID_STRENGTHS = {safety, liveness, performance, structural}
    - `scope` is in VALID_SCOPES = {per-operation, per-object, system-wide}
    - `concept_name` is a non-empty string after strip
    Returns None otherwise.
  - **Side effects:** None (pure function).
- **Satisfies:** Defensive validation gate — no invariant is satisfied directly,
  but this function is the precondition for `store_kernel_invariant()`.
- **Edge wiring:** contains from SUB-KK-INGEST, runs-at stage-delivery.

#### ALG-KK-EXTRACT-STORE-INVARIANT

- **Function:** `store_kernel_invariant(conn, item, evidence_id, concept_name_to_id) -> str | None`
- **Location:** `src/ingest/extractor.py`
- **Hoare triple:**
  - **Pre:** `conn` is an open SQLite connection. `item` is a validated dict
    (output of `validate_invariant_item`). `evidence_id` is an existing Evidence
    node ID. `concept_name_to_id` is a `dict[str, str]` mapping lowercase
    concept names to concept IDs from the current extraction batch.
  - **Post:** If `item["concept_name"]` matches a concept in the batch
    (case-insensitive lookup):
    - A new KernelInvariant node exists with:
      - `predicate` = item["predicate"]
      - `strength` = item["strength"]
      - `scope` = item["scope"]
      - `artifact_class` = "abstracted-mechanism"
    - A `governed-by` edge connects KernelInvariant → matched Concept
    - An `extracted-from` edge connects KernelInvariant → evidence_id
    - Returns the new invariant ID (format: `kinv-{uuid.hex[:12]}`)
    If concept not found: returns None, no side effects.
  - **Side effects:** One INSERT into nodes, two INSERT into edges (on match).
- **Satisfies:** INV-KK-KINV-HAS-PREDICATE, INV-KK-KINV-HAS-STRENGTH,
  INV-KK-KINV-GOVERNED-BY, INV-KK-KINV-PROVENANCE.
- **Edge wiring:** contains from SUB-KK-INGEST, runs-at stage-delivery,
  satisfies edges to all 4 invariant spec nodes.

### New Interface Spec Node (1 node, under SUB-KK-GRAPH)

#### IF-KK-KERNEL-INVARIANT

- **Kind:** interface
- **Location:** SUB-KK-GRAPH (it's a graph schema element)
- **Content:** The KernelInvariant node schema:
  ```
  predicate:      str   — Natural-language invariant statement
  strength:       str   — "safety" | "liveness" | "performance" | "structural"
  scope:          str   — "per-operation" | "per-object" | "system-wide"
  artifact_class: str   — Always "abstracted-mechanism" (Class B)
  ```
- **Edge wiring:** contains from SUB-KK-GRAPH.

### Existing Nodes Updated (4 nodes)

#### ALG-KK-LLM-EXTRACT (update)

- **Change:** Description extended: after `wire_relationships()`, the orchestrator
  iterates over each concept's `invariants` array, calls `validate_invariant_item`
  then `store_kernel_invariant`.
- **New edges:** satisfies edges to INV-KK-KINV-HAS-PREDICATE,
  INV-KK-KINV-HAS-STRENGTH, INV-KK-KINV-GOVERNED-BY, INV-KK-KINV-PROVENANCE.

#### IF-KK-EXTRACTION-PROMPT (update)

- **Change:** CONCEPT_SCHEMA now includes an `invariants` array per concept with
  `predicate`, `strength`, `scope` fields. EXTRACTION_SYSTEM_PROMPT includes
  invariant extraction instructions with examples per strength class.

#### IF-KK-EXTRACTION-RESULT (update)

- **Change:** ExtractionResult dataclass gains `invariants_created: int = 0`.

#### IF-KK-CONCEPT (update)

- **Change:** Description updated to note that Concept nodes may have associated
  KernelInvariant nodes linked via `governed-by` edges.

---

## Classification Systems

### Strength Classification

The strength classification answers: "How bad is it if this invariant is violated?"

| Strength | Violation means | LLM reasoning impact | Examples |
|----------|----------------|---------------------|----------|
| **safety** | Data corruption, undefined behavior, security vulnerability. The system enters an unrecoverable invalid state. | **Absolute blocker.** The LLM must preserve this invariant in any design. No tradeoff is acceptable. | "No reader observes a partially-updated data structure" (RCU). "A valid virtual address maps to exactly one physical frame" (page tables). "No thread holds the same spinlock it already holds" (spinlocks). |
| **liveness** | Deadlock, starvation, unbounded blocking. The system stops making progress. | **Serious concern.** The LLM must prove bounded wait or add timeout/recovery. Relaxation requires explicit justification. | "All pre-existing readers complete within a bounded grace period" (RCU). "Every waiting thread eventually acquires the lock" (fair locking). "The OOM killer terminates at least one process when memory is exhausted" (memory management). |
| **performance** | Quantitative regression — slower, more memory, higher latency. System is still correct. | **Document and benchmark.** The LLM should note the expected cost and recommend measurement. Acceptable if the tradeoff is worth it. | "Task selection completes in O(log n)" (CFS). "Slab allocation amortizes to O(1) per object" (slab allocator). "TLB miss resolution requires at most 5 page table walks" (5-level paging). |
| **structural** | Architectural inconsistency — design constraint violated but no immediate runtime failure. May cause subtle bugs over time. | **Design review flag.** The LLM should warn about the inconsistency and recommend restructuring, but it's not a correctness issue. | "Every runnable task appears in exactly one runqueue" (scheduler). "Every slab belongs to exactly one cache" (slab allocator). "Lock ordering follows the documented hierarchy" (lock ordering). |

### Scope Classification

The scope classification answers: "At what granularity does this rule apply?"

| Scope | Granularity | What it constrains | Examples |
|-------|-------------|-------------------|----------|
| **per-operation** | Each individual invocation of the mechanism. The invariant must hold for every single call. | Function contracts, input/output guarantees, atomicity properties. | "kmalloc returns naturally-aligned memory for the requested size." "rcu_read_lock/unlock are always paired within the same context." "spin_lock disables preemption before acquiring." |
| **per-object** | Each instance of a managed entity over its lifetime. The invariant must hold from creation to destruction. | Object lifecycle properties, monotonicity, state machine constraints. | "vruntime is monotonically increasing per task." "A page's refcount never goes negative." "A file descriptor is valid from open() until close()." |
| **system-wide** | The entire subsystem or kernel globally. The invariant is an aggregate property. | Resource bounds, global ordering, partition properties. | "Total allocated slabs never exceed the zone high watermark." "The sum of all task weights equals the total weight of the runqueue." "No two CPUs hold the same spinlock simultaneously." |

---

## Schema Changes (Code Layer)

### NODE_KINDS

```python
# src/graph/schema.py
NODE_KINDS = (
    "Evidence", "Concept", "Subsystem", "Proposal",
    "PerformanceProfile", "CompatibilityAssessment",
    "ComparativeAnalysis", "OptimizationGoal",
    "UseCaseScenario", "Kernel",
    "KernelInvariant",  # NEW — Phase 1
)
```

### EDGE_KINDS

```python
# src/graph/schema.py
EDGE_KINDS = (
    ...,  # existing edge kinds
    "governed-by",  # NEW — KernelInvariant -> Concept
)
```

### EDGE_VALID_PAIRS (Refactor Required)

Current structure is `dict[str, tuple[str, str]]` — one valid pair per edge kind.
KernelInvariant requires reusing `belongs-to` and `extracted-from` for a second
source node kind. The refactor changes the value type to support lists:

```python
# Before:
EDGE_VALID_PAIRS = {
    "belongs-to": ("Concept", "Subsystem"),
    "extracted-from": ("Concept", "Evidence"),
    ...
}

# After:
EDGE_VALID_PAIRS = {
    "belongs-to": [("Concept", "Subsystem"), ("KernelInvariant", "Subsystem")],
    "extracted-from": [("Concept", "Evidence"), ("KernelInvariant", "Evidence")],
    "governed-by": ("KernelInvariant", "Concept"),  # single pair, no list needed
    ...
}
```

The `add_edge()` validation in `engine.py` must be updated to handle both
`tuple[str, str]` and `list[tuple[str, str]]` values.

### REQUIRED_ATTRS

```python
REQUIRED_ATTRS["KernelInvariant"] = (
    "predicate",       # Natural-language invariant statement
    "strength",        # "safety" | "liveness" | "performance" | "structural"
    "scope",           # "per-operation" | "per-object" | "system-wide"
    "artifact_class",  # Always "abstracted-mechanism" (Class B)
)
```

### ALLOWED_KINDS (Exporter)

```python
# src/export/exporter.py
ALLOWED_KINDS = ("Concept", "Subsystem", "Proposal", ..., "KernelInvariant")
```

---

## New Functions (Code Layer)

### validate_invariant_item()

```python
VALID_STRENGTHS = {"safety", "liveness", "performance", "structural"}
VALID_SCOPES = {"per-operation", "per-object", "system-wide"}

def validate_invariant_item(item) -> dict | None:
    """Validate a raw LLM invariant dict. Returns sanitized copy or None."""
    if not isinstance(item, dict):
        return None

    required = ("predicate", "strength", "scope", "concept_name")
    for key in required:
        if key not in item:
            return None

    predicate = item["predicate"]
    if not isinstance(predicate, str) or not predicate.strip():
        return None

    strength = item["strength"]
    if strength not in VALID_STRENGTHS:
        return None

    scope = item["scope"]
    if scope not in VALID_SCOPES:
        return None

    concept_name = item["concept_name"]
    if not isinstance(concept_name, str) or not concept_name.strip():
        return None

    return {
        "predicate": predicate.strip(),
        "strength": strength,
        "scope": scope,
        "concept_name": concept_name.strip(),
    }
```

### store_kernel_invariant()

```python
def store_kernel_invariant(conn, item, evidence_id, concept_name_to_id) -> str | None:
    """Create a KernelInvariant node with governed-by + extracted-from edges."""
    concept_id = concept_name_to_id.get(item["concept_name"].lower())
    if not concept_id:
        return None

    kinv_id = f"kinv-{uuid.uuid4().hex[:12]}"

    add_node(conn, kinv_id, "KernelInvariant", {
        "predicate": item["predicate"],
        "strength": item["strength"],
        "scope": item["scope"],
        "artifact_class": "abstracted-mechanism",
    })

    add_edge(conn, "governed-by", kinv_id, concept_id)
    add_edge(conn, "extracted-from", kinv_id, evidence_id)

    return kinv_id
```

### Orchestrator Update (extract_concepts)

After the existing `wire_relationships()` call:

```python
invariants_created = 0
for item in concepts_data[:10]:
    if not isinstance(item, dict):
        continue
    for inv in item.get("invariants", []):
        inv["concept_name"] = item.get("name", "")
        validated = validate_invariant_item(inv)
        if validated is None:
            continue
        inv_id = store_kernel_invariant(conn, validated, evidence_id, name_to_id)
        if inv_id:
            invariants_created += 1
```

---

## Prompt Changes

### EXTRACTION_SYSTEM_PROMPT Addition

After the existing `relationships` field instruction, add:

```
- invariants: A list of rules or properties that MUST HOLD for this concept
  to function correctly. Each entry has:
  - predicate: A clear statement of what must be true (e.g., "No reader
    can observe a partially-updated data structure")
  - strength: One of "safety" (violation = corruption/undefined behavior),
    "liveness" (violation = deadlock/starvation), "performance" (violation =
    regression, not incorrectness), "structural" (violation = design
    inconsistency)
  - scope: One of "per-operation" (holds for each invocation), "per-object"
    (holds for each instance over its lifetime), "system-wide" (holds
    globally across the subsystem)
  Extract 1-3 invariants per concept. Focus on the most critical rules
  that distinguish this mechanism from alternatives. If a concept has no
  clear invariants, use an empty list.
```

### CONCEPT_SCHEMA Addition

Add to `items.properties`:

```json
"invariants": {
  "type": "array",
  "items": {
    "type": "object",
    "properties": {
      "predicate": {"type": "string"},
      "strength": {"type": "string"},
      "scope": {"type": "string"}
    },
    "required": ["predicate", "strength", "scope"]
  }
}
```

Add `"invariants"` to `items.required`.

### ExtractionResult Update

```python
@dataclass
class ExtractionResult:
    concepts_created: int = 0
    concepts_skipped: int = 0
    relationships_created: int = 0
    relationships_skipped: int = 0
    invariants_created: int = 0  # NEW
```

---

## Contamination Safety (Class B)

KernelInvariant nodes are **Class B** (abstracted-mechanism). The invariant
predicates are abstract restatements of correctness properties, not verbatim
quotes from source material. The same anti-verbatim rules that apply to Concept
descriptions apply here:

- The LLM generates predicates in its own words.
- No copying of exact sentences from the Evidence text.
- The `artifact_class` is always "abstracted-mechanism".

KernelInvariant nodes pass through the contamination gate and appear in
exported snapshots. They are included in ALLOWED_KINDS for the exporter and
are visible via MCP tools.

---

## Implementation Stages (9 Steps)

### P1-S1: Specify KernelInvariant invariant nodes

- **Skill:** /cb-green
- **What:** Create 4 new invariant spec nodes in `spec.db`:
  INV-KK-KINV-HAS-PREDICATE, INV-KK-KINV-HAS-STRENGTH,
  INV-KK-KINV-GOVERNED-BY, INV-KK-KINV-PROVENANCE.
- **For each node:**
  - INSERT into nodes(id, kind) VALUES ('<id>', 'invariant')
  - INSERT node_properties: label, predicate, predicateNL, predicateAuthority,
    riStatus, enforced, description
  - INSERT edge: SUB-KK-INGEST contains <id>
  - INSERT edge: <id> checked-at stage-delivery
- **Validation:** `npm run spec:check`
- **Output:** 4 new spec nodes with correct edge wiring.

### P1-S2: Specify KernelInvariant algorithm and interface nodes

- **Skill:** /cb-green
- **What:** Create ALG-KK-EXTRACT-VALIDATE-INVARIANT,
  ALG-KK-EXTRACT-STORE-INVARIANT, IF-KK-KERNEL-INVARIANT.
- **For algorithms:**
  - INSERT node + edges (contains from SUB-KK-INGEST, runs-at stage-delivery,
    satisfies to each enforced invariant)
- **For interface:**
  - INSERT node in SUB-KK-GRAPH, contains edge from SUB-KK-GRAPH
- **Cross-references:** All 4 invariant nodes from Stage 1.
- **Validation:** `npm run spec:check`
- **Output:** 2 algorithm nodes + 1 interface node.

### P1-S3: Update existing spec nodes for KernelInvariant

- **Skill:** /cb-green
- **What:** Update 4 existing spec nodes:
  1. ALG-KK-LLM-EXTRACT — update description + add 4 satisfies edges
  2. IF-KK-EXTRACTION-PROMPT — update description for invariants field
  3. IF-KK-EXTRACTION-RESULT — add invariants_created field
  4. IF-KK-CONCEPT — note governed-by linkage
- **Validation:** `npm run spec:check`
- **Output:** 4 updated nodes, 4 new satisfies edges.

### P1-AUDIT-A: Verify Phase 1 spec completeness

- **Skill:** /cb-audit (read-only)
- **Checkpoints:**
  1. All 4 new invariants exist with correct edges (contains, checked-at)
  2. Both new algorithms exist with correct edges (contains, runs-at, satisfies)
  3. IF-KK-KERNEL-INVARIANT exists in SUB-KK-GRAPH
  4. ALG-KK-LLM-EXTRACT has 4 new satisfies edges
  5. Every new invariant has at least one algorithm that satisfies it
  6. No orphaned nodes
  7. `npm run spec:check` passes
  8. pytest confirms no regressions

### P1-S4: Implement schema changes

- **Skill:** /cb-green
- **What:** Five changes:
  A. `schema.py` — Add "KernelInvariant" to NODE_KINDS
  B. `schema.py` — Add "governed-by" to EDGE_KINDS
  C. `schema.py` — Refactor EDGE_VALID_PAIRS for multi-pair support. Add:
     - "governed-by": ("KernelInvariant", "Concept")
     - "belongs-to": [("Concept", "Subsystem"), ("KernelInvariant", "Subsystem")]
     - "extracted-from": [("Concept", "Evidence"), ("KernelInvariant", "Evidence")]
  D. `schema.py` — Add REQUIRED_ATTRS["KernelInvariant"]
  E. `exporter.py` — Add "KernelInvariant" to ALLOWED_KINDS
- **Engine update:** `engine.py` add_edge validation for list pairs.
- **New tests (6):**
  - test_kernel_invariant_node_creation
  - test_governed_by_edge_valid
  - test_governed_by_edge_invalid_source
  - test_belongs_to_kernel_invariant
  - test_extracted_from_kernel_invariant
  - test_kernel_invariant_in_snapshot
- **Validation:** pytest tests/ — all pass.

### P1-S5: Implement validate_invariant_item() and store_kernel_invariant()

- **Skill:** /cb-green
- **What:** Add two functions to `src/ingest/extractor.py`:
  - `validate_invariant_item(item) -> dict | None`
  - `store_kernel_invariant(conn, item, evidence_id, concept_name_to_id) -> str | None`
- **New tests (10):**
  - test_validate_invariant_valid
  - test_validate_invariant_missing_predicate
  - test_validate_invariant_empty_predicate
  - test_validate_invariant_invalid_strength
  - test_validate_invariant_invalid_scope
  - test_validate_invariant_strips_strings
  - test_store_invariant_creates_node
  - test_store_invariant_governed_by_edge
  - test_store_invariant_provenance_edge
  - test_store_invariant_unknown_concept_returns_none
- **Validation:** pytest tests/test_ingest_extractor.py -k "invariant"

### P1-S6: Rewire orchestrator, update prompt and schema constants

- **Skill:** /cb-green
- **What:** Three changes in `src/ingest/extractor.py`:
  A. EXTRACTION_SYSTEM_PROMPT — add invariant extraction instructions
  B. CONCEPT_SCHEMA — add invariants to items.properties + items.required
  C. extract_concepts() — add invariant iteration loop after wire_relationships()
  D. ExtractionResult — add invariants_created field
- **Note:** Do NOT run full test suite — existing mocks lack invariants field.
  Verify only: `python -c "from ingest.extractor import CONCEPT_SCHEMA; assert 'invariants' in CONCEPT_SCHEMA['items']['properties']"`
- **Validation:** Import check only (mocks updated in next stage).

### P1-S7: Update all mocks and tests for KernelInvariant

- **Skill:** /cb-green
- **What:** Update every test file that mocks LLM responses:
  A. `tests/test_ingest_extractor.py` — MockLLMClient concepts get invariants
     field. Add integration tests:
     - test_extract_concepts_invariants_end_to_end
     - test_extract_concepts_invariant_governed_by
     - test_extract_concepts_invariants_created_count
  B. `tests/test_e2e_pipeline.py` — MockLLMClient updated. New assertions:
     - KernelInvariant nodes exist after extraction
     - Snapshot contains KernelInvariant nodes after export
     - governed-by edges survive export
  C. `tests/conftest.py` — Update fixtures if needed
  D. All other test files with MockLLMClient
- **Validation:** pytest tests/ — ALL tests pass. Target: 350+ tests, 0 failures.

### P1-AUDIT-B: Final Phase 1 audit

- **Skill:** /cb-audit (read-only)
- **Comprehensive audit covering:**
  1. **SPEC:** 4 new invariants, 2 new algorithms, IF-KK-KERNEL-INVARIANT,
     4 updated nodes — all with correct edges and satisfies wiring
  2. **CODE:** validate_invariant_item, store_kernel_invariant exist.
     extract_concepts calls them. EXTRACTION_SYSTEM_PROMPT has invariant
     fields. CONCEPT_SCHEMA has invariants property. REQUIRED_ATTRS has
     KernelInvariant. ALLOWED_KINDS includes KernelInvariant.
     EDGE_VALID_PAIRS supports governed-by and multi-pair belongs-to.
  3. **TESTS:** All pass. Each new invariant has test coverage.
     KernelInvariant nodes appear in exported snapshot.
  4. **INVARIANT COVERAGE MATRIX:**
     - INV-KK-KINV-HAS-PREDICATE: tested by store_invariant + E2E
     - INV-KK-KINV-HAS-STRENGTH: tested by validate + store
     - INV-KK-KINV-GOVERNED-BY: tested by store_invariant + E2E
     - INV-KK-KINV-PROVENANCE: tested by store_invariant
  5. **REGRESSIONS:** All prior invariants still hold. pytest 0 failures.
  6. **CONTAMINATION:** KernelInvariant is Class B. Export + MCP still clean.
  7. Run pytest + spec:check.

---

## Test Plan (Complete)

### Unit Tests — Validation

| Test | What it checks | Invariant covered |
|------|---------------|-------------------|
| test_validate_invariant_valid | Complete item returns sanitized dict | (defensive) |
| test_validate_invariant_missing_predicate | Missing predicate key returns None | (defensive) |
| test_validate_invariant_empty_predicate | Whitespace-only predicate returns None | INV-KK-KINV-HAS-PREDICATE |
| test_validate_invariant_invalid_strength | "critical" (not in set) returns None | INV-KK-KINV-HAS-STRENGTH |
| test_validate_invariant_invalid_scope | "global" (not in set) returns None | (defensive) |
| test_validate_invariant_strips_strings | Whitespace trimmed from all string fields | (defensive) |
| test_validate_invariant_not_dict | Non-dict input (string, list, int) returns None | (defensive) |

### Unit Tests — Storage

| Test | What it checks | Invariant covered |
|------|---------------|-------------------|
| test_store_invariant_creates_node | Node exists with all 4 required attrs | INV-KK-KINV-HAS-PREDICATE, HAS-STRENGTH |
| test_store_invariant_governed_by_edge | governed-by edge from KernelInvariant to Concept | INV-KK-KINV-GOVERNED-BY |
| test_store_invariant_provenance_edge | extracted-from edge to Evidence | INV-KK-KINV-PROVENANCE |
| test_store_invariant_unknown_concept_returns_none | Unmatched concept_name returns None, no node created | (defensive) |
| test_store_invariant_artifact_class | artifact_class is "abstracted-mechanism" | Class B safety |

### Integration Tests — Extraction Pipeline

| Test | What it checks | Invariant covered |
|------|---------------|-------------------|
| test_extract_concepts_invariants_end_to_end | Full extraction with mock LLM, KernelInvariant nodes exist with correct attrs | All 4 |
| test_extract_concepts_invariant_governed_by | governed-by edge from KernelInvariant to correct Concept | INV-KK-KINV-GOVERNED-BY |
| test_extract_concepts_invariants_created_count | result.invariants_created matches actual node count | IF-KK-EXTRACTION-RESULT |
| test_extract_concepts_invariant_invalid_skipped | Invalid invariants in LLM response are silently skipped | (defensive) |

### Schema Tests

| Test | What it checks | Invariant covered |
|------|---------------|-------------------|
| test_kernel_invariant_node_creation | add_node with KernelInvariant kind succeeds | IF-KK-KERNEL-INVARIANT |
| test_governed_by_edge_valid | KernelInvariant -> Concept accepted | EDGE_VALID_PAIRS |
| test_governed_by_edge_invalid_source | Concept -> Concept rejected for governed-by | EDGE_VALID_PAIRS |
| test_belongs_to_kernel_invariant | KernelInvariant -> Subsystem accepted | Multi-pair EDGE_VALID_PAIRS |
| test_extracted_from_kernel_invariant | KernelInvariant -> Evidence accepted | Multi-pair EDGE_VALID_PAIRS |
| test_kernel_invariant_in_snapshot | Exported snapshot includes KernelInvariant nodes | INV-KK-SNAPSHOT-ALLOWED-KINDS |

### E2E Tests

| Test | What it checks | Invariant covered |
|------|---------------|-------------------|
| test_e2e_pipeline_with_invariants | Full pipeline: ingest -> extract -> export includes KernelInvariant | INV-KK-E2E-PIPELINE-SOUND |
| test_e2e_governed_by_in_export | governed-by edges survive export | INV-KK-KINV-GOVERNED-BY |

---

## Graph Shape After Phase 1

```
                    Subsystem
                      ^
                      | belongs-to
                      |
Evidence <── extracted-from ── Concept ←── governed-by ── KernelInvariant
                                 |                              |
                                 |                    extracted-from
                                 |                              |
                                 |                              v
                                 |                           Evidence
                                 |
                                 |── refines ──────> Concept
                                 |── contradicts ──> Concept
                                 |── prerequisite ─> Concept
                                 |
                                 |<── profiled-by ────── PerformanceProfile
                                 |<── assesses ───────── CompatibilityAssessment
                                 |<── compares ───────── ComparativeAnalysis
                                 |── contributes-to ──> OptimizationGoal
                                 |── suited-for ──────> UseCaseScenario
```

KernelInvariant is the foundation node for Phase 2 (FailureMode -> triggered-by
-> KernelInvariant) and Phase 3 (InteractionProtocol -> constrains-composition
-> Concept pair). The three phases together complete the operational reasoning
chain:

```
Concepts        → What mechanisms exist
Relationships   → How they relate statically
Invariants      → What must hold per mechanism        (Phase 1)
Failure Modes   → What happens if rules break         (Phase 2)
Protocols       → How mechanisms must coordinate      (Phase 3)
```

---

## Dependencies

- **Requires complete:** Rich concept extraction (Stages 1-8) — done.
- **Requires complete:** Kernel node kind + implemented-in edge — done.
- **Requires complete:** Extraction prompt fix (F1/F2) — done.
- **Blocks:** Phase 2 (FailureMode) — triggered-by edge targets KernelInvariant.
- **Blocks:** Phase 3 (InteractionProtocol) — conceptually dependent but not
  structurally (protocols link to Concepts, not KernelInvariants).

---

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| LLM produces vague invariants ("it works correctly") | Medium | Low — validator rejects, just means fewer invariants | Prompt gives concrete examples per strength class. Validator rejects empty/short predicates. |
| LLM confuses properties with invariants | Medium | Low — still useful knowledge, just miscategorized | Prompt explicitly distinguishes: properties describe *what is*, invariants describe *what must hold*. |
| Too many invariants per concept inflates graph | Low | Medium — graph becomes noisy | Cap at 3 per concept in extraction loop (item.get("invariants", [])[:3]). |
| EDGE_VALID_PAIRS refactor breaks existing edge validation | Low | High — regression in all edge creation | Comprehensive tests for all existing edge kinds before and after refactor. Multi-pair support is backward compatible (single tuple still works). |
| New required attrs in CONCEPT_SCHEMA break LLM responses | Low | Medium — extraction fails silently | invariants field has a schema default of empty array. validate_invariant_item handles missing/malformed gracefully. |
| Existing test mocks missing invariants field cause failures | Certain | Low — expected, handled in Stage 7 | Stage 6 deliberately skips full test suite. Stage 7 is dedicated to mock updates. |

---

## File Inventory

| File | Action | Stage |
|------|--------|-------|
| `spec.db` | MODIFY — new + updated spec nodes | S1, S2, S3 |
| `src/graph/schema.py` | MODIFY — NODE_KINDS, EDGE_KINDS, EDGE_VALID_PAIRS, REQUIRED_ATTRS | S4 |
| `src/graph/engine.py` | MODIFY — add_edge multi-pair validation | S4 |
| `src/export/exporter.py` | MODIFY — ALLOWED_KINDS | S4 |
| `src/ingest/extractor.py` | MODIFY — new functions, prompt, schema, orchestrator | S5, S6 |
| `tests/test_graph_schema.py` | MODIFY — new schema tests | S4 |
| `tests/test_graph_engine.py` | MODIFY — new edge validation tests | S4 |
| `tests/test_ingest_extractor.py` | MODIFY — new validation/storage tests, mock updates | S5, S7 |
| `tests/test_e2e_pipeline.py` | MODIFY — invariant E2E assertions, mock updates | S7 |
| `tests/conftest.py` | MODIFY — fixture updates if needed | S7 |

## What Does NOT Change

- `classifier.py` — subsystem classification untouched (KernelInvariants inherit
  their concept's subsystem via governed-by edge traversal)
- `mcp_server/server.py` — new node kinds flow through existing queries as-is
- Session gate, idempotency, anti-verbatim rules — all preserved
- Existing Concept nodes, edges, attrs — unchanged (additive feature)
- All other existing node kinds — unchanged
