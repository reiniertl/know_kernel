"""Deep enrichment batch 009: 10 papers — production kernel systems, agent OS, and CXL tiering.

Papers:
1. Vmem — Hot-upgradable memory management for Alibaba Cloud (300K servers, 7 years)
2. AgentCgroup — eBPF+cgroup+sched_ext resource control for AI agents
3. kAgent — Execution-guided crash resolution agent for Linux kernel
4. OAMAC — Origin-aware mandatory access control via eBPF LSM
5. KernelGPT — LLM-synthesized syscall specs for kernel fuzzing (24 bugs, 11 CVEs)
6. Blindfold — Confidential memory management by untrusted OS (ARMv8-A)
7. VCAO — Game-theoretic LLM orchestration for kernel vulnerability discovery
8. ByteFS — File system for CXL-based memory-semantic SSDs
9. MIKU — Dynamic memory request control for CXL tiered memory
10. Adaptive Migration Decision — Per-process migration control for CXL tiered memory
"""
import json, sqlite3, uuid

DB_PATH = "data/master.db"

ALL_PAPERS = [
    # ── 1. Vmem: Hot-Upgradable Cloud Memory Management ─────────────
    {
        "ev_id": "ev-arxiv-vmem",
        "brief": {
            "key_ideas": [
                "Lightweight reserved memory management architecture for in-production cloud environments that enables online hot-upgrades — the first such architecture supporting live upgrade of the memory management layer without VM downtime",
                "Increases sellable memory rate by ~2% across Alibaba Cloud fleet — at 300K+ servers, this translates to massive cost savings from reduced memory overhead",
                "Delivers 3x faster boot time for VFIO-based virtual machines and ~10% network performance improvement for DPU-accelerated VMs through optimized memory reservation",
                "Deployed at large scale for seven years on 300,000+ cloud servers supporting hundreds of millions of VMs — proven production reliability"
            ],
            "relevance": "The most production-validated kernel memory management paper in the corpus. Vmem addresses a problem unique to hyperscale cloud: the memory management layer itself needs to be upgraded without taking down VMs. This requires kernel-level hot-upgrade capabilities that go beyond kexec — the memory management metadata must survive the upgrade. The VFIO boot optimization (3x faster) directly targets the kernel's VFIO/IOMMU initialization path. The 7-year deployment at Alibaba scale provides data points that academic papers cannot: real failure modes, upgrade procedures, and performance under production conditions.",
            "methodology": "Production deployment at Alibaba Cloud. 300K+ servers, 7 years. VFIO and DPU-accelerated VM evaluation. Sellable memory rate analysis."
        },
        "concepts": ["KVM (Kernel-based Virtual Machine)", "VFIO (Virtual Function I/O)", "NUMA Topology and Memory Policy"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "Cloud memory management cannot be upgraded without VM downtime",
             "description": "Traditional kernel memory management is static — upgrading it requires rebooting the host, causing VM downtime. At hyperscale (300K+ servers), this creates a maintenance burden that conflicts with SLA requirements."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Hot-upgradable reserved memory management for cloud",
             "description": "Vmem enables online upgrade of the memory management layer without VM downtime. Lightweight reserved memory management increases sellable memory by ~2%, delivers 3x faster VFIO VM boot and 10% DPU network improvement."},
            {"kind": "PerformanceProfile", "id_prefix": "perf", "name": "Vmem production deployment at Alibaba scale",
             "description": "Deployed 7 years on 300K+ Alibaba Cloud servers supporting hundreds of millions of VMs. 2% more sellable memory, 3x faster VFIO boot, 10% better DPU-accelerated networking."}
        ]
    },

    # ── 2. AgentCgroup: eBPF Resource Control for AI Agents ─────────
    {
        "ev_id": "ev-arxiv-6dbecf3f",
        "brief": {
            "key_ideas": [
                "First systematic characterization of OS-level resource dynamics in AI coding agents: OS-level execution (tool calls, initialization) accounts for 56-74% of end-to-end task latency; memory, not CPU, is the concurrency bottleneck",
                "Identifies three mismatches in existing resource controls: granularity (container vs tool-call), responsiveness (userspace vs sub-second bursts), and adaptability (prediction vs non-deterministic execution)",
                "Proposes AgentCgroup: hierarchical cgroup structures aligned with tool-call boundaries, in-kernel enforcement via sched_ext and memcg_bpf_ops, and runtime-adaptive policies",
                "Exploits agents' unique ability to declare resource needs and reconstruct execution strategies — unlike traditional workloads, agents can express intent to the OS"
            ],
            "relevance": "Directly proposes new kernel mechanisms for agent workloads: hierarchical cgroups at tool-call granularity, sched_ext integration for agent scheduling, and memcg_bpf_ops for eBPF-based memory control. The characterization finding that OS-level execution is 56-74% of agent latency is a wake-up call for kernel developers — the kernel is the bottleneck for agent workloads. The intent-driven resource control (agents declare needs) is a fundamentally new kernel-application interaction model. From the same UC Santa Cruz/eunomia-bpf group that produced ActPlane and SchedCP.",
            "methodology": "Characterization of 144 SWE-rebench tasks across 2 LLM models. Comparison against serverless/microservice/batch workloads. AgentCgroup prototype with eBPF+sched_ext+memcg. Open source."
        },
        "concepts": ["Control Groups (cgroups v2)", "sched_ext Extensible Scheduling", "eBPF (Extended Berkeley Packet Filter)"],
        "claims": [
            {"kind": "Observation", "id_prefix": "obs", "name": "OS execution is 56-74% of AI agent task latency",
             "description": "OS-level execution (tool calls, container and agent initialization) accounts for 56-74% of end-to-end task latency for AI coding agents. Memory, not CPU, is the concurrency bottleneck with up to 15.4x peak-to-average ratio."},
            {"kind": "Problem", "id_prefix": "prob", "name": "Three resource control mismatches for agent workloads",
             "description": "Granularity mismatch (container-level vs tool-call-level), responsiveness mismatch (userspace reaction vs sub-second bursts), and adaptability mismatch (history-based prediction vs non-deterministic stateful execution)."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Intent-driven eBPF resource controller for AI agents",
             "description": "AgentCgroup uses hierarchical cgroups at tool-call boundaries, in-kernel enforcement via sched_ext and memcg_bpf_ops, and exploits agents' ability to declare resource needs for runtime-adaptive policies."}
        ]
    },

    # ── 3. kAgent: Kernel Crash Resolution Agent ────────────────────
    {
        "ev_id": "ev-arxiv-6b66fc2c",
        "brief": {
            "key_ideas": [
                "Workflow-based LLM agent inspired by how kernel developers diagnose and fix bugs: inspects execution logs, generates execution-grounded hypotheses, synthesizes patches, validates via crash reproduction, and iteratively refines",
                "Identifies bottlenecks that generic LLM agents struggle with in kernel repair: absence of natural language bug reports, lack of exhaustive test oracles, highly specialized crash artifacts (kasan, kmemleak, lockdep)",
                "kGym++: co-designed toolstack supporting kAgent with kernel build, boot, crash reproduction, and validation infrastructure",
                "Repairs 54.5% of crashes without localization hints and 65% with correct file hints on kBenchSyz. Generalizes to wild syzbot bugs"
            ],
            "relevance": "Directly targets Linux kernel bug repair — the most challenging automated repair domain. The kernel's specialized crash artifacts (KASAN reports, lockdep warnings, kmemleak traces) require domain-specific interpretation that generic LLM agents cannot handle. kAgent's workflow mirrors actual kernel development: read crash log → form hypothesis → write patch → test → iterate. The 54.5% repair rate without hints and 65% with hints establishes a new baseline for automated kernel repair. kGym++ provides reusable infrastructure for kernel development AI tools.",
            "methodology": "Workflow-based LLM agent with execution-grounded reasoning. kGym++ toolstack for kernel build/boot/test. kBenchSyz evaluation. Ablation study of agent features. Wild syzbot bug generalization."
        },
        "concepts": [],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "Generic LLM agents fail at kernel crash repair",
             "description": "Linux kernel fuzz bugs lack natural language reports, have no exhaustive test oracles, and produce highly specialized crash artifacts (KASAN, lockdep, kmemleak). Generic LLM repair techniques targeting userspace applications are not tailored to these unique challenges."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Kernel-developer-inspired crash resolution agent",
             "description": "kAgent follows a kernel developer workflow: inspect logs, form execution-grounded hypotheses, synthesize patches, validate via crash reproduction, iteratively refine. kGym++ provides kernel build/boot/test infrastructure. 54.5% repair rate without hints, 65% with file hints."}
        ]
    },

    # ── 4. OAMAC: Origin-Aware MAC via eBPF LSM ────────────────────
    {
        "ev_id": "ev-arxiv-952313d5",
        "brief": {
            "key_ideas": [
                "Introduces execution origin (physical user, remote access, service execution) as a first-class security attribute in mandatory access control — processes launched remotely vs locally should have different permissions",
                "Implemented entirely using Linux eBPF LSM framework with zero kernel modifications — classifies execution origin using kernel-visible metadata, propagates origin across process creation, enforces origin-aware policies",
                "Policies maintained in kernel-resident eBPF maps, reconfigurable at runtime via userspace tool — no reboot or module reload needed",
                "Restricts common post-compromise actions available to remote attackers while preserving normal local administration and system stability"
            ],
            "relevance": "A fundamentally new dimension for Linux access control. Current LSMs (SELinux, AppArmor) distinguish subjects by identity/label but not by how they arrived at their current state. OAMAC adds 'where did this process come from?' as a security attribute. Implemented purely via eBPF LSM hooks — no kernel patches needed, demonstrating that eBPF LSM is powerful enough for novel security models. The origin propagation across fork/exec is particularly relevant to the kernel's credential management and LSM hook chain.",
            "methodology": "eBPF LSM implementation. Origin classification from kernel metadata. Origin propagation across process creation. Runtime-reconfigurable policies via eBPF maps. Post-compromise attack evaluation."
        },
        "concepts": ["Linux Security Modules", "eBPF (Extended Berkeley Packet Filter)", "Process Creation (fork/clone)"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "MAC ignores execution origin enabling post-compromise abuse",
             "description": "Modern OS MAC reasons about who executes code but not how execution originates. Processes from remote access, local terminals, and background services are treated equivalently once privileges are obtained, enabling post-compromise abuse of sensitive interfaces."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Origin-aware MAC via eBPF LSM with zero kernel modifications",
             "description": "OAMAC treats execution origin as a first-class security attribute. Implemented via eBPF LSM hooks: classifies origin from kernel metadata, propagates across fork/exec, enforces policies from eBPF maps. Runtime reconfigurable without reboot."}
        ]
    },

    # ── 5. KernelGPT: LLM Syscall Specs for Kernel Fuzzing ─────────
    {
        "ev_id": "ev-arxiv-fb8919c6",
        "brief": {
            "key_ideas": [
                "First approach to automatically synthesizing syscall specifications via LLMs for kernel fuzzing — LLMs distill kernel code, documentation, and use cases seen during pre-training into valid syscall specs",
                "Iterative approach: infer specifications, then debug and repair them based on validation feedback from the kernel fuzzer",
                "Generates more new and valid specifications with higher coverage than manual or state-of-the-art automated techniques",
                "24 new unique bugs detected in Linux kernel: 12 fixed, 11 assigned CVEs. Specifications merged into syzkaller by its development team"
            ],
            "relevance": "Directly improves Linux kernel fuzzing — the primary mechanism for finding kernel vulnerabilities. Syzkaller relies on manually-written syscall specifications that define valid argument types, constraints, and relationships. Large numbers of syscalls remain uncovered because specification writing is tedious and requires deep kernel expertise. KernelGPT automates this bottleneck. The 24 bugs found (11 CVEs) and the upstream merge into syzkaller demonstrate immediate kernel security impact.",
            "methodology": "LLM-based iterative specification synthesis with validation feedback. Evaluated on syzkaller. 24 bugs found, 12 fixed, 11 CVEs. Specifications merged into syzkaller upstream."
        },
        "concepts": [],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "Manual syscall spec writing bottlenecks kernel fuzzing coverage",
             "description": "Kernel fuzzers like syzkaller depend on manually-written syscall specifications. Many important syscalls remain uncovered because specification writing requires deep kernel expertise and is tedious. This limits fuzzing coverage and bug discovery."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "LLM-automated syscall specification synthesis for kernel fuzzing",
             "description": "KernelGPT uses LLMs to automatically generate syscall specifications through iterative inference and validation-feedback-based debugging. Achieves higher coverage than manual specs. 24 new kernel bugs (11 CVEs). Specs merged into syzkaller upstream."}
        ]
    },

    # ── 6. Blindfold: Confidential Memory by Untrusted OS ───────────
    {
        "ev_id": "ev-arxiv-4715618c",
        "brief": {
            "key_ideas": [
                "Enables the untrusted Linux kernel to manage confidential memory without encryption — Guardian (small trusted component at higher privilege) mediates OS memory access by switching page and interrupt tables",
                "Lightweight capability system regulates kernel semantic access to user memory — unifies case-by-case approaches from prior confidential computing work into a single mechanism",
                "All Linux kernel memory optimizations except memory compression function correctly for confidential memory with only ~400 lines of kernel modifications",
                "Smaller runtime TCB than related systems with competitive performance on ARMv8-A"
            ],
            "relevance": "Directly modifies the Linux kernel (400 lines) to support confidential computing on ARM. The key insight is that the kernel doesn't need to be completely excluded from memory management — it just needs to be mediated. By switching page tables rather than nesting them, Blindfold avoids the performance cost of nested virtualization. The fact that all kernel memory optimizations (compaction, reclaim, huge pages, migration) work correctly with only 400 lines of changes shows that the kernel's memory management is already well-structured for confidential computing adaptation.",
            "methodology": "ARMv8-A Linux implementation. Guardian trusted component at EL2. Capability-based semantic access control. TCB size analysis. Performance evaluation with kernel memory optimizations."
        },
        "concepts": ["Page Fault Handler", "Hierarchical Page Tables", "Linux Security Modules"],
        "claims": [
            {"kind": "Proposal", "id_prefix": "prop", "name": "Untrusted OS confidential memory via page table switching",
             "description": "Blindfold's Guardian mediates OS memory access by switching page and interrupt tables (not nesting them). A capability system regulates kernel semantic access. All Linux memory optimizations except compression work with ~400 lines of kernel changes."},
            {"kind": "Observation", "id_prefix": "obs", "name": "Linux kernel memory management already structured for CC adaptation",
             "description": "All Linux kernel memory optimizations (compaction, reclaim, huge pages, NUMA migration) function correctly for confidential memory with only ~400 lines of kernel modifications, demonstrating the kernel's memory subsystem is well-structured for confidential computing."}
        ]
    },

    # ── 7. VCAO: Game-Theoretic Kernel Vulnerability Discovery ──────
    {
        "ev_id": "ev-arxiv-161fd98c",
        "brief": {
            "key_ideas": [
                "Formulates OS vulnerability discovery as a repeated Bayesian Stackelberg game — LLM orchestrator allocates analysis budget across kernel files, functions, and attack paths while verifiers provide evidence",
                "Six-layer architecture: surface mapping, intra-kernel attack-graph construction, game-theoretic ranking, parallel executor agents, cascaded verification, safety governor",
                "DOBSS-derived MILP allocates budget optimally across heterogeneous analysis tools (static analyzers, fuzzers, sanitizers) with formal regret bounds",
                "2.7x more validated vulnerabilities per budget than coverage-only fuzzing, 1.9x more than static analysis alone. 68% fewer false positives reaching human reviewers"
            ],
            "relevance": "The most sophisticated automated kernel vulnerability discovery system in the corpus. Combines game theory (Stackelberg games for budget allocation), LLMs (reasoning model for target selection), and traditional tools (static analysis, fuzzing, sanitizers) in a principled framework. Evaluated on 847 historical Linux kernel CVEs across five subsystems. The game-theoretic formulation is novel — treating the attacker as a strategic adversary whose payoff the system minimizes. This could change how kernel security teams allocate audit resources.",
            "methodology": "Bayesian Stackelberg game formulation. MILP budget allocation. Evaluation on 847 historical CVEs across 5 Linux kernel subsystems. Comparison against fuzzing-only, static-analysis-only, and non-game-theoretic multi-agent baselines."
        },
        "concepts": [],
        "claims": [
            {"kind": "Proposal", "id_prefix": "prop", "name": "Game-theoretic LLM orchestration for kernel vulnerability discovery",
             "description": "VCAO formulates vulnerability discovery as a Bayesian Stackelberg game. LLM orchestrator allocates budget across kernel files/functions/attack-paths. MILP-optimal allocation across static analyzers, fuzzers, and sanitizers. 2.7x more vulnerabilities than fuzzing alone, 68% fewer false positives."}
        ]
    },

    # ── 8. ByteFS: File System for CXL Memory-Semantic SSDs ─────────
    {
        "ev_id": "ev-arxiv-16cb9163",
        "brief": {
            "key_ideas": [
                "Rethinks file system design for memory-semantic SSDs that support both byte and block access via CXL — exploits the dual byte/block interface that these devices provide",
                "Byte-granular data persistence: enables fine-grained persistent writes without requiring full-block I/O, retaining the persistence nature of SSDs",
                "Log-structured management of SSD internal DRAM with data coalescing to reduce unnecessary I/O to flash chips — coordinates host page cache with SSD cache",
                "Up to 2.7x performance improvement over state-of-the-art file systems, 5.1x reduction in write traffic to SSDs"
            ],
            "relevance": "Directly extends the Linux kernel's filesystem layer for a new class of storage device: CXL-attached memory-semantic SSDs. ByteFS registers with the VFS and manages a device that supports both load/store (byte) and read/write (block) semantics — a hybrid that no existing kernel filesystem handles natively. The coordinated host/SSD caching is particularly relevant: the kernel's page cache and the SSD's internal cache must cooperate rather than compete. The 5.1x write traffic reduction shows that byte-granular persistence eliminates massive write amplification in traditional block I/O paths.",
            "methodology": "Linux file system implementation. Real programmable SSD and emulated CXL SSD. Comparison against NVM and conventional SSD file systems. Write traffic analysis."
        },
        "concepts": ["Virtual Filesystem Switch", "Page Cache", "NVMe Driver Subsystem", "Adaptive CXL Memory Tiering"],
        "claims": [
            {"kind": "Proposal", "id_prefix": "prop", "name": "Dual byte/block file system for CXL memory-semantic SSDs",
             "description": "ByteFS exploits CXL SSDs' dual interface: byte-granular persistence for fine-grained writes, block access for bulk I/O. Log-structured SSD DRAM management with coordinated host/SSD caching. 2.7x performance, 5.1x less write traffic vs state-of-the-art."}
        ]
    },

    # ── 9. MIKU: Dynamic Memory Request Control for CXL ─────────────
    {
        "ev_id": "ev-arxiv-05470852",
        "brief": {
            "key_ideas": [
                "Identifies that CXL memory's increased latency and parallelism disparity can reduce DDR bandwidth by up to 81% under heavy loads — CXL requests contend with and slow down DDR requests",
                "Discovers unfair queuing in memory request handling: CXL's higher latency hogs memory controller queues, starving DDR requests of bandwidth they should have",
                "Proposes MIKU: dynamically adjusts CXL request rates based on service time estimates, prioritizing DDR requests while serving CXL on a best-effort basis",
                "Achieves near-peak DDR throughput while maintaining high CXL performance"
            ],
            "relevance": "Reveals a critical interaction between the kernel's memory subsystem and CXL hardware: naive CXL memory access can destroy local DDR bandwidth. The kernel's NUMA balancing and memory tiering must account for this interference — migrating pages to CXL doesn't just add CXL latency, it degrades DDR performance for everything else. MIKU's dynamic request control is a hardware mechanism, but the kernel needs to be aware of it for effective tiering decisions. The 81% DDR bandwidth reduction is alarming for kernel memory management assumptions.",
            "methodology": "Micro-benchmarks isolating CXL-DDR interference. Memory request queuing analysis. MIKU dynamic request control. Evaluation with representative workloads."
        },
        "concepts": ["Adaptive CXL Memory Tiering", "NUMA Topology and Memory Policy"],
        "claims": [
            {"kind": "FailureMode", "id_prefix": "fail", "name": "CXL memory access reduces DDR bandwidth by up to 81%",
             "description": "CXL memory's higher latency and parallelism disparity cause unfair queuing in memory controllers. Under heavy CXL load, DDR bandwidth drops by up to 81% due to queue contention — CXL requests starve DDR requests of controller resources."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Dynamic CXL request rate control to preserve DDR bandwidth",
             "description": "MIKU dynamically adjusts CXL request rates based on service time estimates, prioritizing DDR while serving CXL best-effort. Achieves near-peak DDR throughput with high CXL performance."}
        ]
    },

    # ── 10. Adaptive Migration for CXL Tiered Memory ────────────────
    {
        "ev_id": "ev-arxiv-997bcef6",
        "brief": {
            "key_ideas": [
                "Page migration in CXL tiered memory is not always beneficial — migration has costs (detection overhead, data copying) that can exceed benefits for migration-unfriendly applications",
                "Detects migration friendliness using per-page ping-pong status: pages repeatedly promoted and demoted in a short period indicate ineffective migration",
                "Per-process migration control selectively stops and starts migration depending on each application's behavior — avoids penalizing migration-unfriendly workloads",
                "Implemented in the Linux kernel and evaluated on commercial CXL-based tiered memory hardware"
            ],
            "relevance": "Directly modifies the Linux kernel's memory tiering subsystem with per-process migration control. The insight that migration is sometimes harmful (ping-pong pages) is critical for the kernel's CXL tiering policies — the kernel currently migrates aggressively based on hotness signals without considering whether migration is actually helping. The per-process control extends the kernel's existing process-level memory policies (set_mempolicy, cgroup memory) with migration effectiveness tracking. Evaluated on real CXL hardware, making this immediately relevant to kernel CXL development.",
            "methodology": "Linux kernel implementation. Ping-pong detection for migration friendliness. Per-process migration control. Commercial CXL hardware evaluation. Single and multi-tenant workloads."
        },
        "concepts": ["Adaptive CXL Memory Tiering", "NUMA Topology and Memory Policy", "Page Reclaim (kswapd/direct)"],
        "claims": [
            {"kind": "Observation", "id_prefix": "obs", "name": "CXL page migration is harmful for some workloads",
             "description": "Page migration in CXL tiered memory is not always beneficial. For migration-unfriendly applications, the cost of detecting and migrating hot pages exceeds the performance benefit. Ping-pong pages (repeatedly promoted and demoted) indicate ineffective migration."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Per-process adaptive migration control for CXL tiered memory",
             "description": "Detects migration friendliness per-process using ping-pong page tracking. Selectively stops migration for unfriendly processes and resumes when access patterns change. Implemented in Linux kernel on commercial CXL hardware."}
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
