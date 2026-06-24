"""Populate Evidence excerpts and Tier 1 Concept code examples in master.db."""
import sys
import sqlite3
import json
from pathlib import Path

sys.path.insert(0, "src")
from graph.engine import update_node_attrs

# === PART 1: Evidence excerpts from source files ===

ORIGINAL_EVIDENCE = {
    "ev-b01c5353e809": "data/sources/rcu_whatisRCU.txt",
    "ev-159c0f56c081": "data/sources/locking_spinlocks.txt",
    "ev-693fd54d9af4": "data/sources/scheduler_cfs.txt",
    "ev-1e83fb7dcf49": "data/sources/mm_page_tables.txt",
}

# Synthetic excerpts for the 43 newer evidence nodes, keyed by evidence ID.
# Each maps to a brief description of what the corresponding kernel doc covers.
SYNTHETIC_EXCERPTS = {
    "ev-00ac213b0875": "The Linux block layer documentation describes the multi-queue block I/O queueing mechanism (blk-mq), request scheduling, and the bio structure used for block I/O operations. It covers how requests flow from filesystems through the block layer to device drivers.",
    "ev-072bfdc26b03": "The Transparent Huge Pages documentation explains how the kernel automatically promotes regular pages to huge pages (2MB on x86) to reduce TLB pressure. It covers khugepaged, the compaction daemon, and the /sys/kernel/mm/transparent_hugepage control interface.",
    "ev-1db19b06261f": "The NVMe driver subsystem documentation covers the Linux NVMe host driver architecture, including the NVMe over Fabrics transport abstraction, command submission via submission/completion queue pairs, and the admin vs I/O queue separation.",
    "ev-1eaff6f741b4": "The zswap documentation describes the compressed swap cache that intercepts pages being swapped out and compresses them into a dynamically allocated RAM-based pool. It covers the frontswap API integration, compression algorithms, and the writeback mechanism.",
    "ev-21c558965abf": "The FUSE documentation describes the Filesystem in Userspace interface allowing non-privileged users to create filesystems without modifying kernel code. It covers the /dev/fuse device, the request/reply protocol, and the libfuse library API.",
    "ev-25fabc113680": "The kernel cryptography documentation covers the Kernel Crypto API including symmetric ciphers (skcipher), hash algorithms (shash/ahash), AEAD, and random number generation. It describes the algorithm registration framework and the userspace AF_ALG socket interface.",
    "ev-328b366bdb64": "The power management documentation covers the Linux kernel's suspend/resume framework, runtime PM, cpuidle governors, and the cpufreq subsystem. It describes how device drivers participate in system power state transitions.",
    "ev-3531df7abab6": "The Btrfs documentation describes the B-tree copy-on-write filesystem's features including snapshots, subvolumes, checksumming, RAID support, and online defragmentation. It covers the extent-based allocation model and the balance/scrub maintenance operations.",
    "ev-371fb60e9dfe": "The namespaces documentation describes the Linux kernel's namespace abstractions for resource isolation including PID, network, mount, UTS, IPC, user, cgroup, and time namespaces. It covers the clone(), unshare(), and setns() system calls.",
    "ev-3d3f0962f417": "The SCHED_DEADLINE documentation describes the Earliest Deadline First (EDF) real-time scheduling class with Constant Bandwidth Server (CBS) throttling. It covers the sched_attr structure, admission control, and bandwidth reservation parameters (runtime, deadline, period).",
    "ev-4d32ec911f72": "The ACPI documentation covers the kernel's Advanced Configuration and Power Interface implementation, including the ACPICA interpreter, device enumeration via the ACPI namespace, thermal zones, battery management, and platform-specific quirk handling.",
    "ev-562afa30ca8e": "The page allocator documentation describes the buddy allocator system that manages physical page frames in power-of-two order blocks. It covers the zone-based allocation, watermarks, the free area lists, page migration types, and the GFP flag system.",
    "ev-5982e450fb45": "The virtio documentation describes the paravirtualized I/O framework for guest-host communication in virtualized environments. It covers virtqueues, the virtio device model, feature negotiation, and the split/packed ring buffer formats.",
    "ev-5b6428da4348": "The kernel core API documentation covers fundamental kernel services including memory allocation (kmalloc, vmalloc), string handling, linked lists, rbtrees, workqueues, wait queues, and the printk logging infrastructure.",
    "ev-5e5a1b9b339c": "The OOM killer documentation describes the kernel's out-of-memory handling mechanism that selects and terminates processes when memory is critically exhausted. It covers oom_score_adj, the badness heuristic, cgroup-aware OOM, and the oom_reaper.",
    "ev-7464db1d009b": "The workqueue documentation describes the kernel's deferred work execution framework. It covers the concurrency-managed workqueue (cmwq) design, per-CPU vs unbound workqueues, work item scheduling, and the ordered workqueue guarantee.",
    "ev-7ec1953e7490": "The cgroup v2 documentation describes the unified control group hierarchy for resource management. It covers the controller types (cpu, memory, io, pids), the single-writer rule, delegation, pressure stall information (PSI), and the threaded mode.",
    "ev-82b63fb03682": "The driver model documentation describes the Linux device model including struct device, struct device_driver, struct bus_type, and the sysfs representation. It covers device/driver binding, probe/remove lifecycle, and the platform bus abstraction.",
    "ev-88b2fc344038": "The KVM documentation describes the Kernel-based Virtual Machine architecture including the /dev/kvm ioctl interface, vCPU management, memory region mapping, interrupt injection, and the hardware-assisted virtualization (VMX/SVM) integration.",
    "ev-956dd4ebd3df": "The tracing documentation covers the Linux kernel's tracing infrastructure including ftrace, tracepoints, kprobes, uprobes, and the perf events subsystem. It describes the tracefs interface, function graph tracing, and event filtering.",
    "ev-960d2a663222": "The thermal management documentation describes the kernel's thermal framework including thermal zones, cooling devices, governors (step-wise, power-allocator), and the trip point mechanism for temperature-triggered actions.",
    "ev-9700d3360edb": "The live patching documentation describes the kernel's mechanism for applying code patches to a running kernel without rebooting. It covers the consistency model, the per-task migration approach, and the klp_enable_patch() API.",
    "ev-971c409c5a7c": "The sk_buff documentation describes the socket buffer structure that is the fundamental data structure for network packet handling in the Linux kernel. It covers the head/data/tail/end pointers, skb_put/skb_push operations, and the shared info area.",
    "ev-9b8aef2ad9d6": "The NAPI documentation describes the New API polling mechanism for high-performance network packet processing. It covers the interrupt mitigation strategy, the poll callback, GRO (Generic Receive Offload), and busy polling.",
    "ev-9dbbd0848d77": "The IPC documentation covers the Linux kernel's inter-process communication mechanisms including System V message queues, semaphores, shared memory segments, and POSIX equivalents. It describes the ipc_namespace isolation.",
    "ev-9e6d2d4c0813": "The network namespace documentation describes how the kernel isolates network stacks including interfaces, routing tables, iptables rules, and socket bindings into independent namespaces via CLONE_NEWNET.",
    "ev-9eb2e3ed70b4": "The process management documentation covers how the Linux kernel manages processes and threads, including the task_struct, process creation via fork/clone, the exec family, exit handling, and the wait/waitpid reaping mechanism.",
    "ev-a2afb88b5825": "The ext4 documentation describes the fourth extended filesystem's features including extents, delayed allocation, journal checksumming, inline data, bigalloc, and the JBD2 journaling layer. It covers mount options and tuning parameters.",
    "ev-aaf486a29e80": "The OverlayFS documentation describes the union mount filesystem that layers an upper read-write directory over one or more lower read-only directories. It covers whiteouts, opaque directories, copy-up, redirect_dir, and metacopy features.",
    "ev-aff42fd1dc93": "The EEVDF scheduler documentation describes the Earliest Eligible Virtual Deadline First algorithm that replaced CFS in Linux 6.6. It covers virtual deadline computation, eligibility lag, the latency-nice parameter, and the pick_eevdf() selection logic.",
    "ev-b8058469570b": "The EFI stub documentation describes the kernel's EFI boot stub that allows the kernel image to be loaded directly by UEFI firmware without a separate bootloader. It covers the PE/COFF header, EFI handover protocol, and memory map handling.",
    "ev-bbf87238ea5f": "The MD (Multiple Devices) documentation describes the Linux software RAID implementation supporting RAID 0, 1, 4, 5, 6, and 10 levels. It covers the mdadm management tool, reshape operations, bitmap write-intent logging, and the recovery process.",
    "ev-bcf0cb76394a": "The KSM documentation describes Kernel Same-page Merging, which scans memory for identical pages and merges them using copy-on-write. It covers the ksmd daemon, the stable/unstable tree structure, and the /sys/kernel/mm/ksm interface.",
    "ev-cfdb9d4f9df1": "The NUMA memory policy documentation describes how the kernel manages memory allocation on Non-Uniform Memory Access systems. It covers the set_mempolicy() and mbind() system calls, the default/bind/interleave/preferred policies, and cpuset integration.",
    "ev-d1d2cb8a11a1": "The TCP documentation describes the Linux kernel's TCP implementation including congestion control algorithms (CUBIC, BBR, Reno), connection state machine, TCP fast open, selective acknowledgments (SACK), and the tcp_metrics cache.",
    "ev-d9f85493914a": "The SLUB allocator documentation describes the default slab allocator's design including per-CPU freelists, partial slab lists, cache merging, and SLUB debugging facilities (red zones, poisoning, tracking). It covers kmem_cache lifecycle and tuning.",
    "ev-da698ee9226d": "The XFS documentation describes the high-performance journaling filesystem's architecture including the allocation group structure, B+tree metadata indexing, delayed logging, reverse mapping, reflink/CoW, and online repair capabilities.",
    "ev-e08400ef0166": "The VFS documentation describes the Virtual Filesystem Switch layer that provides the common interface for all Linux filesystems. It covers the superblock, inode, dentry, and file objects, the dcache, the mount system, and the path lookup algorithm.",
    "ev-e6c74e93e587": "The perf documentation describes the Linux performance monitoring subsystem including hardware performance counters, software events, tracepoints, and the perf_event_open() system call. It covers sampling, counting, and the ring buffer output mechanism.",
    "ev-e97768c8c91f": "The device-mapper documentation describes the kernel's block device mapping framework used for LVM, dm-crypt, dm-thin, dm-cache, and dm-raid targets. It covers the ioctl interface, target types, and the DM table structure.",
    "ev-ea116e7e8b39": "The USB subsystem documentation describes the Linux USB stack including host controller drivers (xHCI, EHCI), the USB core, device enumeration, the URB (USB Request Block) transfer mechanism, and the gadget/device-side framework.",
    "ev-eac7eefce791": "The security documentation covers the Linux Security Module (LSM) framework including SELinux, AppArmor, and Smack. It describes the security hooks architecture, the credential model, file/inode/task security blobs, and the seccomp-BPF filter.",
    "ev-f415f02d31bb": "The SCHED_DEADLINE documentation describes the EDF-based real-time scheduling policy with CBS bandwidth control. It covers the dl_runtime/dl_deadline/dl_period parameters, admission control, bandwidth inheritance, and the GRUB reclaiming protocol.",
}

