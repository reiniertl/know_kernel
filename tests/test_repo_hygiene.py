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

import json
import re
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
#: that does. The first three write the edges; the rest are sanctioned as
#: CALLERS ONLY and contain no edge-creating line themselves.
#:
#: A THIRD WRITER FROM 2026-09-25: src/ingest/doc_harvest.py. It is the
#: document path — ALG-KK-DOC-HARVEST — and it is legitimate for the same
#: reason claim_extractor.py was found legitimate on 2026-09-21: it is the
#: mechanism for a class of source the others do not handle, and it writes the
#: same build_evidence_attrs verdict onto every edge, so the structural claim
#: that no sanctioned edge can be bare still holds. This test caught it the
#: moment the file became git-tracked and not before, which is the sweep
#: working: an untracked file is not yet part of the repository.
SANCTIONED_WRITERS = (
    "src/ingest/extractor.py",
    "src/ingest/claim_extractor.py",
    "src/ingest/doc_harvest.py",
)
SANCTIONED_CALLERS = (
    "src/ingest/cli_extract.py",
    "src/ingest/cli_feed.py",
    "src/ingest/cli_harvest.py",
    "src/ingest/__init__.py",
)
# harvest_document joined these on 2026-09-25, and adding it STRENGTHENS the
# sweep rather than accommodating the new path: without it, anything could
# import the harvest and write provenance edges one stack frame away, which is
# exactly the hole data/run_extraction.py went through and exactly what the
# indirect half below exists to close.
INDIRECT_WRITE_IMPORTS = ("extract_concepts", "extract_claims", "harvest_document")


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

    # The ninth writer, 2026-09-25, and it lives in the other module. Two
    # branches: _create mints the Concept and writes its edge, _attach writes
    # an edge onto a Concept that already exists. Both carry harvest_batch,
    # which is what INV-KK-HARVEST-BATCH-REVERTIBLE turns on.
    harvest = (REPO / "src" / "ingest" / "doc_harvest.py").read_text(encoding="utf-8")
    assert harvest.count(f'"{PROVENANCE_EDGE_KIND}"') >= 2
    assert "harvest_batch" in harvest

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


# ---------------------------------------------------------------------------
# Cited-but-absent spec ids.
#
# Source files cite spec node ids in docstrings and comments, and the id is
# load-bearing: it is how a reader gets from the code to the rule that governs
# it. Ten citations have been found pointing at nodes that never existed —
# eight in extractor.py on 2026-09-21, then ALG-KK-EXTRACT-CLI, then
# ALG-KK-CLAIM-EXTRACT on 2026-09-22, whose docstring had claimed it since the
# module was written.
#
# Each was found by hand. This sweep is what finds the next one.
# ---------------------------------------------------------------------------

SPEC_ID = re.compile(r"\b(?:ALG|INV|IFC|ANN)-KK-[A-Z0-9-]+")

