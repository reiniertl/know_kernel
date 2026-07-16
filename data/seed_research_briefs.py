"""Seed ResearchBrief nodes from paper titles (PoC data, no LLM needed).

Generates plausible key_ideas, relevance, and methodology from paper
titles and linked concept names. For PoC demonstration only.
"""

import json
import re
import sqlite3
import sys
import uuid

sys.path.insert(0, "src")

DB_PATH = "data/master.db"

_METHODOLOGY_KEYWORDS = {
    "ebpf": "eBPF-based instrumentation",
    "bpf": "eBPF-based instrumentation",
    "formal": "formal verification",
    "verification": "formal verification",
    "proof": "formal verification",
    "simulation": "hardware simulation",
    "benchmark": "performance benchmarking",
    "profil": "workload profiling",
    "characteriz": "workload characterization",
    "trace": "kernel tracing",
    "static analysis": "static analysis",
    "machine learning": "ML-based optimization",
    "llm": "LLM-assisted analysis",
    "neural": "ML-based optimization",
    "deep learning": "ML-based optimization",
    "reinforcement": "reinforcement learning",
    "model check": "model checking",
    "testing": "systematic testing",
    "fuzzing": "fuzz testing",
    "fuzz": "fuzz testing",
    "deterministic": "deterministic testing",
    "hardware": "hardware-software co-design",
    "fpga": "FPGA prototyping",
    "gpu": "GPU-accelerated computing",
    "cxl": "CXL memory architecture",
    "disaggregat": "disaggregated memory architecture",
    "serverless": "serverless systems design",
    "container": "container orchestration",
    "virtuali": "virtualization techniques",
    "compiler": "compiler optimization",
    "scheduling": "scheduling algorithm design",
    "scheduler": "scheduling algorithm design",
    "file system": "filesystem design",
    "filesystem": "filesystem design",
    "storage": "storage system design",
    "network": "network stack optimization",
    "security": "security mechanism design",
    "isolation": "isolation architecture",
    "memory": "memory management design",
    "allocat": "memory allocation optimization",
    "io": "I/O subsystem optimization",
    "concurren": "concurrency control design",
    "lock": "lock protocol analysis",
    "scalab": "scalability analysis",
    "framework": "systems framework design",
    "agent": "agentic systems architecture",
    "policy": "policy enforcement mechanism",
    "log": "logging/recovery design",
    "crash": "crash consistency analysis",
    "recover": "recovery mechanism design",
    "encrypt": "cryptographic systems design",
    "access control": "access control design",
}

_SUBSYSTEM_RELEVANCE = {
    "memory management": "memory allocator, page fault handler, and NUMA-aware allocation subsystems",
    "scheduling": "CFS scheduler, scheduling classes, and CPU load balancing",
    "synchronization": "spinlock, RCU, and futex synchronization primitives",
    "bpf": "eBPF verifier, JIT compiler, and BPF program management",
    "networking": "TCP/IP stack, network namespaces, and netfilter",
    "file systems": "VFS layer, ext4 journaling, and block I/O scheduler",
    "security": "Linux Security Modules, kernel crypto API, and access control",
    "virtualization": "KVM hypervisor, memory ballooning, and device passthrough",
    "storage stack": "block I/O scheduler, device mapper, and NVMe driver",
    "device drivers": "device model, DMA engine, and driver framework",
    "tracing": "ftrace infrastructure, perf events, and tracepoints",
    "ipc": "pipe buffer, epoll, and System V IPC mechanisms",
    "power management": "cpufreq governor framework and idle state management",
    "uncategorized": "general kernel infrastructure and cross-subsystem interfaces",
}


def infer_methodology(title_lower: str) -> str:
    for keyword, method in _METHODOLOGY_KEYWORDS.items():
        if keyword in title_lower:
            return method
    return "systems design and evaluation"


def infer_relevance(title: str, concept_names: list[str], subsystem_names: list[str]) -> str:
    sub = subsystem_names[0].lower() if subsystem_names else "general kernel"
    sub_detail = _SUBSYSTEM_RELEVANCE.get(sub, _SUBSYSTEM_RELEVANCE["uncategorized"])

    if concept_names:
        concepts_str = ", ".join(concept_names[:3])
        return (
            f"Directly relevant to {concepts_str} in the Linux kernel. "
            f"Impacts {sub_detail}."
        )
    return f"Relevant to {sub_detail} in the Linux kernel."


