# Plan: Code Visibility Improvements

**Created:** 2026-06-24
**Status:** Draft — ready for implementation in future sessions
**Scope:** Web UI templates, route handlers, spec DAG mutations
**Prerequisite:** Source Links & Code Examples plan (fully implemented)

---

## Problem Statement

Code examples exist on all 83 Concept nodes, but they are only visible when a user navigates to a specific Concept detail page. There is no visual indicator on list views showing which nodes have code, no dedicated browsing page for code snippets, and no cross-referencing of code examples on related node types (KernelInvariant, FailureMode, InteractionProtocol). The demo feels disconnected — an invariant page describes a rule but doesn't show the kernel API code that enforces or relates to it.

## Goals

1. **List-level visibility:** Concept rows in `/concepts` list show a badge when `code_examples` is non-empty
2. **Dedicated browsing page:** A new `/code-examples` page aggregates all code snippets, grouped by subsystem, with links back to concept detail pages
3. **Cross-referenced code on related node types:** KernelInvariant, FailureMode, and InteractionProtocol detail pages show code examples from their connected Concept nodes

---

## Phase A: Code Badge on Concept List (`/cb-green`)

### Task A.1 — Spec DAG mutation

Add one new invariant:

#### `INV-KK-WEB-CODE-BADGE`
```
kind: invariant
id: INV-KK-WEB-CODE-BADGE
language: meta
description: When a node in the /concepts list has a non-empty code_examples attribute, a visual code indicator badge is displayed next to its name in the list row.
predicate: forall node N in concepts_list response. if N.attrs.code_examples is non-empty list then row(N) contains a visible code indicator element
predicateNL: Concept list rows display a code indicator badge when the node has code examples.
enforced: {}
checked-at → stage-delivery
contained-by ← SUB-KK-WEB
```

Wire edges:
- `add-edge contains from SUB-KK-WEB to INV-KK-WEB-CODE-BADGE`
- `add-edge checked-at from INV-KK-WEB-CODE-BADGE to stage-delivery`
- `add-edge satisfies from ALG-KK-WEB-KIND-DETAIL to INV-KK-WEB-CODE-BADGE` (the list rendering satisfies this)

#### Exact spec-author envelope
```json
{
  "templateId": "cb-green-spec-author-v1",
  "schemaVersion": "1.0.0",
  "stage": "spec-author",
  "payload": {
    "mutations": [
      {
        "type": "add-node",
        "node": {
          "id": "INV-KK-WEB-CODE-BADGE",
          "kind": "invariant",
          "language": "meta",
          "description": "When a node in the /concepts list has a non-empty code_examples attribute, a visual code indicator badge is displayed next to its name in the list row.",
          "predicate": "forall node N in concepts_list response. if N.attrs.code_examples is non-empty list then row(N) contains a visible code indicator element",
          "predicateNL": "Concept list rows display a code indicator badge when the node has code examples.",
          "enforced": "{}"
        }
      },
      {"type": "add-edge", "edge": {"kind": "contains", "from": "SUB-KK-WEB", "to": "INV-KK-WEB-CODE-BADGE"}},
      {"type": "add-edge", "edge": {"kind": "checked-at", "from": "INV-KK-WEB-CODE-BADGE", "to": "stage-delivery"}}
    ]
  }
}
```

### Task A.2 — Template change

**File:** `src/web/templates/concept_list.html`

**Current state (line 21-25):**
```html
{% for node in nodes %}
  <tr>
    <td><a href="/concepts/{{ node.id }}">{{ node.display_name }}</a></td>
    <td>{{ node.kind }}</td>
    <td><code>{{ node.id }}</code></td>
  </tr>
```

**Change:** Add a code badge after the display name link, inside the same `<td>`. The badge only renders when `node.attrs` is a dict and has a non-empty `code_examples` key.

**New code for line 23:**
```html
    <td>
      <a href="/concepts/{{ node.id }}">{{ node.display_name }}</a>
      {% if node.attrs and node.attrs.code_examples %}<span class="badge" style="background:#27ae60;margin-left:0.4rem;font-size:0.7em;">code</span>{% endif %}
    </td>
```

**No route change needed.** The `concepts_list` route already passes full `attrs` (parsed JSON dict) to the template via `_rows_to_dicts()`. The template can access `node.attrs.code_examples` directly. This also works for Evidence nodes with `excerpt` — we could add an `excerpt` badge too, but that's out of scope for this phase.

