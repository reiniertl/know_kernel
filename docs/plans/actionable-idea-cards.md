# Plan: Actionable Idea Cards — Blast Radius, Source Links, and Actionable Framing

**Status:** Ready for implementation
**Date:** 2026-07-02
**Prerequisite:** motivation-categories-and-idea-narrative.md (all 3 stages complete)
**Scope:** Three gaps in the current idea_detail page: (1) no blast radius per category, (2) no direct source links on evidence, (3) descriptive instead of actionable framing
**Implementation:** 2 /cb-green stages

---

## Problem Statement

The idea_detail page now has 7 motivation categories (SECURITY, STABILITY,
PERFORMANCE, SCALABILITY, EFFICIENCY, HARDWARE ENABLEMENT, MAINTAINABILITY)
but three things are missing:

### 1. No blast radius visible in the card

The brief already computes `brief["prerequisites"]["depended_on_by"]` — a list
of `{id, name}` dicts for every Concept that depends on the subject concept via
a `prerequisite` edge. `build_argument_paragraph()` already counts these and
mentions them in the narrative. But the individual motivation category sections
don't show them. When a reader sees "3 active vulnerabilities (1 critical)", the
next question is "how many components are exposed?" — and the page doesn't answer
that without scrolling to a collapsed section.

The data is already in the brief dict. No new queries needed.

### 2. No direct source links on evidence items

Every evidence node (Problem, Vulnerability, Observation, Discussion, Benchmark,
Fix, FailureMode, KernelInvariant, PerformanceProfile) follows a provenance chain:

```
EvidenceNode --extracted-from--> Evidence --sourced-from--> Source{url, source_type}
```

The schema enforces this chain:
- `INV-KK-CONCEPT-PROVENANCE`: Concept must have `extracted-from` edge
- `INV-KK-EVIDENCE-EXACTLY-ONE-SOURCE`: Evidence must have exactly one `sourced-from` edge
- `extracted-from` valid pairs: (Concept|KernelInvariant|FailureMode|InteractionProtocol|PerformanceProfile|Problem|Observation|Discussion|Benchmark|..., Evidence)
- `sourced-from` valid pair: (Evidence, Source)
- Source required attrs: `url`, `source_type`, `license`

The Source.url is the actual link to the paper, patch, LKML thread, or CVE page
where the evidence was first observed. But `build_concept_brief()` never resolves
this chain — it returns `id` fields on each item but no `source_url`.

The existing invariant `INV-KK-WEB-IDEA-BRIEF-VERBATIM` already claims "Source
attribution (forum/source_type, URL, source_date) accompanies every evidence item"
but the implementation doesn't deliver on the URL part.

The query pattern for resolving source URLs already exists in
`src/graph/inference.py:72-86` — it joins `extracted-from` → `sourced-from` →
`Source.attrs.url`. This needs to be adapted for `build_concept_brief()`.

**Current production DB state:** The production DB (`data/know_kernel.db`) has
0 nodes — all testing is done with fixture data. The `extracted-from` and
`sourced-from` edges have 0 rows in the production DB. This means the source URL
resolution will return empty strings for most items until the ingestion pipeline
populates provenance edges. The implementation must handle this gracefully: show
a link to `/concepts/{id}` (internal node detail page) as fallback when no
external source URL is resolved.

### 3. Descriptive instead of actionable framing

Each motivation category says "this exists" but never says "if you act on this,
here's what you gain." The data to construct actionable statements is already in
the brief — it's the same counted data that `build_argument_paragraph()` uses.

Additionally, categories that are co-triggered on the same concept have
relationships that should be surfaced. The clearest case: if HARDWARE ENABLEMENT
and PERFORMANCE are both triggered, implementing hardware support directly
improves the profiled performance metrics. The page should say this.

---

## Current Code State

### `src/graph/briefing.py` — `build_concept_brief()` (lines 37-330)

Returns a 15-key dict. Each evidence item already has an `id` field. The items
that need `source_url` added are:

