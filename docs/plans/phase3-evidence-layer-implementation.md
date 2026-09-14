# Implementation Plan: Phase 3 — Evidence Layer (Node Kinds + Edge Kinds)

**Created:** 2026-06-26
**Status:** Ready for implementation
**Parent plan:** docs/plans/idea-spotter-and-frontier-discovery.md
**Scope:** Schema extensions, admissibility rules, engine queries, export policy,
web display, test updates
**Prerequisite:** None — this is the first implementation phase

---

## Overview

Add 8 new node kinds and 14 new edge kinds to the knowledge graph to support
the evidence layer: Problem, Observation, Discussion, Benchmark, Rejection,
Vulnerability, Fix, and Proposal (revived). This phase delivers the schema
and infrastructure so Phases 4-9 have well-typed nodes and edges to work with.

### What changes

| Metric | Before | After |
|--------|--------|-------|
| NODE_KINDS | 14 | 22 (+8) |
| EDGE_KINDS | 18 | 32 (+14) |
| REQUIRED_ATTRS entries | 14 (Proposal missing!) | 22 |
| EDGE_VALID_PAIRS entries | 18 | 32 |
| RULES_BY_KIND entries | 14 | 22 |
| Admissibility check functions | 17 | 23 (+6) |
| ALLOWED_KINDS (export) | 11 | 19 (+8) |
| _DISPLAY_FIELDS (web) | 14 | 22 (+8) |

### Files changed

| File | Type | What changes |
|------|------|-------------|
| `src/graph/schema.py` | MODIFY | NODE_KINDS, EDGE_KINDS, REQUIRED_ATTRS, EDGE_VALID_PAIRS, new DATE_ATTRS, new ID_PREFIXES |
| `src/graph/rules.py` | MODIFY | 6 new check functions, 8 new RULES_BY_KIND entries |
| `src/graph/engine.py` | MODIFY | contradicted-by symmetry, source_date validation, 3 new temporal query functions |
| `src/graph/diagnostics.py` | MODIFY | 3 new diagnostic fields in DiagnosticReport |
| `src/export/exporter.py` | MODIFY | ALLOWED_KINDS expanded, validate_snapshot refactored |
| `src/web/routes.py` | MODIFY | 8 new _DISPLAY_FIELDS entries |
| `tests/conftest.py` | MODIFY | populated fixture extended |
| `tests/test_graph_schema.py` | MODIFY | Expected sets updated |
| `tests/test_graph_rules.py` | MODIFY | 12 new test functions (pass + fail for each check) |
| `tests/test_graph_engine.py` | MODIFY | Temporal query tests, symmetry tests, date validation tests |
| `tests/test_export_exporter.py` | MODIFY | New kinds in snapshot tests |
| `tests/test_mcp_server.py` | MODIFY | New kinds queryable |
| `tests/test_web.py` | MODIFY | Display name resolution for new kinds |
| `tests/test_graph_diagnostics.py` | MODIFY | New diagnostic field tests |

---

## Step 1: `src/graph/schema.py`

This is the foundation. Every other file imports from schema.py. All changes
in this step must land together or tests will fail.

### Task 1.1: Extend NODE_KINDS tuple

**File:** `src/graph/schema.py` line 8
**Current:**
```python
NODE_KINDS = ("Concept", "Source", "Evidence", "Advisory", "Subsystem", "KernelInvariant", "FailureMode", "InteractionProtocol", "PerformanceProfile", "CompatibilityAssessment", "OptimizationGoal", "UseCaseScenario", "ComparativeAnalysis", "Kernel")
```

**Change to:**
```python
NODE_KINDS = ("Concept", "Source", "Evidence", "Advisory", "Subsystem", "KernelInvariant", "FailureMode", "InteractionProtocol", "PerformanceProfile", "CompatibilityAssessment", "OptimizationGoal", "UseCaseScenario", "ComparativeAnalysis", "Kernel", "Problem", "Observation", "Discussion", "Benchmark", "Rejection", "Vulnerability", "Fix", "Proposal")
```

Note: Proposal is already in NODE_KINDS at position before Kernel. Move it to
the end of the new group for clarity, or leave it in its current position.
Either way, it must remain exactly once.

**Verification:** `len(NODE_KINDS) == 22` and `"Proposal" in NODE_KINDS`.

### Task 1.2: Extend EDGE_KINDS tuple

**File:** `src/graph/schema.py` lines 10-29
**Current:** 18 edge kinds ending with `"implemented-in"`.

**Add these 14 new edge kinds after `"implemented-in"`:**
```python
"identifies-problem",
"observes",
"discusses",
"benchmarks",
"rejected-for",
"grounded-in",
"exploits",
"affects-subsystem",
"fixes",
"patches",
"addresses",
"contradicted-by",
"resulted-in",
"motivated-by",
```

**Verification:** `len(EDGE_KINDS) == 32`.

### Task 1.3: Add REQUIRED_ATTRS for 8 new kinds

**File:** `src/graph/schema.py` after the existing REQUIRED_ATTRS entries
(currently ends at line 67 with `"Kernel"`)

**Add these entries:**

