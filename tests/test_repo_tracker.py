"""Tests for git repository commit tracker -- ALG-KK-REPO-TRACK invariants."""

from __future__ import annotations

import json

import pytest

from graph.engine import add_edge, add_node
from graph.schema import init_db
from ingest.repo_tracker import (
    FIXES_RE,
    ParsedCommit,
    classify_commit,
    derive_fix_type,
    ingest_commit,
    ingest_commits,
    is_high_signal,
    parse_git_log,
    path_to_subsystem,
    subsystems_for_commit,
)


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "test.db")


# --- INV-KK-REPO-SUBSYSTEM-MAP tests ---


class TestPathToSubsystem:
    @pytest.mark.parametrize("path,expected", [
        ("mm/page_alloc.c", "Memory Management"),
        ("mm/slab.h", "Memory Management"),
        ("kernel/sched/core.c", "Scheduler"),
        ("kernel/sched/fair.c", "Scheduler"),
        ("kernel/rcu/tree.c", "RCU"),
        ("kernel/rcu/update.c", "RCU"),
        ("kernel/locking/mutex.c", "Locking"),
        ("kernel/bpf/verifier.c", "BPF"),
        ("kernel/cgroup/cgroup.c", "Cgroups"),
        ("kernel/fork.c", "Core Kernel"),
        ("fs/ext4/super.c", "VFS"),
        ("fs/vfs/open.c", "VFS"),
        ("net/ipv4/tcp.c", "Networking"),
        ("net/core/dev.c", "Networking"),
        ("drivers/gpu/drm/amd/amdgpu.c", "Device Drivers"),
        ("drivers/net/ethernet/intel/e1000.c", "Device Drivers"),
        ("security/selinux/hooks.c", "Security"),
        ("block/blk-core.c", "Block I/O"),
        ("arch/x86/kernel/cpu.c", "Architecture"),
        ("arch/arm64/mm/fault.c", "Architecture"),
        ("crypto/aes.c", "Crypto"),
        ("ipc/shm.c", "IPC"),
        ("include/linux/mm.h", "Headers"),
    ])
    def test_known_paths(self, path, expected):
        assert path_to_subsystem(path) == expected

    def test_unknown_path_returns_none(self):
        assert path_to_subsystem("Makefile") is None
        assert path_to_subsystem("MAINTAINERS") is None

    def test_specificity_ordering(self):
        assert path_to_subsystem("kernel/sched/core.c") == "Scheduler"
        assert path_to_subsystem("kernel/fork.c") == "Core Kernel"


class TestSubsystemsForCommit:
    def test_multiple_subsystems(self):
        commit = ParsedCommit(
            commit_hash="abc123", author_date="2026-06-15",
            subject="fix", body="",
            files=["mm/page_alloc.c", "kernel/sched/core.c", "mm/slab.c"],
        )
        subs = subsystems_for_commit(commit)
        assert "Memory Management" in subs
        assert "Scheduler" in subs
        assert len(subs) == 2

    def test_no_files(self):
        commit = ParsedCommit(
            commit_hash="abc123", author_date="2026-06-15",
            subject="fix", body="", files=[],
        )
        assert subsystems_for_commit(commit) == []


# --- Commit classification tests ---


