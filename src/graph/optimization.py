"""Optimization assessment layer — seeded/curated node creation and linking."""

from __future__ import annotations

import json
import sqlite3
import uuid

from graph.engine import add_edge, add_node, get_node


_VALID_DIRECTIONS = {"minimize", "maximize"}
_VALID_KERNEL_TYPES = {"monolithic", "microkernel", "rtos", "hybrid", "unikernel"}
_VALID_MATURITIES = {"production", "experimental", "deprecated", "removed"}
_VALID_CONTRIBUTION_DIRECTIONS = {"improves", "worsens", "neutral"}
_VALID_MAGNITUDES = {"strong", "moderate", "weak"}
_VALID_FITNESS = {"excellent", "good", "acceptable", "poor"}


def create_optimization_goal(
    conn: sqlite3.Connection,
    name: str,
    description: str,
    metric: str,
    direction: str,
) -> str:
    if not name or not name.strip():
        raise ValueError("name must be non-empty")
    if not metric or not metric.strip():
        raise ValueError("metric must be non-empty")
    if direction not in _VALID_DIRECTIONS:
        raise ValueError(f"direction must be one of {_VALID_DIRECTIONS}, got '{direction}'")
    goal_id = f"goal-{uuid.uuid4().hex[:12]}"
    add_node(conn, goal_id, "OptimizationGoal", {
        "name": name.strip(),
        "description": description.strip() if description else "",
        "metric": metric.strip(),
        "direction": direction,
    })
    return goal_id


def link_concept_to_goal(
    conn: sqlite3.Connection,
    concept_id: str,
    goal_id: str,
    direction: str,
    magnitude: str,
) -> None:
    if direction not in _VALID_CONTRIBUTION_DIRECTIONS:
        raise ValueError(f"direction must be one of {_VALID_CONTRIBUTION_DIRECTIONS}, got '{direction}'")
    if magnitude not in _VALID_MAGNITUDES:
        raise ValueError(f"magnitude must be one of {_VALID_MAGNITUDES}, got '{magnitude}'")
    add_edge(conn, "contributes-to", concept_id, goal_id, {
        "direction": direction,
        "magnitude": magnitude,
    })


def create_use_case_scenario(
    conn: sqlite3.Connection,
    name: str,
    description: str,
    workload_type: str,
    constraints: str,
) -> str:
    if not name or not name.strip():
        raise ValueError("name must be non-empty")
    if not workload_type or not workload_type.strip():
        raise ValueError("workload_type must be non-empty")
    scenario_id = f"scenario-{uuid.uuid4().hex[:12]}"
    add_node(conn, scenario_id, "UseCaseScenario", {
        "name": name.strip(),
        "description": description.strip() if description else "",
        "workload_type": workload_type.strip(),
        "constraints": constraints.strip() if constraints else "",
    })
    return scenario_id


def link_concept_to_scenario(
    conn: sqlite3.Connection,
    concept_id: str,
    scenario_id: str,
    fitness: str,
) -> None:
    if fitness not in _VALID_FITNESS:
        raise ValueError(f"fitness must be one of {_VALID_FITNESS}, got '{fitness}'")
    add_edge(conn, "suited-for", concept_id, scenario_id, {
        "fitness": fitness,
    })


def create_comparative_analysis(
    conn: sqlite3.Connection,
    concept_a_id: str,
    concept_b_id: str,
    dimension: str,
    winner: str,
    conditions: str = "",
    quantitative_delta: str = "",
) -> str:
    if not dimension or not dimension.strip():
        raise ValueError("dimension must be non-empty")
    if not winner or not winner.strip():
        raise ValueError("winner must be non-empty")
    node_a = get_node(conn, concept_a_id)
    node_b = get_node(conn, concept_b_id)
    if node_a is None:
        raise ValueError(f"concept_a_id '{concept_a_id}' does not exist")
    if node_b is None:
        raise ValueError(f"concept_b_id '{concept_b_id}' does not exist")
    if concept_a_id == concept_b_id:
        raise ValueError("concept_a_id and concept_b_id must be distinct")
    analysis_id = f"comparative-{uuid.uuid4().hex[:12]}"
    add_node(conn, analysis_id, "ComparativeAnalysis", {
        "dimension": dimension.strip(),
        "winner": winner.strip(),
        "conditions": conditions.strip() if conditions else "",
        "quantitative_delta": quantitative_delta.strip() if quantitative_delta else "",
        "artifact_class": "abstracted-mechanism",
    })
    add_edge(conn, "compares", analysis_id, concept_a_id)
    add_edge(conn, "compares", analysis_id, concept_b_id)
    return analysis_id


def create_kernel(
    conn: sqlite3.Connection,
    name: str,
    description: str,
    kernel_type: str,
) -> str:
    if not name or not name.strip():
        raise ValueError("name must be non-empty")
    if not description or not description.strip():
        raise ValueError("description must be non-empty")
    if kernel_type not in _VALID_KERNEL_TYPES:
        raise ValueError(f"kernel_type must be one of {_VALID_KERNEL_TYPES}, got '{kernel_type}'")
    kernel_id = f"kernel-{uuid.uuid4().hex[:12]}"
    add_node(conn, kernel_id, "Kernel", {
        "name": name.strip(),
        "description": description.strip(),
        "kernel_type": kernel_type,
    })
    return kernel_id


def link_concept_to_kernel(
    conn: sqlite3.Connection,
    concept_id: str,
    kernel_id: str,
    since_version: str = "",
    maturity: str = "production",
    variant_notes: str = "",
) -> None:
    if maturity not in _VALID_MATURITIES:
        raise ValueError(f"maturity must be one of {_VALID_MATURITIES}, got '{maturity}'")
    add_edge(conn, "implemented-in", concept_id, kernel_id, {
        "since_version": since_version,
        "maturity": maturity,
        "variant_notes": variant_notes,
    })