| Brief key | Item fields that exist | Node kind | Count field |
|---|---|---|---|
| `problems` | id, title, description, severity, status, source_date | Problem | len() |
| `vulnerabilities` | id, cve_id, title, description, severity, cvss_score, affected_versions, status, source_date | Vulnerability | len() |
| `failure_modes` | id, symptom, blast_radius, recoverability | FailureMode | len() |
| `invariants` | id, predicate, strength, scope | KernelInvariant | len() |
| `protocols` | id, rule, ordering, violation_mode, participant_concepts | InteractionProtocol | len() |
| `profiles` | id, metric, complexity, best_case, worst_case, typical_case, conditions | PerformanceProfile | len() |
| `fixes` | id, title, commit_hash, fix_type, source_date, resolves | Fix | len() |
| `observations` | id, claim, confidence, source_date | Observation | len() |
| `discussions` | id, title, forum, participant_count, source_date | Discussion | len() |
| `benchmarks` | id, metric, result_summary, conditions, source_date | Benchmark | len() |
| `timeline` | source_date, kind, id, text | mixed | len() |

All 11 collections return items with an `id` field. The `source_url` needs to be
resolved for each `id` via the provenance chain and added to each item dict.

### `src/graph/briefing.py` — `classify_motivations()` (lines 431-721)

Returns a list of motivation dicts. Each motivation has:
```python
{
    "category": str,       # e.g. "security"
    "icon": str,           # emoji
    "label": str,          # e.g. "SECURITY"
    "headline": str,       # templated summary
    "evidence": list[dict] # flattened evidence items
}
```

The evidence items are **flattened copies** — they extract `text` from the brief
items but lose the `id` and don't carry `source_url`. The evidence dict shapes
per category:

| Category | Evidence type | Fields | Missing |
|---|---|---|---|
| security | vulnerability | type, text, severity, cvss | id, source_url, cve_id, affected_versions, status |
| stability | failure_mode | type, text, blast_radius | id, source_url, recoverability |
| stability | invariant | type, text | id, source_url, strength, scope |
| stability | problem | type, text, severity | id, source_url, status |
| performance | profile | type, text | id, source_url (text is already a formatted string) |
| performance | benchmark | type, text | id, source_url |
| performance | observation | type, text | id, source_url |
| scalability | text_match | type, text | no id (text extracted from problem/observation/discussion, source unknown) |
| efficiency | text_match | type, text | no id (same as scalability) |
| hardware | text_match | type, text | no id |
| hardware | concept_description | type, text | N/A (concept description, not evidence) |
| maintainability | fix | type, text, fix_type, commit | id missing (but `commit` is there) |

**Key insight for scalability/efficiency/hardware:** These categories extract text
from `brief["problems"]`, `brief["observations"]`, and `brief["discussions"]` but
only keep the text string, not the source item. To add source links, the evidence
dicts need to carry the original item's `id` and `source_url`.

### `src/web/templates/idea_detail.html` (239 lines, current state after revert)

Structure:
1. Header (title, kind badge, frontier score, subsystem)
2. "Why Pursue This" — motivation cards with 3-item cap + "...and N more"
3. "The Case" — argument paragraph
4. Scores table
5. Evidence Timeline table (verbatim, date-ordered)
6. Structural Detail (`<details>` collapsed): invariants, failure modes, protocols, dependencies, performance, code examples
7. Related Ideas

**What's wrong with this structure:**
- Motivation cards truncate to 3 evidence items — the rest is hidden
- Full data is in the collapsed `<details>` section — organized by data type, not by motivation category
- No blast radius anywhere in the motivation cards
- No source links on any evidence item
- No actionable framing — "3 active vulnerabilities" but not "fixing these eliminates N attack surfaces"
- Evidence timeline has `id` per item but no link

### `src/web/routes.py` — `idea_detail()` (lines 564-666)

The route merges motivations across briefs (deduplicating by category, merging
evidence lists). Template context includes `briefs` (full data) and `motivations`
(merged motivation list). Both are available to the template.

### `src/web/templates/vuln_detail.html`

