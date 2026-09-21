"""What must never enter Git, and what must never stop entering it.

INV-KK-DB-BACKUPS-NOT-TRACKED — pre-run database backups.
INV-KK-LINK-MECHANISM-SINGLE — only the extractor writes provenance edges.
INV-KK-WORKING-SCRATCH-NOT-TRACKED — the zip, tmp/ and root tmp_*.py.

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


# ---------------------------------------------------------------------------
# INV-KK-LINK-MECHANISM-SINGLE — only the extractor may claim a paper is about
# something, and only by reading the paper.
#
# data/semantic_link.py did it from the title alone. classify_paper(title)
# applied regex such as r'\bscheduler\b|\bscheduling\b|\bsched[_ ]' with no
# abstract, no Evidence text and no model, while its docstring claimed it was
# "NOT substring keyword matching". 191 of the links it produced are known
# wrong: they were computed from titles that an off-by-one in the arXiv loader
# had displaced onto the wrong paper. It is deleted; commit 8f84e5f has it if
# the record of how those 2,022 links were made is ever needed.
#
# This test is what stops the next one appearing. 33 scripts were deleted on
# 2026-09-17 for the same reason and nothing prevented a replacement.
# ---------------------------------------------------------------------------

PROVENANCE_EDGE_KIND = "extracted-from"

#: The only files permitted to create a provenance edge, or to call something
#: that does. The first two write the edges; the other three are sanctioned as
#: CALLERS ONLY and contain no edge-creating line themselves.
SANCTIONED_WRITERS = (
    "src/ingest/extractor.py",
    "src/ingest/claim_extractor.py",
)
SANCTIONED_CALLERS = (
    "src/ingest/cli_extract.py",
    "src/ingest/cli_feed.py",
    "src/ingest/__init__.py",
)
INDIRECT_WRITE_IMPORTS = ("extract_concepts", "extract_claims")


def _tracked_python_files() -> list[str]:
    out = _git("ls-files", "*.py").stdout.splitlines()
    return [p for p in out if p and not p.startswith("tests/")]


def test_the_retired_title_regex_linker_is_gone():
    assert not (REPO / "data" / "semantic_link.py").exists()


@needs_git
def test_only_the_two_sanctioned_writers_create_provenance_edges():
    """The direct half of INV-KK-LINK-MECHANISM-SINGLE, now swept over every
    tracked .py file rather than only data/. The old version looked at data/
    alone and so could not see that src/ingest/claim_extractor.py is a second
    live writer."""
    offenders = []
    for rel in _tracked_python_files():
        if rel in SANCTIONED_WRITERS:
            continue
        text = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            if PROVENANCE_EDGE_KIND not in line:
                continue
            # Reading or counting existing edges is fine; creating them is not.
            if "add_edge" in line or "INSERT INTO edges" in line.upper():
                offenders.append(f"{rel}:{lineno}")
    assert offenders == [], (
        "these create provenance edges outside the sanctioned writers: "
        + ", ".join(offenders))


@needs_git
def test_nothing_outside_the_mechanism_calls_an_extractor():
    """The indirect half, and the half that was missing. data/run_extraction.py
    wrote provenance edges without containing the string 'extracted-from' at
    all: it handed extract_concepts a DirectClient returning hand-written JSON,
    so the edges were created one stack frame away and the old grep passed.
    Going through an extractor is the same act as writing the edge."""
    offenders = []
    for rel in _tracked_python_files():
        if rel in SANCTIONED_WRITERS or rel in SANCTIONED_CALLERS:
            continue
        text = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.lstrip()
            if not (stripped.startswith("from ") or stripped.startswith("import ")):
                continue
            if any(name in line for name in INDIRECT_WRITE_IMPORTS):
                offenders.append(f"{rel}:{lineno}")
    assert offenders == [], (
        "these import an extractor and so can write provenance edges "
        "indirectly: " + ", ".join(offenders))


def test_the_sanctioned_files_all_exist_and_still_write_the_edges():
    """Guards both tests above from passing vacuously. An absence check is
    satisfied by an empty repository, and a sanctioned list is satisfied by a
    sanctioned file that no longer does the thing it is sanctioned for."""
    for rel in SANCTIONED_WRITERS + SANCTIONED_CALLERS:
        assert (REPO / rel).exists(), f"{rel} is named in the spec but missing"

    extractor = (REPO / "src" / "ingest" / "extractor.py").read_text(encoding="utf-8")
    # Eight since 2026-09-21, not seven: attach_existing_concept joined the
    # seven named in INV-KK-EXTRACT-PROVENANCE. It fires only in re-link mode
    # and calls build_evidence_attrs like the rest, so the structural claim
    # that no extractor-written edge can be bare holds across all eight.
    assert extractor.count(f'add_edge(\n        conn, "{PROVENANCE_EDGE_KIND}"') == 8

    claims = (REPO / "src" / "ingest" / "claim_extractor.py").read_text(encoding="utf-8")
    assert claims.count(f'add_edge(conn, "{PROVENANCE_EDGE_KIND}"') == 6, (
        "claim_extractor.py is the second sanctioned mechanism and had six "
        "writers on 2026-09-21; if that changed, INV-KK-LINK-MECHANISM-SINGLE "
        "and INV-KK-CLAIM-EXTRACT-EVIDENCE-BARE both name the number")


def test_the_manual_extraction_script_is_gone():
    """data/run_extraction.py fed pre-crafted JSON through the real extractor
    with model='manual-extraction'. It was inert when removed — none of its
    four Evidence ids existed — but it was one Evidence node away from writing
    hand-authored content the graph could not tell from model output."""
    assert not (REPO / "data" / "run_extraction.py").exists()


# ---------------------------------------------------------------------------
# INV-KK-WORKING-SCRATCH-NOT-TRACKED — the scratch that piles up in the working
# tree is ignored, and the rules that ignore it cannot reach tracked source.
#
# 8.5 MB matched by no rule on 2026-09-21: combobul.zip (5.4 MB), tmp/ (3.1 MB)
# and tmp_test.py. Nothing was deleted — the zip holds 320 files that exist
# nowhere on disk, and tmp/ holds the only copies of five scripts that write
# extracted-from edges. That last fact is why this is not tidy-up: committing
# tmp/ would add five link mechanisms in one command, and
# INV-KK-LINK-MECHANISM-SINGLE's test greps data/*.py, so it would not see them.
# ---------------------------------------------------------------------------


@needs_git
@pytest.mark.parametrize("name", [
    "combobul.zip",
    "tmp/",
    "tmp/abstracts-run.json",
    "tmp/extract_concepts.py",
    "tmp_test.py",
    # Scratch that does not exist yet must be covered in advance, for the same
    # reason the next database backup is: nobody will remember to add a rule.
    "tmp/some-future-run.log",
    "tmp_scratch.py",
])
def test_a_working_scratch_path_is_ignored(name):
    assert _git("check-ignore", "-q", "--no-index", name).returncode == 0, (
        f"{name} is not ignored; a stray `git add -A` would commit it")


@needs_git
def test_no_working_scratch_is_actually_tracked():
    tracked = _git("ls-files").stdout.splitlines()
    offenders = [p for p in tracked
                 if p == "combobul.zip"
                 or p.startswith("tmp/")
                 or (p.startswith("tmp_") and p.endswith(".py") and "/" not in p)]
    assert offenders == []


@needs_git
@pytest.mark.parametrize("kept", [
    # The negations at the top of .gitignore are the only reason the spec
    # survives a clone. A rule such as `combobul*` would undo all three.
    "combobul/spec/mutations/.gitkeep",
    "combobul/spec/associations/artifact-associations.xml",
    "combobul/spec/snapshots/.gitkeep",
    "data/master.db",
    "data/auth.db",
    "src/ingest/extractor.py",
    "tests/test_repo_hygiene.py",
    # Root-anchoring is what stops `tmp` and `tmp_*.py` from reaching a
    # directory or helper of the same name nested inside tracked source.
    "src/web/tmp/renderer.py",
    "tests/tmp_helper.py",
])
def test_the_scratch_rules_do_not_reach_tracked_source(kept):
    assert _git("check-ignore", "-q", "--no-index", kept).returncode != 0, (
        f"{kept} must not be ignored")


@needs_git
def test_the_link_mechanisms_parked_in_tmp_are_ignored():
    """Why the tmp/ rule is load-bearing. These scripts sit outside
    INV-KK-LINK-MECHANISM-SINGLE's reach, which greps data/*.py, so the ignore
    rule is the only thing between them and the repository. Skipped on a clone,
    where tmp/ does not exist."""
    tmp = REPO / "tmp"
    if not tmp.is_dir():
        pytest.skip("tmp/ is local scratch and absent from a fresh clone")
    writers = []
    for path in sorted(tmp.glob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            if PROVENANCE_EDGE_KIND in line and "add_edge" in line:
                writers.append(path)
                break
    assert writers, (
        "tmp/ no longer holds any provenance-edge writer; if they were moved, "
        "check where to and whether they are still ignored")
    for path in writers:
        rel = path.relative_to(REPO).as_posix()
        assert _git("check-ignore", "-q", "--no-index", rel).returncode == 0, (
            f"{rel} writes {PROVENANCE_EDGE_KIND} edges and is not ignored")
