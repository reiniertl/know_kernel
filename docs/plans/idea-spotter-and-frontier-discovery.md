# Plan: Idea Spotter & Frontier Discovery Engine

**Created:** 2026-06-26
**Status:** Draft -- root plan for next development cycle
**Scope:** Schema extensions, feed ingestion, claim extraction, scoring engine, idea feed UX
**Prerequisite:** Current Knowledge Layer (14 node kinds, 19 edge kinds) is complete and stable

---

## Vision

Transform know_kernel from a static kernel knowledge repository into a
**research-navigation system** that answers:

> "Given everything we know, what should kernel developers investigate next?"

The system becomes an **idea spotter** (surface interesting signals from live
feeds) and an **inductive idea generator** (infer high-impact opportunities
from converging evidence in the knowledge graph).

### Showcase Use-Case: Linux Kernel Idea Feed

A continuously updated feed that ingests:
- LWN.net weekly kernel coverage (RSS)
- HackerNews kernel/linux stories (API)
- LKML discussion summaries (RSS/scrape)
- Linux Plumbers Conference schedules and session notes
- Phoronix kernel benchmarks and news

Each feed item is processed through a claim-extraction pipeline, linked to
existing Concepts in the knowledge graph, scored by heat/pain/leverage, and
surfaced as ranked "ideas" to both humans (web UI) and LLMs (MCP tools).

### What makes this different from a news aggregator

A news aggregator shows you articles. This system shows you **convergence**.

Three different HN posts about "TLB shootdowns", "page table overhead",
and "NUMA address translation" are separate articles in a feed. In this
system, all three link to the same Concept nodes (Virtual Memory, Page
Tables, NUMA) and collectively raise the heat score of those areas. The
system spots that independent sources are converging on the same underlying
mechanism -- a signal no single source reveals.

---

## Architecture: Four Layers

```
Layer 1: Knowledge (DONE)
    Concept, Subsystem, KernelInvariant, FailureMode,
    InteractionProtocol, PerformanceProfile, CompatibilityAssessment,
    OptimizationGoal, UseCaseScenario, ComparativeAnalysis, Kernel

Layer 2: Evidence (NEW -- this plan)
    Problem, Observation, Discussion, Benchmark, Rejection
    + revived Proposal (with grounded-in edge)

Layer 3: Metrics (NEW -- this plan)
    Timestamps on all nodes/edges
    Heat score, Pain score, Impact score, Leverage score

Layer 4: Inference (NEW -- this plan)
    Trend, Opportunity, FrontierScore
    Inferred from graph topology, not extracted from text
```

Layer 1 is the **semantic coordinate system** -- stable concepts that change
over years or decades. Layers 2-3 are **telemetry** -- evidence and metrics
that change weekly. Layer 4 is **inference** -- opportunities that emerge
from the interaction of many observations attached to the same semantic
structure.

---

## Current State Assessment

### What exists (Layer 1 -- complete)

| Component | Status | Detail |
|-----------|--------|--------|
| Graph engine | Complete | 14 node kinds, 19 edge kinds, CRUD, 6 query functions |
| Ingestion pipeline | Complete | Parser (txt/pdf), scanner, LLM extractor, session gate |
| Class B export | Complete | Snapshot exporter with contamination validation |
| Web UI | Complete | Dashboard, list, detail, impact, health, viz, search, code examples |
| MCP server | Complete | 11 tools, Class B-only enforcement |
| Optimization layer | Complete | Goals, scenarios, kernels, contribution/fitness scoring |

### What is missing (7 gaps from audit)

| ID | Gap | Severity | Blocks |
|----|-----|----------|--------|
| F1 | Proposal node kind is dead code (no creation fn, no grounded-in edge) | MEDIUM | Frontier layer |
| F2 | No source-date timestamps on evidence nodes | **HIGH** | All scoring |
| F3 | No live feed ingestion (pipeline reads local files only) | **HIGH** | Showcase |
| F4 | Missing frontier node kinds (Problem, Observation, Discussion, ...) | **HIGH** | Evidence layer |
| F5 | No scoring infrastructure (ranked_recommendations only ranks by contribution) | MEDIUM | Idea ranking |
| F6 | Extraction prompt is concept-only, cannot extract claims/problems | MEDIUM | Feed processing |
| F7 | Firewall policy has no "discourse" source type for factual feeds | LOW | Feed ingestion |

---

## Phase 1: Temporal Foundation -- Source-Date Timestamps

**Goal:** Add source-date timestamps to evidence nodes so temporal queries and
scoring windows can operate on when things actually happened in the real world.

**Why first:** Every scoring formula (Heat, Pain, Frontier) aggregates over time
windows. Without knowing WHEN an observation was made, a problem was reported, or
a discussion occurred, none of the subsequent phases can compute anything meaningful.

### Design principle: source date, not ingestion date

Timestamps must reflect **when the knowledge event occurred**, not when our pipeline
happened to consume it:

| Source type | Timestamp meaning | Where to find it |
|-------------|-------------------|------------------|
| Paper | Publication date | PDF metadata, arXiv API, DOI resolver |
| LKML message | Message Date header | RSS `<pubDate>`, email headers |
| HackerNews post | Post creation time | HN API `time` field (Unix epoch) |
| LWN article | Article publication date | RSS `<pubDate>`, page metadata |
| Benchmark report | Date test was run | Extracted from content or publication date |
| Conference talk | Conference date | Schedule page, event metadata |
| Git commit | Commit authorship date | `git log --format=%aI` |

A Concept node like "RCU" has no meaningful timestamp -- it is a timeless
mechanism. Its temporal story emerges from the evidence attached to it: an
Observation from a 2024 paper, a Discussion from a June 2026 LKML thread, a
Benchmark from last week. Stamping the Concept itself would create meaningless
data.

### What gets timestamped

**Evidence-layer nodes only** (Phase 3 kinds): Problem, Observation, Discussion,
Benchmark, Rejection, Proposal. Each carries a required `source_date` attribute.

**Source nodes** also carry a `published_date` attribute (already partially
present via metadata; this makes it required for discourse sources).

**Knowledge-layer nodes do NOT get timestamps:** Concept, Subsystem,
KernelInvariant, FailureMode, InteractionProtocol, PerformanceProfile,
CompatibilityAssessment, OptimizationGoal, UseCaseScenario, ComparativeAnalysis,
Kernel.

### Required attribute additions

```python
# Added to REQUIRED_ATTRS for ALL evidence-layer node kinds (Phase 3):
"source_date"     # ISO-8601 date from the original source (e.g., "2026-06-15")

# Added to Source node (for discourse sources):
# "published_date" becomes a required attr when source_type == "discourse"
```

### Engine changes

- New query: `evidence_in_window(conn, kind, since, until)` -- return evidence
  nodes whose `source_date` falls in a time range.
- New query: `evidence_count_for_concept(conn, concept_id, edge_kind, since, until)`
  -- count evidence nodes linked to a concept via a specific edge kind, filtered
  by `source_date` window.
- These queries power all scoring functions in Phase 6.

### Reconstructing concept timelines

The timeline of a Concept is built by querying all evidence linked to it,
ordered by `source_date`:

```python
def concept_timeline(conn, concept_id) -> list[dict]:
    """Return all evidence nodes linked to this concept, ordered by source_date."""
    evidence_edges = ("identifies-problem", "observes", "discusses",
                      "benchmarks", "rejected-for", "grounded-in")
    placeholders = ",".join("?" for _ in evidence_edges)
    rows = conn.execute(
        f"""SELECT n.id, n.kind, n.attrs, json_extract(n.attrs, '$.source_date') as sd
            FROM nodes n
            JOIN edges e ON (e.source_id = n.id AND e.target_id = ?)
            WHERE e.kind IN ({placeholders})
            ORDER BY sd ASC""",
        (concept_id, *evidence_edges),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]
```

This lets us answer: "Show me the history of RCU -- when were problems reported,
when were proposals made, when did discussions happen?"

### Tasks

