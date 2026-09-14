# Plan: Resolvable Source Links and Code Examples

**Created:** 2026-06-24
**Status:** Draft — ready for implementation in future sessions
**Scope:** Schema changes, data population, web UI templates, spec DAG mutations

---

## Problem Statement

Source nodes carry relative documentation paths (e.g., `Documentation/networking/skbuff.rst`) that are not clickable or resolvable. Evidence nodes are empty provenance anchors with no text content. Concept nodes describe mechanisms in prose but lack concrete code examples showing real kernel API usage. The demo looks theoretical without grounding in actual code.

## Goals

1. Every Source node's `url` attribute is a resolvable HTTPS link to the kernel.org git tree
2. Evidence nodes carry an `excerpt` text field with the actual documentation passage they represent
3. Concept nodes carry a `code_examples` list with real kernel C code snippets and source attribution
4. The web UI renders all three: clickable source links, evidence text blocks, and syntax-highlighted code examples

---

## Phase 1: Schema Changes (`/cb-green`)

### Task 1.1 — Update `REQUIRED_ATTRS` in `src/graph/schema.py`

No new required attributes are needed — all new fields are **optional** to avoid breaking existing nodes. The schema already accepts any JSON attrs; `REQUIRED_ATTRS` only enforces minimums.

Verify: `REQUIRED_ATTRS["Evidence"]` stays `("artifact_class", "contamination_level")`. The new `excerpt` field is optional.
Verify: `REQUIRED_ATTRS["Concept"]` stays `("name", "description", "artifact_class", "key_properties", "tradeoffs", "design_rationale")`. The new `code_examples` field is optional.

**No code change needed for schema.py. Optional attrs are already supported by the JSON attrs column.**

### Task 1.2 — Spec DAG mutations

Add these spec nodes via `/cb-green` spec-author envelope:

#### New invariant: `INV-KK-WEB-CODE-DISPLAY`
```
kind: invariant
id: INV-KK-WEB-CODE-DISPLAY
description: When a Concept node has a non-empty code_examples attribute, the concept detail page renders each example as a labeled code block with syntax highlighting (language tag) and an optional source_url hyperlink.
predicate: forall concept C with C.attrs.code_examples ≠ []. forall example E in C.code_examples. detail_page(C) contains <pre><code class="language-{E.language}"> rendering of E.code ∧ (E.source_url → clickable <a> link)
predicateNL: The concept detail page displays each code example with its label, syntax-highlighted code block, and clickable source URL when available.
checked-at → stage-delivery
contained-by ← SUB-KK-WEB
```

#### New invariant: `INV-KK-WEB-SOURCE-LINKED`
```
kind: invariant
id: INV-KK-WEB-SOURCE-LINKED
description: Source node detail pages render the url attribute as a clickable hyperlink opening in a new tab, enabling direct navigation to the upstream kernel documentation.
predicate: forall source S. detail_page(S) contains <a href="{S.attrs.url}" target="_blank"> element
predicateNL: Source detail pages display the URL as a clickable external link.
checked-at → stage-delivery
contained-by ← SUB-KK-WEB
```

#### New invariant: `INV-KK-WEB-EVIDENCE-EXCERPT`
```
kind: invariant
id: INV-KK-WEB-EVIDENCE-EXCERPT
description: When an Evidence node has a non-empty excerpt attribute, the evidence detail page renders it as a blockquote. The excerpt represents the documentation passage from which concepts were extracted.
predicate: forall evidence E with E.attrs.excerpt ≠ null. detail_page(E) contains <blockquote> rendering of E.attrs.excerpt
predicateNL: Evidence detail pages display the excerpt text as a blockquote when available.
checked-at → stage-delivery
contained-by ← SUB-KK-WEB
```

#### New algorithm: `ALG-KK-WEB-CODE-RENDER`
```
kind: algorithm
id: ALG-KK-WEB-CODE-RENDER
description: Renders code examples on concept detail pages. Iterates over attrs.code_examples list. Each entry has {label: str, language: str, code: str, source_url?: str}. Renders a heading with label, a <pre><code> block with language class for CSS/JS highlighting, and an optional source link.
runs-at → stage-delivery
satisfies → INV-KK-WEB-CODE-DISPLAY
contained-by ← SUB-KK-WEB
```

#### Modify algorithm: `ALG-KK-WEB-KIND-DETAIL`
```
modify-node: ALG-KK-WEB-KIND-DETAIL
props.description: (append) "... Renders code_examples, evidence excerpts, and clickable source URLs when present in node attrs."
add-edge: satisfies → INV-KK-WEB-CODE-DISPLAY
add-edge: satisfies → INV-KK-WEB-SOURCE-LINKED
add-edge: satisfies → INV-KK-WEB-EVIDENCE-EXCERPT
```

