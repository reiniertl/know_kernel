"""Deep enrichment batch 011: 9 papers — agent OS security, hypervisor isolation,
generative filesystems, syscall interception, priority spinlocks, cloud swap, VM tiering,
RDMA page faults, WORM storage.

Papers:
1. AgenticOS — Intent-oriented secure OS architecture for AI agents (Tencent)
2. Edera — High-performance hypervisor with container+driver isolation
3. SYSSPEC — LLM-generated file systems from formal specifications
4. nexpoline — Secure syscall interception via MPK + Seccomp/SUD
5. BPL — Batched Priority Lock for real-time multicore kernels
6. Flexible Swapping — Userspace VM memory management for cloud overcommit
7. VM Memory Tiering — Guest-side access consolidation for host tiering efficiency
8. RDMA Page Faults — DMA engine page fault handling with ARM SMMU
9. Socarrat — Reverse File System for WORM storage via USB device
"""
import json, sqlite3, uuid

DB_PATH = "data/master.db"

ALL_PAPERS = [
    # ── 1. AgenticOS: Intent-Oriented Secure OS ─────────────────────
    {
        "ev_id": "ev-arxiv-agenticos-intent-oriented-secure-os-arch",
        "brief": {
            "key_ideas": [
                "Reconstructs the OS from a 'resource manager' to an 'intent filter' — agents submit structured intent declarations instead of requesting low-level POSIX resources directly",
                "Traditional POSIX syscall interface exposes general-purpose primitives (files, networks, processes, memory, exec) that a compromised agent runtime can combine into arbitrary attack behaviors beyond task authorization",
                "System dynamically synthesizes a least-capability environment from the Manifest and enforces mandatory mediation, auditing, and information-flow control",
                "Addresses prompt injection, supply-chain poisoning, and malicious tool outputs that can hijack agent runtimes with full POSIX access"
            ],
            "relevance": "The most radical OS security redesign for AI agents in the corpus (from Tencent). While ActPlane (batch 001) adds eBPF policy enforcement and Governed MCP (batch 007) adds kernel-resident tool governance, AgenticOS proposes replacing the POSIX interface entirely for agent workloads. The intent-based model is a fundamental departure from the kernel's syscall architecture — instead of the kernel providing primitives that processes compose, the kernel interprets intent and synthesizes a sandboxed environment. This has implications for the kernel's LSM framework, seccomp, and namespace isolation: all would need to be orchestrated by an intent-interpreting layer.",
            "methodology": "Tencent. OS architecture design with intent declarations, least-capability synthesis, and mandatory mediation. Threat model covering prompt injection, supply-chain poisoning, and tool output attacks."
        },
        "concepts": ["Linux Security Modules", "Seccomp-BPF", "Namespaces", "Process Creation (fork/clone)"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "POSIX syscall interface enables agent runtime exploitation",
             "description": "POSIX exposes general-purpose resource primitives to processes. Once an agent runtime is compromised (prompt injection, supply-chain poisoning, malicious tool outputs), an attacker can combine file, network, process, and exec primitives into behaviors far beyond task authorization."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Intent-oriented OS replacing POSIX for agent workloads",
             "description": "AgenticOS replaces direct resource requests with structured intent declarations. The OS synthesizes a least-capability environment per-task and enforces mandatory mediation with information-flow control. Agents never access raw POSIX primitives."}
        ]
    },

    # ── 2. Edera: High-Performance Hypervisor Isolation ─────────────
    {
        "ev_id": "ev-arxiv-b8bed85d",
        "brief": {
            "key_ideas": [
                "Optimized type-1 hypervisor achieving both the isolation of hypervisor virtualization and the performance of OS-level containerization — no existing system previously achieved both",
                "Uses paravirtualization to improve hypervisor VM runtime to container-level performance: 0.9% slower CPU, 3% faster syscalls on average, comparable memory performance to Docker",
                "Kubernetes-compatible container runtime as drop-in replacement — works with all Kubernetes ecosystem tooling without modification",
                "Driver isolation: isolates hardware drivers (networking, storage, GPUs) from the hypervisor and other applications, protecting against driver vulnerabilities"
            ],
            "relevance": "Directly addresses the container escape problem that motivated secure containers (Kata, gVisor, ParaCell). While ParaCell (batch 005) optimizes within the KVM model, Edera replaces it entirely with a purpose-built type-1 hypervisor. The paravirtualization achieving Docker-level performance means the isolation-performance tradeoff is finally resolved. The driver isolation feature is particularly relevant to the kernel — it isolates GPU/NIC/storage drivers in separate VMs, preventing driver bugs from compromising the hypervisor. This is the hardware isolation equivalent of the kernel's VFIO device passthrough.",
            "methodology": "Type-1 hypervisor implementation with paravirtualization. Kubernetes container runtime integration. Performance comparison against Docker. Driver isolation for networking, storage, and GPUs."
        },
        "concepts": ["KVM (Kernel-based Virtual Machine)", "Namespaces", "Control Groups (cgroups v2)", "VFIO (Virtual Function I/O)"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "Container shared kernel enables escape attacks",
             "description": "Container isolation shares the kernel between tenants, presenting a large attack surface. Container escape attacks exploit kernel vulnerabilities to break OS-level virtualization. No existing system achieved both hypervisor isolation and container performance."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Type-1 hypervisor with container-level performance and driver isolation",
             "description": "Edera achieves hypervisor isolation with paravirtualized container performance (0.9% slower CPU, 3% faster syscalls vs Docker). Drop-in Kubernetes runtime. Driver isolation protects against networking/storage/GPU driver vulnerabilities."}
        ]
    },

    # ── 3. SYSSPEC: LLM-Generated File Systems ─────────────────────
    {
        "ev_id": "ev-arxiv-e090da61",
        "brief": {
            "key_ideas": [
                "Proposes generative file systems: LLMs generate and evolve a file system from specifications rather than manual development — addressing the overhead of file system development, bug fixing, and maintenance",
                "Key insight: replace ambiguous natural language prompts with principles from formal methods — SYSSPEC uses a multi-part specification describing functionality, modularity, and concurrency",
                "DAG-structured patches operate on the specification itself, enabling new features without violating existing invariants — evolution is specification-first, not code-first",
                "Generates SPECFS, a concurrent file system with equivalent correctness to manually-coded baseline across hundreds of regression tests. Seamlessly integrates 10 real-world Ext4 features"
            ],
            "relevance": "Proposes a paradigm shift in kernel filesystem development: specification-guided LLM generation instead of manual coding. SPECFS demonstrates that LLMs can produce correct, concurrent kernel file system code when guided by formal specifications. The 10 Ext4 features seamlessly integrated show practical kernel feature parity. The DAG-structured specification patches mirror the kernel's own patch-based development model. This is relevant to the kernel community's discussion about AI-assisted kernel development — showing that specification-first (not prompt-first) is the viable path.",
            "methodology": "Formal specification framework with LLM-based code generation. SPECFS concurrent file system. Regression testing against manually-coded baseline. 10 Ext4 feature evolution. LLM agent toolchain with anti-hallucination mechanisms."
        },
        "concepts": ["Virtual Filesystem Switch", "ext4 Journaling Filesystem"],
        "claims": [
            {"kind": "Proposal", "id_prefix": "prop", "name": "Specification-guided LLM generation of file systems",
             "description": "SYSSPEC replaces ambiguous prompts with formal specifications (functionality, modularity, concurrency) to guide LLMs in generating correct file systems. DAG-structured patches on the specification enable evolution without invariant violation. Generated SPECFS passes hundreds of regression tests and integrates 10 Ext4 features."},
            {"kind": "Observation", "id_prefix": "obs", "name": "LLMs can generate correct concurrent filesystems with formal specs",
             "description": "With a multi-part formal specification replacing natural language, LLMs generate SPECFS with equivalent correctness to manually-coded baselines. Prior attempts at LLM-generated filesystems failed due to ambiguous prompts — the specification is the missing ingredient."}
        ]
    },

    # ── 4. nexpoline: Secure Syscall Interception ───────────────────
    {
        "ev_id": "ev-arxiv-4b190120",
        "brief": {
            "key_ideas": [
                "Transforms syscall instructions into a privilege reserved for the trusted monitor within the address space using MPK (Memory Protection Keys) — applications must switch contexts via nexpoline to execute syscalls",
                "Combines MPK with Seccomp or Syscall User Dispatch (SUD) for security, achieving better efficiency than ptrace-based interception through binary rewriting",
                "No kernel modifications required, works on current Linux without root privileges — making it deployable today",
                "Enables flexible user-defined policies for syscall mediation: supports complex policies beyond seccomp-bpf's limitations while matching ptrace's security guarantees"
            ],
            "relevance": "Directly improves the kernel's syscall interception mechanisms. The current options — ptrace (secure but slow), seccomp-bpf (fast but limited policies), SUD (newer but raw) — all have tradeoffs. nexpoline combines MPK with seccomp/SUD to get security + performance + flexibility. The binary rewriting approach to make syscall instructions privileged is a novel use of the kernel's MPK infrastructure. This is relevant to the kernel's seccomp, SUD, and MPK subsystems, and to the broader question of how the kernel should support sandboxing for browsers, WASM runtimes, and library OSes.",
            "methodology": "MPK + Seccomp/SUD combination. Binary rewriting for syscall privilege. Benchmark comparison against ptrace and firejail. Security analysis."
        },
        "concepts": ["Seccomp-BPF", "Linux Security Modules"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "Syscall interception tradeoff: security vs performance vs flexibility",
             "description": "ptrace is secure but requires expensive kernel-userspace context switches. seccomp-bpf is fast but supports only limited policies. Syscall User Dispatch is newer but provides raw interception. No existing mechanism provides all three: security, performance, and flexible policies."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "MPK-based privileged syscall instruction with seccomp/SUD",
             "description": "nexpoline uses MPK to make syscall instructions a privilege of the trusted monitor. Applications must switch context via nexpoline to syscall. Combined with seccomp/SUD for security. No kernel modifications, works unprivileged on current Linux."}
        ]
    },

    # ── 5. BPL: Batched Priority Lock for RT Kernels ────────────────
    {
        "ev_id": "ev-arxiv-0c32bf24",
        "brief": {
            "key_ideas": [
                "Batched Priority Lock (BPL): groups waiting tasks by lock request order, then selects next holder by priority within the batch — compromise between strict priority (starvation risk) and FIFO (no priority benefit)",
                "Same worst-case waiting bound as FIFO locks but with reduced average delay for higher-priority tasks — predictable yet priority-aware",
                "Working implementation on 8-core machine with a real RTOS and simulations up to 64 cores — practical for production real-time kernels",
                "Common-case execution overhead shown to be inexpensive relative to simple spinlocks — acceptable cost for predictability"
            ],
            "relevance": "Directly relevant to the Linux kernel's locking subsystem. The kernel's spinlocks use ticket or queued variants (MCS) that are FIFO — they provide bounded waiting but no priority awareness. For PREEMPT_RT Linux, priority inversion in kernel spinlocks is a known problem. BPL provides a principled solution: bounded delay like FIFO but with priority benefits. This could be applied to the kernel's rt_mutex (which does priority inheritance but is heavier) or to a new priority-aware spinlock variant for real-time paths.",
            "methodology": "Lock algorithm design and analysis. Working implementation on 8-core RTOS. Simulation up to 64 cores. Comparison against FIFO, strict priority, and simple spinlocks."
        },
        "concepts": ["Spinlock", "Scheduling Classes"],
        "claims": [
            {"kind": "Proposal", "id_prefix": "prop", "name": "Batched Priority Lock with bounded delay and priority awareness",
             "description": "BPL groups waiting tasks by request order into batches, then selects the next lock holder by priority within each batch. Provides same worst-case bound as FIFO while reducing average delay for higher-priority tasks. Practical implementation on 8-core RTOS, simulated to 64 cores."}
        ]
    },

    # ── 6. Flexible Swapping for Cloud VMs ──────────────────────────
    {
        "ev_id": "ev-arxiv-77b49c0c",
        "brief": {
            "key_ideas": [
                "Userspace memory management framework for VMs enabling custom reclaim/prefetch policies — full control over VM memory using a simple API, unlike the kernel's general-purpose swap that isn't optimized for VMs",
                "Supports huge page-based swapping (required for VM performance), easy deployment on Linux/KVM, and zero-copy I/O virtualization with shared VM memory",
                "Outperforms Linux kernel baseline by up to 25% while saving similar memory through custom workload-specific reclaimers and prefetchers",
                "Custom policies save 10% additional memory, improve limited-memory performance by 30% over Linux baseline, and recover faster from hard memory limit releases"
            ],
            "relevance": "Directly addresses the Linux kernel's swap subsystem limitations for VM workloads. The kernel's general-purpose swap (kswapd, zswap, swap partitions) doesn't account for VM-specific access patterns. This framework moves reclaim policy to userspace while keeping the kernel's KVM and memory management as the execution layer. The huge page-based swapping is critical — the kernel's current swap doesn't handle THP well for VMs. The 25% improvement over the kernel baseline quantifies the cost of the kernel's one-size-fits-all swap policy for VM workloads.",
            "methodology": "Userspace framework on Linux/KVM. Custom reclaim and prefetch policies. Huge page-based swapping. Comparison against Linux kernel baseline on micro-benchmarks and cloud workloads."
        },
        "concepts": ["KVM (Kernel-based Virtual Machine)", "Page Reclaim (kswapd/direct)", "Transparent Huge Pages", "Memory Ballooning"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "Linux kernel swap not optimized for VM workloads",
             "description": "General-purpose OS swap mechanisms aren't designed for virtualized workloads, missing memory-saving opportunities and lacking huge page-based swapping required for VM performance. Custom prefetchers cannot be implemented in the kernel's swap path."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Userspace VM memory management with custom swap policies",
             "description": "Framework enables custom reclaim/prefetch policies for VM memory with huge page support and zero-copy I/O virtualization. 25% better than Linux baseline, custom policies save 10% more memory and improve limited-memory performance by 30%."}
        ]
    },

    # ── 7. Guest-Side VM Memory Tiering Consolidation ───────────────
    {
        "ev_id": "ev-arxiv-e61713e8",
        "brief": {
            "key_ideas": [
                "Identifies that host-based memory tiering fails in VMs when frequently accessed data is scattered or skewed across guest physical pages — sparsely-hot huge pages get placed in expensive near memory, wasting capacity",
                "Host-agnostic technique inside the guest exploits two-level address translation to consolidate scattered/skewed accesses into dense guest physical ranges",
                "Transforms sparsely-hot huge pages into densely-hot huge pages from the host's perspective — host-based tiering then works correctly without modification",
                "50-70% reduction in near memory consumption at similar performance, or 10-13% performance improvement at similar memory TCO"
            ],
            "relevance": "Reveals a fundamental interaction between the kernel's memory tiering and virtualization. When the kernel runs as a host tiering system (AutoNUMA, DAMON), it sees guest physical addresses that don't reflect actual access patterns — scattered hot accesses make entire huge pages look hot. The guest-side consolidation is an elegant solution: the guest reorganizes its address space so the host sees correct hotness signals. This has direct implications for how KVM manages guest memory for CXL tiering — the host kernel cannot make correct tiering decisions without guest cooperation.",
            "methodology": "Guest-side address consolidation exploiting two-level translation. Evaluation with state-of-the-art host tiering systems. Near memory consumption and performance analysis."
        },
        "concepts": ["KVM (Kernel-based Virtual Machine)", "Adaptive CXL Memory Tiering", "NUMA Topology and Memory Policy", "Transparent Huge Pages", "Page Fault Handler"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "Host memory tiering misidentifies VM page hotness",
             "description": "Host-based tiering sees scattered/skewed access patterns across guest huge pages. A few hot subpages make the entire huge page look hot, placing sparsely-accessed data in expensive near memory. The host cannot distinguish dense from sparse hotness through the two-level address translation."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Guest-side access consolidation for host tiering correctness",
             "description": "Guest-side technique consolidates scattered accesses into dense guest physical ranges, transforming sparsely-hot into densely-hot huge pages from the host's perspective. 50-70% near memory reduction or 10-13% performance improvement without modifying host tiering."}
        ]
    },

    # ── 8. RDMA Page Fault Handling with ARM SMMU ───────────────────
    {
        "ev_id": "ev-arxiv-d74f635a",
        "brief": {
            "key_ideas": [
                "Implements page fault handling integrated with the DMA engine — faults detected by ARM SMMU (System Memory Management Unit) and resolved through hardware-software co-design with retransmission capability",
                "Addresses the fundamental problem that RDMA engines cannot tolerate page faults and must pin memory, which introduces complexity, limits memory capacity, and wastes resources",
                "Linux kernel's THP (Transparent Huge Pages) can cause page faults even on pinned memory — a fact that breaks the assumption that pinning prevents all faults",
                "Required modifications to Linux SMMU driver, new software library, DMA engine hardware changes, and DMA scheduling logic modifications"
            ],
            "relevance": "Directly modifies the Linux kernel's ARM SMMU driver for DMA page fault handling. The finding that Linux THP can cause faults even on pinned memory is critical — it means the kernel's memory pinning guarantee (used by RDMA, VFIO, and GPU drivers) is weaker than assumed. The page fault handling in the DMA path is relevant to the kernel's IOMMU subsystem and the ongoing work on device-side page fault support (IOPF). This is the embedded/FPGA perspective on the same problem that CXL memory disaggregation faces.",
            "methodology": "Hardware-software co-design on ExaNeSt FPGA platform (Xilinx Zynq UltraScale+). Linux SMMU driver modifications. Comparison against memory pinning and pre-faulting approaches."
        },
        "concepts": ["DMA Mapping Framework", "Page Fault Handler", "Transparent Huge Pages"],
        "claims": [
            {"kind": "FailureMode", "id_prefix": "fail", "name": "Linux THP causes page faults on pinned RDMA memory",
             "description": "Linux Transparent Huge Pages can cause page faults even on memory that has been pinned for RDMA, because THP optimization mechanisms (splitting, compaction) operate on pinned pages. This breaks the assumption that pinning prevents all DMA faults."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "DMA engine page fault handling via ARM SMMU",
             "description": "Page faults detected by ARM SMMU during DMA operations are resolved through hardware-software co-design with retransmission capability. Requires modifications to Linux SMMU driver, new software library, and DMA engine hardware changes."}
        ]
    },

    # ── 9. Socarrat: Reverse File System for WORM Storage ──────────
    {
        "ev_id": "ev-arxiv-2851ad2e",
        "brief": {
            "key_ideas": [
                "Novel WORM (Write Once Read Many) storage using a simple USB device (single-board computer with USB OTG) that appears as an ordinary ext4/exFAT external disk — no specialized software or drivers needed",
                "Reverse File System: infers file system operations occurring at higher layers on the host by monitoring USB block-level I/O — the device reconstructs file-level semantics from block writes",
                "Isolates WORM enforcement in dedicated USB hardware module, reducing attack surface — even privileged host attackers cannot modify or erase stored data",
                "Tamper-evident design with resilience against advanced attacks. Open-source prototype in Go"
            ],
            "relevance": "A creative inversion of the kernel's storage stack: instead of the filesystem talking to the block device, the block device infers what the filesystem is doing by analyzing block I/O patterns. This 'reverse file system' concept is relevant to the kernel's block device layer and USB mass storage class driver. The approach of inferring ext4 operations from block writes requires deep understanding of the kernel's filesystem-to-block-device I/O path. Also relevant to the kernel's USB gadget framework (the device side of USB OTG that presents as a mass storage device).",
            "methodology": "USB device implementation with Linux USB OTG. Reverse File System inferring filesystem operations from block I/O. Ext4 and exFAT support. Go prototype. Performance evaluation on single-board computers."
        },
        "concepts": ["Block Device Layer", "USB Subsystem", "ext4 Journaling Filesystem", "Virtual Filesystem Switch"],
        "claims": [
            {"kind": "Proposal", "id_prefix": "prop", "name": "Reverse File System inferring operations from block I/O for WORM",
             "description": "Socarrat implements WORM storage by isolating enforcement in a USB hardware module. A Reverse File System infers host filesystem operations by analyzing block-level USB I/O patterns, enforcing immutability even against privileged host attackers. Appears as ordinary ext4/exFAT disk."}
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
