"""Deep enrichment batch 001: 5 high-signal papers with full ResearchBrief + structured claims.

Papers:
1. ActPlane — eBPF-based OS-level policy enforcement for AI agent harnesses
2. Kops — Extending the eBPF JIT compilation pipeline with native operations
3. Aquifer — CXL+RDMA hierarchical memory pooling for MicroVM snapshots
4. Heimdall — Formally verified automated migration of eBPF programs to Rust
5. Clove — Object-level CXL memory management in managed runtimes
"""
import json, sqlite3, uuid

DB_PATH = "data/master.db"


# ── Paper 1: ActPlane ────────────────────────────────────────────────
# ev-arxiv-actplane-os-level-ebpf-policy-enforcemen
# UC Santa Cruz, Virginia Tech, HKUST, Alibaba. 2026.
#
# Abstract analysis: ActPlane addresses a fundamental gap in AI agent
# safety — tool-call guardrails miss system actions that bypass the
# tool layer, while OS sandboxes (seccomp, namespaces) control resource
# access but not action semantics. ActPlane bridges this by letting
# agents declare policies in a simple IFC DSL and enforcing them in
# the kernel via eBPF. The system supports cross-event policies (e.g.,
# "run tests before committing") by tracking information flow between
# system calls. Implementation uses eBPF programs attached to syscall
# tracepoints. Overhead is 1.9-8.4%.
#
# This is significant for the kernel because it proposes a new class
# of eBPF program: policy enforcement programs that track causal
# ordering between syscalls. This goes beyond seccomp (which is
# stateless per-syscall filtering) and LSM hooks (which check
# permissions, not action ordering).

ACTPLANE = {
    "ev_id": "ev-arxiv-actplane-os-level-ebpf-policy-enforcemen",
    "brief": {
        "key_ideas": [
            "Bridges the semantic gap between natural-language agent policies and OS-level enforcement using eBPF — tool-call guardrails miss syscalls that bypass the tool layer, while OS sandboxes (seccomp) are stateless and return opaque errors",
            "Introduces an information-flow control (IFC) DSL for cross-event policies that track causal ordering between system calls — e.g., 'run tests before commit' requires tracking exec(go test) → exec(git commit) ordering",
            "Compiles IFC policy rules into eBPF programs attached to syscall tracepoints, creating a new class of stateful per-agent policy enforcement beyond seccomp's stateless filtering",
            "Achieves 1.9-8.4% overhead while improving policy compliance on indirect execution paths invisible to tool-call interception"
        ],
        "relevance": "Proposes a fundamentally new use case for the kernel's eBPF subsystem: stateful, cross-syscall policy enforcement for AI agents. This extends eBPF beyond its traditional networking/observability/security domains into agent governance. The IFC tracking requires eBPF map state that persists across syscall boundaries — pushing the limits of what eBPF programs can express within verifier constraints. Also demonstrates that seccomp-BPF's per-syscall stateless model is insufficient for modern agent safety, motivating richer kernel policy mechanisms.",
        "methodology": "System design + implementation using eBPF tracepoints with IFC-based policy DSL. Evaluated against empirical policy study, coding-task benchmarks, and safety benchmarks. Comparison against tool-call guardrails and OS sandboxes."
    },
    "concepts": [
        "eBPF (Extended Berkeley Packet Filter)",
        "Seccomp-BPF",
        "Linux Security Modules"
    ],
    "claims": [
        {
            "kind": "Problem",
            "id_prefix": "prob",
            "name": "Agent policy enforcement semantic gap",
            "description": "Tool-call guardrails miss system actions that bypass the tool layer (e.g., subprocess spawning, direct file I/O), while OS sandboxes like seccomp control resource access but not action semantics or ordering. Neither mechanism can enforce cross-event policies like 'run tests before committing'."
        },
        {
            "kind": "Observation",
            "id_prefix": "obs",
            "name": "Seccomp is stateless and semantics-blind",
            "description": "Seccomp-BPF filters operate on individual syscalls without cross-call state. They cannot track causal relationships between events (e.g., whether a test ran before a commit). Their error returns are opaque to agents, causing confused retry loops instead of corrective action."
        },
        {
            "kind": "Proposal",
            "id_prefix": "prop",
            "name": "eBPF-based IFC policy engine for agents",
            "description": "ActPlane compiles agent-declared policies into eBPF programs that track information flow across syscall boundaries using eBPF maps for persistent state. Policies expressed in an IFC DSL support ordering constraints, data flow tracking, and semantic feedback to the agent."
        },
        {
            "kind": "PerformanceProfile",
            "id_prefix": "perf",
            "name": "ActPlane overhead characterization",
            "description": "ActPlane adds 1.9-8.4% overhead to agent execution while enforcing cross-event policies. Improves policy compliance on indirect execution paths that tool-call interception cannot observe."
        }
    ]
}


