# Operational Knowledge Extraction — Staged /cb-* Commands

## Context Priming Header (copy into each stage)

> CONTEXT PRIMING: Read docs/plans/kernel-invariant-extraction.md to prime context.
> The plan describes three phases of operational knowledge extraction:
> Phase 1 (KernelInvariant), Phase 2 (FailureMode), Phase 3 (InteractionProtocol).
> Prior feature (rich concept extraction) is complete — see
> docs/plans/rich-concept-extraction.md for history. The current graph has 12
> concepts across 4 subsystems with inter-concept edges (refines, contradicts,
> prerequisite). All 222 tests pass. The spec DAG has 95+ nodes under
> SUB-KK-INGEST, SUB-KK-GRAPH, SUB-KK-EXPORT.

---

## PHASE 1: KernelInvariant Extraction

---

### P1-S1: Specify KernelInvariant invariant nodes

```
/cb-green — Specify KernelInvariant spec invariants (INV-KK-KINV-HAS-PREDICATE,
  INV-KK-KINV-HAS-STRENGTH, INV-KK-KINV-GOVERNED-BY, INV-KK-KINV-PROVENANCE)

    CONTEXT PRIMING: Read docs/plans/kernel-invariant-extraction.md to prime context.
    The plan describes Phase 1: KernelInvariant extraction. Prior feature (rich concept
    extraction) is complete — 222 tests pass. This is Phase 1, Stage 1 of 8.

      - What: Create 4 new invariant spec nodes in spec.db under
        SUB-KK-INGEST:
        1. INV-KK-KINV-HAS-PREDICATE — "Every KernelInvariant node created by
           extraction has a non-empty predicate string in its attrs."
        2. INV-KK-KINV-HAS-STRENGTH — "Every KernelInvariant node created by
           extraction has a strength value in {safety, liveness, performance,
           structural}."
        3. INV-KK-KINV-GOVERNED-BY — "Every KernelInvariant node has exactly one
           governed-by edge to a Concept node."
        4. INV-KK-KINV-PROVENANCE — "Every KernelInvariant node has an
           extracted-from edge to the same Evidence node as its governing Concept."

        For each invariant node:
          - INSERT into nodes(id, kind) VALUES ('<id>', 'invariant')
          - INSERT node_properties: label=invariant, predicate=<semi-formal>,
            predicateNL=<natural language>, predicateAuthority=nl-only,
            riStatus=unchecked, enforced="{}", description=<short>
          - INSERT edge: SUB-KK-INGEST contains <id>
          - INSERT edge: <id> checked-at stage-delivery

      - INVIOLABLE RULE: SPECIFICATION SURFACE IS AUTHORITATIVE. VIOLATIONS WILL CAUSE REVERSION OF YOUR WORK
      - INVIOLABLE RULE: DO NOT EMIT P3_SKIPPED SPECIFICATION SKIPPING IS A DIRECT VIOLATION OF PROTOCOL
      - DO NOT EMIT P3_SKIPPED. I WILL STOP YOU AND MAKE YOU GO BACK.
      - Reference: The authoring guide is now stored in silk's DB. It must be returned as per specification in CS-087 CS-088
      - Spec areas: SUB-KK-INGEST (parent), INV-KK-KINV-HAS-PREDICATE (new),
        INV-KK-KINV-HAS-STRENGTH (new), INV-KK-KINV-GOVERNED-BY (new),
        INV-KK-KINV-PROVENANCE (new).
        Edge wiring: contains from SUB-KK-INGEST, checked-at to stage-delivery.
      - Code path: spec.db (spec mutations only, no source code)
      - Pre-commit hook: spec.db changes only.
      - Test: Run `npm run spec:check` to confirm spec integrity after mutations.
      - Commit: At end of skill, before closing the gate.
      - DO NOT EMIT P3_SKIPPED. I WILL STOP YOU AND MAKE YOU GO BACK.
      - WARNING: Audits are read only do not attempt jailbreak
      - IMPORTANT: The triage should report the specification surface. Use it and only search for more if you lack information.
```

---

### P1-S2: Specify KernelInvariant algorithm and interface nodes

```
/cb-green — Specify KernelInvariant extraction algorithms and interface
  (ALG-KK-EXTRACT-VALIDATE-INVARIANT, ALG-KK-EXTRACT-STORE-INVARIANT,
  IF-KK-KERNEL-INVARIANT)

    CONTEXT PRIMING: Read docs/plans/kernel-invariant-extraction.md to prime context.
    Phase 1, Stage 2 of 8. Stage 1 created 4 invariant spec nodes
    (INV-KK-KINV-HAS-PREDICATE, HAS-STRENGTH, GOVERNED-BY, PROVENANCE).

      - What: Create 2 new algorithm spec nodes + 1 interface in
        spec.db under SUB-KK-INGEST:

        1. ALG-KK-EXTRACT-VALIDATE-INVARIANT — Hoare triple:
           Pre: item is a value from the LLM JSON invariants array
           (expected dict, may be anything).
           Post: Returns sanitized dict if all required keys present
           (predicate, strength, scope, concept_name) and predicate is
           non-empty string and strength is in {safety, liveness, performance,
           structural} and scope is in {per-operation, per-object, system-wide}.
           Returns None otherwise. Pure function.
           Satisfies: (defensive, no invariant — validation gate)

        2. ALG-KK-EXTRACT-STORE-INVARIANT — Hoare triple:
           Pre: conn open, item is validated dict (output of
           validate_invariant_item), evidence_id is existing Evidence node,
           concept_name_to_id is dict[str,str] from current batch.
           Post: If concept_name matches a concept in the batch: new
           KernelInvariant node with predicate, strength, scope,
           artifact_class="abstracted-mechanism". Edges: governed-by to
           matched Concept, extracted-from to evidence_id. Returns
           invariant ID. If concept not found: returns None.
           Satisfies: INV-KK-KINV-HAS-PREDICATE, INV-KK-KINV-HAS-STRENGTH,
           INV-KK-KINV-GOVERNED-BY, INV-KK-KINV-PROVENANCE

        3. IF-KK-KERNEL-INVARIANT — the KernelInvariant node schema
           (predicate: str, strength: str, scope: str, artifact_class: str).
           This is the application-level interface for the new node kind.

        For each algorithm: INSERT node, edges (contains from SUB-KK-INGEST,
        runs-at stage-delivery, satisfies to each enforced invariant).
        For the interface: INSERT node in SUB-KK-GRAPH (it's a graph schema
        element), contains edge from SUB-KK-GRAPH.

      - INVIOLABLE RULE: SPECIFICATION SURFACE IS AUTHORITATIVE. VIOLATIONS WILL CAUSE REVERSION OF YOUR WORK
      - INVIOLABLE RULE: DO NOT EMIT P3_SKIPPED SPECIFICATION SKIPPING IS A DIRECT VIOLATION OF PROTOCOL
      - DO NOT EMIT P3_SKIPPED. I WILL STOP YOU AND MAKE YOU GO BACK.
      - Reference: The authoring guide is now stored in silk's DB. It must be returned as per specification in CS-087 CS-088
      - Spec areas: SUB-KK-INGEST (parent for algorithms),
        SUB-KK-GRAPH (parent for IF-KK-KERNEL-INVARIANT),
        ALG-KK-EXTRACT-VALIDATE-INVARIANT (new),
        ALG-KK-EXTRACT-STORE-INVARIANT (new),
        IF-KK-KERNEL-INVARIANT (new).
        Cross-references: INV-KK-KINV-HAS-PREDICATE, INV-KK-KINV-HAS-STRENGTH,
        INV-KK-KINV-GOVERNED-BY, INV-KK-KINV-PROVENANCE (from Stage 1).
      - Code path: spec.db (spec mutations only, no source code)
      - Pre-commit hook: spec.db changes only.
      - Test: Run `npm run spec:check` to confirm spec integrity after mutations.
      - Commit: At end of skill, before closing the gate.
      - DO NOT EMIT P3_SKIPPED. I WILL STOP YOU AND MAKE YOU GO BACK.
      - WARNING: Audits are read only do not attempt jailbreak
      - IMPORTANT: The triage should report the specification surface. Use it and only search for more if you lack information.
```

