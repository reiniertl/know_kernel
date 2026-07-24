# Research Card Feature — Implementation Plan

Date: 2026-07-16
Status: PLANNED
Estimated skills: 3 `/cb-green` invocations

## Problem Statement

The research feed currently sends concept-centric cards when sharing papers.
This is wrong for two reasons:

1. **Missing paper link.** The card includes a link to the concept page
   (`/research/{concept_id}`) but NOT the paper's source URL (e.g. the arxiv
   link). Users need the paper link to actually read the research.

2. **Concept card vs research card.** A kernel concept (e.g. "RCU",
   "Spinlock") is a timeless mechanism. A paper is a time-bound research
   contribution with specific ideas, methodology, and findings. The feed
   should send a per-paper **research card** — not a per-concept card.
   Each paper has one research card. A concept can have many papers.

## Current Architecture

### Knowledge Graph Structure

```
Source (paper: title, url, source_type, published_date)
  ← sourced-from ← Evidence (text: abstract/PDF content)
    ← extracted-from ← Concept (name, description, key_properties, ...)
```

197 Source nodes of research types (conference-paper: 152, preprint: 37,
paper: 4, conference-proceedings: 4). Of these, 41 have substantial
Evidence text (>100 chars from PDF extraction), 156 have short/empty text.

### Graph Schema (src/graph/schema.py)

- `NODE_KINDS`: tuple of 24 node kinds. `ResearchBrief` is NOT present.
- `EDGE_KINDS`: tuple of 26 edge kinds. `summarizes-for` is NOT present.
- `EDGE_VALID_PAIRS`: dict mapping edge kind → (source_kind, target_kind).
- `REQUIRED_ATTRS`: dict mapping node kind → required attribute tuple.
- `ID_PREFIXES`: dict mapping node kind → id prefix string.
- `SCHEMA_SQL`: DDL with CHECK constraints built from NODE_KINDS/EDGE_KINDS.
  **Modifying NODE_KINDS or EDGE_KINDS requires ALTER TABLE on existing
  databases** (the CHECK constraint references the old set).

### Feed Card Code (src/web/routes.py)

- `_build_single_card_text(item)` (line 953): builds a text card from a
  dict with keys: source_type, concept, motivations, subsystems, summary,
  concept_url, url. Currently includes concept_url OR url, not both.
- `feed_card_json` endpoint (line 977): `GET /api/feed/card/{source_id}` —
  queries Source→Evidence→Concept chain, builds item dict, calls
  `_build_single_card_text`.
- `feed_send_card` endpoint (line 1021): `POST /api/feed/send/{source_id}` —
  same query, builds card, replaces `<CARD>` placeholder in CLI command.
- `_BASE_URL = "http://10.123.102.166:8000"` (line 951).

### Existing Extraction Infrastructure

- `src/ingest/extractor.py`: `extract_concepts()` — LLM-based concept
  extraction from Evidence text. Uses `EXTRACTION_SYSTEM_PROMPT` (detailed
  prompt for 2-5 word concept names). Uses `AnthropicClientAdapter` wrapping
  the Anthropic SDK. Model default: `claude-sonnet-4-6`.
- `src/ingest/claim_extractor.py`: `extract_claims()` — LLM-based claim
  extraction (Problems, Observations, Proposals, etc.). Uses
  `CLAIM_EXTRACTION_PROMPT`. Same client adapter pattern.
- Both follow the same pattern: read Evidence text → build prompt with
  context → call LLM → parse JSON response → validate → create nodes + edges.
- `LLMClient` protocol: `create_message(model, system, user, max_tokens) → dict`
  with keys `text`, `prompt_tokens`, `response_tokens`.

### Spec Surface (combobul DAG)

Existing nodes in scope:

