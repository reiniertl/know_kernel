# Plan: Motivation Categories and Argument-Driven Idea Narratives

**Status:** Ready for implementation
**Date:** 2026-06-30
**Scope:** Add 7 orthogonal motivation categories to idea briefs; restructure idea_detail and vuln_detail templates from data-dump to argument-driven narrative
**Prerequisite:** build_concept_brief() exists in src/graph/briefing.py; idea_detail and vuln_detail routes already call it; templates already render all 15 data categories but in wrong structure
**Implementation:** 3 /cb-green stages

---

## Problem Statement

The idea detail page was rewritten to show all 15 data categories from
build_concept_brief(), but it's organized like a database report:
scores table → evidence table → vulns table → constraints table → dependencies.

This fails in two ways:

### 1. No motivation — "hot for what reason?"

The page says "this area is hot" but never answers WHY a developer should
invest time. Every idea has a reason tied to a specific concern:
- Is there a security issue?
- Is there a performance bottleneck?
- Is there a scalability wall?
- Is reliability breaking down?
- Is new hardware going unexploited?
- Is the code becoming unmaintainable?
- Is there resource waste?

The system detects convergence but doesn't classify WHAT is converging.

### 2. No argument — data without narrative

The page dumps data by category (vulnerabilities section, problems section,
invariants section) when it should lead with an argument:
"Here's what's happening → Here's why you should care → Here's the evidence →
Here's what's at stake → Here's what you'd need to touch."

The KVM page currently reads: score table, then a list of CVE descriptions,
then invariant predicates, then dependency lists. It should read: "KVM has
a security problem AND a stability problem AND a performance opportunity.
Here's the evidence for each. Here's what it would take to fix."

### Current file state (after previous sprint)

- `src/graph/briefing.py` — `build_concept_brief()` returns 15-key dict (exists, works, no changes needed)
- `src/web/routes.py` lines 564-645 — `idea_detail()` calls `build_concept_brief()`, passes briefs to template
- `src/web/routes.py` lines 780-840 — `vuln_detail()` calls `build_concept_brief()` for direct concepts
- `src/web/templates/idea_detail.html` — 239 lines, category-organized data dump
- `src/web/templates/vuln_detail.html` — 161 lines, concept-brief sections

---

## Design: 7 Orthogonal Motivation Categories

Each category is detected by querying data already present in the concept
brief dict returned by `build_concept_brief()`. No new graph queries needed.

### Category definitions with detection logic

#### 1. SECURITY — "This is being attacked"

An adversary can exploit this. Active CVEs, exploitable weaknesses.

**Detection from brief dict:**
```python
triggered = len(brief["vulnerabilities"]) > 0
```

**Display data (all from brief["vulnerabilities"]):**
- Number of active CVEs with severity breakdown (critical/high/medium/low)
- Highest CVSS score
- Each vulnerability's description (verbatim from Vulnerability.description)
- Propagation count from vulnerability_propagation() (already computed by vuln_detail route; for idea_detail, compute from brief["prerequisites"]["depended_on_by"] as proxy)
- CVE IDs for reference

**Example narrative (templated, not LLM-generated):**
> **SECURITY** — 3 active vulnerabilities, all HIGH (CVSS 8.8). Missing SRCU
> locks in page table walks allow memory corruption under concurrent access
> (CVE-2026-53277). VFIO DMABuf cleanup race creates use-after-free window
> (CVE-2026-53322). 4 additional components at risk through coupling.

**Narrative template logic:**
```
"{n} active vulnerabilit{y/ies}, {severity_breakdown}.
{top_vuln.title} ({top_vuln.cve_id}).
{if depended_on_by > 0: "{n} additional components at risk through coupling."}"
```

#### 2. STABILITY — "This fails on its own"

Crashes, panics, data corruption under normal operation. No adversary needed.

**Detection from brief dict:**
```python
triggered = len(brief["failure_modes"]) > 0 or any(
    p["severity"] in ("critical", "high") for p in brief["problems"]
)
```

**Display data:**
- From brief["failure_modes"]: symptom (verbatim from FailureMode.symptom), blast_radius, recoverability
- From brief["invariants"]: predicate text (verbatim from KernelInvariant.predicate) — the rule being violated
- From brief["problems"]: critical/high severity problems (verbatim from Problem.title + description)

**Example narrative:**
> **STABILITY** — Known failure mode: "VM exit handler crashes host kernel —
> unrecoverable panic from dereferencing guest-controlled data in host
> context" (blast radius: kernel-wide, requires restart). Triggered when
> invariant "Every VM exit must be handled by the host before re-entering
> the guest" is violated.

**Narrative template logic:**
```
"{n} known failure mode{s}: "{top_fm.symptom}" (blast radius: {top_fm.blast_radius}, {top_fm.recoverability}).
{if invariants: "Triggered when invariant \"{inv.predicate}\" is violated."}
{if problems: "{n} open {severity} problem{s}."}"
```

**Orthogonality note:** A NULL deref that crashes is STABILITY. The same NULL
deref that an attacker can trigger for privilege escalation is SECURITY. Same
bug, different motivation. A concept can trigger both categories independently.

#### 3. PERFORMANCE — "This could be faster"

Measurably slow. Latency, throughput, IOPS bottlenecks.

**Detection from brief dict:**
```python
triggered = len(brief["profiles"]) > 0 or len(brief["benchmarks"]) > 0 or any(
    _has_performance_keywords(o["claim"]) for o in brief["observations"]
)
```

**Keyword list for `_has_performance_keywords()`:**
```python
_PERFORMANCE_KEYWORDS = {
    "latency", "throughput", "overhead", "bottleneck", "faster", "slower",
    "regression", "improvement", "speedup", "bandwidth", "IOPS", "cycles",
    "cache miss", "TLB miss", "context switch",
}
```

**Display data:**
- From brief["profiles"]: metric, best_case, worst_case, typical_case, conditions (all verbatim from PerformanceProfile attrs)
- The gap between worst_case and best_case as the opportunity signal
- From brief["benchmarks"]: result_summary (verbatim from Benchmark.result_summary)
- Performance-related observations from brief["observations"] filtered by keywords

