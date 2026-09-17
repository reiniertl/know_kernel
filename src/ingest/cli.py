"""CLI entry point for the ingestion service (ALG-KK-INGEST-CLI).

Summary extraction runs here as a FINAL STAGE, after every document has landed
and been committed (D-15b). It is deliberately not called from inside
ingest_document: that function is per-document, synchronous and offline, while
extraction is a rate-limited network call, and inline one API failure would
leave a document written but unsummarised with nothing recording which half
failed. As a stage the documents are already durable before the first model call
and the pass is independently resumable.

The stage is SCOPED to the Sources this invocation created. Unscoped it would
consider every unsummarised paper in the database — 3,482 of them measured
2026-09-17 — so ingesting one document would trigger a corpus migration.
"""


from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from graph.schema import init_db
from ingest.gate import SessionGate
from ingest.pipeline import ingest_document


def main(argv: list[str] | None = None, client=None) -> None:
    parser = argparse.ArgumentParser(
        prog="kk-ingest",
        description="Ingest documents into the know_kernel master database.",
    )
    parser.add_argument("--db", required=True, help="Path to master SQLite database")
    parser.add_argument("--input", required=True, help="File or directory to ingest")
    parser.add_argument("--url", required=True, help="Source URL for the document(s)")
    parser.add_argument(
        "--provider", default=None,
        help="Model provider for the summary stage (see kk-summaries --provider). "
             "Defaults to the extractor's own default.",
    )
    parser.add_argument(
        "--model", default="",
        help="Override the provider's default model for the summary stage.",
    )
    parser.add_argument(
        "--skip-summaries", action="store_true",
        help="Ingest without running the summary extraction stage. For offline "
             "runs and tests: the Anthropic client is imported lazily so this "
             "module works with the ingest extra absent.",
    )
    parser.add_argument(
        "--type", dest="source_type", default="preprint",
        help="Source type. The canonical paper vocabulary is preprint, "
             "conference-paper, conference-proceedings "
             "(INV-KK-PAPER-SOURCE-TYPE-VOCABULARY); other values are legal but "
             "are not treated as papers.",
    )
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: input path not found: {args.input}", file=sys.stderr)
        sys.exit(2)

    try:
        conn = init_db(Path(args.db))
    except Exception as exc:
        print(f"Error: cannot open database '{args.db}': {exc}", file=sys.stderr)
        sys.exit(2)

    files = sorted(f for f in input_path.rglob("*") if f.is_file()) \
        if input_path.is_dir() else [input_path]

    gate = SessionGate()

    results = []
    errors = []

    for fp in files:
        try:
            result = ingest_document(conn, str(fp), args.url, args.source_type, gate=gate)
            results.append({
                "file": str(fp),
                "source_id": result.source_id,
                "evidence_id": result.evidence_id,
                "contamination_level": result.scan_result.contamination_level.value,
                "licenses_found": result.scan_result.licenses_found,
                "file_type": result.file_type,
                "text_length": result.text_length,
            })
        except Exception as exc:
            print(f"Error ingesting {fp}: {exc}", file=sys.stderr)
            errors.append({"file": str(fp), "error": str(exc)})

    conn.commit()

    # --- final stage: summary extraction (D-15b) ---------------------------
    # Everything above is already committed. A failure here costs the summaries,
    # never the documents — which is the whole reason this is a stage and not a
    # call inside ingest_document.
    summaries = None
    ingested_ids = [r["source_id"] for r in results]
    if not args.skip_summaries and ingested_ids:
        from ingest.cli_summaries import run_batch
        from ingest.summary_extractor import DEFAULT_PROVIDER

        try:
            report = run_batch(
                conn, client=client, source_ids=ingested_ids,
                provider=args.provider or DEFAULT_PROVIDER, model=args.model,
            )
            conn.commit()
            summaries = report.as_dict()
        except Exception as exc:
            # The documents stay. Report the failure rather than raising through
            # a successful ingest.
            print(f"Error running the summary stage: {exc}", file=sys.stderr)
            summaries = {"error": str(exc)}
    elif args.skip_summaries:
        summaries = {"skipped": "--skip-summaries"}

    print(json.dumps({
        "ingested": len(results),
        "errors": len(errors),
        "results": results,
        "error_details": errors,
        "summaries": summaries,
    }, indent=2))

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
