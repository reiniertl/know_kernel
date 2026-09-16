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
- **Serves** a structured knowledge base to humans through the web UI

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

## Class A: papers in, no code out

know_kernel is a **Class A** system. Papers are selected for future kernel
work, and nothing travels outward through an LLM-facing path.

There used to be an outward path: a snapshot exporter filtered Class A content
out of the master database to produce a Class B-only snapshot, and an MCP
server shipped that snapshot to LLM clients. Both were retired under decision
D-14, together with the contamination firewall they enforced. **The system no
longer makes that guarantee, because it no longer has the path that needed
it.** Do not read the Class A / Class B split as a live export control; it is
now a provenance distinction only, recorded on the `artifact_class` attribute
so a node's origin stays legible.

What replaces it is registration rather than filtering: every artifact derived
from a paper, by model or by human, stays registered to that paper, so the
graph can be clustered and audited against its sources. The boundary itself is
specified by `INV-KK-NO-OUTWARD-LLM-PATH` in the spec graph rather than by this
paragraph.

Humans continue to see everything. That was never the contested half: it is
legally established that reading GPL code does not contaminate kernel
contributions.

## Deployment

```
+--------------+
|  Ingestion   |
|  service     |
|  (master DB) |
+------+-------+
       |
+------v-------+
|  Web API     | (humans, behind the auth gate)
+--------------+

No outward LLM path: the snapshot export and the MCP server it fed were
retired under D-14.
```

## Reasoning chain

The query chain the graph supports, end to end. The functions named here are
live and reachable from the web layer; the chain is written out because it is
the order the graph is designed to be asked in, not because anything outside
the system consumes it:

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

## Users and login

The web application is behind a login. The gate app (`authgate.app:app`) owns
`/login`, `/logout` and `/admin/users`, and mounts the know_kernel app beneath
it at `/`, so no page is reachable without a session.

Credentials live in their own SQLite file, `data/auth.db`, which is entirely
separate from the knowledge graph in `data/master.db`. The two share no tables
and no connection.

### Bootstrap the first admin

There is no self-registration. The first account is created from a shell:

```bash
kk-useradd --admin reinier    # prompts for the password twice
./start.sh                    # or start.bat on Windows
```

Every user created this way is also added to the reviewer roster under the
same name, so a logged-in person can submit reviews immediately. Later users
can be added from `/admin/users` by any admin, or with `kk-useradd`.

```
kk-useradd [--admin] <name>   # create a user (prompts for the password)
kk-userlist                   # list users, roles, active state
kk-passwd <name>              # change a password
```

### Environment

| Variable | Default | Purpose |
|---|---|---|
| `KNOW_KERNEL_DB` | `data/master.db` | The knowledge graph |
| `KNOW_KERNEL_AUTH_DB` | `data/auth.db` | Users, sessions, remember-me tokens |

### Sessions

A session lasts 24 hours and slides forward on every request. Ticking
"Remember me on this device" additionally stores a 30-day rotating token, so an
expired session is silently renewed and the browser appears to stay logged in.
Sessions are stored server-side, so restarting the server — including
`--reload` — does not log anyone out, and logging out genuinely revokes.

### Do not start the inner app directly

> **Warning:** `uvicorn web.app:app` serves the entire knowledge application
> with **no authentication at all**. The know_kernel app is mounted behind the
> gate and cannot defend itself; the gate is the only thing enforcing access.
> Always start `authgate.app:app` — via `./start.sh`, `start.bat`, or `kk-web`.

## CLI entry points

```
kk-ingest    # Run the ingestion pipeline
kk-web       # Start the web API server behind the auth gate
kk-useradd   # Create a login user (and its reviewer roster entry)
kk-userlist  # List login users
kk-passwd    # Change a user's password
```

## Development

Requires Python 3.11+.

```bash
pip install -e ".[dev]"
pytest
```

1,466 tests, zero failures.

## License

Proprietary.
