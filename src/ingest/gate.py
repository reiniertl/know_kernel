"""Session gate — enforces INV-KK-SESSION-SEPARATION."""

from __future__ import annotations


class SessionViolationError(Exception):
    """Raised when a session attempts a mixed-mode operation."""


class SessionGate:
    """Tracks session mode and enforces INV-KK-SESSION-SEPARATION.

    A session that has accessed Class A content (extraction mode) may not create
    proposals. A session that has created proposals (proposal mode) may not access
    Class A content. Clean sessions may enter either mode.
    """

    def __init__(self) -> None:
        self._class_a_accesses: int = 0
        self._proposals_created: int = 0

    def record_class_a_access(self) -> None:
        """Record a Class A artifact access. Raises SessionViolationError if proposals exist."""
        if self._proposals_created > 0:
            raise SessionViolationError(
                "Cannot access Class A content in a proposal-mode session "
                "(INV-KK-SESSION-SEPARATION)."
            )
        self._class_a_accesses += 1

    def record_proposal(self) -> None:
        """Record a proposal creation. Raises SessionViolationError if Class A was accessed."""
        if self._class_a_accesses > 0:
            raise SessionViolationError(
                "Cannot create proposals in an extraction-mode session "
                "(INV-KK-SESSION-SEPARATION)."
            )
        self._proposals_created += 1

    @property
    def is_extraction_mode(self) -> bool:
        return self._class_a_accesses > 0

    @property
    def is_proposal_mode(self) -> bool:
        return self._proposals_created > 0

    @property
    def is_clean(self) -> bool:
        return self._class_a_accesses == 0 and self._proposals_created == 0
