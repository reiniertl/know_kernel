"""Batch ingest arXiv papers into master.db (PoC manual ingestion).

Creates Source, Evidence, and ResearchBrief nodes for each paper.
Links to existing Concepts via keyword matching.
No API key needed — uses title-based inference for ResearchBriefs.
"""

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
    {
        "title": "Rethinking Polling Efficiency in Service Core Network Stacks",
        "url": "https://arxiv.org/abs/2607.16408",
        "abstract": "Examines how idle network service cores on modern multicore processors compete for shared power and thermal budgets. Proposes a budget-centric view where power becomes the fundamental resource rather than core occupancy.",
        "date": "2026-07-21",
        "source_type": "preprint",
        "venue": "arXiv cs.OS",
    },
    {
        "title": "SuperPass: Fast-Tracking Blocking Threads to Mitigate Priority Inversion on Mobile Devices",
        "url": "https://arxiv.org/abs/2607.18097",
        "abstract": "Addresses priority inversion on Android where high-priority UI threads get delayed by lower-priority ones. Introduces a lightweight kernel mechanism with a scheduler fast track granting immediate CPU access to threads blocking latency-critical threads, achieving 72% reduction in blocking duration.",
        "date": "2026-07-21",
        "source_type": "preprint",
        "venue": "arXiv cs.OS",
    },
    {
        "title": "Hardware-Transparent I/O Governance in Disaggregated Heterogeneous Storage",
        "url": "https://arxiv.org/abs/2607.16578",
        "abstract": "Presents the I/O Resource Manager (IORM) for managing shared storage clusters serving both latency-sensitive databases and block-volume workloads. Uses hardware-aware cost modeling, quantum-based rate limiting, and distributed adaptive feedback control.",
        "date": "2026-07-21",
        "source_type": "preprint",
        "venue": "arXiv cs.DC",
    },
    {
        "title": "Roomie: Interference-Aware Colocation for Efficient Model Serving",
        "url": "https://arxiv.org/abs/2607.16784",
        "abstract": "Develops a model serving system predicting kernel-level interference between colocated DNNs on GPUs. Employs occupancy-based analytical modeling and greedy placement algorithms to reduce SLO violations by up to 3x.",
        "date": "2026-07-21",
        "source_type": "preprint",
        "venue": "arXiv cs.OS",
    },
    {
        "title": "WAR: Workload-Aware Rollouts for Synchronous Agentic Reinforcement Learning",
        "url": "https://arxiv.org/abs/2607.17299",
        "abstract": "Accelerates synchronous agentic RL by jointly optimizing decoding and scheduling. Under low load, enables speculative decoding through suffix pattern reuse; under high load, shifts to cache-aware scheduling to reduce KV-cache recomputation.",
        "date": "2026-07-21",
        "source_type": "preprint",
        "venue": "arXiv cs.OS",
    },
    {
        "title": "Isolation Failure From Shared Storage: Characterizing and Exploiting Page-Cache SCA Leakage Across Containers and VMs",
        "url": "https://arxiv.org/abs/2607.17518",
        "abstract": "Demonstrates that page-cache timing side channels leak information across container and VM isolation boundaries when accessing host-backed filesystems. Shows unprivileged timing measurements can reveal page-cache residency across Docker, gVisor, Kata, and QEMU/KVM deployments.",
        "date": "2026-07-21",
        "source_type": "preprint",
        "venue": "arXiv cs.OS",
    },
    {
        "title": "TRIM: Reducing AI-Generated CodeSlop via Agent Trajectory Minimization",
        "url": "https://arxiv.org/abs/2607.18161",
        "abstract": "Defines CodeSlop as functionally unnecessary edits in AI-generated code from agent search processes. TRIM minimizes agent trajectories rather than code directly, reducing CodeSlop by 17.9%-32.9% with minimal performance impact.",
        "date": "2026-07-21",
        "source_type": "preprint",
        "venue": "arXiv cs.OS",
    },
    {
        "title": "Enabling Spatially Fine-Grained DVFS in Neural Processing Units for Energy-Efficient LLM Serving",
        "url": "https://arxiv.org/abs/2607.16473",
        "abstract": "Develops eNPU with hardware and software support for component-level dynamic voltage and frequency scaling on NPUs. Introduces cross-domain communication and compiler-driven optimization for instruction scheduling and V/f selection, achieving 25.8%-35.2% energy reduction.",
        "date": "2026-07-21",
        "source_type": "preprint",
        "venue": "arXiv cs.AR",
    },
    {
        "title": "Mitigating Compiler Fusion-Induced Power Bursts in Mobile NPU Inference as the Battery Depletes",
        "url": "https://arxiv.org/abs/2607.16555",
        "abstract": "Addresses voltage droop issues in mobile NPU inference through measurement-guided graph rewriting. Demonstrates how aggressive operator fusion creates power bursts that trigger dynamic voltage/frequency scaling.",
        "date": "2026-07-21",
        "source_type": "preprint",
        "venue": "arXiv cs.AR",
    },
    {
        "title": "SABLE: Minimalist Instruction-Level Authenticated Encryption for Constrained Confidential Computing",
        "url": "https://arxiv.org/abs/2607.16771",
        "abstract": "Presents RISC-V processor architecture enabling CPU-level instruction decryption and authentication using ASCON-128a. Explores seven micro-architectures with minimal invasiveness, maintaining RISC-V toolchain compatibility.",
        "date": "2026-07-21",
        "source_type": "preprint",
        "venue": "arXiv cs.AR",
    },
    {
        "title": "SEAM-V: A Hybrid-Decoupled RISC-V Vector Processor with Backend-Visible EP Context",
        "url": "https://arxiv.org/abs/2607.17899",
        "abstract": "Proposes hybrid-decoupled vector execution architecture for RISC-V Vector Extension through task-level decoupling and local instruction supply. Uses VLIW-style execute-packet packing, achieving 1.34x speedup.",
        "date": "2026-07-21",
        "source_type": "preprint",
        "venue": "arXiv cs.AR",
    },
    {
        "title": "Cold-Start Model Delivery in Kubernetes Inference Serving",
        "url": "https://arxiv.org/abs/2607.16596",
        "abstract": "Empirical study of OCI-based model artifact delivery in Kubernetes, comparing delivery paths including native image volumes (KEP-4639), storage initializer pulls, and object-storage downloads. Analyzes admission-time verification and integrity mechanisms.",
        "date": "2026-07-21",
        "source_type": "preprint",
        "venue": "arXiv cs.DC",
    },
    {
        "title": "uSTM: A Lightweight and Efficient STM Supporting General Types and Deferred Aborts",
        "url": "https://arxiv.org/abs/2607.18178",
        "abstract": "Software transactional memory system supporting general data types without layout restrictions. Implements deferred abort semantics to prevent space leaks with a novel split-increment timestamping algorithm for opacity guarantees.",
        "date": "2026-07-21",
        "source_type": "preprint",
        "venue": "arXiv cs.DC",
    },
    {
        "title": "Tempest: A GPU-Accelerated Engine for Streaming Temporal Random Walks",
        "url": "https://arxiv.org/abs/2605.16182",
        "abstract": "GPU-accelerated streaming engine with hierarchical cooperative scheduling for temporal graph traversal. Features dual-index organization, warp/block-level dispatch granularity, and window-based eviction.",
        "date": "2026-05-21",
        "source_type": "preprint",
        "venue": "arXiv cs.DC",
    },
    {
        "title": "Fuzz'EMup: Leveraging EM Side-Channel Emanation to Guide Black-Box Embedded Firmware Fuzzing",
        "url": "https://arxiv.org/abs/2607.16487",
        "abstract": "Firmware fuzzing approach using electromagnetic side-channel signals to guide exploration in black-box embedded systems where instrumentation is infeasible. Uses signal processing and dynamic time-warping alignment.",
        "date": "2026-07-21",
        "source_type": "preprint",
        "venue": "arXiv cs.CR",
    },
    {
        "title": "Self-State Attacks on Self-Hosted AI Agents: How Far Can OS Defenses Go?",
        "url": "https://arxiv.org/abs/2607.17986",
        "abstract": "Investigates OS-level resilience against attacks corrupting agent memory and configuration via legitimate system calls. Evaluates layered defense strategies including access-control prevention, workload-conditioned detection, and recovery mechanisms.",
        "date": "2026-07-21",
        "source_type": "preprint",
        "venue": "arXiv cs.CR",
    },
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
            print(f"  SKIP (exists): {paper['title'][:60]}")
            skipped += 1
            continue

        source_id = f"src-arxiv-{uuid.uuid4().hex[:8]}"
        evidence_id = f"ev-arxiv-{uuid.uuid4().hex[:8]}"
        brief_id = f"rb-{uuid.uuid4().hex[:12]}"

        add_node(conn, source_id, "Source", {
            "url": paper["url"],
            "title": paper["title"],
            "source_type": paper["source_type"],
            "license": "arXiv",
            "published_date": paper["date"],
            "venue": paper["venue"],
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

        concept_str = ", ".join(concept_names[:3]) if concept_names else "no concept match"
        print(f"  ADD: {paper['title'][:55]}... -> {concept_str}")
        created += 1

    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()

    print(f"\n=== Summary ===")
    print(f"Created: {created}")
    print(f"Skipped: {skipped}")
    print(f"Total papers in batch: {len(PAPERS)}")


if __name__ == "__main__":
    main()