| Node ID | Kind | Module | Description |
|---|---|---|---|
| ALG-KK-WEB-FEED-LIST | algorithm | MOD-KK-WEB | Render /feed flat table |
| ALG-KK-WEB-FEED-CARD | algorithm | MOD-KK-WEB | Build single-paper card text |
| ALG-KK-WEB-FEED-SEND | algorithm | MOD-KK-WEB | POST send card via CLI |
| ALG-KK-WEB-RADAR | algorithm | MOD-KK-WEB | Render /radar subsystem→concept→papers |
| ALG-KK-DATA-CLEANUP-CONCEPTS | algorithm | MOD-KK-INGEST | Concept cleanup script |
| ALG-KK-DATA-REPAIR-PAPER-LINKS | algorithm | MOD-KK-INGEST | Paper link repair script |
| MOD-KK-WEB | module | — | Web presentation layer |
| MOD-KK-INGEST | module | — | Ingestion subsystem |

---

## Phase 1: Schema + Extraction Pipeline (`/cb-green` #1)

### Goal

Add the `ResearchBrief` node kind to the knowledge graph, create the LLM
extraction pipeline, and populate `master.db` with research briefs for all
papers that have Evidence text.

### Spec Nodes to Create

#### Algorithms

1. **ALG-KK-RESEARCH-BRIEF-EXTRACT** (MOD-KK-INGEST)
   - Description: Extract a ResearchBrief from a paper's Evidence text via
     LLM. Creates one ResearchBrief node per paper with key_ideas, relevance,
     methodology. Links to Evidence via extracted-from edge and to Concept via
     summarizes-for edge.
   - Precondition: Evidence node exists with non-empty text. At least one
     Concept linked to the Evidence via extracted-from edge.
   - Postcondition: One ResearchBrief node created with key_ideas (1-3 items),
     relevance (1-2 sentences), methodology (string). Edges: extracted-from →
     Evidence, summarizes-for → Concept.
   - Language: py
   - Purity: false (side-effects: LLM call, DB writes)
   - runs-at: tier-implemented

2. **ALG-KK-RESEARCH-BRIEF-BATCH** (MOD-KK-INGEST)
   - Description: Batch orchestrator: iterate all Source nodes of research
     types that have Evidence with text but no linked ResearchBrief. Run
     ALG-KK-RESEARCH-BRIEF-EXTRACT for each. Print summary.
   - Precondition: master.db populated with Source+Evidence nodes. ANTHROPIC_API_KEY set.
   - Postcondition: ResearchBrief nodes created for all eligible papers.
     Summary printed: extracted count, skipped count (no text), error count.
   - Language: py
   - Purity: false
   - runs-at: tier-implemented

#### Invariants

3. **INV-KK-RESEARCH-BRIEF-ONE-PER-PAPER** (MOD-KK-INGEST)
   - Predicate: `forall s in Source. count(ResearchBrief rb : exists path rb --extracted-from--> ev --sourced-from--> s) <= 1`
   - PredicateNL: Each Source node has at most one ResearchBrief linked through its Evidence chain.
   - Checked-at: tier-implemented
   - Strength: structural, scope: per-object

4. **INV-KK-RESEARCH-BRIEF-HAS-IDEAS** (MOD-KK-INGEST)
   - Predicate: `forall rb in ResearchBrief. len(rb.key_ideas) >= 1 AND len(rb.key_ideas) <= 5`
   - PredicateNL: Every ResearchBrief must have between 1 and 5 key research ideas.
   - Checked-at: tier-implemented

5. **INV-KK-RESEARCH-BRIEF-LINKED** (MOD-KK-INGEST)
   - Predicate: `forall rb in ResearchBrief. exists edge(rb, extracted-from, ev) where ev.kind = Evidence`
   - PredicateNL: Every ResearchBrief must have an extracted-from edge to an Evidence node.
   - Checked-at: tier-implemented

### Code Changes

#### `src/graph/schema.py`

1. Add `"ResearchBrief"` to `NODE_KINDS` tuple.
2. Add `"summarizes-for"` to `EDGE_KINDS` tuple.
3. Add to `EDGE_VALID_PAIRS`:
   ```python
   "extracted-from": [...existing..., ("ResearchBrief", "Evidence")],
   "summarizes-for": ("ResearchBrief", "Concept"),
   ```
