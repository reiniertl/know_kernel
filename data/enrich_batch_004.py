"""Deep enrichment batch 004: 13 papers — the richest remaining sources (full papers stored).

Papers:
1. eBPF Runtime — First comprehensive description of eBPF design/implementation in Linux
2. HybridTier — Adaptive CXL memory tiering with frequency + momentum tracking
3. UFS — sched_ext-based unfair scheduler for mixed database workloads
4. io_uring DBMS — When and how to use io_uring in high-performance database systems
5. NecoFuzz — First fuzzer targeting nested virtualization in KVM
6. CacheBPF — eBPF framework for customizing Linux page cache eviction
7. XLB — eBPF-based in-kernel L7 load balancer for microservices
8. TierBPF — eBPF hooks for page migration admission control in tiered memory
9. eBPF-PATROL — eBPF runtime security agent for containers/VMs
10. RCU Synchronization — Identifying Linux kernel instability from RCU misuse
11. BBR Default — Should BBR replace Cubic as default TCP congestion control
12. eBPF-mm — Userspace-guided huge page management via eBPF
13. XFS Zoned — Evolving XFS with zoned storage and intelligent data placement
"""
import json, sqlite3, uuid

DB_PATH = "data/master.db"

ALL_PAPERS = [
    # ── 1. eBPF Runtime in the Linux Kernel ──────────────────────────
    {
        "ev_id": "ev-arxiv-ebpf-runtime",
        "brief": {
            "key_ideas": [
                "First comprehensive description of the design and implementation of the eBPF runtime in the Linux kernel — covers the verifier, JIT compiler, map infrastructure, helper functions, and program types",
                "Argues eBPF has matured from a packet filter into a safe general-purpose programming environment for the kernel — increasingly used not just to extend but to program entire kernel components while preserving runtime integrity",
                "Documents the shift from kernel bypass (DPDK, library OS) to kernel cooperation via eBPF — working with the kernel rather than around it",
                "Identifies key challenges and future directions for eBPF: verifier scalability, program composability, cross-platform portability, and the tension between safety guarantees and expressiveness"
            ],
            "relevance": "The authoritative reference paper for the eBPF subsystem. Written by Red Hat and university researchers involved in eBPF development. Documents the internal architecture that every eBPF-related paper builds on: the verifier's safety model, JIT compilation pipeline, map types, hook points, and the kfunc interface. Essential for understanding why eBPF programs have the constraints they do and where the subsystem is heading.",
            "methodology": "Comprehensive system description with architectural analysis. Covers design rationale, implementation details, production use cases, and future challenges."
        },
        "concepts": ["eBPF (Extended Berkeley Packet Filter)"],
        "claims": [
            {"kind": "Observation", "id_prefix": "obs", "name": "eBPF has evolved from packet filter to kernel programming environment",
             "description": "eBPF today is used not just to extend but to program entire kernel components (scheduling via sched_ext, page cache via cachebpf, networking via XDP) while preserving runtime integrity through the verifier and JIT."},
            {"kind": "Observation", "id_prefix": "obs", "name": "Kernel cooperation outperforms kernel bypass",
             "description": "eBPF enables workload-specific kernel customization without the maintenance burden and feature regression of kernel bypass approaches (DPDK, library OS), while retaining the kernel's resource management and isolation guarantees."}
        ]
    },

    # ── 2. HybridTier: Adaptive CXL Memory Tiering ──────────────────
    {
        "ev_id": "ev-asplos25-hybridtier",
        "brief": {
            "key_ideas": [
                "Tracks both long-term data access frequency and short-term access momentum simultaneously — captures and adapts to dynamically shifting hotness distributions that single-signal trackers miss",
                "Reduces metadata memory overhead by tracking accesses probabilistically — trades a small tracking inaccuracy (negligible performance impact) for 2.0-7.8x less memory overhead than prior systems",
                "Optimizes for data locality in tracking data structures to reduce cache overhead — 1.7-3.5x fewer cache misses than prior tiering systems",
                "Outperforms prior CXL tiering systems by up to 91% (19% geomean) through the combination of dual-signal tracking, probabilistic metadata, and cache-friendly data structures"
            ],
            "relevance": "Directly addresses the Linux kernel's CXL memory tiering challenge. The dual-signal approach (frequency + momentum) is a direct improvement over the kernel's existing NUMA balancing which uses a single-signal (access bit scanning via NUMA hinting faults). The probabilistic tracking with reduced memory overhead is critical for kernel adoption — the kernel's page migration metadata must scale to TB-scale CXL memory without consuming significant DRAM. Published at ASPLOS 2025 with open-source artifact.",
            "methodology": "System design with dual-signal hotness tracking. ASPLOS 2025 publication. Open-source implementation. Evaluation against prior tiering systems (TPP, MEMTIS, etc.) on diverse workloads."
        },
        "concepts": ["Adaptive CXL Memory Tiering", "NUMA Topology and Memory Policy", "AutoNUMA (Automatic NUMA Balancing)", "Page Reclaim (kswapd/direct)"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "Single-signal hotness tracking fails on shifting distributions",
             "description": "Prior CXL tiering systems track only access frequency or only recency. When data hotness distributions shift dynamically (common in production), single-signal trackers either react too slowly (frequency) or thrash (recency)."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Dual-signal frequency+momentum hotness tracking for CXL",
             "description": "HybridTier simultaneously tracks long-term frequency and short-term momentum. Probabilistic metadata reduces memory overhead 2.0-7.8x. Cache-friendly data structures reduce cache misses 1.7-3.5x."},
            {"kind": "PerformanceProfile", "id_prefix": "perf", "name": "HybridTier 91% improvement over prior CXL tiering",
             "description": "Up to 91% improvement (19% geomean) over prior tiering systems with significantly lower memory and cache overhead. ASPLOS 2025 with open-source artifact."}
        ]
    },

    # ── 3. UFS: sched_ext Unfair Scheduler for Databases ────────────
    {
        "ev_id": "ev-arxiv-ufs-sched",
        "brief": {
            "key_ideas": [
                "Implements UFS (Unfair Scheduler) as a sched_ext eBPF scheduler in the Linux kernel — restricts background database tasks to idle CPU capacity and preempts them immediately when latency-sensitive tasks arrive",
                "Addresses priority inversion in database mixed workloads: incorporates application-level hints via eBPF maps so background tasks holding locks needed by high-priority tasks are not unnecessarily delayed",
                "Demonstrates that Linux's existing priority mechanisms (nice, SCHED_BATCH) do not reliably isolate high-priority database tasks from background work — motivating kernel-level scheduling customization",
                "Integrated into PostgreSQL: under mixed workloads, UFS improves throughput for time-sensitive tasks by up to 2x while reducing tail latency by half compared to existing Linux scheduling options"
            ],
            "relevance": "The most concrete demonstration of sched_ext's value for real workloads. sched_ext allows eBPF programs to implement custom scheduling policies — UFS is a production-quality example showing that database workloads need scheduling semantics that CFS/EEVDF cannot provide. The priority inversion solution via eBPF maps (application hints to the scheduler) is a novel kernel-userspace communication pattern. This validates the entire sched_ext design: kernel-level scheduling customized by application-specific policies.",
            "methodology": "sched_ext eBPF scheduler implementation. Integration into PostgreSQL. Evaluation under mixed database workloads (interactive queries + background UDFs/ML tasks). Comparison against CFS, SCHED_BATCH, nice priorities."
        },
        "concepts": ["sched_ext Extensible Scheduling", "eBPF (Extended Berkeley Packet Filter)", "Scheduling Classes", "Virtual Runtime Scheduling"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "Linux priorities fail to isolate database mixed workloads",
             "description": "Despite supporting priorities (nice, SCHED_BATCH), Linux schedulers do not reliably isolate high-priority database tasks from background work. Background CPU-bound tasks (ML training, materialized view refresh) interfere with interactive query latency."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "sched_ext-based unfair scheduler with application hints",
             "description": "UFS is a sched_ext eBPF scheduler that restricts background tasks to idle CPU capacity and preempts them immediately for latency-sensitive tasks. Application-level hints via eBPF maps prevent priority inversion when background tasks hold locks."},
            {"kind": "PerformanceProfile", "id_prefix": "perf", "name": "UFS 2x throughput improvement for database mixed workloads",
             "description": "In PostgreSQL under mixed workloads: UFS improves time-sensitive task throughput by up to 2x and reduces tail latency by half compared to existing Linux scheduling options."}
        ]
    },

    # ── 4. io_uring for High-Performance DBMSs ──────────────────────
    {
        "ev_id": "ev-arxiv-iouring-dbms",
        "brief": {
            "key_ideas": [
                "Systematic study of when io_uring delivers benefits over traditional Linux I/O interfaces in database systems — naively replacing traditional I/O with io_uring does not necessarily yield performance benefits",
                "Evaluates two use cases: storage-bound buffer manager (io_uring for async page I/O) and network-bound analytical shuffling (io_uring for high-throughput data transfer)",
                "Analyzes advanced io_uring features: registered buffers (pre-pinned memory), passthrough I/O (bypassing filesystem layer), and their end-to-end impact on database performance",
                "Derives practical guidelines for io_uring integration and validates them on PostgreSQL's recent io_uring integration — applying the guidelines yields 14% performance improvement"
            ],
            "relevance": "The definitive study on io_uring's practical impact for database I/O workloads. Directly relevant to the kernel's io_uring subsystem and its interaction with the VFS, page cache, and block I/O layers. The finding that naive io_uring adoption doesn't help is crucial — it shows that io_uring's benefits depend on matching the submission/completion model to the application's I/O pattern. The PostgreSQL case study is particularly relevant as PostgreSQL is integrating io_uring upstream. Published in PVLDB 2026.",
            "methodology": "Experimental study with microbenchmarks and end-to-end database workloads. Buffer manager and network shuffle evaluation. PostgreSQL io_uring integration case study. PVLDB 2026 publication."
        },
        "concepts": ["io_uring"],
        "claims": [
            {"kind": "Observation", "id_prefix": "obs", "name": "Naive io_uring adoption does not improve database performance",
             "description": "Simply replacing traditional I/O interfaces with io_uring in database systems does not necessarily yield performance benefits. The benefits depend on matching io_uring's submission/completion model to the application's I/O access patterns."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Practical guidelines for io_uring in database I/O",
             "description": "Guidelines for when and how to use io_uring features (registered buffers, passthrough I/O, batched submissions) in database systems. Validated on PostgreSQL's io_uring integration with 14% improvement."},
            {"kind": "Benchmark", "id_prefix": "bench", "name": "io_uring storage vs network I/O benefit analysis",
             "description": "Storage-bound buffer manager and network-bound analytical shuffle evaluated with io_uring. Advanced features (registered buffers, passthrough I/O) analyzed for end-to-end database impact."}
        ]
    },

    # ── 5. NecoFuzz: Nested Virtualization Fuzzing ──────────────────
    {
        "ev_id": "ev-arxiv-necofuzz-kvm",
        "brief": {
            "key_ideas": [
                "First fuzzing framework systematically targeting nested virtualization-specific logic in hypervisors — no prior work has explicitly addressed the nested virtualization attack surface",
                "Synthesizes executable fuzz-harness VMs with internal states near the boundary between valid and invalid, guided by an approximate model of hardware-assisted virtualization specifications (Intel VT-x, AMD-V)",
                "Specification-guided boundary-oriented VM generation significantly improves coverage of security-critical nested virtualization code across different hypervisors",
                "Achieved 84.7% (VT-x) and 74.2% (AMD-V) code coverage for nested virtualization-specific code; uncovered 6 previously unknown vulnerabilities across 3 hypervisors including 2 CVEs"
            ],
            "relevance": "Directly targets the KVM hypervisor's nested virtualization path — one of the most complex and security-critical code paths in the Linux kernel. Nested virtualization (running VMs inside VMs) is increasingly used in cloud platforms but adds enormous complexity to KVM's VMCS/VMCB handling, shadow page tables, and interrupt injection. The 6 vulnerabilities found demonstrate that this attack surface is under-tested. The fuzz-harness VM approach could be applied to test other KVM subsystems.",
            "methodology": "AFL++-based fuzzing with specification-guided fuzz-harness VM generation. Intel VT-x and AMD-V implementations. Code coverage measurement. Vulnerability discovery across KVM, Xen, and other hypervisors."
        },
        "concepts": ["KVM (Kernel-based Virtual Machine)"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "Nested virtualization is an untested attack surface",
             "description": "Nested virtualization significantly increases hypervisor complexity and introduces a new attack surface, but no prior fuzzing framework has explicitly targeted nested virtualization-specific logic due to the challenge of generating VMs with vast state spaces."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Specification-guided boundary-oriented VM fuzzing",
             "description": "NecoFuzz synthesizes executable fuzz-harness VMs with states near the valid/invalid boundary, guided by hardware virtualization specs. Extends AFL++ to support VM-as-fuzzing-input for Intel VT-x and AMD-V."},
            {"kind": "FailureMode", "id_prefix": "fail", "name": "6 nested virtualization vulnerabilities including 2 CVEs",
             "description": "NecoFuzz uncovered 6 previously unknown vulnerabilities across 3 hypervisors (including KVM), with 2 assigned CVEs. Achieved 84.7% (VT-x) and 74.2% (AMD-V) nested virtualization code coverage."}
        ]
    },

    # ── 6. CacheBPF: eBPF Page Cache Customization ──────────────────
    {
        "ev_id": "ev-arxiv-cachebpf",
        "brief": {
            "key_ideas": [
                "Designs cachebpf, an eBPF-based framework that allows developers to customize Linux page cache eviction policy per-application without modifying the kernel — addressing Stonebraker's 1981 observation that one-size-fits-all cache policy cannot serve heterogeneous workloads",
                "Enables different applications to run different cache policies simultaneously while ensuring policies don't interfere with each other and preserving the page cache's cross-process memory sharing capability",
                "Demonstrates flexibility by implementing several eviction policies (ARC, LFU, FIFO, scan-resistant variants) using the cachebpf interface",
                "Achieves up to 70% higher throughput and 58% lower tail latency by matching cache policy to workload-specific access patterns"
            ],
            "relevance": "This is the cache_ext paper from Columbia University — the companion to SOSP 2025's cache_ext work. It directly modifies the Linux page cache to support eBPF-based policy customization. The page cache is one of the kernel's most performance-critical subsystems, and this work shows how eBPF can replace its fixed eviction heuristic with application-specific policies. The per-application policy isolation (preventing interference) is a novel kernel design challenge. The 70% throughput improvement demonstrates that the kernel's default LRU-like eviction leaves massive performance on the table for specific workloads.",
            "methodology": "Linux kernel eBPF framework implementation. Multiple eviction policy implementations (ARC, LFU, FIFO, scan-resistant). Per-application policy isolation. Evaluation with diverse workloads."
        },
        "concepts": ["eBPF (Extended Berkeley Packet Filter)", "Page Cache", "eBPF-Customizable Page Cache", "Page Reclaim (kswapd/direct)"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "Linux page cache one-size-fits-all eviction policy",
             "description": "The Linux page cache uses a single global eviction policy (LRU-like) for all applications. As Stonebraker observed in 1981, this cannot address heterogeneous workload access patterns. Despite decades of research, applications still contend with Linux's opaque and inflexible page cache policy."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "eBPF-based per-application page cache policy customization",
             "description": "cachebpf allows developers to implement custom page cache eviction policies via eBPF without kernel modification. Policies are per-application and isolated from each other while preserving cross-process page sharing."},
            {"kind": "PerformanceProfile", "id_prefix": "perf", "name": "cachebpf 70% throughput improvement with custom eviction",
             "description": "Up to 70% higher throughput and 58% lower tail latency by matching page cache eviction policy to workload-specific access patterns. Demonstrates that the kernel's default policy leaves massive performance opportunity."}
        ]
    },

    # ── 7. XLB: eBPF In-Kernel L7 Load Balancer ────────────────────
    {
        "ev_id": "ev-arxiv-xlb",
        "brief": {
            "key_ideas": [
                "Reshapes L7 load balancing from sidecar proxy to in-kernel interposition operating on the socket layer — uses eBPF to implement core load balancing logic directly in the kernel",
                "Novel socket layer redirection eliminates scheduling, communication, and data movement overhead of sidecar proxies — eBPF programs redirect socket connections at the kernel level",
                "Nested eBPF maps design solves connection management and state maintenance challenges for in-kernel L7 processing",
                "Over 50 microservice instances: 1.5x higher throughput and 60% lower end-to-end latency compared to Istio and Cilium"
            ],
            "relevance": "Demonstrates eBPF's capability for complex in-kernel networking logic — L7 load balancing requires HTTP parsing, connection management, and routing decisions that traditionally require userspace proxies. The socket layer redirection technique bypasses the entire userspace proxy data path, which is relevant to the kernel's socket subsystem and sk_buff handling. The comparison against Cilium (which already uses eBPF for L4) shows that eBPF can handle even higher-level protocol decisions in-kernel.",
            "methodology": "eBPF kernel implementation with socket layer redirection and nested maps. Evaluation with 50+ microservice instances. Comparison against Istio and Cilium."
        },
        "concepts": ["eBPF (Extended Berkeley Packet Filter)", "Socket Buffer (sk_buff)"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "Sidecar L7 load balancers degrade microservice performance",
             "description": "Traditional sidecar-based L7 load balancers (Istio, Envoy) introduce scheduling, communication, and data movement overhead that degrades microservice performance — especially problematic with co-located services on the same host."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "eBPF socket-layer in-kernel L7 load balancing",
             "description": "XLB implements L7 load balancing logic in the kernel via eBPF with socket layer redirection and nested eBPF maps for connection state management, eliminating sidecar proxy overhead."},
            {"kind": "PerformanceProfile", "id_prefix": "perf", "name": "XLB 1.5x throughput vs Istio/Cilium",
             "description": "Over 50 microservice instances: 1.5x higher throughput and 60% lower end-to-end latency compared to Istio and Cilium sidecar-based load balancers."}
        ]
    },

    # ── 8. TierBPF: eBPF Page Migration Admission ──────────────────
    {
        "ev_id": "ev-arxiv-tierbpf",
        "brief": {
            "key_ideas": [
                "Identifies two factors prior tiering systems ignore: the size of migrated pages (2MB huge pages vs 4KB base pages have vastly different migration costs) and the underlying hardware topology",
                "Implements TierBPF as eBPF hooks that plug into existing memory tiering systems to make binary page admission decisions — should this specific page be migrated or not",
                "Lightweight page profiling mechanism independent of application working set size — unlike access-bit scanning (NUMA hints) which scales with memory footprint",
                "Integrated into three memory tiering systems with 17 workloads: up to 75% improvement for individual workloads, 17.7% geomean throughput gain"
            ],
            "relevance": "Directly extends the kernel's memory tiering infrastructure with eBPF-based admission control. The page size awareness is critical — the kernel's Transparent Huge Pages (THP) mean most migrations are 2MB, but the cost-benefit of migrating a 2MB page vs a 4KB page is very different. TierBPF's eBPF hooks allow userspace/application-specific migration policies without modifying the kernel's core tiering code. This is the memory management equivalent of sched_ext — pluggable policies for a core kernel subsystem.",
            "methodology": "eBPF hooks implementation for three tiering systems. 17-workload evaluation. Page size and topology-aware admission control."
        },
        "concepts": ["eBPF (Extended Berkeley Packet Filter)", "Transparent Huge Pages", "NUMA Topology and Memory Policy", "Adaptive CXL Memory Tiering"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "Tiering systems ignore page size and hardware topology",
             "description": "Memory tiering systems abstract hardware as 'fast tier' and 'slow tier' without considering that 2MB THP migrations cost vastly more than 4KB page migrations, and that hardware topology affects migration benefit."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "eBPF-based page migration admission control",
             "description": "TierBPF implements eBPF hooks for binary page admission decisions in existing tiering systems. Lightweight profiling independent of working set size. Users define custom policies considering page size and hardware topology."},
            {"kind": "PerformanceProfile", "id_prefix": "perf", "name": "TierBPF up to 75% improvement in tiered memory",
             "description": "Integrated into three tiering systems: up to 75% individual workload improvement, 17.7% geomean throughput gain across 17 workloads."}
        ]
    },

    # ── 9. eBPF-PATROL: Runtime Container Security ──────────────────
    {
        "ev_id": "ev-arxiv-ebpf-patrol",
        "brief": {
            "key_ideas": [
                "eBPF-based runtime security agent that monitors and enforces policies in containerized and virtualized environments — intercepts system calls, analyzes execution context, and applies user-defined rules",
                "Addresses limitations of seccomp (lacks context-awareness and syscall argument filtering) and MAC frameworks (static rules, not adaptive) with eBPF-based dynamic enforcement",
                "Detects and prevents real-time boundary violations: reverse shells, privilege escalation, and container escape attempts",
                "Less than 2.5% overhead with high detection accuracy across real-world attack scenarios"
            ],
            "relevance": "Demonstrates eBPF as a replacement/complement for seccomp-BPF in container security. Seccomp filters are stateless and cannot inspect syscall arguments deeply; eBPF-PATROL uses eBPF's richer program model to implement context-aware security decisions. The container escape detection is directly relevant to the kernel's namespace and cgroup isolation — detecting when a process attempts to break out of its namespace boundaries. The <2.5% overhead makes this practical for production deployment.",
            "methodology": "eBPF implementation with syscall interception and context analysis. Real-world attack scenario evaluation (reverse shells, privilege escalation, container escape). Overhead measurement."
        },
        "concepts": ["eBPF (Extended Berkeley Packet Filter)", "Seccomp-BPF", "Namespaces", "Control Groups (cgroups v2)"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "Seccomp and MAC lack context-aware container security",
             "description": "Seccomp-BPF lacks context-awareness and deep syscall argument filtering. MAC frameworks use static rules that cannot adapt at runtime. Neither provides the combination of low overhead and adaptive enforcement needed for container security."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "eBPF-based adaptive runtime security for containers",
             "description": "eBPF-PATROL intercepts system calls with eBPF, analyzes execution context, and applies user-defined rules to detect reverse shells, privilege escalation, and container escapes in real time with <2.5% overhead."}
        ]
    },

    # ── 10. RCU Synchronization Issues in Linux ─────────────────────
    {
        "ev_id": "ev-arxiv-rcu-sync",
        "brief": {
            "key_ideas": [
                "Investigates kernel instability from omitted synchronize_rcu() calls during hash table updates — using a discovered weakness in Intel ICE network driver's Virtual Function management as case study",
                "Demonstrates that removing RCU-protected hash table entries without proper synchronization leaves transient stale entries, delays memory reclamation, and causes memory fragmentation under rapid insert/delete workloads",
                "Shows the connection between improper RCU synchronization and OOM conditions: delayed memory reclamation under high-churn workloads can exhaust available memory",
                "Proposes mitigations: explicit synchronize_rcu() calls to ensure timely safe memory reclamation, reinforcing established RCU best practices"
            ],
            "relevance": "Directly relevant to the kernel's RCU subsystem — the most widely used lock-free synchronization mechanism in Linux. RCU hash tables are deployed in networking, virtualization, and filesystems. The ICE driver vulnerability demonstrates that even production-quality kernel drivers can misuse RCU with serious consequences (stale pointers, UAF, OOM). This paper provides empirical evidence for why RCU synchronization discipline matters and what the failure modes look like.",
            "methodology": "Case study of Intel ICE network driver RCU synchronization issue. Experimental measurement of stale entries, memory reclamation delays, and fragmentation under rapid insert/delete workloads."
        },
        "concepts": ["Read-Copy-Update"],
        "claims": [
            {"kind": "FailureMode", "id_prefix": "fail", "name": "Missing synchronize_rcu() causes stale pointers and OOM",
             "description": "Omitting synchronize_rcu() when removing RCU-protected hash table entries leaves transient stale entries, delays memory reclamation via call_rcu/kfree_rcu, and causes memory fragmentation leading to OOM conditions under rapid insert/delete workloads."},
            {"kind": "Observation", "id_prefix": "obs", "name": "Production Intel ICE driver has RCU synchronization weakness",
             "description": "The Intel ICE network driver's Virtual Function management omits explicit synchronize_rcu() calls during hash table updates, creating a window for stale pointer access and use-after-free vulnerabilities."}
        ]
    },

    # ── 11. BBR as Default TCP Congestion Control ───────────────────
    {
        "ev_id": "ev-arxiv-bbr-default",
        "brief": {
            "key_ideas": [
                "Comprehensive evaluation of whether BBR (BBRv2/v3) should replace Cubic as the default TCP congestion control in Linux — tested across Internet, datacenter, Ethernet, wireless, and satellite networks",
                "BBR consistently achieves highest throughput (~905Mbps) across all environments but introduces higher latency (~0.79ms) and jitter (~4.2ms) — the throughput-latency tradeoff is fundamental",
                "BBR performs especially well for bulk transfers and bandwidth-intensive applications; Reno and Cubic deliver more balanced performance with lower latency and moderate jitter",
                "Concludes that workload-driven protocol selection is important — BBR should not universally replace Cubic but should be the default for bandwidth-intensive paths"
            ],
            "relevance": "Directly evaluates the Linux kernel's TCP congestion control stack — BBR, Cubic, Reno, and Vegas are all implemented as kernel modules. The question of which should be default affects every Linux server. The finding that BBR's throughput advantage comes with a latency cost is critical for kernel configuration decisions. The study covers the kernel's BBR implementation (net/ipv4/tcp_bbr.c) behavior across diverse network conditions. Google already uses BBR for its infrastructure; this paper evaluates whether that choice generalizes.",
            "methodology": "Multi-environment experimental evaluation. Google/web traffic experiments over home network. Campus network evaluation (1-10 Gbps). Controlled comparison between BBR, Cubic, Reno, Vegas. Internet, datacenter, wireless, and satellite scenarios."
        },
        "concepts": ["TCP Congestion Control", "BBR Congestion Control"],
        "claims": [
            {"kind": "Observation", "id_prefix": "obs", "name": "BBR highest throughput but higher latency than Cubic",
             "description": "BBR achieves the highest throughput (~905Mbps) but introduces higher latency (~0.79ms) and jitter (~4.2ms) compared to Cubic. Reno and Cubic deliver balanced performance with lower latency. Vegas minimizes latency at the cost of throughput."},
            {"kind": "Observation", "id_prefix": "obs", "name": "BBR should not universally replace Cubic",
             "description": "While BBR excels for bulk transfers and bandwidth-intensive applications, workload-driven protocol selection remains important. Latency-sensitive environments benefit from Cubic's lower jitter characteristics."}
        ]
    },

    # ── 12. eBPF-mm: Userspace-Guided Huge Page Management ──────────
    {
        "ev_id": "ev-arxiv-ebpf-mm",
        "brief": {
            "key_ideas": [
                "Identifies that Linux Transparent Huge Pages (THP) greedily allocates 2MB pages on first touch without considering whether the memory area benefits from huge pages — leading to underutilization and costly compaction",
                "Uses eBPF to inject userspace-guided huge page management decisions into the kernel's memory management path — applications can hint which memory regions should use huge pages based on their access patterns",
                "Addresses the cost-obliviousness of THP: setting up a huge page requires finding aligned physical memory (potentially triggering compaction), fetching data or zeroing contents — costs that may outweigh benefits for underutilized regions",
                "Covers x86 (2MB, 1GB), ARMv8-A, and RISC-V huge page sizes — the eBPF approach generalizes across architectures"
            ],
            "relevance": "Directly addresses one of the Linux kernel's most persistent performance issues: THP's greedy allocation strategy that causes compaction storms and memory waste. By using eBPF to inject application hints into the kernel's huge page allocation path, this work enables applications to control their own huge page decisions without requiring kernel modification. This is the memory management analog of cachebpf (page cache) and sched_ext (scheduling) — eBPF-based policy customization for a core kernel subsystem.",
            "methodology": "eBPF-based implementation in Linux kernel memory management. Cross-architecture evaluation (x86, ARM, RISC-V). Analysis of THP allocation costs vs benefits."
        },
        "concepts": ["eBPF (Extended Berkeley Packet Filter)", "Transparent Huge Pages", "Huge Page Mapping", "Buddy Allocator"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "THP greedy allocation causes compaction and waste",
             "description": "Linux THP greedily allocates 2MB huge pages on first touch without considering utilization or benefit. On fragmented systems this triggers costly compaction. Underutilized huge pages waste physical memory. Many applications recommend disabling THP entirely."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "eBPF-guided huge page allocation decisions",
             "description": "eBPF-mm injects userspace-guided huge page management into the kernel's allocation path via eBPF. Applications hint which memory regions should use huge pages based on access patterns, avoiding THP's cost-oblivious greedy allocation."}
        ]
    },

    # ── 13. XFS Zoned Storage ───────────────────────────────────────
    {
        "ev_id": "ev-eurosys25-xfs-zoned",
        "brief": {
            "key_ideas": [
                "Enables zoned storage support in XFS — zoned devices require sequential writes within zones and force out-of-place updates, fundamentally different from XFS's original in-place overwrite design",
                "Uses the zone append primitive to eliminate the need for serializing writes to the device — unlike other zoned filesystem implementations that serialize to maintain zone write ordering",
                "Reduces write amplification via intelligent data placement: co-locates data with similar lifetimes into zones based on file locality and application hints",
                "Implements a new zoned allocator and defragmenting garbage collection algorithm; evaluates with RocksDB on production zoned storage devices"
            ],
            "relevance": "Core Linux filesystem development by Western Digital Research (Christoph Hellwig is a major Linux kernel filesystem developer). XFS is one of the kernel's primary enterprise filesystems. Zoned storage support requires fundamental changes to XFS's allocation strategy, journaling, and data placement. The zone append primitive usage and lifetime-aware data placement extend the kernel's zoned storage infrastructure (blk-zoned). Published at EuroSys 2025.",
            "methodology": "Linux kernel XFS implementation. Zone append primitive for unserialized writes. Lifetime-aware data placement. RocksDB evaluation on production zoned storage devices. EuroSys 2025 poster."
        },
        "concepts": ["XFS Filesystem", "Block Device Layer", "XFS Zoned Storage Support"],
        "claims": [
            {"kind": "Proposal", "id_prefix": "prop", "name": "Zoned XFS with zone append and lifetime-aware placement",
             "description": "Zoned XFS enables zoned storage in the XFS enterprise filesystem using zone append (eliminating write serialization) and lifetime-aware data placement (co-locating data with similar lifetimes to reduce write amplification and improve GC performance)."},
            {"kind": "Observation", "id_prefix": "obs", "name": "Zone append eliminates zoned storage write serialization",
             "description": "The zone append primitive eliminates the need to serialize writes to zoned storage devices, unlike prior zoned filesystem implementations. This enables higher write throughput on zoned devices."}
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