**Example narrative:**
> **PERFORMANCE** — VM entry/exit latency: 500ns best → 5μs worst (10x range).
> Typical I/O exit: 1-2μs on Intel VT-x with EPT. Worst case on complex MMIO
> emulation suggests optimization opportunity in the exit handling path.

**Narrative template logic:**
```
"{if profiles: "{prof.metric}: {prof.best_case} best → {prof.worst_case} worst.
Typical: {prof.typical_case} under {prof.conditions}."}
{if benchmarks: "{bench.result_summary} ({bench.conditions})."}
{if perf_observations: "\"{obs.claim}\""}"
```

#### 4. SCALABILITY — "This breaks at scale"

Works at small scale but degrades. Core count walls, NUMA effects, memory
pressure at size.

**Detection from brief dict:**
```python
triggered = any(
    _has_scalability_keywords(p["description"]) for p in brief["problems"]
) or any(
    _has_scalability_keywords(o["claim"]) for o in brief["observations"]
) or any(
    _has_scalability_keywords(d["title"]) for d in brief["discussions"]
)
```

**Keyword list for `_has_scalability_keywords()`:**
```python
_SCALABILITY_KEYWORDS = {
    "NUMA", "core count", "128 cores", "256 cores", "512 cores",
    "scalab", "contention", "lock contention", "per-cpu", "per-node",
    "cache line bouncing", "false sharing", "thundering herd",
    "multi-socket", "cross-node", "numa node", "memory node",
}
```

**Display data:**
- Scaling-related problems (verbatim descriptions)
- Scaling-related observations (verbatim claims)
- Which scale dimension is affected (cores, memory, devices — inferred from keywords)

**Example narrative:**
> **SCALABILITY** — "SLUB per-node partial list traversal causes 15%
> throughput loss on 4-node NUMA systems." Lock contention in the fast path
> spikes above 128 cores on allocation-heavy workloads.

**Narrative template logic:**
```
"{for each scaling problem/observation: "\"{verbatim text}\""}"
```

#### 5. EFFICIENCY — "This wastes resources"

Power consumption, memory footprint, CPU overhead for housekeeping.

**Detection from brief dict:**
```python
triggered = any(
    _has_efficiency_keywords(prof["metric"]) for prof in brief["profiles"]
) or any(
    _has_efficiency_keywords(o["claim"]) for o in brief["observations"]
) or any(
    _has_efficiency_keywords(p["description"]) for p in brief["problems"]
)
```

**Keyword list for `_has_efficiency_keywords()`:**
```python
_EFFICIENCY_KEYWORDS = {
    "memory overhead", "memory footprint", "power consumption", "energy",
    "CPU utilization", "wasted", "footprint", "bloat", "fragmentation",
    "internal fragmentation", "external fragmentation", "metadata overhead",
    "housekeeping", "idle power", "thermal",
}
```

**Display data:**
- Efficiency-related profiles (metric + values)
- Efficiency-related observations (verbatim claims)
- What resource is being wasted

**Example narrative:**
> **EFFICIENCY** — SLUB metadata overhead: 12.5% of slab pages consumed by
> freelist pointers and red zones. Internal fragmentation increases 3x under
> CONFIG_SLAB_MERGE_DEFAULT.

**Narrative template logic:**
```
"{for each efficiency observation/profile: "\"{verbatim text}\""}"
```

**Orthogonality note:** An allocator can be fast (PERFORMANCE) but waste 30%
of RAM on fragmentation (EFFICIENCY). A scheduler can be responsive
(PERFORMANCE) but burn CPU on load balancing housekeeping (EFFICIENCY).
Independent axes.

#### 6. HARDWARE ENABLEMENT — "Hardware is ahead of software"

New hardware capabilities not yet exploited by software.

**Detection from brief dict:**
```python
triggered = any(
    _has_hardware_keywords(d["title"]) for d in brief["discussions"]
) or any(
    _has_hardware_keywords(o["claim"]) for o in brief["observations"]
) or _has_hardware_keywords(brief["concept"]["description"])
```

Additionally, a heuristic: if the concept is in a hardware-adjacent subsystem
(Device Drivers, Virtualization, Storage Stack, Firmware Interface) AND has
high heat but low pain, it's likely an opportunity-driven area rather than a
crisis-driven area.

```python
hardware_opportunity_heuristic = (
    brief["subsystem"] and
    brief["subsystem"]["name"] in _HARDWARE_SUBSYSTEMS and
    brief["scores"]["heat"] > brief["scores"]["pain"]
)
```

**Keyword list for `_has_hardware_keywords()`:**
```python
_HARDWARE_KEYWORDS = {
    "hardware", "instruction", "CXL", "PCIe", "NVMe", "accelerat",
    "FPGA", "GPU", "DPU", "AMX", "SVE", "SME", "TDX", "SEV",
    "persistent memory", "PMEM", "DDR5", "HBM", "CXL.mem",
    "device class", "new device", "hardware capability",
}
_HARDWARE_SUBSYSTEMS = {
    "Device Drivers", "Virtualization", "Storage Stack",
    "Firmware Interface", "Cryptography",
}
```

**Display data:**
- Hardware-related discussions (verbatim titles with dates and forums)
- Concept description referencing hardware (verbatim)
- Which hardware capabilities are mentioned

**Example narrative:**
> **HARDWARE ENABLEMENT** — KVM interfaces directly with VMX/SVM hardware
> virtualization extensions. Recent discussions at OSPM 2026 cover hardware-
> assisted features. 4 hardware-dependent components (Memory Ballooning,
> VMX/SVM, VFIO, Virtio) indicate active hardware interface evolution.

#### 7. MAINTAINABILITY — "Developers struggle with this"

High fix churn, frequent regressions, code that's expensive to change.

**Detection from brief dict:**
```python
regression_fixes = [f for f in brief["fixes"] if f["fix_type"] == "regression-fix"]
triggered = len(brief["fixes"]) >= 3 or len(regression_fixes) > 0
```

**Display data:**
- Fix count in recent window (from brief["fixes"])
- Regression fix count
- Which problems keep getting re-fixed (from fix.resolves cross-referencing)
- Fix type distribution

**Example narrative:**
> **MAINTAINABILITY** — 7 patches in the last 30 days, including 2 regression
> fixes reverting earlier optimizations. High churn indicates fragile code in
> the exit handling path.

