"""CLI entry point for the extraction service (ALG-KK-EXTRACT-CLI)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from graph.schema import init_db
from ingest.extractor import edge_carries_a_current_verdict, extract_concepts
from ingest.llm_provider import DEFAULT_PROVIDER, PROVIDERS, client_for, default_model_for
from ingest.gate import SessionGate


def select_unextracted(conn) -> list[str]:
    """Evidence with no extracted-from edge at all. 2,028 of 3,566 today."""
    extracted = {
        row[0] for row in conn.execute(
            "SELECT DISTINCT target_id FROM edges WHERE kind = 'extracted-from'"
        ).fetchall()
    }
    return [
        row[0] for row in conn.execute(
            "SELECT id FROM nodes WHERE kind = 'Evidence' ORDER BY id").fetchall()
        if row[0] not in extracted
    ]


def select_for_relink(conn) -> list[str]:
    """Evidence that HAS links but none carrying a current verdict.

    Exactly the population --all-unextracted skips: 1,538 today. Before this
    existed the only whole-corpus flag would have attempted the other 2,028
    and left every legacy link in place, which is an expansion and not a
    re-derivation.

    The current() test is the same one INV-KK-EXTRACT-RELINK-CONVERGENT's
    guard uses, which is what makes a failed run resume rather than skip.
    """
    by_evidence: dict[str, bool] = {}
    for target_id, raw in conn.execute(
        "SELECT target_id, attrs FROM edges WHERE kind = 'extracted-from'"
    ).fetchall():
        try:
            attrs = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            attrs = {}
        current = edge_carries_a_current_verdict(attrs)
        by_evidence[target_id] = by_evidence.get(target_id, False) or current
    return sorted(eid for eid, has_current in by_evidence.items() if not has_current)


def drop_evidence_with_no_input(conn, evidence_ids: list[str]) -> tuple[list[str], list[str]]:
    """Split off the papers that would be sent an empty prompt.

    241 Evidence nodes carry no text. extract_concepts would build a prompt
    from an empty string and the model would be paid to read nothing, so they
    are dropped before --limit is applied — a bounded batch should mean N
    papers actually sent, not N candidates of which some evaporate.

    Only Evidence.text counts. The Source.attrs.text fallback in
    extract_concepts is dead code — zero Sources carry that attribute — and
    teaching it to read Source.attrs.abstract instead was measured and
    refused: it would reach four papers, not the 3,157 that have abstracts,
    because Evidence.text is already populated wherever one exists.
    """
    usable, empty = [], []
    for eid in evidence_ids:
        row = conn.execute(
            "SELECT json_extract(attrs, '$.text') FROM nodes WHERE id = ?", (eid,),
        ).fetchone()
        (usable if row and row[0] else empty).append(eid)
    return usable, empty


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
        help="Every Evidence node with no extracted-from edge",
    )
    group.add_argument(
        "--all-relink", action="store_true",
        help="Every Evidence whose links carry no current verdict — the "
             "re-derivation set, which --all-unextracted skips",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Process at most N Evidence nodes. Applied after the empty-input "
             "filter, so N is how many are actually sent. Batch modes only.",
    )
    parser.add_argument(
        "--provider", default=DEFAULT_PROVIDER, choices=sorted(PROVIDERS),
        help="Which LLM provider to call. AUTHORITATIVE: it selects the "
             "adapter AND the default model, and is never inferred from "
             f"--model (default: {DEFAULT_PROVIDER})",
    )
    parser.add_argument(
        "--model", default=None,
        help="LLM model name. Defaults to the provider's default model; "
             "naming a model does NOT change the provider.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Build and print prompts without calling the LLM API",
    )
    args = parser.parse_args()

    batch_mode = args.all_unextracted or args.all_relink
    if args.limit is not None:
        if not batch_mode:
            parser.error("--limit applies to --all-unextracted or --all-relink; "
                         "--evidence-id is already a batch of one")
        if args.limit < 1:
            parser.error("--limit must be at least 1")

    # Provider is authoritative and the model follows it, never the reverse.
    # A prefix rule that guessed the provider from the model name would
    # silently misroute any identifier it did not recognise; this codebase
    # already refuses one silent-inference shortcut in
    # INV-KK-SUMMARY-EXTRACT-INPUT-BASIS, and summary_extractor states the
    # same rule for this port.
    model = args.model or default_model_for(args.provider)

    try:
        conn = init_db(Path(args.db))
    except Exception as exc:
        print(f"Error: cannot open database '{args.db}': {exc}", file=sys.stderr)
        sys.exit(2)

    gate = SessionGate()

    # Built ONCE for the batch rather than per paper, and NOT AT ALL for a dry
    # run: each adapter constructs its SDK client in __init__ and that raises
    # immediately when no credential is present. A dry run must stay runnable
    # without one — it is how the batch is sized before anybody is charged.
    client = None if args.dry_run else client_for(args.provider)

    if args.all_unextracted:
        candidates = select_unextracted(conn)
    elif args.all_relink:
        candidates = select_for_relink(conn)
    else:
        candidates = [args.evidence_id]

    if batch_mode:
        evidence_ids, skipped_empty = drop_evidence_with_no_input(conn, candidates)
    else:
        evidence_ids, skipped_empty = candidates, []

    selected = len(evidence_ids)
    if args.limit is not None:
        evidence_ids = evidence_ids[:args.limit]

    results = []
    errors = []

    for eid in evidence_ids:
        try:
            result = extract_concepts(
                conn, eid, gate, model=model, dry_run=args.dry_run,
                relink=args.all_relink, client=client,
            )
            results.append({
                "evidence_id": result.evidence_id,
                "concept_ids": result.concept_ids,
                "subsystem_ids": result.subsystem_ids,
                "concepts_created": result.concepts_created,
                "concepts_reused": result.concepts_reused,
                "concepts_rejected": result.concepts_rejected,
                "concepts_skipped": result.concepts_skipped,
                "edges_superseded": result.edges_superseded,
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
        "mode": ("relink" if args.all_relink
                 else "unextracted" if args.all_unextracted else "single"),
        "provider": args.provider,
        "model": model,
        "selected": selected,
        "skipped_empty": len(skipped_empty),
        "attempted": len(evidence_ids),
        "extracted": len(results),
        "errors": len(errors),
        "concepts_created": sum(r["concepts_created"] for r in results),
        "concepts_reused": sum(r["concepts_reused"] for r in results),
        "concepts_rejected": sum(r["concepts_rejected"] for r in results),
        "edges_superseded": sum(r["edges_superseded"] for r in results),
        "results": results,
        "error_details": errors,
    }, indent=2))

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
