"""Optimization assessment layer — seeded/curated node creation and linking."""

from __future__ import annotations

import json
import sqlite3
import uuid

from graph.engine import add_edge, add_node


_VALID_DIRECTIONS = {"minimize", "maximize"}
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
