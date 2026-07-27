# Human Paper Scoring — Implementation Plan

## Overview

Add a mechanism for humans to read papers and score them for impact.
This introduces a new `HumanReview` node kind into the know_kernel
graph, with CLI, batch, and web interfaces for creating and displaying
reviews.

**Total spec nodes:** 21 (1 module, 3 interfaces, 7 invariants, 10 algorithms)
**Files touched:** 10 (4 new, 6 modified)
**Phases:** 4 (phases 1-2 have no spec conflicts; phase 3 requires a spec decision; phase 4 is GET-only)

---

## Current State

### Database

- 2 tables: `nodes` (id TEXT PK, kind TEXT, attrs TEXT JSON) and `edges` (id INTEGER PK, kind TEXT, source_id TEXT, target_id TEXT, attrs TEXT JSON)
- 3,574 Source nodes total; 3,482 are research-type (paper, preprint, conference-paper, conference-proceedings)
- No existing impact scoring or human review mechanism
- An existing contamination review pattern exists: `Advisory` nodes linked via `assessed-by` edges (see `src/ingest/reviewer.py`)

### Existing Review Pattern (template to follow)

`src/ingest/reviewer.py` implements `review_source()`:
1. Validate inputs (assessment text non-empty, contamination level in enum)
2. Verify Source node exists via SQL query
3. Check no duplicate `assessed-by` edge exists (INV-KK-ADVISORY-SINGLE-PER-SOURCE)
4. `add_node(conn, advisory_id, "Advisory", {...})`
5. `add_edge(conn, "assessed-by", source_id, advisory_id)`
6. `validate_node(conn, advisory_id, "Advisory")`
7. Return `ReviewResult` dataclass

`src/ingest/cli_review.py` implements the CLI wrapper:
1. argparse with `--db`, `--source-id`, `--assessment`, `--confirm-level`
2. `init_db(Path(args.db))`
3. Call `review_source(conn, ...)`
4. `conn.commit()`
5. `print(json.dumps({...}, indent=2))`
6. Exit codes: 0 success, 1 validation error, 2 DB error

### Web Layer

- All routes are GET-only (no POST endpoints exist anywhere in `src/web/routes.py`)
- Routes are registered in `setup_routes(app, templates)` called from `src/web/app.py`
- DB connection available as `request.app.state.conn`
- Templates extend `src/web/templates/base.html`
- Base template nav bar lists: Dashboard, All Nodes, Subsystems, Sources, Research, Feed, Radar, Vulns, Code, Graph, Health
- HTMX loaded from CDN for search functionality
- Paper detail page at `/paper/{source_id}` (`src/web/templates/paper_detail.html`) shows: research brief, connected concepts, motivations, paper evidence
- Feed page at `/feed` (`src/web/templates/feed.html`) shows papers in a table with: Date, Research Card, Type, Kernel Concept, Summary, Subsystem, Why Pursue, Actions
- Radar page at `/radar` (`src/web/templates/radar.html`) groups papers by subsystem then concept

### Schema Constants (src/graph/schema.py)

All five constants that need modification:

```python
NODE_KINDS = ("Concept", "Source", "Evidence", "Advisory", "Subsystem",
    "KernelInvariant", "FailureMode", "InteractionProtocol",
    "PerformanceProfile", "CompatibilityAssessment", "OptimizationGoal",
    "UseCaseScenario", "ComparativeAnalysis", "Kernel", "Problem",
    "Observation", "Discussion", "Benchmark", "Rejection", "Vulnerability",
    "Fix", "Proposal", "Trend", "Opportunity", "ResearchBrief")

EDGE_KINDS = ("belongs-to", "extracted-from", "sourced-from",
    "alternative-to", "refines", "contradicts", "prerequisite",
    "supersedes", "assessed-by", "governed-by", "triggered-by",
    "constrains-composition", "profiled-by", "assesses-compatibility",
    "contributes-to", "suited-for", "compares", "implemented-in",
    "identifies-problem", "observes", "discusses", "benchmarks",
    "rejected-for", "grounded-in", "exploits", "affects-subsystem",
    "fixes", "patches", "addresses", "contradicted-by", "resulted-in",
    "motivated-by", "trend-about", "opportunity-for", "supported-by",
    "summarizes-for")

REQUIRED_ATTRS = {
    # ... existing entries ...
    # "HumanReview" must be added here
}

EDGE_VALID_PAIRS = {
    # ... existing entries ...
    # "reviewed-by" must be added here
}

ID_PREFIXES = {
    # ... existing entries ...
    # "HumanReview" must be added here
}
```

### Graph Engine (src/graph/engine.py)

- `add_node(conn, node_id, kind, attrs)` — validates required attrs from `REQUIRED_ATTRS[kind]`, validates date format for `DATE_ATTRS`, inserts. Kind-agnostic; no changes needed.
- `add_edge(conn, kind, source_id, target_id)` — validates against `EDGE_VALID_PAIRS`. Kind-agnostic; no changes needed.
- `validate_node(conn, node_id, kind)` from `graph/rules.py` — runs post-insertion checks. Generic; no changes needed.

### paper_review_list.txt Format

Located at `data/paper_review_list.txt`. Contains 3,047 papers (subset of 3,482 research-type Source nodes). Format per paper:

```
--- Paper N/3047 ---
Title:    <paper title>
Venue:    <venue name>
Date:     <YYYY-MM-DD>

Abstract:
<full abstract text, may be multi-line>

Decision: [ ] ACCEPT  [ ] REJECT
Notes:    

--------------------------------------------------------------------------------
```

When a human fills in the Decision, it becomes `[X] ACCEPT` or `[X] REJECT`. Notes can contain freetext rationale. The batch import must parse this format.

### Existing Spec Surface

