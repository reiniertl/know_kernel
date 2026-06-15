# Plan: Operational Knowledge Extraction (Invariants, Failure Modes, Interaction Protocols)

## Vision

The rich concept extraction pipeline (Stages 1-8) captures what kernel
mechanisms *are* and how they *relate*. But a kernel-design intelligence
system must go further — it must capture the knowledge that lets an LLM
reason about **correctness**, **failure**, and **composition** of abstract
mechanisms across any kernel implementation.

This plan adds three layers of operational knowledge to the concept graph,
each building on the previous:

| Phase | Node Kind | Question Answered | LLM Use Case |
|-------|-----------|-------------------|--------------|
| **Phase 1** | KernelInvariant | What must hold? | Constrain mutation plans: "preserve these rules" |
| **Phase 2** | FailureMode | What breaks and how? | Prioritize constraints: "this violation causes data corruption vs this one causes a regression" |
| **Phase 3** | InteractionProtocol | How must mechanisms compose? | Validate designs: "combining these two mechanisms requires this coordination" |

All three are **abstract kernel-design knowledge**, not tied to any specific
kernel's source tree. "Memory allocation under spinlock requires non-sleeping
allocation" is a universal kernel design rule. The graph captures mechanism
intelligence that applies to Linux, FreeBSD, Zephyr, a custom RTOS, or a
kernel designed from scratch.

---

# Phase 1: Kernel Invariant Extraction

## Problem Statement

From "Read-Copy-Update" we extract the property "grace period defers
reclamation safely" but not the checkable invariant *"no reader can observe
a partially-updated data structure"*. These invariants are the most valuable
output — they're what an LLM needs to verify when designing, modifying, or
composing mechanisms.

Currently, invariant-like statements are buried as informal strings in
`key_properties`. They cannot be queried, linked, classified by strength, or
reasoned about independently.

## Design Goals

1. **First-class invariant nodes.** Each kernel invariant is a separate graph
   node with a structured predicate, strength classification, and scope.

2. **Governed-by edges.** Every invariant links back to the Concept(s) it
   governs, making it queryable: "what invariants constrain RCU?"

3. **LLM-extracted.** The extraction prompt asks the LLM to identify
   invariants per concept. A separate validation + storage function handles
   them, following the same pattern as `validate_extraction_item` /
   `store_rich_concept`.

4. **Class B safe.** Invariants are abstract properties expressed in the LLM's
   own words — no verbatim content. They pass through the contamination gate
   and appear in the exported snapshot.

5. **Composable with Proposals.** The existing `grounded-in` edge
   (Proposal → Concept) lets proposals reference concepts. With invariants,
   a proposal can also declare which invariants it *must preserve* or
   *intentionally relaxes* — but that's a future extension, not part of
   Phase 1.

## Design Constraints

1. **Class B only.** Invariant predicates are abstract restatements, not
   quotes. Same anti-verbatim rules as concepts.

2. **No new edge kinds beyond what's needed.** One new edge kind:
   `governed-by` (KernelInvariant → Concept). Reuse existing `belongs-to`
   for subsystem classification.

3. **Separation of concerns.** Two new algorithms: one for validation
   (`validate_invariant_item`), one for storage (`store_kernel_invariant`).
   The orchestrator calls them after concept extraction, in sequence.

4. **Backward compatible.** Existing concepts, edges, tests, and exports
   continue to work unchanged. KernelInvariant is additive.

## Schema Changes

### NODE_KINDS

```python
NODE_KINDS = (..., "KernelInvariant")
```

### EDGE_KINDS + EDGE_VALID_PAIRS

```python
EDGE_KINDS = (..., "governed-by")

EDGE_VALID_PAIRS["governed-by"] = ("KernelInvariant", "Concept")
```

Note: `belongs-to` currently maps `("Concept", "Subsystem")`. We need to
support `("KernelInvariant", "Subsystem")` too. This requires changing
`EDGE_VALID_PAIRS` from `dict[str, tuple[str, str]]` to
`dict[str, list[tuple[str, str]]]` — or adding a second entry like
`"ki-belongs-to"`. The multi-pair approach is cleaner; evaluate during
Stage 1.