### Task A.3 — CSS (optional enhancement)

No CSS changes strictly needed — the existing `.badge` class works. The inline `style="background:#27ae60"` gives it a green color distinct from the existing badges. If desired, add a dedicated class in `base.html`:

```css
.badge-code { background: #27ae60; font-size: 0.7em; }
```

### Task A.4 — Tests

**File:** `tests/test_web.py`

Add two tests using the existing `rich_client` fixture. The `rich_client` fixture creates `c-1` (Concept with name "RCU") — this node does NOT have `code_examples` in the fixture. We need a new fixture or an inline test client.

**Test 1: `test_concept_list_shows_code_badge`**
```python
def test_concept_list_shows_code_badge(tmp_path):
    """INV-KK-WEB-CODE-BADGE: Concept with code_examples shows code badge in list."""
    db_path = tmp_path / "badge_test.db"
    conn = init_db(db_path)
    add_node(conn, "c-with-code", "Concept", {
        "name": "With Code", "description": "test", "artifact_class": "B",
        "key_properties": [], "tradeoffs": [], "design_rationale": "test",
        "code_examples": [{"label": "example", "language": "c", "code": "int x;"}],
    })
    add_node(conn, "c-no-code", "Concept", {
        "name": "No Code", "description": "test", "artifact_class": "B",
        "key_properties": [], "tradeoffs": [], "design_rationale": "test",
    })
    conn.commit()
    conn.close()
    app = create_app(str(db_path))
    with TestClient(app) as c:
        response = c.get("/concepts")
    assert response.status_code == 200
    text = response.text
    # The row for "With Code" should contain a code badge
    with_code_idx = text.index("With Code")
    no_code_idx = text.index("No Code")
    # Badge appears between "With Code" and the next </tr>
    with_code_row = text[with_code_idx:text.index("</tr>", with_code_idx)]
    assert "code" in with_code_row.lower()  # badge text
    # No badge in the "No Code" row
    no_code_row = text[no_code_idx:text.index("</tr>", no_code_idx)]
    assert "badge" not in no_code_row or "code" not in no_code_row.split("badge")[1].split("</td>")[0]
```

**Test 2: `test_concept_list_no_badge_without_code_examples`**
```python
def test_concept_list_no_badge_without_code_examples(rich_client):
    """INV-KK-WEB-CODE-BADGE: Concept without code_examples has no code badge."""
    response = rich_client.get("/concepts?kind=Concept")
    assert response.status_code == 200
    # rich_client's c-1 has no code_examples
    text = response.text
    assert ">code<" not in text.split("RCU")[1].split("</tr>")[0]
```

---

## Phase B: Dedicated Code Examples Page (`/cb-green`)

### Task B.1 — Spec DAG mutations

Add one algorithm and one invariant:

#### `ALG-KK-WEB-CODE-BROWSE`
```
kind: algorithm
id: ALG-KK-WEB-CODE-BROWSE
language: meta
description: Serves GET /code-examples. Queries all Concept nodes with non-empty code_examples attribute, groups them by subsystem (via belongs-to edges), and renders a browsable page with all code snippets.
runs-at → stage-delivery
contained-by ← SUB-KK-WEB
satisfies → INV-KK-WEB-CODE-BROWSE-COMPLETE
```

#### `INV-KK-WEB-CODE-BROWSE-COMPLETE`
```
kind: invariant
id: INV-KK-WEB-CODE-BROWSE-COMPLETE
language: meta
description: The /code-examples page displays all code examples from all Concept nodes that have them, grouped by subsystem. Each example shows the concept name (linked to detail page), example label, syntax-highlighted code block, and optional source URL.
predicate: forall concept C with C.attrs.code_examples != []. forall example E in C.code_examples. /code-examples response contains rendering of E.code with link to detail_page(C)
predicateNL: The code examples browsing page contains every code example from every concept, each linked back to its parent concept detail page.
enforced: {}
checked-at → stage-delivery
contained-by ← SUB-KK-WEB
```

