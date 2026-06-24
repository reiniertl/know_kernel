"""Populate Tier 2 code examples for remaining 63 Concept nodes."""
import sys
import sqlite3

sys.path.insert(0, "src")
from graph.engine import update_node_attrs

TIER2 = {
    # === File Systems ===
    "concept-7c38ea71f3d4": [  # Virtual Filesystem Switch
        {"label": "Registering a filesystem type", "language": "c",
         "code": "static struct file_system_type myfs_type = {\n    .owner    = THIS_MODULE,\n    .name     = \"myfs\",\n    .mount    = myfs_mount,\n    .kill_sb  = kill_litter_super,\n};\nregister_filesystem(&myfs_type);"},
    ],
    "concept-381c9460c8f9": [  # Dentry Cache (dcache)
        {"label": "Looking up a dentry in the dcache", "language": "c",
         "code": "struct dentry *dentry = d_lookup(parent, &name);\nif (dentry) {\n    struct inode *inode = d_inode(dentry);\n    /* use inode */\n    dput(dentry);\n}"},
    ],
    "concept-55ff31c1a3d0": [  # Page Cache
        {"label": "Finding or creating a page in the page cache", "language": "c",
         "code": "struct page *page = find_get_page(mapping, index);\nif (!page) {\n    page = find_or_create_page(mapping, index, GFP_KERNEL);\n    if (page) {\n        /* read data into page */\n        unlock_page(page);\n    }\n}\nput_page(page);"},
    ],
    "concept-ce5181046c73": [  # ext4 Journaling Filesystem
        {"label": "ext4 journaled write transaction", "language": "c",
         "code": "handle_t *handle = ext4_journal_start(inode, EXT4_HT_INODE, credits);\nif (IS_ERR(handle))\n    return PTR_ERR(handle);\n\next4_journal_get_write_access(handle, bh);\n/* modify buffer_head data */\next4_handle_dirty_metadata(handle, NULL, bh);\next4_journal_stop(handle);"},
    ],
    "concept-60c1c4e03593": [  # Btrfs
        {"label": "Creating a Btrfs snapshot (userspace)", "language": "bash",
         "code": "btrfs subvolume create /mnt/data/subvol\nbtrfs subvolume snapshot /mnt/data/subvol /mnt/data/snap\nbtrfs subvolume list /mnt/data"},
    ],
    "concept-adc1a84ba8e7": [  # XFS Filesystem
        {"label": "XFS allocation group inode lookup", "language": "c",
         "code": "struct xfs_inode *ip;\nerror = xfs_iget(mp, tp, ino, XFS_IGET_CREATE, XFS_ILOCK_EXCL, &ip);\nif (error)\n    return error;\n/* operate on inode */\nxfs_iunlock(ip, XFS_ILOCK_EXCL);\nxfs_irele(ip);"},
    ],
    "concept-7966cb602a7f": [  # OverlayFS
        {"label": "Mounting an OverlayFS (userspace)", "language": "bash",
         "code": "mount -t overlay overlay \\\n  -o lowerdir=/lower,upperdir=/upper,workdir=/work \\\n  /merged"},
    ],
    "concept-3884ddb8d90b": [  # FUSE
        {"label": "FUSE filesystem operation handlers (libfuse)", "language": "c",
         "code": "static int my_getattr(const char *path, struct stat *st,\n                      struct fuse_file_info *fi)\n{\n    memset(st, 0, sizeof(*st));\n    if (strcmp(path, \"/\") == 0) {\n        st->st_mode = S_IFDIR | 0755;\n        st->st_nlink = 2;\n    }\n    return 0;\n}\n\nstatic struct fuse_operations ops = { .getattr = my_getattr };\nfuse_main(argc, argv, &ops, NULL);"},
    ],
    "concept-62c68673efc9": [  # io_uring
        {"label": "io_uring read submission", "language": "c",
         "code": "struct io_uring ring;\nio_uring_queue_init(32, &ring, 0);\n\nstruct io_uring_sqe *sqe = io_uring_get_sqe(&ring);\nio_uring_prep_read(sqe, fd, buf, len, offset);\nio_uring_sqe_set_data(sqe, user_data);\n\nio_uring_submit(&ring);\n\nstruct io_uring_cqe *cqe;\nio_uring_wait_cqe(&ring, &cqe);\nint result = cqe->res;\nio_uring_cqe_seen(&ring, cqe);"},
    ],

    # === Scheduler ===
    "concept-bbf4c7fd039b": [  # EEVDF
        {"label": "EEVDF virtual deadline calculation (kernel internal)", "language": "c",
         "code": "/* Simplified pick_eevdf logic */\nstatic struct sched_entity *pick_eevdf(struct cfs_rq *cfs_rq)\n{\n    struct sched_entity *best = NULL;\n    struct rb_node *node = cfs_rq->tasks_timeline.rb_leftmost;\n    while (node) {\n        struct sched_entity *se = rb_entry(node, struct sched_entity, run_node);\n        if (entity_eligible(cfs_rq, se) &&\n            (!best || deadline_before(se, best)))\n            best = se;\n        node = rb_next(node);\n    }\n    return best;\n}"},
    ],
    "concept-e63e8227aec5": [  # Virtual Runtime Scheduling
        {"label": "vruntime update on tick", "language": "c",
         "code": "static void update_curr(struct cfs_rq *cfs_rq)\n{\n    struct sched_entity *curr = cfs_rq->curr;\n    u64 delta_exec = rq_clock_task(rq) - curr->exec_start;\n    curr->vruntime += calc_delta_fair(delta_exec, curr);\n    update_min_vruntime(cfs_rq);\n}"},
    ],
    "concept-a0033f053362": [  # Red-Black Tree Runqueue
        {"label": "Inserting into the CFS rbtree", "language": "c",
         "code": "static void __enqueue_entity(struct cfs_rq *cfs_rq,\n                            struct sched_entity *se)\n{\n    struct rb_node **link = &cfs_rq->tasks_timeline.rb_root.rb_node;\n    struct rb_node *parent = NULL;\n    s64 key = entity_key(cfs_rq, se);\n    while (*link) {\n        parent = *link;\n        struct sched_entity *entry = rb_entry(parent, struct sched_entity, run_node);\n        if (key < entity_key(cfs_rq, entry))\n            link = &parent->rb_left;\n        else\n            link = &parent->rb_right;\n    }\n    rb_link_node(&se->run_node, parent, link);\n    rb_insert_color_cached(&se->run_node, &cfs_rq->tasks_timeline, !parent || key < entity_key(cfs_rq, rb_entry(parent, struct sched_entity, run_node)));\n}"},
    ],
    "concept-1cce1b3cab02": [  # SCHED_DEADLINE
        {"label": "Setting SCHED_DEADLINE parameters", "language": "c",
         "code": "struct sched_attr attr = {\n    .size = sizeof(attr),\n    .sched_policy = SCHED_DEADLINE,\n    .sched_runtime  =  5000000,  /*  5 ms */\n    .sched_deadline = 10000000,  /* 10 ms */\n    .sched_period   = 10000000,  /* 10 ms */\n};\nsyscall(SYS_sched_setattr, 0, &attr, 0);"},
    ],
    "concept-aec36132506b": [  # POSIX Real-Time Scheduling
        {"label": "Setting SCHED_FIFO priority", "language": "c",
         "code": "struct sched_param param = { .sched_priority = 50 };\npthread_setschedparam(pthread_self(), SCHED_FIFO, &param);"},
    ],
    "concept-f9da333b618d": [  # Scheduling Classes
        {"label": "Scheduling class structure", "language": "c",
         "code": "DEFINE_SCHED_CLASS(fair) = {\n    .enqueue_task    = enqueue_task_fair,\n    .dequeue_task    = dequeue_task_fair,\n    .pick_next_task  = __pick_next_task_fair,\n    .task_tick       = task_tick_fair,\n    .set_next_task   = set_next_task_fair,\n};"},
    ],
    "concept-a9bc9eb64a8e": [  # Scheduler Load Balancing
        {"label": "Triggering load balancing", "language": "c",
         "code": "/* Simplified load_balance flow */\nstatic int load_balance(int this_cpu, struct rq *this_rq,\n                       struct sched_domain *sd)\n{\n    struct rq *busiest = find_busiest_queue(sd, this_cpu);\n    if (!busiest)\n        return 0;\n    int moved = detach_tasks(&env);\n    if (moved)\n        attach_tasks(&env);\n    return moved;\n}"},
    ],

    # === Device Drivers ===
    "concept-bce84bba28fc": [  # Unified Device Model
        {"label": "Registering a platform driver", "language": "c",
         "code": "static int my_probe(struct platform_device *pdev) { return 0; }\nstatic void my_remove(struct platform_device *pdev) {}\n\nstatic struct platform_driver my_driver = {\n    .probe  = my_probe,\n    .remove = my_remove,\n    .driver = { .name = \"my_device\", .of_match_table = my_of_ids },\n};\nmodule_platform_driver(my_driver);"},
    ],
    "concept-d67b8ca4aa0a": [  # Interrupt Handling
        {"label": "Requesting and handling an IRQ", "language": "c",
         "code": "static irqreturn_t my_irq_handler(int irq, void *dev_id)\n{\n    /* acknowledge HW interrupt */\n    writel(0x1, priv->base + IRQ_ACK);\n    return IRQ_HANDLED;\n}\n\nrequest_irq(irq, my_irq_handler, IRQF_SHARED,\n            \"my_device\", priv);"},
    ],
    "concept-b33bc2fbf87c": [  # DMA Mapping
        {"label": "Streaming DMA mapping", "language": "c",
         "code": "dma_addr_t dma_handle;\ndma_handle = dma_map_single(dev, buffer, size, DMA_TO_DEVICE);\nif (dma_mapping_error(dev, dma_handle))\n    return -ENOMEM;\n\n/* program HW with dma_handle */\n\ndma_unmap_single(dev, dma_handle, size, DMA_TO_DEVICE);"},
    ],
    "concept-6b57068e3f27": [  # Devicetree
        {"label": "Reading properties from a devicetree node", "language": "c",
         "code": "struct device_node *np = pdev->dev.of_node;\nu32 val;\n\nif (of_property_read_u32(np, \"clock-frequency\", &val))\n    val = 100000; /* default */\n\nconst char *label;\nof_property_read_string(np, \"label\", &label);\n\nint irq = of_irq_get(np, 0);"},
    ],
    "concept-939fefe9f300": [  # USB Subsystem
        {"label": "Submitting a USB Request Block (URB)", "language": "c",
         "code": "struct urb *urb = usb_alloc_urb(0, GFP_KERNEL);\nusb_fill_bulk_urb(urb, udev,\n    usb_sndbulkpipe(udev, ep_out),\n    buf, len, my_urb_complete, priv);\n\nint ret = usb_submit_urb(urb, GFP_KERNEL);\nif (ret)\n    usb_free_urb(urb);"},
    ],
    "concept-26f8d7bacbca": [  # Kernel Module Loader
        {"label": "Basic kernel module skeleton", "language": "c",
         "code": "#include <linux/module.h>\n#include <linux/init.h>\n\nstatic int __init my_init(void) {\n    pr_info(\"module loaded\\n\");\n    return 0;\n}\nstatic void __exit my_exit(void) {\n    pr_info(\"module unloaded\\n\");\n}\n\nmodule_init(my_init);\nmodule_exit(my_exit);\nMODULE_LICENSE(\"GPL\");"},
    ],

    # === Security ===
    "concept-62dbd93b6b5e": [  # Seccomp-BPF
        {"label": "Installing a seccomp-BPF filter", "language": "c",
         "code": "struct sock_filter filter[] = {\n    BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),\n    BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_write, 0, 1),\n    BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),\n    BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_KILL),\n};\nstruct sock_fprog prog = { .len = 4, .filter = filter };\nprctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0);\nprctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, &prog);"},
    ],
    "concept-2d5248a68e1b": [  # POSIX Capabilities
        {"label": "Dropping and checking capabilities", "language": "c",
         "code": "cap_t caps = cap_get_proc();\ncap_value_t drop[] = { CAP_NET_RAW, CAP_SYS_ADMIN };\ncap_set_flag(caps, CAP_EFFECTIVE, 2, drop, CAP_CLEAR);\ncap_set_proc(caps);\ncap_free(caps);\n\n/* Check if we still have a capability */\nif (cap_get_bound(CAP_NET_BIND_SERVICE))\n    bind_to_privileged_port();"},
    ],
    "concept-a70c1aca8416": [  # Linux Security Modules
        {"label": "LSM hook registration", "language": "c",
         "code": "static int my_file_open(struct file *file)\n{\n    /* custom access check */\n    return 0;  /* allow */\n}\n\nstatic struct security_hook_list my_hooks[] = {\n    LSM_HOOK_INIT(file_open, my_file_open),\n};\n\nstatic int __init my_lsm_init(void)\n{\n    security_add_hooks(my_hooks, ARRAY_SIZE(my_hooks), \"my_lsm\");\n    return 0;\n}\n\nDEFINE_LSM(my_lsm) = {\n    .name = \"my_lsm\",\n    .init = my_lsm_init,\n};"},
    ],

    # === Block I/O ===
    "concept-f120807c7668": [  # Block Device Layer
        {"label": "Registering a block device", "language": "c",
         "code": "static const struct block_device_operations my_ops = {\n    .owner = THIS_MODULE,\n    .open  = my_open,\n    .release = my_release,\n};\n\nstruct gendisk *disk = blk_alloc_disk(NULL, NUMA_NO_NODE);\ndisk->major = MY_MAJOR;\ndisk->first_minor = 0;\ndisk->fops = &my_ops;\nset_capacity(disk, nr_sectors);\nadd_disk(disk);"},
    ],

    # === Storage Stack ===
    "concept-b717794f4b66": [  # Device Mapper
        {"label": "Creating a device-mapper target (userspace)", "language": "bash",
         "code": "echo '0 2097152 linear /dev/sda1 0' | dmsetup create my_linear\ndmsetup table my_linear\ndmsetup remove my_linear"},
    ],
    "concept-0ab1037c0920": [  # MD Software RAID
        {"label": "Creating a software RAID array (userspace)", "language": "bash",
         "code": "mdadm --create /dev/md0 --level=1 --raid-devices=2 /dev/sda1 /dev/sdb1\nmdadm --detail /dev/md0\ncat /proc/mdstat"},
    ],
    "concept-d15451a63cf3": [  # dm-crypt
        {"label": "Setting up dm-crypt with LUKS (userspace)", "language": "bash",
         "code": "cryptsetup luksFormat /dev/sda2\ncryptsetup luksOpen /dev/sda2 my_crypt\nmkfs.ext4 /dev/mapper/my_crypt\nmount /dev/mapper/my_crypt /mnt/encrypted"},
    ],
    "concept-4f338eadf8af": [  # NVMe Driver
        {"label": "NVMe admin command submission", "language": "c",
         "code": "struct nvme_command cmd = {};\ncmd.identify.opcode = nvme_admin_identify;\ncmd.identify.cns = NVME_ID_CNS_CTRL;\ncmd.identify.dptr.prp1 = cpu_to_le64(dma_addr);\n\nret = nvme_submit_sync_cmd(ctrl->admin_q, &cmd, NULL, 0);"},
    ],

    # === Power Management ===
    "concept-a8b6633439b5": [  # CPU Frequency Scaling
        {"label": "cpufreq governor registration", "language": "c",
         "code": "static struct cpufreq_governor my_gov = {\n    .name   = \"my_governor\",\n    .init   = my_gov_init,\n    .exit   = my_gov_exit,\n    .limits = my_gov_limits,\n};\ncpufreq_register_governor(&my_gov);"},
    ],
    "concept-25a91f8914fc": [  # CPU Idle Framework
        {"label": "cpuidle driver registration", "language": "c",
         "code": "static struct cpuidle_state my_states[] = {\n    { .name = \"C1\", .exit_latency = 1, .target_residency = 1,\n      .enter = my_c1_enter },\n    { .name = \"C2\", .exit_latency = 100, .target_residency = 300,\n      .enter = my_c2_enter },\n};\nstatic struct cpuidle_driver my_drv = {\n    .name = \"my_idle\", .states = my_states, .state_count = 2,\n};\ncpuidle_register_driver(&my_drv);"},
    ],
    "concept-b2cffcf51c9e": [  # Thermal Management
        {"label": "Registering a thermal zone", "language": "c",
         "code": "static int my_get_temp(struct thermal_zone_device *tz, int *temp)\n{\n    *temp = read_hw_sensor();  /* millidegrees C */\n    return 0;\n}\nstatic struct thermal_zone_device_ops my_ops = { .get_temp = my_get_temp };\n\nthermal_zone_device_register(\"my_sensor\", 1, 0, priv,\n    &my_ops, NULL, 0, 1000);"},
    ],

    # === Firmware Interface ===
    "concept-ba51003c8ca6": [  # ACPI
        {"label": "Evaluating an ACPI method", "language": "c",
         "code": "acpi_handle handle;\nacpi_status status;\nstruct acpi_buffer buf = { ACPI_ALLOCATE_BUFFER, NULL };\n\nstatus = acpi_get_handle(NULL, \"\\\\_SB.PCI0\", &handle);\nstatus = acpi_evaluate_object(handle, \"_STA\", NULL, &buf);\n\nunion acpi_object *obj = buf.pointer;\nif (obj->type == ACPI_TYPE_INTEGER)\n    pr_info(\"_STA = %lld\\n\", obj->integer.value);\nkfree(buf.pointer);"},
    ],
    "concept-b09773d1ab17": [  # EFI/UEFI Boot
        {"label": "Reading an EFI variable", "language": "c",
         "code": "efi_char16_t name[] = L\"SecureBoot\";\nefi_guid_t guid = EFI_GLOBAL_VARIABLE_GUID;\nunsigned long size = 0;\nu32 attr;\nu8 val;\n\nefi.get_variable(name, &guid, &attr, &size, NULL);\nefi.get_variable(name, &guid, &attr, &size, &val);"},
    ],
    "concept-eaa675c1df23": [  # Kernel Live Patching
        {"label": "Defining a live patch", "language": "c",
         "code": "static struct klp_func funcs[] = {\n    { .old_name = \"sched_setscheduler\",\n      .new_func = my_patched_sched_setscheduler },\n    {}\n};\nstatic struct klp_object objs[] = {\n    { .funcs = funcs },  /* vmlinux */\n    {}\n};\nstatic struct klp_patch patch = { .mod = THIS_MODULE, .objs = objs };\n\nklp_enable_patch(&patch);"},
    ],

    # === NUMA ===
    "concept-1ca089ce48b0": [  # NUMA Topology and Memory Policy
        {"label": "Setting NUMA memory policy", "language": "c",
         "code": "unsigned long nodemask = 1 << target_node;\nset_mempolicy(MPOL_BIND, &nodemask, max_node + 1);\n\n/* Or bind a range */\nmbind(addr, len, MPOL_INTERLEAVE, &nodemask, max_node + 1, 0);"},
    ],
    "concept-cde0c9c23458": [  # AutoNUMA
        {"label": "Checking AutoNUMA statistics (userspace)", "language": "bash",
         "code": "cat /proc/vmstat | grep numa\n# numa_hit, numa_miss, numa_foreign, numa_local, numa_other\necho 1 > /proc/sys/kernel/numa_balancing  # enable\ngrep -r . /sys/kernel/mm/numa/"},
    ],

    # === Cryptography ===
    "concept-45002e01d393": [  # Kernel Crypto API
        {"label": "Symmetric encryption with skcipher", "language": "c",
         "code": "struct crypto_skcipher *tfm = crypto_alloc_skcipher(\"cbc(aes)\", 0, 0);\ncrypto_skcipher_setkey(tfm, key, keylen);\n\nstruct skcipher_request *req = skcipher_request_alloc(tfm, GFP_KERNEL);\nskcipher_request_set_crypt(req, &sg_src, &sg_dst, len, iv);\n\ncrypto_skcipher_encrypt(req);\n\nskcipher_request_free(req);\ncrypto_free_skcipher(tfm);"},
    ],

    # === Virtualization ===
    "concept-819626ee51d4": [  # Hardware Virtualization Extensions
        {"label": "VMX enter/exit cycle (simplified)", "language": "c",
         "code": "/* Enable VMX operation */\ncr4_set_bits(X86_CR4_VMXE);\n__vmx_on(phys_addr_of_vmxon_region);\n\n/* Launch a guest */\n__vmx_vmlaunch();  /* enters guest mode */\n\n/* On VM exit, handle the reason */\nreason = vmcs_read32(VM_EXIT_REASON);\nswitch (reason) {\ncase EXIT_REASON_IO_INSTRUCTION:\n    handle_io_exit(vcpu); break;\n}"},
    ],
    "concept-f87ca11a605a": [  # Virtio Paravirtual I/O
        {"label": "Virtio device driver probe", "language": "c",
         "code": "static int my_virtio_probe(struct virtio_device *vdev)\n{\n    struct virtqueue *vq;\n    vq = virtio_find_single_vq(vdev, my_vq_callback, \"my_vq\");\n    if (IS_ERR(vq))\n        return PTR_ERR(vq);\n    virtio_device_ready(vdev);\n    return 0;\n}\n\nstatic struct virtio_driver my_drv = {\n    .driver.name = \"my_virtio\",\n    .id_table = my_id_table,\n    .probe = my_virtio_probe,\n};\nmodule_virtio_driver(my_drv);"},
    ],
    "concept-c221fb66a93c": [  # VFIO
        {"label": "VFIO device access from userspace", "language": "c",
         "code": "int ctr = open(\"/dev/vfio/vfio\", O_RDWR);\nint grp = open(\"/dev/vfio/42\", O_RDWR);\n\nstruct vfio_group_status status = { .argsz = sizeof(status) };\nioctl(grp, VFIO_GROUP_GET_STATUS, &status);\n\nioctl(grp, VFIO_GROUP_SET_CONTAINER, &ctr);\nioctl(ctr, VFIO_SET_IOMMU, VFIO_TYPE1_IOMMU);\n\nint dev = ioctl(grp, VFIO_GROUP_GET_DEVICE_FD, \"0000:06:00.0\");"},
    ],
    "concept-0fed5d516f1f": [  # Memory Ballooning
        {"label": "Virtio balloon inflate/deflate", "language": "c",
         "code": "/* Guest balloon driver inflates (returns pages to host) */\nstatic void balloon_inflate(struct virtio_balloon *vb, size_t num)\n{\n    struct page *page;\n    while (num--) {\n        page = alloc_page(GFP_HIGHUSER);\n        list_add(&page->lru, &vb->pages);\n        tell_host(vb, vb->inflate_vq);\n    }\n}"},
    ],

    # === IPC ===
    "concept-7917f5e8d86f": [  # Pipe and FIFO
        {"label": "Creating and using a pipe", "language": "c",
         "code": "int pipefd[2];\npipe(pipefd);\n\nif (fork() == 0) {\n    close(pipefd[0]);\n    write(pipefd[1], \"hello\", 5);\n    close(pipefd[1]);\n    _exit(0);\n}\nclose(pipefd[1]);\nchar buf[5];\nread(pipefd[0], buf, 5);\nclose(pipefd[0]);"},
    ],
    "concept-249e6fcf80de": [  # Shared Memory (shmem/tmpfs)
        {"label": "POSIX shared memory", "language": "c",
         "code": "int fd = shm_open(\"/my_shm\", O_CREAT | O_RDWR, 0666);\nftruncate(fd, 4096);\nvoid *ptr = mmap(NULL, 4096, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);\n\nmemcpy(ptr, \"hello\", 5);\n\nmunmap(ptr, 4096);\nshm_unlink(\"/my_shm\");"},
    ],
    "concept-11c3c5c674e4": [  # Signal Delivery
        {"label": "Installing a signal handler with sigaction", "language": "c",
         "code": "static void handler(int sig, siginfo_t *info, void *ctx)\n{\n    write(STDOUT_FILENO, \"caught\\n\", 7);\n}\n\nstruct sigaction sa = {\n    .sa_sigaction = handler,\n    .sa_flags = SA_SIGINFO | SA_RESTART,\n};\nsigemptyset(&sa.sa_mask);\nsigaction(SIGUSR1, &sa, NULL);"},
    ],

    # === Memory Management (remaining) ===
    "concept-4579b846e61a": [  # Hierarchical Page Tables
        {"label": "Walking x86-64 page tables", "language": "c",
         "code": "pgd_t *pgd = pgd_offset(mm, addr);\np4d_t *p4d = p4d_offset(pgd, addr);\npud_t *pud = pud_offset(p4d, addr);\npmd_t *pmd = pmd_offset(pud, addr);\npte_t *pte = pte_offset_kernel(pmd, addr);\n\nif (pte_present(*pte)) {\n    unsigned long pfn = pte_pfn(*pte);\n    struct page *page = pfn_to_page(pfn);\n}"},
    ],
    "concept-e1d75c2b2821": [  # Translation Lookaside Buffer
        {"label": "TLB flush operations", "language": "c",
         "code": "/* Flush a single page */\nflush_tlb_page(vma, addr);\n\n/* Flush a range */\nflush_tlb_range(vma, start, end);\n\n/* Flush entire TLB on all CPUs */\nflush_tlb_all();"},
    ],
    "concept-6c06bbc0fb4e": [  # Huge Page Mapping
        {"label": "Allocating huge pages (userspace)", "language": "c",
         "code": "void *p = mmap(NULL, 2 * 1024 * 1024, PROT_READ | PROT_WRITE,\n               MAP_PRIVATE | MAP_ANONYMOUS | MAP_HUGETLB, -1, 0);\nif (p == MAP_FAILED)\n    perror(\"hugetlb mmap\");\nmunmap(p, 2 * 1024 * 1024);"},
    ],
    "concept-11bad48ab285": [  # Transparent Huge Pages
        {"label": "Controlling THP (userspace)", "language": "bash",
         "code": "echo always > /sys/kernel/mm/transparent_hugepage/enabled\necho defer+madvise > /sys/kernel/mm/transparent_hugepage/defrag\n# Per-process via madvise\n# madvise(addr, len, MADV_HUGEPAGE);"},
    ],
    "concept-d119c5436fa1": [  # Page Fault Handler
        {"label": "Page fault handler entry (simplified)", "language": "c",
         "code": "static vm_fault_t handle_pte_fault(struct vm_fault *vmf)\n{\n    if (!vmf->pte) {\n        if (vma_is_anonymous(vmf->vma))\n            return do_anonymous_page(vmf);\n        return do_fault(vmf);  /* file-backed */\n    }\n    if (!pte_present(vmf->orig_pte))\n        return do_swap_page(vmf);\n    if (vmf->flags & FAULT_FLAG_WRITE)\n        return do_wp_page(vmf);  /* copy-on-write */\n    return 0;\n}"},
    ],
    "concept-9bd23539558b": [  # Page Reclaim
        {"label": "Triggering direct reclaim", "language": "c",
         "code": "/* Kernel internal: try_to_free_pages path */\nstatic unsigned long shrink_lruvec(struct lruvec *lruvec,\n    struct scan_control *sc)\n{\n    unsigned long nr_reclaimed = 0;\n    /* Scan inactive anonymous pages */\n    nr_reclaimed += shrink_list(LRU_INACTIVE_ANON, lruvec, sc);\n    /* Scan inactive file pages */\n    nr_reclaimed += shrink_list(LRU_INACTIVE_FILE, lruvec, sc);\n    return nr_reclaimed;\n}"},
    ],
    "concept-eb1a33dfbe79": [  # Contiguous Memory Allocator
        {"label": "CMA allocation", "language": "c",
         "code": "struct page *pages = cma_alloc(cma_area, count, align, GFP_KERNEL);\nif (!pages)\n    return -ENOMEM;\n\nvoid *vaddr = page_address(pages);\ndma_addr_t phys = page_to_phys(pages);\n\n/* Use contiguous buffer for DMA */\n\ncma_release(cma_area, pages, count);"},
    ],
    "concept-e1b8be28a851": [  # KSM
        {"label": "Enabling KSM on a memory region (userspace)", "language": "c",
         "code": "void *addr = mmap(NULL, size, PROT_READ | PROT_WRITE,\n                  MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);\nmadvise(addr, size, MADV_MERGEABLE);\n\n/* Check KSM stats */\n/* cat /sys/kernel/mm/ksm/pages_sharing */\n/* cat /sys/kernel/mm/ksm/pages_shared */"},
    ],
    "concept-424eed1d6e64": [  # Zswap
        {"label": "Configuring Zswap (userspace)", "language": "bash",
         "code": "echo 1 > /sys/module/zswap/parameters/enabled\necho lz4 > /sys/module/zswap/parameters/compressor\necho zsmalloc > /sys/module/zswap/parameters/zpool\necho 20 > /sys/module/zswap/parameters/max_pool_percent\ngrep -r . /sys/kernel/debug/zswap/"},
    ],

    # === Networking (remaining) ===
    "concept-212cd9975ccf": [  # TCP Congestion Control
        {"label": "Registering a TCP congestion control algorithm", "language": "c",
         "code": "static struct tcp_congestion_ops my_cong = {\n    .name       = \"my_cc\",\n    .owner      = THIS_MODULE,\n    .init       = my_cc_init,\n    .ssthresh   = my_cc_ssthresh,\n    .cong_avoid = my_cc_cong_avoid,\n    .undo_cwnd  = my_cc_undo_cwnd,\n};\ntcp_register_congestion_control(&my_cong);"},
    ],
    "concept-17496c703c5f": [  # Netfilter Hook Framework
        {"label": "Registering a netfilter hook", "language": "c",
         "code": "static unsigned int my_hook(void *priv, struct sk_buff *skb,\n    const struct nf_hook_state *state)\n{\n    struct iphdr *iph = ip_hdr(skb);\n    pr_info(\"packet from %pI4\\n\", &iph->saddr);\n    return NF_ACCEPT;\n}\n\nstatic struct nf_hook_ops my_nf_ops = {\n    .hook     = my_hook,\n    .pf       = NFPROTO_IPV4,\n    .hooknum  = NF_INET_PRE_ROUTING,\n    .priority = NF_IP_PRI_FIRST,\n};\nnf_register_net_hook(&init_net, &my_nf_ops);"},
    ],
    "concept-ca0836513c6c": [  # Network Namespaces
        {"label": "Creating and using a network namespace (userspace)", "language": "bash",
         "code": "ip netns add test_ns\nip netns exec test_ns ip link set lo up\nip link add veth0 type veth peer name veth1\nip link set veth1 netns test_ns\nip netns exec test_ns ip addr add 10.0.0.2/24 dev veth1\nip netns exec test_ns ip link set veth1 up"},
    ],

    # === Process Management (remaining) ===
    "concept-c1bd2c7cd50e": [  # Process Creation
        {"label": "fork/exec pattern", "language": "c",
         "code": "pid_t pid = fork();\nif (pid == 0) {\n    /* child */\n    execve(\"/bin/ls\", argv, envp);\n    _exit(127);\n}\n/* parent */\nint status;\nwaitpid(pid, &status, 0);\nif (WIFEXITED(status))\n    printf(\"exit code: %d\\n\", WEXITSTATUS(status));"},
    ],
    "concept-01b26b23a922": [  # Procfs and Sysfs
        {"label": "Creating a procfs entry", "language": "c",
         "code": "static int my_show(struct seq_file *m, void *v)\n{\n    seq_printf(m, \"count: %d\\n\", atomic_read(&my_count));\n    return 0;\n}\n\nstatic int my_open(struct inode *inode, struct file *file)\n{\n    return single_open(file, my_show, NULL);\n}\n\nstatic const struct proc_ops my_proc_ops = {\n    .proc_open = my_open,\n    .proc_read = seq_read,\n    .proc_lseek = seq_lseek,\n    .proc_release = single_release,\n};\nproc_create(\"my_entry\", 0444, NULL, &my_proc_ops);"},
    ],

    # === Misc ===
    "concept-5ebd30a4f427": [  # Control Groups (cgroups v2)
        {"label": "Creating and configuring a cgroup v2 (userspace)", "language": "bash",
         "code": "mkdir /sys/fs/cgroup/mygroup\necho '+cpu +memory' > /sys/fs/cgroup/cgroup.subtree_control\necho 100000 > /sys/fs/cgroup/mygroup/cpu.max\necho 256M > /sys/fs/cgroup/mygroup/memory.max\necho $$ > /sys/fs/cgroup/mygroup/cgroup.procs"},
    ],
    "concept-24984fe25927": [  # Workqueue
        {"label": "Scheduling work on a workqueue", "language": "c",
         "code": "static void my_work_func(struct work_struct *work)\n{\n    struct my_data *data = container_of(work, struct my_data, work);\n    /* deferred processing */\n}\n\nstatic DECLARE_WORK(my_work, my_work_func);\nschedule_work(&my_work);\n\n/* Or delayed: */\nstatic DECLARE_DELAYED_WORK(my_dwork, my_work_func);\nschedule_delayed_work(&my_dwork, msecs_to_jiffies(100));"},
    ],
    "concept-21cffd09b1a6": [  # Perf Events
        {"label": "Opening a perf event counter", "language": "c",
         "code": "struct perf_event_attr pe = {\n    .type = PERF_TYPE_HARDWARE,\n    .config = PERF_COUNT_HW_CACHE_MISSES,\n    .disabled = 1,\n    .exclude_kernel = 1,\n};\nint fd = perf_event_open(&pe, 0, -1, -1, 0);\nioctl(fd, PERF_EVENT_IOC_ENABLE, 0);\n\n/* ... run workload ... */\n\nioctl(fd, PERF_EVENT_IOC_DISABLE, 0);\nlong long count;\nread(fd, &count, sizeof(count));\nclose(fd);"},
    ],
}


