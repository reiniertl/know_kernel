"""Deep enrichment batch 016: 15 conference papers — EuroSys, CCS, ASPLOS continued.
Newly available via OpenAlex abstracts.
"""
import json, sqlite3, uuid

DB_PATH = "data/master.db"

ALL_PAPERS = [
    # ── 1. Reload+Reload: AMD SEV Cache Side Channels ──────────────
    {"ev_id": "ev-conf-6e511b94", "brief": {
        "key_ideas": ["Discovers two previously unknown side channels in AMD SEV processors: cache flush and memory contention side channels", "Applies to SEV-SNP and earlier versions — the strongest confidential VM protection is still vulnerable", "Formulates two Reload+Reload attacks based on cache flush timing and memory contention timing differences", "Demonstrates that hardware memory encryption (SEV) does not prevent timing-based information leakage through shared microarchitectural state"],
        "relevance": "Directly attacks AMD SEV — the kernel manages SEV VMs through KVM. The cache flush side channel exploits how the kernel's KVM switches between SEV-protected VMs sharing cache lines. Memory contention exploits shared memory controller resources. This motivates kernel-level mitigations: cache line flushing on VM switches, memory controller partitioning. Relevant to the kernel's KVM SEV implementation and the resctrl cache allocation interface.",
        "methodology": "ASPLOS. Side channel discovery in AMD SEV/SEV-ES/SEV-SNP. Cache flush and memory contention timing analysis. Reload+Reload attack construction."
    }, "concepts": ["KVM (Kernel-based Virtual Machine)"], "claims": [
        {"kind": "FailureMode", "id_prefix": "fail", "name": "AMD SEV-SNP vulnerable to cache flush and memory contention side channels", "description": "Two previously unknown side channels in AMD SEV processors: cache flush timing and memory contention timing. Both apply to SEV-SNP. Reload+Reload attacks exploit shared microarchitectural state that hardware memory encryption does not protect."}
    ]},

    # ── 2. Core-Gapped Confidential VMs ────────────────────────────
    {"ev_id": "ev-conf-2c6c03e3", "brief": {
        "key_ideas": ["Identifies the root cause of transient-execution attacks against confidential VMs: multiplexing CPU cores among distrusting entities with untrusted hypervisor controlling the multiplexing", "Proposes core-gapping: never time-share a physical core between confidential VMs, eliminating transient-execution side channels by construction", "Applies to Intel TDX, AMD SEV, and Arm CCA — all share the core-multiplexing vulnerability", "Trades some CPU utilization for fundamental elimination of transient-execution attack classes"],
        "relevance": "Proposes that the kernel's KVM scheduler should never schedule different confidential VMs on the same physical core. This is a scheduling constraint the kernel must enforce — today KVM freely migrates vCPUs between cores. Core-gapping requires changes to the kernel's CPU isolation (cpuset cgroups), KVM vCPU scheduling, and NUMA affinity. The tradeoff (utilization vs security) is a kernel scheduling policy decision.",
        "methodology": "ASPLOS. Analysis of transient-execution attacks across TDX/SEV/CCA. Core-gapping design. Security and utilization tradeoff evaluation."
    }, "concepts": ["KVM (Kernel-based Virtual Machine)", "Scheduling Classes"], "claims": [
        {"kind": "Proposal", "id_prefix": "prop", "name": "Core-gapping to eliminate transient-execution attacks on CVMs", "description": "Never time-share a physical core between confidential VMs, eliminating transient-execution side channels by construction. Applies to Intel TDX, AMD SEV, Arm CCA. Trades CPU utilization for fundamental security guarantee."}
    ]},

    # ── 3. Verified Rust Page Tables for Enclave Hypervisor ────────
    {"ev_id": "ev-conf-1c60654c", "brief": {
        "key_ideas": ["Formally verifies Rust implementation of page tables in a software enclave hypervisor — proving spatial isolation properties", "Even memory-safe Rust cannot guarantee correct page table semantics — formal verification needed for isolation proofs", "Targets TEE hypervisors where page table correctness is the foundation of spatial isolation between enclaves", "Demonstrates that Rust + formal verification is practical for critical kernel-level code"],
        "relevance": "Directly relevant to the kernel's page table management and Rust-in-kernel efforts. The kernel is incrementally adopting Rust — this paper shows that even Rust's memory safety guarantees are insufficient for page table correctness (which requires semantic properties like isolation, not just memory safety). The verification methodology could be applied to the Linux kernel's own page table code or to KVM's nested page table management.",
        "methodology": "ASPLOS. Formal verification of Rust page table implementation. Spatial isolation proof. Software enclave hypervisor context."
    }, "concepts": ["Hierarchical Page Tables", "Linux Security Modules"], "claims": [
        {"kind": "Observation", "id_prefix": "obs", "name": "Rust memory safety insufficient for page table correctness", "description": "Even Rust's memory safety guarantees cannot ensure correct page table semantics — spatial isolation requires formal verification of semantic properties (correct mapping, no aliasing) beyond what the type system provides."},
        {"kind": "Proposal", "id_prefix": "prop", "name": "Formal verification of Rust page tables for TEE isolation", "description": "Verifies Rust page table implementation to prove spatial isolation properties in a software enclave hypervisor. Demonstrates Rust + formal verification is practical for critical kernel-level code."}
    ]},

    # ── 4. KASLR is Dead (Formally) ───────────────────────────────
    {"ev_id": "ev-conf-c70809c2", "brief": {
        "key_ideas": ["Formally demonstrates that KASLR (Kernel Address Space Layout Randomization) is dead in the Spectre era", "Relaxes the assumptions from Abadi et al.'s formal proof of ASLR security to match real kernel behavior — shows the proof breaks under Spectre", "Kernel ASLR operates on a different memory model (separate memory with syscall communication) than the shared-memory model originally analyzed", "Provides formal proof that transient-execution attacks fundamentally undermine kernel address randomization"],
        "relevance": "Directly relevant to the Linux kernel's KASLR implementation. KASLR is the kernel's primary defense against code-reuse attacks — this paper formally proves it provides no security guarantees under Spectre. The kernel currently invests significant effort in KASLR (randomizing kernel text, module, and data addresses) — this paper argues those efforts are wasted against Spectre-capable attackers. Published at CCS, the premier security venue.",
        "methodology": "CCS. Formal security analysis of kernel ASLR. Relaxation of Abadi et al.'s ASLR security model. Spectre-era threat model."
    }, "concepts": ["Linux Security Modules"], "claims": [
        {"kind": "FailureMode", "id_prefix": "fail", "name": "KASLR formally proven insecure under Spectre", "description": "Formal analysis proves that kernel ASLR provides no security guarantees against Spectre-capable attackers. The original ASLR security proof (Abadi et al.) assumes a shared-memory model; the kernel's separate-memory + syscall model breaks under transient execution."}
    ]},

    # ── 5. SyzSpec: Kernel Fuzzer Specification Generation ─────────
    {"ev_id": "ev-conf-5ec56768", "brief": {
        "key_ideas": ["Uses under-constrained symbolic execution to automatically generate syzkaller specifications for Linux kernel fuzzing", "syzkaller has found 6,800+ kernel bugs but relies on manually-written specifications — this automates the bottleneck", "Generates specifications that capture syscall argument constraints, data dependencies, and resource management patterns", "Complements KernelGPT (LLM-based spec synthesis) with a symbolic execution approach"],
        "relevance": "Directly improves the syzkaller kernel fuzzing ecosystem — the most productive kernel bug-finding tool. Where KernelGPT (batch 009) uses LLMs to synthesize specs, SyzSpec uses symbolic execution — a complementary approach. The under-constrained symbolic execution runs on kernel code to discover valid syscall argument constraints automatically. Published at CCS. Together with KernelGPT and Snowplow, this completes the trilogy of automated kernel fuzzing improvement approaches.",
        "methodology": "CCS. Under-constrained symbolic execution on Linux kernel code. Automatic syzkaller specification generation. Kernel bug discovery evaluation."
    }, "concepts": [], "claims": [
        {"kind": "Proposal", "id_prefix": "prop", "name": "Symbolic execution for automatic kernel fuzzer spec generation", "description": "SyzSpec uses under-constrained symbolic execution to automatically generate syzkaller specifications, capturing syscall constraints and data dependencies. Complements LLM-based (KernelGPT) and learned-mutation (Snowplow) approaches."}
    ]},

    # ── 6. Hardware-Software Co-Design for Secure Containers ───────
    {"ev_id": "ev-conf-0909de03", "brief": {
        "key_ideas": ["VM-level containers provide strong isolation but rely on virtualization hardware designed for general-purpose VMs, causing non-negligible overhead", "Performance gap widens dramatically in nested virtualization where secure containers run inside a VM", "Co-designs hardware and software to reduce secure container overhead without weakening isolation", "Targets the specific performance bottlenecks of VM-based containers rather than general VM optimization"],
        "relevance": "Complements ParaCell (batch 005) and Edera (batch 011) in the secure container optimization space. While ParaCell uses MPK and Edera uses a custom hypervisor, this paper co-designs hardware extensions specifically for secure containers. Relevant to the kernel's KVM implementation for Kata Containers and the nested virtualization path. The nested virtualization performance focus is particularly relevant — many cloud environments require nested VM support.",
        "methodology": "EuroSys. Hardware-software co-design for secure containers. Nested virtualization optimization. Performance comparison against standard VM-level containers."
    }, "concepts": ["KVM (Kernel-based Virtual Machine)", "Namespaces", "Control Groups (cgroups v2)"], "claims": [
        {"kind": "Proposal", "id_prefix": "prop", "name": "Hardware-software co-designed efficient secure containers", "description": "Co-designs hardware and software to reduce VM-level container overhead, especially in nested virtualization scenarios. Targets specific secure container bottlenecks rather than general VM optimization."}
    ]},

    # ── 7. Chrono: Memory Tiering Hotness Measurement ──────────────
    {"ev_id": "ev-conf-b812f31b", "brief": {
        "key_ideas": ["Meticulous hotness measurement for memory tiering — accurately tracks page access frequency and recency for heterogeneous memory", "Flexible page migration policies that adapt to changing workload access patterns", "Addresses the fundamental challenge of tiered memory: accurately classifying pages as hot or cold determines tiering effectiveness", "Evaluation on tiered memory systems with multiple workload types"],
        "relevance": "Directly relevant to the kernel's memory tiering subsystem. The kernel's current hotness detection (NUMA hinting faults via AutoNUMA, DAMON's region-based sampling) has known limitations. Chrono provides more accurate hotness measurement that could inform kernel tiering policy. Complements HybridTier (frequency+momentum) from batch 004 with a different measurement approach. Published at EuroSys 2025.",
        "methodology": "EuroSys 2025. Hotness measurement for tiered memory. Flexible page migration. Multi-workload evaluation."
    }, "concepts": ["NUMA Topology and Memory Policy", "Adaptive CXL Memory Tiering", "Page Reclaim (kswapd/direct)"], "claims": [
        {"kind": "Proposal", "id_prefix": "prop", "name": "Meticulous hotness measurement for accurate memory tiering", "description": "Chrono provides accurate page hotness tracking (frequency + recency) with flexible migration policies for heterogeneous memory. Addresses the classification accuracy that determines tiering effectiveness."}
    ]},

    # ── 8. Daredevil: Rescue Flash from Inflexible Kernel Storage ──
    {"ev_id": "ev-conf-0b330f94", "brief": {
        "key_ideas": ["Existing kernel storage stacks for NVMe SSDs struggle with performance interference between tenants with different SLAs — the multi-tenancy issue", "Static CPU core-NQ (NVMe Queue) bindings in current kernel storage stacks restrict flexibility for isolating tenant I/O", "Addresses the need to separate I/O requests from different tenants within NVMe queues while the kernel's static bindings prevent this", "Rescues flash storage performance by redesigning the kernel's NVMe queue management for multi-tenant isolation"],
        "relevance": "Directly targets the Linux kernel's NVMe driver and block I/O layer. The kernel's current NVMe implementation uses static CPU-to-queue mappings (blk-mq) that cannot provide per-tenant I/O isolation. Daredevil redesigns this mapping for multi-tenant SLA compliance. This is relevant to the kernel's blk-mq infrastructure, NVMe driver queue management, and cgroup I/O controllers (blk-throttle, BFQ).",
        "methodology": "EuroSys. NVMe queue management redesign for multi-tenant isolation. Performance interference analysis. SLA compliance evaluation."
    }, "concepts": ["NVMe Driver Subsystem", "Block Device Layer"], "claims": [
        {"kind": "Problem", "id_prefix": "prob", "name": "Kernel NVMe static queue bindings prevent tenant I/O isolation", "description": "The Linux kernel's static CPU core-to-NVMe queue bindings (blk-mq) restrict flexibility for separating I/O requests from tenants with different SLAs, causing performance interference in multi-tenant flash storage."},
        {"kind": "Proposal", "id_prefix": "prop", "name": "Flexible NVMe queue management for multi-tenant I/O isolation", "description": "Daredevil redesigns kernel NVMe queue management to separate tenant I/O within NVMe queues, rescuing flash storage performance from the inflexibility of static CPU-NQ bindings."}
    ]},

    # ── 9. Enoki: High-Velocity Linux Kernel Scheduler Development ─
    {"ev_id": "ev-conf-72c42ebf", "brief": {
        "key_ideas": ["Framework for rapid development of Linux kernel schedulers — addresses the slowness and difficulty of developing, testing, and debugging scheduling algorithms in Linux", "Enoki schedulers are written in safe high-level code rather than directly in kernel C", "Enables quick prototyping and comparison of scheduling policies — reducing the iteration cycle from weeks to hours", "Targets Linux, the most widely used cloud operating system, where scheduler development has historically been extremely slow"],
        "relevance": "Directly enables faster Linux kernel scheduler development. This is the development-tooling counterpart to sched_ext (which enables runtime-loadable schedulers). Where sched_ext provides the deployment mechanism (eBPF-based schedulers), Enoki provides the development framework (safe, high-level scheduler authoring). Together they transform kernel scheduler development from a years-long upstream process to rapid prototyping. Published at EuroSys.",
        "methodology": "EuroSys. Linux kernel scheduler development framework. Safe high-level scheduler authoring. Rapid prototyping and comparison."
    }, "concepts": ["Scheduling Classes", "sched_ext Extensible Scheduling"], "claims": [
        {"kind": "Problem", "id_prefix": "prob", "name": "Linux kernel scheduler development is slow and difficult", "description": "Developing, testing, and debugging new scheduling algorithms in the Linux kernel requires deep expertise and takes weeks to months. This prevents rapid innovation in scheduler design for evolving workloads."},
        {"kind": "Proposal", "id_prefix": "prop", "name": "High-velocity kernel scheduler development framework", "description": "Enoki enables rapid Linux kernel scheduler development with safe high-level code, reducing iteration from weeks to hours. Complements sched_ext's runtime deployment with a development-time framework."}
    ]},

    # ── 10. Erebor: Sandbox for Private Data in CVMs ───────────────
    {"ev_id": "ev-conf-06678d79", "brief": {
        "key_ideas": ["Confidential VMs fail to protect data in SaaS environments where the software stack within the CVM may intentionally disclose data to attackers", "Erebor: sandboxing architecture for private data processing within confidential VMs — isolates data from the service code running inside the CVM", "Addresses the overlooked threat model where the service provider's code inside the CVM is untrusted, not just the hypervisor", "Drop-in sandbox solution requiring no changes to the service application"],
        "relevance": "Extends the kernel's confidential computing model with in-CVM sandboxing. Current CVM security (TDX, SEV-SNP) protects against the hypervisor but trusts everything inside the VM — including the service code that processes private data. Erebor adds a second isolation layer inside the CVM. This requires kernel-level sandboxing mechanisms (seccomp, namespaces, or memory encryption) operating within the CVM's already-encrypted memory space.",
        "methodology": "EuroSys. In-CVM sandboxing architecture. SaaS private data protection. Drop-in solution evaluation."
    }, "concepts": ["KVM (Kernel-based Virtual Machine)", "Seccomp-BPF", "Namespaces"], "claims": [
        {"kind": "Problem", "id_prefix": "prob", "name": "CVMs trust service code that may disclose private data", "description": "Confidential VMs protect against untrusted hypervisors but trust all software inside the CVM. In SaaS settings, the service code within the CVM may intentionally disclose private data to attackers — a threat model CVMs don't address."},
        {"kind": "Proposal", "id_prefix": "prop", "name": "In-CVM sandboxing for private data isolation", "description": "Erebor provides a drop-in sandbox within confidential VMs that isolates private data from service code. Adds a second isolation layer inside the CVM's encrypted memory space."}
    ]},

    # ── 11. M5: CXL Page Migration and Memory Management ──────────
    {"ev_id": "ev-asplos25-m5", "brief": {
        "key_ideas": ["Addresses effective and efficient page migration for CXL-based tiered memory where CXL DRAM has 2-3x longer access latency than DDR DRAM", "Mastering page migration — goes beyond just detecting hot pages to optimize the migration process itself (when, what, how to migrate)", "Proposes improvements to the kernel's page migration machinery for CXL tiering", "Evaluated on real CXL hardware for practical applicability"],
        "relevance": "Directly targets the Linux kernel's page migration subsystem for CXL. The kernel's migrate_pages() and move_pages() infrastructure was designed for NUMA balancing — M5 adapts it for CXL's different latency characteristics. Published at ASPLOS 2025 — one of the latest CXL memory management papers with real hardware evaluation. Complements HybridTier (hotness detection) and TierBPF (admission control) with migration machinery optimization.",
        "methodology": "ASPLOS 2025. CXL page migration optimization. Real CXL hardware evaluation. Memory management for tiered systems."
    }, "concepts": ["Adaptive CXL Memory Tiering", "NUMA Topology and Memory Policy", "Page Fault Handler"], "claims": [
        {"kind": "Proposal", "id_prefix": "prop", "name": "Optimized page migration machinery for CXL tiered memory", "description": "M5 masters page migration for CXL-based tiering: optimizes when, what, and how to migrate pages between DDR and CXL DRAM (2-3x latency gap). Goes beyond hotness detection to optimize the migration process itself."}
    ]},

    # ── 12. HyperAlloc: VM Memory De/Inflation ────────────────────
    {"ev_id": "ev-conf-61e330ff", "brief": {
        "key_ideas": ["Efficient VM memory inflation and deflation via hypervisor-shared page-frame allocators — addresses volatile memory demands of VM workloads", "Memory hotplugging and ballooning are established but have limitations — HyperAlloc provides a faster, more efficient alternative", "Hypervisor and guest share page-frame allocation state, enabling direct memory management without costly hypercalls", "Targets Linux/KVM where memory overprovisioning is a major cost driver"],
        "relevance": "Directly modifies the Linux kernel's KVM memory management and the guest kernel's page allocator. The hypervisor-shared allocator bypasses the virtio-balloon protocol's overhead by letting the hypervisor directly manage guest page frames. This requires changes to both the host kernel (KVM) and guest kernel (buddy allocator awareness of shared state). Relevant to the kernel's balloon driver, memory hotplug, and KVM's memory management.",
        "methodology": "EuroSys. Hypervisor-shared page-frame allocator. Linux/KVM implementation. VM memory inflation/deflation evaluation."
    }, "concepts": ["KVM (Kernel-based Virtual Machine)", "Memory Ballooning", "Buddy Allocator"], "claims": [
        {"kind": "Proposal", "id_prefix": "prop", "name": "Hypervisor-shared page-frame allocator for fast VM memory management", "description": "HyperAlloc enables efficient VM memory inflation/deflation by sharing page-frame allocation state between hypervisor and guest, bypassing virtio-balloon overhead. Faster and more efficient than memory hotplugging or ballooning on Linux/KVM."}
    ]},

    # ── 13. eBPF Verifier Correctness Bugs ─────────────────────────
    {"ev_id": "ev-conf-62a2ea8f", "brief": {
        "key_ideas": ["Finds correctness bugs in the eBPF verifier using structured and sanitized programs", "The verifier's correctness is paramount — attackers exploit verifier bugs to execute unsafe programs in kernel space", "Generates programs that are structured to trigger verifier edge cases while being sanitized to avoid crashes during testing", "Targets the gap between what the verifier accepts and what is actually safe"],
        "relevance": "Directly targets the Linux kernel's eBPF verifier — the most security-critical component of the eBPF subsystem. Every eBPF program must pass the verifier; a verifier bug means an attacker can load malicious code into the kernel. This complements Heimdall (verifier-accepted bugs at source level) and VeriFence (Spectre defense precision) by finding bugs in the verifier itself. Published at EuroSys.",
        "methodology": "EuroSys. Structured program generation for eBPF verifier testing. Sanitized programs to avoid test infrastructure crashes. Verifier correctness bug discovery."
    }, "concepts": ["eBPF (Extended Berkeley Packet Filter)", "Linux Security Modules"], "claims": [
        {"kind": "FailureMode", "id_prefix": "fail", "name": "eBPF verifier correctness bugs allow unsafe kernel programs", "description": "The eBPF verifier can incorrectly accept programs that violate safety properties. Structured, sanitized test programs trigger verifier edge cases, discovering bugs that could allow attackers to execute unsafe code in kernel space."}
    ]},

    # ── 14. FastIOV: SR-IOV Startup for Secure Containers ─────────
    {"ev_id": "ev-conf-ea2040a1", "brief": {
        "key_ideas": ["SR-IOV satisfies network requirements for traditional containers but falls short with secure containers which have become mainstream in multi-tenant clouds", "Secure containers (VM-based) require additional VFIO/IOMMU setup for SR-IOV passthrough, slowing startup dramatically", "Optimizes the startup path for SR-IOV network passthrough in secure containers", "Addresses the gap between SR-IOV's fast-path data plane and its slow control-plane initialization for VMs"],
        "relevance": "Directly targets the Linux kernel's VFIO and IOMMU initialization for SR-IOV passthrough in KVM-based secure containers. The kernel's VFIO setup (device binding, IOMMU group configuration, interrupt setup) is the bottleneck for secure container cold start. This complements Vmem (batch 009, 3x faster VFIO boot at Alibaba) with a focused optimization of the SR-IOV passthrough path. Relevant to the kernel's vfio-pci driver and IOMMU subsystem.",
        "methodology": "EuroSys. SR-IOV passthrough optimization for secure containers. VFIO/IOMMU startup path analysis. Fast startup evaluation."
    }, "concepts": ["VFIO (Virtual Function I/O)", "KVM (Kernel-based Virtual Machine)"], "claims": [
        {"kind": "Problem", "id_prefix": "prob", "name": "SR-IOV startup too slow for secure container cold start", "description": "SR-IOV network passthrough requires VFIO/IOMMU setup for secure (VM-based) containers, dramatically slowing startup compared to traditional containers. The control-plane initialization bottleneck limits secure container density."},
        {"kind": "Proposal", "id_prefix": "prop", "name": "Optimized SR-IOV passthrough startup for secure containers", "description": "FastIOV optimizes the VFIO/IOMMU setup path for SR-IOV network passthrough in VM-based secure containers, enabling fast startup without sacrificing isolation or data-plane performance."}
    ]},

    # ── 15. CXL Memory Performance and Cost with ASIC ──────────────
    {"ev_id": "ev-conf-9ed22992", "brief": {
        "key_ideas": ["Explores application performance of ASIC CXL memory in various datacenter scenarios — real ASIC-based CXL device evaluation", "Examines performance and cost optimization opportunities with CXL memory for production workloads", "CXL has risen as a promising interconnect for high-speed, low-latency communication between processors and peripherals", "Provides practical data for CXL deployment decisions in datacenters"],
        "relevance": "Real ASIC CXL hardware evaluation — complements Melody's multi-device characterization (batch 015) with ASIC-specific (non-FPGA) performance data. The kernel's CXL tiering policies need real hardware characterization to be tuned correctly — FPGA emulation and simulation have different performance profiles than production ASIC devices. Published at EuroSys 2025.",
        "methodology": "EuroSys 2025. ASIC CXL memory evaluation. Multiple datacenter workloads. Performance and cost analysis."
    }, "concepts": ["Adaptive CXL Memory Tiering", "NUMA Topology and Memory Policy"], "claims": [
        {"kind": "Observation", "id_prefix": "obs", "name": "ASIC CXL memory performance differs from FPGA/emulation", "description": "ASIC-based CXL memory evaluation across datacenter workloads provides practical deployment data. Performance and cost characteristics differ from FPGA-emulated or simulated CXL, informing real-world kernel tiering policy decisions."}
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
