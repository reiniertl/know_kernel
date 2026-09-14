# Plan: Retire Ideas Section & Collect Research PDFs

**Source:** cb-audit run `cb-audit-ideas-retire` (2026-07-08)
**Status:** Ready for implementation
**Skill:** Use `/cb-green` for each task below (or `/cb-ops` for git-only steps)

---

## Part 1: Retire the Ideas Section

The Ideas section (`/ideas`, `/ideas/{id}`, `/api/ideas`) is fully superseded
by the Research section (`/research`, `/research/{id}`). Ideas shows 28
Opportunity nodes ranked by a single `frontier_score`. Research shows 83
Concept nodes with five scoring dimensions (research, feasibility, impact,
frontier, latest_activity), evidence chains, source provenance, and filtering.

### Task 1.1: Remove Ideas route handlers from routes.py

**File:** `src/web/routes.py`

Delete the following three route handlers (keep surrounding code intact):

| Route | Function | Lines | Invariants referenced |
|---|---|---|---|
| `GET /ideas` | `ideas_list()` | 519–628 | `ALG-KK-WEB-IDEAS-LIST`, `INV-KK-WEB-IDEAS-RANKED`, `INV-KK-WEB-IDEAS-FILTER` |
| `GET /ideas/{idea_id}` | `idea_detail()` | 967–1071 | `ALG-KK-WEB-IDEAS-DETAIL`, `INV-KK-WEB-IDEAS-EVIDENCE-CHAIN`, `INV-KK-WEB-IDEA-BRIEF-VERBATIM`, `INV-KK-WEB-IDEA-BRIEF-DEPTH` |
| `GET /api/ideas` | `api_ideas_json()` | 1347–1428 | `ALG-KK-WEB-API-IDEAS-JSON`, `INV-KK-WEB-API-IDEAS-JSON` |

**Note:** Line numbers are approximate and will shift as routes.py is edited.
Delete from the `@app.get(...)` decorator through the `return` statement of
each handler. Do NOT delete any imports that are still used by other handlers
(e.g. `compute_all_scores`, `build_concept_brief`, `classify_motivations`,
`build_argument_paragraph`—verify usage before removing imports).

### Task 1.2: Remove Ideas templates

**Delete these files entirely:**

| File | Content |
|---|---|
| `src/web/templates/ideas.html` | List page: 50 lines, extends base.html, renders idea cards with frontier_score, pagination |
| `src/web/templates/idea_detail.html` | Detail page: 240 lines, extends base.html, renders motivations, scores table, evidence timeline, interaction protocols, code examples, dependencies, related ideas |

### Task 1.3: Remove Ideas nav link from base.html

**File:** `src/web/templates/base.html`
**Line 48:** Delete `<a href="/ideas">Ideas</a>`

The nav bar currently has these links (lines 44–53):
```
Dashboard | All Nodes | Subsystems | Sources | Ideas | Research | Radar | Vulns | Code | Graph | Health
```
After removal it should be:
```
Dashboard | All Nodes | Subsystems | Sources | Research | Radar | Vulns | Code | Graph | Health
```

### Task 1.4: Remove Ideas link from dashboard.html

**File:** `src/web/templates/dashboard.html`
**Line 15:** Currently reads:
```html
<p><a href="/ideas">View idea feed →</a> &nbsp;|&nbsp; <a href="/radar">Subsystem radar →</a> &nbsp;|&nbsp; <a href="/vulns">Vulnerabilities →</a> &nbsp;|&nbsp; <a href="/health">View graph health diagnostics →</a></p>
```
Remove the `<a href="/ideas">View idea feed →</a> &nbsp;|&nbsp;` portion.

### Task 1.5: Update radar.html to remove top_idea column

**File:** `src/web/templates/radar.html`

The radar table has a "Top Idea" column:
- **Line 16:** `<th>Top Idea</th>` — delete this header
- **Lines 28–33:** Delete the `<td>` block that renders `sub.top_idea`:
  ```html
  <td>
    {% if sub.top_idea %}
      <a href="/ideas/{{ sub.top_idea.id }}">{{ sub.top_idea.title }}</a>
      ({{ "%.1f"|format(sub.top_idea.frontier_score) }})
    {% else %}
      —
    {% endif %}
  </td>
  ```