**Narrative template logic:**
```
"{n} patch{es} in last {window} days{if regressions: ", including {n} regression fix{es}"}.
{if high_churn: "High churn indicates fragile code."}"
```

---

## The Argument Paragraph

After the motivation categories, the page needs a **templated argument
paragraph** ("THE CASE") that ties the motivations together into a coherent
statement about why this convergence matters.

**Input data for the argument:**
- Which motivation categories triggered (list of category names)
- Source count from brief timeline (number of independent sources)
- Window period (from Trend.window_start/window_end or default 90 days)
- Total vulnerability count and dominant severity
- Total dependent count from prerequisites
- Subsystem name

**Template structure:**
```python
def build_argument_paragraph(
    node: dict,
    briefs: list[dict],
    motivations: list[dict],
    window_days: int = 90,
) -> str:
    """Compose a templated argument paragraph from structured data."""
    parts = []

    # Opening: convergence signal
    source_count = sum(len(b["discussions"]) for b in briefs)
    concept_names = [b["concept"]["name"] for b in briefs]
    parts.append(
        f"{source_count} independent source{'s' if source_count != 1 else ''} "
        f"discuss{'es' if source_count == 1 else ''} "
        f"{', '.join(concept_names)} over the last {window_days} days."
    )

    # Middle: what's driving the convergence (from dominant motivations)
    motivation_names = [m["category"] for m in motivations]
    if "security" in motivation_names:
        vuln_count = sum(len(b["vulnerabilities"]) for b in briefs)
        dominant_sev = _dominant_severity(briefs)
        parts.append(
            f"The convergence is driven by {vuln_count} "
            f"{dominant_sev.upper()}-severity vulnerabilit"
            f"{'y' if vuln_count == 1 else 'ies'} "
            f"concentrated in active code paths."
        )

    if "stability" in motivation_names:
        fm_count = sum(len(b["failure_modes"]) for b in briefs)
        parts.append(
            f"{'Combined with' if parts[-1] != parts[0] else 'Driven by'} "
            f"{fm_count} known failure mode{'s' if fm_count != 1 else ''} "
            f"that can cause system instability."
        )

    if "performance" in motivation_names:
        parts.append(
            "Performance profiling shows measurable optimization opportunity."
        )

    # Closing: blast radius
    dep_count = sum(len(b["prerequisites"]["depended_on_by"]) for b in briefs)
    if dep_count > 0:
        dep_names = []
        for b in briefs:
            dep_names.extend(d["name"] for d in b["prerequisites"]["depended_on_by"])
        parts.append(
            f"{dep_count} component{'s' if dep_count != 1 else ''} "
            f"depend{'s' if dep_count == 1 else ''} on "
            f"{concept_names[0]}: {', '.join(dep_names[:4])}"
            f"{'...' if len(dep_names) > 4 else ''}. "
            f"A fix here would resolve exposure across all of them."
        )

    return " ".join(parts)
```

This is NOT an LLM-generated summary. It is templated prose composed from
counted data. Every sentence maps directly to a graph query result.

---

## Revised Idea Card Structure

The page restructures from "data by category" to "argument first, evidence
second, structural detail third":

```
HEADER
  Title · Kind badge · Frontier score · Subsystem

WHY PURSUE THIS (motivation categories — only triggered ones shown)
  🔴 SECURITY — {narrative with verbatim CVE descriptions}
  ⚠️  STABILITY — {narrative with verbatim failure mode symptoms}
  ⚡ PERFORMANCE — {narrative with verbatim profile data}
  📈 SCALABILITY — {narrative with verbatim scaling observations}
  💡 EFFICIENCY — {narrative with verbatim resource waste data}
  🔧 HARDWARE — {narrative with verbatim hardware discussions}
  🔄 MAINTAINABILITY — {narrative with fix churn data}

THE CASE (templated argument paragraph)
  "{n} independent sources... convergence driven by... {dep_count}
   components depend on... fix here resolves..."

SCORES (compact table — heat, pain, impact, leverage, frontier)

EVIDENCE (verbatim timeline — all evidence items with dates)
  Each entry: date · kind badge · verbatim text from node attribute

STRUCTURAL DETAIL (collapsible or below-the-fold)
  Invariants · Failure Modes · Protocols · Dependencies ·
  Performance Profiles · Code Examples

RELATED IDEAS
```

### Key differences from current template

| Aspect | Current (data dump) | Proposed (argument-driven) |
|--------|-------------------|---------------------------|
| Page lead | Score table | WHY PURSUE THIS — motivation categories |
| Vulnerabilities | Separate section after evidence | Integrated into SECURITY motivation |
| Failure modes | Under "Structural Constraints" | Integrated into STABILITY motivation |
| Performance profiles | Under "Performance Context" | Integrated into PERFORMANCE motivation |
| Problems | Under "Open Problems" | Integrated into relevant motivation |
| Evidence | Raw timeline table | Below the argument, with dates |
| Narrative | None | THE CASE — templated argument paragraph |
| Structural detail | Prominent sections | Below the fold / collapsible |

---

## Specification Surface Changes

### Existing nodes to modify (2 modify-node mutations)

#### 1. ALG-KK-WEB-IDEAS-DETAIL

**Current description (from DAG):**
"GET /ideas/{idea_id} route. Fetches Opportunity or Trend node by ID. For
each linked Concept (via opportunity-for or trend-about edges), calls
build_concept_brief() to query the full graph depth..."

**New description:**
"GET /ideas/{idea_id} route. Fetches Opportunity or Trend node by ID. For
each linked Concept, calls build_concept_brief() for full graph depth. Then
calls classify_motivations() to detect which of 7 orthogonal motivation
categories apply (security, stability, performance, scalability, efficiency,
hardware_enablement, maintainability). Calls build_argument_paragraph() to
compose a templated narrative from the motivation data. Renders idea_detail.html
as an argument-driven research brief: motivation categories with verbatim
evidence first, templated argument paragraph, scores, evidence timeline,
structural detail last."

#### 2. INV-KK-WEB-IDEAS-EVIDENCE-CHAIN

**Current predicate:** "forall idea I at /ideas/{id}. forall concept C linked
to I via opportunity-for or trend-about. all evidence E linked to C via
identifies-problem, observes, discusses, benchmarks, rejected-for, grounded-in,
or exploits edges are shown with verbatim text from E.attrs."

