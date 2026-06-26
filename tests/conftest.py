"""Shared fixtures for graph engine tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from graph.schema import init_db
from graph.engine import add_node, add_edge


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    c = init_db(tmp_path / "test.db")
    yield c
    c.close()


@pytest.fixture
def populated(conn: sqlite3.Connection) -> sqlite3.Connection:
    """A graph with one of each node kind and basic edges."""
    add_node(conn, "sub1", "Subsystem", {"name": "scheduler"})
    add_node(conn, "c1", "Concept", {"name": "RCU", "description": "read-copy-update", "artifact_class": "B", "key_properties": ["lock-free reads"], "tradeoffs": ["grace period latency"], "design_rationale": "Optimizes read-heavy workloads by deferring reclamation."})
    add_node(conn, "c2", "Concept", {"name": "rwlock", "description": "read-write lock", "artifact_class": "B", "key_properties": ["shared reads"], "tradeoffs": ["write starvation"], "design_rationale": "Allows concurrent reads while serializing writes."})
    add_node(conn, "src1", "Source", {"url": "http://ex.com", "source_type": "paper", "license": "PD"})
    add_node(conn, "ev1", "Evidence", {"artifact_class": "A", "contamination_level": "L0"})
    add_node(conn, "adv1", "Advisory", {"assessment": "safe", "contamination_confirmed": "none"})
    add_edge(conn, "belongs-to", "c1", "sub1")
    add_edge(conn, "belongs-to", "c2", "sub1")
    add_edge(conn, "extracted-from", "c1", "ev1")
    add_edge(conn, "sourced-from", "ev1", "src1")
    add_edge(conn, "assessed-by", "src1", "adv1")
    add_node(conn, "prob1", "Problem", {
        "title": "Grace period latency",
        "description": "RCU grace periods take too long under NUMA",
        "severity": "high",
        "status": "open",
        "source_date": "2026-06-01",
        "artifact_class": "B",
    })
    add_node(conn, "obs1", "Observation", {
        "claim": "NUMA locality affects RCU throughput",
        "confidence": "0.8",
        "source_date": "2026-06-10",
        "artifact_class": "B",
    })
    add_node(conn, "disc1", "Discussion", {
        "title": "RCU scalability on NUMA systems",
        "forum": "lkml",
        "participant_count": "5",
        "source_date": "2026-06-12",
        "artifact_class": "B",
    })
    add_node(conn, "bench1", "Benchmark", {
        "metric": "grace period latency",
        "result_summary": "17% improvement with batching",
        "conditions": "128 cores, NUMA",
        "source_date": "2026-06-15",
        "artifact_class": "B",
    })
    add_node(conn, "vuln1", "Vulnerability", {
        "cve_id": "CVE-2026-99999",
        "title": "Use-after-free in RCU callback processing",
        "description": "A use-after-free can occur when...",
        "severity": "high",
        "cvss_score": "7.8",
        "affected_versions": "6.8 - 6.10",
        "status": "unfixed",
        "source_date": "2026-06-20",
        "artifact_class": "B",
    })
    add_node(conn, "prop1", "Proposal", {
        "name": "NUMA-aware grace period batching",
        "description": "Batch grace periods by NUMA node",
        "status": "draft",
        "source_date": "2026-06-18",
        "artifact_class": "B",
    })
    add_node(conn, "fix1", "Fix", {
        "title": "Fix RCU callback UAF",
        "commit_hash": "a1b2c3d4e5f6",
        "fix_type": "security-fix",
        "source_date": "2026-06-22",
        "artifact_class": "B",
    })
    add_node(conn, "rej1", "Rejection", {
        "proposal_title": "Remove grace periods entirely",
        "reason": "Would break all existing RCU users",
        "rejector": "Paul McKenney",
        "source_date": "2026-05-01",
        "artifact_class": "B",
    })
    add_edge(conn, "identifies-problem", "prob1", "c1")
    add_edge(conn, "observes", "obs1", "c1")
    add_edge(conn, "discusses", "disc1", "c1")
    add_edge(conn, "benchmarks", "bench1", "c1")
    add_edge(conn, "exploits", "vuln1", "c1")
    add_edge(conn, "grounded-in", "prop1", "c1")
    add_edge(conn, "addresses", "prop1", "prob1")
    add_edge(conn, "fixes", "fix1", "vuln1")
    add_edge(conn, "patches", "fix1", "c1")
    add_edge(conn, "rejected-for", "rej1", "c1")
    return conn


@pytest.fixture
def admissible_master_db(tmp_path: Path) -> Path:
    """A master DB with mixed Class A + B + C content that passes all admissibility rules."""
    db_path = tmp_path / "master.db"
    conn = init_db(db_path)
    add_node(conn, "sub1", "Subsystem", {"name": "scheduler"})
    add_node(conn, "c1", "Concept", {"name": "RCU", "description": "read-copy-update", "artifact_class": "B", "key_properties": ["lock-free reads"], "tradeoffs": ["grace period latency"], "design_rationale": "Optimizes read-heavy workloads by deferring reclamation."})
    add_node(conn, "c2", "Concept", {"name": "rwlock", "description": "read-write lock", "artifact_class": "B", "key_properties": ["shared reads"], "tradeoffs": ["write starvation"], "design_rationale": "Allows concurrent reads while serializing writes."})
    add_node(conn, "src1", "Source", {"url": "http://ex.com", "source_type": "paper", "license": "PD"})
    add_node(conn, "src2", "Source", {"url": "http://ex2.com", "source_type": "paper", "license": "PD"})
    add_node(conn, "ev1", "Evidence", {"artifact_class": "A", "contamination_level": "L0"})
    add_node(conn, "ev2", "Evidence", {"artifact_class": "A", "contamination_level": "L0"})
    add_node(conn, "adv1", "Advisory", {"assessment": "safe", "contamination_confirmed": "none"})
    add_node(conn, "adv2", "Advisory", {"assessment": "safe", "contamination_confirmed": "none"})
    add_edge(conn, "belongs-to", "c1", "sub1")
    add_edge(conn, "belongs-to", "c2", "sub1")
    add_edge(conn, "extracted-from", "c1", "ev1")
    add_edge(conn, "extracted-from", "c2", "ev2")
    add_edge(conn, "sourced-from", "ev1", "src1")
    add_edge(conn, "sourced-from", "ev2", "src2")
    add_edge(conn, "assessed-by", "src1", "adv1")
    add_edge(conn, "assessed-by", "src2", "adv2")
    add_edge(conn, "alternative-to", "c1", "c2")
    add_node(conn, "prob1", "Problem", {
        "title": "Grace period latency",
        "description": "RCU grace periods take too long under NUMA",
        "severity": "high",
        "status": "open",
        "source_date": "2026-06-01",
        "artifact_class": "B",
    })
    add_node(conn, "obs1", "Observation", {
        "claim": "NUMA locality affects RCU throughput",
        "confidence": "0.8",
        "source_date": "2026-06-10",
        "artifact_class": "B",
    })
    add_node(conn, "disc1", "Discussion", {
        "title": "RCU scalability on NUMA systems",
        "forum": "lkml",
        "participant_count": "5",
        "source_date": "2026-06-12",
        "artifact_class": "B",
    })
    add_node(conn, "bench1", "Benchmark", {
        "metric": "grace period latency",
        "result_summary": "17% improvement with batching",
        "conditions": "128 cores, NUMA",
        "source_date": "2026-06-15",
        "artifact_class": "B",
    })
    add_node(conn, "vuln1", "Vulnerability", {
        "cve_id": "CVE-2026-99999",
        "title": "Use-after-free in RCU callback processing",
        "description": "A use-after-free can occur when...",
        "severity": "high",
        "cvss_score": "7.8",
        "affected_versions": "6.8 - 6.10",
        "status": "unfixed",
        "source_date": "2026-06-20",
        "artifact_class": "B",
    })
    add_node(conn, "prop1", "Proposal", {
        "name": "NUMA-aware grace period batching",
        "description": "Batch grace periods by NUMA node",
        "status": "draft",
        "source_date": "2026-06-18",
        "artifact_class": "B",
    })
    add_node(conn, "fix1", "Fix", {
        "title": "Fix RCU callback UAF",
        "commit_hash": "a1b2c3d4e5f6",
        "fix_type": "security-fix",
        "source_date": "2026-06-22",
        "artifact_class": "B",
    })
    add_node(conn, "rej1", "Rejection", {
        "proposal_title": "Remove grace periods entirely",
        "reason": "Would break all existing RCU users",
        "rejector": "Paul McKenney",
        "source_date": "2026-05-01",
        "artifact_class": "B",
    })
    add_edge(conn, "identifies-problem", "prob1", "c1")
    add_edge(conn, "observes", "obs1", "c1")
    add_edge(conn, "discusses", "disc1", "c1")
    add_edge(conn, "benchmarks", "bench1", "c1")
    add_edge(conn, "exploits", "vuln1", "c1")
    add_edge(conn, "grounded-in", "prop1", "c1")
    add_edge(conn, "addresses", "prop1", "prob1")
    add_edge(conn, "fixes", "fix1", "vuln1")
    add_edge(conn, "patches", "fix1", "c1")
    add_edge(conn, "rejected-for", "rej1", "c1")
    conn.commit()
    conn.close()
    return db_path