4. Add to `REQUIRED_ATTRS`:
   ```python
   "ResearchBrief": ("title", "key_ideas", "relevance", "methodology", "source_date", "artifact_class"),
   ```
5. Add to `ID_PREFIXES`:
   ```python
   "ResearchBrief": "rb-",
   ```

**IMPORTANT — ALTER TABLE required for existing databases:** The `SCHEMA_SQL`
template bakes NODE_KINDS/EDGE_KINDS into CHECK constraints. For `master.db`
(which already has the old CHECK), the batch script must run:
```sql
-- SQLite does not support ALTER TABLE ... ALTER CONSTRAINT.
-- Must recreate tables or disable constraint checking for insert.
-- Approach: use PRAGMA writable_schema or recreate via dump/reload.
-- Simplest: the batch script opens with PRAGMA foreign_keys=OFF and
-- drops + recreates the CHECK constraint via temp table migration.
```
Alternatively, the batch script can call `init_db()` on a fresh path and
migrate data, or use `PRAGMA writable_schema=ON` to update the CHECK.
**Decision: the batch script should call a `migrate_schema(conn)` function
that handles this.**

#### `src/ingest/research_brief_extractor.py` (NEW)

This file implements ALG-KK-RESEARCH-BRIEF-EXTRACT.

```python
RESEARCH_BRIEF_PROMPT = """\
You are a research intelligence agent for a kernel development team.

Given a research paper's abstract or full text, extract a RESEARCH BRIEF
that captures what this paper contributes to kernel research.

Return a JSON object with these keys:

"key_ideas": [
    "One sentence per research idea or contribution (1-5 items)"
]

"relevance": "1-2 sentences explaining why this matters for Linux kernel
development. Be specific about which kernel subsystems or mechanisms benefit."

"methodology": "The research approach used (e.g., 'eBPF-based tracing',
'formal verification', 'hardware simulation', 'workload characterization',
'static analysis'). One phrase or short sentence."

RULES:
- Extract ONLY what the paper actually says. Do not embellish.
- key_ideas should capture the NOVEL contributions, not background.
- relevance must connect to concrete kernel areas, not vague statements.
- If the paper is not about kernel/OS topics, set relevance to
  "Not directly kernel-related" and still extract key ideas.
"""
```

Functions:
- `extract_research_brief(conn, evidence_id, source_date, model, dry_run, client, source_text) -> ResearchBriefResult`
  - Follows the same pattern as `extract_claims`:
    1. Read Evidence text (from DB or `source_text` param)
    2. Build user prompt with paper title context
    3. Call LLM
    4. Parse JSON response
    5. Validate: key_ideas must be list with 1-5 strings, relevance must be
       non-empty string, methodology must be non-empty string
    6. Create ResearchBrief node with attrs:
       - `title`: paper title (from Source node)
       - `key_ideas`: validated list
       - `relevance`: validated string
       - `methodology`: validated string
       - `source_date`: from parameter
       - `artifact_class`: "B"
    7. Create edges:
       - `extracted-from`: ResearchBrief → Evidence
       - `summarizes-for`: ResearchBrief → each linked Concept
    8. Return result dataclass

- `ResearchBriefResult` dataclass:
  - `evidence_id: str`
  - `brief_id: str`
  - `key_ideas_count: int`
  - `concepts_linked: int`
  - `extraction_model: str`
  - `prompt_tokens: int`
  - `response_tokens: int`

- `validate_research_brief(parsed: dict) -> dict | None`
  - Checks key_ideas is list of 1-5 non-empty strings
  - Checks relevance is non-empty string
  - Checks methodology is non-empty string
  - Returns validated dict or None

#### `data/extract_research_briefs.py` (NEW)

This file implements ALG-KK-RESEARCH-BRIEF-BATCH.