### REQUIRED_ATTRS

```python
REQUIRED_ATTRS["KernelInvariant"] = (
    "predicate",          # Natural-language invariant statement
    "strength",           # "safety" | "liveness" | "performance" | "structural"
    "scope",              # "per-operation" | "per-object" | "system-wide"
    "artifact_class",     # Always "abstracted-mechanism" (Class B)
)
```

### ALLOWED_KINDS (exporter)

```python
ALLOWED_KINDS = ("Concept", "Subsystem", "Proposal", "KernelInvariant")
```

## New Data Types

```python
@dataclass
class KernelInvariantItem:
    predicate: str        # "No reader can observe a partially-updated structure"
    strength: str         # "safety" | "liveness" | "performance" | "structural"
    scope: str            # "per-operation" | "per-object" | "system-wide"
    concept_name: str     # Name of the concept this invariant governs

VALID_STRENGTHS = {"safety", "liveness", "performance", "structural"}
VALID_SCOPES = {"per-operation", "per-object", "system-wide"}
```

### Strength Classification

| Strength | Meaning | Example |
|----------|---------|---------|
| **safety** | Must never be violated; violation = data corruption or undefined behavior | "No reader observes a partially-updated data structure" (RCU) |
| **liveness** | Must eventually hold; violation = deadlock or starvation | "All pre-existing readers complete within a bounded grace period" (RCU) |
| **performance** | Quantitative bound; violation = regression, not incorrectness | "Task selection completes in O(log n)" (CFS rbtree) |
| **structural** | Architectural constraint; violation = design inconsistency | "Every runnable task appears in exactly one runqueue" |

### Scope Classification

| Scope | Meaning | Example |
|-------|---------|---------|
| **per-operation** | Holds for each individual invocation | "kmalloc returns aligned memory" |
| **per-object** | Holds for each instance over its lifetime | "vruntime is monotonically increasing per task" |
| **system-wide** | Holds globally across the entire subsystem | "Total allocated slabs never exceed zone high watermark" |

## New Invariants (combobul spec DAG)

| ID | Predicate |
|----|-----------|
| **INV-KK-KINV-HAS-PREDICATE** | Every KernelInvariant node has a non-empty `predicate` string in its attrs. |
| **INV-KK-KINV-HAS-STRENGTH** | Every KernelInvariant node has a `strength` value in {safety, liveness, performance, structural}. |
| **INV-KK-KINV-GOVERNED-BY** | Every KernelInvariant node has exactly one `governed-by` edge to a Concept node. |
| **INV-KK-KINV-PROVENANCE** | Every KernelInvariant node has an `extracted-from` edge to the same Evidence node as its governing Concept. |

## New Algorithms (Hoare-Triple Style)

### ALG-KK-EXTRACT-VALIDATE-INVARIANT

- **Function:** `validate_invariant_item(item) -> dict | None`
- **Precondition:** `item` is a value from the LLM JSON (expected dict).
- **Postcondition:** If `item` has required keys (`predicate`, `strength`,
  `scope`, `concept_name`) and `predicate` is non-empty and `strength` is
  in VALID_STRENGTHS and `scope` is in VALID_SCOPES: returns sanitized copy.
  Otherwise returns None.
- **Side effects:** None (pure function).

### ALG-KK-EXTRACT-STORE-INVARIANT

- **Function:** `store_kernel_invariant(conn, item, evidence_id, concept_name_to_id) -> str | None`
- **Precondition:** `conn` is open SQLite. `item` is validated dict.
  `evidence_id` is existing Evidence. `concept_name_to_id` maps concept
  names to IDs from current batch.
- **Postcondition:** If `concept_name` matches a concept in the batch: a new
  KernelInvariant node exists with predicate, strength, scope,
  artifact_class="abstracted-mechanism". Edges: `governed-by` →
  Concept, `extracted-from` → Evidence. Returns invariant ID.
  If concept not found: returns None, no side effects.
- **Side effects:** One INSERT into nodes, two INSERT into edges (on match).

## Changes to Existing Spec