#: Cited in src/ and absent from the graph. 92 of 221, measured 2026-09-22 —
#: FORTY-TWO PERCENT. Thirteen modules cited a governing node that was never
#: written: scoring.py, inference.py, briefing.py, feed.py, vuln_tracker.py,
#: repo_tracker.py, validate_sources.py, scanner.py, classifier.py, gate.py,
#: cli_feed.py, reviewer.py and claim_extractor.py.
#:
#: 86 OF 221 AS OF 2026-09-25: validate_sources.py is off that list. All six
#: ids it cited were authored the day the prose backfill was built, because
#: storing the fetched text changes what that path DOES and rule 3 does not
#: allow a behaviour change against nodes that do not exist. Twelve modules
#: remain.
#:
#: THE FIRST VERSION OF THIS SWEEP REPORTED FIVE, AND FIVE WAS NOT A
#: MEASUREMENT. It batched fifty ids into one `node-info` call, and that
#: command ABORTS THE WHOLE BLOCK on the first id it cannot find — so the sweep
#: saw exactly one missing id per batch and 220/50 rounds to five batches. The
#: number was the batch count. It is one command per id now.
#:
#: Frozen rather than asserted-empty because authoring ninety-two nodes from
#: their own docstrings is how ninety-two wrong nodes get written; each needs
#: its module read. Authoring any of them SHOULD fail this test — the set
#: shrinks deliberately, which is the direction of travel.
KNOWN_UNRESOLVED_SPEC_IDS = frozenset({
    # src/graph/briefing.py
    "ALG-KK-GRAPH-BUILD-ARGUMENT",
    "ALG-KK-GRAPH-CLASSIFY-MOTIVATIONS",
    "ALG-KK-GRAPH-CONCEPT-BRIEF",
    "INV-KK-GRAPH-BRIEF-ALL-CATEGORIES",
    "INV-KK-GRAPH-BRIEF-EMPTY-SAFE",
    "INV-KK-GRAPH-BRIEF-VERBATIM",
    # src/graph/inference.py
    "ALG-KK-IDEA-FEED",
    "ALG-KK-INFER-OPPORTUNITY",
    "ALG-KK-INFER-TREND",
    "INV-KK-IDEA-FEED-RANKED",
    "INV-KK-OPP-CLASS-B",
    "INV-KK-OPP-CONFIDENCE",
    "INV-KK-OPP-FRONTIER-GATE",
    "INV-KK-OPP-SUPPORTED",
    "INV-KK-TREND-CLASS-B",
    "INV-KK-TREND-INDEPENDENT",
    "INV-KK-TREND-INFERRED",
    "INV-KK-TREND-MIN-EVIDENCE",
    "INV-KK-TREND-WINDOW",
    # src/graph/scoring.py
    "ALG-KK-GRAPH-FEASIBILITY-SCORE",
    "ALG-KK-GRAPH-IMPACT-PROJECTION",
    "ALG-KK-GRAPH-RESEARCH-SCORE",
    "ALG-KK-SCORE-FRONTIER",
    "ALG-KK-SCORE-HEAT",
    "ALG-KK-SCORE-IMPACT",
    "ALG-KK-SCORE-LEVERAGE",
    "ALG-KK-SCORE-PAIN",
    "ALG-KK-SCORE-REFRESH",
    "ALG-KK-VULN-PROPAGATE",
    "INV-KK-GRAPH-FEASIBILITY-BOUNDED",
    "INV-KK-GRAPH-FEASIBILITY-FORMULA",
    "INV-KK-GRAPH-FEASIBILITY-PURE",
    "INV-KK-GRAPH-IMPACT-PROJECTION-COMPLETE",
    "INV-KK-GRAPH-IMPACT-PROJECTION-FORMULA",
    "INV-KK-GRAPH-RESEARCH-SCORE-FORMULA",
    "INV-KK-GRAPH-RESEARCH-SCORE-NO-SECURITY-ONLY",
    "INV-KK-GRAPH-RESEARCH-SCORE-NON-NEGATIVE",
    "INV-KK-GRAPH-RESEARCH-SCORE-PURE",
    "INV-KK-SCORE-CACHE-ATTR",
    "INV-KK-SCORE-CVSS-BRACKETS",
    "INV-KK-SCORE-FRONTIER-FORMULA",
    "INV-KK-SCORE-HEAT-EDGES",
    "INV-KK-SCORE-HEAT-WINDOW",
    "INV-KK-SCORE-LEVERAGE-WEIGHTS",
    "INV-KK-SCORE-NON-NEGATIVE",
    "INV-KK-SCORE-PAIN-WEIGHTS",
    "INV-KK-SCORE-REFRESH-ALL",
    "INV-KK-SCORE-SOLVED-RATIO",
    "INV-KK-VULN-PROP-COMPOSE",
    "INV-KK-VULN-PROP-DIRECT",
    "INV-KK-VULN-PROP-INVARIANT",
    "INV-KK-VULN-PROP-NO-SELF",
    "INV-KK-VULN-PROP-PREREQ",
    # src/ingest/claim_extractor.py
    "INV-KK-CLAIM-CONCEPT-CONTEXT",
    "INV-KK-CLAIM-EDGE-VALID",
    "INV-KK-CLAIM-SOURCE-DATE",
    # src/ingest/classifier.py
    "ALG-KK-CLASSIFY-ASSIGN",
    "ALG-KK-CLASSIFY-PARSE-LLM",
    "ALG-KK-CLASSIFY-RESOLVE-SUBSYSTEM",
    # src/ingest/cli_feed.py
    "ALG-KK-FEED-CLI",
    "INV-KK-FEED-CLI-SOURCE-VALID",
    "INV-KK-FEED-CLI-STATE-REPORT",
    # src/ingest/feed.py
    "ALG-KK-FEED-HN",
    "ALG-KK-FEED-RSS",
    "INV-KK-FEED-DEDUP",
    "INV-KK-FEED-HN-EPOCH",
    "INV-KK-FEED-RSS-CONTENT",
    "INV-KK-FEED-RSS-DATE",
    "INV-KK-FEED-SOURCE-DATE",
    "INV-KK-FEED-STATE",
    # src/ingest/gate.py
    "INV-KK-SESSION-SEPARATION",
    # src/ingest/repo_tracker.py
    "ALG-KK-REPO-TRACK",
    "INV-KK-REPO-FIX-TYPE",
    "INV-KK-REPO-FIXES-TAG",
    "INV-KK-REPO-SUBSYSTEM-MAP",
    # src/ingest/reviewer.py
    "ALG-KK-REVIEW-SOURCE",
    "INV-KK-ADVISORY-REQUIRES-ASSESSMENT",
    "INV-KK-ADVISORY-SINGLE-PER-SOURCE",
    # src/ingest/scanner.py
    "INV-KK-ALL-EVIDENCE-CLASS-A",
    "INV-KK-SCAN-DISCOURSE",
    "INV-KK-UNKNOWN-LICENSE-L4",
    # src/ingest/vuln_tracker.py
    "ALG-KK-VULN-TRACK",
    "INV-KK-VULN-CVE-DEDUP",
    "INV-KK-VULN-CVSS-SEVERITY",
    "INV-KK-VULN-CWE-MAP",
})