The vuln_detail template also uses motivations (filtering out security). Changes
to the motivation dict structure in `classify_motivations()` will affect both
templates. The vuln_detail template currently renders motivations as inline
`<span>` elements (compact format) — it can benefit from the same improvements
but the compact format is intentional for that page.

---

## Design

### Part A: Source URL resolution in `build_concept_brief()`

Add a new step 17 to `build_concept_brief()` that batch-resolves source URLs
for all evidence node IDs collected across steps 4-14.

**Step 17 implementation:**

```python
# 17. Batch-resolve source URLs via provenance chain
all_evidence_ids: list[str] = []
for item_list in (problems, vulnerabilities, failure_modes, invariants,
                  protocols, profiles, fixes, observations, discussions,
                  benchmarks):
    for item in item_list:
        all_evidence_ids.append(item["id"])

source_urls: dict[str, str] = {}
if all_evidence_ids:
    placeholders = ",".join("?" for _ in all_evidence_ids)
    url_rows = conn.execute(
        f"SELECT e1.source_id, json_extract(s.attrs, '$.url') "
        f"FROM edges e1 "
        f"JOIN edges e2 ON e2.source_id = e1.target_id AND e2.kind = 'sourced-from' "
        f"JOIN nodes s ON e2.target_id = s.id "
        f"WHERE e1.kind = 'extracted-from' AND e1.source_id IN ({placeholders})",
        all_evidence_ids,
    ).fetchall()
    for row in url_rows:
        if row[1]:
            source_urls[row[0]] = row[1]

# Attach source_url to each item
for item_list in (problems, vulnerabilities, failure_modes, invariants,
                  protocols, profiles, fixes, observations, discussions,
                  benchmarks):
    for item in item_list:
        item["source_url"] = source_urls.get(item["id"], "")

# Also attach to timeline items
for item in timeline:
    item["source_url"] = source_urls.get(item["id"], "")
```

**Query explanation:** This is one SQL query that resolves all evidence IDs at once.
The join chain is: `edges(extracted-from, source_id=evidence_node_id)` → target is
an Evidence node → `edges(sourced-from, source_id=evidence_node_id)` → target is a
Source node → `json_extract(attrs, '$.url')`. This is the same pattern used in
`src/graph/inference.py:75-81` but batched with `IN (?)` instead of per-ID queries.

**Performance:** One query instead of N queries. The `IN` clause with ~50-100 IDs
is well within SQLite's variable limit (999 default). If a concept has more evidence
nodes than that (unlikely), the query can be chunked.

**Graceful degradation:** When the provenance chain doesn't exist (no
`extracted-from` edges), `source_urls` is empty and every item gets
`source_url = ""`. The template renders a fallback link to `/concepts/{id}`
instead.

### Part B: Enrich `classify_motivations()` evidence dicts

Currently, evidence dicts in the motivation list are flat copies that lose the
original item's `id` and `source_url`. Each evidence dict needs to carry:

1. `id` — the node ID of the evidence item (for fallback links to `/concepts/{id}`)
2. `source_url` — the resolved external URL (from Part A, now present on brief items)

Additionally, each motivation dict gets two new fields:

3. `blast_radius` — `{"count": N, "components": [{id, name}, ...]}` from
   `brief["prerequisites"]["depended_on_by"]`
4. `actionable` — a templated sentence stating the expected benefit
5. `cross_links` — list of other triggered category names that relate to this one

**Changes per category in `classify_motivations()`:**

#### All categories — add blast_radius

After computing each motivation dict, before appending:
```python
blast_radius = {
    "count": len(brief["prerequisites"]["depended_on_by"]),
    "components": brief["prerequisites"]["depended_on_by"],
}
```
Add `"blast_radius": blast_radius` to every motivation dict. The blast radius is
a property of the concept, not the category, but showing it per-category answers
"if I fix THIS problem, what else benefits?"

#### SECURITY — enrich evidence, add actionable

Current evidence dict:
```python
{"type": "vulnerability", "text": f"{v['cve_id']}: {v['description']}", "severity": ..., "cvss": ...}
```

