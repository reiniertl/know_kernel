"""Shared graph engine library — SQLite-backed concept store."""

from know_kernel.graph.engine import (
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
from know_kernel.graph.rules import Violation, validate_node
from know_kernel.graph.schema import (
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
    "delete_edge",
    "delete_node",
    "get_edge",
    "get_node",
    "init_db",
    "list_nodes",
    "neighbors",
    "path_exists",
    "query_by_attrs",
    "update_node_attrs",
    "validate_graph",
    "validate_node",
]