# ── Paper 2: Kops ────────────────────────────────────────────────────
# ev-arxiv-kops-extending-ebpf-compilation-with-nat
# UC Santa Cruz, Virginia Tech, Telecom Paris, ETH Zurich. 2026.
#
# Abstract analysis: The eBPF kernel JIT is deliberately simple —
# single-pass, one bytecode instruction at a time — to keep the TCB
# small. This means eBPF runs up to 2x slower than natively compiled
# code. Adding optimizations to the kernel JIT requires upstream
# acceptance, long release cycles, and enlarges the TCB per-architecture.
#
# Kops introduces an extension interface: each new operation has a
# "proof sequence" (vanilla eBPF the verifier checks) and a "native emit"
# (machine instructions the JIT compiles). The verifier validates the
# proof sequence, so the native emit is the only TCB addition per
# operation. They built EInsn — 7 operations (rotate, conditional select)
# that CPUs execute as single instructions. Lean 4 proofs show each
# native emit computes the same result as its proof sequence.
#
# Results: up to 24% speedup on microbenchmarks, 12% on production apps.
# Also supports whole-program native replacement at 2.358x but with
# larger TCB.

KOPS = {
    "ev_id": "ev-arxiv-kops-extending-ebpf-compilation-with-nat",
    "brief": {
        "key_ideas": [
            "Identifies a fundamental tension in eBPF JIT design: the single-pass, one-instruction-at-a-time translation keeps the TCB small but sacrifices up to 2x performance versus natively compiled code",
            "Introduces Kops, an extension interface where each new operation has a proof sequence (vanilla eBPF checked by the verifier) and a native emit (machine code compiled by the JIT) — the verifier validates safety via the proof sequence while the JIT emits the fast path",
            "Builds EInsn: 7 hardware-native operations (rotate, conditional select) with Lean 4 proofs showing each native emit computes the same result as its proof sequence — formal verification of JIT extensions",
            "Achieves 12-24% speedup on production eBPF applications while keeping TCB growth minimal (one native emit per operation per architecture)"
        ],
        "relevance": "Directly addresses the eBPF JIT performance ceiling that limits eBPF adoption for latency-sensitive kernel paths (XDP, tc, sched_ext). The proof-carrying code approach — where the verifier checks a safe proxy and the JIT emits hardware-native code — is a novel compilation architecture that could reshape how eBPF extensions evolve. Lean 4 proofs for JIT correctness set a new bar for kernel extension safety. The whole-program replacement path (2.358x) shows eBPF approaching native kernel module performance.",
        "methodology": "Compiler architecture with proof-carrying code. Lean 4 formal verification of native emit correctness. Evaluation on x86-64 and ARM64 with microbenchmarks and production eBPF applications (networking, observability)."
    },
    "concepts": [
        "eBPF (Extended Berkeley Packet Filter)"
    ],
    "claims": [
        {
            "kind": "Problem",
            "id_prefix": "prob",
            "name": "eBPF JIT performance ceiling from single-pass design",
            "description": "The kernel eBPF JIT translates one bytecode instruction at a time in a single pass to keep the TCB small and trustworthy. This means eBPF programs run up to 2x slower than natively compiled C code, limiting eBPF's viability for latency-sensitive kernel paths."
        },
        {
            "kind": "Observation",
            "id_prefix": "obs",
            "name": "Adding JIT optimizations requires upstream acceptance and enlarges TCB",
            "description": "Optimizing the kernel JIT directly requires Linux upstream acceptance (long release cycles), increases the trusted computing base per-architecture, and risks introducing JIT bugs that compromise kernel safety."
        },
        {
            "kind": "Proposal",
            "id_prefix": "prop",
            "name": "Proof-carrying native operations for eBPF JIT",
            "description": "Kops introduces an extension interface where each new operation has a proof sequence (vanilla eBPF checked by the existing verifier) and a native emit (architecture-specific machine code). The verifier validates the proof sequence for safety; the native emit provides performance. Lean 4 proofs verify that each native emit computes the same result as its proof sequence."
        },
        {
            "kind": "PerformanceProfile",
            "id_prefix": "perf",
            "name": "Kops EInsn speedup on eBPF workloads",
            "description": "Seven hardware-native operations (rotate, conditional select, etc.) speed up eBPF microbenchmarks by up to 24% and production applications by up to 12% on x86-64 and ARM64. Whole-program native replacement reaches 2.358x at the cost of a larger TCB."
        },
        {
            "kind": "Benchmark",
            "id_prefix": "bench",
            "name": "eBPF vs native compilation performance gap",
            "description": "Characterization showing eBPF runs up to 2x slower than natively compiled code due to the single-pass JIT design, establishing the performance ceiling that Kops addresses."
        }
    ]
}