New evidence dict:
```python
{
    "type": "vulnerability",
    "id": v["id"],
    "source_url": v.get("source_url", ""),
    "cve_id": v["cve_id"],
    "title": v.get("title", ""),
    "text": v["description"],
    "severity": v.get("severity", "medium"),
    "cvss": v.get("cvss_score", 0.0),
    "affected_versions": v.get("affected_versions", ""),
    "status": v.get("status", ""),
}
```

Actionable sentence:
```python
dep_count = len(brief["prerequisites"]["depended_on_by"])
actionable = (
    f"Fixing {'this vulnerability' if len(vulns) == 1 else 'these vulnerabilities'} "
    f"eliminates {len(vulns)} active attack surface"
    f"{'s' if len(vulns) != 1 else ''}"
)
if dep_count > 0:
    actionable += f" and removes exposure from {dep_count} dependent component{'s' if dep_count != 1 else ''}"
actionable += "."
```

#### STABILITY — enrich evidence, add actionable

Current evidence dicts:
```python
{"type": "failure_mode", "text": fm["symptom"], "blast_radius": fm["blast_radius"]}
{"type": "invariant", "text": inv["predicate"]}
{"type": "problem", "text": p["title"], "severity": p["severity"]}
```

New evidence dicts:
```python
{
    "type": "failure_mode",
    "id": fm["id"],
    "source_url": fm.get("source_url", ""),
    "text": fm["symptom"],
    "blast_radius": fm["blast_radius"],
    "recoverability": fm.get("recoverability", ""),
}
{
    "type": "invariant",
    "id": inv["id"],
    "source_url": inv.get("source_url", ""),
    "text": inv["predicate"],
    "strength": inv.get("strength", ""),
    "scope": inv.get("scope", ""),
}
{
    "type": "problem",
    "id": p["id"],
    "source_url": p.get("source_url", ""),
    "text": p["title"],
    "description": p["description"],
    "severity": p["severity"],
    "status": p.get("status", ""),
}
```

Actionable sentence:
```python
worst_blast = max(
    (fm["blast_radius"] for fm in failure_modes),
    key=lambda b: {"kernel-wide": 3, "subsystem": 2, "local": 1}.get(b, 0),
    default="local",
)
worst_recovery = max(
    (fm.get("recoverability", "") for fm in failure_modes),
    key=lambda r: {"unrecoverable": 3, "requires-restart": 2, "self-healing": 1}.get(r, 0),
    default="unknown",
)
actionable = (
    f"Fixing this eliminates {len(failure_modes)} known crash/corruption path"
    f"{'s' if len(failure_modes) != 1 else ''} "
    f"(worst case: {worst_blast}, {worst_recovery})"
)
if brief["prerequisites"]["depended_on_by"]:
    actionable += f" and restores invariant guarantees for {len(brief['prerequisites']['depended_on_by'])} dependent components"
actionable += "."
```

#### PERFORMANCE — enrich evidence, add actionable

Current evidence dicts:
```python
{"type": "profile", "text": f"{p['metric']}: {p['best_case']} → {p['worst_case']} ({p['conditions']})"}
{"type": "benchmark", "text": b["result_summary"]}
{"type": "observation", "text": o["claim"]}
```

New evidence dicts:
```python
{
    "type": "profile",
    "id": p["id"],
    "source_url": p.get("source_url", ""),
    "text": f"{p['metric']}: {p['best_case']} → {p['worst_case']} ({p['conditions']})",
    "metric": p["metric"],
    "best_case": p["best_case"],
    "worst_case": p["worst_case"],
    "typical_case": p["typical_case"],
    "conditions": p["conditions"],
    "complexity": p["complexity"],
}
{
    "type": "benchmark",
    "id": b["id"],
    "source_url": b.get("source_url", ""),
    "text": b["result_summary"],
    "conditions": b.get("conditions", ""),
}
{
    "type": "observation",
    "id": o["id"],
    "source_url": o.get("source_url", ""),
    "text": o["claim"],
}
```

