"""CLI for the documentation harvest and its revert (ALG-KK-DOC-HARVEST-CLI).

    python -m ingest.cli_harvest --db data/master.db --dry-run
    python -m ingest.cli_harvest --db data/master.db --provider openai --limit 5
    python -m ingest.cli_harvest --db data/master.db --revert harvest-2026-09-25-ab12cd34

IT FOLLOWS ALG-KK-EXTRACT-CLI'S CONTRACT RATHER THAN INVENTING A THIRD
CONVENTION. --dry-run returns before any client is constructed, so it needs no
credential. --limit applies after selection and after the empty-input filter, so
--limit 10 means ten documents actually sent. --provider selects the adapter AND
the default model and is never inferred from --model. The client is built once,
before the loop, so a missing credential fails immediately rather than once per
document.

THE REVERT IS THIS COMMAND AND NOT A SECOND TOOL, deliberately: a revert that
ships as a separate script is a revert that is not installed when it is needed.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import sqlite3
import sys

from ingest.doc_harvest import (
    format_revert_report,
    harvest_document,
    new_batch_id,
    revert_batch,
    select_doc_evidence,
)
from ingest.llm_provider import DEFAULT_PROVIDER, PROVIDERS, client_for, default_model_for

log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Harvest Concepts from canonical documentation, or revert a batch",
    )
    parser.add_argument("--db", required=True, help="Path to master SQLite database")
    parser.add_argument(
        "--revert", default=None, metavar="BATCH_ID",
        help="Undo a harvest batch by id instead of harvesting. Skips any "
             "concept a human has reviewed or retired, or that a later run has "
             "linked, names each one, and exits 1 if anything was skipped.",
    )
    parser.add_argument(
        "--source-type", action="append", dest="source_types", default=None,
        help="Restrict to these Source types; repeatable. Defaults to "
             "DOC_SOURCE_TYPES per IFC-KK-DOC-DEFINED-PROVENANCE.",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Bound the run to N documents, applied AFTER selection and AFTER "
             "the empty-input filter.",
    )
    parser.add_argument(
        "--provider", default=DEFAULT_PROVIDER, choices=sorted(PROVIDERS),
        help="Selects the adapter AND the default model. Never inferred from "
             f"--model (default: {DEFAULT_PROVIDER})",
    )
    parser.add_argument(
        "--model", default=None,
        help="Model name. Defaults to the provider's default; naming a model "
             "does NOT change the provider.",
    )
    parser.add_argument(
        "--include-harvested", action="store_true",
        help="Re-read documents that already carry a Concept edge. OFF by "
             "default: a bare run can never migrate an earlier batch's edges "
             "(INV-KK-HARVEST-BATCH-REVERTIBLE). _attach refuses to take "
             "ownership either way, so this flag widens the selection and "
             "does not weaken the guarantee.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Build prompts and report what would happen; construct no client "
             "and write nothing",
    )
    args = parser.parse_args(argv)

    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.revert and (args.limit or args.source_types):
        parser.error("--revert takes a batch id and no selection options")

    logging.basicConfig(level=logging.INFO)
    conn = sqlite3.connect(args.db)

    if args.revert:
        report = revert_batch(conn, args.revert, dry_run=args.dry_run)
        conn.close()
        print(format_revert_report(report))
        # Non-zero when anything was skipped, so a partial revert can never be
        # mistaken for a clean one by a script or by a person reading a prompt.
        sys.exit(0 if report.clean else 1)

    batch_id = new_batch_id()
    evidence_ids, skipped_empty, skipped_harvested = select_doc_evidence(
        conn, tuple(args.source_types) if args.source_types else None,
        include_harvested=args.include_harvested)
    selected = len(evidence_ids)
    if args.limit is not None:
        evidence_ids = evidence_ids[:args.limit]

    # ONCE, and BEFORE the loop, so a missing credential fails the invocation
    # immediately. Not at all for a dry run — each adapter builds its SDK
    # client in __init__ and that raises without a credential, and sizing a
    # batch has to work for someone deciding whether to pay for the real one.
    client = None if args.dry_run else client_for(args.provider)
    model = args.model or default_model_for(args.provider)

    from graph.concept_vocabulary import build_vocabulary_context
    from ingest.doc_harvest import build_subsystem_context, resolve_subsystem_names

    vocabulary = build_vocabulary_context(conn)
    subsystem_context = build_subsystem_context(conn)
    subsystems = resolve_subsystem_names(conn)

    results, errors = [], []
    for eid in evidence_ids:
        try:
            results.append(dataclasses.asdict(harvest_document(
                conn, eid, batch_id, client=client, model=model,
                dry_run=args.dry_run, vocabulary=vocabulary,
                subsystem_context=subsystem_context, subsystems=subsystems)))
        except Exception as exc:  # one document does not abort the batch
            print(f"Error harvesting {eid}: {exc}", file=sys.stderr)
            errors.append({"evidence_id": eid, "error": str(exc)})

    if not args.dry_run:
        conn.commit()
    conn.close()

    # Built from the dataclass with asdict, NOT field by field:
    # ALG-KK-EXTRACT-CLI carried concepts_rejected on its result and omitted it
    # from a hand-built dict for a whole run, printing a silently incomplete
    # report. A field added later cannot be dropped by omission here.
    print(json.dumps({
        "batch_id": batch_id,
        "dry_run": args.dry_run,
        "provider": args.provider,
        "model": model,
        "selected": selected,
        "skipped_empty": len(skipped_empty),
        "skipped_harvested": len(skipped_harvested),
        "attempted": len(evidence_ids),
        "errors": len(errors),
        "concepts_created": sum(len(r["concepts_created"]) for r in results),
        "concepts_attached": sum(len(r["concepts_attached"]) for r in results),
        "rejected_not_mechanism": sum(r["rejected_not_mechanism"] for r in results),
        "rejected_incomplete": sum(r["rejected_incomplete"] for r in results),
        "rejected_not_a_class": sum(r["rejected_not_a_class"] for r in results),
        "attached_foreign": sum(r["attached_foreign"] for r in results),
        # INV-KK-LLM-CACHE-REPORTED: read from the provider, never computed.
        # A zero across a batch sharing one prefix means something is
        # invalidating it, and every cause is silent.
        "cached_tokens": sum(r.get("cached_tokens", 0) for r in results),
        "subsystems_unmatched": sum(1 for r in results if r["subsystem_unmatched"]),
        "results": results,
        "error_details": errors,
    }, indent=2))

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