```python
REQUIRED_ATTRS["Problem"] = (
    "title",
    "description",
    "severity",         # "critical" | "high" | "medium" | "low"
    "status",           # "open" | "partially-addressed" | "resolved"
    "source_date",      # ISO-8601 date (e.g., "2026-06-15")
    "artifact_class",
)

REQUIRED_ATTRS["Observation"] = (
    "claim",
    "confidence",       # float 0.0-1.0 as string
    "source_date",
    "artifact_class",
)

REQUIRED_ATTRS["Discussion"] = (
    "title",
    "forum",            # "lkml" | "lwn" | "hackernews" | "plumbers" | "phoronix" | "other"
    "participant_count", # int as string, 0 if unknown
    "source_date",
    "artifact_class",
)

REQUIRED_ATTRS["Benchmark"] = (
    "metric",
    "result_summary",
    "conditions",
    "source_date",
    "artifact_class",
)

REQUIRED_ATTRS["Rejection"] = (
    "proposal_title",
    "reason",
    "rejector",
    "source_date",
    "artifact_class",
)

REQUIRED_ATTRS["Vulnerability"] = (
    "cve_id",
    "title",
    "description",
    "severity",         # "critical" | "high" | "medium" | "low"
    "cvss_score",       # string (e.g., "9.8") or "" if unscored
    "affected_versions",# string (e.g., "5.15 - 6.10") or ""
    "status",           # "unfixed" | "fix-pending" | "fixed" | "mitigated"
    "source_date",
    "artifact_class",
)

REQUIRED_ATTRS["Fix"] = (
    "title",
    "commit_hash",      # git SHA or "" for non-git fixes
    "fix_type",         # "bugfix" | "security-fix" | "regression-fix" | "performance-fix"
    "source_date",
    "artifact_class",
)

REQUIRED_ATTRS["Proposal"] = (
    "name",
    "description",
    "status",           # "draft" | "under-review" | "accepted" | "rejected" | "abandoned"
    "source_date",
    "artifact_class",
)
```

**Critical:** Proposal currently has NO entry in REQUIRED_ATTRS despite being
in NODE_KINDS. This is an existing bug. This task fixes it. There is zero
existing code that creates Proposal nodes, so adding REQUIRED_ATTRS causes
no breakage.

**Verification:** `set(REQUIRED_ATTRS.keys()) == set(NODE_KINDS)` (this is
asserted by `test_graph_schema.py:test_required_attrs_covers_all_node_kinds`).

### Task 1.4: Add EDGE_VALID_PAIRS for 14 new edges

**File:** `src/graph/schema.py` after existing EDGE_VALID_PAIRS (currently
ends at line 49 with `"implemented-in"`)

**Add:**
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

**Verification:** `set(EDGE_VALID_PAIRS.keys()) == set(EDGE_KINDS)` (asserted
by `test_graph_schema.py:test_edge_valid_pairs_covers_all_edge_kinds`).

### Task 1.5: Add DATE_ATTRS constant

**File:** `src/graph/schema.py` after REQUIRED_ATTRS block

**Add:**
```python
DATE_ATTRS = frozenset({"source_date"})
```

This set lists attribute names that must be valid ISO-8601 date strings when
present. Used by engine.py for validation at insert time.

### Task 1.6: Add ID_PREFIXES constant

**File:** `src/graph/schema.py` after DATE_ATTRS

**Add:**
```python
ID_PREFIXES = {
    "Concept": "concept-",
    "Source": "src-",
    "Evidence": "ev-",
    "Advisory": "adv-",
    "Subsystem": "sub-",
    "KernelInvariant": "kinv-",
    "FailureMode": "fm-",
    "InteractionProtocol": "ip-",
    "PerformanceProfile": "pp-",
    "CompatibilityAssessment": "ca-",
    "OptimizationGoal": "goal-",
    "UseCaseScenario": "scenario-",
    "ComparativeAnalysis": "cmpan-",
    "Kernel": "kernel-",
    "Problem": "prob-",
    "Observation": "obs-",
    "Discussion": "disc-",
    "Benchmark": "bench-",
    "Rejection": "rej-",
    "Vulnerability": "vuln-",
    "Fix": "fix-",
    "Proposal": "prop-",
}
```

This is used by future creation functions (Phase 4+) to generate consistent
node IDs. Existing code already uses similar prefixes inline (e.g.,
`f"goal-{uuid.uuid4().hex[:12]}"` in optimization.py).

---

## Step 2: `src/graph/rules.py`

Add admissibility rules for each new evidence-layer node kind.

### Task 2.1: Add check function for Problem

**File:** `src/graph/rules.py` — add after `check_advisory_has_assessor`
(line 198)

```python
def check_problem_has_concept(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'identifies-problem' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "problem-identifies-concept", "Problem must identifies-problem at least one Concept")
    return None
```

### Task 2.2: Add check function for Observation

```python
def check_observation_has_concept(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'observes' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "observation-observes-concept", "Observation must observes at least one Concept")
    return None
```

### Task 2.3: Add check function for Discussion

```python
def check_discussion_has_concept(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'discusses' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "discussion-discusses-concept", "Discussion must discusses at least one Concept")
    return None
```

### Task 2.4: Add check function for Benchmark

```python
def check_benchmark_has_concept(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'benchmarks' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "benchmark-benchmarks-concept", "Benchmark must benchmarks at least one Concept")
    return None
```

### Task 2.5: Add check function for Proposal

```python
def check_proposal_has_concept(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'grounded-in' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "proposal-grounded-in-concept", "Proposal must be grounded-in at least one Concept")
    return None
```

### Task 2.6: Add check function for Vulnerability

```python
def check_vulnerability_has_concept(conn: sqlite3.Connection, node_id: str) -> Violation | None:
    row = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'exploits' AND source_id = ? LIMIT 1",
        (node_id,),
    ).fetchone()
    if row is None:
        return Violation(node_id, "vulnerability-exploits-concept", "Vulnerability must exploits at least one Concept")
    return None
```

### Task 2.7: Add RULES_BY_KIND entries for all 8 new kinds

**File:** `src/graph/rules.py` — add to the RULES_BY_KIND dict (line 201)

