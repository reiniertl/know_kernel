# know_kernel — Architecture

## Purpose

know_kernel is a kernel-design intelligence system. It ingests OS/kernel
papers, proposals, code, and discussions; extracts abstract concepts
while enforcing license contamination boundaries; and serves two
consumer modes: human navigation and LLM-assisted design.

## Two Consumer Modes

### Mode 1: Human Navigation

Engineers browse a structured knowledge base organized by kernel
subsystem. The primary entity is the **Idea** — not a document.
Documents are evidence attached to ideas.

What humans see:

- **Card view** — one idea rendered as a readable datasheet with
  relationships (prerequisites, alternatives, provenance) laid out
  as sections
- **Comparison tables** — side-by-side tradeoff analysis of competing
  mechanisms within a subsystem
- **Timeline view** — evolutionary lineage of an idea through
  refinement and supersession
- **Subsystem explorer** — top-level navigation by kernel domain
  (scheduler, MM, IPC, sync, drivers, security, etc.)
- **Adoption memos** — actionable evaluation: should we consider this
  for our kernel?

Humans never see the graph directly. The graph powers views that feel
natural — cards, tables, timelines, hierarchies.

Humans can see **all content** — Class A (licensed evidence), Class B
(clean concepts), and Class C (internal proposals). The contamination
boundary does not restrict human access.

### Mode 2: LLM Consumption

An LLM agent (via opencode with self-hosted models) has access to a
target kernel codebase. It queries the clean concept store (never the
evidence store) for mechanisms, invariants, and tradeoffs. It proposes
changes to the kernel codebase grounded in abstract design patterns —
not copied implementations.

Constraints:

- Every proposal must cite which clean concepts it draws from
- The LLM never sees Class A (licensed implementation) artifacts
- The extraction agent and the proposal agent must never share a
  session — that is the practical clean-room boundary

---

## Technology Stack

### Language: Python

Python is the primary language for all components. Rationale:

- **Document ingestion** — PDF/paper parsing libraries (PyMuPDF,
  pdfplumber, GROBID bindings) are Python-first
- **LLM SDKs** — extraction and proposal agents call self-hosted
  model endpoints; Python has the most mature orchestration tooling
- **License scanning** — ScanCode is a Python tool, FOSSology has
  Python bindings
- **NLP preprocessing** — tokenizers, text chunking, embedding
  generation are Python-dominated

The graph engine, admissibility rules, API server, and human-facing
frontend are standard application concerns where Python works equally
well (FastAPI, Jinja2/HTMX).

### Storage: SQLite

The runtime graph uses SQLite with an adjacency-list schema. Rationale:

- The knowledge base will be thousands of concepts, not millions
- Single-file deployment, ACID transactions
- No infrastructure overhead
- Edge constraints and node-kind schemas enforced at the application
  layer
- Admissibility rules enforced via the graph engine library

### Web Framework: FastAPI + Jinja2/HTMX

Server-rendered human views — no separate frontend build needed.
FastAPI provides the REST API; Jinja2 templates with HTMX provide
interactive views without a JavaScript build pipeline.

### MCP Server: Python MCP SDK

Anthropic's `mcp` Python package exposes Class B query tools to
opencode. The MCP server runs locally in each developer's Docker
container.

### Self-Hosted Models

All LLM inference (extraction agent, proposal agent) runs against
self-hosted model endpoints via opencode. The model choice does not
affect the architecture — the separation is at the application layer,
not the model layer.

---

## System Decomposition

Four applications and one shared library.

### Shared Library: Graph Engine

The graph engine is a Python library used by all four apps.
Responsibilities:

- SQLite schema management (14 node kinds, 18 edge kinds)
- Node/edge CRUD operations
- Admissibility rule enforcement (every Concept needs `belongs-to`,
  every Evidence needs `sourced-from`, etc.)
- Contamination level propagation
- Optimization module (`optimization.py`): create/link OptimizationGoals,
  UseCaseScenarios, ComparativeAnalyses
- Query layer (6 functions): `subgraph_around`, `query_edges_by_attrs`,
  `compare_neighborhoods`, `match_scenarios`, `transitive_impact`,
  `ranked_recommendations`

This is **not a service** -- it is imported as a dependency by each app.
The SQLite database file is the integration point.

### App 1: Ingestion Service

**Type:** Batch service (internet-facing)

**Purpose:** Ingest documents, scan licenses, extract concepts, build
and maintain the master knowledge base.

**Responsibilities:**

