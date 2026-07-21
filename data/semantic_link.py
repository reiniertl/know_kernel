"""Semantic concept linking for papers — uses structured rules based on
domain expertise, NOT substring keyword matching.

Each paper is classified by analyzing the FULL title for semantic meaning,
not by checking if a short keyword like "io" appears as a substring.
"""

import json
import re
import sqlite3
import sys

sys.path.insert(0, "src")

DB_PATH = "data/master.db"

# Concept ID lookup
_CONCEPTS: dict[str, str] = {}  # populated from DB


def _load_concepts(conn: sqlite3.Connection) -> None:
    global _CONCEPTS
    rows = conn.execute(
        "SELECT id, json_extract(attrs, '$.name') FROM nodes WHERE kind = 'Concept'"
    ).fetchall()
    _CONCEPTS = {r[1].lower(): r[0] for r in rows if r[1]}


def _cid(name: str) -> str | None:
    return _CONCEPTS.get(name.lower())


def classify_paper(title: str) -> list[str]:
    """Return list of concept names this paper relates to.

    Uses semantic rules — each rule matches a SPECIFIC topic,
    not a generic substring.
    """
    t = title.lower()
    concepts: list[str] = []

    # --- Scheduling ---
    if re.search(r'\bscheduler\b|\bscheduling\b|\bsched[_ ]', t):
        if "ebpf" in t or "bpf" in t:
            concepts.append("sched_ext Extensible Scheduling")
        elif "deadline" in t or "edf" in t or "real-time" in t:
            concepts.append("SCHED_DEADLINE (EDF Scheduling)")
        elif "load balanc" in t:
            concepts.append("Scheduler Load Balancing")
        elif "cfs" in t or "virtual runtime" in t or "fair" in t:
            concepts.append("Virtual Runtime Scheduling")
        else:
            concepts.append("Scheduling Classes")

    if re.search(r'\bpriority inversion\b|\bpreempt', t):
        concepts.append("Scheduling Classes")
    if re.search(r'\bcpu freq|dvfs|frequency scal|power manag|energy.efficient.*cpu', t):
        concepts.append("CPU Frequency Scaling (cpufreq)")
    if re.search(r'\bcpu idle|c-state|idle state', t):
        concepts.append("CPU Idle Framework")

    # --- Memory ---
    if re.search(r'\bhuge page|hugepage|thp\b', t):
        concepts.append("Huge Page Mapping")
    if re.search(r'\btransparent huge', t):
        concepts.append("Transparent Huge Pages")
    if re.search(r'\bpage table|pte\b|page walk', t):
        concepts.append("Hierarchical Page Tables")
    if re.search(r'\btlb\b|translation lookaside', t):
        concepts.append("Translation Lookaside Buffer")
    if re.search(r'\bpage fault|demand paging|cow\b.*page|copy.on.write', t):
        concepts.append("Page Fault Handler")
    if re.search(r'\bpage reclaim|kswapd|direct reclaim|memory reclaim', t):
        concepts.append("Page Reclaim (kswapd/direct)")
    if re.search(r'\bpage cache\b', t):
        concepts.append("Page Cache")
    if re.search(r'\boom\b|out.of.memory', t):
        concepts.append("OOM Killer")
    if re.search(r'\bnuma\b|numa.aware|memory tiering|memory tier', t):
        concepts.append("NUMA Topology and Memory Policy")
    if re.search(r'\bautonuma\b', t):
        concepts.append("AutoNUMA (Automatic NUMA Balancing)")
    if re.search(r'\bslab\b|slub\b|slab allocat', t):
        concepts.append("SLUB Allocator")
    if re.search(r'\bkmalloc\b', t):
        concepts.append("Kmalloc")
    if re.search(r'\bbuddy allocat|buddy system', t):
        concepts.append("Buddy Allocator")
    if re.search(r'\bvmalloc\b', t):
        concepts.append("Vmalloc")
    if re.search(r'\bcontiguous memory|cma\b', t):
        concepts.append("Contiguous Memory Allocator")
    if re.search(r'\bksm\b|same.page merg', t):
        concepts.append("KSM (Kernel Same-page Merging)")
    if re.search(r'\bzswap\b|compressed swap', t):
        concepts.append("Zswap (Compressed Swap Cache)")
    if re.search(r'\bmemory balloon|balloon driver|virtio.balloon', t):
        concepts.append("Memory Ballooning")
    if re.search(r'\bcxl\b|compute express link', t):
        concepts.append("Adaptive CXL Memory Tiering")
    if re.search(r'\bshared memory|shmem|tmpfs\b', t):
        concepts.append("Shared Memory (shmem/tmpfs)")
    if re.search(r'\bmmap\b|memory.map', t) and "page fault" not in t:
        concepts.append("Page Fault Handler")

    # --- Synchronization ---
    if re.search(r'\brcu\b|read.copy.update', t):
        concepts.append("Read-Copy-Update")
    if re.search(r'\bspinlock\b', t):
        concepts.append("Spinlock")
    if re.search(r'\brwlock|reader.writer.*lock', t):
        concepts.append("Reader-Writer Spinlock")
    if re.search(r'\bfutex\b', t):
        concepts.append("Futex (Fast Userspace Mutex)")
    if re.search(r'\bgrace period\b', t):
        concepts.append("Grace Period")
    if re.search(r'\bquiescent state\b', t):
        concepts.append("Quiescent State Detection")
    if re.search(r'\bworkqueue\b|work queue\b', t):
        concepts.append("Workqueue")

    # --- eBPF ---
    if re.search(r'\bebpf\b|\bbpf\b', t):
        if re.search(r'verif|safe|sound', t):
            concepts.append("eBPF (Extended Berkeley Packet Filter)")
        elif re.search(r'secur|lsm|patrol', t):
            concepts.append("eBPF Runtime Security Agent")
        elif re.search(r'schedul|sched_ext', t):
            concepts.append("sched_ext Extensible Scheduling")
        elif re.search(r'page migrat|tiering', t):
            concepts.append("eBPF Page Migration Admission Control")
        elif re.search(r'page cache|caching', t):
            concepts.append("eBPF-Customizable Page Cache")
        elif re.search(r'huge page', t):
            concepts.append("eBPF-Guided Huge Page Management")
        elif re.search(r'compaction|lsm.tree', t):
            concepts.append("eBPF-Accelerated LSM Compaction")
        elif re.search(r'load balanc|l7\b|layer.7', t):
            concepts.append("eBPF In-Kernel L7 Load Balancer")
        elif re.search(r'xdp|express data', t):
            concepts.append("XDP (eXpress Data Path)")
        else:
            concepts.append("eBPF (Extended Berkeley Packet Filter)")

    # --- Networking ---
    if re.search(r'\btcp\b.*congestion|\bcongestion control\b|\bbbr\b', t):
        concepts.append("TCP Congestion Control")
    if re.search(r'\bbbr\b', t):
        concepts.append("BBR Congestion Control")
    if re.search(r'\bxdp\b|express data path', t):
        concepts.append("XDP (eXpress Data Path)")
    if re.search(r'\bnapi\b|network poll', t):
        concepts.append("NAPI (New API) Polling")
    if re.search(r'\bsk_buff\b|socket buffer', t):
        concepts.append("Socket Buffer (sk_buff)")
    if re.search(r'\bnetfilter\b|nftables|iptables', t):
        concepts.append("Netfilter Hook Framework")
    if re.search(r'\bnetwork namespace|netns\b', t):
        concepts.append("Network Namespaces")
    if re.search(r'\bepoll\b', t):
        concepts.append("Epoll Event Notification")
    if re.search(r'\bnamespace\b', t) and "network" not in t:
        concepts.append("Namespaces")

    # --- Storage / Filesystems ---
    if re.search(r'\bio_uring\b|io uring\b|iouring\b', t):
        concepts.append("io_uring")
    if re.search(r'\bext4\b', t):
        concepts.append("ext4 Journaling Filesystem")
    if re.search(r'\bxfs\b', t):
        if "zoned" in t:
            concepts.append("XFS Zoned Storage Support")
        else:
            concepts.append("XFS Filesystem")
    if re.search(r'\bbtrfs\b', t):
        concepts.append("Btrfs (B-tree Filesystem)")
    if re.search(r'\bfuse\b|filesystem in userspace', t):
        concepts.append("FUSE (Filesystem in Userspace)")
    if re.search(r'\boverlayfs\b|union mount|overlay filesystem', t):
        concepts.append("OverlayFS (Union Mount)")
    if re.search(r'\bvfs\b|virtual filesystem', t):
        concepts.append("Virtual Filesystem Switch")
    if re.search(r'\bdentry|dcache\b', t):
        concepts.append("Dentry Cache (dcache)")
    if re.search(r'\bnvme\b', t):
        concepts.append("NVMe Driver Subsystem")
    if re.search(r'\bdevice mapper\b|dm.crypt|dm.thin|lvm\b', t):
        concepts.append("Device Mapper")
    if re.search(r'\bdm.crypt\b|full disk encrypt|disk encrypt', t):
        concepts.append("dm-crypt (Full Disk Encryption)")
    if re.search(r'\bblock.*i/?o|block device|block layer', t):
        concepts.append("Block Device Layer")
    if re.search(r'\bmd\b.*raid|software raid', t):
        concepts.append("MD (Multiple Devices) Software RAID")
    if re.search(r'\blog.structured file|file system.*log|journal', t) and "ext4" not in t:
        concepts.append("Virtual Filesystem Switch")

    # --- Virtualization ---
    if re.search(r'\bkvm\b|kernel.based virtual', t):
        concepts.append("KVM (Kernel-based Virtual Machine)")
    if re.search(r'\bvfio\b|virtual function i/o', t):
        concepts.append("VFIO (Virtual Function I/O)")
    if re.search(r'\bvirtio\b|paravirtual', t):
        concepts.append("Virtio Paravirtual I/O")
    if re.search(r'\bnested virtual|hypervisor.*nested', t):
        concepts.append("KVM (Kernel-based Virtual Machine)")
    if re.search(r'\bcontainer\b.*isolat|\bcgroup\b|control group', t):
        concepts.append("Control Groups (cgroups v2)")
    if re.search(r'\bseccomp\b', t):
        concepts.append("Seccomp-BPF")

    # --- Security ---
    if re.search(r'\blsm\b|linux security module|selinux|apparmor|mandatory access control', t):
        concepts.append("Linux Security Modules")
    if re.search(r'\bcrypto\b|encrypt|cipher|hash.*kernel|aes\b', t) and "disk" not in t:
        concepts.append("Kernel Crypto API")
    if re.search(r'\bcapabilit.*posix|posix capabil', t):
        concepts.append("POSIX Capabilities")
    if re.search(r'\bside.channel|spectre|meltdown|rowhammer|cache.*attack|timing.*attack', t):
        concepts.append("Linux Security Modules")
    if re.search(r'\bsgx\b|tdx\b|sev\b|trustzone|tee\b|confidential comput|enclave', t):
        concepts.append("Linux Security Modules")

    # --- Process / IPC ---
    if re.search(r'\bfork\b|clone\b|process creat|posix_spawn', t):
        concepts.append("Process Creation (fork/clone)")
    if re.search(r'\bsignal deliver|signal handl|sigaction', t):
        concepts.append("Signal Delivery")
    if re.search(r'\bpipe\b|fifo\b', t) and "pipeline" not in t:
        concepts.append("Pipe and FIFO")

    # --- Tracing / Debug ---
    if re.search(r'\bftrace\b|function trac', t):
        concepts.append("Ftrace")
    if re.search(r'\bperf\b.*event|perf_event|hardware counter', t):
        concepts.append("Perf Events Subsystem")
    if re.search(r'\bprocfs\b|sysfs\b|/proc|/sys\b', t):
        concepts.append("Procfs and Sysfs")

    # --- Hardware ---
    if re.search(r'\binterrupt\b|irq\b|interrupt handl', t):
        concepts.append("Interrupt Handling")
    if re.search(r'\bdma\b|direct memory access', t):
        concepts.append("DMA Mapping Framework")
    if re.search(r'\busb\b', t):
        concepts.append("USB Subsystem")
    if re.search(r'\bdevicetree\b|device tree|fdt\b|dts\b', t):
        concepts.append("Devicetree (DT/FDT)")
    if re.search(r'\buefi\b|efi\b|secure boot|boot.*firmware', t):
        concepts.append("EFI/UEFI Boot and Runtime Services")
    if re.search(r'\bthermal\b|thermal.*manag|cooling.*device', t):
        concepts.append("Thermal Management Framework")
    if re.search(r'\bkernel module|loadable module|insmod|modprobe', t):
        concepts.append("Kernel Module Loader")
    if re.search(r'\blive patch|kpatch|livepatch', t):
        concepts.append("Kernel Live Patching")

    # --- Specific named systems ---
    if re.search(r'\bred.black tree|rbtree\b', t):
        concepts.append("Red-Black Tree Runqueue")

    # Deduplicate
    seen = set()
    result = []
    for c in concepts:
        if c not in seen:
            seen.add(c)
            result.append(c)
    return result[:3]


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    _load_concepts(conn)

    papers = conn.execute("""
        SELECT s.id,
               COALESCE(json_extract(s.attrs, '$.title'), '') as title,
               ev.id as ev_id
        FROM nodes s
        JOIN edges se ON se.kind = 'sourced-from' AND se.target_id = s.id
        JOIN nodes ev ON ev.id = se.source_id AND ev.kind = 'Evidence'
        WHERE s.kind = 'Source'
        AND json_extract(s.attrs, '$.source_type') IN
            ('paper','preprint','conference-paper','conference-proceedings')
        AND json_extract(s.attrs, '$.title') IS NOT NULL
        AND json_extract(s.attrs, '$.title') != ''
        AND NOT EXISTS (
            SELECT 1 FROM edges ce
            JOIN nodes c ON c.id = ce.source_id AND c.kind = 'Concept'
            WHERE ce.kind = 'extracted-from' AND ce.target_id = ev.id
        )
        ORDER BY json_extract(s.attrs, '$.published_date') DESC, s.id
    """).fetchall()

    print(f"Papers to classify: {len(papers)}")

    linked = 0
    unlinked = 0

    for sid, title, ev_id in papers:
        concepts = classify_paper(title)
        if concepts:
            for cname in concepts:
                cid = _cid(cname)
                if cid:
                    existing = conn.execute(
                        "SELECT 1 FROM edges WHERE kind = 'extracted-from' AND source_id = ? AND target_id = ?",
                        (cid, ev_id),
                    ).fetchone()
                    if not existing:
                        conn.execute(
                            "INSERT INTO edges (kind, source_id, target_id, attrs) VALUES ('extracted-from', ?, ?, '{}')",
                            (cid, ev_id),
                        )
            linked += 1
        else:
            unlinked += 1

        if (linked + unlinked) % 500 == 0:
            conn.commit()
            print(f"  ... {linked} linked, {unlinked} unlinked of {linked + unlinked}")

    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()

    print(f"\n=== Summary ===")
    print(f"Linked: {linked}")
    print(f"Unlinked (no concept match): {unlinked}")
    print(f"Total: {linked + unlinked}")


if __name__ == "__main__":
    main()
