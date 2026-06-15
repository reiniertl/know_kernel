# know_kernel

A kernel-design intelligence system. Ingests OS/kernel papers, proposals,
code, and discussions; extracts abstract concepts while enforcing license
contamination boundaries; serves two consumer modes -- human navigation
and LLM-assisted design.

## What it does

- **Ingests** documents, source repos, papers, mailing list discussions
- **Scans** licenses and classifies artifacts (Class A: licensed evidence,
  Class B: clean abstractions)
- **Extracts** abstract design concepts via LLM -- mechanisms, invariants,
  failure modes, interaction protocols, performance profiles, compatibility
  assessments, and comparative analyses -- never raw code
- **Answers optimization questions** -- "how do I reduce latency?", "which
  concepts work well together?", "what's the full impact of adopting X?"
- **Serves** a structured knowledge base to humans (web UI) and LLMs
  (MCP server with 9 query tools)

The system does not say "here is how Linux implements X." It says "this
source discusses a design pattern where X is handled by separating policy
from mechanism, using Y invariant, with tradeoff Z."

## Architecture

Four apps + one shared library, all Python:

| Component | Type | Purpose |
|-----------|------|---------|
| `know_kernel.graph` | Shared library | SQLite-backed graph engine, admissibility rules, query layer |
| `know_kernel.ingest` | Batch service | Document parsing, license scanning, LLM extraction |
| `know_kernel.web` | Server | FastAPI + Jinja2/HTMX human-facing views |
| `know_kernel.export` | CLI utility | Snapshot exporter -- contamination gate for LLM path |
| `know_kernel.mcp_server` | Container service | MCP server for LLM clients (Class B-only, 9 tools) |

See [docs/architecture.md](docs/architecture.md) for the full design.

## Graph shape

The knowledge graph captures **what mechanisms exist**, **how they relate**,
**what must hold**, **what breaks**, **how things compose**, and **how to
optimize**.

