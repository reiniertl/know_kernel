# Implementation Plan: Venue Viewer, Venue Editor, and Retirement of `/sources`

**Created:** 2026-09-14
**Revised:** 2026-09-15 — every work package executed; D-1 and D-2 answered; §9
reconciled against the commits that actually landed.
**Status:** COMPLETE. WP0 ✅, WP0.5 ✅ (`d0200bd`), WP1 ✅ (`da66f41`), WP2+WP6 ✅
(`068915f`), WP3 ✅ (`5826796`), WP4 ✅ (`7a59e59`), WP5 ✅ (`be361fb` radar repair,
`cac9860` viewer and editor), WP7 ✅ (`f22ecd0`), WP8 ✅ (`09bf666`). D-1 and D-2 are
answered — see §14. Suite: **1,360 passing, 0 failures.**
**Source audits:**
- silk run `cb-audit-venue-viewer-01` (cb-audit, FINAL_STATUS SUCCESS, 6 stages, 0 violations) — scope and first-pass findings
- silk run `cb-audit-venue-plan-02` (cb-audit, FINAL_STATUS SUCCESS, 6 stages, 0 violations) — full-file analysis, this plan

**Scope:** Replace the `/sources` page with a venue-organised viewer modelled on `/radar`;
add a venue editor; author the missing `MOD-KK-WEB` and venue spec nodes; repair the
pre-existing damage that blocks the work.
**Prerequisite:** WP0 (pytest install) — see §7.
**Blocking decisions:** both answered, in §14. D-1 = Option A (`Venue` as a
first-class node kind); D-2 = admin for merge, any authenticated user for a
single-Source edit.

---

## 0. How to use this document

This plan is written to be executed in a **future session with no memory of the
conversation that produced it**. Every fact was verified by reading the repository
on 2026-09-14; re-verification commands are in §12.

Work packages WP0–WP8 in §7 map onto future `/cb-*` invocations. §15 gives the
sequence and says which packages parallelise. Do not collapse packages: each ends
at a stated exit criterion.

**Read §2 before proposing any code.** The web module is not in the state its tests
and docstrings claim, and two of the findings will otherwise be discovered mid-task.

---

## 1. Requirement, as stated by the operator

> "I need to change the way the sources page is handled. We need to move it to contain
> the venues data and behave similar to what the radar page looks like. One entry per
> venue and within it the papers linked to the venue. I also need a venue editor as
> part of this process. Basically the current 'sources' will be replaced by a venue
> viewer similar to the radar but organized by venue. It is important this process
> covers the proper specification work needed."

Decomposed:

| # | Requirement | Work package |
|---|---|---|
| R1 | Retire the current `/sources` page | WP5 |
| R2 | New page: one entry per venue | WP4 (spec), WP5 (code) |
| R3 | Papers linked to a venue nested inside that venue entry | WP4, WP5 |
| R4 | Behaves/looks like `/radar` (expand-collapse hierarchy) | WP5 |
| R5 | A venue editor | WP2 (repr.), WP4 (spec), WP5 (code), WP6 (authz) |
| R6 | Proper specification work, DAG-first | WP2, WP4, WP7 |

---

## 2. Verified baseline (state of the repo before this plan)

Everything in this section was verified on 2026-09-14 by reading whole files, not
by sampling. Files read in full: `src/web/routes.py` (1208 lines), `src/web/app.py`,
`src/web/templates/base.html`, `src/web/templates/concept_list.html`,
`src/web/templates/radar.html`, `src/authgate/app.py`, `src/graph/schema.py`,
`src/ingest/source_abstract.py`, `src/graph/engine.py` (CRUD half),
`src/graph/rules.py` (structure + rule bodies), plus the live DDL of
`data/master.db` and targeted full reads of `tests/test_web.py`.

### 2.1 Application shape

Two FastAPI apps. `src/authgate/app.py` `create_gate_app()` is the wall: it
registers `/login`, `/logout`, `/healthz`, `/admin/users*`, installs
`ALG-KK-AUTH-GATE` as the single middleware via `install_gate()`, then mounts the
knowledge app at `/` **last** (a Mount at `/` matches everything, so it must not
shadow the explicit routes).

`src/web/app.py` `create_app()` builds the inner app, opens `master.db` in its
lifespan (driven by the gate, since a mounted app receives no lifespan events of
its own), and calls `setup_routes(application, templates)`.

`start.sh` runs `authgate.app:app` — never `web.app:app`, which would serve the
knowledge app with no authentication at all (`INV-KK-AUTH-GATE-COVERS-MOUNT`).

### 2.2 Registered routes — the complete set

`src/web/routes.py` (26):

```
GET    /                                   GET    /concepts/{node_id}
GET    /sources                            GET    /graph
GET    /api/impact/{node_id}               GET    /api/compare/{id_a}/{id_b}
GET    /api/recommendations/{goal_id}      GET    /api/match
GET    /api/search                         GET    /api/diagnostics
GET    /health                             GET    /impact/{node_id}
GET    /feed                               GET    /api/feed/card/{source_id:path}
POST   /api/feed/send/{source_id:path}     GET    /paper/{source_id:path}
GET    /radar                              GET    /reviews
GET    /reviewers                          GET    /viz
POST   /api/reviewers                      POST   /api/review/{source_id:path}
PUT    /api/review/{review_id}             DELETE /api/review/{review_id}
PUT    /api/abstract/{source_id:path}      GET    /api/review/{source_id:path}
```

`src/authgate/app.py` (8): `GET/POST /login`, `POST /logout`, `GET /healthz`,
`GET/POST /admin/users`, `POST /admin/users/{username}/deactivate`,
`POST /admin/users/{username}/password`.

**There is no `/concepts` list route, no `/subsystems`, no `/research`, no `/vulns`,
no `/code-examples`.** See §2.6.

### 2.3 The `/sources` route being retired

`src/web/routes.py:240-261`. Full body:

- Query params `page` (≥1) and `per_page` (10–200, default 50).
- `SELECT id, kind, attrs FROM nodes WHERE kind = 'Source' ORDER BY id LIMIT ? OFFSET ?`
  with `per_page + 1` to compute `has_next`.
- Resolves `display_name` per node via `display_name_for_node`.
- Renders `concept_list.html` with `title="Sources"`, `active_kind="Source"`,
  `all_kinds=_all_kinds(conn)`, `page`, `per_page`, `has_next`.

Properties relevant to removal:

- **It has no docstring and no spec-node citation.** Every peer route carries one
  (`ALG-KK-WEB-RADAR`, `ALG-KK-WEB-FEED-LIST`, `ALG-KK-WEB-PAPER-DETAIL`,
  `ALG-KK-WEB-REVIEWS-LIST`, `ALG-KK-WEB-REVIEWERS-PAGE`, …). There is therefore
  **no spec node to supersede or retire** — the spec work is purely additive.
- **`concept_list.html` is rendered by exactly one route: this one.** Verified by
  grep across `src/` and `tests/`. It dies with the route.
- **Its kind-filter dropdown is already a dead control.** `concept_list.html` lines
  5–11 render a `<select>` whose `onchange` navigates to `?kind=VALUE`. `sources_list`
  accepts only `page` and `per_page` and hardcodes `kind = 'Source'`, so the parameter
  is silently ignored. (The dropdown was live when the All-Nodes list page existed;
  that page was removed in `67c4c99`.)
- Nav entry: `src/web/templates/base.html:45` — `<a href="/sources">Sources</a>`.
- Only one test targets it: `test_sources_pagination` at `tests/test_web.py:925-928`.

### 2.4 The `/radar` route — the model to copy

