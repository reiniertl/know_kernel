"""Tests for feed ingestion core -- ALG-KK-FEED-POLL, ALG-KK-FEED-RSS, ALG-KK-FEED-HN invariants."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from graph.engine import add_node
from graph.schema import init_db
from ingest.feed import (
    FeedConfig,
    FeedItem,
    FeedPoller,
    HNFeedPoller,
    KERNEL_FILTER_RE,
    RSSFeedPoller,
    _epoch_to_iso,
    _extract_rss_content,
    _struct_time_to_iso,
    ingest_item,
    is_duplicate,
    load_feed_state,
    save_feed_state,
)


class StubPoller(FeedPoller):
    """Test poller returning pre-configured items."""

    def __init__(self, config: FeedConfig, items: list[FeedItem], state_path: Path) -> None:
        super().__init__(config, state_path)
        self._items = items

    def fetch(self) -> list[FeedItem]:
        return self._items


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "test.db")


@pytest.fixture
def state_path(tmp_path):
    return tmp_path / "feed_state.json"


def _item(url: str = "https://example.com/article", title: str = "Test Article") -> FeedItem:
    return FeedItem(
        title=title,
        url=url,
        content="Some kernel discussion content.",
        published="2026-06-15",
        source_feed="test",
    )


class TestFeedConfig:
    def test_construction(self):
        config = FeedConfig(name="lwn", feed_type="rss", url="https://lwn.net/rss")
        assert config.name == "lwn"
        assert config.feed_type == "rss"
        assert config.poll_interval_seconds == 3600

    def test_with_filter(self):
        config = FeedConfig(
            name="hn", feed_type="api", url="https://hn.api",
            poll_interval_seconds=1800, kernel_filter="linux|kernel",
        )
        assert config.kernel_filter == "linux|kernel"


class TestFeedItem:
    def test_construction(self):
        item = _item()
        assert item.title == "Test Article"
        assert item.published == "2026-06-15"
        assert item.source_feed == "test"
        assert item.metadata == {}

    def test_with_metadata(self):
        item = FeedItem(
            title="T", url="https://x.com", content="C",
            published="2026-06-15", source_feed="hn",
            metadata={"score": 42, "comments": 10},
        )
        assert item.metadata["score"] == 42


class TestFeedState:
    def test_load_missing_file(self, state_path):
        state = load_feed_state(state_path)
        assert state == {}

    def test_save_and_load(self, state_path):
        data = {"lwn": {"seen_urls": ["https://a.com"], "last_fetched_timestamp": "2026-06-15"}}
        save_feed_state(data, state_path)
        loaded = load_feed_state(state_path)
        assert loaded == data

    def test_save_creates_parent_dirs(self, tmp_path):
        nested = tmp_path / "deep" / "dir" / "state.json"
        save_feed_state({"test": {}}, nested)
        assert nested.exists()


class TestDedup:
    def test_not_duplicate_empty_db(self, conn):
        assert not is_duplicate(conn, "https://new.com", {}, "test")

    def test_duplicate_in_db(self, conn):
        add_node(conn, "src-existing", "Source", {
            "url": "https://existing.com",
            "source_type": "discourse",
            "license": "unknown",
        })
        assert is_duplicate(conn, "https://existing.com", {}, "test")

    def test_duplicate_in_state(self, conn):
        state = {"test": {"seen_urls": ["https://seen.com"]}}
        assert is_duplicate(conn, "https://seen.com", state, "test")

    def test_not_duplicate_different_source(self, conn):
        state = {"other": {"seen_urls": ["https://seen.com"]}}
        assert not is_duplicate(conn, "https://seen.com", state, "test")


class TestIngestItem:
    def test_creates_source_and_evidence(self, conn):
        """INV-KK-FEED-SOURCE-NODE: creates Source + Evidence + sourced-from."""
        item = _item()
        src_id, ev_id = ingest_item(conn, item)
        src = conn.execute("SELECT kind, attrs FROM nodes WHERE id = ?", (src_id,)).fetchone()
        assert src[0] == "Source"
        attrs = json.loads(src[1])
        assert attrs["source_type"] == "discourse"
        assert attrs["url"] == item.url

        ev = conn.execute("SELECT kind, attrs FROM nodes WHERE id = ?", (ev_id,)).fetchone()
        assert ev[0] == "Evidence"
        ev_attrs = json.loads(ev[1])
        assert ev_attrs["description"] == item.title
        assert ev_attrs["text"] == item.content

        edge = conn.execute(
            "SELECT 1 FROM edges WHERE kind = 'sourced-from' AND source_id = ? AND target_id = ?",
            (ev_id, src_id),
        ).fetchone()
        assert edge is not None

    def test_source_type_is_discourse(self, conn):
        """INV-KK-FEED-SOURCE-NODE: source_type always 'discourse'."""
        _, _ = ingest_item(conn, _item())
        row = conn.execute(
            "SELECT attrs FROM nodes WHERE kind = 'Source'"
        ).fetchone()
        assert json.loads(row[0])["source_type"] == "discourse"


class TestFeedPoller:
    def test_poll_ingests_items(self, conn, state_path):
        config = FeedConfig(name="test", feed_type="rss", url="https://test.com")
        items = [_item("https://a.com", "A"), _item("https://b.com", "B")]
        poller = StubPoller(config, items, state_path)
        results = poller.poll(conn)
        assert len(results) == 2
        assert all(len(r) == 2 for r in results)

    def test_poll_dedup_skips_duplicate(self, conn, state_path):
        """INV-KK-FEED-DEDUP: second poll skips already-seen URLs."""
        config = FeedConfig(name="test", feed_type="rss", url="https://test.com")
        items = [_item("https://a.com", "A")]
        poller = StubPoller(config, items, state_path)
        results1 = poller.poll(conn)
        assert len(results1) == 1
        results2 = poller.poll(conn)
        assert len(results2) == 0

    def test_poll_persists_state(self, conn, state_path):
        """INV-KK-FEED-STATE: state file written after poll."""
        config = FeedConfig(name="lwn", feed_type="rss", url="https://lwn.net")
        items = [_item("https://lwn.net/1", "Article 1")]
        poller = StubPoller(config, items, state_path)
        poller.poll(conn)
        state = load_feed_state(state_path)
        assert "lwn" in state
        assert "https://lwn.net/1" in state["lwn"]["seen_urls"]
        assert state["lwn"]["last_fetched_timestamp"] == "2026-06-15"
        assert state["lwn"]["last_fetched_url"] == "https://lwn.net/1"

    def test_poll_empty_feed(self, conn, state_path):
        config = FeedConfig(name="empty", feed_type="rss", url="https://empty.com")
        poller = StubPoller(config, [], state_path)
        results = poller.poll(conn)
        assert results == []
        state = load_feed_state(state_path)
        assert "empty" in state

    def test_poll_db_dedup(self, conn, state_path):
        """INV-KK-FEED-DEDUP: skips URLs already in DB from prior runs."""
        add_node(conn, "src-old", "Source", {
            "url": "https://already-in-db.com",
            "source_type": "discourse",
            "license": "unknown",
        })
        config = FeedConfig(name="test", feed_type="rss", url="https://test.com")
        items = [_item("https://already-in-db.com"), _item("https://new.com")]
        poller = StubPoller(config, items, state_path)
        results = poller.poll(conn)
        assert len(results) == 1

    def test_published_is_source_date(self, conn, state_path):
        """INV-KK-FEED-SOURCE-DATE: published comes from source, not ingestion time."""
        item = FeedItem(
            title="Old Article", url="https://old.com", content="Old content.",
            published="2024-01-15", source_feed="test",
        )
        config = FeedConfig(name="test", feed_type="rss", url="https://test.com")
        poller = StubPoller(config, [item], state_path)
        poller.poll(conn)
        state = load_feed_state(state_path)
        assert state["test"]["last_fetched_timestamp"] == "2024-01-15"


# --- RSS Feed Poller Tests (ALG-KK-FEED-RSS) ---

_LWN_RSS = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>LWN.net</title>
    <item>
      <title>Memory folios and large pages</title>
      <link>https://lwn.net/Articles/123456/</link>
      <description>An article about memory folios in the Linux kernel.</description>
      <pubDate>Sun, 15 Jun 2026 00:00:00 +0000</pubDate>
    </item>
    <item>
      <title>RCU and NUMA scalability</title>
      <link>https://lwn.net/Articles/789012/</link>
      <description>Deep dive into RCU grace periods on NUMA systems.</description>
      <pubDate>Mon, 16 Jun 2026 10:30:00 +0000</pubDate>
    </item>
  </channel>
</rss>
"""

