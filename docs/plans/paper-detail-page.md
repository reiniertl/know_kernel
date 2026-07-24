# Paper Detail Page — Implementation Plan

Date: 2026-07-16
Status: PLANNED
Estimated skills: 1 `/cb-green` invocation

## Problem Statement

The current "research card" implementation is wrong. It is a text-only
messaging blob (`_build_research_card_text()`) served via JSON API endpoints.
It contains a title, URL, numbered ideas, and a concept link. That is a
notification payload, not a research card.

A research card must be a **full HTML page** at `/paper/{source_id}` — the
per-paper equivalent of the concept card at `/research/{concept_id}`. It
shows a kernel specialist the complete picture of what a single paper
contributes: its research ideas, how it connects to kernel concepts, which
subsystems it touches, and what invariants, failure modes, problems, and
proposals are relevant through the concept chain.

## Current Architecture

### Concept Detail Page (`/research/{concept_id}`)

The existing concept detail page (`research_detail()` in `src/web/routes.py`
line 660) is the reference implementation. It renders `research_detail.html`
with this data:

- **concept node** — name, description, key_properties, tradeoffs, design_rationale
- **brief** — 15-key dict from `build_concept_brief(conn, concept_id)` containing:
  problems, vulnerabilities, failure_modes, invariants, protocols, profiles,
  prerequisites, fixes, observations, discussions, benchmarks, timeline,
  code_examples, scores, subsystem
- **motivations** — from `classify_motivations(brief)`, 1-7 categories each with:
  category, label, icon, headline, actionable statement, blast_radius
  (count + component links), evidence items, cross_links
- **argument** — from `build_argument_paragraph()`
- **scores** — heat, pain, impact, leverage, frontier, research, feasibility
- **proposals** — with addressed problems and source URLs
- **related_research** — concepts in same subsystem with research scores
- **all_evidence** — filtered timeline of Discussion, Observation, Benchmark,
  Proposal, Problem items with source URLs

Template sections in `research_detail.html`:
1. Header — concept name, subsystem badge, maturity badge
2. Research Assessment — 3-column scores (research, feasibility, impact)
3. Research Activity — evidence counts, proposals list
4. The Case — argument paragraph
5. Why Pursue This — motivation categories with blast radius, invariants,
   failure modes, evidence items
6. Scores — full 7-column table
7. Related Research — linked concepts with scores
8. Evidence Timeline — date/type/text/source/detail table
9. Dependencies — depends_on and depended_on_by concept lists

### What Exists for Papers Now (to be replaced)

| Code | Location | Purpose | Disposition |
|---|---|---|---|
| `_build_research_card_text()` | routes.py:1082 | Text blob builder | REMOVE |
| `_query_research_brief()` | routes.py:1110 | Text blob helper query | REMOVE |
| `GET /api/feed/research-card/{source_id}` | routes.py:1140 | JSON text blob endpoint | REMOVE |
| `POST /api/feed/send-research/{source_id}` | routes.py:1164 | Send text blob via CLI | REMOVE |
| `previewResearchCard()` JS | feed.html | Fetch text blob preview | REMOVE |
| `sendResearchCard()` JS | feed.html | Send text blob | REMOVE |
| "Research" button | feed.html | Trigger text blob preview | REMOVE |
| "Send Research" button | feed.html | Trigger text blob send | REMOVE |
| `previewRadarResearch()` JS | radar.html | Radar text blob preview | REMOVE |
| `🔬` indicator | radar.html | Radar research brief link | REPLACE with `/paper/` link |
| `radar-rb-{source_id}` preview row | radar.html | Inline preview | REMOVE |
| `has_research_brief` query | routes.py:1244 | Per-paper EXISTS check in radar | REMOVE (link always shown) |

### Graph Chain

The paper detail page traverses this chain to assemble content:

```
Source (paper)
  ← sourced-from ← Evidence
    ← extracted-from ← ResearchBrief (key_ideas, relevance, methodology)
    ← extracted-from ← Concept(s) (name, description, key_properties, ...)
      → belongs-to → Subsystem
      ← identifies-problem ← Problem
      ← observes ← Observation
      ← discusses ← Discussion
      ← benchmarks ← Benchmark
      ← grounded-in ← Proposal
      ← exploits ← Vulnerability
      ← patches ← Fix
      → governed-by → KernelInvariant
      → triggered-by → FailureMode (through KernelInvariant)
```

For each connected Concept, the page calls `build_concept_brief(conn, concept_id)`
and `classify_motivations(brief)` — the SAME functions that power
`/research/{concept_id}`. This gives the paper page access to invariants,
blast radius, failure modes, problems, proposals, and motivation categories
through each concept.

### Existing Spec Surface

| Node ID | Kind | Module | Current Description |
|---|---|---|---|
| ALG-KK-WEB-FEED-LIST | algorithm | MOD-KK-WEB | Render /feed flat table |
| ALG-KK-WEB-FEED-CARD | algorithm | MOD-KK-WEB | Build single-paper card text |
| ALG-KK-WEB-FEED-SEND | algorithm | MOD-KK-WEB | POST send card via CLI |
| ALG-KK-WEB-RADAR | algorithm | MOD-KK-WEB | Render /radar subsystem→concept→papers |
| ALG-KK-WEB-FEED-RESEARCH-CARD | algorithm | MOD-KK-WEB | Text blob endpoints (TO REMOVE) |
| INV-KK-FEED-CARD-PAPER-URL | invariant | MOD-KK-WEB | Paper URL in text blob (TO REMOVE) |
| INV-KK-FEED-RESEARCH-CARD-FORMAT | invariant | MOD-KK-WEB | Text blob format (TO REMOVE) |
| ALG-KK-WEB-RESEARCH-DETAIL | algorithm | MOD-KK-WEB | Render /research/{concept_id} (reference) |

---

## Page Structure

### Section 1: Header

- Back link: `← Back to Feed`
- Source type badge (e.g. `CONFERENCE-PAPER`)
- Subsystem badges (collected from all connected concepts)
- Paper title (h1)
- Metadata row: venue, published_date, external paper URL link (`source →`)

### Section 2: Research Brief

If a ResearchBrief node exists for this paper (via Evidence chain):
- **Key Ideas** — numbered list (1-5 items) from `rb.attrs.key_ideas` (stored as JSON string, must be parsed)
- **Relevance** — 1-2 sentence paragraph from `rb.attrs.relevance`
- **Methodology** — badge/tag from `rb.attrs.methodology`

If no ResearchBrief exists:
- "No research brief extracted yet." message

### Section 3: Connected Concepts

Card grid (same layout as Related Research in concept detail). Each card:
- Concept name (linked to `/research/{concept_id}`)
- Research score from `research_score(conn, concept_id)`
- Subsystem name from `belongs-to` edge
- Short description (truncated to 100 words)

### Section 4: Why This Matters

Aggregated motivations from ALL connected concepts. Uses the same
`classify_motivations(brief)` output structure as `research_detail.html`.

Aggregation strategy: deduplicate by motivation category (security,
stability, performance, etc.). For each category:
- Merge evidence lists from all concepts that trigger that category
- Label each evidence item with its source concept name
- Show combined blast radius (union of components across concepts)
- Show combined invariants, failure modes, problems

Template reuses the exact same Jinja2 block structure as the "Why Pursue
This" section in `research_detail.html` (lines 78-158).

### Section 5: Paper Evidence

Table of claim nodes extracted specifically from THIS paper's Evidence
nodes. These are the paper's direct research contributions.

Query: nodes linked via `extracted-from` to this paper's Evidence nodes,
filtered to kinds: Problem, Observation, Discussion, Benchmark, Proposal,
Rejection.

Table columns: Date | Type (badge) | Evidence text | Source link
Same layout as "Evidence Timeline" in `research_detail.html` (lines 192-217).

---

## Specification Changes

### Nodes to CREATE (3)

#### ALG-KK-WEB-PAPER-DETAIL (algorithm, MOD-KK-WEB)