`src/web/routes.py:861-962`, spec node `ALG-KK-WEB-RADAR`
(description: *"Render /radar: query research papers joined to Concepts via Evidence,
resolve each Concept's Subsystem, group into Subsystem → Concept → Papers hierarchy.
Sort subsystems and concepts by paper count descending."*).

Its architecture is what R4 asks to be imitated:

1. **One join** producing `(source, concept)` pairs:
   `Source ←sourced-from— Evidence ←extracted-from— Concept`, filtered to
   `source_type IN ('paper','preprint','conference-paper','conference-proceedings')`,
   ordered by `c.id, published_date DESC`.
2. **One batched subsystem lookup** — a single `IN (...)` over all concept ids
   (`belongs-to` → `Subsystem`), building `subsystem_map`.
3. **One batched review lookup** — `_batch_review_status(conn, all_sids)`
   (`routes.py:104-133`), a single `IN (...)` query, explicitly annotated
   `INV-KK-WEB-QUERY-BOUNDED: single IN(...) query, not per-paper`.
4. **Pure-Python motivation classification** — `_classify_concept_motivations_fast`
   (`routes.py:827-859`), keyword matching with no DB access, explicitly annotated
   `INV-KK-WEB-QUERY-BOUNDED`.
5. Grouping into `by_concept` then `by_subsystem`; both sorted by paper count desc.

**Three queries total regardless of corpus size.** This is the bar the venue viewer
must meet. Contrast `/feed` (`routes.py:393-490`), which calls
`_get_concept_subsystems` and `classify_source_motivations` inside a per-item loop —
bounded only by `per_page`, and therefore satisfying the invariant only by the letter.

`radar.html` (117 lines) is a two-level expand/collapse: a subsystem row with
`total_papers`, concept count and motivation badges, a hidden `<tr>` per subsystem
containing a concept table, and a hidden `<tr>` per concept containing the paper
table (title link to `/paper/{id}`, external `source →` link, review badge, type
badge, date). Toggling is two inline JS functions, `toggleSubsystem` and
`toggleConcept`, keyed on `id` attributes built from a slugged name
(`sub.name|replace(' ','-')|replace('/','-')`) and `concept_id`.

### 2.4a The `/radar` tests are stale — the page is not broken

WP0 found the three `/radar` tests red. They are **not** evidence of a defect in the
page. `/radar` was redefined, and the tests were never updated.

| Commit | Date | What |
|---|---|---|
| `eb1a7d0` | 2026-06-29 | Created `/radar` as a subsystem **vulnerability** radar — heading `Subsystem Radar`, subsystems carrying vuln and fix counts |
| `aaf455f` | 2026-07-09 | **Last commit to `tests/test_web.py`.** The three radar tests were written against *that* semantics |
| `534d725` | 2026-07-15 | *"rewrite radar as research-focused papers-by-concept view"* — heading became `Research Radar` |
| `5f08345` | 2026-07-15 | Regrouped it subsystem → concept → paper (the current shape, §2.4) |

Same URL, a different feature, and the tests predate the rewrite by six days.

**Proof the page is sound.** The current route requires the chain
`Concept —extracted-from→ Evidence —sourced-from→ Source(paper type)`. The
`radar_vuln_client` fixture contains **zero `Source` and zero `Evidence` nodes** — it
builds subsystems, concepts, vulns, fixes, opportunities and trends, but no papers. So
the page correctly renders *"0 research papers across 0 subsystems"*, and the
assertions then search an empty table for `Scheduler`. Correct behaviour, stale
assertion. Against real data the same query returns **1,433 papers across 18
subsystems** in `data/master.db`.

**Consequence for WP5:** this makes `/radar` a *better* model than §2.4 claimed, not a
worse one. It is already "paper-type Sources grouped by X then Y with a drill-down";
the venue viewer is the same query with the grouping key changed. It reuses
`_batch_review_status` and the same three-query discipline that satisfies
`INV-KK-WEB-QUERY-BOUNDED`. The repair is to rewrite the three tests with a
paper-bearing fixture — the same scaffolding `/venues` needs.

### 2.5 Venue: the data, and why it is not yet a thing

**Storage.** `venue` is a free-text key inside the JSON `attrs` blob of `Source`
nodes. Measured on `data/master.db` on 2026-09-14:

- 3,574 `Source` nodes total.
- 3,467 carry a `venue` (97.0%); **107 do not**.
- **34 distinct venue strings.**

Full `Source` attr-key census: `url` 3574, `source_type` 3574, `license` 3574,
`title` 3500, `venue` 3467, `published_date` 3457, `abstract` 3140,
`abstract_source` 3140, `abstract_fetched_at` 3140, `local_pdf_path` 41,
`pdf_downloaded_at` 41.

**Full venue distribution** (preserve this; it is the test oracle for WP5):

| Count | Venue | | Count | Venue |
|---:|---|---|---:|---|
| 897 | arXiv cs.DC | | 17 | ISCA |
| 888 | arXiv cs.AR | | 14 | SYSTOR |
| 705 | arXiv cs.CR | | 11 | CCS |
| 356 | arXiv cs.OS | | 8 | IEEE S&P |
| 136 | OSDI 2026 | | 7 | USENIX Security |
| 60 | USENIX ATC | | 5 | SOSP 2025 |
| 60 | EuroSys | | 4 | HotOS |
| 49 | SOSP | | 4 | MICRO |
| 46 | ASPLOS | | 2 | Linux Plumbers Conference 2025 |
| 36 | NSDI | | 2 | ASPLOS 2025 |
| 30 | OSDI | | 1 | USENIX ATC 2025 |
| 29 | Middleware | | 1 | arXiv/PVLDB |
| 28 | HPCA | | 1 | IEEE UEMCON 2025 |
| 26 | FAST | | 1 | IETF CCWG |
| 20 | NDSS | | 1 | EuroSys 2025 (poster) |
| 19 | arXiv | | 1 | ACM SoCC 2025 |
| | | | 1 | Phoronix |
| | | | 1 | OSDI 2025 |

**Sources with no venue — 107, by `source_type`:** `kernel-doc` 43, `article` 22,
`preprint` 17, `vulnerability-database` 16, `discourse` 9.

**Normalisation problem (R2 correctness).** A raw `GROUP BY` on this string produces
wrong buckets. Known collisions:

| Series | Split across |
|---|---|
| OSDI | `OSDI 2026` (136), `OSDI` (30), `OSDI 2025` (1) |
| SOSP | `SOSP` (49), `SOSP 2025` (5) |
| EuroSys | `EuroSys` (60), `EuroSys 2025 (poster)` (1) |
| ASPLOS | `ASPLOS` (46), `ASPLOS 2025` (2) |
| USENIX ATC | `USENIX ATC` (60), `USENIX ATC 2025` (1) |

And the four `arXiv cs.*` values cover **2,846 Sources — 82% of the corpus** — and
are arXiv *categories*, not venues. Any venue page that shows them as four giant
buckets alongside `HotOS` (4) is not useful. `arXiv` (19) and `arXiv/PVLDB` (1) are
further variants.

**Venue is absent from every enforcement point.** In `src/graph/schema.py`:

| Structure | Contains a venue concept? |
|---|---|
| `NODE_KINDS` (27 kinds) | No |
| `EDGE_KINDS` (37 kinds) | No |
| `EDGE_VALID_PAIRS` | No |
| `REQUIRED_ATTRS` | No — `"Source": ("url", "source_type", "license")` only |
| `ID_PREFIXES` | No |
| `DATE_ATTRS` | No |
| `rules.RULES_BY_KIND` | No |

And in the spec DAG: no `Venue` node kind, no venue edge kind among the 18 edge
kinds actually in use.

**No code writes `Source.venue`.** Exhaustive grep of `src/` and `tests/`:

- `src/ingest/batch_score.py:161,167-168` — reads it for display only.
- `src/ingest/abstract_fetcher.py:108` — the word appears in a prose comment.
- `data/fetch_abstracts.py:47,53-55,66` — a one-off script that reads and filters on it.

The 3,467 values were written by ad-hoc scripts in `data/`, not by any ingest path.
**Consequence: there is no writer to extend — the editor is genuinely new code.**

**A name collision to avoid.** `INV-KK-FEED-CONFIG-VENUE-TYPE` is the *only*
venue-aware node in the DAG. Its predicate:

```
forall entry in feed_configs.feeds. entry.venue_type in
  {conference, journal, workshop, symposium, news, aggregator,
   mailing-list, preprint, documentation, vulnerability-db}
```

This constrains `venue_type` in `data/feed_configs.json`, an unrelated field.
`feed_configs.json` also carries `"feed_type": "venue"` on many entries — a **third**
distinct meaning. Three different "venue"s; none is `Source.venue`.

### 2.6 Pre-existing damage #1 — the test suite has been red for 47 days

On **2026-07-29**, five commits deliberately removed whole page families:

| Commit | Date | Removed |
|---|---|---|
| `275daea` | 2026-07-29 | Research page; rewrote concept links to `/concepts/{id}` |
| `648bee9` | 2026-07-29 | Vulns pages (list, detail, API) + nav/dashboard links |
| `4271c0a` | 2026-07-29 | Subsystems page + nav link |
| `67c4c99` | 2026-07-29 | All Nodes list page + nav link (kept concept detail route) |
| `27bf731` | 2026-07-29 | Code Examples page, template, nav link |

They cleaned `src/` and the templates **correctly** — verified: no orphaned template
remains (`base.html` is the layout parent, extended by the rest; every other template
on disk is rendered by a live route).

**They never touched the tests.** `tests/test_web.py` last changed in `aaf455f`
(2026-07-09) and has **zero commits since** (`git log aaf455f..HEAD -- tests/test_web.py`
returns 0).

Result, derived by matching every HTTP call in `tests/test_web.py` against the routes
registered in `src/web/routes.py`:

- 138 HTTP calls in the file; **68 target routes that do not exist**.
- **64 of 141 test functions (45%) are affected.**

| Deleted path | Calls | Example test lines |
|---|---:|---|
| `GET /concepts` (list) | 19 | 56, 67, 598, 607, 617, 624, 848, 855 |
| `GET /vulns/vuln-1` | 10 | 1359, 1365, 1372, 1380, 1398, 1405, 1412, 1420 |
| `GET /research` | 10 | 1595, 1601, 1607, 1613, 1619, 1817, 1836, 1866 |
| `GET /research/concept-rcu` | 5 | 1625, 1641, 1647, 1653, 1659 |
| `GET /vulns` | 4 | 1330, 1336, 1344, 1352 |
| `GET /code-examples` | 3 | 999, 1016, 1034 |
| `GET /subsystems` | 1 | 920 |
| `GET /vulns/vuln-nonexistent` | 1 | 1387 |
| `GET /vulns/concept-rcu` | 1 | 1392 |
| `GET /api/vuln-impact/{...}` | 3 | 1427, 1438, 1443 |
| `GET /research/{various}` | 9 | 1631, 1636, 1695, 1717, 1747, 1777, 1970, 2016 |

**The complete list of 64 affected test functions** (delete these in WP1):

```
test_api_vuln_impact_404_for_missing            test_research_detail_shows_motivations
test_api_vuln_impact_404_for_non_vuln           test_research_detail_shows_research_assessment
test_api_vuln_impact_returns_propagation        test_research_detail_stale_evidence_muted
test_code_examples_page_empty_db                test_research_detail_strips_non_research_source_from_motivations
test_code_examples_page_returns_200             test_research_list_excludes_concept_with_no_evidence
test_code_examples_page_uncategorized           test_research_list_excludes_concept_with_only_vuln_sources
test_concept_list_no_badge_without_code_examples test_research_list_filters_by_min_research
test_concept_list_shows_code_badge              test_research_list_includes_concept_with_evidence
test_concepts_invalid_kind_returns_empty        test_research_list_includes_concept_with_paper_source
test_concepts_kind_filter_returns_only_matching test_research_list_returns_200
test_concepts_kind_filter_shows_view_all_link   test_research_list_shows_concepts
test_concepts_list_returns_all_kinds            test_research_list_shows_research_score
test_concepts_list_shows_display_names          test_research_list_sort_by_feasibility
test_concepts_no_kind_returns_all               test_research_list_sort_by_latest_activity
test_pagination_default_values                  test_subsystems_pagination
test_pagination_first_page_no_previous          test_vuln_detail_404_for_missing
test_pagination_has_next                        test_vuln_detail_404_for_non_vuln
test_pagination_last_page_no_next               test_vuln_detail_omits_security_motivation
test_pagination_limits_results                  test_vuln_detail_returns_200
test_pagination_page_2_different                test_vuln_detail_shows_blast_radius
test_pagination_page_2_has_previous             test_vuln_detail_shows_concept_brief
test_pagination_per_page_too_large              test_vuln_detail_shows_concept_motivations
test_pagination_per_page_too_small              test_vuln_detail_shows_coupling_type
test_pagination_preserves_kind_filter           test_vuln_detail_shows_fixes
test_research_detail_404_for_missing            test_vuln_detail_shows_invariants_at_risk
test_research_detail_404_for_non_concept        test_vuln_detail_shows_severity
test_research_detail_evidence_timeline_dual_columns test_vuln_detail_shows_subsystems
test_research_detail_evidence_timeline_has_source_link test_vulns_list_returns_200
test_research_detail_excludes_non_research_sources test_vulns_list_shows_cve_ids
test_research_detail_proposal_has_source_link   test_vulns_list_shows_severity_badges
test_research_detail_returns_200                test_vulns_list_sorted_by_cvss
test_research_detail_shows_evidence_timeline
test_research_detail_shows_feasibility
```

`test_sources_pagination` is **not** in this list — it hits `/sources`, which exists.
It is deleted in WP5 with the route, not in WP1.

`test_no_write_endpoints` (`tests/test_web.py:94-97`) is also **not** affected: it
asserts `POST /`, `PUT /concepts/concept-1` and `DELETE /concepts/concept-1` return
**405**, which remains true.

`README.md:257` states *"326 tests, zero failures."* This cannot currently be true.

> **Caveat, stated precisely.** `pytest` is not installed in `venv/` or system-wide,
> and installing it is a mutation that `/cb-audit` cannot authorise, so **the suite
> was never executed**. The 64/141 figure is a *static derivation* from route matching
> plus git history. WP0 exists to convert it into an observed number. Do not quote
> "64 failing tests" as an observed fact until WP0 has run.

> **CAVEAT DISCHARGED 2026-09-14 (WP0). Corrections to the figures above:**
>
> | Claim above | Observed |
> |---|---|
> | 141 test functions in `test_web.py` | **167** (141 top-level + 26 in `TestDisplayNameForNode`) |
> | 138 HTTP calls | **136** |
> | 64 affected functions | **69 must be deleted** |
> | "64 failing" | **63 route-class failures** |
>
> The list of 64 above is *correct as far as it goes* — re-deriving it against the
> live FastAPI router reproduced it exactly. But it is **incomplete in a way the
> method could not detect**. Five further tests assert the presence of nav or
> dashboard links to the deleted pages while calling only `/`:
> `test_dashboard_kind_links`, `test_nav_has_code_link`, `test_dashboard_links_to_vulns`,
> `test_nav_has_vulns_link`, `test_research_nav_link_visible`. They make no dead call,
> so call-site matching is structurally blind to them. 64 + 5 = **69**.
>
> 69 deleted but only 63 failing reconciles exactly: six of the 64 assert `404`, and
> against a route that no longer exists they were *passing spuriously*.
>
> **Correction to the fixture claim.** `paginated_client` is **not** used only by the
> pagination tests — `test_sources_pagination` also uses it, and that test is
> explicitly retained until WP5. The fixture was therefore **kept**; deleting it as
> instructed would have broken a surviving test. It is now that test's sole user, so
> WP5 must delete fixture and test together. `research_client` **was** orphaned
> (13 users, 0 survivors) and was deleted; the plan did not name it.
>
> WP0 also found three defects this section does not cover, each routed to its own
> work package: the mcp 2.x import break (**WP0.5**), the stale `/radar` tests
> (**WP5**, decision D-4), and two schema-drift failures (**WP3**, decision D-5).
>
> Executed in commit `da66f41`. `tests/test_web.py`: 167 → 98 tests.

### 2.7 Pre-existing damage #2 — declared schema vs live database

`src/graph/schema.py` `SCHEMA_SQL` declares:

```sql
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('Concept', 'Source', ... 27 kinds ...)),
    attrs TEXT NOT NULL DEFAULT '{}'
);
```

The live `data/master.db` actually holds:

```sql
CREATE TABLE "nodes" (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    attrs TEXT NOT NULL DEFAULT '{}'
)
```

**No CHECK constraint.** The quoted table name indicates the table was rebuilt at
some point and the constraint was dropped. `edges` has likewise lost its CHECK.

`src/web/app.py` runs `conn.executescript(SCHEMA_SQL)` on every startup, but every
statement is `CREATE TABLE IF NOT EXISTS`, so **it can never repair an existing
table**. There is no migration mechanism anywhere, despite `schema.py`'s docstring
claiming *"SQLite schema definition and migrations"*.

**Why this blocks D-1 Option A specifically:** a fresh DB (every pytest fixture,
every `:memory:` app) *does* get the CHECK. Insert `kind='Venue'` and the test DB
raises `IntegrityError` while production silently accepts it. Tests and production
would disagree about whether the feature works.

Note also that `graph.engine.add_node` does **not** validate `kind` in Python — it
only checks `REQUIRED_ATTRS`. Kind enforcement is *solely* the SQL CHECK.
`graph.engine.add_edge` **does** validate in Python against `EDGE_VALID_PAIRS` and
raises `ValueError(f"Unknown edge kind: {kind}")` for anything unlisted.

### 2.8 Pre-existing damage #3 — dangling spec citations

Docstring citations are this project's only spec-to-code link (`ril query source`
exists but 0 of 25 `MOD-KK-WEB` nodes carry a source location; 7 of 25 carry artifact
associations; all 25 are `riStatus=unchecked`, `predicateAuthority=nl-only`).

