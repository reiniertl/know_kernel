"""Tests for INV-KK-PARSE-RETURNS-TEXT and INV-KK-PARSE-IDEMPOTENT."""

from __future__ import annotations

import pytest
from pathlib import Path

from know_kernel.ingest.parser import ParsedDocument, parse_document


@pytest.fixture
def txt_file(tmp_path: Path) -> Path:
    f = tmp_path / "hello.txt"
    f.write_text("Hello, world!\nLine two.", encoding="utf-8")
    return f


@pytest.fixture
def c_file(tmp_path: Path) -> Path:
    f = tmp_path / "main.c"
    f.write_text('#include <stdio.h>\nint main() { return 0; }\n', encoding="utf-8")
    return f


@pytest.fixture
def py_file(tmp_path: Path) -> Path:
    f = tmp_path / "script.py"
    f.write_text("def hello():\n    return 'world'\n", encoding="utf-8")
    return f


@pytest.fixture
def empty_file(tmp_path: Path) -> Path:
    f = tmp_path / "empty.txt"
    f.write_bytes(b"")
    return f


# --- INV-KK-PARSE-RETURNS-TEXT: non-empty text + recognized file_type ---

def test_parse_text_file(txt_file: Path) -> None:
    """Parsing a .txt file yields non-empty text and file_type='txt'."""
    doc = parse_document(str(txt_file), source_type="paper")
    assert doc.text.strip(), "text must be non-empty"
    assert doc.file_type == "txt"
    assert "Hello" in doc.text


def test_parse_source_code_c(c_file: Path) -> None:
    """Parsing a .c file yields file_type='source-code'."""
    doc = parse_document(str(c_file), source_type="code-repo")
    assert doc.file_type == "source-code"
    assert doc.text.strip()


def test_parse_source_code_py(py_file: Path) -> None:
    """Parsing a .py file yields file_type='source-code'."""
    doc = parse_document(str(py_file), source_type="code-repo")
    assert doc.file_type == "source-code"
    assert doc.text.strip()


def test_parse_returns_parsed_document(txt_file: Path) -> None:
    """Return value is a ParsedDocument with all required fields."""
    doc = parse_document(str(txt_file))
    assert isinstance(doc, ParsedDocument)
    assert isinstance(doc.text, str)
    assert isinstance(doc.metadata, dict)
    assert isinstance(doc.file_type, str)
    assert isinstance(doc.page_count, int)
    assert doc.page_count == 1


# --- INV-KK-PARSE-IDEMPOTENT: same file → identical output ---

def test_parse_idempotent(txt_file: Path) -> None:
    """Parsing the same file twice returns identical results."""
    doc1 = parse_document(str(txt_file), source_type="paper")
    doc2 = parse_document(str(txt_file), source_type="paper")
    assert doc1.text == doc2.text
    assert doc1.file_type == doc2.file_type
    assert doc1.page_count == doc2.page_count


# --- Error handling ---

def test_parse_nonexistent_file_raises() -> None:
    """Parsing a non-existent file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        parse_document("/no/such/file.txt")


def test_parse_empty_file(empty_file: Path) -> None:
    """Parsing a zero-byte file raises ValueError (INV-KK-PARSE-RETURNS-TEXT)."""
    with pytest.raises(ValueError, match="Empty document"):
        parse_document(str(empty_file))