**New predicate:** "forall idea I at /ideas/{id}. forall concept C linked to I.
evidence E linked to C is shown twice: (1) within the triggered motivation
category sections with narrative context, (2) in the complete evidence timeline
with verbatim text and source_date. No evidence is omitted. Evidence text is
never modified."

### New nodes to add

#### 3. INV-KK-WEB-IDEA-MOTIVATIONS (new invariant)

**Description:** "The idea detail page classifies each idea into 1-7 orthogonal
motivation categories (security, stability, performance, scalability,
efficiency, hardware_enablement, maintainability) based on the concept brief
data. Categories are detected from graph data only (no LLM). Only triggered
categories are displayed. Each category shows a narrative sentence with
verbatim evidence supporting the classification."

**Predicate:** "forall idea I. motivations(I) = classify_motivations(briefs(I))
where each category is triggered by threshold conditions on brief data
(vulnerability count > 0 for security, failure_mode count > 0 or critical
problems for stability, etc.). |motivations(I)| >= 1 for all displayed ideas."

**PredicateNL:** "Every idea on the detail page shows at least one motivation
category, detected from graph data. Only triggered categories are shown."

**Edges:**
- `contains` from `SUB-KK-WEB` to `INV-KK-WEB-IDEA-MOTIVATIONS`
- `checked-at` from `INV-KK-WEB-IDEA-MOTIVATIONS` to `stage-delivery`
- `satisfies` from `ALG-KK-WEB-IDEAS-DETAIL` to `INV-KK-WEB-IDEA-MOTIVATIONS`

#### 4. INV-KK-WEB-IDEA-ARGUMENT (new invariant)

**Description:** "The idea detail page includes a templated argument paragraph
('THE CASE') composed from structured data: source count, dominant motivation
categories, vulnerability severity distribution, dependent component count.
The paragraph is deterministic — same graph data always produces the same text.
It is NOT LLM-generated."

**Predicate:** "forall idea I. argument_paragraph(I) =
build_argument_paragraph(node(I), briefs(I), motivations(I)). The function is
pure: same inputs produce identical output."

**PredicateNL:** "Every idea detail page has a templated argument paragraph
composed deterministically from graph data counts and motivation categories."

**Edges:**
- `contains` from `SUB-KK-WEB` to `INV-KK-WEB-IDEA-ARGUMENT`
- `checked-at` from `INV-KK-WEB-IDEA-ARGUMENT` to `stage-delivery`
- `satisfies` from `ALG-KK-WEB-IDEAS-DETAIL` to `INV-KK-WEB-IDEA-ARGUMENT`

### Total spec mutations: 2 modify-node + 2 add-node + 6 add-edge = 10 mutations

---

## Code Changes — Complete Task Breakdown

### Stage 1: classify_motivations() + build_argument_paragraph()

#### Task 1.1: Add motivation classification to `src/graph/briefing.py`

Add the following functions to the existing `src/graph/briefing.py` module
(after `_empty_brief()` at line 365):

**Constants:**

```python
_PERFORMANCE_KEYWORDS = frozenset({
    "latency", "throughput", "overhead", "bottleneck", "faster", "slower",
    "regression", "improvement", "speedup", "bandwidth", "iops", "cycles",
    "cache miss", "tlb miss", "context switch",
})

_SCALABILITY_KEYWORDS = frozenset({
    "numa", "core count", "128 cores", "256 cores", "512 cores",
    "scalab", "contention", "lock contention", "per-cpu", "per-node",
    "cache line bouncing", "false sharing", "thundering herd",
    "multi-socket", "cross-node", "numa node", "memory node",
})

_EFFICIENCY_KEYWORDS = frozenset({
    "memory overhead", "memory footprint", "power consumption", "energy",
    "cpu utilization", "wasted", "footprint", "bloat", "fragmentation",
    "internal fragmentation", "external fragmentation", "metadata overhead",
    "housekeeping", "idle power", "thermal",
})

_HARDWARE_KEYWORDS = frozenset({
    "hardware", "instruction", "cxl", "pcie", "nvme", "accelerat",
    "fpga", "gpu", "dpu", "amx", "sve", "sme", "tdx", "sev",
    "persistent memory", "pmem", "ddr5", "hbm", "cxl.mem",
    "device class", "new device", "hardware capability",
})

_HARDWARE_SUBSYSTEMS = frozenset({
    "Device Drivers", "Virtualization", "Storage Stack",
    "Firmware Interface", "Cryptography",
})

_MOTIVATION_ICONS = {
    "security": "🔴",
    "stability": "⚠️",
    "performance": "⚡",
    "scalability": "📈",
    "efficiency": "💡",
    "hardware_enablement": "🔧",
    "maintainability": "🔄",
}

_MOTIVATION_LABELS = {
    "security": "SECURITY",
    "stability": "STABILITY",
    "performance": "PERFORMANCE",
    "scalability": "SCALABILITY",
    "efficiency": "EFFICIENCY",
    "hardware_enablement": "HARDWARE ENABLEMENT",
    "maintainability": "MAINTAINABILITY",
}
```

**Helper function:**

```python
def _text_has_keywords(text: str, keywords: frozenset[str]) -> bool:
    """Check if text contains any keyword (case-insensitive)."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)
```

**Main function `classify_motivations()`:**