```python
RULES_BY_KIND["Problem"] = [check_problem_has_concept]
RULES_BY_KIND["Observation"] = [check_observation_has_concept]
RULES_BY_KIND["Discussion"] = [check_discussion_has_concept]
RULES_BY_KIND["Benchmark"] = [check_benchmark_has_concept]
RULES_BY_KIND["Rejection"] = []      # links to other evidence, not directly to concepts
RULES_BY_KIND["Vulnerability"] = [check_vulnerability_has_concept]
RULES_BY_KIND["Fix"] = []            # links to Problem/Vulnerability, not directly to concepts
RULES_BY_KIND["Proposal"] = [check_proposal_has_concept]
```

**Why Rejection and Fix have empty rules:** Rejection links to Concept via
`rejected-for` but this is optional (a rejection may reference a concept
indirectly through the proposal it rejects). Fix links to Problem/Vulnerability
via `fixes` and to Concept via `patches`, but both are optional (a fix may
only have one of these links). Requiring concept links on these would over-constrain
the creation flow.

**Verification:** All 22 kinds must have entries in RULES_BY_KIND. The dict
uses `.get(kind, [])` so missing entries silently skip validation — that's
why explicit empty lists are needed.

---

## Step 3: `src/graph/engine.py`

### Task 3.1: Add contradicted-by to symmetric edge handling

**File:** `src/graph/engine.py` lines 98-107

**Current code:**
```python
    if kind == "contradicts":
        existing = conn.execute(
            "SELECT 1 FROM edges WHERE kind = 'contradicts' AND source_id = ? AND target_id = ? LIMIT 1",
            (target_id, source_id),
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO edges (kind, source_id, target_id, attrs) VALUES (?, ?, ?, ?)",
                ("contradicts", target_id, source_id, json.dumps(attrs or {})),
            )
```

**Change to:**
```python
    if kind in ("contradicts", "contradicted-by"):
        existing = conn.execute(
            "SELECT 1 FROM edges WHERE kind = ? AND source_id = ? AND target_id = ? LIMIT 1",
            (kind, target_id, source_id),
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO edges (kind, source_id, target_id, attrs) VALUES (?, ?, ?, ?)",
                (kind, target_id, source_id, json.dumps(attrs or {})),
            )
```

This generalizes the symmetry handling to work for both `contradicts`
(Concept↔Concept) and `contradicted-by` (Observation↔Observation).

### Task 3.2: Add source_date format validation

**File:** `src/graph/engine.py` — modify `add_node()` function (line 20)

**After the existing missing-attrs check (line 28), add:**
```python
    from graph.schema import DATE_ATTRS
    import re
    _ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2})?")
    for attr_name in DATE_ATTRS:
        if attr_name in resolved:
            val = resolved[attr_name]
            if not isinstance(val, str) or not _ISO_DATE_RE.match(val):
                raise ValueError(
                    f"Node '{node_id}' attribute '{attr_name}' must be an ISO-8601 date "
                    f"(e.g., '2026-06-15' or '2026-06-15T10:30:00'), got: {val!r}"
                )
```

**Note:** Move the import and regex to module level for efficiency:
```python
from graph.schema import DATE_ATTRS, EDGE_VALID_PAIRS, REQUIRED_ATTRS

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2})?")
```

Add `import re` at the top of engine.py.

### Task 3.3: Add evidence_in_window query function

**File:** `src/graph/engine.py` — add after `path_exists()` (line 476)

```python
def evidence_in_window(
    conn: sqlite3.Connection,
    kind: str,
    since: str,
    until: str | None = None,
) -> list[dict[str, Any]]:
    """Return evidence nodes of a given kind whose source_date falls in [since, until].

    Args:
        kind: Node kind (e.g., "Problem", "Observation").
        since: ISO-8601 date string (inclusive lower bound).
        until: ISO-8601 date string (inclusive upper bound). None = no upper bound.
    """
    if until is not None:
        rows = conn.execute(
            "SELECT id, kind, attrs FROM nodes "
            "WHERE kind = ? "
            "AND json_extract(attrs, '$.source_date') >= ? "
            "AND json_extract(attrs, '$.source_date') <= ? "
            "ORDER BY json_extract(attrs, '$.source_date') ASC",
            (kind, since, until),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, kind, attrs FROM nodes "
            "WHERE kind = ? "
            "AND json_extract(attrs, '$.source_date') >= ? "
            "ORDER BY json_extract(attrs, '$.source_date') ASC",
            (kind, since),
        ).fetchall()
    return [{"id": r[0], "kind": r[1], "attrs": json.loads(r[2])} for r in rows]
```

### Task 3.4: Add evidence_count_for_concept query function

```python
def evidence_count_for_concept(
    conn: sqlite3.Connection,
    concept_id: str,
    edge_kind: str,
    since: str,
    until: str | None = None,
) -> int:
    """Count evidence nodes linked to a concept via edge_kind whose source_date >= since.

    Args:
        concept_id: The Concept node ID.
        edge_kind: Edge kind connecting evidence to concept
                   (e.g., "identifies-problem", "observes").
        since: ISO-8601 date string (inclusive lower bound).
        until: ISO-8601 date string (inclusive upper bound). None = no upper bound.
    """
    if until is not None:
        row = conn.execute(
            "SELECT COUNT(*) FROM edges e "
            "JOIN nodes n ON e.source_id = n.id "
            "WHERE e.kind = ? AND e.target_id = ? "
            "AND json_extract(n.attrs, '$.source_date') >= ? "
            "AND json_extract(n.attrs, '$.source_date') <= ?",
            (edge_kind, concept_id, since, until),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) FROM edges e "
            "JOIN nodes n ON e.source_id = n.id "
            "WHERE e.kind = ? AND e.target_id = ? "
            "AND json_extract(n.attrs, '$.source_date') >= ?",
            (edge_kind, concept_id, since),
        ).fetchone()
    return row[0]
```