Cross-referencing every `(INV|ALG|IFC|MOD|ERR|ANN)-KK-*` token in `src/` and `tests/`
against the 94 KK nodes in the DAG:

- **316 distinct KK ids cited; 246 do not exist in the DAG (78%).**
- Within `src/web/` + `tests/test_web.py`: **64 cited, 46 dangling.**
- Only 2 DAG `KK-WEB` nodes are cited nowhere: `ALG-KK-WEB-PAPER-DETAIL-REVIEW`, `MOD-KK-WEB`.

**Dangling and cited from `src/web/` itself** (not test-only — these are the ones
WP7 must resolve):

| Dangling id | Cited at |
|---|---|
| `ALG-KK-WEB-SERVE` | `routes.py:1`, `app.py:1` |
| `ALG-KK-WEB-SEARCH` | `routes.py:320` |
| `ALG-KK-WEB-DISPLAY-NAME` | `routes.py:81` |
| `ALG-KK-WEB-KIND-DROPDOWN` | `routes.py:99` |
| `ALG-KK-WEB-IMPACT-PAGE` | `routes.py:373` |
| `ALG-KK-WEB-DIAGNOSTICS-PAGE` | `routes.py:362` |
| `INV-KK-WEB-FULL-ACCESS` | `routes.py:4`, `routes.py:265` |
| `INV-KK-WEB-SEARCH-FULL-ACCESS` | `routes.py:320` |
| `INV-KK-WEB-READ-ONLY` | `routes.py:3` — **and false, see §2.9** |