```python
def classify_motivations(brief: dict[str, Any]) -> list[dict[str, Any]]:
    """Classify a concept brief into 1-7 orthogonal motivation categories.

    Returns list of dicts, each with:
      category: str (security|stability|performance|scalability|efficiency|
                     hardware_enablement|maintainability)
      icon: str (emoji)
      label: str (display name)
      headline: str (one-line summary)
      evidence: list[dict] (supporting data points with verbatim text)

    Only triggered categories are returned. Order follows priority:
    security > stability > performance > scalability > efficiency >
    hardware_enablement > maintainability.
    """
    motivations = []

    # --- SECURITY ---
    vulns = brief["vulnerabilities"]
    if vulns:
        severity_counts = {}
        for v in vulns:
            s = v.get("severity", "medium")
            severity_counts[s] = severity_counts.get(s, 0) + 1
        severity_parts = []
        for s in ("critical", "high", "medium", "low"):
            if severity_counts.get(s):
                severity_parts.append(f"{severity_counts[s]} {s}")
        dep_count = len(brief["prerequisites"]["depended_on_by"])
        headline = (
            f"{len(vulns)} active vulnerabilit{'y' if len(vulns) == 1 else 'ies'}"
            f" ({', '.join(severity_parts)})"
        )
        if dep_count > 0:
            headline += f". {dep_count} additional component{'s' if dep_count != 1 else ''} at risk through coupling"
        evidence = [
            {"type": "vulnerability", "text": f"{v['cve_id']}: {v['description']}", "severity": v["severity"], "cvss": v["cvss_score"]}
            for v in vulns
        ]
        motivations.append({
            "category": "security",
            "icon": _MOTIVATION_ICONS["security"],
            "label": _MOTIVATION_LABELS["security"],
            "headline": headline,
            "evidence": evidence,
        })

    # --- STABILITY ---
    failure_modes = brief["failure_modes"]
    critical_problems = [p for p in brief["problems"] if p["severity"] in ("critical", "high")]
    if failure_modes or critical_problems:
        parts = []
        fm_evidence = []
        if failure_modes:
            top_fm = failure_modes[0]
            parts.append(
                f"Known failure mode: \"{top_fm['symptom']}\""
                f" (blast radius: {top_fm['blast_radius']}, {top_fm['recoverability']})"
            )
            fm_evidence.extend(
                {"type": "failure_mode", "text": fm["symptom"], "blast_radius": fm["blast_radius"]}
                for fm in failure_modes
            )
        if brief["invariants"]:
            top_inv = brief["invariants"][0]
            parts.append(f"Invariant at risk: \"{top_inv['predicate']}\"")
            fm_evidence.extend(
                {"type": "invariant", "text": inv["predicate"]}
                for inv in brief["invariants"]
            )
        if critical_problems:
            parts.append(f"{len(critical_problems)} open {critical_problems[0]['severity']} problem{'s' if len(critical_problems) != 1 else ''}")
            fm_evidence.extend(
                {"type": "problem", "text": p["title"], "severity": p["severity"]}
                for p in critical_problems
            )
        motivations.append({
            "category": "stability",
            "icon": _MOTIVATION_ICONS["stability"],
            "label": _MOTIVATION_LABELS["stability"],
            "headline": ". ".join(parts),
            "evidence": fm_evidence,
        })

    # --- PERFORMANCE ---
    profiles = brief["profiles"]
    benchmarks = brief["benchmarks"]
    perf_observations = [o for o in brief["observations"] if _text_has_keywords(o["claim"], _PERFORMANCE_KEYWORDS)]
    if profiles or benchmarks or perf_observations:
        parts = []
        perf_evidence = []
        if profiles:
            top_prof = profiles[0]
            parts.append(f"{top_prof['metric']}: {top_prof['best_case']} best → {top_prof['worst_case']} worst")
            perf_evidence.extend(
                {"type": "profile", "text": f"{p['metric']}: {p['best_case']} → {p['worst_case']} ({p['conditions']})"}
                for p in profiles
            )
        if benchmarks:
            perf_evidence.extend(
                {"type": "benchmark", "text": b["result_summary"]}
                for b in benchmarks
            )
        if perf_observations:
            for o in perf_observations:
                parts.append(f"\"{o['claim']}\"")
            perf_evidence.extend(
                {"type": "observation", "text": o["claim"]}
                for o in perf_observations
            )
        motivations.append({
            "category": "performance",
            "icon": _MOTIVATION_ICONS["performance"],
            "label": _MOTIVATION_LABELS["performance"],
            "headline": ". ".join(parts) if parts else "Performance data available",
            "evidence": perf_evidence,
        })

    # --- SCALABILITY ---
    all_text_fields = (
        [p["description"] for p in brief["problems"]]
        + [o["claim"] for o in brief["observations"]]
        + [d["title"] for d in brief["discussions"]]
    )
    scaling_hits = [t for t in all_text_fields if _text_has_keywords(t, _SCALABILITY_KEYWORDS)]
    if scaling_hits:
        motivations.append({
            "category": "scalability",
            "icon": _MOTIVATION_ICONS["scalability"],
            "label": _MOTIVATION_LABELS["scalability"],
            "headline": scaling_hits[0],
            "evidence": [{"type": "text_match", "text": t} for t in scaling_hits],
        })

    # --- EFFICIENCY ---
    efficiency_hits = (
        [f"{p['metric']}: {p['worst_case']}" for p in profiles if _text_has_keywords(p["metric"], _EFFICIENCY_KEYWORDS)]
        + [o["claim"] for o in brief["observations"] if _text_has_keywords(o["claim"], _EFFICIENCY_KEYWORDS)]
        + [p["description"] for p in brief["problems"] if _text_has_keywords(p["description"], _EFFICIENCY_KEYWORDS)]
    )
    if efficiency_hits:
        motivations.append({
            "category": "efficiency",
            "icon": _MOTIVATION_ICONS["efficiency"],
            "label": _MOTIVATION_LABELS["efficiency"],
            "headline": efficiency_hits[0],
            "evidence": [{"type": "text_match", "text": t} for t in efficiency_hits],
        })

    # --- HARDWARE ENABLEMENT ---
    hw_hits = (
        [d["title"] for d in brief["discussions"] if _text_has_keywords(d["title"], _HARDWARE_KEYWORDS)]
        + [o["claim"] for o in brief["observations"] if _text_has_keywords(o["claim"], _HARDWARE_KEYWORDS)]
    )
    hw_from_description = _text_has_keywords(brief["concept"]["description"], _HARDWARE_KEYWORDS)
    hw_from_subsystem = (
        brief["subsystem"] is not None
        and brief["subsystem"]["name"] in _HARDWARE_SUBSYSTEMS
        and brief["scores"]["heat"] > brief["scores"]["pain"]
    )
    if hw_hits or hw_from_description or hw_from_subsystem:
        parts = []
        hw_evidence = [{"type": "text_match", "text": t} for t in hw_hits]
        if hw_from_description:
            parts.append(f"{brief['concept']['name']} interfaces with hardware capabilities")
            hw_evidence.append({"type": "concept_description", "text": brief["concept"]["description"][:200]})
        if hw_from_subsystem:
            parts.append(f"Active area in {brief['subsystem']['name']} subsystem (heat > pain)")
        if hw_hits:
            parts.append(hw_hits[0])
        motivations.append({
            "category": "hardware_enablement",
            "icon": _MOTIVATION_ICONS["hardware_enablement"],
            "label": _MOTIVATION_LABELS["hardware_enablement"],
            "headline": ". ".join(parts) if parts else "Hardware-related activity",
            "evidence": hw_evidence,
        })

    # --- MAINTAINABILITY ---
    fixes = brief["fixes"]
    regression_fixes = [f for f in fixes if f["fix_type"] == "regression-fix"]
    if len(fixes) >= 3 or regression_fixes:
        parts = [f"{len(fixes)} patch{'es' if len(fixes) != 1 else ''} in recent window"]
        if regression_fixes:
            parts.append(f"{len(regression_fixes)} regression fix{'es' if len(regression_fixes) != 1 else ''}")
        motivations.append({
            "category": "maintainability",
            "icon": _MOTIVATION_ICONS["maintainability"],
            "label": _MOTIVATION_LABELS["maintainability"],
            "headline": ", including ".join(parts) if len(parts) > 1 else parts[0],
            "evidence": [
                {"type": "fix", "text": f["title"], "fix_type": f["fix_type"], "commit": f["commit_hash"]}
                for f in fixes
            ],
        })

    return motivations
```

