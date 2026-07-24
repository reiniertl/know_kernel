"""Deep enrichment batch 012: 10 papers — CXL NDP, UEFI vuln analysis, rootkit detection,
agent sandbox C/R, RTOS attacks, multikernel serverless, provenance scheduler, uFork,
LLM-synthesized static analyzers, GPU RT scheduling.

Papers:
1. M2NDP — Memory-mapped near-data processing in CXL memory expanders
2. STASE — UEFI vulnerability signature generation via static+symbolic analysis
3. User-space rootkits — Why user-space rootkit detection in user-space is futile
4. DeltaBox — Millisecond sandbox checkpoint/rollback for AI agents
5. KOM Attack — Kernel object masquerading attacks on ThreadX RTOS
6. Nanvix — Multikernel OS for high-density serverless (20-100x fewer servers)
7. Aegis — Learned Linux scheduler for provenance completeness
8. uFork — POSIX fork in single-address-space OS via CHERI (54us fork)
9. KNighter — LLM-synthesized static analyzers for kernel bugs (92 bugs, 30 CVEs)
10. GPU RT Scheduling — Preemptive priority-based GPU scheduling at driver level
"""
import json, sqlite3, uuid

DB_PATH = "data/master.db"

ALL_PAPERS = [
    # ── 1. M2NDP: CXL Near-Data Processing ─────────────────────────
    {
        "ev_id": "ev-arxiv-60d65298",
        "brief": {
            "key_ideas": [
                "Memory-Mapped NDP (M2NDP): low-overhead general-purpose near-data processing for CXL memory using CXL.mem-compatible communication — host issues NDP commands via ordinary memory-mapped store operations",
                "M2func: CXL.mem-compatible communication between host and NDP controller, avoiding the microsecond-scale latency of CXL.io/PCIe-based mechanisms used by prior work",
                "M2uthread: lightweight microthreading enabling low-cost general-purpose NDP unit design with highly concurrent kernel execution in the CXL controller",
                "Overcomes prior work's limitation of application-specific NDP units that are impractical for production CXL systems supporting diverse workloads"
            ],
            "relevance": "Proposes a general-purpose NDP architecture for CXL that the kernel must manage as a new device class. The memory-mapped command interface (M2func) means the kernel's CXL driver sees NDP commands as ordinary store operations — no separate device driver needed. The microthreading in the CXL controller runs compute near data without host CPU involvement. This is relevant to the kernel's CXL subsystem, device model, and how the kernel schedules and manages compute offload to CXL devices.",
            "methodology": "CXL NDP architecture design. Memory-mapped communication protocol. Microthreading execution model. Comparison against application-specific NDP and CPU/GPU-based alternatives."
        },
        "concepts": ["Adaptive CXL Memory Tiering", "NUMA Topology and Memory Policy"],
        "claims": [
            {"kind": "Proposal", "id_prefix": "prop", "name": "Memory-mapped general-purpose NDP for CXL memory",
             "description": "M2NDP enables NDP in CXL memory via memory-mapped commands (CXL.mem-compatible, no PCIe latency) and lightweight microthreading in the CXL controller. General-purpose design supporting diverse workloads unlike prior application-specific NDP units."}
        ]
    },

    # ── 2. STASE: UEFI Vulnerability Analysis ──────────────────────
    {
        "ev_id": "ev-arxiv-7b1fa5fb",
        "brief": {
            "key_ideas": [
                "STASE (Static Analysis guided Symbolic Execution): combines scalable static analysis with precise symbolic execution for automated UEFI vulnerability detection and signature generation",
                "Rule-based static analysis on LLVM bitcode identifies potential vulnerability targets, then focused symbolic execution achieves precise detection — combining scalability with precision",
                "Automates harness generation for symbolic execution — addresses the key usability barrier that typically requires manual harness writing to reduce state space",
                "UEFI has higher privileged security access than any other software including the kernel — vulnerabilities here undermine all higher-level security"
            ],
            "relevance": "UEFI vulnerabilities directly threaten the kernel because UEFI executes with higher privilege than the kernel itself. The LLVM-based analysis on bitcode is relevant because the UEFI firmware codebase (EDK II) is compiled with standard toolchains — the same analysis could be applied to kernel code. The automated harness generation for symbolic execution addresses a key barrier to formal verification of kernel-level code. Complements the UEFI forensics and Peacock papers (previous batches) by focusing on pre-deployment vulnerability finding rather than runtime detection.",
            "methodology": "LLVM bitcode static analysis. Rule-based vulnerability target identification. Focused symbolic execution with automated harness generation. UEFI vulnerability signature generation."
        },
        "concepts": ["EFI/UEFI Boot and Runtime Services"],
        "claims": [
            {"kind": "Proposal", "id_prefix": "prop", "name": "Static-guided symbolic execution for UEFI vulnerability signatures",
             "description": "STASE combines scalable LLVM bitcode static analysis with precise symbolic execution for automated UEFI vulnerability detection. Automates harness generation to overcome symbolic execution's usability barrier. Generates vulnerability signatures for firmware with higher privilege than the kernel."}
        ]
    },

    # ── 3. User-Space Rootkit Detection is Futile ──────────────────
    {
        "ev_id": "ev-arxiv-cef6f630",
        "brief": {
            "key_ideas": [
                "Argues that detecting user-space rootkits with user-space tools is fundamentally futile — contrary to the prevailing view that considers it effective",
                "Demonstrates evasion of the most popular open-source anti-rootkit tool for process hiding by exploiting the assumption that detection tools have trustworthy system call results",
                "Describes classical library rootkit construction (LD_PRELOAD hijacking, GOT overwriting), traditional detection mechanisms, and multiple evasion techniques with code",
                "Shows that detection results from user-space tools cannot be communicated to the user with confidence — the rootkit can intercept and modify the detection output itself"
            ],
            "relevance": "Directly relevant to Linux security architecture. The conclusion — that user-space rootkit detection requires kernel-level mechanisms — validates the kernel's investment in integrity monitoring (IMA, dm-verity, LSM hooks). The evasion techniques exploit Linux's dynamic linking (LD_PRELOAD), process file system (/proc), and library loading mechanisms. This motivates kernel-level detection via eBPF, kprobes, or LSM hooks that user-space rootkits cannot intercept. The paper provides the security threat model that justifies kernel-resident security monitoring.",
            "methodology": "Process concealment experiments on Linux. Evasion of chkrootkit and rkhunter. Library rootkit construction via LD_PRELOAD and GOT. Multiple evasion technique demonstrations."
        },
        "concepts": ["Linux Security Modules", "Process Creation (fork/clone)"],
        "claims": [
            {"kind": "FailureMode", "id_prefix": "fail", "name": "User-space rootkit detection is fundamentally bypassable",
             "description": "User-space anti-rootkit tools rely on system calls that rootkits can intercept. Detection results cannot be trusted because the rootkit can modify detection output. Process hiding evades the most popular open-source tools. Only kernel-level detection mechanisms are trustworthy."}
        ]
    },

    # ── 4. DeltaBox: Millisecond Agent Sandbox C/R ─────────────────
    {
        "ev_id": "ev-arxiv-3203943c",
        "brief": {
            "key_ideas": [
                "New OS-level abstraction DeltaState: change-based transactional checkpoint/rollback — only duplicates changes between consecutive checkpoints instead of full state",
                "DeltaFS: change-based filesystem C/R via layered file states with copy-on-write — checkpoint freezes writable layer and inserts new one, rollback is a layer switch",
                "DeltaCR: change-based process state C/R using incremental dumps — rollback bypasses traditional pipelines by directly fork()ing from frozen template process",
                "14ms checkpoint and rollback latency on SWE-bench — orders of magnitude faster than existing full-state mechanisms (hundreds of ms to seconds)"
            ],
            "relevance": "Proposes two new OS mechanisms (DeltaFS and DeltaCR) that extend the Linux kernel's filesystem and process management for agent workloads. DeltaFS extends overlayfs/CoW concepts to transaction-level filesystem versioning. DeltaCR extends CRIU-style checkpoint/restore with incremental dumps and template-process forking. The 14ms C/R enables tree search and RL exploration that is impossible with current kernel mechanisms. This is the systems-level infrastructure that agent-oriented OS papers (AgenticOS, Fork-Explore-Commit, TClone) all need.",
            "methodology": "OS abstraction design with DeltaFS and DeltaCR. SWE-bench and RL micro-benchmark evaluation. Latency comparison against full-state C/R mechanisms."
        },
        "concepts": ["Process Creation (fork/clone)", "OverlayFS (Union Mount)", "Page Fault Handler"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "Full-state sandbox C/R too slow for agent exploration",
             "description": "AI agents need high-frequency checkpoint/rollback for tree search and RL. Existing mechanisms duplicate entire state (hundreds of ms to seconds per C/R), bottlenecking deep search and large-scale fan-outs."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "DeltaState: change-based OS-level checkpoint/rollback",
             "description": "DeltaFS freezes filesystem layers with CoW for checkpoint; rollback is a layer switch. DeltaCR uses incremental process dumps and fork() from frozen templates. 14ms C/R latency — orders of magnitude faster than full-state approaches."}
        ]
    },

    # ── 5. KOM Attack on ThreadX RTOS ──────────────────────────────
    {
        "ev_id": "ev-arxiv-49d5baea",
        "brief": {
            "key_ideas": [
                "Discovers Kernel Object Masquerading (KOM) attack: exploiting a performance optimization in ThreadX RTOS that weakens system call parameter sanitization",
                "Attackers manipulate kernel objects through carefully selected system calls to access sensitive fields, leading to data manipulation, privilege escalation, or system compromise",
                "Automated approach using under-constrained symbolic execution to identify KOM attack paths — systematically discovers exploitable system call sequences",
                "FreeRTOS lacks essential security protections entirely; Zephyr and ThreadX differ significantly in their sanitization implementations despite similar designs"
            ],
            "relevance": "While ThreadX-specific, the KOM attack pattern applies to any kernel where performance optimizations weaken security checks — including the Linux kernel. The insight that a performance-oriented design choice (reduced parameter validation) creates an exploitable vulnerability is universal. The under-constrained symbolic execution methodology for finding these attacks could be applied to Linux kernel syscall validation. Relevant to the kernel's syscall parameter validation, seccomp argument filtering, and the ongoing tension between performance and security in kernel hot paths.",
            "methodology": "Security analysis of ThreadX parameter sanitization. KOM attack construction. Under-constrained symbolic execution for automated attack discovery. Comparison across FreeRTOS, Zephyr, ThreadX."
        },
        "concepts": [],
        "claims": [
            {"kind": "FailureMode", "id_prefix": "fail", "name": "Performance optimization creates kernel object masquerading attack",
             "description": "ThreadX's performance optimization weakens system call parameter sanitization. Attackers manipulate kernel objects via carefully selected syscall sequences to access sensitive fields, enabling privilege escalation. Automated symbolic execution identifies exploitable paths."}
        ]
    },

    # ── 6. Nanvix: Multikernel for Serverless ─────────────────────
    {
        "ev_id": "ev-arxiv-0acec345",
        "brief": {
            "key_ideas": [
                "Disaggregates ephemeral execution state (per-invocation) from persistent state (per-tenant) — lightweight user VM runs micro-kernel for threads/memory, system VM runs macro-kernel with device drivers shared per-tenant",
                "Achieves hypervisor isolation across tenants without sacrificing same-tenant performance — the split design reduces contention by multiplexing I/O through the system VM",
                "Order-of-magnitude lower application startup times with moderate I/O overheads compared to monolithic VM designs",
                "20-100x fewer host servers needed compared to state-of-the-art when replaying production traces — massive density improvement"
            ],
            "relevance": "A radical multikernel design for serverless that splits the kernel itself into micro-kernel (compute, per-invocation) and macro-kernel (I/O, per-tenant). This is relevant to the Linux kernel because it shows what happens when you disaggregate kernel functionality — the micro-kernel handles only threads and memory (the minimum the kernel must provide per-process), while device drivers and I/O live in a shared macro-kernel. The 20-100x density improvement quantifies the overhead of the current monolithic kernel model for serverless. This could inform future Linux kernel modularization for serverless workloads.",
            "methodology": "Multikernel OS design with user VM (micro-kernel) and system VM (macro-kernel). Production trace replay. Density comparison against state-of-the-art. Startup latency and I/O overhead analysis."
        },
        "concepts": ["KVM (Kernel-based Virtual Machine)", "Namespaces"],
        "claims": [
            {"kind": "Proposal", "id_prefix": "prop", "name": "Disaggregated micro/macro-kernel for serverless density",
             "description": "Nanvix splits the kernel: lightweight user VM with micro-kernel (threads, memory) per-invocation, shared system VM with macro-kernel (drivers, I/O) per-tenant. 20-100x fewer servers than state-of-the-art. Order-of-magnitude faster startup with hypervisor-level tenant isolation."}
        ]
    },

    # ── 7. Aegis: Learned Linux Scheduler for Provenance ────────────
    {
        "ev_id": "ev-arxiv-1c3ae3d2",
        "brief": {
            "key_ideas": [
                "Addresses the 'super producer threat' where provenance generation can overload a system, forcing it to drop security-relevant events and allowing attackers to hide actions",
                "Aegis: a reinforcement-learning-based Linux scheduler specifically designed to ensure provenance completeness — dynamically optimizes resource allocation for provenance tasks",
                "Unlike conventional schedulers that ignore provenance requirements, Aegis learns provenance task behavior and adapts scheduling to prevent event loss",
                "Significantly improves both completeness and efficiency of provenance collection while maintaining reasonable overheads — even improves overall runtime in some cases"
            ],
            "relevance": "A learned scheduler implemented in the Linux kernel specifically for security provenance — showing that scheduling policy can be security-critical, not just performance-critical. The super producer threat (overloading provenance to create blind spots) is a real kernel security issue: audit, ftrace, and eBPF event collection all have finite buffers that can overflow. Aegis shows that the scheduler can be part of the security solution. This complements sched_ext (which allows custom scheduling) by demonstrating an RL-based policy with a concrete security objective.",
            "methodology": "Reinforcement learning-based Linux scheduler implementation. Provenance completeness evaluation under super producer threat. Comparison against default Linux scheduling."
        },
        "concepts": ["Scheduling Classes", "Linux Security Modules"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "Provenance overload creates security blind spots",
             "description": "The 'super producer threat' overloads provenance collection, forcing the system to drop security-relevant events. Attackers exploit this to hide actions. Conventional schedulers ignore provenance completeness requirements, treating provenance tasks like any other workload."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "RL-based Linux scheduler for provenance completeness",
             "description": "Aegis uses reinforcement learning to learn provenance task behavior and dynamically optimize resource allocation. Ensures provenance completeness under adversarial conditions while maintaining or improving overall runtime performance."}
        ]
    },

    # ── 8. uFork: POSIX fork in Single-Address-Space OS ─────────────
    {
        "ev_id": "ev-arxiv-b83f060d",
        "brief": {
            "key_ideas": [
                "uFork supports POSIX fork in a single-address-space OS using CHERI capabilities — the child's memory is copied to a different location within the shared address space and relocated using CHERI pointer manipulation",
                "Solves two fundamental challenges: relocating the child's absolute memory references (pointers) and providing isolation without separate address spaces — both via CHERI hardware capabilities",
                "Fork in 54 microseconds — 3.7x faster than traditional fork. FaaS function throughput 24% higher than monolithic OS",
                "Redis snapshots, Nginx multi-worker, and Zygote FaaS worker warm-up demonstrated as real-world use cases"
            ],
            "relevance": "Reimagines the kernel's most fundamental process creation primitive (fork) for next-generation hardware (CHERI). Traditional fork requires address space duplication via page table copying — uFork eliminates this by using CHERI capabilities to relocate pointers within a single address space. The 3.7x faster fork and 24% higher FaaS throughput show the performance cost of the kernel's current fork/page-table model. This is directly relevant to the kernel's fork implementation, CHERI support (being upstreamed for Arm Morello), and the ongoing debate about fork's future in modern kernels.",
            "methodology": "Single-address-space OS implementation with CHERI. uProcess emulation. Real-world use cases: Redis, Nginx, FaaS Zygote. Performance comparison against traditional monolithic OS fork."
        },
        "concepts": ["Process Creation (fork/clone)"],
        "claims": [
            {"kind": "Proposal", "id_prefix": "prop", "name": "CHERI-based POSIX fork without address space duplication",
             "description": "uFork implements fork in a single-address-space OS using CHERI capabilities for pointer relocation and isolation. 54us fork (3.7x faster than traditional), 24% higher FaaS throughput. Compatible with Redis, Nginx, and Zygote patterns."}
        ]
    },

    # ── 9. KNighter: LLM-Synthesized Kernel Static Analyzers ───────
    {
        "ev_id": "ev-arxiv-5104b42e",
        "brief": {
            "key_ideas": [
                "First approach that uses LLMs to synthesize static analyzers (not directly analyze code) — generates specialized checkers from historical kernel bug patterns that then scan the kernel at scale",
                "Multi-stage synthesis pipeline: validates checker correctness against original patches, iteratively refines to reduce false positives — the LLM produces the tool, not the analysis",
                "92 new critical long-latent bugs found in Linux kernel (average 4.3 years latent): 77 confirmed, 57 fixed, 30 assigned CVEs",
                "Establishes a new paradigm: scalable, reliable, traceable LLM-based static analysis via checker synthesis rather than direct LLM code analysis"
            ],
            "relevance": "The highest-impact kernel security result in the corpus — 92 bugs, 30 CVEs in the Linux kernel from a single tool. The paradigm shift from 'LLM analyzes code' to 'LLM synthesizes analyzers' is brilliant: it sidesteps LLM hallucination by having the LLM produce a deterministic checker that can be validated. The synthesized checkers detect bug patterns that human-written analyzers (Coccinelle, Smatch) missed for years. This directly improves the kernel development toolchain and has already been adopted by kernel maintainers.",
            "methodology": "LLM-based checker synthesis from historical kernel patches. Multi-stage validation and refinement pipeline. Linux kernel evaluation. 92 bugs found, 77 confirmed, 57 fixed, 30 CVEs."
        },
        "concepts": [],
        "claims": [
            {"kind": "Proposal", "id_prefix": "prop", "name": "LLM-synthesized static analyzers for kernel bug detection",
             "description": "KNighter uses LLMs to synthesize specialized static analysis checkers from historical kernel bug patterns, rather than having LLMs directly analyze code. Multi-stage validation against original patches with iterative false-positive reduction. 92 new kernel bugs (30 CVEs), average 4.3 years latent."},
            {"kind": "PerformanceProfile", "id_prefix": "perf", "name": "KNighter: 92 kernel bugs, 30 CVEs from synthesized checkers",
             "description": "92 new critical long-latent bugs in Linux kernel: 77 confirmed, 57 fixed, 30 assigned CVEs. Detects diverse bug patterns overlooked by existing human-written analyzers. Checkers are deterministic, traceable, and have been merged into kernel development toolchains."}
        ]
    },

    # ── 10. GPU Real-Time Scheduling at Driver Level ────────────────
    {
        "ev_id": "ev-arxiv-9cdd9ed4",
        "brief": {
            "key_ideas": [
                "Two novel techniques for preemptive priority-based GPU scheduling: kernel thread approach (no user program changes) and IOCTL approach (single macro at GPU access boundaries)",
                "Controls GPU context scheduling at the device driver level — enables preemptive GPU scheduling based on task priorities rather than GPU-internal scheduling",
                "Comprehensive response time analysis accounting for overlaps between task segments — reduces pessimism in worst-case estimates for mixed CPU-GPU real-time tasks",
                "Up to 40% higher schedulability over prior work with predictable worst-case behavior on Nvidia Jetson platforms"
            ],
            "relevance": "Directly modifies the GPU device driver to enable preemptive priority-based scheduling — the kernel's GPU driver (DRM/Nvidia proprietary) currently lacks real-time scheduling support. The kernel-thread approach is particularly relevant: it adds priority-based GPU preemption without changing user programs, by having a kernel thread manage GPU context switching. This is the real-time counterpart to gpu_ext (eBPF GPU policies) — where gpu_ext focuses on cloud multi-tenancy, this focuses on real-time guarantees. Evaluated on Nvidia Jetson, the primary embedded GPU platform.",
            "methodology": "GPU driver-level scheduling implementation. Kernel thread and IOCTL approaches. Response time analysis with segment overlap. Nvidia Jetson Orin/Xavier evaluation. Schedulability comparison."
        },
        "concepts": ["Scheduling Classes", "Interrupt Handling"],
        "claims": [
            {"kind": "Proposal", "id_prefix": "prop", "name": "Driver-level preemptive priority GPU scheduling",
             "description": "Two approaches for GPU real-time scheduling at the device driver level: kernel thread (no user changes, driver mediates GPU context switches by priority) and IOCTL (single macro at GPU access boundaries). 40% higher schedulability over prior work on Nvidia Jetson."}
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

        print(f"  OK: {title.encode('ascii', 'replace').decode()}")

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