_EMPTY_RSS = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Empty</title></channel></rss>
"""

_CONTENT_ENCODED_RSS = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>Test</title>
    <item>
      <title>Content Encoded Test</title>
      <link>https://example.com/content-encoded</link>
      <description>Short summary</description>
      <content:encoded><![CDATA[<p>This is the full article content with HTML.</p>]]></content:encoded>
      <pubDate>Wed, 18 Jun 2026 12:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>
"""

_NO_DATE_RSS = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>No Date</title>
    <item>
      <title>Article without date</title>
      <link>https://example.com/no-date</link>
      <description>No pubDate present.</description>
    </item>
  </channel>
</rss>
"""

_NO_LINK_RSS = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>No Link</title>
    <item>
      <title>Article without link</title>
      <description>Missing link element.</description>
    </item>
  </channel>
</rss>
"""


import time as time_mod


class TestStructTimeToIso:
    def test_valid_time(self):
        t = time_mod.strptime("2026-06-15", "%Y-%m-%d")
        assert _struct_time_to_iso(t) == "2026-06-15"

    def test_none_returns_empty(self):
        assert _struct_time_to_iso(None) == ""


class TestExtractRssContent:
    def test_summary_used(self):
        class Entry:
            summary = "Summary text"
        assert _extract_rss_content(Entry()) == "Summary text"

    def test_content_encoded_preferred(self):
        class Entry:
            content = [{"value": "Full content"}]
            summary = "Short summary"
        assert _extract_rss_content(Entry()) == "Full content"

    def test_empty_content_falls_to_summary(self):
        class Entry:
            content = [{"value": ""}]
            summary = "Fallback summary"
        assert _extract_rss_content(Entry()) == "Fallback summary"

    def test_no_content_no_summary_uses_title(self):
        class Entry:
            title = "Title Fallback"
        assert _extract_rss_content(Entry()) == "Title Fallback"

    def test_completely_empty_uses_default(self):
        class Entry:
            pass
        result = _extract_rss_content(Entry())
        assert result == "No content"


