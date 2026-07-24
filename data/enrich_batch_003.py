"""Deep enrichment batch 003: 9 papers with full ResearchBrief + structured claims.

Papers:
1. KCOV Data-Flow — Per-task data-flow extraction at kernel function boundaries via LLVM
2. Fairness LLM Scheduling — Aging-based scheduling inspired by CFS vruntime for LLM serving
3. Multi-NUMA VM Allocation — Closed-form expressions for multi-NUMA VM placement
4. WIO — Upload-enabled computational storage on CXL SSDs with migratable actors
5. PREEMPT_RT Pi5 — Scheduling analysis of UAV control on PREEMPT_RT Linux
6. eBPF SSE Leakage — System-level leakage in encrypted search via eBPF monitoring
7. Space-Control — Process-level isolation for CXL disaggregated memory
8. Pichay — Demand paging for LLM context windows (VM concepts applied to LLM)
9. CXLRAMSim — gem5-integrated full-system CXL simulator with unmodified Linux kernel
"""
import json, sqlite3, uuid

DB_PATH = "data/master.db"

ALL_PAPERS = [
    # ── 1. KCOV Data-Flow Extraction ─────────────────────────────────
    # Extends Linux KCOV with data-flow extraction of function arguments and
    # return values. LLVM compiler pass emits callbacks capturing structured
    # tuples at function entry/return. Lock-free per-task ring buffer.
    # Dual utility: fuzzer feedback + security analysis.
    {
        "ev_id": "ev-arxiv-93065f49",
        "brief": {
            "key_ideas": [
                "Extends Linux KCOV beyond edge coverage with data-flow extraction — captures function arguments and return values at kernel function entry/return points, enabling value-aware fuzzing feedback",
                "LLVM compiler pass emits lightweight callbacks capturing structured tuples of program counter, argument metadata, and field values — composite types automatically decomposed via DWARF DICompositeType metadata with zero source annotation",
                "Lock-free per-task ring buffer delivers records to userspace without interfering with existing KCOV or syzkaller infrastructure — the extension is additive, not disruptive",
                "Dual utility: (1) fuzzers gain state-aware feedback for mutation guidance into value-dependent state transitions, (2) security analysts get deterministic argument records without printk or kprobe overhead. Includes Rust instrumentation paths for Rust-in-kernel code"
            ],
            "relevance": "Directly extends the Linux kernel's KCOV infrastructure — the primary fuzzing feedback mechanism used by syzkaller and other kernel fuzzers. The insight that edge coverage is context-blind (two copy_from_user() calls with different sizes hit the same basic blocks) exposes a fundamental limitation in kernel fuzz testing. The LLVM pass approach means this integrates into the kernel's existing build system. The Rust instrumentation paths are significant given Rust's growing presence in the kernel — this is the only runtime method for capturing Rust function arguments under -O2 DWARF elision.",
            "methodology": "LLVM compiler pass extending KCOV. Lock-free per-task ring buffer. DWARF-based composite type decomposition. Dual Rust instrumentation paths (post-compilation and native rustc)."
        },
        "concepts": ["Ftrace", "Perf Events Subsystem"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "Edge coverage is context-blind for kernel fuzzing",
             "description": "Coverage-guided kernel fuzzers like syzkaller use edge coverage (trace-pc) as their sole feedback signal. This cannot distinguish execution paths that differ only in argument values — two copy_from_user() calls with different size parameters hit identical basic blocks but have vastly different security implications."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "LLVM-based KCOV extension with data-flow extraction",
             "description": "An LLVM compiler pass extends Linux KCOV with function argument and return value capture at entry/return points. Composite types are decomposed via DWARF metadata. A lock-free per-task ring buffer delivers records to userspace compatible with existing syzkaller infrastructure."},
            {"kind": "Observation", "id_prefix": "obs", "name": "Rust kernel function arguments unobservable under -O2",
             "description": "Standard debugging tools (drgn, vmcore) fail to capture Rust function arguments under -O2 optimization due to DWARF elision. The LLVM instrumentation pass is the only runtime method for capturing Rust-in-kernel function arguments."}
        ]
    },

    # ── 2. Fairness-Aware LLM Scheduling ─────────────────────────────
    # Aging-based scheduling policy for chunked-prefill LLM serving. Directly
    # inspired by CFS vruntime — uses accumulated waiting time for priority.
    # LPRS and APC replace static token budgets with target-time constraints.
    {
        "ev_id": "ev-arxiv-d849e03f",
        "brief": {
            "key_ideas": [
                "Designs a lightweight aging-based scheduling policy for chunked-prefill LLM serving that dynamically calculates priorities using accumulated waiting time and remaining prefill work — directly analogous to CFS's virtual runtime tracking",
                "Replaces FCFS scheduling with fairness-aware priority that prevents head-of-line blocking and request starvation in heterogeneous LLM workloads",
                "Latency-Prediction-Based Request Scheduling (LPRS) replaces static token budgets with target-time constraints — adapts scheduling decisions to actual latency predictions rather than fixed quotas",
                "Active Prefill Control (APC) actively regulates prefill concurrency rather than passively accepting all prefill requests, confirming that structural prefill control and temporal latency constraints are fundamentally complementary"
            ],
            "relevance": "The aging-based priority scheduling is a direct application of the CFS virtual runtime concept to LLM serving. The paper demonstrates that kernel scheduling principles (fair queuing, aging to prevent starvation, work-conserving disciplines) transfer directly to accelerator workload scheduling. The LPRS mechanism mirrors CFS's approach of using per-task runtime tracking to make scheduling decisions. This validates that the kernel's scheduling theory is general enough for emerging workloads — and suggests that sched_ext or BPF-based scheduling could implement similar policies in-kernel for GPU scheduling.",
            "methodology": "Scheduling framework design with aging-based priority, LPRS, and APC. Evaluation on NVIDIA GPUs and Ascend accelerators with real-world LLM workloads. Comparison against FCFS baseline."
        },
        "concepts": ["Virtual Runtime Scheduling", "Scheduling Classes"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "FCFS causes starvation in chunked-prefill LLM serving",
             "description": "Chunked-prefill LLM engines use rigid FCFS scheduling with static token budgets, causing severe head-of-line blocking and request starvation under heterogeneous workloads with varying prefill sizes."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "CFS-inspired aging scheduler for LLM inference",
             "description": "Aging-based scheduling policy dynamically calculates request priorities using accumulated waiting time and remaining prefill work, analogous to CFS virtual runtime. Combined with LPRS (latency-prediction scheduling) and APC (active prefill control)."},
            {"kind": "PerformanceProfile", "id_prefix": "perf", "name": "Fairness scheduling reduces LLM latency 10%+",
             "description": "Aging policy reduces mean end-to-end latency by over 10% compared to FCFS. LPRS and APC significantly reduce P99 tail latency and suppress prefill fragmentation."}
        ]
    },

    # ── 3. Multi-NUMA VM Allocation ──────────────────────────────────
    # Closed-form expressions for maximum VM allocation on multi-NUMA servers.
    # Maps virtual NUMA topology to physical NUMA topology while minimizing
    # interference. Covers 2/4-NUMA VMs on 4/8-NUMA physical servers.
    {
        "ev_id": "ev-arxiv-2fcd753e",
        "brief": {
            "key_ideas": [
                "Derives closed-form expressions for the maximum number of multi-NUMA VMs allocatable on a physical server — solving a combinatorial optimization problem that cloud schedulers currently use heuristics for",
                "Maps virtual NUMA topology onto physical NUMA topology while minimizing interference with co-located VMs — considers 2- and 4-NUMA symmetric VMs on 4- and 8-NUMA physical topologies",
                "Results applicable to real-time capacity dashboards (available cluster capacity per VM flavor) and optimization tools for large-scale cloud resource reorganization",
                "Addresses the fundamental complexity that multi-NUMA VMs introduce to scheduling: beyond host selection, the scheduler must solve NUMA-to-NUMA mapping"
            ],
            "relevance": "Directly relevant to the kernel's NUMA topology management and KVM's NUMA-aware VM placement. When KVM creates a multi-NUMA VM, the kernel must map vNUMA nodes to pNUMA nodes — this paper provides the mathematical foundation for optimal placement. The closed-form expressions could be used by kernel-level NUMA balancing (AutoNUMA) or by the KVM vCPU placement logic to avoid cross-NUMA memory access penalties. Also relevant to cgroup NUMA memory policies that constrain VMs to specific NUMA nodes.",
            "methodology": "Combinatorial analysis with closed-form derivations. Mathematical modeling of NUMA topology constraints for 2/4-NUMA VMs on 4/8-NUMA physical servers."
        },
        "concepts": ["NUMA Topology and Memory Policy", "KVM (Kernel-based Virtual Machine)"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "Multi-NUMA VM scheduling is combinatorial",
             "description": "Multi-NUMA VMs require mapping virtual NUMA topology onto physical NUMA topology while minimizing interference with co-located VMs. Maximizing allocation under these constraints is a combinatorial optimization problem that current schedulers solve with heuristics."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Closed-form expressions for multi-NUMA VM capacity",
             "description": "Derived closed-form expressions compute the maximum number of 2- and 4-NUMA symmetric VMs allocatable on 4- and 8-NUMA physical servers, enabling exact capacity computation instead of heuristic-based estimation."}
        ]
    },

    # ── 4. WIO: Computational Storage on CXL SSDs ───────────────────
    # Migratable storage actors compiled to WebAssembly on CXL SSDs.
    # Actors share state through coherent CXL.mem regions. Agility-aware
    # scheduler migrates actors between host and device. Turns thermal
    # cliffs into elastic tradeoffs. 2x throughput, 3.75x write latency.
    {
        "ev_id": "ev-arxiv-3fdc3f5c",
        "brief": {
            "key_ideas": [
                "Argues storage-side compute should be reversible — computation migrates dynamically between host and device based on runtime thermal/power conditions, rather than being statically placed on the device",
                "Decomposes I/O-path logic into migratable 'storage actors' compiled to WebAssembly — actors run on CXL SSDs but can migrate to the host when device thermal/power constraints arise",
                "Actors share state through coherent CXL.mem regions — the CXL cache coherence protocol ensures consistency during migration without application-visible state transfer",
                "Agility-aware scheduler uses a zero-copy drain-and-switch protocol to migrate actors, turning hard thermal cliffs into elastic tradeoffs. 2x throughput improvement and 3.75x write latency reduction on FPGA-based CXL SSD prototype"
            ],
            "relevance": "Proposes a new computational storage model built on CXL that directly interacts with the kernel's block I/O and CXL device driver infrastructure. The migratable actor model requires kernel support for CXL.mem coherent regions shared between host CPU and CXL SSD controller — this pushes the kernel's CXL driver beyond simple memory expansion into compute-near-storage territory. The thermal-aware migration scheduler maps to kernel thermal management (thermal zones, cooling devices). The WebAssembly runtime on the CXL device is analogous to eBPF in the kernel — a safe execution environment for user-defined storage logic.",
            "methodology": "System design with WebAssembly-based storage actors on CXL SSDs. FPGA-based CXL SSD prototype evaluation. Comparison against production CSDs. Thermal/power constraint handling."
        },
        "concepts": ["Adaptive CXL Memory Tiering", "NVMe Driver Subsystem", "Thermal Management Framework"],
        "claims": [
            {"kind": "Observation", "id_prefix": "obs", "name": "Computational storage fails under sustained thermal load",
             "description": "Neither persistent memory nor computational storage devices have displaced conventional NVMe SSDs at scale, largely due to programming complexity, ecosystem fragmentation, and thermal/power cliffs under sustained compute load on the device."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Reversible computation with CXL-based migratable storage actors",
             "description": "WIO decomposes I/O-path logic into WebAssembly-compiled actors that share state through CXL.mem coherent regions. An agility-aware scheduler migrates actors between host and CXL SSD via zero-copy drain-and-switch when thermal/power constraints arise."},
            {"kind": "PerformanceProfile", "id_prefix": "perf", "name": "WIO CXL SSD throughput and latency improvement",
             "description": "Up to 2x throughput improvement and 3.75x write latency reduction versus conventional CSD approaches, by turning hard thermal cliffs into elastic host-device compute migration tradeoffs."}
        ]
    },

    # ── 5. PREEMPT_RT on Raspberry Pi 5 ──────────────────────────────
    # NOTE: This paper was wrongly linked as "DPC: Distributed Page Cache"
    # but is actually about PREEMPT_RT Linux scheduling analysis for UAV
    # flight control on Raspberry Pi 5 (ARM Cortex-A76).
    {
        "ev_id": "ev-arxiv-87a3f4dc",
        "brief": {
            "key_ideas": [
                "Performs architectural analysis of PREEMPT_RT Linux kernel on Raspberry Pi 5 (ARM Cortex-A76 quad-core) for 250 Hz UAV flight control loops — directly measuring the impact of kernel preemption paths on real-time latency",
                "Isolates the impact of kernel activation paths: deferred execution (SoftIRQs) versus real-time direct activation — shows that the standard kernel is unsuitable with worst-case latencies exceeding 9ms",
                "PREEMPT_RT reduces worst-case latency by 88% to under 225 microseconds by enforcing direct wake-up paths that mitigate OS noise from SoftIRQ deferral",
                "Key finding: residual jitter on modern multi-core SoCs is primarily driven by hardware memory contention, not OS scheduling variance — PREEMPT_RT solves the software problem but exposes the hardware one"
            ],
            "relevance": "Directly evaluates the Linux kernel's PREEMPT_RT patch set — the primary mechanism for achieving real-time guarantees in mainline Linux. The SoftIRQ vs direct activation comparison reveals how the kernel's interrupt processing architecture affects worst-case latency. The finding that hardware memory contention dominates residual jitter after PREEMPT_RT is applied has implications for kernel cache partitioning (CAT/MBA on Intel, MPAM on ARM) and NUMA-aware interrupt routing. This is practical data for anyone deploying Linux in real-time control systems.",
            "methodology": "Measurement study on Raspberry Pi 5 with PREEMPT_RT kernel. 250 Hz control loop under heavy stress conditions. Worst-case latency analysis comparing standard kernel vs PREEMPT_RT. SoftIRQ vs direct activation path isolation."
        },
        "concepts": ["Scheduling Classes", "Interrupt Handling"],
        "claims": [
            {"kind": "Observation", "id_prefix": "obs", "name": "Standard Linux kernel unsuitable for 250Hz control at 9ms+ latency",
             "description": "Under heavy stress on Raspberry Pi 5, the standard Linux kernel exhibits worst-case latencies exceeding 9ms for a 250 Hz control loop — well beyond the 4ms deadline. SoftIRQ deferred execution is the primary source of scheduling variance."},
            {"kind": "PerformanceProfile", "id_prefix": "perf", "name": "PREEMPT_RT achieves 88% latency reduction on Pi 5",
             "description": "PREEMPT_RT reduces worst-case latency by 88% to under 225 microseconds by enforcing direct wake-up paths instead of deferred SoftIRQ execution."},
            {"kind": "Observation", "id_prefix": "obs", "name": "Hardware memory contention dominates residual RT jitter",
             "description": "After PREEMPT_RT resolves scheduling variance, residual jitter on modern multi-core SoCs is primarily driven by shared hardware memory contention, not OS scheduling — the software problem is solved but the hardware contention floor remains."}
        ]
    },

    # ── 6. eBPF SSE Leakage ──────────────────────────────────────────
    # eBPF monitoring reveals system-level leakage in Searchable Symmetric
    # Encryption deployments. Low-level system behavior during search
    # operations leaks query and document access patterns.
    {
        "ev_id": "ev-arxiv-981d4483",
        "brief": {
            "key_ideas": [
                "Demonstrates that eBPF system-level monitoring can uncover leakage patterns in Searchable Symmetric Encryption (SSE) that go beyond what SSE threat models capture — observing low-level system behavior during encrypted search operations",
                "By monitoring kernel-level events (syscalls, I/O patterns, scheduling) with eBPF, an attacker gains insights into query behavior, document access, and processing flow even when data is encrypted",
                "Defines a new leakage pattern based on system-level observations and shows how it strengthens existing SSE attacks",
                "Bridges the gap between theoretical SSE security (which assumes an idealized execution environment) and the reality of system-level side channels in production deployments"
            ],
            "relevance": "Demonstrates eBPF as an offensive tool — using the kernel's own observability infrastructure to break encrypted computation's security guarantees. This is relevant to kernel security design: any computation running on Linux leaks information through observable kernel behaviors (scheduling decisions, I/O patterns, memory access patterns) that eBPF can capture. This has implications for the kernel's isolation mechanisms — TEE integration, memory encryption, and I/O path isolation all need to consider eBPF-observable side channels.",
            "methodology": "eBPF-based system monitoring of SSE operations. New leakage pattern definition. Integration with existing leakage abuse attacks. Gap analysis between theoretical SSE security and system-level exposure."
        },
        "concepts": ["eBPF (Extended Berkeley Packet Filter)"],
        "claims": [
            {"kind": "FailureMode", "id_prefix": "fail", "name": "eBPF exposes SSE leakage beyond threat model",
             "description": "System-level monitoring using eBPF reveals leakage patterns in Searchable Symmetric Encryption that go beyond the theoretical SSE threat model — query behavior, document access patterns, and processing flow are observable through kernel-level events."},
            {"kind": "Observation", "id_prefix": "obs", "name": "System-level side channels practical threat to encrypted computation",
             "description": "The gap between theoretical SSE security (idealized execution) and production deployments (observable kernel behaviors) is a practical threat. eBPF monitoring can strengthen existing leakage abuse attacks by providing system-level signal."}
        ]
    },

    # ── 7. Space-Control: CXL Process-Level Isolation ────────────────
    # Hardware-rooted process-level isolation for CXL shared memory.
    # Cross-host identity primitive. SPACE validation engine for immutable
    # process identity. Permission Checker at memory egress point.
    # 127 processes across 255 hosts, 1.56% storage overhead, 3.3% perf.
    {
        "ev_id": "ev-arxiv-7ee39e61",
        "brief": {
            "key_ideas": [
                "Identifies a critical security gap in CXL memory disaggregation: virtual memory provides process-level isolation on a host, CXL provides host-level isolation, but there is no process-level isolation across CXL-shared memory",
                "Introduces a cross-host identity primitive that decouples authorization from the untrusted OS using SPACE — a hardware-rooted validation engine that establishes immutable process identity",
                "Permission Checker at the CXL memory egress point performs fine-grained validation on every access — the enforcement happens in hardware at the memory controller, not in software",
                "Scales to 127 concurrent processes across 255 hosts with 1.56% storage overhead and 3.3% performance penalty with a 16 KiB cache"
            ],
            "relevance": "Directly addresses a fundamental gap in the kernel's CXL security model. Today the kernel trusts host-level CXL isolation but has no mechanism to enforce process-level access control on CXL-shared memory regions. Space-Control shows this requires hardware support — the kernel's virtual memory page tables only protect local memory, not CXL-attached shared memory. The 'immutable process identity' decoupled from the OS has implications for kernel security: if the OS is compromised, CXL memory permissions should still hold. This is analogous to how IOMMU protects DMA from kernel bugs.",
            "methodology": "Architectural design with hardware-rooted validation. Cycle-level evaluation using gem5 + SST. Scalability analysis for process and host counts."
        },
        "concepts": ["Adaptive CXL Memory Tiering", "NUMA Topology and Memory Policy"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "No process-level isolation for CXL shared memory",
             "description": "Virtual memory provides process-level isolation within a host. CXL provides host-level isolation. But there is no mechanism for process-level memory isolation across CXL-shared disaggregated memory — any process on an authorized host can access all shared CXL memory."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Hardware-rooted cross-host process identity for CXL",
             "description": "Space-Control introduces SPACE (hardware validation engine) for immutable process identity decoupled from the OS, and a Permission Checker at the CXL memory egress point for fine-grained per-access validation."},
            {"kind": "PerformanceProfile", "id_prefix": "perf", "name": "Space-Control scales to 127 processes x 255 hosts",
             "description": "Supports 127 concurrent processes across 255 hosts with 1.56% storage overhead. 3.3% performance penalty with a 16 KiB permission cache."}
        ]
    },

    # ── 8. Pichay: Demand Paging for LLM Context Windows ────────────
    # Brilliant analogy: LLM context window = L1 cache. Applies VM concepts
    # (demand paging, working set theory, fault-driven replacement) to LLM
    # context management. 93% context reduction. 0.0254% fault rate.
    {
        "ev_id": "ev-arxiv-d23bec08",
        "brief": {
            "key_ideas": [
                "Reframes LLM context window management as a virtual memory problem: the context window is L1 cache (small, fast, expensive), and there is no L2, no virtual memory, no paging — every tool definition and stale result occupies context for the session lifetime",
                "Quantifies the waste: across 857 production sessions and 4.45 million input tokens, 21.8% is structural waste from stale content that should have been evicted",
                "Implements Pichay, a demand paging system for LLM context: evicts stale content, detects page faults when the model re-requests evicted material, and pins working-set pages identified by fault history — directly applying Denning's working set theory (1968)",
                "In production deployment: reduces context consumption by up to 93% (5,038KB to 339KB) with a 0.0254% fault rate across 1.4 million simulated evictions. Describes a full memory hierarchy (L1 through persistent storage) for LLM systems"
            ],
            "relevance": "The deepest application of kernel virtual memory concepts to a non-kernel domain. Every mechanism maps directly: eviction = page reclaim, fault = page fault handler, pinning = mlock, working set = RSS tracking, thrashing = when eviction rate exceeds useful work. This validates that the kernel's 60-year-old virtual memory abstractions (Denning 1968) are fundamental enough to solve modern AI infrastructure problems. For the kernel community, this paper is a mirror — it shows what happens when a system lacks VM, and the solutions look exactly like what the kernel already does.",
            "methodology": "Production deployment as a transparent proxy between LLM client and inference API. Offline replay across 1.4M simulated evictions. Live deployment over 681 turns. Working set analysis of 857 production sessions."
        },
        "concepts": ["Page Fault Handler", "Page Cache", "Page Reclaim (kswapd/direct)"],
        "claims": [
            {"kind": "Observation", "id_prefix": "obs", "name": "LLM context problems are virtual memory problems",
             "description": "LLM context limits, attention degradation, cost scaling, and lost state across sessions are virtual memory problems wearing different clothes. The context window is L1 cache with no memory hierarchy — 21.8% of tokens in production are structural waste."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Demand paging system for LLM context windows",
             "description": "Pichay implements demand paging for LLM context: content eviction, fault detection when the model re-requests evicted material, and working-set-based pinning. Applies Denning's working set theory directly to LLM serving."},
            {"kind": "PerformanceProfile", "id_prefix": "perf", "name": "Pichay context reduction with minimal faulting",
             "description": "Up to 93% context consumption reduction (5,038KB to 339KB) with 0.0254% fault rate across 1.4 million evictions. Under extreme sustained pressure, exhibits expected thrashing pathology — repeated fault-in of evicted content."}
        ]
    },

    # ── 9. CXLRAMSim ────────────────────────────────────────────────
    # First gem5-integrated CXL full-system simulator that models CXL at
    # correct I/O bus position. Runs unmodified Linux kernel. Captures
    # cache pollution from CXL memory access.
    {
        "ev_id": "ev-arxiv-f6cf13bb",
        "brief": {
            "key_ideas": [
                "First gem5-integrated full-system simulator that models CXL devices at their correct position on the I/O bus — unlike previous tools that use simplified or non-compliant architectural models",
                "Enables running unmodified Linux kernels and the full software stack on simulated CXL hardware — critical for validating kernel CXL drivers and memory management policies",
                "Provides realistic latency-bandwidth behavior and true interleaving with system DRAM — captures phenomena like cache pollution when accessing CXL memory that simplified models miss",
                "High-fidelity CXL.mem characterization enabling computer architects to explore hardware/software co-design for CXL memory expansion"
            ],
            "relevance": "Essential infrastructure for kernel CXL development. Running unmodified Linux kernels means kernel developers can test CXL memory tiering patches (AutoNUMA, DAMON, page migration heuristics) against cycle-accurate CXL hardware models before physical hardware is available. The cache pollution characterization is particularly important — the kernel's page cache and TLB management need to account for CXL access patterns that pollute CPU caches differently than local DRAM. Previous CXL simulators couldn't capture this because they didn't model the I/O bus position correctly.",
            "methodology": "gem5 simulator extension with CXL device models at correct I/O bus position. Full-system simulation supporting unmodified Linux kernel. CXL.mem latency-bandwidth characterization. Cache pollution analysis."
        },
        "concepts": ["Adaptive CXL Memory Tiering", "NUMA Topology and Memory Policy"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "Existing CXL simulators use non-compliant architectural models",
             "description": "Recent CXL simulation tools rely on simplified or non-compliant architectural models — placing CXL devices at incorrect bus positions — impacting accuracy for kernel-level memory management policy evaluation."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "gem5-integrated CXL simulator at correct I/O bus position",
             "description": "CXLRAMSim models CXL devices at their correct I/O bus position in gem5, enabling unmodified Linux kernel execution, realistic latency-bandwidth, true DRAM interleaving, and cache pollution characterization."},
            {"kind": "Observation", "id_prefix": "obs", "name": "CXL memory access causes cache pollution",
             "description": "CXL memory access at its correct I/O bus position exhibits cache pollution effects invisible in simplified models — CXL accesses that traverse the I/O bus pollute CPU caches differently than local DRAM accesses, affecting kernel page cache and TLB management."}
        ]
    },
]


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")

    concepts_map = {}
    for r in conn.execute(
        "SELECT id, json_extract(attrs, '$.name') FROM nodes WHERE kind = 'Concept'"
    ).fetchall():
        if r[1]:
            concepts_map[r[1].lower()] = r[0]

    stats = {"briefs": 0, "claims": 0, "edges": 0}

    for paper in ALL_PAPERS:
        ev_id = paper["ev_id"]
        brief = paper["brief"]

        existing = conn.execute(
            "SELECT 1 FROM nodes rb JOIN edges re ON re.source_id = rb.id "
            "WHERE rb.kind = 'ResearchBrief' AND re.kind = 'extracted-from' AND re.target_id = ?",
            (ev_id,),
        ).fetchone()
        if existing:
            print(f"  SKIP (brief exists): {ev_id}")
            continue

        title_row = conn.execute(
            "SELECT json_extract(s.attrs, '$.title'), json_extract(s.attrs, '$.published_date') "
            "FROM edges se JOIN nodes s ON s.id = se.target_id "
            "WHERE se.kind = 'sourced-from' AND se.source_id = ?",
            (ev_id,),
        ).fetchone()
        title = title_row[0] if title_row else ""
        date = title_row[1] if title_row else "2026-01-01"

        brief_id = f"rb-{uuid.uuid4().hex[:12]}"
        conn.execute(
            "INSERT INTO nodes (id, kind, attrs) VALUES (?, 'ResearchBrief', ?)",
            (
                brief_id,
                json.dumps(
                    {
                        "title": title,
                        "key_ideas": json.dumps(brief["key_ideas"]),
                        "relevance": brief["relevance"],
                        "methodology": brief["methodology"],
                        "source_date": date or "2026-01-01",
                        "artifact_class": "A",
                    }
                ),
            ),
        )
        conn.execute(
            "INSERT INTO edges (kind, source_id, target_id, attrs) VALUES ('extracted-from', ?, ?, '{}')",
            (brief_id, ev_id),
        )
        stats["briefs"] += 1

        for cname in paper["concepts"]:
            cid = concepts_map.get(cname.lower())
            if cid:
                try:
                    conn.execute(
                        "INSERT INTO edges (kind, source_id, target_id, attrs) VALUES ('summarizes-for', ?, ?, '{}')",
                        (brief_id, cid),
                    )
                    stats["edges"] += 1
                except Exception:
                    pass
                try:
                    conn.execute(
                        "INSERT INTO edges (kind, source_id, target_id, attrs) VALUES ('extracted-from', ?, ?, '{}')",
                        (cid, ev_id),
                    )
                    stats["edges"] += 1
                except Exception:
                    pass

        for claim in paper["claims"]:
            claim_id = f"{claim['id_prefix']}-{uuid.uuid4().hex[:12]}"
            conn.execute(
                "INSERT INTO nodes (id, kind, attrs) VALUES (?, ?, ?)",
                (
                    claim_id,
                    claim["kind"],
                    json.dumps(
                        {
                            "name": claim["name"],
                            "description": claim["description"],
                            "source_date": date or "2026-01-01",
                        }
                    ),
                ),
            )
            conn.execute(
                "INSERT INTO edges (kind, source_id, target_id, attrs) VALUES ('extracted-from', ?, ?, '{}')",
                (claim_id, ev_id),
            )
            stats["claims"] += 1
            stats["edges"] += 1

        print(f"  OK: {title}")

    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    total_briefs = conn.execute(
        "SELECT count(*) FROM nodes WHERE kind = 'ResearchBrief'"
    ).fetchone()[0]
    total_claims = conn.execute(
        "SELECT count(*) FROM nodes WHERE kind IN ('Problem','Observation','Proposal','PerformanceProfile','FailureMode','Benchmark')"
    ).fetchone()[0]
    print(
        f"\nCreated {stats['briefs']} briefs, {stats['claims']} claims, {stats['edges']} edges"
    )
    print(f"Totals: {total_briefs} briefs, {total_claims} claims in DB")
    conn.close()


if __name__ == "__main__":
    main()
