"""Deep enrichment batch 010: 10 papers — GPU OS layer, simulation OS, tiered memory,
io_uring complexities, bandwidth regulation, ML-specialized OS, serverless KVM, CXL characterization.

Papers:
1. AgileOS — GPU OS layer for protected CUDA services
2. LiveStack — OS support for cluster-scale full-stack simulation on Linux
3. AROM — Application Read-Only Memory for asymmetric latency (LtRAM/CXL)
4. io_uring Async — Complexities preventing io_uring adoption
5. LMS-AR — LMS prediction-based adaptive memory bandwidth regulation (Linux kernel module)
6. MaLV-OS — ML-specialized OS architecture for virtualized clouds
7. Nexus — Transparent I/O offloading for high-density KVM serverless
8. Samsung CMM-H — First public CXL Memory Module Hybrid characterization
9. PUMA — Kernel memory allocator for Processing-using-DRAM architectures
10. LFOC — Clustering-based LLC cache partitioning in Linux kernel (Intel CAT)
"""
import json, sqlite3, uuid

DB_PATH = "data/master.db"

ALL_PAPERS = [
    # ── 1. AgileOS: GPU OS Layer ────────────────────────────────────
    {
        "ev_id": "ev-arxiv-agileos-gpu-os-layer-for-protected-cuda-",
        "brief": {
            "key_ideas": [
                "Identifies that modern GPU applications interact with storage, network, vendor libraries, and GPU-resident services — requiring OS-like protection for GPU service metadata, device queues, and MMIO regions",
                "Virtualizes CUDA at the library boundary: applications link against client-side shims while a trusted runtime worker owns the real CUDA context and mediates operations",
                "GPU memory-management model separates user allocations from protected module/MMIO ranges using pointer validation and memory access guards via PTX injection",
                "Modular and flexible protection supporting a range of protection profiles from lightweight to full isolation"
            ],
            "relevance": "Proposes OS abstractions for GPU resource protection — complementing gpu_ext (batch 005) which focused on policy extensibility. AgileOS addresses the protection model: today's CUDA gives each application direct ownership of GPU resources, with no kernel-mediated access control. The CUDA-level virtualization is analogous to how the kernel virtualizes CPU resources for processes. The PTX-injection memory guards are the GPU equivalent of page table protections. This is relevant to the kernel's DRM/KMS GPU driver model and how it should evolve for multi-tenant GPU sharing.",
            "methodology": "CUDA library-level virtualization. Trusted runtime worker architecture. PTX injection for memory access guards. Modular protection profiles."
        },
        "concepts": [],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "CUDA gives applications direct unprotected GPU access",
             "description": "The CUDA programming model gives each application direct ownership of CUDA context, device pointers, runtime handles, and kernel launches. Protected GPU services must build ad hoc isolation. No OS-mediated access control exists for GPU resources."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "GPU OS layer with CUDA virtualization and memory guards",
             "description": "AgileOS virtualizes CUDA at the library boundary with a trusted runtime worker mediating operations. GPU memory model separates user from protected allocations via PTX-injected access guards. Modular protection profiles from lightweight to full isolation."}
        ]
    },

    # ── 2. LiveStack: Simulation-Native OS Support ──────────────────
    {
        "ev_id": "ev-arxiv-livestack-os-support-for-cluster-scale-f",
        "brief": {
            "key_ideas": [
                "Makes simulation control and orchestration a core OS responsibility — simulation-oriented scheduling, live memory hierarchy management, simulation-aware IPC, and distributed simulation orchestration",
                "Built on top of the Linux virtualization stack (KVM) — coordinates live and modeled components under shared simulated time while controlling interference among co-located hosts",
                "Addresses the fundamental tension in cluster-scale simulation: full-stack fidelity (unmodified production stack) vs simulation performance (iterative exploration) — no existing method achieves both",
                "Points toward 'simulation-native OS support' as a new kernel responsibility for datacenter infrastructure evaluation"
            ],
            "relevance": "Proposes that simulation should be a first-class OS concern, using the Linux KVM stack as the foundation. The simulation-oriented scheduler modifies how the kernel schedules VMs to maintain simulated time consistency. The live memory hierarchy management extends kernel memory management for simulation fidelity. This is a novel use of KVM beyond traditional virtualization — using the hypervisor for time-controlled execution. Relevant to the kernel's KVM scheduler interface and timer management.",
            "methodology": "Linux KVM-based implementation. Four OS subsystems for simulation. Cluster-scale evaluation with unmodified production stacks."
        },
        "concepts": ["KVM (Kernel-based Virtual Machine)", "Scheduling Classes"],
        "claims": [
            {"kind": "Proposal", "id_prefix": "prop", "name": "Simulation-native OS support on Linux KVM",
             "description": "LiveStack adds simulation-oriented scheduling, memory management, IPC, and orchestration to the Linux virtualization stack. Coordinates live and modeled components under shared simulated time for cluster-scale full-stack simulation with unmodified production stacks."}
        ]
    },

    # ── 3. AROM: Application Read-Only Memory ───────────────────────
    {
        "ev_id": "ev-arxiv-application-read-only-memory-for-asymmet",
        "brief": {
            "key_ideas": [
                "Proposes AROM: LtRAM/CXL memory pages are read-only to applications and written only by the OS during page migration — enforced via copy-on-write where application writes trigger fault+migration back to DRAM",
                "Shifts LtRAM management from the on-DIMM controller to the OS — the DIMM hardware is drastically simplified because the OS guarantees no in-place writes from applications",
                "Key insight: by making LtRAM read-only to apps, the OS eliminates the need for the translation layer (wear-leveling, address remapping, read/write caching) that adds latency to LtRAM devices like Intel Optane",
                "Aims to match pure DRAM performance on read-mostly workloads while delivering LtRAM's density and cost advantages"
            ],
            "relevance": "A fundamental redesign of the kernel's page management for asymmetric memory. The AROM invariant (LtRAM pages are read-only, writes trigger CoW migration to DRAM) is a new page protection semantic that the kernel must enforce via page table permissions and fault handling. This is directly relevant to the kernel's page fault handler, CoW implementation, memory tiering, and the NUMA balancing subsystem. The approach of simplifying hardware by moving intelligence to the OS kernel is the philosophical opposite of CXL controllers that handle everything in hardware — and shows that the kernel has untapped potential to manage asymmetric memory directly.",
            "methodology": "OS-hardware co-design with AROM page protection semantics. Copy-on-write enforcement for LtRAM. Performance analysis on read-mostly workloads."
        },
        "concepts": ["Page Fault Handler", "NUMA Topology and Memory Policy", "Adaptive CXL Memory Tiering"],
        "claims": [
            {"kind": "Proposal", "id_prefix": "prop", "name": "OS-managed read-only pages for asymmetric memory",
             "description": "AROM makes LtRAM/CXL pages read-only to applications — writes trigger CoW migration to DRAM. This invariant lets the OS manage LtRAM directly, eliminating the on-DIMM translation layer (wear-leveling, remapping, caching) that adds latency."},
            {"kind": "Observation", "id_prefix": "obs", "name": "Moving memory management from DIMM to OS simplifies hardware",
             "description": "The AROM invariant (no application writes to LtRAM) allows the DIMM to be drastically simplified. The OS handles all management functions that the on-DIMM controller previously performed, using page table protections and fault handling it already has."}
        ]
    },

    # ── 4. io_uring Async: Adoption Barriers ────────────────────────
    {
        "ev_id": "ev-arxiv-iouring-async",
        "brief": {
            "key_ideas": [
                "Explains why io_uring has limited adoption in practice despite significant performance improvements — the complexities of asynchronous completion-based I/O are the primary barrier",
                "Discusses the paradigm shift from blocking to asynchronous I/O: submission/completion ring management, callback-based control flow, error handling in async contexts, and resource lifetime management",
                "Identifies that integrating async I/O into existing database architectures requires fundamental redesign, not just API replacement — architectural choices determine whether io_uring benefits materialize",
                "Shares practical implications and tradeoffs for different architectures that may be used to integrate asynchronous I/O into database applications"
            ],
            "relevance": "Complements the PVLDB io_uring paper (batch 004) by focusing on why adoption is low rather than just benchmarking performance. The complexities identified — ring management, async error handling, resource lifetimes — are consequences of the kernel's io_uring API design. Understanding these barriers is essential for kernel developers who want io_uring to be adopted: the API may need to be made simpler or provide better abstractions. The finding that architectural redesign is needed (not just API swap) explains why io_uring adoption lags despite performance advantages.",
            "methodology": "Analysis of io_uring adoption barriers. Discussion of async I/O integration patterns. Architectural tradeoff analysis for database applications."
        },
        "concepts": ["io_uring"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "io_uring adoption limited by async complexity, not performance",
             "description": "Despite significant performance improvements, io_uring has limited adoption in practice. The complexities of asynchronous completion-based I/O (ring management, callback control flow, async error handling, resource lifetimes) are the primary adoption barrier, not performance."},
            {"kind": "Observation", "id_prefix": "obs", "name": "io_uring requires architectural redesign, not API replacement",
             "description": "Integrating io_uring into existing applications requires fundamental architectural redesign, not just replacing syscalls with io_uring submissions. Whether io_uring benefits materialize depends on the application's overall I/O architecture."}
        ]
    },

    # ── 5. LMS-AR: Adaptive Memory Bandwidth Regulation ─────────────
    {
        "ev_id": "ev-arxiv-lms-ar-adaptive-memory-bandwidth-regulat",
        "brief": {
            "key_ideas": [
                "Linux kernel module for per-core memory bandwidth regulation using LMS adaptive filtering for bandwidth prediction — master core monitors and regulates other cores",
                "Monitoring and regulation enforced from outside by a master core (not a dedicated controller) — allows computationally heavy prediction algorithms without interfering with regulated cores",
                "LMS (Least Mean Squares) adaptive filtering predicts per-core bandwidth requirements, enabling proactive regulation rather than reactive throttling",
                "Significant improvement over MemGuard in slowdown ratios under memory contention with SPEC CPU 2017 benchmarks"
            ],
            "relevance": "A Linux kernel module implementing memory bandwidth regulation — directly relevant to the kernel's resctrl (Resource Control) interface and Intel MBA (Memory Bandwidth Allocation). Unlike MBA which uses hardware throttling with fixed limits, LMS-AR predicts bandwidth needs and adapts proactively. The master-core architecture is a novel approach to kernel resource monitoring. Open-source implementation. This complements H-MBR (batch 008) which does bandwidth regulation at the hypervisor level — LMS-AR does it within the kernel.",
            "methodology": "Linux kernel module implementation. LMS adaptive filtering for bandwidth prediction. Master-core monitoring architecture. SPEC CPU 2017 evaluation. Comparison against MemGuard. Open source."
        },
        "concepts": ["Scheduling Classes"],
        "claims": [
            {"kind": "Proposal", "id_prefix": "prop", "name": "LMS-based adaptive memory bandwidth regulation in Linux kernel",
             "description": "LMS-AR is a Linux kernel module that uses LMS adaptive filtering to predict per-core memory bandwidth requirements and proactively regulate bandwidth allocation. Master core monitors and regulates without dedicating a controller. Outperforms MemGuard on SPEC CPU 2017."}
        ]
    },

    # ── 6. MaLV-OS: ML-Specialized OS for Virtualized Clouds ───────
    {
        "ev_id": "ev-arxiv-41e1b15c",
        "brief": {
            "key_ideas": [
                "Takes the opposite direction from 'ML improves the OS' — uses the OS to improve ML by rethinking OS architecture specifically for ML workloads in virtualized clouds",
                "Micro-LAKE microkernel allows kernel-space applications to use the GPU directly — enabling ML models to influence kernel decisions (scheduling, memory management) from within the kernel",
                "MLaaS (ML as a Service) subsystem gathers ML models as loadable kernel modules — VMs dynamically select policies that improve their specific ML workload performance",
                "Offloads system-sensitive model components to the OS to lighten model complexity and speed execution. Integrates GPU virtualization directly into the hypervisor"
            ],
            "relevance": "Proposes a radical kernel architecture where ML models run as kernel modules influencing scheduling and memory management decisions. This is the most ambitious intersection of ML and OS design in the corpus. The microkernel with GPU access (Micro-LAKE) pushes the boundary of what kernel code can do. The loadable-kernel-module ML policies are analogous to sched_ext but generalized to all kernel subsystems. While visionary rather than production-ready, this maps the design space for ML-native kernel architectures.",
            "methodology": "OS architecture design. Micro-LAKE microkernel with GPU access. MLaaS as loadable kernel modules. GPU virtualization integration. Visionary architecture paper."
        },
        "concepts": ["KVM (Kernel-based Virtual Machine)", "Kernel Module Loader", "Scheduling Classes"],
        "claims": [
            {"kind": "Proposal", "id_prefix": "prop", "name": "ML-specialized OS with kernel-space GPU access and ML-as-module",
             "description": "MaLV-OS rethinks the OS for ML workloads: Micro-LAKE microkernel enables kernel-space GPU access, MLaaS provides ML models as loadable kernel modules for scheduling/memory decisions, and GPU virtualization is integrated into the hypervisor."}
        ]
    },

    # ── 7. Nexus: KVM Serverless I/O Offloading ────────────────────
    {
        "ev_id": "ev-arxiv-16fc952a",
        "brief": {
            "key_ideas": [
                "Identifies that serverless VMs duplicate a heavyweight communication fabric (cloud SDK, RPC, TCP/IP) per-VM — consuming 25%+ of memory footprint and doubling CPU cycles vs bare-metal",
                "Nexus: serverless-native KVM hypervisor that transparently decouples compute from I/O by intercepting communication at the API boundary and offloading to shared host backend via zero-copy shared memory",
                "Enables async I/O optimizations: overlapping input prefetch with VM snapshot restoration, writing output payloads off the critical path",
                "44% CPU reduction, 31% memory reduction, 37% higher deployment density. 39% lower warm-start and 10% lower cold-start latency vs production baseline"
            ],
            "relevance": "Directly modifies the KVM hypervisor for serverless optimization. The transparent I/O decoupling (intercepting cloud SDK calls and offloading to host backend) changes how the kernel's KVM and virtio subsystems manage guest I/O. The zero-copy shared memory path between guest and host backend is a new KVM communication primitive. The 37% density improvement from removing per-VM communication fabric shows that the kernel's current VM isolation model is too heavyweight for serverless — motivating lighter-weight KVM configurations.",
            "methodology": "KVM hypervisor modification for serverless I/O offloading. API-boundary interception. Zero-copy shared memory backend. Comparison against production baseline and WASM-based hypervisor."
        },
        "concepts": ["KVM (Kernel-based Virtual Machine)", "Virtio Paravirtual I/O", "Namespaces"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "Serverless VMs duplicate heavyweight communication fabric",
             "description": "Each serverless VM duplicates cloud SDK, RPC, and TCP/IP stacks — consuming 25%+ of memory footprint and doubling CPU cycles compared to bare-metal. Prior solutions sacrifice ecosystem compatibility by forcing WASM or library OSes."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Serverless-native KVM with transparent I/O offloading",
             "description": "Nexus intercepts communication at the API boundary and offloads to shared host backend via zero-copy shared memory. Preserves conventional programming model. 44% less CPU, 31% less memory, 37% higher density, 39% lower warm-start latency."}
        ]
    },

    # ── 8. Samsung CMM-H: CXL Memory Module Characterization ───────
    {
        "ev_id": "ev-arxiv-324679c2",
        "brief": {
            "key_ideas": [
                "First publicly available comprehensive characterization of Samsung CMM-H (CXL Memory Module Hybrid) — integrates DRAM cache with NAND flash in a single CXL device for near-DRAM latency",
                "Addresses whether diverse applications can run on NAND-backed memory devices — validates that byte-addressable NAND flash via CXL is practical for real workloads",
                "Three-fold benefits: byte-addressability (no OS/IO overhead like block devices), scalable capacity, and persistence at low cost",
                "Provides key insights into how to best take advantage of CMM-H devices across workload types"
            ],
            "relevance": "The first public data on Samsung's CXL Memory Module Hybrid — a production CXL device that the kernel's CXL drivers must manage. CMM-H integrates DRAM cache with NAND flash, presenting byte-addressable memory to the kernel. The kernel sees this as a NUMA memory node but must understand that the performance characteristics differ from DRAM (the DRAM cache masks NAND latency for hot data). This data is essential for tuning the kernel's CXL tiering policies (when to migrate to/from CMM-H) and for validating that the kernel's memory management works correctly on this device class.",
            "methodology": "FPGA-based CMM-H prototype characterization. Application-level benchmarking across workload types. Performance profiling of byte vs block access patterns. Usage guidelines derivation."
        },
        "concepts": ["Adaptive CXL Memory Tiering", "NVMe Driver Subsystem"],
        "claims": [
            {"kind": "Observation", "id_prefix": "obs", "name": "CXL NAND-backed memory is practical for diverse workloads",
             "description": "Samsung CMM-H integrating DRAM cache with NAND flash via CXL delivers byte-addressable, persistent, scalable memory at low cost. First public characterization confirms diverse applications can run successfully on NAND-backed CXL memory with near-DRAM latency."}
        ]
    },

    # ── 9. PUMA: Kernel Allocator for Processing-using-DRAM ─────────
    {
        "ev_id": "ev-arxiv-17fbca6f",
        "brief": {
            "key_ideas": [
                "Identifies that standard memory allocation (malloc, posix_memalign, huge pages) cannot meet the data layout and alignment requirements of Processing-using-DRAM (PUD) architectures — source and destination must be in the same DRAM subarray",
                "PUMA: kernel module that uses internal DRAM mapping information with huge pages, then splits them into finer-grained allocation units aligned to subarray boundaries",
                "Lazy allocation: pages are allocated on-demand but guaranteed to land in the correct subarray for PUD operations",
                "Significantly outperforms baseline kernel allocators for PUD microbenchmarks and all allocation sizes"
            ],
            "relevance": "Directly extends the Linux kernel's memory allocator for a new class of hardware: Processing-in-Memory/Processing-using-DRAM. The kernel's current page allocator (buddy system) and huge page allocation don't understand DRAM subarray topology — they allocate pages based on address alignment without considering which physical DRAM rows they land in. PUMA bridges this gap by using DRAM mapping information (which the kernel could learn from the memory controller) to ensure correct placement. This is the memory management equivalent of NUMA-aware allocation but at DRAM subarray granularity.",
            "methodology": "Linux kernel module on QEMU with emulated RISC-V. DRAM mapping-aware allocation. RowClone and Ambit PUD operation evaluation. Comparison against standard allocators."
        },
        "concepts": ["Buddy Allocator", "Huge Page Mapping", "NUMA Topology and Memory Policy"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "Kernel allocators unaware of DRAM subarray topology for PUD",
             "description": "Standard kernel memory allocation (malloc, posix_memalign, huge pages) cannot guarantee that source and destination operands land in the same DRAM subarray — required for Processing-using-DRAM operations like RowClone and Ambit."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "DRAM-topology-aware kernel memory allocator for PUD",
             "description": "PUMA is a kernel module using internal DRAM mapping information to split huge pages into subarray-aligned allocation units. Lazy allocation guarantees correct PUD operand placement. Outperforms baseline allocators for all PUD workloads."}
        ]
    },

    # ── 10. LFOC: LLC Cache Partitioning in Linux ───────────────────
    {
        "ev_id": "ev-arxiv-0ba2e150",
        "brief": {
            "key_ideas": [
                "Clustering-based LLC cache partitioning implemented in the Linux kernel using Intel CAT (Cache Allocation Technology) — strives for fairness while maintaining acceptable throughput",
                "Identifies streaming aggressor programs and cache-sensitive applications, assigns them to separate cache partitions to mitigate shared-resource contention",
                "Mimics the behavior of the optimal cache-clustering solution (approximated via simulation) using lightweight runtime heuristics suitable for a real OS",
                "Higher reduction in unfairness than state-of-the-art policies with a lightweight algorithm suitable for kernel adoption"
            ],
            "relevance": "Directly implements cache partitioning policy in the Linux kernel using Intel CAT via the resctrl interface. This is one of the few papers that implements a novel cache management policy as actual Linux kernel code and evaluates on real hardware (Intel Skylake). The aggressor detection (streaming programs that thrash the LLC) and victim identification (cache-sensitive applications) are exactly the intelligence the kernel needs to use CAT effectively. The resctrl interface provides the mechanism; LFOC provides the policy.",
            "methodology": "Linux kernel implementation using Intel CAT via resctrl. Intel Skylake real hardware evaluation. Comparison against two state-of-the-art fairness and throughput policies."
        },
        "concepts": ["Scheduling Classes"],
        "claims": [
            {"kind": "Proposal", "id_prefix": "prop", "name": "Clustering-based LLC partitioning policy for Linux with Intel CAT",
             "description": "LFOC implements cache partitioning in the Linux kernel using Intel CAT. Identifies streaming aggressors and cache-sensitive victims, assigns them to separate LLC partitions. Lightweight algorithm achieving higher fairness than state-of-the-art on real Intel Skylake hardware."}
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