- **description**: Render `/paper/{source_id}`: query Source → Evidence →
  ResearchBrief and all connected Concepts. For each Concept, call
  `build_concept_brief()` and `classify_motivations()`. Aggregate
  motivations, blast radius, invariants, failure modes, problems, proposals
  across all concepts. Show paper-specific claim evidence. Render
  `paper_detail.html`.
- **preconditionNL**: source_id exists and is a Source node of research type.
- **postconditionNL**: HTML page with: paper header (title, URL, date, type,
  subsystems), research brief (key ideas, relevance, methodology if
  ResearchBrief exists), connected concepts card grid with scores, aggregated
  motivation categories with blast radius and evidence, paper-specific
  evidence timeline. 404 for missing or non-Source nodes.
- **language**: py
- **purity**: true (read-only)
- **runs-at**: tier-implemented

#### INV-KK-WEB-PAPER-404-NON-SOURCE (invariant, MOD-KK-WEB)

- **predicate**: `forall req to /paper/{id}. nodes[id].kind != 'Source' implies HTTP 404`
- **predicateNL**: Paper detail page returns 404 for missing nodes or nodes
  that are not Source kind.
- **enforced**: `{}`
- **checked-at**: tier-implemented

#### INV-KK-WEB-PAPER-CONCEPT-CHAIN (invariant, MOD-KK-WEB)

- **predicate**: `forall paper_page. concepts_shown = {c : exists ev, e1, e2.
  e1=(ev, sourced-from, source) AND e2=(c, extracted-from, ev) AND c.kind=Concept}`
- **predicateNL**: Paper detail page shows all Concepts linked through the
  paper's Evidence chain, each with a link to its concept detail page.
- **enforced**: `{}`
- **checked-at**: tier-implemented

### Nodes to MODIFY (2)

#### ALG-KK-WEB-FEED-LIST

- **postconditionNL** (update): "Flat table ordered by published_date DESC.
  Each paper title links to `/paper/{source_id}`. Per-item concept link,
  subsystem/motivation badges, preview/send controls for concept card."

#### ALG-KK-WEB-RADAR

- **postconditionNL** (update): "Three-level expandable table. Paper rows
  include title linked to `/paper/{source_id}`, type badge, date."

### Nodes to REMOVE (3)

#### ALG-KK-WEB-FEED-RESEARCH-CARD
- Reason: text-blob endpoints replaced by full `/paper/` page.

#### INV-KK-FEED-CARD-PAPER-URL
- Reason: governed text-blob card format, no longer needed.

#### INV-KK-FEED-RESEARCH-CARD-FORMAT
- Reason: governed text-blob card format, no longer needed.

### Spec Node Summary Table

| Node ID | Kind | Action | Module |
|---|---|---|---|
| ALG-KK-WEB-PAPER-DETAIL | algorithm | CREATE | MOD-KK-WEB |
| INV-KK-WEB-PAPER-404-NON-SOURCE | invariant | CREATE | MOD-KK-WEB |
| INV-KK-WEB-PAPER-CONCEPT-CHAIN | invariant | CREATE | MOD-KK-WEB |
| ALG-KK-WEB-FEED-LIST | algorithm | MODIFY | MOD-KK-WEB |
| ALG-KK-WEB-RADAR | algorithm | MODIFY | MOD-KK-WEB |
| ALG-KK-WEB-FEED-RESEARCH-CARD | algorithm | REMOVE | MOD-KK-WEB |
| INV-KK-FEED-CARD-PAPER-URL | invariant | REMOVE | MOD-KK-WEB |
| INV-KK-FEED-RESEARCH-CARD-FORMAT | invariant | REMOVE | MOD-KK-WEB |

Total: 3 CREATE, 2 MODIFY, 3 REMOVE.

---

## Code Changes — Detailed

### File 1: `src/web/routes.py`

#### Task 1A: Add `paper_detail()` route (~80-100 lines)

Insert new route BEFORE the radar route (before line 1198). Location:
after the `feed_send_card()` endpoint (line 1080) and REPLACING the
removed text-blob code (lines 1082-1196).

