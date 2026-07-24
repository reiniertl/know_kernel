"""Deep enrichment batch 018: 15 conference papers — ASPLOS, EuroSys, SOSP continued.
Focus on kernel-touching papers from the remaining conference backlog.
"""
import json, sqlite3, uuid

DB_PATH = "data/master.db"

ALL_PAPERS = [
    # ── 1. Tiny Quanta: Microsecond Blind Scheduling ──────────────
    {"ev_id": "ev-conf-2099e0ee", "brief": {
        "key_ideas": ["Efficient blind scheduling with tiny quanta (microsecond-scale) for datacenter request handling", "No assumptions about job duration or distribution — requires frequent and efficient preemption at μs granularity", "Achieves high throughput and low tail latency for very short jobs spawned by client requests", "Scalable preemption mechanism that works at microsecond timescales where existing kernel preemption is too coarse"],
        "relevance": "Directly addresses the kernel scheduler's preemption granularity. The Linux kernel's default timer tick (1-4ms) is too coarse for μs-scale job scheduling. TQ requires sub-millisecond preemption — relevant to the kernel's hrtimer, PREEMPT_RT, and the ongoing work on microsecond-scale scheduling (sched_ext, user interrupts). The blind scheduling model (no duration assumptions) contrasts with the kernel's CFS/EEVDF which track virtual runtime.",
        "methodology": "ASPLOS. Microsecond-scale blind scheduling. Scalable preemption mechanism. Throughput and tail latency evaluation."
    }, "concepts": ["Scheduling Classes", "Interrupt Handling"], "claims": [
        {"kind": "Problem", "id_prefix": "prob", "name": "Kernel preemption too coarse for microsecond job scheduling", "description": "Existing kernel schedulers cannot efficiently preempt at microsecond granularity needed for datacenter request handling. Blind scheduling (no job duration knowledge) requires frequent preemption that current kernel mechanisms don't scale to."},
        {"kind": "Proposal", "id_prefix": "prop", "name": "Tiny quanta for microsecond-scale blind scheduling", "description": "Scalable preemption at μs granularity for blind scheduling of datacenter jobs. No assumptions about duration distribution. Achieves high throughput and low tail latency."}
    ]},

    # ── 2. Cornucopia Reloaded: CHERI Heap Temporal Safety ────────
    {"ev_id": "ev-conf-b805a458", "brief": {
        "key_ideas": ["Load barriers for CHERI heap temporal memory safety — addresses use-after-free vulnerabilities", "Builds on CHERI capability architecture which provides spatial memory safety for C/C++", "Load barriers ensure that freed memory cannot be accessed via stale capabilities — temporal safety on top of spatial", "Addresses the remaining gap after CHERI provides spatial safety: temporal violations (UAF) still possible"],
        "relevance": "Directly relevant to the kernel's CHERI support and the broader push for hardware-enforced memory safety. The Linux kernel is being ported to CHERI (Arm Morello) — temporal safety (preventing UAF in kernel code) is the harder problem that CHERI's spatial safety alone doesn't solve. Load barriers add runtime checks at memory load time, which affects every pointer dereference in kernel code. This determines the performance cost of full memory safety for the kernel.",
        "methodology": "ASPLOS. CHERI load barrier implementation. Temporal memory safety for C/C++. Performance evaluation of UAF prevention."
    }, "concepts": ["SLUB Allocator"], "claims": [
        {"kind": "Problem", "id_prefix": "prob", "name": "CHERI spatial safety leaves temporal (UAF) vulnerabilities open", "description": "CHERI provides hardware-enforced spatial memory safety for C/C++ via capabilities. But use-after-free (temporal violations) remain possible — freed memory can still be accessed through stale capabilities until they're revoked."},
        {"kind": "Proposal", "id_prefix": "prop", "name": "Load barriers for CHERI heap temporal memory safety", "description": "Cornucopia Reloaded adds load barriers that check capability validity at every memory load, preventing access to freed memory via stale capabilities. Provides full temporal safety on top of CHERI's spatial guarantees."}
    ]},

    # ── 3. Direct Memory Translation for Virtualized Clouds ───────
    # Already done in batch 015 — skip

    # ── 4. Concurrency-Informed Serverless Orchestration ──────────
    {"ev_id": "ev-conf-ed8998e6", "brief": {
        "key_ideas": ["Identifies new challenges in FaaS keep-alive policies that state-of-the-art platforms miss", "Cold start mitigation via keeping function containers alive is complicated by concurrency patterns", "Concurrency-informed orchestration improves warm start rates without excessive memory consumption", "Targets the kernel's container lifecycle management for serverless platforms"],
        "relevance": "Relevant to the kernel's cgroup and namespace lifecycle management. FaaS platforms create/destroy containers rapidly — the kernel must handle high container churn efficiently. Keep-alive decisions depend on memory pressure (cgroup memory limits) and process state. The concurrency-aware approach means the kernel needs to expose container concurrency information to orchestrators via cgroup/proc interfaces.",
        "methodology": "ASPLOS. FaaS keep-alive optimization. Concurrency-informed container lifecycle. Memory and warm-start tradeoff analysis."
    }, "concepts": ["Namespaces", "Control Groups (cgroups v2)"], "claims": [
        {"kind": "Proposal", "id_prefix": "prop", "name": "Concurrency-informed serverless container keep-alive", "description": "Concurrency-aware orchestration for FaaS container keep-alive decisions, improving warm start rates without excessive memory consumption. Addresses new challenges in container lifecycle management at serverless scale."}
    ]},

    # ── 5. Embracing Imbalance: Container Load Shifting ──────────
    {"ev_id": "ev-conf-9a950195", "brief": {
        "key_ideas": ["Dynamic load shifting among microservice containers to address temporal and spatial performance imbalance", "Traditional load-balancing causes over-provisioning in shared clusters when containers have uneven load", "Shifts work between containers of the same microservice rather than scaling out", "Reduces resource wastage from over-provisioning to meet SLAs"],
        "relevance": "Relevant to the kernel's cgroup CPU/memory accounting and container resource management. Load shifting between containers requires the kernel to support efficient resource rebalancing (cgroup limit adjustment, CPU affinity changes) without container restart. The temporal/spatial imbalance is observable through the kernel's PSI (Pressure Stall Information) interface.",
        "methodology": "ASPLOS. Dynamic container load shifting. Shared cluster evaluation. SLA compliance with reduced over-provisioning."
    }, "concepts": ["Control Groups (cgroups v2)", "Scheduling Classes"], "claims": [
        {"kind": "Proposal", "id_prefix": "prop", "name": "Dynamic load shifting between microservice containers", "description": "Shifts work between containers of the same microservice to handle temporal/spatial performance imbalance, reducing over-provisioning waste while meeting SLAs in shared clusters."}
    ]},

    # ── 6. MaxEmbed: SSD Bandwidth for Embedding Models ──────────
    {"ev_id": "ev-conf-5ec32dca", "brief": {
        "key_ideas": ["Maximizes SSD bandwidth utilization for serving huge embedding tables in recommendation models", "Embedding tables are too large for GPU/DRAM — SSDs provide cost-effective capacity but have read amplification issues", "Addresses mismatch between embedding access patterns (small random reads) and SSD block I/O granularity", "Optimizes the SSD I/O path for the specific access patterns of embedding table lookups"],
        "relevance": "Relevant to the kernel's NVMe driver and block I/O layer for embedding model serving. The read amplification problem (small embedding reads vs large SSD page reads) is a kernel block I/O issue — the kernel's I/O scheduler and readahead logic are designed for sequential/large I/O, not the tiny random reads that embedding lookups generate. This motivates NVMe passthrough or io_uring direct I/O for embedding access.",
        "methodology": "ASPLOS. SSD bandwidth optimization for embedding models. Read amplification analysis. I/O path optimization."
    }, "concepts": ["NVMe Driver Subsystem", "Block Device Layer"], "claims": [
        {"kind": "Problem", "id_prefix": "prob", "name": "SSD read amplification for embedding table access", "description": "Embedding tables in recommendation models are too large for GPU/DRAM. SSDs provide capacity but suffer read amplification: small random embedding reads (tens of bytes) trigger full SSD page reads (4-16KB), wasting bandwidth."}
    ]},

    # ── 7. Will We Ever Have Truly Secure Operating Systems? ──────
    {"ev_id": "ev-conf-33f481b4", "brief": {
        "key_ideas": ["Retrospective on OS security from PSOS to seL4 — half a century after first attempts to prove an OS secure, OS faults remain a major threat", "seL4 microkernel was the first proof of implementation correctness of an OS kernel — a major milestone", "Examines what remains after formal verification: the gap between verified correctness and practical security", "Assesses the path toward truly secure operating systems — what verification has achieved and what remains"],
        "relevance": "The most fundamental question in the corpus: can we have secure operating systems? Directly relevant to the Linux kernel's security posture — Linux is unverified and will remain so due to its size. This paper assesses what seL4's verification means for practical security and what the kernel community can learn. The gap between formal correctness and practical security (hardware bugs, side channels, specification completeness) applies directly to the Linux kernel's defense strategy.",
        "methodology": "ASPLOS. Retrospective/position paper. PSOS to seL4 history. Security guarantee analysis."
    }, "concepts": ["Linux Security Modules"], "claims": [
        {"kind": "Observation", "id_prefix": "obs", "name": "Half century after PSOS, OS faults still a major security threat", "description": "Despite seL4's proof of implementation correctness (the first verified OS kernel), OS security remains an open problem. The gap between formal verification and practical security (hardware vulnerabilities, side channels, specification completeness) means truly secure operating systems remain elusive."}
    ]},

    # ── 8. AlloyStack: Library OS for Serverless Workflows ────────
    {"ev_id": "ev-conf-7243bf00", "brief": {
        "key_ideas": ["Library OS tailored for serverless workflow applications composed of multiple serverless functions", "Addresses inter-function communication and cold start latency — the key serverless performance bottlenecks", "LibOS approach shares kernel resources within a workflow while maintaining function isolation", "Optimizes for the multi-function workflow pattern rather than individual function invocations"],
        "relevance": "A library OS that runs on the Linux kernel — relevant to the kernel's interface with specialized runtimes. AlloyStack uses the kernel's namespace and cgroup mechanisms differently than traditional containers: sharing resources within a workflow while isolating between workflows. The cold start optimization likely uses the kernel's fork/clone for fast function instantiation within the LibOS. Published at EuroSys.",
        "methodology": "EuroSys. Library OS for serverless workflows. Inter-function communication optimization. Cold start latency reduction."
    }, "concepts": ["Namespaces", "Process Creation (fork/clone)"], "claims": [
        {"kind": "Proposal", "id_prefix": "prop", "name": "Library OS optimized for multi-function serverless workflows", "description": "AlloyStack is a LibOS tailored for serverless workflow applications. Shares kernel resources within a workflow for fast inter-function communication while maintaining function isolation. Reduces cold start latency for multi-function patterns."}
    ]},

    # ── 9. Deft: Scalable Tree Index for Disaggregated Memory ─────
    {"ev_id": "ev-conf-1e4162fa", "brief": {
        "key_ideas": ["Scalable tree-based index for disaggregated memory — addresses inefficiency of traditional indexes on separate compute/memory pools", "Memory disaggregation enables independent scaling but traditional tree nodes cause excessive network round-trips", "Designed for CXL/RDMA disaggregated memory where compute and memory are in different pools", "Addresses the fundamental mismatch between tree traversal (sequential pointer chasing) and remote memory access (high-latency)"],
        "relevance": "Relevant to how the kernel should manage indexes on CXL-attached disaggregated memory. The kernel's own internal indexes (radix tree for page cache, red-black trees for VMA management) face the same problem on CXL — pointer chasing through remote memory is expensive. Deft's techniques for reducing remote memory round-trips in tree traversal could inform kernel data structure design for CXL-aware page management.",
        "methodology": "EuroSys. Tree index design for disaggregated memory. CXL/RDMA memory model. Scalability evaluation."
    }, "concepts": ["Adaptive CXL Memory Tiering", "NUMA Topology and Memory Policy"], "claims": [
        {"kind": "Problem", "id_prefix": "prob", "name": "Tree indexes inefficient on disaggregated memory due to pointer chasing", "description": "Traditional tree-based indexes cause excessive network round-trips on disaggregated memory because tree traversal requires sequential pointer chasing through high-latency remote memory."},
        {"kind": "Proposal", "id_prefix": "prop", "name": "Disaggregated-memory-aware tree index design", "description": "Deft provides a scalable tree index optimized for CXL/RDMA disaggregated memory, minimizing remote memory round-trips during tree traversal while maintaining scalability."}
    ]},

    # ── 10. Empowering WASM with Thin Kernel Interfaces ──────────
    {"ev_id": "ev-conf-9d29e6f1", "brief": {
        "key_ideas": ["Adds standard system interfaces to WebAssembly, addressing the lack of kernel interfaces that hinders WASM adoption outside the browser", "WASM's ISA portability, low memory footprint, and sandboxing are attractive but missing system interfaces limit reusability of existing software", "Thin kernel interfaces provide WASM modules access to OS resources without breaking the sandbox model", "Enables efficient in-process sandboxing with OS interaction for non-browser WASM use cases"],
        "relevance": "Defines how WASM modules interact with the Linux kernel — the WASI (WebAssembly System Interface) is essentially a syscall interface for WASM. This is relevant to the kernel's seccomp filtering for WASM runtimes, cgroup resource limits for WASM containers, and the ongoing standardization of WASM system interfaces. Published at EuroSys.",
        "methodology": "EuroSys. WASM system interface design. Thin kernel interface specification. WASM runtime OS integration."
    }, "concepts": ["Seccomp-BPF", "Namespaces"], "claims": [
        {"kind": "Proposal", "id_prefix": "prop", "name": "Thin kernel interfaces for WebAssembly outside the browser", "description": "Standard system interfaces that give WASM modules access to OS resources without breaking the sandbox model. Addresses the missing kernel interface that prevents WASM adoption for non-browser use cases."}
    ]},

    # ── 11. Cherifying Linux: CHERI on a Real Kernel ──────────────
    {"ev_id": "ev-conf-613fa1b5", "brief": {
        "key_ideas": ["Practical view on using CHERI ISA extension with the Linux kernel — the first attempt to apply CHERI to a full production kernel", "CHERI enforces memory safety in C/C++ via hardware capabilities on RISC-V architecture", "Addresses the challenges of applying CHERI to a large, complex codebase like the Linux kernel vs small point solutions", "Reports practical experience from the effort of adding CHERI support to Linux"],
        "relevance": "The most directly Linux-kernel-relevant CHERI paper. While other CHERI papers target enclaves or interpreters, this one tackles the Linux kernel itself. The challenges reported (porting a large C codebase with extensive pointer manipulation, assembly code, and hardware interaction to CHERI) are unique to kernel-level software. This informs the kernel community about what CHERI adoption actually requires — not theoretical but practical experience.",
        "methodology": "EuroSys. CHERI porting of Linux kernel. Practical challenge documentation. RISC-V CHERI ISA."
    }, "concepts": [], "claims": [
        {"kind": "Observation", "id_prefix": "obs", "name": "CHERI-ifying Linux reveals unique kernel porting challenges", "description": "Applying CHERI hardware memory safety to the Linux kernel encounters challenges unique to kernel code: extensive raw pointer manipulation, inline assembly, hardware interaction patterns, and a codebase too large for the point-solution approaches that prior CHERI work targeted."}
    ]},

    # ── 12. SmartNIC Thin Hypervisor for Multi-Tenant Edge ────────
    {"ev_id": "ev-conf-5090ff28", "brief": {
        "key_ideas": ["Thin hypervisor approach for multi-tenant SmartNICs in edge data centers — enables sharing SmartNIC resources between tenants", "SmartNICs can offload processing to reduce service response times but need isolation for multi-tenancy", "Lightweight hypervisor provides isolation without the overhead of full virtualization on the SmartNIC", "Targets post-5G edge environments where response time is critical"],
        "relevance": "Relevant to the kernel's SmartNIC and NIC driver management. The kernel currently manages SmartNICs as network devices via standard NIC drivers — a thin hypervisor on the SmartNIC adds a virtualization layer below the kernel's NIC driver. This affects how the kernel sees and manages the SmartNIC (virtio interface vs hardware direct access). Also relevant to the kernel's VFIO for SmartNIC passthrough to tenants.",
        "methodology": "EuroSys. SmartNIC thin hypervisor. Multi-tenant isolation. Edge datacenter evaluation."
    }, "concepts": ["Virtio Paravirtual I/O", "VFIO (Virtual Function I/O)"], "claims": [
        {"kind": "Proposal", "id_prefix": "prop", "name": "Thin hypervisor for multi-tenant SmartNIC sharing at the edge", "description": "Lightweight hypervisor on SmartNICs provides multi-tenant isolation for edge data centers without full virtualization overhead. Enables sharing SmartNIC offload capabilities between tenants."}
    ]},

    # ── 13. HyperAlloc: VM Memory De/Inflation ───────────────────
    # Already done in batch 016 — skip

    # ── 14. FastIOV: SR-IOV for Secure Containers ────────────────
    # Already done in batch 016 — skip

    # ── 15. Revealing Unstable Foundations of eBPF Extensions ──────
    {"ev_id": "ev-conf-8a97279c", "brief": {
        "key_ideas": ["Reveals that eBPF-based kernel extensions have unstable foundations — the kernel interfaces they depend on can change without notice", "eBPF programs hook into kernel functions that are not stable ABI — kernel updates can silently break deployed eBPF programs", "Quantifies the instability: measures how frequently eBPF hook points change across kernel versions", "Proposes approaches to improve stability of eBPF-kernel interfaces without ossifying kernel internals"],
        "relevance": "Directly addresses a critical challenge for the Linux kernel's eBPF ecosystem. eBPF programs (from Cilium, Falco, bpftrace, etc.) hook into kernel functions that are internal implementation details — not stable ABI. This means kernel updates can break production eBPF programs. This paper quantifies the problem and proposes solutions. The tension between kernel freedom to change internals and eBPF's need for stable hooks is one of the most important eBPF ecosystem challenges. Published at EuroSys.",
        "methodology": "EuroSys. eBPF hook stability analysis across kernel versions. Quantitative measurement of hook point changes. Stability improvement proposals."
    }, "concepts": ["eBPF (Extended Berkeley Packet Filter)"], "claims": [
        {"kind": "Problem", "id_prefix": "prob", "name": "eBPF kernel extensions depend on unstable internal interfaces", "description": "eBPF programs hook into kernel functions that are not stable ABI. Kernel updates can silently break deployed eBPF programs from projects like Cilium and Falco. The instability creates a tension between kernel development freedom and eBPF ecosystem reliability."}
    ]},

    # ── 16. Daredevil: NVMe Multi-Tenant I/O ────────────────────
    # Already done in batch 016 — skip

    # ── 17. EXIST: Intra-Service Tracing Observability ──────────
    {"ev_id": "ev-conf-213eb9ec", "brief": {
        "key_ideas": ["Extremely efficient intra-service tracing for datacenter observability — captures both inter-service RPC traces and intra-service execution traces", "Current tracing gets inter-service data via RPC-level tracing but misses intra-service execution details", "Near-zero overhead tracing enables always-on observability without performance impact", "Targets the gap between RPC traces (what service was called) and execution traces (what happened inside the service)"],
        "relevance": "Relevant to the kernel's tracing infrastructure (ftrace, perf, eBPF tracepoints) that underpins datacenter observability. Intra-service tracing likely uses kernel tracepoints and perf events to capture execution details within a service process. The near-zero overhead goal pushes the limits of what the kernel's tracing mechanisms can deliver. Published at ASPLOS.",
        "methodology": "ASPLOS. Intra-service execution tracing. Near-zero overhead design. Datacenter-scale evaluation."
    }, "concepts": ["Ftrace", "Perf Events Subsystem"], "claims": [
        {"kind": "Proposal", "id_prefix": "prop", "name": "Near-zero overhead intra-service execution tracing", "description": "EXIST captures both inter-service RPC traces and intra-service execution details with near-zero overhead, enabling always-on observability for understanding application behavior inside services, not just between them."}
    ]},

    # ── 18. NDPipe: Near-Data Processing for Photo Storage ────────
    {"ev_id": "ev-conf-42428478", "brief": {
        "key_ideas": ["Accelerates training and inference on image data by leveraging near-data processing in storage servers", "Distributes commodity GPUs in storage servers for near-data ML processing rather than centralized GPU clusters", "Reduces data movement by processing images where they're stored — near-data computation for ML workloads", "Novel photo storage architecture that integrates ML processing into the storage tier"],
        "relevance": "Relevant to the kernel's storage and GPU driver management — NDPipe runs GPU workloads on storage servers, requiring the kernel to manage both NVMe storage and GPU compute on the same node. The near-data processing model means the kernel's I/O path (NVMe → page cache → GPU DMA) must be optimized for local GPU-storage data flow. Published at ASPLOS.",
        "methodology": "ASPLOS. Near-data ML processing in storage servers. Commodity GPU + storage co-location. Training and inference acceleration."
    }, "concepts": ["NVMe Driver Subsystem"], "claims": [
        {"kind": "Proposal", "id_prefix": "prop", "name": "Near-data ML processing in storage servers with commodity GPUs", "description": "NDPipe distributes commodity GPUs in storage servers for near-data training and inference on image data, reducing data movement by processing images where they're stored."}
    ]},
]


