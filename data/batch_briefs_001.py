"""Batch 1: Semantically analyzed research briefs — 19 papers."""
import json, sqlite3, uuid

DB_PATH = "data/master.db"

BRIEFS = [
    {"ev_id": "ev-arxiv-083576df", "key_ideas": ["General-type software transactional memory without layout restrictions", "Deferred abort semantics preventing space leaks in concurrent transactions", "Novel split-increment timestamping algorithm providing opacity guarantees"], "relevance": "Directly applicable to kernel synchronization primitives. The deferred abort and opacity techniques could improve RCU and lock-free data structures in the kernel's concurrent subsystems.", "methodology": "Concurrent data structure design with formal correctness proofs", "concepts": ["Spinlock", "Read-Copy-Update"]},
    {"ev_id": "ev-arxiv-1111b1d8", "key_ideas": ["Page-cache timing side channels leak information across container and VM isolation boundaries", "Unprivileged timing measurements reveal page-cache residency in Docker, gVisor, Kata, and QEMU/KVM", "Host-backed filesystem access creates shared microarchitectural state across isolation domains"], "relevance": "Critical for Linux container and VM security. Exposes a fundamental weakness in page cache isolation that affects cgroups, namespaces, and KVM.", "methodology": "Side-channel attack characterization and exploitation across isolation boundaries", "concepts": ["Page Cache", "KVM (Kernel-based Virtual Machine)", "Control Groups (cgroups v2)", "Linux Security Modules"]},
    {"ev_id": "ev-arxiv-40ba42c1", "key_ideas": ["Empirical comparison of OCI-based model artifact delivery paths in Kubernetes", "Analysis of native image volumes vs storage initializer vs object-storage for cold start", "Admission-time verification and integrity mechanisms for large model weights"], "relevance": "Relevant to container runtime and storage stack interactions. The OCI image pulling path exercises overlayfs, namespace isolation, and block device layer in the kernel.", "methodology": "Empirical systems evaluation with controlled benchmarks", "concepts": ["Namespaces", "OverlayFS (Union Mount)"]},
    {"ev_id": "ev-arxiv-47ac8ac2", "key_ideas": ["EM side-channel emanation guides black-box firmware fuzzing without instrumentation", "Signal processing and dynamic time-warping alignment detect execution divergence", "Enables coverage-guided fuzzing on embedded systems where source access is infeasible"], "relevance": "Relevant to embedded Linux firmware security testing. The technique could detect vulnerabilities in kernel device drivers running on embedded SoCs.", "methodology": "Hardware side-channel analysis combined with fuzz testing", "concepts": ["Linux Security Modules"]},
    {"ev_id": "ev-arxiv-96a9327b", "key_ideas": ["Component-level DVFS for neural processing units with cross-domain communication", "Compiler-driven optimization for instruction scheduling and voltage/frequency selection", "Achieves 25-35% energy reduction under service-level objective constraints"], "relevance": "Extends the cpufreq governor framework concepts to NPU accelerators. The cross-domain DVFS coordination between CPU and NPU requires kernel-level power management.", "methodology": "Hardware-software co-design with compiler optimization", "concepts": ["CPU Frequency Scaling (cpufreq)", "Thermal Management Framework"]},
    {"ev_id": "ev-arxiv-9b55d4e1", "key_ideas": ["Idle network service cores compete for shared power and thermal budgets on modern processors", "Power-centric resource model where efficient waiting outperforms aggressive core reclamation", "Challenges the assumption that idle cores waste compute resources"], "relevance": "Directly relevant to NAPI polling, CPU idle states, and the cpufreq governor framework. Proposes rethinking how the kernel manages idle network-processing cores.", "methodology": "Power and thermal budget analysis of multicore network stacks", "concepts": ["NAPI (New API) Polling", "CPU Idle Framework", "CPU Frequency Scaling (cpufreq)"]},
    {"ev_id": "ev-arxiv-b5c3c7bd", "key_ideas": ["Compiler operator fusion creates power bursts triggering voltage droop on mobile NPUs", "Measurement-guided graph rewriting mitigates fusion-induced power spikes", "Reduced peak current improves low-voltage operating margins as battery depletes"], "relevance": "Relevant to thermal management and power governor frameworks in the kernel. The voltage droop mitigation technique applies to kernel-managed accelerators with aggressive power states.", "methodology": "Measurement-guided compiler optimization for power management", "concepts": ["CPU Frequency Scaling (cpufreq)", "Thermal Management Framework"]},
    {"ev_id": "ev-arxiv-b6636748", "key_ideas": ["Lightweight kernel mechanism providing scheduler fast-track for priority-inverted threads", "Immediate CPU access granted to threads blocking latency-critical threads", "72% reduction in blocking duration on Android devices"], "relevance": "Directly modifies the Linux CPU scheduler to address priority inversion. The fast-track mechanism interacts with CFS scheduling classes and preemption control.", "methodology": "Kernel scheduler modification with real-device evaluation", "concepts": ["Scheduling Classes", "Virtual Runtime Scheduling"]},
    {"ev_id": "ev-arxiv-b9fc6b7e", "key_ideas": ["OS-level resilience analysis against agent memory and configuration corruption via syscalls", "Layered defense evaluation: access-control prevention, workload-conditioned detection, recovery", "43 concrete attack operations targeting self-hosted AI agent state"], "relevance": "Tests the limits of Linux security mechanisms (LSM, capabilities, seccomp) against a new threat model where AI agents run as OS processes with persistent mutable state.", "methodology": "Systematic security evaluation of OS defense mechanisms", "concepts": ["Linux Security Modules", "POSIX Capabilities", "Seccomp-BPF"]},
    {"ev_id": "ev-arxiv-d2e1efda", "key_ideas": ["Joint optimization of LLM decoding and task scheduling for synchronous agentic RL", "Speculative decoding via suffix pattern reuse under low load", "Cache-aware scheduling reducing KV-cache recomputation under high load"], "relevance": "The scheduling and cache management techniques are relevant to kernel-level CPU scheduling for latency-sensitive ML workloads and memory management for large working sets.", "methodology": "Systems optimization combining speculative execution with cache-aware scheduling", "concepts": ["Scheduling Classes"]},
    {"ev_id": "ev-arxiv-e0137265", "key_ideas": ["Predicts kernel-level interference between colocated DNN workloads on GPUs", "Occupancy-based analytical modeling for GPU resource contention", "Greedy placement algorithms reduce SLO violations by up to 3x"], "relevance": "The interference modeling relies on kernel-level resource accounting through cgroups and GPU device driver interactions. Relevant to container colocation and resource isolation.", "methodology": "Analytical modeling with occupancy-based interference prediction", "concepts": ["Control Groups (cgroups v2)", "Scheduling Classes"]},
    {"ev_id": "ev-arxiv-e7278fd5", "key_ideas": ["RISC-V processor with CPU-level instruction decryption and authentication using ASCON-128a", "Seven micro-architecture variants balancing area, performance, and energy overhead", "Maintains standard RISC-V toolchain compatibility with minimal changes"], "relevance": "Relevant to confidential computing support in the kernel, similar to AMD SEV and Intel TDX. The instruction-level encryption requires kernel boot and memory management changes.", "methodology": "Hardware security architecture design with FPGA prototyping", "concepts": ["Linux Security Modules"]},
    {"ev_id": "ev-arxiv-fc9f94e0", "key_ideas": ["I/O Resource Manager for shared-nothing storage clusters", "Hardware-aware cost modeling with quantum-based rate limiting", "Distributed adaptive feedback control enforcing global I/O limits across heterogeneous hardware"], "relevance": "Relevant to block I/O scheduling and device mapper layers. The I/O governance techniques extend kernel-level I/O scheduling to disaggregated storage.", "methodology": "Distributed storage system design with hardware-aware scheduling", "concepts": ["Block Device Layer", "NVMe Driver Subsystem"]},
    {"ev_id": "ev-arxiv-lock-free-multi-word-compare-and-swap", "key_ideas": ["Efficient lock-free multi-word compare-and-swap via contention-aware helping", "Eliminates scalability limitations of lock-based synchronization", "Addresses deadlock and liveness issues in concurrent shared-memory data structures"], "relevance": "Directly applicable to kernel lock-free data structures. The multi-word CAS technique could improve RCU, per-CPU data structures, and lock-free queues.", "methodology": "Lock-free concurrent algorithm design with formal correctness analysis", "concepts": ["Spinlock", "Read-Copy-Update", "Futex (Fast Userspace Mutex)"]},
    {"ev_id": "ev-arxiv-seekable-oci-lazy-loading-container-imag", "key_ideas": ["SOCI enables lazy-loading container images via range-request indexing", "Containers start before entire image is downloaded", "Reduces pod startup time by eliminating full-image pull requirement"], "relevance": "Exercises the kernel's overlayfs, FUSE, and namespace subsystems. Lazy-loading requires kernel page fault handling for on-demand content fetching.", "methodology": "Container runtime optimization with lazy content delivery", "concepts": ["OverlayFS (Union Mount)", "FUSE (Filesystem in Userspace)", "Namespaces", "Page Fault Handler"]},
    {"ev_id": "ev-arxiv-bounded-memory-parallel-container-image-", "key_ideas": ["Bounded-memory parallel downloading for large container images", "Prevents OOM during concurrent image layer decompression", "Optimizes cold image pull for GPU/AI workloads with multi-gigabyte images"], "relevance": "The bounded-memory constraint interacts with kernel memory management — cgroups memory limits, OOM killer, and page reclaim under memory pressure during container operations.", "methodology": "Memory-bounded systems design for container runtimes", "concepts": ["Control Groups (cgroups v2)", "OOM Killer", "Page Reclaim (kswapd/direct)"]},
    {"ev_id": "ev-arxiv-complets-arm-poe2-intra-process-isolatio", "key_ideas": ["Universal compartmentalization model for ARM Permission Overlay Extension 2", "Intra-process isolation via memory protection keys without privilege separation", "POE-based protection domains applicable to userspace without kernel mode transitions"], "relevance": "Directly extends kernel memory protection. ARM POE2 is the ARM equivalent of Intel MPK — the kernel must manage protection key registers and handle POE faults.", "methodology": "Hardware-assisted intra-process isolation architecture", "concepts": ["Linux Security Modules", "POSIX Capabilities", "Hierarchical Page Tables"]},
    {"ev_id": "ev-arxiv-elastic-gang-scheduling-for-llm-inferenc", "key_ideas": ["Per-token membership change for hard-barriered LLM inference gang scheduling", "Elastic gang mechanism prevents deadlock when OS preempts gang members", "On-device LLM decoding requires all cores for milliseconds per token"], "relevance": "Directly modifies the Linux CPU scheduler. The elastic gang mechanism requires new scheduling class support for hard-barriered CPU-SIMD gangs coexisting with normal OS scheduling.", "methodology": "Kernel scheduler extension for gang scheduling with elastic membership", "concepts": ["Scheduling Classes", "Virtual Runtime Scheduling", "Scheduler Load Balancing"]},
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
