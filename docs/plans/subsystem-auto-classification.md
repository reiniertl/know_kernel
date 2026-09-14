# Plan: Subsystem Auto-Classification

## Problem Statement

After `extract_concepts()` creates Concept nodes, a human must manually create
Subsystem nodes and wire `belongs-to` edges. This is the only manual step in the
ingest -> review -> extract -> export -> MCP pipeline. The graph validation rule
`check_concept_has_belongs_to` fails on any Concept without a `belongs-to` edge,
so export is blocked until a human intervenes (see `test_e2e_pipeline.py:76-78`
where every E2E test manually patches this gap).

## Design Constraints

1. **Class B only.** Subsystem names and the classification decision are abstract
   metadata -- no Class A leakage risk. The LLM already sees the full Evidence
   text during extraction; asking it to also return subsystem labels adds zero
   contamination surface.

2. **Existing Subsystems are reusable.** The LLM should assign to an existing
   Subsystem when one fits, and only suggest new ones when none match.

3. **One LLM call, not two.** The classification prompt is folded into the
   existing extraction call (amend `EXTRACTION_SYSTEM_PROMPT` + `CONCEPT_SCHEMA`)
   rather than adding a second LLM round-trip.

4. **Separation of concerns.** The *classification* logic (resolve LLM label ->
   Subsystem node) is a distinct algorithm from the *extraction* logic.
   `extract_concepts()` must not grow God-like. New functions handle the new
   responsibility.

## Spec Nodes to Create

### New Invariants

| ID | Subsystem | Predicate |
|----|-----------|-----------|
| **INV-KK-CLASSIFY-USES-EXISTING** | SUB-KK-INGEST | If a Subsystem node with a matching name (case-insensitive) already exists in the graph, the classifier MUST reuse it rather than creating a duplicate. |
| **INV-KK-CLASSIFY-CREATES-BELONGS-TO** | SUB-KK-INGEST | Every Concept returned by `extract_concepts()` has at least one `belongs-to` edge to a Subsystem node before the function returns. (Eliminates the manual patching step.) |
| **INV-KK-CLASSIFY-SUBSYSTEM-HAS-NAME** | SUB-KK-INGEST | Every Subsystem node created by the classifier has a non-empty `name` attribute (satisfying `REQUIRED_ATTRS["Subsystem"]`). |

### New Algorithms (Hoare-Triple Style)

Each algorithm is one Python function with explicit pre/postconditions.

---

#### ALG-KK-CLASSIFY-RESOLVE-SUBSYSTEM

- **Function:** `resolve_subsystem(conn, label) -> str`
- **Location:** `src/ingest/classifier.py`
- **Precondition:** `conn` is an open SQLite connection to the master DB with the
  know_kernel schema initialized. `label` is a non-empty string (the subsystem
  name suggested by the LLM).
- **Postcondition:** Returns a `node_id` (string) for a Subsystem node. If a
  Subsystem whose `name` matches `label` case-insensitively already exists,
  returns that node's ID (no new node created --
  **INV-KK-CLASSIFY-USES-EXISTING**). Otherwise, creates a new Subsystem node
  with `{"name": label}` and returns its ID
  (**INV-KK-CLASSIFY-SUBSYSTEM-HAS-NAME**).
- **Side effects:** At most one `INSERT INTO nodes` (the new Subsystem). No edges
  created.
- **Scope:** Subsystem node resolution only. Does not touch Concepts or edges.

---

#### ALG-KK-CLASSIFY-ASSIGN

- **Function:** `assign_subsystems(conn, concept_ids, classifications) -> ClassificationResult`
- **Location:** `src/ingest/classifier.py`
- **Precondition:** `conn` is an open SQLite connection. `concept_ids` is a
  non-empty list of existing Concept node IDs. `classifications` is a
  `dict[str, str]` mapping each `concept_id` -> `subsystem_label` (every
  concept_id in `concept_ids` must be present as a key in `classifications`).
