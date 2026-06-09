"""License scanning and Class A/B classification."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, List, Tuple

if TYPE_CHECKING:
    from ingest.parser import ParsedDocument


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


@dataclass
class ScanResult:
    artifact_class: ArtifactClass
    contamination_level: ContaminationLevel
    licenses_found: List[str] = field(default_factory=list)


# Priority order: highest contamination wins
_CONTAMINATION_ORDER = [
    ContaminationLevel.L3,
    ContaminationLevel.L2,
    ContaminationLevel.L1,
    ContaminationLevel.L0,
]

# (regex pattern, contamination level, SPDX-ish identifier)
_LICENSE_RULES: List[Tuple[str, ContaminationLevel, str]] = [
    # L3 â€” patent-sensitive (explicit patent restrictions, not permissive grants)
    (r"patent\s+retaliation", ContaminationLevel.L3, "LicenseRef-Patent-Retaliation"),
    (r"patent\s+claim", ContaminationLevel.L3, "LicenseRef-Patent-Claim"),
    (r"patent\s+termination", ContaminationLevel.L3, "LicenseRef-Patent-Termination"),
    # L2 â€” strong copyleft
    (r"\bAGPL", ContaminationLevel.L2, "AGPL"),
    (r"\bLGPL", ContaminationLevel.L2, "LGPL"),
    (r"\bGPL", ContaminationLevel.L2, "GPL"),
    (r"GNU\s+(?:General|Lesser)\s+Public\s+License", ContaminationLevel.L2, "GPL"),
    # L1 â€” permissive / weak copyleft
    (r"\bMIT\b", ContaminationLevel.L1, "MIT"),
    (r"\bBSD\b", ContaminationLevel.L1, "BSD"),
    (r"\bApache\b", ContaminationLevel.L1, "Apache-2.0"),
    (r"\bISC\b", ContaminationLevel.L1, "ISC"),
    (r"\bMPL\b", ContaminationLevel.L1, "MPL"),
    (r"Mozilla\s+Public\s+License", ContaminationLevel.L1, "MPL"),
    # L0 â€” public domain / CC0
    (r"\bCC[-\s]?0\b", ContaminationLevel.L0, "CC0-1.0"),
    (r"CC[-\s]?ZERO", ContaminationLevel.L0, "CC0-1.0"),
    (r"public[-\s]domain", ContaminationLevel.L0, "LicenseRef-PD"),
    (r"\bUnlicense\b", ContaminationLevel.L0, "Unlicense"),
    (r"\bPDDL\b", ContaminationLevel.L0, "PDDL"),
]


def scan_license(parsed_doc: "ParsedDocument") -> ScanResult:
    """Scan a ParsedDocument for license markers and classify contamination level.

    INV-KK-ALL-EVIDENCE-CLASS-A: always returns artifact_class=A.
    INV-KK-UNKNOWN-LICENSE-L4: returns L4 when no license is detected.
    """
    text = parsed_doc.text
    found_levels: set[ContaminationLevel] = set()
    licenses: list[str] = []
    seen_ids: set[str] = set()

    for pattern, level, spdx_id in _LICENSE_RULES:
        if re.search(pattern, text, re.IGNORECASE):
            found_levels.add(level)
            if spdx_id not in seen_ids:
                licenses.append(spdx_id)
                seen_ids.add(spdx_id)

    if not found_levels:
        return ScanResult(
            artifact_class=ArtifactClass.A,
            contamination_level=ContaminationLevel.L4,
            licenses_found=[],
        )

    for level in _CONTAMINATION_ORDER:
        if level in found_levels:
            return ScanResult(
                artifact_class=ArtifactClass.A,
                contamination_level=level,
                licenses_found=licenses,
            )

    # unreachable: _CONTAMINATION_ORDER covers all non-L4 levels
    return ScanResult(  # pragma: no cover
        artifact_class=ArtifactClass.A,
        contamination_level=ContaminationLevel.L4,
        licenses_found=[],
    )
