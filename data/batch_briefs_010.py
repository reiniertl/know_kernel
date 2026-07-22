"""Batch 10: Fill remaining feed page 1-3 gaps. Mix of kernel-relevant
and hardware/ML papers that need at least a minimal brief."""
import json, sqlite3, uuid

DB_PATH = "data/master.db"

BRIEFS = [
    {"ev_id": "ev-arxiv-ebpf-verifier-diagnostic-gap-analysis", "key_ideas": ["Identifies gaps in eBPF verifier diagnostic messages", "Maps verifier rejection reasons to improve developer debugging experience", "Catalogs undocumented verifier behaviors affecting eBPF program development"], "relevance": "Directly targets the Linux eBPF verifier — the kernel's primary safety gate for BPF program loading. Better diagnostics improve the eBPF development ecosystem.", "methodology": "Systematic analysis of eBPF verifier diagnostic output", "concepts": ["eBPF (Extended Berkeley Packet Filter)"]},
    {"ev_id": "ev-arxiv-c2ebfce7", "key_ideas": ["Access-control architecture for automated anomaly-driven network reconfiguration", "Closes the loop between anomaly detection and network policy enforcement"], "relevance": "Relevant to kernel netfilter and network namespace management for automated network security responses.", "methodology": "Automated network access control architecture", "concepts": ["Netfilter Hook Framework", "Network Namespaces"]},
    {"ev_id": "ev-arxiv-a02b2675", "key_ideas": ["Session-aware serverless serving for hundred-billion-parameter LLMs", "Talaria maintains session state across serverless invocations for conversational LLMs"], "relevance": "Serverless LLM serving exercises kernel container lifecycle management, cgroup resource isolation, and process snapshot/restore for warm starts.", "methodology": "Session-aware serverless system design for LLM inference", "concepts": ["Control Groups (cgroups v2)", "Namespaces"]},
    {"ev_id": "ev-arxiv-3266d6e0", "key_ideas": ["Measures realism gaps in malware-analysis sandboxes", "Quantifies how sandbox environments differ from real systems affecting malware behavior"], "relevance": "Malware sandboxes rely on kernel isolation — KVM, namespaces, seccomp, and ptrace. Realism gaps expose weaknesses in kernel-level sandbox fidelity.", "methodology": "Sandbox environment characterization for malware analysis", "concepts": ["KVM (Kernel-based Virtual Machine)", "Namespaces", "Seccomp-BPF"]},
    {"ev_id": "ev-arxiv-e6a38856", "key_ideas": ["Control-flow attestation via symbolic replay against control-flow bending attacks", "KS-CFA verifies runtime control flow integrity of embedded/kernel software"], "relevance": "Control-flow attestation is relevant to kernel integrity monitoring — verifying that kernel code follows expected control paths against rootkit-style attacks.", "methodology": "Symbolic execution for control-flow integrity verification", "concepts": ["Linux Security Modules"]},
    {"ev_id": "ev-arxiv-70903f2a", "key_ideas": ["Systematization of knowledge on mobile on-device AI system attacks and defenses", "Catalogs attack surfaces across model, runtime, OS, and hardware layers"], "relevance": "The OS layer attacks target kernel scheduling, memory isolation, and TEE boundaries. Defensive measures rely on kernel security mechanisms.", "methodology": "Systematization of knowledge for mobile AI security", "concepts": ["Linux Security Modules"]},
    {"ev_id": "ev-arxiv-b77c8baa", "key_ideas": ["Seekable OCI enables lazy-loading container images via range-request indexing", "Containers start before full image download — only accessed content is fetched on demand"], "relevance": "Exercises kernel overlayfs, FUSE, and page fault handler for on-demand content fetching from remote storage.", "methodology": "Lazy container image loading via range-request indexing", "concepts": ["OverlayFS (Union Mount)", "FUSE (Filesystem in Userspace)", "Page Fault Handler"]},
    {"ev_id": "ev-arxiv-bd9e1a43", "key_ideas": ["Multi-stage accelerated read stack for large-buffer buffered reads", "MARS optimizes the kernel read path for large sequential I/O operations"], "relevance": "Directly targets the kernel's VFS read path, page cache readahead, and block I/O scheduling for large buffered reads.", "methodology": "Storage I/O stack optimization for sequential reads", "concepts": ["Page Cache", "Block Device Layer", "Virtual Filesystem Switch"]},
    {"ev_id": "ev-arxiv-897da305", "key_ideas": ["Bounded-memory parallel downloading for large container images", "Prevents OOM during concurrent image layer decompression for GPU/AI workloads"], "relevance": "Interacts with kernel cgroup memory limits, OOM killer, and page reclaim under memory pressure during container operations.", "methodology": "Memory-bounded container image pulling", "concepts": ["Control Groups (cgroups v2)", "OOM Killer"]},
    {"ev_id": "ev-arxiv-1b0903bf", "key_ideas": ["Control-flow attestation for heterogeneous CPU-GPU execution", "WarpGuard extends attestation to verify GPU kernel execution integrity"], "relevance": "Extends kernel security to GPU workloads — attestation requires kernel GPU driver cooperation and TEE support for GPU code integrity.", "methodology": "Cross-device control-flow attestation", "concepts": ["Linux Security Modules", "DMA Mapping Framework"]},
    {"ev_id": "ev-arxiv-44f93cce", "key_ideas": ["Stage-level executor allocation in Apache Spark with cost-performance tradeoffs", "Dynamic resource allocation at Spark stage granularity rather than job level"], "relevance": "Spark executor allocation exercises kernel cgroup CPU/memory limits and container scheduling at the OS level.", "methodology": "Dynamic resource allocation for distributed data processing", "concepts": ["Control Groups (cgroups v2)", "Scheduling Classes"]},
    {"ev_id": "ev-arxiv-f4a04417", "key_ideas": ["Function-based framework for edge computing", "EdgeFaaS provides serverless abstractions for edge device workloads"], "relevance": "Edge serverless exercises kernel container namespaces, cgroup resource isolation, and lightweight process management for function invocations.", "methodology": "Serverless edge computing framework design", "concepts": ["Namespaces", "Control Groups (cgroups v2)"]},
    {"ev_id": "ev-arxiv-b26bd626", "key_ideas": ["Monitoring vulnerabilities in next-generation automotive operating systems", "Identifies security weaknesses in automotive Linux/AUTOSAR platforms"], "relevance": "Automotive Linux security relies on kernel LSM, seccomp, and namespace isolation. Vulnerability monitoring targets kernel-level attack surfaces.", "methodology": "Automotive OS vulnerability analysis", "concepts": ["Linux Security Modules"]},
    {"ev_id": "ev-arxiv-dbb8077b", "key_ideas": ["Cross-layer denial-of-service quality attack exploiting side channels", "DoSQ degrades service quality by exploiting microarchitectural side channels"], "relevance": "Side-channel DoS attacks exploit kernel-managed shared resources — CPU caches, TLBs, and memory bus. Defense requires kernel-level resource partitioning.", "methodology": "Side-channel-based denial-of-service attack analysis", "concepts": ["Linux Security Modules", "Translation Lookaside Buffer"]},
    {"ev_id": "ev-arxiv-054aa75f", "key_ideas": ["Fast durable storage engine for modern databases", "FlintKV optimizes write-ahead logging and compaction for NVMe storage"], "relevance": "Directly relevant to kernel block I/O and NVMe driver performance. The storage engine exercises io_uring, direct I/O, and NVMe command submission.", "methodology": "Storage engine design for NVMe devices", "concepts": ["NVMe Driver Subsystem", "io_uring", "Block Device Layer"]},
    {"ev_id": "ev-arxiv-eaaed8f6", "key_ideas": ["Self-evolving agentic operating system for autonomous web exploration", "Mako OS-level abstractions for AI agent lifecycle management"], "relevance": "Proposes OS-level abstractions for AI agents — relates to kernel process management, sandboxing, and resource isolation for autonomous agents.", "methodology": "Agentic OS architecture design", "concepts": ["Process Creation (fork/clone)", "Namespaces"]},
    {"ev_id": "ev-arxiv-633c4f88", "key_ideas": ["Data structures for private token transfers in TEE-based networks", "Efficient oblivious data structures within hardware enclaves"], "relevance": "TEE-based data structures require kernel SGX/TDX enclave management and secure memory allocation.", "methodology": "Oblivious data structure design for TEE environments", "concepts": ["Linux Security Modules"]},
    {"ev_id": "ev-arxiv-c6212bdc", "key_ideas": ["State as a runtime control problem in parallel and distributed systems", "Proposes treating state management as active control rather than passive storage"], "relevance": "State management as a control problem is relevant to kernel state machines — scheduling state, memory management state, and I/O request state.", "methodology": "State management paradigm for distributed systems", "concepts": []},
    {"ev_id": "ev-arxiv-027e07c3", "key_ideas": ["Survey of side-channel vulnerabilities and countermeasures in deep learning hardware", "Catalogs power, timing, and EM side channels in DNN accelerators"], "relevance": "Hardware side-channel defenses require kernel-level countermeasures — cache partitioning, timing isolation, and DMA access control.", "methodology": "Systematization of hardware side-channel attacks on DNN accelerators", "concepts": ["Linux Security Modules"]},
    {"ev_id": "ev-arxiv-77273082", "key_ideas": ["Automated tensor scheduling for hybrid CPU-GPU LLM inference on consumer devices", "Optimizes operator placement across CPU and GPU for on-device inference"], "relevance": "CPU-GPU scheduling coordination requires kernel-level thread scheduling, DMA for data transfers, and NUMA-aware memory placement.", "methodology": "Hybrid CPU-GPU inference scheduling optimization", "concepts": ["Scheduling Classes", "DMA Mapping Framework"]},
    {"ev_id": "ev-arxiv-be0371e6", "key_ideas": ["Systematization of execution-security research for AI coding agents", "Identifies fragmentation in isolation approaches for AI agent sandboxing"], "relevance": "Agent isolation relies on kernel sandboxing — containers, VMs, seccomp, and capability-based isolation. The balkanization reflects gaps in kernel isolation mechanisms.", "methodology": "Systematization of AI agent isolation approaches", "concepts": ["Seccomp-BPF", "Namespaces", "KVM (Kernel-based Virtual Machine)"]},
    {"ev_id": "ev-arxiv-46898c2e", "key_ideas": ["Cyber-physical vulnerability exploiting GPU workloads across power and thermal domains", "Bit2Watt demonstrates that GPU workload patterns can affect physical power delivery"], "relevance": "GPU power/thermal attacks interact with kernel thermal management, RAPL power capping, and GPU driver power state management.", "methodology": "Cyber-physical attack analysis on GPU power delivery", "concepts": ["Thermal Management Framework", "CPU Frequency Scaling (cpufreq)"]},
    {"ev_id": "ev-arxiv-4efa1e0b", "key_ideas": ["Cross-core inference offload as an OS service on dual-core microcontrollers", "Treats ML inference as a first-class OS service with dedicated core allocation"], "relevance": "Inference as an OS service directly proposes kernel-level scheduling abstractions for ML workloads on embedded multi-core processors.", "methodology": "OS service design for embedded ML inference", "concepts": ["Scheduling Classes"]},
    {"ev_id": "ev-arxiv-0824bca5", "key_ideas": ["Scaling unmodified multithreaded applications with elastic CXL-based distributed shared memory", "Transparently extends application memory via CXL without code changes"], "relevance": "Directly targets kernel CXL memory management — transparent CXL expansion requires kernel page migration, NUMA policy changes, and CXL device driver support.", "methodology": "Transparent CXL memory expansion for legacy applications", "concepts": ["Adaptive CXL Memory Tiering", "NUMA Topology and Memory Policy", "Page Fault Handler"]},
    {"ev_id": "ev-arxiv-5d100c63", "key_ideas": ["Leveraging high-bandwidth flash for high-throughput LLM inference", "FlashAccel uses NVMe flash as an extended memory tier for LLM KV caches"], "relevance": "Flash-as-memory for LLM inference exercises kernel NVMe driver, block I/O, and memory tiering — treating flash as a slow memory tier below DRAM.", "methodology": "Flash-based memory extension for LLM inference", "concepts": ["NVMe Driver Subsystem", "Block Device Layer"]},
    {"ev_id": "ev-arxiv-10d53d99", "key_ideas": ["Survey of KV cache management from tensor buffer to distributed memory hierarchy", "Catalogs approaches for managing LLM attention caches across memory tiers"], "relevance": "KV cache management maps to kernel memory tiering concepts — page cache, CXL tiers, swap, and distributed memory. The survey covers kernel-relevant memory hierarchy decisions.", "methodology": "Survey of memory hierarchy management for LLM caches", "concepts": ["Page Cache", "Adaptive CXL Memory Tiering"]},
    {"ev_id": "ev-arxiv-d46a7857", "key_ideas": ["Dissects hidden efficiency bottlenecks in mobile NPU LLM inference", "Identifies where NPU hardware underperforms relative to theoretical capability"], "relevance": "NPU efficiency bottlenecks interact with kernel driver scheduling, DMA throughput, and power management for mobile accelerators.", "methodology": "NPU performance characterization for mobile LLM inference", "concepts": ["CPU Frequency Scaling (cpufreq)", "DMA Mapping Framework"]},
    {"ev_id": "ev-arxiv-9bd0c0f1", "key_ideas": ["High-goodput disaggregated serving for MoE LLMs with adaptive routing", "ExpertPlex routes expert requests across disaggregated GPU resources"], "relevance": "Disaggregated MoE serving exercises kernel RDMA networking, CXL memory, and cgroup resource management across distributed inference workers.", "methodology": "Disaggregated inference system design for MoE models", "concepts": ["Control Groups (cgroups v2)", "Adaptive CXL Memory Tiering"]},
    {"ev_id": "ev-arxiv-d27c4a42", "key_ideas": ["Fine-grained computation offload for off-the-shelf servers in tens of lines", "Minimal-code approach to offloading compute to SmartNICs or accelerators"], "relevance": "Computation offload requires kernel driver support for SmartNIC programming, DMA for data transfer, and device model integration.", "methodology": "Lightweight computation offload framework", "concepts": ["DMA Mapping Framework"]},
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
                try: conn.execute("INSERT INTO edges (kind, source_id, target_id, attrs) VALUES ('extracted-from', ?, ?, '{}')", (cid, ev_id))
                except: pass
        created += 1
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    total = conn.execute("SELECT count(*) FROM nodes WHERE kind = 'ResearchBrief'").fetchone()[0]
    remaining = conn.execute('''
        SELECT count(*) FROM nodes s
        JOIN edges se ON se.kind = 'sourced-from' AND se.target_id = s.id
        JOIN nodes ev ON ev.id = se.source_id AND ev.kind = 'Evidence'
        WHERE s.kind = 'Source'
        AND json_extract(s.attrs, '$.source_type') IN ('paper','preprint','conference-paper','conference-proceedings')
        AND NOT EXISTS (
            SELECT 1 FROM nodes rb JOIN edges re ON re.source_id = rb.id
            WHERE rb.kind = 'ResearchBrief' AND re.kind = 'extracted-from' AND re.target_id = ev.id
        )
        AND json_extract(s.attrs, '$.published_date') >= '2026-07-01'
    ''').fetchone()[0]
    print(f"Created {created} briefs. Total: {total}. Remaining July 2026: {remaining}")
    conn.close()

if __name__ == "__main__":
    main()