- **Line 37:** Update `colspan="7"` to `colspan="6"` in the empty-state row

### Task 1.6: Remove top_idea computation from radar route handler

**File:** `src/web/routes.py`
**In function `radar()` starting at line 1073:**

Delete the `top_idea` computation block (lines 1115–1132):
```python
top_idea = None
for cid in concept_ids:
    opp_rows = conn.execute(
        "SELECT n.id, n.attrs FROM nodes n "
        "JOIN edges e ON e.source_id = n.id "
        "WHERE e.kind = 'opportunity-for' AND e.target_id = ? AND n.kind = 'Opportunity'",
        (cid,),
    ).fetchall()
    for orow in opp_rows:
        oattrs = json.loads(orow[1]) if isinstance(orow[1], str) else (orow[1] or {})
        fs = oattrs.get("frontier_score", 0)
        if isinstance(fs, str):
            try:
                fs = float(fs)
            except ValueError:
                fs = 0
        if top_idea is None or fs > top_idea["frontier_score"]:
            top_idea = {"id": orow[0], "title": oattrs.get("title", orow[0]), "frontier_score": fs}
```

Also remove `"top_idea": top_idea,` from the `subsystems.append(...)` dict
(line 1141).

### Task 1.7: Remove Ideas-related tests

**File:** `tests/test_web.py`

Delete the following test functions and fixtures:

**Fixture (lines 765–850):**
- `ideas_client` — creates a test DB with Opportunity/Trend/Evidence/Source nodes

**Tests using `ideas_client` fixture (28 tests):**
| Line | Test function |
|---|---|
| 852 | `test_ideas_list_returns_200` |
| 858 | `test_ideas_list_shows_opportunities` |
| 864 | `test_ideas_list_shows_trends` |
| 870 | `test_ideas_list_ranked_by_frontier` |
| 882 | `test_ideas_list_min_score_filter` |
| 889 | `test_ideas_list_window_days_param` |
| 894 | `test_ideas_detail_opportunity_200` |
| 901 | `test_ideas_detail_shows_evidence` |
| 909 | `test_ideas_detail_evidence_ordered_by_date` |
| 920 | `test_ideas_detail_trend_200` |
| 926 | `test_ideas_detail_404_for_missing` |
| 931 | `test_ideas_detail_404_for_non_idea` |
| 936 | `test_ideas_detail_shows_related` |
| 944 | `test_ideas_detail_shows_scores` |
| 953 | `test_ideas_detail_shows_evidence_verbatim` |
| 961 | `test_ideas_detail_shows_vuln_section` |
| 969 | `test_ideas_detail_shows_invariants` |
| 976 | `test_ideas_detail_shows_prerequisites` |
| 983 | `test_dashboard_links_to_ideas` |
| 989 | `test_nav_has_ideas_link` |
| 1738 | `test_idea_detail_shows_motivations` |
| 1745 | `test_idea_detail_shows_security_motivation` |
| 1753 | `test_idea_detail_shows_argument` |
| 1825 | `test_idea_detail_no_empty_motivations` |
| 1853 | `test_idea_detail_shows_actionable_text` |
| 1860 | `test_idea_detail_shows_blast_radius` |
| 1868 | `test_idea_detail_shows_source_links` |
| 1875 | `test_idea_detail_no_truncation` |
| 1882 | `test_idea_detail_evidence_timeline_has_links` |
| 1889 | `test_idea_detail_shows_external_source_link` |

**Tests using `radar_vuln_client` fixture (idea-specific only):**
| Line | Test function |
|---|---|
| 1562 | `test_radar_shows_top_idea` — DELETE (column removed) |
| 1663 | `test_api_ideas_json_returns_array` — DELETE |
| 1677 | `test_api_ideas_json_has_opportunity` — DELETE |
| 1685 | `test_api_ideas_json_min_score_filter` — DELETE |