```python
def main():
    conn = sqlite3.connect("data/master.db")
    # 1. Migrate schema (add ResearchBrief to CHECK constraint)
    migrate_schema(conn)

    # 2. Find all research Sources with Evidence text but no ResearchBrief
    orphans = find_papers_without_brief(conn)
    # Query: Source JOIN Evidence WHERE source_type IN research types
    #   AND Evidence.text length > 100
    #   AND NOT EXISTS (ResearchBrief --extracted-from--> Evidence)

    # 3. For each, run extract_research_brief
    for paper in orphans:
        result = extract_research_brief(conn, paper.evidence_id, paper.source_date)
        conn.commit()
        print(f"  {paper.source_id}: {result.key_ideas_count} ideas")

    # 4. Checkpoint WAL
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
```

**For papers WITHOUT Evidence text (156 of 197):** These have empty or
very short Evidence text. The batch script should handle them by using the
Source title as a minimal prompt, or skip them and log as "no text available".
**Decision needed at implementation time:** use title-only extraction (lower
quality but covers all papers) vs skip (41 papers with briefs, 156 without).
The prompt should instruct that if given only a title, extract what can be
inferred about the research direction from the title alone.

#### `data/master.db`

After running the batch script, the database will contain:
- ~41 high-quality ResearchBrief nodes (from papers with full text)
- ~156 title-only ResearchBrief nodes (if we extract from titles)
- Or ~41 ResearchBrief nodes + 156 papers without briefs (if we skip)

Commit the checkpointed master.db.

---

## Phase 2: Feed Card Updates — Paper URL + Research Card (`/cb-green` #2)

### Goal

1. Add paper source URL to the existing concept card.
2. Add a new research card format that shows the ResearchBrief content.
3. Add research card endpoints and UI controls.

### Spec Nodes to Create

#### Algorithms

1. **ALG-KK-WEB-FEED-RESEARCH-CARD** (MOD-KK-WEB)
   - Description: Build per-paper research card text from ResearchBrief
     node: paper title, paper source URL, key research ideas, relevance,
     methodology, concept link, subsystem badges.
   - Precondition: source_id valid; ResearchBrief node exists for this
     paper's Evidence chain.
   - Postcondition: Multi-line string: paper title, paper URL, numbered
     key ideas, relevance paragraph, methodology tag, concept link,
     subsystem badges.
   - Language: py
   - runs-at: tier-implemented

#### Algorithms to Modify

2. **ALG-KK-WEB-FEED-CARD** (MOD-KK-WEB)
   - MODIFY description: "Build emoji card text for a single paper: type
     emoji, concept name, motivation tags, truncated summary, subsystem
     tags, paper source URL, research detail URL."
   - MODIFY postconditionNL: add "paper source URL" to the output.

3. **ALG-KK-WEB-FEED-SEND** (MOD-KK-WEB)
   - MODIFY description: add research card send endpoint.

4. **ALG-KK-WEB-FEED-LIST** (MOD-KK-WEB)
   - MODIFY postconditionNL: add "per-item research card button" to controls.

#### Invariants

5. **INV-KK-FEED-CARD-PAPER-URL** (MOD-KK-WEB)
   - Predicate: `forall card in feed_card_output. Source.url != "" implies card contains Source.url`
   - PredicateNL: Feed concept cards must include the paper's source URL
     when the Source node has a non-empty url attribute.
   - Checked-at: tier-implemented

6. **INV-KK-FEED-RESEARCH-CARD-FORMAT** (MOD-KK-WEB)
   - Predicate: `forall rc in research_card_output. rc contains key_ideas AND rc contains paper_url AND rc contains concept_link`
   - PredicateNL: Research cards must include the paper's key research ideas,
     paper source URL, and concept detail link.
   - Checked-at: tier-implemented

### Code Changes

#### `src/web/routes.py`

1. **`_build_single_card_text(item)`** (line 953):
   - Add paper source URL to card output. Currently the card shows
     `concept_url` OR `url`, never both. Change to show both:
     ```
     📎 *Concept Name*
        SECURITY PERFORMANCE
        📂 [Synchronization]
        _Summary text..._
        📄 https://arxiv.org/abs/...       ← NEW: paper link
        🔗 http://10.123.../research/id    ← existing: concept link
     ```
   - The item dict already has `url` (paper URL) and `concept_url`.
     Change the logic from "concept_url OR url" to "both when available".

