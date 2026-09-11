"""Use Case Agent graph: LLMClient-driven nodes + offline stub fallbacks.

Generator / critic / repair call LLMClient (scripted fake in tests; real adapter later).
Deterministic validators remain separate Python checks.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from traceable_spec.entities import (
    CriticVerdict,
    IssueCategory,
    IssueSeverity,
    PipelineStatus,
    TraceManifest,
    UseCaseGenerationArtifact,
    UseCaseGraphOutput,
    UseCaseGraphState,
    UseCaseSet,
    ValidationIssue,
    ValidationReport,
    ensure_requirement_atoms,
)
from traceable_spec.llm.parsing import parse_json_model
from traceable_spec.llm.protocol import LLMClient
from traceable_spec.prompts.use_cases import (
    build_use_case_critic_messages,
    build_use_case_generator_messages,
    build_use_case_repair_messages,
)
from traceable_spec.rendering.use_case_text import render_use_case_text
from traceable_spec.testing.fixtures import sample_uc_trace_manifest, sample_use_case_set
from traceable_spec.traceability import inherit_step_sources, materialize_trace_manifest
from traceable_spec.validators import (
    validate_repair_limit,
    validate_use_case_set_deterministic,
)

NodeFn = Callable[[UseCaseGraphState], dict[str, Any]]


@dataclass
class UseCaseNodeFns:
    prepare_requirements: NodeFn
    generate_use_case_set: NodeFn
    validate_uc_schema: NodeFn
    validate_uc_deterministic: NodeFn
    criticize_use_case_set: NodeFn
    decide_uc_result: NodeFn
    repair_use_case_set: NodeFn
    finalize_use_case_set: NodeFn
    fail_use_case_generation: NodeFn


def _prepare_requirements(state: UseCaseGraphState) -> dict[str, Any]:
    request = ensure_requirement_atoms(state["request"])
    return {
        "request": request,
        "normalized_frs": list(request.functional_requirements),
        "normalized_nfrs": list(request.non_functional_requirements),
        "max_repair_attempts": request.max_repair_attempts,
        "repair_attempt": 0,
        "trace_manifest": TraceManifest(links=[]),
        "validation_reports": [],
        "status": PipelineStatus.PARTIAL,
    }


def _enrich_use_case_texts(use_case_set: UseCaseSet) -> UseCaseSet:
    for uc in use_case_set.use_cases:
        if not uc.human_readable_text:
            uc.human_readable_text = render_use_case_text(uc)
    return use_case_set


def _collect_issue_dicts(state: UseCaseGraphState) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for report in state.get("validation_reports") or []:
        for issue in report.issues:
            if issue.blocking:
                issues.append(issue.model_dump(mode="json"))
    return issues


def _generate_use_case_set_stub(state: UseCaseGraphState) -> dict[str, Any]:
    """Legacy stub: fixed sample (no LLMClient). Prefer use_case_nodes_with_llm."""
    use_case_set = inherit_step_sources(_enrich_use_case_texts(sample_use_case_set()))
    return {
        "use_case_set": use_case_set,
        "trace_manifest": materialize_trace_manifest(
            state["request"],
            use_case_set,
            existing=sample_uc_trace_manifest(),
        ),
    }


def _make_generate_use_case_set(client: LLMClient) -> NodeFn:
    def _generate_use_case_set(state: UseCaseGraphState) -> dict[str, Any]:
        messages = build_use_case_generator_messages(state["request"])
        text = client.complete(
            messages=messages,
            temperature=0,
            response_format={"type": "json_object"},
        )
        artifact, parse_report = parse_json_model(
            UseCaseGenerationArtifact,
            text,
            validator_name="uc_generator_parse",
        )
        reports = list(state.get("validation_reports") or [])
        reports.append(parse_report)
        if artifact is None:
            return {
                "use_case_set": None,
                "trace_manifest": state.get("trace_manifest") or TraceManifest(),
                "validation_reports": reports,
            }
        use_case_set = inherit_step_sources(_enrich_use_case_texts(artifact.use_case_set))
        return {
            "use_case_set": use_case_set,
            "trace_manifest": materialize_trace_manifest(
                state["request"],
                use_case_set,
                existing=artifact.trace_manifest,
            ),
            "validation_reports": reports,
        }

    return _generate_use_case_set


def _validate_uc_schema(state: UseCaseGraphState) -> dict[str, Any]:
    use_case_set = state.get("use_case_set")
    if use_case_set is None:
        report = ValidationReport(
            passed=False,
            issues=[
                ValidationIssue(
                    id="VI-001",
                    severity=IssueSeverity.ERROR,
                    category=IssueCategory.SCHEMA,
                    code="missing_use_case_set",
                    message="use_case_set is missing",
                )
            ],
            validator_name="uc_schema",
        )
    else:
        UseCaseSet.model_validate(use_case_set.model_dump())
        report = ValidationReport(passed=True, issues=[], validator_name="uc_schema")
    reports = list(state.get("validation_reports") or [])
    reports.append(report)
    return {"schema_report": report, "validation_reports": reports}


def _validate_uc_deterministic(state: UseCaseGraphState) -> dict[str, Any]:
    use_case_set = state.get("use_case_set")
    reports = list(state.get("validation_reports") or [])
    if use_case_set is None:
        report = ValidationReport(
            passed=False,
            issues=[
                ValidationIssue(
                    id="VI-001",
                    severity=IssueSeverity.ERROR,
                    category=IssueCategory.STRUCTURAL,
                    code="missing_use_case_set",
                    message="Cannot run deterministic UC validators without use_case_set",
                )
            ],
            validator_name="uc_deterministic_aggregate",
        )
        reports.append(report)
        return {"deterministic_report": report, "validation_reports": reports}

    report = validate_use_case_set_deterministic(
        use_case_set,
        state["request"],
        state.get("trace_manifest") or TraceManifest(),
    )
    reports.append(report)
    return {"deterministic_report": report, "validation_reports": reports}


def _criticize_use_case_set_stub(state: UseCaseGraphState) -> dict[str, Any]:
    """Legacy stub critic: always accept."""
    report = ValidationReport(
        passed=True,
        issues=[],
        validator_name="uc_llm_critic_stub",
        details={"stub": True},
    )
    reports = list(state.get("validation_reports") or [])
    reports.append(report)
    return {"critic_report": report, "validation_reports": reports}


def _make_criticize_use_case_set(client: LLMClient) -> NodeFn:
    def _criticize_use_case_set(state: UseCaseGraphState) -> dict[str, Any]:
        reports = list(state.get("validation_reports") or [])
        use_case_set = state.get("use_case_set")
        if use_case_set is None:
            report = ValidationReport(
                passed=False,
                issues=[
                    ValidationIssue(
                        id="VI-001",
                        severity=IssueSeverity.ERROR,
                        category=IssueCategory.SEMANTIC,
                        code="critic_skipped_missing_artifact",
                        message="Critic skipped: use_case_set missing",
                    )
                ],
                validator_name="uc_llm_critic",
                details={"decision": "repair"},
            )
            reports.append(report)
            return {"critic_report": report, "validation_reports": reports}

        det = state.get("deterministic_report")
        schema = state.get("schema_report")
        det_reports = [r for r in (schema, det) if r is not None]
        messages = build_use_case_critic_messages(
            state["request"],
            use_case_set,
            det_reports,
            int(state.get("repair_attempt") or 0),
        )
        text = client.complete(
            messages=messages,
            temperature=0,
            response_format={"type": "json_object"},
        )
        verdict, parse_report = parse_json_model(
            CriticVerdict,
            text,
            validator_name="uc_critic_parse",
        )
        reports.append(parse_report)
        if verdict is None:
            report = ValidationReport(
                passed=False,
                issues=list(parse_report.issues)
                or [
                    ValidationIssue(
                        id="VI-001",
                        severity=IssueSeverity.ERROR,
                        category=IssueCategory.SEMANTIC,
                        code="critic_parse_failed",
                        message="Critic response could not be parsed",
                    )
                ],
                validator_name="uc_llm_critic",
                details={"decision": "repair"},
            )
        else:
            report = ValidationReport(
                passed=verdict.decision == "accept",
                issues=list(verdict.issues),
                validator_name="uc_llm_critic",
                details={
                    "decision": verdict.decision,
                    "summary": verdict.summary,
                    "critic_not_deterministic_validator": True,
                },
            )
        reports.append(report)
        return {"critic_report": report, "validation_reports": reports}

    return _criticize_use_case_set


def _decide_uc_result(state: UseCaseGraphState) -> dict[str, Any]:
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


def _route_uc_after_deterministic(
    state: UseCaseGraphState,
) -> Literal["criticize_use_case_set", "decide_uc_result"]:
    """Skip semantic criticism when a known formal error already requires repair."""

    empty = ValidationReport(passed=False, issues=[], validator_name="missing")
    schema_ok = (state.get("schema_report") or empty).passed
    deterministic_ok = (state.get("deterministic_report") or empty).passed
    return "criticize_use_case_set" if schema_ok and deterministic_ok else "decide_uc_result"


def _route_uc_decision(
    state: UseCaseGraphState,
) -> Literal["finalize_use_case_set", "repair_use_case_set", "fail_use_case_generation"]:
    decision = state.get("decision") or "fail"
    if decision == "finalize":
        return "finalize_use_case_set"
    if decision == "repair":
        return "repair_use_case_set"
    return "fail_use_case_generation"


def _repair_use_case_set_stub(state: UseCaseGraphState) -> dict[str, Any]:
    """Legacy stub repair: increments counter and reuses sample set."""
    attempt = int(state.get("repair_attempt") or 0) + 1
    use_case_set = inherit_step_sources(sample_use_case_set())
    return {
        "repair_attempt": attempt,
        "use_case_set": use_case_set,
        "trace_manifest": materialize_trace_manifest(
            state["request"],
            use_case_set,
            existing=sample_uc_trace_manifest(),
        ),
    }


def _make_repair_use_case_set(client: LLMClient) -> NodeFn:
    def _repair_use_case_set(state: UseCaseGraphState) -> dict[str, Any]:
        attempt = int(state.get("repair_attempt") or 0) + 1
        messages = build_use_case_repair_messages(
            state["request"],
            state.get("use_case_set"),
            _collect_issue_dicts(state),
            attempt,
        )
        text = client.complete(
            messages=messages,
            temperature=0,
            response_format={"type": "json_object"},
        )
        artifact, parse_report = parse_json_model(
            UseCaseGenerationArtifact,
            text,
            validator_name="uc_repair_parse",
        )
        reports = list(state.get("validation_reports") or [])
        reports.append(parse_report)
        if artifact is None:
            return {
                "repair_attempt": attempt,
                "use_case_set": state.get("use_case_set"),
                "trace_manifest": state.get("trace_manifest") or TraceManifest(),
                "validation_reports": reports,
            }
        use_case_set = inherit_step_sources(_enrich_use_case_texts(artifact.use_case_set))
        return {
            "repair_attempt": attempt,
            "use_case_set": use_case_set,
            "trace_manifest": materialize_trace_manifest(
                state["request"],
                use_case_set,
                existing=artifact.trace_manifest,
            ),
            "validation_reports": reports,
        }

    return _repair_use_case_set


def _finalize_use_case_set(state: UseCaseGraphState) -> dict[str, Any]:
    use_case_set = state.get("use_case_set")
    if use_case_set is not None:
        _enrich_use_case_texts(use_case_set)
    return {
        "status": PipelineStatus.SUCCESS,
        "failure_reason": None,
        "use_case_set": use_case_set,
    }


def _fail_use_case_generation(state: UseCaseGraphState) -> dict[str, Any]:
    attempt = int(state.get("repair_attempt") or 0)
    max_attempts = int(state.get("max_repair_attempts") or 0)
    return {
        "status": PipelineStatus.FAILED,
        "failure_reason": (
            "Use Case generation failed after validation/repair limit "
            f"(repair_attempt={attempt}, max_repair_attempts={max_attempts})"
        ),
    }


def default_use_case_nodes() -> UseCaseNodeFns:
    """Stub nodes for offline scaffold / root pipeline (no LLMClient)."""
    return UseCaseNodeFns(
        prepare_requirements=_prepare_requirements,
        generate_use_case_set=_generate_use_case_set_stub,
        validate_uc_schema=_validate_uc_schema,
        validate_uc_deterministic=_validate_uc_deterministic,
        criticize_use_case_set=_criticize_use_case_set_stub,
        decide_uc_result=_decide_uc_result,
        repair_use_case_set=_repair_use_case_set_stub,
        finalize_use_case_set=_finalize_use_case_set,
        fail_use_case_generation=_fail_use_case_generation,
    )


def use_case_nodes_with_llm(client: LLMClient) -> UseCaseNodeFns:
    """Wire generator/critic/repair to an LLMClient (scripted fake or real adapter)."""
    return UseCaseNodeFns(
        prepare_requirements=_prepare_requirements,
        generate_use_case_set=_make_generate_use_case_set(client),
        validate_uc_schema=_validate_uc_schema,
        validate_uc_deterministic=_validate_uc_deterministic,
        criticize_use_case_set=_make_criticize_use_case_set(client),
        decide_uc_result=_decide_uc_result,
        repair_use_case_set=_make_repair_use_case_set(client),
        finalize_use_case_set=_finalize_use_case_set,
        fail_use_case_generation=_fail_use_case_generation,
    )


def build_use_cases_graph(nodes: UseCaseNodeFns | None = None) -> Any:
    """Build and compile the Use Cases StateGraph."""
    fns = nodes or default_use_case_nodes()
    builder: Any = StateGraph(UseCaseGraphState)

    builder.add_node("prepare_requirements", fns.prepare_requirements)
    builder.add_node("generate_use_case_set", fns.generate_use_case_set)
    builder.add_node("validate_uc_schema", fns.validate_uc_schema)
    builder.add_node("validate_uc_deterministic", fns.validate_uc_deterministic)
    builder.add_node("criticize_use_case_set", fns.criticize_use_case_set)
    builder.add_node("decide_uc_result", fns.decide_uc_result)
    builder.add_node("repair_use_case_set", fns.repair_use_case_set)
    builder.add_node("finalize_use_case_set", fns.finalize_use_case_set)
    builder.add_node("fail_use_case_generation", fns.fail_use_case_generation)

    builder.add_edge(START, "prepare_requirements")
    builder.add_edge("prepare_requirements", "generate_use_case_set")
    builder.add_edge("generate_use_case_set", "validate_uc_schema")
    builder.add_edge("validate_uc_schema", "validate_uc_deterministic")
    builder.add_conditional_edges(
        "validate_uc_deterministic",
        _route_uc_after_deterministic,
        {
            "criticize_use_case_set": "criticize_use_case_set",
            "decide_uc_result": "decide_uc_result",
        },
    )
    builder.add_edge("criticize_use_case_set", "decide_uc_result")
    builder.add_conditional_edges(
        "decide_uc_result",
        _route_uc_decision,
        {
            "finalize_use_case_set": "finalize_use_case_set",
            "repair_use_case_set": "repair_use_case_set",
            "fail_use_case_generation": "fail_use_case_generation",
        },
    )
    builder.add_edge("repair_use_case_set", "validate_uc_schema")
    builder.add_edge("finalize_use_case_set", END)
    builder.add_edge("fail_use_case_generation", END)

    return builder.compile()


def compile_use_cases_graph(nodes: UseCaseNodeFns | None = None) -> Any:
    return build_use_cases_graph(nodes)


def use_case_graph_output_from_state(state: dict[str, Any]) -> UseCaseGraphOutput:
    """Map graph invoke result to the output contract."""
    return UseCaseGraphOutput(
        use_case_set=state.get("use_case_set"),
        trace_manifest=state.get("trace_manifest") or TraceManifest(),
        validation_reports=list(state.get("validation_reports") or []),
        status=state.get("status") or PipelineStatus.FAILED,
        repair_attempts_used=int(state.get("repair_attempt") or 0),
        failure_reason=state.get("failure_reason"),
    )
