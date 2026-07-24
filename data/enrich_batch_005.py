"""Deep enrichment batch 005: 11 papers with full ResearchBrief + structured claims.

Papers:
1. ParaCell — Paravirtualized secure containers with MPK-based intra-container isolation
2. RESYSTANCE — eBPF+io_uring to offload LSM-tree compaction into the kernel
3. uringscope — CO-RE eBPF observability for io_uring
4. UEFI Memory Forensics — Framework for UEFI runtime memory analysis
5. Fork, Explore, Commit — OS branch context abstraction for agent exploration
6. gpu_ext — eBPF-based extensible OS policies for GPUs
7. Peacock — UEFI firmware runtime observability for bootkit detection
8. page_leap — User-space fine-grained NUMA page migration
9. eBeeMetrics — eBPF-based QoS metrics observation framework
10. Yaksha-Prashna — eBPF bytecode network function verification
11. OBASE — Object-based address-space engineering for memory tiering
"""
import json, sqlite3, uuid

DB_PATH = "data/master.db"

ALL_PAPERS = [
    # ── 1. ParaCell: Paravirtualized Secure Containers ───────────────
    {
        "ev_id": "ev-arxiv-paracell",
        "brief": {
            "key_ideas": [
                "Identifies two root causes of the isolation-performance tradeoff in secure containers: (1) lack of lightweight intra-container isolation for frequent user-kernel transitions, (2) host treats container memory as opaque, forcing reactive secondary faults",
                "Uses Intel MPK-based XGates for intra-container isolation — container user and container kernel share a single address space with hardware-enforced domain boundaries, turning frequent user-kernel transitions into direct domain switches",
                "Introduces Pager, which interposes on container kernel allocation/free events to batch proactive GPA→HPA bindings and avoid reactive shadow page-table faults while preserving fine-grained memory elasticity",
                "Drop-in replacement for RunV: reduces latency by up to 57%/79% over PVM and 33%/88% over RunV in bare-metal/nested setups. Saves 35.6% memory on agent workloads"
            ],
            "relevance": "Core work on the kernel's container isolation stack. ParaCell addresses the performance cost of KVM-based secure containers (like Kata Containers/RunV) by replacing VM exits with MPK domain switches. The Pager component directly modifies how the host kernel manages guest physical memory — proactive binding instead of reactive page faults. This is relevant to KVM's nested page table handling, virtio paravirtualization, and the kernel's MPK infrastructure. The agent workload optimization (bursty memory demand with fine-grained elasticity) is a new use case for kernel memory management.",
            "methodology": "Linux implementation as RunV drop-in replacement. MPK-based XGates for domain isolation. Pager for proactive memory binding. Evaluation on bare-metal and nested (cloud) setups with traditional and agent workloads."
        },
        "concepts": ["KVM (Kernel-based Virtual Machine)", "Control Groups (cgroups v2)", "Virtio Paravirtual I/O", "Page Fault Handler", "Namespaces"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "Secure containers suffer isolation-performance tradeoff",
             "description": "VM-based secure containers (Kata/RunV) isolate each container with its own kernel, but nested-cloud deployments amplify VM exit costs and shadow page-table management overhead. Agentic workloads expose bursty memory demand that requires fine-grained elasticity incompatible with coarse huge page mappings."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "MPK-based intra-container isolation with proactive memory binding",
             "description": "ParaCell uses Intel MPK XGates for lightweight intra-container user/kernel isolation within a single address space. Pager interposes on allocation/free events to batch proactive GPA→HPA bindings, avoiding reactive shadow page-table faults."},
            {"kind": "PerformanceProfile", "id_prefix": "perf", "name": "ParaCell latency reduction vs RunV and PVM",
             "description": "Up to 57%/79% latency reduction over PVM and 33%/88% over RunV in bare-metal/nested setups. 35.6% memory savings on agent workloads through fine-grained memory elasticity."}
        ]
    },

    # ── 2. RESYSTANCE: eBPF+io_uring for LSM-tree Compaction ────────
    {
        "ev_id": "ev-arxiv-resystance",
        "brief": {
            "key_ideas": [
                "Identifies that LSM-tree background compaction generates massive numbers of read system calls, causing significant overhead now that NVMe SSDs have shifted the I/O bottleneck from hardware to software",
                "Offloads compaction I/O into the kernel using eBPF — handles key I/O routines directly inside the kernel without modifying the LSM-tree structure or compaction algorithm",
                "Combines eBPF (kernel-side logic) with io_uring (async batched I/O) to minimize user-kernel transitions during compaction — 99% reduction in system call invocations",
                "On RocksDB: 50% shorter compaction time, up to 75% throughput improvement in write-intensive workloads, 40% reduction in p99 latency"
            ],
            "relevance": "Demonstrates a powerful combination of two kernel mechanisms — eBPF for in-kernel logic execution and io_uring for async I/O — to eliminate the software overhead of a critical storage workload. This is significant because it shows eBPF can be used not just for observability/networking/security but for I/O path optimization in storage systems. The 99% syscall reduction validates the kernel-bypass-without-kernel-bypass pattern: using eBPF to bring application logic into the kernel rather than bypassing the kernel entirely (like SPDK).",
            "methodology": "eBPF+io_uring implementation for RocksDB compaction. Evaluation with db_bench, YCSB, and OLTP workloads. System call counting, compaction time, throughput, and tail latency measurement."
        },
        "concepts": ["eBPF (Extended Berkeley Packet Filter)", "io_uring", "NVMe Driver Subsystem", "Block Device Layer"],
        "claims": [
            {"kind": "Observation", "id_prefix": "obs", "name": "NVMe shifts I/O bottleneck from hardware to software",
             "description": "Modern NVMe SSDs deliver several GB/s bandwidth and microsecond latency, but each I/O request still incurs multiple system calls and kernel-user context switches. The I/O bottleneck has shifted from storage hardware to the software I/O stack."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "eBPF+io_uring kernel-side compaction for LSM-trees",
             "description": "RESYSTANCE offloads LSM-tree compaction I/O into the kernel using eBPF for logic execution and io_uring for async batched I/O. Minimizes user-kernel transitions without modifying the compaction algorithm. 99% reduction in system call invocations."},
            {"kind": "PerformanceProfile", "id_prefix": "perf", "name": "RESYSTANCE 75% throughput improvement on RocksDB",
             "description": "50% shorter compaction time. Write-intensive workloads: up to 75% throughput improvement and 40% p99 latency reduction on RocksDB. 99% fewer system calls during compaction."}
        ]
    },

    # ── 3. uringscope: io_uring Observability ────────────────────────
    {
        "ev_id": "ev-arxiv-iouring-scope",
        "brief": {
            "key_ideas": [
                "Addresses io_uring's fundamental observability gap: strace sees only ring setup calls, not the millions of I/O requests flowing through shared-memory rings — io_uring is fast but invisible",
                "Precise request lifecycle model with method to reconstruct per-request flows from unstable kernel tracepoints using CO-RE (Compile Once, Run Everywhere) eBPF — portable across kernel versions",
                "Novel technique for attaching to unstable tracepoint surfaces using BTF-probed program variants, CO-RE field flavors, and position-independent reads",
                "Aggregate mode costs 0.7-9.9% throughput on device-bound NVMe workloads — cheaper than every full-fidelity alternative. Includes built-in doctor that turns measurements into named pathologies with evidence"
            ],
            "relevance": "Fills a critical gap in the kernel's observability story. io_uring deliberately bypasses the syscall interface for performance, but this makes traditional tracing tools (strace, perf trace) ineffective. uringscope shows how eBPF can reconstruct per-request observability for subsystems that bypass syscalls. The CO-RE portability technique for unstable tracepoints is broadly applicable — many kernel subsystems have tracepoints that change across versions. The pathology detector (doctor) is a novel pattern for kernel observability: not just collecting data but diagnosing problems.",
            "methodology": "CO-RE eBPF implementation targeting io_uring kernel tracepoints. Request lifecycle reconstruction. BTF-probed portability across kernel versions. NVMe workload evaluation. Comparison against alternatives."
        },
        "concepts": ["io_uring", "eBPF (Extended Berkeley Packet Filter)", "Ftrace"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "io_uring makes I/O invisible to traditional tracing",
             "description": "io_uring submits I/O through shared-memory rings, bypassing syscalls. strace sees only io_uring_enter calls (or none with SQPOLL). A busy application may issue millions of requests with zero traceable syscalls. The kernel tracepoints that expose request flow are not stable ABI."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "CO-RE eBPF observability for io_uring with pathology detection",
             "description": "uringscope reconstructs per-request io_uring flows using CO-RE eBPF with BTF-probed variants for cross-kernel portability. Built-in doctor diagnoses named pathologies with evidence from measurements."},
            {"kind": "PerformanceProfile", "id_prefix": "perf", "name": "uringscope 0.7-9.9% overhead on NVMe workloads",
             "description": "Aggregate mode costs 0.7-9.9% throughput on device-bound NVMe workloads, cheaper than every full-fidelity alternative measured."}
        ]
    },

    # ── 4. UEFI Memory Forensics ────────────────────────────────────
    {
        "ev_id": "ev-arxiv-3a381759",
        "brief": {
            "key_ideas": [
                "First framework for capturing and analyzing volatile UEFI runtime memory to detect malicious exploitation during the pre-OS boot phase — no prior work has addressed UEFI memory forensics",
                "UEFIMemDump: memory acquisition tool that captures UEFI runtime memory. UEFIDumpAnalysis: extendable analysis modules detecting function pointer hooking, inline hooking, malicious image loading, and gadget-based control-flow manipulation",
                "Detects modern UEFI bootkits including Thunderstrike, CosmicStrand, Glupteba, LoJax, and MosaicRegressor",
                "Bridges the gap between mature OS-level memory forensics (Volatility, Rekall) and the below-OS firmware layer where no equivalent tools existed"
            ],
            "relevance": "Directly relevant to the kernel's boot security chain. UEFI firmware executes with high privileges and persists across reboots — if compromised, it can tamper with the kernel before it loads. Current protections (Secure Boot, signature verification) are static; this framework provides dynamic runtime analysis of UEFI memory. The detection of function pointer hooking and control-flow manipulation in UEFI runtime services is critical because the kernel relies on EFI runtime services for hardware abstraction post-boot.",
            "methodology": "UEFI memory acquisition tool + extendable analysis framework. Detection of function pointer hooking, inline hooking, malicious image loading, gadget-based control-flow manipulation. Validation against real-world bootkits."
        },
        "concepts": ["EFI/UEFI Boot and Runtime Services"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "No UEFI memory forensics tools exist",
             "description": "Memory forensics is foundational to incident response at the OS level (Volatility, Rekall, MemProcFS), but no prior work addresses capturing and analyzing volatile UEFI runtime memory. This gap prevents detecting firmware-level threats during the pre-OS phase."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "UEFI runtime memory forensics framework",
             "description": "UEFIMemDump captures UEFI runtime memory. UEFIDumpAnalysis provides extendable modules detecting function pointer hooking, inline hooking, malicious image loading, and gadget-based control-flow manipulation in UEFI runtime."},
            {"kind": "FailureMode", "id_prefix": "fail", "name": "Real-world UEFI bootkits detected by framework",
             "description": "Framework detects Thunderstrike, CosmicStrand, Glupteba, LoJax, BlackLotus, and MosaicRegressor bootkits through UEFI memory analysis — threats that bypass OS-level security entirely."}
        ]
    },

    # ── 5. Fork, Explore, Commit: OS Primitives for Agents ──────────
    {
        "ev_id": "ev-arxiv-e7e60678",
        "brief": {
            "key_ideas": [
                "Introduces the branch context, a new OS abstraction for AI agent exploration: provides copy-on-write state isolation with independent filesystem views and process groups, structured fork/explore/commit lifecycle, and first-commit-wins resolution",
                "BranchFS: FUSE-based filesystem giving each branch context an isolated CoW workspace with O(1) creation, atomic commit to parent, and automatic sibling invalidation — all without root privileges",
                "Proposes branch() as a new Linux syscall that spawns processes into branch contexts with kernel-enforced sibling isolation, reliable termination, and first-commit-wins coordination",
                "Sub-350 microsecond branch creation independent of base filesystem size; modification-proportional commit overhead (under 1ms for small changes)"
            ],
            "relevance": "Proposes a new Linux syscall (branch()) — the most ambitious kernel extension proposal in this batch. The branch context abstraction is a direct generalization of fork(): where fork() duplicates process state, branch() duplicates filesystem + process state as a first-class unit. BranchFS as a FUSE prototype validates the design without kernel modification. The first-commit-wins semantics map to optimistic concurrency control in the kernel's VFS layer. This has implications for the kernel's namespace, mount, and process management subsystems.",
            "methodology": "OS abstraction design. BranchFS FUSE prototype (open source). Proposed branch() Linux syscall specification. Performance evaluation of branch creation and commit latency."
        },
        "concepts": ["Process Creation (fork/clone)", "FUSE (Filesystem in Userspace)", "Namespaces", "Virtual Filesystem Switch"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "No OS primitive for agent exploration with atomic rollback",
             "description": "AI agents need isolated environments for parallel exploration with atomic commit/rollback for both filesystem and process state. Existing primitives (fork, containers, VMs) provide either isolation or performance but not both with the right semantics."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Branch context OS abstraction with FUSE prototype and proposed syscall",
             "description": "The branch context provides CoW state isolation, fork/explore/commit lifecycle, first-commit-wins resolution, and nestable contexts. BranchFS (FUSE) validates the design; branch() is proposed as a Linux syscall for kernel-native implementation."},
            {"kind": "PerformanceProfile", "id_prefix": "perf", "name": "Branch creation under 350us independent of filesystem size",
             "description": "Sub-350 microsecond branch creation independent of base filesystem size via CoW semantics. Commit overhead proportional to modifications only (under 1ms for small changes)."}
        ]
    },

    # ── 6. gpu_ext: eBPF for GPU OS Policies ────────────────────────
    {
        "ev_id": "ev-arxiv-d5969348",
        "brief": {
            "key_ideas": [
                "Argues the GPU driver and device layer should provide an extensible OS interface for policy enforcement — treats the GPU driver as a programmable OS subsystem analogous to how eBPF treats the network stack",
                "Extends GPU drivers with safe programmable hooks and introduces a device-side eBPF runtime capable of executing verified policy logic within GPU kernels — enabling coherent host+device policies",
                "Addresses the tradeoff between user-space runtimes (flexible but lack cross-tenant visibility) and kernel modifications (powerful but complex and risky)",
                "Up to 4.8x throughput improvement and 2x tail latency reduction across inference, training, and vector search workloads without application modification"
            ],
            "relevance": "Extends the eBPF paradigm from CPU-side kernel subsystems to GPU drivers — a significant conceptual leap. If GPUs are OS-managed resources (like CPUs, memory, network), their drivers should be extensible like the network stack (XDP), scheduler (sched_ext), and page cache (cachebpf). The device-side eBPF runtime running within GPU kernels pushes eBPF verification and safety guarantees to a new execution domain. This has direct implications for the kernel's GPU driver model (DRM/KMS) and how the kernel manages GPU resources for multi-tenant workloads.",
            "methodology": "eBPF-based GPU driver extension framework. Host-side and device-side eBPF hooks. Evaluation on inference, training, and vector search workloads."
        },
        "concepts": ["eBPF (Extended Berkeley Packet Filter)"],
        "claims": [
            {"kind": "Proposal", "id_prefix": "prop", "name": "eBPF-extensible GPU driver as programmable OS subsystem",
             "description": "gpu_ext extends GPU drivers with safe programmable eBPF hooks and introduces a device-side eBPF runtime for verified policy logic within GPU kernels. Enables coherent, transparent GPU resource management policies across host and device."},
            {"kind": "PerformanceProfile", "id_prefix": "perf", "name": "gpu_ext 4.8x throughput improvement",
             "description": "Up to 4.8x throughput improvement and 2x tail latency reduction across inference, training, and vector search workloads without modifying or restarting applications."}
        ]
    },

    # ── 7. Peacock: UEFI Runtime Observability ──────────────────────
    {
        "ev_id": "ev-arxiv-7e17eb6c",
        "brief": {
            "key_ideas": [
                "Introduces integrity-assured monitoring and remote verification for the UEFI boot process — fills the gap where OS environments have mature inspection tools but pre-OS firmware has none",
                "Three components: (1) UEFI agent recording Boot/Runtime Service activity with cryptographic tamper protection, (2) OS Agent extracting measurements with hardware-backed TPM attestation, (3) Peacock Server verifying attestation and exporting structured telemetry",
                "Detects real-world UEFI bootkits: Glupteba, BlackLotus, LoJax, MosaicRegressor — threats that bypass Secure Boot and OS-level security",
                "Provides practical visibility into the firmware layer for enterprise detection pipelines"
            ],
            "relevance": "Complements the UEFI Memory Forensics paper by providing real-time monitoring (vs post-incident forensics). The UEFI agent intercepts Boot and Runtime Service calls — the same interfaces the kernel uses via EFI runtime services. The TPM-based attestation chain extends the kernel's integrity measurement architecture (IMA) down into firmware. This is critical for the kernel's Secure Boot chain: if firmware is compromised before the kernel loads, all kernel-level security is undermined.",
            "methodology": "UEFI firmware agent + OS agent + verification server. Cryptographic integrity protection. TPM-based hardware attestation. Detection validation against real-world bootkits."
        },
        "concepts": ["EFI/UEFI Boot and Runtime Services"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "No runtime visibility into UEFI boot process",
             "description": "Existing UEFI protections (Secure Boot, signature verification) are static and cannot detect runtime manipulation. The pre-OS stage lacks practical mechanisms for real-time visibility and threat detection, unlike the mature tooling available at the OS level."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "TPM-attested UEFI runtime monitoring with bootkit detection",
             "description": "Peacock monitors UEFI Boot/Runtime Service activity with cryptographic integrity, extracts measurements via TPM-backed attestation, and exports structured telemetry for enterprise detection. Detects Glupteba, BlackLotus, LoJax, and MosaicRegressor bootkits."}
        ]
    },

    # ── 8. page_leap: User-Space NUMA Migration ─────────────────────
    {
        "ev_id": "ev-arxiv-11740903",
        "brief": {
            "key_ideas": [
                "Proposes page_leap(), a new user-space NUMA page migration method that exploits virtual memory subsystem features for high-performance asynchronous migration — addressing limitations of both AutoNUMA and move_pages()",
                "Six properties: (a) actively triggered by user, (b) guarantees all pages eventually migrate, (c) handles concurrent writes correctly, (d) supports pooled memory, (e) adaptively adjusts migration granularity based on workload, (f) supports both small and huge pages",
                "Identifies fundamental downsides of kernel-provided alternatives: AutoNUMA's automatic balancing has unpredictable behavior, move_pages() is synchronous and blocks the calling thread",
                "Achieves high-performance NUMA migration without kernel modification by exploiting page fault handling and mmap/mremap semantics"
            ],
            "relevance": "Directly addresses the Linux kernel's NUMA page migration infrastructure. The paper finds that both kernel-provided mechanisms (AutoNUMA and move_pages syscall) have significant limitations for database workloads. The page_leap() approach exploits the kernel's virtual memory subsystem (page faults, mmap, mremap) to achieve migration without modifying the kernel — demonstrating that the existing kernel interfaces, while limited individually, can be composed for high-performance migration. This is relevant to kernel memory management, NUMA balancing policy, and the move_pages() syscall design.",
            "methodology": "User-space implementation exploiting Linux VM subsystem features. Comparison against AutoNUMA and move_pages(). Multi-socket NUMA evaluation."
        },
        "concepts": ["NUMA Topology and Memory Policy", "AutoNUMA (Automatic NUMA Balancing)", "Page Fault Handler", "Huge Page Mapping"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "Kernel NUMA migration mechanisms have fundamental limitations",
             "description": "AutoNUMA's automatic balancing is unpredictable and cannot be actively directed. move_pages() is synchronous and blocks the calling thread. Neither supports adaptive migration granularity or pooled memory well."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "User-space NUMA migration exploiting VM subsystem features",
             "description": "page_leap() performs asynchronous NUMA page migration in user-space by exploiting page fault handling and mmap/mremap semantics. Supports active triggering, guaranteed completion, concurrent-write safety, pooled memory, adaptive granularity, and both small/huge pages."}
        ]
    },

    # ── 9. eBeeMetrics: eBPF QoS Observation ────────────────────────
    {
        "ev_id": "ev-arxiv-da006ade",
        "brief": {
            "key_ideas": [
                "Observes application-level QoS metrics (tail latency, throughput) from within the OS kernel using only eBPF-observable events like system calls — without application instrumentation",
                "Drop-in replacement to decouple system management runtimes (resource management, power management) from application-specific QoS metric reporting",
                "Achieves strong correlation with real-world measured throughput and latency across various latency-sensitive workloads",
                "Open-source eBPF-based library framework that supplements or replaces existing QoS feedback mechanisms"
            ],
            "relevance": "Demonstrates that eBPF can infer application-level metrics from kernel-observable events — bridging the gap between kernel observability (which sees syscalls, scheduling, I/O) and application metrics (which the kernel normally cannot see). This enables kernel-level resource management (CPU frequency scaling, memory tiering, scheduling) to react to application QoS without requiring application cooperation. Relevant to the kernel's power management and resource allocation subsystems.",
            "methodology": "eBPF-based implementation deriving QoS metrics from syscall patterns. Correlation analysis with ground-truth application metrics. Open-source tool evaluation across latency-sensitive workloads."
        },
        "concepts": ["eBPF (Extended Berkeley Packet Filter)", "Perf Events Subsystem"],
        "claims": [
            {"kind": "Proposal", "id_prefix": "prop", "name": "eBPF-derived application QoS metrics without instrumentation",
             "description": "eBeeMetrics derives application-level tail latency and throughput metrics from eBPF-observable kernel events (syscalls) without requiring application instrumentation. Can be used as drop-in QoS feedback for system management runtimes."},
            {"kind": "Observation", "id_prefix": "obs", "name": "Syscall patterns correlate strongly with application QoS",
             "description": "eBPF-observable events (system calls, their timing, and sequencing) correlate strongly with real-world application throughput and latency metrics across various latency-sensitive workloads."}
        ]
    },

    # ── 10. Yaksha-Prashna: eBPF Bytecode Verification ──────────────
    {
        "ev_id": "ev-arxiv-b887dad6",
        "brief": {
            "key_ideas": [
                "Enables operators to verify eBPF network function bytecode conformance to specifications without requiring source code — critical for third-party eBPF programs from vendors like F5 and Palo Alto",
                "Builds domain-specific models for eBPF programs enabling scalable program analysis to extract and model behavior from bytecode alone",
                "Yaksha-Prashna language expresses 24 properties on standard and non-standard eBPF network functions with 200-1000x speedup over state-of-the-art verification",
                "Addresses the trust gap in eBPF ecosystem: third-party bytecode gives operators little understanding of functional correctness and interaction with other network functions in a chain"
            ],
            "relevance": "Addresses a growing security concern in the eBPF ecosystem: as organizations deploy third-party eBPF programs (from security vendors, observability platforms), operators need to verify what these programs actually do. The kernel's eBPF verifier checks safety (memory safety, termination) but not functional correctness or behavioral properties. Yaksha-Prashna fills this gap with bytecode-level verification. This complements Heimdall (eBPF C-to-Rust migration) — both address the trustworthiness of eBPF programs beyond what the kernel verifier checks.",
            "methodology": "Domain-specific program analysis for eBPF bytecode. Yaksha-Prashna property specification language. 24 properties across standard and non-standard network functions. Performance comparison against state-of-the-art."
        },
        "concepts": ["eBPF (Extended Berkeley Packet Filter)"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "Third-party eBPF bytecode is functionally opaque",
             "description": "Cloud operators deploy third-party eBPF network functions (from F5, Palo Alto, etc.) as bytecode with no understanding of functional correctness or interaction with other network functions in a chain. The kernel verifier checks safety but not behavioral properties."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Bytecode-level eBPF behavioral verification",
             "description": "Yaksha-Prashna builds domain-specific models enabling scalable analysis of eBPF bytecode. A property language expresses 24 behavioral properties with 200-1000x speedup over state-of-the-art, without requiring source code."}
        ]
    },

    # ── 11. OBASE: Object-Based Address-Space Engineering ────────────
    {
        "ev_id": "ev-arxiv-91f7da72",
        "brief": {
            "key_ideas": [
                "Identifies hotness fragmentation as the root cause of DRAM overprovisioning: allocators place objects by size rather than access pattern, so hot and cold objects interleave within pages — a single hot object traps surrounding cold data in expensive DRAM",
                "Quantifies the problem at scale: in Google production workloads, up to 97% of bytes in active pages are cold and unreclaimable by the kernel's page-level tiering",
                "Proposes address-space engineering: dynamically reorganizing virtual memory so hot objects cluster into uniformly hot pages and cold objects into uniformly cold pages — enabling unmodified kernel backends (kswapd, TPP, Memtis) to tier effectively",
                "OBASE: compiler-runtime system for unmanaged languages with lightweight pointer instrumentation and lock-free object migration. 2-4x page utilization improvement, up to 70% memory footprint reduction with 2-5% overhead"
            ],
            "relevance": "Directly addresses why the kernel's page-level memory tiering fails in practice. The finding that 97% of bytes in active pages are cold at Google is devastating for kernel tiering — it means the kernel's page reclaim, NUMA balancing, and CXL tiering are operating on contaminated signals. OBASE is an object-aware frontend that makes page-aware kernel backends (kswapd, TPP, Memtis) work correctly by solving the fragmentation problem in userspace. This has profound implications for kernel memory management: the kernel's page-level view is fundamentally insufficient, and solutions must bridge the object-page boundary.",
            "methodology": "Compiler-runtime system with pointer instrumentation and lock-free migration. Evaluation with 10 concurrent data structures, 6 kernel backends, and production traces from Meta and Twitter."
        },
        "concepts": ["NUMA Topology and Memory Policy", "Page Reclaim (kswapd/direct)", "Adaptive CXL Memory Tiering", "Transparent Huge Pages"],
        "claims": [
            {"kind": "Observation", "id_prefix": "obs", "name": "97% of bytes in active pages are cold at Google",
             "description": "Hotness fragmentation: allocators place objects by size, interleaving hot and cold objects on the same page. A single hot object marks its page as active, trapping surrounding cold data in DRAM. In Google production, up to 97% of bytes in active pages are cold and unreclaimable."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Address-space engineering for object-page alignment",
             "description": "OBASE dynamically reorganizes virtual memory so hot objects cluster into uniformly hot pages and cold objects into uniformly cold pages. A compiler-runtime system with pointer instrumentation and lock-free migration serves as an object-aware frontend for page-aware kernel backends."},
            {"kind": "PerformanceProfile", "id_prefix": "perf", "name": "OBASE 2-4x page utilization improvement",
             "description": "2-4x page utilization improvement and up to 70% memory footprint reduction with only 2-5% overhead. Enables unmodified kernel backends (kswapd, TPP, Memtis) to tier memory effectively by solving object-page hotness fragmentation."}
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
