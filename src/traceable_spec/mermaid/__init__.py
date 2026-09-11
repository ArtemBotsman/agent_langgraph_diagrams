"""Deterministic Mermaid renderer: ActivityDiagram -> str.

MVP format: flowchart TD (see docs/decisions/ADR-003-mermaid-format.md).
Identical input must yield identical output (stable sort by ID).
"""

from __future__ import annotations

from traceable_spec.entities import ActivityDiagram, ActivityNode, ActivityNodeKind

_NODE_SHAPES: dict[ActivityNodeKind, tuple[str, str]] = {
    ActivityNodeKind.INITIAL: ("((", "))"),
    ActivityNodeKind.FINAL: ("((", "))"),
    ActivityNodeKind.ACTION: ("[", "]"),
    ActivityNodeKind.DECISION: ("{", "}"),
    ActivityNodeKind.MERGE: ("{", "}"),
    ActivityNodeKind.FORK: ("[[", "]]"),
    ActivityNodeKind.JOIN: ("[[", "]]"),
    ActivityNodeKind.OBJECT: ("[", "]"),
}


def _escape_label(text: str) -> str:
    return text.replace('"', "'").replace("\n", " ")


def _escape_edge_label(text: str) -> str:
    """Escape tokens that Mermaid otherwise parses as edge/shape syntax."""

    return _escape_label(text).replace("|", "'")


def _node_line(node_id: str, kind: ActivityNodeKind, name: str) -> str:
    left, right = _NODE_SHAPES[kind]
    label = _escape_label(name)
    if kind == ActivityNodeKind.INITIAL:
        label = "start"
    elif kind == ActivityNodeKind.FINAL:
        label = "end"
    return f'  {node_id}{left}"{label}"{right}'


def render_mermaid(diagram: ActivityDiagram) -> str:
    """Pure function: ActivityDiagram -> Mermaid flowchart string."""
    lines: list[str] = ["flowchart TD", f"  %% activity:{diagram.id} uc:{diagram.use_case_id}"]

    partitions = sorted(diagram.partitions, key=lambda p: p.id)
    nodes_by_partition: dict[str | None, list[ActivityNode]] = {None: []}
    for partition in partitions:
        nodes_by_partition[partition.id] = []
    for node in sorted(diagram.nodes, key=lambda n: n.id):
        key = node.partition_id if node.partition_id in nodes_by_partition else None
        nodes_by_partition.setdefault(key, []).append(node)

    emitted: set[str] = set()

    def emit_node(node: ActivityNode) -> None:
        if node.id in emitted:
            return
        lines.append(_node_line(node.id, node.kind, node.name))
        emitted.add(node.id)

    for partition in partitions:
        lines.append(f'  subgraph {partition.id}["{_escape_label(partition.name)}"]')
        for node in nodes_by_partition.get(partition.id, []):
            emit_node(node)
        lines.append("  end")

    for node in nodes_by_partition.get(None, []):
        emit_node(node)

    # Safety: any node not yet emitted
    for node in sorted(diagram.nodes, key=lambda n: n.id):
        emit_node(node)

    for edge in sorted(diagram.edges, key=lambda e: e.id):
        label = edge.guard or edge.label
        if label:
            lines.append(
                f'  {edge.source_node_id} -->|"{_escape_edge_label(label)}"| {edge.target_node_id}'
            )
        else:
            lines.append(f"  {edge.source_node_id} --> {edge.target_node_id}")

    return "\n".join(lines) + "\n"