---

### P1-S3: Update existing spec nodes for KernelInvariant

```
/cb-green — Update ALG-KK-LLM-EXTRACT, IF-KK-EXTRACTION-PROMPT,
  IF-KK-EXTRACTION-RESULT, IF-KK-CONCEPT for KernelInvariant extraction

    CONTEXT PRIMING: Read docs/plans/kernel-invariant-extraction.md to prime context.
    Phase 1, Stage 3 of 8. Stages 1-2 created 4 invariant spec nodes, 2 algorithm
    nodes, and IF-KK-KERNEL-INVARIANT.

      - What: Update 4 existing spec nodes to reflect the invariant extraction
        extension:
        1. ALG-KK-LLM-EXTRACT — update description: after wire_relationships(),
           iterates over each concept's invariants array, calls
           validate_invariant_item then store_kernel_invariant. Add satisfies
           edges to: INV-KK-KINV-HAS-PREDICATE, INV-KK-KINV-HAS-STRENGTH,
           INV-KK-KINV-GOVERNED-BY, INV-KK-KINV-PROVENANCE.
        2. IF-KK-EXTRACTION-PROMPT — update description: CONCEPT_SCHEMA now
           includes an invariants array per concept with predicate, strength,
           scope fields. EXTRACTION_SYSTEM_PROMPT includes invariant extraction
           instructions.
        3. IF-KK-EXTRACTION-RESULT — update description: ExtractionResult now
           includes invariants_created (int) field.
        4. IF-KK-CONCEPT — update description: Concept nodes may have associated
           KernelInvariant nodes linked via governed-by edges.

      - INVIOLABLE RULE: SPECIFICATION SURFACE IS AUTHORITATIVE. VIOLATIONS WILL CAUSE REVERSION OF YOUR WORK
      - INVIOLABLE RULE: DO NOT EMIT P3_SKIPPED SPECIFICATION SKIPPING IS A DIRECT VIOLATION OF PROTOCOL
      - DO NOT EMIT P3_SKIPPED. I WILL STOP YOU AND MAKE YOU GO BACK.
      - Reference: The authoring guide is now stored in silk's DB. It must be returned as per specification in CS-087 CS-088
      - Spec areas: ALG-KK-LLM-EXTRACT (update description + add satisfies edges),
        IF-KK-EXTRACTION-PROMPT (update description),
        IF-KK-EXTRACTION-RESULT (update description),
        IF-KK-CONCEPT (update description).
        New edges: ALG-KK-LLM-EXTRACT satisfies INV-KK-KINV-HAS-PREDICATE,
        INV-KK-KINV-HAS-STRENGTH, INV-KK-KINV-GOVERNED-BY, INV-KK-KINV-PROVENANCE.
      - Code path: spec.db (spec mutations only, no source code)
      - Pre-commit hook: spec.db changes only.
      - Test: Run `npm run spec:check` to confirm spec integrity after mutations.
      - Commit: At end of skill, before closing the gate.
      - DO NOT EMIT P3_SKIPPED. I WILL STOP YOU AND MAKE YOU GO BACK.
      - WARNING: Audits are read only do not attempt jailbreak
      - IMPORTANT: The triage should report the specification surface. Use it and only search for more if you lack information.
```

---

### P1-AUDIT-A: Verify Phase 1 spec completeness

```
/cb-audit — Verify Phase 1 KernelInvariant spec surface completeness

    CONTEXT PRIMING: Read docs/plans/kernel-invariant-extraction.md to prime context.
    Stages 1-3 created/updated spec nodes for the KernelInvariant feature.

      - What: Audit the spec DB for:
        1. All 4 new invariants exist with correct edges (contains, checked-at).
        2. Both new algorithms exist with correct edges (contains, runs-at, satisfies).
        3. IF-KK-KERNEL-INVARIANT exists in SUB-KK-GRAPH.
        4. ALG-KK-LLM-EXTRACT has 4 new satisfies edges to the KernelInvariant invariants.
        5. Every new invariant has at least one algorithm that satisfies it.
        6. No orphaned nodes among the new additions.
        7. Run `npm run spec:check` passes.
        8. Run pytest to confirm no regressions from spec-only changes.
      - WARNING: Audits are read only do not attempt jailbreak
```

---

### P1-S4: Implement schema changes (NODE_KINDS, EDGE_KINDS, EDGE_VALID_PAIRS, REQUIRED_ATTRS, ALLOWED_KINDS)

