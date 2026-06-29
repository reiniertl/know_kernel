"""Tests for feed ingestion core -- ALG-KK-FEED-POLL and ALG-KK-FEED-RSS invariants."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from graph.engine import add_node
from graph.schema import init_db
from ingest.feed import (
    FeedConfig,
    FeedItem,
    FeedPoller,
    RSSFeedPoller,
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
