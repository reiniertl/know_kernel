"""Document parsing — PDFs, source repos, papers, mailing lists."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_SOURCE_CODE_EXTENSIONS = {".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".py", ".rs", ".go",
                            ".ts", ".js", ".java", ".cs", ".rb", ".php", ".swift", ".kt"}
_TEXT_EXTENSIONS = {".txt", ".md", ".rst", ".log", ".csv", ".json", ".xml", ".yaml", ".yml",
                    ".toml", ".ini", ".cfg"}
_MBOX_EXTENSIONS = {".mbox", ".mbx"}
_PDF_EXTENSIONS = {".pdf"}


@dataclass
class ParsedDocument:
    text: str
    metadata: dict
    file_type: str  # 'txt', 'source-code', 'pdf', 'mbox'
    page_count: int


def parse_document(path: str, source_type: str = "") -> ParsedDocument:
    """Parse a document at *path* and return a ParsedDocument.

    Raises FileNotFoundError if the file does not exist.
    Raises ValueError if the file type is not recognised.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")

    ext = p.suffix.lower()

    if ext in _PDF_EXTENSIONS:
        return _parse_pdf(p, source_type)
    if ext in _SOURCE_CODE_EXTENSIONS:
        return _parse_text(p, source_type, file_type="source-code")
    if ext in _MBOX_EXTENSIONS:
        return _parse_text(p, source_type, file_type="mbox")
    if ext in _TEXT_EXTENSIONS:
        return _parse_text(p, source_type, file_type="txt")
    # Unknown extension — treat as plain text
    return _parse_text(p, source_type, file_type="txt")


def _parse_text(p: Path, source_type: str, file_type: str) -> ParsedDocument:
    text = p.read_text(encoding="utf-8", errors="replace")
    metadata = {
        "filename": p.name,
        "source_type": source_type,
        "size_bytes": p.stat().st_size,
    }
    return ParsedDocument(text=text, metadata=metadata, file_type=file_type, page_count=1)


def _parse_pdf(p: Path, source_type: str) -> ParsedDocument:
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise ImportError(
            "PyMuPDF (fitz) is required to parse PDF files. "
            "Install it with: pip install pymupdf"
        ) from exc

    doc = fitz.open(str(p))
    pages = [page.get_text() for page in doc]
    doc.close()
    text = "\n".join(pages)
    metadata = {
        "filename": p.name,
        "source_type": source_type,
        "size_bytes": p.stat().st_size,
        "page_count": len(pages),
    }
    return ParsedDocument(text=text, metadata=metadata, file_type="pdf", page_count=len(pages))