#### Exact spec-author envelope
```json
{
  "templateId": "cb-green-spec-author-v1",
  "schemaVersion": "1.0.0",
  "stage": "spec-author",
  "payload": {
    "mutations": [
      {
        "type": "add-node",
        "node": {
          "id": "INV-KK-WEB-CODE-BROWSE-COMPLETE",
          "kind": "invariant",
          "language": "meta",
          "description": "The /code-examples page displays all code examples from all Concept nodes that have them, grouped by subsystem. Each example shows the concept name (linked to detail page), example label, syntax-highlighted code block, and optional source URL.",
          "predicate": "forall concept C with C.attrs.code_examples != []. forall example E in C.code_examples. /code-examples response contains rendering of E.code with link to detail_page(C)",
          "predicateNL": "The code examples browsing page contains every code example from every concept, each linked back to its parent concept detail page.",
          "enforced": "{}"
        }
      },
      {"type": "add-edge", "edge": {"kind": "contains", "from": "SUB-KK-WEB", "to": "INV-KK-WEB-CODE-BROWSE-COMPLETE"}},
      {"type": "add-edge", "edge": {"kind": "checked-at", "from": "INV-KK-WEB-CODE-BROWSE-COMPLETE", "to": "stage-delivery"}},
      {
        "type": "add-node",
        "node": {
          "id": "ALG-KK-WEB-CODE-BROWSE",
          "kind": "algorithm",
          "language": "meta",
          "description": "Serves GET /code-examples. Queries all Concept nodes with non-empty code_examples attribute, groups them by subsystem (via belongs-to edges), and renders a browsable page with all code snippets."
        }
      },
      {"type": "add-edge", "edge": {"kind": "contains", "from": "SUB-KK-WEB", "to": "ALG-KK-WEB-CODE-BROWSE"}},
      {"type": "add-edge", "edge": {"kind": "runs-at", "from": "ALG-KK-WEB-CODE-BROWSE", "to": "stage-delivery"}},
      {"type": "add-edge", "edge": {"kind": "satisfies", "from": "ALG-KK-WEB-CODE-BROWSE", "to": "INV-KK-WEB-CODE-BROWSE-COMPLETE"}}
    ]
  }
}
```

### Task B.2 — Route handler

**File:** `src/web/routes.py`

Add a new route inside `setup_routes()`, after the existing `/sources` route (around line 228):

```python
@app.get("/code-examples", response_class=HTMLResponse)
async def code_examples_page(request: Request):
    """Browsable page of all code examples grouped by subsystem (ALG-KK-WEB-CODE-BROWSE)."""
    conn = request.app.state.conn
    # Get all concepts with code_examples
    rows = conn.execute(
        "SELECT id, kind, attrs FROM nodes "
        "WHERE kind = 'Concept' AND json_extract(attrs, '$.code_examples') IS NOT NULL "
        "ORDER BY json_extract(attrs, '$.name')"
    ).fetchall()
    concepts = _rows_to_dicts(rows)

    # Build subsystem mapping via belongs-to edges
    concept_ids = [c["id"] for c in concepts]
    subsystem_map: dict[str, str] = {}  # concept_id -> subsystem_name
    if concept_ids:
        placeholders = ",".join("?" for _ in concept_ids)
        sub_rows = conn.execute(
            f"SELECT e.source_id, json_extract(s.attrs, '$.name') as sub_name "
            f"FROM edges e "
            f"JOIN nodes s ON e.target_id = s.id AND s.kind = 'Subsystem' "
            f"WHERE e.kind = 'belongs-to' AND e.source_id IN ({placeholders})",
            tuple(concept_ids),
        ).fetchall()
        for sr in sub_rows:
            subsystem_map[sr["source_id"]] = sr["sub_name"]

    # Group by subsystem
    grouped: dict[str, list[dict]] = {}
    for c in concepts:
        sub_name = subsystem_map.get(c["id"], "Uncategorized")
        c["display_name"] = display_name_for_node(c["kind"], c.get("attrs") or {}, c["id"])
        grouped.setdefault(sub_name, []).append(c)

    # Sort subsystem keys alphabetically
    sorted_groups = dict(sorted(grouped.items()))

    return templates.TemplateResponse(
        request,
        "code_examples.html",
        {"grouped_concepts": sorted_groups, "total_concepts": len(concepts)},
    )
```

### Task B.3 — Template

**New file:** `src/web/templates/code_examples.html`

