# Plan: Rich Concept Extraction

## Problem Statement

Current extraction produces stub concepts: a name, one-line description, and a
subsystem label. The graph schema supports 5 inter-concept edge kinds (`refines`,
`contradicts`, `prerequisite`, `alternative-to`, `supersedes`) but extraction
never populates them. Concept nodes carry no structured properties or tradeoff
analysis. The result is a knowledge graph with isolated stubs that produce
meaningless reports.

## Design Constraints

1. **Class B only.** New fields (key_properties, tradeoffs, design_rationale)
   are abstract metadata — no Class A leakage. The LLM already sees the full
   Evidence text; asking it to return richer structure adds zero contamination.

2. **No new edge kinds.** All needed relationship types (`refines`,
   `contradicts`, `prerequisite`) already exist in `EDGE_VALID_PAIRS`. We
   only wire them.

3. **Existing extract_concepts() stays as orchestrator.** It already handles
   session gate, idempotency, LLM call, concept creation, and classification.
   New responsibilities are factored into separate algorithms that
   extract_concepts calls — it does NOT grow new logic inline.

4. **Separation of concerns.** Four new algorithms, each a Hoare triple with
   a single responsibility. extract_concepts orchestrates them in sequence.

## New Invariants

| ID | Subsystem | Predicate |
|----|-----------|-----------|
| **INV-KK-CONCEPT-HAS-PROPERTIES** | SUB-KK-INGEST | Every Concept node created by extraction has a non-empty `key_properties` list (at least 1 entry) in its attrs. |
| **INV-KK-CONCEPT-HAS-TRADEOFFS** | SUB-KK-INGEST | Every Concept node created by extraction has a `tradeoffs` list in its attrs (may be empty if the mechanism has no known tradeoffs, but the field must exist). |
| **INV-KK-CONCEPT-HAS-RATIONALE** | SUB-KK-INGEST | Every Concept node created by extraction has a non-empty `design_rationale` string in its attrs explaining why this approach exists. |
| **INV-KK-EXTRACT-RELATIONSHIPS-VALID** | SUB-KK-INGEST | Every inter-concept edge created by `wire_relationships()` uses a kind in {`refines`, `contradicts`, `prerequisite`} and both endpoints are Concept nodes from the same extraction batch. No dangling edges. |

## New Algorithms (Hoare-Triple Style)

### ALG-KK-EXTRACT-STORE-RICH-CONCEPT

- **Function:** `store_rich_concept(conn, item, evidence_id) -> str`
- **Location:** `src/ingest/extractor.py`
- **Precondition:** `conn` is open SQLite. `item` is a dict with keys `name`
  (str), `description` (str), `key_properties` (list[str], len >= 1),
  `tradeoffs` (list[str]), `design_rationale` (str, non-empty), `subsystem`
  (str). `evidence_id` is an existing Evidence node ID.
- **Postcondition:** A new Concept node exists with `artifact_class =
  "abstracted-mechanism"`, `name`, `description`, `key_properties`,
  `tradeoffs`, `design_rationale` stored in attrs
  (**INV-KK-CONCEPT-HAS-PROPERTIES**, **INV-KK-CONCEPT-HAS-TRADEOFFS**,
  **INV-KK-CONCEPT-HAS-RATIONALE**). An `extracted-from` edge connects it
  to `evidence_id` (**INV-KK-EXTRACT-PROVENANCE**). Returns the new concept
  ID.
- **Side effects:** One INSERT into nodes, one INSERT into edges.
- **Scope:** Single concept creation. Does not touch subsystems, does not
  wire relationships.

### ALG-KK-EXTRACT-WIRE-RELATIONSHIPS

- **Function:** `wire_relationships(conn, concepts_data, concept_name_to_id) -> RelationshipResult`
- **Location:** `src/ingest/extractor.py`
- **Precondition:** `conn` is open SQLite. `concepts_data` is the parsed LLM
  JSON array (list of dicts, each may have a `relationships` key containing a
  list of `{target: str, kind: str, reason: str}`). `concept_name_to_id` is a
  `dict[str, str]` mapping lowercase concept name to concept ID, covering all
  concepts in the current batch.
