"""Source content classification for provenance grounding.

Spec: ALG-KK-CLASSIFY-SOURCE-CONTENT, ALG-KK-EXTRACT-KERNEL-DOC-REFS,
      INV-KK-SOURCE-CONTENT-SUFFICIENT
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


GIT_KERNEL_ORG_BLOB = (
    "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/{path}"
)

_KERNEL_DOC_RE = re.compile(r"\.\.\s+kernel-doc::\s+(\S+)")

_DIRECTORY_MARKERS = [
    '<table class="list">',
    "drwxr-xr-x",
    '<td class="ls-mode">',
]

_RST_DIRECTIVE_RE = re.compile(r"^\.\.\s+\S+::", re.MULTILINE)
_RST_ROLE_RE = re.compile(r":\w+:`[^`]*`")
_CODE_BLOCK_RE = re.compile(
    r"(?s)\.\.\s+code-block::\s*\w*\n(?:[ \t]+[^\n]*\n?)+", re.MULTILINE
)
_LITERAL_BLOCK_RE = re.compile(r"(?s)::\n\n(?:[ \t]+[^\n]*\n?)+", re.MULTILINE)


@dataclass
class ContentClassification:
    classification: str  # substantive | stub | directory | thin | unreachable
    word_count: int = 0
    kernel_doc_refs: list[str] = field(default_factory=list)
    prose_excerpt: str = ""


def _strip_markup(text: str) -> str:
    """Remove RST/HTML markup, leaving only prose words."""
    cleaned = _CODE_BLOCK_RE.sub("", text)
    cleaned = _LITERAL_BLOCK_RE.sub("", cleaned)
    cleaned = _RST_DIRECTIVE_RE.sub("", cleaned)
    cleaned = _RST_ROLE_RE.sub("", cleaned)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    cleaned = re.sub(r"[=\-~^`]{3,}", "", cleaned)
    cleaned = re.sub(r"^\s*\.\.\s+.*$", "", cleaned, flags=re.MULTILINE)
    return cleaned


def _count_prose_words(text: str) -> int:
    stripped = _strip_markup(text)
    words = stripped.split()
    return len(words)


def _extract_prose_excerpt(text: str, max_len: int = 500) -> str:
    stripped = _strip_markup(text)
    lines = [ln.strip() for ln in stripped.splitlines() if ln.strip()]
    excerpt = " ".join(lines)
    if len(excerpt) > max_len:
        excerpt = excerpt[:max_len] + "..."
    return excerpt


def classify_content(text: str) -> ContentClassification:
    """Classify fetched document text (ALG-KK-CLASSIFY-SOURCE-CONTENT).

    Returns ContentClassification with one of:
      substantive — >=100 words of prose
      stub        — kernel-doc directives only, <50 words prose
      directory   — git.kernel.org tree listing
      thin        — 50-99 words (needs manual review)
      unreachable — empty or None input
    """
    if not text or not text.strip():
        return ContentClassification(classification="unreachable")

    if any(marker in text for marker in _DIRECTORY_MARKERS):
        return ContentClassification(
            classification="directory",
            prose_excerpt=_extract_prose_excerpt(text),
        )

    kernel_doc_refs = extract_kernel_doc_refs(text)
    word_count = _count_prose_words(text)
    prose_excerpt = _extract_prose_excerpt(text)

    if kernel_doc_refs and word_count < 50:
        return ContentClassification(
            classification="stub",
            word_count=word_count,
            kernel_doc_refs=kernel_doc_refs,
            prose_excerpt=prose_excerpt,
        )

    if word_count >= 100:
        return ContentClassification(
            classification="substantive",
            word_count=word_count,
            kernel_doc_refs=kernel_doc_refs,
            prose_excerpt=prose_excerpt,
        )

    if word_count >= 50:
        return ContentClassification(
            classification="thin",
            word_count=word_count,
            kernel_doc_refs=kernel_doc_refs,
            prose_excerpt=prose_excerpt,
        )

    return ContentClassification(
        classification="unreachable",
        word_count=word_count,
        prose_excerpt=prose_excerpt,
    )


def extract_kernel_doc_refs(rst_text: str) -> list[str]:
    """Parse RST for '.. kernel-doc::' directives (ALG-KK-EXTRACT-KERNEL-DOC-REFS).

    Returns list of kernel source file paths, e.g. ['mm/slub.c', 'mm/slab.h'].
    """
    return _KERNEL_DOC_RE.findall(rst_text)


def build_replacement_url(kernel_path: str) -> str:
    """Convert a kernel source path to a git.kernel.org blob URL."""
    return GIT_KERNEL_ORG_BLOB.format(path=kernel_path.strip("/"))
