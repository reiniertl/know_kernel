"""Batch import/export for paper review lists (ALG-KK-REVIEW-BATCH-IMPORT, ALG-KK-REVIEW-BATCH-EXPORT)."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

from graph.schema import init_db
from ingest.paper_scorer import review_paper


@dataclass
class BatchImportReport:
    imported: int = 0
    skipped: int = 0
    errors: list = field(default_factory=list)


_BLOCK_START = re.compile(r"^--- Paper \d+/\d+ ---$")
_SEPARATOR = re.compile(r"^-{40,}$")
_SCORE_PREFIX = re.compile(r"^Score:\s*(\d)\s*", re.IGNORECASE)


def parse_review_list(file_path: str | Path) -> list[dict]:
    """Parse paper_review_list.txt into a list of reviewed entries."""
    text = Path(file_path).read_text(encoding="utf-8")
    lines = text.splitlines()

    entries = []
    i = 0
    while i < len(lines):
        if not _BLOCK_START.match(lines[i].strip()):
            i += 1
            continue

        i += 1
        title = ""
        decision_line = ""
        notes_lines: list[str] = []
        in_notes = False

        while i < len(lines) and not _SEPARATOR.match(lines[i].strip()):
            line = lines[i]
            stripped = line.strip()

            if stripped.startswith("Title:"):
                title = stripped[len("Title:"):].strip()
                in_notes = False
            elif stripped.startswith("Decision:"):
                decision_line = stripped
                in_notes = False
            elif stripped.startswith("Notes:"):
                notes_text = stripped[len("Notes:"):].strip()
                notes_lines = [notes_text] if notes_text else []
                in_notes = True
            elif in_notes:
                notes_lines.append(line.rstrip())
            i += 1

        if i < len(lines):
            i += 1

        if not decision_line or "[X]" not in decision_line.upper():
            continue

        if "[X] ACCEPT" in decision_line.upper():
            verdict = "accept"
        elif "[X] REJECT" in decision_line.upper():
            verdict = "reject"
        else:
            continue

        notes = "\n".join(notes_lines).strip()

        score_match = _SCORE_PREFIX.match(notes)
        if score_match:
            score = int(score_match.group(1))
            if score < 1 or score > 5:
                score = 4 if verdict == "accept" else 1
            rationale = notes[score_match.end():].strip()
        else:
            score = 4 if verdict == "accept" else 1
            rationale = notes

        if not rationale:
            rationale = f"Batch reviewed as {verdict}"

        entries.append({
            "title": title,
            "verdict": verdict,
            "notes": notes,
            "score": score,
            "rationale": rationale,
        })

    return entries


def import_reviews(
    conn: sqlite3.Connection,
    file_path: str | Path,
    reviewer: str,
) -> BatchImportReport:
    """Import reviews from a filled paper_review_list.txt (INV-KK-REVIEW-BATCH-IDEMPOTENT)."""
    entries = parse_review_list(file_path)
    report = BatchImportReport()

    for entry in entries:
        row = conn.execute(
            "SELECT id FROM nodes WHERE kind = 'Source' AND json_extract(attrs, '$.title') = ?",
            (entry["title"],),
        ).fetchone()

        if row is None:
            report.errors.append({"title": entry["title"], "reason": "Source not found by title"})
            continue

        source_id = row[0]
        try:
            review_paper(conn, source_id, reviewer, entry["score"], entry["verdict"], entry["rationale"])
            report.imported += 1
        except ValueError:
            report.skipped += 1

    return report


def export_review_list(conn: sqlite3.Connection, output_path: str | Path) -> int:
    """Generate paper_review_list.txt from DB state."""
    rows = conn.execute(
        "SELECT id, attrs FROM nodes WHERE kind = 'Source' "
        "AND json_extract(attrs, '$.source_type') IN "
        "('paper','preprint','conference-paper','conference-proceedings') "
        "ORDER BY json_extract(attrs, '$.published_date') DESC, id",
    ).fetchall()

    lines = [
        "=" * 80,
        "PAPER REVIEW LIST - Generated from database",
        f"Total papers: {len(rows)}",
        "=" * 80,
        "",
    ]

    for idx, row in enumerate(rows, 1):
        sid = row[0]
        attrs = json.loads(row[1]) if isinstance(row[1], str) else (row[1] or {})

        rev_row = conn.execute(
            "SELECT n.attrs FROM edges e JOIN nodes n ON e.target_id = n.id "
            "WHERE e.kind = 'reviewed-by' AND e.source_id = ? AND n.kind = 'HumanReview' LIMIT 1",
            (sid,),
        ).fetchone()

        title = attrs.get("title", sid)
        venue = attrs.get("venue", "")
        pub_date = attrs.get("published_date", attrs.get("source_date", ""))
        abstract = attrs.get("abstract", "")

        lines.append(f"--- Paper {idx}/{len(rows)} ---")
        lines.append(f"Title:    {title}")
        if venue:
            lines.append(f"Venue:    {venue}")
        if pub_date:
            lines.append(f"Date:     {pub_date}")
        if abstract:
            lines.append("")
            lines.append("Abstract:")
            lines.append(abstract)
        lines.append("")

        if rev_row:
            r_attrs = json.loads(rev_row[0]) if isinstance(rev_row[0], str) else (rev_row[0] or {})
            verdict = r_attrs.get("verdict", "")
            score = r_attrs.get("score", "")
            rationale = r_attrs.get("rationale", "")
            if verdict == "accept":
                lines.append("Decision: [X] ACCEPT  [ ] REJECT")
            elif verdict == "reject":
                lines.append("Decision: [ ] ACCEPT  [X] REJECT")
            else:
                lines.append("Decision: [ ] ACCEPT  [ ] REJECT")
            notes_parts = []
            if score:
                notes_parts.append(f"Score: {score}")
            if rationale:
                notes_parts.append(rationale)
            lines.append(f"Notes:    {' '.join(notes_parts)}")
        else:
            lines.append("Decision: [ ] ACCEPT  [ ] REJECT")
            lines.append("Notes:    ")

        lines.append("")
        lines.append("-" * 80)
        lines.append("")

    Path(output_path).write_text("\n".join(lines), encoding="utf-8")
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(prog="kk-batch-score", description="Batch import/export paper reviews.")
    sub = parser.add_subparsers(dest="command")

    imp = sub.add_parser("import", help="Import reviews from a filled paper_review_list.txt")
    imp.add_argument("--db", required=True, help="Path to master SQLite database")
    imp.add_argument("--file", required=True, help="Path to filled paper_review_list.txt")
    imp.add_argument("--reviewer", required=True, help="Reviewer identifier")

    exp = sub.add_parser("export", help="Export paper_review_list.txt from database")
    exp.add_argument("--db", required=True, help="Path to master SQLite database")
    exp.add_argument("--output", required=True, help="Output file path")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(2)

    try:
        conn = init_db(Path(args.db))
    except Exception as exc:
        print(f"Error: cannot open database: {exc}", file=sys.stderr)
        sys.exit(2)

    if args.command == "import":
        report = import_reviews(conn, args.file, args.reviewer)
        conn.commit()
        print(json.dumps({
            "imported": report.imported,
            "skipped": report.skipped,
            "errors": report.errors,
        }, indent=2))
    elif args.command == "export":
        count = export_review_list(conn, args.output)
        print(f"Exported {count} papers to {args.output}")


if __name__ == "__main__":
    main()
