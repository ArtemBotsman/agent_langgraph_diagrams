"""Measure deterministic-validator detection on intentionally corrupted artifacts."""

# SVG fragments are kept inline so the generated evidence is reproducible.
# ruff: noqa: E501

from __future__ import annotations

import csv
import json
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from traceable_spec.entities import (
    ActivityDiagram,
    ActivityGenerationResult,
    ActivityNodeKind,
    ElementRefType,
    GeneratedSpecification,
    PipelineStatus,
    SpecificationRequest,
    TraceLink,
    TraceLinkType,
    TraceManifest,
    TraceOrigin,
    UseCaseSet,
    ValidationReport,
    normalize_specification_req,
)
from traceable_spec.testing.fixtures import (
    sample_activity_diagram,
    sample_request,
    sample_use_case_set,
)
from traceable_spec.traceability import inherit_step_sources, materialize_trace_manifest
from traceable_spec.validators import (
    validate_activity_deterministic,
    validate_end_to_end_trace,
    validate_trace_link_contracts,
    validate_use_case_set_deterministic,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "artifacts" / "validator_mutations_v1"


@dataclass(frozen=True)
class Mutation:
    mutation_id: str
    error_class: str
    expected_code: str
    run: Callable[[], ValidationReport]


def _base() -> tuple[SpecificationRequest, UseCaseSet, ActivityDiagram, TraceManifest]:
    request = normalize_specification_req(sample_request())
    use_case_set = inherit_step_sources(sample_use_case_set())
    diagram = sample_activity_diagram()
    trace = materialize_trace_manifest(request, use_case_set, [diagram])
    return request, use_case_set, diagram, trace


def _e2e(
    request: SpecificationRequest,
    use_case_set: UseCaseSet,
    diagram: ActivityDiagram,
    trace: TraceManifest,
) -> ValidationReport:
    return validate_end_to_end_trace(
        GeneratedSpecification(
            request=request,
            use_case_set=use_case_set,
            activity_results=[
                ActivityGenerationResult(
                    use_case_id=diagram.use_case_id,
                    activity_diagram=diagram,
                    status=PipelineStatus.SUCCESS,
                )
            ],
            trace_manifest=trace,
            status=PipelineStatus.SUCCESS,
        )
    )


def build_mutations() -> list[Mutation]:
    request, use_case_set, diagram, trace = _base()

    def duplicate_actor() -> ValidationReport:
        broken = deepcopy(use_case_set)
        broken.actors.append(deepcopy(broken.actors[0]))
        return validate_use_case_set_deterministic(broken, request, trace)

    def atom_parent() -> ValidationReport:
        broken_request = deepcopy(request)
        object.__setattr__(
            broken_request.functional_requirements[0].atoms[0],
            "parent_fr_id",
            "FR-999",
        )
        return validate_use_case_set_deterministic(use_case_set, broken_request, trace)

    def missing_relation() -> ValidationReport:
        broken = TraceManifest(links=trace.links[1:])
        return _e2e(request, use_case_set, diagram, broken)

    def extra_reverse_relation() -> ValidationReport:
        extra = TraceLink(
            id=f"TL-{len(trace.links) + 1:03d}",
            source_type=ElementRefType.FR,
            source_id="FR-001",
            target_type=ElementRefType.STEP,
            target_id="STEP-UC001-002",
            link_type=TraceLinkType.FR_TO_STEP,
            origin=TraceOrigin.HUMAN,
        )
        return _e2e(request, use_case_set, diagram, TraceManifest(links=[*trace.links, extra]))

    def endpoint_type() -> ValidationReport:
        broken_link = trace.links[0].model_copy(update={"source_type": ElementRefType.ACTOR})
        return validate_trace_link_contracts(TraceManifest(links=[broken_link, *trace.links[1:]]))

    def dangling_target() -> ValidationReport:
        broken_link = trace.links[0].model_copy(update={"target_id": "FRA-999-999"})
        return _e2e(
            request,
            use_case_set,
            diagram,
            TraceManifest(links=[broken_link, *trace.links[1:]]),
        )

    def no_initial() -> ValidationReport:
        broken = diagram.model_copy(
            update={
                "nodes": [node for node in diagram.nodes if node.kind != ActivityNodeKind.INITIAL]
            }
        )
        return validate_activity_deterministic(broken, use_case_set.use_cases[0])

    def unknown_edge_target() -> ValidationReport:
        edge = diagram.edges[0].model_copy(update={"target_node_id": "ADN-UC001-999"})
        broken = diagram.model_copy(update={"edges": [edge, *diagram.edges[1:]]})
        return validate_activity_deterministic(broken, use_case_set.use_cases[0])

    def missing_guard() -> ValidationReport:
        edges = [deepcopy(edge) for edge in diagram.edges]
        decision_id = next(
            node.id for node in diagram.nodes if node.kind == ActivityNodeKind.DECISION
        )
        for edge in edges:
            if edge.source_node_id == decision_id:
                edge.guard = None
                break
        return validate_activity_deterministic(
            diagram.model_copy(update={"edges": edges}),
            use_case_set.use_cases[0],
        )

    def untraced_node() -> ValidationReport:
        nodes = [deepcopy(node) for node in diagram.nodes]
        action = next(node for node in nodes if node.kind == ActivityNodeKind.ACTION)
        action.related_step_ids = []
        return validate_activity_deterministic(
            diagram.model_copy(update={"nodes": nodes}),
            use_case_set.use_cases[0],
        )

    def untraced_edge() -> ValidationReport:
        edges = [deepcopy(edge) for edge in diagram.edges]
        edges[0].related_step_ids = []
        return validate_activity_deterministic(
            diagram.model_copy(update={"edges": edges}),
            use_case_set.use_cases[0],
        )

    def unknown_partition() -> ValidationReport:
        nodes = [deepcopy(node) for node in diagram.nodes]
        nodes[1].partition_id = "PART-UC001-999"
        return validate_activity_deterministic(
            diagram.model_copy(update={"nodes": nodes}),
            use_case_set.use_cases[0],
        )

    def step_outside_uc() -> ValidationReport:
        broken = deepcopy(use_case_set)
        broken.use_cases[0].main_success_scenario.steps[0].source_fr_ids = ["FR-999"]
        return validate_use_case_set_deterministic(broken, request, trace)

    def unknown_activity_step() -> ValidationReport:
        nodes = [deepcopy(node) for node in diagram.nodes]
        nodes[1].related_step_ids = ["STEP-UC001-999"]
        return validate_activity_deterministic(
            diagram.model_copy(update={"nodes": nodes}),
            use_case_set.use_cases[0],
        )

    def unsupported_without_reason() -> ValidationReport:
        extra = TraceLink(
            id=f"TL-{len(trace.links) + 1:03d}",
            source_type=ElementRefType.ACTIVITY_NODE,
            source_id="ADN-UC001-002",
            target_type=ElementRefType.ACTIVITY,
            target_id="AD-UC001",
            link_type=TraceLinkType.UNSUPPORTED,
            origin=TraceOrigin.LLM,
        )
        return validate_trace_link_contracts(TraceManifest(links=[*trace.links, extra]))

    return [
        Mutation("MUT-001", "identifier uniqueness", "duplicate_id", duplicate_actor),
        Mutation("MUT-002", "FR atom parent", "atom_parent_mismatch", atom_parent),
        Mutation("MUT-003", "missing forward link", "missing_declared_trace", missing_relation),
        Mutation(
            "MUT-004",
            "unsupported reverse link",
            "undeclared_reverse_trace",
            extra_reverse_relation,
        ),
        Mutation("MUT-005", "endpoint type", "trace_endpoint_type_mismatch", endpoint_type),
        Mutation("MUT-006", "dangling endpoint", "dangling_trace_target", dangling_target),
        Mutation("MUT-007", "initial cardinality", "initial_node_count", no_initial),
        Mutation("MUT-008", "edge endpoint", "unknown_edge_target", unknown_edge_target),
        Mutation("MUT-009", "decision guard", "decision_missing_guard", missing_guard),
        Mutation("MUT-010", "node provenance", "activity_node_untraced", untraced_node),
        Mutation("MUT-011", "edge provenance", "activity_edge_untraced", untraced_edge),
        Mutation("MUT-012", "partition reference", "unknown_node_partition", unknown_partition),
        Mutation("MUT-013", "step FR scope", "step_fr_outside_uc_scope", step_outside_uc),
        Mutation("MUT-014", "step reference", "activity_step_missing", unknown_activity_step),
        Mutation(
            "MUT-015",
            "unsupported provenance",
            "unsupported_without_rationale",
            unsupported_without_reason,
        ),
    ]


def run_suite() -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for mutation in build_mutations():
        report = mutation.run()
        codes = sorted({issue.code for issue in report.issues})
        detected = mutation.expected_code in codes
        rows.append(
            {
                "mutation_id": mutation.mutation_id,
                "error_class": mutation.error_class,
                "expected_code": mutation.expected_code,
                "detected": detected,
                "observed_codes": codes,
            }
        )
    detected_count = sum(bool(row["detected"]) for row in rows)
    return {
        "experiment_id": "validator-mutations-v1",
        "experiment_type": "deterministic_validator_mutation_test",
        "llm_calls": 0,
        "mutation_count": len(rows),
        "detected_count": detected_count,
        "detection_rate": detected_count / len(rows),
        "claim_limit": (
            "Detection applies only to the 15 predefined structural/trace mutation classes."
        ),
        "rows": rows,
    }


def _write_svg(result: dict[str, object]) -> None:
    rate = float(result["detection_rate"])
    detected = int(result["detected_count"])
    total = int(result["mutation_count"])
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="430">
<rect width="1200" height="430" fill="#ffffff"/>
<text x="55" y="58" font-family="Arial" font-size="28" font-weight="700" fill="#111827">Validator mutation suite v1</text>
<text x="55" y="88" font-family="Arial" font-size="16" fill="#4b5563">15 predefined structural and trace error classes; no LLM calls</text>
<rect x="55" y="145" width="1000" height="62" rx="6" fill="#e5e7eb"/>
<rect x="55" y="145" width="{1000 * rate:.1f}" height="62" rx="6" fill="#0f766e"/>
<text x="55" y="253" font-family="Arial" font-size="46" font-weight="700" fill="#0f766e">{detected}/{total} detected ({rate:.0%})</text>
<text x="55" y="302" font-family="Arial" font-size="17" fill="#111827">Covered: IDs, FR atoms, forward/reverse links, endpoint types, dangling links, control flow, guards, partitions and provenance.</text>
<text x="55" y="354" font-family="Arial" font-size="15" fill="#991b1b">Scope limit: this result does not prove semantic correctness or detection of unenumerated error classes.</text>
</svg>"""
    (OUTPUT_DIR / "mutation_detection.svg").write_text(svg, encoding="utf-8")


def main() -> None:
    result = run_suite()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    rows = result["rows"]
    with (OUTPUT_DIR / "results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "mutation_id",
                "error_class",
                "expected_code",
                "detected",
                "observed_codes",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, "observed_codes": ";".join(row["observed_codes"])})
    _write_svg(result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["detection_rate"] == 1.0 else 1)


if __name__ == "__main__":
    main()