```python
@app.get("/paper/{source_id:path}", response_class=HTMLResponse)
async def paper_detail(request: Request, source_id: str):
    """Paper detail page (ALG-KK-WEB-PAPER-DETAIL).

    INV-KK-WEB-PAPER-404-NON-SOURCE: 404 for missing or non-Source.
    INV-KK-WEB-PAPER-CONCEPT-CHAIN: all concepts shown with links.
    """
    conn = request.app.state.conn
```

Step-by-step query logic:

**Step 1 — Load Source node:**
```python
row = conn.execute(
    "SELECT id, kind, attrs FROM nodes WHERE id = ?", (source_id,)
).fetchone()
if row is None:
    raise HTTPException(status_code=404, detail="Paper not found")
node = _rows_to_dicts([row])[0]
if node["kind"] != "Source":
    raise HTTPException(status_code=404, detail="Not a Source node")
s_attrs = node.get("attrs") or {}
```

**Step 2 — Find all Evidence nodes:**
```python
ev_rows = conn.execute(
    "SELECT ev.id, ev.attrs FROM nodes ev "
    "JOIN edges se ON se.kind = 'sourced-from' AND se.source_id = ev.id "
    "AND se.target_id = ? WHERE ev.kind = 'Evidence'",
    (source_id,),
).fetchall()
evidence_ids = [r[0] for r in ev_rows]
```

**Step 3 — Load ResearchBrief (if exists):**
```python
research_brief = None
if evidence_ids:
    placeholders = ",".join("?" for _ in evidence_ids)
    rb_row = conn.execute(
        f"SELECT rb.attrs FROM nodes rb "
        f"JOIN edges re ON re.kind = 'extracted-from' "
        f"AND re.source_id = rb.id AND re.target_id IN ({placeholders}) "
        f"WHERE rb.kind = 'ResearchBrief' LIMIT 1",
        evidence_ids,
    ).fetchone()
    if rb_row:
        rb_attrs = json.loads(rb_row[0]) if isinstance(rb_row[0], str) else (rb_row[0] or {})
        key_ideas = rb_attrs.get("key_ideas", [])
        if isinstance(key_ideas, str):
            try:
                key_ideas = json.loads(key_ideas)
            except (ValueError, TypeError):
                key_ideas = [key_ideas]
        research_brief = {
            "key_ideas": key_ideas,
            "relevance": rb_attrs.get("relevance", ""),
            "methodology": rb_attrs.get("methodology", ""),
        }
```

**Step 4 — Find all connected Concepts:**
```python
concept_rows = conn.execute(
    f"SELECT DISTINCT c.id, c.attrs FROM nodes c "
    f"JOIN edges ce ON ce.kind = 'extracted-from' "
    f"AND ce.source_id = c.id AND ce.target_id IN ({placeholders}) "
    f"WHERE c.kind = 'Concept'",
    evidence_ids,
).fetchall()
```

**Step 5 — For each Concept, build brief and motivations:**
```python
from graph.briefing import build_concept_brief, classify_motivations
from graph.scoring import research_score

concepts = []
all_motivations = {}  # category -> motivation dict (for dedup/merge)
all_subsystems = set()

for crow in concept_rows:
    cid = crow[0]
    c_attrs = json.loads(crow[1]) if isinstance(crow[1], str) else (crow[1] or {})

    brief = build_concept_brief(conn, cid)
    motivs = classify_motivations(brief)
    rs = research_score(conn, cid)

    sub_name = ""
    if brief.get("subsystem"):
        sub_name = brief["subsystem"].get("name", "")
        all_subsystems.add(sub_name)

    concepts.append({
        "id": cid,
        "name": c_attrs.get("name", cid),
        "description": _truncate_words(c_attrs.get("description", ""), 100),
        "research_score": rs,
        "subsystem": sub_name,
    })

    # Merge motivations by category
    for m in motivs:
        cat = m["category"]
        if cat not in all_motivations:
            all_motivations[cat] = m
        else:
            existing = all_motivations[cat]
            # Merge evidence lists
            existing["evidence"] = existing.get("evidence", []) + m.get("evidence", [])
            # Merge blast radius
            if m.get("blast_radius") and m["blast_radius"].get("count", 0) > 0:
                if not existing.get("blast_radius"):
                    existing["blast_radius"] = m["blast_radius"]
                else:
                    seen_ids = {c["id"] for c in existing["blast_radius"].get("components", [])}
                    for comp in m["blast_radius"].get("components", []):
                        if comp["id"] not in seen_ids:
                            existing["blast_radius"]["components"].append(comp)
                    existing["blast_radius"]["count"] = len(
                        existing["blast_radius"]["components"]
                    )

merged_motivations = list(all_motivations.values())
```