### EXTRACTION_SYSTEM_PROMPT

Add after the `relationships` field:

```
- invariants: A list of rules or properties that MUST HOLD for this concept
  to function correctly. Each entry has:
  - predicate: A clear statement of what must be true (e.g., "No reader
    can observe a partially-updated data structure")
  - strength: One of "safety" (violation = corruption), "liveness"
    (violation = deadlock/starvation), "performance" (violation = regression),
    "structural" (violation = design inconsistency)
  - scope: One of "per-operation", "per-object", "system-wide"
  Extract 1-3 invariants per concept. Focus on the most critical rules.
  If a concept has no clear invariants, use an empty list.
```

### CONCEPT_SCHEMA

Add to items.properties:
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

Add `"invariants"` to items.required.

### ExtractionResult

Add field: `invariants_created: int = 0`

### ALG-KK-LLM-EXTRACT (extract_concepts)

After `wire_relationships()`, add:

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

## Phase 1 Test Plan

| Test | Invariant Covered |
|------|-------------------|
| `test_validate_invariant_valid` | (defensive) |
| `test_validate_invariant_missing_predicate` | (defensive) |
| `test_validate_invariant_empty_predicate` | INV-KK-KINV-HAS-PREDICATE |
| `test_validate_invariant_invalid_strength` | INV-KK-KINV-HAS-STRENGTH |
| `test_validate_invariant_invalid_scope` | (defensive) |
| `test_store_invariant_creates_node` | INV-KK-KINV-HAS-PREDICATE, HAS-STRENGTH |
| `test_store_invariant_governed_by_edge` | INV-KK-KINV-GOVERNED-BY |
| `test_store_invariant_provenance_edge` | INV-KK-KINV-PROVENANCE |
| `test_store_invariant_unknown_concept_returns_none` | (defensive) |
| `test_extract_concepts_invariants_end_to_end` | All |
| `test_invariants_in_snapshot` | Class B export |
| `test_invariants_not_class_a` | Contamination gate |

## Phase 1 Implementation Stages

| Stage | What | Spec Nodes |
|-------|------|-----------|
| 1 | Spec: create 4 invariant nodes + 2 algorithm nodes | INV-KK-KINV-* (4), ALG-KK-EXTRACT-VALIDATE-INVARIANT, ALG-KK-EXTRACT-STORE-INVARIANT |
| 2 | Spec: update ALG-KK-LLM-EXTRACT, IF-KK-EXTRACTION-PROMPT, IF-KK-EXTRACTION-RESULT | (modify existing) |
| 3 | Schema: add KernelInvariant to NODE_KINDS, governed-by to EDGE_KINDS, update EDGE_VALID_PAIRS, REQUIRED_ATTRS, ALLOWED_KINDS | (code) |
| 4 | Code: implement validate_invariant_item + store_kernel_invariant + unit tests | (code) |
| 5 | Code: update EXTRACTION_SYSTEM_PROMPT, CONCEPT_SCHEMA, extract_concepts orchestration | (code) |
| 6 | Tests: update mocks for invariant fields, add E2E invariant assertions | (code) |
| 7 | Audit: verify spec-code-test alignment, run full suite | (read-only) |

---

# Phase 2: Failure Mode Extraction

## Problem Statement

Invariants tell the LLM *what must hold*. But not all invariant violations
are equal. An LLM reasoning about a kernel design needs to know:
"if I violate this invariant, does the system crash, corrupt data, deadlock,
or just get slower?" Without failure severity, every invariant looks equally
important — the LLM either treats everything as a hard blocker (overly
cautious) or nothing as one (dangerous).

Failure modes are abstract kernel-design knowledge. "Violating vruntime
totality causes priority inversion leading to unbounded latency for high-
priority tasks" is true regardless of which kernel implements the mechanism.

## Node Design

```python
NODE_KINDS = (..., "FailureMode")

REQUIRED_ATTRS["FailureMode"] = (
    "symptom",            # Observable behavior: "priority inversion", "deadlock", "data corruption"
    "blast_radius",       # "local" | "subsystem" | "kernel-wide"
    "recoverability",     # "self-healing" | "requires-restart" | "data-loss"
    "artifact_class",     # Always "abstracted-mechanism" (Class B)
)

EDGE_KINDS = (..., "triggered-by")
EDGE_VALID_PAIRS["triggered-by"] = ("FailureMode", "KernelInvariant")
```

