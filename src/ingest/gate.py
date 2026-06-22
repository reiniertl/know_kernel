"""Session gate — enforces INV-KK-SESSION-SEPARATION."""

from __future__ import annotations


class SessionViolationError(Exception):
    """Raised when a session attempts a mixed-mode operation."""


class SessionGate:
    """Tracks session mode and enforces INV-KK-SESSION-SEPARATION.

    A session that has accessed Class A content is in extraction mode.
    """

    def __init__(self) -> None:
        self._class_a_accesses: int = 0

    def record_class_a_access(self) -> None:
        """Record a Class A artifact access."""
        self._class_a_accesses += 1

    @property
    def is_extraction_mode(self) -> bool:
        return self._class_a_accesses > 0

    @property
    def is_clean(self) -> bool:
        return self._class_a_accesses == 0
