"""Batch 4: OSDI 2026 papers continued."""
import json, sqlite3, uuid

DB_PATH = "data/master.db"

BRIEFS = [
    {"ev_id": "ev-osdi26-hu-yigong", "key_ideas": ["Diagnosing performance issues in application-defined resources", "Framework for identifying bottlenecks in custom resource abstractions"], "relevance": "Relevant to kernel perf events and tracing infrastructure. Performance diagnosis of application resources requires kernel-level profiling and cgroup accounting.", "methodology": "Performance diagnosis framework with resource-aware profiling", "concepts": ["Perf Events Subsystem", "Control Groups (cgroups v2)"]},
    {"ev_id": "ev-osdi26-kim-donghyun", "key_ideas": ["Generates realistic executable testing environments from resource usage traces", "Mimesys replays real workload patterns for systems testing without production data"], "relevance": "The trace replay exercises kernel scheduling, memory management, and I/O subsystems. Realistic resource traces require accurate kernel-level instrumentation via perf/ftrace.", "methodology": "Trace-driven workload simulation for systems testing", "concepts": ["Perf Events Subsystem", "Ftrace"]},
    {"ev_id": "ev-osdi26-lei", "key_ideas": ["Online silent data corruption detection during LLM training at scale", "Insights from 35 million GPU hours of production training", "Real-time SDC detection without stopping training pipelines"], "relevance": "SDC detection at the hardware level requires kernel ECC memory handling, MCE (machine check exception) processing, and GPU driver error reporting.", "methodology": "Online error detection for large-scale GPU computing", "concepts": ["Interrupt Handling"]},
    {"ev_id": "ev-osdi26-li-liujia", "key_ideas": ["Adaptive cache eviction via fine-grained characterization of access patterns", "Merlin outperforms LRU/LFU by learning per-object access characteristics"], "relevance": "Directly relevant to kernel page cache eviction and the page reclaim subsystem. The adaptive eviction algorithm could replace or augment the kernel's existing LRU-based page reclaim.", "methodology": "Adaptive cache algorithm design with online learning", "concepts": ["Page Cache", "Page Reclaim (kswapd/direct)"]},
    {"ev_id": "ev-osdi26-li-nanqinqin", "key_ideas": ["Harvests sub-microsecond CXL memory stalls with LiteSwitch", "Detects and exploits CXL memory access latency variations for optimization", "Sub-microsecond stall harvesting enables useful work during CXL round-trips"], "relevance": "Directly targets CXL memory management in the kernel. Stall harvesting requires integration with the kernel's NUMA policy, page migration, and CXL device driver.", "methodology": "CXL memory latency characterization and stall exploitation", "concepts": ["Adaptive CXL Memory Tiering", "NUMA Topology and Memory Policy"]},
    {"ev_id": "ev-osdi26-li-shihang", "key_ideas": ["NEMO: Nimble and expressive memory observability framework", "Enables fine-grained memory behavior monitoring with low overhead", "Provides visibility into memory allocation, access patterns, and lifecycle"], "relevance": "Directly targets kernel memory observability — integrates with SLUB allocator tracing, page fault monitoring, and memory cgroup accounting. Extends perf/ftrace for memory-specific events.", "methodology": "Memory observability framework with low-overhead instrumentation", "concepts": ["SLUB Allocator", "Perf Events Subsystem", "Ftrace", "Page Fault Handler"]},
    {"ev_id": "ev-osdi26-li-suyi", "key_ideas": ["Characterization and scheduling of heterogeneous AI clusters at Alibaba hyperscale", "Addresses GPU/TPU/NPU heterogeneity in production cluster scheduling", "Workload-hardware affinity optimization for mixed accelerator environments"], "relevance": "The cluster scheduler interacts with kernel-level cgroup resource management, NUMA topology, and device driver resource accounting for heterogeneous accelerators.", "methodology": "Production cluster characterization and heterogeneity-aware scheduling", "concepts": ["Scheduling Classes", "Control Groups (cgroups v2)", "NUMA Topology and Memory Policy"]},
    {"ev_id": "ev-osdi26-li-tianyu", "key_ideas": ["Distributed speculative execution for resilient cloud applications", "Speculatively executes ahead on replicas to mask failures", "Reduces recovery latency by maintaining speculative execution state"], "relevance": "The speculative execution and checkpoint mechanisms require kernel process management, memory snapshotting, and network stack support for replica synchronization.", "methodology": "Speculative execution for fault-tolerant distributed systems", "concepts": ["Process Creation (fork/clone)"]},
    {"ev_id": "ev-osdi26-li-zecheng", "key_ideas": ["Lightweight data type profiler with high resolution", "TypeCraft profiles memory object types and their usage patterns with minimal overhead"], "relevance": "Relevant to kernel memory allocator profiling. Type-aware profiling of kmalloc/SLUB allocations helps identify memory usage patterns and potential optimization targets.", "methodology": "Low-overhead type-aware memory profiling", "concepts": ["SLUB Allocator", "Kmalloc", "Perf Events Subsystem"]},
    {"ev_id": "ev-osdi26-liargkovas", "key_ideas": ["Speculative script reordering at subprocess granularity", "hS identifies independent subprocess commands and executes them in parallel", "Speeds up shell script execution by exploiting subprocess-level parallelism"], "relevance": "Directly exercises the kernel's process creation (fork/exec), pipe management, and signal delivery. Subprocess parallelism stresses the scheduler and IPC mechanisms.", "methodology": "Speculative parallelization of sequential shell scripts", "concepts": ["Process Creation (fork/clone)", "Pipe and FIFO", "Signal Delivery"]},
    {"ev_id": "ev-osdi26-liu-yicheng", "key_ideas": ["Transparent and efficient virtual memory for secure computation", "Osprey provides virtual memory abstraction within TEE enclaves", "Enables standard memory management inside confidential computing environments"], "relevance": "Directly modifies kernel virtual memory management for TEE enclaves. Requires changes to page table management, fault handling, and memory encryption for Intel TDX/AMD SEV.", "methodology": "Virtual memory system design for confidential computing", "concepts": ["Hierarchical Page Tables", "Page Fault Handler", "Linux Security Modules"]},
    {"ev_id": "ev-osdi26-luo", "key_ideas": ["Zero-copy KV cache offloading for long-context LLMs", "Eliminates buffer copies when moving KV cache between GPU and host memory", "No Buffer No Bottleneck: direct memory transfers for cache offloading"], "relevance": "The zero-copy mechanism requires kernel DMA mapping, pinned memory management, and GPU driver cooperation. Direct memory transfers bypass the page cache and use kernel DMA APIs.", "methodology": "Zero-copy memory management for GPU-host data movement", "concepts": ["DMA Mapping Framework", "Page Cache"]},
    {"ev_id": "ev-osdi26-lyu", "key_ideas": ["Disaggregated garbage collection to tame tail latency in managed workloads", "Offloads GC pauses to remote memory/compute to reduce application tail latency", "Shaving the Peaks: GC work migrated off the critical path"], "relevance": "The disaggregated GC interacts with kernel page migration, CXL memory tiering, and NUMA-aware allocation. GC-kernel cooperation requires page fault handler and memory management changes.", "methodology": "Disaggregated runtime design for garbage collection", "concepts": ["NUMA Topology and Memory Policy", "Adaptive CXL Memory Tiering", "Page Fault Handler"]},
    {"ev_id": "ev-osdi26-lin-hannah", "key_ideas": ["AI-driven code efficiency optimizer for warehouse-scale computers", "ECO identifies and optimizes inefficient code patterns across fleet-wide binaries"], "relevance": "The fleet-wide optimization relies on kernel perf events for profiling and the kernel's binary loading infrastructure. Performance counters from perf_event subsystem guide optimization.", "methodology": "AI-assisted performance optimization at warehouse scale", "concepts": ["Perf Events Subsystem"]},
    {"ev_id": "ev-osdi26-liu-guangda", "key_ideas": ["Efficient KV cache offloading with lossless prefetching for sparse attention LLMs", "ECHO prefetches KV cache entries from host memory to GPU before they are needed", "Serves native sparse attention patterns without cache quality loss"], "relevance": "The prefetching mechanism requires kernel-level DMA and page pinning for GPU memory transfers. The host-GPU memory management path goes through the kernel's DMA mapping framework.", "methodology": "Memory prefetching design for GPU-host KV cache management", "concepts": ["DMA Mapping Framework"]},
    {"ev_id": "ev-osdi26-manakkal", "key_ideas": ["vBOIDs: Coarse-grained scheduling abstraction for taming container chaos", "Provides higher-level scheduling primitives above individual container scheduling", "Reduces scheduling complexity in large container deployments"], "relevance": "Directly targets the kernel's cgroup-based container scheduling. The coarse-grained abstraction sits above the scheduler and interacts with cgroup CPU bandwidth control.", "methodology": "Container scheduling abstraction design", "concepts": ["Control Groups (cgroups v2)", "Scheduling Classes"]},
    {"ev_id": "ev-osdi26-patel", "key_ideas": ["MDK: Rethinking data center memory reclamation", "Novel approach to reclaiming memory across a fleet of machines", "Addresses the mismatch between per-machine reclaim and fleet-wide memory pressure"], "relevance": "Directly targets the kernel's page reclaim subsystem (kswapd, direct reclaim) and memory cgroup OOM handling. Fleet-wide reclamation requires coordinated kernel memory pressure signals.", "methodology": "Fleet-wide memory reclamation system design", "concepts": ["Page Reclaim (kswapd/direct)", "OOM Killer", "Control Groups (cgroups v2)"]},
    {"ev_id": "ev-osdi26-sharma", "key_ideas": ["Mohabi: Disaggregating and sandboxing the Firefox JavaScript engine", "Isolates JS engine components into separate sandboxed processes", "Uses lightweight sandboxing to contain JS engine vulnerabilities"], "relevance": "The sandboxing uses kernel isolation primitives — seccomp-BPF, namespaces, and capabilities. Process disaggregation exercises fork/clone and IPC mechanisms.", "methodology": "Process-level sandboxing for browser engine security", "concepts": ["Seccomp-BPF", "Namespaces", "Process Creation (fork/clone)", "POSIX Capabilities"]},
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