| Task | File | Detail |
|------|------|--------|
| T1.1 | `src/graph/engine.py` | Add `evidence_in_window()` query |
| T1.2 | `src/graph/engine.py` | Add `evidence_count_for_concept()` query |
| T1.3 | `src/graph/engine.py` | Add `concept_timeline()` query |
| T1.4 | `tests/` | Tests for window queries with various date ranges |
| T1.5 | `tests/` | Tests for timeline ordering and edge cases (missing dates) |

**Note:** The `source_date` attribute itself is defined in Phase 3 (evidence node
kinds) and populated in Phase 4 (feed ingestion extracts dates from sources).
This phase defines the query infrastructure that consumes those dates.

**Effort:** Small (1 session)

---

## Phase 2: Discourse Source Policy

**Goal:** Allow the contamination firewall to handle factual discourse sources
(news articles, mailing list discussions, forum posts) without the restrictions
designed for copyrightable source code.

**Why:** Feed items from LWN, LKML, and HackerNews are factual discussions. The
Class A/B separation was designed to prevent verbatim copying of licensed code.
Factual discourse needs a lighter-touch policy that still tracks provenance but
doesn't block ingestion.

### Design

Extend `Source` node's `source_type` attribute to include `"discourse"` alongside
existing values (`"paper"`, `"code"`, `"documentation"`). The scanner assigns
`artifact_class = "A"` to discourse sources (they still have provenance) but the
extractor applies relaxed anti-verbatim rules -- factual claims can be stated
directly; only creative expression needs rephrasing.

### Tasks

| Task | File | Detail |
|------|------|--------|
| T2.1 | `src/ingest/scanner.py` | Add `"discourse"` to valid source_type values |
| T2.2 | `src/ingest/scanner.py` | Discourse sources get `contamination_level = "L1"` (factual, low risk) |
| T2.3 | `src/ingest/extractor.py` | Add conditional rules in extraction prompt for discourse sources |
| T2.4 | `tests/` | Tests for discourse source classification and extraction |

**Effort:** Small (1 session)

---

## Phase 3: Evidence Layer -- New Node Kinds

**Goal:** Introduce the node kinds that represent time-varying evidence: Problems,
Observations, Discussions, Benchmarks, Rejections, and revive the dead Proposal kind.

**Why:** The current graph only stores timeless mechanisms. To spot ideas, we need
to record what people are saying about those mechanisms right now -- what problems
they're hitting, what they're observing, what they're proposing, and what's being
rejected.

### New node kinds

```python
# Batch 1: Evidence nodes (extracted from feeds)
"Problem"       # An unsolved issue in kernel development
"Observation"   # An empirical finding or claim from a source
"Discussion"    # A notable debate or thread (LKML, conference, etc.)
"Benchmark"     # A quantitative measurement or regression report
"Rejection"     # An idea that was proposed and rejected (with reasons)
"Vulnerability" # A security vulnerability (CVE, kernel advisory, etc.)
"Fix"           # A bug fix or patch that resolves a Problem or Vulnerability

# Batch 2: already in NODE_KINDS but non-functional
"Proposal"      # An idea proposed for kernel development (revived)
```

### Required attributes per kind

```python
REQUIRED_ATTRS["Problem"] = (
    "title",            # Short problem statement (e.g., "Excessive TLB shootdowns")
    "description",      # Detailed explanation of the problem
    "severity",         # "critical" | "high" | "medium" | "low"
    "status",           # "open" | "partially-addressed" | "resolved"
    "source_date",      # ISO-8601 date from the original source (e.g., "2026-06-15")
    "artifact_class",   # Always "B" -- problems are abstract
)

REQUIRED_ATTRS["Observation"] = (
    "claim",            # The factual assertion (e.g., "NUMA locality affects throughput")
    "confidence",       # 0.0 - 1.0 (how well-supported is this claim)
    "source_date",      # ISO-8601 date from the original source
    "artifact_class",
)

REQUIRED_ATTRS["Discussion"] = (
    "title",            # Thread subject or talk title
    "forum",            # "lkml" | "lwn" | "hackernews" | "plumbers" | "phoronix" | "other"
    "participant_count",# Number of distinct participants (0 if unknown)
    "source_date",      # ISO-8601 date from the original source
    "artifact_class",
)

REQUIRED_ATTRS["Benchmark"] = (
    "metric",           # What was measured (e.g., "throughput", "latency", "memory")
    "result_summary",   # One-line result (e.g., "17% improvement on 128 cores")
    "conditions",       # Under what hardware/workload
    "source_date",      # ISO-8601 date when benchmark was run or published
    "artifact_class",
)

REQUIRED_ATTRS["Rejection"] = (
    "proposal_title",   # What was rejected
    "reason",           # Why it was rejected
    "rejector",         # Who rejected it (maintainer name or "consensus")
    "source_date",      # ISO-8601 date of the rejection
    "artifact_class",
)

REQUIRED_ATTRS["Proposal"] = (    # REVIVED -- currently has no REQUIRED_ATTRS
    "name",             # Short proposal name
    "description",      # What is being proposed
    "status",           # "draft" | "under-review" | "accepted" | "rejected" | "abandoned"
    "source_date",      # ISO-8601 date when proposal was made
    "artifact_class",
)

REQUIRED_ATTRS["Vulnerability"] = (
    "cve_id",           # CVE identifier (e.g., "CVE-2026-12345") or empty if no CVE assigned
    "title",            # Short vulnerability description
    "description",      # Detailed explanation of the vulnerability
    "severity",         # "critical" | "high" | "medium" | "low" (from CVSS or maintainer assessment)
    "cvss_score",       # CVSS score as string (e.g., "9.8") or empty if not scored
    "affected_versions",# Kernel version range (e.g., "5.15 - 6.10") or empty
    "status",           # "unfixed" | "fix-pending" | "fixed" | "mitigated"
    "source_date",      # ISO-8601 date of disclosure or advisory
    "artifact_class",
)

REQUIRED_ATTRS["Fix"] = (
    "title",            # Short description of what was fixed
    "commit_hash",      # Git commit SHA (e.g., "a1b2c3d4e5f6") or empty for non-git fixes
    "fix_type",         # "bugfix" | "security-fix" | "regression-fix" | "performance-fix"
    "source_date",      # ISO-8601 date of the commit or patch
    "artifact_class",
)
```

### New edge kinds

```python
# Evidence -> Knowledge links
"identifies-problem"     # Problem -> Concept (this concept has this problem)
"observes"               # Observation -> Concept (observation about this concept)
"discusses"              # Discussion -> Concept (discussion about this concept)
"benchmarks"             # Benchmark -> Concept (benchmark of this concept)
"rejected-for"           # Rejection -> Concept (rejected in context of this concept)
"grounded-in"            # Proposal -> Concept (proposal builds on this concept)

# Vulnerability -> Knowledge links
"exploits"               # Vulnerability -> Concept (this vuln exploits a weakness in this concept)
"affects-subsystem"      # Vulnerability -> Subsystem (directly affected subsystem)

# Fix -> links
"fixes"                  # Fix -> Problem | Vulnerability (this fix resolves this issue)
"patches"                # Fix -> Concept (this fix modifies this concept's implementation)

# Evidence -> Evidence links
"addresses"              # Proposal -> Problem (this proposal aims to solve this problem)
"contradicted-by"        # Observation -> Observation (conflicting observations)
"resulted-in"            # Discussion -> Proposal | Rejection (discussion outcome)
"motivated-by"           # Benchmark -> Problem (benchmark reveals problem)
```

### Edge valid pairs