```html
{% extends "base.html" %}
{% block content %}
<h1>Code Examples</h1>
<p>{{ total_concepts }} concepts with code examples across {{ grouped_concepts | length }} subsystems</p>

{% for subsystem, concepts in grouped_concepts.items() %}
<details class="edge-group" open>
  <summary>{{ subsystem }} <span class="count">{{ concepts | length }}</span></summary>
  {% for concept in concepts %}
  <div style="margin:0.8rem 0 1.2rem 0;">
    <h3 style="margin-bottom:0.3rem;">
      <a href="/concepts/{{ concept.id }}">{{ concept.display_name }}</a>
    </h3>
    {% for ex in concept.attrs.code_examples %}
    <div class="card" style="margin-bottom:0.6rem;">
      <strong>{{ ex.label }}</strong>
      {% if ex.source_url %}<span style="float:right;font-size:0.85em;"><a href="{{ ex.source_url }}" target="_blank" rel="noopener">source &rarr;</a></span>{% endif %}
      <pre style="margin-top:0.3rem;"><code class="language-{{ ex.language }}">{{ ex.code }}</code></pre>
    </div>
    {% endfor %}
  </div>
  {% endfor %}
</details>
{% endfor %}
{% endblock %}
```

### Task B.4 — Navigation link

**File:** `src/web/templates/base.html`

Add a nav link after the existing "Sources" link (line 41):

**Current line 41:**
```html
  <a href="/sources">Sources</a>
```

**New line after it:**
```html
  <a href="/code-examples">Code</a>
```

### Task B.5 — Tests

**File:** `tests/test_web.py`

**Test 1: `test_code_examples_page_returns_200`**
```python
def test_code_examples_page_returns_200(tmp_path):
    """ALG-KK-WEB-CODE-BROWSE: /code-examples returns 200 with grouped code."""
    db_path = tmp_path / "code_browse.db"
    conn = init_db(db_path)
    add_node(conn, "sub-sync", "Subsystem", {"name": "Synchronization"})
    add_node(conn, "c-rcu", "Concept", {
        "name": "RCU", "description": "Read-Copy-Update", "artifact_class": "B",
        "key_properties": [], "tradeoffs": [], "design_rationale": "test",
        "code_examples": [{"label": "RCU lock", "language": "c", "code": "rcu_read_lock();"}],
    })
    add_edge(conn, "belongs-to", "c-rcu", "sub-sync")
    conn.commit()
    conn.close()
    app = create_app(str(db_path))
    with TestClient(app) as c:
        response = c.get("/code-examples")
    assert response.status_code == 200
    text = response.text
    assert "Synchronization" in text
    assert "RCU" in text
    assert "rcu_read_lock" in text
    assert 'href="/concepts/c-rcu"' in text
```

**Test 2: `test_code_examples_page_empty_db`**
```python
def test_code_examples_page_empty_db(tmp_path):
    db_path = tmp_path / "code_empty.db"
    conn = init_db(db_path)
    conn.commit()
    conn.close()
    app = create_app(str(db_path))
    with TestClient(app) as c:
        response = c.get("/code-examples")
    assert response.status_code == 200
    assert "0 concepts" in response.text
```

**Test 3: `test_nav_has_code_link`**
```python
def test_nav_has_code_link(client):
    """Navigation bar contains link to /code-examples."""
    response = client.get("/")
    assert response.status_code == 200
    assert 'href="/code-examples"' in response.text
```

---

## Phase C: Related Code on KernelInvariant/FailureMode/InteractionProtocol Pages (`/cb-green`)

### Task C.1 — Spec DAG mutation

Add one invariant:

#### `INV-KK-WEB-RELATED-CODE`
```
kind: invariant
id: INV-KK-WEB-RELATED-CODE
language: meta
description: When a KernelInvariant, FailureMode, or InteractionProtocol detail page is rendered, and the node has edges to Concept nodes that have non-empty code_examples, a "Related Code" section displays those code examples with attribution to the source concept.
predicate: forall node N of kind in {KernelInvariant, FailureMode, InteractionProtocol}. forall edge E from N to concept C. if C.attrs.code_examples != [] then detail_page(N) contains rendering of C.code_examples with link to C
predicateNL: KernelInvariant, FailureMode, and InteractionProtocol detail pages display code examples from connected Concept nodes in a Related Code section.
enforced: {}
checked-at → stage-delivery
contained-by ← SUB-KK-WEB
```

Wire `ALG-KK-WEB-KIND-DETAIL satisfies INV-KK-WEB-RELATED-CODE`.