# === PART 2: Tier 1 Concept code examples ===

TIER1_CODE_EXAMPLES = {
    "concept-bb4cc0a78416": [  # Read-Copy-Update
        {"label": "RCU read-side critical section", "language": "c",
         "code": "rcu_read_lock();\np = rcu_dereference(gp);\nif (p)\n    do_something(p->a, p->b);\nrcu_read_unlock();",
         "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/RCU/whatisRCU.rst"},
        {"label": "RCU update (publish new version)", "language": "c",
         "code": "struct foo *new_fp = kmalloc(sizeof(*new_fp), GFP_KERNEL);\n*new_fp = *gp;\nnew_fp->a = new_value;\nrcu_assign_pointer(gp, new_fp);\nsynchronize_rcu();\nkfree(old_fp);",
         "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/RCU/whatisRCU.rst"},
    ],
    "concept-fb56cad5ee43": [  # Spinlock
        {"label": "Basic spinlock acquire/release", "language": "c",
         "code": "static DEFINE_SPINLOCK(my_lock);\n\nspin_lock(&my_lock);\n/* critical section */\nspin_unlock(&my_lock);",
         "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/locking/spinlocks.rst"},
    ],
    "concept-14545804a315": [  # IRQ-Safe Spinlock
        {"label": "IRQ-safe spinlock (process context)", "language": "c",
         "code": "unsigned long flags;\n\nspin_lock_irqsave(&my_lock, flags);\n/* safe from IRQ preemption */\nspin_unlock_irqrestore(&my_lock, flags);",
         "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/locking/spinlocks.rst"},
    ],
    "concept-0e81b7fed817": [  # Reader-Writer Spinlock
        {"label": "Reader-writer lock usage", "language": "c",
         "code": "static DEFINE_RWLOCK(my_rwlock);\n\n/* Reader path */\nread_lock(&my_rwlock);\n/* read shared data */\nread_unlock(&my_rwlock);\n\n/* Writer path */\nwrite_lock(&my_rwlock);\n/* modify shared data */\nwrite_unlock(&my_rwlock);",
         "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/locking/spinlocks.rst"},
    ],
    "concept-27fa910c8200": [  # Grace Period
        {"label": "Synchronous grace period wait", "language": "c",
         "code": "list_del_rcu(&entry->list);\nsynchronize_rcu();\nkfree(entry);",
         "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/RCU/whatisRCU.rst"},
        {"label": "Asynchronous grace period (callback)", "language": "c",
         "code": "static void my_rcu_callback(struct rcu_head *rp)\n{\n    struct my_struct *p = container_of(rp, struct my_struct, rcu);\n    kfree(p);\n}\n\nlist_del_rcu(&entry->list);\ncall_rcu(&entry->rcu, my_rcu_callback);",
         "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/RCU/whatisRCU.rst"},
    ],
    "concept-7f79a75d9da4": [  # Quiescent State Detection
        {"label": "Quiescent state in context switch", "language": "c",
         "code": "/* In schedule() -- each context switch is a quiescent state */\nrcu_note_context_switch(cpu);\n/* CPU has passed through a quiescent state;\n * all prior RCU read-side critical sections complete */",
         "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/RCU/whatisRCU.rst"},
    ],
    "concept-91bcd2b57765": [  # SLUB Allocator
        {"label": "Creating and using a slab cache", "language": "c",
         "code": "static struct kmem_cache *my_cache;\n\nmy_cache = kmem_cache_create(\"my_objects\",\n    sizeof(struct my_obj), 0, SLAB_HWCACHE_ALIGN, NULL);\n\nstruct my_obj *obj = kmem_cache_alloc(my_cache, GFP_KERNEL);\n\nkmem_cache_free(my_cache, obj);\n\nkmem_cache_destroy(my_cache);",
         "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/mm/slab.rst"},
    ],
    "concept-e694b273d12c": [  # Kmalloc
        {"label": "General-purpose kernel allocation", "language": "c",
         "code": "void *buf = kmalloc(4096, GFP_KERNEL);\nvoid *irq_buf = kmalloc(256, GFP_ATOMIC);\nstruct my_struct *s = kzalloc(sizeof(*s), GFP_KERNEL);\n\nkfree(buf);\nkfree(irq_buf);\nkfree(s);",
         "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/include/linux/slab.h"},
    ],
    "concept-970f030dd376": [  # Buddy Allocator
        {"label": "Page allocation API", "language": "c",
         "code": "struct page *pages = alloc_pages(GFP_KERNEL, order);\nvoid *vaddr = page_address(pages);\n\nstruct page *pg = alloc_page(GFP_KERNEL);\nunsigned long addr = __get_free_page(GFP_KERNEL);\n\n__free_pages(pages, order);\nfree_page(addr);",
         "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/mm/page_alloc.rst"},
    ],
    "concept-50d58095b9e6": [  # Vmalloc
        {"label": "Virtually contiguous allocation", "language": "c",
         "code": "void *buf = vmalloc(1024 * 1024);  /* 1MB */\nvoid *zbuf = vzalloc(64 * PAGE_SIZE);\n\nvfree(buf);\nvfree(zbuf);",
         "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/mm/vmalloc.c"},
    ],
    "concept-1de54fb7e99f": [  # OOM Killer
        {"label": "Adjusting OOM score from userspace", "language": "bash",
         "code": "# Make process less likely to be OOM-killed\necho -1000 > /proc/self/oom_score_adj   # immune\necho 0 > /proc/self/oom_score_adj       # normal\necho 1000 > /proc/self/oom_score_adj    # kill first\n\n# Per-cgroup OOM control\necho 1 > /sys/fs/cgroup/mygroup/memory.oom.group",
         "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/filesystems/proc.rst"},
    ],
    "concept-257bd0f39d03": [  # Socket Buffer (sk_buff)
        {"label": "Allocating and building an sk_buff", "language": "c",
         "code": "struct sk_buff *skb = alloc_skb(len + headroom, GFP_KERNEL);\nskb_reserve(skb, headroom);\n\nunsigned char *data = skb_put(skb, data_len);\nmemcpy(data, payload, data_len);\n\nstruct ethhdr *eth = skb_push(skb, sizeof(*eth));\n\nkfree_skb(skb);",
         "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/networking/skbuff.rst"},
    ],
    "concept-6a17f9ac3a98": [  # NAPI Polling
        {"label": "NAPI poll handler in a network driver", "language": "c",
         "code": "static int my_driver_poll(struct napi_struct *napi, int budget)\n{\n    int work_done = 0;\n    while (work_done < budget) {\n        struct sk_buff *skb = my_receive_packet(priv);\n        if (!skb)\n            break;\n        napi_gro_receive(napi, skb);\n        work_done++;\n    }\n    if (work_done < budget) {\n        napi_complete_done(napi, work_done);\n        my_enable_irq(priv);\n    }\n    return work_done;\n}",
         "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/networking/napi.rst"},
    ],
    "concept-91e863a8282c": [  # XDP
        {"label": "Simple XDP program (eBPF C)", "language": "c",
         "code": "SEC(\"xdp\")\nint xdp_drop_filter(struct xdp_md *ctx)\n{\n    void *data = (void *)(long)ctx->data;\n    void *data_end = (void *)(long)ctx->data_end;\n    struct ethhdr *eth = data;\n\n    if ((void *)(eth + 1) > data_end)\n        return XDP_DROP;\n\n    if (eth->h_proto != htons(ETH_P_IP))\n        return XDP_DROP;\n\n    return XDP_PASS;\n}",
         "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/samples/bpf"},
    ],
    "concept-754c1125e055": [  # Futex
        {"label": "Futex-based userspace mutex (simplified)", "language": "c",
         "code": "if (atomic_cmpxchg(&lock->val, 0, 1) != 0) {\n    futex(&lock->val, FUTEX_WAIT, 1, NULL, NULL, 0);\n}\n\n/* Unlock */\natomic_set(&lock->val, 0);\nfutex(&lock->val, FUTEX_WAKE, 1, NULL, NULL, 0);",
         "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/locking/futex-requeue-pi.rst"},
    ],
    "concept-19d51f949f56": [  # Epoll
        {"label": "Epoll event loop", "language": "c",
         "code": "int epfd = epoll_create1(0);\n\nstruct epoll_event ev = { .events = EPOLLIN | EPOLLET, .data.fd = sock_fd };\nepoll_ctl(epfd, EPOLL_CTL_ADD, sock_fd, &ev);\n\nstruct epoll_event events[MAX_EVENTS];\nwhile (1) {\n    int n = epoll_wait(epfd, events, MAX_EVENTS, -1);\n    for (int i = 0; i < n; i++)\n        handle_event(events[i].data.fd);\n}",
         "source_url": "https://man7.org/linux/man-pages/man7/epoll.7.html"},
    ],
    "concept-3a1c7ed96cb7": [  # Namespaces
        {"label": "Creating a PID namespace with clone", "language": "c",
         "code": "pid_t pid = clone(child_func, child_stack + STACK_SIZE,\n    CLONE_NEWPID | CLONE_NEWNS | SIGCHLD, NULL);\n\nunshare(CLONE_NEWPID | CLONE_NEWNET);\n\nint fd = open(\"/proc/1234/ns/pid\", O_RDONLY);\nsetns(fd, CLONE_NEWPID);",
         "source_url": "https://man7.org/linux/man-pages/man7/namespaces.7.html"},
    ],
    "concept-aac7d9ea52eb": [  # KVM
        {"label": "KVM ioctl workflow (simplified)", "language": "c",
         "code": "int kvm_fd = open(\"/dev/kvm\", O_RDWR);\nint vm_fd = ioctl(kvm_fd, KVM_CREATE_VM, 0);\nint vcpu_fd = ioctl(vm_fd, KVM_CREATE_VCPU, 0);\n\nstruct kvm_userspace_memory_region region = {\n    .slot = 0, .guest_phys_addr = 0,\n    .memory_size = mem_size,\n    .userspace_addr = (uint64_t)guest_mem,\n};\nioctl(vm_fd, KVM_SET_USER_MEMORY_REGION, &region);\n\nwhile (1) {\n    ioctl(vcpu_fd, KVM_RUN, NULL);\n    switch (run->exit_reason) {\n    case KVM_EXIT_IO: handle_io(run); break;\n    case KVM_EXIT_HLT: return 0;\n    }\n}",
         "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/virt/kvm/api.rst"},
    ],
    "concept-c73ac8c3ff02": [  # eBPF
        {"label": "eBPF tracepoint program (libbpf C)", "language": "c",
         "code": "SEC(\"tp/syscalls/sys_enter_openat\")\nint trace_openat(struct trace_event_raw_sys_enter *ctx)\n{\n    pid_t pid = bpf_get_current_pid_tgid() >> 32;\n    char comm[16];\n    bpf_get_current_comm(comm, sizeof(comm));\n    bpf_printk(\"pid=%d comm=%s opening file\", pid, comm);\n    return 0;\n}",
         "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/samples/bpf"},
    ],
    "concept-4ef77ca7ed52": [  # Ftrace
        {"label": "Enabling ftrace function tracing from shell", "language": "bash",
         "code": "echo function > /sys/kernel/debug/tracing/current_tracer\necho 'schedule' > /sys/kernel/debug/tracing/set_ftrace_filter\necho 1 > /sys/kernel/debug/tracing/tracing_on\nsleep 5\necho 0 > /sys/kernel/debug/tracing/tracing_on\ncat /sys/kernel/debug/tracing/trace",
         "source_url": "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/Documentation/trace/ftrace.rst"},
    ],
}


