"""Deep enrichment batch 002: 12 high-signal papers with full ResearchBrief + structured claims.

Papers:
1. EFQ — Energy-Based Fair Queuing Scheduler on Linux CFS
2. ITME — Inference Tiered Memory Expansion with CXL-Hybrid Memories
3. NEURON-Fabric — CXL-Side Low-Bit Gradient Aggregation
4. SAC — Disaggregated KV Cache System with CXL for Sparse Attention
5. LearnedCache — eBPF-Integrated Perceptron Cache Eviction for Linux Page Cache
6. eBPF Thread Diagnostics — Performance Degradation Analysis with eBPF
7. Grimlock — eBPF + kTLS Agent Guard for High-Agency Systems
8. ForkKV — Copy-on-Write Disaggregated KV Cache for Multi-LoRA
9. DAXFS — Lock-Free Shared Filesystem for CXL Disaggregated Memory
10. UEFI SPDM — Device Authentication via SPDM in UEFI
11. TClone — Low-Latency Forking of Live GUI Environments
12. CXL-ClusterSim — Modeling CXL Disaggregated Memory Clusters
"""
import json, sqlite3, uuid

DB_PATH = "data/master.db"

ALL_PAPERS = [
    # ── 1. EFQ: Energy-Based Fair Queuing on Linux CFS ──────────────
    # Implements EFQ scheduling algorithm directly in the Linux kernel by
    # extending CFS. EFQ applies fair queuing theory to the energy domain:
    # instead of fair CPU time sharing, it provides proportional power
    # sharing. Uses CFS's red-black tree runqueue structure. Tested for
    # both energy management and real-time scheduling on mobile systems.
    {
        "ev_id": "ev-arxiv-78717f68",
        "brief": {
            "key_ideas": [
                "Implements Energy-based Fair Queuing (EFQ) directly in the Linux kernel by extending the CFS scheduler structure — applies classical fair queuing theory to the energy domain, providing proportional power sharing rather than proportional CPU time sharing",
                "Reuses the CFS red-black tree runqueue infrastructure to track per-task energy budgets instead of virtual runtime, minimizing scheduling overhead by piggybacking on existing kernel data structures",
                "Achieves proportional power sharing regardless of which device (CPU, display, radios) consumes energy — unlike DVFS governors which only control CPU power, EFQ manages system-wide energy budgets at the scheduler level",
                "Demonstrates strict time-constraint compliance under varying energy estimation errors and task counts, showing EFQ can serve as both an energy manager and a soft real-time scheduler simultaneously"
            ],
            "relevance": "Directly modifies the Linux CFS scheduler to add energy-aware scheduling. This is one of very few papers that actually implements a novel scheduling class inside the kernel. The approach of reusing CFS's vruntime-based red-black tree for energy budgets shows how the kernel's scheduling infrastructure can be repurposed for new resource dimensions beyond CPU time. Relevant to the kernel's Energy Aware Scheduling (EAS) framework and cpufreq governors, but goes further by making energy a first-class schedulable resource.",
            "methodology": "Linux kernel implementation extending CFS. Test bench with diverse workload types. Dual evaluation: energy management (proportional power sharing) and real-time scheduling (time-constraint compliance). Comparison against standard CFS."
        },
        "concepts": ["Virtual Runtime Scheduling", "Scheduling Classes", "CPU Frequency Scaling (cpufreq)"],
        "claims": [
            {"kind": "Proposal", "id_prefix": "prop", "name": "Energy-based fair queuing in Linux CFS",
             "description": "EFQ extends the Linux CFS scheduler to provide proportional power sharing by tracking per-task energy budgets in the CFS red-black tree runqueue. Tasks receive a proportional share of system-wide power rather than just CPU time."},
            {"kind": "Observation", "id_prefix": "obs", "name": "CFS vruntime structure generalizes to energy budgets",
             "description": "The CFS red-black tree and virtual runtime accounting infrastructure can be repurposed to track energy budgets with minimal overhead, demonstrating that the kernel's scheduling data structures are more general than their current CPU-time-only use."},
            {"kind": "PerformanceProfile", "id_prefix": "perf", "name": "EFQ achieves proportional power sharing across devices",
             "description": "EFQ provides proportional power sharing regardless of which device consumes energy (CPU, display, radios), unlike DVFS governors which only control CPU frequency. Also maintains strict time-constraint compliance under energy estimation errors."}
        ]
    },

    # ── 2. ITME: CXL-Hybrid Memory for LLM Inference ────────────────
    # TB-scale KV caches for agentic/long-context LLMs exceed single-server
    # memory. ITME uses CXL-hybrid memory (CXL DRAM + NVMe SSDs) to present
    # a massive byte-addressable remote memory expansion. Key insight:
    # deterministic access patterns of model weights and prefix caches enable
    # proactive data movement. Validated with SK Hynix CMM and PCIe Gen5 NVMe.
    # 35.7% throughput improvement over CPU-offloading.
    {
        "ev_id": "ev-arxiv-5b20b04f",
        "brief": {
            "key_ideas": [
                "Addresses TB-scale KV cache requirements for agentic/long-context LLMs by presenting CXL-hybrid memory (CXL DRAM + NVMe SSDs) as a massive byte-addressable remote memory expansion — simplifies software stack through direct byte-addressability versus RDMA-based alternatives",
                "Key insight: deterministic access patterns of LLM model weights and prefix caches enable proactive data movement across the memory-storage hierarchy — the system can predict and prefetch without reactive page faulting",
                "Validated with production-grade SK Hynix CMM (CXL Memory Module) and PCIe Gen5 NVMe SSDs, plus an FPGA-based hardware prototype demonstrating functional feasibility",
                "Achieves 35.7% throughput improvement over conventional CPU-offloading by providing additional remote memory expansion beyond host memory limits"
            ],
            "relevance": "Directly relevant to kernel CXL memory device drivers (CXL.mem), NUMA topology for CXL-attached memory tiers, and the kernel's memory tiering infrastructure. The proactive data movement across CXL-DRAM-NVMe hierarchy maps to kernel page migration and tiering policies. The byte-addressable CXL memory access bypasses kernel page fault handling for the hot path, while cold data falls back to NVMe through the block I/O layer. Represents the emerging pattern where the kernel must manage a 3-tier memory hierarchy (local DRAM → CXL DRAM → NVMe).",
            "methodology": "System design with CXL-hybrid memory architecture. Hardware validation on SK Hynix CMM and PCIe Gen5 NVMe. FPGA-based prototype. Performance evaluation against CPU-offloading baseline."
        },
        "concepts": ["Adaptive CXL Memory Tiering", "NVMe Driver Subsystem", "NUMA Topology and Memory Policy"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "TB-scale LLM context state exceeds single-server memory",
             "description": "Agentic and long-context LLM workloads push inference state to TB-scale, exceeding individual server memory capacity. This forces disaggregated shared storage, but RDMA-based solutions require software overhead (page faults, kernel intervention) on every remote access."},
            {"kind": "Observation", "id_prefix": "obs", "name": "LLM access patterns are deterministic and prefetchable",
             "description": "Model weights and prefix KV caches have deterministic access patterns that enable proactive data movement across the memory-storage hierarchy, unlike general-purpose workloads that require reactive page faulting."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "CXL-hybrid byte-addressable memory expansion for inference",
             "description": "ITME presents CXL DRAM + NVMe SSDs as a byte-addressable remote memory tier, with proactive data movement exploiting deterministic LLM access patterns. Simplifies the software stack versus RDMA-based disaggregation."},
            {"kind": "PerformanceProfile", "id_prefix": "perf", "name": "ITME throughput improvement over CPU offloading",
             "description": "35.7% throughput improvement over conventional CPU-offloading by extending memory capacity beyond host DRAM limits using CXL-hybrid memory. Validated with production SK Hynix CMM hardware."}
        ]
    },

    # ── 3. NEURON-Fabric: CXL-Side Gradient Aggregation ──────────────
    # CXL memory controller that performs gradient aggregation as cache lines
    # pass through it. Supports packed gradient-binary and gradient-ternary
    # aggregation near CXL memory, with FP32 bypass for sensitive layers.
    # 5-cycle aggregation datapath, 1.67% overhead. Layer-aware admission
    # identifies classifier head as sensitive. Reduces gradient traffic to
    # 3.6-5.4% of FP32 baseline.
    {
        "ev_id": "ev-arxiv-4d25e88d",
        "brief": {
            "key_ideas": [
                "Places gradient aggregation logic inside the CXL memory controller — performs packed low-bit gradient aggregation as cache lines pass through, avoiding separate accelerator blocks",
                "Supports dual-path operation: low-bit aggregation (G-Binary sign-count, G-Ternary gated) for bandwidth reduction, with FP32 bypass for layers/phases that need full precision — controlled via a software interface",
                "Layer-aware admission control identifies the classifier head as the precision-sensitive component; keeping head on FP32 while applying low-bit to backbone reduces gradient traffic to 3.6-5.4% of FP32 baseline while recovering most accuracy",
                "Five-cycle low-bit aggregation datapath adds at most 1.67% exposed runtime overhead; under bandwidth pressure the compute is fully hidden by CXL service time"
            ],
            "relevance": "Pioneers near-memory computation on CXL devices — a model where the CXL memory controller actively processes data in transit rather than passively serving load/store requests. This has implications for kernel CXL device drivers: the kernel must manage a CXL device that has both memory semantics (load/store) and compute semantics (aggregation mode selection). The dual-path control interface suggests the need for a kernel-level CXL device capability negotiation mechanism, and the layer-aware admission control could be exposed through sysfs or a dedicated CXL ioctl.",
            "methodology": "CXL controller architecture design. Cycle-level timing experiments. Functional tests for byte-exact identity, aggregation correctness. Training accuracy evaluation on CIFAR-10/100 and SST-2. Hardware synthesis and FPGA place-and-route."
        },
        "concepts": ["Adaptive CXL Memory Tiering"],
        "claims": [
            {"kind": "Proposal", "id_prefix": "prop", "name": "In-CXL-controller gradient aggregation",
             "description": "NEURON-Fabric places gradient aggregation logic inside the CXL memory controller, performing packed low-bit aggregation as gradient cache lines pass through. Supports G-Binary and G-Ternary formats with FP32 bypass for precision-sensitive layers."},
            {"kind": "Observation", "id_prefix": "obs", "name": "Classifier head is the precision-sensitive layer for gradient aggregation",
             "description": "Layer-aware admission analysis identifies the classifier head as the component requiring FP32 gradient precision. Applying low-bit aggregation to the backbone while keeping the head on FP32 recovers most accuracy and reduces gradient traffic to 3.6-5.4% of FP32 baseline."},
            {"kind": "PerformanceProfile", "id_prefix": "perf", "name": "NEURON-Fabric CXL aggregation overhead",
             "description": "Five-cycle low-bit aggregation datapath adds at most 1.67% exposed runtime overhead in the last-level-cache miss regime. Under bandwidth pressure, compute is fully hidden by CXL service time. Hardware synthesis shows the 512-bit datapath is small enough for near-memory integration."}
        ]
    },

    # ── 4. SAC: CXL Disaggregated KV Cache for Sparse Attention ─────
    # First efficient disaggregated KV cache optimized for sparse attention
    # models. RDMA-based systems fetch the entire prefix KV cache, but sparse
    # attention only needs top-k entries. CXL's cache-line granularity
    # load/store enables fetching only required entries on demand.
    # 2.1x throughput, 9.7x lower TTFT, 1.8x lower TBT vs RDMA on DeepSeek-V3.2.
    {
        "ev_id": "ev-arxiv-da75a544",
        "brief": {
            "key_ideas": [
                "First disaggregated KV cache system optimized for sparse attention models — exploits the insight that only a small fraction of KV entries are active during decoding, making full-cache RDMA fetches fundamentally wasteful",
                "Leverages CXL's cache-line granularity load/store semantics to fetch only required top-k KV entries on demand during inference, versus RDMA's coarse-grained bulk transfers",
                "Evaluated on DeepSeek-V3.2 (a production sparse attention model) using SGLang serving framework — demonstrates practical applicability to real MoE/sparse models",
                "Achieves 2.1x throughput, 9.7x lower time-to-first-token (TTFT), and 1.8x lower time-between-tokens (TBT) compared to RDMA-based disaggregation baselines"
            ],
            "relevance": "Establishes CXL as the superior disaggregation fabric for sparse attention LLM serving, directly challenging RDMA-based approaches. For the kernel, this means CXL memory access patterns shift from sequential/bulk (where page-level management works) to fine-grained random access (where cache-line-level management matters). The kernel's CXL drivers and NUMA balancing must handle high-frequency, small-granularity remote memory accesses without incurring page fault overhead — this paper shows the performance cliff when page-level (RDMA) granularity is applied to sparse workloads.",
            "methodology": "System design for CXL-based sparse KV cache disaggregation. Evaluation on DeepSeek-V3.2 with SGLang framework. Comparison against RDMA-based baselines on throughput, TTFT, and TBT metrics."
        },
        "concepts": ["Adaptive CXL Memory Tiering", "NUMA Topology and Memory Policy"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "RDMA disaggregation wastes bandwidth for sparse attention",
             "description": "RDMA-based disaggregated memory systems fetch the entire prefix KV cache from remote storage before decoding. For sparse attention models where only a small fraction of KV entries are active, this causes severe transmission bottlenecks and local memory wastage."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "CXL cache-line-granularity KV cache disaggregation",
             "description": "SAC leverages CXL's load/store semantics to fetch only required top-k KV entries on demand at cache-line granularity, avoiding the full-cache bulk transfer overhead of RDMA-based systems."},
            {"kind": "PerformanceProfile", "id_prefix": "perf", "name": "SAC vs RDMA on DeepSeek-V3.2 sparse attention",
             "description": "On DeepSeek-V3.2 with SGLang: 2.1x higher throughput, 9.7x lower time-to-first-token, and 1.8x lower time-between-tokens versus RDMA-based disaggregation baselines."}
        ]
    },

    # ── 5. LearnedCache: eBPF ML Cache Eviction for Linux Page Cache ─
    # Directly implements an ML-based page cache eviction policy inside the
    # Linux kernel using eBPF. Trains a single-layer perceptron on real kernel
    # data to predict page reuse time. Embeds the model in-kernel via eBPF
    # for real-time eviction decisions. Statistically significant improvement
    # over FIFO (up to 10% insertion rate improvement) with minimal overhead.
    {
        "ev_id": "ev-arxiv-e100ffe8",
        "brief": {
            "key_ideas": [
                "First implementation of an ML-based cache eviction policy running inside the Linux kernel via eBPF — trains a single-layer perceptron on real kernel data from diverse workloads to predict page reuse time",
                "Achieves median AUCs of nearly 80% over multiple linear models modeling page reuse time, demonstrating that ML-based eviction decisions are feasible with lightweight models in kernel context",
                "Embeds the trained model inside the Linux kernel using eBPF for real-time cache eviction decisions — the eBPF program runs on every page cache eviction event with minimal overhead",
                "Statistical testing over 50 paired trials against FIFO baseline shows statistically significant improvements of up to 10% in insertion rate (frequency-adjusted cache hit rate) for specific workloads"
            ],
            "relevance": "Directly extends the Linux page cache — one of the kernel's most performance-critical subsystems. This is a concrete implementation of the 'eBPF-customizable page cache' concept, where eBPF programs replace or augment the kernel's built-in LRU/clock eviction heuristics. The work validates that ML inference inside eBPF programs is practical for real-time kernel decisions. This aligns with the kernel's recent cache_ext/BPF page cache customization patches (SOSP 2025's cache_ext paper). The minimal overhead finding is crucial — it means ML-based kernel policies don't need to be limited to offline analysis.",
            "methodology": "Linux kernel eBPF implementation. Training on real kernel page cache trace data from diverse workloads. 50 paired statistical trials against FIFO baseline. Multiple workload types for generalization testing."
        },
        "concepts": ["Page Cache", "eBPF (Extended Berkeley Packet Filter)", "eBPF-Customizable Page Cache", "Page Reclaim (kswapd/direct)"],
        "claims": [
            {"kind": "Observation", "id_prefix": "obs", "name": "ML models can predict page reuse time from kernel features",
             "description": "A single-layer perceptron trained on real Linux kernel page cache data achieves median AUCs of nearly 80% for predicting page reuse time across diverse workloads, demonstrating that ML-based eviction is feasible with lightweight models."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "eBPF-embedded perceptron for real-time Linux page cache eviction",
             "description": "LearnedCache embeds a trained perceptron model inside the Linux kernel via eBPF, running inference on every page cache eviction event. The eBPF program replaces the kernel's default eviction heuristic with an ML-based decision."},
            {"kind": "PerformanceProfile", "id_prefix": "perf", "name": "LearnedCache improvement over FIFO eviction",
             "description": "Statistical testing over 50 paired trials shows statistically significant improvements of up to 10% in insertion rate (frequency-adjusted cache hit rate) for specific workloads, with minimal overhead from in-kernel ML inference."},
            {"kind": "Benchmark", "id_prefix": "bench", "name": "First in-kernel ML cache eviction benchmark",
             "description": "50 paired trials per workload with statistical significance testing. Multiple workload types (sequential, random, mixed). Comparison against FIFO baseline with insertion rate as the metric."}
        ]
    },

    # ── 6. eBPF Thread Diagnostics ───────────────────────────────────
    # 16 eBPF-based metrics across 6 kernel subsystems (scheduling, VFS,
    # networking, futex, multiplexing IO, block IO). Extends Thread State
    # Analysis by capturing fine-grained inter-thread dependencies. Selective
    # thread tracking algorithm traces from entry-point threads to constrained
    # resources.
    {
        "ev_id": "ev-arxiv-37a6742e",
        "brief": {
            "key_ideas": [
                "Implements 16 eBPF-based metrics across six kernel subsystems — scheduling, VFS, networking, futex, multiplexing I/O, and block I/O — capturing fine-grained thread-resource interactions invisible to traditional Thread State Analysis",
                "Extends Thread State Analysis with inter-thread dependency tracking: performance degradation propagates along thread dependencies, and specific thread-resource interactions enable capturing common degradation patterns",
                "Designs a selective thread tracking algorithm that traces performance issues from entry-point threads to constrained resources, avoiding the overhead of system-wide tracing",
                "Successfully diagnoses CPU, disk, lock, and external service contention with minimal overhead across diverse applications under variable workloads and resource contention"
            ],
            "relevance": "Demonstrates eBPF as a comprehensive kernel observability layer spanning multiple subsystems simultaneously. The 16 metrics across scheduling, VFS, networking, futex, epoll, and block I/O represent a blueprint for holistic kernel-level performance diagnosis. The selective thread tracking algorithm is particularly relevant — it shows how eBPF programs can implement cross-subsystem causal tracing without the overhead of full system tracing (ftrace/perf). This is the kind of observability that sched_ext and future kernel extension frameworks should enable natively.",
            "methodology": "eBPF-based implementation with 16 kernel subsystem metrics. Selective thread tracking algorithm. Evaluation with diverse applications under workload variability and resource contention scenarios."
        },
        "concepts": ["eBPF (Extended Berkeley Packet Filter)", "Ftrace", "Perf Events Subsystem", "Futex (Fast Userspace Mutex)", "Virtual Filesystem Switch"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "Thread State Analysis lacks inter-thread dependency granularity",
             "description": "Traditional Thread State Analysis identifies which subsystem a thread is blocked on but cannot reveal the inter-thread dependencies that propagate performance degradation across subsystem boundaries."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Cross-subsystem eBPF thread dependency tracing",
             "description": "16 eBPF-based metrics across six kernel subsystems (scheduling, VFS, networking, futex, multiplexing I/O, block I/O) with a selective thread tracking algorithm that traces degradation from entry-point threads to constrained resources."},
            {"kind": "PerformanceProfile", "id_prefix": "perf", "name": "eBPF thread diagnostics identifies four contention types",
             "description": "Successfully diagnoses CPU, disk, lock, and external service contention with minimal overhead across diverse applications under variable workloads and resource contention."}
        ]
    },

    # ── 7. Grimlock: eBPF + kTLS Agent Guard ─────────────────────────
    # Uses eBPF-enforced traffic interception + kTLS for agent-to-agent
    # security. Post-handshake attestation bound to TLS 1.3 channel bindings.
    # Short-lived, channel-bound scope tokens for least-privilege delegation.
    # No changes to user-layer orchestration code.
    {
        "ev_id": "ev-arxiv-5eb6bf39",
        "brief": {
            "key_ideas": [
                "Uses eBPF-enforced traffic interception to ensure all sandbox communication passes through a guard layer — eBPF programs intercept network traffic at the kernel level, making bypass impossible from userspace",
                "Combines eBPF interception with post-handshake attestation bound to standard TLS 1.3 channel bindings — the guard verifies identity and authorization after the TLS handshake, using the channel binding to prevent relay attacks",
                "Mints short-lived, channel-bound scope tokens for least-privilege delegation between agents — tokens capture specific authorized actions and are bound to the TLS channel, preventing reuse across connections",
                "Leverages kTLS (kernel TLS) for efficient dataplane after policy checks — once the guard validates communication, kTLS handles encryption in the kernel for zero-copy performance"
            ],
            "relevance": "Combines three kernel mechanisms (eBPF, kTLS, attestation) into a practical security architecture for AI agent communication. eBPF provides the interception layer that makes the guard mandatory, kTLS provides efficient in-kernel encryption, and the channel binding leverages the kernel's TLS implementation for cryptographic identity. This is a concrete example of how kernel security primitives compose for modern workloads — and shows that the kernel's existing eBPF + kTLS stack is sufficient for zero-trust agent communication without kernel modifications.",
            "methodology": "System design combining eBPF traffic interception, TLS 1.3 channel bindings, and scope-token-based authorization. Architecture for multi-cloud agent communication using commodity Linux primitives."
        },
        "concepts": ["eBPF (Extended Berkeley Packet Filter)", "Kernel Crypto API"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "Agent identity and authorization pushed to application code",
             "description": "Agentic systems running user-authored orchestration code push identity, authorization, provenance, and delegation into application code where it is difficult to enforce consistently and audit."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "eBPF + kTLS agent guard with channel-bound scope tokens",
             "description": "Grimlock uses eBPF-enforced traffic interception + kTLS to create a mandatory guard layer. Post-handshake attestation binds to TLS 1.3 channels. Short-lived scope tokens capture least-privilege delegation and are channel-bound to prevent reuse."},
            {"kind": "Observation", "id_prefix": "obs", "name": "Existing kernel primitives suffice for zero-trust agent communication",
             "description": "The combination of eBPF (interception), kTLS (efficient encryption), and TLS 1.3 channel bindings (attestation) provides transparent, auditable agent-to-agent security using commodity Linux primitives without kernel modifications."}
        ]
    },

    # ── 8. ForkKV: CoW KV Cache for Multi-LoRA ──────────────────────
    # Applies OS fork with copy-on-write semantics to LLM KV caches.
    # Decouples KV cache into shared (parent pages) and agent-specific
    # (child pages). DualRadixTree for cache inheritance. ResidualAttention
    # kernel reconstructs disaggregated KV cache in on-chip SRAM.
    # 3.0x throughput over state-of-the-art multi-LoRA serving.
    {
        "ev_id": "ev-arxiv-0e442a12",
        "brief": {
            "key_ideas": [
                "Applies the OS fork/copy-on-write (CoW) paradigm to LLM KV caches — decouples KV cache into a massive shared component (analogous to parent process memory pages) and lightweight agent-specific components (child process pages that diverge on write)",
                "Designs DualRadixTree architecture that enables newly forked agents to inherit the shared cache instantly and apply CoW semantics only for their unique divergent cache entries",
                "Implements ResidualAttention, a GPU kernel that reconstructs the disaggregated KV cache (shared + agent-specific components) directly within on-chip SRAM, avoiding the memory bandwidth penalty of cache reconstruction",
                "Achieves up to 3.0x throughput of state-of-the-art multi-LoRA serving systems with negligible impact on generation quality"
            ],
            "relevance": "Directly applies the kernel's fork/CoW memory management paradigm to GPU memory management for LLM serving. The insight that CoW semantics solve the KV cache divergence problem in multi-LoRA serving validates the generality of the kernel's virtual memory design patterns. The DualRadixTree mirrors the kernel's page table structure (shared + per-process private mappings). This is a case study in how OS memory management concepts transfer to accelerator memory management — relevant to GPU driver memory management and future CXL-based shared memory architectures.",
            "methodology": "System design applying OS CoW semantics to GPU KV cache. DualRadixTree data structure. ResidualAttention GPU kernel. Evaluation across diverse language models and multi-task datasets."
        },
        "concepts": ["Page Fault Handler", "Process Creation (fork/clone)"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "LoRA activations cause KV cache divergence killing prefix caching",
             "description": "In multi-LoRA agent workflows, unique LoRA activations cause KV cache divergence across agents, rendering traditional prefix caching ineffective for shared contexts. This forces redundant KV cache maintenance, rapidly saturating GPU memory."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Fork/CoW semantics for LLM KV cache management",
             "description": "ForkKV decouples KV cache into shared (parent) and agent-specific (child) components using copy-on-write semantics. DualRadixTree enables instant cache inheritance; ResidualAttention reconstructs disaggregated cache in on-chip SRAM."},
            {"kind": "PerformanceProfile", "id_prefix": "perf", "name": "ForkKV 3x throughput over multi-LoRA baselines",
             "description": "Up to 3.0x throughput of state-of-the-art multi-LoRA serving systems with negligible impact on generation quality, by eliminating redundant KV cache storage through CoW sharing."}
        ]
    },

    # ── 9. DAXFS: Lock-Free CXL Shared Filesystem ───────────────────
    # Linux filesystem for CXL shared memory using cmpxchg atomics as sole
    # coordination primitive. CAS-based hash overlay for lock-free concurrent
    # writes. Multi-host clock eviction (MH-clock) for shared page cache.
    # >99% CAS accuracy, 2.68x random write throughput vs tmpfs.
    {
        "ev_id": "ev-arxiv-bd065ae4",
        "brief": {
            "key_ideas": [
                "First Linux filesystem designed specifically for CXL shared memory — uses cmpxchg atomic operations, made coherent across host boundaries by CXL, as the sole coordination primitive (no locks, no centralized coordinator)",
                "CAS-based hash overlay enables lock-free concurrent writes from multiple hosts — eliminates the need for distributed locking protocols that would add latency on CXL's tight performance budget",
                "Novel multi-host clock eviction algorithm (MH-clock) provides demand-paged caching in shared DAX memory with fully decentralized victim selection via cmpxchg — each host independently selects eviction candidates",
                "Exceeds tmpfs throughput across all write workloads on single-host DRAM-backed DAX: 2.68x higher random write throughput with 4 threads, with preliminary GPU microbenchmarks showing the design extends to GPU threads at PCIe 5.0 bandwidth"
            ],
            "relevance": "Directly extends the Linux VFS with a new filesystem type for CXL shared memory. This is core kernel filesystem work: DaxFS implements a new filesystem that registers with the VFS, uses DAX (direct access) mappings to bypass the page cache for the hot path, and implements its own shared page cache with CXL-aware eviction. The lock-free design using only cmpxchg is particularly relevant — it shows that CXL's hardware-coherent atomics are sufficient for multi-host filesystem coordination, which has implications for all kernel data structures that need to be shared across CXL-connected hosts.",
            "methodology": "Linux filesystem implementation. Multi-host correctness validation on QEMU-emulated CXL 3.0 with TCP-forwarded atomics. Performance comparison against tmpfs on DRAM-backed DAX. GPU microbenchmarks."
        },
        "concepts": ["Adaptive CXL Memory Tiering", "Virtual Filesystem Switch", "Page Cache"],
        "claims": [
            {"kind": "Proposal", "id_prefix": "prop", "name": "Lock-free CXL filesystem using cmpxchg-only coordination",
             "description": "DaxFS is a Linux filesystem for CXL shared memory that uses cmpxchg atomic operations as its sole coordination primitive. A CAS-based hash overlay enables lock-free concurrent multi-host writes without centralized coordination."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Multi-host clock eviction for shared DAX page cache",
             "description": "MH-clock algorithm provides demand-paged caching in shared CXL DAX memory with fully decentralized victim selection — each host independently selects eviction candidates using cmpxchg, requiring no cross-host consensus for eviction decisions."},
            {"kind": "PerformanceProfile", "id_prefix": "perf", "name": "DAXFS throughput vs tmpfs",
             "description": "Exceeds tmpfs throughput across all write workloads on single-host DRAM-backed DAX: 2.68x higher random write throughput with 4 threads and 1.18x higher random read throughput at 64KB. >99% CAS accuracy under cross-host contention with no lost updates."}
        ]
    },

    # ── 10. UEFI SPDM: Device Authentication ────────────────────────
    # Uses SPDM (Security Protocol and Data Model) in UEFI to authenticate
    # PCIe and USB devices. Restricts connections to authorized devices.
    # Open-source PoC with KVM-based evaluation. 13% instruction overhead,
    # 8% CPU cycle overhead during boot.
    {
        "ev_id": "ev-arxiv-2a747b75",
        "brief": {
            "key_ideas": [
                "Proposes a UEFI system that authenticates PCIe and USB devices using the Security Protocol and Data Model (SPDM) before allowing connection — prevents malicious peripherals from being enumerated by the OS",
                "Restricts device connections to an allowlist of authenticated devices, blocking unauthorized peripherals at the firmware level before the kernel's device driver stack processes them",
                "Open-source proof-of-concept using QEMU emulation with KVM virtualization features for cycle-accurate evaluation of boot-time overhead",
                "13% instruction overhead and 8% CPU cycle overhead during firmware execution — acceptable for high-security environments"
            ],
            "relevance": "Directly relevant to the kernel's boot path and device enumeration. Currently the kernel trusts all devices enumerated by UEFI firmware — if UEFI can authenticate devices before handing them to the kernel, it creates a hardware root-of-trust for the kernel's device model. This complements kernel-level device security (IOMMU, USB authorization) by moving the trust boundary earlier in the boot sequence. The SPDM protocol could also be exposed to the kernel via EFI runtime services, enabling the kernel to verify device identity post-boot.",
            "methodology": "UEFI firmware implementation with SPDM device authentication. Open-source proof-of-concept on QEMU with KVM. Boot-time overhead measurement via instruction and CPU cycle counting."
        },
        "concepts": ["EFI/UEFI Boot and Runtime Services", "USB Subsystem"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "Kernel trusts all firmware-enumerated devices",
             "description": "Attackers can use malicious peripherals as an attack vector because the kernel trusts all PCIe and USB devices enumerated by UEFI firmware without verifying hardware authenticity."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "SPDM-based device authentication in UEFI firmware",
             "description": "A UEFI system that authenticates PCIe and USB devices using SPDM before allowing enumeration. Only authorized devices are made visible to the operating system, blocking malicious peripherals at the firmware level."},
            {"kind": "PerformanceProfile", "id_prefix": "perf", "name": "SPDM authentication boot overhead",
             "description": "13% increase in instruction count and 8% increase in CPU cycles during firmware execution. Overhead is concentrated in boot phase and does not affect runtime performance."}
        ]
    },

    # ── 11. TClone: Forkable GUI Workspaces for Agents ──────────────
    # Fork/snapshot/rollback for live GUI workspaces. Uses sibling containers,
    # CoW memory sharing, filesystem versioning, GUI-local execution.
    # 1.9x lower latency than KVM, 1.5x lower than CRIU.
    {
        "ev_id": "ev-arxiv-7f8a7f3f",
        "brief": {
            "key_ideas": [
                "Enables live GUI workspaces to be snapshotted, forked into isolated branches, rolled back, and selectively committed/merged — workspace versioning as a first-class systems primitive for computer-use agents",
                "Separates fast branch creation from durable checkpointing using sibling containers with copy-on-write memory sharing — fork is fast because it shares pages; checkpoint is asynchronous and doesn't block execution",
                "Combines filesystem versioning with GUI-local execution to support speculative agent exploration — agents can fork the workspace, try an action, and roll back without affecting the main branch",
                "1.9x lower total task latency than KVM-based isolation and 1.5x lower than CRIU checkpoint/restore"
            ],
            "relevance": "Pushes the kernel's container and CoW primitives to their limits for a new use case: interactive workspace branching. The design relies on kernel namespace isolation, CoW memory sharing (via fork semantics at the container level), overlayfs for filesystem branching, and the kernel's checkpoint/restore infrastructure. The comparison showing 1.9x improvement over KVM and 1.5x over CRIU quantifies the overhead of the kernel's current isolation mechanisms and motivates lighter-weight alternatives.",
            "methodology": "System design with sibling containers, CoW memory sharing, filesystem versioning. End-to-end agent-loop measurement. Comparison against KVM and CRIU baselines."
        },
        "concepts": ["Process Creation (fork/clone)", "Namespaces", "OverlayFS (Union Mount)"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "VMs and CRIU are too slow for agent workspace branching",
             "description": "Computer-use agents need fast branching for speculative execution and parallel search, but existing VMs (KVM), containers, and checkpoint/restore (CRIU) systems don't provide low-latency versioning of full interactive workspaces."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Forkable workspace system with sibling containers and CoW",
             "description": "TClone enables workspace forking via sibling containers with copy-on-write memory sharing, filesystem versioning for branch isolation, GUI-local execution, and asynchronous checkpointing decoupled from branch creation."},
            {"kind": "PerformanceProfile", "id_prefix": "perf", "name": "TClone latency vs KVM and CRIU",
             "description": "1.9x lower total task latency than KVM-based isolation and 1.5x lower than CRIU checkpoint/restore in end-to-end agent-loop measurement."}
        ]
    },

    # ── 12. CXL-ClusterSim: Modeling CXL Disaggregated Memory ───────
    # Full-system modeling framework combining gem5 (fidelity) with SST
    # (parallel simulation) for CXL disaggregated memory clusters.
    {
        "ev_id": "ev-arxiv-31422b1d",
        "brief": {
            "key_ideas": [
                "First full-system modeling and simulation framework for CXL-based disaggregated memory clusters — combines gem5 (cycle-accurate CPU/memory fidelity) with the Structural Simulation Toolkit (SST) for parallel, scalable simulation",
                "Addresses the critical gap in CXL research tooling: limited simulation tools prevent exploring the design space and evaluating performance tradeoffs in systems with disaggregated memory",
                "Designed to be scalable, flexible, and reasonably fast to enable computer architects to explore hardware/software co-design opportunities for CXL memory pooling and sharing",
                "Enables evaluation of kernel-level memory management policies (page migration, NUMA balancing, tiering) on simulated CXL hardware before physical devices are available"
            ],
            "relevance": "Directly relevant to kernel CXL memory management development. Without simulation tools, kernel developers cannot test CXL memory tiering policies (AutoNUMA, DAMON, page migration) against realistic CXL hardware behavior. CXL-ClusterSim enables pre-silicon evaluation of kernel memory management changes — critical because kernel CXL patches are being upstreamed faster than CXL hardware deployment. The gem5+SST combination provides the cycle-accurate fidelity needed to validate kernel-level timing assumptions about CXL latency and bandwidth.",
            "methodology": "Simulation framework design combining gem5 and SST. Focus on scalability, flexibility, and fidelity for CXL disaggregated memory architecture exploration."
        },
        "concepts": ["Adaptive CXL Memory Tiering", "NUMA Topology and Memory Policy"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "Limited simulation tools for CXL disaggregated memory",
             "description": "AI training and inference require hundreds of GB to TB of DRAM with low utilization ratios. CXL memory disaggregation is a solution, but limited simulation tools prevent exploring the design space and evaluating performance tradeoffs."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "gem5+SST full-system CXL cluster simulator",
             "description": "CXL-ClusterSim combines gem5 (cycle-accurate CPU/memory simulation) with SST (parallel simulation toolkit) for full-system modeling of CXL disaggregated memory clusters. Enables pre-silicon evaluation of memory management policies."}
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