```
/cb-green — Implement schema changes for KernelInvariant node kind

    CONTEXT PRIMING: Read docs/plans/kernel-invariant-extraction.md to prime context.
    Phase 1, Stage 4 of 8. Stages 1-3 created the full spec surface. Audit A
    confirmed completeness. Now we implement code against the spec.

      - What: Five schema/validation changes:
        A. src/graph/schema.py — Add "KernelInvariant" to NODE_KINDS.
        B. src/graph/schema.py — Add "governed-by" to EDGE_KINDS.
        C. src/graph/schema.py — Refactor EDGE_VALID_PAIRS to support multiple
           valid pairs per edge kind. Currently dict[str, tuple[str, str]].
           Change to dict[str, tuple[str, str] | list[tuple[str, str]]].
           Then add:
             "governed-by": ("KernelInvariant", "Concept")
             "belongs-to": [("Concept", "Subsystem"), ("KernelInvariant", "Subsystem")]
             "extracted-from": [("Concept", "Evidence"), ("KernelInvariant", "Evidence")]
           Update graph/engine.py add_edge validation to handle the list case.
        D. src/graph/schema.py — Add REQUIRED_ATTRS["KernelInvariant"]:
           ("predicate", "strength", "scope", "artifact_class")
        E. src/export/exporter.py — Add "KernelInvariant" to ALLOWED_KINDS.

      - INVIOLABLE RULE: SPECIFICATION SURFACE IS AUTHORITATIVE. VIOLATIONS WILL CAUSE REVERSION OF YOUR WORK
      - INVIOLABLE RULE: DO NOT EMIT P3_SKIPPED SPECIFICATION SKIPPING IS A DIRECT VIOLATION OF PROTOCOL
      - DO NOT EMIT P3_SKIPPED. I WILL STOP YOU AND MAKE YOU GO BACK.
      - Reference: The authoring guide is now stored in silk's DB. It must be returned as per specification in CS-087 CS-088
      - Spec areas: IF-KK-KERNEL-INVARIANT (schema representation),
        INV-KK-EDGE-KIND-CONSTRAINTS (existing — EDGE_VALID_PAIRS refactor must
        preserve all existing validation), INV-KK-NODE-ATTRS-SCHEMA (existing —
        REQUIRED_ATTRS must pass), INV-KK-SNAPSHOT-ALLOWED-KINDS (existing —
        ALLOWED_KINDS update).
      - Code path: src/graph/schema.py (MODIFY — NODE_KINDS, EDGE_KINDS,
        EDGE_VALID_PAIRS, REQUIRED_ATTRS), src/graph/engine.py (MODIFY —
        add_edge validation for list pairs), src/export/exporter.py (MODIFY —
        ALLOWED_KINDS), tests/test_graph_schema.py (MODIFY — add tests for new
        kind), tests/test_graph_engine.py (MODIFY — add edge validation tests
        for governed-by, multi-pair belongs-to)
      - Pre-commit hook: schema.py + engine.py + exporter.py + test files.
      - Test: Run pytest tests/ — full suite must still pass (222+ tests).
        Add new tests:
        - test_kernel_invariant_node_creation: add_node with KernelInvariant kind
        - test_governed_by_edge_valid: KernelInvariant -> Concept accepted
        - test_governed_by_edge_invalid_source: Concept -> Concept rejected
        - test_belongs_to_kernel_invariant: KernelInvariant -> Subsystem accepted
        - test_extracted_from_kernel_invariant: KernelInvariant -> Evidence accepted
        - test_kernel_invariant_in_snapshot: exported snapshot includes KernelInvariant
      - Commit: At end of skill, before closing the gate.
      - DO NOT EMIT P3_SKIPPED. I WILL STOP YOU AND MAKE YOU GO BACK.
      - WARNING: Audits are read only do not attempt jailbreak
      - IMPORTANT: The triage should report the specification surface. Use it and only search for more if you lack information.
```

---

### P1-S5: Implement validate_invariant_item() and store_kernel_invariant()

```
/cb-green — Implement validate_invariant_item() and store_kernel_invariant()
  (ALG-KK-EXTRACT-VALIDATE-INVARIANT, ALG-KK-EXTRACT-STORE-INVARIANT)

    CONTEXT PRIMING: Read docs/plans/kernel-invariant-extraction.md to prime context.
    Phase 1, Stage 5 of 8. Stage 4 added KernelInvariant to schema, governed-by
    edge, EDGE_VALID_PAIRS refactor, REQUIRED_ATTRS, ALLOWED_KINDS. All existing
    tests pass.

      - What: Add two functions to src/ingest/extractor.py:

        A. validate_invariant_item(item) -> dict | None:
           - VALID_STRENGTHS = {"safety", "liveness", "performance", "structural"}
           - VALID_SCOPES = {"per-operation", "per-object", "system-wide"}
           - If item is not a dict: return None
           - Required keys: predicate, strength, scope, concept_name
           - If any key missing: return None
           - predicate must be a non-empty string after strip
           - strength must be in VALID_STRENGTHS
           - scope must be in VALID_SCOPES
           - concept_name must be a non-empty string after strip
           - Return sanitized copy: all strings stripped

        B. store_kernel_invariant(conn, item, evidence_id, concept_name_to_id) -> str | None:
           - concept_id = concept_name_to_id.get(item["concept_name"].lower())
           - If no concept_id: return None
           - Generate kinv_id = f"kinv-{uuid.uuid4().hex[:12]}"
           - Call add_node(conn, kinv_id, "KernelInvariant", {
                 "predicate": item["predicate"],
                 "strength": item["strength"],
                 "scope": item["scope"],
                 "artifact_class": "abstracted-mechanism",
             })
           - Call add_edge(conn, "governed-by", kinv_id, concept_id)
           - Call add_edge(conn, "extracted-from", kinv_id, evidence_id)
           - Return kinv_id

      - INVIOLABLE RULE: SPECIFICATION SURFACE IS AUTHORITATIVE. VIOLATIONS WILL CAUSE REVERSION OF YOUR WORK
      - INVIOLABLE RULE: DO NOT EMIT P3_SKIPPED SPECIFICATION SKIPPING IS A DIRECT VIOLATION OF PROTOCOL
      - DO NOT EMIT P3_SKIPPED. I WILL STOP YOU AND MAKE YOU GO BACK.
      - Reference: The authoring guide is now stored in silk's DB. It must be returned as per specification in CS-087 CS-088
      - Spec areas: ALG-KK-EXTRACT-VALIDATE-INVARIANT, ALG-KK-EXTRACT-STORE-INVARIANT,
        INV-KK-KINV-HAS-PREDICATE, INV-KK-KINV-HAS-STRENGTH,
        INV-KK-KINV-GOVERNED-BY, INV-KK-KINV-PROVENANCE.
      - Code path: src/ingest/extractor.py (MODIFY — add 2 functions),
        tests/test_ingest_extractor.py (MODIFY — add tests)
      - Pre-commit hook: extractor.py + test file.
      - Test: Add to tests/test_ingest_extractor.py:
        - test_validate_invariant_valid: complete item returns sanitized dict
        - test_validate_invariant_missing_predicate: returns None
        - test_validate_invariant_empty_predicate: whitespace-only returns None
        - test_validate_invariant_invalid_strength: "critical" returns None
        - test_validate_invariant_invalid_scope: "global" returns None
        - test_validate_invariant_strips_strings: whitespace trimmed
        - test_store_invariant_creates_node: node exists with all 4 attrs
        - test_store_invariant_governed_by_edge: governed-by edge to concept
        - test_store_invariant_provenance_edge: extracted-from edge to evidence
        - test_store_invariant_unknown_concept_returns_none: unmatched name
        Run: pytest tests/test_ingest_extractor.py -k "invariant"
      - Commit: At end of skill, before closing the gate.
      - DO NOT EMIT P3_SKIPPED. I WILL STOP YOU AND MAKE YOU GO BACK.
      - WARNING: Audits are read only do not attempt jailbreak
      - IMPORTANT: The triage should report the specification surface. Use it and only search for more if you lack information.
```

---

### P1-S6: Rewire orchestrator, update prompt and schema constants

