"""Snapshot exporter — produces a Class B-only SQLite DB from the master.

This is the contamination gate for LLM consumption. It filters out all
Class A content so the MCP server is clean by construction.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def export_class_b_snapshot(master_db: Path, output_db: Path) -> None:
    raise NotImplementedError