#: An id broken across a comment wrap — a line ending in a hyphen, continued on
#: the next line after an optional `#` or `#:` marker. src/graph/rules.py wraps
#: ANN-KK-UNLINKED-PROVENANCE-CENSUS exactly this way, and without rejoining it
#: the scan reports the fragment as a missing node.
WRAPPED_ID = re.compile(r"([A-Z0-9]-)[ \t]*\n[ \t]*(?:#+:?)?[ \t]*([A-Z][A-Z0-9-]*)")


def _cited_spec_ids() -> dict[str, set[str]]:
    cited: dict[str, set[str]] = {}
    for path in sorted((REPO / "src").rglob("*.py")):
        text = WRAPPED_ID.sub(
            r"\1\2", path.read_text(encoding="utf-8", errors="replace"))
        for node_id in SPEC_ID.findall(text):
            cited.setdefault(node_id.rstrip("-"), set()).add(
                path.relative_to(REPO).as_posix())
    return cited


def _unresolved(ids: list[str]) -> set[str]:
    """Ask the RIL which of these do not exist. spec.db is opaque binary and
    the CLI is the only interface to it (CLAUDE.md), so this shells out.

    `query node` answers RIL-ERR-QUERY-NOT-FOUND and `query-multi` answers a
    bare `Node not found: X`. Greps for either alone have produced false
    readings in BOTH directions, so this matches the id out of whichever
    phrasing comes back rather than the phrasing itself.
    """
    # ONE COMMAND PER ID, not one command with many args. `node-info` with
    # several args ABORTS THE WHOLE BLOCK on the first id it cannot find and
    # returns a single error, so batching by 50 reported exactly one missing id
    # per batch — the first version of this sweep reported "five", which was
    # the batch count and not a measurement. One command each costs nothing
    # extra: query-multi still runs them in a single subprocess, which is the
    # expense worth avoiding.
    commands = [{"cmd": "node-info", "args": [i]} for i in ids]
    proc = subprocess.run(
        ["node", "combobul/cli/ril.mjs", "query-multi",
         json.dumps(commands), "--json"],
        cwd=REPO, capture_output=True, text=True, check=False)
    if proc.returncode != 0 or "{" not in proc.stdout:
        pytest.skip("ril CLI unavailable")
    payload = json.loads(proc.stdout[proc.stdout.index("{"):])
    missing: set[str] = set()
    for block in payload["results"]:
        for result in (block.get("results") or [block]):
            if isinstance(result, dict) and "error" in result:
                found = SPEC_ID.search(result["error"])
                if found:
                    missing.add(found.group(0))
    return missing


def test_no_new_spec_id_is_cited_without_existing():
    cited = _cited_spec_ids()
    assert len(cited) > 100, "the citation scan found almost nothing; it broke"
    unresolved = _unresolved(sorted(cited))
    new = unresolved - KNOWN_UNRESOLVED_SPEC_IDS
    assert new == set(), (
        "these spec ids are cited in src/ and do not exist: "
        + ", ".join(f"{i} ({', '.join(sorted(cited[i]))})" for i in sorted(new)))


def test_the_known_unresolved_set_has_not_silently_been_fixed():
    """The counterpart. If one of the five is authored, this fails and the
    frozen set shrinks — so the list cannot quietly rot into a description of
    a problem that no longer exists."""
    cited = _cited_spec_ids()
    unresolved = _unresolved(sorted(cited))
    fixed = KNOWN_UNRESOLVED_SPEC_IDS - unresolved
    assert fixed == set(), (
        "these now exist and should be removed from KNOWN_UNRESOLVED_SPEC_IDS: "
        + ", ".join(sorted(fixed)))


def test_the_claim_extractor_no_longer_cites_a_node_that_does_not_exist():
    """ALG-KK-CLAIM-EXTRACT, authored 2026-09-22. The docstring had cited it
    since the module was written."""
    src = (REPO / "src" / "ingest" / "claim_extractor.py").read_text(encoding="utf-8")
    assert "ALG-KK-CLAIM-EXTRACT" in src
    assert "ALG-KK-CLAIM-EXTRACT" not in KNOWN_UNRESOLVED_SPEC_IDS
