"""Batch 5: OSDI 2026 papers continued."""
import json, sqlite3, uuid

DB_PATH = "data/master.db"

BRIEFS = [
    {"ev_id": "ev-osdi26-hu-muyan", "key_ideas": ["Virtual tensor abstraction eliminates data movement in DNN compilation", "VTC compiler optimizes tensor layouts to avoid copies between operators"], "relevance": "The data movement elimination requires kernel-level DMA and memory mapping optimizations. Virtual tensor layouts interact with GPU driver memory management.", "methodology": "Compiler optimization for data movement elimination", "concepts": ["DMA Mapping Framework"]},
    {"ev_id": "ev-osdi26-hwang", "key_ideas": ["Revisits pipeline parallelism design choices for LLM serving workloads", "Identifies that LLM serving has different parallelism requirements than training"], "relevance": "Pipeline parallelism at the systems level interacts with kernel scheduling for GPU process management and network stack for inter-stage communication.", "methodology": "Systems design analysis for distributed LLM serving", "concepts": ["Scheduling Classes"]},
    {"ev_id": "ev-osdi26-jiang-yapeng", "key_ideas": ["Adaptive GPU-CPU hybrid inference via online neuron balancing", "Kairox dynamically partitions LLM layers between GPU and CPU based on load", "Online neuron balancing adapts to varying inference demand patterns"], "relevance": "The GPU-CPU work partitioning requires kernel-level scheduling coordination, DMA for data transfers, and NUMA-aware memory placement for CPU-side inference.", "methodology": "Adaptive hybrid computing with online workload balancing", "concepts": ["Scheduling Classes", "NUMA Topology and Memory Policy", "DMA Mapping Framework"]},
    {"ev_id": "ev-osdi26-leonhardi", "key_ideas": ["Fleet-wide datacenter maintenance with minimal capacity buffer", "PIMS achieves predictable latency during rolling maintenance operations", "Minimizes the capacity headroom needed for maintenance windows"], "relevance": "Fleet maintenance orchestration interacts with kernel-level live migration, container rescheduling via cgroups, and process checkpoint/restore.", "methodology": "Fleet-wide maintenance scheduling optimization", "concepts": ["Control Groups (cgroups v2)"]},
    {"ev_id": "ev-osdi26-mao-ziming-writeguards", "key_ideas": ["Distributed storage support for strongly consistent caches", "WriteGuards ensures cache consistency without sacrificing write performance", "Provides strong consistency guarantees for distributed write-back caches"], "relevance": "Relevant to the kernel's page cache write-back mechanisms and distributed filesystem cache consistency. WriteGuards patterns apply to NFS, FUSE, and clustered filesystem cache management.", "methodology": "Distributed cache consistency protocol design", "concepts": ["Page Cache", "Virtual Filesystem Switch"]},
    {"ev_id": "ev-osdi26-men", "key_ideas": ["Shared disaggregated memory for distributed data processing frameworks", "Duhu enables multiple frameworks to share a common CXL/RDMA memory pool", "Eliminates redundant data copies across framework boundaries"], "relevance": "Directly relevant to CXL memory management and NUMA policy in the kernel. Shared disaggregated memory requires kernel support for remote memory mapping and coherence.", "methodology": "Disaggregated memory architecture for multi-framework data sharing", "concepts": ["Adaptive CXL Memory Tiering", "NUMA Topology and Memory Policy", "Shared Memory (shmem/tmpfs)"]},
    {"ev_id": "ev-osdi26-ni", "key_ideas": ["Practical lock-free adaptive radix tree data structure", "Arctic achieves high concurrency without locks for in-memory indexing", "Adapts radix tree node sizes based on key distribution"], "relevance": "Lock-free radix trees are directly applicable to kernel data structures. The kernel uses radix trees for page cache indexing and IDR (ID radix) allocations.", "methodology": "Lock-free concurrent data structure design", "concepts": ["Read-Copy-Update", "Page Cache"]},
    {"ev_id": "ev-osdi26-pardeshi", "key_ideas": ["Overload control for servers with multiple resource bottlenecks", "Svalinn identifies and manages concurrent CPU, memory, and I/O bottlenecks", "Prevents cascading failures from resource exhaustion in large-scale servers"], "relevance": "The multi-resource overload control interacts with kernel cgroup resource limits, OOM killer, and CPU throttling. Preventing cascading failures requires coordinated kernel-level resource management.", "methodology": "Multi-resource overload control system design", "concepts": ["Control Groups (cgroups v2)", "OOM Killer", "Scheduling Classes"]},
    {"ev_id": "ev-osdi26-ren", "key_ideas": ["Trinity of observability: metrics, logs, and traces unified in cloud systems", "DiTing correlates cross-layer observability signals for faster root cause analysis"], "relevance": "Cloud observability relies on kernel tracing infrastructure — ftrace, perf events, eBPF tracepoints. DiTing's cross-layer correlation requires kernel-level instrumentation points.", "methodology": "Unified observability platform design for cloud systems", "concepts": ["Ftrace", "Perf Events Subsystem", "eBPF (Extended Berkeley Packet Filter)"]},
    {"ev_id": "ev-osdi26-rosenblum", "key_ideas": ["Isolated time-based defense for storage systems", "Timelock Drive prevents timing-based side channels in shared storage", "Time isolation in the storage path to prevent information leakage"], "relevance": "Directly targets the kernel's block I/O and storage driver layers. Time isolation requires modifications to the I/O scheduler and NVMe driver to prevent timing leaks.", "methodology": "Timing isolation design for storage security", "concepts": ["Block Device Layer", "NVMe Driver Subsystem", "Linux Security Modules"]},
    {"ev_id": "ev-osdi26-sang", "key_ideas": ["Asymmetry-aware scalable DNN inference on mobile CPUs", "Unleashes all heterogeneous cores (big.LITTLE) for mobile inference", "Adapts workload distribution to CPU core asymmetry"], "relevance": "Directly relevant to the kernel's heterogeneous CPU scheduling — big.LITTLE/DynamIQ scheduling, energy-aware scheduling (EAS), and cpufreq governor interactions.", "methodology": "Asymmetry-aware scheduling for heterogeneous mobile CPUs", "concepts": ["Scheduling Classes", "CPU Frequency Scaling (cpufreq)", "Scheduler Load Balancing"]},
    {"ev_id": "ev-osdi26-schimmelpfennig", "key_ideas": ["Ordered network data path key-value store", "DPA-Store places KV operations directly in the network data path", "Achieves low-latency ordered operations via SmartNIC offload"], "relevance": "Relevant to kernel network stack and SmartNIC driver model. Data path KV stores interact with XDP, NAPI polling, and DMA for network-attached storage operations.", "methodology": "SmartNIC-accelerated data path design for key-value storage", "concepts": ["XDP (eXpress Data Path)", "NAPI (New API) Polling", "DMA Mapping Framework"]},
    {"ev_id": "ev-osdi26-song", "key_ideas": ["Revisits DDIO performance with page coloring optimization", "Sepia uses page coloring to control DDIO cache allocation behavior", "Addresses performance degradation when DDIO and CPU compete for LLC space"], "relevance": "Directly targets kernel page allocation and cache coloring. DDIO (Data Direct I/O) performance depends on how the kernel allocates physical pages relative to LLC partitions.", "methodology": "Page coloring optimization for DDIO-aware cache management", "concepts": ["Page Cache", "DMA Mapping Framework", "NUMA Topology and Memory Policy"]},
    {"ev_id": "ev-osdi26-srivatsan", "key_ideas": ["Continuation-centric computing model with Arca", "Replaces traditional process/thread model with first-class continuations", "Enables efficient capture and resumption of computation state"], "relevance": "Fundamentally rethinks the kernel's process model. Continuations as a first-class OS abstraction would require changes to scheduler, context switching, and memory management.", "methodology": "Operating system architecture design with continuation-passing", "concepts": ["Process Creation (fork/clone)", "Scheduling Classes", "Virtual Runtime Scheduling"]},
    {"ev_id": "ev-osdi26-sivan", "key_ideas": ["Dynamic pricing for efficient allocation of ML training resources", "Quota Marketplace uses market mechanisms to allocate GPU/TPU time", "Improves resource utilization by letting teams trade unused quotas"], "relevance": "The resource marketplace interacts with kernel cgroup resource accounting and quota enforcement. Dynamic resource reallocation requires cgroup migration and CPU/memory limit adjustments.", "methodology": "Market-based resource allocation for shared compute clusters", "concepts": ["Control Groups (cgroups v2)"]},
]


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    concepts_map = {}
    for r in conn.execute("SELECT id, json_extract(attrs, '$.name') FROM nodes WHERE kind = 'Concept'").fetchall():
        if r[1]: concepts_map[r[1].lower()] = r[0]
    created = 0
    for b in BRIEFS:
        ev_id = b["ev_id"]
        existing = conn.execute(
            "SELECT 1 FROM nodes rb JOIN edges re ON re.source_id = rb.id "
            "WHERE rb.kind = 'ResearchBrief' AND re.kind = 'extracted-from' AND re.target_id = ?", (ev_id,)
        ).fetchone()
        if existing: continue
        brief_id = f"rb-{uuid.uuid4().hex[:12]}"
        title_row = conn.execute(
            "SELECT json_extract(s.attrs, '$.title'), json_extract(s.attrs, '$.published_date') "
            "FROM edges se JOIN nodes s ON s.id = se.target_id "
            "WHERE se.kind = 'sourced-from' AND se.source_id = ?", (ev_id,)
        ).fetchone()
        title = title_row[0] if title_row else ""
        date = title_row[1] if title_row else "2026-01-01"
        conn.execute("INSERT INTO nodes (id, kind, attrs) VALUES (?, 'ResearchBrief', ?)",
            (brief_id, json.dumps({"title": title, "key_ideas": json.dumps(b["key_ideas"]),
             "relevance": b["relevance"], "methodology": b["methodology"],
             "source_date": date or "2026-01-01", "artifact_class": "B"})))
        conn.execute("INSERT INTO edges (kind, source_id, target_id, attrs) VALUES ('extracted-from', ?, ?, '{}')", (brief_id, ev_id))
        for cname in b["concepts"]:
            cid = concepts_map.get(cname.lower())
            if cid:
                try: conn.execute("INSERT INTO edges (kind, source_id, target_id, attrs) VALUES ('summarizes-for', ?, ?, '{}')", (brief_id, cid))
                except: pass
        created += 1
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    total = conn.execute("SELECT count(*) FROM nodes WHERE kind = 'ResearchBrief'").fetchone()[0]
    print(f"Created {created} briefs. Total ResearchBriefs: {total}")
    conn.close()

if __name__ == "__main__":
    main()