```
Subsystem
  ^ belongs-to
Concept <-- governed-by -- KernelInvariant
  |                            ^ triggered-by
  |-- refines --> Concept    FailureMode
  |-- contradicts -> Concept
  |-- prerequisite -> Concept
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

### Node kinds (14)

| Kind | Purpose | Class |
|------|---------|-------|
| Source | Document, repo, paper, mailing list thread | A |
| Evidence | Specific excerpt/code fragment from a source | A |
| Advisory | License/contamination metadata | A |
| Concept | Abstract kernel design mechanism | B |
| Subsystem | Kernel domain (scheduler, MM, IPC, etc.) | B |
| Proposal | LLM-generated design suggestion | B |
| KernelInvariant | Rule that must hold for correctness | B |
| FailureMode | What breaks when an invariant is violated | B |
| InteractionProtocol | Cross-concept composition constraint | B |
| PerformanceProfile | Quantitative bounds per concept per metric | B |
| CompatibilityAssessment | Synergy analysis between concept pairs | B |
| OptimizationGoal | Measurable objective (minimize latency, etc.) | B |
| UseCaseScenario | Workload pattern (cpu-bound, real-time, etc.) | B |
| ComparativeAnalysis | Head-to-head comparison on a dimension | B |

### Edge kinds (18)

| Edge | From | To | Purpose |
|------|------|----|---------|
| belongs-to | Concept/KernelInvariant | Subsystem | Domain classification |
| extracted-from | (7 kinds) | Evidence | Provenance chain |
| sourced-from | Evidence | Source | Origin tracking |
| alternative-to | Concept | Concept | Competing approaches |
| refines | Concept | Concept | Evolutionary improvement |
| contradicts | Concept | Concept | Conflicting claims (symmetric) |
| prerequisite | Concept | Concept | Dependency |
| supersedes | Concept | Concept | Replaces (acyclic) |
| assessed-by | Source | Advisory | License assessment |
| grounded-in | Proposal | Concept | Design provenance |
| governed-by | KernelInvariant | Concept | Invariant governs mechanism |
| triggered-by | FailureMode | KernelInvariant | Violation consequence |
| constrains-composition | InteractionProtocol | Concept | Composition rule |
| profiled-by | PerformanceProfile | Concept | Performance data |
| assesses-compatibility | CompatibilityAssessment | Concept | Synergy analysis |
| contributes-to | Concept | OptimizationGoal | Goal contribution |
| suited-for | Concept | UseCaseScenario | Workload fitness |
| compares | ComparativeAnalysis | Concept | Head-to-head comparison |

## Query layer

Six analytical query functions in the graph engine:

| Function | Purpose |
|----------|---------|
| `subgraph_around(node_id, depth)` | Multi-hop BFS traversal (depth bounded) |
| `query_edges_by_attrs(kind, **filters)` | Filter edges by JSON attr values |
| `compare_neighborhoods(id_a, id_b)` | Symmetric diff of two neighborhoods |
| `match_scenarios(workload_type)` | Find scenarios + suited concepts ranked by fitness |
| `transitive_impact(concept_id)` | Full impact surface: invariants, failures, protocols, profiles, goals, compatibilities, comparatives, scenarios |
| `ranked_recommendations(goal_id)` | Concepts ranked by contribution + impact |

## MCP tools

The MCP server exposes 9 read-only tools to LLM clients:

| Tool | Purpose |
|------|---------|
| `search_concepts(query)` | Search all Class B kinds by keyword |
| `get_concept(id)` | Single node with edges |
| `list_subsystems()` | All subsystem nodes |
| `get_subsystem_concepts(subsystem_id)` | Concepts in a subsystem |
| `get_impact_surface(concept_id)` | Full impact surface for a concept |
| `find_concepts_for_goal(goal_name)` | Ranked concepts for an optimization goal |
| `compare_concepts(id_a, id_b)` | Neighborhood diff + comparative analyses |
| `match_workload(workload_type)` | Scenarios + suited concepts |
| `explore_subgraph(node_id, depth)` | Neighborhood traversal (depth capped at 3) |

## The contamination firewall

The boundary is between **humans and LLMs**, not between networks.

- Humans see everything (Class A + B) -- legally established that reading
  GPL code doesn't contaminate kernel contributions
- LLMs get only Class B (clean abstractions) -- an LLM that saw licensed
  implementation details creates an unprovable contamination question

The **snapshot exporter** is the single enforcement point. It filters
Class A content out of the master DB, producing a Class B-only snapshot
that the MCP server ships with.

## Deployment

```
Internet side                 Air-gapped network
+--------------+               +---------------+
|  Ingestion   |--snapshot-->  |  Web API      | (humans)
|  service     |               |               |
|  (master DB) |               |  Dev containers|
+--------------+               |  +- MCP server| (LLM via opencode)
                               |  +- B-only DB |
                               |  +- tooling   |
                               +---------------+
```

## LLM reasoning chain

The complete reasoning chain when an LLM uses the knowledge graph:

```
Question ("design a subsystem using RCU + slab allocation")
  -> Query relevant Concepts              (what mechanisms exist)
  -> Follow relationship edges            (how they relate statically)
  -> Query KernelInvariants               (what must hold per mechanism)
  -> Query FailureModes                   (what happens if rules break)
  -> Query InteractionProtocols           (how mechanisms must coordinate)
  -> Query PerformanceProfiles            (quantitative bounds)
  -> Query CompatibilityAssessments       (do they compose well?)
  -> transitive_impact() per concept      (full impact surface)
  -> ranked_recommendations() for goal    (best candidates)
  -> Generate design with:
      uses: [Concepts]
      preserves: [safety invariants -- non-negotiable]
      benchmarks: [performance profiles -- measure after]
      coordinates: [interaction protocols -- composition rules]
      risk-accepts: [failure modes with local blast + self-healing]
```

## CLI entry points

```
kk-ingest   # Run the ingestion pipeline
kk-web      # Start the web API server
kk-export   # Export a Class B-only snapshot
kk-mcp      # Start the MCP server
```

## Development

Requires Python 3.11+.

```bash
pip install -e ".[dev]"
pytest
```

326 tests, zero failures.

## License

Proprietary.