### Task 3.5: Add concept_timeline query function

```python
def concept_timeline(
    conn: sqlite3.Connection,
    concept_id: str,
) -> list[dict[str, Any]]:
    """Return all evidence nodes linked to a concept, ordered by source_date.

    Traverses all evidence-to-concept edge kinds to build a chronological
    timeline of everything that has been said about this concept.
    """
    evidence_edge_kinds = (
        "identifies-problem", "observes", "discusses",
        "benchmarks", "rejected-for", "grounded-in", "exploits",
    )
    placeholders = ",".join("?" for _ in evidence_edge_kinds)
    rows = conn.execute(
        f"SELECT n.id, n.kind, n.attrs, json_extract(n.attrs, '$.source_date') as sd "
        f"FROM nodes n "
        f"JOIN edges e ON e.source_id = n.id AND e.target_id = ? "
        f"WHERE e.kind IN ({placeholders}) "
        f"ORDER BY sd ASC",
        (concept_id, *evidence_edge_kinds),
    ).fetchall()
    return [{"id": r[0], "kind": r[1], "attrs": json.loads(r[2]), "source_date": r[3]} for r in rows]
```

---

## Step 4: `src/graph/diagnostics.py`

### Task 4.1: Add new diagnostic fields to DiagnosticReport

**File:** `src/graph/diagnostics.py` lines 14-22

**Add these fields to the DiagnosticReport dataclass:**
```python
    orphan_problems: list[str] = field(default_factory=list)
    orphan_observations: list[str] = field(default_factory=list)
    unlinked_vulnerabilities: list[str] = field(default_factory=list)
```

### Task 4.2: Add diagnostic queries to diagnose_graph

**File:** `src/graph/diagnostics.py` — add after the `lone_protocols` query
(line 70), before the `sub_rows` query (line 72)

```python
    report.orphan_problems = [
        r[0]
        for r in conn.execute(
            "SELECT n.id FROM nodes n "
            "WHERE n.kind = 'Problem' "
            "AND n.id NOT IN ("
            "  SELECT e.source_id FROM edges e WHERE e.kind = 'identifies-problem'"
            ")"
        ).fetchall()
    ]

    report.orphan_observations = [
        r[0]
        for r in conn.execute(
            "SELECT n.id FROM nodes n "
            "WHERE n.kind = 'Observation' "
            "AND n.id NOT IN ("
            "  SELECT e.source_id FROM edges e WHERE e.kind = 'observes'"
            ")"
        ).fetchall()
    ]

    report.unlinked_vulnerabilities = [
        r[0]
        for r in conn.execute(
            "SELECT n.id FROM nodes n "
            "WHERE n.kind = 'Vulnerability' "
            "AND n.id NOT IN ("
            "  SELECT e.source_id FROM edges e WHERE e.kind = 'exploits'"
            ")"
        ).fetchall()
    ]
```

---

## Step 5: `src/export/exporter.py`

### Task 5.1: Expand ALLOWED_KINDS

**File:** `src/export/exporter.py` line 17

**Current:**
```python
ALLOWED_KINDS = ("Concept", "Subsystem", "KernelInvariant", "FailureMode", "InteractionProtocol", "PerformanceProfile", "CompatibilityAssessment", "OptimizationGoal", "UseCaseScenario", "ComparativeAnalysis", "Kernel")
```

**Change to:**
```python
ALLOWED_KINDS = ("Concept", "Subsystem", "KernelInvariant", "FailureMode", "InteractionProtocol", "PerformanceProfile", "CompatibilityAssessment", "OptimizationGoal", "UseCaseScenario", "ComparativeAnalysis", "Kernel", "Problem", "Observation", "Discussion", "Benchmark", "Rejection", "Vulnerability", "Fix", "Proposal")
```

### Task 5.2: Refactor validate_snapshot to use ALLOWED_KINDS dynamically

**File:** `src/export/exporter.py` lines 85-89

**Current (hardcoded kind list):**
```python
    forbidden = conn.execute(
        "SELECT kind, COUNT(*) FROM nodes WHERE kind NOT IN ('Concept', 'Subsystem', 'KernelInvariant', 'FailureMode', 'InteractionProtocol', 'PerformanceProfile', 'CompatibilityAssessment', 'OptimizationGoal', 'UseCaseScenario', 'ComparativeAnalysis', 'Kernel') GROUP BY kind"
    ).fetchall()
```

**Change to (dynamic from ALLOWED_KINDS):**
```python
    allowed_placeholders = ",".join("?" for _ in ALLOWED_KINDS)
    forbidden = conn.execute(
        f"SELECT kind, COUNT(*) FROM nodes WHERE kind NOT IN ({allowed_placeholders}) GROUP BY kind",
        ALLOWED_KINDS,
    ).fetchall()
```

This eliminates the duplicated kind list that would silently diverge whenever
ALLOWED_KINDS is updated.

---

## Step 6: `src/web/routes.py`

### Task 6.1: Add _DISPLAY_FIELDS entries for 8 new kinds

**File:** `src/web/routes.py` lines 38-53

**Add these entries to the `_DISPLAY_FIELDS` dict:**
```python
    "Problem": ("title", None),
    "Observation": ("claim", 60),
    "Discussion": ("title", None),
    "Benchmark": ("metric", 40),
    "Rejection": ("proposal_title", 60),
    "Vulnerability": ("cve_id", None),
    "Fix": ("title", 60),
    "Proposal": ("name", None),
```

**Note:** Proposal already has no _DISPLAY_FIELDS entry (another existing gap).
The Vulnerability display name uses `cve_id` as the primary field. If `cve_id`
is empty (no CVE assigned), `display_name_for_node()` falls through to the
`node_id` fallback. Consider adding a secondary fallback to `title` for
Vulnerability. This can be done by modifying `display_name_for_node()` to check
a secondary field:

```python
    # In display_name_for_node, after the primary field check:
    if kind == "Vulnerability" and not value:
        value = (attrs.get("title") or "").strip()
        if value:
            return value
```

This is optional but improves UX for vulnerabilities without CVE IDs.

---

## Step 7: `tests/conftest.py`

### Task 7.1: Extend populated fixture with evidence-layer nodes

**File:** `tests/conftest.py` — modify `populated` fixture (line 22)

**Add after the existing `add_edge(conn, "assessed-by", "src1", "adv1")`
(line 34):**

```python
    # Evidence-layer nodes for testing
    add_node(conn, "prob1", "Problem", {
        "title": "Grace period latency",
        "description": "RCU grace periods take too long under NUMA",
        "severity": "high",
        "status": "open",
        "source_date": "2026-06-01",
        "artifact_class": "B",
    })
    add_node(conn, "obs1", "Observation", {
        "claim": "NUMA locality affects RCU throughput",
        "confidence": "0.8",
        "source_date": "2026-06-10",
        "artifact_class": "B",
    })
    add_node(conn, "disc1", "Discussion", {
        "title": "RCU scalability on NUMA systems",
        "forum": "lkml",
        "participant_count": "5",
        "source_date": "2026-06-12",
        "artifact_class": "B",
    })
    add_node(conn, "bench1", "Benchmark", {
        "metric": "grace period latency",
        "result_summary": "17% improvement with batching",
        "conditions": "128 cores, NUMA",
        "source_date": "2026-06-15",
        "artifact_class": "B",
    })
    add_node(conn, "vuln1", "Vulnerability", {
        "cve_id": "CVE-2026-99999",
        "title": "Use-after-free in RCU callback processing",
        "description": "A use-after-free can occur when...",
        "severity": "high",
        "cvss_score": "7.8",
        "affected_versions": "6.8 - 6.10",
        "status": "unfixed",
        "source_date": "2026-06-20",
        "artifact_class": "B",
    })
    add_node(conn, "prop1", "Proposal", {
        "name": "NUMA-aware grace period batching",
        "description": "Batch grace periods by NUMA node",
        "status": "draft",
        "source_date": "2026-06-18",
        "artifact_class": "B",
    })
    add_node(conn, "fix1", "Fix", {
        "title": "Fix RCU callback UAF",
        "commit_hash": "a1b2c3d4e5f6",
        "fix_type": "security-fix",
        "source_date": "2026-06-22",
        "artifact_class": "B",
    })
    add_node(conn, "rej1", "Rejection", {
        "proposal_title": "Remove grace periods entirely",
        "reason": "Would break all existing RCU users",
        "rejector": "Paul McKenney",
        "source_date": "2026-05-01",
        "artifact_class": "B",
    })
    # Evidence-layer edges
    add_edge(conn, "identifies-problem", "prob1", "c1")
    add_edge(conn, "observes", "obs1", "c1")
    add_edge(conn, "discusses", "disc1", "c1")
    add_edge(conn, "benchmarks", "bench1", "c1")
    add_edge(conn, "exploits", "vuln1", "c1")
    add_edge(conn, "grounded-in", "prop1", "c1")
    add_edge(conn, "addresses", "prop1", "prob1")
    add_edge(conn, "fixes", "fix1", "vuln1")
    add_edge(conn, "patches", "fix1", "c1")
    add_edge(conn, "rejected-for", "rej1", "c1")
```

### Task 7.2: Extend admissible_master_db fixture

**File:** `tests/conftest.py` — modify `admissible_master_db` fixture (line 39)

Add the same evidence-layer nodes and edges after the existing content (before
`conn.commit()`). This fixture is used by export tests.

---

## Step 8: Test updates

### Task 8.1: Update test_graph_schema.py

**File:** `tests/test_graph_schema.py`

**8.1a: Update `test_node_kinds_complete()` (line 17)**

Replace the expected set with:
```python
    assert set(NODE_KINDS) == {
        "Concept", "Source", "Evidence", "Advisory", "Subsystem",
        "KernelInvariant", "FailureMode", "InteractionProtocol",
        "PerformanceProfile", "CompatibilityAssessment",
        "OptimizationGoal", "UseCaseScenario", "ComparativeAnalysis",
        "Kernel", "Problem", "Observation", "Discussion", "Benchmark",
        "Rejection", "Vulnerability", "Fix", "Proposal",
    }
```

**8.1b: Update `test_edge_kinds_complete()` (line 20)**

Add to the expected set:
```python
        "identifies-problem", "observes", "discusses", "benchmarks",
        "rejected-for", "grounded-in", "exploits", "affects-subsystem",
        "fixes", "patches", "addresses", "contradicted-by",
        "resulted-in", "motivated-by",
```

**8.1c: Add test for DATE_ATTRS**
```python
def test_date_attrs_is_frozenset():
    from graph.schema import DATE_ATTRS
    assert isinstance(DATE_ATTRS, frozenset)
    assert "source_date" in DATE_ATTRS
```

**8.1d: Add test for ID_PREFIXES**
```python
def test_id_prefixes_covers_all_node_kinds():
    from graph.schema import ID_PREFIXES
    assert set(ID_PREFIXES.keys()) == set(NODE_KINDS)
```

### Task 8.2: Update test_graph_rules.py

**File:** `tests/test_graph_rules.py`

Add 12 new test functions (pass + fail for each of the 6 new check functions).
Follow the existing pattern (e.g., `test_concept_belongs_to_pass` / `_fail`).

