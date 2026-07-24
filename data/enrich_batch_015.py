"""Deep enrichment batch 015: 12 conference papers with newly-fetched OpenAlex abstracts.

Papers from ASPLOS, EuroSys, SOSP, NSDI, HPCA, FAST, HotOS — all top-tier conferences.
"""
import json, sqlite3, uuid

DB_PATH = "data/master.db"

ALL_PAPERS = [
    # ── 1. CXLfork: Remote Fork over CXL ───────────────────────────
    {"ev_id": "ev-conf-8483b837", "brief": {
        "key_ideas": ["Realizes near-zero-serialization, zero-copy process cloning across nodes over CXL fabrics using globally-shared CXL memory", "Remote fork using CXL-attached shared memory for cluster-wide process cloning — rethinks traditional fork() for disaggregated memory", "Utilizes CXL shared memory to share page tables and process state across nodes without serialization", "Explores implications of CXL shared memory for fundamental OS interfaces beyond simple memory expansion"],
        "relevance": "Directly extends the Linux kernel's fork() syscall for CXL disaggregated memory. fork() currently operates within a single machine — CXLfork makes it work across nodes via CXL shared memory. This requires kernel changes to page table management (sharing guest page tables via CXL), process state serialization, and the fork/clone infrastructure. Published at ASPLOS 2025.",
        "methodology": "ASPLOS 2025. CXL-based remote fork implementation. Zero-copy process cloning. Evaluation of cluster-wide fork latency."
    }, "concepts": ["Process Creation (fork/clone)", "Adaptive CXL Memory Tiering", "Hierarchical Page Tables"], "claims": [
        {"kind": "Proposal", "id_prefix": "prop", "name": "Zero-copy remote fork via CXL shared memory", "description": "CXLfork enables near-zero-serialization, zero-copy process cloning across nodes using CXL-attached globally-shared memory. Rethinks fork() for disaggregated memory architectures."}
    ]},

    # ── 2. Direct Memory Translation for Virtualized Clouds ────────
    {"ev_id": "ev-conf-5aa68600", "brief": {
        "key_ideas": ["Hardware-software extension for x86 that minimizes nested virtual memory translation overhead while maintaining backward compatibility", "Nested translation on x86 needs up to 24 sequential PTE fetches — DMT reduces this by managing last-level PTEs in contiguous physical memory", "OS manages contiguous PTE regions, allowing hardware to skip intermediate page walk levels for the common case", "Maintains backward compatibility with x86 — no changes to guest OS or applications needed"],
        "relevance": "Directly addresses the kernel's nested page table walk performance for KVM. The 24-PTE worst case is the fundamental bottleneck for virtualized memory-intensive workloads. DMT requires kernel changes to how it manages page tables (contiguous PTE layout) and hypervisor changes to how KVM handles nested translation. This is relevant to the kernel's x86 page table code, KVM's nested paging, and the EPT/NPT implementation.",
        "methodology": "ASPLOS. Hardware-software x86 extension. Contiguous last-level PTE management. Evaluation of nested translation overhead reduction."
    }, "concepts": ["KVM (Kernel-based Virtual Machine)", "Hierarchical Page Tables", "Translation Lookaside Buffer"], "claims": [
        {"kind": "Problem", "id_prefix": "prob", "name": "Nested x86 translation requires up to 24 sequential PTE fetches", "description": "On x86 with virtualization, a single address translation in a guest VM can require up to 24 sequential page table entry fetches through nested page tables, making virtual memory translation a key performance bottleneck."},
        {"kind": "Proposal", "id_prefix": "prop", "name": "Contiguous PTE layout for fast nested translation", "description": "DMT manages last-level PTEs in contiguous physical memory, allowing hardware to skip intermediate walk levels. Backward compatible with x86, requires OS page table management changes."}
    ]},

    # ── 3. HyperHammer: Breaking KVM Isolation ─────────────────────
    {"ev_id": "ev-conf-8a7015ab", "brief": {
        "key_ideas": ["Demonstrates RowHammer can break KVM-enforced VM isolation — hardware vulnerability threatens the fundamental security promise of hardware-assisted virtualization", "Due to extensive sharing between VMs (physical memory, cache hierarchy), hardware vulnerabilities can cross isolation boundaries that software cannot prevent", "Targets AMD SEV and earlier virtualization where VMs share physical DRAM rows", "Undermines the cloud security model where guest VM isolation is the primary trust boundary"],
        "relevance": "Directly attacks the Linux kernel's KVM hypervisor isolation. RowHammer bitflips in shared DRAM rows can corrupt another VM's memory, breaking the isolation that KVM is supposed to enforce. This is relevant to how the kernel allocates physical pages to VMs — if two VMs share adjacent DRAM rows, RowHammer can cross the boundary. Motivates kernel-level RowHammer-aware page allocation.",
        "methodology": "ASPLOS. RowHammer attack against KVM isolation. AMD SEV evaluation. Cross-VM memory corruption demonstration."
    }, "concepts": ["KVM (Kernel-based Virtual Machine)"], "claims": [
        {"kind": "FailureMode", "id_prefix": "fail", "name": "RowHammer breaks KVM VM isolation via shared DRAM rows", "description": "RowHammer bitflips in physically adjacent DRAM rows can corrupt memory belonging to another VM, breaking the isolation guarantee that KVM-based hardware-assisted virtualization provides. Physical memory sharing between VMs enables cross-boundary attacks."}
    ]},

    # ── 4. xUI: Extended User Interrupts ───────────────────────────
    {"ev_id": "ev-conf-c11cd370", "brief": {
        "key_ideas": ["Deconstructs Intel UIPI user interrupt design and develops accurate timing model", "Four novel enhancements: tracked interrupts, hardware safepoints, kernel bypass timer, and interrupt forwarding", "Enables fast notification without polling — alternative to busy-waiting for low-latency communication", "Modeled in gem5 simulation and evaluated for performance"],
        "relevance": "Extends the kernel's interrupt delivery model with user-space interrupt enhancements. Intel UIPI allows user-to-user interrupt delivery without kernel involvement — xUI adds tracking, safepoints, and kernel bypass timers. This is relevant to the kernel's interrupt handling, signal delivery, and the ongoing work on user interrupts for preemptive userspace scheduling. The kernel bypass timer is particularly significant — it allows userspace to get timer events without syscall overhead.",
        "methodology": "ASPLOS. Intel UIPI analysis. gem5 simulation of four extensions. Performance evaluation."
    }, "concepts": ["Interrupt Handling", "Scheduling Classes"], "claims": [
        {"kind": "Proposal", "id_prefix": "prop", "name": "Extended user interrupts with tracking, safepoints, and bypass timer", "description": "xUI adds tracked interrupts, hardware safepoints, kernel bypass timer, and interrupt forwarding to Intel's UIPI user interrupt model. Enables fast user-space notification without polling or kernel involvement."}
    ]},

    # ── 5. Merlin: eBPF Multi-tier Optimization ────────────────────
    {"ev_id": "ev-conf-1168a840", "brief": {
        "key_ideas": ["Multi-tier optimization framework for eBPF programs targeting both performance and compactness under the kernel's instruction limit", "eBPF's customized ISA with kernel safety requirements (limited instruction count) necessitates optimization that standard compilers don't provide", "Addresses the gap between LLVM's general-purpose optimization and eBPF's unique constraints (verifier-safe, bounded instructions)", "Achieves significant performance improvements within eBPF's strict safety and size constraints"],
        "relevance": "Directly improves the eBPF compilation pipeline. The kernel's eBPF verifier imposes an instruction limit (1M instructions) and safety constraints that LLVM's standard optimization passes don't account for. Merlin fills this gap with eBPF-specific optimizations. This complements Kops (batch 001, JIT-level optimization) by working at the compiler level. Published at ASPLOS 2024.",
        "methodology": "ASPLOS 2024. eBPF-specific compiler optimization. Multi-tier approach balancing performance and instruction count. Evaluation on real-world eBPF programs."
    }, "concepts": ["eBPF (Extended Berkeley Packet Filter)"], "claims": [
        {"kind": "Problem", "id_prefix": "prob", "name": "Standard compilers don't optimize for eBPF constraints", "description": "eBPF's ISA has unique constraints (instruction limits, verifier safety requirements) that LLVM's general-purpose optimization passes don't target. Programs may exceed instruction limits or miss performance opportunities specific to eBPF's execution model."},
        {"kind": "Proposal", "id_prefix": "prop", "name": "Multi-tier eBPF-specific compiler optimization", "description": "Merlin provides eBPF-aware optimization tiers targeting both performance and compactness within the kernel verifier's constraints, filling the gap between LLVM's general optimization and eBPF's unique requirements."}
    ]},

    # ── 6. SEVeriFast: Fast Confidential MicroVM Startup ───────────
    {"ev_id": "ev-conf-e2881eaf", "brief": {
        "key_ideas": ["Investigates AMD SEV for microVMs and finds confidential VM startup times are prohibitively expensive for serverless", "Minimizes the root of trust to accelerate SEV microVM boot — reduces the trusted initialization path", "Addresses the gap between serverless latency requirements (10-100ms boot) and confidential VM overhead", "Enables practical confidential computing for latency-sensitive serverless platforms"],
        "relevance": "Directly targets the Linux kernel's KVM + AMD SEV initialization path. The kernel creates SEV-encrypted VMs through KVM ioctls — SEVeriFast optimizes this path by minimizing what needs to be measured and encrypted during boot. Relevant to the kernel's KVM SEV support (arch/x86/kvm/svm/sev.c), the SEV firmware interface, and the startup sequence for confidential VMs.",
        "methodology": "ASPLOS. AMD SEV microVM optimization. Root of trust minimization. Startup time evaluation for serverless workloads."
    }, "concepts": ["KVM (Kernel-based Virtual Machine)", "Linux Security Modules"], "claims": [
        {"kind": "Problem", "id_prefix": "prob", "name": "Confidential VM startup too slow for serverless", "description": "Current AMD SEV confidential VM startup times are prohibitively expensive for serverless platforms that need 10-100ms boot times. The root of trust initialization adds significant overhead to the KVM VM creation path."},
        {"kind": "Proposal", "id_prefix": "prop", "name": "Minimized root of trust for fast SEV microVM boot", "description": "SEVeriFast reduces the trusted initialization path for AMD SEV microVMs, enabling practical confidential computing for latency-sensitive serverless platforms."}
    ]},

    # ── 7. Snowplow: Learned Kernel Fuzzer Mutation ────────────────
    {"ev_id": "ev-conf-564f17d9", "brief": {
        "key_ideas": ["White-box test mutator for kernel fuzzing that learns effective mutations from kernel code structure", "Alters control and data flow by inserting syscalls, changing arguments based on learned patterns rather than random mutation", "Addresses the challenge that kernel code complexity makes random mutation inefficient for reaching deep code paths", "Achieves higher coverage than random mutation by learning which mutations are effective for specific kernel subsystems"],
        "relevance": "Directly improves kernel fuzzing (syzkaller ecosystem). Where KernelGPT (batch 009) synthesizes syscall specifications and KNighter (batch 012) synthesizes static analyzers, Snowplow learns effective test mutations — a complementary approach. All three use learning to improve kernel testing. The white-box approach uses kernel code structure to guide mutations, which means it interacts with the kernel's KCOV coverage infrastructure.",
        "methodology": "ASPLOS. Learned mutation for kernel fuzzing. White-box approach using kernel code structure. Coverage comparison against random mutation."
    }, "concepts": [], "claims": [
        {"kind": "Proposal", "id_prefix": "prop", "name": "Learned white-box kernel fuzzer mutations", "description": "Snowplow learns effective test mutations from kernel code structure rather than random mutation, improving coverage for deep kernel code paths. Complements specification-based (KernelGPT) and analyzer-based (KNighter) approaches."}
    ]},

    # ── 8. Melody: CXL Memory Characterization at Scale ────────────
    {"ev_id": "ev-conf-48ba1c56", "brief": {
        "key_ideas": ["Framework for systematic characterization of CXL memory across 265 workloads, 4 real CXL devices, 7 latency levels, and 5 CPU platforms", "Most comprehensive real-hardware CXL evaluation — spans devices, processors, and workloads to understand performance implications", "Reveals that CXL performance depends heavily on device type, latency regime, and processor architecture — no single characterization applies universally", "Provides guidance for kernel memory tiering policy based on empirical multi-device data"],
        "relevance": "The most comprehensive real-hardware CXL characterization — essential data for kernel CXL memory management. The kernel's tiering policies (AutoNUMA, DAMON) need to know how CXL devices actually perform across different conditions. Testing on 4 real devices and 5 CPU platforms reveals that one-size-fits-all kernel policies are insufficient — the kernel needs device-aware tiering. Published at ASPLOS 2025.",
        "methodology": "ASPLOS 2025. 265 workloads, 4 CXL devices, 7 latency levels, 5 CPU platforms. Systematic characterization framework."
    }, "concepts": ["Adaptive CXL Memory Tiering", "NUMA Topology and Memory Policy"], "claims": [
        {"kind": "Observation", "id_prefix": "obs", "name": "CXL performance varies dramatically across device-CPU combinations", "description": "Characterization across 4 real CXL devices, 5 CPU platforms, and 265 workloads shows CXL memory performance depends heavily on device type, latency regime, and processor architecture. No single characterization or kernel policy applies universally."}
    ]},

    # ── 9. GMT: GPU-Orchestrated Memory Tiering ────────────────────
    {"ev_id": "ev-conf-f0d4708f", "brief": {
        "key_ideas": ["GPU directly orchestrates memory tiering to SSD storage, bypassing CPU/host software intermediaries that are too slow for GPU throughput needs", "State-of-art CPU-mediated approaches (Dragon, HMM) perform poorly for GPU access patterns — NVMe queue direct access (BaM) lacks proper memory management", "GPU threads manage their own page tables and data movement between GPU memory and SSD", "Addresses the growing need for GPUs to access datasets larger than GPU memory capacity"],
        "relevance": "Challenges the kernel's role as memory manager for GPU workloads. When GPUs need to access SSD data, going through the kernel's page cache and block I/O layer is too slow. GMT bypasses the kernel entirely for the GPU-SSD data path. This is relevant to the kernel's HMM (Heterogeneous Memory Management) subsystem, the GPU driver's memory management, and the NVMe driver. Shows that the kernel's memory management is the bottleneck for GPU-storage tiering.",
        "methodology": "ASPLOS. GPU-orchestrated SSD tiering. Comparison against CPU-mediated (Dragon, HMM) and direct NVMe (BaM) approaches."
    }, "concepts": ["NVMe Driver Subsystem", "Page Fault Handler", "NUMA Topology and Memory Policy"], "claims": [
        {"kind": "Problem", "id_prefix": "prob", "name": "Kernel-mediated GPU-SSD tiering too slow for GPU throughput", "description": "CPU/host software intermediaries (including kernel page cache and block I/O) cannot meet GPU throughput needs for accessing SSD-backed datasets. State-of-art approaches like HMM perform poorly for GPU access patterns."},
        {"kind": "Proposal", "id_prefix": "prop", "name": "GPU-orchestrated direct memory tiering to SSD", "description": "GMT enables GPU threads to directly manage page tables and data movement between GPU memory and SSDs, bypassing CPU/kernel intermediaries. Addresses datasets larger than GPU memory capacity."}
    ]},

    # ── 10. Cooperative Graceful Degradation in Containers ──────────
    {"ev_id": "ev-conf-53d35d58", "brief": {
        "key_ideas": ["Vision for automated cloud resilience with cooperative graceful degradation between applications and cloud operators", "Applications declare availability requirements and degradation strategies; cloud operators execute degradation decisions respecting those requirements", "Investigates graceful degradation techniques and identifies challenges for containerized cloud environments", "Enables cloud operators to perform degradation while satisfying application SLAs"],
        "relevance": "Relevant to the kernel's cgroup resource management and container lifecycle. Graceful degradation requires the kernel to reduce resources (CPU, memory via cgroup limits) while applications adapt. The cooperative model means the kernel must communicate resource pressure to applications (OOM notifications, memory pressure events via PSI) rather than just killing containers. Relevant to the kernel's PSI (Pressure Stall Information) and cgroup memory.events interface.",
        "methodology": "ASPLOS. Graceful degradation techniques for containerized clouds. Application-operator cooperation model."
    }, "concepts": ["Control Groups (cgroups v2)", "OOM Killer", "Namespaces"], "claims": [
        {"kind": "Proposal", "id_prefix": "prop", "name": "Cooperative graceful degradation for containerized clouds", "description": "Applications declare availability requirements and degradation strategies; cloud operators execute degradation decisions. Enables resource reduction via cgroups while applications adapt, rather than abrupt OOM killing."}
    ]},

    # ── 11. Instruction-Aware TLB and Cache Replacement ─────────────
    {"ev_id": "ev-conf-286140aa", "brief": {
        "key_ideas": ["Modern server applications have large instruction footprints causing frequent instruction TLB and cache misses", "Instruction TLB misses cause pipeline stalls significantly harming performance — worse than data TLB misses", "Proposes cooperative replacement policies that are aware of instruction vs data access type", "Targets the instruction-specific performance bottleneck that general replacement policies miss"],
        "relevance": "Directly relevant to the kernel's TLB management. The kernel's page table layout affects instruction TLB miss rates — code pages and data pages compete for TLB entries. The kernel could hint the hardware about instruction vs data pages through page table flags. Also relevant to the kernel's own instruction footprint — the kernel's code paths (syscall handlers, scheduler, networking) contribute to instruction TLB pressure.",
        "methodology": "ASPLOS. Instruction-aware TLB and cache replacement. Server workload evaluation. Pipeline stall analysis."
    }, "concepts": ["Translation Lookaside Buffer", "Hierarchical Page Tables"], "claims": [
        {"kind": "Observation", "id_prefix": "obs", "name": "Instruction TLB misses dominate server workload performance", "description": "Modern server and datacenter applications have large instruction footprints causing frequent instruction TLB and cache misses. Instruction TLB misses cause pipeline stalls that are more harmful than data TLB misses."}
    ]},

    # ── 12. FLEXPROF: Side-Channel-Free Memory Access ──────────────
    {"ev_id": "ev-conf-e6185f82", "brief": {
        "key_ideas": ["Allocates turns within the memory controller to each co-scheduled VM, with gaps between turns to prevent resource conflicts and side-channels", "Prior secure memory scheduling imposes 2x performance slowdown — FLEXPROF reduces this significantly", "Flexible memory scheduling that prevents side-channel leakage between co-located VMs through the shared memory controller", "Addresses microarchitectural side-channels induced by shared memory controller resources"],
        "relevance": "Directly relevant to the kernel's memory controller interaction and KVM VM scheduling. Memory controller side-channels leak information between VMs scheduled on the same socket. FLEXPROF's turn-based scheduling must be coordinated with the kernel's KVM vCPU scheduler — when VMs are scheduled affects which memory controller turns they get. This is relevant to the kernel's resctrl (Resource Control) interface and cache/memory bandwidth allocation.",
        "methodology": "ASPLOS. Secure memory controller scheduling. VM turn allocation with gaps. Performance vs security tradeoff evaluation."
    }, "concepts": ["KVM (Kernel-based Virtual Machine)"], "claims": [
        {"kind": "Problem", "id_prefix": "prob", "name": "Shared memory controller enables VM-to-VM side-channels", "description": "Co-scheduled VMs share memory controller resources, enabling microarchitectural side-channels. Prior secure scheduling defenses impose a 2x performance slowdown to eliminate these channels."},
        {"kind": "Proposal", "id_prefix": "prop", "name": "Flexible side-channel-free memory scheduling for VMs", "description": "FLEXPROF allocates per-VM turns in the memory controller with gaps to prevent resource conflicts. Reduces the 2x performance overhead of prior secure memory scheduling approaches."}
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
