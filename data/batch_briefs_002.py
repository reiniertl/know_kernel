"""Batch 2: OSDI 2026 papers — semantic analysis from titles."""
import json, sqlite3, uuid

DB_PATH = "data/master.db"

BRIEFS = [
    {"ev_id": "ev-osdi26-ahn", "key_ideas": ["Decentralized log-structured file system designed for manycore processors", "Eliminates centralized metadata bottleneck in parallel filesystem operations", "Scales filesystem throughput with core count on modern many-core machines"], "relevance": "Directly targets the VFS and log-structured filesystem layers. Addresses scalability bottlenecks in ext4/XFS journaling on high-core-count NUMA systems.", "methodology": "Scalable filesystem design with manycore evaluation", "concepts": ["Virtual Filesystem Switch", "ext4 Journaling Filesystem"]},
    {"ev_id": "ev-osdi26-akewar", "key_ideas": ["Uses LLMs to interpret SMART disk health logs for predictive failure analysis", "Bridges the semantic gap between low-level storage telemetry and human-interpretable diagnostics"], "relevance": "Relevant to NVMe and block device health monitoring in the kernel. SMART data is exposed through the kernel's block device and NVMe driver subsystems.", "methodology": "LLM-assisted log analysis for storage systems", "concepts": ["NVMe Driver Subsystem", "Block Device Layer"]},
    {"ev_id": "ev-osdi26-athlur", "key_ideas": ["Declarative I/O programming model that breaks the storage I/O scalability wall", "Separates I/O intent from execution, enabling runtime optimization of I/O paths"], "relevance": "Directly targets the Linux I/O stack — block layer, io_uring, and VFS. Proposes a new abstraction layer above the kernel's existing I/O interfaces.", "methodology": "Declarative systems design for storage I/O", "concepts": ["io_uring", "Block Device Layer", "Virtual Filesystem Switch"]},
    {"ev_id": "ev-osdi26-banakar", "key_ideas": ["Object-based address-space engineering to improve memory tiering across DRAM and CXL tiers", "Rethinks virtual memory layout to optimize data placement in heterogeneous memory systems"], "relevance": "Directly modifies the kernel's virtual memory subsystem — page tables, NUMA policies, and memory tiering. Relevant to CXL memory management and the page fault handler.", "methodology": "Virtual memory system redesign for heterogeneous memory tiering", "concepts": ["NUMA Topology and Memory Policy", "Hierarchical Page Tables", "Page Fault Handler", "Adaptive CXL Memory Tiering"]},
    {"ev_id": "ev-osdi26-cai", "key_ideas": ["Breaks scalability barriers of wide-stripe vector erasure codes", "Enables efficient large-scale distributed storage with high fault tolerance"], "relevance": "Relevant to the MD RAID and device mapper layers for software-defined storage. Wide-stripe codes are used in kernel-level RAID implementations.", "methodology": "Erasure coding algorithm design for distributed storage", "concepts": ["MD (Multiple Devices) Software RAID", "Device Mapper"]},
    {"ev_id": "ev-osdi26-cao", "key_ideas": ["Characterizes and enables deterministic testing of Linux CPU scheduler bugs", "kSTEP framework for systematic exploration of scheduler state space", "Identifies concurrency bugs in the CFS and deadline schedulers"], "relevance": "Directly targets the Linux CPU scheduler codebase. Tests scheduling classes, load balancing, and the CFS virtual runtime mechanism for concurrency bugs.", "methodology": "Deterministic testing and bug characterization for kernel schedulers", "concepts": ["Scheduling Classes", "Virtual Runtime Scheduling", "Scheduler Load Balancing"]},
    {"ev_id": "ev-osdi26-carin", "key_ideas": ["First-class scheduling support for latency-critical eBPF applications", "Elevates eBPF programs from best-effort to guaranteed scheduling priority", "PeeR scheduling framework for predictable eBPF execution latency"], "relevance": "Directly modifies the Linux scheduler to give eBPF programs scheduling guarantees. Combines eBPF runtime with scheduling class extensions.", "methodology": "Kernel scheduler extension for eBPF program scheduling", "concepts": ["eBPF (Extended Berkeley Packet Filter)", "Scheduling Classes", "sched_ext Extensible Scheduling"]},
    {"ev_id": "ev-osdi26-chai", "key_ideas": ["Serverless execution paradigm for co-located batch workloads", "Challenges busy-polling and spinning patterns that waste resources", "Demonstrates that serverless cold-start is acceptable for batch co-location"], "relevance": "Relevant to the kernel's CPU scheduling and cgroup resource management for serverless/container workloads. Addresses busy-wait vs sleep tradeoffs in the scheduler.", "methodology": "Workload characterization and serverless system design", "concepts": ["Control Groups (cgroups v2)", "Scheduling Classes", "CPU Idle Framework"]},
    {"ev_id": "ev-osdi26-chaudhry", "key_ideas": ["Resource-efficient orchestration for agentic AI workflows in cloud platforms", "Reduces resource waste in multi-step AI agent pipelines"], "relevance": "Relevant to container orchestration and cgroup resource management. The agent workflow patterns exercise kernel-level resource isolation and scheduling.", "methodology": "Cloud systems design for AI workload orchestration", "concepts": ["Control Groups (cgroups v2)"]},
    {"ev_id": "ev-osdi26-chen-guanyi", "key_ideas": ["CPU co-pilots GPU I/O operations to free GPU compute resources", "Offloads I/O management from GPU to CPU for better GPU utilization"], "relevance": "Relevant to DMA mapping, interrupt handling, and the kernel's GPU driver subsystem. The CPU-GPU I/O coordination requires kernel-level DMA and interrupt management.", "methodology": "CPU-GPU cooperative I/O system design", "concepts": ["DMA Mapping Framework", "Interrupt Handling"]},
    {"ev_id": "ev-osdi26-chen-jiyang", "key_ideas": ["Microkernel-based shell architecture for FPGA accelerators", "Isolates FPGA management from application logic using microkernel principles"], "relevance": "Applies microkernel design principles to FPGA shell architecture. Relevant to the kernel's device model and VFIO framework for FPGA management.", "methodology": "Microkernel architecture design for FPGA management", "concepts": ["VFIO (Virtual Function I/O)"]},
    {"ev_id": "ev-osdi26-chen-zhongjie", "key_ideas": ["Principled performance tunability for operating system kernels", "Xkernel framework enabling systematic kernel performance configuration", "Exposes and controls kernel-level performance knobs with formal guarantees"], "relevance": "Directly targets the Linux kernel's performance tuning surface — sysctl parameters, scheduler knobs, memory management thresholds, and I/O scheduler settings.", "methodology": "Systematic kernel performance tuning framework", "concepts": ["Scheduling Classes", "Page Reclaim (kswapd/direct)", "Procfs and Sysfs"]},
    {"ev_id": "ev-osdi26-devsot", "key_ideas": ["Trustworthy performance profiling for flat workloads where sampling-based profilers fail", "Blink profiler detects when statistical sampling lies about hot code paths", "Addresses fundamental accuracy issues in perf-based profiling"], "relevance": "Directly relevant to the kernel's perf events subsystem and ftrace infrastructure. Identifies and corrects sampling bias in perf_event hardware counters.", "methodology": "Statistical analysis of profiling accuracy with kernel-level instrumentation", "concepts": ["Perf Events Subsystem", "Ftrace"]},
    {"ev_id": "ev-osdi26-haque", "key_ideas": ["Framework for precise tracking of memory objects in systems software", "Ichnaea provides object-level provenance for memory allocation and deallocation", "Enables detection of use-after-free, double-free, and memory leak bugs"], "relevance": "Directly targets the kernel's memory allocators — SLUB, kmalloc, vmalloc. Memory object tracking is essential for detecting kernel memory safety bugs.", "methodology": "Memory object tracking framework with allocator integration", "concepts": ["SLUB Allocator", "Kmalloc", "Vmalloc"]},
    {"ev_id": "ev-osdi26-he-yongchao", "key_ideas": ["Revisits memory-mapped I/O for distributed file systems", "Umap optimizes mmap for efficient matrix access patterns on remote storage", "Bridges the semantic gap between application memory access and distributed file I/O"], "relevance": "Directly modifies the kernel's mmap and page fault handler for distributed filesystem access. Relevant to VFS, page cache, and FUSE interactions.", "methodology": "Memory-mapped I/O redesign for distributed storage", "concepts": ["Page Fault Handler", "Virtual Filesystem Switch", "Page Cache", "FUSE (Filesystem in Userspace)"]},
    {"ev_id": "ev-osdi26-heer", "key_ideas": ["Service-enhanced RDMA offload engine for data center SmartNICs", "RoCE BALBOA extends RDMA with application-aware network services on SmartNICs"], "relevance": "Relevant to the kernel's RDMA subsystem and SmartNIC driver model. RDMA offload interacts with kernel memory registration, DMA, and network namespaces.", "methodology": "SmartNIC hardware-software co-design for RDMA acceleration", "concepts": ["DMA Mapping Framework", "Network Namespaces"]},
    {"ev_id": "ev-osdi26-holmes", "key_ideas": ["Process snapshots enabling near-warm serverless cold starts", "Rethinks checkpoint/restore (CRIU) for serverless function invocation", "Achieves near-warm start latency without maintaining idle containers"], "relevance": "Directly uses the kernel's CRIU (checkpoint/restore in userspace) infrastructure — process memory snapshots, file descriptor serialization, and namespace reconstruction.", "methodology": "Checkpoint/restore optimization for serverless computing", "concepts": ["Process Creation (fork/clone)", "Namespaces", "Page Fault Handler"]},
    {"ev_id": "ev-osdi26-hu-jiyu", "key_ideas": ["MEGALON: Efficient data sharing for partly coherent CXL memory", "Addresses coherence challenges in CXL memory pools shared across multiple hosts", "Optimizes data sharing protocols for CXL's partial coherence model"], "relevance": "Directly relevant to CXL memory management in the kernel — CXL.mem device drivers, NUMA topology, and cache coherence protocol interactions.", "methodology": "CXL memory architecture design with coherence protocol optimization", "concepts": ["Adaptive CXL Memory Tiering", "NUMA Topology and Memory Policy"]},
    {"ev_id": "ev-osdi26-hu-kang", "key_ideas": ["SBB eliminates centralized bottlenecks in userspace network runtime", "Scales network processing by removing single-threaded dispatch chokepoints"], "relevance": "Relevant to the kernel's network stack scalability — NAPI polling, XDP, and socket buffer management. Userspace network runtimes bypass kernel networking but still depend on kernel memory and interrupt management.", "methodology": "Lock-free network runtime design for scalability", "concepts": ["NAPI (New API) Polling", "XDP (eXpress Data Path)", "Socket Buffer (sk_buff)"]},
    {"ev_id": "ev-osdi26-hu-yuehao", "key_ideas": ["FARLock: Asymmetric RDMA locking made fair", "Addresses fairness issues in RDMA-based distributed locking protocols", "Achieves fair lock acquisition across asymmetric RDMA network topologies"], "relevance": "The distributed locking techniques draw on kernel spinlock and RCU design principles. RDMA locking requires kernel-level memory registration and RDMA subsystem support.", "methodology": "Distributed lock protocol design for RDMA networks", "concepts": ["Spinlock", "Read-Copy-Update"]},
    {"ev_id": "ev-osdi26-huang-jiacheng", "key_ideas": ["LifeLine: Object-page lifetime alignment for garbage collection on mobile devices", "Minimizes memory copying by aligning GC object lifetimes with OS page lifetimes", "Enables GC to cooperate with the kernel's page reclaim mechanism"], "relevance": "Directly interacts with the kernel's page reclaim (kswapd), page fault handler, and memory management for managed runtimes. The GC-kernel cooperation crosses the user-kernel boundary.", "methodology": "GC-OS co-design for memory-efficient mobile computing", "concepts": ["Page Reclaim (kswapd/direct)", "Page Fault Handler"]},
]


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")

    concepts_map = {}
    for r in conn.execute("SELECT id, json_extract(attrs, '$.name') FROM nodes WHERE kind = 'Concept'").fetchall():
        if r[1]:
            concepts_map[r[1].lower()] = r[0]

    created = 0
    for b in BRIEFS:
        ev_id = b["ev_id"]
        existing = conn.execute(
            "SELECT 1 FROM nodes rb JOIN edges re ON re.source_id = rb.id "
            "WHERE rb.kind = 'ResearchBrief' AND re.kind = 'extracted-from' AND re.target_id = ?",
            (ev_id,),
        ).fetchone()
        if existing:
            continue

        brief_id = f"rb-{uuid.uuid4().hex[:12]}"
        title_row = conn.execute(
            "SELECT json_extract(s.attrs, '$.title'), json_extract(s.attrs, '$.published_date') "
            "FROM edges se JOIN nodes s ON s.id = se.target_id "
            "WHERE se.kind = 'sourced-from' AND se.source_id = ?", (ev_id,)
        ).fetchone()
        title = title_row[0] if title_row else ""
        date = title_row[1] if title_row else "2026-01-01"

        conn.execute(
            "INSERT INTO nodes (id, kind, attrs) VALUES (?, 'ResearchBrief', ?)",
            (brief_id, json.dumps({
                "title": title,
                "key_ideas": json.dumps(b["key_ideas"]),
                "relevance": b["relevance"],
                "methodology": b["methodology"],
                "source_date": date or "2026-01-01",
                "artifact_class": "B",
            }))
        )
        conn.execute(
            "INSERT INTO edges (kind, source_id, target_id, attrs) VALUES ('extracted-from', ?, ?, '{}')",
            (brief_id, ev_id)
        )
        for cname in b["concepts"]:
            cid = concepts_map.get(cname.lower())
            if cid:
                try:
                    conn.execute(
                        "INSERT INTO edges (kind, source_id, target_id, attrs) VALUES ('summarizes-for', ?, ?, '{}')",
                        (brief_id, cid)
                    )
                except Exception:
                    pass
        created += 1

    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    total = conn.execute("SELECT count(*) FROM nodes WHERE kind = 'ResearchBrief'").fetchone()[0]
    print(f"Created {created} briefs. Total ResearchBriefs: {total}")
    conn.close()


if __name__ == "__main__":
    main()