def infer_key_ideas(title: str) -> list[str]:
    ideas = []

    title_clean = re.sub(r":\s+", ": ", title)
    if ":" in title_clean:
        parts = title_clean.split(":", 1)
        name = parts[0].strip()
        desc = parts[1].strip()
        ideas.append(f"Introduces {name} — {desc[:100]}")
    else:
        ideas.append(f"Proposes a novel approach: {title[:100]}")

    title_lower = title.lower()
    if any(w in title_lower for w in ("scalab", "scale", "scaling", "manycore")):
        ideas.append("Addresses scalability challenges in multi-core/distributed environments")
    if any(w in title_lower for w in ("latency", "performance", "fast", "efficient", "overhead")):
        ideas.append("Targets performance optimization with reduced overhead")
    if any(w in title_lower for w in ("security", "secure", "isolation", "protect", "sandbox")):
        ideas.append("Strengthens security boundaries and isolation guarantees")
    if any(w in title_lower for w in ("fault", "crash", "recover", "reliab", "deterministic")):
        ideas.append("Improves reliability through fault detection or recovery mechanisms")
    if any(w in title_lower for w in ("memory", "allocat", "page", "address", "numa")):
        ideas.append("Innovates on memory management or allocation strategies")
    if any(w in title_lower for w in ("schedule", "cpu", "thread", "preempt")):
        ideas.append("Advances CPU scheduling or thread management")
    if any(w in title_lower for w in ("io", "storage", "disk", "nvme", "ssd", "file")):
        ideas.append("Optimizes I/O or storage subsystem performance")
    if any(w in title_lower for w in ("network", "tcp", "rdma", "packet")):
        ideas.append("Enhances network stack efficiency or capabilities")

    return ideas[:3] if len(ideas) > 3 else ideas if ideas else [f"Investigates: {title[:80]}"]


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")

    papers = conn.execute("""
        SELECT DISTINCT s.id, json_extract(s.attrs, '$.title') as title,
               json_extract(s.attrs, '$.published_date') as pub_date,
               ev.id as ev_id
        FROM nodes s
        JOIN edges se ON se.kind = 'sourced-from' AND se.target_id = s.id
        JOIN nodes ev ON ev.id = se.source_id AND ev.kind = 'Evidence'
        WHERE s.kind = 'Source'
        AND json_extract(s.attrs, '$.source_type') IN
            ('paper','preprint','conference-paper','conference-proceedings')
        AND NOT EXISTS (
            SELECT 1 FROM nodes rb
            JOIN edges re ON re.kind = 'extracted-from'
                AND re.source_id = rb.id AND re.target_id = ev.id
            WHERE rb.kind = 'ResearchBrief'
        )
    """).fetchall()

    print(f"Papers without ResearchBrief: {len(papers)}")

    created = 0
    for source_id, title, pub_date, ev_id in papers:
        title = title or "(untitled)"
        pub_date = pub_date or "2026-01-01"
        title_lower = title.lower()

        concept_rows = conn.execute(
            "SELECT json_extract(c.attrs, '$.name') FROM nodes c "
            "JOIN edges ce ON ce.kind = 'extracted-from' AND ce.source_id = c.id "
            "AND ce.target_id = ? WHERE c.kind = 'Concept'",
            (ev_id,),
        ).fetchall()
        concept_names = [r[0] for r in concept_rows if r[0]]

        subsystem_rows = conn.execute(
            "SELECT DISTINCT json_extract(sub.attrs, '$.name') FROM nodes sub "
            "JOIN edges bt ON bt.kind = 'belongs-to' AND bt.target_id = sub.id "
            "JOIN nodes c ON c.id = bt.source_id AND c.kind = 'Concept' "
            "JOIN edges ce ON ce.kind = 'extracted-from' AND ce.source_id = c.id "
            "AND ce.target_id = ? WHERE sub.kind = 'Subsystem'",
            (ev_id,),
        ).fetchall()
        subsystem_names = [r[0] for r in subsystem_rows if r[0]]

        key_ideas = infer_key_ideas(title)
        relevance = infer_relevance(title, concept_names, subsystem_names)
        methodology = infer_methodology(title_lower)

        brief_id = f"rb-{uuid.uuid4().hex[:12]}"
        attrs = json.dumps({
            "title": title,
            "key_ideas": json.dumps(key_ideas),
            "relevance": relevance,
            "methodology": methodology,
            "source_date": pub_date,
            "artifact_class": "B",
        })

        conn.execute(
            "INSERT INTO nodes (id, kind, attrs) VALUES (?, 'ResearchBrief', ?)",
            (brief_id, attrs),
        )
        conn.execute(
            "INSERT INTO edges (kind, source_id, target_id, attrs) VALUES ('extracted-from', ?, ?, '{}')",
            (brief_id, ev_id),
        )

        for concept_name in concept_names:
            concept_id_row = conn.execute(
                "SELECT id FROM nodes WHERE kind = 'Concept' AND json_extract(attrs, '$.name') = ?",
                (concept_name,),
            ).fetchone()
            if concept_id_row:
                try:
                    conn.execute(
                        "INSERT INTO edges (kind, source_id, target_id, attrs) VALUES ('summarizes-for', ?, ?, '{}')",
                        (brief_id, concept_id_row[0]),
                    )
                except sqlite3.IntegrityError:
                    pass

        created += 1
        if created % 20 == 0:
            conn.commit()
            print(f"  ... {created}/{len(papers)}")

    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()

    print(f"\n=== Summary ===")
    print(f"Created: {created} ResearchBrief nodes")
    print(f"Total papers processed: {len(papers)}")


if __name__ == "__main__":
    main()