```python
# --- Problem ---

def test_problem_has_concept_pass(populated: sqlite3.Connection):
    from graph.rules import check_problem_has_concept
    assert check_problem_has_concept(populated, "prob1") is None

def test_problem_has_concept_fail(conn: sqlite3.Connection):
    from graph.rules import check_problem_has_concept
    add_node(conn, "prob1", "Problem", {
        "title": "test", "description": "test", "severity": "low",
        "status": "open", "source_date": "2026-01-01", "artifact_class": "B",
    })
    v = check_problem_has_concept(conn, "prob1")
    assert isinstance(v, Violation)
    assert "identifies-problem" in v.message

# --- Observation ---

def test_observation_has_concept_pass(populated: sqlite3.Connection):
    from graph.rules import check_observation_has_concept
    assert check_observation_has_concept(populated, "obs1") is None

def test_observation_has_concept_fail(conn: sqlite3.Connection):
    from graph.rules import check_observation_has_concept
    add_node(conn, "obs1", "Observation", {
        "claim": "test", "confidence": "0.5",
        "source_date": "2026-01-01", "artifact_class": "B",
    })
    v = check_observation_has_concept(conn, "obs1")
    assert isinstance(v, Violation)

# --- Discussion ---

def test_discussion_has_concept_pass(populated: sqlite3.Connection):
    from graph.rules import check_discussion_has_concept
    assert check_discussion_has_concept(populated, "disc1") is None

def test_discussion_has_concept_fail(conn: sqlite3.Connection):
    from graph.rules import check_discussion_has_concept
    add_node(conn, "disc1", "Discussion", {
        "title": "test", "forum": "lkml", "participant_count": "0",
        "source_date": "2026-01-01", "artifact_class": "B",
    })
    v = check_discussion_has_concept(conn, "disc1")
    assert isinstance(v, Violation)

# --- Benchmark ---

def test_benchmark_has_concept_pass(populated: sqlite3.Connection):
    from graph.rules import check_benchmark_has_concept
    assert check_benchmark_has_concept(populated, "bench1") is None

def test_benchmark_has_concept_fail(conn: sqlite3.Connection):
    from graph.rules import check_benchmark_has_concept
    add_node(conn, "bench1", "Benchmark", {
        "metric": "latency", "result_summary": "fast", "conditions": "test",
        "source_date": "2026-01-01", "artifact_class": "B",
    })
    v = check_benchmark_has_concept(conn, "bench1")
    assert isinstance(v, Violation)

# --- Proposal ---

def test_proposal_has_concept_pass(populated: sqlite3.Connection):
    from graph.rules import check_proposal_has_concept
    assert check_proposal_has_concept(populated, "prop1") is None

def test_proposal_has_concept_fail(conn: sqlite3.Connection):
    from graph.rules import check_proposal_has_concept
    add_node(conn, "prop1", "Proposal", {
        "name": "test", "description": "test", "status": "draft",
        "source_date": "2026-01-01", "artifact_class": "B",
    })
    v = check_proposal_has_concept(conn, "prop1")
    assert isinstance(v, Violation)

# --- Vulnerability ---

def test_vulnerability_has_concept_pass(populated: sqlite3.Connection):
    from graph.rules import check_vulnerability_has_concept
    assert check_vulnerability_has_concept(populated, "vuln1") is None

def test_vulnerability_has_concept_fail(conn: sqlite3.Connection):
    from graph.rules import check_vulnerability_has_concept
    add_node(conn, "vuln1", "Vulnerability", {
        "cve_id": "CVE-2026-00001", "title": "test", "description": "test",
        "severity": "low", "cvss_score": "3.0", "affected_versions": "",
        "status": "unfixed", "source_date": "2026-01-01", "artifact_class": "B",
    })
    v = check_vulnerability_has_concept(conn, "vuln1")
    assert isinstance(v, Violation)
```

Also update the imports at the top of the file to include the new check functions.

### Task 8.3: Update test_graph_engine.py

**File:** `tests/test_graph_engine.py`

**8.3a: Add test for contradicted-by symmetry**
```python
def test_contradicted_by_symmetric(conn: sqlite3.Connection):
    add_node(conn, "c1", "Concept", {"name": "A", "description": "a", "artifact_class": "B", "key_properties": ["x"], "tradeoffs": [], "design_rationale": "r"})
    add_node(conn, "obs1", "Observation", {"claim": "X is true", "confidence": "0.9", "source_date": "2026-01-01", "artifact_class": "B"})
    add_node(conn, "obs2", "Observation", {"claim": "X is false", "confidence": "0.8", "source_date": "2026-01-02", "artifact_class": "B"})
    add_edge(conn, "contradicted-by", "obs1", "obs2")
    # Reverse edge should exist
    reverse = conn.execute(
        "SELECT 1 FROM edges WHERE kind = 'contradicted-by' AND source_id = 'obs2' AND target_id = 'obs1'"
    ).fetchone()
    assert reverse is not None
```

**8.3b: Add test for source_date validation**
```python
def test_source_date_valid_date(conn: sqlite3.Connection):
    add_node(conn, "prob1", "Problem", {
        "title": "test", "description": "test", "severity": "low",
        "status": "open", "source_date": "2026-06-15", "artifact_class": "B",
    })
    node = get_node(conn, "prob1")
    assert node is not None

def test_source_date_valid_datetime(conn: sqlite3.Connection):
    add_node(conn, "prob1", "Problem", {
        "title": "test", "description": "test", "severity": "low",
        "status": "open", "source_date": "2026-06-15T10:30:00", "artifact_class": "B",
    })
    node = get_node(conn, "prob1")
    assert node is not None

def test_source_date_invalid_rejected(conn: sqlite3.Connection):
    import pytest
    with pytest.raises(ValueError, match="ISO-8601"):
        add_node(conn, "prob1", "Problem", {
            "title": "test", "description": "test", "severity": "low",
            "status": "open", "source_date": "yesterday", "artifact_class": "B",
        })
```

