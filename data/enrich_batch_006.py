"""Deep enrichment batch 006: 9 papers — deep kernel work found via title search.

Papers:
1. TOMOYO Linux — Execution-state-based MAC for Linux
2. L7FP — eBPF-based L7 policy offload to kernel for service meshes
3. DFUSE — Strongly consistent write-back kernel caching for FUSE
4. PatchAdvisor — Linux kernel patch evolution study with automated repair
5. Joyride — Rethinking Linux network stack with microkernel-style architecture
6. SchedCP — LLM agent framework for Linux scheduler optimization via sched_ext
7. Kubernetes Cross-Namespace — Cross-namespace reference vulnerabilities (7 CVEs)
8. Linux Radiation — Kernel failure characterization under proton radiation
9. Safe Kernel-Bypass Sharing — Protected libraries for sharing kernel-bypass I/O
"""
import json, sqlite3, uuid

DB_PATH = "data/master.db"

ALL_PAPERS = [
    # ── 1. TOMOYO Linux ─────────────────────────────────────────────
    {
        "ev_id": "ev-arxiv-tomoyo-linux-execution-state-mac",
        "brief": {
            "key_ideas": [
                "Proposes mandatory access control based on application execution history and intent — grants or denies access based on how the process reached its current state (execution path), not just the subject-object pair",
                "Introduces execution-state tracking where the kernel records the chain of program invocations leading to the current process — enabling policies like 'Apache may read config files only when launched by systemd, not by a shell'",
                "Implemented as a Linux Security Module (TOMOYO Linux) — one of the four LSMs in mainline Linux alongside SELinux, AppArmor, and Smack",
                "System administrators can reduce risks from malicious access attempts and wrong operations by specifying policies in terms of execution history rather than static subject-object labels"
            ],
            "relevance": "TOMOYO Linux is one of the four mainline Linux Security Modules. This paper describes its foundational design — execution-state-based MAC is a fundamentally different security model from SELinux (type enforcement) and AppArmor (path-based). The execution history tracking requires kernel-level process ancestry recording beyond what standard credentials provide. This is directly implemented in the Linux kernel's LSM framework and affects how the kernel makes access control decisions for file operations, network access, and IPC.",
            "methodology": "MAC design with execution-state tracking. Linux kernel LSM implementation. Evaluation of access control granularity and administrator usability."
        },
        "concepts": ["Linux Security Modules", "Process Creation (fork/clone)"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "Traditional MAC ignores application execution intent",
             "description": "Existing access control methods grant access based on subject-object combinations without considering why the application is making the request or how it reached its current execution state. This allows compromised processes to access resources their execution context shouldn't permit."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Execution-state-based mandatory access control",
             "description": "TOMOYO Linux tracks the chain of program invocations leading to the current process and uses this execution history to make access control decisions. Policies specify allowed operations based on execution path, not just static labels."}
        ]
    },

    # ── 2. L7FP: eBPF L7 Policy Offload for Service Meshes ─────────
    {
        "ev_id": "ev-arxiv-l7-offload",
        "brief": {
            "key_ideas": [
                "Automatically synthesizes an eBPF-based data plane from high-level service mesh policies to enforce L7 (HTTP/2, TLS) policies directly in kernel space — eliminating sidecar proxy overhead",
                "Given high-level policies, L7FP generates eBPF programs that enforce them in the kernel, transparently falling back to existing service proxies for unsupported policies",
                "Supports both TLS termination and HTTP/2 parsing in eBPF — demonstrating that complex application-layer protocol handling is feasible in-kernel",
                "Reduces median request latency by up to 6x and sustains 3x more throughput compared to state-of-the-art service meshes (Istio, Linkerd) without any application code modification"
            ],
            "relevance": "Pushes eBPF further than XLB (batch 004) by automatically synthesizing eBPF programs from declarative policies and handling TLS + HTTP/2 in-kernel. The automatic policy-to-eBPF compilation is a new paradigm: operators write high-level policies, the system generates verified eBPF code. This has implications for the kernel's eBPF verifier (can it handle synthesized programs?) and kTLS (L7FP must interoperate with kernel TLS for encrypted traffic). The 6x latency improvement over Istio quantifies the cost of the sidecar model that L7FP eliminates.",
            "methodology": "ETH Zürich/Nvidia/NYU. Automatic eBPF synthesis from high-level policies. TLS and HTTP/2 support. Evaluation against Istio and Linkerd on realistic microservice applications."
        },
        "concepts": ["eBPF (Extended Berkeley Packet Filter)", "Kernel Crypto API", "Socket Buffer (sk_buff)"],
        "claims": [
            {"kind": "Proposal", "id_prefix": "prop", "name": "Automatic eBPF synthesis for L7 service mesh policies",
             "description": "L7FP automatically synthesizes eBPF-based data planes from high-level service mesh policies, enforcing L7 policies (HTTP/2, TLS) directly in kernel space. Transparently falls back to sidecar proxies for unsupported policies."},
            {"kind": "PerformanceProfile", "id_prefix": "perf", "name": "L7FP 6x latency reduction vs service meshes",
             "description": "Reduces median request latency by up to 6x and sustains 3x more throughput versus state-of-the-art service meshes (Istio, Linkerd) with full TLS and HTTP/2 support and no application modification."}
        ]
    },

    # ── 3. DFUSE: Consistent Write-Back Caching for FUSE ───────────
    {
        "ev_id": "ev-socc25-dfuse",
        "brief": {
            "key_ideas": [
                "First distributed FUSE filesystem that delivers write-back kernel caching AND strong consistency simultaneously — breaking the tradeoff where FUSE disables write-back cache when consistency is required",
                "Offloads userspace consistency control to the kernel FUSE driver, allowing coordinated access to the kernel's page cache across distributed nodes",
                "Eliminates blind local cache updates by having the kernel driver coordinate cache coherence — ensures cluster-wide strong consistency without bypassing the page cache",
                "68% higher throughput and 40.4% lower latency than existing write-through FUSE distributed filesystems"
            ],
            "relevance": "Directly modifies the Linux kernel's FUSE driver to support distributed consistency-aware page cache management. FUSE filesystems (used by cloud storage: JuiceFS, Alluxio, CubeFS) are forced into write-through mode for consistency, sacrificing the kernel's write-back page cache performance. DFUSE changes the kernel FUSE interface to support coordinated cache access across nodes — a fundamental extension of how the kernel's page cache interacts with userspace filesystems. Published at SoCC 2025 by Columbia/Alibaba.",
            "methodology": "Linux kernel FUSE driver modification. Distributed consistency protocol for page cache coordination. SoCC 2025 publication. Evaluation against write-through FUSE baseline."
        },
        "concepts": ["FUSE (Filesystem in Userspace)", "Page Cache", "Virtual Filesystem Switch"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "FUSE disables write-back cache for strong consistency",
             "description": "The Linux FUSE interface disables the kernel's write-back page cache whenever strong consistency is required for distributed filesystems. Operators must choose write-back+weak-consistency or write-through+strong-consistency, keeping FUSE out of write-intensive cloud workloads."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Kernel-side consistency control for FUSE write-back caching",
             "description": "DFUSE offloads consistency control to the FUSE kernel driver, enabling coordinated access to the kernel's page cache across distributed nodes. Delivers write-back caching with strong consistency simultaneously."},
            {"kind": "PerformanceProfile", "id_prefix": "perf", "name": "DFUSE 68% throughput improvement over write-through FUSE",
             "description": "68% higher throughput and 40.4% lower latency than write-through FUSE distributed filesystems while maintaining strong consistency guarantees."}
        ]
    },

    # ── 4. PatchAdvisor: Linux Kernel Patch Evolution ───────────────
    {
        "ev_id": "ev-arxiv-patch-evolution",
        "brief": {
            "key_ideas": [
                "Large-scale study of Linux kernel patch evolution: reconstructs 6,946 syzbot-linked bug-fix lifecycles connecting crash reports, reproducers, mailing-list discussions, revision histories, and merged fixes",
                "Confirms accepted kernel repairs are frequently non-local and governed by reviewer-enforced constraints (concurrency handling, API compliance, subsystem conventions) not present in bug reports",
                "PatchAdvisor: repair framework integrating retrieval-based memory with a fine-tuned diagnostic advisor to guide a coding agent toward reviewer-aligned patches",
                "Demonstrates that leveraging patch-evolution history (reviewer feedback, revision patterns) yields measurable gains in repair quality over unguided and retrieval-only baselines"
            ],
            "relevance": "Provides the first large-scale empirical evidence on how Linux kernel patches actually evolve from crash report to merged fix. The finding that accepted patches are shaped by reviewer constraints invisible in bug reports is critical — it means automated kernel repair must model the kernel development process, not just the code. The 6,946 syzbot lifecycle reconstructions are a unique dataset for kernel development research. PatchAdvisor shows how LLMs can be guided by kernel development conventions to produce reviewer-aligned patches.",
            "methodology": "Large-scale study of 6,946 syzbot-linked patch lifecycles. Mining of crash reports, reproducers, mailing-list discussions, and revision histories. Retrieval-augmented repair framework with fine-tuned advisor. Temporal holdout evaluation."
        },
        "concepts": [],
        "claims": [
            {"kind": "Observation", "id_prefix": "obs", "name": "Kernel patches are shaped by invisible reviewer constraints",
             "description": "Accepted Linux kernel repairs are frequently non-local and governed by reviewer-enforced constraints (concurrency handling, API compliance, subsystem conventions) that are not present in bug reports or crash logs. Automated repair must model the review process, not just the code."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Patch-evolution-guided automated kernel repair",
             "description": "PatchAdvisor integrates retrieval-based memory of historical patch evolutions with a fine-tuned diagnostic advisor. Guides a coding agent toward reviewer-aligned patches using patterns from 6,946 syzbot-linked bug-fix lifecycles."}
        ]
    },

    # ── 5. Joyride: Rethinking Linux Network Stack ──────────────────
    {
        "ev_id": "ev-arxiv-joyride",
        "brief": {
            "key_ideas": [
                "Proposes replacing Linux's legacy TCP/IP network stack with a microkernel-style architecture that integrates kernel bypass (DPDK) and a user-space TCP/IP stack while maintaining application compatibility",
                "Identifies fundamental limitations of the legacy Linux network stack for 100+ Gbps NICs: kernel space processing, mode switching, and data copying overhead cannot be eliminated incrementally",
                "Aims to provide compatibility with existing applications (no code changes) while delivering kernel bypass performance — unlike DPDK/RDMA which require application redesign",
                "Designs a hybrid where the microkernel-style networking runs in userspace for the fast path but retains kernel integration for management, security, and legacy compatibility"
            ],
            "relevance": "A bold proposal to fundamentally restructure the Linux kernel's networking subsystem. While eBPF/XDP/io_uring improve the existing stack incrementally, Joyride argues for architectural replacement. This is the most radical networking proposal in the corpus — it challenges the assumption that the kernel's sk_buff-based networking can be optimized enough for 100+ Gbps. The microkernel-style design (userspace fast path + kernel management) is a middle ground between full kernel bypass (DPDK) and full kernel networking. Published at KISV 2025 (Kernel Isolation, Safety and Verification workshop).",
            "methodology": "Architectural proposal with prototype framework. Performance analysis of Linux legacy stack limitations at 100+ Gbps. KISV 2025 workshop paper."
        },
        "concepts": ["TCP Congestion Control", "Socket Buffer (sk_buff)", "NAPI (New API) Polling"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "Linux network stack cannot saturate 100+ Gbps NICs",
             "description": "Linux's conventional TCP/IP stack becomes increasingly problematic for high-end NICs at 100 Gbps and beyond. Kernel space processing, mode switching, and data copying overhead cannot be eliminated incrementally within the legacy architecture."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Microkernel-style Linux networking with DPDK integration",
             "description": "Joyride replaces Linux's legacy network stack with a microkernel-style architecture integrating DPDK and a user-space TCP/IP stack. Maintains application compatibility while providing kernel bypass performance for the fast path."}
        ]
    },

    # ── 6. SchedCP: LLM Agents for Linux Schedulers ─────────────────
    {
        "ev_id": "ev-arxiv-agentic-sched",
        "brief": {
            "key_ideas": [
                "First framework enabling fully autonomous LLM agents to safely optimize Linux schedulers without human involvement — addresses the semantic gap where kernel scheduling policies cannot understand application-specific needs",
                "Core architecture: decoupled control plane separating AI semantic reasoning ('what to optimize') from system execution ('how to observe and act') via Model Context Protocol (MCP) server",
                "Three key services: Workload Analysis Engine, evolving Scheduler Policy Repository, and Execution Verifier that validates all AI-generated code with static and dynamic analysis before deployment",
                "sched-agent: multi-agent system that autonomously analyzes workloads, synthesizes custom eBPF scheduling policies, and deploys via sched_ext. 1.79x performance improvement, 13x cost reduction vs naive agentic approaches"
            ],
            "relevance": "Closes the loop between LLM intelligence and the kernel's sched_ext infrastructure. Where UFS (batch 004) showed a hand-crafted sched_ext scheduler, SchedCP automates the entire pipeline: workload analysis → policy synthesis → eBPF code generation → safety verification → sched_ext deployment. The Execution Verifier (static + dynamic analysis before deployment) addresses the critical safety concern of deploying LLM-generated code in the kernel. The MCP server interface is a novel kernel-AI integration pattern.",
            "methodology": "MCP server architecture with multi-agent system. eBPF policy synthesis for sched_ext. Static and dynamic analysis verification. Evaluation against naive agentic approaches on diverse workloads."
        },
        "concepts": ["sched_ext Extensible Scheduling", "eBPF (Extended Berkeley Packet Filter)", "Scheduling Classes"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "Kernel schedulers cannot understand application semantics",
             "description": "Linux's EEVDF scheduler applies one-size-fits-all policies to diverse workloads. sched_ext enables custom eBPF schedulers but developing them requires deep kernel expertise. The semantic gap between application needs and kernel policies remains."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "LLM agent framework for autonomous Linux scheduler optimization",
             "description": "SchedCP provides a decoupled control plane (MCP server) with Workload Analysis Engine, Scheduler Policy Repository, and Execution Verifier. sched-agent autonomously synthesizes eBPF scheduling policies and deploys via sched_ext with safety verification."},
            {"kind": "PerformanceProfile", "id_prefix": "perf", "name": "SchedCP 1.79x improvement with 13x cost reduction",
             "description": "1.79x performance improvement and 13x cost reduction compared to naive agentic approaches. All AI-generated code validated by static and dynamic analysis before kernel deployment."}
        ]
    },

    # ── 7. Kubernetes Cross-Namespace Vulnerabilities ────────────────
    {
        "ev_id": "ev-arxiv-f63bae55",
        "brief": {
            "key_ideas": [
                "First systematic investigation of Kubernetes Operator cross-namespace attacks — Operators demand elevated privileges and may interact across namespaces, creating a mismatch between declared and implemented scope",
                "Two attack strategies demonstrated: adversary with access to a single namespace exploits the Operator to affect unauthorized namespaces, causing privilege escalation",
                "Large-scale measurement: over 14% of Operators in the wild are potentially vulnerable to cross-namespace reference attacks",
                "8 confirmations and 7 CVEs assigned affecting vendors including Red Hat and NVIDIA — highlights critical need for enhanced Kubernetes Operator security practices"
            ],
            "relevance": "Directly relevant to the kernel's namespace isolation mechanism. Kubernetes namespaces are implemented using Linux kernel namespaces (pid, net, mnt, user, etc.). The cross-namespace vulnerability occurs when Kubernetes Operators bypass the isolation boundary that the kernel provides — the kernel correctly isolates processes in different namespaces, but the Operator's elevated privileges allow it to bridge that isolation. This demonstrates that kernel-level namespace isolation is necessary but not sufficient — application-level components can break the isolation contract.",
            "methodology": "Systematic vulnerability analysis of Kubernetes Operators. Two cross-namespace attack strategies. Large-scale measurement of Operators in the wild. Responsible disclosure with 8 confirmations and 7 CVEs."
        },
        "concepts": ["Namespaces", "Control Groups (cgroups v2)"],
        "claims": [
            {"kind": "FailureMode", "id_prefix": "fail", "name": "14% of Kubernetes Operators vulnerable to cross-namespace attacks",
             "description": "Kubernetes Operators demand elevated privileges and may interact across namespaces. Over 14% of Operators in the wild have cross-namespace reference vulnerabilities where an attacker in one namespace can affect unauthorized namespaces. 7 CVEs assigned affecting Red Hat and NVIDIA."},
            {"kind": "Observation", "id_prefix": "obs", "name": "Kernel namespace isolation necessary but not sufficient",
             "description": "The Linux kernel correctly isolates processes in different namespaces, but Kubernetes Operators with elevated privileges can bridge that isolation. The root cause is mismatch between declared scope of resources and implemented scope of Operator logic — an application-level problem the kernel cannot prevent."}
        ]
    },

    # ── 8. Linux Under Radiation ────────────────────────────────────
    {
        "ev_id": "ev-arxiv-5cfba71f",
        "brief": {
            "key_ideas": [
                "First cross-architecture characterization of Linux kernel failure modes under proton radiation — traces all 133 observed failures to their originating kernel handlers across three platforms (40nm ARM, 14nm FinFET ARM, 40nm RISC-V FPGA)",
                "Failure profiles differ sharply across architectures: on 40nm platforms memory management and driver handlers account for 67-78% of events; on 14nm SoC ~90% funnel through a single eMMC storage path",
                "Reconstructed propagation chains show faults can cascade through up to six kernel subsystems before terminal failure — demonstrating how a single hardware upset can cause system-wide kernel failure",
                "Results identify kernel subsystem boundaries where radiation-induced faults originate, enabling targeted mitigations instead of blanket redundancy"
            ],
            "relevance": "Unique study of how the Linux kernel fails under radiation — directly relevant to kernel reliability for space, aviation, and high-altitude computing. The finding that a single SEFI-susceptible peripheral (eMMC) can dictate 90% of system failures on 14nm shows that kernel driver reliability is the weakest link. The 6-subsystem cascade chains (e.g., hardware fault → driver → memory management → filesystem → kernel panic) reveal how tightly coupled kernel subsystems are in failure modes. This has implications for kernel fault isolation and error containment.",
            "methodology": "Proton irradiation (20-58 MeV) of three Linux platforms. Kernel log forensics tracing 133 failures to originating handlers. Cross-architecture comparison. Failure propagation chain reconstruction."
        },
        "concepts": ["Interrupt Handling"],
        "claims": [
            {"kind": "Observation", "id_prefix": "obs", "name": "Radiation failures cascade through up to 6 kernel subsystems",
             "description": "Under proton radiation, hardware single-event functional interrupts propagate through up to six Linux kernel subsystems before terminal failure. On 40nm platforms, memory management and drivers account for 67-78% of failures. On 14nm, 90% funnel through a single eMMC storage path."},
            {"kind": "Observation", "id_prefix": "obs", "name": "A single SEFI-susceptible peripheral dictates system reliability",
             "description": "On the 14nm SoC, approximately 90% of Linux failures (56% filesystem + 34% driver) originate from a single eMMC storage path. A SEFI-susceptible peripheral can strongly dictate overall system reliability regardless of CPU hardness."}
        ]
    },

    # ── 9. Safe Kernel-Bypass Sharing ───────────────────────────────
    {
        "ev_id": "ev-arxiv-90ef2fc7",
        "brief": {
            "key_ideas": [
                "Identifies and solves previously unaddressed obstacles to sharing kernel-bypass services among mutually distrusting applications — protected user-level libraries provide a new OS service structure",
                "Protected library functions must complete in bounded time to preserve kernel's process reclaim capability — shows how to move unbounded waits outside the library for synchronous inter-process interaction without polling",
                "Discovers and prevents a buffer unmapping attack where applications remove pages shared with the protected library — prevents this by disallowing page removal for shared regions",
                "First successful sharing of a kernel-bypass NIC among mutually untrusting applications: 50% lower latency and up to 7x throughput vs commercial FastDDS implementation"
            ],
            "relevance": "Proposes a new OS service architecture that combines kernel bypass performance with microkernel-style safety — directly relevant to how the kernel manages fast I/O devices. The bounded-time requirement for protected libraries maps to the kernel's preemption model. The buffer unmapping attack is a novel kernel security vulnerability: if userspace can unmap pages that a protected library depends on, it can crash or corrupt the service. This has implications for VFIO, DPDK, and any kernel-bypass mechanism where userspace shares memory with a privileged component.",
            "methodology": "Protected library model extension. Bounded-time execution requirement. Buffer unmapping attack discovery and mitigation. DDS communication service prototype with kernel-bypass NIC sharing."
        },
        "concepts": ["VFIO (Virtual Function I/O)"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "Kernel-bypass I/O cannot be safely shared among untrusting apps",
             "description": "Kernel-bypass NIC services require mutual trust between applications sharing the device. Protected user-level libraries could provide safe sharing, but face obstacles: unbounded function execution prevents process reclaim, and a buffer unmapping attack allows applications to corrupt shared state."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Bounded-time protected libraries for safe kernel-bypass sharing",
             "description": "Protected libraries complete in bounded time (preserving kernel process reclaim), move unbounded waits outside the library, and prevent buffer unmapping attacks by disallowing page removal for shared regions. First safe sharing of kernel-bypass NIC among untrusting applications."},
            {"kind": "PerformanceProfile", "id_prefix": "perf", "name": "Protected library NIC sharing 7x throughput vs FastDDS",
             "description": "50% lower latency and up to 7x throughput versus commercial FastDDS implementation, with lower CPU utilization. First kernel-bypass NIC sharing among mutually untrusting applications."}
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