#### Exact spec-author envelope
```json
{
  "templateId": "cb-green-spec-author-v1",
  "schemaVersion": "1.0.0",
  "stage": "spec-author",
  "payload": {
    "mutations": [
      {
        "type": "add-node",
        "node": {
          "id": "INV-KK-WEB-RELATED-CODE",
          "kind": "invariant",
          "language": "meta",
          "description": "When a KernelInvariant, FailureMode, or InteractionProtocol detail page is rendered, and the node has edges to Concept nodes that have non-empty code_examples, a Related Code section displays those code examples with attribution to the source concept.",
          "predicate": "forall node N of kind in {KernelInvariant, FailureMode, InteractionProtocol}. forall edge E from N to concept C. if C.attrs.code_examples != [] then detail_page(N) contains rendering of C.code_examples with link to C",
          "predicateNL": "KernelInvariant, FailureMode, and InteractionProtocol detail pages display code examples from connected Concept nodes in a Related Code section.",
          "enforced": "{}"
        }
      },
      {"type": "add-edge", "edge": {"kind": "contains", "from": "SUB-KK-WEB", "to": "INV-KK-WEB-RELATED-CODE"}},
      {"type": "add-edge", "edge": {"kind": "checked-at", "from": "INV-KK-WEB-RELATED-CODE", "to": "stage-delivery"}},
      {"type": "add-edge", "edge": {"kind": "satisfies", "from": "ALG-KK-WEB-KIND-DETAIL", "to": "INV-KK-WEB-RELATED-CODE"}}
    ]
  }
}
```

### Task C.2 — Route handler change

**File:** `src/web/routes.py`

Modify the `concept_detail` function (line 133-182). After building `node_labels` (line 172) and before `return templates.TemplateResponse`, add logic to collect related code examples for KernelInvariant, FailureMode, and InteractionProtocol nodes.

**Data flow:**
1. The route already fetches all edges for the current node (line 145-150)
2. The route already fetches all neighbor nodes (line 161-172)
3. For KernelInvariant/FailureMode/InteractionProtocol nodes, find neighbor IDs where the neighbor is a Concept
4. For each such Concept neighbor, check if it has `code_examples` in its attrs
5. Build a `related_code` list: `[{concept_name, concept_id, examples: [...]}]`
6. Pass `related_code` to the template context

**Exact code to insert after line 172 (`node_labels[lr_dict["id"]] = ...`) and before line 173 (`return templates.TemplateResponse`):**

```python
        related_code = []
        if node["kind"] in ("KernelInvariant", "FailureMode", "InteractionProtocol"):
            for lr in label_rows:
                lr_dict_rc = _rows_to_dicts([lr])[0]
                if lr_dict_rc["kind"] == "Concept":
                    rc_attrs = lr_dict_rc.get("attrs") or {}
                    if rc_attrs.get("code_examples"):
                        related_code.append({
                            "concept_name": rc_attrs.get("name", lr_dict_rc["id"]),
                            "concept_id": lr_dict_rc["id"],
                            "examples": rc_attrs["code_examples"],
                        })
```

**Important implementation detail:** The variable `label_rows` is consumed by the `for lr in label_rows` loop above (line 167). Since `label_rows` is a SQLite cursor result, iterating it twice won't work. The loop at line 167 already converts rows via `_rows_to_dicts([lr])`. The solution: the label-building loop already processes each row. We need to either:
- **Option A:** Store the `_rows_to_dicts` results in a list during the first loop, then iterate that list for related_code extraction.
- **Option B:** Re-query the neighbor nodes for Concept kind only.

**Recommended approach (Option A):** Modify the label-building loop to accumulate processed dicts:

```python
        node_labels: dict[str, str] = {}
        neighbor_dicts: list[dict] = []  # NEW: accumulate for related_code
        if neighbor_ids:
            placeholders = ",".join("?" for _ in neighbor_ids)
            label_rows = conn.execute(
                f"SELECT id, kind, attrs FROM nodes WHERE id IN ({placeholders})",
                tuple(neighbor_ids),
            ).fetchall()
            for lr in label_rows:
                lr_dict = _rows_to_dicts([lr])[0]
                attrs = lr_dict.get("attrs") or {}
                kind = lr_dict["kind"]
                label = display_name_for_node(kind, attrs, lr_dict["id"])
                node_labels[lr_dict["id"]] = f"{label} ({kind})"
                neighbor_dicts.append(lr_dict)  # NEW

        related_code = []  # NEW BLOCK
        if node["kind"] in ("KernelInvariant", "FailureMode", "InteractionProtocol"):
            for nd in neighbor_dicts:
                if nd["kind"] == "Concept":
                    nd_attrs = nd.get("attrs") or {}
                    if nd_attrs.get("code_examples"):
                        related_code.append({
                            "concept_name": nd_attrs.get("name", nd["id"]),
                            "concept_id": nd["id"],
                            "examples": nd_attrs["code_examples"],
                        })
```