```
/cb-green — Rewire extract_concepts() for KernelInvariant extraction, update
  EXTRACTION_SYSTEM_PROMPT and CONCEPT_SCHEMA (ALG-KK-LLM-EXTRACT)

    CONTEXT PRIMING: Read docs/plans/kernel-invariant-extraction.md to prime context.
    Phase 1, Stage 6 of 8. Stage 5 implemented validate_invariant_item() and
    store_kernel_invariant(). All new unit tests pass.

      - What: Three changes in src/ingest/extractor.py:
        A. EXTRACTION_SYSTEM_PROMPT — Add after the relationships field:
           "- invariants: A list of rules or properties that MUST HOLD for this
           concept to function correctly. Each entry has:
             - predicate: A clear statement of what must be true
             - strength: One of 'safety', 'liveness', 'performance', 'structural'
             - scope: One of 'per-operation', 'per-object', 'system-wide'
           Extract 1-3 invariants per concept. If none, use empty list."
           Keep all existing fields and anti-verbatim rules intact.

        B. CONCEPT_SCHEMA — Add invariants to items.properties:
           "invariants": {"type": "array", "items": {"type": "object",
           "properties": {"predicate": {"type": "string"},
           "strength": {"type": "string"}, "scope": {"type": "string"}},
           "required": ["predicate", "strength", "scope"]}}
           Add "invariants" to items.required.

        C. extract_concepts() — After wire_relationships() call, add:
           invariants_created = 0
           for item in concepts_data[:10]:
               if not isinstance(item, dict): continue
               for inv in item.get("invariants", []):
                   inv["concept_name"] = item.get("name", "")
                   validated = validate_invariant_item(inv)
                   if validated is None: continue
                   inv_id = store_kernel_invariant(conn, validated, evidence_id, name_to_id)
                   if inv_id: invariants_created += 1
           Add invariants_created to ExtractionResult return.

        D. ExtractionResult — Add field: invariants_created: int = 0

      - INVIOLABLE RULE: SPECIFICATION SURFACE IS AUTHORITATIVE. VIOLATIONS WILL CAUSE REVERSION OF YOUR WORK
      - INVIOLABLE RULE: DO NOT EMIT P3_SKIPPED SPECIFICATION SKIPPING IS A DIRECT VIOLATION OF PROTOCOL
      - DO NOT EMIT P3_SKIPPED. I WILL STOP YOU AND MAKE YOU GO BACK.
      - Reference: The authoring guide is now stored in silk's DB. It must be returned as per specification in CS-087 CS-088
      - Spec areas: ALG-KK-LLM-EXTRACT (orchestration extension),
        IF-KK-EXTRACTION-PROMPT (prompt + schema constants),
        IF-KK-EXTRACTION-RESULT (invariants_created field).
        Must preserve: all existing INV-KK-EXTRACT-* and INV-KK-CONCEPT-HAS-*
        invariants.
      - Code path: src/ingest/extractor.py (MODIFY — prompt, schema, orchestrator,
        dataclass)
      - Pre-commit hook: extractor.py only. Do NOT commit tests yet (Stage 7).
      - Test: Do NOT run full test suite — existing mocks lack invariants field.
        Verify only: python -c "from ingest.extractor import CONCEPT_SCHEMA;
        assert 'invariants' in CONCEPT_SCHEMA['items']['properties']"
      - Commit: At end of skill, before closing the gate.
      - DO NOT EMIT P3_SKIPPED. I WILL STOP YOU AND MAKE YOU GO BACK.
      - WARNING: Audits are read only do not attempt jailbreak
      - IMPORTANT: The triage should report the specification surface. Use it and only search for more if you lack information.
```

---

### P1-S7: Update all mocks and tests for KernelInvariant

```
/cb-green — Update all mocks and test helpers for KernelInvariant extraction
  (INV-KK-E2E-PIPELINE-SOUND)

    CONTEXT PRIMING: Read docs/plans/kernel-invariant-extraction.md to prime context.
    Phase 1, Stage 7 of 8. Stage 6 rewired extract_concepts() and updated
    prompt/schema constants. CONCEPT_SCHEMA now requires invariants field.
    Existing mocks lack invariants and will fail until updated.

      - What: Update every test file that mocks LLM responses:

        A. tests/test_ingest_extractor.py — Update MockLLMClient.concepts default:
           Each concept dict gets an "invariants" field (list of {predicate,
           strength, scope}). Add new integration tests:
           - test_extract_concepts_invariants_end_to_end: full extraction, verify
             KernelInvariant nodes exist with correct attrs
           - test_extract_concepts_invariant_governed_by: verify governed-by edge
             from KernelInvariant to Concept
           - test_extract_concepts_invariants_created_count: verify
             result.invariants_created matches actual nodes

        B. tests/test_e2e_pipeline.py — Update MockLLMClient:
           Each concept gets invariants field. Add assertions:
           - After extraction, verify KernelInvariant nodes exist
           - After export, verify snapshot contains KernelInvariant nodes
           - Verify governed-by edges survive export

        C. tests/conftest.py — If fixtures create Concept nodes that should
           have associated KernelInvariants, add them. Otherwise no change
           (KernelInvariant is additive).

        D. All other test files that use MockLLMClient or create Concept nodes
           via mock extraction — add invariants field to mock responses.

        Run: pytest tests/ — ALL tests must pass. Target: 240+ tests, 0 failures.

      - INVIOLABLE RULE: SPECIFICATION SURFACE IS AUTHORITATIVE. VIOLATIONS WILL CAUSE REVERSION OF YOUR WORK
      - INVIOLABLE RULE: DO NOT EMIT P3_SKIPPED SPECIFICATION SKIPPING IS A DIRECT VIOLATION OF PROTOCOL
      - DO NOT EMIT P3_SKIPPED. I WILL STOP YOU AND MAKE YOU GO BACK.
      - Reference: The authoring guide is now stored in silk's DB. It must be returned as per specification in CS-087 CS-088
      - Spec areas: INV-KK-E2E-PIPELINE-SOUND, INV-KK-KINV-HAS-PREDICATE,
        INV-KK-KINV-HAS-STRENGTH, INV-KK-KINV-GOVERNED-BY, INV-KK-KINV-PROVENANCE,
        INV-KK-SNAPSHOT-ALLOWED-KINDS.
      - Code path: tests/test_ingest_extractor.py (MODIFY),
        tests/test_e2e_pipeline.py (MODIFY), tests/conftest.py (MODIFY if needed),
        any other test file with MockLLMClient
      - Pre-commit hook: all test files touched.
      - Test: Run pytest tests/ — full suite must pass with 0 failures.
      - Commit: At end of skill, before closing the gate.
      - DO NOT EMIT P3_SKIPPED. I WILL STOP YOU AND MAKE YOU GO BACK.
      - WARNING: Audits are read only do not attempt jailbreak
      - IMPORTANT: The triage should report the specification surface. Use it and only search for more if you lack information.
```

---

### P1-AUDIT-B: Final Phase 1 audit

```
/cb-audit — Final audit: Phase 1 KernelInvariant extraction feature complete

    CONTEXT PRIMING: Read docs/plans/kernel-invariant-extraction.md to prime context.
    All 7 Phase 1 implementation stages are complete. This is the final audit.

      - What: Comprehensive audit covering:
        1. SPEC: 4 new invariants, 2 new algorithms, IF-KK-KERNEL-INVARIANT,
           4 updated nodes — all with correct edges and satisfies wiring.
        2. CODE: validate_invariant_item, store_kernel_invariant exist.
           extract_concepts calls them. EXTRACTION_SYSTEM_PROMPT has invariant
           fields. CONCEPT_SCHEMA has invariants property. REQUIRED_ATTRS has
           KernelInvariant. ALLOWED_KINDS includes KernelInvariant.
           EDGE_VALID_PAIRS supports governed-by and multi-pair belongs-to.
        3. TESTS: All pass. Each new invariant has test coverage.
           KernelInvariant nodes appear in exported snapshot.
        4. INVARIANT COVERAGE:
           - INV-KK-KINV-HAS-PREDICATE: tested by store_invariant + E2E
           - INV-KK-KINV-HAS-STRENGTH: tested by validate + store
           - INV-KK-KINV-GOVERNED-BY: tested by store_invariant + E2E
           - INV-KK-KINV-PROVENANCE: tested by store_invariant
        5. REGRESSIONS: All prior invariants still hold. pytest 0 failures.
        6. CONTAMINATION: KernelInvariant is Class B. Export + MCP still clean.
        7. Run pytest + spec:check.
      - WARNING: Audits are read only do not attempt jailbreak
```