Actionable sentence:
```python
if profiles:
    top = profiles[0]
    actionable = (
        f"Closing the gap between {top['best_case']} (best) and "
        f"{top['worst_case']} (worst) on {top['metric']} "
        f"under {top['conditions']}."
    )
elif benchmarks:
    actionable = f"Benchmark data shows optimization opportunity: {benchmarks[0]['result_summary']}."
else:
    actionable = "Performance observations indicate measurable optimization opportunity."
```

#### SCALABILITY — resolve source IDs, add actionable

Current evidence: `{"type": "text_match", "text": t}` — text extracted from
`brief["problems"]`, `brief["observations"]`, `brief["discussions"]` but the
source item is not tracked.

**Fix:** When building `all_text_fields` and `scaling_hits`, track which item
each text came from:

```python
scaling_items: list[dict] = []
for p in brief["problems"]:
    if _text_has_keywords(p["description"], _SCALABILITY_KEYWORDS):
        scaling_items.append({
            "type": "problem", "id": p["id"],
            "source_url": p.get("source_url", ""),
            "text": p["description"],
        })
for o in brief["observations"]:
    if _text_has_keywords(o["claim"], _SCALABILITY_KEYWORDS):
        scaling_items.append({
            "type": "observation", "id": o["id"],
            "source_url": o.get("source_url", ""),
            "text": o["claim"],
        })
for d in brief["discussions"]:
    if _text_has_keywords(d["title"], _SCALABILITY_KEYWORDS):
        scaling_items.append({
            "type": "discussion", "id": d["id"],
            "source_url": d.get("source_url", ""),
            "text": d["title"],
            "forum": d.get("forum", ""),
        })
```

Actionable: `"Removes scaling wall, enabling linear throughput growth with core count and NUMA topology."`

#### EFFICIENCY — same pattern as scalability

Track source items instead of bare text strings. Same structural change.

Actionable: Build from the matched metric/text: `"Reclaims resources currently wasted on {first matched term} without sacrificing functionality."`

#### HARDWARE ENABLEMENT — resolve sources, add actionable + cross-link

Track source items for hw_hits (from discussions and observations).

Actionable sentence:
```python
actionable = "Unlocks hardware capabilities that software currently cannot exploit."
# Cross-link to PERFORMANCE if profiles exist
if brief["profiles"]:
    actionable += (
        f" Direct performance gains expected: {brief['profiles'][0]['metric']} "
        f"currently {brief['profiles'][0]['worst_case']} worst case."
    )
```

Cross-links:
```python
cross_links = []
if brief["profiles"] or brief["benchmarks"]:
    cross_links.append("performance")
```

#### MAINTAINABILITY — enrich evidence, add actionable

Current evidence dict:
```python
{"type": "fix", "text": f["title"], "fix_type": f.get("fix_type", "unknown"), "commit": f.get("commit_hash", "")}
```

New evidence dict:
```python
{
    "type": "fix",
    "id": f["id"],
    "source_url": f.get("source_url", ""),
    "text": f["title"],
    "fix_type": f.get("fix_type", "unknown"),
    "commit": f.get("commit_hash", ""),
    "source_date": f.get("source_date", ""),
    "resolves": f.get("resolves", []),
}
```

Actionable:
```python
actionable = (
    f"Reduces patch churn from {len(fixes)} patches in recent window"
)
if regression_fixes:
    actionable += f", eliminates {len(regression_fixes)} regression cycle{'s' if len(regression_fixes) != 1 else ''}"
actionable += ". Future changes become cheaper and safer."
```

### Part C: Template rewrite — `idea_detail.html`

The template restructures from the current layout to:

