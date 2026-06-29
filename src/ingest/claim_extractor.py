"""Claim extraction from discourse sources (ALG-KK-CLAIM-EXTRACT).

Extracts time-varying evidence (problems, observations, proposals,
benchmarks, rejections, discussions) from news articles, mailing list
threads, forum posts, and conference notes. Structurally distinct from
concept extraction (extractor.py) which extracts timeless mechanisms.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from graph.engine import add_edge, add_node

log = logging.getLogger(__name__)


CLAIM_EXTRACTION_PROMPT = """\
You are a claim extraction agent for a kernel research intelligence system.

Your task: given a news article, mailing list thread, conference abstract, \
or benchmark report about Linux kernel development, extract CLAIMS, \
PROBLEMS, PROPOSALS, OBSERVATIONS, and REJECTIONS.

You are NOT extracting abstract concepts or design patterns. You are \
extracting what people are SAYING, PROPOSING, OBSERVING, and DEBATING \
about the kernel RIGHT NOW.

For each item, also identify which existing kernel CONCEPTS it relates to. \
You will be given a list of known concept names to match against.

Return a JSON object with these keys:

"problems": [
    {
        "title": "Short problem statement",
        "description": "What is going wrong or what is unsolved",
        "severity": "critical|high|medium|low",
        "related_concepts": ["concept-name-1", "concept-name-2"]
    }
]

"observations": [
    {
        "claim": "A factual assertion made in the source",
        "confidence": 0.0-1.0,
        "related_concepts": ["concept-name-1"]
    }
]

"proposals": [
    {
        "name": "Short proposal name",
        "description": "What is being proposed",
        "status": "draft|under-review|accepted|rejected|abandoned",
        "related_concepts": ["concept-name-1"],
        "addresses_problems": ["problem-title-1"]
    }
]

"benchmarks": [
    {
        "metric": "What was measured",
        "result_summary": "One-line result",
        "conditions": "Hardware/workload/config",
        "related_concepts": ["concept-name-1"]
    }
]

"rejections": [
    {
        "proposal_title": "What was rejected",
        "reason": "Why it was rejected",
        "rejector": "Who rejected it",
        "related_concepts": ["concept-name-1"]
    }
]

"discussion": {
    "title": "Thread/article title",
    "forum": "lkml|lwn|hackernews|plumbers|phoronix|other",
    "participant_count": 0,
    "summary": "2-3 sentence summary of the discussion",
    "related_concepts": ["concept-name-1", "concept-name-2"]
}

IMPORTANT: Only extract what the source ACTUALLY SAYS. Do not hallucinate \
claims, problems, or proposals that are not in the text. If the source \
does not contain a particular category, return an empty array for it.

