"""Deep enrichment batch 014: 8 papers — GPU virtual memory, WASM container security,
serverless elasticity, confidential computing survey, TEE agent confinement,
unikernel edge evaluation, WASM data transfer, Dandelion cloud platform.

Papers:
1. GPUVM — GPU-driven unified virtual memory without CPU/OS involvement
2. WASM Container Resource Isolation — Exploiting WASI for resource exhaustion attacks
3. CC for Agentic AI Survey — TEE platforms for agent security (SGX/TDX/SEV-SNP/CCA)
4. TEE Agent Confinement — TDX-backed operation plane for self-hosted computer-use agents
5. Dandelion — Microsecond-cold-start elastic serverless with pure-function sandboxes
6. Roadrunner — Zero-copy data transfer for WASM serverless via memory mapping
7. Unikernel Edge Evaluation — OSv/Nanos/Unikraft vs Docker on ARM edge devices
8. Hybrid Edge Containers+Unikernels — Container/unikernel co-design for IoT edge
"""
import json, sqlite3, uuid

DB_PATH = "data/master.db"

ALL_PAPERS = [
    # ── 1. GPUVM: GPU-Driven Virtual Memory ────────────────────────
    {
        "ev_id": "ev-arxiv-174bbf10",
        "brief": {
            "key_ideas": [
                "GPU memory management system that uses RDMA-capable network device to build virtual memory without CPU/OS involvement — GPU threads handle memory management and page migration directly",
                "Addresses GPU memory oversubscription: models and datasets exceed single GPU memory, and UVM (Unified Virtual Memory) brings OS overhead and inefficient page faulting",
                "Enables on-demand paging for GPU applications where GPU threads perform page fault handling and migration — eliminating CPU chipset bottleneck",
                "Supports irregular access patterns (deep learning, recommender systems, graph applications) where manual data partitioning is impractical"
            ],
            "relevance": "Proposes bypassing the kernel's virtual memory system entirely for GPU memory management — GPU threads do their own page fault handling via RDMA. This is the opposite of how the kernel currently manages GPU memory (through the DRM subsystem and CPU-side page fault handlers). If GPU-driven VM succeeds, the kernel's role shrinks to initial setup. Relevant to the kernel's GPU driver model, RDMA subsystem, and the ongoing debate about whether the kernel should manage GPU memory or just provide passthrough. The RDMA-based page migration is a novel use of the kernel's network stack for memory management.",
            "methodology": "GPU VM system using RDMA for CPU-free memory management. GPU thread-based page fault handling and migration. Evaluation on deep learning, recommender, and graph workloads."
        },
        "concepts": ["Page Fault Handler", "NUMA Topology and Memory Policy"],
        "claims": [
            {"kind": "Proposal", "id_prefix": "prop", "name": "GPU-driven virtual memory via RDMA without CPU/OS",
             "description": "GPUVM builds a virtual memory system where GPU threads handle page faults and migration using RDMA-capable NICs, bypassing the CPU/OS entirely. Enables on-demand paging for GPU applications with irregular access patterns."}
        ]
    },

    # ── 2. WASM Container Resource Isolation Attacks ────────────────
    {
        "ev_id": "ev-arxiv-77640319",
        "brief": {
            "key_ideas": [
                "Systematically explores the resource isolation attack surface of WebAssembly container runtimes — discovers that WASI/WASIX interfaces can be exploited to exhaust host resources",
                "Static Wasm runtime analysis approaches identify exploitable interfaces; exploitation strategies break resource isolation across multiple runtimes",
                "Malicious Wasm instances can consume large amounts of system resources and introduce high workloads into other container instances and host components",
                "Resource isolation is not well protected by current Wasm runtimes despite Wasm's reputation for strong security (linear memory, type checking, protected stacks)"
            ],
            "relevance": "Directly relevant to the kernel's resource isolation for the emerging Wasm-based container ecosystem. Wasm containers rely on the kernel's cgroup resource limits and seccomp filtering for resource isolation, but this paper shows those mechanisms are insufficient when Wasm runtimes expose WASI interfaces that allow host resource exhaustion. The attack surface analysis methodology (static runtime analysis) could be applied to evaluate any container runtime's interaction with kernel resource controls. This motivates tighter kernel-level resource enforcement for Wasm containers.",
            "methodology": "Static Wasm runtime analysis. Resource exhaustion exploitation strategies. Multi-runtime evaluation. Host resource consumption measurement."
        },
        "concepts": ["Control Groups (cgroups v2)", "Namespaces", "Seccomp-BPF"],
        "claims": [
            {"kind": "FailureMode", "id_prefix": "fail", "name": "WASM container resource isolation is breakable via WASI",
             "description": "Despite Wasm's security reputation, current runtimes do not adequately protect resource isolation. WASI/WASIX interfaces allow malicious Wasm instances to exhaust host system resources and interfere with other container instances. The attack surface is broader than previously explored."}
        ]
    },

    # ── 3. CC for Agentic AI Survey ────────────────────────────────
    {
        "ev_id": "ev-arxiv-485ad281",
        "brief": {
            "key_ideas": [
                "First survey synthesizing confidential computing for LLM-driven agentic AI — covers six TEE platforms: Intel SGX, Intel TDX, AMD SEV-SNP, ARM TrustZone, ARM CCA, and NVIDIA H100 CC",
                "Agent-centric threat model spanning perception, planning, memory, action, and coordination layers mapped to nine security goals — distinguishes agent threats from inference-time threats",
                "Identifies which CC defenses transfer from single-call inference versus requiring new agentic designs — compound attestation for multi-hop agent chains is a key open challenge",
                "Agents accumulate sensitive context, hold credentials, and operate across pipelines no single party fully controls — CC provides hardware-rooted isolation that software guards cannot"
            ],
            "relevance": "Comprehensive reference for how kernel-managed TEE platforms (Intel TDX via KVM, AMD SEV-SNP via KVM, ARM CCA) apply to the emerging agentic AI workload. The kernel is the TEE manager: it creates confidential VMs (TDX/SEV-SNP), manages attestation, and enforces isolation boundaries. The survey's agent-centric threat model identifies where kernel isolation is sufficient and where new mechanisms are needed. The six-platform comparison (SGX/TDX/SEV-SNP/TrustZone/CCA/H100) is the most complete TEE taxonomy for kernel developers.",
            "methodology": "Survey of six TEE platforms. Agent-centric threat taxonomy. Comparative analysis of CC defenses for inference vs agentic workloads. Open challenge identification."
        },
        "concepts": ["KVM (Kernel-based Virtual Machine)", "Linux Security Modules"],
        "claims": [
            {"kind": "Observation", "id_prefix": "obs", "name": "Agent CC needs differ from single-inference CC",
             "description": "Agents accumulate context, hold credentials, and operate across multi-party pipelines. CC defenses that work for single-call inference (TEE-isolated model execution) are insufficient for agentic workloads that need compound attestation, persistent secure memory, and cross-agent trust chains."}
        ]
    },

    # ── 4. TEE Agent Confinement ───────────────────────────────────
    {
        "ev_id": "ev-arxiv-3393c61a",
        "brief": {
            "key_ideas": [
                "Operation-centric risk model for self-hosted computer-use agents — security criticality depends jointly on action type, target object, execution context, and potential effect (not just action alone)",
                "Ordinary operations run on constrained REE (Rich Execution Environment) path; security-critical decisions (classification, authorization, binding, evidence) run inside TDX-backed trusted operation plane",
                "Intel TDX as primary trusted backend with remote terminal-side verification of TDX-audited commands before constrained local execution",
                "Blocks unsafe operations before execution, preserves ordinary functionality, provides auditable evidence — practical enforcement for OpenClaw-like agent frameworks"
            ],
            "relevance": "Demonstrates Intel TDX (managed by the Linux kernel's KVM) as the trust anchor for agent operation confinement. The kernel creates and manages the TDX confidential VM that runs the trusted operation plane. The REE/TEE split for agent operations maps to the kernel's existing virtualization boundary: ordinary operations in the host, sensitive operations in a TDX guest. The remote verification of TDX-audited commands before local execution requires the kernel's attestation infrastructure (CCEL, RTMR). This is a practical blueprint for using the kernel's CVM capabilities for agent security.",
            "methodology": "Operation-centric risk model. Intel TDX-backed trusted operation plane. OpenClaw integration. Evaluation of blocking unsafe operations while preserving functionality."
        },
        "concepts": ["KVM (Kernel-based Virtual Machine)", "Linux Security Modules"],
        "claims": [
            {"kind": "Proposal", "id_prefix": "prop", "name": "TDX-backed trusted operation plane for agent confinement",
             "description": "Security-critical agent operations (classification, authorization, evidence generation) run inside an Intel TDX confidential VM. Ordinary operations stay on the REE path. Remote terminal verifies TDX-audited commands before local execution. Blocks unsafe operations while preserving normal functionality."}
        ]
    },

    # ── 5. Dandelion: Microsecond-Cold-Start Serverless ────────────
    {
        "ev_id": "ev-arxiv-1daf7f8c",
        "brief": {
            "key_ideas": [
                "Key insight: redesigning the cloud application interface enables microsecond-cold-start sandboxes — pure compute functions with declarative communication eliminate the need for guest OS and networking setup",
                "Dandelion programming model expresses applications as DAGs of pure compute functions and higher-level communication functions — no POSIX, no filesystem, no networking stack in the sandbox",
                "Hundreds-of-microseconds cold start for secure untrusted function execution — orders of magnitude faster than current FaaS platforms that boot guest OSes in sandboxes",
                "Eliminates pre-provisioning of idle sandboxes in memory that current serverless platforms require to avoid slow cold starts"
            ],
            "relevance": "Challenges the assumption that serverless sandboxes need a kernel/OS inside them. Current approaches (Firecracker/KVM, gVisor, Kata) boot a guest kernel — Dandelion shows that for cloud-native pure functions, no guest OS is needed. This has implications for the kernel's KVM subsystem: if sandboxes don't need a guest kernel, the hypervisor interface can be vastly simplified. The microsecond cold start eliminates the need for snapshot/restore (CRIU) and warm pool management that currently burden the kernel. This is the purest expression of minimal-kernel-involvement serverless.",
            "methodology": "DAG-based declarative programming model. Lightweight sandbox without guest OS. Cold start latency evaluation. Comparison against pre-provisioned FaaS platforms."
        },
        "concepts": ["KVM (Kernel-based Virtual Machine)", "Namespaces"],
        "claims": [
            {"kind": "Observation", "id_prefix": "obs", "name": "Guest OS in serverless sandboxes is unnecessary for pure functions",
             "description": "Current FaaS platforms boot guest OSes in sandboxes for POSIX compatibility and networking. Cloud-native pure functions don't need this — eliminating the guest OS enables hundreds-of-microseconds cold start and removes the need for pre-provisioned idle sandboxes."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Pure-function serverless with microsecond cold start",
             "description": "Dandelion expresses applications as DAGs of pure compute functions with declarative communication. Lightweight sandboxes cold-start in hundreds of microseconds without guest OS, networking, or filesystem. Eliminates idle sandbox pre-provisioning."}
        ]
    },

    # ── 6. Roadrunner: Zero-Copy WASM Serverless Data Transfer ─────
    {
        "ev_id": "ev-arxiv-75b3a5e6",
        "brief": {
            "key_ideas": [
                "Sidecar shim enabling near-zero-copy serialization-free data transfer between WebAssembly serverless functions via memory mapping — bypasses the user/kernel boundary copying",
                "Maps function memory and moves data along a dedicated virtual data hose, eliminating multiple copies between user and kernel space",
                "44-89% inter-function communication latency improvement, 97% serialization overhead reduction, 69x throughput increase over state-of-the-art WASM serverless",
                "Addresses the fundamental inefficiency: stateless serverless functions use network for data exchange, requiring serialization and multiple kernel-user copies"
            ],
            "relevance": "Demonstrates that the kernel's user/kernel boundary (the syscall interface for network I/O) is the primary bottleneck for serverless inter-function communication. Roadrunner bypasses this via memory mapping (mmap) to create shared memory regions between WASM functions — using the kernel's virtual memory system instead of its network stack. The 69x throughput improvement quantifies the cost of the kernel's network I/O path for local inter-process communication. This motivates kernel-level shared memory primitives for co-located serverless functions.",
            "methodology": "Sidecar shim implementation with memory-mapped data hose. WASM function memory mapping. Latency, serialization overhead, and throughput evaluation."
        },
        "concepts": ["Shared Memory (shmem/tmpfs)", "Virtual Filesystem Switch"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "Kernel I/O path is 69x bottleneck for serverless data transfer",
             "description": "Serverless functions exchange data via network requiring serialization and multiple user/kernel space copies through the kernel's I/O stack. This overhead dominates inter-function communication latency."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Memory-mapped zero-copy data hose for WASM serverless",
             "description": "Roadrunner maps WASM function memory into a shared virtual data hose via mmap, bypassing serialization and kernel I/O stack. 44-89% latency reduction, 97% less serialization, 69x throughput vs state-of-the-art."}
        ]
    },

    # ── 7. Unikernel ARM Edge Evaluation ───────────────────────────
    {
        "ev_id": "ev-arxiv-ecdeda96",
        "brief": {
            "key_ideas": [
                "Evaluates three unikernel systems (OSv, Nanos, Unikraft) against Docker containers on ARM-powered edge devices — first thorough feasibility study for ARM unikernels at the edge",
                "Metrics: boot time, execution time, memory usage, CPU overhead, and network performance with real-world edge computing applications",
                "Unikernels show advantages in reduced resource consumption and faster startup while highlighting areas needing optimization for edge deployment",
                "Provides practical guidance for choosing between unikernels and containers on resource-constrained ARM devices"
            ],
            "relevance": "Evaluates alternatives to the Linux kernel for edge computing — unikernels are single-address-space, application-specific OS images that eliminate the kernel's generality overhead. The comparison against Docker (which uses Linux kernel namespaces/cgroups) quantifies what the kernel's generality costs on constrained ARM devices. The boot time and memory usage comparisons directly measure the kernel's initialization overhead vs minimal unikernel startup. This informs decisions about where the full Linux kernel is justified vs where a unikernel suffices.",
            "methodology": "Three unikernel systems vs Docker on ARM edge devices. Real-world edge applications. Boot time, execution time, memory, CPU, and network metrics."
        },
        "concepts": ["Namespaces", "Control Groups (cgroups v2)"],
        "claims": [
            {"kind": "Observation", "id_prefix": "obs", "name": "Unikernels outperform Docker on ARM edge for resource consumption",
             "description": "OSv, Nanos, and Unikraft show reduced resource consumption and faster startup than Docker containers on ARM edge devices. The Linux kernel's generality overhead (namespace/cgroup management, driver initialization) is measurable on constrained hardware."}
        ]
    },

    # ── 8. Hybrid Container+Unikernel Edge System ──────────────────
    {
        "ev_id": "ev-arxiv-d1bb6a61",
        "brief": {
            "key_ideas": [
                "Hybrid edge design: containers for complex applications (computer vision) where flexibility matters, unikernels for lightweight applications where resource efficiency matters",
                "Container orchestration manages multiple instances across edge efficiently — integrating both container and unikernel workloads under unified management",
                "Improves resource utilization and reduces latency compared to purely virtualized solutions on ARM-powered edge devices",
                "Demonstrates practical co-existence of Linux kernel-based containers and unikernels for IoT edge deployment"
            ],
            "relevance": "Proposes that the kernel should coexist with unikernels rather than being the sole OS on edge devices. Containers use the kernel's namespace/cgroup/scheduling infrastructure for complex workloads; unikernels run alongside for simple ones. The unified orchestration layer must manage both kernel-based and non-kernel workloads — relevant to how Kubernetes and containerd interact with the kernel for mixed workload management. The ARM edge focus is relevant to the kernel's ARM platform support.",
            "methodology": "Hybrid edge system design. Container + unikernel co-deployment. Computer vision and data science applications. ARM edge device evaluation."
        },
        "concepts": ["Namespaces", "Control Groups (cgroups v2)", "Scheduling Classes"],
        "claims": [
            {"kind": "Proposal", "id_prefix": "prop", "name": "Hybrid container+unikernel edge system with unified orchestration",
             "description": "Containers handle complex applications (computer vision) using Linux kernel namespaces/cgroups, while unikernels handle lightweight applications with minimal overhead. Unified orchestration manages both on ARM edge devices, improving utilization and latency vs purely virtualized approaches."}
        ]
    },
]


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")

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
        title = title_row[0] if title_row else ""; date = title_row[1] if title_row else "2026-01-01"

        brief_id = f"rb-{uuid.uuid4().hex[:12]}"
        conn.execute("INSERT INTO nodes (id, kind, attrs) VALUES (?, 'ResearchBrief', ?)",
            (brief_id, json.dumps({"title": title, "key_ideas": json.dumps(brief["key_ideas"]),
             "relevance": brief["relevance"], "methodology": brief["methodology"],
             "source_date": date or "2026-01-01", "artifact_class": "A"})))
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
                (claim_id, claim["kind"], json.dumps({"name": claim["name"], "description": claim["description"], "source_date": date or "2026-01-01"})))
            conn.execute("INSERT INTO edges (kind, source_id, target_id, attrs) VALUES ('extracted-from', ?, ?, '{}')", (claim_id, ev_id))
            stats["claims"] += 1; stats["edges"] += 1

        print(f"  OK: {title.encode('ascii', 'replace').decode()}")

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