class TestClassifyCommit:
    def test_fixes_tag(self):
        body = 'Fixes: a1b2c3d4e5f6 ("original commit subject")\nSigned-off-by: Dev'
        result = classify_commit("mm: fix page alloc", body)
        assert result["fixes_sha"] == "a1b2c3d4e5f6"

    def test_fixes_tag_12_char(self):
        body = 'Fixes: deadbeef1234 ("some commit")'
        result = classify_commit("fix something", body)
        assert result["fixes_sha"] == "deadbeef1234"

    def test_no_fixes_tag(self):
        result = classify_commit("mm: cleanup", "Just a cleanup commit")
        assert result["fixes_sha"] is None

    def test_cc_stable(self):
        body = "Cc: stable@vger.kernel.org\nSigned-off-by: Dev"
        result = classify_commit("fix: backport worthy", body)
        assert result["has_cc_stable"] is True

    def test_no_cc_stable(self):
        result = classify_commit("fix: minor", "body text")
        assert result["has_cc_stable"] is False

    def test_cve_mention(self):
        result = classify_commit("fix: CVE-2026-12345 use-after-free", "details")
        assert "CVE-2026-12345" in result["cve_ids"]

    def test_multiple_cves(self):
        body = "Fixes CVE-2026-11111 and CVE-2026-22222"
        result = classify_commit("security fix", body)
        assert len(result["cve_ids"]) == 2

    def test_no_cve(self):
        result = classify_commit("normal fix", "body")
        assert result["cve_ids"] == []

    def test_revert(self):
        result = classify_commit('Revert "mm: bad optimization"', "This reverts commit abc.")
        assert result["is_revert"] is True

    def test_not_revert(self):
        result = classify_commit("mm: fix revert handling", "body about reverts")
        assert result["is_revert"] is False

    def test_combined_signals(self):
        subject = 'Revert "net: broken thing"'
        body = 'Fixes: abc1234567890 ("net: broken thing")\nCc: stable@vger.kernel.org\nCVE-2026-99999'
        result = classify_commit(subject, body)
        assert result["fixes_sha"] == "abc1234567890"
        assert result["has_cc_stable"] is True
        assert "CVE-2026-99999" in result["cve_ids"]
        assert result["is_revert"] is True


# --- INV-KK-REPO-FIX-TYPE tests ---


class TestDeriveFixType:
    def test_cve_gives_security_fix(self):
        assert derive_fix_type({"cve_ids": ["CVE-2026-1234"], "is_revert": False, "fixes_sha": None, "has_cc_stable": False}) == "security-fix"

    def test_cve_takes_priority_over_revert(self):
        assert derive_fix_type({"cve_ids": ["CVE-2026-1234"], "is_revert": True, "fixes_sha": None, "has_cc_stable": False}) == "security-fix"

    def test_revert_gives_regression_fix(self):
        assert derive_fix_type({"cve_ids": [], "is_revert": True, "fixes_sha": None, "has_cc_stable": False}) == "regression-fix"

    def test_fixes_tag_gives_bugfix(self):
        assert derive_fix_type({"cve_ids": [], "is_revert": False, "fixes_sha": "abc123", "has_cc_stable": True}) == "bugfix"

    def test_cc_stable_gives_bugfix(self):
        assert derive_fix_type({"cve_ids": [], "is_revert": False, "fixes_sha": None, "has_cc_stable": True}) == "bugfix"


class TestIsHighSignal:
    def test_fixes_tag(self):
        assert is_high_signal({"fixes_sha": "abc", "has_cc_stable": False, "cve_ids": [], "is_revert": False})

    def test_cc_stable(self):
        assert is_high_signal({"fixes_sha": None, "has_cc_stable": True, "cve_ids": [], "is_revert": False})

    def test_cve(self):
        assert is_high_signal({"fixes_sha": None, "has_cc_stable": False, "cve_ids": ["CVE-2026-1"], "is_revert": False})

    def test_revert(self):
        assert is_high_signal({"fixes_sha": None, "has_cc_stable": False, "cve_ids": [], "is_revert": True})

    def test_no_signal(self):
        assert not is_high_signal({"fixes_sha": None, "has_cc_stable": False, "cve_ids": [], "is_revert": False})


# --- Git log parser tests ---


