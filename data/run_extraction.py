"""Manual extraction script — feeds pre-crafted LLM responses through the pipeline."""
import json
import sqlite3
import sys
sys.path.insert(0, "src")

from ingest.extractor import extract_concepts
from ingest.gate import SessionGate

EVIDENCE_RESPONSES = {
    "ev-b01c5353e809": {  # RCU
        "concepts": [
            {
                "name": "Read-Copy-Update",
                "description": "A synchronization mechanism optimized for read-heavy workloads that splits data updates into separate removal and reclamation phases. Readers access shared data without any locking or atomic operations, achieving zero read-side overhead. Updaters make changes by creating new versions of data structures and deferring destruction of old versions until all pre-existing readers have finished.",
                "key_properties": [
                    "Zero read-side overhead — no locks, no atomics, no cache-line bouncing",
                    "Grace period-based deferred reclamation",
                    "Publish-subscribe pointer semantics via rcu_assign_pointer/rcu_dereference",
                    "Readers and updaters can execute concurrently without coordination",
                    "Linear read scalability across CPUs"
                ],
                "tradeoffs": [
                    "Memory overhead from coexisting old and new data versions during grace periods",
                    "Write-side latency from grace period wait (synchronize_rcu may block milliseconds to seconds)",
                    "Requires separate locking for concurrent updaters"
                ],
                "design_rationale": "Chosen over reader-writer locks because RCU eliminates all read-side cache-line bouncing, providing orders-of-magnitude better scalability for read-dominated workloads on modern multiprocessor hardware.",
                "subsystem": "Synchronization",
                "relationships": [
                    {"target": "Grace Period", "kind": "prerequisite", "reason": "RCU's correctness depends on grace periods to ensure all pre-existing readers finish before reclaiming memory."},
                    {"target": "Quiescent State Detection", "kind": "prerequisite", "reason": "Grace periods rely on detecting quiescent states on all CPUs to determine when readers have completed."}
                ],
                "invariants": [
                    {
                        "predicate": "No reader can observe a partially-updated data structure — readers see either the complete old version or the complete new version, never a mix",
                        "strength": "safety",
                        "scope": "per-operation",
                        "failure_modes": [
                            {"symptom": "Data corruption from reading a half-initialized pointer target", "blast_radius": "kernel-wide", "recoverability": "data-loss"},
                            {"symptom": "Use-after-free if reclamation occurs before all readers finish", "blast_radius": "kernel-wide", "recoverability": "data-loss"}
                        ]
                    },
                    {
                        "predicate": "No sleeping or blocking is permitted within an RCU read-side critical section for classic (non-preemptible) RCU",
                        "strength": "safety",
                        "scope": "per-operation",
                        "failure_modes": [
                            {"symptom": "Grace period stall — synchronize_rcu blocks indefinitely because a CPU cannot report a quiescent state", "blast_radius": "kernel-wide", "recoverability": "requires-restart"}
                        ]
                    },
                    {
                        "predicate": "Every grace period must eventually complete — all CPUs must pass through a quiescent state in bounded time",
                        "strength": "liveness",
                        "scope": "system-wide",
                        "failure_modes": [
                            {"symptom": "Memory exhaustion from unbounded deferred-free queue growth", "blast_radius": "kernel-wide", "recoverability": "requires-restart"}
                        ]
                    }
                ],
                "performance_profiles": [
                    {
                        "metric": "Read-side latency",
                        "complexity": "O(1)",
                        "best_case": "Zero overhead — rcu_read_lock compiles to nothing on non-preemptible kernels",
                        "worst_case": "Preemption-disable overhead on CONFIG_PREEMPT_RCU kernels (~tens of nanoseconds)",
                        "typical_case": "Zero overhead on most kernel configurations",
                        "conditions": "Non-preemptible kernel configuration (most servers)"
                    },
                    {
                        "metric": "Write-side grace period latency",
                        "complexity": "O(nr_cpus)",
                        "best_case": "One scheduling tick per CPU (~1-4ms on idle system)",
                        "worst_case": "Seconds if CPUs run long non-preemptible code paths",
                        "typical_case": "Low single-digit milliseconds",
                        "conditions": "Standard server workload with regular context switches"
                    }
                ]
            },
            {
                "name": "Grace Period",
                "description": "A time interval during which every CPU in the system executes at least one quiescent state, guaranteeing that all pre-existing RCU read-side critical sections have completed. Grace periods form the temporal boundary between safe and unsafe memory reclamation, enabling lock-free readers by deferring destruction.",
                "key_properties": [
                    "Bounded completion — every CPU must eventually pass through a quiescent state",
                    "Only waits for pre-existing readers, not new ones that start during the period",
                    "Can be synchronous (synchronize_rcu blocks) or asynchronous (call_rcu registers callback)",
                    "Quiescent state varies by RCU flavor (context switch, softirq completion, preemption)"
                ],
                "tradeoffs": [
                    "Latency of grace period delays memory reclamation",
                    "Memory accumulation during long grace periods under heavy update load"
                ],
                "design_rationale": "Deferred destruction via grace periods avoids the need for per-object reference counting or garbage collection, trading temporary memory overhead for elimination of read-side synchronization.",
                "subsystem": "Synchronization",
                "relationships": [
                    {"target": "Quiescent State Detection", "kind": "prerequisite", "reason": "A grace period completes only when quiescent states have been detected on all CPUs."},
                    {"target": "Read-Copy-Update", "kind": "refines", "reason": "Grace periods are the mechanism that makes RCU's deferred reclamation safe."}
                ],
                "invariants": [
                    {
                        "predicate": "A grace period does not complete until every CPU has passed through at least one quiescent state since the grace period began",
                        "strength": "safety",
                        "scope": "system-wide",
                        "failure_modes": [
                            {"symptom": "Use-after-free — memory reclaimed while a reader still holds a reference", "blast_radius": "kernel-wide", "recoverability": "data-loss"}
                        ]
                    }
                ],
                "performance_profiles": [
                    {
                        "metric": "Grace period duration",
                        "complexity": "O(nr_cpus)",
                        "best_case": "Single scheduling tick across all CPUs (~1ms)",
                        "worst_case": "Multiple seconds under heavy non-preemptible workloads",
                        "typical_case": "Low single-digit milliseconds on active systems",
                        "conditions": "All CPUs regularly context-switching"
                    }
                ]
            },
            {
                "name": "Quiescent State Detection",
                "description": "The mechanism by which the kernel determines that a CPU has exited all RCU read-side critical sections. Different RCU flavors define different events as quiescent states: context switches for classic RCU, softirq completion for RCU-bh, and preemption/interrupt enabling for RCU-sched. Aggregating quiescent states across all CPUs determines grace period completion.",
                "key_properties": [
                    "Per-CPU tracking of quiescent state passage",
                    "Different quiescent state definitions per RCU flavor",
                    "No explicit reader-to-detector communication required",
                    "Leverages existing kernel scheduling events as implicit signals"
                ],
                "tradeoffs": [
                    "Different RCU flavors needed for different execution contexts",
                    "Complexity of tracking quiescent states accurately on preemptible kernels"
                ],
                "design_rationale": "By defining quiescent states as naturally-occurring kernel events (context switches), the detection mechanism piggybacks on existing scheduler infrastructure without adding new synchronization points.",
                "subsystem": "Synchronization",
                "relationships": [
                    {"target": "Grace Period", "kind": "refines", "reason": "Quiescent state detection is the implementation mechanism that drives grace period completion."}
                ],
                "invariants": [
                    {
                        "predicate": "A quiescent state on a CPU implies no RCU read-side critical section is active on that CPU at that moment",
                        "strength": "safety",
                        "scope": "per-operation",
                        "failure_modes": [
                            {"symptom": "Premature grace period completion leads to use-after-free", "blast_radius": "kernel-wide", "recoverability": "data-loss"}
                        ]
                    }
                ],
                "performance_profiles": []
            }
        ],
        "interaction_protocols": [
            {
                "rule": "RCU read-side critical sections must not contain blocking or sleeping operations in classic (non-preemptible) RCU — blocking prevents the CPU from reporting a quiescent state",
                "ordering": "never-during",
                "violation_mode": "Grace period stall causing system-wide hang or memory exhaustion from growing callback queue",
                "concept_a": "Read-Copy-Update",
                "concept_b": "Grace Period"
            }
        ],
        "compatibility_assessments": [],
        "comparative_analyses": []
    },
    "ev-159c0f56c081": {  # Locking/Spinlocks
        "concepts": [
            {
                "name": "Spinlock",
                "description": "A mutual exclusion primitive where waiting threads busy-wait (spin) in a tight loop until the lock becomes available. Spinlocks provide the simplest and lowest-latency locking in the kernel, suitable for short critical sections where sleeping would be more expensive than spinning. They include implicit memory barriers at acquire and release points.",
                "key_properties": [
                    "Busy-wait acquisition — no sleeping or context switching on contention",
                    "Implicit ACQUIRE barrier on lock, RELEASE barrier on unlock",
                    "Non-recursive — attempting to re-acquire a held lock deadlocks",
                    "Multiple variants for different interrupt contexts (irqsave, irq, bh, plain)"
                ],
                "tradeoffs": [
                    "CPU waste from busy-waiting under contention",
                    "Cache-line bouncing on NUMA systems when multiple CPUs contend",
                    "Must not sleep while holding — restricts callable functions"
                ],
                "design_rationale": "Spinlocks are the lowest-overhead mutual exclusion primitive for short critical sections where the expected hold time is less than the cost of a context switch, making them the foundation of kernel synchronization.",
                "subsystem": "Synchronization",
                "relationships": [
                    {"target": "IRQ-Safe Spinlock", "kind": "refines", "reason": "IRQ-safe variants extend the basic spinlock with interrupt disabling to prevent deadlocks from interrupt handlers."},
                    {"target": "Reader-Writer Spinlock", "kind": "refines", "reason": "Reader-writer spinlocks extend basic spinlocks to allow concurrent readers while maintaining exclusive writer access."}
                ],
                "invariants": [
                    {
                        "predicate": "A CPU must never attempt to acquire a spinlock it already holds — no recursive acquisition is supported",
                        "strength": "safety",
                        "scope": "per-operation",
                        "failure_modes": [
                            {"symptom": "Deadlock — the CPU spins forever waiting for itself to release the lock", "blast_radius": "kernel-wide", "recoverability": "requires-restart"}
                        ]
                    },
                    {
                        "predicate": "Code executing under a held spinlock must not sleep, yield, or call any function that might sleep",
                        "strength": "safety",
                        "scope": "per-operation",
                        "failure_modes": [
                            {"symptom": "Deadlock — sleeping CPU cannot release the lock; other CPUs spin indefinitely", "blast_radius": "kernel-wide", "recoverability": "requires-restart"}
                        ]
                    },
                    {
                        "predicate": "When multiple spinlocks must be held simultaneously, all code paths must acquire them in a globally consistent order",
                        "strength": "safety",
                        "scope": "system-wide",
                        "failure_modes": [
                            {"symptom": "ABBA deadlock — two CPUs each hold one lock and spin waiting for the other", "blast_radius": "kernel-wide", "recoverability": "requires-restart"}
                        ]
                    }
                ],
                "performance_profiles": [
                    {
                        "metric": "Uncontended acquisition latency",
                        "complexity": "O(1)",
                        "best_case": "10-20 CPU cycles on modern hardware",
                        "worst_case": "~50 cycles with memory barriers on weakly-ordered architectures",
                        "typical_case": "10-30 cycles",
                        "conditions": "No contention, lock cacheline is local"
                    },
                    {
                        "metric": "Contended throughput",
                        "complexity": "O(nr_cpus)",
                        "best_case": "Linear degradation with 2-3 CPUs contending",
                        "worst_case": "Severe cache-line bouncing on NUMA with many contending CPUs",
                        "typical_case": "Acceptable with low contention ratios (<10% of hold time)",
                        "conditions": "NUMA multi-socket system"
                    }
                ]
            },
            {
                "name": "IRQ-Safe Spinlock",
                "description": "A spinlock variant that disables local interrupts before acquisition and restores them on release. This prevents the deadlock scenario where an interrupt handler on the same CPU tries to acquire a spinlock already held by the interrupted code. The irqsave/irqrestore variant preserves the prior interrupt state for safe nesting.",
                "key_properties": [
                    "Disables local interrupts before acquiring the lock",
                    "Prevents same-CPU interrupt handler deadlocks",
                    "irqsave variant preserves and restores prior interrupt state",
                    "Slightly higher overhead than plain spinlocks due to interrupt manipulation"
                ],
                "tradeoffs": [
                    "Higher latency than plain spinlock due to interrupt disable/enable",
                    "Increases interrupt latency on the holding CPU"
                ],
                "design_rationale": "Required whenever a lock may be acquired in both process context and interrupt context, because a plain spinlock would deadlock if an interrupt fires on the same CPU while the lock is held.",
                "subsystem": "Synchronization",
                "relationships": [
                    {"target": "Spinlock", "kind": "refines", "reason": "IRQ-safe spinlocks add interrupt disabling to the base spinlock mechanism."}
                ],
                "invariants": [
                    {
                        "predicate": "Any spinlock that may be acquired in interrupt context must always be acquired with the IRQ-safe variant, even in process context",
                        "strength": "safety",
                        "scope": "system-wide",
                        "failure_modes": [
                            {"symptom": "Deadlock — interrupt handler on same CPU spins on lock held by interrupted process-context code", "blast_radius": "kernel-wide", "recoverability": "requires-restart"}
                        ]
                    }
                ],
                "performance_profiles": [
                    {
                        "metric": "Acquisition latency",
                        "complexity": "O(1)",
                        "best_case": "30-50 cycles with interrupt save/restore",
                        "worst_case": "Same as contended spinlock plus interrupt disable overhead",
                        "typical_case": "30-60 cycles uncontended",
                        "conditions": "No contention"
                    }
                ]
            },
            {
                "name": "Reader-Writer Spinlock",
                "description": "A spinlock variant that permits multiple concurrent readers while requiring exclusive access for writers. Read-heavy workloads benefit from concurrent read access, but the implementation requires more atomic operations than a plain spinlock. Read locks cannot be upgraded to write locks.",
                "key_properties": [
                    "Multiple concurrent readers allowed",
                    "Exclusive writer access — no readers or writers may hold concurrently",
                    "Higher atomic operation overhead than plain spinlocks",
                    "No read-to-write upgrade — must acquire write lock from the outset"
                ],
                "tradeoffs": [
                    "Higher per-operation overhead than plain spinlocks from additional atomics",
                    "Writer starvation possible under continuous read load",
                    "RCU provides better performance for most read-heavy use cases"
                ],
                "design_rationale": "Provides a middle ground between plain spinlocks (exclusive only) and RCU (requires careful API usage) for data structures with moderate read-to-write ratios where RCU's complexity is not warranted.",
                "subsystem": "Synchronization",
                "relationships": [
                    {"target": "Spinlock", "kind": "refines", "reason": "Reader-writer spinlocks extend the basic spinlock with shared-read/exclusive-write semantics."}
                ],
                "invariants": [
                    {
                        "predicate": "A read lock cannot be upgraded to a write lock — attempting to acquire a write lock while holding a read lock causes deadlock",
                        "strength": "safety",
                        "scope": "per-operation",
                        "failure_modes": [
                            {"symptom": "Self-deadlock — thread holds read lock and spins waiting for write lock that requires all read locks to be released", "blast_radius": "kernel-wide", "recoverability": "requires-restart"}
                        ]
                    }
                ],
                "performance_profiles": [
                    {
                        "metric": "Read acquisition overhead",
                        "complexity": "O(1)",
                        "best_case": "20-40 cycles with atomic increment",
                        "worst_case": "Cache-line contention from multiple readers updating shared counter",
                        "typical_case": "20-50 cycles",
                        "conditions": "Moderate reader concurrency"
                    }
                ]
            }
        ],
        "interaction_protocols": [
            {
                "rule": "When acquiring multiple spinlocks, the lock that may be taken in interrupt context must be acquired first (with IRQ disabling), then the process-context lock — reverse order for release",
                "ordering": "before",
                "violation_mode": "Deadlock from interrupt handler acquiring the interrupt-context lock while process context holds it with interrupts enabled",
                "concept_a": "IRQ-Safe Spinlock",
                "concept_b": "Spinlock"
            }
        ],
        "compatibility_assessments": [
            {
                "synergy": "antagonistic",
                "rationale": "Reader-writer spinlocks have higher overhead per operation than plain spinlocks and provide no benefit when write operations are frequent, making them worse than a plain spinlock in write-heavy scenarios",
                "conditions": "Write-heavy workloads with >30% write operations",
                "concept_a": "Reader-Writer Spinlock",
                "concept_b": "Spinlock"
            }
        ],
        "comparative_analyses": [
            {
                "dimension": "Read-side latency",
                "winner": "Spinlock",
                "conditions": "Single reader, no contention",
                "quantitative_delta": "Spinlock ~10-30 cycles vs rwlock ~20-50 cycles",
                "concept_a": "Spinlock",
                "concept_b": "Reader-Writer Spinlock"
            }
        ]
    },
    "ev-693fd54d9af4": {  # CFS Scheduler
        "concepts": [
            {
                "name": "Virtual Runtime Scheduling",
                "description": "A scheduling algorithm that tracks each task's normalized CPU consumption as 'virtual runtime' (vruntime) measured in nanoseconds. The scheduler always selects the task with the smallest vruntime, approximating an ideal fair CPU that runs all tasks simultaneously at equal speed. Task weights from nice levels adjust the rate at which vruntime accumulates.",
                "key_properties": [
                    "Nanosecond-precision vruntime accounting, independent of timer tick frequency",
                    "Always picks the task with smallest vruntime (least-served task)",
                    "No fixed timeslices — scheduling granularity is dynamic",
                    "No heuristics for interactivity detection — fairness emerges from the mechanism",
                    "Task weights from nice levels scale vruntime accumulation rate"
                ],
                "tradeoffs": [
                    "More complex than fixed-timeslice schedulers",
                    "Slight overhead from maintaining sorted task data structure"
                ],
                "design_rationale": "By modeling an ideal fair CPU and using vruntime to track deviation from perfect fairness, the scheduler inherently handles interactivity without heuristics that can be exploited or tuned incorrectly.",
                "subsystem": "Scheduler",
                "relationships": [
                    {"target": "Red-Black Tree Runqueue", "kind": "prerequisite", "reason": "Virtual runtime scheduling requires an efficient sorted data structure to find the task with smallest vruntime."},
                    {"target": "Scheduling Classes", "kind": "refines", "reason": "Virtual runtime scheduling is implemented as the CFS scheduling class within the extensible scheduling class framework."}
                ],
                "invariants": [
                    {
                        "predicate": "A running task's vruntime monotonically increases — it is never decremented during execution",
                        "strength": "structural",
                        "scope": "per-object",
                        "failure_modes": [
                            {"symptom": "Unfairness — a task with artificially low vruntime monopolizes the CPU", "blast_radius": "subsystem", "recoverability": "self-healing"}
                        ]
                    },
                    {
                        "predicate": "The per-runqueue min_vruntime value monotonically increases, tracking the minimum vruntime among all queued tasks",
                        "strength": "structural",
                        "scope": "per-object",
                        "failure_modes": [
                            {"symptom": "Newly waking tasks get unfair advantage or disadvantage from incorrect timeline positioning", "blast_radius": "subsystem", "recoverability": "self-healing"}
                        ]
                    }
                ],
                "performance_profiles": [
                    {
                        "metric": "Task selection latency",
                        "complexity": "O(1)",
                        "best_case": "Cached leftmost node access in constant time",
                        "worst_case": "O(1) with cached leftmost pointer",
                        "typical_case": "Constant time via cached pointer to minimum-vruntime task",
                        "conditions": "Standard CFS with rbtree and cached leftmost"
                    }
                ]
            },
            {
                "name": "Red-Black Tree Runqueue",
                "description": "The data structure backing CFS that organizes runnable tasks as a self-balancing binary search tree keyed by virtual runtime. The leftmost node (smallest vruntime) is the next task to execute. As tasks run and accumulate vruntime, they migrate rightward through the tree, eventually yielding the leftmost position to other tasks.",
                "key_properties": [
                    "O(log n) insertion and deletion of tasks",
                    "Constant-time access to the leftmost (minimum vruntime) node via caching",
                    "Eliminates the 'array switch' artifacts of prior O(1) scheduler",
                    "Timeline-based ordering — tasks naturally progress left-to-right as they execute"
                ],
                "tradeoffs": [
                    "O(log n) insert/remove overhead vs O(1) for array-based runqueues",
                    "Higher per-operation constant factor than simple arrays"
                ],
                "design_rationale": "A red-black tree provides the optimal balance between insert/delete performance and sorted-order access, while eliminating the discrete priority-level buckets and array-switch latency spikes of the prior scheduler.",
                "subsystem": "Scheduler",
                "relationships": [
                    {"target": "Virtual Runtime Scheduling", "kind": "refines", "reason": "The rbtree is the implementation mechanism that enables efficient lookup of the task with minimum vruntime."}
                ],
                "invariants": [
                    {
                        "predicate": "The rbtree maintains correct sorted order by vruntime at all times — the leftmost node always has the minimum vruntime",
                        "strength": "structural",
                        "scope": "per-object",
                        "failure_modes": [
                            {"symptom": "Wrong task selected for execution, causing fairness violations or starvation", "blast_radius": "subsystem", "recoverability": "self-healing"}
                        ]
                    }
                ],
                "performance_profiles": [
                    {
                        "metric": "Task insertion latency",
                        "complexity": "O(log n)",
                        "best_case": "Few nanoseconds with small task count",
                        "worst_case": "Microseconds with hundreds of runnable tasks plus rebalancing",
                        "typical_case": "Sub-microsecond for typical desktop/server task counts",
                        "conditions": "Standard server workload with 10-100 runnable tasks"
                    }
                ]
            },
            {
                "name": "Scheduling Classes",
                "description": "An extensible framework that encapsulates scheduling policies as modular classes with a well-defined function-pointer interface. The core scheduler dispatches to class methods (enqueue, dequeue, pick_next, tick) without knowing implementation details. Classes are prioritized — real-time classes run before CFS, and CFS runs before idle.",
                "key_properties": [
                    "Modular policy encapsulation via function-pointer dispatch table (sched_class)",
                    "Priority ordering — RT class > CFS class > idle class",
                    "Core scheduler is policy-agnostic, iterating classes by priority",
                    "Each class implements: enqueue_task, dequeue_task, pick_next_task, task_tick, wakeup_preempt"
                ],
                "tradeoffs": [
                    "Indirection overhead from function pointer dispatch",
                    "Priority ordering means RT tasks can starve CFS tasks"
                ],
                "design_rationale": "Separating scheduling policy from mechanism allows independent development of different scheduling algorithms (fair, real-time, deadline, idle) without modifying the core scheduler, enabling kernel modularity and experimentation.",
                "subsystem": "Scheduler",
                "relationships": [
                    {"target": "Virtual Runtime Scheduling", "kind": "prerequisite", "reason": "CFS is implemented as one scheduling class within this framework."}
                ],
                "invariants": [
                    {
                        "predicate": "Scheduling classes are consulted in strict priority order — a higher-priority class always gets to run its tasks before lower-priority classes are considered",
                        "strength": "structural",
                        "scope": "system-wide",
                        "failure_modes": [
                            {"symptom": "Priority inversion — lower-priority scheduling class tasks run when higher-priority tasks are available", "blast_radius": "subsystem", "recoverability": "self-healing"}
                        ]
                    }
                ],
                "performance_profiles": []
            }
        ],
        "interaction_protocols": [
            {
                "rule": "Real-time scheduling class tasks always preempt CFS tasks — the RT class has strictly higher priority and is always consulted first by pick_next_task",
                "ordering": "before",
                "violation_mode": "RT task latency violation — real-time guarantees broken if CFS tasks run when RT tasks are runnable",
                "concept_a": "Scheduling Classes",
                "concept_b": "Virtual Runtime Scheduling"
            }
        ],
        "compatibility_assessments": [
            {
                "synergy": "synergistic",
                "rationale": "The red-black tree provides exactly the O(log n) sorted access that virtual runtime scheduling needs to efficiently find the minimum-vruntime task, and the caching of the leftmost node brings selection to O(1)",
                "conditions": "Standard CFS scheduling with any task count",
                "concept_a": "Virtual Runtime Scheduling",
                "concept_b": "Red-Black Tree Runqueue"
            }
        ],
        "comparative_analyses": []
    },
    "ev-1e83fb7dcf49": {  # VM/Page Tables
        "concepts": [
            {
                "name": "Hierarchical Page Tables",
                "description": "A five-level tree structure (PGD→P4D→PUD→PMD→PTE) that maps virtual addresses to physical page frames. Each level is an array of pointers to the next level, with the final PTE level containing the actual virtual-to-physical mappings. Unused levels are 'folded' at compile time on architectures with fewer levels, maintaining a uniform traversal API.",
                "key_properties": [
                    "Five levels: PGD, P4D, PUD, PMD, PTE",
                    "Sparse-friendly — unmapped regions consume no page table memory at upper levels",
                    "Level folding for architectures with fewer than 5 levels",
                    "Architecture-neutral traversal API (pgd_offset, p4d_offset, etc.)",
                    "Supports huge pages at PMD (2MB) and PUD (1GB) levels"
                ],
                "tradeoffs": [
                    "Multi-level walk latency on TLB miss (~10-100 cycles per level)",
                    "Memory overhead for page table pages themselves",
                    "Complexity of maintaining consistency across five levels"
                ],
                "design_rationale": "Hierarchical tables efficiently handle sparse virtual address spaces by avoiding allocation of page table memory for unmapped regions, while the uniform five-level API ensures portability across architectures with varying page table depths.",
                "subsystem": "Virtual Memory",
                "relationships": [
                    {"target": "Translation Lookaside Buffer", "kind": "prerequisite", "reason": "TLBs cache page table translations to avoid the expensive multi-level page table walk on every memory access."},
                    {"target": "Huge Page Mapping", "kind": "refines", "reason": "Huge pages are implemented by terminating the page table walk at an upper level (PMD or PUD) instead of descending to the PTE level."}
                ],
                "invariants": [
                    {
                        "predicate": "Architecture-neutral code must always traverse all five page table levels — folded levels are handled transparently by no-op offset/alloc functions",
                        "strength": "structural",
                        "scope": "system-wide",
                        "failure_modes": [
                            {"symptom": "Incorrect address translation causing kernel panic or silent data corruption", "blast_radius": "kernel-wide", "recoverability": "data-loss"}
                        ]
                    },
                    {
                        "predicate": "A given virtual address in a given address space maps to at most one physical page frame at any point in time",
                        "strength": "safety",
                        "scope": "per-object",
                        "failure_modes": [
                            {"symptom": "Aliased mappings cause data corruption when two virtual addresses unexpectedly map to the same physical page", "blast_radius": "kernel-wide", "recoverability": "data-loss"}
                        ]
                    }
                ],
                "performance_profiles": [
                    {
                        "metric": "Page table walk latency",
                        "complexity": "O(levels)",
                        "best_case": "Single memory access for 1GB huge page (PUD-level termination)",
                        "worst_case": "5 sequential memory accesses for 4KB page (all 5 levels)",
                        "typical_case": "2-4 memory accesses depending on huge page usage and folded levels",
                        "conditions": "TLB miss requiring full page table walk"
                    }
                ]
            },
            {
                "name": "Translation Lookaside Buffer",
                "description": "A hardware cache within the MMU that stores recent virtual-to-physical address translations to avoid the expensive multi-level page table walk on every memory access. TLB entries must be explicitly invalidated when page table entries change, requiring inter-processor interrupts (TLB shootdowns) on SMP systems to maintain coherence.",
                "key_properties": [
                    "Hardware-managed cache of page table translations",
                    "Limited capacity (typically 64-1024 entries for L1 dTLB)",
                    "Each entry covers one page (4KB standard, 2MB/1GB for huge pages)",
                    "Requires explicit invalidation (flush) on page table changes",
                    "TLB shootdowns via IPI needed on SMP systems for coherence"
                ],
                "tradeoffs": [
                    "Limited capacity creates pressure under large working sets",
                    "TLB shootdown IPIs add latency to page table modifications on SMP",
                    "Stale TLB entries from missed invalidation cause security vulnerabilities"
                ],
                "design_rationale": "Hardware TLB caching makes virtual memory practical by reducing the common-case translation cost to zero, amortizing the expensive page table walk across many accesses to the same page.",
                "subsystem": "Virtual Memory",
                "relationships": [
                    {"target": "Hierarchical Page Tables", "kind": "refines", "reason": "TLBs cache the results of page table walks to avoid repeating the multi-level traversal."},
                    {"target": "Huge Page Mapping", "kind": "prerequisite", "reason": "Huge pages reduce TLB pressure by covering 2MB or 1GB per TLB entry instead of 4KB."}
                ],
                "invariants": [
                    {
                        "predicate": "When page table entries change (unmapping, permission change, migration), corresponding TLB entries must be invalidated on ALL CPUs that may have cached the translation",
                        "strength": "safety",
                        "scope": "system-wide",
                        "failure_modes": [
                            {"symptom": "Stale TLB entry causes reads/writes to wrong physical page — data corruption or security bypass", "blast_radius": "kernel-wide", "recoverability": "data-loss"},
                            {"symptom": "Access to freed memory via stale translation — use-after-free exploitable for privilege escalation", "blast_radius": "kernel-wide", "recoverability": "data-loss"}
                        ]
                    }
                ],
                "performance_profiles": [
                    {
                        "metric": "TLB hit rate",
                        "complexity": "O(1)",
                        "best_case": "99%+ for workloads with good locality, effectively zero translation overhead",
                        "worst_case": "<50% for large scattered-access working sets, dominating memory latency",
                        "typical_case": "95-99% for most server and desktop workloads",
                        "conditions": "Working set fits in TLB coverage (entries × page size)"
                    }
                ]
            },
            {
                "name": "Huge Page Mapping",
                "description": "A memory management optimization that uses page sizes larger than the standard 4KB (typically 2MB at PMD level or 1GB at PUD level). Huge pages reduce TLB pressure by covering more memory per entry and reduce page table overhead by terminating the walk at a higher level. Transparent Huge Pages (THP) can automatically promote contiguous 4KB pages without application changes.",
                "key_properties": [
                    "2MB pages mapped at PMD level, 1GB pages at PUD level",
                    "Reduces TLB pressure by 512x (2MB) or 262144x (1GB) per entry",
                    "Fewer page table levels traversed on TLB miss",
                    "Transparent Huge Pages (THP) provide automatic promotion via khugepaged",
                    "Significant benefit for memory-intensive workloads (databases, HPC)"
                ],
                "tradeoffs": [
                    "Internal fragmentation when only part of a huge page is used",
                    "Physical memory fragmentation makes allocation harder over time",
                    "Less granular permission control — permissions apply to entire 2MB/1GB region"
                ],
                "design_rationale": "Huge pages trade finer-grained memory management for dramatically improved TLB efficiency, which is the dominant performance factor for memory-intensive workloads with large working sets.",
                "subsystem": "Virtual Memory",
                "relationships": [
                    {"target": "Translation Lookaside Buffer", "kind": "refines", "reason": "Huge pages directly address TLB capacity limitations by covering more memory per entry."},
                    {"target": "Hierarchical Page Tables", "kind": "refines", "reason": "Huge pages exploit the hierarchical structure by terminating the walk at upper levels."}
                ],
                "invariants": [
                    {
                        "predicate": "A huge page mapping must reference a physically contiguous region of the appropriate size (2MB-aligned for PMD, 1GB-aligned for PUD)",
                        "strength": "safety",
                        "scope": "per-object",
                        "failure_modes": [
                            {"symptom": "Misaligned huge page causes hardware fault or maps wrong physical memory", "blast_radius": "kernel-wide", "recoverability": "data-loss"}
                        ]
                    }
                ],
                "performance_profiles": [
                    {
                        "metric": "TLB coverage per entry",
                        "complexity": "O(1)",
                        "best_case": "1GB per TLB entry with PUD-level huge pages",
                        "worst_case": "2MB per TLB entry with PMD-level huge pages (still 512x better than 4KB)",
                        "typical_case": "2MB per entry (most common huge page size)",
                        "conditions": "Workload uses huge pages (explicit or via THP)"
                    }
                ]
            },
            {
                "name": "Page Fault Handler",
                "description": "The kernel mechanism that responds to MMU translation failures. When a virtual address cannot be resolved by the TLB or page table walk, the CPU raises a page fault exception. The handler determines the fault type (minor/major/invalid), allocates physical memory if needed, populates page table entries, and resumes the faulting instruction. It implements lazy allocation and copy-on-write optimizations.",
                "key_properties": [
                    "Handles minor faults (page present, PTE missing) with no I/O",
                    "Handles major faults (page on swap/disk) with I/O",
                    "Detects and signals invalid accesses (SIGSEGV)",
                    "Implements lazy allocation — physical pages allocated on first access",
                    "Implements copy-on-write — shared pages copied only when written"
                ],
                "tradeoffs": [
                    "Minor faults add latency to first access of lazily-allocated pages",
                    "Major faults involve disk I/O with millisecond-scale latency",
                    "OOM killer invoked as last resort when physical memory exhausted"
                ],
                "design_rationale": "Demand-paging via the fault handler allows the kernel to defer physical memory allocation until actually needed, reducing memory waste and process startup time while maintaining the illusion of a large, flat address space.",
                "subsystem": "Virtual Memory",
                "relationships": [
                    {"target": "Hierarchical Page Tables", "kind": "prerequisite", "reason": "The fault handler populates page table entries as part of resolving faults."},
                    {"target": "Translation Lookaside Buffer", "kind": "prerequisite", "reason": "Resolved translations are loaded into the TLB after the fault handler installs the PTE."}
                ],
                "invariants": [
                    {
                        "predicate": "Page table modifications during fault handling must hold the appropriate locks (mmap_lock for VMA lookup, pte_lock for PTE installation)",
                        "strength": "safety",
                        "scope": "per-operation",
                        "failure_modes": [
                            {"symptom": "Lost PTE updates from concurrent modifications — page mapped to wrong frame or mapping lost entirely", "blast_radius": "subsystem", "recoverability": "data-loss"},
                            {"symptom": "Use-after-free from page freed while another CPU installs a mapping to it", "blast_radius": "kernel-wide", "recoverability": "data-loss"}
                        ]
                    }
                ],
                "performance_profiles": [
                    {
                        "metric": "Minor fault latency",
                        "complexity": "O(levels)",
                        "best_case": "Sub-microsecond for simple PTE installation",
                        "worst_case": "Microseconds with page table allocation at multiple levels",
                        "typical_case": "Low single-digit microseconds",
                        "conditions": "Page already in memory, only PTE needs installation"
                    },
                    {
                        "metric": "Major fault latency",
                        "complexity": "O(1) + I/O",
                        "best_case": "Tens of microseconds if page is in page cache",
                        "worst_case": "Milliseconds for disk/swap I/O",
                        "typical_case": "100-1000 microseconds depending on storage",
                        "conditions": "Page must be read from swap or filesystem"
                    }
                ]
            }
        ],
        "interaction_protocols": [
            {
                "rule": "Page table modifications must acquire mmap_lock (read mode) for VMA lookup, then pte_lock for PTE installation — never modify PTEs without holding the per-page-table spinlock",
                "ordering": "before",
                "violation_mode": "Lost updates or use-after-free from concurrent page table modifications without proper serialization",
                "concept_a": "Page Fault Handler",
                "concept_b": "Hierarchical Page Tables"
            },
            {
                "rule": "After modifying or removing a page table entry, the corresponding TLB entries must be flushed on all CPUs before the physical page can be reused or freed",
                "ordering": "before",
                "violation_mode": "Stale TLB entries allow access to freed or reassigned physical pages — data corruption or security bypass",
                "concept_a": "Hierarchical Page Tables",
                "concept_b": "Translation Lookaside Buffer"
            }
        ],
        "compatibility_assessments": [
            {
                "synergy": "synergistic",
                "rationale": "Huge pages directly mitigate TLB capacity limitations by covering 512x-262144x more memory per TLB entry, making them the primary technique for reducing TLB pressure in memory-intensive workloads",
                "conditions": "Workloads with large contiguous memory regions (databases, HPC, virtual machines)",
                "concept_a": "Huge Page Mapping",
                "concept_b": "Translation Lookaside Buffer"
            }
        ],
        "comparative_analyses": [
            {
                "dimension": "TLB coverage per entry",
                "winner": "Huge Page Mapping",
                "conditions": "Comparing standard 4KB pages vs 2MB huge pages",
                "quantitative_delta": "512x more memory covered per TLB entry (2MB vs 4KB)",
                "concept_a": "Huge Page Mapping",
                "concept_b": "Hierarchical Page Tables"
            }
        ]
    },
}


