"""Shared graph engine library â€” SQLite-backed concept store."""

from graph.engine import (
    AdmissibilityError,
    add_edge,
    add_node,
    delete_edge,
    delete_node,
    get_edge,
    get_node,
    list_nodes,
    neighbors,
    path_exists,
    query_by_attrs,
    update_node_attrs,
    validate_graph,
)
from graph.optimization import (
    create_optimization_goal,
    create_use_case_scenario,
    link_concept_to_goal,
    link_concept_to_scenario,
)
from graph.rules import Violation, validate_node
from graph.schema import (
    EDGE_KINDS,
    EDGE_VALID_PAIRS,
    NODE_KINDS,
    REQUIRED_ATTRS,
    init_db,
)

__all__ = [
    "AdmissibilityError",
    "EDGE_KINDS",
    "EDGE_VALID_PAIRS",
    "NODE_KINDS",
    "REQUIRED_ATTRS",
    "Violation",
    "add_edge",
    "add_node",
    "create_optimization_goal",
    "create_use_case_scenario",
    "delete_edge",
    "delete_node",
    "get_edge",
    "get_node",
    "init_db",
    "link_concept_to_goal",
    "link_concept_to_scenario",
    "list_nodes",
    "neighbors",
    "path_exists",
    "query_by_attrs",
    "update_node_attrs",
    "validate_graph",
    "validate_node",
]
