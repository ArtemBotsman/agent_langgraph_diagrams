"""Root pipeline graph: SpecificationReq -> normalization -> GeneratedSpecification.

Flow:
  normalize requirements
  -> Use Cases subgraph
  -> activity model per UC (sequential in scaffold; parallelization later)
  -> end-to-end trace validation
  -> deterministic UC text + Mermaid already produced in subgraphs
  -> evaluator
  -> GeneratedSpecification
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langgraph.graph import END, START, StateGraph

from traceable_spec.activity_diagram_graph import (
    ActivityNodeFns,
    activity_result_from_state,
    build_activity_diagram_graph,
    default_activity_nodes,
)
from traceable_spec.entities import (
    GeneratedSpecification,
    PipelineGraphState,
    PipelineStatus,
    SpecificationRequest,
    TraceManifest,
    normalize_specification_req,
)
from traceable_spec.evaluation.evaluator import evaluate_specification
from traceable_spec.use_cases_graph import (
    UseCaseNodeFns,
    build_use_cases_graph,
    default_use_case_nodes,
)
from traceable_spec.validators import validate_end_to_end_trace

NodeFn = Callable[[PipelineGraphState], dict[str, Any]]


@dataclass
class PipelineDeps:
    use_case_nodes: UseCaseNodeFns
    activity_nodes: ActivityNodeFns


def default_pipeline_deps() -> PipelineDeps:
    return PipelineDeps(
        use_case_nodes=default_use_case_nodes(),
        activity_nodes=default_activity_nodes(),
    )


def _normalize_requirements(state: PipelineGraphState) -> dict[str, Any]:
    request = normalize_specification_req(state["request"])
    return {
        "request": request,
        "normalized_frs": list(request.functional_requirements),
        "normalized_nfrs": list(request.non_functional_requirements),
        "max_repair_attempts": request.max_repair_attempts,
        "trace_manifest": TraceManifest(links=[]),
        "validation_reports": [],
        "activity_results": [],
        "status": PipelineStatus.PARTIAL,
    }


def _run_use_cases_factory(deps: PipelineDeps) -> NodeFn:
    compiled = build_use_cases_graph(deps.use_case_nodes)

    def _run_use_cases(state: PipelineGraphState) -> dict[str, Any]:
        request = state["request"]
        if not isinstance(request, SpecificationRequest):
            raise TypeError("request must be normalized before the Use Case stage")
        result = compiled.invoke(
            {
                "request": request,
            }
        )
        return {
            "use_case_set": result.get("use_case_set"),
            "trace_manifest": result.get("trace_manifest") or TraceManifest(),
            "validation_reports": list(state.get("validation_reports") or [])
            + list(result.get("validation_reports") or []),
            "status": result.get("status") or PipelineStatus.FAILED,
            "failure_reason": result.get("failure_reason"),
        }

    return _run_use_cases


def _run_activities_factory(deps: PipelineDeps) -> NodeFn:
    compiled = build_activity_diagram_graph(deps.activity_nodes)

    def _run_activities(state: PipelineGraphState) -> dict[str, Any]:
        request = state["request"]
        if not isinstance(request, SpecificationRequest):
            raise TypeError("request must be normalized before the activity stage")
        use_case_set = state.get("use_case_set")
        if use_case_set is None or state.get("status") == PipelineStatus.FAILED:
            return {
                "activity_results": [],
                "status": PipelineStatus.FAILED,
                "failure_reason": state.get("failure_reason")
                or "Skipping activity generation: Use Case stage failed",
            }

        results = []
        reports = list(state.get("validation_reports") or [])
        merged_links = list((state.get("trace_manifest") or TraceManifest()).links)

        # Sequential now; parallel map-reduce over UCs is a later increment.
        for use_case in use_case_set.use_cases:
            out = compiled.invoke(
                {
                    "use_case": use_case,
                    "actors": use_case_set.actors,
                    "max_repair_attempts": state.get("max_repair_attempts")
                    or request.max_repair_attempts,
                    "trace_manifest": TraceManifest(links=list(merged_links)),
                }
            )
            activity_result = activity_result_from_state(out)
            results.append(activity_result)
            reports.extend(activity_result.validation_reports)
            if out.get("trace_manifest") is not None:
                merged_links = list(out["trace_manifest"].links)

        any_failed = any(item.status == PipelineStatus.FAILED for item in results)
        status = PipelineStatus.FAILED if any_failed else PipelineStatus.SUCCESS
        return {
            "activity_results": results,
            "trace_manifest": TraceManifest(links=merged_links),
            "validation_reports": reports,
            "status": status,
            "failure_reason": "One or more activity diagrams failed" if any_failed else None,
        }

    return _run_activities


def _validate_e2e_trace(state: PipelineGraphState) -> dict[str, Any]:
    request = state["request"]
    if not isinstance(request, SpecificationRequest):
        raise TypeError("request must be normalized before trace validation")
    spec = GeneratedSpecification(
        request=request,
        use_case_set=state.get("use_case_set"),
        activity_results=list(state.get("activity_results") or []),
        trace_manifest=state.get("trace_manifest") or TraceManifest(),
        validation_reports=list(state.get("validation_reports") or []),
        status=state.get("status") or PipelineStatus.FAILED,
        failure_reason=state.get("failure_reason"),
    )
    report = validate_end_to_end_trace(spec)
    reports = list(state.get("validation_reports") or [])
    reports.append(report)
    status = state.get("status") or PipelineStatus.FAILED
    if not report.passed:
        status = PipelineStatus.FAILED
    return {"validation_reports": reports, "status": status}


def _run_evaluator(state: PipelineGraphState) -> dict[str, Any]:
    request = state["request"]
    if not isinstance(request, SpecificationRequest):
        raise TypeError("request must be normalized before evaluation")
    spec = GeneratedSpecification(
        request=request,
        use_case_set=state.get("use_case_set"),
        activity_results=list(state.get("activity_results") or []),
        trace_manifest=state.get("trace_manifest") or TraceManifest(),
        validation_reports=list(state.get("validation_reports") or []),
        status=state.get("status") or PipelineStatus.FAILED,
        failure_reason=state.get("failure_reason"),
    )
    evaluation = evaluate_specification(spec)
    spec = spec.model_copy(update={"evaluation_report": evaluation})
    return {"evaluation_report": evaluation, "specification": spec}


def _finalize_pipeline(state: PipelineGraphState) -> dict[str, Any]:
    request = state["request"]
    if not isinstance(request, SpecificationRequest):
        raise TypeError("request must be normalized before finalization")
    spec = state.get("specification")
    if spec is None:
        spec = GeneratedSpecification(
            request=request,
            use_case_set=state.get("use_case_set"),
            activity_results=list(state.get("activity_results") or []),
            trace_manifest=state.get("trace_manifest") or TraceManifest(),
            validation_reports=list(state.get("validation_reports") or []),
            evaluation_report=state.get("evaluation_report"),
            status=state.get("status") or PipelineStatus.FAILED,
            failure_reason=state.get("failure_reason"),
        )
    else:
        spec = spec.model_copy(
            update={
                "status": state.get("status") or spec.status,
                "failure_reason": state.get("failure_reason"),
            }
        )
    return {"specification": spec}


def build_pipeline_graph(deps: PipelineDeps | None = None) -> Any:
    deps = deps or default_pipeline_deps()
    builder: StateGraph = StateGraph(PipelineGraphState)

    builder.add_node("normalize_requirements", _normalize_requirements)
    builder.add_node("run_use_cases", _run_use_cases_factory(deps))
    builder.add_node("run_activities", _run_activities_factory(deps))
    builder.add_node("validate_e2e_trace", _validate_e2e_trace)
    builder.add_node("run_evaluator", _run_evaluator)
    builder.add_node("finalize_pipeline", _finalize_pipeline)

    builder.add_edge(START, "normalize_requirements")
    builder.add_edge("normalize_requirements", "run_use_cases")
    builder.add_edge("run_use_cases", "run_activities")
    builder.add_edge("run_activities", "validate_e2e_trace")
    builder.add_edge("validate_e2e_trace", "run_evaluator")
    builder.add_edge("run_evaluator", "finalize_pipeline")
    builder.add_edge("finalize_pipeline", END)

    return builder.compile()


def compile_pipeline(deps: PipelineDeps | None = None) -> Any:
    return build_pipeline_graph(deps)