**Function `build_argument_paragraph()`:**

```python
def build_argument_paragraph(
    node_attrs: dict[str, Any],
    briefs: list[dict[str, Any]],
    motivations: list[dict[str, Any]],
    window_days: int = 90,
) -> str:
    """Compose a deterministic argument paragraph from structured data.

    Every sentence maps to a specific graph data count. This is NOT
    LLM-generated — same inputs always produce identical output.
    """
    parts = []
    concept_names = [b["concept"]["name"] for b in briefs]
    source_count = sum(len(b["discussions"]) + len(b["observations"]) for b in briefs)

    # Opening: convergence signal
    if source_count > 0:
        parts.append(
            f"{source_count} independent source{'s' if source_count != 1 else ''} "
            f"discuss{'es' if source_count == 1 else ''} "
            f"{' and '.join(concept_names)} over the last {window_days} days."
        )

    # Middle: what's driving the convergence
    cat_names = {m["category"] for m in motivations}

    if "security" in cat_names:
        vuln_count = sum(len(b["vulnerabilities"]) for b in briefs)
        severities = [v["severity"] for b in briefs for v in b["vulnerabilities"]]
        dominant = max(set(severities), key=severities.count) if severities else "medium"
        parts.append(
            f"The convergence is driven by {vuln_count} "
            f"{dominant.upper()}-severity "
            f"vulnerabilit{'y' if vuln_count == 1 else 'ies'} "
            f"in active code paths."
        )

    if "stability" in cat_names:
        fm_count = sum(len(b["failure_modes"]) for b in briefs)
        connector = "Combined with" if "security" in cat_names else "Driven by"
        parts.append(
            f"{connector} {fm_count} known failure "
            f"mode{'s' if fm_count != 1 else ''} "
            f"that can cause system instability."
        )

    if "performance" in cat_names and "security" not in cat_names and "stability" not in cat_names:
        parts.append("Performance profiling shows measurable optimization opportunity.")

    # Closing: blast radius
    dep_count = sum(len(b["prerequisites"]["depended_on_by"]) for b in briefs)
    if dep_count > 0:
        dep_names = [d["name"] for b in briefs for d in b["prerequisites"]["depended_on_by"]]
        shown = dep_names[:4]
        suffix = f"{'...' if len(dep_names) > 4 else ''}"
        parts.append(
            f"{dep_count} component{'s' if dep_count != 1 else ''} "
            f"depend{'s' if dep_count == 1 else ''} on "
            f"{concept_names[0]}: {', '.join(shown)}{suffix}. "
            f"A fix here would resolve exposure across all of them."
        )

    # Frontier score context
    if briefs:
        frontier = briefs[0]["scores"]["frontier"]
        pain = briefs[0]["scores"]["pain"]
        heat = briefs[0]["scores"]["heat"]
        dominant_score = "pain" if pain > heat else "heat"
        parts.append(
            f"Frontier score: {frontier:.1f} "
            f"(heat={heat:.1f}, pain={pain:.1f}). "
            f"{'Pain dominates' if dominant_score == 'pain' else 'Activity dominates'} "
            f"the frontier score."
        )

    return " ".join(parts)
```


#### Task 1.2: Write tests for classify_motivations() — `tests/test_graph_briefing.py`

Add to the EXISTING test file `tests/test_graph_briefing.py` (which already
has tests for `build_concept_brief()`).

**Tests to add (14 tests):**

| Test name | What it verifies |
|-----------|-----------------|
| `test_classify_security_triggered` | Concept with 1+ vulnerabilities → security category present |
| `test_classify_security_not_triggered` | Concept with 0 vulnerabilities → security absent |
| `test_classify_security_headline_has_count` | Headline contains vulnerability count |
| `test_classify_stability_from_failure_modes` | Concept with failure modes → stability present |
| `test_classify_stability_from_critical_problems` | Concept with critical problem → stability present |
| `test_classify_stability_not_triggered` | No failure modes, no critical problems → stability absent |
| `test_classify_performance_from_profiles` | Concept with performance profile → performance present |
| `test_classify_performance_from_observation_keyword` | Observation with "latency" → performance present |
| `test_classify_scalability_from_keyword` | Problem with "NUMA" → scalability present |
| `test_classify_scalability_not_triggered` | No scaling keywords → scalability absent |
| `test_classify_hardware_from_subsystem_heuristic` | Virtualization subsystem + heat > pain → hardware present |
| `test_classify_maintainability_from_regression_fix` | Fix with type "regression-fix" → maintainability present |
| `test_classify_maintainability_from_high_churn` | 3+ fixes → maintainability present |
| `test_classify_returns_only_triggered` | Empty brief → at least 0 categories, all valid |

**Tests for build_argument_paragraph() (4 tests):**

| Test name | What it verifies |
|-----------|-----------------|
| `test_argument_paragraph_returns_string` | Returns a non-empty string |
| `test_argument_paragraph_mentions_source_count` | String contains source count |
| `test_argument_paragraph_mentions_dependencies` | String contains dependent names |
| `test_argument_paragraph_deterministic` | Same inputs → same output |


