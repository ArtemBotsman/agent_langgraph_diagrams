"""Activity Diagram Agent graph: structured model + deterministic Mermaid render."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from traceable_spec.entities import (
    ActivityDiagram,
    ActivityGenerationArtifact,
    ActivityGenerationResult,
    ActivityGraphState,
    CriticVerdict,
    IssueCategory,
    IssueSeverity,
    PipelineStatus,
    TraceLinkType,
    TraceManifest,
    ValidationIssue,
    ValidationReport,
)
from traceable_spec.llm.parsing import parse_json_model
from traceable_spec.llm.protocol import LLMClient
from traceable_spec.mermaid import render_mermaid
from traceable_spec.prompts.activities import (
    build_activity_critic_messages,
    build_activity_generator_messages,
    build_activity_repair_messages,
)
from traceable_spec.testing.fixtures import (
    sample_activity_diagram,
    sample_activity_trace_links,
    sample_uc_trace_manifest,
)
from traceable_spec.validators import validate_activity_deterministic, validate_repair_limit

NodeFn = Callable[[ActivityGraphState], dict[str, Any]]


@dataclass
class ActivityNodeFns:
    prepare_use_case: NodeFn
    generate_activity_model: NodeFn
    validate_activity_schema: NodeFn
    validate_activity_deterministic: NodeFn
    criticize_activity_model: NodeFn
    decide_activity_result: NodeFn
    repair_activity_model: NodeFn
    render_mermaid: NodeFn
    finalize_activity: NodeFn
    fail_activity_generation: NodeFn


def _prepare_use_case(state: ActivityGraphState) -> dict[str, Any]:
    configured_limit = state.get("max_repair_attempts")
    return {
        "repair_attempt": 0,
        "max_repair_attempts": 2 if configured_limit is None else int(configured_limit),
        "trace_manifest": state.get("trace_manifest") or TraceManifest(links=[]),
        "validation_reports": [],
        "status": PipelineStatus.PARTIAL,
    }


def _generate_activity_model_stub(state: ActivityGraphState) -> dict[str, Any]:
    uc = state["use_case"]
    diagram = sample_activity_diagram()
    if uc.id != "UC-001":
        diagram = diagram.model_copy(
            update={"use_case_id": uc.id, "id": f"AD-{uc.id.replace('-', '')}"}
        )
    existing = state.get("trace_manifest") or sample_uc_trace_manifest()
    merged = TraceManifest(links=[*existing.links, *sample_activity_trace_links()])
    return {
        "activity_diagram": diagram,
        "trace_manifest": merged,
    }


def _merge_unsupported_trace(
    current: TraceManifest,
    generated: TraceManifest,
) -> TraceManifest:
    """Retain base links plus explicit unsupported provenance from an LLM artifact."""

    links = list(current.links)
    existing = {(link.link_type, link.source_id, link.target_id) for link in links}
    for link in generated.links:
        key = (link.link_type, link.source_id, link.target_id)
        if link.link_type == TraceLinkType.UNSUPPORTED and key not in existing:
            links.append(link.model_copy(update={"id": f"TL-{len(links) + 1:03d}"}))
            existing.add(key)
    return TraceManifest(links=links)


def _make_generate_activity_model(client: LLMClient) -> NodeFn:
    def _generate_activity_model(state: ActivityGraphState) -> dict[str, Any]:
        text = client.complete(
            messages=build_activity_generator_messages(
                state["use_case"],
                list(state.get("actors") or []),
            ),
            temperature=0,
            response_format={"type": "json_object"},
        )
        artifact, report = parse_json_model(
            ActivityGenerationArtifact,
            text,
            validator_name="activity_generator_parse",
        )
        reports = list(state.get("validation_reports") or [])
        reports.append(report)
        if artifact is None:
            return {"activity_diagram": None, "validation_reports": reports}
        return {
            "activity_diagram": artifact.activity_diagram,
            "trace_manifest": _merge_unsupported_trace(
                state.get("trace_manifest") or TraceManifest(),
                artifact.trace_manifest,
            ),
            "validation_reports": reports,
        }

    return _generate_activity_model


def _validate_activity_schema(state: ActivityGraphState) -> dict[str, Any]:
    from traceable_spec.entities import IssueCategory, IssueSeverity, ValidationIssue

    diagram = state.get("activity_diagram")
    if diagram is None:
        report = ValidationReport(
            passed=False,
            issues=[
                ValidationIssue(
                    id="VI-001",
                    severity=IssueSeverity.ERROR,
                    category=IssueCategory.SCHEMA,
                    code="missing_activity_diagram",
                    message="activity_diagram is missing",
                )
            ],
            validator_name="activity_schema",
        )
    else:
        ActivityDiagram.model_validate(diagram.model_dump())
        report = ValidationReport(passed=True, issues=[], validator_name="activity_schema")
    reports = list(state.get("validation_reports") or [])
    reports.append(report)
    return {"schema_report": report, "validation_reports": reports}


def _validate_activity_deterministic_node(state: ActivityGraphState) -> dict[str, Any]:
    diagram = state.get("activity_diagram")
    if diagram is None:
        report = ValidationReport(
            passed=False,
            issues=[
                ValidationIssue(
                    id="VI-001",
                    severity=IssueSeverity.ERROR,
                    category=IssueCategory.STRUCTURAL,
                    code="missing_activity_diagram",
                    message="Cannot validate a missing activity diagram",
                )
            ],
            validator_name="activity_deterministic",
        )
    else:
        report = validate_activity_deterministic(diagram, state["use_case"])
    reports = list(state.get("validation_reports") or [])
    reports.append(report)
    return {"deterministic_report": report, "validation_reports": reports}


def _criticize_activity_model_stub(state: ActivityGraphState) -> dict[str, Any]:
    report = ValidationReport(
        passed=True,
        issues=[],
        validator_name="activity_llm_critic_stub",
        details={"stub": True},
    )
    reports = list(state.get("validation_reports") or [])
    reports.append(report)
    return {"critic_report": report, "validation_reports": reports}


def _make_criticize_activity_model(client: LLMClient) -> NodeFn:
    def _criticize_activity_model(state: ActivityGraphState) -> dict[str, Any]:
        diagram = state.get("activity_diagram")
        reports = list(state.get("validation_reports") or [])
        if diagram is None:
            report = ValidationReport(
                passed=False,
                issues=[
                    ValidationIssue(
                        id="VI-001",
                        severity=IssueSeverity.ERROR,
                        category=IssueCategory.SEMANTIC,
                        code="activity_critic_skipped_missing_artifact",
                        message="Activity critic skipped because the diagram is missing",
                    )
                ],
                validator_name="activity_llm_critic",
                details={"decision": "repair"},
            )
            reports.append(report)
            return {"critic_report": report, "validation_reports": reports}
        formal_reports = [
            report
            for report in (state.get("schema_report"), state.get("deterministic_report"))
            if report is not None
        ]
        text = client.complete(
            messages=build_activity_critic_messages(
                state["use_case"],
                diagram,
                formal_reports,
                int(state.get("repair_attempt") or 0),
            ),
            temperature=0,
            response_format={"type": "json_object"},
        )
        verdict, parse_report = parse_json_model(
            CriticVerdict,
            text,
            validator_name="activity_critic_parse",
        )
        reports.append(parse_report)
        if verdict is None:
            report = ValidationReport(
                passed=False,
                issues=list(parse_report.issues),
                validator_name="activity_llm_critic",
                details={"decision": "repair"},
            )
        else:
            report = ValidationReport(
                passed=verdict.decision == "accept",
                issues=list(verdict.issues),
                validator_name="activity_llm_critic",
                details={"decision": verdict.decision, "summary": verdict.summary},
            )
        reports.append(report)
        return {"critic_report": report, "validation_reports": reports}

    return _criticize_activity_model


def _decide_activity_result(state: ActivityGraphState) -> dict[str, Any]:
    empty = ValidationReport(passed=False, issues=[], validator_name="x")
    schema_ok = (state.get("schema_report") or empty).passed
    det_ok = (state.get("deterministic_report") or empty).passed
    critic_ok = (state.get("critic_report") or empty).passed
    attempt = int(state.get("repair_attempt") or 0)
    max_attempts = int(state.get("max_repair_attempts") or 0)
    ok = schema_ok and det_ok and critic_ok
    if ok:
        decision: Literal["finalize", "repair", "fail"] = "finalize"
    elif attempt < max_attempts:
        decision = "repair"
    else:
        decision = "fail"
    limit_report = validate_repair_limit(attempt, max_attempts)
    reports = list(state.get("validation_reports") or [])
    if not limit_report.passed and decision == "repair":
        decision = "fail"
    reports.append(limit_report)
    return {"decision": decision, "validation_reports": reports}


def _route_activity_after_deterministic(
    state: ActivityGraphState,
) -> Literal["criticize_activity_model", "decide_activity_result"]:
    """Skip the paid semantic critic when formal validation already failed."""

    empty = ValidationReport(passed=False, issues=[], validator_name="missing")
    schema_ok = (state.get("schema_report") or empty).passed
    deterministic_ok = (state.get("deterministic_report") or empty).passed
    return (
        "criticize_activity_model" if schema_ok and deterministic_ok else "decide_activity_result"
    )


def _route_activity_decision(
    state: ActivityGraphState,
) -> Literal["render_mermaid", "repair_activity_model", "fail_activity_generation"]:
    decision = state.get("decision") or "fail"
    if decision == "finalize":
        return "render_mermaid"
    if decision == "repair":
        return "repair_activity_model"
    return "fail_activity_generation"


def _repair_activity_model_stub(state: ActivityGraphState) -> dict[str, Any]:
    attempt = int(state.get("repair_attempt") or 0) + 1
    existing = state.get("trace_manifest") or sample_uc_trace_manifest()
    # Drop previous activity links then re-attach sample ones
    kept = [link for link in existing.links if not link.id.startswith("TL-01")]
    merged = TraceManifest(links=[*kept, *sample_activity_trace_links()])
    return {
        "repair_attempt": attempt,
        "activity_diagram": sample_activity_diagram(),
        "trace_manifest": merged,
    }


def _collect_activity_issues(state: ActivityGraphState) -> list[dict[str, Any]]:
    return [
        issue.model_dump(mode="json")
        for report in state.get("validation_reports") or []
        for issue in report.issues
        if issue.blocking
    ]


def _make_repair_activity_model(client: LLMClient) -> NodeFn:
    def _repair_activity_model(state: ActivityGraphState) -> dict[str, Any]:
        attempt = int(state.get("repair_attempt") or 0) + 1
        text = client.complete(
            messages=build_activity_repair_messages(
                state["use_case"],
                state.get("activity_diagram"),
                _collect_activity_issues(state),
                attempt,
            ),
            temperature=0,
            response_format={"type": "json_object"},
        )
        artifact, report = parse_json_model(
            ActivityGenerationArtifact,
            text,
            validator_name="activity_repair_parse",
        )
        reports = list(state.get("validation_reports") or [])
        reports.append(report)
        if artifact is None:
            return {"repair_attempt": attempt, "validation_reports": reports}
        return {
            "repair_attempt": attempt,
            "activity_diagram": artifact.activity_diagram,
            "trace_manifest": _merge_unsupported_trace(
                state.get("trace_manifest") or TraceManifest(),
                artifact.trace_manifest,
            ),
            "validation_reports": reports,
        }

    return _repair_activity_model


def _render_mermaid_node(state: ActivityGraphState) -> dict[str, Any]:
    diagram = state["activity_diagram"]
    assert diagram is not None
    source = render_mermaid(diagram)
    updated = diagram.model_copy(update={"mermaid_source": source})
    return {"activity_diagram": updated, "mermaid_source": source}


def _finalize_activity(state: ActivityGraphState) -> dict[str, Any]:
    return {"status": PipelineStatus.SUCCESS, "failure_reason": None}


def _fail_activity_generation(state: ActivityGraphState) -> dict[str, Any]:
    return {
        "status": PipelineStatus.FAILED,
        "failure_reason": "Activity generation failed after validation/repair limit",
    }


def activity_result_from_state(state: ActivityGraphState) -> ActivityGenerationResult:
    """Build ActivityGenerationResult from graph state (explicit artifact field)."""
    status = state.get("status") or PipelineStatus.FAILED
    return ActivityGenerationResult(
        use_case_id=state["use_case"].id,
        activity_diagram=state.get("activity_diagram"),
        status=status,
        validation_reports=list(state.get("validation_reports") or []),
        repair_attempts_used=int(state.get("repair_attempt") or 0),
        failure_reason=state.get("failure_reason"),
    )


def default_activity_nodes() -> ActivityNodeFns:
    return ActivityNodeFns(
        prepare_use_case=_prepare_use_case,
        generate_activity_model=_generate_activity_model_stub,
        validate_activity_schema=_validate_activity_schema,
        validate_activity_deterministic=_validate_activity_deterministic_node,
        criticize_activity_model=_criticize_activity_model_stub,
        decide_activity_result=_decide_activity_result,
        repair_activity_model=_repair_activity_model_stub,
        render_mermaid=_render_mermaid_node,
        finalize_activity=_finalize_activity,
        fail_activity_generation=_fail_activity_generation,
    )


def activity_nodes_with_llm(client: LLMClient) -> ActivityNodeFns:
    """Wire Activity generator, semantic critic and repair roles to a client."""

    return ActivityNodeFns(
        prepare_use_case=_prepare_use_case,
        generate_activity_model=_make_generate_activity_model(client),
        validate_activity_schema=_validate_activity_schema,
        validate_activity_deterministic=_validate_activity_deterministic_node,
        criticize_activity_model=_make_criticize_activity_model(client),
        decide_activity_result=_decide_activity_result,
        repair_activity_model=_make_repair_activity_model(client),
        render_mermaid=_render_mermaid_node,
        finalize_activity=_finalize_activity,
        fail_activity_generation=_fail_activity_generation,
    )


def build_activity_diagram_graph(nodes: ActivityNodeFns | None = None) -> Any:
    fns = nodes or default_activity_nodes()
    builder: Any = StateGraph(ActivityGraphState)

    builder.add_node("prepare_use_case", fns.prepare_use_case)
    builder.add_node("generate_activity_model", fns.generate_activity_model)
    builder.add_node("validate_activity_schema", fns.validate_activity_schema)
    builder.add_node("validate_activity_deterministic", fns.validate_activity_deterministic)
    builder.add_node("criticize_activity_model", fns.criticize_activity_model)
    builder.add_node("decide_activity_result", fns.decide_activity_result)
    builder.add_node("repair_activity_model", fns.repair_activity_model)
    builder.add_node("render_mermaid", fns.render_mermaid)
    builder.add_node("finalize_activity", fns.finalize_activity)
    builder.add_node("fail_activity_generation", fns.fail_activity_generation)

    builder.add_edge(START, "prepare_use_case")
    builder.add_edge("prepare_use_case", "generate_activity_model")
    builder.add_edge("generate_activity_model", "validate_activity_schema")
    builder.add_edge("validate_activity_schema", "validate_activity_deterministic")
    builder.add_conditional_edges(
        "validate_activity_deterministic",
        _route_activity_after_deterministic,
        {
            "criticize_activity_model": "criticize_activity_model",
            "decide_activity_result": "decide_activity_result",
        },
    )
    builder.add_edge("criticize_activity_model", "decide_activity_result")
    builder.add_conditional_edges(
        "decide_activity_result",
        _route_activity_decision,
        {
            "render_mermaid": "render_mermaid",
            "repair_activity_model": "repair_activity_model",
            "fail_activity_generation": "fail_activity_generation",
        },
    )
    builder.add_edge("repair_activity_model", "validate_activity_schema")
    builder.add_edge("render_mermaid", "finalize_activity")
    builder.add_edge("finalize_activity", END)
    builder.add_edge("fail_activity_generation", END)

    return builder.compile()


def compile_activity_diagram_graph(nodes: ActivityNodeFns | None = None) -> Any:
    return build_activity_diagram_graph(nodes)
