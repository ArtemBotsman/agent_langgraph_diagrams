"""Direct baseline methods that consume the same SpecificationReq input."""

from __future__ import annotations

from traceable_spec.entities import (
    ActivityDiagram,
    ActivityEdge,
    ActivityGenerationResult,
    ActivityNode,
    ActivityNodeKind,
    ActivityPartition,
    Actor,
    GeneratedSpecification,
    IssueCategory,
    IssueSeverity,
    OneShotGenerationArtifact,
    PipelineStatus,
    Postcondition,
    RequirementCoverageStatus,
    Scenario,
    ScenarioKind,
    ScenarioStep,
    SpecificationInput,
    SystemStory,
    UseCase,
    UseCaseSet,
    UserStory,
    ValidationIssue,
    ValidationReport,
    normalize_specification_req,
)
from traceable_spec.evaluation.evaluator import evaluate_specification
from traceable_spec.llm.parsing import parse_json_model
from traceable_spec.llm.protocol import LLMClient
from traceable_spec.mermaid import render_mermaid
from traceable_spec.prompts.one_shot import build_one_shot_messages
from traceable_spec.rendering.use_case_text import render_use_case_text
from traceable_spec.traceability import inherit_step_sources, materialize_trace_manifest
from traceable_spec.validators import (
    validate_activity_deterministic,
    validate_end_to_end_trace,
)


def run_rule_based_baseline(value: SpecificationInput) -> GeneratedSpecification:
    """B0: deterministic linear projection, intentionally without semantic reasoning.

    The method is reproducible and accepts the exact same input as the full
    pipeline. Its deliberate limitation is that it groups all FRs into one UC
    and cannot infer actor/goal boundaries or branching semantics.
    """

    request = normalize_specification_req(value)
    actor = Actor(
        id="ACT-001",
        name="User",
        description="Generic actor used by the rule-based baseline",
        is_primary=True,
    )
    steps = [
        ScenarioStep(
            id=f"STEP-UC001-{index:03d}",
            order=index,
            actor_id=actor.id,
            action=requirement.text,
            expected_result="Requirement is completed",
            source_fr_ids=[requirement.id],
        )
        for index, requirement in enumerate(request.functional_requirements, start=1)
    ]
    use_case = UseCase(
        id="UC-001",
        name=request.project_goal,
        goal=request.project_goal,
        primary_actor_id=actor.id,
        trigger="User starts the requested process",
        success_postconditions=[
            Postcondition(
                id="POST-UC001-001",
                text="All listed functional requirements have been processed",
                outcome="success",
            )
        ],
        main_success_scenario=Scenario(
            id="SCN-UC001-MAIN-001",
            kind=ScenarioKind.MAIN,
            name="Requirements in input order",
            steps=steps,
        ),
        user_stories=[
            UserStory(
                id="US-001",
                role=actor.name,
                capability=request.project_goal,
                benefit="the project goal is achieved",
                use_case_id="UC-001",
            )
        ],
        system_stories=[
            SystemStory(
                id="SS-001",
                system_action="Process functional requirements in input order",
                responsibility="Provide a deterministic comparison artifact",
                use_case_id="UC-001",
            )
        ],
        source_fr_ids=[item.id for item in request.functional_requirements],
        source_nfr_ids=[item.id for item in request.non_functional_requirements],
    )
    use_case.human_readable_text = render_use_case_text(use_case)
    use_case_set = UseCaseSet(
        actors=[actor],
        use_cases=[use_case],
        fr_coverage={
            item.id: RequirementCoverageStatus.COVERED for item in request.functional_requirements
        },
    )

    partition = ActivityPartition(
        id="PART-UC001-001",
        name=actor.name,
        actor_id=actor.id,
    )
    nodes = [
        ActivityNode(
            id="ADN-UC001-001",
            kind=ActivityNodeKind.INITIAL,
            name="start",
            partition_id=partition.id,
        )
    ]
    for index, step in enumerate(steps, start=2):
        nodes.append(
            ActivityNode(
                id=f"ADN-UC001-{index:03d}",
                kind=ActivityNodeKind.ACTION,
                name=step.action,
                partition_id=partition.id,
                related_step_ids=[step.id],
            )
        )
    final_index = len(nodes) + 1
    nodes.append(
        ActivityNode(
            id=f"ADN-UC001-{final_index:03d}",
            kind=ActivityNodeKind.FINAL,
            name="end",
            partition_id=partition.id,
        )
    )
    edges: list[ActivityEdge] = []
    for index, (source, target) in enumerate(zip(nodes, nodes[1:], strict=False), start=1):
        if target.kind == ActivityNodeKind.ACTION:
            related = list(target.related_step_ids)
        else:
            related = list(nodes[-2].related_step_ids)
        edges.append(
            ActivityEdge(
                id=f"ADE-UC001-{index:03d}",
                source_node_id=source.id,
                target_node_id=target.id,
                related_step_ids=related,
            )
        )
    diagram = ActivityDiagram(
        id="AD-UC001",
        use_case_id="UC-001",
        name=f"{request.project_name}: rule-based activity",
        partitions=[partition],
        nodes=nodes,
        edges=edges,
    )
    diagram = diagram.model_copy(update={"mermaid_source": render_mermaid(diagram)})
    activity_report = validate_activity_deterministic(diagram, use_case)
    activity_result = ActivityGenerationResult(
        use_case_id=use_case.id,
        activity_diagram=diagram,
        status=PipelineStatus.SUCCESS if activity_report.passed else PipelineStatus.FAILED,
        validation_reports=[activity_report],
    )
    trace = materialize_trace_manifest(request, use_case_set, [diagram])
    provisional = GeneratedSpecification(
        request=request,
        use_case_set=use_case_set,
        activity_results=[activity_result],
        trace_manifest=trace,
        validation_reports=[activity_report],
        status=PipelineStatus.SUCCESS,
    )
    e2e_report = validate_end_to_end_trace(provisional)
    status = PipelineStatus.SUCCESS if e2e_report.passed else PipelineStatus.FAILED
    result = provisional.model_copy(
        update={"validation_reports": [activity_report, e2e_report], "status": status}
    )
    return result.model_copy(update={"evaluation_report": evaluate_specification(result)})