### Stage 2: Rewrite idea_detail template

#### Task 2.1: Modify `idea_detail()` route in `src/web/routes.py`

In the existing `idea_detail()` function (lines 564-645), add after the
`high_vulns` computation (line 616) and before `related_ideas` (line 618):

```python
        # Classify motivations and build argument
        from graph.briefing import classify_motivations, build_argument_paragraph
        all_motivations = []
        for brief in briefs:
            all_motivations.extend(classify_motivations(brief))
        # Deduplicate categories (if multiple concepts trigger same category, merge)
        seen_categories = set()
        merged_motivations = []
        for m in all_motivations:
            if m["category"] not in seen_categories:
                seen_categories.add(m["category"])
                merged_motivations.append(m)
            else:
                # Merge evidence into existing entry
                for existing in merged_motivations:
                    if existing["category"] == m["category"]:
                        existing["evidence"].extend(m["evidence"])
                        break

        argument = build_argument_paragraph(
            node.get("attrs") or {},
            briefs,
            merged_motivations,
        )
```

Add to the template context dict (line 634-644):
```python
            {
                "node": node,
                "briefs": briefs,
                "motivations": merged_motivations,  # NEW
                "argument": argument,                # NEW
                "all_evidence": all_evidence,
                "total_vulns": total_vulns,
                "total_problems": total_problems,
                "total_dependents": total_dependents,
                "critical_vulns": critical_vulns,
                "high_vulns": high_vulns,
                "related_ideas": related_ideas,
            },
```

Also add `classify_motivations` and `build_argument_paragraph` to the import
from `graph.briefing` at the top of the file (line 25 area, where
`build_concept_brief` is already imported).


#### Task 2.2: Rewrite `src/web/templates/idea_detail.html`

Replace the entire 239-line template with the new argument-driven structure.

**New template structure (in order):**

```html
{% extends "base.html" %}
{% block content %}

{# --- HEADER --- #}
<p><a href="/ideas">&larr; Back to Idea Feed</a></p>
<h1>{{ node.attrs.title }}</h1>
<span class="badge" style="...">{{ node.kind }}</span>
{% if node.attrs.frontier_score %}
  Frontier: <strong>{{ "%.1f"|format(node.attrs.frontier_score) }}</strong>
{% endif %}
{% if briefs and briefs[0].subsystem %}
  <span class="badge badge-kind">{{ briefs[0].subsystem.name }}</span>
{% endif %}

{% if node.attrs.description %}
<p>{{ node.attrs.description }}</p>
{% endif %}

{# --- WHY PURSUE THIS (motivation categories) --- #}
{% if motivations %}
<div class="attrs-section">
  <h2>Why Pursue This</h2>
  {% for m in motivations %}
  <div style="margin-bottom:1em; padding:0.8em; border-left:3px solid
    {% if m.category == 'security' %}#c0392b
    {% elif m.category == 'stability' %}#e67e22
    {% elif m.category == 'performance' %}#2980b9
    {% elif m.category == 'scalability' %}#8e44ad
    {% elif m.category == 'efficiency' %}#27ae60
    {% elif m.category == 'hardware_enablement' %}#2c3e50
    {% elif m.category == 'maintainability' %}#7f8c8d
    {% endif %};">
    <strong>{{ m.icon }} {{ m.label }}</strong>
    <p style="margin:0.3em 0;">{{ m.headline }}</p>
    {% for ev in m.evidence[:3] %}
      <div style="margin-left:1em; font-size:0.9em; color:#555;">
        {% if ev.type == 'vulnerability' %}
          <span class="badge" style="...">{{ ev.severity }}</span>
          {{ ev.text }}
        {% elif ev.type == 'failure_mode' %}
          "{{ ev.text }}" (blast radius: {{ ev.blast_radius }})
        {% elif ev.type == 'profile' %}
          {{ ev.text }}
        {% else %}
          "{{ ev.text }}"
        {% endif %}
      </div>
    {% endfor %}
    {% if m.evidence|length > 3 %}
      <small style="margin-left:1em;">...and {{ m.evidence|length - 3 }} more</small>
    {% endif %}
  </div>
  {% endfor %}
</div>
{% endif %}

{# --- THE CASE (argument paragraph) --- #}
{% if argument %}
<div class="attrs-section">
  <h2>The Case</h2>
  <p>{{ argument }}</p>
</div>
{% endif %}

{# --- SCORES (compact) --- #}
{# same as current section 3, unchanged #}

{# --- EVIDENCE TIMELINE (verbatim, all items) --- #}
{# same as current section 4, unchanged #}

{# --- STRUCTURAL DETAIL (below the fold) --- #}
{# Merge current sections 7 (constraints), 8 (dependencies),
   9 (performance), 10 (code examples) into a collapsible section.
   Use HTML <details> element. #}
{% if briefs %}
<details>
  <summary><h2 style="display:inline;">Structural Detail</h2></summary>
  {# invariants, failure modes, protocols, dependencies,
     performance profiles, code examples — same rendering as current #}
</details>
{% endif %}

{# --- RELATED IDEAS --- #}
{# same as current section 11, unchanged #}

{% endblock %}
```

**Key changes from current template:**
1. Remove sections 5 (Active Vulnerabilities) and 6 (Open Problems) as
   standalone sections — their data is now integrated into the SECURITY and
   STABILITY motivation categories
2. Add "Why Pursue This" section with motivation cards
3. Add "The Case" section with argument paragraph
4. Wrap structural detail in `<details>` element (collapsible)
5. Remove "Why This Matters" section (replaced by motivations)


#### Task 2.3: Add idea_detail route tests

Add to `tests/test_web.py`:

| Test name | What it verifies |
|-----------|-----------------|
| `test_idea_detail_shows_motivations` | Response HTML contains "Why Pursue This" heading |
| `test_idea_detail_shows_security_motivation` | When concept has vulns, response contains "SECURITY" |
| `test_idea_detail_shows_argument` | Response contains "The Case" heading |
| `test_idea_detail_no_empty_motivations` | When no data, motivation section is absent |


#### Task 2.4: Spec mutations for Stage 2