```python
EDGE_VALID_PAIRS["identifies-problem"] = ("Problem", "Concept")
EDGE_VALID_PAIRS["observes"] = ("Observation", "Concept")
EDGE_VALID_PAIRS["discusses"] = ("Discussion", "Concept")
EDGE_VALID_PAIRS["benchmarks"] = ("Benchmark", "Concept")
EDGE_VALID_PAIRS["rejected-for"] = ("Rejection", "Concept")
EDGE_VALID_PAIRS["grounded-in"] = ("Proposal", "Concept")
EDGE_VALID_PAIRS["exploits"] = ("Vulnerability", "Concept")
EDGE_VALID_PAIRS["affects-subsystem"] = ("Vulnerability", "Subsystem")
EDGE_VALID_PAIRS["fixes"] = [("Fix", "Problem"), ("Fix", "Vulnerability")]
EDGE_VALID_PAIRS["patches"] = ("Fix", "Concept")
EDGE_VALID_PAIRS["addresses"] = ("Proposal", "Problem")
EDGE_VALID_PAIRS["contradicted-by"] = ("Observation", "Observation")
EDGE_VALID_PAIRS["resulted-in"] = [("Discussion", "Proposal"), ("Discussion", "Rejection")]
EDGE_VALID_PAIRS["motivated-by"] = ("Benchmark", "Problem")
```

### Tasks

| Task | File | Detail |
|------|------|--------|
| T3.1 | `src/graph/schema.py` | Add 8 new node kinds to NODE_KINDS (Problem, Observation, Discussion, Benchmark, Rejection, Vulnerability, Fix, + Proposal revival) |
| T3.2 | `src/graph/schema.py` | Add REQUIRED_ATTRS for all 8 kinds |
| T3.3 | `src/graph/schema.py` | Add 14 new edge kinds to EDGE_KINDS |
| T3.4 | `src/graph/schema.py` | Add EDGE_VALID_PAIRS for all new edges |
| T3.5 | `src/graph/engine.py` | Update `_ACYCLIC_EDGE_KINDS` if any new edges should be acyclic |
| T3.6 | `src/web/routes.py` | Add _DISPLAY_FIELDS entries for new node kinds |
| T3.7 | `src/export/exporter.py` | Add new Class B kinds to ALLOWED_KINDS |
| T3.8 | `tests/` | Admissibility tests for all new node/edge combinations |
| T3.9 | `tests/` | Edge constraint tests (valid pairs, missing attrs rejection) |

**Effort:** Large (2-3 sessions)

---

## Phase 4: Feed Ingestion Pipeline

**Goal:** Build a polling pipeline that fetches content from live feeds (RSS, APIs,
web scraping) and creates Source + Evidence nodes for each item.

**Why:** This is the showcase enabler. Without live feeds, the system can only process
manually downloaded documents.

### Feed sources for MVP

| Source | Type | URL / API | Frequency | Content |
|--------|------|-----------|-----------|---------|
| LWN Kernel Page | RSS | `https://lwn.net/headlines/Features` | Weekly | Kernel articles |
| HackerNews | API | `https://hacker-news.firebaseio.com/v0/` | Hourly | Top stories filtered for linux/kernel |
| LKML | RSS | `https://lkml.org/lkml/rss` | Daily | Mailing list threads |
| Phoronix | RSS | `https://www.phoronix.com/rss.php` | Daily | Benchmarks and kernel news |
| Linux Plumbers | Scrape | `https://lpc.events/` | Monthly | Conference sessions and abstracts |
| **Kernel Git (mainline)** | Git | `git.kernel.org/torvalds/linux.git` | Daily | Commits, merge messages, changelogs |
| **Kernel Git (stable)** | Git | `git.kernel.org/stable/linux.git` | Daily | Stable backports, regression fixes |
| **linux-next** | Git | `git.kernel.org/linux-next/linux-next.git` | Daily | Staging tree -- what's coming next |
| **CVE (kernel.org)** | API | `https://www.cve.org/api/` + kernel.org advisories | Daily | Kernel CVEs with CVSS, affected versions |
| **NVD** | API | `https://services.nvd.nist.gov/rest/json/cves/2.0` | Daily | NIST vulnerability database (kernel CPE filter) |

### Repository tracking strategy

Git repositories are the most authoritative signal source. Unlike news and
discussions, commits are ground truth: code was actually changed, bugs were
actually fixed, vulnerabilities were actually patched.

#### What to extract from commits

Not every commit is worth ingesting. Focus on high-signal commits:

```
Merge commits        → New features landing (merge window summary)
Revert commits       → Something broke -- a regression signal
Fixes: tag commits   → Bug fixes with explicit linkage to the broken commit
CVE commits          → Security fixes (highest priority)
Cc: stable@ commits  → Issues serious enough for stable backport
```

**Commit message parsing:**

Linux kernel commits follow conventions that are machine-parseable:

```
Fixes: a1b2c3d4e5f6 ("original commit subject")
Cc: stable@vger.kernel.org
Reviewed-by: Name <email>
Signed-off-by: Name <email>
Link: https://lore.kernel.org/...
```

The `Fixes:` tag directly links a fix to the commit that introduced the bug.
The `Cc: stable` tag indicates severity (worth backporting). These are
structured signals, not LLM extraction -- parse them deterministically.

#### Commit -> Graph flow

```
git log --since="30 days ago" --format=...
    |
    v
Filter: Fixes: tag? Revert? CVE mention? Cc: stable?
    |
    v
Source node (source_type="commit", url=commit_url)
    |
    v
Fix node (commit_hash, fix_type, source_date=author_date)
    |
    patches edge -> Concept (matched by subsystem path or content)
    fixes edge -> Problem | Vulnerability (if CVE or Fixes: tag present)
```

**The source_date for a commit is the author date (`git log --format=%aI`),
not the committer date** -- the author date reflects when the fix was written,
which may predate its merge by days or weeks.

#### Subsystem matching from file paths

Kernel commits touch specific files. The file path tells you which subsystem
is affected:

```
mm/*              → Memory Management
kernel/sched/*    → Scheduler
kernel/rcu/*      → RCU
fs/*              → VFS / Filesystems
net/*             → Networking
drivers/*         → Device Drivers
security/*        → Security
block/*           → Block I/O
arch/*            → Architecture
```

This deterministic mapping (no LLM needed) links Fix nodes to the correct
Subsystem and Concept nodes via the existing `belongs-to` edges.

### Vulnerability feed strategy

Vulnerabilities are the highest-value evidence type because:

1. **High urgency** -- they demand immediate attention
2. **Well-documented** -- CVEs have structured severity, affected versions, CWE class
3. **Cross-module implications** -- a vuln in Module A immediately matters for
   Modules X, Y if the knowledge graph shows coupling through `prerequisite`,
   `constrains-composition`, or `governed-by` edges
4. **High turnaround** -- fixes typically land within days/weeks, creating a
   complete Problem → Fix lifecycle observable in real time

#### CVE -> Graph flow

```
CVE API response (cve_id, description, CVSS, CWE, affected_versions)
    |
    v
Source node (source_type="cve", url=cve_url)
    |
    v
Vulnerability node (cve_id, severity from CVSS, affected_versions)
    |
    exploits edge -> Concept (matched by CWE class + description)
    affects-subsystem edge -> Subsystem (matched by affected component)
    |
    v
Impact propagation (see Phase 6 scoring):
    Concept A has vulnerability
    Concept A --prerequisite--> Concept B
    Concept A --constrains-composition--> Concept C
    → Concepts B, C flagged for review
```

#### Matching CVEs to the knowledge graph

CVEs include a CWE classification (e.g., CWE-416 = Use After Free) and
typically name the affected subsystem or file path. Matching strategy:

1. **Path-based:** If the CVE or fix commit names a file path, use subsystem
   mapping (same as commit tracking)
2. **CWE-based:** Map CWE classes to Concept patterns:
   - CWE-416 (Use After Free) → RCU, Slab Allocator, Reference Counting
   - CWE-362 (Race Condition) → Spinlocks, Mutexes, RCU
   - CWE-787 (Out-of-bounds Write) → Page Tables, Buffer Management
   - CWE-476 (NULL Pointer Deref) → VFS, Driver Model
3. **LLM-assisted:** For CVEs that don't match deterministically, use the
   claim extractor with the concept name list

### Design

New module `src/ingest/feed.py`:

