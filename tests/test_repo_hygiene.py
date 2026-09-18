"""INV-KK-DB-BACKUPS-NOT-TRACKED — pre-run database backups never enter Git.

On 2026-09-18 sixteen files matching data/master.db.bak-* totalling 358 MB sat
untracked in the working tree, matched by no .gitignore rule. The repository's
entire history is smaller than that, and a single `git add -A` would have
committed all of it. The files must stay on disk — master.db.bak-pre-corpus-
summaries and master.db.bak-pre-title-reconcile are the only copies of the
graph from before two runs that cannot be undone — so the fix is an ignore
rule, and this test is what stops the rule from being lost again.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=False)


def _is_a_git_checkout() -> bool:
    return _git("rev-parse", "--is-inside-work-tree").returncode == 0


needs_git = pytest.mark.skipif(
    not _is_a_git_checkout(), reason="not a git checkout")


@needs_git
@pytest.mark.parametrize("name", [
    "data/master.db.bak-pre-corpus-summaries",
    "data/master.db.bak-pre-title-reconcile",
    # The -shm and -wal siblings SQLite leaves when a backup is opened
    # read-only for diffing. A rule anchored on the label alone misses these.
    "data/master.db.bak-pre-title-reconcile-wal",
    "data/master.db.bak-pre-title-search-shm",
    # A backup that does not exist yet must be covered in advance — the point
    # of the rule is that the NEXT one is ignored without anybody remembering.
    "data/master.db.bak-pre-some-future-run",
])
def test_a_database_backup_path_is_ignored(name):
    assert _git("check-ignore", "-q", "--no-index", name).returncode == 0, (
        f"{name} is not ignored; a stray `git add -A` would commit it")


@needs_git
def test_no_database_backup_is_actually_tracked():
    """The consequence that matters, checked separately: adding an ignore rule
    after a file is already tracked does not untrack it."""
    tracked = [p for p in _git("ls-files").stdout.splitlines()
               if ".bak-" in p and p.startswith("data/")]
    assert tracked == []


@needs_git
def test_the_rule_does_not_swallow_the_databases_themselves():
    """data/master.db and data/auth.db are deliberately tracked. An over-broad
    rule such as `data/*` would satisfy every test above and lose the corpus."""
    for kept in ("data/master.db", "data/auth.db"):
        assert _git("check-ignore", "-q", "--no-index", kept).returncode != 0, (
            f"{kept} must not be ignored")
