"""Deep enrichment batch 007: 8 papers — RowHammer trilogy, CXL, containers, kernel governance.

Papers:
1. TinyContainer — Container runtime for multi-tenant microcontrollers
2. FAULT+PROBE — RowHammer as a probing attack for secret bit recovery
3. LeakyHammer — Timing covert/side channels from RowHammer defenses
4. BreakHammer — Throttling RowHammer-triggering threads at OS level
5. Cohet — CXL-driven coherent heterogeneous computing framework
6. CXL-Aware LLM Fine-Tuning — Tensor-level NUMA control for CXL memory
7. PrISM — Probabilistic RowHammer defense with intersection sampling
8. Governed MCP — Kernel-resident tool governance for AI agents (Rust OS)
"""
import json, sqlite3, uuid

DB_PATH = "data/master.db"

ALL_PAPERS = [
    # ── 1. TinyContainer ────────────────────────────────────────────
    {
        "ev_id": "ev-arxiv-tinycontainer-multi-tenant-microcontroll",
        "brief": {
            "key_ideas": [
                "Lightweight container management middleware for multi-tenant microcontrollers — enables running multiple applications with different permission levels on resource-constrained MCUs (Cortex-M)",
                "Per-container configurable scheduling and fine-grained access control to host resources through a metadata-driven approach — brings Linux container concepts to bare-metal MCUs",
                "Runtime abstraction layer supporting multiple container runtimes (WebAssembly via CS4WAMR, native RIOT OS) — demonstrates that containerization principles work below Linux",
                "Endpoint system for regulating container access to host resources with up to 4ms overhead per call — includes TinyML use case for ML inference in constrained containers"
            ],
            "relevance": "Translates Linux container concepts (namespaces, cgroups, scheduling isolation) to microcontrollers that don't run Linux. The per-container scheduling and access control mirror what the kernel provides via cgroups and namespaces, but implemented in firmware/RTOS. This is relevant because it shows the universality of the kernel's container abstractions and identifies which aspects (scheduling isolation, resource access control, runtime sandboxing) are fundamental versus Linux-specific. The WebAssembly runtime plays the role that eBPF plays in the kernel — a safe execution environment for untrusted code.",
            "methodology": "Container middleware implementation on RIOT OS. WebAssembly and native runtime support. Evaluation on Cortex-M microcontrollers. TinyML container use case."
        },
        "concepts": ["Namespaces", "Control Groups (cgroups v2)", "Scheduling Classes"],
        "claims": [
            {"kind": "Proposal", "id_prefix": "prop", "name": "Container runtime for multi-tenant microcontrollers",
             "description": "TinyContainer provides per-container scheduling, fine-grained access control, and runtime abstraction for multi-tenant microcontrollers. WebAssembly containers on Cortex-M MCUs with metadata-driven permission control and up to 4ms overhead per host call."}
        ]
    },

    # ── 2. FAULT+PROBE: RowHammer as Secret Bit Probe ───────────────
    {
        "ev_id": "ev-arxiv-897e7843",
        "brief": {
            "key_ideas": [
                "Shifts RowHammer from an integrity attack to an information leakage attack — uses RowHammer as a probe to deduce secret bit values from the victim's operational behavior, not from corrupted output",
                "Constructs a memory profile based on directional patterns of bit flips, then identifies susceptible bit locations within DRAM rows for targeted online probing",
                "Circumvents verify-after-sign fault check mechanisms: injects directional faults into key positions and observes signature generation rate to decode secret bits via statistical fault analysis",
                "FAULT+PROBE is generic — works on any system where an observable channel leaks the result of the fault injection attempt, not limited to cryptographic victims"
            ],
            "relevance": "Demonstrates a new class of DRAM-based attack that the kernel's existing RowHammer mitigations (memory isolation, page frame randomization) may not fully address. The attack doesn't need to corrupt data — it only needs to observe whether a fault was induced, which is visible through timing or behavioral changes. This has implications for kernel memory allocation (how pages are assigned to security-sensitive processes) and DRAM refresh policies. The generic nature means any kernel subsystem with observable behavior could be probed.",
            "methodology": "Memory profiling via directional bit flip analysis. Online statistical fault analysis. Demonstrated against ECDSA in wolfSSL TLS 1.3 implementation."
        },
        "concepts": [],
        "claims": [
            {"kind": "FailureMode", "id_prefix": "fail", "name": "RowHammer enables secret bit recovery via behavioral observation",
             "description": "FAULT+PROBE uses RowHammer to inject directional faults and observes the victim's behavioral changes (e.g., signature generation rate) to deduce secret bit values via statistical fault analysis. Circumvents verify-after-sign protections. Generic across systems with observable fault channels."}
        ]
    },

    # ── 3. LeakyHammer: RowHammer Defense Side Channels ─────────────
    {
        "ev_id": "ev-arxiv-04a6d879",
        "brief": {
            "key_ideas": [
                "First analysis of timing covert and side channel vulnerabilities introduced by RowHammer defenses themselves — the defenses that protect memory isolation create new information leakage channels",
                "Two fundamental features enable timing channels: (1) preventive actions reduce DRAM bandwidth, increasing memory latencies, (2) preventive actions can be triggered on demand via specific memory access patterns",
                "Builds covert channel attacks achieving 39.0 and 48.7 Kbps channel capacity by exploiting two RowHammer defense mechanisms",
                "Demonstrates website fingerprinting attack identifying visited websites based on the RowHammer-preventive actions they trigger"
            ],
            "relevance": "A ironic finding: RowHammer defenses designed to protect memory isolation inadvertently create new side channels. This is directly relevant to kernel DRAM management — the kernel must choose RowHammer mitigations, but the paper shows those mitigations leak information. The 39-48 Kbps covert channels are practical for real attacks. The website fingerprinting demonstrates that kernel-triggered DRAM defense actions are observable from userspace. This creates a tension for kernel security: stronger RowHammer protection = more observable defense actions = more information leakage.",
            "methodology": "Timing analysis of RowHammer defense preventive actions. Covert channel construction with capacity measurement. Website fingerprinting attack. Three countermeasure evaluations."
        },
        "concepts": [],
        "claims": [
            {"kind": "FailureMode", "id_prefix": "fail", "name": "RowHammer defenses create 39-48 Kbps covert channels",
             "description": "RowHammer preventive actions (triggered by memory access patterns) reduce DRAM bandwidth observably. Attackers build 39.0-48.7 Kbps covert channels and website fingerprinting attacks by exploiting the timing differences introduced by the defenses themselves."},
            {"kind": "Observation", "id_prefix": "obs", "name": "RowHammer protection and information leakage are fundamentally coupled",
             "description": "Stronger RowHammer mitigations produce more observable defense actions (bandwidth reduction, latency spikes), creating more information leakage. Countermeasures that fully mitigate the channel induce large performance overheads in RowHammer-vulnerable systems."}
        ]
    },

    # ── 4. BreakHammer: Throttling RowHammer Threads ────────────────
    {
        "ev_id": "ev-arxiv-7a2774cd",
        "brief": {
            "key_ideas": [
                "Tackles RowHammer defense overhead by tracking and throttling the hardware threads that trigger many preventive actions — instead of making defenses cheaper, reduces the trigger rate",
                "BreakHammer observes RowHammer-preventive actions of existing mitigations, identifies threads causing many actions, and reduces their memory bandwidth — a per-thread throttling approach",
                "Addresses the RowHammer denial-of-service problem: a malicious program can hog the memory system by causing excessive preventive actions, denying service to benign applications",
                "Reduces negative performance, energy, and fairness effects of eight different RowHammer mitigation mechanisms with near-zero area overhead"
            ],
            "relevance": "Proposes OS/hardware-level thread throttling to manage RowHammer defense overhead — directly relevant to the kernel's scheduler and memory controller interaction. The per-thread memory bandwidth throttling is analogous to cgroup memory bandwidth limiting (MBA on Intel). The denial-of-service mitigation is a kernel fairness problem: how to prevent one process from degrading system performance through RowHammer-triggering access patterns. This is the RowHammer analog of the kernel's existing resource control mechanisms.",
            "methodology": "Per-thread RowHammer trigger tracking and bandwidth throttling. Evaluation across eight RowHammer mitigation mechanisms. Performance, energy, and fairness metrics. Open-source."
        },
        "concepts": ["Scheduling Classes"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "RowHammer defenses enable denial-of-service attacks",
             "description": "As RowHammer worsens with DRAM scaling, defense overheads become prohibitively expensive. A malicious program can hog the memory system by triggering many RowHammer-preventive actions, denying service to benign applications."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Per-thread throttling of RowHammer-triggering memory access",
             "description": "BreakHammer identifies hardware threads causing many RowHammer-preventive actions and reduces their memory bandwidth. Reduces performance/energy/fairness degradation across eight RowHammer mitigations with near-zero area overhead."}
        ]
    },

    # ── 5. Cohet: CXL Coherent Heterogeneous Computing ──────────────
    {
        "ev_id": "ev-arxiv-97e8b7c8",
        "brief": {
            "key_ideas": [
                "First CXL-driven coherent heterogeneous computing framework — decouples compute and memory resources into unbiased CPU and XPU pools sharing a single unified coherent memory pool",
                "Exposes standard malloc/mmap interface to both CPU and XPU threads, with the OS handling memory allocation and management of heterogeneous resources transparently",
                "SimCXL: full-system cycle-level simulator modeling all CXL sub-protocols and device types, calibrated against real CXL hardware with 3% average simulation error",
                "CXL.cache reduces latency by 68% and increases bandwidth by 14.4x compared to DMA at cacheline granularity. CXL-NIC achieves 5.5-40.2x speedup over PCIe-NIC for remote atomic operations and RPC"
            ],
            "relevance": "Directly proposes a new OS memory model for CXL — the kernel's malloc/mmap interface extended to heterogeneous devices. The unified coherent memory pool requires the kernel to manage memory allocation across CPU and XPU pools with NUMA-aware placement. SimCXL's 3% error calibration against real hardware makes it the gold standard for validating kernel CXL patches. The 68% latency reduction from CXL.cache over DMA quantifies why the kernel should prefer cache-coherent CXL access over traditional DMA for fine-grained device interaction.",
            "methodology": "CXL framework design with unified memory model. SimCXL cycle-level simulator calibrated against real CXL hardware. Evaluation of CXL.cache vs DMA. Remote atomic operation and RPC applications."
        },
        "concepts": ["Adaptive CXL Memory Tiering", "NUMA Topology and Memory Policy"],
        "claims": [
            {"kind": "Proposal", "id_prefix": "prop", "name": "Unified coherent memory pool for CPU and XPU via CXL",
             "description": "Cohet decouples compute/memory into CPU and XPU pools sharing a single CXL-coherent memory pool. Standard malloc/mmap interface for both CPU and XPU threads with OS-managed heterogeneous memory allocation."},
            {"kind": "PerformanceProfile", "id_prefix": "perf", "name": "CXL.cache 68% latency reduction over DMA",
             "description": "CXL.cache reduces latency by 68% and increases bandwidth by 14.4x compared to DMA at cacheline granularity. CXL-NIC achieves 5.5-40.2x speedup over PCIe-NIC for atomic operations and RPC. SimCXL validated at 3% error against real hardware."}
        ]
    },

    # ── 6. CXL-Aware LLM Fine-Tuning ───────────────────────────────
    {
        "ev_id": "ev-arxiv-d56a5ebe",
        "brief": {
            "key_ideas": [
                "Reveals that PyTorch and similar frameworks lack fine-grained per-tensor control over NUMA memory allocation — only coarse process-level policies, causing naive CXL memory use to incur 4x slowdowns",
                "Introduces a PyTorch extension enabling tensor-level system memory control and a CXL-aware allocator that pins latency-critical tensors in local DRAM while striping latency-tolerant tensors across CXL devices",
                "Evaluated with real CXL hardware (CXL AIC) on 7B and 12B LLM models with 4K-32K contexts — recovers throughput to 97-99% of DRAM-only with a single CXL AIC",
                "Shows carefully managed CXL memory is a practical path for extending fine-tuning capacity beyond host DRAM limits"
            ],
            "relevance": "Directly exposes a limitation in the kernel's NUMA memory allocation interface as seen from userspace. The kernel provides process-level NUMA policies (set_mempolicy, mbind) but these are too coarse for frameworks that need per-tensor placement. The CXL-aware allocator essentially implements what the kernel should provide: fine-grained memory placement hints at the allocation level. The 4x slowdown from naive CXL use quantifies the cost of getting kernel NUMA policy wrong. The real-hardware validation on production CXL AICs makes this immediately relevant to kernel CXL developers.",
            "methodology": "PyTorch extension with tensor-level NUMA control. Real CXL AIC hardware evaluation. 7B/12B LLM fine-tuning with 4K-32K contexts. Comparison against DRAM-only and naive CXL interleaving."
        },
        "concepts": ["Adaptive CXL Memory Tiering", "NUMA Topology and Memory Policy"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "Kernel NUMA policy too coarse for CXL tensor placement",
             "description": "PyTorch and similar frameworks only have access to process-level NUMA memory policies from the kernel. Per-tensor placement is not possible, causing naive CXL offloading to incur 4x slowdowns when optimizer data lands on high-latency CXL memory."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Tensor-level CXL-aware memory allocator",
             "description": "A PyTorch extension enables tensor-level NUMA memory control, pinning latency-critical tensors in local DRAM while striping latency-tolerant tensors across CXL devices. Recovers to 97-99% of DRAM-only throughput on real CXL hardware."}
        ]
    },

    # ── 7. PrISM: Probabilistic RowHammer Mitigation ────────────────
    {
        "ev_id": "ev-arxiv-f9145637",
        "brief": {
            "key_ideas": [
                "Addresses the non-selection problem in probabilistic RowHammer defenses: at low thresholds, heavily hammered rows can repeatedly escape random sampling, requiring globally increased mitigation rates that waste bandwidth",
                "PrISM correlates sampled rows across time windows using a Sampled History Queue (SHQ) — requests additional mitigation only when persistent row activity is observed, avoiding fixed-rate scaling",
                "At threshold 500: 0.2% average slowdown vs 14% for PRAC (JEDEC standard), with no DRAM array changes, no per-row counters, and only 625 bytes of SRAM per bank",
                "At threshold 250: reduces average slowdown from 10.7% (MINT) to 1.5% — a 7.1x improvement in performance overhead"
            ],
            "relevance": "Directly relevant to how DRAM controllers (managed by the kernel's memory controller driver) implement RowHammer mitigation. PRAC is the JEDEC DDR5 standard defense, but its 14% overhead at threshold 500 makes it expensive. PrISM achieves comparable security with 70x less overhead (0.2% vs 14%). The kernel's memory management must account for RowHammer defense overhead when scheduling memory-intensive workloads — PrISM makes this overhead negligible. The 625-byte SRAM budget per bank is small enough for practical implementation.",
            "methodology": "Intersection-based probabilistic sampling with Sampled History Queue. Comparison against PRAC (JEDEC standard) and MINT. Threshold sweep from 250-1000. Area and performance overhead analysis."
        },
        "concepts": [],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "Probabilistic RowHammer defenses waste bandwidth at low thresholds",
             "description": "At low RowHammer thresholds (<1000 activations), probabilistic defenses must increase their fixed mitigation rate to overcome the non-selection problem (heavily hammered rows escaping sampling). This wastes effective memory bandwidth even when no attack is present."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Intersection-based probabilistic RowHammer mitigation",
             "description": "PrISM correlates sampled rows across windows using a Sampled History Queue, triggering additional mitigation only when persistent hammering is observed. 0.2% slowdown at threshold 500 (vs 14% for PRAC), 625 bytes SRAM per bank, no DRAM array changes."}
        ]
    },

    # ── 8. Governed MCP: Kernel-Level AI Agent Governance ───────────
    {
        "ev_id": "ev-arxiv-a076fc8f",
        "brief": {
            "key_ideas": [
                "Proposes kernel-resident tool governance for AI agents via a 6-layer pipeline: schema validation, trust tier, rate limit, adversarial pre-filter, ProbeLogits semantic gate (LLM-based classification), and constitutional policy match with Blake3-hashed audit chain",
                "ProbeLogits: a logit-based safety primitive that reads a single logit from a probe prompt to classify tool calls as safe/unsafe — 2.4-3.4x faster than Llama Guard 3 with comparable accuracy",
                "Implemented in Anima OS, a bare-metal x86-64 kernel in ~286K lines of Rust — every WASM-to-system host function and MCP tool is mediated by the kernel gateway, making userspace bypass structurally impossible",
                "Ablation shows removing ProbeLogits collapses F1 from 0.789 to 0.357 — hand-rule firewalling alone is insufficient for tool governance"
            ],
            "relevance": "The most radical proposal in the corpus: a bare-metal Rust OS kernel that mediates AI agent tool calls with an LLM-based safety gate in the kernel's syscall path. While not Linux, this demonstrates what kernel-level AI governance looks like. The ProbeLogits primitive (single logit read for classification) is efficient enough for kernel-path integration. The 6-layer pipeline is analogous to Linux's LSM hook chain but with an LLM as one of the decision points. The finding that hand rules alone are insufficient (F1 drops 0.432) motivates semantic reasoning in kernel security decisions — a direction Linux's eBPF LSM hooks could explore.",
            "methodology": "Bare-metal Rust kernel (Anima OS, 286K lines). 6-layer governance pipeline with ProbeLogits. Evaluation across three LLM architectures (Qwen2.5-7B, Llama-3-8B, Mistral-7B). Ablation study. HarmBench, XSTest, ToxicChat benchmarks."
        },
        "concepts": ["Linux Security Modules"],
        "claims": [
            {"kind": "Proposal", "id_prefix": "prop", "name": "Kernel-resident LLM-based tool governance for AI agents",
             "description": "Governed MCP places a 6-layer tool governance pipeline in the kernel's syscall path, including ProbeLogits (LLM-based semantic classification). Implemented in a bare-metal Rust OS. Every tool call is mediated, making userspace bypass structurally impossible."},
            {"kind": "Observation", "id_prefix": "obs", "name": "Hand-rule firewalling insufficient for AI tool governance",
             "description": "Removing ProbeLogits (LLM semantic gate) from the governance pipeline drops F1 from 0.789 to 0.357. Static rules alone cannot distinguish safe from unsafe tool calls — semantic reasoning is necessary in the kernel security path."}
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
    class_a = conn.execute(
        "SELECT count(*) FROM nodes WHERE kind = 'ResearchBrief' AND json_extract(attrs, '$.artifact_class') = 'A'"
    ).fetchone()[0]
    print(
        f"\nCreated {stats['briefs']} briefs, {stats['claims']} claims, {stats['edges']} edges"
    )
    print(f"Totals: {total_briefs} briefs ({class_a} Class A), {total_claims} claims in DB")
    conn.close()


if __name__ == "__main__":
    main()