```python
@dataclass
class FeedConfig:
    name: str                    # "lwn", "hackernews", "lkml", "phoronix", "plumbers"
    feed_type: str               # "rss" | "api" | "scrape"
    url: str                     # Feed URL or API base
    poll_interval_seconds: int   # How often to poll
    kernel_filter: str | None    # Regex to filter relevant items (for HN)

@dataclass
class FeedItem:
    title: str
    url: str
    content: str                 # Article text or thread summary
    published: str               # ISO-8601 date from the SOURCE (publication date,
                                 # message date, commit date -- NOT ingestion time)
    source_feed: str             # Which feed this came from
    metadata: dict               # Feed-specific extras (score, comments, author, etc.)

class FeedPoller:
    def __init__(self, config: FeedConfig):
        ...

    def poll(self) -> list[FeedItem]:
        """Fetch new items since last poll. Deduplicates by URL."""
        ...

    def ingest_item(self, conn, item: FeedItem) -> str:
        """Create Source + Evidence nodes for a feed item.
        Returns the Source node ID."""
        ...
```

### Feed -> Graph flow

```
FeedPoller.poll()
    |
    v
FeedItem (title, url, content, published)
    |
    v
Source node (source_type="discourse", url=item.url)
    |
    v
Evidence node (description=item.content summary, artifact_class="A")
    |
    sourced-from edge
    |
    v
ClaimExtractor (Phase 5)
    |
    v
Problem / Observation / Discussion / Benchmark / Rejection nodes
    |
    identifies-problem / observes / discusses / benchmarks / rejected-for edges
    |
    v
Existing Concept nodes (linked by LLM concept-matching)
```

### HackerNews-specific logic

The HN API returns story IDs. For each top story:
1. Fetch story metadata (`/v0/item/{id}.json`)
2. Filter by title regex: `/(linux|kernel|scheduler|memory|io_uring|bpf|ebpf|rcu|numa|folio|mm|vfs|filesystem|networking|net|driver|module|kconfig|systemd|cgroup|namespace|seccomp|landlock)/i`
3. Fetch linked article URL content (readability extraction)
4. Create FeedItem with article content + HN metadata (score, comments)

### Deduplication

Each feed source tracks `last_fetched_url` and `last_fetched_timestamp` in a
local state file (`data/feed_state.json`). On each poll, skip items already seen
by URL. Additionally, before creating a Source node, check if a Source with the
same URL already exists in the database.

### CLI entry point

```
kk-feed poll --source lwn          # Poll one source
kk-feed poll --all                 # Poll all configured sources
kk-feed poll --all --extract       # Poll + run claim extraction on new items
kk-feed status                     # Show last poll time per source
```

### Tasks

| Task | File | Detail |
|------|------|--------|
| T4.1 | `src/ingest/feed.py` | FeedConfig, FeedItem dataclasses |
| T4.2 | `src/ingest/feed.py` | FeedPoller base class with poll() and ingest_item() |
| T4.3 | `src/ingest/feed.py` | RSS poller implementation (feedparser library) |
| T4.4 | `src/ingest/feed.py` | HackerNews API poller with kernel-topic filter |
| T4.5 | `src/ingest/feed.py` | Deduplication logic (URL-based + DB check) |
| T4.6 | `src/ingest/feed.py` | Feed state persistence (data/feed_state.json) |
| T4.7 | `src/ingest/cli_feed.py` | CLI entry point (kk-feed command) |
| T4.8 | `pyproject.toml` | Add kk-feed entry point, feedparser + httpx dependencies |
| T4.9 | `data/feed_configs.json` | Default feed configurations for MVP sources |
| T4.10 | `tests/` | Mock-based tests for RSS parsing, HN API filtering, dedup |
| T4.11 | `src/ingest/repo_tracker.py` | Git log parser for kernel repos (Fixes: tag, Cc: stable, Revert, CVE) |
| T4.12 | `src/ingest/repo_tracker.py` | File-path-to-subsystem deterministic mapper |
| T4.13 | `src/ingest/repo_tracker.py` | Commit -> Fix node + patches/fixes edges creation |
| T4.14 | `src/ingest/vuln_tracker.py` | CVE API poller (cve.org + NVD, filtered by kernel CPE) |
| T4.15 | `src/ingest/vuln_tracker.py` | CVE -> Vulnerability node + exploits/affects-subsystem edges |
| T4.16 | `src/ingest/vuln_tracker.py` | CWE-to-Concept mapping table |
| T4.17 | `src/ingest/cli_feed.py` | Add `kk-feed poll --source kernel-git` and `--source cve` commands |
| T4.18 | `tests/` | Tests for commit message parsing (Fixes: tag, Cc: stable, Revert detection) |
| T4.19 | `tests/` | Tests for CVE ingestion, CWE mapping, subsystem matching |

**Effort:** Large (2-3 sessions)

---

## Phase 5: Claim Extraction Prompt

**Goal:** Build a second LLM extraction prompt optimized for extracting claims,
problems, proposals, and observations from discourse sources (news, discussions,
meeting minutes) rather than from technical documentation.

**Why:** The existing `EXTRACTION_SYSTEM_PROMPT` extracts abstract mechanisms from
kernel documentation. Feed items contain a different kind of knowledge: opinions,
debates, benchmark results, proposed changes, and rejected ideas. A separate
extraction pass with a different prompt produces better results than trying to
force-fit discourse content into the concept extraction schema.

### New prompt: CLAIM_EXTRACTION_PROMPT

```python
CLAIM_EXTRACTION_PROMPT = """\
You are a claim extraction agent for a kernel research intelligence system.

Your task: given a news article, mailing list thread, conference abstract,
or benchmark report about Linux kernel development, extract CLAIMS,
PROBLEMS, PROPOSALS, OBSERVATIONS, and REJECTIONS.

You are NOT extracting abstract concepts or design patterns. You are
extracting what people are SAYING, PROPOSING, OBSERVING, and DEBATING
about the kernel RIGHT NOW.

For each item, also identify which existing kernel CONCEPTS it relates to.
You will be given a list of known concept names to match against.

Return a JSON object with these arrays:

"problems": [
    {
        "title": "Short problem statement",
        "description": "What is going wrong or what is unsolved",
        "severity": "critical|high|medium|low",
        "related_concepts": ["concept-name-1", "concept-name-2"]
    }
]

"observations": [
    {
        "claim": "A factual assertion made in the source",
        "confidence": 0.0-1.0,
        "related_concepts": ["concept-name-1"]
    }
]

"proposals": [
    {
        "name": "Short proposal name",
        "description": "What is being proposed",
        "status": "draft|under-review|accepted|rejected|abandoned",
        "related_concepts": ["concept-name-1"],
        "addresses_problems": ["problem-title-1"]
    }
]

"benchmarks": [
    {
        "metric": "What was measured",
        "result_summary": "One-line result",
        "conditions": "Hardware/workload/config",
        "related_concepts": ["concept-name-1"]
    }
]

"rejections": [
    {
        "proposal_title": "What was rejected",
        "reason": "Why it was rejected",
        "rejector": "Who rejected it",
        "related_concepts": ["concept-name-1"]
    }
]

"discussion": {
    "title": "Thread/article title",
    "forum": "lkml|lwn|hackernews|plumbers|phoronix|other",
    "key_participants": ["name1", "name2"],
    "summary": "2-3 sentence summary of the discussion",
    "related_concepts": ["concept-name-1", "concept-name-2"]
}

IMPORTANT: Only extract what the source ACTUALLY SAYS. Do not hallucinate
claims, problems, or proposals that are not in the text. If the source
does not contain a particular category, return an empty array for it.\
"""
```

### Concept matching

Before calling the LLM, the system queries all existing Concept names from the
database and passes them as context:

```python
def build_claim_extraction_context(conn) -> str:
    concepts = conn.execute(
        "SELECT json_extract(attrs, '$.name') as name FROM nodes WHERE kind = 'Concept'"
    ).fetchall()
    names = [c["name"] for c in concepts if c["name"]]
    return "Known kernel concepts: " + ", ".join(sorted(names))
```