2. **New function `_build_research_card_text(brief, item)`:**
   ```python
   def _build_research_card_text(brief: dict, item: dict) -> str:
       """Build research card text from ResearchBrief (ALG-KK-WEB-FEED-RESEARCH-CARD)."""
       lines = [f"🔬 *{item.get('title', '')}*"]
       if item.get("url"):
           lines.append(f"   📄 {item['url']}")
       ideas = brief.get("key_ideas", [])
       if ideas:
           lines.append("   *Key Ideas:*")
           for i, idea in enumerate(ideas, 1):
               lines.append(f"   {i}. {idea}")
       relevance = brief.get("relevance", "")
       if relevance:
           lines.append(f"   *Relevance:* _{relevance}_")
       methodology = brief.get("methodology", "")
       if methodology:
           lines.append(f"   🔧 {methodology}")
       concept_url = item.get("concept_url", "")
       if concept_url:
           lines.append(f"   🔗 {concept_url}")
       return "\\n".join(lines).replace("\n", "\\n")
   ```

3. **New endpoint `GET /api/feed/research-card/{source_id:path}`:**
   - Query Source→Evidence→ResearchBrief chain.
   - If no ResearchBrief found, return 404 with `{"error": "No research brief for this paper"}`.
   - Build research card text via `_build_research_card_text`.
   - Return JSON: `{"source_id": ..., "card": ..., "brief": {...}}`.
   - SQL query:
     ```sql
     SELECT rb.id, rb.attrs, s.attrs as s_attrs, c.id as concept_id, c.attrs as concept_attrs
     FROM nodes s
     JOIN edges se ON se.kind = 'sourced-from' AND se.target_id = s.id
     JOIN nodes ev ON ev.id = se.source_id AND ev.kind = 'Evidence'
     JOIN edges re ON re.kind = 'extracted-from' AND re.source_id = rb_candidate.id AND re.target_id = ev.id
     JOIN nodes rb_candidate ON rb_candidate.kind = 'ResearchBrief'
     ...
     ```
     Simpler approach: query the ResearchBrief that has extracted-from edge
     to the Evidence that has sourced-from edge to the Source.

4. **New endpoint `POST /api/feed/send-research/{source_id:path}`:**
   - Same as feed_send_card but uses `_build_research_card_text` instead
     of `_build_single_card_text`.
   - Same CLI command template + `<CARD>` placeholder mechanism.

