"""Re-add CPU Frequency Scaling (cpufreq) concept wrongly deleted by cleanup_concepts_v2."""
import json
import sqlite3

DB_PATH = "data/master.db"

def main():
    conn = sqlite3.connect(DB_PATH)
    node_id = "concept-a8b6633439b5"
    attrs = json.dumps({
        "name": "CPU Frequency Scaling (cpufreq)",
        "description": "Linux kernel subsystem for dynamically adjusting CPU clock frequency based on system load, thermal constraints, and power policy.",
        "artifact_class": "B",
        "key_properties": json.dumps(["frequency governors", "P-state management", "energy-performance tradeoff"]),
        "tradeoffs": json.dumps(["latency vs power savings", "governor selection complexity"]),
        "design_rationale": "Enables power management by allowing the kernel to scale CPU frequency according to workload demands.",
    })
    conn.execute("INSERT INTO nodes (id, kind, attrs) VALUES (?, 'Concept', ?)", (node_id, attrs))

    sub_row = conn.execute(
        "SELECT id FROM nodes WHERE kind = 'Subsystem' AND json_extract(attrs, '$.name') LIKE '%Power%' LIMIT 1"
    ).fetchone()
    if sub_row:
        conn.execute(
            "INSERT INTO edges (kind, source_id, target_id, attrs) VALUES ('belongs-to', ?, ?, '{}')",
            (node_id, sub_row[0]),
        )
        print(f"Linked to subsystem {sub_row[0]}")

    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    print("Re-added CPU Frequency Scaling (cpufreq)")

if __name__ == "__main__":
    main()