# ── Paper 3: Aquifer ─────────────────────────────────────────────────
# ev-arxiv-aquifer-cxl/rdma-hierarchical-memory-poo
# Chinese University of Hong Kong, Virginia Tech. 2026.
#
# Abstract analysis: Memory stranding wastes 25-35% of DRAM in production
# clouds (Microsoft, Google, Meta, Alibaba). CXL provides low-latency
# load/store access but is pod-limited. RDMA provides cluster-wide reach
# but with higher latency and software overhead (page faults, kernel
# intervention).
#
# Aquifer is the first system to serve MicroVM snapshots from a
# hierarchical CXL+RDMA memory pool. Key insights:
# 1. Snapshot image characterization: most pages are zero or cold
# 2. Hotness-based snapshot format eliminates zero pages, places hot
#    working set in CXL pool, cold pages in RDMA pool
# 3. CXL 2.0 multi-headed devices lack hardware coherence → ownership-
#    based coherence protocol for shared snapshots
# 4. Copy-based page serving: pre-installs hot pages from CXL before
#    MicroVM resume, demand-pages cold pages from RDMA asynchronously
#
# Result: 2.2x speedup in end-to-end invocation time over Firecracker.

AQUIFER = {
    "ev_id": "ev-arxiv-aquifer-cxl/rdma-hierarchical-memory-poo",
    "brief": {
        "key_ideas": [
            "First system to serve MicroVM snapshots from a hierarchical CXL+RDMA memory pool — CXL for low-latency hot pages (pod-local), RDMA for cluster-wide cold pages, addressing the fundamental CXL reach vs RDMA latency tradeoff",
            "Characterizes MicroVM snapshot images and finds the vast majority of pages are either zero or cold — enabling a hotness-based snapshot format that eliminates zero pages and tiered placement",
            "Designs an ownership-based coherence protocol for sharing snapshots on CXL 2.0 multi-headed devices that lack hardware cache coherence — a practical solution to the CXL 2.0 coherence gap",
            "Pre-installs hot pages from CXL memory before MicroVM resume and demand-pages cold pages asynchronously from RDMA, achieving 2.2x geometric-mean speedup over Firecracker"
        ],
        "relevance": "Directly relevant to kernel CXL memory management (CXL.mem device drivers, NUMA node enumeration for CXL-attached memory), KVM's MicroVM snapshot/restore path (Firecracker uses KVM), and the kernel's page fault handler for demand-paging cold pages from remote RDMA storage. The ownership-based coherence protocol for CXL 2.0 multi-headed devices has implications for how the kernel manages shared memory regions across hosts — current kernel CXL drivers assume hardware coherence. The hotness-based snapshot tiering maps directly to the kernel's page migration and NUMA balancing infrastructure.",
        "methodology": "System design with emulated CXL+RDMA hardware. MicroVM snapshot image characterization. End-to-end evaluation against Firecracker baseline and alternatives."
    },
    "concepts": [
        "Adaptive CXL Memory Tiering",
        "KVM (Kernel-based Virtual Machine)",
        "NUMA Topology and Memory Policy",
        "Page Fault Handler"
    ],
    "claims": [
        {
            "kind": "Problem",
            "id_prefix": "prob",
            "name": "Memory stranding wastes 25-35% of cloud DRAM",
            "description": "Provisioned DRAM sits idle when co-located CPU cores are fully subscribed. Measurements at Microsoft Azure, Google, Meta, and Alibaba confirm 25-45% memory stranding across production clusters."
        },
        {
            "kind": "Observation",
            "id_prefix": "obs",
            "name": "CXL and RDMA are complementary but neither suffices alone",
            "description": "CXL provides low-latency load/store-transparent access limited to a pod. RDMA provides cluster-wide reach but with higher latency and software overhead (page faults, kernel intervention). A hierarchical architecture combining both tiers is the practical path forward."
        },
        {
            "kind": "Observation",
            "id_prefix": "obs",
            "name": "MicroVM snapshot pages are mostly zero or cold",
            "description": "Characterization of MicroVM snapshot images reveals the vast majority of pages are either zero-filled or cold (rarely accessed after restore), enabling hotness-based tiered placement that eliminates zero pages entirely."
        },
        {
            "kind": "Proposal",
            "id_prefix": "prop",
            "name": "Hierarchical CXL+RDMA memory pool with ownership coherence",
            "description": "Aquifer places hot snapshot working set in CXL pool and cold pages in RDMA pool. An ownership-based coherence protocol ensures correctness on CXL 2.0 multi-headed devices that lack hardware cache coherence. Copy-based page serving pre-installs hot pages before MicroVM resume."
        },
        {
            "kind": "PerformanceProfile",
            "id_prefix": "perf",
            "name": "Aquifer serverless cold start improvement",
            "description": "2.2x geometric-mean speedup in end-to-end MicroVM invocation time over Firecracker, and 1.1x over the next best alternative, on emulated CXL+RDMA hardware."
        }
    ]
}


