"""CVE vulnerability tracker -- poll NVD API and create Vulnerability nodes (ALG-KK-VULN-TRACK)."""

from __future__ import annotations

import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from typing import Any

from graph.engine import add_edge, add_node

log = logging.getLogger(__name__)

# INV-KK-VULN-CWE-MAP: static CWE-to-Concept name mapping.
CWE_CONCEPT_MAP: dict[str, list[str]] = {
    "CWE-416": ["RCU", "Slab Allocator"],
    "CWE-415": ["Slab Allocator", "Reference Counting"],
    "CWE-362": ["Spinlocks", "Mutexes", "RCU"],
    "CWE-787": ["Page Tables", "Buffer Management"],
    "CWE-125": ["Buffer Management", "Page Tables"],
    "CWE-476": ["VFS", "Driver Model"],
    "CWE-190": ["Integer Overflow"],
    "CWE-119": ["Buffer Management"],
    "CWE-120": ["Buffer Management"],
    "CWE-401": ["Memory Management", "Slab Allocator"],
    "CWE-667": ["Locking", "Deadlock"],
    "CWE-908": ["Memory Management"],
    "CWE-772": ["Memory Management", "File Descriptors"],
}

NVD_API_BASE = "https://services.nvd.nist.gov/rest/json/cves/2.0"
KERNEL_CPE_MATCH = "cpe:2.3:o:linux:linux_kernel"


@dataclass
class ParsedCVE:
    cve_id: str
    description: str
    cvss_score: float | None
    severity: str
    cwe_ids: list[str]
    affected_versions: str
    published_date: str
    status: str = "unfixed"


def cvss_to_severity(score: float | None) -> str:
    """INV-KK-VULN-CVSS-SEVERITY: derive severity from CVSS score brackets."""
    if score is None:
        return "medium"
    if score >= 9.0:
        return "critical"
    if score >= 7.0:
        return "high"
    if score >= 4.0:
        return "medium"
    return "low"


def _cve_id_exists(conn: sqlite3.Connection, cve_id: str) -> bool:
    """INV-KK-VULN-CVE-DEDUP: check if a Vulnerability with this cve_id exists."""
    row = conn.execute(
        "SELECT 1 FROM nodes WHERE kind = 'Vulnerability' AND json_extract(attrs, '$.cve_id') = ?",
        (cve_id,),
    ).fetchone()
    return row is not None


def _find_concepts_by_name(conn: sqlite3.Connection, name: str) -> list[str]:
    """Find Concept nodes matching a name (case-insensitive)."""
    rows = conn.execute(
        "SELECT id FROM nodes WHERE kind = 'Concept' AND LOWER(json_extract(attrs, '$.name')) = LOWER(?)",
        (name,),
    ).fetchall()
    return [r[0] for r in rows]


def _find_subsystems_by_name(conn: sqlite3.Connection, name: str) -> list[str]:
    """Find Subsystem nodes matching a name (case-insensitive)."""
    rows = conn.execute(
        "SELECT id FROM nodes WHERE kind = 'Subsystem' AND LOWER(json_extract(attrs, '$.name')) = LOWER(?)",
        (name,),
    ).fetchall()
    return [r[0] for r in rows]


def parse_nvd_response(data: dict[str, Any]) -> list[ParsedCVE]:
    """Parse NVD API 2.0 response into ParsedCVE objects."""
    cves: list[ParsedCVE] = []
    for vuln in data.get("vulnerabilities", []):
        cve_data = vuln.get("cve", {})
        cve_id = cve_data.get("id", "")
        if not cve_id:
            continue

        descriptions = cve_data.get("descriptions", [])
        description = ""
        for d in descriptions:
            if d.get("lang") == "en":
                description = d.get("value", "")
                break
        if not description and descriptions:
            description = descriptions[0].get("value", "")

        metrics = cve_data.get("metrics", {})
        cvss_score = None
        for version_key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
            metric_list = metrics.get(version_key, [])
            if metric_list:
                cvss_data = metric_list[0].get("cvssData", {})
                cvss_score = cvss_data.get("baseScore")
                if cvss_score is not None:
                    break

        cwe_ids: list[str] = []
        for weakness in cve_data.get("weaknesses", []):
            for wd in weakness.get("description", []):
                val = wd.get("value", "")
                if val.startswith("CWE-"):
                    cwe_ids.append(val)

        affected_versions = ""
        configurations = cve_data.get("configurations", [])
        for config in configurations:
            for node in config.get("nodes", []):
                for match in node.get("cpeMatch", []):
                    cpe = match.get("criteria", "")
                    if "linux_kernel" in cpe:
                        vs = match.get("versionStartIncluding", "")
                        ve = match.get("versionEndExcluding", match.get("versionEndIncluding", ""))
                        if vs and ve:
                            affected_versions = f"{vs} - {ve}"
                        elif ve:
                            affected_versions = f"< {ve}"
                        elif vs:
                            affected_versions = f">= {vs}"
                        break

        published = cve_data.get("published", "")[:10]

        cves.append(ParsedCVE(
            cve_id=cve_id,
            description=description,
            cvss_score=cvss_score,
            severity=cvss_to_severity(cvss_score),
            cwe_ids=cwe_ids,
            affected_versions=affected_versions,
            published_date=published,
        ))

    return cves


def ingest_cve(conn: sqlite3.Connection, cve: ParsedCVE) -> str | None:
    """Create Vulnerability node + edges for a CVE. Returns node ID or None if duplicate."""
    if _cve_id_exists(conn, cve.cve_id):
        log.debug("Skipping duplicate CVE: %s", cve.cve_id)
        return None

    vuln_id = f"vuln-{uuid.uuid4().hex[:12]}"

    add_node(conn, vuln_id, "Vulnerability", {
        "cve_id": cve.cve_id,
        "title": cve.description[:120] if cve.description else cve.cve_id,
        "description": cve.description,
        "severity": cve.severity,
        "cvss_score": str(cve.cvss_score) if cve.cvss_score is not None else "",
        "affected_versions": cve.affected_versions,
        "status": cve.status,
        "source_date": cve.published_date,
        "artifact_class": "B",
    })

    linked_concepts: set[str] = set()
    for cwe_id in cve.cwe_ids:
        concept_names = CWE_CONCEPT_MAP.get(cwe_id, [])
        for name in concept_names:
            concept_ids = _find_concepts_by_name(conn, name)
            for cid in concept_ids:
                if cid not in linked_concepts:
                    add_edge(conn, "exploits", vuln_id, cid)
                    linked_concepts.add(cid)

    return vuln_id


def ingest_cves(conn: sqlite3.Connection, nvd_data: dict[str, Any]) -> list[str]:
    """Parse NVD response and ingest all CVEs. Returns list of Vulnerability node IDs."""
    cves = parse_nvd_response(nvd_data)
    vuln_ids: list[str] = []
    for cve in cves:
        vuln_id = ingest_cve(conn, cve)
        if vuln_id:
            vuln_ids.append(vuln_id)
    return vuln_ids