class TestRSSFeedPoller:
    def test_parse_lwn_rss(self, state_path):
        """ALG-KK-FEED-RSS: parses standard RSS 2.0 entries."""
        config = FeedConfig(name="lwn", feed_type="rss", url="https://lwn.net/rss")
        poller = RSSFeedPoller(config, state_path, raw_xml=_LWN_RSS)
        items = poller.fetch()
        assert len(items) == 2
        assert items[0].title == "Memory folios and large pages"
        assert items[0].url == "https://lwn.net/Articles/123456/"
        assert items[1].title == "RCU and NUMA scalability"

    def test_pubdate_to_iso(self, state_path):
        """INV-KK-FEED-RSS-DATE: pubDate converted to ISO-8601."""
        config = FeedConfig(name="lwn", feed_type="rss", url="https://lwn.net/rss")
        poller = RSSFeedPoller(config, state_path, raw_xml=_LWN_RSS)
        items = poller.fetch()
        assert items[0].published == "2026-06-15"
        assert items[1].published == "2026-06-16"

    def test_content_extraction(self, state_path):
        """INV-KK-FEED-RSS-CONTENT: content from description."""
        config = FeedConfig(name="lwn", feed_type="rss", url="https://lwn.net/rss")
        poller = RSSFeedPoller(config, state_path, raw_xml=_LWN_RSS)
        items = poller.fetch()
        assert "memory folios" in items[0].content.lower()

    def test_content_encoded_preferred(self, state_path):
        """INV-KK-FEED-RSS-CONTENT: content:encoded preferred over description."""
        config = FeedConfig(name="test", feed_type="rss", url="https://test.com")
        poller = RSSFeedPoller(config, state_path, raw_xml=_CONTENT_ENCODED_RSS)
        items = poller.fetch()
        assert len(items) == 1
        assert "full article content" in items[0].content.lower()

    def test_empty_feed(self, state_path):
        config = FeedConfig(name="empty", feed_type="rss", url="https://empty.com")
        poller = RSSFeedPoller(config, state_path, raw_xml=_EMPTY_RSS)
        items = poller.fetch()
        assert items == []

    def test_no_date_entry(self, state_path):
        """INV-KK-FEED-RSS-DATE: missing pubDate produces empty string."""
        config = FeedConfig(name="nodate", feed_type="rss", url="https://nodate.com")
        poller = RSSFeedPoller(config, state_path, raw_xml=_NO_DATE_RSS)
        items = poller.fetch()
        assert len(items) == 1
        assert items[0].published == ""

    def test_no_link_entry_skipped(self, state_path):
        """Entries without a link are skipped."""
        config = FeedConfig(name="nolink", feed_type="rss", url="https://nolink.com")
        poller = RSSFeedPoller(config, state_path, raw_xml=_NO_LINK_RSS)
        items = poller.fetch()
        assert items == []

    def test_source_feed_set(self, state_path):
        config = FeedConfig(name="phoronix", feed_type="rss", url="https://phoronix.com/rss")
        poller = RSSFeedPoller(config, state_path, raw_xml=_LWN_RSS)
        items = poller.fetch()
        assert all(item.source_feed == "phoronix" for item in items)

    def test_poll_integration(self, conn, state_path):
        """Full poll: RSS parse -> dedup -> ingest -> state."""
        config = FeedConfig(name="lwn", feed_type="rss", url="https://lwn.net/rss")
        poller = RSSFeedPoller(config, state_path, raw_xml=_LWN_RSS)
        results = poller.poll(conn)
        assert len(results) == 2
        state = load_feed_state(state_path)
        assert "lwn" in state
        assert len(state["lwn"]["seen_urls"]) == 2