- **Postcondition:** For each relationship entry where `target` matches a name
  in `concept_name_to_id` (case-insensitive) and `kind` is in
  `{refines, contradicts, prerequisite}`: an edge of that kind exists between
  the source concept and the target concept
  (**INV-KK-EXTRACT-RELATIONSHIPS-VALID**). Unmatched targets or invalid kinds
  are counted but silently skipped. Returns a `RelationshipResult` with
  `edges_created` and `edges_skipped` counts.
- **Side effects:** Zero or more INSERT into edges. No node creation.
- **Scope:** Relationship wiring only. Does not create or modify concepts.

### ALG-KK-EXTRACT-VALIDATE-ITEM

- **Function:** `validate_extraction_item(item) -> dict | None`
- **Location:** `src/ingest/extractor.py`
- **Precondition:** `item` is a value from the parsed LLM JSON array (expected
  to be a dict but may be anything if LLM output is malformed).
- **Postcondition:** If `item` is a dict with all required keys (`name`,
  `description`, `key_properties`, `tradeoffs`, `design_rationale`,
  `subsystem`) and `key_properties` is a non-empty list and
  `design_rationale` is a non-empty string: returns a sanitized copy with
  all string fields stripped and lists validated. Otherwise returns `None`.
- **Side effects:** None (pure function).
- **Scope:** Single-item validation and sanitization.

### ALG-KK-EXTRACT-BUILD-PROMPT

- **Function:** `build_extraction_prompt(evidence_text) -> str`
- **Location:** `src/ingest/extractor.py`
- **Precondition:** `evidence_text` is a string (may be empty).
- **Postcondition:** Returns a user prompt string containing the evidence text
  formatted for LLM consumption. If `evidence_text` is empty, returns a
  metadata-only fallback prompt.
- **Side effects:** None (pure function).
- **Scope:** Prompt construction only.

## Changes to Existing Spec

### EXTRACTION_SYSTEM_PROMPT (IF-KK-EXTRACTION-PROMPT)

Replace the "For each concept, provide:" block:

```
For each concept, provide:
- name: A short descriptive name (2-5 words)
- description: An abstract description of the mechanism (3-5 sentences,
  your own words, covering WHAT it does, HOW it works at a high level,
  and WHERE in the system it operates)
- key_properties: A list of 3-5 defining properties or characteristics
  (e.g., "O(log n) lookup time", "lazy allocation", "hardware-assisted")
- tradeoffs: A list of 1-3 limitations or costs (e.g., "internal
  fragmentation with large pages", "increased context switch overhead").
  Empty list if no significant tradeoffs.
- design_rationale: One sentence explaining WHY this approach was chosen
  over alternatives
- subsystem: The kernel subsystem (e.g., "Virtual Memory", "Scheduler",
  "Filesystem", "IPC", "Networking", "Device Drivers", "Security")
- relationships: A list of connections to OTHER concepts you are
  extracting in this same batch. Each entry has:
  - target: The exact name of the other concept
  - kind: One of "refines", "contradicts", "prerequisite"
  - reason: One sentence explaining the relationship
  If a concept has no relationships, use an empty list.
```

### CONCEPT_SCHEMA (IF-KK-EXTRACTION-PROMPT)

Add to items.properties:
```json
"key_properties": {"type": "array", "items": {"type": "string"}},
"tradeoffs": {"type": "array", "items": {"type": "string"}},
"design_rationale": {"type": "string"},
"relationships": {
  "type": "array",
  "items": {
    "type": "object",
    "properties": {
      "target": {"type": "string"},
      "kind": {"type": "string"},
      "reason": {"type": "string"}
    },
    "required": ["target", "kind", "reason"]
  }
}
```

Add to items.required: `key_properties`, `tradeoffs`, `design_rationale`,
`relationships`.

### REQUIRED_ATTRS["Concept"] (schema.py)

Change from: `("name", "description", "artifact_class")`
Change to:   `("name", "description", "artifact_class", "key_properties",
              "tradeoffs", "design_rationale")`

### ExtractionResult (IF-KK-EXTRACTION-RESULT)

Add field: `relationships_created: int = 0`

### ALG-KK-LLM-EXTRACT (extract_concepts)

Modified orchestration. After the LLM call:

1. For each item in LLM response: call `validate_extraction_item(item)`.
   Skip if None.
2. For each valid item: call `store_rich_concept(conn, item, evidence_id)`.
   Collect concept_ids and build name→id map.