- `modify-node` ALG-KK-WEB-IDEAS-DETAIL (new description)
- `modify-node` INV-KK-WEB-IDEAS-EVIDENCE-CHAIN (new predicate)
- `add-node` INV-KK-WEB-IDEA-MOTIVATIONS + 3 edges
- `add-node` INV-KK-WEB-IDEA-ARGUMENT + 3 edges

Total: 2 modify-node + 2 add-node + 6 add-edge = 10 mutations


### Stage 3: Apply motivation categories to vuln_detail

#### Task 3.1: Modify `vuln_detail()` route in `src/web/routes.py`

The vuln_detail page already has full concept briefs for direct concepts.
Add motivation classification for each direct brief:

After the `direct_briefs` list is built (around line 810), add:

```python
        # Classify motivations per directly exploited concept
        for brief in direct_briefs:
            brief["motivations"] = classify_motivations(brief)
```

Add to template context.

#### Task 3.2: Update `src/web/templates/vuln_detail.html`

In the "Directly Exploited Concepts" section (current lines 37-121), add
a motivation summary before the structural sub-sections:

After the concept description (line 47) and before "Invariants at Risk"
(line 49), insert:

```html
    {% if brief.motivations %}
    <div style="margin:0.5em 0;">
      {% for m in brief.motivations %}
        {% if m.category != 'security' %}{# security is obvious on a vuln page #}
        <span style="margin-right:0.5em;">{{ m.icon }} <strong>{{ m.label }}</strong>: {{ m.headline }}</span>
        {% endif %}
      {% endfor %}
    </div>
    {% endif %}
```

This shows stability/performance/scalability/etc. motivations for each
exploited concept WITHOUT duplicating the security information (which is
already the context of the entire page).

#### Task 3.3: Add vuln_detail tests

| Test name | What it verifies |
|-----------|-----------------|
| `test_vuln_detail_shows_concept_motivations` | Exploited concept shows non-security motivations |
| `test_vuln_detail_omits_security_motivation` | Security motivation not shown (redundant on vuln page) |

#### Task 3.4: Spec mutations for Stage 3

- `modify-node` ALG-KK-WEB-VULNS-DETAIL (add motivation classification)

Total: 1 modify-node

---

## Files Modified Per Stage

### Stage 1 (classify_motivations + build_argument_paragraph)
| File | Action | Lines affected |
|------|--------|---------------|
| `src/graph/briefing.py` | Add ~250 lines (constants + 3 functions) | After line 365 |
| `tests/test_graph_briefing.py` | Add ~18 tests | After existing tests |

### Stage 2 (idea_detail template rewrite)
| File | Action | Lines affected |
|------|--------|---------------|
| `src/web/routes.py` | Modify idea_detail() — add ~15 lines for motivation/argument computation + 2 context vars | Lines 606-644 |
| `src/web/templates/idea_detail.html` | Full rewrite — restructure from data-dump to argument-driven | All 239 lines |
| `tests/test_web.py` | Add ~4 tests | After existing tests |

### Stage 3 (vuln_detail motivation integration)
| File | Action | Lines affected |
|------|--------|---------------|
| `src/web/routes.py` | Add ~2 lines to vuln_detail() | After line 810 |
| `src/web/templates/vuln_detail.html` | Add ~10 lines in concept section | After line 47 |
| `tests/test_web.py` | Add ~2 tests | After existing tests |

### Files NOT modified
| File | Why |
|------|-----|
| `src/graph/briefing.py` build_concept_brief() | Already works, returns all needed data |
| `src/graph/scoring.py` | All scoring functions unchanged |
| `src/graph/engine.py` | All graph queries unchanged |
| `src/graph/schema.py` | No schema changes |
| `src/web/templates/ideas.html` | List page unchanged (confirmed good) |
| `src/web/templates/vulns.html` | List page unchanged (confirmed good) |
| `src/mcp_server/server.py` | MCP tools unchanged |

---

## Implementation Commands

Stage 1:
```
/cb-green — Motivation Categories: classify_motivations() and build_argument_paragraph()

Add to src/graph/briefing.py (after line 365): keyword constants (_PERFORMANCE_KEYWORDS,
_SCALABILITY_KEYWORDS, _EFFICIENCY_KEYWORDS, _HARDWARE_KEYWORDS, _HARDWARE_SUBSYSTEMS,
_MOTIVATION_ICONS, _MOTIVATION_LABELS), helper _text_has_keywords(), main function
classify_motivations(brief) -> list[dict] that detects 7 orthogonal categories
(security, stability, performance, scalability, efficiency, hardware_enablement,
maintainability) from brief data, and build_argument_paragraph() that composes a
deterministic narrative from motivations + graph data counts. Add 18 tests to
tests/test_graph_briefing.py. See docs/plans/motivation-categories-and-idea-narrative.md
Task 1.1 and 1.2 for exact function signatures, detection logic, keyword lists, and
test definitions.
```

Stage 2:
```
/cb-green — Idea Detail Rewrite: argument-driven research brief with motivation categories

Modify idea_detail() route in src/web/routes.py to call classify_motivations() per
brief and build_argument_paragraph(), passing motivations + argument to template.
Rewrite src/web/templates/idea_detail.html from 239-line data dump to argument-driven
brief: "Why Pursue This" (triggered motivation categories with verbatim evidence),
"The Case" (templated argument paragraph), scores, evidence timeline, structural
detail in collapsible <details>. Remove standalone Active Vulnerabilities and Open
Problems sections (data now in motivation cards). Add 4 route tests. Spec mutations:
modify ALG-KK-WEB-IDEAS-DETAIL and INV-KK-WEB-IDEAS-EVIDENCE-CHAIN, add
INV-KK-WEB-IDEA-MOTIVATIONS and INV-KK-WEB-IDEA-ARGUMENT. See
docs/plans/motivation-categories-and-idea-narrative.md Tasks 2.1-2.4.
```

Stage 3:
```
/cb-green — Vuln Detail: add motivation categories to exploited concept briefs

Modify vuln_detail() route to call classify_motivations() per direct_brief. Update
vuln_detail.html to show non-security motivations (stability, performance, etc.) for
each exploited concept. Omit security category (redundant on vuln page). Add 2 tests.
Spec mutation: modify ALG-KK-WEB-VULNS-DETAIL. See
docs/plans/motivation-categories-and-idea-narrative.md Tasks 3.1-3.4.
```
