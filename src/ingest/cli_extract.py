"""CLI entry point for the extraction service (ALG-KK-EXTRACT-CLI)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from graph.schema import init_db
from ingest.extractor import extract_concepts
from ingest.gate import SessionGate


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="kk-extract",
        description="Extract abstract concepts from Evidence nodes via LLM.",
    )
    parser.add_argument("--db", required=True, help="Path to master SQLite database")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--evidence-id", help="Single Evidence node ID to extract from")
    group.add_argument(
        "--all-unextracted", action="store_true",
        help="Find all Evidence nodes without extracted Concepts and extract from each",
    )
    parser.add_argument(
        "--model", default="claude-sonnet-4-6",
        help="LLM model name (default: claude-sonnet-4-6)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Build and print prompts without calling the LLM API",
    )
    args = parser.parse_args()

    try:
        conn = init_db(Path(args.db))
    except Exception as exc:
        print(f"Error: cannot open database '{args.db}': {exc}", file=sys.stderr)
        sys.exit(2)

    gate = SessionGate()

    if args.all_unextracted:
        all_evidence = conn.execute(
            "SELECT id FROM nodes WHERE kind = 'Evidence'"
        ).fetchall()
        extracted = set(
            row[0] for row in conn.execute(
                "SELECT DISTINCT target_id FROM edges WHERE kind = 'extracted-from'"
            ).fetchall()
        )
        evidence_ids = [row[0] for row in all_evidence if row[0] not in extracted]
    else:
        evidence_ids = [args.evidence_id]

    results = []
    errors = []

    for eid in evidence_ids:
        try:
            result = extract_concepts(
                conn, eid, gate, model=args.model, dry_run=args.dry_run,
            )
            results.append({
                "evidence_id": result.evidence_id,
                "concept_ids": result.concept_ids,
                "subsystem_ids": result.subsystem_ids,
                "concepts_created": result.concepts_created,
                "concepts_skipped": result.concepts_skipped,
                "extraction_model": result.extraction_model,
                "prompt_tokens": result.prompt_tokens,
                "response_tokens": result.response_tokens,
            })
        except ValueError as exc:
            print(f"Error extracting {eid}: {exc}", file=sys.stderr)
            errors.append({"evidence_id": eid, "error": str(exc)})
        except Exception as exc:
            print(f"Error extracting {eid}: {exc}", file=sys.stderr)
            errors.append({"evidence_id": eid, "error": str(exc)})

    if not args.dry_run:
        conn.commit()

    print(json.dumps({
        "extracted": len(results),
        "errors": len(errors),
        "results": results,
        "error_details": errors,
    }, indent=2))

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