```
HEADER
  Title · Kind badge · Frontier score · Subsystem

THE CASE (argument paragraph — unchanged)

MOTIVATION CATEGORIES (one section per triggered category)
  For each category:
    h3: icon + LABEL
    p.actionable: "If addressed: {actionable sentence}"
    p.blast-radius: "Blast radius: N components — X, Y, Z (linked)"
    Cross-link note (if cross_links non-empty)

    Full evidence rendering (category-specific):
      SECURITY: full vulnerability cards (severity badge, CVE ID linked,
        CVSS, title, description, affected versions, status)
      STABILITY: failure mode cards (symptom, blast_radius badge,
        recoverability) + invariant cards (predicate, strength, scope)
        + critical problem cards (severity badge, title, description)
      PERFORMANCE: profile table (metric, complexity, best, typical,
        worst, conditions — each row linked) + benchmark cards + observation cards
      SCALABILITY: evidence cards with source links
      EFFICIENCY: evidence cards with source links
      HARDWARE: evidence cards with source links + cross-link to PERFORMANCE
      MAINTAINABILITY: fix cards (fix_type badge, title, commit hash
        linked, date, resolves list)

    Every evidence item has a source link:
      - If source_url non-empty: <a href="{source_url}" target="_blank">source</a>
      - Else: <a href="/concepts/{id}">detail →</a>

SCORES (compact table — unchanged)

EVIDENCE TIMELINE (verbatim, date-ordered — add source link column)

STRUCTURAL CONTEXT (protocols, code examples — open, not collapsed)

DEPENDENCIES (depended_on_by and depends_on — open, linked)

OTHER OPEN PROBLEMS (non-critical, not in STABILITY — with source links)

RELATED IDEAS (unchanged)
```

**Key changes from current template:**
1. Remove 3-item cap on evidence — show ALL items per category
2. Remove `<details>` collapsed section — data is organized by category
3. Add source link to every evidence item (external URL or internal fallback)
4. Add actionable sentence per category
5. Add blast radius per category
6. Add cross-category notes where applicable
7. Evidence timeline gets a 4th column with source links
8. Protocols and code examples remain as standalone sections (they don't
   belong to a motivation category)
9. Dependencies section stays open (not collapsed) with linked names

### Part D: vuln_detail template update

The vuln_detail template uses `brief["motivations"]` with the same dict
structure. The enriched evidence dicts (with `id`, `source_url`) will
automatically be available. The compact inline format can be enhanced:

- Add source link per motivation headline
- Show blast radius count inline

This is a smaller change — ~5 lines in the template.

---

## Spec Surface Changes

### Modified nodes (3 modify-node mutations)

#### 1. ALG-KK-GRAPH-CONCEPT-BRIEF

**Current description:** "Builds a complete research brief dict for a Concept
node by querying the full graph depth across 15 data categories."

**New description:** "Builds a complete research brief dict for a Concept node
by querying the full graph depth across 15 data categories. Step 17 batch-
resolves source URLs for all evidence node IDs via the provenance chain
(extracted-from → sourced-from → Source.url). Each evidence item dict includes
source_url (external URL) or empty string if the provenance chain is not
populated."

#### 2. INV-KK-WEB-IDEA-MOTIVATIONS

**Current predicate:** "forall idea I at /ideas/{id}. motivations(I) =
classify_motivations(briefs(I)) where each category is triggered by threshold
conditions on brief data. Only triggered categories are displayed. Each category
shows verbatim evidence."

**New predicate:** "forall idea I at /ideas/{id}. motivations(I) =
classify_motivations(briefs(I)) where each category is triggered by threshold
conditions on brief data. Only triggered categories are displayed. Each category
shows: (1) all evidence items with direct source links (source_url or fallback
to /concepts/{id}), (2) blast radius (count and linked names of dependent
components), (3) actionable statement composing expected benefit from graph
data counts."

#### 3. INV-KK-WEB-IDEAS-EVIDENCE-CHAIN

**Current predicate:** (ends with) "No evidence is omitted. Evidence text is
never modified."

**New predicate:** Add: "Each evidence item links directly to its source URL
(from Source.url via provenance chain) or to its node detail page
(/concepts/{id}) as fallback."

### New nodes (2 add-node mutations)

#### 4. INV-KK-GRAPH-BRIEF-SOURCE-RESOLVED (new invariant)

**Description:** "build_concept_brief() batch-resolves source URLs for all
evidence node IDs via the extracted-from → sourced-from → Source.url provenance
chain. Each evidence item in the returned brief dict includes a source_url field
(external URL string, or empty string if the chain is not populated)."

