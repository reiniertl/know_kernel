"""Batch 3: OSDI 2026 papers continued — semantic analysis."""
import json, sqlite3, uuid

DB_PATH = "data/master.db"

BRIEFS = [
    {"ev_id": "ev-osdi26-chen-luofan", "key_ideas": ["Efficient data pipeline construction for large-scale LLM pre-training", "Addresses data loading bottlenecks that limit GPU utilization during training"], "relevance": "Relevant to kernel I/O stack — the data pipelines exercise io_uring, page cache, and direct I/O paths. Data loading at scale stresses the block device and filesystem layers.", "methodology": "Data pipeline systems design for ML training", "concepts": ["io_uring", "Page Cache", "Block Device Layer"]},
    {"ev_id": "ev-osdi26-chen-zhenqian", "key_ideas": ["Role-based fault tolerance for reinforcement learning post-training", "Differentiated checkpointing and recovery based on worker roles in RL systems"], "relevance": "The fault tolerance mechanisms interact with kernel process management and checkpoint/restore infrastructure. Role-based recovery patterns map to cgroup hierarchy and process groups.", "methodology": "Fault-tolerant distributed systems design for ML", "concepts": ["Process Creation (fork/clone)", "Control Groups (cgroups v2)"]},
    {"ev_id": "ev-osdi26-cheng", "key_ideas": ["Compiler and runtime for mega-kernelizing tensor programs", "Fuses multiple tensor operations into single large GPU kernels to reduce launch overhead"], "relevance": "The kernel launch overhead reduction requires interaction with the GPU driver and DMA subsystem. Mega-kernels change the granularity at which the kernel schedules GPU work.", "methodology": "Compiler optimization for GPU kernel fusion", "concepts": ["DMA Mapping Framework"]},
    {"ev_id": "ev-osdi26-cottone", "key_ideas": ["Platform for encrypted and accountable collaborative editing", "Combines end-to-end encryption with auditability guarantees"], "relevance": "The encryption layer relies on the kernel crypto API for cryptographic operations. Accountability requires kernel-level audit logging.", "methodology": "Cryptographic protocol design for collaborative systems", "concepts": ["Kernel Crypto API"]},
    {"ev_id": "ev-osdi26-destefano", "key_ideas": ["Succinct proofs for numerical computations enabling verification", "Verifiable computing for numerical workloads with compact proof size"], "relevance": "Not directly kernel-related. Formal verification techniques that could potentially verify kernel numerical code.", "methodology": "Verifiable computing with succinct proof systems", "concepts": []},
    {"ev_id": "ev-osdi26-du", "key_ideas": ["Efficient LLM serving on commodity GPU clusters", "Data-reduced cross-instance orchestration minimizing inter-GPU communication"], "relevance": "The cross-instance orchestration exercises kernel networking (TCP, RDMA), GPU driver DMA, and cgroup-based resource isolation across container instances.", "methodology": "Distributed GPU systems design for LLM inference", "concepts": ["Control Groups (cgroups v2)", "TCP Congestion Control"]},
    {"ev_id": "ev-osdi26-ferreira", "key_ideas": ["Automated detection of data integrity violations in microservices", "Identifies inconsistencies in distributed state across microservice boundaries"], "relevance": "Not directly kernel-related. Operates at the application/middleware layer above the kernel.", "methodology": "Distributed systems integrity analysis", "concepts": []},
    {"ev_id": "ev-osdi26-gaikwad", "key_ideas": ["Abstention protocol for root cause analysis in Clos network fabrics", "Systematic approach to diagnosing failures in data center network topologies"], "relevance": "Relevant to the kernel's network driver and netfilter layers. Clos fabric diagnostics require kernel-level packet tracing and network device health monitoring.", "methodology": "Network diagnostics protocol design", "concepts": ["Netfilter Hook Framework"]},
    {"ev_id": "ev-osdi26-gao", "key_ideas": ["Disaggregated multi-task agentic RL training at scale", "Separates RL training components across disaggregated resources for efficiency"], "relevance": "The disaggregated architecture exercises kernel memory management for CXL/remote memory, RDMA networking, and cgroup resource isolation.", "methodology": "Disaggregated systems design for distributed ML training", "concepts": ["Adaptive CXL Memory Tiering", "Control Groups (cgroups v2)"]},
    {"ev_id": "ev-osdi26-ghosh", "key_ideas": ["Compiler support for unlocking CUDA graph optimizations in ML workloads", "GraCE enables automatic CUDA graph capture for dynamic ML computation patterns"], "relevance": "CUDA graph management requires kernel-level GPU driver interactions — command buffer submission, memory pinning, and DMA scheduling.", "methodology": "Compiler-GPU runtime co-optimization for ML", "concepts": ["DMA Mapping Framework"]},
    {"ev_id": "ev-osdi26-giridharan", "key_ideas": ["Racing-based optimization for Byzantine fault-tolerant consensus", "Ambulance reduces BFT latency by speculatively executing on fast paths"], "relevance": "Not directly kernel-related. Distributed consensus protocol optimization.", "methodology": "BFT consensus protocol design with speculative execution", "concepts": []},
    {"ev_id": "ev-osdi26-he-baoding", "key_ideas": ["Neuro-symbolic proof generation for verifying systems software", "Combines neural networks with symbolic reasoning for automated verification at scale"], "relevance": "Directly relevant to kernel verification. Could be applied to verify Linux kernel invariants, memory safety properties, and concurrency correctness.", "methodology": "Neuro-symbolic AI for formal systems verification", "concepts": []},
    {"ev_id": "ev-osdi26-hu-guanzhou", "key_ideas": ["Localized linearizable reads via roster leases in distributed systems", "Bodega achieves strong consistency for reads without cross-datacenter coordination"], "relevance": "Not directly kernel-related. Distributed storage consistency protocol.", "methodology": "Distributed consistency protocol design", "concepts": []},
    {"ev_id": "ev-osdi26-huang-wenxuan", "key_ideas": ["Crypto-free mappings accelerate confidential database operations", "Eliminates cryptographic overhead in TEE-protected databases through memory mapping techniques"], "relevance": "Directly relevant to TEE support in the kernel (Intel TDX, AMD SEV). The crypto-free mapping technique requires kernel memory management changes for TEE enclaves.", "methodology": "TEE-assisted confidential computing optimization", "concepts": ["Linux Security Modules", "Hierarchical Page Tables"]},
    {"ev_id": "ev-osdi26-jiang-yu", "key_ideas": ["User-requirement-driven mandatory access control framework for operating systems", "USEC enables application developers to specify MAC policies without sysadmin intervention", "Bridges the gap between application security needs and OS-level MAC enforcement"], "relevance": "Directly extends Linux Security Modules. USEC proposes a new MAC framework that interacts with LSM hooks, SELinux/AppArmor policies, and capability-based access control.", "methodology": "Security framework design for mandatory access control", "concepts": ["Linux Security Modules", "POSIX Capabilities", "Seccomp-BPF"]},
    {"ev_id": "ev-osdi26-kim-jongyul", "key_ideas": ["Coordinated architecture for multi-component file systems", "Oxbow enables composing multiple filesystem implementations coherently", "Addresses the challenge of layered filesystem interactions (e.g., overlayfs + ext4 + dm-crypt)"], "relevance": "Directly targets the VFS layer and filesystem stacking in the kernel. Relevant to overlayfs, FUSE, device mapper, and how multiple filesystem layers interact.", "methodology": "Filesystem architecture design for composable storage stacks", "concepts": ["Virtual Filesystem Switch", "OverlayFS (Union Mount)", "Device Mapper"]},
    {"ev_id": "ev-osdi26-lai", "key_ideas": ["JANUS: Cross-world cooperative nested virtualization for secure containers", "Enables nested virtualization with cooperation between VM and container isolation domains", "Combines hardware virtualization (KVM) with container isolation for defense in depth"], "relevance": "Directly targets KVM nested virtualization and container security. Combines hardware-assisted isolation (VT-x/VT-d) with namespace/cgroup-based container isolation.", "methodology": "Nested virtualization architecture for secure container isolation", "concepts": ["KVM (Kernel-based Virtual Machine)", "Control Groups (cgroups v2)", "Namespaces", "Linux Security Modules"]},
    {"ev_id": "ev-osdi26-lee", "key_ideas": ["Metadata acceleration using CXL DRAM for sustainable big-data performance", "MAC places hot metadata on fast CXL-attached DRAM tier", "Addresses metadata bottleneck in large-scale data processing systems"], "relevance": "Directly relevant to CXL memory tiering and NUMA-aware allocation in the kernel. Metadata placement on CXL tiers requires kernel page migration and NUMA policy support.", "methodology": "CXL memory tiering for metadata-intensive workloads", "concepts": ["Adaptive CXL Memory Tiering", "NUMA Topology and Memory Policy", "Page Cache"]},
    {"ev_id": "ev-osdi26-lao", "key_ideas": ["Interruption-resilient runtime for ML training", "TrainMover handles preemptions, failures, and migrations without restarting training from scratch"], "relevance": "The checkpoint/restore and migration mechanisms require kernel support for process snapshotting, memory page migration, and cgroup-aware resource reallocation.", "methodology": "Resilient distributed systems design for ML training", "concepts": ["Process Creation (fork/clone)", "NUMA Topology and Memory Policy"]},
    {"ev_id": "ev-osdi26-lechowicz", "key_ideas": ["Signal-aware DAG scheduling with dynamic provisioning for data processing clusters", "SPADE uses workload signals to optimize task scheduling and resource allocation"], "relevance": "The cluster scheduling interacts with kernel-level cgroup resource controls and CPU scheduling for container-based task execution.", "methodology": "Signal-driven cluster scheduling with dynamic resource provisioning", "concepts": ["Scheduling Classes", "Control Groups (cgroups v2)"]},
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
