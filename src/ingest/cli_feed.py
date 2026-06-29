"""CLI entry point for feed polling and status (ALG-KK-FEED-CLI)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from graph.schema import init_db
from ingest.feed import (
    FeedConfig,
    HNFeedPoller,
    RSSFeedPoller,
    load_feed_state,
)

DEFAULT_DB = Path("data/know_kernel.db")
DEFAULT_CONFIGS = Path("data/feed_configs.json")
BUILTIN_SOURCES = {"kernel-git", "cve"}


def load_feed_configs(path: Path = DEFAULT_CONFIGS) -> list[FeedConfig]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    configs = []
    for entry in data.get("feeds", []):
        configs.append(FeedConfig(
            name=entry["name"],
            feed_type=entry["feed_type"],
            url=entry["url"],
            poll_interval_seconds=entry.get("poll_interval_seconds", 3600),
            kernel_filter=entry.get("kernel_filter"),
        ))
    return configs


def get_valid_sources(configs: list[FeedConfig]) -> set[str]:
    """INV-KK-FEED-CLI-SOURCE-VALID: valid source names."""
    return {c.name for c in configs} | BUILTIN_SOURCES


def _make_poller(config: FeedConfig):
    if config.feed_type == "rss":
        return RSSFeedPoller(config)
    elif config.feed_type == "api":
        return HNFeedPoller(config)
    return None


def cmd_poll(args: argparse.Namespace, configs: list[FeedConfig]) -> int:
    valid = get_valid_sources(configs)
    conn = init_db(Path(args.db))

    sources_to_poll: list[str] = []
    if args.all:
        sources_to_poll = [c.name for c in configs] + list(BUILTIN_SOURCES)
    elif args.source:
        if args.source not in valid:
            print(
                f"Error: unknown source '{args.source}'. "
                f"Valid sources: {', '.join(sorted(valid))}",
                file=sys.stderr,
            )
            return 2
        sources_to_poll = [args.source]
    else:
        print("Error: specify --source <name> or --all", file=sys.stderr)
        return 2

    config_map = {c.name: c for c in configs}
    total = 0

    for source_name in sources_to_poll:
        if source_name == "kernel-git":
            print(f"[kernel-git] Repo tracking requires a local git repo path (use repo_tracker directly).")
            continue
        elif source_name == "cve":
            print(f"[cve] CVE polling requires NVD API access (use vuln_tracker directly).")
            continue

        config = config_map.get(source_name)
        if not config:
            continue

        poller = _make_poller(config)
        if poller is None:
            print(f"[{source_name}] Unsupported feed type: {config.feed_type}", file=sys.stderr)
            continue

        print(f"[{source_name}] Polling {config.url}...")
        try:
            results = poller.poll(conn)
            count = len(results)
            total += count
            print(f"[{source_name}] Ingested {count} new item(s).")
        except Exception as exc:
            print(f"[{source_name}] Error: {exc}", file=sys.stderr)

    if args.extract:
        print("[extract] Claim extraction not yet available (Phase 5).")

    print(f"\nTotal: {total} new item(s) ingested.")
    return 0


def cmd_status(args: argparse.Namespace, configs: list[FeedConfig]) -> int:
    """INV-KK-FEED-CLI-STATE-REPORT: show last poll time per source."""
    state = load_feed_state()
    all_sources = [c.name for c in configs] + sorted(BUILTIN_SOURCES)

    print(f"{'Source':<20} {'Last Polled':<25}")
    print("-" * 45)
    for name in all_sources:
        source_state = state.get(name, {})
        last = source_state.get("last_fetched_timestamp", "never")
        if not last:
            last = "never"
        print(f"{name:<20} {last:<25}")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="kk-feed",
        description="Feed ingestion for know_kernel.",
    )
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Path to master SQLite database")
    subparsers = parser.add_subparsers(dest="command")

    poll_parser = subparsers.add_parser("poll", help="Poll feed sources for new items")
    poll_parser.add_argument("--source", help="Feed source name to poll")
    poll_parser.add_argument("--all", action="store_true", help="Poll all configured sources")
    poll_parser.add_argument("--extract", action="store_true", help="Run claim extraction on new items (stub)")

    subparsers.add_parser("status", help="Show last poll time per source")

    args = parser.parse_args()
    configs = load_feed_configs()

    if args.command == "poll":
        sys.exit(cmd_poll(args, configs))
    elif args.command == "status":
        sys.exit(cmd_status(args, configs))
    else:
        parser.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