Then add `related_code` to the template context dict:

```python
        return templates.TemplateResponse(
            request,
            "concept_detail.html",
            {
                "node": node,
                "edges": edges,
                "grouped_edges": grouped_edges,
                "node_labels": node_labels,
                "related_code": related_code,  # NEW
            },
        )
```

### Task C.3 — Template change

**File:** `src/web/templates/concept_detail.html`

Add a "Related Code" section to the KernelInvariant, FailureMode, and InteractionProtocol blocks. The cleanest approach: add it AFTER the `</div>` closing the attrs-section for each of these three kinds, but still within their `{% elif %}` branch.

**For KernelInvariant (after line 48, the `</div>` closing the attrs-section):**

Insert between the closing `</div>` (line 48) and `{% elif node.kind == 'FailureMode' %}` (line 50):

```html
{% if related_code %}
<div class="attrs-section">
  <h3>Related Code</h3>
  {% for rc in related_code %}
  <p style="margin-bottom:0.2rem;"><a href="/concepts/{{ rc.concept_id }}">{{ rc.concept_name }}</a></p>
  {% for ex in rc.examples %}
  <div class="card" style="margin-bottom:0.6rem;">
    <strong>{{ ex.label }}</strong>
    {% if ex.source_url %}<span style="float:right;font-size:0.85em;"><a href="{{ ex.source_url }}" target="_blank" rel="noopener">source &rarr;</a></span>{% endif %}
    <pre style="margin-top:0.3rem;"><code class="language-{{ ex.language }}">{{ ex.code }}</code></pre>
  </div>
  {% endfor %}
  {% endfor %}
</div>
{% endif %}
```

**Repeat the same block** after the FailureMode `</div>` (line 66) and after the InteractionProtocol `</div>` (line 83).

**DRY alternative:** Since the block is identical for all three kinds, Jinja2 doesn't have partials without macros. The simplest approach is to place the Related Code section AFTER the entire `{% if node.kind == ... %}...{% endif %}` block but BEFORE the `<h2>Edges</h2>` heading. This way it renders for any node kind that has `related_code` populated (and the route only populates it for the three target kinds).

**Recommended insertion point:** After line 176 (`{% endif %}` closing the kind-dispatch) and before line 178 (`<h2>Edges</h2>`):

```html
{% if related_code %}
<div class="attrs-section">
  <h3>Related Code</h3>
  {% for rc in related_code %}
  <p style="margin-bottom:0.2rem;"><a href="/concepts/{{ rc.concept_id }}">{{ rc.concept_name }}</a></p>
  {% for ex in rc.examples %}
  <div class="card" style="margin-bottom:0.6rem;">
    <strong>{{ ex.label }}</strong>
    {% if ex.source_url %}<span style="float:right;font-size:0.85em;"><a href="{{ ex.source_url }}" target="_blank" rel="noopener">source &rarr;</a></span>{% endif %}
    <pre style="margin-top:0.3rem;"><code class="language-{{ ex.language }}">{{ ex.code }}</code></pre>
  </div>
  {% endfor %}
  {% endfor %}
</div>
{% endif %}
```

This is cleaner because:
- Single insertion point, not three
- `related_code` is only non-empty for the three target kinds (controlled by route logic)
- If we later want to add related code to other kinds, only the route needs to change

### Task C.4 — Edge relationships (data context)

The current database has these edge relationships connecting the target kinds to Concepts:

| From Kind | Edge Kind | To Kind | Count |
|-----------|-----------|---------|-------|
| KernelInvariant | governed-by | Concept | 65 |
| FailureMode | triggered-by | KernelInvariant | 67 |
| InteractionProtocol | constrains-composition | Concept | 29 |

**Important:** FailureMode connects to KernelInvariant (not directly to Concept). To show related code on FailureMode pages, the route handler needs to traverse **two hops**: FailureMode → KernelInvariant → Concept. However, the current `concept_detail` route already fetches direct neighbors only. The simplest approach for Phase C is:

- **KernelInvariant → Concept (direct):** Works with current neighbor data. Edge kind: `governed-by`.
- **InteractionProtocol → Concept (direct):** Works with current neighbor data. Edge kind: `constrains-composition`.
- **FailureMode → Concept (indirect via KernelInvariant):** Requires a second query. The route would need to:
  1. Find KernelInvariant neighbors of the FailureMode
  2. For each KernelInvariant, find its Concept neighbors
  3. Collect code_examples from those Concepts

**Implementation for FailureMode two-hop traversal:**

```python
if node["kind"] == "FailureMode" and not related_code:
    # FailureMode connects to KernelInvariant via triggered-by,
    # which connects to Concept via governed-by
    kinv_ids = [nd["id"] for nd in neighbor_dicts if nd["kind"] == "KernelInvariant"]
    if kinv_ids:
        kinv_ph = ",".join("?" for _ in kinv_ids)
        concept_rows = conn.execute(
            f"SELECT DISTINCT n.id, n.kind, n.attrs FROM nodes n "
            f"JOIN edges e ON e.target_id = n.id AND e.kind = 'governed-by' "
            f"WHERE e.source_id IN ({kinv_ph}) AND n.kind = 'Concept'",
            tuple(kinv_ids),
        ).fetchall()
        for cr in concept_rows:
            cr_dict = _rows_to_dicts([cr])[0]
            cr_attrs = cr_dict.get("attrs") or {}
            if cr_attrs.get("code_examples"):
                related_code.append({
                    "concept_name": cr_attrs.get("name", cr_dict["id"]),
                    "concept_id": cr_dict["id"],
                    "examples": cr_attrs["code_examples"],
                })
```

### Task C.5 — Tests

**File:** `tests/test_web.py`

**Test 1: `test_invariant_detail_shows_related_code`**
```python
def test_invariant_detail_shows_related_code(tmp_path):
    """INV-KK-WEB-RELATED-CODE: KernelInvariant shows code from connected Concept."""
    db_path = tmp_path / "rel_code.db"
    conn = init_db(db_path)
    add_node(conn, "c-1", "Concept", {
        "name": "Spinlock", "description": "test", "artifact_class": "B",
        "key_properties": [], "tradeoffs": [], "design_rationale": "test",
        "code_examples": [{"label": "spin_lock", "language": "c", "code": "spin_lock(&lock);"}],
    })
    add_node(conn, "kinv-1", "KernelInvariant", {
        "predicate": "No sleeping under spinlock", "strength": "safety",
        "scope": "global", "artifact_class": "B",
    })
    add_edge(conn, "governed-by", "kinv-1", "c-1")
    conn.commit()
    conn.close()
    app = create_app(str(db_path))
    with TestClient(app) as c:
        response = c.get("/concepts/kinv-1")
    assert response.status_code == 200
    text = response.text
    assert "Related Code" in text
    assert "spin_lock" in text
    assert "Spinlock" in text
    assert 'href="/concepts/c-1"' in text
```

**Test 2: `test_invariant_no_related_code_when_concept_has_none`**
```python
def test_invariant_no_related_code_when_concept_has_none(tmp_path):
    """INV-KK-WEB-RELATED-CODE: No Related Code section when connected concept has no examples."""
    db_path = tmp_path / "rel_no_code.db"
    conn = init_db(db_path)
    add_node(conn, "c-1", "Concept", {
        "name": "Test", "description": "test", "artifact_class": "B",
        "key_properties": [], "tradeoffs": [], "design_rationale": "test",
    })
    add_node(conn, "kinv-1", "KernelInvariant", {
        "predicate": "test", "strength": "safety",
        "scope": "global", "artifact_class": "B",
    })
    add_edge(conn, "governed-by", "kinv-1", "c-1")
    conn.commit()
    conn.close()
    app = create_app(str(db_path))
    with TestClient(app) as c:
        response = c.get("/concepts/kinv-1")
    assert response.status_code == 200
    assert "Related Code" not in response.text
```