Do NOT use your general training knowledge to embellish or augment what \
the source says. If a category has no items in the source, return an \
empty array.\
"""

VALID_SEVERITIES = frozenset({"critical", "high", "medium", "low"})
VALID_PROPOSAL_STATUSES = frozenset({"draft", "under-review", "accepted", "rejected", "abandoned"})
VALID_FORUMS = frozenset({"lkml", "lwn", "hackernews", "plumbers", "phoronix", "other"})


class LLMClient(Protocol):
    def create_message(
        self, model: str, system: str, user: str, max_tokens: int,
    ) -> dict[str, Any]: ...


def build_claim_extraction_context(conn: sqlite3.Connection) -> str:
    """Query all existing Concept names for LLM matching context (INV-KK-CLAIM-CONCEPT-CONTEXT)."""
    rows = conn.execute(
        "SELECT json_extract(attrs, '$.name') as name FROM nodes WHERE kind = 'Concept'"
    ).fetchall()
    names = sorted({r[0] for r in rows if r[0]})
    if not names:
        return "No known kernel concepts yet."
    return "Known kernel concepts: " + ", ".join(names)


def build_claim_user_prompt(source_text: str, concept_context: str) -> str:
    parts = [concept_context, "", "Extract claims from this discourse source:", "", source_text]
    return "\n".join(parts)


def _resolve_concept_names(conn: sqlite3.Connection) -> dict[str, str]:
    """Build lowercase concept name -> node ID map."""
    rows = conn.execute(
        "SELECT id, json_extract(attrs, '$.name') as name FROM nodes WHERE kind = 'Concept'"
    ).fetchall()
    return {r[1].lower(): r[0] for r in rows if r[1]}


def levenshtein_distance(s: str, t: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(s) < len(t):
        return levenshtein_distance(t, s)
    if not t:
        return len(s)
    prev = list(range(len(t) + 1))
    for i, sc in enumerate(s):
        curr = [i + 1]
        for j, tc in enumerate(t):
            cost = 0 if sc == tc else 1
            curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[-1]


def fuzzy_match_concept(
    query: str, name_to_id: dict[str, str], max_distance: int = 2,
) -> str | None:
    """Three-tier fuzzy match: exact, prefix, Levenshtein (INV-KK-CLAIM-FUZZY-THRESHOLD).

    Returns the concept node ID or None.
    """
    q = query.lower()
    if q in name_to_id:
        return name_to_id[q]
    for name, cid in name_to_id.items():
        if name.startswith(q) or q.startswith(name):
            return cid
    best_id = None
    best_dist = max_distance + 1
    for name, cid in name_to_id.items():
        d = levenshtein_distance(q, name)
        if d <= max_distance and d < best_dist:
            best_dist = d
            best_id = cid
    return best_id


def validate_problem(item: Any) -> dict | None:
    if not isinstance(item, dict):
        return None
    title = item.get("title")
    desc = item.get("description")
    severity = item.get("severity", "").strip().lower() if isinstance(item.get("severity"), str) else ""
    if not isinstance(title, str) or not title.strip():
        return None
    if not isinstance(desc, str) or not desc.strip():
        return None
    if severity not in VALID_SEVERITIES:
        return None
    return {
        "title": title.strip(),
        "description": desc.strip(),
        "severity": severity,
        "related_concepts": _extract_related(item),
    }


def validate_observation(item: Any) -> dict | None:
    if not isinstance(item, dict):
        return None
    claim = item.get("claim")
    confidence = item.get("confidence")
    if not isinstance(claim, str) or not claim.strip():
        return None
    if not isinstance(confidence, (int, float)):
        return None
    confidence = max(0.0, min(1.0, float(confidence)))
    return {
        "claim": claim.strip(),
        "confidence": confidence,
        "related_concepts": _extract_related(item),
    }


def validate_proposal(item: Any) -> dict | None:
    if not isinstance(item, dict):
        return None
    name = item.get("name")
    desc = item.get("description")
    status = item.get("status", "").strip().lower() if isinstance(item.get("status"), str) else ""
    if not isinstance(name, str) or not name.strip():
        return None
    if not isinstance(desc, str) or not desc.strip():
        return None
    if status not in VALID_PROPOSAL_STATUSES:
        status = "draft"
    addresses = item.get("addresses_problems", [])
    if not isinstance(addresses, list):
        addresses = []
    return {
        "name": name.strip(),
        "description": desc.strip(),
        "status": status,
        "related_concepts": _extract_related(item),
        "addresses_problems": [str(a).strip() for a in addresses if isinstance(a, str) and a.strip()],
    }


def validate_benchmark(item: Any) -> dict | None:
    if not isinstance(item, dict):
        return None
    metric = item.get("metric")
    result_summary = item.get("result_summary")
    conditions = item.get("conditions")
    if not isinstance(metric, str) or not metric.strip():
        return None
    if not isinstance(result_summary, str) or not result_summary.strip():
        return None
    if not isinstance(conditions, str) or not conditions.strip():
        return None
    return {
        "metric": metric.strip(),
        "result_summary": result_summary.strip(),
        "conditions": conditions.strip(),
        "related_concepts": _extract_related(item),
    }


def validate_rejection(item: Any) -> dict | None:
    if not isinstance(item, dict):
        return None
    proposal_title = item.get("proposal_title")
    reason = item.get("reason")
    rejector = item.get("rejector")
    if not isinstance(proposal_title, str) or not proposal_title.strip():
        return None
    if not isinstance(reason, str) or not reason.strip():
        return None
    if not isinstance(rejector, str) or not rejector.strip():
        return None
    return {
        "proposal_title": proposal_title.strip(),
        "reason": reason.strip(),
        "rejector": rejector.strip(),
        "related_concepts": _extract_related(item),
    }


def validate_discussion(item: Any) -> dict | None:
    if not isinstance(item, dict):
        return None
    title = item.get("title")
    forum = item.get("forum", "").strip().lower() if isinstance(item.get("forum"), str) else ""
    if not isinstance(title, str) or not title.strip():
        return None
    if forum not in VALID_FORUMS:
        forum = "other"
    participant_count = item.get("participant_count", 0)
    if not isinstance(participant_count, int):
        try:
            participant_count = int(participant_count)
        except (TypeError, ValueError):
            participant_count = 0
    return {
        "title": title.strip(),
        "forum": forum,
        "participant_count": max(0, participant_count),
        "related_concepts": _extract_related(item),
    }


def _extract_related(item: dict) -> list[str]:
    rc = item.get("related_concepts", [])
    if not isinstance(rc, list):
        return []
    return [str(c).strip() for c in rc if isinstance(c, str) and c.strip()]


def parse_llm_response(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        text = text.rsplit("```", 1)[0]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


@dataclass
class ClaimExtractionResult:
    evidence_id: str
    problems_created: int = 0
    observations_created: int = 0
    proposals_created: int = 0
    benchmarks_created: int = 0
    rejections_created: int = 0
    discussions_created: int = 0
    edges_created: int = 0
    concepts_matched: int = 0
    extraction_model: str = ""
    prompt_tokens: int = 0
    response_tokens: int = 0
    node_ids: list[str] = field(default_factory=list)


def extract_claims(
    conn: sqlite3.Connection,
    evidence_id: str,
    source_date: str,
    model: str = "claude-sonnet-4-6",
    dry_run: bool = False,
    client: LLMClient | None = None,
    source_text: str | None = None,
) -> ClaimExtractionResult:
    """Extract claims from discourse source (ALG-KK-CLAIM-EXTRACT).

    Creates Problem, Observation, Proposal, Benchmark, Rejection, Discussion
    nodes with source_date from the feed item (INV-KK-CLAIM-SOURCE-DATE).
    """
    row = conn.execute(
        "SELECT id, kind, attrs FROM nodes WHERE id = ?", (evidence_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Node '{evidence_id}' does not exist")

    if source_text is None:
        attrs = json.loads(row[2]) if row[2] else {}
        source_text = attrs.get("text", "")

    concept_context = build_claim_extraction_context(conn)
    user_prompt = build_claim_user_prompt(source_text or "", concept_context)

    if dry_run:
        return ClaimExtractionResult(
            evidence_id=evidence_id,
            extraction_model=model,
            prompt_tokens=len(CLAIM_EXTRACTION_PROMPT.split()) + len(user_prompt.split()),
        )

    if client is None:
        from ingest.extractor import AnthropicClientAdapter
        client = AnthropicClientAdapter()

    response = client.create_message(
        model=model,
        system=CLAIM_EXTRACTION_PROMPT,
        user=user_prompt,
        max_tokens=4096,
    )

    parsed = parse_llm_response(response["text"])
    name_to_id = _resolve_concept_names(conn)

    result = ClaimExtractionResult(
        evidence_id=evidence_id,
        extraction_model=model,
        prompt_tokens=response.get("prompt_tokens", 0),
        response_tokens=response.get("response_tokens", 0),
    )

    problem_title_to_id: dict[str, str] = {}

    for item in parsed.get("problems", []):
        validated = validate_problem(item)
        if validated is None:
            continue
        node_id = f"prob-{uuid.uuid4().hex[:12]}"
        add_node(conn, node_id, "Problem", {
            "title": validated["title"],
            "description": validated["description"],
            "severity": validated["severity"],
            "status": "open",
            "source_date": source_date,
            "artifact_class": "B",
        })
        add_edge(conn, "extracted-from", node_id, evidence_id)
        result.edges_created += 1
        result.node_ids.append(node_id)
        problem_title_to_id[validated["title"].lower()] = node_id
        result.problems_created += 1
        result.edges_created += _wire_concept_edges(
            conn, node_id, validated["related_concepts"], name_to_id, "identifies-problem",
        )
        result.concepts_matched += _count_matches(validated["related_concepts"], name_to_id)

    for item in parsed.get("observations", []):
        validated = validate_observation(item)
        if validated is None:
            continue
        node_id = f"obs-{uuid.uuid4().hex[:12]}"
        add_node(conn, node_id, "Observation", {
            "claim": validated["claim"],
            "confidence": validated["confidence"],
            "source_date": source_date,
            "artifact_class": "B",
        })
        add_edge(conn, "extracted-from", node_id, evidence_id)
        result.edges_created += 1
        result.node_ids.append(node_id)
        result.observations_created += 1
        result.edges_created += _wire_concept_edges(
            conn, node_id, validated["related_concepts"], name_to_id, "observes",
        )
        result.concepts_matched += _count_matches(validated["related_concepts"], name_to_id)

    for item in parsed.get("proposals", []):
        validated = validate_proposal(item)
        if validated is None:
            continue
        node_id = f"prop-{uuid.uuid4().hex[:12]}"
        add_node(conn, node_id, "Proposal", {
            "name": validated["name"],
            "description": validated["description"],
            "status": validated["status"],
            "source_date": source_date,
            "artifact_class": "B",
        })
        add_edge(conn, "extracted-from", node_id, evidence_id)
        result.edges_created += 1
        result.node_ids.append(node_id)
        result.proposals_created += 1
        result.edges_created += _wire_concept_edges(
            conn, node_id, validated["related_concepts"], name_to_id, "grounded-in",
        )
        result.concepts_matched += _count_matches(validated["related_concepts"], name_to_id)
        for prob_title in validated.get("addresses_problems", []):
            prob_id = problem_title_to_id.get(prob_title.lower())
            if prob_id:
                add_edge(conn, "addresses", node_id, prob_id)
                result.edges_created += 1

    for item in parsed.get("benchmarks", []):
        validated = validate_benchmark(item)
        if validated is None:
            continue
        node_id = f"bench-{uuid.uuid4().hex[:12]}"
        add_node(conn, node_id, "Benchmark", {
            "metric": validated["metric"],
            "result_summary": validated["result_summary"],
            "conditions": validated["conditions"],
            "source_date": source_date,
            "artifact_class": "B",
        })
        add_edge(conn, "extracted-from", node_id, evidence_id)
        result.edges_created += 1
        result.node_ids.append(node_id)
        result.benchmarks_created += 1
        result.edges_created += _wire_concept_edges(
            conn, node_id, validated["related_concepts"], name_to_id, "benchmarks",
        )
        result.concepts_matched += _count_matches(validated["related_concepts"], name_to_id)

    for item in parsed.get("rejections", []):
        validated = validate_rejection(item)
        if validated is None:
            continue
        node_id = f"rej-{uuid.uuid4().hex[:12]}"
        add_node(conn, node_id, "Rejection", {
            "proposal_title": validated["proposal_title"],
            "reason": validated["reason"],
            "rejector": validated["rejector"],
            "source_date": source_date,
            "artifact_class": "B",
        })
        add_edge(conn, "extracted-from", node_id, evidence_id)
        result.edges_created += 1
        result.node_ids.append(node_id)
        result.rejections_created += 1
        result.edges_created += _wire_concept_edges(
            conn, node_id, validated["related_concepts"], name_to_id, "rejected-for",
        )
        result.concepts_matched += _count_matches(validated["related_concepts"], name_to_id)

    disc_data = parsed.get("discussion")
    if disc_data:
        validated = validate_discussion(disc_data)
        if validated is not None:
            node_id = f"disc-{uuid.uuid4().hex[:12]}"
            add_node(conn, node_id, "Discussion", {
                "title": validated["title"],
                "forum": validated["forum"],
                "participant_count": validated["participant_count"],
                "source_date": source_date,
                "artifact_class": "B",
            })
            add_edge(conn, "extracted-from", node_id, evidence_id)
            result.edges_created += 1
            result.node_ids.append(node_id)
            result.discussions_created += 1
            result.edges_created += _wire_concept_edges(
                conn, node_id, validated["related_concepts"], name_to_id, "discusses",
            )
            result.concepts_matched += _count_matches(validated["related_concepts"], name_to_id)

    conn.commit()
    return result


def _wire_concept_edges(
    conn: sqlite3.Connection,
    node_id: str,
    related_concepts: list[str],
    name_to_id: dict[str, str],
    edge_kind: str,
) -> int:
    """INV-KK-CLAIM-EDGE-VALID: only create edges for matched concepts."""
    created = 0
    for concept_name in related_concepts:
        concept_id = fuzzy_match_concept(concept_name, name_to_id)
        if concept_id:
            add_edge(conn, edge_kind, node_id, concept_id)
            created += 1
    return created


def _count_matches(related_concepts: list[str], name_to_id: dict[str, str]) -> int:
    return sum(1 for c in related_concepts if fuzzy_match_concept(c, name_to_id) is not None)