Test-only dangling ids of note: `INV-KK-WEB-PAGINATION` (tests 821–861, 920, 925),
`INV-KK-WEB-KIND-FILTER` (593, 597), `ALG-KK-WEB-CODE-BROWSE`, `ALG-KK-WEB-GRAPH-VIZ`,
`ALG-KK-WEB-RESEARCH-LIST`, `ALG-KK-WEB-QUERY-ROUTES`, `ALG-KK-WEB-KIND-DETAIL`, and
`INV-KK-WEB-CODE-BROWSE-` (`tests/test_web.py:981` — **malformed, trailing hyphen**).
Most of these die with WP1.

### 2.9 Pre-existing damage #4 — `INV-KK-WEB-READ-ONLY` is false

`src/web/routes.py:1-5`:

```python
"""Route handlers for the human-facing web API (ALG-KK-WEB-SERVE).

INV-KK-WEB-READ-ONLY: only GET endpoints are registered here.
INV-KK-WEB-FULL-ACCESS: all node kinds are served without filtering.
"""
```

Six mutating endpoints are registered in this file: `POST /api/reviewers`,
`POST /api/review/{source_id}`, `PUT /api/review/{review_id}`,
`DELETE /api/review/{review_id}`, `PUT /api/abstract/{source_id}`,
`POST /api/feed/send/{source_id}`.

The assertion was superseded in practice by `INV-KK-WEB-MUTATION-ALLOWLISTED` but
never retired from the docstring. **It must be deleted, not authored** (CLAUDE.md
rule 2 forbids weakening a predicate to suppress a finding; here the correct action
is removing a false claim, not weakening a real one).

### 2.10 The mutation allowlist — the structural gate the editor must pass

`src/web/routes.py:27-36`:

```python
# INV-KK-WEB-MUTATION-ALLOWLISTED: this tuple IS the structural enforcement.
# Every POST/PUT/DELETE route registered in setup_routes must have a path
# starting with one of these prefixes. Admitting a new mutating endpoint means
# adding its prefix here — the invariant itself does not move.
WEB_MUTATION_ALLOWLIST = (
    "/api/review/",
    "/api/reviewers",
    "/api/abstract/",
    "/api/feed/send/",  # side-effecting shell-out, not a graph write
)
```

DAG node `INV-KK-WEB-MUTATION-ALLOWLISTED`: `invariantStrength=strong`,
`enforcementBasis=structural`, predicate
`forall endpoint in MOD-KK-WEB. endpoint.method in {POST, PUT, DELETE} implies endpoint.path in WEB_MUTATION_ALLOWLIST`.

### 2.11 The editor pattern to copy — `set_abstract`

`src/ingest/source_abstract.py` (80 lines) is the established shape for a
human-driven write to a `Source` attribute, and the venue editor must mirror it:

- Module docstring names the interface node (`IFC-KK-SOURCE-ABSTRACT`) and explains
  *why* one place owns the write: "so that every writer … goes through one place and
  stamps provenance the same way."
- A frozen vocabulary constant: `VALID_ABSTRACT_SOURCES = ("arxiv", "openalex", "pdf", "manual")`.
- A `@dataclass` result type (`AbstractResult`) returned to the route.
- `set_abstract(conn, source_id, text, source_label="manual")` validates the label,
  strips and rejects empty text, loads the node and rejects a non-`Source` kind,
  stamps `date.today().isoformat()`, and writes via `graph.engine.update_node_attrs`.
- A documented decision not to re-run `validate_node`: the Source-must-have-an-Advisory
  rule would reject a good write for an unrelated pre-existing gap. **The venue editor
  faces exactly the same trap and needs the same carve-out.**