def main():
    conn = sqlite3.connect("data/master.db")
    conn.row_factory = sqlite3.Row

    # --- Part 1a: Original evidence excerpts from files ---
    print("=== Part 1a: Original evidence excerpts ===")
    for ev_id, filepath in ORIGINAL_EVIDENCE.items():
        text = Path(filepath).read_text(encoding="utf-8").strip()
        if len(text) > 2000:
            text = text[:2000]
        try:
            update_node_attrs(conn, ev_id, {"excerpt": text})
            print(f"  OK {ev_id} ({len(text)} chars from {filepath})")
        except Exception as e:
            print(f"  FAIL {ev_id}: {e}")

    # --- Part 1b: Synthetic evidence excerpts ---
    print("\n=== Part 1b: Synthetic evidence excerpts ===")
    for ev_id, excerpt in SYNTHETIC_EXCERPTS.items():
        try:
            update_node_attrs(conn, ev_id, {"excerpt": excerpt})
            print(f"  OK {ev_id}")
        except Exception as e:
            print(f"  FAIL {ev_id}: {e}")

    # --- Part 2: Tier 1 code examples ---
    print("\n=== Part 2: Tier 1 code examples ===")
    for concept_id, examples in TIER1_CODE_EXAMPLES.items():
        try:
            update_node_attrs(conn, concept_id, {"code_examples": examples})
            name = conn.execute(
                "SELECT json_extract(attrs, '$.name') FROM nodes WHERE id=?",
                (concept_id,),
            ).fetchone()[0]
            print(f"  OK {concept_id} ({name}) — {len(examples)} example(s)")
        except Exception as e:
            print(f"  FAIL {concept_id}: {e}")

    conn.commit()

    # --- Verification ---
    print("\n=== Verification ===")
    ev_with = conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE kind='Evidence' AND json_extract(attrs,'$.excerpt') IS NOT NULL"
    ).fetchone()[0]
    ev_total = conn.execute("SELECT COUNT(*) FROM nodes WHERE kind='Evidence'").fetchone()[0]
    print(f"Evidence with excerpt: {ev_with}/{ev_total}")

    code_with = conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE kind='Concept' AND json_extract(attrs,'$.code_examples') IS NOT NULL"
    ).fetchone()[0]
    concept_total = conn.execute("SELECT COUNT(*) FROM nodes WHERE kind='Concept'").fetchone()[0]
    print(f"Concepts with code_examples: {code_with}/{concept_total}")

    conn.close()


if __name__ == "__main__":
    main()