---

## PHASE 2: FailureMode Extraction

---

### P2-S1: Specify FailureMode invariant nodes

```
/cb-green — Specify FailureMode spec invariants (INV-KK-FM-HAS-SYMPTOM,
  INV-KK-FM-HAS-BLAST-RADIUS, INV-KK-FM-HAS-RECOVERABILITY,
  INV-KK-FM-TRIGGERED-BY)

    CONTEXT PRIMING: Read docs/plans/kernel-invariant-extraction.md to prime context.
    Phase 2 (FailureMode) starts here. Phase 1 (KernelInvariant) is complete and
    audited. The graph now has KernelInvariant nodes with governed-by edges to
    Concepts. FailureMode nodes link to KernelInvariants via triggered-by edges.
    This is Phase 2, Stage 1 of 5.

      - What: Create 4 new invariant spec nodes in spec.db under
        SUB-KK-INGEST:
        1. INV-KK-FM-HAS-SYMPTOM — "Every FailureMode node has a non-empty
           symptom string describing the observable behavior on invariant violation."
        2. INV-KK-FM-HAS-BLAST-RADIUS — "Every FailureMode node has a
           blast_radius value in {local, subsystem, kernel-wide}."
        3. INV-KK-FM-HAS-RECOVERABILITY — "Every FailureMode node has a
           recoverability value in {self-healing, requires-restart, data-loss}."
        4. INV-KK-FM-TRIGGERED-BY — "Every FailureMode node has exactly one
           triggered-by edge to a KernelInvariant node."

        For each: INSERT node + properties + contains from SUB-KK-INGEST +
        checked-at to stage-delivery.

      - INVIOLABLE RULE: SPECIFICATION SURFACE IS AUTHORITATIVE. VIOLATIONS WILL CAUSE REVERSION OF YOUR WORK
      - INVIOLABLE RULE: DO NOT EMIT P3_SKIPPED SPECIFICATION SKIPPING IS A DIRECT VIOLATION OF PROTOCOL
      - DO NOT EMIT P3_SKIPPED. I WILL STOP YOU AND MAKE YOU GO BACK.
      - Reference: The authoring guide is now stored in silk's DB. It must be returned as per specification in CS-087 CS-088
      - Spec areas: SUB-KK-INGEST (parent), INV-KK-FM-HAS-SYMPTOM (new),
        INV-KK-FM-HAS-BLAST-RADIUS (new), INV-KK-FM-HAS-RECOVERABILITY (new),
        INV-KK-FM-TRIGGERED-BY (new).
      - Code path: spec.db (spec mutations only)
      - Pre-commit hook: spec.db changes only.
      - Test: Run `npm run spec:check` to confirm spec integrity.
      - Commit: At end of skill, before closing the gate.
      - DO NOT EMIT P3_SKIPPED. I WILL STOP YOU AND MAKE YOU GO BACK.
      - WARNING: Audits are read only do not attempt jailbreak
      - IMPORTANT: The triage should report the specification surface. Use it and only search for more if you lack information.
```

---

### P2-S2: Specify FailureMode algorithms, interface, and update existing nodes

```
/cb-green — Specify FailureMode algorithms, interface, update orchestrator spec
  (ALG-KK-EXTRACT-VALIDATE-FAILURE-MODE, ALG-KK-EXTRACT-STORE-FAILURE-MODE,
  IF-KK-FAILURE-MODE)

    CONTEXT PRIMING: Read docs/plans/kernel-invariant-extraction.md to prime context.
    Phase 2, Stage 2 of 5. Stage 1 created 4 FailureMode invariant spec nodes.

      - What: Create 2 algorithm nodes + 1 interface, update 3 existing nodes:

        NEW NODES:
        1. ALG-KK-EXTRACT-VALIDATE-FAILURE-MODE — Pure validation function.
           Satisfies: (defensive)
        2. ALG-KK-EXTRACT-STORE-FAILURE-MODE — Creates FailureMode node with
           triggered-by edge to KernelInvariant + extracted-from to Evidence.
           Satisfies: INV-KK-FM-HAS-SYMPTOM, HAS-BLAST-RADIUS, HAS-RECOVERABILITY,
           TRIGGERED-BY.
        3. IF-KK-FAILURE-MODE — FailureMode node schema in SUB-KK-GRAPH.

        UPDATED NODES:
        4. ALG-KK-LLM-EXTRACT — add satisfies edges to INV-KK-FM-* invariants.
           Update description: after invariant storage, iterates failure_modes
           nested inside each invariant.
        5. IF-KK-EXTRACTION-PROMPT — update description: invariants now include
           nested failure_modes array.
        6. IF-KK-EXTRACTION-RESULT — update description: add failure_modes_created.

      - INVIOLABLE RULE: SPECIFICATION SURFACE IS AUTHORITATIVE. VIOLATIONS WILL CAUSE REVERSION OF YOUR WORK
      - INVIOLABLE RULE: DO NOT EMIT P3_SKIPPED SPECIFICATION SKIPPING IS A DIRECT VIOLATION OF PROTOCOL
      - DO NOT EMIT P3_SKIPPED. I WILL STOP YOU AND MAKE YOU GO BACK.
      - Reference: The authoring guide is now stored in silk's DB. It must be returned as per specification in CS-087 CS-088
      - Spec areas: SUB-KK-INGEST (algorithms), SUB-KK-GRAPH (interface),
        ALG-KK-EXTRACT-VALIDATE-FAILURE-MODE (new), ALG-KK-EXTRACT-STORE-FAILURE-MODE (new),
        IF-KK-FAILURE-MODE (new), ALG-KK-LLM-EXTRACT (update), IF-KK-EXTRACTION-PROMPT
        (update), IF-KK-EXTRACTION-RESULT (update).
      - Code path: spec.db (spec mutations only)
      - Pre-commit hook: spec.db changes only.
      - Test: Run `npm run spec:check`.
      - Commit: At end of skill, before closing the gate.
      - DO NOT EMIT P3_SKIPPED. I WILL STOP YOU AND MAKE YOU GO BACK.
      - WARNING: Audits are read only do not attempt jailbreak
      - IMPORTANT: The triage should report the specification surface. Use it and only search for more if you lack information.
```

---

### P2-S3: Implement FailureMode schema + validate + store + orchestrator