### Task 1.3 — Exact spec-author envelope

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
          "id": "INV-KK-WEB-CODE-DISPLAY",
          "kind": "invariant",
          "language": "meta",
          "description": "When a Concept node has a non-empty code_examples attribute, the concept detail page renders each example as a labeled code block with syntax highlighting and an optional source_url hyperlink.",
          "predicate": "forall concept C with C.attrs.code_examples != []. forall example E in C.code_examples. detail_page(C) contains pre>code rendering of E.code AND (E.source_url implies clickable link)",
          "predicateNL": "The concept detail page displays each code example with its label, syntax-highlighted code block, and clickable source URL when available.",
          "enforced": "{}"
        }
      },
      {"type": "add-edge", "edge": {"kind": "contains", "from": "SUB-KK-WEB", "to": "INV-KK-WEB-CODE-DISPLAY"}},
      {"type": "add-edge", "edge": {"kind": "checked-at", "from": "INV-KK-WEB-CODE-DISPLAY", "to": "stage-delivery"}},
      {
        "type": "add-node",
        "node": {
          "id": "INV-KK-WEB-SOURCE-LINKED",
          "kind": "invariant",
          "language": "meta",
          "description": "Source node detail pages render the url attribute as a clickable hyperlink opening in a new tab, enabling direct navigation to upstream kernel documentation.",
          "predicate": "forall source S. detail_page(S) contains anchor element with href=S.attrs.url and target=_blank",
          "predicateNL": "Source detail pages display the URL as a clickable external link.",
          "enforced": "{}"
        }
      },
      {"type": "add-edge", "edge": {"kind": "contains", "from": "SUB-KK-WEB", "to": "INV-KK-WEB-SOURCE-LINKED"}},
      {"type": "add-edge", "edge": {"kind": "checked-at", "from": "INV-KK-WEB-SOURCE-LINKED", "to": "stage-delivery"}},
      {
        "type": "add-node",
        "node": {
          "id": "INV-KK-WEB-EVIDENCE-EXCERPT",
          "kind": "invariant",
          "language": "meta",
          "description": "When an Evidence node has a non-empty excerpt attribute, the evidence detail page renders it as a blockquote.",
          "predicate": "forall evidence E with E.attrs.excerpt != null. detail_page(E) contains blockquote rendering of E.attrs.excerpt",
          "predicateNL": "Evidence detail pages display the excerpt text as a blockquote when available.",
          "enforced": "{}"
        }
      },
      {"type": "add-edge", "edge": {"kind": "contains", "from": "SUB-KK-WEB", "to": "INV-KK-WEB-EVIDENCE-EXCERPT"}},
      {"type": "add-edge", "edge": {"kind": "checked-at", "from": "INV-KK-WEB-EVIDENCE-EXCERPT", "to": "stage-delivery"}},
      {
        "type": "add-node",
        "node": {
          "id": "ALG-KK-WEB-CODE-RENDER",
          "kind": "algorithm",
          "language": "meta",
          "description": "Renders code examples on concept detail pages. Iterates attrs.code_examples list. Each entry: {label, language, code, source_url?}. Outputs heading + pre/code block + optional source link."
        }
      },
      {"type": "add-edge", "edge": {"kind": "contains", "from": "SUB-KK-WEB", "to": "ALG-KK-WEB-CODE-RENDER"}},
      {"type": "add-edge", "edge": {"kind": "runs-at", "from": "ALG-KK-WEB-CODE-RENDER", "to": "stage-delivery"}},
      {"type": "add-edge", "edge": {"kind": "satisfies", "from": "ALG-KK-WEB-CODE-RENDER", "to": "INV-KK-WEB-CODE-DISPLAY"}},
      {"type": "add-edge", "edge": {"kind": "satisfies", "from": "ALG-KK-WEB-KIND-DETAIL", "to": "INV-KK-WEB-CODE-DISPLAY"}},
      {"type": "add-edge", "edge": {"kind": "satisfies", "from": "ALG-KK-WEB-KIND-DETAIL", "to": "INV-KK-WEB-SOURCE-LINKED"}},
      {"type": "add-edge", "edge": {"kind": "satisfies", "from": "ALG-KK-WEB-KIND-DETAIL", "to": "INV-KK-WEB-EVIDENCE-EXCERPT"}}
    ]
  }
}
```

---

## Phase 2: Web UI Template Changes (`/cb-green`)

### Task 2.1 — Source detail: clickable URL

**File:** `src/web/templates/concept_detail.html`

In the `{% else %}` fallback block (lines 129–144) that renders Source/Evidence/Advisory nodes as a generic key-value table, the `url` value is displayed as plain text.

**Change:** Add a Source-specific block before the generic fallback:

```html
{% elif node.kind == 'Source' %}
<div class="attrs-section">
  {% if attrs.get('url') %}
  <h3>Documentation URL</h3>
  <p><a href="{{ attrs.url }}" target="_blank" rel="noopener">{{ attrs.url }}</a></p>
  {% endif %}
  {% if attrs.get('source_type') %}<p><strong>Source Type:</strong> {{ attrs.source_type }}</p>{% endif %}
  {% if attrs.get('license') %}<p><strong>License:</strong> {{ attrs.license }}</p>{% endif %}