**Update (do not delete):**
- `test_dashboard_links_to_radar` (line 1713) — verify it doesn't also assert `/ideas` link
- `test_nav_has_radar_link` (line 1723) — verify it doesn't also assert `/ideas` link

### Task 1.8: Remove get_idea_feed from MCP server

**File:** `src/mcp_server/server.py`

- **Line 9:** Remove invariant comment `INV-KK-MCP-IDEA-FEED-RANKED`
- **Lines 266–344:** Delete the `get_idea_feed()` function entirely
- Check if `get_idea_feed` is registered as an MCP tool; if so, remove the registration

**File:** `tests/test_mcp_server.py`

Delete the following tests and their fixture:
| Line | Item |
|---|---|
| 452 | `idea_snapshot_path` fixture |
| 532 | `test_get_idea_feed_returns_list` |
| 538 | `test_get_idea_feed_ranked_by_frontier` |
| 545 | `test_get_idea_feed_top_k` |
| 550 | `test_get_idea_feed_subsystem_filter` |
| 556 | `test_get_idea_feed_empty_on_nonexistent_subsystem` |

### Task 1.9: Keep Opportunity nodes in database

Do NOT delete Opportunity or Trend nodes from `data/master.db`. They are data,
not UI artifacts. They may be useful for future analysis or re-exposure through
the Research section.

### Task 1.10: Retire spec DAG invariants (if they exist)

The following invariant IDs are referenced in docstrings and should be checked
for DAG node entries. If they exist as spec nodes, mark them deprecated or
remove them:

- `ALG-KK-WEB-IDEAS-LIST`
- `ALG-KK-WEB-IDEAS-DETAIL`
- `ALG-KK-WEB-API-IDEAS-JSON`
- `INV-KK-WEB-IDEAS-RANKED`
- `INV-KK-WEB-IDEAS-FILTER`
- `INV-KK-WEB-IDEAS-EVIDENCE-CHAIN`
- `INV-KK-WEB-IDEA-BRIEF-VERBATIM`
- `INV-KK-WEB-IDEA-BRIEF-DEPTH`
- `INV-KK-WEB-API-IDEAS-JSON`
- `INV-KK-MCP-IDEA-FEED-RANKED`

**Note:** A grep for these in `combobul/spec/` found no files — they may only
exist as inline docstring references. If so, the docstring deletions in
Tasks 1.1 and 1.8 are sufficient.

---

## Part 2: Collect Research PDFs Locally

### Current state

- **44 research-type Source nodes** exist in `master.db` (see full inventory below)
- **0 local PDFs** exist anywhere in the repo
- `data/sources/` contains only 4 `.txt` kernel documentation files
- Only 1 of the 44 URLs points directly to a `.pdf` file

### Task 2.1: Create PDF download script

**New file:** `scripts/download_research_pdfs.py`

The script should:
1. Connect to `data/master.db`
2. Query all Source nodes where `source_type` is one of: `paper`, `preprint`,
   `conference-paper`, `conference-proceedings`
3. For each source, resolve the landing-page URL to a direct PDF URL using
   provider-specific rules (see table below)
4. Download the PDF to `data/pdfs/{source_id}.pdf`
5. Update the Source node's `attrs` with a `local_pdf_path` field
6. Print a summary of successes and failures

**Provider URL resolution rules:**

| Provider | URL pattern | PDF resolution |
|---|---|---|
| arxiv | `arxiv.org/abs/XXXX.XXXXX` | Replace `/abs/` with `/pdf/` and append `.pdf` → `arxiv.org/pdf/XXXX.XXXXX.pdf` |
| ACM DL | `dl.acm.org/doi/10.XXXX/XXXXXXX` | Append `/reader` or use `dl.acm.org/doi/pdf/10.XXXX/XXXXXXX` |
| USENIX | `usenix.org/conference/*/presentation/*` | Navigate to page, find PDF link (usually `usenix.org/system/files/*/paper.pdf`) — may require HTML parsing |
| EuroSys | `2025.eurosys.org/posters/*.pdf` | Already a direct PDF URL — download directly |
| LPC | `lpc.events/event/*/sessions/*` | Conference proceedings — no PDF typically available, skip or flag for manual download |
| SIGOPS/SOSP | `sigops.org/s/conferences/sosp/2025/accepted.html` | Accepted-papers list, not individual paper — skip, or look for linked preprints on arxiv |
| kernel.org | `kernel.org/doc/html/latest/*` | HTML documentation, not a PDF — already have `.txt` copies in `data/sources/`; skip |
| Other | Various | Log as "manual download needed" |