- **Postcondition:** For each `(concept_id, label)` pair: calls
  `resolve_subsystem(conn, label)` to get or create the Subsystem node, then
  creates a `belongs-to` edge from the Concept to that Subsystem. Every
  concept_id in `concept_ids` now has at least one `belongs-to` edge
  (**INV-KK-CLASSIFY-CREATES-BELONGS-TO**). Returns a `ClassificationResult`
  with the mapping of concept_id -> subsystem_id and counts.
- **Side effects:** Creates `belongs-to` edges (one per concept). May create
  Subsystem nodes (via `resolve_subsystem`).
- **Scope:** Edge wiring and Subsystem resolution. Does not call the LLM, does
  not modify Concept nodes.

---

#### ALG-KK-CLASSIFY-PARSE-LLM

- **Function:** `parse_classification_labels(concepts_data, concept_ids) -> dict[str, str]`
- **Location:** `src/ingest/classifier.py`
- **Precondition:** `concepts_data` is the parsed JSON array returned by the LLM
  (list of dicts with `"name"`, `"description"`, `"subsystem"` keys).
  `concept_ids` is the list of node IDs created from that same data, in the same
  order.
- **Postcondition:** Returns a `dict[str, str]` mapping each `concept_id` ->
  `subsystem_label`. If an entry in `concepts_data` has no `"subsystem"` key or
  it's empty, the label defaults to `"Unclassified"`. The returned dict has
  exactly `len(concept_ids)` entries.
- **Side effects:** None (pure function).
- **Scope:** LLM output parsing only. Bridges the gap between the LLM JSON shape
  and the classification input.

---

## Changes to Existing Algorithms

### ALG-KK-LLM-EXTRACT (`extract_concepts` in `extractor.py`)

Modified, not replaced:

1. **Prompt change:** Amend `EXTRACTION_SYSTEM_PROMPT` to add one line to the
   "For each concept, provide:" section:
   ```
   - subsystem: The kernel subsystem this concept belongs to (e.g., "Virtual Memory",
     "Scheduler", "Filesystem", "IPC", "Networking", "Device Drivers", "Security")
   ```

2. **Schema change:** Add `"subsystem": {"type": "string"}` to
   `CONCEPT_SCHEMA.items.properties` and add `"subsystem"` to the `required`
   list.

3. **Post-creation wiring:** After the concept-creation loop (current line 191),
   add a call sequence:
   ```python
   classifications = parse_classification_labels(concepts_data, concept_ids)
   assign_subsystems(conn, concept_ids, classifications)
   ```

4. **ExtractionResult change:** Add a `subsystem_ids: list[str]` field to report
   which Subsystems were used/created.

5. **Existing invariants preserved:** All existing postconditions of
   `extract_concepts` remain unchanged -- Class B output, provenance edges,
   idempotency, session enforcement. The new behavior only *adds* `belongs-to`
   edges and Subsystem nodes.

6. **Idempotency preserved:** When `extract_concepts` hits the early-return path
   (concepts already extracted), `belongs-to` edges already exist from the first
   run. No classification is re-attempted.

### ALG-KK-EXTRACT-CLI (`cli_extract.py`)

Add `subsystem_ids` to the JSON output for each extraction result. No new CLI
flags needed.

## Data Types

```python
@dataclass
class ClassificationResult:
    concept_subsystem_map: dict[str, str]   # concept_id -> subsystem_id
    subsystems_created: int
    subsystems_reused: int
```

## What Does NOT Change

- `schema.py` -- `belongs-to` edge and `Subsystem` node kind already exist.
- `rules.py` -- `check_concept_has_belongs_to` already enforces the invariant.
- `exporter.py` -- `ALLOWED_KINDS` already includes `Subsystem`.
- `pipeline.py` -- ingest is upstream; untouched.
- `reviewer.py` -- review is orthogonal; untouched.

## Test Plan