This allows the LLM to match extracted claims to existing concepts by name,
which the system then resolves to node IDs for edge creation.

### Post-extraction wiring

After extraction, for each item:
1. Create the appropriate node (Problem, Observation, etc.) with `artifact_class="B"`
   and `source_date` set to the feed item's publication date (from RSS `<pubDate>`,
   HN API `time` field, etc.) -- never the current ingestion time
2. For each `related_concepts` name, fuzzy-match against existing Concept nodes
3. Create the appropriate edge (identifies-problem, observes, discusses, etc.)
4. For Proposals that `addresses_problems`, create `addresses` edges
5. Create `extracted-from` edge back to Evidence node

### Tasks

| Task | File | Detail |
|------|------|--------|
| T5.1 | `src/ingest/claim_extractor.py` | New module with CLAIM_EXTRACTION_PROMPT |
| T5.2 | `src/ingest/claim_extractor.py` | `build_claim_extraction_context()` -- concept name list |
| T5.3 | `src/ingest/claim_extractor.py` | `extract_claims(conn, evidence_id, llm)` -- main extraction fn |
| T5.4 | `src/ingest/claim_extractor.py` | Concept name fuzzy matching (case-insensitive, prefix, Levenshtein) |
| T5.5 | `src/ingest/claim_extractor.py` | Post-extraction wiring (node creation + edge linking) |
| T5.6 | `src/ingest/cli_feed.py` | Wire `--extract` flag to claim extraction |
| T5.7 | `tests/` | Tests with mock LLM responses for each extraction category |
| T5.8 | `tests/` | Tests for concept name fuzzy matching edge cases |

**Effort:** Medium (2 sessions)

---

## Phase 6: Scoring Engine

**Goal:** Build a pluggable scoring system that computes Heat, Pain, Impact, Leverage,
and Frontier scores for concepts and problems based on graph topology and temporal
metrics.

**Why:** Scores are what transform the graph from a knowledge store into a decision
support system. Without scores, a human or LLM must manually traverse the graph to
find what matters. With scores, the system answers: "This area deserves attention."

### Score definitions

#### Heat Score (activity intensity)

Measures how much recent discussion and evidence a concept is attracting.

```python
def heat_score(conn, concept_id, window_days=30) -> float:
    """Count evidence nodes linked to this concept whose source_date
    falls within the time window. Uses source_date (when the event
    happened in the real world), NOT ingestion time."""
    since = (datetime.utcnow() - timedelta(days=window_days)).isoformat()[:10]
    edge_kinds = ("discusses", "observes", "benchmarks", "grounded-in")
    count = 0
    for ek in edge_kinds:
        count += evidence_count_for_concept(conn, concept_id, ek, since)
    return float(count)
```

**Interpretation:** Heat = 0 means nobody is talking about this. Heat = 20 means
this is a very active area.

#### Pain Score (suffering intensity)

Measures how many problems, failure modes, and vulnerabilities are connected to
a concept. Vulnerabilities are weighted most heavily because they represent
active security risk.

```python
def pain_score(conn, concept_id) -> float:
    """Count Problems + FailureModes + Vulnerabilities connected to this concept.
    Vulnerabilities are weighted 5x because they represent active security risk
    with immediate operational impact."""
    problems = count_edges(conn, concept_id, "identifies-problem", direction="incoming")
    failures = count_edges(conn, concept_id, "triggered-by", direction="incoming",
                           via="governed-by")  # FailureMode -> Invariant -> Concept
    regressions = count_edges(conn, concept_id, "motivated-by", direction="incoming",
                              via="benchmarks")  # Benchmark -> Problem -> Concept
    vulns = count_edges(conn, concept_id, "exploits", direction="incoming")
    # Weight by CVSS severity if available
    vuln_weighted = sum(
        _cvss_weight(v) for v in get_linked_vulns(conn, concept_id)
    )
    return float(problems * 2 + failures * 3 + regressions * 1 + vuln_weighted * 5)

def _cvss_weight(vuln: dict) -> float:
    """Map CVSS score to weight. Critical vulns dominate the pain score."""
    try:
        cvss = float(vuln.get("cvss_score", "0"))
    except ValueError:
        cvss = 0.0
    if cvss >= 9.0: return 4.0   # critical
    if cvss >= 7.0: return 3.0   # high
    if cvss >= 4.0: return 2.0   # medium
    return 1.0                    # low
```

**Interpretation:** Pain = 0 means this concept is working fine. Pain = 15 means
developers are struggling with it. Pain = 30+ with vulnerability contributions
means this concept has active security exposure.

#### Impact Score (blast radius)

Measures how many other concepts, subsystems, and workloads are affected.

```python
def impact_score(conn, concept_id) -> float:
    """Count distinct downstream nodes reachable via impact edges."""
    impact = transitive_impact(conn, concept_id)
    total = sum(len(v) for v in impact.values())
    return float(total)
```

**Interpretation:** Impact = 3 means localized. Impact = 25 means touching this
concept has system-wide consequences.

#### Leverage Score (problem-solving multiplier)

Measures how many problems a single concept improvement could address.

```python
def leverage_score(conn, concept_id) -> float:
    """Sum of (problem severity weight) for all problems linked to this concept."""
    severity_weights = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    problems = get_linked_problems(conn, concept_id)
    return sum(severity_weights.get(p["severity"], 1) for p in problems)
```

**Interpretation:** Leverage = 12 means improving this concept addresses
multiple high-severity problems.

#### Frontier Score (research opportunity)

Composite score identifying promising research directions.

```python
def frontier_score(conn, concept_id, window_days=90) -> float:
    """Composite: high heat + high pain + high leverage - solved confidence."""
    heat = heat_score(conn, concept_id, window_days)
    pain = pain_score(conn, concept_id)
    leverage = leverage_score(conn, concept_id)
    # Solved confidence: ratio of resolved to total problems
    problems = get_linked_problems(conn, concept_id)
    if problems:
        resolved = sum(1 for p in problems if p["status"] == "resolved")
        solved_confidence = resolved / len(problems)
    else:
        solved_confidence = 0.0
    return (heat * 0.3) + (pain * 0.3) + (leverage * 0.3) - (solved_confidence * 10)
```

**Interpretation:** Frontier > 10 means "smart people should spend time here."

#### Vulnerability Impact Propagation (cross-module alerting)

This is the highest-value scoring capability. When a vulnerability is discovered
in Concept A, the existing knowledge graph already knows which other concepts
depend on A, compose with A, or share invariants with A. This means the system
can immediately flag coupled concepts for review.

```python
def vulnerability_propagation(conn, vuln_id) -> dict:
    """Given a Vulnerability node, find all concepts at risk through coupling.

    Uses the existing knowledge graph edges to propagate risk:
    - prerequisite: if A requires B, and B has a vuln, A may be affected
    - constrains-composition: if A and B compose under a protocol,
      a vuln in A may violate that protocol
    - governed-by: if an invariant governs A, and A has a vuln,
      the invariant may be violated -- check all other concepts
      governed by the same invariant
    """
    # Step 1: Find directly exploited concepts
    direct = conn.execute(
        "SELECT target_id FROM edges WHERE source_id = ? AND kind = 'exploits'",
        (vuln_id,)
    ).fetchall()
    direct_ids = {r[0] for r in direct}

    # Step 2: For each directly exploited concept, find coupled concepts
    at_risk = {}
    for concept_id in direct_ids:
        # Concepts that require this concept (prerequisite)
        dependents = conn.execute(
            "SELECT source_id FROM edges WHERE target_id = ? AND kind = 'prerequisite'",
            (concept_id,)
        ).fetchall()

        # Concepts composed with this concept (constrains-composition)
        composed = conn.execute(
            "SELECT e2.target_id FROM edges e1 "
            "JOIN edges e2 ON e1.source_id = e2.source_id AND e2.kind = 'constrains-composition' "
            "WHERE e1.target_id = ? AND e1.kind = 'constrains-composition' AND e2.target_id != ?",
            (concept_id, concept_id)
        ).fetchall()

        # Concepts sharing invariants (governed-by -> same invariant)
        shared_invariant = conn.execute(
            "SELECT DISTINCT e2.target_id FROM edges e1 "
            "JOIN edges e2 ON e1.source_id = e2.source_id AND e2.kind = 'governed-by' "
            "WHERE e1.target_id = ? AND e1.kind = 'governed-by' AND e2.target_id != ?",
            (concept_id, concept_id)
        ).fetchall()

        at_risk[concept_id] = {
            "dependents": [r[0] for r in dependents],
            "composed_with": [r[0] for r in composed],
            "shared_invariant": [r[0] for r in shared_invariant],
        }

    return {"direct": list(direct_ids), "propagated": at_risk}
```