- Document parsing: PDFs, source repositories, papers, mailing lists
- License scanning via ScanCode/FOSSology
- Class A/B classification of all ingested material
- LLM extraction agent: reads raw evidence, produces abstract concept
  records (extraction-mode sessions only)
- Writes the full master DB (Class A + Class B content)

**Deployment:** Runs on internet-connected infrastructure. Needs
network access (to fetch documents, repos, papers), GPU access (for
self-hosted model inference), and storage for evidence artifacts.

**Data flow:**

```
Documents/repos/papers
    → Document parser
    → License scanner (ScanCode/FOSSology)
    → Class A/B classification
    → Evidence store (Class A, restricted)
    → LLM extraction agent
    → Contamination gate (within extraction)
    → Concept store (Class B, clean)
    → Master DB (full: Class A + B)
```

### App 2: Web API

**Type:** Long-running server (internal network)

**Purpose:** Serve the human-facing views from the knowledge base.

**Responsibilities:**

- FastAPI REST API serving concept data
- Jinja2/HTMX server-rendered views:
  - Card view (single idea datasheet)
  - Comparison tables (side-by-side tradeoffs)
  - Timeline view (idea lineage)
  - Subsystem explorer (domain navigation)
  - Adoption memos (evaluation records)
- Full DB access — humans see all content (Class A + B), no restrictions

**Deployment:** Single server on internal network. Reads from a copy
of the master DB (or the master DB directly if co-located with the
ingestion service).

### App 3: Snapshot Exporter

**Type:** CLI utility

**Purpose:** Produce a Class B-only SQLite file from the full master
DB. This is the **contamination gate** — the single point where the
clean/dirty boundary is enforced for LLM consumption.

**Responsibilities:**

- Read the full master DB
- Filter out all Class A content (licensed evidence, code excerpts,
  restricted artifacts)
- Produce a standalone Class B-only SQLite file
- Validate that the output contains no Class A material

**Deployment:** Runs on demand (or scripted) whenever the master DB is
updated and a new snapshot needs to reach developers. Output is the DB
file that App 4 (MCP server) ships with.

**This utility is architecturally critical.** It is the single
enforcement point for the contamination firewall in the LLM path. If
this tool is correct, the MCP server is clean by construction.

### App 4: MCP Server

**Type:** Local container service (per-developer Docker)

**Purpose:** Expose Class B concepts to LLM coding assistants via MCP
protocol.

**Responsibilities:**

- Serve the Class B-only DB snapshot via 9 MCP tools
- Search across all Class B node kinds (dynamic ALLOWED_KINDS)
- Query tools: concept lookup, impact surface analysis,
  goal-based recommendations, concept comparison, workload matching,
  subgraph exploration (depth capped at 3)
- Enforce proposal-mode only: no evidence endpoints, no write path
- Lightweight, offline-capable, no external dependencies

**Deployment:** Runs inside each developer's Docker container alongside
opencode and development tooling. Ships with a Class B-only DB
snapshot. No network dependency on the ingestion service or web API.

**Update cycle:**

```
Ingestion service populates master DB
    → Snapshot exporter filters to Class B-only
    → Developers pull updated snapshot into their container
    → MCP server serves fresh concepts
```

---

## Deployment Topology

The system spans two network zones with distinct security postures.

### Internet Side (Untrusted Network)

The **ingestion service** runs here. It needs internet access to fetch
documents, repositories, papers, and mailing list archives. It also
runs self-hosted LLM inference for concept extraction.

This is the only place where Class A evidence exists in its raw form.
The master DB (containing both Class A and Class B content) lives here.

### Air-Gapped Network (Trusted, Internal)

The development environment is air-gapped. Components inside:

- **Web API** — single server, serves human views from a DB copy.
  Maintainers browse, curate, and verify concepts.
- **Developer containers** — one Docker container per developer.
  Each contains:
  - MCP server (App 4)
  - Class B-only DB snapshot
  - opencode (LLM frontend)
  - Development tooling (compiler, debugger, etc.)
  - Target kernel source tree

The master DB crosses the air gap via controlled transfer (sneakernet,
one-way data diode, or whatever security policy requires). The snapshot
exporter runs before or during the transfer to produce the Class B-only
version for developer containers.

### Network Diagram