- `MOD-KK-WEB` — contains all web-layer spec nodes
- `MOD-KK-INGEST` — contains ingest subsystem nodes (briefs, cleanup, repair)
- `ALG-KK-WEB-PAPER-DETAIL` — paper detail page algorithm
- `ALG-KK-WEB-FEED-LIST` — feed list algorithm
- `ALG-KK-WEB-RADAR` — radar algorithm
- `INV-KK-WEB-QUERY-BOUNDED` — every list route must bound enrichment to page size
- `INV-KK-WEB-PAPER-404-NON-SOURCE` — 404 for missing/non-Source nodes
- No `MOD-KK-REVIEW` exists yet
- No `INV-KK-WEB-READ-ONLY` exists in the spec DAG (it's referenced in code comments but not as a formal invariant node)

---

## Phase 1: Core Data Model + CLI

**Spec nodes created:** 11
**Files:** 3 (1 modified, 2 new)
**Spec conflicts:** None
**Dependencies:** None

### Task 1.1: Schema Extension (src/graph/schema.py)

Modify `src/graph/schema.py` to add:

1. Append `"HumanReview"` to `NODE_KINDS` tuple
2. Add to `REQUIRED_ATTRS`:
   ```python
   "HumanReview": ("reviewer", "score", "verdict", "rationale", "review_date", "artifact_class"),
   ```
3. Add to `ID_PREFIXES`:
   ```python
   "HumanReview": "hrev-",
   ```
4. Append `"reviewed-by"` to `EDGE_KINDS` tuple
5. Add to `EDGE_VALID_PAIRS`:
   ```python
   "reviewed-by": ("Source", "HumanReview"),
   ```
6. Add `"review_date"` to `DATE_ATTRS` frozenset (it's a date field that needs ISO-8601 validation by `add_node()`)

**Note on migration:** The SQLite CHECK constraint on `nodes.kind` is generated from `NODE_KINDS` in `SCHEMA_SQL` at module load time. `init_db()` uses `CREATE TABLE IF NOT EXISTS`, which does NOT update CHECK constraints on existing tables. For existing databases (like `data/master.db`), a migration is needed: either recreate the table (risky) or use `ALTER TABLE` to drop and re-add the constraint (SQLite doesn't support this natively). The pragmatic approach is to add a migration function that:
1. Creates a new table with the updated CHECK constraint
2. Copies all data from the old table
3. Drops the old table
4. Renames the new table

Alternatively, since `data/master.db` is a working database (not the spec DB), a simpler approach may work: just insert without the CHECK constraint if we're willing to bypass it, or rebuild from scratch. This decision should be made at implementation time.

### Task 1.2: Domain Logic (src/ingest/paper_scorer.py) — NEW FILE

Create `src/ingest/paper_scorer.py` with:

**Imports:**
```python
from __future__ import annotations
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date
from graph.engine import add_node, add_edge
from graph.rules import validate_node
```

**PaperReviewResult dataclass:**
```python
@dataclass
class PaperReviewResult:
    review_id: str
    source_id: str
    reviewer: str
    score: int
    verdict: str
    rationale: str
```

**Constants:**
```python
VALID_VERDICTS = {"accept", "reject", "skip"}
VALID_SCORES = {1, 2, 3, 4, 5}
```

**review_paper() function:**

Signature:
```python
def review_paper(
    conn: sqlite3.Connection,
    source_id: str,
    reviewer: str,
    score: int,
    verdict: str,
    rationale: str,
) -> PaperReviewResult:
```

Implementation steps (each enforces a specific invariant):

1. **INV-KK-REVIEW-SCORE-RANGE:** Validate `score in VALID_SCORES`. Raise `ValueError` with message `f"Score must be 1-5, got {score}"` if not.

2. **INV-KK-REVIEW-VERDICT-ENUM:** Validate `verdict in VALID_VERDICTS`. Raise `ValueError` with message listing valid values if not.

3. **INV-KK-REVIEW-RATIONALE-REQUIRED:** Validate `rationale.strip()` is non-empty. Raise `ValueError("Rationale must be non-empty (INV-KK-REVIEW-RATIONALE-REQUIRED)")`.

4. **INV-KK-REVIEW-SOURCE-EXISTS:** Query `SELECT id, kind FROM nodes WHERE id = ? AND kind = 'Source'` with `(source_id,)`. Raise `ValueError(f"Source node '{source_id}' does not exist")` if None.

5. **INV-KK-REVIEW-SINGLE-PER-REVIEWER:** Query all existing `reviewed-by` edges from this source, join to HumanReview nodes, check if any have `reviewer` matching the current reviewer:
   ```sql
   SELECT 1 FROM edges e
   JOIN nodes n ON e.target_id = n.id
   WHERE e.kind = 'reviewed-by'
   AND e.source_id = ?
   AND n.kind = 'HumanReview'
   AND json_extract(n.attrs, '$.reviewer') = ?
   LIMIT 1
   ```
   Raise `ValueError(f"Source '{source_id}' already reviewed by '{reviewer}' (INV-KK-REVIEW-SINGLE-PER-REVIEWER)")` if exists.

6. Generate ID: `review_id = f"hrev-{uuid.uuid4().hex[:12]}"`

7. Create node:
   ```python
   add_node(conn, review_id, "HumanReview", {
       "reviewer": reviewer,
       "score": score,
       "verdict": verdict,
       "rationale": rationale.strip(),
       "review_date": date.today().isoformat(),
       "artifact_class": "human-review",
   })
   ```

8. Create edge: `add_edge(conn, "reviewed-by", source_id, review_id)`

9. Validate: `violations = validate_node(conn, review_id, "HumanReview")`. Raise `RuntimeError` if violations.

10. Return `PaperReviewResult(review_id, source_id, reviewer, score, verdict, rationale.strip())`

### Task 1.3: CLI Entry Point (src/ingest/cli_score.py) — NEW FILE

Create `src/ingest/cli_score.py` with:

**main() function:**

Arguments:
- `--db` (required): Path to master SQLite database
- `--source-id` (required): Source node ID to review
- `--score` (required, type=int): Impact score 1-5
- `--verdict` (required, choices=["accept", "reject", "skip"]): Review verdict
- `--rationale` (required): Assessment rationale text
- `--reviewer` (required): Reviewer identifier (name or email)

Flow:
1. Parse args
2. `conn = init_db(Path(args.db))`
3. Try `result = review_paper(conn, args.source_id, args.reviewer, args.score, args.verdict, args.rationale)`
4. `conn.commit()`
5. Print JSON: `{"review_id", "source_id", "reviewer", "score", "verdict", "rationale"}`
6. Catch `ValueError` → print to stderr, exit 1
7. Catch other `Exception` → print to stderr, exit 2

### Task 1.4: Unit Tests (tests/test_paper_scorer.py) — NEW FILE

Create `tests/test_paper_scorer.py` modeled on `tests/test_ingest_reviewer.py`.

Test cases:
1. **Happy path:** create a Source node, call `review_paper()`, verify HumanReview node exists, verify `reviewed-by` edge exists, verify returned `PaperReviewResult` fields
2. **INV-KK-REVIEW-SCORE-RANGE:** score=0 raises ValueError, score=6 raises ValueError, score=3 succeeds
3. **INV-KK-REVIEW-VERDICT-ENUM:** verdict="maybe" raises ValueError, verdict="accept" succeeds
4. **INV-KK-REVIEW-RATIONALE-REQUIRED:** empty string raises ValueError, whitespace-only raises ValueError
5. **INV-KK-REVIEW-SOURCE-EXISTS:** non-existent source_id raises ValueError
6. **INV-KK-REVIEW-SINGLE-PER-REVIEWER:** same reviewer on same source raises ValueError; different reviewer on same source succeeds; same reviewer on different source succeeds

Test fixture: use `init_db()` with `:memory:` database, pre-insert a Source node with required attrs.

### Task 1.5: Spec Nodes (via ril apply-batch)

Create these spec nodes:

1. **MOD-KK-REVIEW** (module): "Human review subsystem: CLI and batch interfaces for scoring papers, storing reviewer judgments as graph nodes."
   - language: "py"

2. **IFC-KK-HUMAN-REVIEW** (interface): "HumanReview node schema — graph representation of a reviewer's judgment on a Source. Fields: reviewer (str), score (int 1-5), verdict (accept|reject|skip), rationale (str), review_date (ISO date), artifact_class (str). Linked via reviewed-by edge."

3. **IFC-KK-REVIEW-RESULT** (interface): "Return type from review_paper(). Fields: review_id, source_id, reviewer, score, verdict, rationale."

4. **INV-KK-REVIEW-SCORE-RANGE** (invariant):
   - predicate: `forall r : HumanReview. r.score in {1, 2, 3, 4, 5}`
   - predicateNL: "Score must be an integer between 1 and 5 inclusive."
   - invariantStrength: "strong"
   - enforcementBasis: "runtime"
   - enforced: {}

5. **INV-KK-REVIEW-VERDICT-ENUM** (invariant):
   - predicate: `forall r : HumanReview. r.verdict in {"accept", "reject", "skip"}`
   - predicateNL: "Verdict must be one of accept, reject, or skip."
   - invariantStrength: "strong"
   - enforcementBasis: "runtime"
   - enforced: {}

6. **INV-KK-REVIEW-SINGLE-PER-REVIEWER** (invariant):
   - predicate: `forall (s : Source, reviewer : string). count(reviewed-by edges from s where target.reviewer = reviewer) <= 1`
   - predicateNL: "A given reviewer may review a given Source at most once."
   - invariantStrength: "strong"
   - enforcementBasis: "runtime"
   - enforced: {}

7. **INV-KK-REVIEW-SOURCE-EXISTS** (invariant):
   - predicate: `forall r : HumanReview. exists s : Source. edge(kind="reviewed-by", source=s, target=r)`
   - predicateNL: "Every HumanReview must be linked to an existing Source node."
   - invariantStrength: "strong"
   - enforcementBasis: "runtime"
   - enforced: {}

8. **INV-KK-REVIEW-RATIONALE-REQUIRED** (invariant):
   - predicate: `forall r : HumanReview. r.rationale.strip() != ""`
   - predicateNL: "Rationale text must be non-empty after trimming whitespace."
   - invariantStrength: "strong"
   - enforcementBasis: "runtime"
   - enforced: {}

9. **ALG-KK-REVIEW-PAPER** (algorithm):
   - preconditionNL: "source_id exists as Source, score in 1-5, verdict in {accept, reject, skip}, rationale non-empty, no existing review by same reviewer for this source."
   - postconditionNL: "HumanReview node created with hrev- prefix, reviewed-by edge from Source to HumanReview, PaperReviewResult returned. All five review invariants enforced at runtime."

10. **ALG-KK-REVIEW-CLI** (algorithm):
    - preconditionNL: "Valid CLI arguments: --db (path), --source-id, --score (int), --verdict (choice), --rationale (str), --reviewer (str)."
    - postconditionNL: "JSON output to stdout with review_id, source_id, reviewer, score, verdict, rationale. Exit 0 on success, 1 on validation error, 2 on DB error."

Edges to create:
- MOD-KK-REVIEW --contains--> IFC-KK-HUMAN-REVIEW
- MOD-KK-REVIEW --contains--> IFC-KK-REVIEW-RESULT
- MOD-KK-REVIEW --contains--> INV-KK-REVIEW-SCORE-RANGE
- MOD-KK-REVIEW --contains--> INV-KK-REVIEW-VERDICT-ENUM
- MOD-KK-REVIEW --contains--> INV-KK-REVIEW-SINGLE-PER-REVIEWER
- MOD-KK-REVIEW --contains--> INV-KK-REVIEW-SOURCE-EXISTS
- MOD-KK-REVIEW --contains--> INV-KK-REVIEW-RATIONALE-REQUIRED
- MOD-KK-REVIEW --contains--> ALG-KK-REVIEW-PAPER
- MOD-KK-REVIEW --contains--> ALG-KK-REVIEW-CLI
- ALG-KK-REVIEW-PAPER --enforces--> INV-KK-REVIEW-SCORE-RANGE
- ALG-KK-REVIEW-PAPER --enforces--> INV-KK-REVIEW-VERDICT-ENUM
- ALG-KK-REVIEW-PAPER --enforces--> INV-KK-REVIEW-SINGLE-PER-REVIEWER
- ALG-KK-REVIEW-PAPER --enforces--> INV-KK-REVIEW-SOURCE-EXISTS
- ALG-KK-REVIEW-PAPER --enforces--> INV-KK-REVIEW-RATIONALE-REQUIRED

---

## Phase 2: Batch Import/Export

**Spec nodes created:** 4
**Files:** 1 new
**Spec conflicts:** None
**Dependencies:** Phase 1 complete

### Task 2.1: Batch Score Module (src/ingest/batch_score.py) — NEW FILE

**BatchImportReport dataclass:**
```python
@dataclass
class BatchImportReport:
    imported: int
    skipped: int
    errors: list  # [{source_id: str, reason: str}]
```

**parse_review_list(file_path) function:**

Parses `paper_review_list.txt` format. For each paper block:
1. Extract `Title:` line value
2. Extract `Decision:` line — check if `[X] ACCEPT` or `[X] REJECT` is marked
3. Extract `Notes:` line value (may span multiple lines until the `---` separator)
4. Skip papers where Decision has no `[X]` mark (unreviewed)
5. Return list of `{"title": str, "verdict": "accept"|"reject", "notes": str}`

Parsing rules:
- Paper blocks are delimited by `--- Paper N/M ---` headers
- Each block ends at `--------------------------------------------------------------------------------`
- Title is on the line starting with `Title:` (strip leading whitespace after colon)
- Decision line: `[X] ACCEPT` means verdict="accept", `[X] REJECT` means verdict="reject"
- Notes may contain an explicit score: if notes contain `Score: N` (where N is 1-5), use that as score; otherwise derive from verdict: accept=4, reject=1, skip=3
- Notes text (minus any `Score: N` prefix) becomes the rationale

**import_reviews(conn, file_path, reviewer) function:**

1. Call `parse_review_list(file_path)` to get parsed entries
2. For each entry with a marked decision:
   a. Look up Source by title: `SELECT id FROM nodes WHERE kind = 'Source' AND json_extract(attrs, '$.title') = ?`
   b. If no Source found, add to errors list: `{"title": entry["title"], "reason": "Source not found by title"}`
   c. If Source found, try `review_paper(conn, source_id, reviewer, score, verdict, rationale)`
   d. If `ValueError` (e.g., duplicate review), increment skipped count — this makes import idempotent (INV-KK-REVIEW-BATCH-IDEMPOTENT)
   e. If success, increment imported count
3. Return `BatchImportReport(imported, skipped, errors)`

**export_review_list(conn, output_path) function:**

1. Query all research-type Source nodes: `SELECT id, attrs FROM nodes WHERE kind = 'Source' AND json_extract(attrs, '$.source_type') IN ('paper', 'preprint', 'conference-paper', 'conference-proceedings') ORDER BY json_extract(attrs, '$.published_date') DESC`
2. For each Source, check for existing review: `SELECT n.attrs FROM edges e JOIN nodes n ON e.target_id = n.id WHERE e.kind = 'reviewed-by' AND e.source_id = ? AND n.kind = 'HumanReview' LIMIT 1`
3. Write in the same format as `paper_review_list.txt`:
   - If reviewed: `Decision: [X] ACCEPT` or `[X] REJECT` filled in, Notes populated with rationale and `Score: N`
   - If not reviewed: `Decision: [ ] ACCEPT  [ ] REJECT` (empty)

**CLI entry in same file:**

```python
def main():
    parser = argparse.ArgumentParser(prog="kk-batch-score")
    sub = parser.add_subparsers(dest="command")

    imp = sub.add_parser("import")
    imp.add_argument("--db", required=True)
    imp.add_argument("--file", required=True)
    imp.add_argument("--reviewer", required=True)

    exp = sub.add_parser("export")
    exp.add_argument("--db", required=True)
    exp.add_argument("--output", required=True)
```

### Task 2.2: Spec Nodes (via ril apply-batch)

Create these spec nodes:

1. **IFC-KK-REVIEW-BATCH-REPORT** (interface): "Return type from batch import. Fields: imported (int), skipped (int), errors (list of {title, reason})."

2. **INV-KK-REVIEW-BATCH-IDEMPOTENT** (invariant):
   - predicate: `forall batch_import(file). batch_import(file); batch_import(file) ≡ batch_import(file)`
   - predicateNL: "Running batch import twice on the same file produces the same DB state. Duplicate reviews are skipped, not created."
   - invariantStrength: "strong"
   - enforcementBasis: "runtime"
   - enforced: {}

3. **ALG-KK-REVIEW-BATCH-IMPORT** (algorithm):
   - preconditionNL: "File path exists, DB open, reviewer identifier provided."
   - postconditionNL: "BatchImportReport returned. Papers with marked decisions have HumanReview nodes created. Already-reviewed papers skipped. Title-unmatched papers listed in errors. INV-KK-REVIEW-BATCH-IDEMPOTENT holds."

4. **ALG-KK-REVIEW-BATCH-EXPORT** (algorithm):
   - preconditionNL: "DB open, output path writable."
   - postconditionNL: "Text file written in paper_review_list.txt format. Reviewed papers show filled Decision and Notes with score. Unreviewed papers show empty checkboxes."

Edges to create:
- MOD-KK-REVIEW --contains--> IFC-KK-REVIEW-BATCH-REPORT
- MOD-KK-REVIEW --contains--> INV-KK-REVIEW-BATCH-IDEMPOTENT
- MOD-KK-REVIEW --contains--> ALG-KK-REVIEW-BATCH-IMPORT
- MOD-KK-REVIEW --contains--> ALG-KK-REVIEW-BATCH-EXPORT

---

## Phase 3: Web UI for Scoring

**Spec nodes created:** 4
**Files:** 2 modified, 1 new template
**Spec conflicts:** YES — introduces first POST endpoint
**Dependencies:** Phase 1 complete

### DECISION REQUIRED BEFORE IMPLEMENTATION

The web layer currently has zero POST endpoints. Adding `POST /api/review/{source_id}` creates the first write path. The code comments reference `INV-KK-WEB-READ-ONLY` but this invariant does not exist as a formal spec node.

**Options:**

A. **Add INV-KK-WEB-REVIEW-WRITE-SCOPED** — permits POST only at `/api/review/*` paths. All other routes remain GET-only. This is a new invariant, not a relaxation of an existing one (since the formal invariant doesn't exist yet).

B. **Skip Phase 3** — CLI-only scoring (Phases 1+2+4 still work). Users score papers via command line or batch file only.

C. **Separate write app** — A second FastAPI app on a different port that handles review POST endpoints. The main app stays pure GET.

**Recommendation:** Option A. The formal invariant `INV-KK-WEB-READ-ONLY` doesn't exist in the spec DAG, so we're adding a scoped write permission rather than relaxing an existing constraint. The code comment can be updated to reference the new invariant.

### Task 3.1: Review Submit Endpoint (src/web/routes.py)

Add inside `setup_routes()`:

```python
@app.post("/api/review/{source_id}")
async def submit_review(request: Request, source_id: str):
    body = await request.json()
    conn = request.app.state.conn
    # Validate required fields present: score, verdict, rationale, reviewer
    # Call review_paper(conn, source_id, body["reviewer"],
    #     body["score"], body["verdict"], body["rationale"])
    # conn.commit()
    # Return JSONResponse with 201 status
    # Catch ValueError -> 422 (validation) or 404 (source not found) or 409 (duplicate)
```

Error responses:
- 404: Source not found (`{"error": "Source node not found"}`)
- 409: Duplicate review by same reviewer (`{"error": "Already reviewed by this reviewer"}`)
- 422: Validation error — score out of range, bad verdict, empty rationale (`{"error": "<specific message>"}`)

Import needed: `from ingest.paper_scorer import review_paper`

### Task 3.2: Review Status Endpoint (src/web/routes.py)

Add inside `setup_routes()`:

```python
@app.get("/api/review/{source_id}")
async def review_status(request: Request, source_id: str):
    conn = request.app.state.conn
    # Verify source exists
    # Query: SELECT n.attrs FROM edges e JOIN nodes n ON e.target_id = n.id
    #        WHERE e.kind = 'reviewed-by' AND e.source_id = ?
    #        AND n.kind = 'HumanReview'
    # Parse each row's attrs JSON
    # Return JSONResponse with list of {reviewer, score, verdict, rationale, review_date}
```

### Task 3.3: Extend Paper Detail Page

**src/web/routes.py — paper_detail() handler (line 1117):**

Add after existing queries, before `return templates.TemplateResponse(...)`:

```python
# Fetch existing reviews for this paper
review_rows = conn.execute(
    "SELECT n.attrs FROM edges e JOIN nodes n ON e.target_id = n.id "
    "WHERE e.kind = 'reviewed-by' AND e.source_id = ? AND n.kind = 'HumanReview'",
    (source_id,),
).fetchall()
existing_reviews = []
for rr in review_rows:
    r_attrs = json.loads(rr[0]) if isinstance(rr[0], str) else (rr[0] or {})
    existing_reviews.append({
        "reviewer": r_attrs.get("reviewer", ""),
        "score": r_attrs.get("score", 0),
        "verdict": r_attrs.get("verdict", ""),
        "rationale": r_attrs.get("rationale", ""),
        "review_date": r_attrs.get("review_date", ""),
    })
```

Add `"existing_reviews": existing_reviews` to the template context dict.

**src/web/templates/paper_detail.html:**

Add new section after `{# --- PAPER EVIDENCE --- #}` block (after line 173, before `{% endblock %}`):

```html
{# --- HUMAN REVIEW --- #}
<div class="attrs-section">
  <h3>Human Review</h3>
  {% if existing_reviews %}
    {% for rev in existing_reviews %}
    <div class="card" style="margin-bottom:0.5rem;">
      <div style="display:flex;justify-content:space-between;align-items:baseline;">
        <span>
          <span class="badge" style="background:
            {% if rev.verdict == 'accept' %}#27ae60
            {% elif rev.verdict == 'reject' %}#c0392b
            {% else %}#7f8c8d{% endif %};">{{ rev.verdict }}</span>
          <strong>{{ rev.score }}/5</strong>
        </span>
        <span style="font-size:0.85em;color:#888;">
          {{ rev.reviewer }} &middot; {{ rev.review_date }}
        </span>
      </div>
      <p style="margin:0.3em 0 0 0;font-size:0.9em;">{{ rev.rationale }}</p>
    </div>
    {% endfor %}
  {% else %}
    <p style="color:#888;">No reviews yet.</p>
  {% endif %}

  <details style="margin-top:1rem;">
    <summary style="cursor:pointer;font-weight:bold;">Submit Review</summary>
    <form id="review-form" style="margin-top:0.5rem;">
      <div style="margin-bottom:0.5rem;">
        <label>Reviewer:</label>
        <input type="text" name="reviewer" required
               style="font-family:monospace;padding:0.2rem 0.4rem;width:100%;">
      </div>
      <div style="margin-bottom:0.5rem;">
        <label>Impact Score:</label>
        <input type="range" name="score" min="1" max="5" value="3"
               oninput="this.nextElementSibling.textContent=this.value">
        <span>3</span>/5
      </div>
      <div style="margin-bottom:0.5rem;">
        <label>Verdict:</label>
        <label><input type="radio" name="verdict" value="accept"> Accept</label>
        <label><input type="radio" name="verdict" value="reject"> Reject</label>
        <label><input type="radio" name="verdict" value="skip"> Skip</label>
      </div>
      <div style="margin-bottom:0.5rem;">
        <label>Rationale:</label>
        <textarea name="rationale" rows="3" required
                  style="font-family:monospace;width:100%;padding:0.3rem;"></textarea>
      </div>
      <button type="submit" style="padding:0.3rem 1rem;">Submit</button>
      <span id="review-status" style="margin-left:0.5rem;font-size:0.85em;"></span>
    </form>
  </details>
</div>

<script>
document.getElementById('review-form').addEventListener('submit', async function(e) {
  e.preventDefault();
  const form = e.target;
  const status = document.getElementById('review-status');
  const data = {
    reviewer: form.reviewer.value,
    score: parseInt(form.score.value),
    verdict: form.querySelector('input[name="verdict"]:checked')?.value,
    rationale: form.rationale.value,
  };
  if (!data.verdict) { status.textContent = 'Select a verdict'; return; }
  try {
    const resp = await fetch('/api/review/{{ source.id }}', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data),
    });
    const result = await resp.json();
    if (resp.ok) {
      status.textContent = 'Saved';
      status.style.color = '#27ae60';
      setTimeout(() => location.reload(), 1000);
    } else {
      status.textContent = result.error || 'Error';
      status.style.color = '#c0392b';
    }
  } catch (err) {
    status.textContent = 'Network error';
    status.style.color = '#c0392b';
  }
});
</script>
```

### Task 3.4: Spec Nodes (via ril apply-batch)

Create these spec nodes:

1. **INV-KK-WEB-REVIEW-WRITE-SCOPED** (invariant):
   - predicate: `forall POST endpoint in MOD-KK-WEB. endpoint.path matches "/api/review/*"`
   - predicateNL: "Only review-related POST endpoints are permitted in the web layer. All other routes remain GET-only."
   - invariantStrength: "strong"
   - enforcementBasis: "structural"
   - enforced: {}

2. **ALG-KK-WEB-REVIEW-SUBMIT** (algorithm):
   - preconditionNL: "Valid JSON body with score (int 1-5), verdict (accept|reject|skip), rationale (non-empty string), reviewer (string). Source node exists."
   - postconditionNL: "HumanReview node created, 201 JSON response with review_id. 404 if source missing, 409 if duplicate reviewer, 422 if validation fails."

3. **ALG-KK-WEB-REVIEW-STATUS** (algorithm):
   - preconditionNL: "source_id parameter provided."
   - postconditionNL: "JSON array of existing reviews for this source: [{reviewer, score, verdict, rationale, review_date}]. Empty array if no reviews. 404 if source not found."

4. **ALG-KK-WEB-PAPER-DETAIL-REVIEW** (algorithm):
   - preconditionNL: "Paper detail page rendered for a valid Source."
   - postconditionNL: "Review section appended showing existing reviews (verdict badge, score, reviewer, date, rationale) and a collapsible review form. Form POSTs to /api/review/{source_id} via JavaScript fetch."

Edges to create:
- MOD-KK-WEB --contains--> INV-KK-WEB-REVIEW-WRITE-SCOPED
- MOD-KK-WEB --contains--> ALG-KK-WEB-REVIEW-SUBMIT
- MOD-KK-WEB --contains--> ALG-KK-WEB-REVIEW-STATUS
- MOD-KK-WEB --contains--> ALG-KK-WEB-PAPER-DETAIL-REVIEW
- ALG-KK-WEB-REVIEW-SUBMIT --depends-on--> ALG-KK-REVIEW-PAPER

---

## Phase 4: Integration into Existing Views

**Spec nodes created:** 2
**Files:** 4 modified (routes.py, feed.html, base.html) + 1 new (reviews.html)
**Spec conflicts:** None (all GET-only)
**Dependencies:** Phase 1 complete (Phase 3 optional)

### Task 4.1: Review Badge Query (src/web/routes.py)

Add a helper function inside `setup_routes()`:

```python
def _batch_review_status(conn, source_ids: list[str]) -> dict[str, dict]:
    """Batch-query review status for multiple sources. Returns {source_id: {avg_score, count, latest_verdict}}."""
    if not source_ids:
        return {}
    ph = ",".join("?" for _ in source_ids)
    rows = conn.execute(
        f"SELECT e.source_id, "
        f"json_extract(n.attrs, '$.score') as score, "
        f"json_extract(n.attrs, '$.verdict') as verdict "
        f"FROM edges e JOIN nodes n ON e.target_id = n.id "
        f"WHERE e.kind = 'reviewed-by' AND n.kind = 'HumanReview' "
        f"AND e.source_id IN ({ph})",
        source_ids,
    ).fetchall()
    result = {}
    for sid, score, verdict in rows:
        if sid not in result:
            result[sid] = {"scores": [], "verdicts": []}
        result[sid]["scores"].append(score)
        result[sid]["verdicts"].append(verdict)
    for sid, data in result.items():
        scores = [s for s in data["scores"] if s is not None]
        result[sid] = {
            "avg_score": sum(scores) / len(scores) if scores else 0,
            "count": len(data["scores"]),
            "latest_verdict": data["verdicts"][0] if data["verdicts"] else None,
        }
    return result
```

This satisfies INV-KK-WEB-QUERY-BOUNDED: one batch query for all source IDs on the current page, not a per-paper query.

### Task 4.2: Feed Page Badge (src/web/routes.py + src/web/templates/feed.html)

**routes.py — research_feed() handler (line 852):**

After computing `items` list and before `return templates.TemplateResponse(...)`, add:

```python
feed_sids = [item["source_id"] for item in items]
review_status = _batch_review_status(conn, feed_sids)
for item in items:
    item["review"] = review_status.get(item["source_id"])
```

Add `"review_status_available": True` to the template context (so the template can conditionally render the column).

**feed.html:**

Add a "Review" column header after "Actions" in the thead:
```html
<th style="width:8%;">Review</th>
```

Add column in each row:
```html
<td>
  {% if item.review %}
    <span class="badge" style="background:
      {% if item.review.latest_verdict == 'accept' %}#27ae60
      {% elif item.review.latest_verdict == 'reject' %}#c0392b
      {% else %}#7f8c8d{% endif %};">
      {{ item.review.avg_score|round(1) }}/5
    </span>
  {% else %}
    <span style="color:#ccc;">—</span>
  {% endif %}
</td>
```

### Task 4.3: Radar Page Badge (src/web/routes.py)

**routes.py — radar() handler (line 1297):**

After building `by_concept` dict, batch-query review status for all source IDs:

```python
all_sids = [row[0] for row in rows]
review_status = _batch_review_status(conn, all_sids)
```

Then when building each paper entry in the loop, add:
```python
entry["papers"][-1]["review"] = review_status.get(sid)
```

Update `src/web/templates/radar.html` to show the badge next to each paper title.

### Task 4.4: Reviews List Page (src/web/routes.py + src/web/templates/reviews.html)

**routes.py — new route:**

```python
@app.get("/reviews", response_class=HTMLResponse)
async def reviews_list(
    request: Request,
    verdict: str | None = None,
    min_score: int | None = Query(None, ge=1, le=5),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
):
    conn = request.app.state.conn
    # Base query: HumanReview nodes joined to Source via reviewed-by
    sql = (
        "SELECT n.id, n.attrs, s.id as source_id, s.attrs as source_attrs "
        "FROM nodes n "
        "JOIN edges e ON e.kind = 'reviewed-by' AND e.target_id = n.id "
        "JOIN nodes s ON s.id = e.source_id AND s.kind = 'Source' "
        "WHERE n.kind = 'HumanReview'"
    )
    params = []
    if verdict:
        sql += " AND json_extract(n.attrs, '$.verdict') = ?"
        params.append(verdict)
    if min_score is not None:
        sql += " AND CAST(json_extract(n.attrs, '$.score') AS INTEGER) >= ?"
        params.append(min_score)
    sql += " ORDER BY json_extract(n.attrs, '$.review_date') DESC"
    sql += " LIMIT ? OFFSET ?"
    params.extend([per_page + 1, (page - 1) * per_page])

    rows = conn.execute(sql, params).fetchall()
    has_next = len(rows) > per_page
    rows = rows[:per_page]

    reviews = []
    for r in rows:
        r_attrs = json.loads(r[1]) if isinstance(r[1], str) else (r[1] or {})
        s_attrs = json.loads(r[3]) if isinstance(r[3], str) else (r[3] or {})
        reviews.append({
            "review_id": r[0],
            "source_id": r[2],
            "paper_title": s_attrs.get("title", r[2]),
            "reviewer": r_attrs.get("reviewer", ""),
            "score": r_attrs.get("score", 0),
            "verdict": r_attrs.get("verdict", ""),
            "rationale": r_attrs.get("rationale", ""),
            "review_date": r_attrs.get("review_date", ""),
        })

    return templates.TemplateResponse(
        request, "reviews.html",
        {"reviews": reviews, "page": page, "per_page": per_page,
         "has_next": has_next, "verdict_filter": verdict,
         "min_score_filter": min_score},
    )
```

**reviews.html — NEW TEMPLATE:**

Extends `base.html`. Contains:
- Filter controls: verdict dropdown (all/accept/reject/skip), min score dropdown
- Table: Date, Paper, Reviewer, Score, Verdict, Rationale
- Pagination at bottom
- Paper titles link to `/paper/{source_id}`

### Task 4.5: Nav Bar Update (src/web/templates/base.html)

Add "Reviews" link to nav bar at line 52, after the "Radar" link:

```html
<a href="/reviews">Reviews</a>
```

### Task 4.6: Spec Nodes (via ril apply-batch)

Create these spec nodes:

1. **ALG-KK-WEB-FEED-REVIEW-BADGE** (algorithm):
   - preconditionNL: "Page source IDs computed for feed or radar view."
   - postconditionNL: "Review status badge rendered per paper showing average score and verdict color. Single batch query for all source IDs on current page. INV-KK-WEB-QUERY-BOUNDED satisfied."

2. **ALG-KK-WEB-REVIEWS-LIST** (algorithm):
   - preconditionNL: "DB open. Optional filters: verdict, min_score."
   - postconditionNL: "Paginated HTML table of all reviews sorted by review_date descending. Filterable by verdict and minimum score. Paper titles link to /paper/{source_id}. INV-KK-WEB-QUERY-BOUNDED satisfied via SQL LIMIT/OFFSET."

Edges to create:
- MOD-KK-WEB --contains--> ALG-KK-WEB-FEED-REVIEW-BADGE
- MOD-KK-WEB --contains--> ALG-KK-WEB-REVIEWS-LIST
- ALG-KK-WEB-FEED-REVIEW-BADGE --satisfies--> INV-KK-WEB-QUERY-BOUNDED
- ALG-KK-WEB-REVIEWS-LIST --satisfies--> INV-KK-WEB-QUERY-BOUNDED

---

## Implementation Order for /cb-green Commands

Each line below is one `/cb-green` invocation:

1. `/cb-green` — Phase 1 spec nodes: create MOD-KK-REVIEW module and all Phase 1 spec nodes (IFC-KK-HUMAN-REVIEW, IFC-KK-REVIEW-RESULT, 5 invariants, ALG-KK-REVIEW-PAPER, ALG-KK-REVIEW-CLI) with edges via ril apply-batch
2. `/cb-green` — Phase 1 code: schema.py changes + paper_scorer.py + cli_score.py + test_paper_scorer.py
3. `/cb-green` — Phase 2 spec nodes: create IFC-KK-REVIEW-BATCH-REPORT, INV-KK-REVIEW-BATCH-IDEMPOTENT, ALG-KK-REVIEW-BATCH-IMPORT, ALG-KK-REVIEW-BATCH-EXPORT with edges
4. `/cb-green` — Phase 2 code: batch_score.py
5. `/cb-green` — Phase 3 spec nodes: create INV-KK-WEB-REVIEW-WRITE-SCOPED, ALG-KK-WEB-REVIEW-SUBMIT, ALG-KK-WEB-REVIEW-STATUS, ALG-KK-WEB-PAPER-DETAIL-REVIEW with edges (DECISION REQUIRED on Option A/B/C before this)
6. `/cb-green` — Phase 3 code: POST endpoint in routes.py + paper_detail.html review section
7. `/cb-green` — Phase 4 spec nodes: create ALG-KK-WEB-FEED-REVIEW-BADGE, ALG-KK-WEB-REVIEWS-LIST with edges
8. `/cb-green` — Phase 4 code: _batch_review_status helper, feed/radar badge integration, reviews.html template, base.html nav update

---

## Complete File Manifest

| File | Action | Phase | Description |
|------|--------|-------|-------------|
| `src/graph/schema.py` | MODIFY | 1 | Add HumanReview to NODE_KINDS, REQUIRED_ATTRS, ID_PREFIXES; add reviewed-by to EDGE_KINDS, EDGE_VALID_PAIRS; add review_date to DATE_ATTRS |
| `src/ingest/paper_scorer.py` | NEW | 1 | review_paper() + PaperReviewResult dataclass |
| `src/ingest/cli_score.py` | NEW | 1 | CLI entry point for single-paper scoring |
| `tests/test_paper_scorer.py` | NEW | 1 | Unit tests for all 5 invariants + happy path |
| `src/ingest/batch_score.py` | NEW | 2 | Batch import/export + BatchImportReport + CLI |
| `src/web/routes.py` | MODIFY | 3,4 | POST /api/review, GET /api/review, GET /reviews, _batch_review_status helper, extend paper_detail/feed/radar handlers |
| `src/web/templates/paper_detail.html` | MODIFY | 3 | Review display section + review form with JS |
| `src/web/templates/feed.html` | MODIFY | 4 | Review badge column |
| `src/web/templates/reviews.html` | NEW | 4 | Paginated review list with filters |
| `src/web/templates/base.html` | MODIFY | 4 | Add Reviews link to nav |

## Complete Spec Node Manifest

| ID | Kind | Module | Phase |
|----|------|--------|-------|
| MOD-KK-REVIEW | module | — | 1 |
| IFC-KK-HUMAN-REVIEW | interface | MOD-KK-REVIEW | 1 |
| IFC-KK-REVIEW-RESULT | interface | MOD-KK-REVIEW | 1 |
| IFC-KK-REVIEW-BATCH-REPORT | interface | MOD-KK-REVIEW | 2 |
| INV-KK-REVIEW-SCORE-RANGE | invariant | MOD-KK-REVIEW | 1 |
| INV-KK-REVIEW-VERDICT-ENUM | invariant | MOD-KK-REVIEW | 1 |
| INV-KK-REVIEW-SINGLE-PER-REVIEWER | invariant | MOD-KK-REVIEW | 1 |
| INV-KK-REVIEW-SOURCE-EXISTS | invariant | MOD-KK-REVIEW | 1 |
| INV-KK-REVIEW-RATIONALE-REQUIRED | invariant | MOD-KK-REVIEW | 1 |
| INV-KK-REVIEW-BATCH-IDEMPOTENT | invariant | MOD-KK-REVIEW | 2 |
| INV-KK-WEB-REVIEW-WRITE-SCOPED | invariant | MOD-KK-WEB | 3 |
| ALG-KK-REVIEW-PAPER | algorithm | MOD-KK-REVIEW | 1 |
| ALG-KK-REVIEW-CLI | algorithm | MOD-KK-REVIEW | 1 |
| ALG-KK-REVIEW-BATCH-IMPORT | algorithm | MOD-KK-REVIEW | 2 |
| ALG-KK-REVIEW-BATCH-EXPORT | algorithm | MOD-KK-REVIEW | 2 |
| ALG-KK-WEB-REVIEW-SUBMIT | algorithm | MOD-KK-WEB | 3 |
| ALG-KK-WEB-REVIEW-STATUS | algorithm | MOD-KK-WEB | 3 |
| ALG-KK-WEB-PAPER-DETAIL-REVIEW | algorithm | MOD-KK-WEB | 3 |
| ALG-KK-WEB-FEED-REVIEW-BADGE | algorithm | MOD-KK-WEB | 4 |
| ALG-KK-WEB-REVIEWS-LIST | algorithm | MOD-KK-WEB | 4 |

## Complete Edge Manifest

| From | Kind | To | Phase |
|------|------|----|-------|
| MOD-KK-REVIEW | contains | IFC-KK-HUMAN-REVIEW | 1 |
| MOD-KK-REVIEW | contains | IFC-KK-REVIEW-RESULT | 1 |
| MOD-KK-REVIEW | contains | INV-KK-REVIEW-SCORE-RANGE | 1 |
| MOD-KK-REVIEW | contains | INV-KK-REVIEW-VERDICT-ENUM | 1 |
| MOD-KK-REVIEW | contains | INV-KK-REVIEW-SINGLE-PER-REVIEWER | 1 |
| MOD-KK-REVIEW | contains | INV-KK-REVIEW-SOURCE-EXISTS | 1 |
| MOD-KK-REVIEW | contains | INV-KK-REVIEW-RATIONALE-REQUIRED | 1 |
| MOD-KK-REVIEW | contains | ALG-KK-REVIEW-PAPER | 1 |
| MOD-KK-REVIEW | contains | ALG-KK-REVIEW-CLI | 1 |
| ALG-KK-REVIEW-PAPER | enforces | INV-KK-REVIEW-SCORE-RANGE | 1 |
| ALG-KK-REVIEW-PAPER | enforces | INV-KK-REVIEW-VERDICT-ENUM | 1 |
| ALG-KK-REVIEW-PAPER | enforces | INV-KK-REVIEW-SINGLE-PER-REVIEWER | 1 |
| ALG-KK-REVIEW-PAPER | enforces | INV-KK-REVIEW-SOURCE-EXISTS | 1 |
| ALG-KK-REVIEW-PAPER | enforces | INV-KK-REVIEW-RATIONALE-REQUIRED | 1 |
| MOD-KK-REVIEW | contains | IFC-KK-REVIEW-BATCH-REPORT | 2 |
| MOD-KK-REVIEW | contains | INV-KK-REVIEW-BATCH-IDEMPOTENT | 2 |
| MOD-KK-REVIEW | contains | ALG-KK-REVIEW-BATCH-IMPORT | 2 |
| MOD-KK-REVIEW | contains | ALG-KK-REVIEW-BATCH-EXPORT | 2 |
| MOD-KK-WEB | contains | INV-KK-WEB-REVIEW-WRITE-SCOPED | 3 |
| MOD-KK-WEB | contains | ALG-KK-WEB-REVIEW-SUBMIT | 3 |
| MOD-KK-WEB | contains | ALG-KK-WEB-REVIEW-STATUS | 3 |
| MOD-KK-WEB | contains | ALG-KK-WEB-PAPER-DETAIL-REVIEW | 3 |
| ALG-KK-WEB-REVIEW-SUBMIT | depends-on | ALG-KK-REVIEW-PAPER | 3 |
| MOD-KK-WEB | contains | ALG-KK-WEB-FEED-REVIEW-BADGE | 4 |
| MOD-KK-WEB | contains | ALG-KK-WEB-REVIEWS-LIST | 4 |
| ALG-KK-WEB-FEED-REVIEW-BADGE | satisfies | INV-KK-WEB-QUERY-BOUNDED | 4 |
| ALG-KK-WEB-REVIEWS-LIST | satisfies | INV-KK-WEB-QUERY-BOUNDED | 4 |
