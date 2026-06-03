# know_kernel — Specification

This document defines the specification nodes for know_kernel's initial
phase. Node kinds and attributes follow the combobul metamodel schema
so they can be mechanically imported into a spec.db when know_kernel
gets its own combobul instance.

---

## Modules

### SUB-KK

Top-level system module for know_kernel.

```
kind: module
id: SUB-KK
description: know_kernel — kernel-design intelligence system. Ingests
  OS/kernel papers, proposals, code, and discussions; extracts abstract
  concepts while enforcing license contamination boundaries; serves
  human navigation (web) and LLM-assisted design (MCP).
```

### SUB-KK-GRAPH

```
kind: module
id: SUB-KK-GRAPH
location: SUB-KK
description: Shared graph engine library. SQLite-backed concept store
  with adjacency-list schema. Provides node/edge CRUD, traversal queries,
  and admissibility rule enforcement. Imported as a dependency by all
  four apps — not a standalone service.
```

### SUB-KK-INGEST

```
kind: module
id: SUB-KK-INGEST
location: SUB-KK
description: Ingestion service (App 1). Batch processor running on
  internet-connected infrastructure. Parses documents, scans licenses,
  classifies artifacts (Class A/B), runs LLM extraction agent, writes
  the full master DB. Extraction-mode sessions only.
```

### SUB-KK-WEB

```
kind: module
id: SUB-KK-WEB
location: SUB-KK
description: Web API (App 2). Long-running FastAPI + Jinja2/HTMX server
  on internal network. Serves human-facing views (card, comparison,
  timeline, subsystem explorer) from the full master DB. No content
  restrictions — humans see all classes.
```

### SUB-KK-EXPORT

```
kind: module
id: SUB-KK-EXPORT
location: SUB-KK
description: Snapshot exporter (App 3). CLI utility that reads the full
  master DB, filters out all Class A content, and produces a Class B-only
  SQLite file. This is the contamination gate — the single enforcement
  point for the clean-room boundary in the LLM path.
```

### SUB-KK-MCP

```
kind: module
id: SUB-KK-MCP
location: SUB-KK
description: MCP server (App 4). Lightweight container service running
  per-developer in Docker. Reads a Class B-only DB snapshot. Exposes
  concept query tools to opencode via MCP protocol. Proposal-mode
  sessions only. No write path, no evidence access.
```

---

## Interfaces

### IF-KK-CONCEPT

```
kind: interface
id: IF-KK-CONCEPT
language: meta
description: A kernel design concept — the primary entity in the knowledge
  base. Represents an abstract mechanism, pattern, or invariant extracted
  from evidence. Always Class B (clean).
```

**Fields (relations):**

| Field | Description |
|-------|-------------|
| IF-KK-CONCEPT.name | Human-readable name |
| IF-KK-CONCEPT.description | Abstract description of the mechanism |
| IF-KK-CONCEPT.problem | Problem addressed |
| IF-KK-CONCEPT.mechanism | How it works (abstract, no code) |
| IF-KK-CONCEPT.assumptions | Required assumptions |
| IF-KK-CONCEPT.subsystems | Kernel subsystems affected |
| IF-KK-CONCEPT.invariants | Invariants the mechanism depends on |
| IF-KK-CONCEPT.performanceModel | Performance characteristics |
| IF-KK-CONCEPT.securityModel | Security implications |
| IF-KK-CONCEPT.portability | Portability concerns |
| IF-KK-CONCEPT.maturity | Maturity level |
| IF-KK-CONCEPT.evidenceStrength | How well-supported by evidence |
| IF-KK-CONCEPT.contaminationRisk | License contamination risk level (L0-L4) |
| IF-KK-CONCEPT.recommendation | adopt / study / reject / quarantine |

### IF-KK-SOURCE

```
kind: interface
id: IF-KK-SOURCE
language: meta
description: A document, repository, paper, or mailing list thread that
  has been ingested. Carries license and provenance metadata.
```

**Fields:**

| Field | Description |
|-------|-------------|
| IF-KK-SOURCE.url | Origin URL or identifier |
| IF-KK-SOURCE.author | Author or maintainer |
| IF-KK-SOURCE.license | License identifier (SPDX where applicable) |
| IF-KK-SOURCE.confidence | Confidence in license classification |
| IF-KK-SOURCE.sourceType | repo / paper / proposal / mailing-list |

### IF-KK-EVIDENCE

