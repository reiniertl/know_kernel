"""Repair orphaned Source-Evidence chains after concept cleanup (ALG-KK-DATA-REPAIR-PAPER-LINKS).

Finds papers that lost their Concept link when bad Concept nodes were removed,
and reconnects them to good Concepts via keyword matching on title and description.
"""
import json
import re
import sqlite3
import sys

sys.path.insert(0, "src")

DB_PATH = "data/master.db"

_KERNEL_KEYWORDS = {
    "scheduler": ["virtual runtime scheduling", "scheduling classes", "scheduler load balancing"],
    "scheduling": ["virtual runtime scheduling", "scheduling classes", "scheduler load balancing"],
    "cpu": ["virtual runtime scheduling", "scheduling classes"],
    "memory": ["memory ballooning", "slab allocator", "huge page mapping"],
    "vm": ["memory ballooning", "hierarchical page tables", "page fault handler"],
    "page": ["hierarchical page tables", "page fault handler", "huge page mapping"],
    "tlb": ["translation lookaside buffer"],
    "rcu": ["read-copy-update"],
    "lock": ["spinlock", "reader-writer spinlock"],
    "spinlock": ["spinlock"],
    "mutex": ["mutex"],
    "cgroup": ["control groups (cgroups v2)"],
    "namespace": ["network namespaces"],
    "ebpf": ["ebpf verifier", "ebpf jit compilation"],
    "bpf": ["ebpf verifier", "ebpf jit compilation"],
    "network": ["network namespaces", "tcp congestion control"],
    "tcp": ["tcp congestion control"],
    "io": ["io_uring", "block i/o scheduler"],
    "io_uring": ["io_uring"],
    "filesystem": ["virtual filesystem switch (vfs)", "overlayfs (union mount)"],
    "vfs": ["virtual filesystem switch (vfs)"],
    "ext4": ["ext4 journaling"],
    "security": ["linux security modules", "kernel crypto api"],
    "crypto": ["kernel crypto api"],
    "lsm": ["linux security modules"],
    "selinux": ["linux security modules"],
    "driver": ["device mapper"],
    "device": ["device mapper"],
    "container": ["control groups (cgroups v2)", "network namespaces"],
    "virtualization": ["memory ballooning", "kvm hypervisor"],
    "kvm": ["kvm hypervisor"],
    "gpu": ["memory ballooning"],
    "rdma": ["memory ballooning"],
    "cxl": ["memory ballooning"],
    "numa": ["numa-aware allocation"],
    "slab": ["slab allocator"],
    "cache": ["slab allocator", "translation lookaside buffer"],
    "interrupt": ["irq-safe spinlock"],
    "irq": ["irq-safe spinlock"],
    "preempt": ["preemption control"],
    "futex": ["futex"],
    "swap": ["page fault handler"],
    "mmap": ["page fault handler"],
    "syscall": ["system call dispatch"],
    "signal": ["signal delivery"],
    "ipc": ["system v ipc"],
    "pipe": ["pipe buffer management"],
    "epoll": ["epoll event notification"],
    "netfilter": ["netfilter/nftables"],
    "iptables": ["netfilter/nftables"],
    "overlay": ["overlayfs (union mount)"],
    "workqueue": ["workqueue"],
    "rbtree": ["red-black tree runqueue"],
    "power": ["cpufreq governor framework"],
    "frequency": ["cpufreq governor framework"],
    "tracing": ["ftrace infrastructure"],
    "ftrace": ["ftrace infrastructure"],
    "perf": ["perf events subsystem"],
    "debug": ["ftrace infrastructure"],
    "module": ["kernel module loader"],
    "dma": ["dma engine framework"],
    "block": ["block i/o scheduler"],
    "dm": ["device mapper"],
    "verification": ["ebpf verifier"],
    "jit": ["ebpf jit compilation"],
    "inference": ["scheduling classes"],
    "llm": ["scheduling classes"],
    "serving": ["scheduling classes"],
    "disaggregat": ["memory ballooning"],
    "defragment": ["memory ballooning"],
    "allocat": ["slab allocator", "numa-aware allocation"],
    "profil": ["perf events subsystem"],
    "fault": ["page fault handler"],
    "access control": ["linux security modules"],
    "mac": ["linux security modules"],
    "sandbox": ["linux security modules", "control groups (cgroups v2)"],
    "isolation": ["control groups (cgroups v2)", "network namespaces"],
    "parallel": ["spinlock", "read-copy-update"],
    "synchroniz": ["spinlock", "read-copy-update", "futex"],
    "concurren": ["spinlock", "read-copy-update"],
    "storage": ["block i/o scheduler", "device mapper"],
    "file system": ["virtual filesystem switch (vfs)"],
    "log": ["ext4 journaling"],
    "journal": ["ext4 journaling"],
}