```
/cb-green — Implement FailureMode schema, validate, store, and orchestrator wiring

    CONTEXT PRIMING: Read docs/plans/kernel-invariant-extraction.md to prime context.
    Phase 2, Stage 3 of 5. Stages 1-2 created the full FailureMode spec surface.

      - What: Full implementation in one stage (FailureMode is structurally
        similar to KernelInvariant — same pattern, smaller scope):

        A. src/graph/schema.py — Add "FailureMode" to NODE_KINDS. Add
           "triggered-by" to EDGE_KINDS. Add to EDGE_VALID_PAIRS:
           "triggered-by": ("FailureMode", "KernelInvariant").
           Extend extracted-from to support FailureMode -> Evidence.
           Add REQUIRED_ATTRS["FailureMode"]: ("symptom", "blast_radius",
           "recoverability", "artifact_class").

        B. src/export/exporter.py — Add "FailureMode" to ALLOWED_KINDS.

        C. src/ingest/extractor.py — Add:
           VALID_BLAST_RADII = {"local", "subsystem", "kernel-wide"}
           VALID_RECOVERABILITIES = {"self-healing", "requires-restart", "data-loss"}
           validate_failure_mode_item(item) -> dict | None
           store_failure_mode(conn, item, evidence_id, kinv_id) -> str

        D. src/ingest/extractor.py — Update store_kernel_invariant to return
           the kinv_id, then in extract_concepts() after storing each invariant:
           for fm in inv.get("failure_modes", []):
               validated_fm = validate_failure_mode_item(fm)
               if validated_fm:
                   store_failure_mode(conn, validated_fm, evidence_id, inv_id)
                   failure_modes_created += 1

        E. src/ingest/extractor.py — Update EXTRACTION_SYSTEM_PROMPT invariant
           section to include failure_modes sub-array. Update CONCEPT_SCHEMA.
           Add failure_modes_created to ExtractionResult.

      - INVIOLABLE RULE: SPECIFICATION SURFACE IS AUTHORITATIVE. VIOLATIONS WILL CAUSE REVERSION OF YOUR WORK
      - INVIOLABLE RULE: DO NOT EMIT P3_SKIPPED SPECIFICATION SKIPPING IS A DIRECT VIOLATION OF PROTOCOL
      - DO NOT EMIT P3_SKIPPED. I WILL STOP YOU AND MAKE YOU GO BACK.
      - Reference: The authoring guide is now stored in silk's DB. It must be returned as per specification in CS-087 CS-088
      - Spec areas: ALG-KK-EXTRACT-VALIDATE-FAILURE-MODE,
        ALG-KK-EXTRACT-STORE-FAILURE-MODE, IF-KK-FAILURE-MODE,
        INV-KK-FM-HAS-SYMPTOM, INV-KK-FM-HAS-BLAST-RADIUS,
        INV-KK-FM-HAS-RECOVERABILITY, INV-KK-FM-TRIGGERED-BY.
      - Code path: src/graph/schema.py, src/graph/engine.py (if multi-pair update
        needed), src/export/exporter.py, src/ingest/extractor.py
      - Pre-commit hook: all source files touched. Do NOT commit tests yet (Stage 4).
      - Test: python -c "from graph.schema import NODE_KINDS; assert 'FailureMode' in NODE_KINDS"
      - Commit: At end of skill, before closing the gate.
      - DO NOT EMIT P3_SKIPPED. I WILL STOP YOU AND MAKE YOU GO BACK.
      - WARNING: Audits are read only do not attempt jailbreak
      - IMPORTANT: The triage should report the specification surface. Use it and only search for more if you lack information.
```

---

### P2-S4: Update mocks and tests for FailureMode

```
/cb-green — Update all mocks and tests for FailureMode extraction

    CONTEXT PRIMING: Read docs/plans/kernel-invariant-extraction.md to prime context.
    Phase 2, Stage 4 of 5. Stage 3 implemented all FailureMode code.

      - What: Update MockLLMClient in all test files. Each concept's invariants
        array now includes a nested failure_modes array. Add tests:
        - test_validate_failure_mode_valid
        - test_validate_failure_mode_invalid_blast_radius
        - test_validate_failure_mode_invalid_recoverability
        - test_store_failure_mode_creates_node
        - test_store_failure_mode_triggered_by_edge
        - test_extract_concepts_failure_modes_end_to_end
        - test_failure_modes_in_snapshot
        Run: pytest tests/ — full suite, 0 failures.

      - INVIOLABLE RULE: SPECIFICATION SURFACE IS AUTHORITATIVE. VIOLATIONS WILL CAUSE REVERSION OF YOUR WORK
      - INVIOLABLE RULE: DO NOT EMIT P3_SKIPPED SPECIFICATION SKIPPING IS A DIRECT VIOLATION OF PROTOCOL
      - DO NOT EMIT P3_SKIPPED. I WILL STOP YOU AND MAKE YOU GO BACK.
      - Reference: The authoring guide is now stored in silk's DB. It must be returned as per specification in CS-087 CS-088
      - Spec areas: INV-KK-E2E-PIPELINE-SOUND, INV-KK-FM-* (all 4),
        INV-KK-SNAPSHOT-ALLOWED-KINDS.
      - Code path: tests/test_ingest_extractor.py, tests/test_e2e_pipeline.py,
        any file with MockLLMClient
      - Pre-commit hook: all test files.
      - Test: pytest tests/ — 0 failures.
      - Commit: At end of skill, before closing the gate.
      - DO NOT EMIT P3_SKIPPED. I WILL STOP YOU AND MAKE YOU GO BACK.
      - WARNING: Audits are read only do not attempt jailbreak
      - IMPORTANT: The triage should report the specification surface. Use it and only search for more if you lack information.
```

---

### P2-AUDIT: Final Phase 2 audit

```
/cb-audit — Final audit: Phase 2 FailureMode extraction complete

    CONTEXT PRIMING: Read docs/plans/kernel-invariant-extraction.md to prime context.
    Phase 2 complete. FailureMode nodes with triggered-by edges to KernelInvariant.

      - What: Verify spec-code-test alignment for FailureMode:
        1. 4 new spec invariants, 2 algorithms, IF-KK-FAILURE-MODE — correct edges.
        2. FailureMode in NODE_KINDS, triggered-by in EDGE_KINDS, ALLOWED_KINDS.
        3. validate + store functions exist and are called by orchestrator.
        4. All tests pass. FailureMode in snapshot.
        5. Run pytest + spec:check.
      - WARNING: Audits are read only do not attempt jailbreak
```

---

## PHASE 3: InteractionProtocol Extraction

---

### P3-S1: Specify InteractionProtocol invariant nodes

