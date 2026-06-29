"""Tests for feed CLI entry point -- ALG-KK-FEED-CLI invariants."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ingest.cli_feed import (
    BUILTIN_SOURCES,
    cmd_poll,
    cmd_status,
    get_valid_sources,
    load_feed_configs,
)
from ingest.feed import FeedConfig


@pytest.fixture
def configs_file(tmp_path):
    data = {
        "feeds": [
            {"name": "lwn", "feed_type": "rss", "url": "https://lwn.net/rss", "poll_interval_seconds": 604800},
            {"name": "hackernews", "feed_type": "api", "url": "https://hn.api", "poll_interval_seconds": 3600, "kernel_filter": "linux|kernel"},
            {"name": "phoronix", "feed_type": "rss", "url": "https://phoronix.com/rss", "poll_interval_seconds": 86400},
        ]
    }
    path = tmp_path / "feed_configs.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


class TestLoadFeedConfigs:
    def test_loads_configs(self, configs_file):
        configs = load_feed_configs(configs_file)
        assert len(configs) == 3
        assert configs[0].name == "lwn"
        assert configs[0].feed_type == "rss"
        assert configs[1].name == "hackernews"
        assert configs[1].feed_type == "api"
        assert configs[1].kernel_filter == "linux|kernel"

    def test_missing_file_returns_empty(self, tmp_path):
        configs = load_feed_configs(tmp_path / "nonexistent.json")
        assert configs == []

    def test_default_poll_interval(self, tmp_path):
        data = {"feeds": [{"name": "test", "feed_type": "rss", "url": "https://test.com"}]}
        path = tmp_path / "config.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        configs = load_feed_configs(path)
        assert configs[0].poll_interval_seconds == 3600


class TestGetValidSources:
    def test_includes_config_names(self):
        configs = [FeedConfig(name="lwn", feed_type="rss", url="u"), FeedConfig(name="hn", feed_type="api", url="u")]
        valid = get_valid_sources(configs)
        assert "lwn" in valid
        assert "hn" in valid

    def test_includes_builtin_sources(self):
        """INV-KK-FEED-CLI-SOURCE-VALID: kernel-git and cve are always valid."""
        valid = get_valid_sources([])
        assert "kernel-git" in valid
        assert "cve" in valid

    def test_unknown_not_in_valid(self):
        valid = get_valid_sources([FeedConfig(name="lwn", feed_type="rss", url="u")])
        assert "nonexistent" not in valid


class TestCmdPoll:
    def _args(self, source=None, all_flag=False, extract=False, db="test.db"):
        import argparse
        ns = argparse.Namespace()
        ns.source = source
        ns.all = all_flag
        ns.extract = extract
        ns.db = db
        return ns

    def test_invalid_source_exits_2(self, db_path, capsys):
        """INV-KK-FEED-CLI-SOURCE-VALID: unknown source returns exit 2."""
        configs = [FeedConfig(name="lwn", feed_type="rss", url="u")]
        result = cmd_poll(self._args(source="bogus", db=db_path), configs)
        assert result == 2
        captured = capsys.readouterr()
        assert "unknown source" in captured.err.lower()

    def test_no_source_no_all_exits_2(self, db_path, capsys):
        result = cmd_poll(self._args(db=db_path), [])
        assert result == 2

    def test_kernel_git_source_prints_message(self, db_path, capsys):
        configs = []
        result = cmd_poll(self._args(source="kernel-git", db=db_path), configs)
        assert result == 0
        captured = capsys.readouterr()
        assert "kernel-git" in captured.out

    def test_cve_source_prints_message(self, db_path, capsys):
        configs = []
        result = cmd_poll(self._args(source="cve", db=db_path), configs)
        assert result == 0
        captured = capsys.readouterr()
        assert "cve" in captured.out.lower()

    def test_extract_no_sources_message(self, db_path, capsys):
        """INV-KK-FEED-CLI-EXTRACT-STUB: --extract with no items prints info message."""
        configs = []
        result = cmd_poll(self._args(source="kernel-git", extract=True, db=db_path), configs)
        assert result == 0
        captured = capsys.readouterr()
        assert "no new sources" in captured.out.lower()

    @patch("ingest.cli_feed._make_poller")
    def test_poll_dispatches_to_poller(self, mock_make, db_path, capsys):
        mock_poller = mock_make.return_value
        mock_poller.poll.return_value = [("src-1", "ev-1")]
        config = FeedConfig(name="lwn", feed_type="rss", url="https://lwn.net/rss")
        result = cmd_poll(self._args(source="lwn", db=db_path), [config])
        assert result == 0
        mock_poller.poll.assert_called_once()
        captured = capsys.readouterr()
        assert "1 new item" in captured.out

    @patch("ingest.cli_feed._make_poller")
    def test_poll_all(self, mock_make, db_path, capsys):
        mock_poller = mock_make.return_value
        mock_poller.poll.return_value = []
        configs = [
            FeedConfig(name="lwn", feed_type="rss", url="u"),
            FeedConfig(name="phoronix", feed_type="rss", url="u"),
        ]
        result = cmd_poll(self._args(all_flag=True, db=db_path), configs)
        assert result == 0
        assert mock_poller.poll.call_count == 2


class TestCmdStatus:
    def _args(self):
        import argparse
        return argparse.Namespace()

    def test_shows_all_sources(self, tmp_path, capsys):
        """INV-KK-FEED-CLI-STATE-REPORT: shows all configured sources."""
        state = {"lwn": {"last_fetched_timestamp": "2026-06-15"}}
        state_path = tmp_path / "data" / "feed_state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state), encoding="utf-8")

        configs = [
            FeedConfig(name="lwn", feed_type="rss", url="u"),
            FeedConfig(name="phoronix", feed_type="rss", url="u"),
        ]
        with patch("ingest.cli_feed.load_feed_state", return_value=state):
            result = cmd_status(self._args(), configs)
        assert result == 0
        captured = capsys.readouterr()
        assert "lwn" in captured.out
        assert "2026-06-15" in captured.out
        assert "phoronix" in captured.out
        assert "never" in captured.out

    def test_never_for_unpolled(self, capsys):
        """INV-KK-FEED-CLI-STATE-REPORT: unpolled sources show 'never'."""
        configs = [FeedConfig(name="newone", feed_type="rss", url="u")]
        with patch("ingest.cli_feed.load_feed_state", return_value={}):
            cmd_status(self._args(), configs)
        captured = capsys.readouterr()
        assert "never" in captured.out

    def test_builtin_sources_shown(self, capsys):
        """INV-KK-FEED-CLI-STATE-REPORT: kernel-git and cve in status output."""
        with patch("ingest.cli_feed.load_feed_state", return_value={}):
            cmd_status(self._args(), [])
        captured = capsys.readouterr()
        assert "kernel-git" in captured.out
        assert "cve" in captured.out