# --- HackerNews API Poller Tests (ALG-KK-FEED-HN) ---


def _mock_hn_client(top_stories: list[int], stories: dict[int, dict | None]):
    """Build a mock httpx client that serves HN API responses."""
    client = MagicMock()

    def mock_get(url: str):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        if url.endswith("/topstories.json"):
            resp.json.return_value = top_stories
        else:
            for sid, data in stories.items():
                if url.endswith(f"/item/{sid}.json"):
                    resp.json.return_value = data
                    break
            else:
                resp.json.return_value = None
        return resp

    client.get = mock_get
    return client


class TestEpochToIso:
    def test_valid_epoch(self):
        assert _epoch_to_iso(1718409600) == "2024-06-15"

    def test_none_returns_empty(self):
        assert _epoch_to_iso(None) == ""

    def test_zero_epoch(self):
        assert _epoch_to_iso(0) == "1970-01-01"


class TestKernelFilterRegex:
    @pytest.mark.parametrize("title", [
        "Linux 6.10 release candidate",
        "New kernel scheduler improvements",
        "io_uring performance benchmarks",
        "BPF subsystem updates",
        "eBPF verifier changes",
        "RCU grace period optimization",
        "NUMA balancing patches",
        "folio migration in memory management",
        "mm: page cache improvements",
        "VFS layer refactoring",
        "ext4 filesystem bug fix",
        "TCP networking stack changes",
        "New GPU driver for AMD",
        "Kernel module loading",
        "Memory management rework",
    ])
    def test_matching_titles(self, title):
        """INV-KK-FEED-HN-FILTER: kernel-topic titles pass filter."""
        assert KERNEL_FILTER_RE.search(title) is not None

    @pytest.mark.parametrize("title", [
        "React 19 released",
        "How I built my startup",
        "Python 3.13 new features",
        "Rust async patterns",
        "Ask HN: Best laptop for coding?",
        "Show HN: My todo app",
        "YC W26 batch",
    ])
    def test_non_matching_titles(self, title):
        """INV-KK-FEED-HN-FILTER: non-kernel titles are rejected."""
        assert KERNEL_FILTER_RE.search(title) is None