**8.3c: Add tests for temporal query functions**
```python
from graph.engine import evidence_in_window, evidence_count_for_concept, concept_timeline

def test_evidence_in_window(populated: sqlite3.Connection):
    results = evidence_in_window(populated, "Problem", "2026-05-01", "2026-07-01")
    assert len(results) >= 1
    assert all(r["kind"] == "Problem" for r in results)

def test_evidence_in_window_empty(populated: sqlite3.Connection):
    results = evidence_in_window(populated, "Problem", "2020-01-01", "2020-12-31")
    assert len(results) == 0

def test_evidence_count_for_concept(populated: sqlite3.Connection):
    count = evidence_count_for_concept(populated, "c1", "identifies-problem", "2026-01-01")
    assert count >= 1

def test_evidence_count_for_concept_empty_window(populated: sqlite3.Connection):
    count = evidence_count_for_concept(populated, "c1", "identifies-problem", "2030-01-01")
    assert count == 0

def test_concept_timeline(populated: sqlite3.Connection):
    timeline = concept_timeline(populated, "c1")
    assert len(timeline) >= 1
    # Should be ordered by source_date ascending
    dates = [e["source_date"] for e in timeline if e["source_date"]]
    assert dates == sorted(dates)
```

### Task 8.4: Update test_export_exporter.py

**File:** `tests/test_export_exporter.py`

Update tests that verify snapshot contents to account for new evidence-layer
kinds. The `admissible_master_db` fixture (updated in Step 7) now includes
evidence nodes, so:

- Tests that count nodes in the snapshot must expect the new kinds
- Tests that verify "no forbidden kinds" must accept the new Class B kinds
- The refactored `validate_snapshot` must be tested to confirm it uses
  ALLOWED_KINDS dynamically

```python
def test_snapshot_includes_evidence_kinds(admissible_master_db, tmp_path):
    from export.exporter import export_class_b_snapshot
    snap_path = tmp_path / "snap.db"
    report = export_class_b_snapshot(admissible_master_db, snap_path)
    snap = sqlite3.connect(str(snap_path))
    snap.row_factory = sqlite3.Row
    kinds = {r[0] for r in snap.execute("SELECT DISTINCT kind FROM nodes").fetchall()}
    assert "Problem" in kinds
    assert "Vulnerability" in kinds
    assert "Proposal" in kinds
    # Class A kinds should NOT be in snapshot
    assert "Evidence" not in kinds
    assert "Source" not in kinds
    assert "Advisory" not in kinds
    snap.close()
```

### Task 8.5: Update test_mcp_server.py

**File:** `tests/test_mcp_server.py`

Verify that `search_concepts()` returns results for new evidence-layer kinds.
The MCP server uses `ALLOWED_KINDS` from exporter, which now includes the new
kinds.

```python
def test_search_returns_evidence_kinds(snapshot_conn):
    # Assumes snapshot_conn has evidence-layer nodes
    results = search_concepts("grace period")
    evidence_kinds = {r["kind"] for r in results}
    # Should find Problem, Observation, etc. if they match the query
    assert len(results) >= 0  # May or may not match depending on fixture data
```

### Task 8.6: Update test_web.py

**File:** `tests/test_web.py`

Add test for display name resolution for new kinds:

```python
def test_display_name_problem():
    from web.routes import display_name_for_node
    assert display_name_for_node("Problem", {"title": "Grace period latency"}, "prob-123") == "Grace period latency"

def test_display_name_vulnerability():
    from web.routes import display_name_for_node
    assert display_name_for_node("Vulnerability", {"cve_id": "CVE-2026-99999"}, "vuln-123") == "CVE-2026-99999"

def test_display_name_vulnerability_no_cve():
    from web.routes import display_name_for_node
    # Falls back to node_id when cve_id is empty
    result = display_name_for_node("Vulnerability", {"cve_id": ""}, "vuln-123")
    assert result == "vuln-123"

def test_display_name_proposal():
    from web.routes import display_name_for_node
    assert display_name_for_node("Proposal", {"name": "NUMA batching"}, "prop-123") == "NUMA batching"
```

### Task 8.7: Update test_graph_diagnostics.py

**File:** `tests/test_graph_diagnostics.py`

```python
def test_orphan_problems_detected(conn: sqlite3.Connection):
    from graph.diagnostics import diagnose_graph
    add_node(conn, "prob1", "Problem", {
        "title": "orphan", "description": "test", "severity": "low",
        "status": "open", "source_date": "2026-01-01", "artifact_class": "B",
    })
    report = diagnose_graph(conn)
    assert "prob1" in report.orphan_problems

def test_orphan_problems_clean(populated: sqlite3.Connection):
    from graph.diagnostics import diagnose_graph
    report = diagnose_graph(populated)
    assert len(report.orphan_problems) == 0

def test_unlinked_vulnerabilities_detected(conn: sqlite3.Connection):
    from graph.diagnostics import diagnose_graph
    add_node(conn, "vuln1", "Vulnerability", {
        "cve_id": "CVE-2026-00001", "title": "test", "description": "test",
        "severity": "low", "cvss_score": "3.0", "affected_versions": "",
        "status": "unfixed", "source_date": "2026-01-01", "artifact_class": "B",
    })
    report = diagnose_graph(conn)
    assert "vuln1" in report.unlinked_vulnerabilities
```

---

## Invariant and Algorithm ID Registry

These IDs follow the existing naming convention in the codebase.

### New Invariants