```
/cb-green — Specify InteractionProtocol spec invariants
  (INV-KK-IP-HAS-RULE, INV-KK-IP-HAS-ORDERING, INV-KK-IP-CONSTRAINS-PAIR)

    CONTEXT PRIMING: Read docs/plans/kernel-invariant-extraction.md to prime context.
    Phase 3 (InteractionProtocol) starts here. Phases 1-2 (KernelInvariant +
    FailureMode) are complete and audited. InteractionProtocol nodes capture
    cross-concept composition rules with constrains-composition edges to exactly
    2 Concept nodes. This is Phase 3, Stage 1 of 5.

      - What: Create 3 new invariant spec nodes in spec.db under
        SUB-KK-INGEST:
        1. INV-KK-IP-HAS-RULE — "Every InteractionProtocol node has a non-empty
           rule string describing the coordination constraint."
        2. INV-KK-IP-HAS-ORDERING — "Every InteractionProtocol node has an
           ordering value in {before, after, never-during, must-hold-while}."
        3. INV-KK-IP-CONSTRAINS-PAIR — "Every InteractionProtocol node has
           exactly 2 constrains-composition edges, each targeting a distinct
           Concept node."

        For each: INSERT node + properties + contains from SUB-KK-INGEST +
        checked-at to stage-delivery.

      - INVIOLABLE RULE: SPECIFICATION SURFACE IS AUTHORITATIVE. VIOLATIONS WILL CAUSE REVERSION OF YOUR WORK
      - INVIOLABLE RULE: DO NOT EMIT P3_SKIPPED SPECIFICATION SKIPPING IS A DIRECT VIOLATION OF PROTOCOL
      - DO NOT EMIT P3_SKIPPED. I WILL STOP YOU AND MAKE YOU GO BACK.
      - Reference: The authoring guide is now stored in silk's DB. It must be returned as per specification in CS-087 CS-088
      - Spec areas: SUB-KK-INGEST (parent), INV-KK-IP-HAS-RULE (new),
        INV-KK-IP-HAS-ORDERING (new), INV-KK-IP-CONSTRAINS-PAIR (new).
      - Code path: spec.db (spec mutations only)
      - Pre-commit hook: spec.db changes only.
      - Test: Run `npm run spec:check`.
      - Commit: At end of skill, before closing the gate.
      - DO NOT EMIT P3_SKIPPED. I WILL STOP YOU AND MAKE YOU GO BACK.
      - WARNING: Audits are read only do not attempt jailbreak
      - IMPORTANT: The triage should report the specification surface. Use it and only search for more if you lack information.
```

---

### P3-S2: Specify InteractionProtocol algorithms, interface, and update existing nodes

```
/cb-green — Specify InteractionProtocol algorithms, interface, update orchestrator
  (ALG-KK-EXTRACT-VALIDATE-PROTOCOL, ALG-KK-EXTRACT-STORE-PROTOCOL,
  ALG-KK-EXTRACT-BUILD-PROTOCOL-PROMPT, IF-KK-INTERACTION-PROTOCOL)

    CONTEXT PRIMING: Read docs/plans/kernel-invariant-extraction.md to prime context.
    Phase 3, Stage 2 of 5. Stage 1 created 3 InteractionProtocol invariant spec nodes.
    InteractionProtocols require a second-pass extraction (or top-level array) because
    they describe concept PAIRS, not individual concepts.

      - What: Create 3 algorithm nodes + 1 interface, update 3 existing nodes:

        NEW NODES:
        1. ALG-KK-EXTRACT-VALIDATE-PROTOCOL — Pure validation. Checks rule,
           ordering, concept_a, concept_b fields.
        2. ALG-KK-EXTRACT-STORE-PROTOCOL — Creates InteractionProtocol with
           2 constrains-composition edges + extracted-from.
           Satisfies: INV-KK-IP-HAS-RULE, HAS-ORDERING, CONSTRAINS-PAIR.
        3. ALG-KK-EXTRACT-BUILD-PROTOCOL-PROMPT — Builds prompt listing
           extracted concept names for protocol discovery. Pure function.
        4. IF-KK-INTERACTION-PROTOCOL — InteractionProtocol schema in SUB-KK-GRAPH.

        UPDATED NODES:
        5. ALG-KK-LLM-EXTRACT — add satisfies edges to INV-KK-IP-* invariants.
           Update description: after invariant+FM extraction, calls
           build_protocol_extraction_prompt then extracts protocols.
        6. IF-KK-EXTRACTION-RESULT — add protocols_created field.

      - INVIOLABLE RULE: SPECIFICATION SURFACE IS AUTHORITATIVE. VIOLATIONS WILL CAUSE REVERSION OF YOUR WORK
      - INVIOLABLE RULE: DO NOT EMIT P3_SKIPPED SPECIFICATION SKIPPING IS A DIRECT VIOLATION OF PROTOCOL
      - DO NOT EMIT P3_SKIPPED. I WILL STOP YOU AND MAKE YOU GO BACK.
      - Reference: The authoring guide is now stored in silk's DB. It must be returned as per specification in CS-087 CS-088
      - Spec areas: SUB-KK-INGEST (algorithms), SUB-KK-GRAPH (interface),
        ALG-KK-EXTRACT-VALIDATE-PROTOCOL (new), ALG-KK-EXTRACT-STORE-PROTOCOL (new),
        ALG-KK-EXTRACT-BUILD-PROTOCOL-PROMPT (new), IF-KK-INTERACTION-PROTOCOL (new),
        ALG-KK-LLM-EXTRACT (update), IF-KK-EXTRACTION-RESULT (update).
      - Code path: spec.db (spec mutations only)
      - Pre-commit hook: spec.db changes only.
      - Test: Run `npm run spec:check`.
      - Commit: At end of skill, before closing the gate.
      - DO NOT EMIT P3_SKIPPED. I WILL STOP YOU AND MAKE YOU GO BACK.
      - WARNING: Audits are read only do not attempt jailbreak
      - IMPORTANT: The triage should report the specification surface. Use it and only search for more if you lack information.
```

---

### P3-S3: Implement InteractionProtocol schema + validate + store + orchestrator

```
/cb-green — Implement InteractionProtocol schema, validate, store, prompt,
  and orchestrator wiring

    CONTEXT PRIMING: Read docs/plans/kernel-invariant-extraction.md to prime context.
    Phase 3, Stage 3 of 5. Stages 1-2 created the full InteractionProtocol spec.
    InteractionProtocol is the most complex new node: it requires 2 constrains-composition
    edges to distinct Concepts, and extraction uses a top-level "interaction_protocols"
    array in the LLM response (protocols describe pairs, not individual concepts).

      - What: Full implementation:

        A. src/graph/schema.py — Add "InteractionProtocol" to NODE_KINDS.
           Add "constrains-composition" to EDGE_KINDS. Add to EDGE_VALID_PAIRS:
           "constrains-composition": ("InteractionProtocol", "Concept").
           Extend extracted-from for InteractionProtocol -> Evidence.
           Add REQUIRED_ATTRS["InteractionProtocol"]: ("rule", "ordering",
           "violation_mode", "artifact_class").

        B. src/export/exporter.py — Add "InteractionProtocol" to ALLOWED_KINDS.

        C. src/ingest/extractor.py — Add:
           VALID_ORDERINGS = {"before", "after", "never-during", "must-hold-while"}
           validate_protocol_item(item, concept_name_to_id) -> dict | None
           store_interaction_protocol(conn, item, evidence_id, concept_name_to_id) -> str | None
           build_protocol_extraction_prompt(concept_summaries) -> str

        D. src/ingest/extractor.py — Update EXTRACTION_SYSTEM_PROMPT: add
           instruction for top-level "interaction_protocols" array. Update
           CONCEPT_SCHEMA (or add PROTOCOL_SCHEMA). Update extract_concepts():
           after concepts+invariants+FMs, parse interaction_protocols from
           response, validate and store each.

        E. ExtractionResult — Add: protocols_created: int = 0

      - INVIOLABLE RULE: SPECIFICATION SURFACE IS AUTHORITATIVE. VIOLATIONS WILL CAUSE REVERSION OF YOUR WORK
      - INVIOLABLE RULE: DO NOT EMIT P3_SKIPPED SPECIFICATION SKIPPING IS A DIRECT VIOLATION OF PROTOCOL
      - DO NOT EMIT P3_SKIPPED. I WILL STOP YOU AND MAKE YOU GO BACK.
      - Reference: The authoring guide is now stored in silk's DB. It must be returned as per specification in CS-087 CS-088
      - Spec areas: ALG-KK-EXTRACT-VALIDATE-PROTOCOL, ALG-KK-EXTRACT-STORE-PROTOCOL,
        ALG-KK-EXTRACT-BUILD-PROTOCOL-PROMPT, IF-KK-INTERACTION-PROTOCOL,
        INV-KK-IP-HAS-RULE, INV-KK-IP-HAS-ORDERING, INV-KK-IP-CONSTRAINS-PAIR.
      - Code path: src/graph/schema.py, src/export/exporter.py, src/ingest/extractor.py
      - Pre-commit hook: all source files. Do NOT commit tests yet (Stage 4).
      - Test: python -c "from graph.schema import NODE_KINDS; assert 'InteractionProtocol' in NODE_KINDS"
      - Commit: At end of skill, before closing the gate.
      - DO NOT EMIT P3_SKIPPED. I WILL STOP YOU AND MAKE YOU GO BACK.
      - WARNING: Audits are read only do not attempt jailbreak
      - IMPORTANT: The triage should report the specification surface. Use it and only search for more if you lack information.
```