### Edge Semantics

- **triggered-by** (FailureMode → KernelInvariant): "This failure mode
  occurs when this invariant is violated." One failure mode links to exactly
  one invariant. An invariant may have multiple failure modes (a safety
  invariant violation may cause both data corruption AND a kernel panic).

### Blast Radius Classification

| Blast Radius | Meaning | Example |
|-------------|---------|---------|
| **local** | Affects only the immediate caller/object | "Misaligned kmalloc return → single struct corruption" |
| **subsystem** | Affects the containing subsystem | "Scheduler priority inversion → all tasks in affected runqueue delayed" |
| **kernel-wide** | Affects the entire kernel or causes halt | "Page table corruption → kernel panic on next TLB miss" |

### Recoverability Classification

| Recoverability | Meaning | Example |
|---------------|---------|---------|
| **self-healing** | System recovers without intervention | "Performance degradation from suboptimal scheduling — resolves when load changes" |
| **requires-restart** | Subsystem or kernel must restart | "Deadlock in lock ordering — requires process kill or reboot" |
| **data-loss** | Irrecoverable corruption | "Partially-updated data structure visible to readers — inconsistent state propagates" |

## How This Helps the LLM

When an LLM considers relaxing an invariant, the failure mode tells it
the cost. This enables informed tradeoff reasoning:

- **safety invariant** + **kernel-wide** blast + **data-loss**: absolute blocker,
  design must preserve this
- **performance invariant** + **local** blast + **self-healing**: acceptable
  regression, document and monitor
- **liveness invariant** + **subsystem** blast + **requires-restart**: serious
  concern, must prove bounded wait or add timeout

## Extraction Approach

Failure modes are extracted per invariant, nested inside the invariant's
LLM output:

```json
{
  "predicate": "No reader observes partially-updated data",
  "strength": "safety",
  "scope": "per-operation",
  "failure_modes": [
    {
      "symptom": "Data corruption visible to concurrent readers",
      "blast_radius": "kernel-wide",
      "recoverability": "data-loss"
    }
  ]
}
```

This keeps extraction atomic — one LLM call produces concepts, invariants,
and failure modes together. The orchestrator calls `validate_failure_mode`
and `store_failure_mode` in sequence, same pattern as all prior phases.

## Phase 2 Implementation Stages

| Stage | What |
|-------|------|
| 1 | Spec: invariant + algorithm nodes for FailureMode |
| 2 | Schema: add FailureMode kind, triggered-by edge, REQUIRED_ATTRS |
| 3 | Code: validate + store functions, orchestration update |
| 4 | Tests + mocks + E2E |
| 5 | Audit |

## Phase 2 Depends On

Phase 1 (KernelInvariant) must be complete — FailureMode links to
KernelInvariant via `triggered-by`.

---

# Phase 3: Interaction Protocol Extraction

## Problem Statement

Concepts have static relationships (refines, contradicts, prerequisite).
But these don't capture the **runtime coordination rules** that govern how
mechanisms must be used together. "Memory allocation under spinlock requires
non-sleeping allocation" is not a property of either mechanism alone — it's
a rule about their *composition*.

These protocols are where most kernel bugs live: not in single-mechanism
logic, but in incorrect composition. An LLM designing a new subsystem that
uses both locking and memory allocation needs to know these coordination
rules to produce correct designs.

Like invariants and failure modes, these are **universal kernel design
rules** — they apply to any kernel that implements these mechanisms, not
just Linux.

## Node Design

```python
NODE_KINDS = (..., "InteractionProtocol")

REQUIRED_ATTRS["InteractionProtocol"] = (
    "rule",               # The coordination rule in natural language
    "ordering",           # "before" | "after" | "never-during" | "must-hold-while"
    "violation_mode",     # What happens on violation: references a failure mode or describes inline
    "artifact_class",     # Always "abstracted-mechanism" (Class B)
)

EDGE_KINDS = (..., "constrains-composition")
EDGE_VALID_PAIRS["constrains-composition"] = [
    ("InteractionProtocol", "Concept"),  # one edge per participating concept
]
```