| ID | Rule | Enforced by |
|----|------|-------------|
| INV-KK-PROBLEM-CONCEPT | Problem must identifies-problem at least 1 Concept | `check_problem_has_concept()` |
| INV-KK-OBSERVATION-CONCEPT | Observation must observes at least 1 Concept | `check_observation_has_concept()` |
| INV-KK-DISCUSSION-CONCEPT | Discussion must discusses at least 1 Concept | `check_discussion_has_concept()` |
| INV-KK-BENCHMARK-CONCEPT | Benchmark must benchmarks at least 1 Concept | `check_benchmark_has_concept()` |
| INV-KK-PROPOSAL-CONCEPT | Proposal must grounded-in at least 1 Concept | `check_proposal_has_concept()` |
| INV-KK-VULN-CONCEPT | Vulnerability must exploits at least 1 Concept | `check_vulnerability_has_concept()` |
| INV-KK-DATE-FORMAT | source_date must be ISO-8601 (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS) | `add_node()` validation |
| INV-KK-CONTRADICTED-SYMMETRIC | contradicted-by edge must be symmetric (A→B implies B→A) | `add_edge()` symmetry |

### New Algorithms

| ID | Description | Location |
|----|-------------|----------|
| ALG-KK-EVIDENCE-WINDOW | Query evidence nodes by source_date range | `evidence_in_window()` |
| ALG-KK-EVIDENCE-COUNT | Count evidence linked to concept in date window | `evidence_count_for_concept()` |
| ALG-KK-CONCEPT-TIMELINE | Chronological evidence chain for a concept | `concept_timeline()` |
| ALG-KK-DIAG-ORPHAN-EVIDENCE | Detect evidence nodes without concept links | `diagnose_graph()` |

---

## Execution checklist

This is the ordered list of implementation actions. Each line is one atomic
change that can be committed or verified independently.

```
[ ] 1.1  schema.py: Extend NODE_KINDS (14 -> 22)
[ ] 1.2  schema.py: Extend EDGE_KINDS (18 -> 32)
[ ] 1.3  schema.py: Add REQUIRED_ATTRS for 8 new kinds (including Proposal fix)
[ ] 1.4  schema.py: Add EDGE_VALID_PAIRS for 14 new edges
[ ] 1.5  schema.py: Add DATE_ATTRS frozenset
[ ] 1.6  schema.py: Add ID_PREFIXES dict
[ ] 2.1  rules.py: Add check_problem_has_concept()
[ ] 2.2  rules.py: Add check_observation_has_concept()
[ ] 2.3  rules.py: Add check_discussion_has_concept()
[ ] 2.4  rules.py: Add check_benchmark_has_concept()
[ ] 2.5  rules.py: Add check_proposal_has_concept()
[ ] 2.6  rules.py: Add check_vulnerability_has_concept()
[ ] 2.7  rules.py: Add 8 RULES_BY_KIND entries
[ ] 3.1  engine.py: Add contradicted-by to symmetric edge handling
[ ] 3.2  engine.py: Add source_date ISO-8601 validation in add_node()
[ ] 3.3  engine.py: Add evidence_in_window() query function
[ ] 3.4  engine.py: Add evidence_count_for_concept() query function
[ ] 3.5  engine.py: Add concept_timeline() query function
[ ] 4.1  diagnostics.py: Add 3 new DiagnosticReport fields
[ ] 4.2  diagnostics.py: Add 3 diagnostic queries in diagnose_graph()
[ ] 5.1  exporter.py: Expand ALLOWED_KINDS (11 -> 19)
[ ] 5.2  exporter.py: Refactor validate_snapshot to use ALLOWED_KINDS dynamically
[ ] 6.1  routes.py: Add 8 _DISPLAY_FIELDS entries
[ ] 7.1  conftest.py: Extend populated fixture with evidence-layer nodes + edges
[ ] 7.2  conftest.py: Extend admissible_master_db fixture
[ ] 8.1  test_graph_schema.py: Update expected NODE_KINDS and EDGE_KINDS sets + new tests
[ ] 8.2  test_graph_rules.py: Add 12 new test functions (6 pass + 6 fail)
[ ] 8.3  test_graph_engine.py: Add symmetry, date validation, temporal query tests
[ ] 8.4  test_export_exporter.py: Add snapshot evidence-kinds test
[ ] 8.5  test_mcp_server.py: Verify new kinds queryable
[ ] 8.6  test_web.py: Display name tests for new kinds
[ ] 8.7  test_graph_diagnostics.py: Orphan evidence detection tests
```

Total: 31 tasks across 8 steps and 14 files.

---

## DB Migration Note

SQLite CHECK constraints in SCHEMA_SQL are auto-generated from NODE_KINDS and
EDGE_KINDS tuples at schema.py lines 69-92. The `init_db()` function uses
`CREATE TABLE IF NOT EXISTS` which means existing databases will NOT get the
updated CHECK constraints. Options:

1. **Recreate the database** (recommended for development) — delete
   `data/know_kernel.db` and re-run ingestion.
2. **Add a migration function** that uses `ALTER TABLE ... RENAME TO ...` +
   recreate pattern (complex, needed only if preserving production data).

For this development phase, option 1 is sufficient since the database is
small and can be regenerated.

---

## What this phase does NOT include

- No feed ingestion code (Phase 4)
- No claim extraction prompt (Phase 5)
- No scoring functions (Phase 6)
- No trend/opportunity inference (Phase 7)
- No new web routes for /ideas, /vulns, /radar (Phase 8)
- No new MCP tools for ideas/vulns (Phase 9)
- No end-to-end showcase (Phase 10)

This phase delivers only the **schema, rules, queries, and test infrastructure**
so that all subsequent phases have well-typed nodes and edges to work with.