The route side (`routes.py:1156-1180`, `ALG-KK-WEB-ABSTRACT-EDIT`) is thin: parse
body, call the domain function, `conn.commit()`, map `ValueError` to 404/422.
Provenance is forced server-side ("the provenance label is forced to `manual` — a
human typed it, whatever the caller claims").

### 2.12 Authentication vs authorisation

`install_gate()` puts `ALG-KK-AUTH-GATE` in front of the whole mount, so every
request reaching `MOD-KK-WEB` already carries `request.state.user`
(`INV-KK-AUTH-GATE-COVERS-MOUNT`). Authentication is free.

**Authorisation is not.** `require_admin()` is defined in `src/authgate/app.py:59-68`
("Single definition site for the admin rule. Every /admin route calls this and nothing
else decides who is an admin, so the check cannot drift between handlers") and is
called **only** by the four `/admin/*` handlers. **No `MOD-KK-WEB` mutating endpoint
has a role check.** `submit_review` reads `request.state.user` for *attribution*
(`INV-KK-REVIEW-ATTRIBUTION-FROM-SESSION`), not authorisation.

Blast-radius comparison that motivates D-2:

| Operation | Rows touched |
|---|---|
| `PUT /api/abstract/{id}` | 1 Source |
| `POST /api/review/{id}` | 1 HumanReview + 1 edge |
| **Venue merge `OSDI 2026` → `OSDI`** | **up to 897 Sources** |

### 2.13 Spec graph baseline

`npm run spec:check` on 2026-09-14: **3,613 nodes checked, 0 errors, 1,055 warnings.**

| Warning code | Count |
|---|---:|
| `AUTH-WARN-ORPHANED-INV` | 493 |
| `AUTH-WARN-ORPHANED-ALGO` | 275 |
| `AUTH-WARN-DISCONNECTED-ANNOTATION` | 152 |
| `AUTH-WARN-MISSING-PREDICATE-NL` | 68 |
| `AUTH-WARN-DEAD-INTERFACE` | 61 |
| `AUTH-WARN-UNANCHORED-AUTOMATON` | 3 |
| `AUTH-WARN-UNEMITTED-ERROR` | 3 |

35 are KK-scoped; **8 are `MOD-KK-WEB`/`MOD-KK-GRAPH`-scoped**:

```
AUTH-WARN-ORPHANED-ALGO   ALG-KK-GRAPH-CLASSIFY-SOURCE-MOTIVATIONS
AUTH-WARN-ORPHANED-ALGO   ALG-KK-WEB-FEED-SEND
AUTH-WARN-ORPHANED-ALGO   ALG-KK-WEB-FEED-CARD
AUTH-WARN-ORPHANED-ALGO   ALG-KK-WEB-FEED-LIST
AUTH-WARN-ORPHANED-ALGO   ALG-KK-WEB-PAPER-DETAIL
AUTH-WARN-ORPHANED-INV    INV-KK-WEB-PAPER-404-NON-SOURCE
AUTH-WARN-ORPHANED-INV    INV-KK-WEB-PAPER-CONCEPT-CHAIN
AUTH-WARN-ORPHANED-INV    INV-KK-WEB-QUERY-BOUNDED
```

`INV-KK-WEB-QUERY-BOUNDED` is orphaned *and* is the bound the new viewer must honour.
Predicate: `forall route in web_list_routes. count(enrichment_calls(route)) <= route.per_page`;
`invariantStrength=strong`, `enforcementBasis=structural`.

**`MOD-KK-WEB` contents — 15 algorithms, 10 invariants:**

```
ALG-KK-WEB-ABSTRACT-EDIT      ALG-KK-WEB-REVIEW-EDIT        INV-KK-FEED-CARD-LINK-ABSOLUTE
ALG-KK-WEB-FEED-CARD          ALG-KK-WEB-REVIEW-STATUS      INV-KK-FEED-CONFIG-VENUE-TYPE
ALG-KK-WEB-FEED-LIST          ALG-KK-WEB-REVIEW-SUBMIT      INV-KK-FEED-SEND-PLACEHOLDER-REQUIRED
ALG-KK-WEB-FEED-REVIEW-BADGE  ALG-KK-WEB-REVIEWER-CREATE    INV-KK-FEED-SEND-TIMEOUT
ALG-KK-WEB-FEED-SEND          ALG-KK-WEB-REVIEWERS-PAGE     INV-KK-FEED-SUMMARY-MAX-WORDS
ALG-KK-WEB-PAPER-DETAIL       ALG-KK-WEB-REVIEWS-LIST       INV-KK-REVIEW-ATTRIBUTION-FROM-SESSION
ALG-KK-WEB-PAPER-DETAIL-REVIEW                              INV-KK-WEB-MUTATION-ALLOWLISTED
ALG-KK-WEB-RADAR                                            INV-KK-WEB-PAPER-404-NON-SOURCE
ALG-KK-WEB-REVIEW-DELETE                                    INV-KK-WEB-PAPER-CONCEPT-CHAIN
                                                            INV-KK-WEB-QUERY-BOUNDED
```

`MOD-KK-GRAPH` holds only 3 nodes: `ALG-KK-GRAPH-CLASSIFY-SOURCE-MOTIVATIONS`,
`INV-KK-MOTIV-EVIDENCE-GROUNDED`, `INV-KK-MOTIV-LABEL-VOCABULARY`.

Graph-wide: 3,613 nodes / 8,464 edges; 94 KK nodes; 5 KK modules
(`MOD-KK-WEB`, `MOD-KK-GRAPH`, `MOD-KK-INGEST`, `MOD-KK-REVIEW`, `MOD-KK-AUTH`).

### 2.14 Encoding damage

> **RESOLVED 2026-09-14, commit `09bf666`.** The extent below was understated by an
> order of magnitude. A tree-wide scan found the UTF-8 BOM in **26** tracked files and
> mojibake in **21** (24 characters: 22 em dashes, 2 rightwards arrows), not the 2
> files named here. All were repaired in one commit; a re-scan reports zero of both.
> `.gitattributes` was added with `* text=auto eol=lf` plus explicit binary markings
> for `.db/.pdf/.png/.jpg/.zip/.node`. The suite was bit-identical across that commit
> (1,222 passing, 5 failing, 2 uncollectable, before and after), confirming the change
> was encoding-only. The two files below were merely the ones the audit sampled.

`src/web/app.py` and `src/graph/engine.py` both begin with a UTF-8 BOM (`﻿`) and
contain mojibake where an em dash was intended:

```
"""FastAPI application factory â€” ALG-KK-WEB-SERVE."""
"""Graph engine â€” node/edge CRUD and traversal queries."""
```

Same root cause as two other observations from 2026-09-14: all 7 tracked files in the
working tree had been flipped LF→CRLF with zero content change (43,417 insertions /
43,417 deletions; `git diff --ignore-all-space` empty), and
`node_modules/better-sqlite3/build/Release/better_sqlite3.node` was a
`PE32+ executable (DLL) … for MS Windows`. The repo moves between Windows and Linux
(`start.bat` alongside `start.sh`) with no `.gitattributes`.

### 2.15 Environment as of 2026-09-14

| Tool | State |
|---|---|
| `git` | 2.43.0 — **installed during this session** (`apt-get install -y git`); was absent |
| `node` | 22.23.1 LTS — **installed during this session** (`snap install node --classic --channel=22/stable`); was absent. Ubuntu 24.04 apt only offers Node 18, which `better-sqlite3@^12.8.0` does not support |
| `npm` | 10.9.8 |
| `better-sqlite3` | **rebuilt for Linux** during this session (`npm rebuild better-sqlite3`); was a Windows DLL |
| `silk` / `ril` | working — `spec:check` 3,613 nodes, 0 errors |
| **`pytest`** | ~~**NOT installed**~~ → **installed 2026-09-14 (WP0)**, pytest 9.1.1, via `./venv/bin/pip install -e ".[dev,ingest]"` (38 packages) |
| `mcp` | **2.2.0** — `mcp>=1.0` floats across the 1.x→2.x breaking rename; this is WP0.5 |
| git identity | **not configured** (no `~/.gitconfig`, no repo-local user). Commits in this session used `-c user.name='reinier' -c user.email='reiniertl@gmail.com'`, matching prior commit authors |

`venv/` is Python 3.12 with only the web subset installed (17 packages: fastapi,
uvicorn, jinja2, starlette, pydantic, python_multipart, …). **`mcp`, `httpx`,
`pymupdf`, `feedparser`, `anthropic`, `pytest` and `ruff` are all absent.**
`pyproject.toml` was corrected in commit `d38e0e0` (2026-09-14) to add `feedparser`
and `anthropic` to the `ingest` extra and drop the unused `scancode-toolkit`.

Full install: `./venv/bin/pip install -e ".[dev,ingest]"` (dry-run resolved to 38
packages, no conflicts).

### 2.16 Tooling defect found during the audit

`.claude/skills/cb-audit/templates/ap2-analyze.request.json` instructs the auditor to
run `npm run spec:conformance`. **That script does not exist** — `package.json` defines
only `ril`, `silk`, `spec:validate`, `spec:check`. CLAUDE.md records L5 conformance and
L∞ `spec:trace` as *retired*, so the absence is intentional and the skill template is
stale. Not blocking; fix separately.

---

## 3. Design decisions (with rationale — do not re-litigate)

### Operator decisions taken 2026-09-15

Raised by WP0's observed baseline and answered directly by the operator.

**D-3. Migrate to mcp 2.x; do not pin `mcp<2`.** The `mcp>=1.0` declaration floats to
2.2.0, which renamed `FastMCP` → `MCPServer`. Pinning back would freeze the project on
a superseded API to avoid a change that a probe shows is small: the constructor keeps
its positional signature and `.tool()` still returns the original function, so the 25
direct-call tests in `tests/test_mcp_server.py` are unaffected. Issued as **WP0.5**.

**D-4. Rewrite the three `/radar` tests; do not touch the page.** Full evidence in
§2.4a — the page is sound and the tests predate a deliberate rewrite by six days.
Folded into **WP5**, which needs the same paper-chain fixture.
*Scope clarification from the operator:* the venue viewer does **not** replace
`/radar`. `/radar` stays. The venue viewer **adopts radar's shape** in place of
`/sources`.

**D-5. Fold the two schema-drift failures into WP3.** `RULES_BY_KIND` is missing two
node kinds and the `/viz` `edgeColor` map is missing an edge kind. Both are the same
defect class as the SQLite CHECK drift — a declaration in `schema.py` that a consumer
has fallen out of step with — so they belong in one work package with one predicate
rather than three unrelated patches.

**Still open and still blocking WP2/WP4:** D-1 (venue representation) and D-2 (venue
mutation authorisation). See §14.

### Design decisions from the audit

**DD-1. The viewer copies `/radar`'s query discipline, not just its markup.**
Three queries total, no per-item enrichment. `/feed`'s per-item loop is the
anti-pattern. Rationale: `INV-KK-WEB-QUERY-BOUNDED` is `strength=strong`,
`enforcementBasis=structural`, and the venue page spans all 3,574 Sources with no
pagination (venues are the unit, not papers).

**DD-2. The editor copies `set_abstract`'s layering.** A new domain module owns
venue writes; the route is thin. Rationale: `source_abstract.py` states the reason
explicitly — one place stamps provenance the same way for every writer. Since *no*
code currently writes `Source.venue`, this module becomes the sole writer from day one,
which is a better starting position than abstracts had.

**DD-3. The editor must not re-run `validate_node`.** Same carve-out
`set_abstract` documents: the Source-must-have-an-Advisory rule
(`rules.check_source_has_advisory`) is not satisfied by the great majority of real
Sources, so revalidating would reject a good venue edit for an unrelated pre-existing
gap. Venue is an optional attr; the write cannot make a valid Source invalid.

**DD-4. `venue` stays out of `REQUIRED_ATTRS["Source"]`.** 107 Sources have no venue
and adding it there would invalidate every existing Source and every `add_node` call
in the ingest pipeline — the identical reasoning `source_abstract.py` gives for the
abstract fields.

**DD-5. The no-venue bucket is explicit, not implicit.** 107 Sources
(`kernel-doc` 43, `article` 22, `preprint` 17, `vulnerability-database` 16,
`discourse` 9) must have a defined placement, specified as a postcondition. Silently
dropping them loses 3% of the corpus from a page whose whole job is coverage.

**DD-6. WP1 and WP3 are separate commits from the venue work.** CLAUDE.md rule 7,
one logical change per commit. They are also the packages most likely to be handed
to a different person.

**DD-7. `INV-KK-WEB-READ-ONLY` is deleted, not authored.** It is a false claim about
the current code, not a real invariant that the code violates. CLAUDE.md rule 2
("the spec verifies the code") applies to *real* invariants; authoring a predicate
known to be false would be worse than removing a stale comment.

---

## 4. Target architecture

```
GET  /venues                     ALG-KK-WEB-VENUES       (viewer, replaces /sources)
PUT  /api/venue/{source_id:path} ALG-KK-WEB-VENUE-EDIT   (editor, single Source)
POST /api/venue/merge            ALG-KK-WEB-VENUE-MERGE  (editor, alias/merge — see D-1)
```

`WEB_MUTATION_ALLOWLIST` gains `"/api/venue/"` — one prefix covers both mutating routes.

```
src/web/routes.py
  ├─ venues()            thin, 3 queries, renders venues.html
  ├─ edit_venue()        thin → venue_store.set_venue()
  └─ merge_venues()      thin → venue_store.merge_venues()

src/ingest/venue_store.py        NEW — sole writer of venue data
  ├─ set_venue(conn, source_id, venue, ...)
  ├─ merge_venues(conn, from_venue, to_venue)
  ├─ normalise_venue(raw) -> str        (pure, testable, no DB)
  └─ VenueResult / MergeResult dataclasses

src/web/templates/venues.html    NEW — two-level expand/collapse, modelled on radar.html
src/web/templates/concept_list.html   DELETED
```

---

## 5. New spec nodes

### 5.1 Under D-1 Option A (Venue as node kind) — additionally required

| Node | Kind | Notes |
|---|---|---|
| `IFC-KK-VENUE` | interface | fields: `name`, `venue_type`, `series`, `aliases` |
| `INV-KK-VENUE-NAME-UNIQUE` | invariant | one Venue node per canonical name |
| `INV-KK-VENUE-SOURCE-EDGE` | invariant | every Source with a venue has exactly one `published-at` edge |
| `ALG-KK-VENUE-BACKFILL` | algorithm | one-time migration of 3,467 Sources |

Plus schema changes in §6.

### 5.2 Common to both options

| Node | Kind | Module | Notes |
|---|---|---|---|
| `ALG-KK-WEB-VENUES` | algorithm | `MOD-KK-WEB` | Viewer. Pre/post: grouping, ordering, nesting, no-venue bucket (DD-5). `satisfies` → `INV-KK-WEB-QUERY-BOUNDED` |
| `ALG-KK-WEB-VENUE-EDIT` | algorithm | `MOD-KK-WEB` | Single-Source venue write |
| `ALG-KK-WEB-VENUE-MERGE` | algorithm | `MOD-KK-WEB` | Alias/merge operation |
| `INV-KK-VENUE-NORMALISED` | invariant | `MOD-KK-GRAPH` | Canonical form; `OSDI 2026`/`OSDI`/`OSDI 2025` resolve to one venue |
| `INV-KK-VENUE-MUTATION-AUTHORISED` | invariant | `MOD-KK-WEB` | Per D-2 |
| `IFC-KK-VENUE-EDIT` | interface | `MOD-KK-WEB` | Result shape returned by the domain functions |

**Authoring requirements:** use `npm run ril -- template <kind> --json` for required
attributes and valid edge targets. Every new node gets `predicate-nl`. Attach artifacts
with `ril associate` at authoring time (§2.8 — 0 of 25 existing web nodes have a source
location; do not extend that pattern).

---

## 6. Schema changes (D-1 Option A only)

`src/graph/schema.py`:

```python
NODE_KINDS   += ("Venue",)
EDGE_KINDS   += ("published-at",)
EDGE_VALID_PAIRS["published-at"] = ("Source", "Venue")
REQUIRED_ATTRS["Venue"] = ("name", "venue_type")
ID_PREFIXES["Venue"] = "venue-"
rules.RULES_BY_KIND["Venue"] = [...]     # or explicit empty list
```

**And a migration** (WP3 makes this possible): the live table has no CHECK, fresh
test DBs do. Adding `Venue` to `NODE_KINDS` changes the CHECK for new DBs only; WP3
must first reconcile declared vs live so both behave identically.

Backfill: 3,467 `Venue`-less Sources → create ~20–34 `Venue` nodes (post-normalisation)
+ 3,467 `published-at` edges. Must be idempotent and re-runnable.

---

## 7. Work packages

### WP0 — Establish a real test baseline ✅ DONE 2026-09-14
**Severity:** CRITICAL · **Skill:** `/cb-free` (not `/cb-ops`: `pip install` is not on
the `CB-OPS-INV-OPERATIONAL-ONLY` allowlist) · **Blocks:** everything

- `./venv/bin/pip install -e ".[dev,ingest]"`. → 38 packages, no conflicts.
- Run `pytest`. Record the true pass/fail count.
- Compare against the static prediction in §2.6 (64 of 141 in `test_web.py`).
- **Exit:** an observed baseline exists; §2.6's caveat is discharged. ✅

**Result:** plain `pytest` yields **zero** results — 2 modules fail at import and the
collection error aborts the run. With `--continue-on-collection-errors`: **68 failed,
1228 passed, 2 errors**, in four distinct classes (63 dead tests, 3 radar, 2 drift,
2 uncollectable). See the corrections block in §2.6. No commit; measurement only.

### WP0.5 — Migrate the MCP server to mcp 2.x (decision D-3 in §3) ✅ DONE 2026-09-15 (commit `d0200bd`)
**Severity:** CRITICAL · **Skill:** `/cb-green` · **Blocks:** every later "suite green" gate

- `pyproject.toml` declares `mcp>=1.0`, which floats to **mcp 2.2.0**. mcp 2.x renamed
  `FastMCP` → `MCPServer` and moved it to `mcp.server.mcpserver`.
  `src/mcp_server/server.py:25` still imports the 1.x path, so the module raises
  `ModuleNotFoundError`; `tests/test_mcp_server.py` and `tests/test_e2e_pipeline.py`
  both import it, and **a collection error aborts the entire pytest run**.
- Operator decision: **migrate**, do not pin `mcp<2`.
- Surface: line 25 (import), line 40 (`FastMCP("know_kernel")` → `MCPServer(...)`,
  same positional signature), 18 `@mcp.tool()` decorators (probed: `.tool()` still
  returns the original function, so the direct-call tests keep working), `mcp.run()`
  at line 608. Audit the whole file for other 1.x-only APIs.
- Remove the `--continue-on-collection-errors` paragraph WP1 added to `README.md`.
- **Exit:** plain `pytest` collects with no flag; 0 errors. ✅
  → Migrated `src/mcp_server/server.py` to `mcp.server.mcpserver.MCPServer`. The 18
  `@mcp.tool()` decorators and the direct-call tests in `tests/test_mcp_server.py`
  needed no change, as the probe in this section predicted. Plain `pytest` now
  collects the whole suite; the `--continue-on-collection-errors` paragraph is gone
  from `README.md`.

### WP1 — Delete the dead tests ✅ DONE 2026-09-14 (commit `da66f41`)
**Severity:** CRITICAL · **Skill:** `/cb-green` · **Parallel with:** WP2, WP3, WP7, WP8

- Delete the 64 test functions listed in §2.6 from `tests/test_web.py`.
  → **69 deleted.** The list of 64 is complete only for tests that *call* a dead
  route; 5 more assert nav/dashboard links to deleted pages while calling only `/`.
- Delete now-unused fixtures (`paginated_client` at `tests/test_web.py:822-840` is
  used only by the pagination tests; check each before removing).
  → **`paginated_client` was KEPT** — the claim is false, `test_sources_pagination`
  still uses it. **`research_client` was deleted** instead (13 users, 0 survivors).
  The "check each before removing" instruction is what caught this.
- Do **not** delete `test_sources_pagination` (WP5 owns it) or `test_no_write_endpoints`. ✅
- Correct `README.md:257`. ✅
- **Exit:** `pytest` green; test count honest.
  → Count is honest (167 → 98, ruff clean, every surviving HTTP call resolves).
  **Green was NOT reached**, by design: 5 failures remain, all outside this WP and
  routed to WP0.5, WP3 and WP5.

### WP2 — Decide and specify venue representation ✅ DONE 2026-09-15 (commit `068915f`, carrying WP6)
**Severity:** CRITICAL · **Skill:** `/cb-green`, spec-only · **Blocks:** WP4, WP5 · **Needs:** D-1, D-2

- Resolve D-1 (§14). Author the nodes in §5.1 (if Option A) and the venue-model nodes
  in §5.2 via `ril apply-batch`.
- Specify normalisation semantics against the §2.5 collision table.
- **Exit:** nodes applied; `spec:check` still 0 errors; no new dangling ids.

### WP3 — Reconcile declared vs actual, three surfaces ✅ DONE 2026-09-15 (commit `5826796`)
**Severity:** ERROR · **Skill:** `/cb-green` · **Parallel with:** WP1, WP2, WP7, WP8

Widened by decision D-5 (§3) from the SQLite CHECK alone to **all three** consumers of
`schema.py`'s declarations that have drifted. Surfaces 2 and 3 were found by WP0 and
are each a currently-failing test.

1. **SQLite CHECK.** Fix §2.7. Either add a real migration step or reconcile
   `SCHEMA_SQL` with the live table so fresh and existing DBs agree.
2. **`RULES_BY_KIND`.** `graph.rules.RULES_BY_KIND` has no entry for `ResearchBrief`
   or `HumanReview`, both in `NODE_KINDS` — two node kinds with zero validation rules.
   Verified directly: `set(NODE_KINDS) - set(RULES_BY_KIND) == {'HumanReview',
   'ResearchBrief'}`. Red test: `tests/test_graph_rules.py::test_rules_by_kind_covers_all_node_kinds`.
3. **`/viz` `edgeColor`.** No entry for edge kind `summarizes-for`, which is in
   `EDGE_KINDS`, so it renders uncoloured. Red test:
   `tests/test_web.py::test_web_viz_edge_color_covers_all_edge_kinds`.

- Add a check/invariant that they agree. **Consider one predicate covering all three**
  — "every kind declared in `schema.py` is honoured by every consumer of that
  declaration" — rather than three unrelated patches; a single predicate is what stops
  a fourth consumer drifting next. Design decision: ask.
- Both red tests must go green **without being edited**. They are correct as written
  and are detecting real drift; weakening either violates CLAUDE.md rule 2.
- **Exit:** a fresh test DB and `data/master.db` accept and reject the same `kind`
  values; `NODE_KINDS`/`EDGE_KINDS` are fully covered by rules and by the viz map.

### WP4 — Author the web spec nodes ✅ DONE 2026-09-15 (commit `7a59e59`)
**Severity:** ERROR · **Skill:** `/cb-green`, spec-only · **Depends:** WP2

- Author §5.2 nodes with full pre/postconditions.
- Attach `INV-KK-WEB-QUERY-BOUNDED` to `ALG-KK-WEB-VENUES` with a `satisfies` edge —
  this also clears one of the 8 warnings in §2.13.
- **Exit:** `spec:check` 0 errors; new nodes carry artifacts and `predicate-nl`.

### WP5 — Implement ✅ DONE 2026-09-15 (commits `be361fb` radar repair, `cac9860` viewer and editor)
**Severity:** ERROR · **Skill:** `/cb-green` · **Depends:** WP4 (and WP1 for a green suite)

Remove:
- `src/web/routes.py:240-261` (`sources_list`)
- `src/web/templates/concept_list.html`
- `src/web/templates/base.html:45` (nav entry)
- `tests/test_web.py:780` (`test_sources_pagination`) **and `:759`
  (`paginated_client`)** — line numbers shifted when WP1 removed 69 functions, and
  after WP1 that fixture's sole remaining user is this test, so both go together

Add:
- `src/ingest/venue_store.py` per DD-2/DD-3/DD-4
- `GET /venues` + `src/web/templates/venues.html` per DD-1
- `PUT /api/venue/{source_id}` and `POST /api/venue/merge`
- `"/api/venue/"` in `WEB_MUTATION_ALLOWLIST` (`routes.py:31-36`)
- Tests per §10

Repair (decision D-4, §3) ✅ DONE 2026-09-15 (commit `be361fb`):
- Rewrite the three `/radar` tests — `test_radar_returns_200:1046`,
  `test_radar_shows_subsystems_with_concepts:1052`,
  `test_radar_shows_vuln_and_fix_counts:1062` — against research-radar semantics.
  **The radar page is not broken and must not be changed.** See §2.4a.
- Folded in here rather than given its own WP because `/venues` needs the identical
  paper-chain fixture scaffolding. Build one fixture, share it.
  → The fixture was built first and the repair shipped ahead of the viewer, so WP5
  landed as **two** commits rather than one. `/radar`'s route and template are
  byte-identical to their pre-WP5 state, as the exit criterion required.

**Scope note:** the venue viewer does **not** replace `/radar`. `/radar` stays exactly
as it is. The venue viewer **adopts radar's shape** in place of `/sources`.

**Exit:** `pytest` green; `spec:check` 0 errors; `/venues` renders; `/sources` 404s;
the radar route and template are byte-identical to their pre-WP5 state.

### WP6 — Decide venue-mutation authorisation ✅ DONE 2026-09-15 (folded into WP2, commit `068915f`)
**Severity:** ERROR · **Skill:** fold into WP2 · **Needs:** D-2

Per §2.12. If admin-only: either make `require_admin` reachable from `MOD-KK-WEB`
or host the editor in the gate app. Decide **before** WP4 authors the invariant.

### WP7 — Close the dangling citations ✅ DONE 2026-09-15 (commit `f22ecd0`)
**Severity:** ERROR · **Skill:** `/cb-green`, spec-only · **Parallel**

- Author nodes for the 8 live dangling ids in §2.8, or delete the citation where the
  route is going away.
- **Delete** `INV-KK-WEB-READ-ONLY` from `routes.py:3` (DD-7).
- **Exit:** `src/web/` cites no id that does not exist in the DAG.

### WP8 — Encoding hygiene ✅ DONE 2026-09-14 (commit `09bf666`)
**Severity:** WARN · **Skill:** `/cb-green` · **Fully parallel**

- Strip BOM + repair mojibake in `src/web/app.py`, `src/graph/engine.py` (§2.14).
  → **26 files carried the BOM and 21 carried mojibake**, not 2. All repaired.
- Add `.gitattributes` with `* text=auto eol=lf`. ✅ plus binary markings.
- **Exit:** no BOM; `git diff` clean after a round trip. ✅ re-scan reports zero.

---

## 8. File manifest

**New:** `src/ingest/venue_store.py`, `src/web/templates/venues.html`,
`tests/test_venue_store.py`, `.gitattributes` (WP8).

**Modified:** `src/web/routes.py` (remove `/sources`; add 3 routes; allowlist; docstring),
`src/web/templates/base.html` (nav), `tests/test_web.py` (WP1 + WP5), `README.md` (WP1
and WP0.5), `src/graph/schema.py` (WP3, and WP5 under Option A), `src/graph/rules.py`
(WP3 surface 2, and Option A), `src/mcp_server/server.py` (WP0.5),
**26 files for WP8** — not the 2 named in §2.14; the full list is in commit `09bf666`.
→ Two more were modified that this manifest did not predict:
`src/graph/engine.py` (WP3 — `add_node` now rejects a kind outside `NODE_KINDS`) and
`src/web/templates/graph_viz.html` (WP3 surface 3 and WP5 — an `edgeColor` entry for
`summarizes-for` and then for `published-at`). `.gitignore` was also modified, by the
spec store recovery in §9 item 5.

**Deleted:** `src/web/templates/concept_list.html`. ✅

**Explicitly untouched — assert in review:** `src/authgate/*`, `src/export/*`,
`src/graph/briefing.py`, `src/graph/scoring.py`, `src/ingest/extractor.py`,
`src/ingest/feed.py`, all `data/*.py` one-off scripts.
→ Verified against `git diff --name-only 58a31c7^..f22ecd0 -- src/`: all of these
held. D-2 came out admin-for-merge, but `src/authgate/` still needed no change —
`require_admin` was imported, not modified. `src/mcp_server/*` was **removed from
this list**: it was never truly untouched once WP0.5 existed, and the Modified list
above has named `src/mcp_server/server.py` since WP0.5 was added.

---

## 9. Commit sequence

**Planned nine commits; eleven landed.** Two were never anticipated by this plan
— items 4 and 5 below. WP5 split in two because the shared fixture was finished
before the viewer was. WP6 folded into WP2, as §7 said it would. The order below
is the actual one.

1. WP0 — no commit (environment). ✅
2. `test: remove tests for pages deleted on 2026-07-29` (WP1) ✅ `da66f41`
3. `chore: strip BOM, repair mojibake, add .gitattributes` (WP8) ✅ `09bf666`
   — executed alongside WP1 as one grouped housekeeping run, hence out of the
   original order.
4. `docs: record the venue plan and apply operator decisions D-3/D-4/D-5` ✅ `58a31c7`
   — **unanticipated.** This document itself, committed once WP0's observed baseline
   discharged the caveat in §2.6.
5. `fix: persist the spec store so the graph survives a rebuild` ✅ `d6de283`
   — **unanticipated, and the most serious finding of the run.** The entire KK
   specification (91 nodes) was missing from `spec/spec.db`. The journal had gone
   uncoalesced since 2026-07-13 because `ril journal coalesce` runs `git add`
   internally, and that call failed against a blanket `combobul/` entry in
   `.gitignore` — silently, so the loss accumulated for two months. Recovered by
   coalesce + rebuild (103 nodes). The recurrence was closed by narrowing the ignore
   so `combobul/spec/mutations` and `combobul/spec/snapshots` are tracked while
   `spec.db` and the engine source stay ignored. **WP2, WP4 and WP7 could not have
   run until this landed**, which is why it precedes them here.
6. `fix: reconcile declared schema with live database` (WP3) ✅ `5826796`
7. `fix: migrate MCP server to the mcp 2.x MCPServer API` (WP0.5) ✅ `d0200bd`
   — ran after WP3 rather than before it; the two are independent.
8. `test: rewrite the /radar tests against research-radar semantics` (WP5, decision
   D-4) ✅ `be361fb`
9. `spec: model venue representation` (WP2 + WP6) ✅ `068915f`
10. `spec: author venue viewer and editor nodes` (WP4) ✅ `7a59e59`
11. `feat: replace /sources with venue viewer and add venue editor` (WP5) ✅ `cac9860`
12. `spec: close dangling MOD-KK-WEB citations` (WP7) ✅ `f22ecd0`

Run `npm run spec:check` before each commit (CLAUDE.md rule 7). Attribution line per
CLAUDE.md. Note git identity is unset (§2.15).

---

## 10. Test plan (WP5)

**`tests/test_venue_store.py` (new, pure domain):**
- `normalise_venue` maps each §2.5 collision pair to one canonical value.
- `normalise_venue` is pure — no DB, no I/O.
- `set_venue` rejects a non-`Source` node; rejects empty; stamps provenance.
- `set_venue` does not re-run `validate_node` (DD-3) — a Source with no Advisory
  still accepts a venue edit.
- `merge_venues` is idempotent; re-running changes nothing.
- `merge_venues` reports the row count it touched.

**`tests/test_web.py` additions:**
- `GET /venues` returns 200 and shows one row per canonical venue.
- Papers nest under their venue; count per venue matches the §2.5 table post-normalisation.
- The 107 no-venue Sources appear in the specified bucket (DD-5).
- **Query-count assertion**: `/venues` issues ≤ 3 queries regardless of corpus size
  (`INV-KK-WEB-QUERY-BOUNDED`).
- `GET /sources` returns 404.
- `PUT /api/venue/{id}` 200 for a Source, 404 for a non-Source, 422 for empty.
- Allowlist test: every registered POST/PUT/DELETE path starts with a
  `WEB_MUTATION_ALLOWLIST` prefix (`INV-KK-WEB-MUTATION-ALLOWLISTED`).
- Per D-2, authorisation test for the mutating venue routes.

**Regression (must pass unmodified):** all `/radar`, `/feed`, `/paper`, `/reviews`,
`/reviewers`, `/health`, `/impact`, `/api/search` tests.

---

## 11. Fixture design

`paginated_client` (`tests/test_web.py:822-840`) builds 15 Concepts and 1 Subsystem —
it is a *pagination* fixture and dies with WP1. The venue tests need a **venue fixture**:
Sources carrying the §2.5 collision pairs (`OSDI 2026`, `OSDI`, `OSDI 2025`, `SOSP`,
`SOSP 2025`) plus at least two no-venue Sources with distinct `source_type`s, so
normalisation and the DD-5 bucket are both exercised.

Note fresh fixture DBs get the SQL CHECK; under Option A they will reject `kind='Venue'`
until WP3 + §6 land. **Build the fixture after WP3, not before.**

---

## 12. Verification commands

```bash
npm run spec:check                                    # expect 0 errors
npm run ril -- query module-context MOD-KK-WEB --json
npm run ril -- query node-info INV-KK-WEB-QUERY-BOUNDED --json
./venv/bin/pytest -q                                  # after WP0
grep -n "WEB_MUTATION_ALLOWLIST" -A 8 src/web/routes.py
grep -rn "concept_list.html" src/ tests/              # expect 0 after WP5
python3 -c "import sqlite3;print(sqlite3.connect('file:data/master.db?mode=ro',uri=True).execute(\"SELECT sql FROM sqlite_master WHERE name='nodes'\").fetchone()[0])"
```

Venue distribution re-check:

```bash
python3 - <<'EOF'
import sqlite3, json, collections
c = sqlite3.connect("file:data/master.db?mode=ro", uri=True)
v = collections.Counter(); missing = collections.Counter()
for (a,) in c.execute("SELECT attrs FROM nodes WHERE kind='Source'"):
    d = json.loads(a or "{}")
    if d.get("venue"): v[d["venue"]] += 1
    else: missing[d.get("source_type","?")] += 1
print(len(v), "venues;", sum(v.values()), "with;", sum(missing.values()), "without")
print(v.most_common()); print(missing.most_common())
EOF
```

---

## 13. Known risks and accepted trade-offs

- **R-1.** The 64/141 figure is static, not observed (§2.6). WP0 discharges it.
- **R-2.** Option A requires a 3,467-Source backfill against a 22MB production DB.
  `data/master.db.bak-pre-abstracts` exists as a prior backup precedent; take a fresh one.
- **R-3.** Normalisation is a judgement call. `OSDI 2026` vs `OSDI` may legitimately be
  a series-vs-instance distinction rather than a duplicate. D-1 must say which.
- **R-4.** The `arXiv cs.*` categories are 82% of the corpus. Whatever the rule, the
  page is dominated by them unless they are treated specially. Accepted: specify in WP2.
- **R-5.** `MOD-KK-WEB` nodes are all `riStatus=unchecked`, `nl-only`, 0 source
  locations. New nodes will not be mechanically verified against code. Mitigate with
  `ril associate`; do not claim verification the tooling does not perform.

---

## 14. Decisions — both answered 2026-09-15

Both were answered by the operator before WP2 was authored. The option tables are
kept as the rationale record; the answers are stated with each.

**D-1 — Venue representation. ANSWERED: Option A.** `Venue` is a first-class node
kind, linked from a Source by a `published-at` edge. Shipped in `068915f`
(`IFC-KK-VENUE`, `INV-KK-VENUE-NORMALISED`, `INV-KK-VENUE-NAME-UNIQUE`,
`INV-KK-VENUE-SOURCE-EDGE`, `ALG-KK-VENUE-BACKFILL`) and `cac9860`.

| | Option A: first-class node kind | Option B: attribute + normalisation |
|---|---|---|
| Model | `Venue` node + `published-at` edge from Source | `Source.attrs.venue` stays |
| Viewer | Real traversal, like radar | `GROUP BY` on a normalised string |
| Editor | Node mutation (rename = 1 row) | Bulk rewrite (up to 897 rows) |
| Schema | `NODE_KINDS`, `EDGE_KINDS`, `EDGE_VALID_PAIRS`, `REQUIRED_ATTRS`, `ID_PREFIXES`, `RULES_BY_KIND` | none |
| Migration | 3,467-Source backfill + ~20–34 Venue nodes | none |
| Blocked by | WP3 (schema drift) | not blocked |
| Cost | High | Low |
| Fidelity | Matches "similar to radar" literally | Approximates it |

**D-2 — Authorisation for venue mutation. ANSWERED: the suggested default was
adopted.** `PUT /api/venue/{source_id}` touches one Source and requires only an
authenticated user, matching `PUT /api/abstract/{source_id}`. `POST /api/venue/merge`
can repoint up to 897 Sources and requires `role == 'admin'` via
`authgate.app.require_admin`. Specified by `INV-KK-VENUE-MUTATION-AUTHORISED`
(`068915f`); this is the first role check on any `MOD-KK-WEB` mutating endpoint.

---

## 15. Suggested `/cb-*` sequence

```
1.  /cb-ops    install pytest and project deps            → WP0
2.  /cb-fix    delete 64 dead tests, fix README            → WP1   ┐
3.  /cb-fix    reconcile declared vs live schema           → WP3   │ parallel
4.  /cb-green  author venue model (needs D-1, D-2)         → WP2   │
5.  /cb-green  author ALG-KK-WEB-VENUES + editor nodes     → WP4   │
6.  /cb-green  implement viewer, editor, removal, tests    → WP5   │
7.  /cb-green  close dangling citations                    → WP7   │
8.  /cb-fix    BOM, mojibake, .gitattributes               → WP8   ┘
```

Critical path: 1 → 4 → 5 → 6. Packages 2, 3, 7, 8 are independent.

---

## 16. Deliberately out of scope

- `_BASE_URL = "http://10.123.102.166:8000"` hardcoded at `src/web/routes.py:530`,
  baked into every feed card's `concept_url` and `research_card_url`
  (`ALG-KK-WEB-FEED-CARD`, `ALG-KK-WEB-FEED-SEND`). Configuration issue; track separately.
- The 5 pre-existing orphaned algorithms in §2.13 other than via WP4's one `satisfies` edge.
- The 238 non-web dangling KK ids (§2.8) across ingest, graph, mcp_server, export.
- `.claude/skills/cb-audit/templates/ap2-analyze.request.json` stale
  `spec:conformance` instruction (§2.16).
- `data/auth.db` churning as a tracked file (it holds live session tokens and is
  modified by ordinary use).
- Whether `CLAUDE.md`, which describes combobul, should describe know-kernel.