def get_good_concepts(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute(
        "SELECT id, json_extract(attrs, '$.name') as name FROM nodes WHERE kind = 'Concept'"
    ).fetchall()
    return {r[1].lower(): r[0] for r in rows if r[1]}


def find_orphaned_papers(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT s.id as source_id, s.attrs as s_attrs, ev.id as ev_id, ev.attrs as ev_attrs "
        "FROM nodes s "
        "JOIN edges se ON se.kind = 'sourced-from' AND se.target_id = s.id "
        "JOIN nodes ev ON ev.id = se.source_id AND ev.kind = 'Evidence' "
        "WHERE s.kind = 'Source' "
        "AND json_extract(s.attrs, '$.source_type') IN "
        "('paper','preprint','conference-paper','conference-proceedings') "
        "AND NOT EXISTS ("
        "  SELECT 1 FROM edges ce "
        "  JOIN nodes c ON c.id = ce.source_id AND c.kind = 'Concept' "
        "  WHERE ce.kind = 'extracted-from' AND ce.target_id = ev.id"
        ")"
    ).fetchall()
    result = []
    for r in rows:
        s_attrs = json.loads(r[1]) if isinstance(r[1], str) else (r[1] or {})
        ev_attrs = json.loads(r[3]) if isinstance(r[3], str) else (r[3] or {})
        result.append({
            "source_id": r[0],
            "evidence_id": r[2],
            "title": s_attrs.get("title", ""),
            "text": ev_attrs.get("text", ev_attrs.get("description", "")),
        })
    return result


def match_paper_to_concepts(title: str, text: str, name_to_id: dict[str, str]) -> list[str]:
    title_lower = title.lower()
    text_lower = (text or "").lower()
    combined = title_lower + " " + text_lower

    matched_ids: set[str] = set()

    for keyword, concept_names in _KERNEL_KEYWORDS.items():
        if keyword in combined:
            for cn in concept_names:
                if cn in name_to_id:
                    matched_ids.add(name_to_id[cn])

    for concept_name, concept_id in name_to_id.items():
        words = concept_name.split()
        if len(words) >= 2 and all(w in combined for w in words):
            matched_ids.add(concept_id)
        elif len(words) == 1 and len(concept_name) > 3:
            pattern = r'\b' + re.escape(concept_name) + r'\b'
            if re.search(pattern, combined):
                matched_ids.add(concept_id)

    return list(matched_ids)[:3]


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    name_to_id = get_good_concepts(conn)
    orphans = find_orphaned_papers(conn)

    print(f"Good Concepts: {len(name_to_id)}")
    print(f"Orphaned papers: {len(orphans)}")
    print()

    reconnected = 0
    still_orphaned = 0

    for paper in orphans:
        matches = match_paper_to_concepts(paper["title"], paper["text"], name_to_id)
        if matches:
            for concept_id in matches:
                existing = conn.execute(
                    "SELECT 1 FROM edges WHERE kind = 'extracted-from' AND source_id = ? AND target_id = ?",
                    (concept_id, paper["evidence_id"]),
                ).fetchone()
                if not existing:
                    conn.execute(
                        "INSERT INTO edges (kind, source_id, target_id, attrs) VALUES (?, ?, ?, '{}')",
                        ("extracted-from", concept_id, paper["evidence_id"]),
                    )
            concept_names = []
            for cid in matches:
                for n, i in name_to_id.items():
                    if i == cid:
                        concept_names.append(n)
                        break
            print(f"  LINK {paper['source_id']}: {paper['title'][:60]}... -> {', '.join(concept_names)}")
            reconnected += 1
        else:
            print(f"  ORPHAN {paper['source_id']}: {paper['title'][:60]}...")
            still_orphaned += 1

    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()

    print(f"\n=== Summary ===")
    print(f"Reconnected: {reconnected} papers")
    print(f"Still orphaned: {still_orphaned} papers")
    print(f"Total processed: {len(orphans)}")


if __name__ == "__main__":
    main()