def main():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")

    concepts_map = {}
    for r in conn.execute("SELECT id, json_extract(attrs, '$.name') FROM nodes WHERE kind = 'Concept'").fetchall():
        if r[1]: concepts_map[r[1].lower()] = r[0]

    stats = {"briefs": 0, "claims": 0, "edges": 0}

    for paper in ALL_PAPERS:
        ev_id = paper["ev_id"]
        brief = paper["brief"]

        existing = conn.execute(
            "SELECT 1 FROM nodes rb JOIN edges re ON re.source_id = rb.id "
            "WHERE rb.kind = 'ResearchBrief' AND re.kind = 'extracted-from' AND re.target_id = ?", (ev_id,)
        ).fetchone()
        if existing:
            print(f"  SKIP: {ev_id}"); continue

        title_row = conn.execute(
            "SELECT json_extract(s.attrs, '$.title'), json_extract(s.attrs, '$.published_date') "
            "FROM edges se JOIN nodes s ON s.id = se.target_id WHERE se.kind = 'sourced-from' AND se.source_id = ?", (ev_id,)
        ).fetchone()
        title = title_row[0] if title_row else ""; date = title_row[1] if title_row else "2025-01-01"

        brief_id = f"rb-{uuid.uuid4().hex[:12]}"
        conn.execute("INSERT INTO nodes (id, kind, attrs) VALUES (?, 'ResearchBrief', ?)",
            (brief_id, json.dumps({"title": title, "key_ideas": json.dumps(brief["key_ideas"]),
             "relevance": brief["relevance"], "methodology": brief["methodology"],
             "source_date": date or "2025-01-01", "artifact_class": "A"})))
        conn.execute("INSERT INTO edges (kind, source_id, target_id, attrs) VALUES ('extracted-from', ?, ?, '{}')", (brief_id, ev_id))
        stats["briefs"] += 1

        for cname in paper["concepts"]:
            cid = concepts_map.get(cname.lower())
            if cid:
                try: conn.execute("INSERT INTO edges (kind, source_id, target_id, attrs) VALUES ('summarizes-for', ?, ?, '{}')", (brief_id, cid)); stats["edges"] += 1
                except: pass
                try: conn.execute("INSERT INTO edges (kind, source_id, target_id, attrs) VALUES ('extracted-from', ?, ?, '{}')", (cid, ev_id)); stats["edges"] += 1
                except: pass

        for claim in paper["claims"]:
            claim_id = f"{claim['id_prefix']}-{uuid.uuid4().hex[:12]}"
            conn.execute("INSERT INTO nodes (id, kind, attrs) VALUES (?, ?, ?)",
                (claim_id, claim["kind"], json.dumps({"name": claim["name"], "description": claim["description"], "source_date": date or "2025-01-01"})))
            conn.execute("INSERT INTO edges (kind, source_id, target_id, attrs) VALUES ('extracted-from', ?, ?, '{}')", (claim_id, ev_id))
            stats["claims"] += 1; stats["edges"] += 1

        print(f"  OK: {title[:60].encode('ascii', 'replace').decode()}")

    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    tb = conn.execute("SELECT count(*) FROM nodes WHERE kind = 'ResearchBrief'").fetchone()[0]
    tc = conn.execute("SELECT count(*) FROM nodes WHERE kind IN ('Problem','Observation','Proposal','PerformanceProfile','FailureMode','Benchmark')").fetchone()[0]
    ta = conn.execute("SELECT count(*) FROM nodes WHERE kind = 'ResearchBrief' AND json_extract(attrs, '$.artifact_class') = 'A'").fetchone()[0]
    print(f"\nCreated {stats['briefs']} briefs, {stats['claims']} claims, {stats['edges']} edges")
    print(f"Totals: {tb} briefs ({ta} Class A), {tc} claims in DB")
    conn.close()

if __name__ == "__main__":
    main()