class TestParseGitLog:
    def test_single_commit(self):
        raw = '\x1eabc123def456\x1f2026-06-15T10:00:00+00:00\x1fmm: fix page alloc\x1fFixes: deadbeef1234 ("old commit")\n\nmm/page_alloc.c'
        commits = parse_git_log(raw)
        assert len(commits) == 1
        assert commits[0].commit_hash == "abc123def456"
        assert commits[0].author_date == "2026-06-15"
        assert commits[0].subject == "mm: fix page alloc"
        assert commits[0].fixes_sha == "deadbeef1234"

    def test_multiple_commits(self):
        raw = (
            '\x1eaaa111\x1f2026-06-10\x1ffirst commit\x1fbody1'
            '\x1ebbb222\x1f2026-06-11\x1fsecond commit\x1fbody2'
        )
        commits = parse_git_log(raw)
        assert len(commits) == 2
        assert commits[0].commit_hash == "aaa111"
        assert commits[1].commit_hash == "bbb222"

    def test_empty_input(self):
        assert parse_git_log("") == []

    def test_malformed_record_skipped(self):
        raw = "\x1ebadrecord"
        commits = parse_git_log(raw)
        assert len(commits) == 0

    def test_author_date_truncated_to_date(self):
        """INV-KK-REPO-AUTHOR-DATE: only date portion kept."""
        raw = '\x1eabc123\x1f2026-06-15T14:30:00+02:00\x1fsubject\x1fbody'
        commits = parse_git_log(raw)
        assert commits[0].author_date == "2026-06-15"

    def test_cve_in_subject(self):
        raw = '\x1eabc123\x1f2026-06-15\x1ffix: CVE-2026-54321\x1fbody'
        commits = parse_git_log(raw)
        assert "CVE-2026-54321" in commits[0].cve_ids

    def test_revert_detection(self):
        raw = '\x1eabc123\x1f2026-06-15\x1fRevert "mm: bad change"\x1freverts commit xyz'
        commits = parse_git_log(raw)
        assert commits[0].is_revert is True

    def test_cc_stable_in_body(self):
        raw = '\x1eabc123\x1f2026-06-15\x1fsubject\x1fCc: stable@vger.kernel.org'
        commits = parse_git_log(raw)
        assert commits[0].has_cc_stable is True


# --- Fix node creation tests ---