### Edge Semantics

- **constrains-composition** (InteractionProtocol → Concept): "This
  protocol constrains the use of this concept when composed with another."
  Each InteractionProtocol has exactly 2 constrains-composition edges —
  one per participating concept. The protocol is *about* the pair.

### Ordering Classification

| Ordering | Meaning | Example |
|----------|---------|---------|
| **before** | Mechanism A must complete before B starts | "Lock acquisition must complete before shared data access" |
| **after** | Mechanism A must happen after B | "synchronize_rcu() must be called after pointer swap before freeing old data" |
| **never-during** | A must not occur while B is active | "Sleeping allocation must never occur while spinlock is held" |
| **must-hold-while** | A must remain active throughout B | "Preemption must be disabled while per-CPU data is accessed" |

## Examples Across the PoC Graph

| Protocol | Concept A | Concept B | Ordering |
|----------|-----------|-----------|----------|
| "Non-sleeping allocation under spinlock" | Spinlock | GFP Flag Allocation Control | never-during |
| "Grace period before reclamation" | Read-Copy-Update | Slab Object Caching | before |
| "TLB flush after page table update" | Five-Level Page Table Hierarchy | TLB Translation Caching | after |
| "Preemption disabled during per-CPU slab access" | Spinlock | Slab Object Caching | must-hold-while |

Note how these cross subsystem boundaries (Locking × Memory Management,
Virtual Memory × Locking). This is precisely the cross-cutting knowledge
that a flat concept list cannot represent.

## How This Helps the LLM

When an LLM designs a system that touches multiple subsystems, it queries:
"what InteractionProtocols constrain the concepts I'm composing?" The
answer is a checklist of coordination rules that must be satisfied. Without
this, the LLM produces designs that are individually correct per-mechanism
but violate composition rules.

The combination of all three phases creates a full operational reasoning
chain:

```
LLM receives design question about kernel subsystem
  → Query relevant Concepts                  (what mechanisms exist)
  → Follow relationship edges                (how they relate statically)
  → Query KernelInvariants via governed-by   (what must hold per mechanism)
  → Query FailureModes via triggered-by      (what happens if rules break)
  → Query InteractionProtocols               (how mechanisms must coordinate)
  → Generate design with:
      uses: [Concepts]
      preserves: [safety invariants — non-negotiable]
      benchmarks: [performance invariants — measure after]
      coordinates: [interaction protocols — composition rules]
      risk-accepts: [failure modes with local blast + self-healing]
```

## Extraction Approach

Interaction protocols cannot be extracted per-concept (they describe pairs).
They require a **second-pass extraction** after all concepts are stored:

```python
# After concepts + invariants + failure modes are stored:
protocol_prompt = build_protocol_extraction_prompt(concept_summaries)
protocol_response = client.create_message(...)
for proto in protocol_response:
    validated = validate_protocol_item(proto, name_to_id)
    if validated:
        store_interaction_protocol(conn, validated, evidence_id, name_to_id)
```

This is the first extraction step that requires a **separate LLM call**
(or a clearly distinct section in the same call). The prompt provides the
list of extracted concept names and asks: "what coordination rules govern
the composition of these mechanisms?"

Alternatively, protocols could be extracted in the same call by adding a
top-level `interaction_protocols` array alongside the concept array. This
avoids a second API call but makes the prompt more complex. Evaluate during
Phase 3 implementation.

## Phase 3 Implementation Stages

| Stage | What |
|-------|------|
| 1 | Spec: invariant + algorithm nodes for InteractionProtocol |
| 2 | Schema: add InteractionProtocol kind, constrains-composition edge |
| 3 | Code: validate + store functions, extraction prompt, orchestration |
| 4 | Tests + mocks + E2E |
| 5 | Audit |

## Phase 3 Depends On

