"""Tests for feed ingestion core -- ALG-KK-FEED-POLL invariants."""

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