**Step 6 — Load paper-specific claim evidence:**
```python
_CLAIM_KINDS = ("Problem", "Observation", "Discussion", "Benchmark",
                "Proposal", "Rejection")
paper_evidence = []
if evidence_ids:
    ev_ph = ",".join("?" for _ in evidence_ids)
    ck_ph = ",".join("?" for _ in _CLAIM_KINDS)
    claim_rows = conn.execute(
        f"SELECT n.id, n.kind, n.attrs FROM nodes n "
        f"JOIN edges e ON e.kind = 'extracted-from' "
        f"AND e.source_id = n.id AND e.target_id IN ({ev_ph}) "
        f"WHERE n.kind IN ({ck_ph})",
        evidence_ids + list(_CLAIM_KINDS),
    ).fetchall()
    _TEXT_FIELD = {
        "Problem": "title", "Observation": "claim",
        "Discussion": "title", "Benchmark": "result_summary",
        "Proposal": "name", "Rejection": "proposal_title",
    }
    for cr in claim_rows:
        ca = json.loads(cr[2]) if isinstance(cr[2], str) else (cr[2] or {})
        paper_evidence.append({
            "id": cr[0],
            "kind": cr[1],
            "text": ca.get(_TEXT_FIELD.get(cr[1], "title"), ""),
            "source_date": ca.get("source_date", ""),
        })
    paper_evidence.sort(key=lambda x: x.get("source_date") or "", reverse=True)
```

**Step 7 — Render template:**
```python
return templates.TemplateResponse(
    request,
    "paper_detail.html",
    {
        "source": node,
        "s_attrs": s_attrs,
        "research_brief": research_brief,
        "concepts": concepts,
        "motivations": merged_motivations,
        "subsystems": sorted(all_subsystems),
        "paper_evidence": paper_evidence,
    },
)
```

#### Task 1B: REMOVE text-blob code (lines 1082-1196)

Delete these functions and routes entirely:
- `_build_research_card_text()` (lines 1082-1108)
- `_query_research_brief()` (lines 1110-1138)
- `feed_research_card_json()` route (lines 1140-1162)
- `feed_send_research_card()` route (lines 1164-1196)

#### Task 1C: REMOVE `has_research_brief` query from radar

In `radar()` function (currently around line 1244), remove the per-paper
`has_research_brief` EXISTS subquery and the `has_research_brief` key from
the paper dict. The paper title will link to `/paper/{source_id}` instead.

The lines to remove are approximately:
```python
has_rb = conn.execute(
    "SELECT 1 FROM edges re "
    "JOIN nodes rb ON rb.id = re.source_id AND rb.kind = 'ResearchBrief' "
    "JOIN edges se ON se.kind = 'sourced-from' AND se.target_id = ? "
    "JOIN nodes ev ON ev.id = se.source_id AND ev.kind = 'Evidence' "
    "WHERE re.kind = 'extracted-from' AND re.target_id = ev.id "
    "LIMIT 1",
    (sid,),
).fetchone() is not None
```
And remove `"has_research_brief": has_rb,` from the paper dict.

### File 2: `src/web/templates/paper_detail.html` (NEW, ~180 lines)

Extends `base.html`. Full template structure:

**Section 1 — Header:**
```jinja2
<p><a href="/feed">&larr; Back to Feed</a></p>
<div style="display:flex;justify-content:space-between;align-items:baseline;">
  <h1>{{ s_attrs.title or source.id }}</h1>
  <div>
    <span class="badge badge-kind">{{ s_attrs.source_type }}</span>
    {% for sub in subsystems %}
    <span class="badge" style="background:#2980b9;">{{ sub }}</span>
    {% endfor %}
  </div>
</div>
<p style="color:#888;">
  {{ s_attrs.published_date or "" }}
  {% if s_attrs.url %}
  &middot; <a href="{{ s_attrs.url }}" target="_blank">source paper &rarr;</a>
  {% endif %}
</p>
```

**Section 2 — Research Brief:**
```jinja2
<div class="attrs-section">
  <h3>Research Brief</h3>
  {% if research_brief %}
  <div>
    <h4>Key Ideas</h4>
    <ol>
      {% for idea in research_brief.key_ideas %}
      <li>{{ idea }}</li>
      {% endfor %}
    </ol>
    {% if research_brief.relevance %}
    <h4>Relevance</h4>
    <p>{{ research_brief.relevance }}</p>
    {% endif %}
    {% if research_brief.methodology %}
    <p><span class="badge badge-kind">{{ research_brief.methodology }}</span></p>
    {% endif %}
  </div>
  {% else %}
  <p style="color:#888;">No research brief extracted yet.</p>
  {% endif %}
</div>
```

**Section 3 — Connected Concepts:** (card grid)
```jinja2
<div class="attrs-section">
  <h3>Connected Concepts</h3>
  <div style="display:flex;gap:1rem;flex-wrap:wrap;">
    {% for c in concepts %}
    <div class="card" style="flex:1;min-width:200px;max-width:300px;">
      <h4><a href="/research/{{ c.id }}">{{ c.name }}</a></h4>
      <p style="font-size:0.85em;">Research Score: {{ "%.1f"|format(c.research_score) }}</p>
      {% if c.subsystem %}
      <span class="badge" style="background:#2980b9;font-size:0.75em;">{{ c.subsystem }}</span>
      {% endif %}
      {% if c.description %}
      <p style="font-size:0.85em;color:#666;">{{ c.description }}</p>
      {% endif %}
    </div>
    {% endfor %}
  </div>
</div>
```

**Section 4 — Why This Matters:** (aggregated motivations)

Copy the EXACT Jinja2 block from `research_detail.html` lines 78-158
(the "Why Pursue This" section). The template variable name is `motivations`
which matches. The block renders:
- Category heading with icon and label
- Headline
- Actionable statement
- Blast radius with component count and links
- Cross-links
- Evidence items (vulnerability, failure_mode, invariant, problem, profile,
  benchmark, fix)

No changes needed to the Jinja2 — the `motivations` list has the same
structure because it comes from `classify_motivations()`.

**Section 5 — Paper Evidence:**
```jinja2
{% if paper_evidence %}
<div class="attrs-section">
  <h3>Paper Evidence</h3>
  <table>
    <thead><tr><th>Date</th><th>Type</th><th>Evidence</th></tr></thead>
    <tbody>
    {% for ev in paper_evidence %}
    <tr>
      <td style="white-space:nowrap;">{{ ev.source_date or "&mdash;" }}</td>
      <td><span class="badge badge-kind"
        {% if ev.kind == 'Problem' %}style="background:#f1c40f;color:#333;"
        {% elif ev.kind == 'Discussion' %}style="background:#2980b9;"
        {% elif ev.kind == 'Observation' %}style="background:#27ae60;"
        {% elif ev.kind == 'Benchmark' %}style="background:#e67e22;"
        {% elif ev.kind == 'Proposal' %}style="background:#8e44ad;"
        {% endif %}>{{ ev.kind }}</span></td>
      <td>{{ ev.text }}</td>
    </tr>
    {% endfor %}
    </tbody>
  </table>
</div>
{% endif %}
```

### File 3: `src/web/templates/feed.html`

#### Task 3A: Change paper title link

Current (line 34):
```jinja2
{% if item.url %}<a href="{{ item.url }}" target="_blank">{{ item.title }}</a>{% else %}{{ item.title }}{% endif %}
```