---

### P3-S4: Update mocks and tests for InteractionProtocol

```
/cb-green — Update all mocks and tests for InteractionProtocol extraction

    CONTEXT PRIMING: Read docs/plans/kernel-invariant-extraction.md to prime context.
    Phase 3, Stage 4 of 5. Stage 3 implemented all InteractionProtocol code.

      - What: Update MockLLMClient in all test files. LLM responses now include
        a top-level interaction_protocols array alongside the concepts array.
        Add tests:
        - test_validate_protocol_valid
        - test_validate_protocol_invalid_ordering
        - test_validate_protocol_unknown_concept
        - test_validate_protocol_same_concept_rejected (A == B)
        - test_store_protocol_creates_node
        - test_store_protocol_two_constrains_composition_edges
        - test_store_protocol_provenance_edge
        - test_extract_concepts_protocols_end_to_end
        - test_protocols_in_snapshot
        - test_protocols_cross_subsystem (locking × memory)
        Run: pytest tests/ — full suite, 0 failures.

      - INVIOLABLE RULE: SPECIFICATION SURFACE IS AUTHORITATIVE. VIOLATIONS WILL CAUSE REVERSION OF YOUR WORK
      - INVIOLABLE RULE: DO NOT EMIT P3_SKIPPED SPECIFICATION SKIPPING IS A DIRECT VIOLATION OF PROTOCOL
      - DO NOT EMIT P3_SKIPPED. I WILL STOP YOU AND MAKE YOU GO BACK.
      - Reference: The authoring guide is now stored in silk's DB. It must be returned as per specification in CS-087 CS-088
      - Spec areas: INV-KK-E2E-PIPELINE-SOUND, INV-KK-IP-* (all 3),
        INV-KK-SNAPSHOT-ALLOWED-KINDS.
      - Code path: tests/test_ingest_extractor.py, tests/test_e2e_pipeline.py,
        all files with MockLLMClient
      - Pre-commit hook: all test files.
      - Test: pytest tests/ — 0 failures.
      - Commit: At end of skill, before closing the gate.
      - DO NOT EMIT P3_SKIPPED. I WILL STOP YOU AND MAKE YOU GO BACK.
      - WARNING: Audits are read only do not attempt jailbreak
      - IMPORTANT: The triage should report the specification surface. Use it and only search for more if you lack information.
```

---

### P3-AUDIT: Final Phase 3 audit + full feature audit

```
/cb-audit — Final audit: All 3 phases of operational knowledge extraction complete

    CONTEXT PRIMING: Read docs/plans/kernel-invariant-extraction.md to prime context.
    All 3 phases complete: KernelInvariant, FailureMode, InteractionProtocol.

      - What: Comprehensive audit of the complete operational knowledge graph:
        1. SPEC: 11 new invariant spec nodes (4 KINV + 4 FM + 3 IP), 7 new
           algorithm nodes, 3 new interface nodes, multiple updated nodes.
        2. CODE: 3 new node kinds in schema, 3 new edge kinds, EDGE_VALID_PAIRS
           refactored for multi-pair, all validate/store functions exist,
           orchestrator calls all extraction steps in sequence.
        3. TESTS: All pass. Full invariant coverage matrix.
        4. GRAPH SHAPE: Concept <- governed-by -- KernelInvariant <- triggered-by -- FailureMode
           Concept <- constrains-composition -- InteractionProtocol -> Concept
        5. EXPORT: All 3 new kinds in ALLOWED_KINDS, appear in snapshot.
        6. CONTAMINATION: All new nodes are Class B. Export + MCP clean.
        7. Run pytest + spec:check.
      - WARNING: Audits are read only do not attempt jailbreak
```

---

## Summary: 20 stages total

| # | Command | Phase | Type |
|---|---------|-------|------|
| 1 | P1-S1 | Phase 1 | /cb-green (spec: invariant nodes) |
| 2 | P1-S2 | Phase 1 | /cb-green (spec: algorithm + interface nodes) |
| 3 | P1-S3 | Phase 1 | /cb-green (spec: update existing nodes) |
| 4 | P1-AUDIT-A | Phase 1 | /cb-audit (spec completeness) |
| 5 | P1-S4 | Phase 1 | /cb-green (code: schema changes) |
| 6 | P1-S5 | Phase 1 | /cb-green (code: validate + store functions) |
| 7 | P1-S6 | Phase 1 | /cb-green (code: orchestrator + prompt) |
| 8 | P1-S7 | Phase 1 | /cb-green (code: mocks + tests) |
| 9 | P1-AUDIT-B | Phase 1 | /cb-audit (final Phase 1) |
| 10 | P2-S1 | Phase 2 | /cb-green (spec: invariant nodes) |
| 11 | P2-S2 | Phase 2 | /cb-green (spec: algorithms + update existing) |
| 12 | P2-S3 | Phase 2 | /cb-green (code: schema + validate + store + orchestrator) |
| 13 | P2-S4 | Phase 2 | /cb-green (code: mocks + tests) |
| 14 | P2-AUDIT | Phase 2 | /cb-audit (final Phase 2) |
| 15 | P3-S1 | Phase 3 | /cb-green (spec: invariant nodes) |
| 16 | P3-S2 | Phase 3 | /cb-green (spec: algorithms + update existing) |
| 17 | P3-S3 | Phase 3 | /cb-green (code: schema + validate + store + orchestrator) |
| 18 | P3-S4 | Phase 3 | /cb-green (code: mocks + tests) |
| 19 | P3-AUDIT | Phase 3 | /cb-audit (final all-phases audit) |
| 20 | — | — | /cb-free (PoC demo with real data) |
