"""License scanning and Class A/B classification."""

from __future__ import annotations

from enum import Enum


class ArtifactClass(Enum):
    A = "licensed-evidence"
    B = "abstracted-mechanism"
    C = "internal-proposal"


class ContaminationLevel(Enum):
    L0 = "public-domain"
    L1 = "weak-copyleft"
    L2 = "strong-copyleft"
    L3 = "patent-sensitive"
    L4 = "unknown-provenance"


def scan_license(path: str) -> tuple[ArtifactClass, ContaminationLevel]:
    raise NotImplementedError