Replace with:
```jinja2
<a href="/paper/{{ item.source_id }}">{{ item.title }}</a>
{% if item.url %}<a href="{{ item.url }}" target="_blank" style="font-size:0.8em; margin-left:0.3em;">source &rarr;</a>{% endif %}
```

#### Task 3B: Remove Research/Send Research buttons

Remove from the Actions `<td>` (currently line 53-54):
```html
<button onclick="previewResearchCard(..." ...>Research</button>
<button onclick="sendResearchCard(..." ...>Send Research</button>
```

Keep only Preview and Send buttons.

#### Task 3C: Remove JS functions

Remove `previewResearchCard()` and `sendResearchCard()` functions from the
`<script>` block (approximately lines 128-195 of current feed.html).

### File 4: `src/web/templates/radar.html`

#### Task 4A: Change paper title link

Current (line 72):
```jinja2
{% if p.url %}<a href="{{ p.url }}" target="_blank">{{ p.title }}</a>{% else %}{{ p.title }}{% endif %}
```

Replace with:
```jinja2
<a href="/paper/{{ p.source_id }}">{{ p.title }}</a>
{% if p.url %}<a href="{{ p.url }}" target="_blank" style="font-size:0.8em; margin-left:0.3em;">source &rarr;</a>{% endif %}
```

#### Task 4B: Remove `🔬` indicator and preview row

Remove the `{% if p.has_research_brief %}` conditional block with the `🔬`
link (around lines 73-76) and the `radar-rb-{source_id}` preview `<tr>`
(around lines 78-84).

#### Task 4C: Remove `previewRadarResearch()` JS

Remove the `previewRadarResearch()` function from the `<script>` block
(approximately lines 110-140 of current radar.html).

---

## Open Decisions

### D6 — Concept brief depth

Calling `build_concept_brief()` per concept is ~15 queries each. A paper
linked to 3 concepts = ~45 queries.

**Options:**
- (a) Full brief for all concepts — accurate but slow
- (b) Lightweight query for just motivations + scores — fast but less data
- (c) Full brief for first concept, lightweight for rest

**Recommendation:** (a) — papers rarely link to more than 2-3 concepts, and
the page is not latency-critical.

### D7 — Motivation aggregation strategy

When a paper touches two concepts that both trigger SECURITY, how to merge?

**Options:**
- (a) Union all evidence under one SECURITY section
- (b) Show per-concept motivation sections
- (c) Dedup by category, pool evidence with concept labels

**Recommendation:** (c) — one section per category, evidence from all
concepts pooled and labelled by source concept.

### D8 — Keep messaging endpoints?

The text-blob endpoints are superseded by the full page.

**Options:**
- (a) Remove entirely
- (b) Keep for future messaging automation

**Recommendation:** (a) — the concept card (`_build_single_card_text`)
already carries the paper URL for messaging.

---

## File Inventory

### New Files

| File | Purpose |
|---|---|
| `src/web/templates/paper_detail.html` | Full paper detail template (~180 lines) |

### Modified Files

| File | Changes |
|---|---|
| `src/web/routes.py` | Add `paper_detail()` route (~80 lines). Remove `_build_research_card_text()`, `_query_research_brief()`, `feed_research_card_json()`, `feed_send_research_card()`, `has_research_brief` radar query (~115 lines removed). Net ~-35 lines. |
| `src/web/templates/feed.html` | Paper title links to `/paper/{source_id}`. Remove Research/Send Research buttons and JS. |
| `src/web/templates/radar.html` | Paper title links to `/paper/{source_id}`. Remove 🔬 indicator, preview row, and JS. |

---

## Verification

- Start dev server, navigate to `/feed`
- Paper titles link to `/paper/{source_id}` — click one
- Paper detail page shows: header, research brief (if extracted), connected
  concepts with links, motivations with blast radius, paper evidence
- Click concept link → navigates to `/research/{concept_id}`
- Navigate to `/radar`, expand subsystem → concept → papers
- Paper titles link to `/paper/{source_id}`
- External paper URL accessible via "source →" secondary link
- `spec:check` passes with 0 new errors