</div>
```

Insert this block at line 129, before the `{% else %}` fallback.

### Task 2.2 — Evidence detail: excerpt display

**File:** `src/web/templates/concept_detail.html`

Add an Evidence-specific block:

```html
{% elif node.kind == 'Evidence' %}
<div class="attrs-section">
  {% if attrs.get('excerpt') %}
  <h3>Source Excerpt</h3>
  <blockquote style="white-space:pre-wrap;">{{ attrs.excerpt }}</blockquote>
  {% endif %}
  <p><strong>Artifact Class:</strong> {{ attrs.artifact_class }}</p>
  <p><strong>Contamination Level:</strong> {{ attrs.contamination_level }}</p>
</div>
```

### Task 2.3 — Concept detail: code examples

**File:** `src/web/templates/concept_detail.html`

Add inside the `{% if node.kind == 'Concept' %}` block, after the Design Rationale section (after line 23):

```html
  {% if attrs.get('code_examples') %}
  <h3>Code Examples</h3>
  {% for ex in attrs.code_examples %}
  <div class="card" style="margin-bottom:0.8rem;">
    <strong>{{ ex.label }}</strong>
    {% if ex.source_url %}<span style="float:right;font-size:0.85em;"><a href="{{ ex.source_url }}" target="_blank" rel="noopener">source →</a></span>{% endif %}
    <pre style="background:#f5f5f5;padding:0.5rem;overflow-x:auto;margin-top:0.3rem;"><code>{{ ex.code }}</code></pre>
  </div>
  {% endfor %}
  {% endif %}
