"""Deep enrichment batch 017: 15 conference papers from SOSP, FAST, HPCA, NSDI, CCS, HotOS.
"""
import json, sqlite3, uuid

DB_PATH = "data/master.db"

ALL_PAPERS = [
    # ── 1. Time Machine: Hypervisor Ransomware Defense ─────────────
    {"ev_id": "ev-conf-f1191eee", "brief": {
        "key_ideas": ["Real-time sector-level live view navigation at the hypervisor level to defend against ransomware", "Fine-grained sector-level tracking enables point-in-time recovery without full backups", "Operates at the hypervisor layer — transparent to the guest OS and filesystem, protecting against kernel-level ransomware", "Advances over prior work: real-time defense rather than post-incident recovery"],
        "relevance": "Operates at the KVM hypervisor level, intercepting block I/O between the guest and storage to track sector-level changes. This requires integration with the kernel's block device layer and KVM's I/O interception path (virtio-blk or VFIO). The sector-level versioning is analogous to device-mapper snapshots but at hypervisor granularity. Relevant to the kernel's dm-snapshot, KVM I/O path, and block layer change tracking.",
        "methodology": "CCS. Hypervisor-level sector tracking. Live view navigation for ransomware defense. Real-time overhead evaluation."
    }, "concepts": ["KVM (Kernel-based Virtual Machine)", "Block Device Layer", "Device Mapper"], "claims": [
        {"kind": "Proposal", "id_prefix": "prop", "name": "Hypervisor-level sector versioning for ransomware defense", "description": "Time Machine provides real-time sector-level change tracking at the hypervisor, enabling point-in-time filesystem recovery without full backups. Transparent to guest OS, protects against kernel-level ransomware."}
    ]},

    # ── 2. GhostCache: Timer-Free Cache Attacks on RISC-V/ARM ─────
    {"ev_id": "ev-conf-8ace3f4b", "brief": {
        "key_ideas": ["Verifies widespread weak L1 cache coherence on multiple RISC-V and ARM chips — exploits it to bypass timer restrictions", "Timer- and counter-free cache side-channel attacks that work even when high-resolution timers are restricted", "Demonstrates that restricting timers is insufficient mitigation — weak coherence provides an alternative timing signal", "Affects emerging processor architectures designed with security mitigations in mind"],
        "relevance": "Directly relevant to the kernel's cache management on RISC-V and ARM. The kernel assumes coherent caches across cores — weak coherence means the kernel's memory ordering assumptions may be wrong on these platforms. The attack bypasses timer restrictions that the kernel enforces (e.g., reduced timer resolution for untrusted processes). This motivates kernel-level cache coherence enforcement or architectural changes. Published at CCS 2025.",
        "methodology": "CCS 2025. Weak L1 cache coherence exploitation. Multiple RISC-V and ARM chips. Timer-free and counter-free side-channel construction."
    }, "concepts": ["Translation Lookaside Buffer", "Interrupt Handling"], "claims": [
        {"kind": "FailureMode", "id_prefix": "fail", "name": "Weak cache coherence enables timer-free side-channel attacks", "description": "Multiple RISC-V and ARM chips exhibit weak L1 cache coherence that can be exploited for side-channel attacks without requiring high-resolution timers or counters. Timer restriction mitigations are insufficient on these architectures."}
    ]},

    # ── 3. I/O Passthru: Upstreaming Flexible I/O Path in Linux ───
    {"ev_id": "ev-conf-7f7d33f2", "brief": {
        "key_ideas": ["Upstream-quality flexible and efficient I/O path in the Linux kernel for NVMe passthrough", "Addresses tight coupling between data-intensive systems and I/O interface — databases inherit limitations of their I/O backend", "With high-performance NVMe SSDs enabling millions of IOPS, the kernel I/O stack overhead becomes the bottleneck", "Provides passthrough I/O that bypasses filesystem and block layer overhead while remaining in-kernel"],
        "relevance": "Directly contributes to the Linux kernel's NVMe and block I/O subsystems. I/O passthrough (bypassing the filesystem and block layer for direct NVMe access) is being upstreamed into the Linux kernel. This complements io_uring's passthrough mode. The paper addresses the fundamental problem that the kernel's layered I/O stack (VFS → filesystem → block layer → NVMe driver) adds overhead that matters at millions of IOPS. Published at FAST.",
        "methodology": "FAST. Linux kernel NVMe passthrough implementation. Performance evaluation at high IOPS. Upstream-quality design."
    }, "concepts": ["NVMe Driver Subsystem", "Block Device Layer", "io_uring"], "claims": [
        {"kind": "Problem", "id_prefix": "prob", "name": "Kernel I/O stack overhead visible at millions of NVMe IOPS", "description": "The kernel's layered I/O stack (VFS → filesystem → block layer → NVMe driver) adds overhead that becomes the bottleneck with modern NVMe SSDs capable of millions of IOPS. Data-intensive systems inherit I/O backend limitations."},
        {"kind": "Proposal", "id_prefix": "prop", "name": "Upstream-quality NVMe I/O passthrough in Linux kernel", "description": "Flexible and efficient I/O passthrough path in the Linux kernel that bypasses filesystem and block layer overhead for direct NVMe access while remaining in-kernel (not a bypass solution)."}
    ]},

    # ── 4. Symbiosis: Application and Kernel Cache Cooperation ─────
    {"ev_id": "ev-conf-e5f44c78", "brief": {
        "key_ideas": ["Art of cooperation between application-level caches and the kernel page cache — currently they compete rather than cooperate", "Application caches (database buffer pools, KV store caches) and the kernel page cache independently cache the same data, wasting memory", "Proposes mechanisms for the application to communicate cache intent to the kernel, and vice versa", "Achieves better memory utilization by eliminating double-caching between application and kernel layers"],
        "relevance": "Directly addresses the Linux kernel's page cache interaction with applications. The double-caching problem (application buffer pool + kernel page cache caching the same data) wastes 30-50% of memory in database workloads. The kernel provides madvise() and fadvise() for hints but they're insufficient. Symbiosis proposes richer kernel-application cache coordination. Published at FAST — directly relevant to the kernel's page cache, VFS, and memory management.",
        "methodology": "FAST. Application-kernel cache cooperation design. Double-caching elimination. Memory utilization evaluation."
    }, "concepts": ["Page Cache", "Virtual Filesystem Switch"], "claims": [
        {"kind": "Problem", "id_prefix": "prob", "name": "Application and kernel page cache double-cache the same data", "description": "Application-level caches (database buffer pools, KV store caches) and the kernel page cache independently cache the same data, wasting significant memory. Existing hints (madvise/fadvise) are insufficient for proper coordination."},
        {"kind": "Proposal", "id_prefix": "prop", "name": "Cooperative caching between application and kernel page cache", "description": "Symbiosis enables application caches and the kernel page cache to cooperate rather than compete, eliminating double-caching through richer kernel-application cache coordination mechanisms."}
    ]},

    # ── 5. Computational CXL-Memory for Data-Intensive Apps ────────
    {"ev_id": "ev-conf-e81c94e6", "brief": {
        "key_ideas": ["Novel CXL-based memory disaggregation architecture with computational capabilities to overcome CXL's limited physical bandwidth", "CXL bandwidth can be a bottleneck for data-intensive applications — adding compute near CXL memory reduces data movement", "Proposes compute-capable CXL memory controller for near-data processing", "Addresses the gap between CXL's memory expansion promise and its bandwidth limitations"],
        "relevance": "Extends the CXL memory model with in-controller computation — the kernel's CXL driver must manage a device that is both memory and compute. This complements M2NDP (batch 012, general-purpose CXL NDP) and NEURON-Fabric (batch 002, gradient aggregation in CXL). The kernel needs a unified device model for CXL devices with varying compute capabilities. Published at HPCA.",
        "methodology": "HPCA. Computational CXL memory architecture. Near-data processing for data-intensive applications. Bandwidth optimization evaluation."
    }, "concepts": ["Adaptive CXL Memory Tiering", "NUMA Topology and Memory Policy"], "claims": [
        {"kind": "Proposal", "id_prefix": "prop", "name": "Computational CXL memory to overcome bandwidth limitations", "description": "CXL-based memory with computational capabilities in the memory controller reduces data movement over the bandwidth-limited CXL interface. Near-data processing for data-intensive applications on CXL-expanded memory."}
    ]},

    # ── 6. NVMePass: Lightweight NVMe Virtualization ───────────────
    {"ev_id": "ev-conf-58745420", "brief": {
        "key_ideas": ["Lightweight NVMe virtualization with I/O queues passthrough — avoids both software emulation overhead and hardware SR-IOV limitations", "Virtio suffers performance degradation; polling-based solutions consume too many CPU resources — NVMePass provides a middle ground", "Passes NVMe I/O queues directly to VMs while maintaining isolation without dedicated hardware", "High-performance and scalable NVMe virtualization for cloud computing"],
        "relevance": "Directly addresses the Linux kernel's NVMe virtualization options in KVM. Current approaches: virtio-blk (software, slow), VFIO/SR-IOV (hardware, limited VFs), vhost (polling, CPU-heavy). NVMePass provides a new point in the design space — NVMe queue passthrough with software isolation. This requires kernel changes to both the NVMe driver (queue management) and KVM (queue passthrough). Published at HPCA.",
        "methodology": "HPCA. NVMe queue passthrough architecture. Comparison against virtio, polling, and SR-IOV approaches. Scalability evaluation."
    }, "concepts": ["NVMe Driver Subsystem", "KVM (Kernel-based Virtual Machine)", "Virtio Paravirtual I/O"], "claims": [
        {"kind": "Proposal", "id_prefix": "prop", "name": "NVMe I/O queue passthrough for lightweight virtualization", "description": "NVMePass passes NVMe I/O queues directly to VMs without hardware SR-IOV, avoiding both virtio software emulation overhead and polling CPU waste. Lightweight, high-performance, and scalable NVMe virtualization."}
    ]},

    # ── 7. Data Enclave: Data-Centric TEE ──────────────────────────
    {"ev_id": "ev-conf-466aa58e", "brief": {
        "key_ideas": ["New data abstraction for TEEs: data enclaves manage data independently of code enclaves, enabling secure data sharing between enclaves", "Existing TEEs with integrity protection lack data management primitives — sharing data between enclaves is either insecure or cumbersome", "Data-centric rather than code-centric TEE model — the data owns its access policy, not the code", "Addresses the fundamental limitation of enclave-based TEEs where data is locked to a single enclave"],
        "relevance": "Proposes a new TEE abstraction that the kernel must support. Current kernel TEE management (KVM for TDX/SEV, SGX driver) is code-centric — each enclave/CVM owns its data. Data enclaves require the kernel to manage data objects with their own access policies across enclave boundaries. This is relevant to the kernel's SGX driver, KVM's CVM data sharing, and the attestation infrastructure. Published at HPCA.",
        "methodology": "HPCA. Data-centric TEE architecture. Secure cross-enclave data sharing. Data management primitive design."
    }, "concepts": ["Linux Security Modules", "KVM (Kernel-based Virtual Machine)"], "claims": [
        {"kind": "Proposal", "id_prefix": "prop", "name": "Data enclaves for secure cross-TEE data sharing", "description": "Data enclaves manage data independently of code enclaves with their own access policies. Enables secure data sharing between TEEs without the insecurity or complexity of current enclave data export mechanisms."}
    ]},

    # ── 8. Marching Page Walks: Batching GPU Page Table Walks ──────
    {"ev_id": "ev-conf-48b6d177", "brief": {
        "key_ideas": ["Batching and concurrent page table walks to enhance GPU throughput — addresses discrepancy between page table walker behavior and thousands of concurrent GPU threads", "GPU execution model heavily pressures translation hardware due to thousands of concurrent threads", "Proposes marching (batched, pipelined) page walks that amortize translation overhead across many concurrent requests", "Directly targets the GPU's virtual memory translation bottleneck"],
        "relevance": "Relevant to the kernel's GPU memory management via the DRM/KMS driver and IOMMU. The kernel sets up GPU page tables through the driver; marching page walks change how the hardware traverses those tables. This is relevant to the kernel's IOMMU page table management for GPU (PASID-based), the HMM (Heterogeneous Memory Management) subsystem, and future GPU driver page table optimizations. Published at HPCA.",
        "methodology": "HPCA. Batched concurrent page table walk architecture. GPU throughput evaluation. Translation overhead amortization analysis."
    }, "concepts": ["Hierarchical Page Tables", "Translation Lookaside Buffer"], "claims": [
        {"kind": "Proposal", "id_prefix": "prop", "name": "Batched concurrent page table walks for GPU throughput", "description": "Marching page walks batch and pipeline page table translations across thousands of concurrent GPU threads, amortizing the overhead of sequential PTE fetches. Addresses the GPU virtual memory translation bottleneck."}
    ]},

    # ── 9. LibPreemptible: User-Space Scheduling ──────────────────
    {"ev_id": "ev-conf-a3f64924", "brief": {
        "key_ideas": ["Fast, adaptive, hardware-assisted user-space scheduling for microsecond-scale workloads — targets high tail latency in cloud applications", "Existing approaches (custom dataplane OSes) require significant application changes — LibPreemptible works as a library", "Hardware-assisted preemption enables responsive scheduling without OS kernel involvement", "Reduces tail latency for microsecond-scale workloads without requiring a custom OS"],
        "relevance": "Directly relevant to the kernel's scheduling interface and the user-space scheduling movement (sched_ext, User Interrupts). LibPreemptible provides user-space preemptive scheduling using hardware features (Intel User Interrupts) — avoiding kernel scheduler involvement for latency-critical paths. This complements Enoki (scheduler development framework) and sched_ext (eBPF schedulers) by enabling user-space scheduling with hardware assistance. Published at HPCA.",
        "methodology": "HPCA. Library-based user-space scheduling. Hardware-assisted preemption. Tail latency evaluation for microsecond workloads."
    }, "concepts": ["Scheduling Classes", "Interrupt Handling"], "claims": [
        {"kind": "Proposal", "id_prefix": "prop", "name": "Hardware-assisted user-space scheduling library", "description": "LibPreemptible enables fast, adaptive preemptive scheduling in user space via hardware assistance (Intel User Interrupts), avoiding kernel scheduler overhead for microsecond-scale workloads. Works as a library without requiring a custom OS."}
    ]},

    # ── 10. LearnedFTL: Learning-Based SSD FTL ────────────────────
    {"ev_id": "ev-conf-f79f0c6f", "brief": {
        "key_ideas": ["Uses learned indexes to improve SSD flash translation layer (FTL) address translation efficiency", "Reduces double reads induced by address translation in random read accesses — the FTL is the SSD-internal bottleneck", "On-demand page-level FTL design that learns address mapping patterns for predictive translation", "First application of learned indexes to SSD firmware-level address translation"],
        "relevance": "The FTL is invisible to the kernel (it's inside the SSD firmware), but its performance directly affects what the kernel's block I/O layer and NVMe driver observe. LearnedFTL's reduction of double reads improves the random read performance that kernel filesystems (ext4, XFS) and block I/O paths depend on. Understanding FTL behavior helps kernel developers design better I/O scheduling policies. Published at HPCA.",
        "methodology": "HPCA. Learned index-based FTL design. Double read reduction analysis. Random read performance evaluation."
    }, "concepts": ["NVMe Driver Subsystem", "Block Device Layer"], "claims": [
        {"kind": "Proposal", "id_prefix": "prop", "name": "Learned indexes for efficient SSD flash translation", "description": "LearnedFTL applies learned indexes to the SSD's flash translation layer, reducing double reads from address translation in random access patterns. First application of ML to firmware-level address mapping."}
    ]},

    # ── 11. PREFETCHX: Cross-Core Prefetcher Side Channels ────────
    {"ev_id": "ev-conf-e7138412", "brief": {
        "key_ideas": ["Reveals existence of a new XPT prefetcher class in Intel processors that has never been officially documented", "The prefetcher speculatively issues loads bypassing LLC lookups when it predicts an LLC miss — creating a cross-core side channel", "Cross-core and cache-agnostic — works across CPU cores without requiring shared cache lines", "New class of hardware side channel from undocumented Intel prefetcher behavior"],
        "relevance": "Discovers an undocumented Intel hardware feature that creates side channels — directly relevant to the kernel's security model. The kernel assumes certain hardware behaviors for isolation (cache partitioning, core isolation); undocumented prefetchers that bypass LLC create channels the kernel cannot mitigate with existing resctrl/CAT controls. This motivates kernel-level prefetcher management (disabling or constraining prefetch behavior per security domain). Published at HPCA.",
        "methodology": "HPCA. Reverse engineering of undocumented Intel XPT prefetcher. Cross-core side-channel construction. Cache-agnostic attack demonstration."
    }, "concepts": ["Interrupt Handling"], "claims": [
        {"kind": "FailureMode", "id_prefix": "fail", "name": "Undocumented Intel XPT prefetcher creates cross-core side channel", "description": "A previously unknown XPT prefetcher class in Intel processors speculatively issues loads bypassing LLC lookups. This creates cross-core, cache-agnostic side channels that existing kernel mitigations (resctrl, CAT) cannot address."}
    ]},

    # ── 12. DockerSSD: Containerized In-Storage Processing ─────────
    {"ev_id": "ev-conf-620df12d", "brief": {
        "key_ideas": ["Containerized in-storage processing and hardware acceleration for computational SSDs", "Applies container isolation concepts (namespaces, resource limits) to computational SSD workloads", "Addresses practical challenges of in-storage processing: limited processing capabilities and security vulnerabilities", "Hardware acceleration within the SSD for efficient near-data computation"],
        "relevance": "Brings the kernel's container abstractions (namespaces, cgroups) to computational storage devices. The kernel manages containers on CPUs — DockerSSD applies the same isolation model to SSD-internal compute. This is relevant to the kernel's device model for computational storage and how the kernel should expose in-storage compute capabilities. Published at HPCA.",
        "methodology": "HPCA. Containerized computational SSD architecture. Hardware acceleration for in-storage processing. Security and isolation evaluation."
    }, "concepts": ["NVMe Driver Subsystem", "Namespaces", "Control Groups (cgroups v2)"], "claims": [
        {"kind": "Proposal", "id_prefix": "prop", "name": "Container isolation model for in-storage processing on SSDs", "description": "DockerSSD applies container isolation (namespaces, resource limits) to computational SSD workloads with hardware acceleration, addressing the processing limitations and security challenges of in-storage computation."}
    ]},

    # ── 13. Spork: posix_spawn as Fork Replacement ────────────────
    {"ev_id": "ev-conf-aabd4cc6", "brief": {
        "key_ideas": ["posix_spawn that you can actually use as a fork replacement — addresses the long-standing debate about fork() being obsolete", "Makes posix_spawn practical as a general-purpose process creation mechanism, not just a narrow POSIX interface", "Fork is unsafe in multithreaded programs and increasingly expensive — posix_spawn avoids both problems", "Practical drop-in replacement for common fork+exec patterns"],
        "relevance": "Directly addresses the Linux kernel's fork() and posix_spawn() implementations. The fork-is-broken-in-multithreaded-programs problem has been known for decades (only one thread survives fork, locks may be held). posix_spawn avoids this by never creating an intermediate process state. This is relevant to the kernel's process creation path (kernel/fork.c) and the ongoing discussion about whether the kernel should optimize for posix_spawn over fork. Published at HotOS 2025.",
        "methodology": "HotOS 2025. posix_spawn as practical fork replacement. Multi-threaded safety analysis. Performance comparison against fork+exec."
    }, "concepts": ["Process Creation (fork/clone)"], "claims": [
        {"kind": "Observation", "id_prefix": "obs", "name": "Fork is unsafe in multithreaded programs and increasingly expensive", "description": "fork() in multithreaded programs only preserves one thread, leaving locks potentially held by dead threads. As address spaces grow, fork's CoW setup becomes expensive. posix_spawn avoids both problems but needs practical improvements to serve as a general replacement."},
        {"kind": "Proposal", "id_prefix": "prop", "name": "Practical posix_spawn as fork replacement", "description": "Spork makes posix_spawn practical as a general-purpose process creation mechanism — a drop-in replacement for common fork+exec patterns that avoids fork's multi-threading unsafety and CoW overhead."}
    ]},

    # ── 14. LightPool: NVMe-oF Storage Pool for Cloud DB ──────────
    {"ev_id": "ev-conf-96d94aa7", "brief": {
        "key_ideas": ["NVMe-oF-based storage pool architecture for cloud-native distributed databases — addresses low utilization of local NVMe storage", "Imbalance between CPU and storage capacities within database nodes causes storage underutilization", "High-performance pooling via NVMe over Fabrics enables storage sharing across database nodes", "Targets OceanBase and similar distributed databases running on local NVMe"],
        "relevance": "Directly uses the Linux kernel's NVMe-oF (NVMe over Fabrics) subsystem. The kernel's NVMe-oF target and initiator drivers enable remote NVMe access — LightPool builds a storage pool on top. Relevant to the kernel's nvme-of target, RDMA subsystem, and the block device layer's support for remote storage. Published at HPCA.",
        "methodology": "HPCA. NVMe-oF storage pooling for distributed databases. Storage utilization optimization. OceanBase integration."
    }, "concepts": ["NVMe Driver Subsystem", "Block Device Layer"], "claims": [
        {"kind": "Proposal", "id_prefix": "prop", "name": "NVMe-oF storage pool for cloud-native database storage sharing", "description": "LightPool uses NVMe over Fabrics to pool local NVMe storage across distributed database nodes, addressing CPU-storage imbalance that causes storage underutilization. High-performance storage sharing for cloud-native databases."}
    ]},

    # ── 15. Superpages in SSDs: Performance Variation ──────────────
    {"ev_id": "ev-conf-2fae49d7", "brief": {
        "key_ideas": ["Discovers that flash superpages (grouped flash pages) suffer from process variation — each page has different read/write performance", "If a slow page is grouped with fast pages in a superpage, the entire superpage operates at slow-page speed", "Proves that superpage organization causes performance degradation visible to the host system", "Proposes flash block distillation to unify page performance within superpages"],
        "relevance": "The kernel's block I/O layer and filesystem assume uniform performance within an SSD — this paper shows that's false at the flash page level. Performance variation within superpages affects the latency distribution that the kernel's I/O scheduler (mq-deadline, BFQ) observes. Understanding this helps kernel developers design I/O schedulers that account for SSD-internal performance heterogeneity. Published at HPCA.",
        "methodology": "HPCA. Flash superpage performance characterization. Process variation analysis. Flash block distillation for performance uniformity."
    }, "concepts": ["Block Device Layer", "NVMe Driver Subsystem"], "claims": [
        {"kind": "Observation", "id_prefix": "obs", "name": "Flash superpage process variation degrades SSD performance", "description": "Process variation gives each flash page different read/write performance. Slow pages grouped with fast pages in a superpage cause the entire superpage to operate at slow-page speed, creating performance variation visible to the host OS."}
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