```
┌─────────────────────────────────────┐
│         INTERNET SIDE               │
│                                     │
│   ┌──────────────────────────┐      │
│   │  App 1: Ingestion        │      │
│   │  Service                 │      │
│   │  ┌────────────────────┐  │      │
│   │  │ Document parser    │  │      │
│   │  │ License scanner    │  │      │
│   │  │ LLM extraction     │  │      │
│   │  │ agent              │  │      │
│   │  └────────────────────┘  │      │
│   │          │               │      │
│   │   Master DB (A + B)      │      │
│   └──────────────────────────┘      │
│              │                      │
└──────────────│──────────────────────┘
               │ controlled transfer
               │ (+ snapshot export)
┌──────────────│──────────────────────┐
│         AIR-GAPPED NETWORK          │
│              │                      │
│    ┌─────────┴──────────┐           │
│    │                    │           │
│    ▼                    ▼           │
│  Full DB             B-only DB     │
│    │                    │           │
│    ▼                    │           │
│  ┌──────────────┐       │           │
│  │ App 2:       │       │           │
│  │ Web API      │       │           │
│  │ (humans)     │       │           │
│  └──────────────┘       │           │
│                         │           │
│    ┌────────────────────┼────┐      │
│    │ Dev Container 1    │    │      │
│    │    ┌───────────────▼─┐  │      │
│    │    │ App 4: MCP      │  │      │
│    │    │ Server (B-only) │  │      │
│    │    └────────┬────────┘  │      │
│    │             │           │      │
│    │    ┌────────▼────────┐  │      │
│    │    │ opencode +      │  │      │
│    │    │ self-hosted LLM │  │      │
│    │    └─────────────────┘  │      │
│    │                         │      │
│    │    kernel source tree   │      │
│    └─────────────────────────┘      │
│                                     │
│    ┌─────────────────────────┐      │
│    │ Dev Container 2 ...     │      │
│    └─────────────────────────┘      │
│                                     │
└─────────────────────────────────────┘
```

---

## The Contamination Firewall

The most critical architectural element. The boundary is between
**humans and LLMs**, not between networks.

### Why Human Access Is Unrestricted

Humans can see everything — Class A, Class B, all of it. A human
reading GPL code does not contaminate their kernel contributions.
This is legally established. The web API serves the full knowledge base
without restrictions.

### Why LLM Access Is Restricted

An LLM that saw Class A implementation details and then produced
kernel code creates an unprovable contamination question. The LLM's
context window is what must stay clean. If a session has seen licensed
implementation details, any code it produces afterward is suspect.

### Where the Boundary Is Enforced

The contamination gate is the **snapshot exporter** (App 3). It is
the single point where Class A content is filtered out before reaching
the MCP server. Everything upstream has full content; everything
downstream is clean by construction.

The MCP server (App 4) physically cannot serve Class A content because
it only has the Class B-only snapshot. No runtime check needed — the
data simply isn't there.

### Session-Level Operational Separation

No operational session may both access Class A evidence artifacts and
produce Class C design proposals. Sessions are classified at
initialization:

- **Extraction sessions** — can read Class A evidence, can write to
  the concept store. Cannot produce kernel proposals. (Ingestion
  service only.)
- **Proposal sessions** — can read Class B concepts only. Cannot
  access the evidence store at all. This is what opencode connects
  to via the MCP server.

The same model infrastructure serves both session types. The
separation is architectural (different entry points, different
processes), not model-level. Same model, different apps.

### Artifact Classes

```
CLASS A — Licensed Evidence
  raw code, patches, implementation details, direct excerpts

CLASS B — Abstracted Mechanisms
  concepts, invariants, architectural patterns, tradeoffs,
  mathematical models

CLASS C — Internal Design Proposals
  independently generated designs, no structural dependence
  on licensed implementation, provenance-tracked
```

### Contamination Risk Levels

```
L0 — Public domain / permissive license
L1 — Weak copyleft
L2 — Strong copyleft
L3 — Patent-sensitive
L4 — Unknown provenance
```

---

## Three-Layer Data Model

### Layer 1: Source Layer

Raw ingested material with license and provenance metadata.

- **Source cards** — URL, author, license, confidence, source type
  (repo, paper, proposal, mailing list)
- **Evidence artifacts** — code, patches, excerpts with license
  metadata (Class A, access-restricted for LLM consumers)

### Layer 2: Concept Layer

LLM-extracted abstractions. The heart of the system.

- **Concept records** — mechanism description, invariants, assumptions,
  tradeoffs, subsystem tags, maturity, evidence strength
- **Relationships** between concepts: alternative, refines, contradicts,
  prerequisite, supersedes, applicable-to
- **License advisories** — what usage is safe, what is not

### Layer 3: Output Layer

Generated artifacts for consumption.