```
kind: interface
id: IF-KK-EVIDENCE
language: meta
description: A specific excerpt, code fragment, or patch from a source.
  Always Class A (licensed, access-restricted for LLM consumers).
```

**Fields:**

| Field | Description |
|-------|-------------|
| IF-KK-EVIDENCE.content | The raw evidence (code, excerpt, patch) |
| IF-KK-EVIDENCE.artifactClass | Always "A" |
| IF-KK-EVIDENCE.contaminationLevel | L0-L4 |

### IF-KK-ADVISORY

```
kind: interface
id: IF-KK-ADVISORY
language: meta
description: License and contamination metadata attached to a source or
  concept. Every source must have one, even if classification is "unknown."
```

**Fields:**

| Field | Description |
|-------|-------------|
| IF-KK-ADVISORY.license | License identifier |
| IF-KK-ADVISORY.contaminationLevel | L0 (public) through L4 (unknown) |
| IF-KK-ADVISORY.usageConstraints | What usage is safe, what is not |
| IF-KK-ADVISORY.directReuse | Whether direct reuse is permitted |

### IF-KK-PROPOSAL

```
kind: interface
id: IF-KK-PROPOSAL
language: meta
description: An LLM-generated design suggestion for the target kernel.
  Always Class C (internal). Must be grounded in concepts, never evidence.
```

**Fields:**

| Field | Description |
|-------|-------------|
| IF-KK-PROPOSAL.description | What the proposal changes |
| IF-KK-PROPOSAL.rationale | Why this design is recommended |
| IF-KK-PROPOSAL.groundedIn | List of concept IDs backing this proposal |
| IF-KK-PROPOSAL.subsystem | Target kernel subsystem |

### IF-KK-SNAPSHOT

```
kind: interface
id: IF-KK-SNAPSHOT
language: meta
description: A Class B-only SQLite database file produced by the snapshot
  exporter. Contains only clean concepts, no Class A evidence.
```

**Fields:**

| Field | Description |
|-------|-------------|
| IF-KK-SNAPSHOT.sourceDbHash | Hash of the master DB at export time |
| IF-KK-SNAPSHOT.exportedAt | Timestamp of export |
| IF-KK-SNAPSHOT.nodeCount | Number of nodes in the snapshot |
| IF-KK-SNAPSHOT.classACount | Must be 0 (validation check) |

---

## Invariants

### INV-KK-CONTAMINATION-GATE

```
kind: invariant
id: INV-KK-CONTAMINATION-GATE
description: The snapshot exporter must filter out ALL Class A content.
  The output DB must contain zero Evidence nodes, zero Class A artifacts,
  and no edges that reference Evidence nodes.
predicateNL: For every node N in the exported snapshot, N.artifactClass != "A"
  AND N.kind != "Evidence". For every edge E in the snapshot,
  E.target.kind != "Evidence" AND E.source.kind != "Evidence".
severity: critical
```

### INV-KK-SESSION-SEPARATION

```
kind: invariant
id: INV-KK-SESSION-SEPARATION
description: No operational session may both access Class A evidence
  artifacts and produce Class C design proposals. Sessions are classified
  at initialization as either extraction-mode or proposal-mode, and the
  classification is immutable for the session lifetime.
predicateNL: For every session S, if S accessed any Class A artifact,
  then S.proposals = empty. If S produced any proposal, then
  S.classAAccesses = empty.
severity: critical
```

### INV-KK-CONCEPT-PROVENANCE

```
kind: invariant
id: INV-KK-CONCEPT-PROVENANCE
description: Every Concept node must have at least one extracted-from
  edge to an Evidence node. No orphan concepts — provenance is required
  to trace how the abstraction was derived.
predicateNL: For every node N where N.kind = "Concept",
  exists edge E where E.kind = "extracted-from" AND E.source = N.id.
severity: error
```

### INV-KK-EVIDENCE-TRACEABLE

```
kind: invariant
id: INV-KK-EVIDENCE-TRACEABLE
description: Every Evidence node must have exactly one sourced-from edge
  to a Source node. Raw material must be traceable to its origin.
predicateNL: For every node N where N.kind = "Evidence",
  count(edges E where E.kind = "sourced-from" AND E.source = N.id) = 1.
severity: error
```

### INV-KK-PROPOSAL-NO-EVIDENCE