```

### Task 2.4 — CSS for code blocks

**File:** `src/web/templates/base.html`

Add to the `<style>` block:

```css
pre code { font-family: monospace; font-size: 0.9em; }
pre { border: 1px solid #ddd; border-radius: 3px; }
```

---

## Phase 3: Data Population — Source URL Rewriting (`/cb-free`)

### Task 3.1 — URL mapping table

All 43 Source nodes with relative `Documentation/...` paths must be rewritten to resolvable kernel.org git tree URLs. The 4 original sources already have full HTTPS URLs and need no change.

**Base URL pattern:** `https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/{path}`

**Complete mapping (43 sources):**

| Source ID | Current `url` | New `url` |
|-----------|---------------|-----------|
| src-09529cef90e4 | Documentation/admin-guide/numa_policy.rst | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/admin-guide/mm/numa_memory_policy.rst |
| src-13d374ce19a7 | Documentation/mm/slab.rst | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/mm/slab.rst |
| src-14539382ad09 | Documentation/livepatch/ | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/livepatch |
| src-1ce98b32b995 | Documentation/filesystems/overlayfs.rst | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/filesystems/overlayfs.rst |
| src-1d2ac703db3f | Documentation/mm/oom.rst | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/admin-guide/mm/concepts.rst |
| src-229b391b1364 | Documentation/core-api/kernel-api.rst | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/core-api/kernel-api.rst |
| src-247295ca11f0 | Documentation/power/ | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/power |
| src-2868c14b49ad | Documentation/crypto/ | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/crypto |
| src-2ab22506911d | Documentation/driver-api/driver-model/ | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/driver-api/driver-model |
| src-36d30d7b5d0a | Documentation/process/ | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/process |
| src-3772631c1a21 | Documentation/admin-guide/efi-stub.rst | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/admin-guide/efi-stub.rst |
| src-3810cb4a3708 | Documentation/scheduler/sched-eevdf.rst | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/scheduler/sched-eevdf.rst |
| src-3bde0050c5a4 | Documentation/filesystems/xfs/ | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/filesystems/xfs |
| src-4a50e2612720 | Documentation/filesystems/btrfs.rst | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/filesystems/btrfs.rst |
| src-4aae8b0752fc | Documentation/admin-guide/device-mapper/ | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/admin-guide/device-mapper |
| src-53c20ffdae81 | Documentation/virt/virtio/ | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/virt/virtio |
| src-5ea2b3e2df76 | Documentation/driver-api/thermal/ | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/driver-api/thermal |
| src-66eed8a9f689 | Documentation/scheduler/sched-deadline.rst | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/scheduler/sched-deadline.rst |
| src-6f9d5d1c73dc | Documentation/usb/ | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/usb |
| src-72a9f4dc2721 | Documentation/filesystems/vfs.rst | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/filesystems/vfs.rst |
| src-7541098a44d9 | Documentation/nvme/ | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/nvme |
| src-79e1df6b4f02 | Documentation/block/ | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/block |
| src-851a5e88c6fd | Documentation/admin-guide/mm/ksm.rst | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/admin-guide/mm/ksm.rst |
| src-8a51fa0011e4 | Documentation/core-api/workqueue.rst | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/core-api/workqueue.rst |
| src-8c1204cbaa3b | Documentation/firmware-guide/acpi/ | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/firmware-guide/acpi |
| src-8fef8a32ba6c | Documentation/admin-guide/mm/transhuge.rst | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/admin-guide/mm/transhuge.rst |
| src-97b0f20052b2 | Documentation/trace/ | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/trace |
| src-9a8b2251ef08 | Documentation/virt/kvm/ | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/virt/kvm |
| src-a76555b18853 | Documentation/security/ | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/security |
| src-a9bc87d30bf8 | Documentation/networking/napi.rst | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/networking/napi.rst |
| src-af333f2c8fd0 | Documentation/networking/net_namespace.rst | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/networking/net_namespace.rst |
| src-b182a450a3fe | Documentation/filesystems/fuse.rst | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/filesystems/fuse.rst |
| src-b280276ff32e | Documentation/ipc/ | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/ipc |
| src-b8a81f4b4b91 | Documentation/scheduler/sched-rt-group.rst | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/scheduler/sched-rt-group.rst |
| src-bc320fbc6c96 | Documentation/admin-guide/cgroup-v2.rst | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/admin-guide/cgroup-v2.rst |
| src-c697ec445d38 | Documentation/admin-guide/perf/ | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/admin-guide/perf |
| src-cf306a484849 | Documentation/admin-guide/mm/zswap.rst | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/admin-guide/mm/zswap.rst |
| src-d167dddf5351 | Documentation/filesystems/ext4/ | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/filesystems/ext4 |
| src-de7c74ffb2f5 | Documentation/networking/skbuff.rst | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/networking/skbuff.rst |
| src-e2c49a090d9e | Documentation/admin-guide/md.rst | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/admin-guide/md.rst |
| src-e81019df75ec | Documentation/mm/page_alloc.rst | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/mm/page_alloc.rst |
| src-f43a581012f7 | Documentation/networking/tcp.rst | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/networking/tcp.rst |
| src-f7c80bc67494 | Documentation/namespaces/ | https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/namespaces |

**Implementation:** Write a Python script that calls `graph.engine.update_node_attrs(conn, src_id, {"url": new_url})` for each of the 43 source nodes. Run via `/cb-free`.

**Note:** Some kernel.org paths may differ from the relative paths stored (e.g., `Documentation/mm/oom.rst` may actually be at `Documentation/admin-guide/mm/concepts.rst`). The script should log each URL after rewriting so the operator can verify reachability. Ideally, validate URLs via HTTP HEAD requests before committing.

---

## Phase 4: Data Population — Evidence Excerpts (`/cb-free`)

### Task 4.1 — Populate evidence excerpts for the 4 original sources

These 4 Evidence nodes have corresponding text files in `data/sources/`:

| Evidence ID | Source File | Lines |
|-------------|-------------|-------|
| ev-b01c5353e809 | data/sources/rcu_whatisRCU.txt | 88 lines |
| ev-159c0f56c081 | data/sources/locking_spinlocks.txt | 100 lines |
| ev-693fd54d9af4 | data/sources/scheduler_cfs.txt | 94 lines |
| ev-1e83fb7dcf49 | data/sources/mm_page_tables.txt | 143 lines |

**Implementation:** Read each file, store its content in the evidence node's `excerpt` attribute:
```python
text = open("data/sources/rcu_whatisRCU.txt").read()
update_node_attrs(conn, "ev-b01c5353e809", {"excerpt": text})
```

### Task 4.2 — Populate evidence excerpts for the 43 new sources

The 43 new Evidence nodes have no backing text files. Two options:

**Option A (recommended for demo):** Write a brief 3-5 sentence synthetic excerpt for each evidence node summarizing what the corresponding kernel documentation covers. This is adequate for the demo and avoids copyright concerns.

**Option B (more thorough):** Fetch the actual kernel.org documentation pages and extract the first ~500 words as the excerpt. Requires `WebFetch` tool and careful content extraction from HTML.

**Implementation for Option A:** A Python script that generates excerpts like:
```python
excerpts = {
    "ev-{hash-for-kernel-mm-slab}": "The Linux kernel slab allocator documentation describes the SLUB allocator's design, including per-CPU freelists, cache merging, and debugging facilities. It covers kmem_cache_create(), kmem_cache_alloc(), and kmem_cache_free() APIs.",
    ...
}
```

Each excerpt should be 3-5 sentences covering: what the documentation describes, which APIs it documents, and what subsystem it belongs to.

---

## Phase 5: Data Population — Code Examples (`/cb-free`)

### Task 5.1 — Code example data format

Each code example is a JSON object stored in the Concept node's `code_examples` list attribute:

```json
{
  "label": "Human-readable title for the example",
  "language": "c",
  "code": "/* Actual kernel C code */\nrcu_read_lock();\np = rcu_dereference(gp);\nrcu_read_unlock();",
  "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/RCU/whatisRCU.rst"
}
```

### Task 5.2 — Tier 1 concepts (20 — highest demo impact)

These are the most important concepts that should get code examples first. Each needs 1-3 examples.

#### Synchronization (6 concepts)

**Read-Copy-Update** (concept-bb4cc0a78416):
```json
[
  {
    "label": "RCU read-side critical section",
    "language": "c",
    "code": "rcu_read_lock();\np = rcu_dereference(gp);\nif (p)\n    do_something(p->a, p->b);\nrcu_read_unlock();",
    "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/RCU/whatisRCU.rst"
  },
  {
    "label": "RCU update (publish new version)",
    "language": "c",
    "code": "struct foo *new_fp = kmalloc(sizeof(*new_fp), GFP_KERNEL);\n*new_fp = *gp;  /* copy old data */\nnew_fp->a = new_value;\nrcu_assign_pointer(gp, new_fp);\nsynchronize_rcu();\nkfree(old_fp);",
    "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/RCU/whatisRCU.rst"
  }
]
```

**Spinlock** (concept-fb56cad5ee43):
```json
[
  {
    "label": "Basic spinlock acquire/release",
    "language": "c",
    "code": "static DEFINE_SPINLOCK(my_lock);\n\nspin_lock(&my_lock);\n/* critical section */\nspin_unlock(&my_lock);",
    "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/locking/spinlocks.rst"
  }
]
```

**IRQ-Safe Spinlock** (concept-14545804a315):
```json
[
  {
    "label": "IRQ-safe spinlock (process context)",
    "language": "c",
    "code": "unsigned long flags;\n\nspin_lock_irqsave(&my_lock, flags);\n/* safe from IRQ preemption */\nspin_unlock_irqrestore(&my_lock, flags);",
    "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/locking/spinlocks.rst"
  }
]
```

**Reader-Writer Spinlock** (concept-0e81b7fed817):
```json
[
  {
    "label": "Reader-writer lock usage",
    "language": "c",
    "code": "static DEFINE_RWLOCK(my_rwlock);\n\n/* Reader path */\nread_lock(&my_rwlock);\n/* read shared data */\nread_unlock(&my_rwlock);\n\n/* Writer path */\nwrite_lock(&my_rwlock);\n/* modify shared data */\nwrite_unlock(&my_rwlock);",
    "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/locking/spinlocks.rst"
  }
]
```

**Grace Period** (concept-27fa910c8200):
```json
[
  {
    "label": "Synchronous grace period wait",
    "language": "c",
    "code": "/* Updater: wait for all pre-existing readers to finish */\nlist_del_rcu(&entry->list);\nsynchronize_rcu();  /* blocks until grace period ends */\nkfree(entry);",
    "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/RCU/whatisRCU.rst"
  },
  {
    "label": "Asynchronous grace period (callback)",
    "language": "c",
    "code": "static void my_rcu_callback(struct rcu_head *rp)\n{\n    struct my_struct *p = container_of(rp, struct my_struct, rcu);\n    kfree(p);\n}\n\nlist_del_rcu(&entry->list);\ncall_rcu(&entry->rcu, my_rcu_callback);  /* non-blocking */",
    "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/RCU/whatisRCU.rst"
  }
]
```

**Quiescent State Detection** (concept-7f79a75d9da4):
```json
[
  {
    "label": "Quiescent state in context switch",
    "language": "c",
    "code": "/* In schedule() — each context switch is a quiescent state for classic RCU */\nrcu_note_context_switch(cpu);\n/* CPU has passed through a quiescent state;\n * all prior RCU read-side critical sections have completed */",
    "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/RCU/whatisRCU.rst"
  }
]
```

#### Memory Management (5 concepts)

**SLUB Allocator** (concept-91bcd2b57765):
```json
[
  {
    "label": "Creating and using a slab cache",
    "language": "c",
    "code": "static struct kmem_cache *my_cache;\n\n/* Init */\nmy_cache = kmem_cache_create(\"my_objects\",\n    sizeof(struct my_obj), 0, SLAB_HWCACHE_ALIGN, NULL);\n\n/* Alloc */\nstruct my_obj *obj = kmem_cache_alloc(my_cache, GFP_KERNEL);\n\n/* Free */\nkmem_cache_free(my_cache, obj);\n\n/* Teardown */\nkmem_cache_destroy(my_cache);",
    "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/mm/slab.rst"
  }
]
```

**Kmalloc** (concept-e694b273d12c):
```json
[
  {
    "label": "General-purpose kernel allocation",
    "language": "c",
    "code": "/* Normal allocation (may sleep) */\nvoid *buf = kmalloc(4096, GFP_KERNEL);\n\n/* Atomic allocation (interrupt context) */\nvoid *irq_buf = kmalloc(256, GFP_ATOMIC);\n\n/* Zeroed allocation */\nstruct my_struct *s = kzalloc(sizeof(*s), GFP_KERNEL);\n\nkfree(buf);\nkfree(irq_buf);\nkfree(s);",
    "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/include/linux/slab.h"
  }
]
```

**Buddy Allocator** (concept-970f030dd376):
```json
[
  {
    "label": "Page allocation API",
    "language": "c",
    "code": "/* Allocate 2^order contiguous pages */\nstruct page *pages = alloc_pages(GFP_KERNEL, order);\nvoid *vaddr = page_address(pages);\n\n/* Single page shorthand */\nstruct page *pg = alloc_page(GFP_KERNEL);\nunsigned long addr = __get_free_page(GFP_KERNEL);\n\n/* Free */\n__free_pages(pages, order);\nfree_page(addr);",
    "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/mm/page_alloc.rst"
  }
]
```

**Vmalloc** (concept-50d58095b9e6):
```json
[
  {
    "label": "Virtually contiguous allocation",
    "language": "c",
    "code": "/* Allocate virtually contiguous memory (pages may be physically scattered) */\nvoid *buf = vmalloc(1024 * 1024);  /* 1MB */\n\n/* Zeroed variant */\nvoid *zbuf = vzalloc(64 * PAGE_SIZE);\n\nvfree(buf);\nvfree(zbuf);",
    "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/mm/vmalloc.c"
  }
]
```

**OOM Killer** (concept-1de54fb7e99f):
```json
[
  {
    "label": "Adjusting OOM score from userspace",
    "language": "c",
    "code": "/* From userspace: make process less likely to be OOM-killed */\necho -1000 > /proc/self/oom_score_adj   /* immune */\necho 0 > /proc/self/oom_score_adj       /* normal */\necho 1000 > /proc/self/oom_score_adj    /* kill first */\n\n/* Kernel: per-cgroup OOM control */\necho 1 > /sys/fs/cgroup/mygroup/memory.oom.group",
    "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/filesystems/proc.rst"
  }
]
```

#### Networking (3 concepts)

**Socket Buffer (sk_buff)** (concept-257bd0f39d03):
```json
[
  {
    "label": "Allocating and building an sk_buff",
    "language": "c",
    "code": "struct sk_buff *skb = alloc_skb(len + headroom, GFP_KERNEL);\nskb_reserve(skb, headroom);  /* reserve space for headers */\n\n/* Add data to tail */\nunsigned char *data = skb_put(skb, data_len);\nmemcpy(data, payload, data_len);\n\n/* Push a header at the front */\nstruct ethhdr *eth = skb_push(skb, sizeof(*eth));\n\nkfree_skb(skb);",
    "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/networking/skbuff.rst"
  }
]
```

**NAPI Polling** (concept-6a17f9ac3a98):
```json
[
  {
    "label": "NAPI poll handler in a network driver",
    "language": "c",
    "code": "static int my_driver_poll(struct napi_struct *napi, int budget)\n{\n    int work_done = 0;\n    while (work_done < budget) {\n        struct sk_buff *skb = my_receive_packet(priv);\n        if (!skb)\n            break;\n        napi_gro_receive(napi, skb);\n        work_done++;\n    }\n    if (work_done < budget) {\n        napi_complete_done(napi, work_done);\n        my_enable_irq(priv);  /* re-enable interrupts */\n    }\n    return work_done;\n}",
    "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/networking/napi.rst"
  }
]
```

**XDP** (concept-91e863a8282c):
```json
[
  {
    "label": "Simple XDP program (eBPF C)",
    "language": "c",
    "code": "SEC(\"xdp\")\nint xdp_drop_filter(struct xdp_md *ctx)\n{\n    void *data = (void *)(long)ctx->data;\n    void *data_end = (void *)(long)ctx->data_end;\n    struct ethhdr *eth = data;\n\n    if ((void *)(eth + 1) > data_end)\n        return XDP_DROP;\n\n    /* Drop all non-IP traffic */\n    if (eth->h_proto != htons(ETH_P_IP))\n        return XDP_DROP;\n\n    return XDP_PASS;\n}",
    "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/samples/bpf"
  }
]
```

#### Process Management / IPC (3 concepts)

**Futex** (concept-754c1125e055):
```json
[
  {
    "label": "Futex-based userspace mutex (simplified)",
    "language": "c",
    "code": "/* Userspace lock via futex */\nif (atomic_cmpxchg(&lock->val, 0, 1) != 0) {\n    /* Contended — sleep in kernel */\n    futex(&lock->val, FUTEX_WAIT, 1, NULL, NULL, 0);\n}\n\n/* Unlock */\natomic_set(&lock->val, 0);\nfutex(&lock->val, FUTEX_WAKE, 1, NULL, NULL, 0);",
    "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/locking/futex-requeue-pi.rst"
  }
]
```

**Epoll** (concept-19d51f949f56):
```json
[
  {
    "label": "Epoll event loop",
    "language": "c",
    "code": "int epfd = epoll_create1(0);\n\nstruct epoll_event ev = { .events = EPOLLIN | EPOLLET, .data.fd = sock_fd };\nepoll_ctl(epfd, EPOLL_CTL_ADD, sock_fd, &ev);\n\nstruct epoll_event events[MAX_EVENTS];\nwhile (1) {\n    int n = epoll_wait(epfd, events, MAX_EVENTS, -1);\n    for (int i = 0; i < n; i++) {\n        handle_event(events[i].data.fd);\n    }\n}",
    "source_url": "https://man7.org/linux/man-pages/man7/epoll.7.html"
  }
]
```

**Namespaces** (concept-3a1c7ed96cb7):
```json
[
  {
    "label": "Creating a PID namespace with clone",
    "language": "c",
    "code": "/* Clone with new PID and mount namespaces */\npid_t pid = clone(child_func, child_stack + STACK_SIZE,\n    CLONE_NEWPID | CLONE_NEWNS | SIGCHLD, NULL);\n\n/* Or from existing process */\nunshare(CLONE_NEWPID | CLONE_NEWNET);\n\n/* Enter an existing namespace */\nint fd = open(\"/proc/1234/ns/pid\", O_RDONLY);\nsetns(fd, CLONE_NEWPID);",
    "source_url": "https://man7.org/linux/man-pages/man7/namespaces.7.html"
  }
]
```

#### Virtualization (1 concept)

**KVM** (concept from make_id("concept", "KVM (Kernel-based Virtual Machine)")):
```json
[
  {
    "label": "KVM ioctl workflow (simplified)",
    "language": "c",
    "code": "int kvm_fd = open(\"/dev/kvm\", O_RDWR);\nint vm_fd = ioctl(kvm_fd, KVM_CREATE_VM, 0);\nint vcpu_fd = ioctl(vm_fd, KVM_CREATE_VCPU, 0);\n\n/* Map guest memory */\nstruct kvm_userspace_memory_region region = {\n    .slot = 0, .guest_phys_addr = 0,\n    .memory_size = mem_size,\n    .userspace_addr = (uint64_t)guest_mem,\n};\nioctl(vm_fd, KVM_SET_USER_MEMORY_REGION, &region);\n\n/* Run loop */\nwhile (1) {\n    ioctl(vcpu_fd, KVM_RUN, NULL);\n    switch (run->exit_reason) {\n    case KVM_EXIT_IO:\n        handle_io(run); break;\n    case KVM_EXIT_HLT:\n        return 0;\n    }\n}",
    "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/virt/kvm/api.rst"
  }
]
```

#### eBPF / Tracing (2 concepts)

**eBPF** (concept-c73ac8c3ff02):
```json
[
  {
    "label": "eBPF tracepoint program (libbpf C)",
    "language": "c",
    "code": "SEC(\"tp/syscalls/sys_enter_openat\")\nint trace_openat(struct trace_event_raw_sys_enter *ctx)\n{\n    pid_t pid = bpf_get_current_pid_tgid() >> 32;\n    char comm[16];\n    bpf_get_current_comm(comm, sizeof(comm));\n    bpf_printk(\"pid=%d comm=%s opening file\", pid, comm);\n    return 0;\n}",
    "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/samples/bpf"
  }
]
```

**Ftrace** (concept-4ef77ca7ed52):
```json
[
  {
    "label": "Enabling ftrace function tracing from shell",
    "language": "bash",
    "code": "# Enable function tracer\necho function > /sys/kernel/debug/tracing/current_tracer\n\n# Filter to specific function\necho 'schedule' > /sys/kernel/debug/tracing/set_ftrace_filter\n\n# Start/stop\necho 1 > /sys/kernel/debug/tracing/tracing_on\nsleep 5\necho 0 > /sys/kernel/debug/tracing/tracing_on\n\n# Read trace\ncat /sys/kernel/debug/tracing/trace",
    "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/trace/ftrace.rst"
  }
]
```

### Task 5.3 — Tier 2 concepts (remaining 63)

After Tier 1 is complete and verified, extend code examples to all remaining concepts. Each concept should get at least 1 example. Priority order:

1. **File Systems** (9 concepts) — VFS open/read, ext4 mount, btrfs snapshot, overlayfs mount
2. **Scheduler** (7 concepts) — sched_setattr, EEVDF slice request, SCHED_DEADLINE params
3. **Device Drivers** (6 concepts) — platform_driver_register, request_irq, dma_map_single
4. **Security** (3 concepts) — seccomp_rule_add, cap_set_flag, selinux_check
5. **Block I/O** (2 concepts) — io_uring_prep_read, blk_mq_make_request
6. **Storage Stack** (3 concepts) — dmsetup create, mdadm --create, nvme CLI
7. **Power Management** (3 concepts) — cpuidle_register_governor, cpufreq_register_driver
8. **Firmware Interface** (3 concepts) — acpi_evaluate_object, efi_get_variable
9. **NUMA** (2 concepts) — set_mempolicy, numactl
10. **Cryptography** (2 concepts) — crypto_alloc_skcipher, cryptsetup
11. **Remaining Virtualization** (4 concepts) — virtio_config_ops, vfio_register_group
12. **Remaining IPC** (2 concepts) — pipe, shmget/shmat

**Implementation:** A Python data script (similar to populate.py/populate2.py) that calls `update_node_attrs(conn, concept_id, {"code_examples": [...]})` for each concept.

---

## Phase 6: Verification

### Task 6.1 — URL reachability check

Write a script that HTTP-HEADs every Source URL and reports non-200 responses. Fix broken links.

### Task 6.2 — Visual inspection

Start the server with `start.bat` and verify:
- Source detail page shows clickable URL
- Evidence detail page shows excerpt text
- Concept detail page shows code examples with proper formatting
- All 14 node kinds render correctly in their detail views

### Task 6.3 — Commit and push

One commit per phase:
1. `feat(web): add code examples and source links to detail views (INV-KK-WEB-CODE-DISPLAY, INV-KK-WEB-SOURCE-LINKED, INV-KK-WEB-EVIDENCE-EXCERPT)`
2. `chore: rewrite source URLs to resolvable kernel.org links`
3. `chore: populate code examples for tier 1 concepts (20 concepts)`
4. `chore: populate code examples for tier 2 concepts (63 concepts)`

---

## Execution Commands

| Phase | Skill | Command |
|-------|-------|---------|
| 1 (Spec + Templates) | `/cb-green` | Spec mutations + template changes in one contract |
| 2 (Source URLs) | `/cb-free` | Python script to rewrite all 43 Source node URLs |
| 3 (Evidence excerpts) | `/cb-free` | Python script to populate excerpt attrs on 47 Evidence nodes |
| 4 (Tier 1 code examples) | `/cb-free` | Python script to add code_examples to 20 key Concept nodes |
| 5 (Tier 2 code examples) | `/cb-free` | Python script to add code_examples to remaining 63 Concept nodes |
| 6 (Verification) | `/cb-free` | URL check script + manual visual inspection |

---

## Dependencies

- Phase 1 must complete before Phases 2-5 (templates must exist to render new data)
- Phases 2, 3, 4 are independent of each other (can run in any order after Phase 1)
- Phase 5 depends on Phase 4 being verified (learn from Tier 1 before scaling)
- Phase 6 runs after all others

## Risk Notes

- **Stale code examples:** Code snippets may not match latest kernel versions. This is explicitly acceptable — the `source_url` link points to the authoritative current version.
- **URL breakage:** Kernel.org tree URLs are stable but doc files occasionally get renamed. The verification script in Phase 6 catches this.
- **Evidence excerpt length:** Some kernel docs are very long. Excerpts should be capped at ~2000 characters to keep detail pages manageable.
- **Schema backward compatibility:** All new attrs are optional. Existing nodes without code_examples/excerpt/updated URLs continue to render correctly.