class TestIngestCommit:
    def test_creates_fix_node(self, conn):
        commit = ParsedCommit(
            commit_hash="abc123def456", author_date="2026-06-15",
            subject="mm: fix page alloc regression",
            body='Fixes: deadbeef1234 ("mm: bad alloc")\nCc: stable@vger.kernel.org',
            files=["mm/page_alloc.c"],
            fixes_sha="deadbeef1234", has_cc_stable=True, cve_ids=[], is_revert=False,
        )
        fix_id = ingest_commit(conn, commit)
        assert fix_id is not None
        row = conn.execute("SELECT kind, attrs FROM nodes WHERE id = ?", (fix_id,)).fetchone()
        assert row[0] == "Fix"
        attrs = json.loads(row[1])
        assert attrs["commit_hash"] == "abc123def456"
        assert attrs["fix_type"] == "bugfix"
        assert attrs["source_date"] == "2026-06-15"
        assert attrs["artifact_class"] == "B"

    def test_security_fix_type(self, conn):
        """INV-KK-REPO-FIX-TYPE: CVE mention => security-fix."""
        commit = ParsedCommit(
            commit_hash="sec123", author_date="2026-06-15",
            subject="fix: CVE-2026-12345 use-after-free",
            body="", files=[], fixes_sha=None, has_cc_stable=False,
            cve_ids=["CVE-2026-12345"], is_revert=False,
        )
        fix_id = ingest_commit(conn, commit)
        attrs = json.loads(conn.execute("SELECT attrs FROM nodes WHERE id = ?", (fix_id,)).fetchone()[0])
        assert attrs["fix_type"] == "security-fix"

    def test_regression_fix_type(self, conn):
        """INV-KK-REPO-FIX-TYPE: Revert => regression-fix."""
        commit = ParsedCommit(
            commit_hash="rev123", author_date="2026-06-15",
            subject='Revert "mm: bad optimization"',
            body="", files=[], fixes_sha=None, has_cc_stable=False,
            cve_ids=[], is_revert=True,
        )
        fix_id = ingest_commit(conn, commit)
        attrs = json.loads(conn.execute("SELECT attrs FROM nodes WHERE id = ?", (fix_id,)).fetchone()[0])
        assert attrs["fix_type"] == "regression-fix"

    def test_non_high_signal_skipped(self, conn):
        commit = ParsedCommit(
            commit_hash="low123", author_date="2026-06-15",
            subject="docs: update README",
            body="", files=["Documentation/readme.txt"],
            fixes_sha=None, has_cc_stable=False, cve_ids=[], is_revert=False,
        )
        assert ingest_commit(conn, commit) is None

    def test_patches_edge_created(self, conn):
        """ALG-KK-REPO-TRACK: patches edge to Concept via subsystem."""
        sub_id = "sub-mm"
        add_node(conn, sub_id, "Subsystem", {"name": "Memory Management"})
        concept_id = "concept-pagecache"
        add_node(conn, concept_id, "Concept", {
            "name": "Page Cache", "description": "Page cache mechanism",
            "key_properties": "[]", "tradeoffs": "[]",
            "design_rationale": "Caches disk pages in memory",
            "artifact_class": "B",
        })
        add_edge(conn, "belongs-to", concept_id, sub_id)

        commit = ParsedCommit(
            commit_hash="patch123", author_date="2026-06-15",
            subject="mm: fix page cache",
            body='Fixes: aaa111222333 ("mm: old bug")',
            files=["mm/filemap.c"],
            fixes_sha="aaa111222333", has_cc_stable=False, cve_ids=[], is_revert=False,
        )
        fix_id = ingest_commit(conn, commit)
        edge = conn.execute(
            "SELECT 1 FROM edges WHERE kind = 'patches' AND source_id = ? AND target_id = ?",
            (fix_id, concept_id),
        ).fetchone()
        assert edge is not None

    def test_fixes_edge_to_vulnerability(self, conn):
        """INV-KK-REPO-FIXES-TAG: fixes edge created when matching Vulnerability exists."""
        vuln_id = "vuln-test"
        add_node(conn, vuln_id, "Vulnerability", {
            "cve_id": "CVE-2026-99999", "title": "UAF in slab",
            "description": "desc", "severity": "high", "cvss_score": "7.5",
            "affected_versions": "6.0-6.10", "status": "unfixed",
            "source_date": "2026-06-01", "artifact_class": "B",
            "commit_hash": "deadbeef1234",
        })

        commit = ParsedCommit(
            commit_hash="fix999", author_date="2026-06-15",
            subject="mm: fix UAF in slab allocator",
            body='Fixes: deadbeef1234 ("mm: slab alloc")',
            files=["mm/slab.c"],
            fixes_sha="deadbeef1234", has_cc_stable=True, cve_ids=[], is_revert=False,
        )
        fix_id = ingest_commit(conn, commit)
        edge = conn.execute(
            "SELECT 1 FROM edges WHERE kind = 'fixes' AND source_id = ? AND target_id = ?",
            (fix_id, vuln_id),
        ).fetchone()
        assert edge is not None

    def test_fixes_edge_not_created_when_no_match(self, conn):
        """INV-KK-REPO-FIXES-TAG: unmatched SHA does not create fixes edge."""
        commit = ParsedCommit(
            commit_hash="fix888", author_date="2026-06-15",
            subject="net: fix tcp",
            body='Fixes: nonexistent123 ("net: old")',
            files=["net/ipv4/tcp.c"],
            fixes_sha="nonexistent123", has_cc_stable=False, cve_ids=[], is_revert=False,
        )
        fix_id = ingest_commit(conn, commit)
        edges = conn.execute(
            "SELECT 1 FROM edges WHERE kind = 'fixes' AND source_id = ?",
            (fix_id,),
        ).fetchall()
        assert len(edges) == 0

    def test_author_date_used_as_source_date(self, conn):
        """INV-KK-REPO-AUTHOR-DATE: source_date is author date."""
        commit = ParsedCommit(
            commit_hash="date123", author_date="2024-01-20",
            subject="mm: old fix",
            body='Fixes: aaa111 ("mm: old bug")',
            files=["mm/page_alloc.c"],
            fixes_sha="aaa111", has_cc_stable=True, cve_ids=[], is_revert=False,
        )
        fix_id = ingest_commit(conn, commit)
        attrs = json.loads(conn.execute("SELECT attrs FROM nodes WHERE id = ?", (fix_id,)).fetchone()[0])
        assert attrs["source_date"] == "2024-01-20"


class TestIngestCommits:
    def test_batch_ingestion(self, conn):
        raw = (
            '\x1eaaa111\x1f2026-06-10\x1fmm: fix alloc\x1fFixes: bbb2222abcdef ("old")'
            '\x1eccc333\x1f2026-06-11\x1fdocs: update\x1fjust docs'
            '\x1eddd444\x1f2026-06-12\x1fRevert "net: bad change"\x1freverts commit'
        )
        fix_ids = ingest_commits(conn, raw)
        assert len(fix_ids) == 2

    def test_empty_log(self, conn):
        assert ingest_commits(conn, "") == []