def main():
    conn = sqlite3.connect("data/master.db")
    conn.row_factory = sqlite3.Row

    updated = 0
    for concept_id, examples in TIER2.items():
        try:
            update_node_attrs(conn, concept_id, {"code_examples": examples})
            name = conn.execute(
                "SELECT json_extract(attrs, '$.name') FROM nodes WHERE id=?",
                (concept_id,),
            ).fetchone()[0]
            updated += 1
            print(f"  OK {concept_id} ({name}) -- {len(examples)} example(s)")
        except Exception as e:
            print(f"  FAIL {concept_id}: {e}")

    conn.commit()
    print(f"\nUpdated {updated}/{len(TIER2)} concepts")

    # Verification
    code_with = conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE kind='Concept' AND json_extract(attrs,'$.code_examples') IS NOT NULL"
    ).fetchone()[0]
    code_without = conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE kind='Concept' AND json_extract(attrs,'$.code_examples') IS NULL"
    ).fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM nodes WHERE kind='Concept'").fetchone()[0]
    print(f"Concepts with code_examples: {code_with}/{total}")
    if code_without > 0:
        missing = conn.execute(
            "SELECT id, json_extract(attrs,'$.name') FROM nodes WHERE kind='Concept' AND json_extract(attrs,'$.code_examples') IS NULL"
        ).fetchall()
        print(f"WARNING: {code_without} concepts still missing code_examples:")
        for r in missing:
            print(f"  {r[0]}: {r[1]}")

    conn.close()


if __name__ == "__main__":
    main()