**Expected results by provider:**

| Provider | Count | Auto-downloadable? |
|---|---|---|
| arxiv (preprint + some conference) | 26 | Yes — trivial URL transform |
| ACM DL | 3 | Maybe — may need cookie/scraping |
| USENIX | 1 | Maybe — needs HTML parsing |
| EuroSys | 1 | Yes — direct PDF URL |
| LPC | 4 | No — proceedings pages, no PDFs |
| SIGOPS/SOSP | 5 | No — accepted-list pages only |
| kernel.org | 4 | No — HTML docs, already have .txt |

### Task 2.2: Create data/pdfs/ directory

- Create `data/pdfs/` directory
- Add `data/pdfs/.gitkeep` so the directory is tracked
- Consider adding `data/pdfs/*.pdf` to `.gitignore` (PDFs are large binaries;
  alternatively use Git LFS). Decision needed: track PDFs in git or gitignore them?

### Task 2.3: Complete inventory of all 44 research sources

This is the exhaustive list of Source nodes to process. Each entry includes the
node ID, source_type, title, and URL. The script must handle all of them.

**conference-paper (16 sources):**

| Node ID | Title | URL |
|---|---|---|
| `src-arxiv-bbr-default` | Should BBR be the default TCP Congestion Control Protocol? | https://arxiv.org/abs/2510.22461 |
| `src-asplos25-hybridtier` | HybridTier: an Adaptive and Lightweight CXL-Memory Tiering System | https://arxiv.org/abs/2312.04789 |
| `src-asplos25-m5` | M5: Mastering Page Migration and Memory Management for CXL-based Tiered Memory Systems | https://dl.acm.org/doi/10.1145/3676641.3711999 |
| `src-atc25-pageflex` | PageFlex: Flexible and Efficient User-space Delegation of Linux Paging Policies with eBPF | https://www.usenix.org/conference/atc25/presentation/yelam |
| `src-eurosys25-adios` | Adios to Busy-Waiting for Microsecond-scale Memory Disaggregation | https://dl.acm.org/doi/10.1145/3689031 |
| `src-eurosys25-xfs-zoned` | Evolving XFS with Zoned Storage and Intelligent Data Placement | https://2025.eurosys.org/posters/eurosys25posters-paper26.pdf |
| `src-osdi25-krr` | KRR: Efficient and Scalable Kernel Record Replay | https://paper.lingyunyang.com/reading-notes/conference/osdi-2025 |
| `src-socc25-dfuse` | DFUSE: Strongly Consistent Write-Back Kernel Caching for Distributed Userspace File Systems | https://arxiv.org/abs/2503.18191 |
| `src-sosp25-aeolia` | Aeolia: A Fast and Secure Userspace Interrupt-Based Storage Stack | https://sigops.org/s/conferences/sosp/2025/accepted.html |
| `src-sosp25-cache-ext` | cache_ext: Customizing the Page Cache with eBPF | https://dl.acm.org/doi/10.1145/3731569.3764820 |
| `src-sosp25-cortenmm` | CortenMM: Efficient Memory Management with Strong Correctness Guarantees | https://sigops.org/s/conferences/sosp/2025/accepted.html |
| `src-sosp25-demeter` | Demeter: A Scalable and Elastic Tiered Memory Solution for Virtualized Cloud via Guest Delegation | https://sigops.org/s/conferences/sosp/2025/accepted.html |
| `src-sosp25-far-memory` | Scalable Far Memory: Balancing Faults and Evictions | https://sigops.org/s/conferences/sosp/2025/accepted.html |
| `src-sosp25-flexguard` | FlexGuard: Fast Mutual Exclusion Independent of Subscription | https://sigops.org/s/conferences/sosp/2025/accepted.html |
| `src-sosp25-prove-kernel` | Prove It to the Kernel: Precise Extension Analysis via Proof-Guided Abstraction Refinement | https://dl.acm.org/doi/10.1145/3731569 |
| `src-sosp25-skiplist-vas` | Scalable Address Spaces using Concurrent Interval Skiplist | https://dl.acm.org/doi/10.1145/3731569.3764820 |