**Test 3: `test_failure_mode_shows_related_code_via_invariant`**
```python
def test_failure_mode_shows_related_code_via_invariant(tmp_path):
    """INV-KK-WEB-RELATED-CODE: FailureMode shows code from Concept via KernelInvariant hop."""
    db_path = tmp_path / "fm_rel_code.db"
    conn = init_db(db_path)
    add_node(conn, "c-1", "Concept", {
        "name": "RCU", "description": "test", "artifact_class": "B",
        "key_properties": [], "tradeoffs": [], "design_rationale": "test",
        "code_examples": [{"label": "rcu_lock", "language": "c", "code": "rcu_read_lock();"}],
    })
    add_node(conn, "kinv-1", "KernelInvariant", {
        "predicate": "test", "strength": "safety",
        "scope": "global", "artifact_class": "B",
    })
    add_node(conn, "fm-1", "FailureMode", {
        "symptom": "Stale read", "blast_radius": "local",
        "recoverability": "self-healing", "artifact_class": "B",
    })
    add_edge(conn, "governed-by", "kinv-1", "c-1")
    add_edge(conn, "triggered-by", "fm-1", "kinv-1")
    conn.commit()
    conn.close()
    app = create_app(str(db_path))
    with TestClient(app) as c:
        response = c.get("/concepts/fm-1")
    assert response.status_code == 200
    text = response.text
    assert "Related Code" in text
    assert "rcu_read_lock" in text
```

**Test 4: `test_protocol_shows_related_code`**
```python
def test_protocol_shows_related_code(tmp_path):
    """INV-KK-WEB-RELATED-CODE: InteractionProtocol shows code from connected Concept."""
    db_path = tmp_path / "ip_rel_code.db"
    conn = init_db(db_path)
    add_node(conn, "c-1", "Concept", {
        "name": "Spinlock", "description": "test", "artifact_class": "B",
        "key_properties": [], "tradeoffs": [], "design_rationale": "test",
        "code_examples": [{"label": "lock", "language": "c", "code": "spin_lock(&l);"}],
    })
    add_node(conn, "ip-1", "InteractionProtocol", {
        "rule": "No sleep under spinlock", "ordering": "never-during",
        "violation_mode": "deadlock", "artifact_class": "B",
    })
    add_edge(conn, "constrains-composition", "ip-1", "c-1")
    conn.commit()
    conn.close()
    app = create_app(str(db_path))
    with TestClient(app) as c:
        response = c.get("/concepts/ip-1")
    assert response.status_code == 200
    text = response.text
    assert "Related Code" in text
    assert "spin_lock" in text
```

---

## Execution Commands

| Phase | Skill | Description |
|-------|-------|-------------|
| A | `/cb-green` | Spec: `INV-KK-WEB-CODE-BADGE`. Code: `concept_list.html` badge. Tests: 2 |
| B | `/cb-green` | Spec: `ALG-KK-WEB-CODE-BROWSE` + `INV-KK-WEB-CODE-BROWSE-COMPLETE`. Code: new route + template + nav link. Tests: 3 |
| C | `/cb-green` | Spec: `INV-KK-WEB-RELATED-CODE`. Code: route handler + template section. Tests: 4 |

## Dependencies

- Phases A, B, C are independent of each other and can run in any order
- All three depend on the completed Source Links & Code Examples plan (already implemented)
- Phase C modifies `concept_detail` route handler — if Phase A also touches the same route (it doesn't — A only touches the template), there would be no conflict

## Database Details

- **Database file:** `data/master.db` (NOT `data/know_kernel.db` which is empty)
- **start.bat** defaults to `data/master.db`
- **Edge relationships for Phase C:**
  - KernelInvariant → Concept: edge kind `governed-by` (65 edges)
  - InteractionProtocol → Concept: edge kind `constrains-composition` (29 edges)
  - FailureMode → KernelInvariant: edge kind `triggered-by` (67 edges) — requires two-hop to reach Concept
- **Subsystem mapping for Phase B:** Concepts connect to Subsystems via `belongs-to` edges (83 concepts across 18 subsystems)

## Risk Notes

- **Phase C two-hop query for FailureMode:** Adds a second database query for FailureMode pages only. With 67 failure modes and small result sets, this is negligible performance impact.
- **Template repetition in Phase C:** The "Related Code" template block is placed once after the kind-dispatch `{% endif %}` rather than repeated in each kind block. This works because `related_code` is only populated for the three target kinds by the route handler.
- **Phase B subsystem grouping:** Concepts without a `belongs-to` edge to a Subsystem will appear under "Uncategorized". Currently all 83 concepts have subsystem assignments so this is a safety fallback.
