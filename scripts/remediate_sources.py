"""Source URL remediation for provenance grounding.

Spec: ALG-KK-REMEDIATE-STUB-SOURCE, ALG-KK-REMEDIATE-DIRECTORY-SOURCE,
      ALG-KK-UPDATE-CODE-EXAMPLE-URLS, INV-KK-REMEDIATION-BACKUP,
      INV-KK-STUB-SOURCE-REPLACED, INV-KK-DIRECTORY-SOURCE-REPLACED,
      INV-KK-CODE-EXAMPLE-SOURCE-VALID
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ingest.validate_sources import (
    SourceValidationResult,
    build_replacement_url,
    resolve_directory_url,
    validate_all_sources,
)

log = logging.getLogger(__name__)


@dataclass
class RemediationResult:
    source_id: str
    old_url: str
    new_url: str
    action: str  # "stub_replaced" | "skipped" | "directory_replaced" | ...
    kernel_doc_ref: str = ""


def backup_database(db_path: str) -> str:
    """Create a backup at {db_path}.pre-remediation (INV-KK-REMEDIATION-BACKUP)."""
    backup_path = f"{db_path}.pre-remediation"
    shutil.copy2(db_path, backup_path)
    log.info("Backup created at %s", backup_path)
    return backup_path


def _select_primary_ref(kernel_doc_refs: list[str]) -> str | None:
    """Select the primary kernel-doc ref, preferring .c over .h."""
    if not kernel_doc_refs:
        return None
    c_refs = [r for r in kernel_doc_refs if r.endswith(".c")]
    if c_refs:
        return c_refs[0]
    return kernel_doc_refs[0]


def remediate_stub_sources(
    conn: sqlite3.Connection,
    validation_results: list[SourceValidationResult],
) -> list[RemediationResult]:
    """Replace stub source URLs with actual content URLs (ALG-KK-REMEDIATE-STUB-SOURCE).

    For each stub source, selects the primary kernel-doc reference (.c preferred
    over .h), builds a git.kernel.org blob URL, and updates the Source node's
    url attribute. Satisfies INV-KK-STUB-SOURCE-REPLACED.
    """
    results: list[RemediationResult] = []

    for vr in validation_results:
        if vr.classification != "stub":
            continue

        primary_ref = _select_primary_ref(vr.kernel_doc_refs)
        if not primary_ref:
            results.append(RemediationResult(
                source_id=vr.source_id,
                old_url=vr.url,
                new_url=vr.url,
                action="skipped",
            ))
            log.warning("Stub %s has no kernel-doc refs, skipping", vr.source_id)
            continue

        new_url = build_replacement_url(primary_ref)

        row = conn.execute(
            "SELECT attrs FROM nodes WHERE id = ?", (vr.source_id,)
        ).fetchone()
        if row is None:
            log.warning("Source %s not found in DB, skipping", vr.source_id)
            continue

        attrs = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        attrs["url"] = new_url
        conn.execute(
            "UPDATE nodes SET attrs = ? WHERE id = ?",
            (json.dumps(attrs), vr.source_id),
        )

        results.append(RemediationResult(
            source_id=vr.source_id,
            old_url=vr.url,
            new_url=new_url,
            action="stub_replaced",
            kernel_doc_ref=primary_ref,
        ))
        log.info("Replaced %s: %s -> %s", vr.source_id, vr.url, new_url)

    conn.commit()
    return results


def remediate_directory_sources(
    conn: sqlite3.Connection,
    validation_results: list[SourceValidationResult],
    fetch_fn: Callable[[str], str] | None = None,
) -> list[RemediationResult]:
    """Replace directory source URLs with specific file URLs (ALG-KK-REMEDIATE-DIRECTORY-SOURCE).

    For each directory source, fetches the listing via resolve_directory_url(),
    selects the best file. If there is a single clear winner (index.rst present,
    or only one candidate), updates the URL. Otherwise flags as ambiguous.
    Satisfies INV-KK-DIRECTORY-SOURCE-REPLACED.
    """
    results: list[RemediationResult] = []

    for vr in validation_results:
        if vr.classification != "directory":
            continue

        candidates = vr.suggested_replacement_urls
        if not candidates and fetch_fn:
            candidates = resolve_directory_url(vr.url, fetch_fn=fetch_fn)

        if not candidates:
            results.append(RemediationResult(
                source_id=vr.source_id, old_url=vr.url, new_url=vr.url,
                action="skipped",
            ))
            log.warning("Directory %s: no candidate files found", vr.source_id)
            continue

        index_candidates = [u for u in candidates if "index" in u.lower().rsplit("/", 1)[-1]]
        if index_candidates:
            best = index_candidates[0]
        elif len(candidates) == 1:
            best = candidates[0]
        else:
            results.append(RemediationResult(
                source_id=vr.source_id, old_url=vr.url, new_url=vr.url,
                action="flagged_ambiguous",
            ))
            log.info("Directory %s flagged: %d candidates, needs manual review",
                     vr.source_id, len(candidates))
            continue

        row = conn.execute(
            "SELECT attrs FROM nodes WHERE id = ?", (vr.source_id,)
        ).fetchone()
        if row is None:
            continue

        attrs = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        attrs["url"] = best
        conn.execute(
            "UPDATE nodes SET attrs = ? WHERE id = ?",
            (json.dumps(attrs), vr.source_id),
        )

        results.append(RemediationResult(
            source_id=vr.source_id, old_url=vr.url, new_url=best,
            action="directory_replaced",
        ))
        log.info("Replaced directory %s: %s -> %s", vr.source_id, vr.url, best)

    conn.commit()
    return results


def update_code_example_urls(
    conn: sqlite3.Connection,
    remediation_results: list[RemediationResult],
) -> int:
    """Update code example source_urls to match remediated Source URLs
    (ALG-KK-UPDATE-CODE-EXAMPLE-URLS).

    For each Concept with code_examples, if any example's source_url exactly
    matches an old (pre-remediation) URL, replace it with the new URL.
    Returns count of updated examples. Satisfies INV-KK-CODE-EXAMPLE-SOURCE-VALID.
    """
    url_map = {
        r.old_url: r.new_url
        for r in remediation_results
        if r.action in ("stub_replaced", "directory_replaced") and r.old_url != r.new_url
    }
    if not url_map:
        return 0

    rows = conn.execute(
        "SELECT id, attrs FROM nodes WHERE kind = 'Concept'"
    ).fetchall()

    updated_count = 0
    for node_id, attrs_json in rows:
        attrs = json.loads(attrs_json) if isinstance(attrs_json, str) else attrs_json
        examples = attrs.get("code_examples", [])
        if not examples:
            continue

        changed = False
        for ex in examples:
            src_url = ex.get("source_url")
            if src_url and src_url in url_map:
                ex["source_url"] = url_map[src_url]
                changed = True
                updated_count += 1

        if changed:
            conn.execute(
                "UPDATE nodes SET attrs = ? WHERE id = ?",
                (json.dumps(attrs), node_id),
            )

    conn.commit()
    return updated_count


def generate_remediation_report(results: list[RemediationResult], code_example_count: int = 0) -> str:
    """Generate a markdown report of remediation changes."""
    stub_replaced = [r for r in results if r.action == "stub_replaced"]
    dir_replaced = [r for r in results if r.action == "directory_replaced"]
    flagged = [r for r in results if r.action == "flagged_ambiguous"]
    skipped = [r for r in results if r.action == "skipped"]

    lines = [
        "# Source Remediation Report",
        "",
        "## Summary",
        "",
        f"- **Stub sources replaced:** {len(stub_replaced)}",
        f"- **Directory sources replaced:** {len(dir_replaced)}",
        f"- **Directory sources flagged (ambiguous):** {len(flagged)}",
        f"- **Code examples updated:** {code_example_count}",
        f"- **Skipped:** {len(skipped)}",
        "",
    ]

    if stub_replaced:
        lines.append("## Replaced Stub Sources")
        lines.append("")
        lines.append("| Source ID | Old URL | New URL | Ref |")
        lines.append("|-----------|---------|---------|-----|")
        for r in stub_replaced:
            old_short = r.old_url[:50] + "..." if len(r.old_url) > 50 else r.old_url
            new_short = r.new_url[:50] + "..." if len(r.new_url) > 50 else r.new_url
            lines.append(f"| {r.source_id} | {old_short} | {new_short} | `{r.kernel_doc_ref}` |")
        lines.append("")

    if dir_replaced:
        lines.append("## Replaced Directory Sources")
        lines.append("")
        lines.append("| Source ID | Old URL | New URL |")
        lines.append("|-----------|---------|---------|")
        for r in dir_replaced:
            old_short = r.old_url[:50] + "..." if len(r.old_url) > 50 else r.old_url
            new_short = r.new_url[:50] + "..." if len(r.new_url) > 50 else r.new_url
            lines.append(f"| {r.source_id} | {old_short} | {new_short} |")
        lines.append("")

    if flagged:
        lines.append("## Flagged for Manual Review")
        lines.append("")
        for r in flagged:
            lines.append(f"- **{r.source_id}**: {r.old_url} (ambiguous candidates)")
        lines.append("")

    if skipped:
        lines.append("## Skipped Sources")
        lines.append("")
        for r in skipped:
            lines.append(f"- **{r.source_id}**: {r.old_url}")
        lines.append("")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    """CLI entry point: python -m scripts.remediate_sources"""
    parser = argparse.ArgumentParser(description="Remediate source URLs")
    parser.add_argument("--db", default="data/know_kernel.db", help="Database path")
    parser.add_argument("--output", default=None, help="Report output file")
    parser.add_argument("--stub-only", action="store_true", help="Only remediate stub sources")
    parser.add_argument("--directory-only", action="store_true", help="Only remediate directory sources")
    parser.add_argument("--code-examples-only", action="store_true", help="Only update code example URLs")
    parser.add_argument("--rate-limit", type=float, default=1.0)
    parser.add_argument("--no-backup", action="store_true", help="Skip backup (dangerous)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)
    do_all = not (args.stub_only or args.directory_only or args.code_examples_only)

    if not args.no_backup:
        backup_database(args.db)

    conn = sqlite3.connect(args.db)
    validation_results = validate_all_sources(conn, rate_limit=args.rate_limit)

    all_results: list[RemediationResult] = []
    code_count = 0

    if do_all or args.stub_only:
        all_results.extend(remediate_stub_sources(conn, validation_results))

    if do_all or args.directory_only:
        all_results.extend(remediate_directory_sources(conn, validation_results))

    if do_all or args.code_examples_only:
        code_count = update_code_example_urls(conn, all_results)

    report = generate_remediation_report(all_results, code_example_count=code_count)

    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        log.info("Report written to %s", args.output)
    else:
        print(report)

    conn.close()


if __name__ == "__main__":
    main()
