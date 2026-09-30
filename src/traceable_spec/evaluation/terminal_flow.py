"""Read-only terminal-flow sensitivity, separate from the frozen chain metric.

Initial nodes are sources and final nodes are sinks. Filtering the historical
audit through these constraints does not establish semantic requirement truth
or replace the official acceptance contract. Historical outputs stay intact.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from traceable_spec.entities import (
    ActivityDiagram,
    GeneratedSpecification,
    IssueCategory,
    IssueSeverity,
    ValidationIssue,
    ValidationReport,
)
from traceable_spec.evaluation.chain_audit import audit_chain

VERSION = "terminal-flow-sensitivity-v1"


def _reach(starts: set[str], adjacency: Mapping[str, set[str]]) -> set[str]:
    visited: set[str] = set()
    pending = list(starts)
    while pending:
        node_id = pending.pop()
        if node_id not in visited:
            visited.add(node_id)
            pending.extend(adjacency.get(node_id, set()) - visited)
    return visited


@dataclass(frozen=True)
class _TerminalPaths:
    reachable: set[str]
    terminating: set[str]
    valid_node_ids: set[str]
    valid_edge_ids: set[str]
    violations: list[dict[str, Any]]


def _terminal_paths(diagram: Mapping[str, Any]) -> _TerminalPaths:
    """Ignore dangling/ambiguous references; existing validators diagnose them.

    Both adjacency directions are built from the same permissible edges, so a
    path cannot reach its destination by leaving a final or reentering initial.
    """
    raw_nodes = diagram.get("nodes", [])
    raw_edges = diagram.get("edges", [])
    node_counts = Counter(node["id"] for node in raw_nodes)
    edge_counts = Counter(edge["id"] for edge in raw_edges)
    nodes = {node["id"]: node for node in raw_nodes if node_counts[node["id"]] == 1}
    # Retain all kinds for boundary diagnostics even when an ID is ambiguous.
    kinds: dict[str, set[str]] = defaultdict(set)
    for node in raw_nodes:
        kinds[node["id"]].add(node["kind"])
    forward: dict[str, set[str]] = defaultdict(set)
    reverse: dict[str, set[str]] = defaultdict(set)
    valid_edges: set[str] = set()
    violations: list[dict[str, Any]] = []
    for edge in raw_edges:
        source, target = edge["source_node_id"], edge["target_node_id"]
        illegal = False
        for condition, code, message in (
            (
                "final" in kinds.get(source, set()),
                "outgoing_final_edge",
                "A final node is a sink and cannot have outgoing edges.",
            ),
            (
                "initial" in kinds.get(target, set()),
                "incoming_initial_edge",
                "An initial node is a source and cannot have incoming edges.",
            ),
        ):
            if condition:
                illegal = True
                violations.append(
                    {
                        "code": code,
                        "message": message,
                        "diagram_id": diagram["id"],
                        "use_case_id": diagram["use_case_id"],
                        "edge_id": edge["id"],
                        "source_node_id": source,
                        "target_node_id": target,
                        "element_ids": [edge["id"], source, target],
                    }
                )
        if illegal or source not in nodes or target not in nodes or edge_counts[edge["id"]] != 1:
            continue
        forward[source].add(target)
        reverse[target].add(source)
        valid_edges.add(edge["id"])
    initials = {node_id for node_id, node in nodes.items() if node["kind"] == "initial"}
    finals = {node_id for node_id, node in nodes.items() if node["kind"] == "final"}
    reachable = _reach(initials, forward)
    terminating = _reach(finals, reverse)
    for node_id in sorted(nodes):
        for condition, code, message in (
            (
                node_id not in reachable,
                "terminal_unreachable_from_initial",
                "Node is unreachable from an initial without crossing a terminal boundary.",
            ),
            (
                node_id not in terminating,
                "terminal_cannot_reach_final",
                "Node has no path to a final without crossing a terminal boundary.",
            ),
        ):
            if condition:
                violations.append(
                    {
                        "code": code,
                        "message": message,
                        "diagram_id": diagram["id"],
                        "use_case_id": diagram["use_case_id"],
                        "node_id": node_id,
                        "element_ids": [node_id],
                    }
                )
    return _TerminalPaths(reachable, terminating, set(nodes), valid_edges, violations)


def validate_terminal_flow(diagram: ActivityDiagram) -> ValidationReport:
    """Additional typed guard, intended to run alongside existing validators.

    Missing endpoints and duplicate IDs are skipped safely here; the existing
    schema/structure/ID validators remain responsible for those defects.
    """
    paths = _terminal_paths(diagram.model_dump(mode="json"))
    issues = [
        ValidationIssue(
            id=f"VI-{i:03d}",
            severity=IssueSeverity.ERROR,
            category=IssueCategory.STRUCTURAL,
            code=violation["code"],
            message=violation["message"],
            element_ids=violation["element_ids"],
            blocking=True,
        )
        for i, violation in enumerate(paths.violations, 1)
    ]
    return ValidationReport(
        passed=not issues,
        issues=issues,
        validator_name="activity_terminal_flow",
        details={
            "profile": VERSION,
            "additional_opt_in_guard": True,
            "reachable_node_ids": sorted(paths.reachable),
            "can_reach_final_node_ids": sorted(paths.terminating),
        },
    )


def audit_terminal_flow(spec: Mapping[str, Any] | GeneratedSpecification) -> dict[str, Any]:
    """Compare frozen chain coverage with terminal-safe path coverage, read-only.

    All legacy conditions (ownership, uniqueness, source scope, unsupported
    flags) are retained by filtering its chains. An FR remains covered if ANY
    of its action chains survives, including one in a different diagram.
    """
    raw = spec.model_dump(mode="json") if isinstance(spec, GeneratedSpecification) else spec
    legacy = audit_chain(raw)  # type: ignore[no-untyped-call]
    diagrams = [
        result["activity_diagram"]
        for result in raw.get("activity_results", [])
        if result.get("activity_diagram") is not None
    ]
    contexts: dict[tuple[str, str], list[tuple[Mapping[str, Any], _TerminalPaths]]] = defaultdict(
        list
    )
    violations: list[dict[str, Any]] = []
    diagram_rows: list[dict[str, Any]] = []
    for index, diagram in enumerate(diagrams):
        paths = _terminal_paths(diagram)
        contexts[(diagram["use_case_id"], diagram["id"])].append((diagram, paths))
        violations.extend({**item, "diagram_index": index} for item in paths.violations)
        diagram_rows.append(
            {
                "diagram_index": index,
                "diagram_id": diagram["id"],
                "use_case_id": diagram["use_case_id"],
                "reachable_node_ids": sorted(paths.reachable),
                "can_reach_final_node_ids": sorted(paths.terminating),
            }
        )
    kept: list[dict[str, Any]] = []
    discarded: list[dict[str, Any]] = []
    for chain in legacy["chains"]:
        matches = contexts.get((chain["uc_id"], chain["diagram_id"]), [])
        survives = False
        if len(matches) == 1:
            diagram, paths = matches[0]
            on_path = paths.reachable & paths.terminating
            if chain["element_type"] == "edge":
                edges = [e for e in diagram["edges"] if e["id"] == chain["element_id"]]
                survives = (
                    len(edges) == 1
                    and edges[0]["id"] in paths.valid_edge_ids
                    and edges[0]["source_node_id"] in on_path
                    and edges[0]["target_node_id"] in on_path
                )
            else:
                survives = chain["element_id"] in paths.valid_node_ids & on_path
        (kept if survives else discarded).append(deepcopy(chain))
    old_frs = {c["fr_id"] for c in legacy["chains"] if c["element_type"] == "action"}
    safe_frs = {c["fr_id"] for c in kept if c["element_type"] == "action"}
    fr_ids = {fr["id"] for fr in raw["request"]["functional_requirements"]}
    denominator = len(fr_ids)
    boundary_edges: dict[tuple[int, str, str, str], dict[str, Any]] = {}
    for violation in violations:
        if "edge_id" not in violation:
            continue
        key = (
            violation["diagram_index"],
            violation["edge_id"],
            violation["source_node_id"],
            violation["target_node_id"],
        )
        if key not in boundary_edges:
            boundary_edges[key] = {**violation, "codes": []}
        boundary_edges[key]["codes"].append(violation["code"])
    return {
        "version": VERSION,
        "sensitivity_only": True,
        "official_metric_replacement": False,
        "semantic_truth_verified": False,
        "fr_count": denominator,
        "legacy_fr_with_action_chain": len(old_frs),
        "terminal_safe_fr_with_action_chain": len(safe_frs),
        "legacy_fr_action_chain_coverage": len(old_frs) / denominator if denominator else None,
        "terminal_safe_fr_action_chain_coverage": (
            len(safe_frs) / denominator if denominator else None
        ),
        "legacy_action_chain_count": sum(c["element_type"] == "action" for c in legacy["chains"]),
        "terminal_safe_action_chain_count": sum(c["element_type"] == "action" for c in kept),
        "lost_fr_ids": sorted(old_frs - safe_frs),
        "missing_terminal_safe_fr_ids": sorted(fr_ids - safe_frs),
        "illegal_boundary_edges": list(boundary_edges.values()),
        "violations": violations,
        "diagrams": diagram_rows,
        "terminal_safe_chains": kept,
        "discarded_chains": discarded,
        "legacy_audit": legacy,
    }
