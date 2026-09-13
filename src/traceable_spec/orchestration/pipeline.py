"""Root orchestrator: SpecificationReq -> normalization -> GeneratedSpecification.

Flow:
  normalize requirements
  -> Use Cases subgraph
  -> one checkpointable Activity subgraph invocation per UC
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

from traceable_spec.agents.activity.graph import (
    ActivityNodeFns,
    activity_nodes_with_llm,
    activity_result_from_state,
    build_activity_diagram_graph,
    default_activity_nodes,
)
from traceable_spec.agents.use_case.graph import (
    UseCaseNodeFns,
    build_use_cases_graph,
    default_use_case_nodes,
    use_case_nodes_with_llm,
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
from traceable_spec.llm.protocol import LLMClient
from traceable_spec.traceability import materialize_trace_manifest
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


def live_pipeline_deps(client: LLMClient) -> PipelineDeps:
    """Use the same provider-neutral client for both specialized agents."""

    return PipelineDeps(
        use_case_nodes=use_case_nodes_with_llm(client),
        activity_nodes=activity_nodes_with_llm(client),
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
        "next_activity_index": 0,
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
            "uc_repair_attempts_used": int(result.get("repair_attempt") or 0),
        }

    return _run_use_cases


def _run_next_activity_factory(deps: PipelineDeps) -> NodeFn:
    """Run exactly one Activity subgraph so LangGraph can checkpoint progress."""

    compiled = build_activity_diagram_graph(deps.activity_nodes)

    def _run_next_activity(state: PipelineGraphState) -> dict[str, Any]:
        request = state["request"]
        if not isinstance(request, SpecificationRequest):
            raise TypeError("request must be normalized before the activity stage")
        use_case_set = state.get("use_case_set")
        if use_case_set is None or state.get("status") == PipelineStatus.FAILED:
            return {
                "activity_results": list(state.get("activity_results") or []),
                "status": PipelineStatus.FAILED,
                "failure_reason": state.get("failure_reason")
                or "Skipping activity generation: Use Case stage failed",
            }

        index = int(state.get("next_activity_index") or 0)
        if index >= len(use_case_set.use_cases):
            return {"next_activity_index": index}

        results = list(state.get("activity_results") or [])
        reports = list(state.get("validation_reports") or [])
        merged_links = list((state.get("trace_manifest") or TraceManifest()).links)
        use_case = use_case_set.use_cases[index]
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

        diagrams = [item.activity_diagram for item in results if item.activity_diagram is not None]
        merged_manifest = materialize_trace_manifest(
            request,
            use_case_set,
            diagrams,
            existing=TraceManifest(links=merged_links),
        )
        any_failed = any(item.status == PipelineStatus.FAILED for item in results)
        status = PipelineStatus.FAILED if any_failed else PipelineStatus.SUCCESS
        return {
            "activity_results": results,
            "next_activity_index": index + 1,
            "trace_manifest": merged_manifest,
            "validation_reports": reports,
            "status": status,
            "failure_reason": "One or more activity diagrams failed" if any_failed else None,
        }

    return _run_next_activity


def _route_after_use_cases(
    state: PipelineGraphState,
) -> str:
    use_case_set = state.get("use_case_set")
    if state.get("status") == PipelineStatus.FAILED:
        return "validate_e2e_trace"
    if use_case_set is None or not use_case_set.use_cases:
        return "validate_e2e_trace"
    return "run_next_activity"


def _route_after_activity(
    state: PipelineGraphState,
) -> str:
    if state.get("status") == PipelineStatus.FAILED:
        return "validate_e2e_trace"
    use_case_set = state.get("use_case_set")
    if use_case_set is None:
        return "validate_e2e_trace"
    next_index = int(state.get("next_activity_index") or 0)
    if next_index < len(use_case_set.use_cases):
        return "run_next_activity"
    return "validate_e2e_trace"


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
        uc_repair_attempts_used=int(state.get("uc_repair_attempts_used") or 0),
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
        uc_repair_attempts_used=int(state.get("uc_repair_attempts_used") or 0),
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
            uc_repair_attempts_used=int(state.get("uc_repair_attempts_used") or 0),
        )
    else:
        spec = spec.model_copy(
            update={
                "status": state.get("status") or spec.status,
                "failure_reason": state.get("failure_reason"),
            }
        )
    return {"specification": spec}


def build_pipeline_graph(
    deps: PipelineDeps | None = None,
    *,
    checkpointer: Any | None = None,
) -> Any:
    deps = deps or default_pipeline_deps()
    builder: Any = StateGraph(PipelineGraphState)

    builder.add_node("normalize_requirements", _normalize_requirements)
    builder.add_node("run_use_cases", _run_use_cases_factory(deps))
    builder.add_node("run_next_activity", _run_next_activity_factory(deps))
    builder.add_node("validate_e2e_trace", _validate_e2e_trace)
    builder.add_node("run_evaluator", _run_evaluator)
    builder.add_node("finalize_pipeline", _finalize_pipeline)

    builder.add_edge(START, "normalize_requirements")
    builder.add_edge("normalize_requirements", "run_use_cases")
    builder.add_conditional_edges(
        "run_use_cases",
        _route_after_use_cases,
        {
            "run_next_activity": "run_next_activity",
            "validate_e2e_trace": "validate_e2e_trace",
        },
    )
    builder.add_conditional_edges(
        "run_next_activity",
        _route_after_activity,
        {
            "run_next_activity": "run_next_activity",
            "validate_e2e_trace": "validate_e2e_trace",
        },
    )
    builder.add_edge("validate_e2e_trace", "run_evaluator")
    builder.add_edge("run_evaluator", "finalize_pipeline")
    builder.add_edge("finalize_pipeline", END)

    return builder.compile(checkpointer=checkpointer)


def compile_pipeline(
    deps: PipelineDeps | None = None,
    *,
    checkpointer: Any | None = None,
) -> Any:
    return build_pipeline_graph(deps, checkpointer=checkpointer)


def compile_live_pipeline(
    client: LLMClient,
    *,
    checkpointer: Any | None = None,
) -> Any:
    """Compile the production path with live UC and Activity agent roles."""

    return build_pipeline_graph(live_pipeline_deps(client), checkpointer=checkpointer)
