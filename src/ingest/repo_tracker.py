"""Git repository commit tracker -- parse kernel commits for Fix nodes (ALG-KK-REPO-TRACK)."""

from __future__ import annotations

import logging
import re
import sqlite3
import uuid
from dataclasses import dataclass, field
from typing import Any

from graph.engine import add_edge, add_node

log = logging.getLogger(__name__)

# INV-KK-REPO-SUBSYSTEM-MAP: deterministic file-path-to-subsystem mapping.
# Ordered by specificity (longer prefixes first).
SUBSYSTEM_MAP: list[tuple[str, str]] = [
    ("kernel/sched/", "Scheduler"),
    ("kernel/rcu/", "RCU"),
    ("kernel/locking/", "Locking"),
    ("kernel/bpf/", "BPF"),
    ("kernel/cgroup/", "Cgroups"),
    ("kernel/", "Core Kernel"),
    ("mm/", "Memory Management"),
    ("fs/", "VFS"),
    ("net/", "Networking"),
    ("drivers/", "Device Drivers"),
    ("security/", "Security"),
    ("block/", "Block I/O"),
    ("arch/", "Architecture"),
    ("crypto/", "Crypto"),
    ("ipc/", "IPC"),
    ("init/", "Init"),
    ("lib/", "Lib"),
    ("tools/", "Tools"),
    ("scripts/", "Scripts"),
    ("Documentation/", "Documentation"),
    ("include/", "Headers"),
]

FIXES_RE = re.compile(r"Fixes:\s+([0-9a-f]{7,40})\s+\(", re.IGNORECASE)
CC_STABLE_RE = re.compile(r"Cc:\s+stable@vger\.kernel\.org", re.IGNORECASE)
CVE_RE = re.compile(r"CVE-\d{4}-\d{4,}", re.IGNORECASE)
REVERT_RE = re.compile(r'^Revert\s+"', re.IGNORECASE)


@dataclass
class ParsedCommit:
    commit_hash: str
    author_date: str
    subject: str
    body: str
    files: list[str] = field(default_factory=list)
    fixes_sha: str | None = None
    has_cc_stable: bool = False
    cve_ids: list[str] = field(default_factory=list)
    is_revert: bool = False


def path_to_subsystem(path: str) -> str | None:
    """INV-KK-REPO-SUBSYSTEM-MAP: map a file path to a subsystem name."""
    for prefix, subsystem in SUBSYSTEM_MAP:
        if path.startswith(prefix):
            return subsystem
    return None


def classify_commit(subject: str, body: str) -> dict[str, Any]:
    """INV-KK-REPO-FIX-TYPE: classify commit by message patterns."""
    full_text = subject + "\n" + body

    fixes_match = FIXES_RE.search(full_text)
    fixes_sha = fixes_match.group(1) if fixes_match else None

    has_cc_stable = bool(CC_STABLE_RE.search(full_text))
    cve_ids = CVE_RE.findall(full_text)
    is_revert = bool(REVERT_RE.match(subject))

    return {
        "fixes_sha": fixes_sha,
        "has_cc_stable": has_cc_stable,
        "cve_ids": [cve.upper() for cve in cve_ids],
        "is_revert": is_revert,
    }


def derive_fix_type(classification: dict[str, Any]) -> str:
    """INV-KK-REPO-FIX-TYPE: deterministic fix_type from classification."""
    if classification["cve_ids"]:
        return "security-fix"
    if classification["is_revert"]:
        return "regression-fix"
    return "bugfix"


def is_high_signal(classification: dict[str, Any]) -> bool:
    """Only ingest commits with at least one high-signal marker."""
    return bool(
        classification["fixes_sha"]
        or classification["has_cc_stable"]
        or classification["cve_ids"]
        or classification["is_revert"]
    )


