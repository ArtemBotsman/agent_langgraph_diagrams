"""Deterministic validators: schema helpers, structural, and trace checks."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from traceable_spec.entities import (
    ActivityDiagram,
    ActivityNodeKind,
    GeneratedSpecification,
    IssueCategory,
    IssueSeverity,
    PipelineStatus,
    RequirementCoverageStatus,
    ScenarioKind,
    TraceLinkType,
    TraceManifest,
    UseCase,
    UseCaseSet,
    ValidationIssue,
    ValidationReport,
)

ModelT = TypeVar("ModelT", bound=BaseModel)


def _issue(
    *,
    seq: int,
    severity: IssueSeverity,
    category: IssueCategory,
    code: str,
    message: str,
    element_ids: list[str] | None = None,
    blocking: bool = True,
) -> ValidationIssue:
    return ValidationIssue(
        id=f"VI-{seq:03d}",
        severity=severity,
        category=category,
        code=code,
        message=message,
        element_ids=element_ids or [],
        blocking=blocking,
    )


def _report(
    name: str,
    issues: list[ValidationIssue],
    details: dict[str, Any] | None = None,
) -> ValidationReport:
    blocking = [i for i in issues if i.blocking]
    return ValidationReport(
        passed=len(blocking) == 0,
        issues=issues,
        validator_name=name,
        details=details or {},
    )


def validate_pydantic_model(model_type: type[ModelT], data: dict[str, Any]) -> ValidationReport:
    """Schema validation via Pydantic; returns a ValidationReport."""
    issues: list[ValidationIssue] = []
    try:
        model_type.model_validate(data)
    except ValidationError as exc:
        for idx, err in enumerate(exc.errors(), start=1):
            loc = ".".join(str(part) for part in err.get("loc", ()))
            issues.append(
                _issue(
                    seq=idx,
                    severity=IssueSeverity.ERROR,
                    category=IssueCategory.SCHEMA,
                    code="schema_validation_error",
                    message=f"{loc}: {err.get('msg')}",
                    element_ids=[loc] if loc else [],
                )
            )
    return _report("pydantic_schema", issues)


def collect_ids(use_case_set: UseCaseSet, diagrams: Iterable[ActivityDiagram] = ()) -> list[str]:
    ids: list[str] = []
    for actor in use_case_set.actors:
        ids.append(actor.id)
    for uc in use_case_set.use_cases:
        ids.append(uc.id)
        for pre in uc.preconditions:
            ids.append(pre.id)
        for post in uc.success_postconditions + uc.failure_postconditions:
            ids.append(post.id)
        for user_story in uc.user_stories:
            ids.append(user_story.id)
        for system_story in uc.system_stories:
            ids.append(system_story.id)
        scenarios = (
            [uc.main_success_scenario]
            + uc.alternative_scenarios
            + uc.exception_scenarios
        )
        for scenario in scenarios:
            ids.append(scenario.id)
            for step in scenario.steps:
                ids.append(step.id)
        for missing in uc.missing_information:
            ids.append(missing.id)
        for assumption in uc.unsupported_assumptions:
            ids.append(assumption.id)
    for diagram in diagrams:
        ids.append(diagram.id)
        for part in diagram.partitions:
            ids.append(part.id)
        for node in diagram.nodes:
            ids.append(node.id)
        for edge in diagram.edges:
            ids.append(edge.id)
    return ids


def validate_unique_ids(
    use_case_set: UseCaseSet,
    diagrams: Iterable[ActivityDiagram] = (),
    trace: TraceManifest | None = None,
) -> ValidationReport:
    ids = collect_ids(use_case_set, diagrams)
    if trace is not None:
        ids.extend(link.id for link in trace.links)
    seen: dict[str, int] = defaultdict(int)
    for item_id in ids:
        seen[item_id] += 1
    issues: list[ValidationIssue] = []
    seq = 1
    for item_id, count in sorted(seen.items()):
        if count > 1:
            issues.append(
                _issue(
                    seq=seq,
                    severity=IssueSeverity.ERROR,
                    category=IssueCategory.STRUCTURAL,
                    code="duplicate_id",
                    message=f"Duplicate ID '{item_id}' appears {count} times",
                    element_ids=[item_id],
                )
            )
            seq += 1
    return _report("unique_ids", issues)


def validate_use_case_structure(use_case_set: UseCaseSet) -> ValidationReport:
    issues: list[ValidationIssue] = []
    seq = 1
    actor_ids = {actor.id for actor in use_case_set.actors}

    if not use_case_set.use_cases:
        issues.append(
            _issue(
                seq=seq,
                severity=IssueSeverity.ERROR,
                category=IssueCategory.STRUCTURAL,
                code="empty_use_case_set",
                message="UseCaseSet contains no use cases",
            )
        )
        seq += 1
        return _report("use_case_structure", issues)

    if not use_case_set.actors:
        issues.append(
            _issue(
                seq=seq,
                severity=IssueSeverity.ERROR,
                category=IssueCategory.STRUCTURAL,
                code="missing_actors",
                message="UseCaseSet has use cases but no actors",
            )
        )
        seq += 1

    for uc in use_case_set.use_cases:
        if not uc.goal.strip():
            issues.append(
                _issue(
                    seq=seq,
                    severity=IssueSeverity.ERROR,
                    category=IssueCategory.STRUCTURAL,
                    code="missing_goal",
                    message=f"Use Case {uc.id} has an empty goal",
                    element_ids=[uc.id],
                )
            )
            seq += 1

        if not uc.source_fr_ids:
            issues.append(
                _issue(
                    seq=seq,
                    severity=IssueSeverity.ERROR,
                    category=IssueCategory.TRACE,
                    code="uc_without_fr",
                    message=f"Use Case {uc.id} has no source FR references",
                    element_ids=[uc.id],
                )
            )
            seq += 1

        if uc.primary_actor_id not in actor_ids:
            issues.append(
                _issue(
                    seq=seq,
                    severity=IssueSeverity.ERROR,
                    category=IssueCategory.STRUCTURAL,
                    code="unknown_primary_actor",
                    message=f"Use Case {uc.id} primary actor {uc.primary_actor_id} is unknown",
                    element_ids=[uc.id, uc.primary_actor_id],
                )
            )
            seq += 1

        if uc.main_success_scenario.kind != ScenarioKind.MAIN:
            issues.append(
                _issue(
                    seq=seq,
                    severity=IssueSeverity.ERROR,
                    category=IssueCategory.STRUCTURAL,
                    code="missing_main_scenario",
                    message=f"Use Case {uc.id} main scenario kind is not 'main'",
                    element_ids=[uc.id, uc.main_success_scenario.id],
                )
            )
            seq += 1

        if not uc.main_success_scenario.steps:
            issues.append(
                _issue(
                    seq=seq,
                    severity=IssueSeverity.ERROR,
                    category=IssueCategory.STRUCTURAL,
                    code="missing_basic_flow",
                    message=f"Use Case {uc.id} has no basic flow steps",
                    element_ids=[uc.id, uc.main_success_scenario.id],
                )
            )
            seq += 1

        orders = [step.order for step in uc.main_success_scenario.steps]
        if orders != sorted(orders) or len(orders) != len(set(orders)):
            issues.append(
                _issue(
                    seq=seq,
                    severity=IssueSeverity.ERROR,
                    category=IssueCategory.STRUCTURAL,
                    code="invalid_step_order",
                    message=f"Use Case {uc.id} main scenario steps have invalid order",
                    element_ids=[uc.id],
                )
            )
            seq += 1

        for assumption in uc.unsupported_assumptions:
            if not assumption.justified:
                issues.append(
                    _issue(
                        seq=seq,
                        severity=IssueSeverity.ERROR,
                        category=IssueCategory.SEMANTIC,
                        code="unjustified_assumption",
                        message=f"Unjustified assumption {assumption.id} on {uc.id}",
                        element_ids=[uc.id, assumption.id],
                    )
                )
                seq += 1

    return _report("use_case_structure", issues)


def validate_uc_fr_references(
    use_case_set: UseCaseSet,
    fr_ids: Iterable[str],
) -> ValidationReport:
    """Ensure UC.source_fr_ids only reference known FRs from the request."""
    known = set(fr_ids)
    issues: list[ValidationIssue] = []
    seq = 1
    for uc in use_case_set.use_cases:
        for fr_id in uc.source_fr_ids:
            if fr_id not in known:
                issues.append(
                    _issue(
                        seq=seq,
                        severity=IssueSeverity.ERROR,
                        category=IssueCategory.TRACE,
                        code="unknown_fr_reference",
                        message=f"Use Case {uc.id} references unknown FR {fr_id}",
                        element_ids=[uc.id, fr_id],
                    )
                )
                seq += 1
    return _report("uc_fr_references", issues)


def validate_fr_to_uc_trace_links(
    use_case_set: UseCaseSet,
    trace: TraceManifest,
) -> ValidationReport:
    """Require an explicit FR_TO_UC TraceLink for each UC.source_fr_ids pair."""
    linked = {
        (link.source_id, link.target_id)
        for link in trace.links
        if link.link_type == TraceLinkType.FR_TO_UC
    }
    issues: list[ValidationIssue] = []
    seq = 1
    for uc in use_case_set.use_cases:
        for fr_id in uc.source_fr_ids:
            if (fr_id, uc.id) not in linked:
                issues.append(
                    _issue(
                        seq=seq,
                        severity=IssueSeverity.ERROR,
                        category=IssueCategory.TRACE,
                        code="missing_fr_to_uc_link",
                        message=(
                            f"Missing TraceManifest FR_TO_UC link for {fr_id} → {uc.id}"
                        ),
                        element_ids=[fr_id, uc.id],
                    )
                )
                seq += 1
    return _report("fr_to_uc_trace", issues)


def validate_fr_coverage(
    fr_ids: Iterable[str],
    use_case_set: UseCaseSet,
) -> ValidationReport:
    issues: list[ValidationIssue] = []
    seq = 1
    covered: set[str] = set()
    for uc in use_case_set.use_cases:
        covered.update(uc.source_fr_ids)

    fr_id_list = list(fr_ids)
    for fr_id in fr_id_list:
        status = use_case_set.fr_coverage.get(fr_id)
        if fr_id in covered:
            continue
        if status in {
            RequirementCoverageStatus.UNCOVERED,
            RequirementCoverageStatus.OUT_OF_SCOPE,
            RequirementCoverageStatus.CONFLICTING,
        }:
            issues.append(
                _issue(
                    seq=seq,
                    severity=IssueSeverity.WARNING,
                    category=IssueCategory.TRACE,
                    code="fr_explicitly_uncovered",
                    message=f"FR {fr_id} is explicitly marked as {status.value}",
                    element_ids=[fr_id],
                    blocking=False,
                )
            )
            seq += 1
        else:
            issues.append(
                _issue(
                    seq=seq,
                    severity=IssueSeverity.ERROR,
                    category=IssueCategory.TRACE,
                    code="fr_uncovered",
                    message=f"FR {fr_id} is not covered by any UC and has no explicit status",
                    element_ids=[fr_id],
                )
            )
            seq += 1
    return _report("fr_coverage", issues, details={"covered": sorted(covered)})


def validate_trace_integrity(
    known_ids: set[str],
    trace: TraceManifest,
) -> ValidationReport:
    issues: list[ValidationIssue] = []
    seq = 1
    for link in trace.links:
        if link.source_id not in known_ids:
            issues.append(
                _issue(
                    seq=seq,
                    severity=IssueSeverity.ERROR,
                    category=IssueCategory.TRACE,
                    code="dangling_trace_source",
                    message=f"TraceLink {link.id} source '{link.source_id}' does not exist",
                    element_ids=[link.id, link.source_id],
                )
            )
            seq += 1
        if link.target_id not in known_ids:
            issues.append(
                _issue(
                    seq=seq,
                    severity=IssueSeverity.ERROR,
                    category=IssueCategory.TRACE,
                    code="dangling_trace_target",
                    message=f"TraceLink {link.id} target '{link.target_id}' does not exist",
                    element_ids=[link.id, link.target_id],
                )
            )
            seq += 1
    return _report("trace_integrity", issues)


def validate_activity_structure(diagram: ActivityDiagram) -> ValidationReport:
    issues: list[ValidationIssue] = []
    seq = 1
    nodes = {node.id: node for node in diagram.nodes}
    initials = [n for n in diagram.nodes if n.kind == ActivityNodeKind.INITIAL]
    finals = [n for n in diagram.nodes if n.kind == ActivityNodeKind.FINAL]

    if len(initials) != 1:
        issues.append(
            _issue(
                seq=seq,
                severity=IssueSeverity.ERROR,
                category=IssueCategory.STRUCTURAL,
                code="initial_node_count",
                message=f"Activity {diagram.id} must have exactly one initial node",
                element_ids=[diagram.id],
            )
        )
        seq += 1
    if not finals:
        issues.append(
            _issue(
                seq=seq,
                severity=IssueSeverity.ERROR,
                category=IssueCategory.STRUCTURAL,
                code="missing_final_node",
                message=f"Activity {diagram.id} has no final node",
                element_ids=[diagram.id],
            )
        )
        seq += 1

    for edge in diagram.edges:
        if edge.source_node_id not in nodes:
            issues.append(
                _issue(
                    seq=seq,
                    severity=IssueSeverity.ERROR,
                    category=IssueCategory.STRUCTURAL,
                    code="unknown_edge_source",
                    message=f"Edge {edge.id} source '{edge.source_node_id}' is unknown",
                    element_ids=[edge.id, edge.source_node_id],
                )
            )
            seq += 1
        if edge.target_node_id not in nodes:
            issues.append(
                _issue(
                    seq=seq,
                    severity=IssueSeverity.ERROR,
                    category=IssueCategory.STRUCTURAL,
                    code="unknown_edge_target",
                    message=f"Edge {edge.id} target '{edge.target_node_id}' is unknown",
                    element_ids=[edge.id, edge.target_node_id],
                )
            )
            seq += 1

    decision_ids = {n.id for n in diagram.nodes if n.kind == ActivityNodeKind.DECISION}
    outgoing: dict[str, list[Any]] = defaultdict(list)
    for edge in diagram.edges:
        outgoing[edge.source_node_id].append(edge)

    for decision_id in decision_ids:
        branches = outgoing.get(decision_id, [])
        if len(branches) < 2:
            issues.append(
                _issue(
                    seq=seq,
                    severity=IssueSeverity.ERROR,
                    category=IssueCategory.STRUCTURAL,
                    code="decision_without_branches",
                    message=f"Decision {decision_id} must have at least two outgoing edges",
                    element_ids=[decision_id],
                )
            )
            seq += 1
            continue
        for edge in branches:
            if not edge.guard:
                issues.append(
                    _issue(
                        seq=seq,
                        severity=IssueSeverity.ERROR,
                        category=IssueCategory.STRUCTURAL,
                        code="decision_missing_guard",
                        message=f"Decision branch {edge.id} has no guard",
                        element_ids=[decision_id, edge.id],
                    )
                )
                seq += 1

    for node in diagram.nodes:
        if node.kind in {ActivityNodeKind.ACTION, ActivityNodeKind.DECISION} and not (
            node.related_step_ids or node.unsupported
        ):
            issues.append(
                _issue(
                    seq=seq,
                    severity=IssueSeverity.ERROR,
                    category=IssueCategory.TRACE,
                    code="activity_node_untraced",
                    message=(
                        f"Node {node.id} must link to UC step(s) or be marked unsupported"
                    ),
                    element_ids=[node.id],
                )
            )
            seq += 1

    # Reachability from initial
    if len(initials) == 1:
        start = initials[0].id
        adjacency: dict[str, list[str]] = defaultdict(list)
        for edge in diagram.edges:
            if edge.source_node_id in nodes and edge.target_node_id in nodes:
                adjacency[edge.source_node_id].append(edge.target_node_id)

        reachable: set[str] = set()
        queue: deque[str] = deque([start])
        while queue:
            current = queue.popleft()
            if current in reachable:
                continue
            reachable.add(current)
            queue.extend(adjacency.get(current, []))

        significant = {
            n.id
            for n in diagram.nodes
            if n.kind
            in {
                ActivityNodeKind.ACTION,
                ActivityNodeKind.DECISION,
                ActivityNodeKind.MERGE,
                ActivityNodeKind.FORK,
                ActivityNodeKind.JOIN,
                ActivityNodeKind.FINAL,
            }
        }
        for node_id in sorted(significant - reachable):
            issues.append(
                _issue(
                    seq=seq,
                    severity=IssueSeverity.ERROR,
                    category=IssueCategory.STRUCTURAL,
                    code="unreachable_from_initial",
                    message=f"Node {node_id} is unreachable from initial node",
                    element_ids=[node_id, start],
                )
            )
            seq += 1

        final_ids = {n.id for n in finals}
        if final_ids and reachable.isdisjoint(final_ids):
            issues.append(
                _issue(
                    seq=seq,
                    severity=IssueSeverity.ERROR,
                    category=IssueCategory.STRUCTURAL,
                    code="final_unreachable",
                    message=f"No final node is reachable from initial in {diagram.id}",
                    element_ids=[diagram.id, start],
                )
            )
            seq += 1

    return _report("activity_structure", issues)


def validate_repair_limit(attempt: int, max_attempts: int) -> ValidationReport:
    issues: list[ValidationIssue] = []
    if attempt > max_attempts:
        issues.append(
            _issue(
                seq=1,
                severity=IssueSeverity.ERROR,
                category=IssueCategory.REPAIR,
                code="repair_limit_exceeded",
                message=f"Repair attempt {attempt} exceeds max_repair_attempts={max_attempts}",
            )
        )
    return _report("repair_limit", issues, details={"attempt": attempt, "max": max_attempts})


def validate_use_case_set_deterministic(
    use_case_set: UseCaseSet,
    fr_ids: Iterable[str],
    trace: TraceManifest,
) -> ValidationReport:
    """Aggregate deterministic UC checks into one report."""
    fr_id_list = list(fr_ids)
    reports = [
        validate_unique_ids(use_case_set, trace=trace),
        validate_use_case_structure(use_case_set),
        validate_uc_fr_references(use_case_set, fr_id_list),
        validate_fr_coverage(fr_id_list, use_case_set),
        validate_fr_to_uc_trace_links(use_case_set, trace),
        validate_trace_integrity(
            set(collect_ids(use_case_set)) | set(fr_id_list),
            trace,
        ),
    ]
    merged: list[ValidationIssue] = []
    seq = 1
    for report in reports:
        for issue in report.issues:
            merged.append(issue.model_copy(update={"id": f"VI-{seq:03d}"}))
            seq += 1
    details = {report.validator_name: report.passed for report in reports}
    return _report("uc_deterministic_aggregate", merged, details=details)


def validate_activity_deterministic(
    diagram: ActivityDiagram,
    use_case: UseCase,
) -> ValidationReport:
    step_ids = {
        step.id
        for step in use_case.main_success_scenario.steps
    }
    for scenario in use_case.alternative_scenarios + use_case.exception_scenarios:
        step_ids.update(step.id for step in scenario.steps)

    issues = list(validate_activity_structure(diagram).issues)
    seq = len(issues) + 1
    for node in diagram.nodes:
        for step_id in node.related_step_ids:
            if step_id not in step_ids:
                issues.append(
                    _issue(
                        seq=seq,
                        severity=IssueSeverity.ERROR,
                        category=IssueCategory.TRACE,
                        code="activity_step_missing",
                        message=f"Node {node.id} references unknown step {step_id}",
                        element_ids=[node.id, step_id],
                    )
                )
                seq += 1
    return _report("activity_deterministic", issues)


def validate_end_to_end_trace(spec: GeneratedSpecification) -> ValidationReport:
    if spec.use_case_set is None:
        return _report(
            "e2e_trace",
            [
                _issue(
                    seq=1,
                    severity=IssueSeverity.ERROR,
                    category=IssueCategory.TRACE,
                    code="missing_use_case_set",
                    message="Cannot validate end-to-end trace without UseCaseSet",
                )
            ],
        )
    diagrams = [
        result.activity_diagram
        for result in spec.activity_results
        if result.activity_diagram is not None
    ]
    fr_ids = [fr.id for fr in spec.request.functional_requirements]
    known = set(collect_ids(spec.use_case_set, diagrams)) | set(fr_ids)
    known.update(nfr.id for nfr in spec.request.non_functional_requirements)
    reports = [
        validate_unique_ids(spec.use_case_set, diagrams, spec.trace_manifest),
        validate_fr_coverage(fr_ids, spec.use_case_set),
        validate_trace_integrity(known, spec.trace_manifest),
    ]
    merged: list[ValidationIssue] = []
    seq = 1
    for report in reports:
        for issue in report.issues:
            merged.append(issue.model_copy(update={"id": f"VI-{seq:03d}"}))
            seq += 1
    return _report("e2e_trace", merged)


def all_reports_passed(reports: Iterable[ValidationReport]) -> bool:
    return all(report.passed for report in reports)


def summarize_pipeline_status(reports: Iterable[ValidationReport]) -> PipelineStatus:
    reports_list = list(reports)
    if not reports_list:
        return PipelineStatus.FAILED
    if all_reports_passed(reports_list):
        return PipelineStatus.SUCCESS
    if any(report.passed for report in reports_list):
        return PipelineStatus.PARTIAL
    return PipelineStatus.FAILED