**Example:** A use-after-free vulnerability (CVE-2026-XXXXX) is found in the
Slab Allocator concept.

```
Vulnerability: CVE-2026-XXXXX (Use After Free in SLUB)
    |
    exploits -> Slab Allocator
    |
    Knowledge graph knows:
        Page Cache --prerequisite--> Slab Allocator
        RCU --constrains-composition--> Slab Allocator
        VFS --prerequisite--> Slab Allocator
    |
    System immediately flags:
        ⚠ Page Cache: depends on Slab Allocator (prerequisite)
        ⚠ RCU: composes with Slab Allocator (shared protocol)
        ⚠ VFS: depends on Slab Allocator (prerequisite)
        → Review these concepts for exposure to the same vulnerability class
```

This is the key insight: the knowledge graph's coupling edges (`prerequisite`,
`constrains-composition`, `governed-by`) were designed to model how concepts
interact. Vulnerability propagation is a natural query over that same topology.
No new graph structure is needed -- only a new traversal.

### Score storage

Scores are computed on demand and optionally cached as node attributes:

```python
def compute_all_scores(conn, concept_id) -> dict:
    return {
        "heat": heat_score(conn, concept_id),
        "pain": pain_score(conn, concept_id),
        "impact": impact_score(conn, concept_id),
        "leverage": leverage_score(conn, concept_id),
        "frontier": frontier_score(conn, concept_id),
    }

def refresh_scores(conn, concept_ids=None):
    """Recompute and cache scores for given concepts (or all)."""
    if concept_ids is None:
        rows = conn.execute("SELECT id FROM nodes WHERE kind = 'Concept'").fetchall()
        concept_ids = [r["id"] for r in rows]
    for cid in concept_ids:
        scores = compute_all_scores(conn, cid)
        attrs = json.loads(conn.execute(
            "SELECT attrs FROM nodes WHERE id = ?", (cid,)
        ).fetchone()[0])
        attrs["_scores"] = scores
        attrs["_scores_computed_at"] = datetime.utcnow().isoformat() + "Z"
        conn.execute("UPDATE nodes SET attrs = ? WHERE id = ?", (json.dumps(attrs), cid))
    conn.commit()
```

### Tasks

| Task | File | Detail |
|------|------|--------|
| T6.1 | `src/graph/scoring.py` | New module with score function signatures |
| T6.2 | `src/graph/scoring.py` | `heat_score()` implementation |
| T6.3 | `src/graph/scoring.py` | `pain_score()` implementation |
| T6.4 | `src/graph/scoring.py` | `impact_score()` implementation |
| T6.5 | `src/graph/scoring.py` | `leverage_score()` implementation |
| T6.6 | `src/graph/scoring.py` | `frontier_score()` implementation |
| T6.7 | `src/graph/scoring.py` | `compute_all_scores()` and `refresh_scores()` |
| T6.8 | `src/graph/scoring.py` | `vulnerability_propagation()` -- cross-module impact from vulns |
| T6.9 | `src/graph/scoring.py` | `_cvss_weight()` and `get_linked_vulns()` helpers |
| T6.10 | `tests/` | Score computation tests with known graph topologies |
| T6.11 | `tests/` | Vulnerability propagation tests (prerequisite, composition, shared invariant paths) |
| T6.12 | `tests/` | Edge case tests (no problems, no evidence, zero scores, vuln with no CVSS) |

**Effort:** Medium (2 sessions)

---

## Phase 7: Inference Layer -- Trends and Opportunities

**Goal:** Introduce Trend and Opportunity node kinds that are **inferred from graph
topology**, not extracted from text. These represent the system's own conclusions
about where kernel development is heading and where effort should be invested.

**Why:** This is where the system transitions from "here's what people are saying"
to "here's what you should investigate." Trends and Opportunities are the product.

### Trend detection

A Trend is an inferred pattern: multiple independent observations/discussions
converging on the same concepts over a time window.

```python
REQUIRED_ATTRS["Trend"] = (
    "title",            # "NUMA-aware folio management" (generated)
    "description",      # Summary of the convergence pattern
    "strength",         # Number of independent evidence sources
    "window_start",     # ISO-8601 start of observation window
    "window_end",       # ISO-8601 end of observation window
    "artifact_class",   # Always "B"
)
```

**Detection algorithm:**

```python
def detect_trends(conn, window_days=90, min_evidence=3):
    """Find concept clusters with high evidence convergence.

    Uses source_date (the real-world date from each evidence node's
    original source) to define the observation window -- not ingestion
    time. window_start/window_end on the resulting Trend node reflect
    the earliest and latest source_date of the contributing evidence."""
    since = (datetime.utcnow() - timedelta(days=window_days)).isoformat()[:10]
    # Group evidence nodes by linked concept, filtering by source_date >= since
    # If N independent sources (different URLs) link to the same concept
    # cluster (concepts connected by refines/prerequisite), that's a trend.
    ...
```

New edge: `"trend-about"` (Trend -> Concept)

### Opportunity detection

An Opportunity is a high-leverage unsolved problem area where evidence suggests
investigation would produce outsized impact.

```python
REQUIRED_ATTRS["Opportunity"] = (
    "title",            # "Adaptive folio sizing based on NUMA locality"
    "description",      # Why this is an opportunity
    "confidence",       # 0.0 - 1.0 (based on evidence strength)
    "frontier_score",   # Computed frontier score at time of creation
    "artifact_class",   # Always "B"
)
```

**Detection algorithm:**

```python
def detect_opportunities(conn, min_frontier=8.0):
    """Find concepts with high frontier scores and generate opportunity nodes."""
    concepts = conn.execute("SELECT id, attrs FROM nodes WHERE kind = 'Concept'").fetchall()
    opportunities = []
    for c in concepts:
        score = frontier_score(conn, c["id"])
        if score >= min_frontier:
            # Use LLM to synthesize an opportunity description from
            # the concept's linked problems, observations, and proposals
            ...
```

New edges:
- `"opportunity-for"` (Opportunity -> Concept)
- `"supported-by"` (Opportunity -> Problem | Observation | Discussion | Benchmark)

### Tasks

| Task | File | Detail |
|------|------|--------|
| T7.1 | `src/graph/schema.py` | Add Trend, Opportunity to NODE_KINDS |
| T7.2 | `src/graph/schema.py` | Add REQUIRED_ATTRS for Trend, Opportunity |
| T7.3 | `src/graph/schema.py` | Add trend-about, opportunity-for, supported-by edges |
| T7.4 | `src/graph/inference.py` | New module: `detect_trends()` |
| T7.5 | `src/graph/inference.py` | `detect_opportunities()` |
| T7.6 | `src/graph/inference.py` | `generate_idea_feed()` -- top-level function that combines scoring + inference |
| T7.7 | `tests/` | Trend detection tests with synthetic evidence clusters |
| T7.8 | `tests/` | Opportunity detection tests with known high-frontier graphs |

**Effort:** Large (2-3 sessions)

---

## Phase 8: Human UX -- Web Idea Feed

**Goal:** Build the human-facing idea feed: a web page that shows ranked kernel
development ideas with scores, provenance, linked concepts, and confidence.

**Why:** This is how humans consume the system's output. The idea feed is the
primary product of the frontier discovery engine.

### New web routes

#### GET /ideas -- Idea Feed page