def run_one_shot_baseline(
    value: SpecificationInput,
    client: LLMClient,
) -> GeneratedSpecification:
    """B1: one LLM call, no critic and no repair, with the same typed artifacts."""

    request = normalize_specification_req(value)
    text = client.complete(
        messages=build_one_shot_messages(request),
        temperature=0,
        response_format={"type": "json_object"},
    )
    artifact, parse_report = parse_json_model(
        OneShotGenerationArtifact,
        text,
        validator_name="one_shot_parse",
    )
    if artifact is None:
        result = GeneratedSpecification(
            request=request,
            validation_reports=[parse_report],
            status=PipelineStatus.FAILED,
            failure_reason="One-shot response did not satisfy the output contract",
        )
        return result.model_copy(update={"evaluation_report": evaluate_specification(result)})

    use_case_set = inherit_step_sources(artifact.use_case_set)
    for current_use_case in use_case_set.use_cases:
        if not current_use_case.human_readable_text:
            current_use_case.human_readable_text = render_use_case_text(current_use_case)
    use_cases = {use_case.id: use_case for use_case in use_case_set.use_cases}
    diagrams: list[ActivityDiagram] = []
    activity_results: list[ActivityGenerationResult] = []
    reports: list[ValidationReport] = [parse_report]
    for diagram in artifact.activity_diagrams:
        diagram = diagram.model_copy(update={"mermaid_source": render_mermaid(diagram)})
        diagrams.append(diagram)
        matched_use_case = use_cases.get(diagram.use_case_id)
        if matched_use_case is None:
            report = ValidationReport(
                passed=False,
                issues=[
                    ValidationIssue(
                        id="VI-001",
                        severity=IssueSeverity.ERROR,
                        category=IssueCategory.TRACE,
                        code="one_shot_unknown_diagram_uc",
                        message=(
                            f"Diagram {diagram.id} references unknown UC {diagram.use_case_id}"
                        ),
                        element_ids=[diagram.id, diagram.use_case_id],
                    )
                ],
                validator_name="one_shot_activity",
            )
        else:
            report = validate_activity_deterministic(diagram, matched_use_case)
        reports.append(report)
        activity_results.append(
            ActivityGenerationResult(
                use_case_id=diagram.use_case_id,
                activity_diagram=diagram,
                status=PipelineStatus.SUCCESS if report.passed else PipelineStatus.FAILED,
                validation_reports=[report],
            )
        )
    missing_diagram_ucs = sorted(set(use_cases) - {item.use_case_id for item in diagrams})
    if missing_diagram_ucs:
        reports.append(
            ValidationReport(
                passed=False,
                issues=[
                    ValidationIssue(
                        id=f"VI-{index:03d}",
                        severity=IssueSeverity.ERROR,
                        category=IssueCategory.STRUCTURAL,
                        code="one_shot_missing_activity",
                        message=f"No activity diagram generated for {use_case_id}",
                        element_ids=[use_case_id],
                    )
                    for index, use_case_id in enumerate(missing_diagram_ucs, start=1)
                ],
                validator_name="one_shot_diagram_coverage",
            )
        )
    trace = materialize_trace_manifest(
        request,
        use_case_set,
        diagrams,
        existing=artifact.trace_manifest,
    )
    provisional = GeneratedSpecification(
        request=request,
        use_case_set=use_case_set,
        activity_results=activity_results,
        trace_manifest=trace,
        validation_reports=reports,
        status=(
            PipelineStatus.SUCCESS
            if all(report.passed for report in reports)
            else PipelineStatus.FAILED
        ),
    )
    e2e = validate_end_to_end_trace(provisional)
    reports.append(e2e)
    status = (
        PipelineStatus.SUCCESS
        if all(report.passed for report in reports)
        else PipelineStatus.FAILED
    )
    result = provisional.model_copy(update={"validation_reports": reports, "status": status})
    return result.model_copy(update={"evaluation_report": evaluate_specification(result)})