5. **`feed_card_json` endpoint (line 977):**
   - Add `paper_url` to the returned item dict (already has `url` field
     but need to ensure it's included in the card text).

#### `src/web/templates/feed.html`

1. Add a "Research" button per paper row alongside "Preview" and "Send":
   ```html
   <button onclick="previewResearchCard('{{ item.source_id }}', this)" ...>Research</button>
   <button onclick="sendResearchCard('{{ item.source_id }}', this)" ...>Send Research</button>
   ```

2. Add JS functions `previewResearchCard(sourceId, btn)` and
   `sendResearchCard(sourceId, btn)`:
   - `previewResearchCard`: fetch `/api/feed/research-card/{sourceId}`,
     show in the collapsible preview row.
   - `sendResearchCard`: POST to `/api/feed/send-research/{sourceId}`
     with CLI command template.

---

## Phase 3: Radar Integration (`/cb-green` #3, optional)

### Goal

Show research brief availability on the radar page. Mark concepts that
have papers with research briefs. Allow drill-down to research card
from the radar's paper list.

### Spec Nodes to Modify

1. **ALG-KK-WEB-RADAR** (MOD-KK-WEB)
   - MODIFY postconditionNL: each paper in the expandable list includes
     a "Research" link/indicator if a ResearchBrief exists.

### Code Changes

#### `src/web/routes.py`

1. In `radar()` route: for each paper in the papers list, check if a
   ResearchBrief exists (via Evidence chain). Add `has_research_brief: bool`
   to each paper dict.

#### `src/web/templates/radar.html`

1. In the paper rows within the concept drill-down, show a "🔬" indicator
   or link for papers that have research briefs.

---

## Decision Log

These decisions must be resolved at implementation time. The `/cb-green`
prompts should include these as DECISION PROTOCOL items.

| # | Decision | Options | Recommendation |
|---|---|---|---|
| D1 | LLM model for research brief extraction | claude-sonnet-4-6 (best quality, ~$0.003/paper), claude-haiku-4-5 (cheaper, ~$0.0003/paper) | Sonnet for papers with full text, Haiku for title-only |
| D2 | Papers without Evidence text (156 of 197) | (a) Extract from title only, (b) Skip, (c) Use Source title + concept description as proxy | (a) title-only with a modified prompt |
| D3 | Edge kind name for ResearchBrief → Concept | summarizes-for, research-for, analyzes | summarizes-for |
| D4 | Research card replaces or coexists with concept card | (a) Replace, (b) Coexist as separate buttons, (c) Research card is default, concept card is fallback | (b) Coexist — Send = concept card, Research = research card |
| D5 | ALTER TABLE migration strategy for CHECK constraint | (a) Recreate tables, (b) PRAGMA writable_schema, (c) Drop CHECK and use app-level validation | (c) Drop CHECK — the app-level validation in add_node() already enforces kinds |

## File Inventory

### New Files

| File | Phase | Purpose |
|---|---|---|
| `src/ingest/research_brief_extractor.py` | 1 | LLM extraction: ResearchBrief from Evidence text |
| `data/extract_research_briefs.py` | 1 | Batch script: run extraction on all eligible papers |

### Modified Files

| File | Phase | Changes |
|---|---|---|
| `src/graph/schema.py` | 1 | Add ResearchBrief to NODE_KINDS, EDGE_KINDS, EDGE_VALID_PAIRS, REQUIRED_ATTRS, ID_PREFIXES |
| `src/web/routes.py` | 2 | _build_single_card_text (add paper URL), _build_research_card_text (new), GET /api/feed/research-card/{source_id} (new), POST /api/feed/send-research/{source_id} (new) |
| `src/web/templates/feed.html` | 2 | Research button per row, previewResearchCard/sendResearchCard JS functions |
| `src/web/templates/radar.html` | 3 | Research brief indicator per paper in drill-down |
| `data/master.db` | 1 | Populated with ResearchBrief nodes |

### Spec Nodes Summary

| Node ID | Kind | Action | Module | Phase |
|---|---|---|---|---|
| ALG-KK-RESEARCH-BRIEF-EXTRACT | algorithm | CREATE | MOD-KK-INGEST | 1 |
| ALG-KK-RESEARCH-BRIEF-BATCH | algorithm | CREATE | MOD-KK-INGEST | 1 |
| INV-KK-RESEARCH-BRIEF-ONE-PER-PAPER | invariant | CREATE | MOD-KK-INGEST | 1 |
| INV-KK-RESEARCH-BRIEF-HAS-IDEAS | invariant | CREATE | MOD-KK-INGEST | 1 |
| INV-KK-RESEARCH-BRIEF-LINKED | invariant | CREATE | MOD-KK-INGEST | 1 |
| ALG-KK-WEB-FEED-RESEARCH-CARD | algorithm | CREATE | MOD-KK-WEB | 2 |
| INV-KK-FEED-CARD-PAPER-URL | invariant | CREATE | MOD-KK-WEB | 2 |
| INV-KK-FEED-RESEARCH-CARD-FORMAT | invariant | CREATE | MOD-KK-WEB | 2 |
| ALG-KK-WEB-FEED-CARD | algorithm | MODIFY | MOD-KK-WEB | 2 |
| ALG-KK-WEB-FEED-SEND | algorithm | MODIFY | MOD-KK-WEB | 2 |
| ALG-KK-WEB-FEED-LIST | algorithm | MODIFY | MOD-KK-WEB | 2 |
| ALG-KK-WEB-RADAR | algorithm | MODIFY | MOD-KK-WEB | 3 |

Total: 8 CREATE, 4 MODIFY across 2 modules and 3 phases.
