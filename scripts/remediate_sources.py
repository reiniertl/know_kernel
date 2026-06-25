"""Source URL remediation for provenance grounding.

Spec: ALG-KK-REMEDIATE-STUB-SOURCE, INV-KK-REMEDIATION-BACKUP,
      INV-KK-STUB-SOURCE-REPLACED
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from ingest.validate_sources import (
    SourceValidationResult,
    build_replacement_url,
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


def generate_remediation_report(results: list[RemediationResult]) -> str:
    """Generate a markdown report of remediation changes."""
    replaced = [r for r in results if r.action == "stub_replaced"]
    skipped = [r for r in results if r.action == "skipped"]

    lines = [
        "# Source Remediation Report",
        "",
        "## Summary",
        "",
        f"- **Stub sources replaced:** {len(replaced)}",
        f"- **Skipped (no refs):** {len(skipped)}",
        "",
    ]

    if replaced:
        lines.append("## Replaced Stub Sources")
        lines.append("")
        lines.append("| Source ID | Old URL | New URL | Ref |")
        lines.append("|-----------|---------|---------|-----|")
        for r in replaced:
            old_short = r.old_url[:50] + "..." if len(r.old_url) > 50 else r.old_url
            new_short = r.new_url[:50] + "..." if len(r.new_url) > 50 else r.new_url
            lines.append(f"| {r.source_id} | {old_short} | {new_short} | `{r.kernel_doc_ref}` |")
        lines.append("")

    if skipped:
        lines.append("## Skipped Sources")
        lines.append("")
        for r in skipped:
            lines.append(f"- **{r.source_id}**: {r.old_url} (no kernel-doc refs)")
        lines.append("")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    """CLI entry point: python -m scripts.remediate_sources"""
    parser = argparse.ArgumentParser(description="Remediate source URLs")
    parser.add_argument("--db", default="data/know_kernel.db", help="Database path")
    parser.add_argument("--output", default=None, help="Report output file")
    parser.add_argument("--stub-only", action="store_true", help="Only remediate stub sources")
    parser.add_argument("--rate-limit", type=float, default=1.0)
    parser.add_argument("--no-backup", action="store_true", help="Skip backup (dangerous)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)

    if not args.no_backup:
        backup_database(args.db)

    conn = sqlite3.connect(args.db)
    validation_results = validate_all_sources(conn, rate_limit=args.rate_limit)

    stub_results = remediate_stub_sources(conn, validation_results)
    report = generate_remediation_report(stub_results)

    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        log.info("Report written to %s", args.output)
    else:
        print(report)

    conn.close()


if __name__ == "__main__":
    main()
