"""Feed ingestion pipeline -- poll live sources and create Source + Evidence nodes (ALG-KK-FEED-POLL)."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
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


#: Terms that mark an item as being about the Linux kernel. Deliberately
#: NARROW and about the kernel as such, not about computing: "memory" and
#: "storage" and "performance" are what the nine off-topic Sources of
#: 2026-10-05 were full of.
KERNEL_TERMS = frozenset("""
kernel linux syscall sched_ext ebpf bpf netfilter iommu dma kvm virtio cgroup
cgroups namespace lkml mainline rcu vfs ext4 btrfs xfs overlayfs io_uring
preempt mm vmalloc kmalloc slub page-cache hugetlb tlb numa lsm selinux
apparmor landlock seccomp ftrace kprobe uprobe tracepoint perf_event module
driver dts devicetree acpi pci usb scsi nvme block-layer irq softirq
workqueue spinlock mutex futex kthread procfs sysfs debugfs
""".split())

#: How many distinct kernel terms an item must carry.
#: ONE IS TOO FEW AND WAS MEASURED: "Netflix Simplified Batch Compute with
#: Kueue" mentions a driver, and "A look at MinIO alternatives" mentions
#: storage. TWO distinct terms is what separates an item about the kernel from
#: one that merely touches it.
KERNEL_TERM_THRESHOLD = 2

_WORD_RE = re.compile(r"[a-z0-9_]+")


def item_is_kernel_relevant(item: FeedItem, config: FeedConfig | None = None) -> bool:
    """INV-KK-FEED-ITEM-KERNEL-RELEVANT: is this item about the kernel?

    THE GATE THE OTHER ENTRANCE ALREADY HAD. INV-KK-SEED-PATH-DEFINITIONAL
    refuses a document outside DOC_PATH_PREFIXES before any fetch, and has been
    argued over and widened by measurement four times. The feed path had
    nothing: ingest_item created a Source for every item a poller returned,
    filtered only by URL duplication, and one of the pollers reads the Hacker
    News API. A corpus with one guarded door and one open one is guarded by
    neither.

    MEASURED 2026-10-05 OVER EVERY discourse SOURCE IN THE CORPUS: all NINE are
    off-topic — Venetian bridge brawls in 17th-century art, font-family
    recommendations, Netflix batch compute with Kueue, three Phoronix desktop
    items on Vim/GTK3, KDE Plasma and COSMIC, a look at MinIO alternatives, and
    free-threaded Python. This rule refuses all nine.

    THE SAMPLE HAS NO POSITIVE EXAMPLES AND THAT BOUNDS WHAT CAN BE CLAIMED.
    Nine of nine refused is a precision result on a set with no true positives
    in it; RECALL IS UNMEASURED, because this corpus contains no feed item that
    should have been admitted. The threshold of two distinct terms is a
    judgement, not a measurement, and the first legitimate item this refuses is
    the evidence that would lower it. kernel_filter on FeedConfig — a field
    declared and never wired until now — overrides this per feed for exactly
    that case.
    """
    if config is not None and config.kernel_filter:
        return bool(re.search(config.kernel_filter, f"{item.title} {item.content}",
                              re.IGNORECASE))
    words = set(_WORD_RE.findall(f"{item.title} {item.content}".lower()))
    return len(words & KERNEL_TERMS) >= KERNEL_TERM_THRESHOLD


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
        "published_date": item.published,
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
        # COUNTED, not silently dropped. A filter that discards without a
        # record is indistinguishable from a feed that returned nothing — the
        # shape this project has now found six times.
        refused: list[str] = []

        for item in items:
            if is_duplicate(conn, item.url, state, self.config.name):
                log.debug("Skipping duplicate URL: %s", item.url)
                continue

            # INV-KK-FEED-ITEM-KERNEL-RELEVANT, BEFORE the write and AFTER the
            # dedup. Before the write because a refused item must leave no node
            # behind; after the dedup because a URL already seen costs nothing
            # to skip and re-testing it would only be slower. The url IS marked
            # seen, so a refused item is not re-tested on every poll — a
            # refusal nobody records is one that is paid for daily.
            if not item_is_kernel_relevant(item, self.config):
                log.debug("Skipping off-topic item: %s", item.url)
                refused.append(item.url)
                seen_set.add(item.url)
                continue

            src_id, ev_id = ingest_item(conn, item)
            results.append((src_id, ev_id))
            seen_set.add(item.url)

        source_state["seen_urls"] = list(seen_set)
        if items:
            source_state["last_fetched_timestamp"] = items[-1].published
            source_state["last_fetched_url"] = items[-1].url
        source_state["refused_off_topic"] = (
            source_state.get("refused_off_topic", 0) + len(refused))
        state[self.config.name] = source_state
        save_feed_state(state, self.state_path)
        if refused:
            log.info("%s: refused %d off-topic item(s) "
                     "(INV-KK-FEED-ITEM-KERNEL-RELEVANT)",
                     self.config.name, len(refused))

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


# --- HackerNews API Poller (ALG-KK-FEED-HN) ---

KERNEL_FILTER_RE = re.compile(
    r"linux|kernel|scheduler|memory|io_uring|bpf|ebpf|rcu|numa|folio|mm"
    r"|vfs|filesystem|networking|net|driver|module",
    re.IGNORECASE,
)

HN_API_BASE = "https://hacker-news.firebaseio.com/v0"


def _epoch_to_iso(epoch: int | None) -> str:
    """INV-KK-FEED-HN-EPOCH: convert Unix epoch to ISO-8601 date. Empty string if None."""
    if epoch is None:
        return ""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d")


class HNFeedPoller(FeedPoller):
    """ALG-KK-FEED-HN: HackerNews API poller with kernel-topic filtering."""

    def __init__(
        self,
        config: FeedConfig,
        state_path: Path = DEFAULT_STATE_PATH,
        http_client: Any | None = None,
        max_stories: int = 50,
    ) -> None:
        super().__init__(config, state_path)
        self._http_client = http_client
        self._max_stories = max_stories

    def _get_client(self) -> Any:
        if self._http_client is not None:
            return self._http_client
        import httpx
        return httpx.Client(timeout=30)

    def fetch(self) -> list[FeedItem]:
        client = self._get_client()
        state = load_feed_state(self.state_path)
        source_state = state.get(self.config.name, {})
        seen_ids: set[int] = set(source_state.get("seen_ids", []))

        resp = client.get(f"{self.config.url}/topstories.json")
        resp.raise_for_status()
        story_ids: list[int] = resp.json()

        story_ids = story_ids[: self._max_stories]

        items: list[FeedItem] = []
        new_seen: list[int] = []

        for sid in story_ids:
            if sid in seen_ids:
                continue

            story_resp = client.get(f"{self.config.url}/item/{sid}.json")
            story_resp.raise_for_status()
            story = story_resp.json()

            if story is None:
                continue

            title = story.get("title", "")
            if not title or not KERNEL_FILTER_RE.search(title):
                new_seen.append(sid)
                continue

            url = story.get("url", "")
            if not url:
                url = f"https://news.ycombinator.com/item?id={sid}"

            published = _epoch_to_iso(story.get("time"))

            items.append(FeedItem(
                title=title,
                url=url,
                content=title,
                published=published,
                source_feed=self.config.name,
                metadata={
                    "hn_id": sid,
                    "score": story.get("score", 0),
                    "descendants": story.get("descendants", 0),
                },
            ))
            new_seen.append(sid)

        all_seen = list(seen_ids | set(new_seen))
        source_state["seen_ids"] = all_seen
        state[self.config.name] = source_state
        save_feed_state(state, self.state_path)

        return items
