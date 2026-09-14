# Sprint Plan: Kernel Implementation Tracking + Extraction Prompt Fix

## Overview

This sprint addresses two concerns:

1. **Kernel Implementation Tracking** -- new node kind and edge to record
   which real kernels implement which abstract concepts
2. **Extraction Prompt Fix** -- the HIGH audit finding (F1) that has been
   flagged in every audit since Phase 2: the EXTRACTION_SYSTEM_PROMPT
   does not ask the LLM to produce `compatibility_assessments` or
   `comparative_analyses`, so production extraction silently yields zero
   nodes for those kinds

---

## Part 1: Kernel Implementation Tracking

### Problem Statement

The knowledge graph captures abstract mechanisms (Concepts) without
recording where they are actually implemented. An LLM designing a kernel
can learn "RCU provides lock-free reads with deferred reclamation" but
cannot learn "RCU is production-proven in Linux since 2.5, experimental
in FreeBSD since 9.0, and absent from Zephyr." Without implementation
provenance, the LLM cannot distinguish well-proven patterns from
theoretical proposals, and humans cannot filter by "show me everything
Linux uses that we haven't adopted yet."

### Design

#### New Node Kind: Kernel

A lightweight grouping node (same pattern as Subsystem).

```python
NODE_KINDS = (..., "Kernel")

REQUIRED_ATTRS["Kernel"] = (
    "name",             # "Linux", "FreeBSD", "Zephyr", "seL4", etc.
    "description",      # Brief description of the kernel
    "kernel_type",      # "monolithic" | "microkernel" | "rtos" | "hybrid" | "unikernel"
)
```

#### New Edge Kind: implemented-in

Directed edge from Concept to Kernel, with attrs carrying relationship
details.

```python
EDGE_KINDS = (..., "implemented-in")

EDGE_VALID_PAIRS["implemented-in"] = ("Concept", "Kernel")
```

Edge attrs:
```python
{
    "since_version": "2.5",           # Version where first introduced (optional)
    "maturity": "production",          # "production" | "experimental" | "deprecated" | "removed"
    "variant_notes": "Tree RCU...",    # How this kernel's version differs (optional)
}
```

#### Data Model Properties

- **One Concept can be implemented in many Kernels** (RCU is in Linux,
  FreeBSD, etc.)
- **One Kernel has many Concepts** (Linux implements RCU, slab, spinlock,
  etc.)
- **Edge attrs carry the per-implementation details** -- version, maturity,
  variant notes
- **Kernel nodes are seeded/curated** (like OptimizationGoal and
  UseCaseScenario) -- not LLM-extracted. Implementation claims need to be
  accurate.
- **No provenance edge** -- Kernel is not extracted from Evidence. It is
  a reference entity.

#### New Functions (optimization.py)

```python
def create_kernel(conn, name, description, kernel_type) -> str:
    """Create a Kernel node. Validates kernel_type enum."""

def link_concept_to_kernel(
    conn, concept_id, kernel_id, since_version="", maturity="production", variant_notes=""
) -> None:
    """Create implemented-in edge with attrs. Validates maturity enum."""
```

#### Export / MCP Impact

- Add `"Kernel"` to `ALLOWED_KINDS` in exporter (12 kinds total)
- Kernel nodes appear in snapshot and are searchable via MCP
- `transitive_impact()` does NOT traverse implemented-in (it's concept
  outward, not concept-inward) -- but `subgraph_around()` and
  `compare_neighborhoods()` will naturally include Kernel neighbors
- New MCP tool candidate: `find_implementations(concept_id)` -- returns
  all Kernels implementing a concept, or `find_concepts_in_kernel(kernel_name)`
  -- returns all concepts in a kernel. These could also be deferred to a
  later sprint if we just want the data model now.

#### New Invariants

| ID | Predicate |
|----|-----------|
| INV-KK-KERNEL-HAS-NAME | Every Kernel node has a non-empty name string |
| INV-KK-KERNEL-HAS-TYPE | Every Kernel node has kernel_type in {monolithic, microkernel, rtos, hybrid, unikernel} |
| INV-KK-KERNEL-NO-PROVENANCE | Kernel nodes do not have extracted-from edges (seeded, not LLM-extracted) |
| INV-KK-IMPL-MATURITY | Every implemented-in edge has maturity in {production, experimental, deprecated, removed} |

#### New Algorithms

| ID | Function |
|----|----------|
| ALG-KK-CREATE-KERNEL | create_kernel(conn, name, description, kernel_type) |
| ALG-KK-LINK-CONCEPT-KERNEL | link_concept_to_kernel(conn, concept_id, kernel_id, ...) |

#### Tests (6)

| Test | What |
|------|------|
| test_create_kernel | Happy path, correct attrs |
| test_create_kernel_invalid_type | Rejects invalid kernel_type |
| test_link_concept_to_kernel | Edge with correct attrs |
| test_link_concept_to_kernel_invalid_maturity | Rejects invalid maturity |
| test_kernel_in_snapshot | Kernel nodes survive Class B export |
| test_kernel_no_provenance | No extracted-from edge on Kernel |

---

## Part 2: Extraction Prompt Fix (F1 + F2)

### Problem Statement

`EXTRACTION_SYSTEM_PROMPT` line 86-88 tells the LLM:

```
Return a JSON object with "concepts" (array, at most 10) and
"interaction_protocols" (array, at most 5).
```

The orchestrator (line 741-742) reads:

```python
compat_data = parsed.get("compatibility_assessments", [])
comparative_data = parsed.get("comparative_analyses", [])
```

But the LLM is never told to produce these keys. Tests pass only because
MockLLMClient injects them. In production, the LLM will never produce
`compatibility_assessments` or `comparative_analyses`, and those node
kinds will silently remain empty.

Additionally, `build_compatibility_prompt()` (line 580) and
`build_profile_extraction_prompt()` (line 450) are defined but never
called by the orchestrator.

### Fix

**F1 fix:** Update line 86-88 of EXTRACTION_SYSTEM_PROMPT to:

```
Return a JSON object with:
- "concepts" (array, at most 10)
- "interaction_protocols" (array, at most 5)
- "compatibility_assessments" (array, at most 5)
- "comparative_analyses" (array, at most 5)
Focus on the most significant ideas.
```

Add corresponding sections to the prompt body (before the return
instruction) describing what each top-level key should contain:

- `compatibility_assessments`: synergy analysis between concept pairs
  (synergy, rationale, conditions, concept_a, concept_b)
- `comparative_analyses`: head-to-head comparisons on specific dimensions
  (dimension, winner, conditions, quantitative_delta, concept_a, concept_b)

**F2 fix:** Remove `build_compatibility_prompt()` and
`build_profile_extraction_prompt()`. These were designed for a
second-pass extraction model that was never adopted. All extraction
happens in a single LLM call. The corresponding spec ALG nodes
(ALG-KK-EXTRACT-BUILD-COMPAT-PROMPT, ALG-KK-EXTRACT-BUILD-PROFILE-PROMPT)
should be removed from the DAG.

### Tests

| Test | What |
|------|------|
| test_extraction_prompt_mentions_all_keys | Verify EXTRACTION_SYSTEM_PROMPT contains all 4 return keys |
| test_mock_extraction_produces_all_kinds | E2E with MockLLMClient, verify all node kinds created |

---

## Implementation Stages

| Stage | Type | Scope | Spec Nodes | Est. Complexity |
|-------|------|-------|------------|-----------------|
| 1 | spec | Kernel + implemented-in spec surface | ~4 INV, 2 ALG, 1 IF, schema updates | Low |
| 2 | code | Kernel schema + optimization.py + tests | schema.py, optimization.py, exporter.py, 6 tests | Medium |
| 3 | audit | Milestone check | -- | Read-only |
| 4 | spec | F1/F2 spec updates | Remove 2 ALG nodes, update prompt spec | Low |
| 5 | code | Extraction prompt fix + dead code removal + tests | extractor.py, 2 tests | Low |
| 6 | code | E2E update with Kernel nodes | test_e2e_pipeline.py | Low |
| 7 | audit | Final sprint audit | -- | Read-only |

**Totals:** 5 code stages, 2 audit stages, ~4 new invariants, ~2 new
algorithms, ~1 new interface, ~8 new tests, 2 dead functions removed,
2 dead spec nodes removed.

---

## Graph Shape After Sprint

```
Subsystem
  ^ belongs-to
Concept <-- governed-by -- KernelInvariant
  |                            ^ triggered-by
  |-- refines --> Concept    FailureMode
  |-- contradicts -> Concept
  |-- prerequisite -> Concept
  |-- implemented-in -> Kernel        <<< NEW
  |
  |<-- profiled-by -- PerformanceProfile
  |<-- assesses-compatibility -- CompatibilityAssessment --> Concept
  |<-- compares -- ComparativeAnalysis --> Concept
  |
  |-- contributes-to -> OptimizationGoal
  |-- suited-for -> UseCaseScenario
  |
  |<-- constrains-composition -- InteractionProtocol --> Concept
```

Final graph: **15 node kinds**, **19 edge kinds**, 9 MCP tools,
6 query functions.

---

## LLM Query Chain Enhancement

With Kernel nodes, the LLM reasoning chain gains production-provenance:

```
Question ("design a subsystem using RCU + slab allocation")
  -> Query relevant Concepts
  -> Follow implemented-in edges:
      "RCU: production in Linux since 2.5, experimental in FreeBSD"
      "Slab: production in Linux since 2.2, production in FreeBSD since 5.0"
  -> Confidence assessment: both are production-proven across multiple kernels
  -> ...rest of reasoning chain...
  -> Generate design with:
      uses: [Concepts]
      proven-in: [Kernels with maturity=production]   <<< NEW
      preserves: [safety invariants]
      ...
```

---

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Kernel implementation data is hard to verify | Manual curation only -- no LLM extraction of implementation claims |
| Too many Kernel nodes dilute the graph | Start with 5-8 major kernels (Linux, FreeBSD, NetBSD, Zephyr, seL4, MINIX, QNX, Fuchsia) |
| implemented-in edge attrs are incomplete | All attrs except maturity are optional (since_version, variant_notes can be empty) |
| F1 fix changes LLM output format | Existing single-call pattern is preserved. Only the return instruction changes. MockLLMClient already produces the right format. |
| F2 removal breaks callers | grep confirms no callers of the dead functions outside their definitions |