class TestHNFeedPoller:
    def _config(self):
        return FeedConfig(
            name="hackernews", feed_type="api",
            url="https://hacker-news.firebaseio.com/v0",
            kernel_filter="linux|kernel",
        )

    def test_fetch_kernel_stories(self, state_path):
        """ALG-KK-FEED-HN: fetches and filters kernel-related stories."""
        stories = {
            101: {"title": "Linux 6.10 released", "url": "https://lwn.net/linux610", "time": 1718409600, "score": 200, "descendants": 50},
            102: {"title": "React 19 is out", "url": "https://react.dev/19", "time": 1718409601, "score": 300, "descendants": 80},
            103: {"title": "Kernel scheduler rework", "url": "https://lkml.org/sched", "time": 1718409602, "score": 150, "descendants": 30},
        }
        client = _mock_hn_client([101, 102, 103], stories)
        poller = HNFeedPoller(self._config(), state_path, http_client=client)
        items = poller.fetch()
        assert len(items) == 2
        titles = {i.title for i in items}
        assert "Linux 6.10 released" in titles
        assert "Kernel scheduler rework" in titles
        assert "React 19 is out" not in titles

    def test_epoch_to_published(self, state_path):
        """INV-KK-FEED-HN-EPOCH: Unix epoch converted to ISO-8601."""
        stories = {
            201: {"title": "Linux kernel update", "url": "https://example.com", "time": 1718409600, "score": 10, "descendants": 5},
        }
        client = _mock_hn_client([201], stories)
        poller = HNFeedPoller(self._config(), state_path, http_client=client)
        items = poller.fetch()
        assert len(items) == 1
        assert items[0].published == "2024-06-15"

    def test_missing_time_uses_empty(self, state_path):
        """INV-KK-FEED-HN-EPOCH: missing time produces empty string."""
        stories = {
            301: {"title": "Linux patch", "url": "https://example.com", "score": 5, "descendants": 1},
        }
        client = _mock_hn_client([301], stories)
        poller = HNFeedPoller(self._config(), state_path, http_client=client)
        items = poller.fetch()
        assert len(items) == 1
        assert items[0].published == ""

    def test_metadata_stored(self, state_path):
        """ALG-KK-FEED-HN: score and descendants stored in metadata."""
        stories = {
            401: {"title": "Kernel memory leak", "url": "https://example.com", "time": 1718409600, "score": 42, "descendants": 15},
        }
        client = _mock_hn_client([401], stories)
        poller = HNFeedPoller(self._config(), state_path, http_client=client)
        items = poller.fetch()
        assert items[0].metadata["hn_id"] == 401
        assert items[0].metadata["score"] == 42
        assert items[0].metadata["descendants"] == 15

    def test_dedup_by_story_id(self, state_path):
        """INV-KK-FEED-HN-DEDUP: already-seen story IDs are skipped."""
        stories = {
            501: {"title": "Linux RCU update", "url": "https://example.com/501", "time": 1718409600, "score": 10, "descendants": 2},
            502: {"title": "Linux BPF patches", "url": "https://example.com/502", "time": 1718409601, "score": 20, "descendants": 5},
        }
        client = _mock_hn_client([501, 502], stories)
        poller = HNFeedPoller(self._config(), state_path, http_client=client)
        items1 = poller.fetch()
        assert len(items1) == 2

        items2 = poller.fetch()
        assert len(items2) == 0

    def test_dedup_persists_across_instances(self, state_path):
        """INV-KK-FEED-HN-DEDUP: seen IDs persist in feed state file."""
        stories = {
            601: {"title": "Linux NUMA fix", "url": "https://example.com/601", "time": 1718409600, "score": 10, "descendants": 1},
        }
        client = _mock_hn_client([601], stories)
        poller1 = HNFeedPoller(self._config(), state_path, http_client=client)
        poller1.fetch()
        state = load_feed_state(state_path)
        assert 601 in state["hackernews"]["seen_ids"]

        poller2 = HNFeedPoller(self._config(), state_path, http_client=client)
        items = poller2.fetch()
        assert len(items) == 0

    def test_empty_top_stories(self, state_path):
        """ALG-KK-FEED-HN: empty top stories returns empty list."""
        client = _mock_hn_client([], {})
        poller = HNFeedPoller(self._config(), state_path, http_client=client)
        items = poller.fetch()
        assert items == []

    def test_null_story_response(self, state_path):
        """ALG-KK-FEED-HN: null story API response is skipped."""
        stories = {701: None}
        client = _mock_hn_client([701], stories)
        poller = HNFeedPoller(self._config(), state_path, http_client=client)
        items = poller.fetch()
        assert items == []

    def test_story_without_url_uses_hn_link(self, state_path):
        """ALG-KK-FEED-HN: stories without URL use HN discussion link."""
        stories = {
            801: {"title": "Ask HN: Linux kernel question", "time": 1718409600, "score": 50, "descendants": 20},
        }
        client = _mock_hn_client([801], stories)
        poller = HNFeedPoller(self._config(), state_path, http_client=client)
        items = poller.fetch()
        assert len(items) == 1
        assert items[0].url == "https://news.ycombinator.com/item?id=801"

    def test_source_feed_set(self, state_path):
        """ALG-KK-FEED-HN: source_feed matches config name."""
        stories = {
            901: {"title": "Linux driver model", "url": "https://example.com/901", "time": 1718409600, "score": 5, "descendants": 1},
        }
        client = _mock_hn_client([901], stories)
        poller = HNFeedPoller(self._config(), state_path, http_client=client)
        items = poller.fetch()
        assert items[0].source_feed == "hackernews"

    def test_max_stories_limit(self, state_path):
        """ALG-KK-FEED-HN: only first max_stories are fetched."""
        all_ids = list(range(1000, 1010))
        stories = {
            sid: {"title": "Linux kernel patch", "url": f"https://example.com/{sid}", "time": 1718409600, "score": 10, "descendants": 1}
            for sid in all_ids
        }
        client = _mock_hn_client(all_ids, stories)
        poller = HNFeedPoller(self._config(), state_path, http_client=client, max_stories=3)
        items = poller.fetch()
        assert len(items) == 3

    def test_non_matching_ids_still_tracked(self, state_path):
        """INV-KK-FEED-HN-DEDUP: non-kernel stories are still tracked to prevent refetch."""
        stories = {
            1101: {"title": "React 19 released", "url": "https://react.dev", "time": 1718409600, "score": 500, "descendants": 200},
        }
        client = _mock_hn_client([1101], stories)
        poller = HNFeedPoller(self._config(), state_path, http_client=client)
        items = poller.fetch()
        assert len(items) == 0
        state = load_feed_state(state_path)
        assert 1101 in state["hackernews"]["seen_ids"]

    def test_poll_integration(self, conn, state_path):
        """Full poll: HN fetch -> filter -> dedup -> ingest -> state."""
        stories = {
            1201: {"title": "Linux kernel 6.11", "url": "https://lwn.net/611", "time": 1718409600, "score": 100, "descendants": 30},
            1202: {"title": "React hooks update", "url": "https://react.dev", "time": 1718409601, "score": 200, "descendants": 50},
        }
        client = _mock_hn_client([1201, 1202], stories)
        poller = HNFeedPoller(self._config(), state_path, http_client=client)
        results = poller.poll(conn)
        assert len(results) == 1
        state = load_feed_state(state_path)
        assert "hackernews" in state
        assert "https://lwn.net/611" in state["hackernews"]["seen_urls"]