The main product page. Shows a ranked list of ideas (Opportunities + high-scoring
Trends) with:

```
┌────────────────────────────────────────────────────────────────────┐
│  🔬 Kernel Idea Feed                              Last updated: 2h│
│                                                                    │
│  Filters: [All Subsystems ▼] [Last 30 days ▼] [Min score: 5 ▼]   │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ #1  Adaptive folio sizing based on NUMA locality             │  │
│  │     Frontier: 18.4  Heat: 12  Pain: 8  Leverage: 6          │  │
│  │                                                              │  │
│  │     Concepts: Large Folios, NUMA Balancing, Page Reclaim     │  │
│  │     Evidence: 7 discussions, 4 benchmarks, 2 rejections      │  │
│  │     Confidence: 0.82                                         │  │
│  │                                                              │  │
│  │     Sources:                                                 │  │
│  │       - LWN: "Folios and Large Pages" (Jun 15)              │  │
│  │       - LKML: "[RFC] numa-aware folio alloc" (Jun 12)       │  │
│  │       - HN: "Linux memory management in 2026" (Jun 8)      │  │
│  │                                                              │  │
│  │     [View Details]  [View Concept Graph]                     │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ #2  RCU grace period batching for NUMA scalability           │  │
│  │     Frontier: 15.2  Heat: 9  Pain: 11  Leverage: 4          │  │
│  │     ...                                                      │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ #3  ...                                                      │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
```

#### GET /ideas/{idea_id} -- Idea Detail page

Deep dive into a single idea showing:
- Full description and rationale
- Score breakdown with explanations
- Linked Concepts with their own scores
- Evidence chain: every Problem, Observation, Discussion, Benchmark, Rejection
  that contributed to this idea, with source links
- Timeline: when each piece of evidence appeared
- Related ideas (other Opportunities linked to overlapping concepts)

#### GET /radar -- Subsystem Research Radar

Per-subsystem dashboard showing:

```
┌─────────────────────────────────────────────────────────┐
│  Subsystem Research Radar                               │
│                                                         │
│  Memory Management                                      │
│    Activity    ████████░░  (8/10)                       │
│    Pain        ██████░░░░  (6/10)                       │
│    Vulns       ██░░░░░░░░  (2 unfixed, 1 critical)     │
│    Fixes       ████████░░  (14 in last 30d)            │
│    Open Ideas  3                                        │
│    Top Idea    "Adaptive folio sizing" (18.4)           │
│                                                         │
│  Scheduler                                              │
│    Activity    ████░░░░░░  (4/10)                       │
│    Pain        ███░░░░░░░  (3/10)                       │
│    Vulns       ░░░░░░░░░░  (0 unfixed)                 │
│    Fixes       ██████░░░░  (8 in last 30d)             │
│    Open Ideas  1                                        │
│    Top Idea    "EEVDF latency bounds" (9.1)             │
│                                                         │
│  RCU                                                    │
│    Activity    ██████░░░░  (6/10)                       │
│    Pain        ████████░░  (8/10)                       │
│    Vulns       ███░░░░░░░  (1 unfixed, 0 critical)     │
│    Fixes       ██████████  (22 in last 30d)            │
│    Open Ideas  2                                        │
│    Top Idea    "Grace period NUMA batching" (15.2)      │
│                                                         │
│  ...                                                    │
└─────────────────────────────────────────────────────────┘
```

#### GET /api/ideas -- JSON API for idea feed

Returns the idea feed as JSON for programmatic consumption:

```json
{
    "generated_at": "2026-06-26T15:00:00Z",
    "window_days": 30,
    "ideas": [
        {
            "id": "opp-a1b2c3d4e5f6",
            "title": "Adaptive folio sizing based on NUMA locality",
            "description": "...",
            "scores": {
                "frontier": 18.4,
                "heat": 12,
                "pain": 8,
                "leverage": 6
            },
            "confidence": 0.82,
            "concepts": [
                {"id": "concept-xxx", "name": "Large Folios"},
                {"id": "concept-yyy", "name": "NUMA Balancing"}
            ],
            "evidence_summary": {
                "discussions": 7,
                "benchmarks": 4,
                "rejections": 2,
                "problems": 3,
                "observations": 5,
                "vulnerabilities": 2,
                "fixes": 14
            },
            "sources": [
                {"url": "https://lwn.net/...", "title": "...", "date": "2026-06-15"}
            ]
        }
    ]
}
```

### Tasks

| Task | File | Detail |
|------|------|--------|
| T8.1 | `src/web/routes.py` | Add `/ideas` route with filtering and pagination |
| T8.2 | `src/web/routes.py` | Add `/ideas/{idea_id}` detail route |
| T8.3 | `src/web/routes.py` | Add `/radar` subsystem dashboard route (incl. vuln/fix counts) |
| T8.4 | `src/web/routes.py` | Add `/api/ideas` JSON endpoint |
| T8.5 | `src/web/routes.py` | Add `/vulns` route -- vulnerability list with impact propagation |
| T8.6 | `src/web/routes.py` | Add `/vulns/{vuln_id}` detail -- cross-module impact visualization |
| T8.7 | `src/web/routes.py` | Add `/api/vuln-impact/{vuln_id}` JSON endpoint for propagation data |
| T8.8 | `src/web/templates/ideas.html` | Idea feed list template (HTMX-powered) |
| T8.9 | `src/web/templates/idea_detail.html` | Idea detail template with evidence chain |
| T8.10 | `src/web/templates/radar.html` | Subsystem radar dashboard template |
| T8.11 | `src/web/templates/vulns.html` | Vulnerability list with severity badges and impact counts |
| T8.12 | `src/web/templates/vuln_detail.html` | Vuln detail with coupled-concept graph |
| T8.13 | `src/web/templates/dashboard.html` | Update dashboard to link to ideas, radar, and vulns |
| T8.14 | `tests/` | Route tests for new endpoints (status codes, filtering, pagination) |

**Effort:** Medium (2 sessions)

---

## Phase 9: LLM UX -- MCP Idea Tools

**Goal:** Expose the idea feed and scoring to LLM clients via new MCP tools, so an
LLM can ask "what should I investigate?" and get structured, scored answers.

**Why:** The MCP server is how LLMs consume know_kernel. Without idea tools, an LLM
can only query concepts -- it can't discover opportunities.

### New MCP tools

#### get_idea_feed(subsystem?, top_k?, window_days?)

Returns the ranked idea feed, optionally filtered by subsystem.

```python
@mcp.tool()
def get_idea_feed(
    subsystem: str | None = None,
    top_k: int = 10,
    window_days: int = 30,
) -> list[dict[str, Any]]:
    """Get ranked kernel development ideas sorted by frontier score.

    Each idea includes: title, description, scores (frontier, heat, pain,
    leverage), confidence, linked concepts, and evidence summary.

    Use this to discover what kernel areas deserve investigation.
    """
```

#### get_concept_scores(concept_id)

Returns all scores for a specific concept.

```python
@mcp.tool()
def get_concept_scores(concept_id: str) -> dict[str, Any]:
    """Get Heat, Pain, Impact, Leverage, and Frontier scores for a concept.

    Scores indicate:
    - Heat: how actively discussed (higher = more activity)
    - Pain: how many problems and failures (higher = more suffering)
    - Impact: how many other concepts affected (higher = wider blast radius)
    - Leverage: how many problems would be addressed (higher = more valuable)
    - Frontier: composite research opportunity score (higher = more promising)
    """
```

#### get_hot_areas(top_k?, window_days?)

Returns subsystems ranked by aggregate heat across their concepts.

```python
@mcp.tool()
def get_hot_areas(top_k: int = 5, window_days: int = 30) -> list[dict[str, Any]]:
    """Get kernel subsystems ranked by recent activity intensity.

    Returns subsystems with their aggregate heat score, top concepts,
    and count of recent evidence nodes.
    """
```

#### get_problems_for_concept(concept_id)

Returns all open problems linked to a concept.