# ── Paper 4: Heimdall ────────────────────────────────────────────────
# ev-arxiv-2c149bd7
# 2026. Multiple institutions.
#
# Abstract analysis: Documents 6 classes of source-level bugs that
# compile, pass the eBPF verifier, and silently corrupt data, leak
# events, or yield incorrect enforcement. Key finding: information
# leaks in 10 open-source eBPF programs where ring-buffer or stack
# event records carry fully decodable prior traced events, including
# user-identifying paths and kernel-text return addresses sufficient
# to recover the KASLR slide on every event.
#
# Heimdall automates migration of libbpf C programs to Aya Rust:
# - LLM-based translation with iterative repair of compilation/verifier failures
# - Static analysis safety engine rejects unsafe escape hatches in Rust-Aya
# - Symbolic execution + Z3-based equivalence checking proves per-program
#   behavioral equivalence
# - 96/102 programs (94.1%) produce formally proven-equivalent translations

HEIMDALL = {
    "ev_id": "ev-arxiv-2c149bd7",
    "brief": {
        "key_ideas": [
            "Documents six classes of source-level bugs that compile and pass the eBPF verifier but silently corrupt data, leak previously traced events, or yield incorrect enforcement — the verifier checks memory safety and termination but not higher-level properties like initialization discipline or schema consistency",
            "Discovers previously unreported information leaks in 10 open-source eBPF programs: ring-buffer and stack-resident event records carry fully decodable prior traced events including user-identifying paths and kernel-text return addresses sufficient to recover the KASLR slide on every event",
            "Presents Heimdall, an automated pipeline using LLMs to translate legacy libbpf C programs to Aya Rust with iterative repair of compilation and verifier failures, static analysis to reject unsafe Rust escape hatches, and Z3-based symbolic equivalence checking",
            "Achieves 94.1% formally proven-equivalent translations (96/102 programs) — first system to automate memory-safe-language migration of production eBPF programs with per-program formal guarantees"
        ],
        "relevance": "Directly impacts the kernel eBPF ecosystem at two levels. First, the verifier gap analysis shows that the kernel's eBPF verifier — the primary safety gate for in-kernel extensions — has a blind spot for source-level properties. The KASLR leak through ring-buffer events is a concrete kernel security vulnerability. Second, the C-to-Rust migration path aligns with the kernel's ongoing Rust adoption — if eBPF programs can be automatically migrated to memory-safe Rust (Aya), it reduces the attack surface of kernel extensions. The equivalence checking provides formal assurance that migration preserves observable behavior.",
        "methodology": "Bug taxonomy from manual analysis of open-source eBPF programs. LLM-based automated translation pipeline (C → Rust/Aya) with static safety analysis and symbolic equivalence verification via Z3. Evaluation on 102 production eBPF programs."
    },
    "concepts": [
        "eBPF (Extended Berkeley Packet Filter)",
        "Linux Security Modules"
    ],
    "claims": [
        {
            "kind": "Problem",
            "id_prefix": "prob",
            "name": "eBPF verifier blind spot for source-level properties",
            "description": "The in-kernel eBPF verifier checks low-level memory safety and termination but does not enforce higher-level source-level properties such as initialization discipline, schema consistency, or error handling. Six classes of bugs compile, pass the verifier, and silently cause data corruption or information leaks."
        },
        {
            "kind": "FailureMode",
            "id_prefix": "fail",
            "name": "KASLR slide leak via eBPF ring-buffer events",
            "description": "Ten open-source eBPF programs leak previously traced events through ring-buffer or stack-resident event records. These records carry fully decodable prior traced events including user-identifying paths and kernel-text return addresses sufficient to recover the KASLR slide on every emitted event — a concrete kernel security vulnerability."
        },
        {
            "kind": "Proposal",
            "id_prefix": "prop",
            "name": "LLM-based eBPF C-to-Rust migration with formal equivalence",
            "description": "Heimdall uses LLMs to translate libbpf C programs to Aya Rust, iteratively repairs compilation and kernel-verifier failures, rejects unsafe escape hatches via static analysis, and proves per-program equivalence via symbolic execution and Z3-based checking. 94.1% success rate (96/102 programs)."
        }
    ]
}