```
kind: invariant
id: INV-KK-PROPOSAL-NO-EVIDENCE
description: Proposal nodes may only have grounded-in edges to Concept
  nodes, never to Evidence nodes. This is the structural contamination
  firewall — proposals cannot reference licensed implementation details.
predicateNL: For every edge E where E.kind = "grounded-in",
  E.target.kind = "Concept" (never "Evidence").
severity: critical
```

### INV-KK-SOURCE-ADVISORY

```
kind: invariant
id: INV-KK-SOURCE-ADVISORY
description: Every Source node must have at least one assessed-by edge to
  an Advisory node. License status must always be known, even if the
  classification is "unknown provenance" (L4).
predicateNL: For every node N where N.kind = "Source",
  exists edge E where E.kind = "assessed-by" AND E.source = N.id.
severity: error
```

### INV-KK-CONCEPT-SUBSYSTEM

```
kind: invariant
id: INV-KK-CONCEPT-SUBSYSTEM
description: Every Concept node must have at least one belongs-to edge
  to a Subsystem node. No orphan ideas — domain classification is required.
predicateNL: For every node N where N.kind = "Concept",
  exists edge E where E.kind = "belongs-to" AND E.source = N.id.
severity: error
```

### INV-KK-CONTRADICTS-SYMMETRIC

```
kind: invariant
id: INV-KK-CONTRADICTS-SYMMETRIC
description: The contradicts edge kind is symmetric. If concept A
  contradicts concept B, then B contradicts A.
predicateNL: For every edge E where E.kind = "contradicts",
  exists edge E' where E'.kind = "contradicts" AND E'.source = E.target
  AND E'.target = E.source.
severity: error
```

### INV-KK-SUPERSEDES-ACYCLIC

```
kind: invariant
id: INV-KK-SUPERSEDES-ACYCLIC
description: The supersedes relation is acyclic. No circular replacement
  chains.
predicateNL: The directed graph formed by supersedes edges contains no
  cycles.
severity: error
```

### INV-KK-SNAPSHOT-ZERO-CLASS-A

```
kind: invariant
id: INV-KK-SNAPSHOT-ZERO-CLASS-A
description: A validated snapshot must report classACount = 0. This is
  the acceptance test for the contamination gate.
predicateNL: For every snapshot S, S.classACount = 0.
severity: critical
```

---

## Algorithms

### ALG-KK-INGEST-DOCUMENT

```
kind: algorithm
id: ALG-KK-INGEST-DOCUMENT
location: SUB-KK-INGEST
description: Ingest a document into the knowledge base. Parse it, scan
  its license, classify it, create Source and Evidence nodes.
preconditionNL: Input is a valid document path or URL.
postconditionNL: A Source node exists with at least one assessed-by edge
  to an Advisory. Evidence artifacts are created with correct Class A
  classification.
```

### ALG-KK-LICENSE-SCAN

```
kind: algorithm
id: ALG-KK-LICENSE-SCAN
location: SUB-KK-INGEST
description: Scan a document or repository for license information.
  Classify the artifact as Class A (licensed evidence) and assign a
  contamination level (L0-L4).
preconditionNL: Input is a parseable document with identifiable content.
postconditionNL: An Advisory node exists with license, contaminationLevel,
  usageConstraints, and directReuse fields populated.
```

### ALG-KK-LLM-EXTRACT

```
kind: algorithm
id: ALG-KK-LLM-EXTRACT
location: SUB-KK-INGEST
description: Run the LLM extraction agent on evidence artifacts to
  produce abstract concept records. The agent reads Class A evidence
  and outputs Class B concepts. Must run in an extraction-mode session.
preconditionNL: Evidence artifacts exist with sourced-from provenance.
  Session is extraction-mode (INV-KK-SESSION-SEPARATION).
postconditionNL: Concept nodes exist with extracted-from edges to the
  evidence. Concepts contain no code — only mechanisms, invariants,
  tradeoffs, and assumptions.
```

### ALG-KK-EXPORT-SNAPSHOT

```
kind: algorithm
id: ALG-KK-EXPORT-SNAPSHOT
location: SUB-KK-EXPORT
description: Read the full master DB, filter out all Class A content,
  produce a Class B-only SQLite file. Validate that the output contains
  zero Evidence nodes and zero Class A artifacts.
preconditionNL: Master DB exists and is readable.
postconditionNL: Output DB satisfies INV-KK-CONTAMINATION-GATE and
  INV-KK-SNAPSHOT-ZERO-CLASS-A.
```

### ALG-KK-MCP-QUERY

