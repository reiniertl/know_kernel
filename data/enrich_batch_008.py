"""Deep enrichment batch 008: 8 papers — IOMMU, hypervisor bandwidth, driver security,
compressed swap, ZNS SSD, confidential VMs, RTOS timers, TPM attestation.

Papers:
1. IOMMU Shared Virtual Addressing — RISC-V IOMMU evaluation for heterogeneous SoCs
2. H-MBR — Hypervisor-level memory bandwidth reservation for mixed-criticality
3. Intel ICE Driver Security — Security audit with RCU issues and timing side channels
4. Ariadne — Hotness-aware compressed swap (ZRAM) for mobile (50% faster relaunch)
5. SilentZNS — Eliminating hidden costs of zone management in ZNS SSDs
6. CCxTrust — TEE+TPM collaborative confidential computing with AMD SEV-SNP
7. CHRONOS — Multi-timer RTOS tick optimization for FreeRTOS
8. TPM Remote Attestation — IMA+TPM continuous attestation for K8s 5G VNFs
"""
import json, sqlite3, uuid

DB_PATH = "data/master.db"

ALL_PAPERS = [
    # ── 1. IOMMU Shared Virtual Addressing on RISC-V ────────────────
    {
        "ev_id": "ev-arxiv-762b51db",
        "brief": {
            "key_ideas": [
                "Quantitative evaluation of IOMMU-based shared virtual addressing in RISC-V heterogeneous embedded SoCs — integrates IOMMU into an open-source SoC with 64-bit host and 32-bit accelerator cluster",
                "IO virtual address translation costs 4.2-17.6% of accelerator runtime for GEMM at varying memory bandwidth — showing IOMMU overhead is significant for compute-bound accelerator workloads",
                "With a last-level cache, IOTLB miss cost drops to 0.4-0.7% — demonstrating that caching is essential for practical IOMMU-based shared virtual addressing",
                "Evaluated with RajaPERF benchmark suite using heterogeneous OpenMP — showing practical shared-address-space programming for RISC-V accelerators"
            ],
            "relevance": "Directly evaluates the IOMMU subsystem — the kernel's primary mechanism for allowing devices to share virtual address space with the CPU. The 4.2-17.6% overhead without LLC (dropping to <1% with LLC) quantifies the cost of the kernel's IOMMU page table walks for accelerator I/O. This is relevant to the kernel's IOMMU driver (iommu subsystem), DMA mapping framework, and the ARM SMMU/Intel VT-d equivalent on RISC-V. The shared virtual addressing model is what enables the kernel's SVA (Shared Virtual Addressing) feature for accelerators.",
            "methodology": "FPGA emulation of RISC-V heterogeneous SoC with IOMMU. RajaPERF benchmark suite with heterogeneous OpenMP. DRAM latency sweep. IOTLB miss cost analysis."
        },
        "concepts": ["DMA Mapping Framework"],
        "claims": [
            {"kind": "Observation", "id_prefix": "obs", "name": "IOMMU translation costs 4-18% without cache, <1% with LLC",
             "description": "IO virtual address translation via IOMMU accounts for 4.2-17.6% of accelerator runtime for GEMM on RISC-V without a last-level cache (requiring up to 3 sequential memory accesses on IOTLB miss). With LLC, the cost drops to 0.4-0.7%."},
            {"kind": "PerformanceProfile", "id_prefix": "perf", "name": "IOTLB caching essential for IOMMU shared virtual addressing",
             "description": "Without LLC caching, IOMMU-based shared virtual addressing overhead is 4.2-17.6% at varying memory bandwidth. LLC reduces this to sub-1%, making IOTLB/LLC sizing critical for practical accelerator shared addressing."}
        ]
    },

    # ── 2. H-MBR: Hypervisor Memory Bandwidth Reservation ──────────
    {
        "ev_id": "ev-arxiv-d17f990d",
        "brief": {
            "key_ideas": [
                "VM-centric memory bandwidth reservation at the hypervisor level — ensures temporal isolation for mixed-criticality VMs sharing hardware without relying on specific OS support",
                "Addresses the gap between cache coloring (implemented in hypervisors) and memory bandwidth reservation (implemented at Linux kernel level) — H-MBR brings bandwidth reservation to the hypervisor where it's OS-agnostic",
                "Three properties: VM-centric reservation, OS/platform agnosticism, and reduced overhead — works for any guest OS (Linux, RTOS, bare-metal) running in VMs",
                "Open-source implementation with no measurable overhead on non-regulated workloads"
            ],
            "relevance": "Directly addresses the kernel's resource isolation challenge for KVM-based mixed-criticality systems. Linux's existing bandwidth control (MBA on Intel, MPAM on ARM) operates at the OS level, but when running VMs, the hypervisor needs to enforce bandwidth limits per-VM regardless of the guest OS. H-MBR fills this gap — it's the memory bandwidth analog of what cgroups provide for CPU time, but implemented at the hypervisor level. Relevant to KVM's resource management and the kernel's hardware QoS interfaces (resctrl).",
            "methodology": "Hypervisor-level implementation of memory bandwidth reservation. Mixed-criticality system evaluation with real-time and best-effort VMs. Open-source."
        },
        "concepts": ["KVM (Kernel-based Virtual Machine)", "Control Groups (cgroups v2)"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "Memory bandwidth reservation missing at hypervisor level",
             "description": "Cache coloring is implemented in hypervisors, but memory bandwidth reservation exists only at the Linux kernel level. Mixed-criticality systems running different guest OSes in VMs need hypervisor-level bandwidth isolation that is OS-agnostic."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "VM-centric hypervisor memory bandwidth reservation",
             "description": "H-MBR provides per-VM memory bandwidth reservation at the hypervisor level, independent of guest OS. Works for Linux, RTOS, and bare-metal guests. Open-source with no overhead on non-regulated workloads."}
        ]
    },

    # ── 3. Intel ICE Driver Security Audit ──────────────────────────
    {
        "ev_id": "ev-arxiv-bea9cf52",
        "brief": {
            "key_ideas": [
                "Comprehensive security audit of the Intel ICE driver (E810 NIC) using static analysis, fuzz testing, and timing-based side-channel evaluation",
                "Static analysis reveals insufficient bounds checking and unsafe string operations that may introduce security flaws in the kernel driver",
                "Fuzz testing of Admin Queue, debugfs, and VF management confirms strong input validation under normal conditions but discovers timing-based side-channel vulnerability using KernelSnitch principles",
                "Timing side channel: execution time discrepancies in hash table lookups allow unprivileged attackers to infer VF occupancy states, enabling network mapping in multi-tenant environments. Also confirms RCU synchronization issues (stale data, memory leaks, OOM)"
            ],
            "relevance": "A concrete security audit of a production Linux kernel network driver. The ICE driver is one of the most widely deployed NIC drivers in data center environments (Intel E810 is ubiquitous). The findings — timing side channels in hash table lookups, RCU synchronization gaps leading to OOM, insufficient bounds checking — are representative of vulnerabilities in high-complexity kernel drivers. This complements the RCU synchronization paper (batch 004) with additional evidence from the same driver. The KernelSnitch-based timing analysis methodology is applicable to auditing other kernel drivers.",
            "methodology": "Static code analysis, fuzz testing (Admin Queue, debugfs, VF management), timing-based side-channel evaluation using KernelSnitch methodology. Kernel instrumentation for RCU verification."
        },
        "concepts": ["Read-Copy-Update", "Interrupt Handling"],
        "claims": [
            {"kind": "FailureMode", "id_prefix": "fail", "name": "Intel ICE driver timing side channel for VF occupancy inference",
             "description": "Execution time discrepancies in RCU hash table lookups in the Intel ICE driver allow unprivileged attackers to infer VF (Virtual Function) occupancy states. Enables network mapping in multi-tenant environments via timing side channel."},
            {"kind": "FailureMode", "id_prefix": "fail", "name": "ICE driver RCU gaps cause stale data and OOM",
             "description": "Missing RCU synchronization in the Intel ICE driver leads to stale data persistence, memory leaks, and out-of-memory conditions under rapid VF insert/delete workloads. Static analysis also reveals insufficient bounds checking."}
        ]
    },

    # ── 4. Ariadne: Hotness-Aware Compressed Swap ───────────────────
    {
        "ev_id": "ev-arxiv-de3f6b41",
        "brief": {
            "key_ideas": [
                "Three observations about Linux ZRAM compressed swap: (1) anonymous data has different hotness levels, with hot data being similar between consecutive relaunches, (2) small-size compression is fast while large-size gets better ratio, (3) there is locality in data access during relaunch",
                "Hotness-aware data organization identifies data temperature without significant overhead — organizes swap pages by hotness to enable differentiated treatment",
                "Size-adaptive compression uses different chunk sizes based on hotness: fast decompression for hot/warm data (small chunks), better ratio for cold data (large chunks)",
                "Proactive decompression predicts next-needed data and decompresses in advance. On Google Pixel 7: 50% faster app relaunch, 15% less CPU usage for compression/decompression"
            ],
            "relevance": "Directly modifies the Linux kernel's ZRAM compressed swap subsystem — one of the most performance-critical components on memory-constrained mobile devices. The three observations (hotness differentiation, size-adaptive compression, locality-based prefetch) are fundamental improvements to how the kernel manages compressed memory. This is relevant to the kernel's swap subsystem, zram driver, and memory reclaim path (kswapd). The Google Pixel 7 validation makes this immediately relevant to Android kernel development.",
            "methodology": "Linux kernel ZRAM modification. Hotness tracking, size-adaptive compression, proactive decompression. Evaluation on Google Pixel 7. Relaunch latency and CPU usage measurement."
        },
        "concepts": ["Zswap (Compressed Swap Cache)", "Page Reclaim (kswapd/direct)"],
        "claims": [
            {"kind": "Observation", "id_prefix": "obs", "name": "ZRAM anonymous data has exploitable hotness structure",
             "description": "Linux ZRAM treats all anonymous data equally, but hot data (used during relaunch) is similar across consecutive relaunches, small compression is fast, and relaunch access patterns have spatial locality. These properties enable differentiated swap management."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Hotness-aware size-adaptive ZRAM with proactive decompression",
             "description": "Ariadne organizes swap data by hotness, uses size-adaptive compression (fast small chunks for hot data, efficient large chunks for cold), and proactively decompresses predicted-next data. 50% faster relaunch, 15% less CPU on Pixel 7."}
        ]
    },

    # ── 5. SilentZNS: Zone Management for ZNS SSDs ─────────────────
    {
        "ev_id": "ev-arxiv-ef845965",
        "brief": {
            "key_ideas": [
                "Identifies four causes of hidden costs in ZNS SSD zone management: zone allocation granularity, zone geometry, write order, and zone mapping/management strategy — these affect device-level write amplification, wear, and host I/O interference",
                "SilentZNS: a flexible zone allocation scheme that allocates blocks to zones on the fly, departing from traditional logical-to-physical zone mapping — arbitrary block collections can be assigned to zones",
                "Guarantees wear-leveling and competitive read performance while substantially reducing device-level write amplification (92% less at 10% zone occupancy)",
                "Up to 12% less overall wear and up to 3.7x faster workload execution evaluated with key-value storage engines"
            ],
            "relevance": "Directly relevant to the kernel's block device layer and ZNS SSD support (blk-zoned). The kernel exposes ZNS zones to filesystems (btrfs, f2fs, XFS-zoned) but the hidden costs identified here — device-level write amplification from zone management — are invisible to the kernel's block layer abstraction. SilentZNS changes how the SSD controller manages zones, but the kernel's zone management API (zone append, zone reset) must be designed with these hidden costs in mind. The 92% DLWA reduction shows that naive zone management (which the kernel currently assumes) is extremely wasteful.",
            "methodology": "ConfZNS++ emulator implementation. Synthetic microbenchmarks and key-value storage engine evaluation. DLWA, wear, and performance analysis."
        },
        "concepts": ["Block Device Layer", "NVMe Driver Subsystem"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "ZNS SSD zone management has hidden write amplification costs",
             "description": "Existing ZNS controllers exhibit increased device-level write amplification (DLWA), increased wear, and increased interference with host I/O due to zone allocation granularity, geometry, write order, and mapping strategy — costs hidden from the host/kernel."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "On-the-fly zone allocation eliminating DLWA",
             "description": "SilentZNS allocates blocks to zones dynamically rather than using fixed logical-to-physical mapping. Guarantees wear-leveling with 92% less DLWA at 10% occupancy, 12% less wear, and 3.7x faster workload execution."}
        ]
    },

    # ── 6. CCxTrust: TEE+TPM Confidential Computing ────────────────
    {
        "ev_id": "ev-arxiv-e10c955f",
        "brief": {
            "key_ideas": [
                "Combines CPU-TEE black-box root of trust (AMD SEV-SNP) with TPM white-box root of trust for collaborative trust — addresses the limitation of relying on a single hardware RoT",
                "Independent Roots of Trust for Measurement (RTM) for both TEE and TPM, with a collaborative Root of Trust for Report (RTR) for composite attestation",
                "Confidential TPM supporting multiple modes for secure use within confidential VMs — enables TPM operations inside SEV-SNP protected guest VMs",
                "Prototype on AMD SEV-SNP server with TPM requiring minimal Linux kernel modifications. 24% improvement in composite attestation efficiency"
            ],
            "relevance": "Directly modifies the Linux kernel for AMD SEV-SNP + TPM integration. The kernel must manage both SEV-SNP's encrypted memory isolation and TPM's measurement chain simultaneously. The confidential TPM (vTPM inside SEV-SNP VM) requires kernel driver changes for TPM passthrough to confidential guests. The composite attestation protocol — combining hardware TEE and TPM measurements — extends the kernel's integrity measurement architecture (IMA) into the confidential computing domain. Minimal kernel modifications needed makes this practical for upstream.",
            "methodology": "AMD SEV-SNP + TPM prototype. Confidential TPM implementation. Composite attestation protocol with PCL security proof. Kernel modification analysis."
        },
        "concepts": ["KVM (Kernel-based Virtual Machine)", "Linux Security Modules"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "Single hardware root of trust insufficient for confidential computing",
             "description": "Relying on a single hardware RoT (CPU-TEE only) limits user confidence. TEE provides black-box isolation but lacks the flexible measurement and storage capabilities of TPM. Multi-cloud environments need cross-platform trust establishment."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "TEE+TPM collaborative roots of trust with composite attestation",
             "description": "CCxTrust combines AMD SEV-SNP (black-box RoT) with TPM (white-box RoT) for collaborative trust. Independent RTMs for each, collaborative RTR for composite attestation. Confidential TPM enables TPM inside SEV-SNP VMs. 24% faster attestation."}
        ]
    },

    # ── 7. CHRONOS: Multi-Timer RTOS Optimization ───────────────────
    {
        "ev_id": "ev-arxiv-a310c822",
        "brief": {
            "key_ideas": [
                "Exploits multiple hardware timers available in modern microcontrollers to reduce RTOS tick interrupt overhead — maps tasks to timers to maximize the GCD of task periods per timer, reducing interrupt frequency",
                "MIQCP optimization model minimizes the total number of tick interrupts while ensuring correct task release behavior",
                "Implemented in FreeRTOS — demonstrates significant reduction in tick interrupt overhead compared to single-timer baseline",
                "Applicable to any RTOS with periodic task models on MCUs with multiple hardware timers"
            ],
            "relevance": "While FreeRTOS-specific, the concept directly applies to the Linux kernel's timer subsystem and interrupt handling. Linux's hrtimer framework and tickless (NO_HZ) kernel address similar problems — reducing unnecessary timer interrupts. The GCD-based timer mapping optimization could inform the kernel's timer coalescing strategy (timer slack, deferrable timers). The MIQCP model for mapping tasks to timers is a formal approach to what the kernel's timer subsystem does heuristically. Relevant to real-time Linux (PREEMPT_RT) timer management.",
            "methodology": "MIQCP optimization model for task-to-timer mapping. FreeRTOS implementation. Embedded system evaluation. Interrupt count reduction measurement."
        },
        "concepts": ["Interrupt Handling", "Scheduling Classes"],
        "claims": [
            {"kind": "Proposal", "id_prefix": "prop", "name": "Multi-timer task mapping to minimize RTOS tick interrupts",
             "description": "CHRONOS maps tasks to multiple hardware timers using GCD-based period optimization (MIQCP model) to minimize total tick interrupts. Each timer's period is the GCD of its assigned tasks' periods, reducing interrupt frequency while maintaining correct task release."}
        ]
    },

    # ── 8. TPM+IMA Continuous Attestation for K8s ───────────────────
    {
        "ev_id": "ev-arxiv-de2ceac2",
        "brief": {
            "key_ideas": [
                "TPM 2.0-based continuous remote attestation for 5G VNFs running as containerized pods on Kubernetes — extends Linux IMA with a custom template for pod-level measurement isolation",
                "Addresses the gap in 5G security specs (3GPP TS 33.501) which lack runtime integrity validation — aligns with Zero Trust principles of 'never trust, always verify'",
                "Custom IMA template isolates measurements per-pod, enabling per-pod integrity verification instead of system-wide measurement conflation",
                "Integrates Keylime open-source framework with pod-aware IMA. Detects unauthorized modifications in real-time, labels pod trust state, generates audit logs"
            ],
            "relevance": "Directly extends the Linux kernel's Integrity Measurement Architecture (IMA) — the kernel's built-in integrity monitoring framework. The custom IMA template for per-pod measurement is a kernel-level modification that enables container-granularity integrity verification. IMA normally measures at the file/process level; extending it to Kubernetes pods requires understanding the kernel's namespace and cgroup boundaries to isolate measurements. The TPM integration uses the kernel's TPM driver and IMA-TPM interface. This is practical kernel security work with upstream relevance.",
            "methodology": "Linux IMA extension with custom pod-aware template. TPM 2.0 integration via Keylime. k3s cluster prototype (1 master, 2 workers). Real-time unauthorized modification detection."
        },
        "concepts": ["Linux Security Modules", "Namespaces", "Control Groups (cgroups v2)"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "5G security specs lack runtime integrity verification",
             "description": "3GPP TS 33.501 focuses on communication security but assumes network functions remain trustworthy after authentication. No mechanism continuously validates integrity of containerized 5G VNFs at runtime, violating Zero Trust principles."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Pod-aware Linux IMA with TPM continuous attestation",
             "description": "Custom IMA template isolates integrity measurements per Kubernetes pod. TPM 2.0 provides hardware-backed validation. Keylime integration for continuous remote attestation. Detects unauthorized modifications in real-time with per-pod trust labeling."}
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