# ── Paper 5: Clove ───────────────────────────────────────────────────
# ev-arxiv-f21b9680
# 2026.
#
# Abstract analysis: Object-level management of tiered memory addresses
# inefficiencies in page-based systems, but for CXL memory it's
# underexplored due to CXL's tight performance budget and load/store
# interface. Existing approaches are limited to unmanaged languages
# with bespoke runtimes.
#
# Key insight: managed runtimes (JVM, etc.) already provide highly
# optimized mechanisms for object relocation and dynamic code generation
# — closely related to what object-level CXL management needs. But they
# lack hotness tracking and relocation policies.
#
# Clove extends the JVM with profile-guided object hotness tracking
# and object relocation policies for CXL. Reduces application slowdown
# by 22-84% compared to page-based tiering systems.

CLOVE = {
    "ev_id": "ev-arxiv-f21b9680",
    "brief": {
        "key_ideas": [
            "Identifies a new design point for CXL memory management: managed language runtimes (JVM, .NET) already have optimized object relocation and dynamic code generation — closely related to what object-level CXL tiering needs, but lacking hotness tracking and relocation policies",
            "Extends the JVM with profile-guided object hotness tracking that monitors access frequency at object granularity rather than page granularity — enables placing individual hot objects on fast DRAM tier and cold objects on CXL tier",
            "Combines object-level hotness tracking with GC-integrated relocation policies — objects are migrated between tiers during garbage collection, amortizing the cost of tier migration into existing GC pauses",
            "Reduces application slowdown by 22-84% compared to page-based CXL tiering systems (like Linux's NUMA balancing / AutoNUMA), demonstrating that object-level granularity significantly outperforms page-level for managed workloads"
        ],
        "relevance": "Directly challenges the kernel's page-based approach to CXL memory tiering (AutoNUMA, DAMON-based migration). The 22-84% improvement over page-based systems quantifies the cost of the kernel's page-granularity blind spot for managed-language workloads. This motivates either kernel support for user-space tiering hints (e.g., madvise extensions for object-level placement) or kernel-bypass tiering where the runtime manages CXL placement directly. The GC-integrated migration approach suggests that the kernel's NUMA balancing may need to cooperate with runtime-level memory managers rather than overriding them.",
        "methodology": "JVM prototype extending an existing managed runtime with CXL-aware object hotness profiling and GC-integrated tier migration. Evaluation against page-based Linux tiering on CXL-attached memory."
    },
    "concepts": [
        "Adaptive CXL Memory Tiering",
        "NUMA Topology and Memory Policy",
        "AutoNUMA (Automatic NUMA Balancing)"
    ],
    "claims": [
        {
            "kind": "Problem",
            "id_prefix": "prob",
            "name": "Page-granularity CXL tiering is coarse for managed workloads",
            "description": "Kernel page-based CXL tiering (AutoNUMA, DAMON) operates at 4KB/2MB page granularity but managed-language applications allocate many small objects with varying hotness on the same page. A single hot object pins an entire cold page on the fast DRAM tier, wasting fast-tier capacity."
        },
        {
            "kind": "Observation",
            "id_prefix": "obs",
            "name": "Managed runtimes already have object relocation infrastructure",
            "description": "JVM and similar managed runtimes provide highly optimized mechanisms for object relocation (GC compaction) and dynamic code generation (JIT recompilation of pointer updates). These mechanisms are closely related to what object-level CXL tiering needs but lack hotness tracking and tier-placement policies."
        },
        {
            "kind": "Proposal",
            "id_prefix": "prop",
            "name": "GC-integrated object-level CXL tier migration",
            "description": "Clove extends the JVM with profile-guided object hotness tracking and GC-integrated relocation policies. Objects are migrated between DRAM and CXL tiers during garbage collection pauses, amortizing migration cost into existing GC overhead."
        },
        {
            "kind": "PerformanceProfile",
            "id_prefix": "perf",
            "name": "Object-level vs page-level CXL tiering performance",
            "description": "Clove reduces application slowdown by 22-84% compared to page-based Linux CXL tiering systems, quantifying the cost of the kernel's page-granularity blind spot for managed-language workloads."
        }
    ]
}