- **Tiered reports**: L0 (executive summary) through L4 (adoption memo)
- **Kernel proposals** (LLM mode): design changes referencing only
  clean concepts
- **Comparison tables, timeline views, subsystem maps** (human mode)

---

## Graph Schema

### Why a Graph

The relationships between kernel design concepts are more valuable
than the concepts themselves in isolation. Kernel architecture is
dominated by interactions:

- RCU only makes sense if you understand quiescent-state detection
  (prerequisite)
- Choosing RCU means rejecting rwlock for that use case (alternative)
- A scheduling decision constrains synchronization choices (dependency)
- An idea from 1990 was refined three times (lineage)
- Two papers contradict each other on scalability (contradiction)

A graph makes three things cheap:

1. **Traversal** — "show me everything that depends on the assumption
   that we have SMP" is one query
2. **Contamination propagation** — if a concept was derived from a GPL
   source, everything downstream inherits contamination risk via graph
   walk
3. **LLM grounding** — the proposal agent traverses typed edges for
   structured, traceable reasoning rather than embedding similarity

The graph also enforces the contamination firewall structurally —
Class A and Class B are distinct node types with directional edges,
preventing accidental traversal from clean concepts back into licensed
code.

Humans never see the graph. The graph powers curated views (cards,
tables, timelines). The LLM traverses the raw graph directly. One
graph, two rendering strategies.

### Node Kinds (14)

| Node kind  | What it represents | Class |
|------------|-----------------------------------------------------|-------|
| Source | A document, repo, paper, mailing list thread | A |
| Evidence | A specific excerpt/code fragment from a source | A |
| Advisory | License/contamination metadata for a source | A |
| Concept | A kernel design idea/mechanism (the primary entity) | B |
| Subsystem | Kernel domain (scheduler, MM, IPC, etc.) | B |
| Proposal | An LLM-generated design suggestion for the target kernel | B |
| KernelInvariant | A rule that must hold for a mechanism to be correct | B |
| FailureMode | What breaks when an invariant is violated | B |
| InteractionProtocol | Cross-concept composition constraint | B |
| PerformanceProfile | Quantitative bounds per concept per metric | B |
| CompatibilityAssessment | Synergy analysis between concept pairs | B |
| OptimizationGoal | Measurable objective (minimize latency, etc.) | B |
| UseCaseScenario | Workload pattern (cpu-bound, real-time, etc.) | B |
| ComparativeAnalysis | Head-to-head comparison on a dimension | B |

### Edge Kinds (18)

| Edge kind | From --> To | Meaning |
|-----------|-------------|---------|
| belongs-to | Concept/KernelInvariant --> Subsystem | Domain classification |
| extracted-from | (7 kinds) --> Evidence | Provenance chain |
| sourced-from | Evidence --> Source | Where the raw material came from |
| alternative-to | Concept --> Concept | Competing approaches |
| refines | Concept --> Concept | Evolutionary improvement |
| contradicts | Concept --> Concept | Conflicting claims (symmetric) |
| prerequisite | Concept --> Concept | Must exist for this to work |
| supersedes | Concept --> Concept | Replaces an older idea (acyclic) |
| assessed-by | Source --> Advisory | Contamination/license assessment |
| grounded-in | Proposal --> Concept | What clean concepts back the proposal |
| governed-by | KernelInvariant --> Concept | Invariant constrains mechanism |
| triggered-by | FailureMode --> KernelInvariant | Violation consequence |
| constrains-composition | InteractionProtocol --> Concept | Composition rule (2 edges per protocol) |
| profiled-by | PerformanceProfile --> Concept | Performance data attached to mechanism |
| assesses-compatibility | CompatibilityAssessment --> Concept | Synergy analysis (2 edges per assessment) |
| contributes-to | Concept --> OptimizationGoal | Goal contribution with direction + magnitude |
| suited-for | Concept --> UseCaseScenario | Workload fitness rating |
| compares | ComparativeAnalysis --> Concept | Head-to-head comparison (2 edges per analysis) |

### Admissibility Rules

- Every Concept must have at least one `belongs-to` edge (no orphan
  ideas)
- Every Concept must have at least one `extracted-from` edge
  (provenance required)
- Every Evidence must have exactly one `sourced-from` edge (traceable
  origin)
- Proposal nodes may only have `grounded-in` edges to Concept nodes,
  never to Evidence nodes (contamination firewall)
- `contradicts` is symmetric -- if A contradicts B, B contradicts A
- `supersedes` is acyclic -- no circular replacement chains
- Every Source must have an Advisory (license status always known,
  even if "unknown")