**conference-proceedings (4 sources):**

| Node ID | Title | URL |
|---|---|---|
| `src-lpc25-damon` | DAMON-based Pages Migration for CPU/GPU/XPU NUMA nodes (LPC 2025) | https://lpc.events/event/19/timetable/?view=standard |
| `src-lpc25-device-mem` | Device and Specific Purpose Memory Microconference (LPC 2025) | https://lpc.events/event/19/sessions/238/ |
| `src-lpc25-live-update` | Live Update Microconference (LPC 2025) | https://lpc.events/event/19/sessions/231/ |
| `src-lpc25-schedext` | sched_ext: The BPF extensible scheduler class (LPC 2025 Microconference) | https://lpc.events/event/19/sessions/229/ |

**paper (4 sources):**

| Node ID | Title | URL |
|---|---|---|
| `src-81beb980b826` | (untitled) | https://www.kernel.org/doc/html/latest/scheduler/sched-design-CFS.html |
| `src-963b067256a1` | (untitled) | https://www.kernel.org/doc/html/latest/RCU/whatisRCU.html |
| `src-c703381156d0` | (untitled) | https://www.kernel.org/doc/html/latest/locking/spinlocks.html |
| `src-ff0e8cb65c2c` | (untitled) | https://www.kernel.org/doc/html/latest/mm/page_tables.html |

**preprint (20 sources):**

| Node ID | Title | URL |
|---|---|---|
| `src-arxiv-agentic-sched` | Towards Agentic OS: An LLM Agent Framework for Linux Schedulers | https://arxiv.org/abs/2509.01245 |
| `src-arxiv-cachebpf` | Cache is King: Smart Page Eviction with eBPF | https://arxiv.org/abs/2502.02750 |
| `src-arxiv-ebpf-mm` | eBPF-mm: Userspace-guided memory management in Linux with eBPF | https://arxiv.org/abs/2409.11220 |
| `src-arxiv-ebpf-patrol` | eBPF-PATROL: Protective Agent for Threat Recognition and Overreach Limitation using eBPF | https://arxiv.org/abs/2511.18155 |
| `src-arxiv-ebpf-runtime` | The eBPF Runtime in the Linux Kernel | https://arxiv.org/abs/2410.00026 |
| `src-arxiv-iouring-async` | Asynchronous I/O -- With Great Power Comes Great Responsibility | https://arxiv.org/abs/2411.16254 |
| `src-arxiv-iouring-dbms` | io_uring for High-Performance DBMSs: When and How to use it | https://arxiv.org/abs/2512.04859 |
| `src-arxiv-iouring-scope` | uringscope: Portable, Low-Overhead Observability for io_uring | https://arxiv.org/abs/2606.15137 |
| `src-arxiv-joyride` | Joyride: Rethinking Linux's network stack design for better performance, security, and reliability | https://arxiv.org/abs/2509.25015 |
| `src-arxiv-l7-offload` | Offloading L7 Policies to the Kernel | https://arxiv.org/abs/2605.31084 |
| `src-arxiv-necofuzz-kvm` | NecoFuzz: Effective Fuzzing of Nested Virtualization via Fuzz-Harness Virtual Machines | https://arxiv.org/abs/2512.08858 |
| `src-arxiv-paracell` | ParaCell: Paravirtualized Secure Containers with Lightweight Intra-Container Isolation | https://arxiv.org/abs/2605.20906 |
| `src-arxiv-paracell-ns` | ParaCell: Paravirtualized Secure Containers with Lightweight Intra-Container Isolation | https://arxiv.org/abs/2605.20906 |
| `src-arxiv-patch-evolution` | Beyond Crash-to-Patch: Patch Evolution for Linux Kernel Repair | https://arxiv.org/abs/2604.03851 |
| `src-arxiv-rcu-sync` | Identifying Linux Kernel Instability Due to Poor RCU Synchronization | https://arxiv.org/abs/2511.00237 |
| `src-arxiv-resystance` | RESYSTANCE: Unleashing Hidden Performance of Compaction in LSM-trees via eBPF | https://arxiv.org/abs/2603.05162 |
| `src-arxiv-tierbpf` | TierBPF: Page Migration Admission Control for Tiered Memory via eBPF | https://arxiv.org/abs/2604.12300 |
| `src-arxiv-ufs-sched` | Unfair by design: eBPF-based scheduling of mixed database workloads | https://arxiv.org/abs/2605.02377 |
| `src-arxiv-vmem` | Vmem: A Lightweight Hot-Upgradable Memory Management for In-production Cloud Environment | https://arxiv.org/abs/2511.09961 |
| `src-arxiv-xlb` | XLB: A High Performance Layer-7 Load Balancer for Microservices using eBPF-based In-kernel Interposition | https://arxiv.org/abs/2602.09473 |