3. Call `parse_classification_labels()` + `assign_subsystems()` (unchanged).
4. Call `wire_relationships(conn, concepts_data, name_to_id_map)`.
5. Return ExtractionResult with all counts.

Steps 1-2 replace the current inline loop (lines 182-194). Steps 3-4 are
additions. The function remains an orchestrator — each step is a separate
algorithm call.

## Data Types

```python
@dataclass
class RelationshipResult:
    edges_created: int
    edges_skipped: int
```

## What Does NOT Change

- `classifier.py` — subsystem classification untouched
- `graph/schema.py` `EDGE_KINDS`, `EDGE_VALID_PAIRS` — all needed kinds exist
- `graph/engine.py` — add_node, add_edge unchanged
- `export/exporter.py` — new attrs flow through automatically
- `mcp_server/server.py` — attrs are JSON, MCP tools return them as-is
- Session gate, idempotency, anti-verbatim rules — all preserved

## Test Plan

| Test | Invariant Covered | What It Checks |
|------|-------------------|----------------|
| `test_validate_item_valid` | (defensive) | Valid item returns sanitized copy |
| `test_validate_item_missing_fields` | (defensive) | Missing required key returns None |
| `test_validate_item_empty_properties` | INV-KK-CONCEPT-HAS-PROPERTIES | Empty key_properties returns None |
| `test_validate_item_empty_rationale` | INV-KK-CONCEPT-HAS-RATIONALE | Empty design_rationale returns None |
| `test_store_rich_concept_creates_node` | INV-KK-CONCEPT-HAS-PROPERTIES, HAS-TRADEOFFS, HAS-RATIONALE | Node attrs contain all new fields |
| `test_store_rich_concept_creates_provenance` | INV-KK-EXTRACT-PROVENANCE | extracted-from edge exists |
| `test_wire_relationships_creates_edges` | INV-KK-EXTRACT-RELATIONSHIPS-VALID | Matched relationships produce edges |
| `test_wire_relationships_skips_unknown_target` | INV-KK-EXTRACT-RELATIONSHIPS-VALID | Unmatched target name counted in skipped |
| `test_wire_relationships_skips_invalid_kind` | INV-KK-EXTRACT-RELATIONSHIPS-VALID | Kind not in allowed set is skipped |
| `test_extract_concepts_rich_end_to_end` | All new + existing | Full extraction with rich mock, verify all fields + edges |
| `test_build_prompt_with_text` | (prompt) | Returns formatted prompt with evidence text |
| `test_build_prompt_empty_text` | (prompt) | Returns metadata-only fallback |
| **E2E updated** | INV-KK-E2E-PIPELINE-SOUND | Rich concepts flow through export + MCP |

## File Inventory

| File | Action |
|------|--------|
| `src/ingest/extractor.py` | **MODIFY** — prompt, schema, new functions, updated orchestration |
| `src/graph/schema.py` | **MODIFY** — REQUIRED_ATTRS["Concept"] |
| `tests/test_ingest_extractor.py` | **MODIFY** — rich mock, new tests |
| `tests/test_ingest_classifier.py` | **MODIFY** — update _make_concept helper for new required attrs |
| `tests/test_e2e_pipeline.py` | **MODIFY** — rich mock, verify attrs in snapshot |

## Implementation Order

1. **Spec first** — create 4 new invariant nodes, 4 new algorithm nodes in
   spec.db.
2. **schema.py** — update REQUIRED_ATTRS.
3. **extractor.py** — implement 4 new functions, update orchestration, update
   prompt and schema constants.
4. **Fix tests** — update all mocks and concept creation helpers for new
   required attrs. Add new tests.
5. **Real data test** — extract from kernel.org docs, review output quality.
6. **Full suite** — pytest must stay at 0 failures.

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| LLM returns shallow key_properties | Prompt explicitly asks for 3-5 with examples. validate_extraction_item rejects items with empty list. |
| LLM omits relationships field | Schema requires it. validate_extraction_item requires it. Falls back to empty list at worst. |
| Relationship target names don't match | Case-insensitive matching. Unmatched targets are skipped and counted, not errors. |
| New required attrs break existing concept creation in tests | Update all test helpers and mocks in one pass before running. |
| Richer prompt causes longer/more expensive LLM responses | max_tokens already 4096. Prompt still says "at most 10 concepts". |