| Test | Invariant Covered | What It Checks |
|------|-------------------|----------------|
| `test_resolve_existing_subsystem_reuses` | INV-KK-CLASSIFY-USES-EXISTING | Create a Subsystem "Virtual Memory", call `resolve_subsystem(conn, "virtual memory")` (lowercase), verify it returns the existing ID and no new node is created. |
| `test_resolve_new_subsystem_creates` | INV-KK-CLASSIFY-SUBSYSTEM-HAS-NAME | Call `resolve_subsystem(conn, "Scheduler")` with no existing Subsystem, verify a new node is created with `attrs.name == "Scheduler"`. |
| `test_assign_creates_belongs_to_edges` | INV-KK-CLASSIFY-CREATES-BELONGS-TO | Create 2 Concepts, call `assign_subsystems`, verify each has a `belongs-to` edge. |
| `test_assign_reuses_subsystem_across_concepts` | INV-KK-CLASSIFY-USES-EXISTING | Two concepts classified to same label -> one Subsystem node, two `belongs-to` edges. |
| `test_parse_labels_handles_missing_subsystem` | (defensive) | LLM returns concept with no `"subsystem"` key -> defaults to `"Unclassified"`. |
| `test_extract_concepts_now_creates_belongs_to` | INV-KK-CLASSIFY-CREATES-BELONGS-TO | Call `extract_concepts` with mock LLM (updated mock returns `subsystem` field), verify every concept has a `belongs-to` edge immediately. No manual patching needed. |
| `test_extract_concepts_schema_includes_subsystem` | (prompt) | Verify `CONCEPT_SCHEMA` requires `"subsystem"`. |
| **E2E tests updated** | INV-KK-E2E-PIPELINE-SOUND | Remove the manual `add_node("sub-vm"...)` / `add_edge("belongs-to"...)` blocks from all E2E tests. The pipeline produces valid graphs without manual intervention. |

## File Inventory

| File | Action |
|------|--------|
| `src/ingest/classifier.py` | **NEW** -- `resolve_subsystem`, `assign_subsystems`, `parse_classification_labels`, `ClassificationResult` |
| `src/ingest/extractor.py` | **MODIFY** -- prompt, schema, post-creation wiring, `ExtractionResult` dataclass |
| `src/ingest/cli_extract.py` | **MODIFY** -- add `subsystem_ids` to JSON output |
| `tests/test_ingest_classifier.py` | **NEW** -- unit tests for all 3 new algorithms |
| `tests/test_ingest_extractor.py` | **MODIFY** -- update `MockLLMClient` to return `subsystem` field, add belongs-to assertion |
| `tests/test_e2e_pipeline.py` | **MODIFY** -- remove manual Subsystem/belongs-to patches, verify auto-classification |

## Implementation Order

1. **Spec first** -- create the 3 new invariant nodes and 3 new algorithm nodes
   in the spec database.
2. **`classifier.py`** -- implement the 3 new functions + dataclass. Unit-test
   them in `test_ingest_classifier.py`.
3. **`extractor.py`** -- amend prompt, schema, and add post-creation call. Update
   tests in `test_ingest_extractor.py`.
4. **`cli_extract.py`** -- add `subsystem_ids` to JSON output.
5. **E2E tests** -- remove manual patches, verify the pipeline validates cleanly
   end-to-end.
6. **Run full suite** -- `pytest` must stay at 0 failures.

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| LLM returns inconsistent subsystem names ("VM" vs "Virtual Memory" vs "virtual memory") | `resolve_subsystem` does case-insensitive matching. Future: could add a normalization/alias table, but case-insensitive is sufficient for MVP. |
| LLM omits `subsystem` field despite schema | `parse_classification_labels` defaults to `"Unclassified"`, so the graph is always valid. |
| Adding `"subsystem"` to `required` in schema breaks existing LLM responses | Only affects new extractions. Existing concepts already extracted via idempotency guard won't re-run. If the LLM omits it, we fall back to "Unclassified" before the JSON schema enforcement matters (we parse the response ourselves, not via API-level schema enforcement). |