```python
@mcp.tool()
def get_problems_for_concept(concept_id: str) -> list[dict[str, Any]]:
    """Get all open Problems linked to a concept, sorted by severity.

    Each problem includes: title, description, severity, status,
    and links to related proposals and benchmarks.
    """
```

#### get_convergence(concept_ids)

Checks if multiple concepts are seeing converging evidence.

```python
@mcp.tool()
def get_convergence(concept_ids: list[str]) -> dict[str, Any]:
    """Check if a set of concepts are seeing converging independent evidence.

    Returns shared evidence sources, common problems, overlapping
    discussions, and a convergence score. High convergence across
    independently-raised concepts suggests an emerging trend.
    """
```

#### get_vulnerability_impact(vuln_id)

Returns the full cross-module impact propagation for a vulnerability.

```python
@mcp.tool()
def get_vulnerability_impact(vuln_id: str) -> dict[str, Any]:
    """Get the cross-module impact of a vulnerability.

    Uses the knowledge graph's coupling edges (prerequisite,
    constrains-composition, governed-by) to find all concepts
    at risk through transitive dependency on the exploited concept.

    Returns:
    - direct: concepts directly exploited by this vulnerability
    - propagated: for each direct concept, which other concepts
      are coupled (dependents, composed_with, shared_invariant)
    - affected_subsystems: subsystems containing at-risk concepts

    This is the key differentiator: a vulnerability in Concept A
    immediately flags Concepts X, Y, Z for review because the
    knowledge graph knows they are coupled.
    """
```

#### get_recent_vulns(subsystem?, window_days?, min_severity?)

Returns recent vulnerabilities with their impact propagation.

```python
@mcp.tool()
def get_recent_vulns(
    subsystem: str | None = None,
    window_days: int = 30,
    min_severity: str = "medium",
) -> list[dict[str, Any]]:
    """Get recent kernel vulnerabilities sorted by severity.

    Each vulnerability includes: CVE ID, CVSS score, affected concepts,
    cross-module impact propagation, and fix status.

    Use this to identify security-critical areas that need attention
    and discover which coupled concepts may be at risk.
    """
```

#### get_recent_fixes(subsystem?, window_days?, fix_type?)

Returns recent fixes from kernel repositories.

```python
@mcp.tool()
def get_recent_fixes(
    subsystem: str | None = None,
    window_days: int = 30,
    fix_type: str | None = None,
) -> list[dict[str, Any]]:
    """Get recent kernel fixes (bug fixes, security patches, regression fixes).

    Each fix includes: commit hash, fix type, patched concepts, and
    what Problem or Vulnerability it resolves.

    Use this to understand what's being actively fixed and where
    regressions are occurring.
    """
```

### Export considerations

New node kinds (Problem, Observation, Discussion, Benchmark, Rejection, Proposal,
Trend, Opportunity) are all Class B (artifact_class="B"). They should be included
in `ALLOWED_KINDS` in `src/export/exporter.py` and therefore visible in the MCP
snapshot.

**Exception:** Discussion nodes may contain attribution to specific developers
(participant names). These are factual and not copyrightable, but the export
should strip `key_participants` if privacy concerns arise. This is a policy
decision to make during implementation.

### Tasks

| Task | File | Detail |
|------|------|--------|
| T9.1 | `src/mcp_server/server.py` | Add `get_idea_feed()` tool |
| T9.2 | `src/mcp_server/server.py` | Add `get_concept_scores()` tool |
| T9.3 | `src/mcp_server/server.py` | Add `get_hot_areas()` tool |
| T9.4 | `src/mcp_server/server.py` | Add `get_problems_for_concept()` tool |
| T9.5 | `src/mcp_server/server.py` | Add `get_convergence()` tool |
| T9.6 | `src/mcp_server/server.py` | Add `get_vulnerability_impact()` tool |
| T9.7 | `src/mcp_server/server.py` | Add `get_recent_vulns()` tool |
| T9.8 | `src/mcp_server/server.py` | Add `get_recent_fixes()` tool |
| T9.9 | `src/export/exporter.py` | Add new Class B kinds to ALLOWED_KINDS (including Vulnerability, Fix) |
| T9.10 | `tests/` | MCP tool tests with mock snapshot containing evidence, vulns, fixes + scores |

**Effort:** Medium (2 sessions)

---

## Phase 10: End-to-End Showcase

**Goal:** Run the full pipeline end-to-end with real data to produce a working
idea feed from the last 30 days of Linux kernel news.

**Why:** Validates the entire architecture with real data and produces a demo-ready
artifact.

### Steps

1. Ensure all Phases 1-9 are implemented and tests pass
2. Run `kk-feed poll --all` to fetch from all configured feed sources
3. Run `kk-feed poll --all --extract` to extract claims from fetched items
4. Run score refresh across all concepts
5. Run trend and opportunity detection
6. Start web server and verify `/ideas` page shows ranked ideas
7. Start MCP server with fresh snapshot and verify `get_idea_feed()` returns results
8. Document the showcase with screenshots and example queries

### Success criteria

- At least 5 feed sources successfully polled (including kernel git + CVE)
- At least 10 claim extractions completed with concept linking
- At least 2 subsystems show non-zero heat scores
- At least 1 Opportunity node generated with frontier score > 5
- At least 1 Vulnerability node with cross-module impact propagation
- At least 5 Fix nodes created from kernel git commit parsing
- Idea feed page renders with ranked ideas and provenance chains
- Vulnerability impact page shows coupled concepts flagged for review
- MCP `get_idea_feed()` and `get_vulnerability_impact()` return structured results

### Tasks

| Task | Detail |
|------|--------|
| T10.1 | Feed polling dry run (test with real URLs, verify content extraction) |
| T10.2 | Claim extraction on real feed items (verify LLM concept matching) |
| T10.3 | Score computation and validation (verify scores are sensible) |
| T10.4 | Trend/opportunity detection run |
| T10.5 | Web UI verification (screenshots, edge cases) |
| T10.6 | MCP tool verification (structured output validation) |
| T10.7 | Demo documentation |

**Effort:** Large (2-3 sessions)

---

## Implementation Order Summary

```
Phase 1  Source-date temporal queries   [SMALL]   ← foundation for scoring (dates live on evidence nodes)
Phase 2  Discourse source policy       [SMALL]   ← unblocks feed ingestion
Phase 3  Evidence layer node kinds     [LARGE]   ← new schema
Phase 4  Feed ingestion pipeline       [LARGE]   ← the data input
Phase 5  Claim extraction prompt       [MEDIUM]  ← the intelligence
Phase 6  Scoring engine                [MEDIUM]  ← the ranking
Phase 7  Inference layer               [LARGE]   ← the product
Phase 8  Web idea feed UX              [MEDIUM]  ← human consumption
Phase 9  MCP idea tools                [MEDIUM]  ← LLM consumption
Phase 10 End-to-end showcase           [LARGE]   ← validation + demo
```

**Total estimated effort:** 15-22 sessions across 10 phases.

**Minimum viable slice** (proves architecture end-to-end):
Phases 1 + 2 + 3 (batch 1 only: Problem + Observation) + 4 (LWN RSS only) + 5 +
6 (heat score only) + 8 (minimal /ideas page) = ~8-10 sessions.

---

## Dependencies

```
Phase 1 ─────────────────────────┐
Phase 2 ──────────┐              │
                   ├─ Phase 4 ───┤
Phase 3 ──────────┘              ├─ Phase 6 ─── Phase 7 ─── Phase 10
                                 │
Phase 5 (needs Phase 3 + 4) ─────┘
                                 
Phase 8 (needs Phase 6 + 7)
Phase 9 (needs Phase 6 + 7)
Phase 8 and Phase 9 are independent of each other.
```

Phases 1 and 2 can run in parallel. Phase 3 can start as soon as Phase 1 is done.
Phase 4 needs Phases 2 and 3. Phase 5 needs Phases 3 and 4. Phase 6 needs timestamps
(Phase 1) and evidence nodes (from Phase 4+5). Phases 8 and 9 are independent and
can be built in parallel after Phase 7.