Phase 1 (KernelInvariant) must be complete. Phase 2 (FailureMode) is
recommended but not strictly required — protocols can reference violation
modes inline if no FailureMode nodes exist yet.

---

# Cross-Phase File Inventory

| File | Phase 1 | Phase 2 | Phase 3 |
|------|---------|---------|---------|
| `combobul/spec/spec.db` | MODIFY | MODIFY | MODIFY |
| `src/graph/schema.py` | MODIFY | MODIFY | MODIFY |
| `src/graph/rules.py` | MODIFY | MODIFY | MODIFY |
| `src/ingest/extractor.py` | MODIFY | MODIFY | MODIFY |
| `src/export/exporter.py` | MODIFY | MODIFY | MODIFY |
| `tests/test_ingest_extractor.py` | MODIFY | MODIFY | MODIFY |
| `tests/test_e2e_pipeline.py` | MODIFY | MODIFY | MODIFY |
| `tests/conftest.py` | MODIFY | MODIFY | MODIFY |

# What Does NOT Change (Across All Phases)

- `classifier.py` — subsystem classification (new node kinds inherit their
  concept's subsystem via edges, no separate classification needed)
- `graph/engine.py` — add_node, add_edge unchanged (just new kinds/edges)
- `mcp_server/server.py` — new node kinds flow through existing queries
- Session gate, idempotency, anti-verbatim rules — all preserved
- Existing Concept nodes, edges, attrs — unchanged

# Risks and Mitigations

| Risk | Phase | Mitigation |
|------|-------|-----------|
| LLM produces vague invariants ("it works correctly") | 1 | Prompt gives concrete examples per strength class. Validator rejects empty/short predicates. |
| LLM confuses properties with invariants | 1 | Prompt explicitly distinguishes: properties describe *what is*, invariants describe *what must hold*. |
| Too many invariants per concept inflates graph | 1 | Cap at 3 per concept in extraction loop. Validate before store. |
| EDGE_VALID_PAIRS refactor for multi-source `belongs-to` | 1 | Evaluate simplest approach: multi-pair dict, union type, or separate edge kind. |
| LLM invents failure modes not implied by the invariant | 2 | Failure modes are nested inside invariants in the prompt, constraining them to the invariant's scope. |
| LLM produces trivial protocols ("use locks correctly") | 3 | Prompt requires concrete ordering + specific concept pair. Validator rejects protocols without two named concepts. |
| Second LLM call for protocols doubles API cost | 3 | Evaluate single-call approach (top-level array) first. Fall back to second call only if prompt quality degrades. |
| New node kinds break existing tests | 1-3 | All additions are strictly additive — no existing test creates or queries these kinds. Only new tests + E2E updates needed. |
| Invariant predicates contain verbatim text | 1-3 | Same anti-verbatim rules apply. Validators could add heuristic length/similarity checks (future). |

# Complete Graph Shape (After All Phases)

```
Subsystem
  ^ belongs-to
Concept <-- governed-by -- KernelInvariant
  |                            ^ triggered-by
  |-- refines --> Concept    FailureMode
  |-- contradicts -> Concept
  |-- prerequisite -> Concept
  |-- extracted-from -> Evidence
  |
  |<-- profiled-by -- PerformanceProfile
  |<-- assesses-compatibility -- CompatibilityAssessment --> Concept
  |<-- compares -- ComparativeAnalysis --> Concept
  |-- contributes-to -> OptimizationGoal
  |-- suited-for -> UseCaseScenario
  |<-- constrains-composition -- InteractionProtocol --> Concept

Proposal
  |-- grounded-in -> Concept
  |-- (future) preserves -> KernelInvariant
  |-- (future) relaxes -> KernelInvariant
```

This graph answers: what exists (Concepts), how it relates (edges), what
must hold (KernelInvariants), what breaks (FailureModes), how things
compose (InteractionProtocols), how fast they are (PerformanceProfiles),
whether they compose well (CompatibilityAssessments), how they compare
(ComparativeAnalyses), what goals they serve (OptimizationGoals), and
what workloads they suit (UseCaseScenarios) -- the complete operational
and optimization knowledge an LLM needs to reason about kernel design.
