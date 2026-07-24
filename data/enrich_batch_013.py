"""Deep enrichment batch 013: 7 papers — eBPF Spectre defense, automated OS specialization,
NDP page tables, kernel-level LLM safety, GPU OS, CXL SSD co-design, syncfs side channel.

Papers:
1. VeriFence — Lightweight Spectre defenses for untrusted eBPF kernel extensions
2. Wayfinder — Automated OS configuration specialization (up to 24% perf gain)
3. NDPage — Efficient address translation for near-data processing architectures
4. ProbeLogits — Kernel-level LLM inference primitive for AI-native OS safety
5. LithOS — Operating system for efficient ML on GPUs (TPC scheduling, atomization)
6. SkyByte — CXL-based memory-semantic SSD with OS and hardware co-design
7. syncfs Side Channel — Covert and side channel attacks via Linux syncfs
"""
import json, sqlite3, uuid

DB_PATH = "data/master.db"

ALL_PAPERS = [
    # ── 1. VeriFence: Spectre Defenses for eBPF ────────────────────
    {
        "ev_id": "ev-arxiv-27671a23",
        "brief": {
            "key_ideas": [
                "Finds that 31-54% of real-world eBPF programs from popular open-source projects are rejected by the kernel's Spectre defenses — users are forced to disable defenses entirely, putting the system at risk",
                "VeriFence enhances the kernel's Spectre defenses to reduce rejected eBPF programs from 54% to zero — enabling secure and expressive untrusted kernel extensions",
                "Measures overhead across all mainstream performance-sensitive eBPF applications (event tracing, profiling, packet processing) and finds it significantly improves upon the status quo",
                "The status quo forces a binary choice: reject programs (breaking functionality) or disable Spectre defenses (enabling transient execution attacks on the kernel)"
            ],
            "relevance": "Directly addresses a critical tension in the Linux kernel's eBPF subsystem: Spectre mitigations reject too many legitimate programs. The eBPF verifier's Spectre defenses (added after the 2018 disclosure) are overly conservative, blocking programs that are actually safe. VeriFence makes these defenses precise rather than conservative, preserving both security and expressiveness. This is relevant to every eBPF user — networking (Cilium), observability (bpftrace), security (Falco), and scheduling (sched_ext) all hit these rejections. Published at a top venue with real-world validation on 844 production eBPF programs.",
            "methodology": "Analysis of 844 real-world eBPF programs from open-source projects. Enhanced Spectre defense implementation in the eBPF verifier. Performance evaluation on tracing, profiling, and packet processing."
        },
        "concepts": ["eBPF (Extended Berkeley Packet Filter)", "Linux Security Modules"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "Spectre defenses reject 31-54% of real-world eBPF programs",
             "description": "The Linux kernel's Spectre mitigations in the eBPF verifier reject 31-54% of real-world programs from popular open-source projects. Users are forced to disable defenses to use these programs, creating a binary choice between functionality and security."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Precise Spectre defenses reducing eBPF rejection to zero",
             "description": "VeriFence enhances the kernel's eBPF Spectre defenses to reject zero legitimate programs while maintaining protection. Evaluated on 844 real-world programs across tracing, profiling, and packet processing with acceptable overhead."}
        ]
    },

    # ── 2. Wayfinder: Automated OS Specialization ──────────────────
    {
        "ev_id": "ev-arxiv-7171071c",
        "brief": {
            "key_ideas": [
                "Fully automatic OS configuration specialization without expert knowledge — specializes compile-time, boot-time, and run-time configuration toward any quantifiable metric (performance, resource, security)",
                "Neural network-based search algorithm learns on the fly which configuration parameters impact performance most and which lead to runtime failures",
                "Addresses the sheer size of modern OS configuration space: existing attempts limited to feature toggling for memory/attack-surface reduction, cannot target performance",
                "Up to 24% application performance improvement through automated configuration specialization across two OSes and four applications"
            ],
            "relevance": "Directly applicable to Linux kernel configuration. The Linux kernel has thousands of compile-time options (Kconfig), boot parameters, and sysctl tunables. Wayfinder automates the expert-level task of tuning these for specific workloads. The neural network approach to navigating invalid configurations is particularly relevant — many kernel option combinations are invalid or cause boot failures. The 24% performance improvement from configuration alone (no code changes) shows how much performance the kernel leaves on the table with default configurations. This complements sched_ext and eBPF-based customization with configuration-level specialization.",
            "methodology": "Automated OS benchmarking platform. Neural network-based configuration search. Two OSes, four applications, two target metrics. Transfer learning between related applications."
        },
        "concepts": ["Kernel Module Loader"],
        "claims": [
            {"kind": "Problem", "id_prefix": "prob", "name": "OS configuration space too large for manual specialization",
             "description": "Modern OSes have enormous configuration spaces (compile/boot/runtime). Manual specialization requires deep expertise. Automated approaches have been limited to feature toggling for memory/attack-surface, unable to target performance due to space size and invalid configurations."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "Neural network-driven automated OS specialization",
             "description": "Wayfinder specializes all aspects of OS configuration automatically via a neural network that learns parameter impact and failure patterns on the fly. Up to 24% performance improvement without code changes. Supports pre-trained model transfer between related applications."}
        ]
    },

    # ── 3. NDPage: NDP-Tailored Page Tables ────────────────────────
    {
        "ev_id": "ev-arxiv-6f125888",
        "brief": {
            "key_ideas": [
                "Identifies that standard 4-level page tables cause significant overhead in NDP because (1) NDP generates many address translations and (2) limited NDP L1 cache cannot cover page table entry accesses",
                "Observes PTE memory access is highly irregular (cannot benefit from L1 cache) and last two page table levels are nearly fully occupied",
                "L1 cache bypass mechanism for PTEs: accelerates PTE memory accesses and prevents PTE pollution in the cache system",
                "Flattened page table merging last two levels: reduces PTE accesses while maintaining 4KB page flexibility"
            ],
            "relevance": "Directly redesigns the page table structure for near-data processing — a new hardware paradigm where the kernel's standard 4-level page table is too expensive. The L1 cache bypass for PTEs is counter-intuitive but correct for NDP's irregular access patterns (the cache does more harm than good). The flattened page table is a variant of the kernel's 5-level page table support but optimized for the opposite direction (fewer levels, not more). This is relevant to the kernel's page table management for any device-side compute (CXL NDP, SmartNICs, computational storage) that needs address translation.",
            "methodology": "Analysis of page table behavior in NDP systems. L1 cache bypass mechanism. Flattened last-two-levels page table design. Evaluation with data-intensive workloads."
        },
        "concepts": ["Hierarchical Page Tables", "Translation Lookaside Buffer", "Page Fault Handler"],
        "claims": [
            {"kind": "Observation", "id_prefix": "obs", "name": "Standard page tables cause significant NDP overhead via cache pollution",
             "description": "PTE accesses in NDP are highly irregular and pollute the limited L1 cache. The last two page table levels are nearly fully occupied but still require separate lookups. Standard 4-level translation adds substantial overhead to data-intensive NDP workloads."},
            {"kind": "Proposal", "id_prefix": "prop", "name": "NDP-tailored page table with cache bypass and level flattening",
             "description": "NDPage bypasses L1 cache for PTEs (preventing pollution) and merges the last two page table levels (reducing PTE accesses while keeping 4KB page flexibility). Improves NDP end-to-end performance for data-intensive workloads."}
        ]
    },

    # ── 4. ProbeLogits: Kernel-Level LLM Safety Primitive ──────────
    {
        "ev_id": "ev-arxiv-1d1b18ab",
        "brief": {
            "key_ideas": [
                "A kernel-level operation that performs a single forward pass and reads specific token logits to classify an agent's action as safe/dangerous — zero learned parameters, uses the agent's own base model",
                "Removes the need for a separate guard model (like Llama Guard): the safety check reads a logit from the same model, making marginal cost a single logit read",
                "2.4-3.4x faster than Llama Guard 3 (332-556ms vs 851-1142ms) because it reads one logit position instead of generating tokens",
                "Implemented in Anima OS (bare-metal x86-64 Rust kernel): enforcement below the WASM sandbox boundary makes bypass structurally impossible. Calibration alpha as a deployment-time policy knob"
            ],
            "relevance": "The foundational primitive behind Governed MCP (batch 007). ProbeLogits shows that LLM inference can be a kernel operation — the OS kernel runs a forward pass and reads logits for safety classification. This is the most extreme intersection of ML and OS kernels: the kernel itself performs neural network inference as a security gate. The single-logit-read approach is efficient enough for the kernel hot path. Implemented in a real Rust OS kernel (285K lines), demonstrating feasibility. While not Linux, this establishes the design pattern that Linux could adopt via eBPF or kernel modules.",
            "methodology": "Kernel-level implementation in Anima OS (bare-metal Rust). Three base models (Qwen2.5-7B, Llama-3-8B, Mistral-7B). Three benchmarks (HarmBench, XSTest, ToxicChat). Speed comparison vs Llama Guard 3."
        },
        "concepts": [],
        "claims": [
            {"kind": "Proposal", "id_prefix": "prop", "name": "Single-logit kernel-level LLM safety classification",
             "description": "ProbeLogits reads one logit position from the agent's own base model for safe/dangerous classification — no separate guard model needed. 2.4-3.4x faster than Llama Guard 3. Implemented as a kernel operation in bare-metal Rust OS with enforcement below WASM sandbox."},
            {"kind": "PerformanceProfile", "id_prefix": "perf", "name": "ProbeLogits matches Llama Guard 3 accuracy 2.4-3.4x faster",
             "description": "On ToxicChat: F1 parity or better vs Llama Guard 3 across three models. HarmBench: 97-99% non-copyright block rate. 332-556ms vs 851-1142ms classification latency."}
        ]
    },

    # ── 5. LithOS: GPU Operating System ────────────────────────────
    {
        "ev_id": "ev-arxiv-d7707834",
        "brief": {
            "key_ideas": [
                "First step toward a GPU OS: TPC Scheduler supports spatial scheduling at individual TPC (Texture Processing Cluster) granularity, enabling efficient TPC stealing between workloads",
                "Transparent kernel atomization reduces head-of-line blocking and enables dynamic resource reallocation mid-execution — GPU kernels are broken into smaller schedulable units",
                "Lightweight hardware right-sizing determines minimal TPC resources per atom; transparent power management reduces consumption based on in-flight work behavior",
                "13x lower tail latency than NVIDIA MPS for inference stacking; 3x lower than best SoTA with 1.6x higher aggregate throughput. Implemented in Rust"
            ],
            "relevance": "Treats the GPU as an OS-managed resource with scheduling, isolation, and power management — the same abstractions the kernel provides for CPUs. The TPC scheduler is the GPU equivalent of the kernel's CPU scheduler. Kernel atomization is analogous to preemption (breaking long-running work into schedulable pieces). The power management maps to the kernel's cpufreq governors. This shows what GPU resource management would look like if the kernel (not the NVIDIA driver) controlled it. Implemented in Rust, 13x better than NVIDIA MPS.",
            "methodology": "GPU OS implementation in Rust. TPC-granularity spatial scheduling. Kernel atomization. Hardware right-sizing. Power management. Extensive ML environment evaluation vs NVIDIA MPS and SoTA."
        },
        "concepts": ["Scheduling Classes"],
        "claims": [
            {"kind": "Proposal", "id_prefix": "prop", "name": "GPU OS with TPC scheduling, kernel atomization, and power management",
             "description": "LithOS provides OS-level GPU management: TPC-granularity spatial scheduling with work stealing, transparent kernel atomization for preemptibility, hardware right-sizing, and behavior-based power management. 13x lower tail latency than MPS, 3x vs SoTA with 1.6x throughput."}
        ]
    },

    # ── 6. SkyByte: CXL Memory-Semantic SSD Co-Design ──────────────
    {
        "ev_id": "ev-arxiv-4e39b7a8",
        "brief": {
            "key_ideas": [
                "Architects a memory-semantic CXL-based SSD with OS and hardware co-design — the SSD presents byte-addressable memory to the host via CXL while being backed by NAND flash",
                "OS co-design: the kernel manages the CXL SSD's memory tiers (DRAM cache + NAND) with awareness of the device's internal caching and wear characteristics",
                "Hardware co-design: the SSD controller exposes enough information for the OS to make intelligent placement decisions rather than hiding everything behind a black-box FTL",
                "Demonstrates that OS-hardware cooperation for CXL SSDs yields better performance than either OS-only or hardware-only management"
            ],
            "relevance": "Directly relevant to how the Linux kernel should manage CXL-attached SSDs that present as memory. The co-design philosophy — the kernel and SSD controller cooperate rather than the SSD hiding behind an opaque FTL — is a departure from traditional block device management. This complements ByteFS (batch 009) which built a filesystem for CXL SSDs, and Samsung CMM-H (batch 010) which characterized a production device. SkyByte provides the architectural framework for kernel CXL SSD drivers.",
            "methodology": "OS-hardware co-design architecture. CXL SSD with byte-addressable memory interface. Evaluation comparing OS-only, hardware-only, and co-designed management."
        },
        "concepts": ["Adaptive CXL Memory Tiering", "NVMe Driver Subsystem", "Block Device Layer"],
        "claims": [
            {"kind": "Proposal", "id_prefix": "prop", "name": "OS-hardware co-designed CXL memory-semantic SSD",
             "description": "SkyByte architects a CXL SSD where the kernel and device controller cooperate: the SSD exposes tier information (DRAM cache + NAND) and the OS makes intelligent placement decisions. Co-design outperforms OS-only or hardware-only management."}
        ]
    },

    # ── 7. syncfs Side Channel Attacks ─────────────────────────────
    {
        "ev_id": "ev-arxiv-974226f2",
        "brief": {
            "key_ideas": [
                "Discovers covert and side channel attacks exploiting Linux's syncfs system call — syncfs flushes all dirty pages for a filesystem, and its timing reveals information about other processes' file I/O activity",
                "Demonstrates both covert channel communication and side channel information leakage between isolated processes sharing the same filesystem",
                "The attack exploits the kernel's page cache and writeback mechanism: syncfs duration correlates with the amount of dirty data from all processes on the filesystem",
                "Challenges the assumption that process isolation prevents information flow through shared kernel resources like the page cache"
            ],
            "relevance": "Directly exploits the Linux kernel's syncfs implementation and page cache writeback mechanism. The timing side channel through syncfs reveals dirty page activity of other processes — a violation of the isolation the kernel is supposed to provide. This is relevant to kernel security: container isolation (where containers share the host filesystem) is weaker than assumed. The page cache writeback path leaks information about I/O activity across process boundaries. This motivates per-container or per-namespace page cache isolation.",
            "methodology": "Side channel analysis of Linux syncfs timing. Covert channel construction. Cross-process information leakage demonstration. Page cache dirty page correlation analysis."
        },
        "concepts": ["Page Cache", "Virtual Filesystem Switch", "Namespaces"],
        "claims": [
            {"kind": "FailureMode", "id_prefix": "fail", "name": "Linux syncfs leaks cross-process I/O activity via timing",
             "description": "The syncfs system call's execution time correlates with dirty page volume from all processes on the filesystem. Attackers exploit this to build covert channels and infer other processes' file I/O activity, breaking process isolation assumptions. Relevant to container security where containers share host filesystem."}
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
            print(f"  SKIP: {ev_id}")
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
            (brief_id, json.dumps({
                "title": title, "key_ideas": json.dumps(brief["key_ideas"]),
                "relevance": brief["relevance"], "methodology": brief["methodology"],
                "source_date": date or "2026-01-01", "artifact_class": "A",
            })),
        )
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
                (claim_id, claim["kind"], json.dumps({"name": claim["name"], "description": claim["description"], "source_date": date or "2026-01-01"})))
            conn.execute("INSERT INTO edges (kind, source_id, target_id, attrs) VALUES ('extracted-from', ?, ?, '{}')", (claim_id, ev_id))
            stats["claims"] += 1; stats["edges"] += 1

        safe_title = title.encode('ascii', 'replace').decode()
        print(f"  OK: {safe_title}")

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