- Every KernelInvariant has exactly one `governed-by` edge to a Concept
- Every FailureMode has exactly one `triggered-by` edge to a KernelInvariant
- Every InteractionProtocol has exactly 2 `constrains-composition` edges
  to distinct Concepts
- Every CompatibilityAssessment has exactly 2 `assesses-compatibility`
  edges to distinct Concepts
- Every ComparativeAnalysis has exactly 2 `compares` edges to distinct
  Concepts
- OptimizationGoal and UseCaseScenario are seeded/curated (no provenance
  edge required)

---

## Concept Record Attributes

Each concept in the runtime graph carries:

```
name
description
artifact_class (always "abstracted-mechanism" for Class B)
key_properties (list of defining characteristics)
tradeoffs (list of limitations or costs)
design_rationale (why this approach was chosen)
```

Related node kinds attached to each concept via edges:

```
KernelInvariant (via governed-by): predicate, strength, scope
FailureMode (via triggered-by on invariant): symptom, blast_radius, recoverability
InteractionProtocol (via constrains-composition): rule, ordering, violation_mode
PerformanceProfile (via profiled-by): metric, complexity, best/worst/typical case, conditions
CompatibilityAssessment (via assesses-compatibility): synergy, rationale, conditions
ComparativeAnalysis (via compares): dimension, winner, conditions, quantitative_delta
OptimizationGoal (via contributes-to): name, metric, direction (minimize/maximize)
UseCaseScenario (via suited-for): workload_type, constraints, fitness rating
```

---

## Report Tiers

```
L0: one-paragraph executive summary
L1: mechanism summary
L2: subsystem impact summary
L3: formal design record with assumptions/invariants
L4: evaluation memo for adoption/rejection
```

The adoption memo (L4) answers:

- Should we consider this?
- What subsystem would it affect?
- What invariant does it depend on?
- What breaks if the assumption is false?
- Is this merely an implementation trick, or a reusable architecture
  idea?
- Is there any licensing/provenance concern?

---

## Specification Graph vs. Runtime Graph

Two distinct graphs are in play:

1. **Specification graph** — specifies the application itself. Its
   nodes describe what node kinds the runtime graph supports, what
   admissibility rules it enforces, what happens when contamination
   is detected. This is the engineering specification, maintained
   separately from the deliverable.

2. **Runtime graph** — the actual knowledge base the app builds and
   serves. Its nodes are things like "RCU Synchronization" and
   "Linux kernel source." This is what humans browse and the LLM
   traverses.

The specification graph describes *how the runtime graph should
behave*. The runtime graph engine, its storage, its query API — that
is all application code.

---

## Summary Table

| Component | Type | Language | Reads | Writes | Deployment |
|-----------|------|----------|-------|--------|------------|
| Graph engine | Shared library | Python | -- | -- | Imported by all apps |
| Ingestion service | Batch service | Python | Documents, repos, papers | Full master DB (A+B) | Internet-connected |
| Web API | Long-running server | Python | Full master DB (A+B) | Nothing (read-only) | Air-gapped, single server |
| Snapshot exporter | CLI utility | Python | Full master DB (A+B) | Class B-only DB (11 kinds) | Runs at transfer time |
| MCP server | Container service | Python | Class B-only DB | Nothing (read-only, 9 tools) | Air-gapped, per-dev Docker |

---

## LLM Query Chain

The complete reasoning chain when an LLM queries the knowledge graph:

```
Question ("reduce latency in subsystem X")
  -> OptimizationGoal lookup ("minimize latency")
  -> contributes-to edges (direction=improves)
  -> Candidate Concepts (ranked by magnitude + impact surface size)
  -> For each candidate: transitive_impact() returns full surface:
      invariants, failure_modes, protocols, profiles,
      goals, compatibilities, comparatives, scenarios
  -> Answer + complete impact surface
```

The graph also supports direct queries:

```
compare_concepts(A, B)    -> neighborhood diff + ComparativeAnalysis nodes
match_workload("cpu-bound") -> scenarios with suited concepts by fitness
explore_subgraph(node, 2) -> multi-hop BFS neighborhood
```

---

## Key Principle

The system does not say:

> "Here is how Linux implements X."

It says:

> "This source discusses a design pattern where X is handled by
> separating policy from mechanism, using Y invariant, with
> tradeoff Z. The mechanism has O(1) read latency, composes
> synergistically with mechanism B, and contributes strongly
> to the goal of minimizing latency in cpu-bound workloads."

That distinction is central.