```
kind: algorithm
id: ALG-KK-MCP-QUERY
location: SUB-KK-MCP
description: Handle a concept query from opencode via MCP protocol.
  Traverse the Class B-only graph to find concepts by subsystem,
  mechanism, or relationship.
preconditionNL: Class B-only snapshot DB is loaded. Session is
  proposal-mode (INV-KK-SESSION-SEPARATION).
postconditionNL: Response contains only Class B concept data. No Class A
  artifacts are referenced or returned.
```

### ALG-KK-VALIDATE-ADMISSIBILITY

```
kind: algorithm
id: ALG-KK-VALIDATE-ADMISSIBILITY
location: SUB-KK-GRAPH
description: Check all admissibility rules against the current graph state.
  Reports violations for concepts without provenance, evidence without
  sources, proposals grounded in evidence, etc.
preconditionNL: Graph DB is loaded and queryable.
postconditionNL: Returns a list of violations. Empty list means the graph
  is admissible.
```

---

## Edge Schema

For reference, the complete edge schema for the runtime graph:

| Edge kind | From → To | Meaning | Cardinality |
|-----------|-----------|---------|-------------|
| belongs-to | Concept → Subsystem | Domain classification | 1..* |
| extracted-from | Concept → Evidence | Provenance chain | 1..* |
| sourced-from | Evidence → Source | Material origin | 1..1 |
| alternative-to | Concept → Concept | Competing approaches | 0..* |
| refines | Concept → Concept | Evolutionary improvement | 0..* |
| contradicts | Concept → Concept | Conflicting claims (symmetric) | 0..* |
| prerequisite | Concept → Concept | Must exist for this to work | 0..* |
| supersedes | Concept → Concept | Replaces older idea (acyclic) | 0..* |
| assessed-by | Source → Advisory | License assessment | 1..* |
| grounded-in | Proposal → Concept | Clean concept backing (never Evidence) | 1..* |

---

## Containment Hierarchy

```
SUB-KK
├── SUB-KK-GRAPH
│   ├── IF-KK-CONCEPT
│   ├── IF-KK-SOURCE
│   ├── IF-KK-EVIDENCE
│   ├── IF-KK-ADVISORY
│   ├── IF-KK-PROPOSAL
│   ├── INV-KK-CONCEPT-PROVENANCE
│   ├── INV-KK-EVIDENCE-TRACEABLE
│   ├── INV-KK-PROPOSAL-NO-EVIDENCE
│   ├── INV-KK-SOURCE-ADVISORY
│   ├── INV-KK-CONCEPT-SUBSYSTEM
│   ├── INV-KK-CONTRADICTS-SYMMETRIC
│   ├── INV-KK-SUPERSEDES-ACYCLIC
│   └── ALG-KK-VALIDATE-ADMISSIBILITY
├── SUB-KK-INGEST
│   ├── ALG-KK-INGEST-DOCUMENT
│   ├── ALG-KK-LICENSE-SCAN
│   ├── ALG-KK-LLM-EXTRACT
│   └── INV-KK-SESSION-SEPARATION
├── SUB-KK-WEB
│   (views and routes — deferred to next phase)
├── SUB-KK-EXPORT
│   ├── IF-KK-SNAPSHOT
│   ├── ALG-KK-EXPORT-SNAPSHOT
│   ├── INV-KK-CONTAMINATION-GATE
│   └── INV-KK-SNAPSHOT-ZERO-CLASS-A
└── SUB-KK-MCP
    └── ALG-KK-MCP-QUERY
```

---

## Node Count Summary

| Kind | Count |
|------|-------|
| module | 6 |
| interface | 6 |
| invariant | 9 |
| algorithm | 6 |
| **Total** | **27** |

---

## Notes

- **Project isolation (combobul rule #6):** These nodes are specified
  here as documentation. They do NOT belong in combobul's spec.db.
  When know_kernel gets its own combobul instance, these definitions
  can be imported via `ril apply-batch`.

- **Web views (SUB-KK-WEB):** Deferred to a later phase. Card view,
  comparison tables, timeline, and subsystem explorer will each get
  their own algorithm nodes when implemented.

- **Report tiers:** The L0-L4 report generation algorithms are deferred.
  They depend on the web module and template engine, which come after
  the core graph and ingestion are working.

- **Subsystem nodes:** The actual kernel subsystem nodes (Scheduler, MM,
  IPC, Sync, Drivers, Security, etc.) are runtime data, not spec nodes.
  They will be created by the ingestion service as it processes sources.
