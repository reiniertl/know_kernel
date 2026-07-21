"""Batch ingest arXiv cs.OS 2024 papers into master.db."""

import json
import sqlite3
import sys
import uuid

sys.path.insert(0, "src")
sys.path.insert(0, "data")

from graph.engine import add_edge, add_node
from repair_paper_links import get_good_concepts, match_paper_to_concepts
from seed_research_briefs import infer_key_ideas, infer_relevance, infer_methodology

DB_PATH = "data/master.db"

PAPERS = [
    {"title": "Characterizing Physical Memory Fragmentation", "url": "https://arxiv.org/abs/2401.03523", "date": "2024-01-07", "abstract": "Analyzes physical memory fragmentation patterns and characteristics in modern operating systems."},
    {"title": "When eBPF Meets Machine Learning: On-the-fly OS Kernel Compartmentalization", "url": "https://arxiv.org/abs/2401.05641", "date": "2024-01-11", "abstract": "Combines eBPF with ML for dynamic kernel isolation mechanisms, enabling on-the-fly compartmentalization of kernel subsystems."},
    {"title": "File System Aging", "url": "https://arxiv.org/abs/2401.08858", "date": "2024-01-17", "abstract": "Examines how file system performance degrades over time due to fragmentation, metadata growth, and structural decay."},
    {"title": "Herding LLaMaS: Using LLMs as an OS Module", "url": "https://arxiv.org/abs/2401.08908", "date": "2024-01-17", "abstract": "Proposes integrating large language models as operating system components for intelligent resource management."},
    {"title": "Nomad: Non-Exclusive Memory Tiering via Transactional Page Migration", "url": "https://arxiv.org/abs/2401.13154", "date": "2024-01-24", "abstract": "Implements shared memory tiering through transactional page movement across DRAM and CXL tiers."},
    {"title": "Characterizing Network Requirements for GPU API Remoting in AI Applications", "url": "https://arxiv.org/abs/2401.13354", "date": "2024-01-24", "abstract": "Identifies network specifications needed for remote GPU resource access in AI workloads."},
    {"title": "numaPTE: Managing Page-Tables and TLBs on NUMA Systems", "url": "https://arxiv.org/abs/2401.15558", "date": "2024-01-28", "abstract": "Optimizes page table and TLB management for NUMA architectures with topology-aware placement."},
    {"title": "A System-Level Dynamic Binary Translator using Automatically-Learned Translation Rules", "url": "https://arxiv.org/abs/2402.09688", "date": "2024-02-15", "abstract": "Creates system-level binary translation with machine-learned conversion patterns for cross-ISA execution."},
    {"title": "Next4: Snapshots in Ext4 File System", "url": "https://arxiv.org/abs/2403.06790", "date": "2024-03-11", "abstract": "Adds snapshot capabilities to the ext4 file system with minimal overhead via copy-on-write metadata."},
    {"title": "LLM as a System Service on Mobile Devices", "url": "https://arxiv.org/abs/2403.11805", "date": "2024-03-18", "abstract": "Integrates language models as core mobile OS services with shared inference and memory management."},
    {"title": "AIOS: LLM Agent Operating System", "url": "https://arxiv.org/abs/2403.16971", "date": "2024-03-25", "abstract": "Proposes operating system designed around LLM agent management with scheduling and resource isolation for agents."},
    {"title": "THEMIS: Time, Heterogeneity, and Energy Minded Scheduling for Fair Multi-Tenant Use in FPGAs", "url": "https://arxiv.org/abs/2404.00507", "date": "2024-04-01", "abstract": "Develops fair scheduling considering temporal, resource diversity, and power factors for FPGA multi-tenancy."},
    {"title": "Taming Server Memory TCO with Multiple Software-Defined Compressed Tiers", "url": "https://arxiv.org/abs/2404.13886", "date": "2024-04-22", "abstract": "Reduces total cost of ownership through tiered memory compression using software-defined tiers."},
    {"title": "uTNT: Unikernels for Efficient and Flexible Internet Probing", "url": "https://arxiv.org/abs/2405.04036", "date": "2024-05-07", "abstract": "Uses lightweight unikernels for network measurement with minimal attack surface and fast boot."},
    {"title": "Potential of WebAssembly for Embedded Systems", "url": "https://arxiv.org/abs/2405.09213", "date": "2024-05-15", "abstract": "Evaluates WebAssembly viability for resource-constrained embedded environments."},
    {"title": "SVFF: An Automated Framework for SR-IOV Virtual Function Management in FPGA Accelerated Virtualized Environments", "url": "https://arxiv.org/abs/2406.01225", "date": "2024-06-03", "abstract": "Automates virtual function provisioning for FPGA virtualization using SR-IOV."},
    {"title": "SquirrelFS: using the Rust compiler to check file-system crash consistency", "url": "https://arxiv.org/abs/2406.09649", "date": "2024-06-14", "abstract": "Employs Rust type system for verifying file system crash consistency at compile time."},
    {"title": "Simulation of high-performance memory allocators", "url": "https://arxiv.org/abs/2406.15776", "date": "2024-06-22", "abstract": "Models and evaluates performance characteristics of memory allocation strategies under various workloads."},
    {"title": "E-Mapper: Energy-Efficient Resource Allocation for Traditional Operating Systems on Heterogeneous Processors", "url": "https://arxiv.org/abs/2406.18980", "date": "2024-06-27", "abstract": "Manages heterogeneous processor resources to minimize energy consumption in general-purpose OSes."},
    {"title": "Accelerator-as-a-Service in Public Clouds: An Intra-Host Traffic Management View for Performance Isolation", "url": "https://arxiv.org/abs/2407.10098", "date": "2024-07-14", "abstract": "Ensures performance isolation for shared accelerator resources through intra-host traffic management."},
    {"title": "Boosting File Systems Elegantly: A Transparent NVM Write-ahead Log for Disk File Systems", "url": "https://arxiv.org/abs/2408.02911", "date": "2024-08-06", "abstract": "Enhances file system reliability using non-volatile memory write-ahead logging transparently."},
    {"title": "Crash Consistency in DRAM-NVM-Disk Hybrid Storage System", "url": "https://arxiv.org/abs/2408.04238", "date": "2024-08-08", "abstract": "Addresses consistency guarantees across multi-tier DRAM-NVM-disk storage hierarchies."},
    {"title": "Wasm-bpf: Streamlining eBPF Deployment in Cloud Environments with WebAssembly", "url": "https://arxiv.org/abs/2408.04856", "date": "2024-08-09", "abstract": "Simplifies eBPF program deployment via WebAssembly containerization for cloud environments."},
    {"title": "FRAP: A Flexible Resource Accessing Protocol for Multiprocessor Real-Time Systems", "url": "https://arxiv.org/abs/2408.13772", "date": "2024-08-25", "abstract": "Defines resource access protocol for temporal guarantees in multiprocessor real-time systems."},
    {"title": "Wave: Offloading Resource Management to SmartNIC Cores", "url": "https://arxiv.org/abs/2408.17351", "date": "2024-08-30", "abstract": "Delegates OS resource scheduling to SmartNIC processors for reduced host CPU overhead."},
    {"title": "Foreactor: Exploiting Storage I/O Parallelism with Explicit Speculation", "url": "https://arxiv.org/abs/2409.01580", "date": "2024-09-03", "abstract": "Increases storage throughput via speculative I/O request execution with explicit prediction."},
    {"title": "Head-First Memory Allocation on Best-Fit with Space-Fitting", "url": "https://arxiv.org/abs/2409.03488", "date": "2024-09-05", "abstract": "Proposes memory allocation strategy combining best-fit with spatial optimization for reduced fragmentation."},
    {"title": "Skip TLB flushes for reused pages within mmap's", "url": "https://arxiv.org/abs/2409.10946", "date": "2024-09-17", "abstract": "Reduces TLB invalidation overhead by skipping flushes for pages reused within the same mmap region."},
    {"title": "eBPF-mm: Userspace-guided memory management in Linux with eBPF", "url": "https://arxiv.org/abs/2409.11220", "date": "2024-09-17", "abstract": "Enables application-level memory policy customization via eBPF hooks in the Linux memory subsystem."},
    {"title": "Dissecting CXL Memory Performance at Scale: Analysis, Modeling, and Optimization", "url": "https://arxiv.org/abs/2409.14317", "date": "2024-09-22", "abstract": "Analyzes CXL interconnect memory technology performance characteristics at datacenter scale."},
    {"title": "The eBPF Runtime in the Linux Kernel", "url": "https://arxiv.org/abs/2410.00026", "date": "2024-10-01", "abstract": "Comprehensive description of the extended Berkeley Packet Filter runtime execution engine architecture in Linux."},
    {"title": "SJMalloc: the security-conscious, fast, thread-safe and memory-efficient heap allocator", "url": "https://arxiv.org/abs/2410.17928", "date": "2024-10-23", "abstract": "Develops heap allocator emphasizing protection against memory-based attacks while maintaining performance."},
    {"title": "xNVMe: Unleashing Storage Hardware-Software Co-design", "url": "https://arxiv.org/abs/2411.06980", "date": "2024-11-11", "abstract": "Presents interface for optimized storage hardware-software interaction across NVMe, io_uring, and SPDK."},
    {"title": "EDM: An Ultra-Low Latency Ethernet Fabric for Memory Disaggregation", "url": "https://arxiv.org/abs/2411.08300", "date": "2024-11-13", "abstract": "Designs high-performance Ethernet interconnect for distributed memory systems with microsecond latency."},
    {"title": "Squeezy: Rapid VM Memory Reclamation for Serverless Functions", "url": "https://arxiv.org/abs/2411.12893", "date": "2024-11-19", "abstract": "Quickly recovers virtual machine memory for serverless function invocations with sub-millisecond reclaim."},
    {"title": "Mercury: QoS-Aware Tiered Memory System", "url": "https://arxiv.org/abs/2412.08938", "date": "2024-12-12", "abstract": "Manages multi-level memory with quality-of-service guarantees for heterogeneous memory tiering."},
    {"title": "Optimizing System Memory Bandwidth with Micron CXL Memory Expansion Modules on Intel Xeon 6 Processors", "url": "https://arxiv.org/abs/2412.12491", "date": "2024-12-17", "abstract": "Improves memory bandwidth utilization through CXL memory expansion on latest Intel server processors."},
]


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")

    name_to_id = get_good_concepts(conn)
    existing_urls = set()
    for r in conn.execute("SELECT json_extract(attrs, '$.url') FROM nodes WHERE kind = 'Source'").fetchall():
        if r[0]:
            existing_urls.add(r[0].strip())

    created = 0
    skipped = 0

    for paper in PAPERS:
        if paper["url"] in existing_urls:
            print(f"  SKIP: {paper['title'][:55]}")
            skipped += 1
            continue

        source_id = f"src-arxiv-{uuid.uuid4().hex[:8]}"
        evidence_id = f"ev-arxiv-{uuid.uuid4().hex[:8]}"
        brief_id = f"rb-{uuid.uuid4().hex[:12]}"

        add_node(conn, source_id, "Source", {
            "url": paper["url"],
            "title": paper["title"],
            "source_type": "preprint",
            "license": "arXiv",
            "published_date": paper["date"],
            "venue": "arXiv cs.OS",
        })

        add_node(conn, evidence_id, "Evidence", {
            "artifact_class": "licensed-evidence",
            "contamination_level": "weak-copyleft",
            "description": paper["title"],
            "text": paper["abstract"],
        })

        add_edge(conn, "sourced-from", evidence_id, source_id)

        matches = match_paper_to_concepts(paper["title"], paper["abstract"], name_to_id)
        for concept_id in matches:
            existing = conn.execute(
                "SELECT 1 FROM edges WHERE kind = 'extracted-from' AND source_id = ? AND target_id = ?",
                (concept_id, evidence_id),
            ).fetchone()
            if not existing:
                add_edge(conn, "extracted-from", concept_id, evidence_id)

        concept_names = []
        for cid in matches:
            for n, i in name_to_id.items():
                if i == cid:
                    concept_names.append(n)
                    break

        subsystem_names = []
        for cid in matches:
            sub_rows = conn.execute(
                "SELECT json_extract(n.attrs, '$.name') FROM nodes n "
                "JOIN edges e ON e.target_id = n.id "
                "WHERE e.kind = 'belongs-to' AND e.source_id = ? AND n.kind = 'Subsystem'",
                (cid,),
            ).fetchall()
            for sr in sub_rows:
                if sr[0] and sr[0] not in subsystem_names:
                    subsystem_names.append(sr[0])

        key_ideas = infer_key_ideas(paper["title"])
        relevance = infer_relevance(paper["title"], concept_names, subsystem_names)
        methodology = infer_methodology(paper["title"].lower())

        add_node(conn, brief_id, "ResearchBrief", {
            "title": paper["title"],
            "key_ideas": json.dumps(key_ideas),
            "relevance": relevance,
            "methodology": methodology,
            "source_date": paper["date"],
            "artifact_class": "B",
        })

        add_edge(conn, "extracted-from", brief_id, evidence_id)
        for cid in matches:
            try:
                add_edge(conn, "summarizes-for", brief_id, cid)
            except Exception:
                pass

        concept_str = ", ".join(concept_names[:3]) if concept_names else "no match"
        print(f"  ADD: {paper['title'][:55]}... -> {concept_str}")
        created += 1

        if created % 20 == 0:
            conn.commit()

    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()

    print(f"\n=== Summary ===")
    print(f"Created: {created}")
    print(f"Skipped: {skipped}")
    print(f"Total in batch: {len(PAPERS)}")


if __name__ == "__main__":
    main()