**Predicate:** "forall concept C. forall evidence item E in
build_concept_brief(conn, C). E['source_url'] == Source.url resolved via
E --extracted-from--> Evidence --sourced-from--> Source, or '' if chain
not populated."

**PredicateNL:** "Every evidence item in the concept brief includes a
source_url resolved from the provenance chain, or empty string as fallback."

**Edges:**
- `contains` from `SUB-KK-GRAPH` to `INV-KK-GRAPH-BRIEF-SOURCE-RESOLVED`
- `checked-at` from `INV-KK-GRAPH-BRIEF-SOURCE-RESOLVED` to `stage-delivery`
- `satisfies` from `ALG-KK-GRAPH-CONCEPT-BRIEF` to `INV-KK-GRAPH-BRIEF-SOURCE-RESOLVED`

#### 5. INV-KK-WEB-IDEA-MOTIVATION-ACTIONABLE (new invariant)

**Description:** "Each triggered motivation category on the idea detail page
includes a deterministic actionable statement composed from brief data counts
(not LLM-generated) that states the expected benefit of addressing the
category. Categories that co-occur with related categories include cross-
reference notes."

**Predicate:** "forall idea I at /ideas/{id}. forall motivation M in
motivations(I). M.actionable is a non-empty string composed deterministically
from brief data (vulnerability count, failure mode blast_radius, profile
best/worst gap, fix count, dependent count). Same brief data always produces
identical actionable text."

**PredicateNL:** "Every motivation category on the idea detail page includes
an actionable statement telling the reader what they gain by addressing it."

**Edges:**
- `contains` from `SUB-KK-WEB` to `INV-KK-WEB-IDEA-MOTIVATION-ACTIONABLE`
- `checked-at` from `INV-KK-WEB-IDEA-MOTIVATION-ACTIONABLE` to `stage-delivery`
- `satisfies` from `ALG-KK-WEB-IDEAS-DETAIL` to `INV-KK-WEB-IDEA-MOTIVATION-ACTIONABLE`

### Total spec mutations: 3 modify-node + 2 add-node + 6 add-edge = 11 mutations

---

## Files Modified

### Stage 1: Source URL resolution + motivation enrichment (backend)

| File | Action | Lines affected |
|------|--------|---------------|
| `src/graph/briefing.py` | Add step 17 to `build_concept_brief()` (~25 lines): batch source URL resolution | After line 308 (after timeline, before code_examples) |
| `src/graph/briefing.py` | Modify `classify_motivations()` (~150 lines rewritten): add `id`, `source_url` to all evidence dicts; add `blast_radius`, `actionable`, `cross_links` to each motivation dict | Lines 431-721 |
| `tests/test_graph_briefing.py` | Add ~10 tests for source URL resolution, blast_radius, actionable, cross_links | After existing tests |

### Stage 2: Template rewrite + route update (frontend)

| File | Action | Lines affected |
|------|--------|---------------|
| `src/web/templates/idea_detail.html` | Full rewrite (~300 lines): categories as full sections with source links, actionable, blast radius | All 249 lines |
| `src/web/templates/vuln_detail.html` | Minor update (~5 lines): add source link + blast radius to compact motivation rendering | Lines 49-57 |
| `src/web/routes.py` | No changes needed — motivations and briefs already passed to template | — |
| `tests/test_web.py` | Add ~6 tests for source links, actionable text, blast radius rendering | After existing tests |

### Files NOT modified

| File | Why |
|------|-----|
| `src/graph/engine.py` | No new graph queries — source URL uses existing edges |
| `src/graph/scoring.py` | Scoring unchanged |
| `src/graph/schema.py` | Schema unchanged — extracted-from and sourced-from already exist |
| `src/web/templates/ideas.html` | List page unchanged |
| `src/web/templates/vulns.html` | List page unchanged |

---

## Test Definitions

### Stage 1 tests (add to `tests/test_graph_briefing.py`)