def parse_git_log(raw: str) -> list[ParsedCommit]:
    """Parse git log output formatted with record separators.

    Expected format from:
        git log --format='%x1e%H%x1f%aI%x1f%s%x1f%b' --name-only
    Record separator (0x1e) between commits, unit separator (0x1f) between fields.
    File names follow the body, one per line, until next record or EOF.
    """
    commits: list[ParsedCommit] = []
    records = raw.split("\x1e")

    for record in records:
        record = record.strip()
        if not record:
            continue

        parts = record.split("\x1f", 3)
        if len(parts) < 3:
            log.warning("Malformed commit record, skipping: %s", record[:80])
            continue

        commit_hash = parts[0].strip()
        author_date = parts[1].strip()
        subject = parts[2].strip()
        rest = parts[3] if len(parts) > 3 else ""

        body_and_files = rest.strip()
        lines = body_and_files.split("\n")

        body_lines: list[str] = []
        file_lines: list[str] = []
        in_files = False

        for line in lines:
            stripped = line.strip()
            if not stripped:
                if body_lines and not in_files:
                    in_files = True
                continue
            if in_files or (not stripped.startswith(("Signed-off-by:", "Reviewed-by:", "Acked-by:", "Cc:", "Link:", "Fixes:", "Reported-by:", "Tested-by:")) and "/" in stripped and not stripped.startswith(" ")):
                if "/" in stripped or "." in stripped:
                    in_files = True
                    file_lines.append(stripped)
                else:
                    body_lines.append(line)
            else:
                body_lines.append(line)

        body = "\n".join(body_lines).strip()
        files = [f for f in file_lines if f]

        classification = classify_commit(subject, body)

        commits.append(ParsedCommit(
            commit_hash=commit_hash,
            author_date=author_date[:10],
            subject=subject,
            body=body,
            files=files,
            fixes_sha=classification["fixes_sha"],
            has_cc_stable=classification["has_cc_stable"],
            cve_ids=classification["cve_ids"],
            is_revert=classification["is_revert"],
        ))

    return commits


def subsystems_for_commit(commit: ParsedCommit) -> list[str]:
    """INV-KK-REPO-SUBSYSTEM-MAP: get unique subsystem names for commit's changed files."""
    subs: list[str] = []
    seen: set[str] = set()
    for path in commit.files:
        sub = path_to_subsystem(path)
        if sub and sub not in seen:
            subs.append(sub)
            seen.add(sub)
    return subs


def _find_concepts_by_subsystem(conn: sqlite3.Connection, subsystem_name: str) -> list[str]:
    """Find Concept nodes that belong to a Subsystem with the given name."""
    rows = conn.execute(
        """SELECT e.source_id FROM edges e
           JOIN nodes n ON e.target_id = n.id
           WHERE e.kind = 'belongs-to'
             AND n.kind = 'Subsystem'
             AND json_extract(n.attrs, '$.name') = ?""",
        (subsystem_name,),
    ).fetchall()
    return [r[0] for r in rows]


def _find_fixable_node(conn: sqlite3.Connection, commit_hash: str) -> tuple[str, str] | None:
    """INV-KK-REPO-FIXES-TAG: find a Problem or Vulnerability node with matching commit_hash."""
    for kind in ("Problem", "Vulnerability"):
        row = conn.execute(
            "SELECT id FROM nodes WHERE kind = ? AND json_extract(attrs, '$.commit_hash') = ?",
            (kind, commit_hash),
        ).fetchone()
        if row:
            return row[0], kind
    return None


def ingest_commit(conn: sqlite3.Connection, commit: ParsedCommit) -> str | None:
    """Create Fix node + edges for a high-signal commit. Returns Fix node ID or None."""
    classification = {
        "fixes_sha": commit.fixes_sha,
        "has_cc_stable": commit.has_cc_stable,
        "cve_ids": commit.cve_ids,
        "is_revert": commit.is_revert,
    }

    if not is_high_signal(classification):
        return None

    fix_type = derive_fix_type(classification)
    fix_id = f"fix-{uuid.uuid4().hex[:12]}"

    add_node(conn, fix_id, "Fix", {
        "title": commit.subject,
        "commit_hash": commit.commit_hash,
        "fix_type": fix_type,
        "source_date": commit.author_date,
        "artifact_class": "B",
    })

    subsystems = subsystems_for_commit(commit)
    for sub_name in subsystems:
        concept_ids = _find_concepts_by_subsystem(conn, sub_name)
        for cid in concept_ids:
            add_edge(conn, "patches", fix_id, cid)

    if commit.fixes_sha:
        target = _find_fixable_node(conn, commit.fixes_sha)
        if target:
            target_id, _ = target
            add_edge(conn, "fixes", fix_id, target_id)

    return fix_id


def ingest_commits(conn: sqlite3.Connection, raw_log: str) -> list[str]:
    """Parse git log output and ingest all high-signal commits. Returns list of Fix node IDs."""
    commits = parse_git_log(raw_log)
    fix_ids: list[str] = []
    for commit in commits:
        fix_id = ingest_commit(conn, commit)
        if fix_id:
            fix_ids.append(fix_id)
    return fix_ids