**Note:** `src-arxiv-paracell` and `src-arxiv-paracell-ns` are duplicates
pointing to the same arxiv URL. The script should deduplicate downloads but
update both node attrs.

### Task 2.4: Handle SOSP/SIGOPS papers without direct PDFs

Five conference papers point to `sigops.org/s/conferences/sosp/2025/accepted.html`
(the accepted-papers list page). These are:
- `src-sosp25-aeolia`
- `src-sosp25-cortenmm`
- `src-sosp25-demeter`
- `src-sosp25-far-memory`
- `src-sosp25-flexguard`

Strategy:
1. Search arxiv for each paper title — many SOSP papers have arxiv preprints
2. If found, download from arxiv and update the Source node URL (or add a
   secondary `arxiv_url` attr)
3. If not found, log as "manual download needed"

### Task 2.5: Update Source node attrs with local_pdf_path

After downloading, update each Source node's `attrs` JSON to include:
```json
{
  "local_pdf_path": "data/pdfs/src-arxiv-cachebpf.pdf",
  "pdf_downloaded_at": "2026-07-08"
}
```

This lets the web UI and extraction pipeline know a local copy exists.

---

## Implementation order

| Step | Task(s) | Skill | Notes |
|---|---|---|---|
| 1 | 1.1–1.6 | `/cb-green` | Single changeset: remove all Ideas UI code |
| 2 | 1.7–1.8 | `/cb-green` | Second changeset: remove all Ideas tests + MCP |
| 3 | 1.10 | `/cb-green` | If spec nodes exist, deprecate them |
| 4 | 2.1–2.2 | `/cb-green` | Create download script + directory |
| 5 | 2.3–2.5 | `/cb-free` or manual | Run the download script, handle failures |
| 6 | — | `/cb-ops` | Commit and push all changes |

Steps 1 and 2 could potentially be combined into a single `/cb-green` if the
changeset is not too large. Steps 4 and 5 are independent of steps 1–3.

---

## Existing local source files (for reference)

These 4 `.txt` files already exist in `data/sources/` and correspond to the 4
`paper`-type Source nodes pointing to kernel.org:

| File | Corresponds to |
|---|---|
| `data/sources/rcu_whatisRCU.txt` | `src-963b067256a1` (kernel.org RCU doc) |
| `data/sources/locking_spinlocks.txt` | `src-c703381156d0` (kernel.org locking doc) |
| `data/sources/scheduler_cfs.txt` | `src-81beb980b826` (kernel.org CFS doc) |
| `data/sources/mm_page_tables.txt` | `src-ff0e8cb65c2c` (kernel.org page_tables doc) |

These do NOT need PDF downloads — they are already local as text.