| Test name | What it verifies |
|-----------|-----------------|
| `test_brief_items_have_source_url_key` | Every item in problems, vulns, failure_modes, etc. has a `source_url` key |
| `test_brief_source_url_resolves_when_chain_exists` | When extracted-from → sourced-from → Source{url} exists, source_url is populated |
| `test_brief_source_url_empty_when_no_chain` | When no provenance edges exist, source_url is empty string |
| `test_brief_timeline_items_have_source_url` | Timeline items also get source_url |
| `test_motivation_has_blast_radius` | Each motivation dict has blast_radius with count and components |
| `test_motivation_blast_radius_matches_prerequisites` | blast_radius.count == len(brief.prerequisites.depended_on_by) |
| `test_motivation_has_actionable` | Each motivation dict has a non-empty actionable string |
| `test_motivation_actionable_deterministic` | Same brief produces same actionable string |
| `test_motivation_evidence_has_id` | Every evidence dict has an id field |
| `test_motivation_evidence_has_source_url` | Every evidence dict has a source_url field |
| `test_motivation_cross_links_hw_perf` | When hardware + profiles both present, hardware motivation has cross_links containing "performance" |
| `test_motivation_no_cross_links_when_solo` | When only one category triggered, cross_links is empty |

### Stage 2 tests (add to `tests/test_web.py`)

| Test name | What it verifies |
|-----------|-----------------|
| `test_idea_detail_shows_source_links` | Response HTML contains `href="/concepts/` links for evidence items |
| `test_idea_detail_shows_external_source_link` | When source_url exists, response contains external `<a href>` |
| `test_idea_detail_shows_actionable_text` | Response contains actionable text (e.g. "Fixing" or "eliminates") per category |
| `test_idea_detail_shows_blast_radius` | Response contains blast radius count and linked component names |
| `test_idea_detail_no_truncation` | All evidence items rendered (no "...and N more" text) |
| `test_idea_detail_evidence_timeline_has_links` | Evidence timeline table has source link column |

---

## Implementation Commands

Stage 1:
```
/cb-green — Source URL resolution + motivation enrichment

Add step 17 to build_concept_brief() in src/graph/briefing.py: batch-resolve source
URLs for all evidence node IDs via extracted-from → sourced-from → Source.url
provenance chain. Attach source_url to every item in problems, vulnerabilities,
failure_modes, invariants, protocols, profiles, fixes, observations, discussions,
benchmarks, timeline. Modify classify_motivations() to enrich each evidence dict
with id and source_url from the brief items; add blast_radius (count + components
from brief.prerequisites.depended_on_by), actionable (templated benefit sentence
from data counts), and cross_links (list of related co-triggered categories) to
each motivation dict. Add 12 tests to tests/test_graph_briefing.py. Spec mutations:
modify ALG-KK-GRAPH-CONCEPT-BRIEF description, add INV-KK-GRAPH-BRIEF-SOURCE-RESOLVED.
See docs/plans/actionable-idea-cards.md Parts A and B for exact function signatures,
evidence dict shapes, and actionable sentence templates per category.
```

Stage 2:
```
/cb-green — Idea detail template: full categories with source links and actionable framing

Rewrite src/web/templates/idea_detail.html: each motivation category becomes a full
section with actionable sentence, blast radius (count + linked component names), and
all evidence items with direct source links (source_url href or /concepts/{id}
fallback). SECURITY shows full vuln cards. STABILITY shows failure mode cards +
invariants + critical problems. PERFORMANCE shows profile table + benchmarks.
SCALABILITY/EFFICIENCY/HARDWARE show evidence cards with source links. MAINTAINABILITY
shows fix cards with commit hashes and resolves links. Remove 3-item cap and <details>
collapsed section. Add source link column to evidence timeline. Update vuln_detail.html
with source links on compact motivations. Add 6 tests. Spec mutations: modify
INV-KK-WEB-IDEA-MOTIVATIONS and INV-KK-WEB-IDEAS-EVIDENCE-CHAIN, add
INV-KK-WEB-IDEA-MOTIVATION-ACTIONABLE. See docs/plans/actionable-idea-cards.md
Part C for exact template structure and Part D for vuln_detail changes.
```
