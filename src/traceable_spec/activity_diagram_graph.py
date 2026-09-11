"""Compatibility import for the Activity Diagram Agent graph.

New code should import :mod:`traceable_spec.agents.activity.graph`.
"""

from __future__ import annotations

from traceable_spec.agents.activity.graph import (
    ActivityNodeFns,
    activity_nodes_with_llm,
    activity_result_from_state,
    build_activity_diagram_graph,
    compile_activity_diagram_graph,
    default_activity_nodes,
)

__all__ = [
    "ActivityNodeFns",
    "activity_nodes_with_llm",
    "activity_result_from_state",
    "build_activity_diagram_graph",
    "compile_activity_diagram_graph",
    "default_activity_nodes",
]
