"""Feed ingestion pipeline -- poll live sources and create Source + Evidence nodes (ALG-KK-FEED-POLL)."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from graph.engine import add_edge, add_node

log = logging.getLogger(__name__)

DEFAULT_STATE_PATH = Path("data/feed_state.json")


@dataclass
class FeedConfig:
    name: str
    feed_type: str
    url: str
    poll_interval_seconds: int = 3600
    kernel_filter: str | None = None


@dataclass
class FeedItem:
    title: str
    url: str
    content: str
    published: str
    source_feed: str
    metadata: dict[str, Any] = field(default_factory=dict)


def load_feed_state(state_path: Path = DEFAULT_STATE_PATH) -> dict[str, Any]:
    if state_path.exists():
        return json.loads(state_path.read_text(encoding="utf-8"))
    return {}


def save_feed_state(state: dict[str, Any], state_path: Path = DEFAULT_STATE_PATH) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _source_url_exists(conn: sqlite3.Connection, url: str) -> bool:
    """INV-KK-FEED-DEDUP: check if a Source with this URL already exists."""
    row = conn.execute(
        "SELECT 1 FROM nodes WHERE kind = 'Source' AND json_extract(attrs, '$.url') = ?",
        (url,),
    ).fetchone()
    return row is not None


def is_duplicate(conn: sqlite3.Connection, url: str, state: dict[str, Any], source_name: str) -> bool:
    """INV-KK-FEED-DEDUP: check both DB and feed state for URL."""
    if _source_url_exists(conn, url):
        return True
    seen_urls = state.get(source_name, {}).get("seen_urls", [])
    return url in seen_urls


def ingest_item(conn: sqlite3.Connection, item: FeedItem) -> tuple[str, str]:
    """INV-KK-FEED-SOURCE-NODE: create Source + Evidence nodes for a feed item.

    Returns (source_id, evidence_id).
    """
    source_id = f"src-{uuid.uuid4().hex[:12]}"
    evidence_id = f"ev-{uuid.uuid4().hex[:12]}"

    add_node(conn, source_id, "Source", {
        "url": item.url,
        "source_type": "discourse",
        "license": "unknown",
    })

    add_node(conn, evidence_id, "Evidence", {
        "artifact_class": "licensed-evidence",
        "contamination_level": "weak-copyleft",
        "description": item.title,
        "text": item.content,
    })

    add_edge(conn, "sourced-from", evidence_id, source_id)

    return source_id, evidence_id


class FeedPoller(ABC):
    """Base class for feed pollers. Subclasses implement fetch()."""

    def __init__(self, config: FeedConfig, state_path: Path = DEFAULT_STATE_PATH) -> None:
        self.config = config
        self.state_path = state_path

    @abstractmethod
    def fetch(self) -> list[FeedItem]:
        """Fetch new items from the feed source. Must set FeedItem.published
        to the SOURCE publication date (INV-KK-FEED-SOURCE-DATE)."""
        ...

    def poll(self, conn: sqlite3.Connection) -> list[tuple[str, str]]:
        """Poll the feed and ingest new items. Returns list of (source_id, evidence_id).

        INV-KK-FEED-DEDUP: skips duplicate URLs.
        INV-KK-FEED-STATE: persists state after poll.
        INV-KK-FEED-SOURCE-NODE: creates Source+Evidence per item.
        """
        state = load_feed_state(self.state_path)
        items = self.fetch()
        results: list[tuple[str, str]] = []

        source_state = state.get(self.config.name, {"seen_urls": [], "last_fetched_timestamp": ""})
        seen_urls: list[str] = source_state.get("seen_urls", [])
        seen_set = set(seen_urls)

        for item in items:
            if is_duplicate(conn, item.url, state, self.config.name):
                log.debug("Skipping duplicate URL: %s", item.url)
                continue

            src_id, ev_id = ingest_item(conn, item)
            results.append((src_id, ev_id))
            seen_set.add(item.url)

        source_state["seen_urls"] = list(seen_set)
        if items:
            source_state["last_fetched_timestamp"] = items[-1].published
            source_state["last_fetched_url"] = items[-1].url
        state[self.config.name] = source_state
        save_feed_state(state, self.state_path)

        return results


def _struct_time_to_iso(t: time.struct_time | None) -> str:
    """INV-KK-FEED-RSS-DATE: convert time_struct to ISO-8601 date. Empty string if None."""
    if t is None:
        return ""
    return time.strftime("%Y-%m-%d", t)


def _extract_rss_content(entry: Any) -> str:
    """INV-KK-FEED-RSS-CONTENT: extract content from RSS entry, never empty."""
    if hasattr(entry, "content") and entry.content:
        value = entry.content[0].get("value", "")
        if value.strip():
            return value.strip()
    summary = getattr(entry, "summary", "")
    if summary and summary.strip():
        return summary.strip()
    return getattr(entry, "title", "No content").strip() or "No content"


class RSSFeedPoller(FeedPoller):
    """ALG-KK-FEED-RSS: RSS/Atom feed parser using feedparser library."""

    def __init__(self, config: FeedConfig, state_path: Path = DEFAULT_STATE_PATH, raw_xml: str | None = None) -> None:
        super().__init__(config, state_path)
        self._raw_xml = raw_xml

    def fetch(self) -> list[FeedItem]:
        import feedparser

        if self._raw_xml is not None:
            feed = feedparser.parse(self._raw_xml)
        else:
            feed = feedparser.parse(self.config.url)

        items: list[FeedItem] = []
        for entry in feed.entries:
            link = getattr(entry, "link", "")
            if not link:
                continue
            title = getattr(entry, "title", "").strip() or "Untitled"
            content = _extract_rss_content(entry)
            published = _struct_time_to_iso(getattr(entry, "published_parsed", None))
            items.append(FeedItem(
                title=title,
                url=link,
                content=content,
                published=published,
                source_feed=self.config.name,
            ))
        return items
