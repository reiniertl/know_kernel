"""Rewrite 43 Source node URLs from relative paths to resolvable kernel.org links."""
import sys
import sqlite3

sys.path.insert(0, "src")
from graph.engine import update_node_attrs

BASE = "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/"

URL_MAP = {
    "src-09529cef90e4": "Documentation/admin-guide/mm/numa_memory_policy.rst",
    "src-13d374ce19a7": "Documentation/mm/slab.rst",
    "src-14539382ad09": "Documentation/livepatch",
    "src-1ce98b32b995": "Documentation/filesystems/overlayfs.rst",
    "src-1d2ac703db3f": "Documentation/admin-guide/mm/concepts.rst",
    "src-229b391b1364": "Documentation/core-api/kernel-api.rst",
    "src-247295ca11f0": "Documentation/power",
    "src-2868c14b49ad": "Documentation/crypto",
    "src-2ab22506911d": "Documentation/driver-api/driver-model",
    "src-36d30d7b5d0a": "Documentation/process",
    "src-3772631c1a21": "Documentation/admin-guide/efi-stub.rst",
    "src-3810cb4a3708": "Documentation/scheduler/sched-eevdf.rst",
    "src-3bde0050c5a4": "Documentation/filesystems/xfs",
    "src-4a50e2612720": "Documentation/filesystems/btrfs.rst",
    "src-4aae8b0752fc": "Documentation/admin-guide/device-mapper",
    "src-53c20ffdae81": "Documentation/virt/virtio",
    "src-5ea2b3e2df76": "Documentation/driver-api/thermal",
    "src-66eed8a9f689": "Documentation/scheduler/sched-deadline.rst",
    "src-6f9d5d1c73dc": "Documentation/usb",
    "src-72a9f4dc2721": "Documentation/filesystems/vfs.rst",
    "src-7541098a44d9": "Documentation/nvme",
    "src-79e1df6b4f02": "Documentation/block",
    "src-851a5e88c6fd": "Documentation/admin-guide/mm/ksm.rst",
    "src-8a51fa0011e4": "Documentation/core-api/workqueue.rst",
    "src-8c1204cbaa3b": "Documentation/firmware-guide/acpi",
    "src-8fef8a32ba6c": "Documentation/admin-guide/mm/transhuge.rst",
    "src-97b0f20052b2": "Documentation/trace",
    "src-9a8b2251ef08": "Documentation/virt/kvm",
    "src-a76555b18853": "Documentation/security",
    "src-a9bc87d30bf8": "Documentation/networking/napi.rst",
    "src-af333f2c8fd0": "Documentation/networking/net_namespace.rst",
    "src-b182a450a3fe": "Documentation/filesystems/fuse.rst",
    "src-b280276ff32e": "Documentation/ipc",
    "src-b8a81f4b4b91": "Documentation/scheduler/sched-rt-group.rst",
    "src-bc320fbc6c96": "Documentation/admin-guide/cgroup-v2.rst",
    "src-c697ec445d38": "Documentation/admin-guide/perf",
    "src-cf306a484849": "Documentation/admin-guide/mm/zswap.rst",
    "src-d167dddf5351": "Documentation/filesystems/ext4",
    "src-de7c74ffb2f5": "Documentation/networking/skbuff.rst",
    "src-e2c49a090d9e": "Documentation/admin-guide/md.rst",
    "src-e81019df75ec": "Documentation/mm/page_alloc.rst",
    "src-f43a581012f7": "Documentation/networking/tcp.rst",
    "src-f7c80bc67494": "Documentation/namespaces",
}


def main():
    conn = sqlite3.connect("data/master.db")
    conn.row_factory = sqlite3.Row
    updated = 0
    for src_id, path in URL_MAP.items():
        new_url = BASE + path
        try:
            update_node_attrs(conn, src_id, {"url": new_url})
            updated += 1
            print(f"  OK {src_id} -> .../{path}")
        except Exception as e:
            print(f"  FAIL {src_id}: {e}")

    conn.commit()
    print(f"\nUpdated {updated}/{len(URL_MAP)} source nodes")

    cur = conn.execute(
        "SELECT id, json_extract(attrs, '$.url') as url FROM nodes "
        "WHERE kind='Source' AND json_extract(attrs,'$.url') NOT LIKE 'https://%'"
    )
    non_https = cur.fetchall()
    if non_https:
        print(f"WARNING: {len(non_https)} sources still without HTTPS:")
        for r in non_https:
            print(f"  {r['id']}: {r['url']}")
    else:
        total = conn.execute("SELECT COUNT(*) FROM nodes WHERE kind='Source'").fetchone()[0]
        print(f"VERIFIED: All {total} Source nodes have HTTPS URLs")

    conn.close()


if __name__ == "__main__":
    main()