# ── Insertion logic ──────────────────────────────────────────────────

ALL_PAPERS = [ACTPLANE, KOPS, AQUIFER, HEIMDALL, CLOVE]


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")

    # Build concept name → id map
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

        # Check if ResearchBrief already exists for this evidence
        existing = conn.execute(
            "SELECT 1 FROM nodes rb JOIN edges re ON re.source_id = rb.id "
            "WHERE rb.kind = 'ResearchBrief' AND re.kind = 'extracted-from' AND re.target_id = ?",
            (ev_id,),
        ).fetchone()
        if existing:
            print(f"  SKIP (brief exists): {ev_id}")
            continue

        # Get title and date from Source
        title_row = conn.execute(
            "SELECT json_extract(s.attrs, '$.title'), json_extract(s.attrs, '$.published_date') "
            "FROM edges se JOIN nodes s ON s.id = se.target_id "
            "WHERE se.kind = 'sourced-from' AND se.source_id = ?",
            (ev_id,),
        ).fetchone()
        title = title_row[0] if title_row else ""
        date = title_row[1] if title_row else "2026-01-01"

        # Create ResearchBrief node
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
                        "artifact_class": "A",  # Class A = deep analysis with abstract
                    }
                ),
            ),
        )
        conn.execute(
            "INSERT INTO edges (kind, source_id, target_id, attrs) VALUES ('extracted-from', ?, ?, '{}')",
            (brief_id, ev_id),
        )
        stats["briefs"] += 1

        # Create concept links
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

        # Create structured claim nodes
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
            # Link claim to evidence
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
    print(
        f"\nCreated {stats['briefs']} briefs, {stats['claims']} claims, {stats['edges']} edges"
    )
    print(f"Totals: {total_briefs} briefs, {total_claims} claims in DB")
    conn.close()


if __name__ == "__main__":
    main()