class MockLLMClient:
    def __init__(self, responses):
        self._responses = responses

    def create_message(self, model, system, user, max_tokens):
        for ev_id, data in self._responses.items():
            if ev_id in getattr(self, '_current_evidence', ''):
                return {
                    "text": json.dumps(data),
                    "prompt_tokens": len(system.split()) + len(user.split()),
                    "response_tokens": len(json.dumps(data).split()),
                }
        return {"text": "{}", "prompt_tokens": 0, "response_tokens": 0}


def main():
    conn = sqlite3.connect("data/master.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")

    evidence_ids = [r[0] for r in conn.execute(
        "SELECT id FROM nodes WHERE kind = 'Evidence' ORDER BY id"
    ).fetchall()]

    print(f"Found {len(evidence_ids)} evidence nodes: {evidence_ids}")

    for ev_id in evidence_ids:
        if ev_id not in EVIDENCE_RESPONSES:
            print(f"  SKIP {ev_id} — no pre-crafted response")
            continue

        response_data = EVIDENCE_RESPONSES[ev_id]

        class DirectClient:
            def create_message(self, model, system, user, max_tokens):
                return {
                    "text": json.dumps(response_data),
                    "prompt_tokens": len(system.split()) + len(user.split()),
                    "response_tokens": len(json.dumps(response_data).split()),
                }

        gate = SessionGate()
        result = extract_concepts(
            conn, ev_id, gate,
            model="manual-extraction",
            client=DirectClient(),
        )
        conn.commit()

        print(f"  {ev_id}: {result.concepts_created} concepts, "
              f"{result.invariants_created} invariants, "
              f"{result.failure_modes_created} failure_modes, "
              f"{result.protocols_created} protocols, "
              f"{result.profiles_created} profiles, "
              f"{result.compatibilities_created} compatibilities, "
              f"{result.comparatives_created} comparatives, "
              f"subsystems={result.subsystem_ids}")

    # Summary
    for kind in ("Concept", "Subsystem", "KernelInvariant", "FailureMode",
                 "InteractionProtocol", "PerformanceProfile",
                 "CompatibilityAssessment", "ComparativeAnalysis"):
        count = conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE kind = ?", (kind,)
        ).fetchone()[0]
        print(f"  {kind}: {count}")

    edge_count = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    print(f"  Total edges: {edge_count}")
    conn.close()


if __name__ == "__main__":
    main()
