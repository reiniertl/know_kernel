"""Batch 6: OSDI 2026 papers — final batch."""
import json, sqlite3, uuid

DB_PATH = "data/master.db"

BRIEFS = [
    {"ev_id": "ev-osdi26-takiguchi", "key_ideas": ["Nested SEV: secure and generic AMD SEV support for nested virtualization", "Enables running SEV-protected VMs inside other VMs", "Addresses the gap between hardware SEV capabilities and nested virtualization support"], "relevance": "Directly targets the kernel's KVM hypervisor and AMD SEV support. Nested SEV requires kernel changes to memory encryption, page table management, and VMCB handling.", "methodology": "Nested virtualization architecture for confidential computing", "concepts": ["KVM (Kernel-based Virtual Machine)", "Linux Security Modules", "Hierarchical Page Tables"]},
    {"ev_id": "ev-osdi26-teguia", "key_ideas": ["Inside Out: paradigm shift from external to internal VM introspection", "Moves introspection agents inside the VM with hardware-enforced isolation", "Eliminates the semantic gap problem in traditional VMI approaches"], "relevance": "Directly relevant to KVM introspection and virtualization security. Internal VMI requires hardware isolation (TDX/SEV) managed by the kernel's virtualization subsystem.", "methodology": "VM introspection architecture redesign", "concepts": ["KVM (Kernel-based Virtual Machine)", "Linux Security Modules"]},
    {"ev_id": "ev-osdi26-vickers", "key_ideas": ["Composable durability for cloud-based shared logs", "LogDrive separates durability from ordering in distributed log systems", "Enables flexible durability guarantees without sacrificing performance"], "relevance": "Relevant to kernel filesystem journaling and write-ahead log design. The composable durability patterns apply to ext4 journaling and dm log-writes.", "methodology": "Distributed log system design with composable durability", "concepts": ["ext4 Journaling Filesystem", "Block Device Layer"]},
    {"ev_id": "ev-osdi26-wang-jiawei", "key_ideas": ["Verified memory allocator for mobile devices", "jwmalloc provides formal correctness guarantees for heap allocation", "Bridges the gap between verified allocator designs and practical mobile performance"], "relevance": "Directly applicable to kernel memory allocators. A verified allocator design could strengthen SLUB/kmalloc with formal safety guarantees against use-after-free and heap overflow.", "methodology": "Formally verified memory allocator design", "concepts": ["SLUB Allocator", "Kmalloc"]},
    {"ev_id": "ev-osdi26-wang-wenxin", "key_ideas": ["CPU-GPU hybrid design for local Mixture-of-Experts inference", "Achieves cloud-grade SLOs on local hardware by balancing work between CPU and GPU", "Dynamic expert routing across heterogeneous compute resources"], "relevance": "The CPU-GPU hybrid inference requires kernel scheduling coordination, DMA for data transfer, and NUMA-aware memory placement for CPU-side expert execution.", "methodology": "Heterogeneous compute design for MoE inference", "concepts": ["Scheduling Classes", "DMA Mapping Framework", "NUMA Topology and Memory Policy"]},
    {"ev_id": "ev-osdi26-wang-yun", "key_ideas": ["Quantifies the hidden cost of MWAIT idle in hyperscale cloud", "Reveals that CPU idle mechanisms waste significant power at fleet scale", "Proposes alternatives to MWAIT for energy-efficient idle management"], "relevance": "Directly targets the kernel's CPU idle framework and cpuidle governors. MWAIT instruction behavior is managed by the kernel's C-state selection logic.", "methodology": "Fleet-scale analysis of CPU idle power consumption", "concepts": ["CPU Idle Framework", "CPU Frequency Scaling (cpufreq)"]},
    {"ev_id": "ev-osdi26-wu-haonan", "key_ideas": ["Efficient tracing and diagnosis for online LLM inference systems", "StriaTrace provides low-overhead distributed tracing for inference pipelines", "Correlates traces across model serving components for latency diagnosis"], "relevance": "The tracing infrastructure builds on kernel tracing primitives — perf events, ftrace tracepoints, and eBPF-based trace collection.", "methodology": "Distributed tracing system design for ML inference", "concepts": ["Ftrace", "Perf Events Subsystem", "eBPF (Extended Berkeley Packet Filter)"]},
    {"ev_id": "ev-osdi26-wu-ruofan", "key_ideas": ["Joint reduction of dynamic and static energy in large model training", "Kareus optimizes both active compute energy and idle power during training", "Coordinates DVFS, power capping, and idle management across training workers"], "relevance": "Directly relevant to kernel power management — cpufreq governors, CPU idle states, and RAPL power capping interfaces. Joint dynamic/static energy optimization requires coordinated kernel power control.", "methodology": "Energy optimization for distributed ML training", "concepts": ["CPU Frequency Scaling (cpufreq)", "CPU Idle Framework", "Thermal Management Framework"]},
    {"ev_id": "ev-osdi26-wu-tianyuan", "key_ideas": ["Efficient co-scheduling for disaggregated RL post-training", "Weave coordinates GPU, CPU, and memory resources across disaggregated RL components"], "relevance": "The disaggregated scheduling interacts with kernel cgroup resource management and NUMA-aware memory allocation for distributed compute resources.", "methodology": "Co-scheduling design for disaggregated RL systems", "concepts": ["Control Groups (cgroups v2)", "Scheduling Classes"]},
    {"ev_id": "ev-osdi26-xia", "key_ideas": ["Learning-augmented heuristics for cache eviction", "Simple yet effective ML-enhanced cache replacement policy", "Robust and interpretable — degrades gracefully when ML predictions are wrong"], "relevance": "Directly applicable to the kernel page cache and page reclaim. Learning-augmented eviction could replace or augment the kernel's LRU-based page cache management.", "methodology": "ML-augmented cache algorithm design", "concepts": ["Page Cache", "Page Reclaim (kswapd/direct)"]},
    {"ev_id": "ev-osdi26-lamprou", "key_ideas": ["Controlling opaque-component effects with semisolates and try-catch semantics", "Language-level isolation for components with unknown or untrusted side effects"], "relevance": "The isolation semantics relate to kernel sandboxing concepts — seccomp, namespaces, and capability-based isolation for untrusted components.", "methodology": "Programming language design for component isolation", "concepts": ["Seccomp-BPF", "Namespaces"]},
    {"ev_id": "ev-osdi26-li-ruihao", "key_ideas": ["Hardware lifecycle-aware power planning for commercial hyperscale datacenters", "Accounts for hardware degradation over time in power capacity planning", "Prevents power budget violations as hardware ages and becomes less efficient"], "relevance": "Relevant to kernel thermal management and power capping. Hardware lifecycle awareness requires kernel RAPL, thermal zone, and cpufreq integration.", "methodology": "Lifecycle-aware datacenter power planning", "concepts": ["Thermal Management Framework", "CPU Frequency Scaling (cpufreq)"]},
    {"ev_id": "ev-osdi26-li-zekai", "key_ideas": ["Regular types for the streaming shell enabling type-safe shell pipelines", "RT adds type checking to Unix shell command composition"], "relevance": "Relevant to the kernel's pipe and process creation infrastructure. Typed shell pipelines exercise fork/exec, pipe buffer management, and signal handling.", "methodology": "Type system design for shell programming", "concepts": ["Pipe and FIFO", "Process Creation (fork/clone)"]},
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
    remaining_osdi = conn.execute('''
        SELECT count(*) FROM nodes s
        JOIN edges se ON se.kind = 'sourced-from' AND se.target_id = s.id
        JOIN nodes ev ON ev.id = se.source_id AND ev.kind = 'Evidence'
        WHERE s.kind = 'Source' AND s.id LIKE 'src-osdi26%'
        AND NOT EXISTS (
            SELECT 1 FROM nodes rb JOIN edges re ON re.source_id = rb.id
            WHERE rb.kind = 'ResearchBrief' AND re.kind = 'extracted-from' AND re.target_id = ev.id
        )
    ''').fetchone()[0]
    print(f"Created {created} briefs. Total: {total}. Remaining OSDI: {remaining_osdi}")
    conn.close()

if __name__ == "__main__":
    main()
