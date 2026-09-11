"""Deterministic validators: schema helpers, structural, and trace checks."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from traceable_spec.entities import (
    ActivityDiagram,
    ActivityNodeKind,
    ElementRefType,
    GeneratedSpecification,
    IssueCategory,
    IssueSeverity,
    PipelineStatus,
    RequirementCoverageStatus,
    ScenarioKind,
    SpecificationRequest,
    TraceLinkType,
    TraceManifest,
    UseCase,
    UseCaseSet,
    ValidationIssue,
    ValidationReport,
)
from traceable_spec.traceability import declared_relations, iter_use_case_steps

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
        scenarios = [uc.main_success_scenario] + uc.alternative_scenarios + uc.exception_scenarios
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

        for user_story in uc.user_stories:
            if user_story.use_case_id != uc.id:
                issues.append(
                    _issue(
                        seq=seq,
                        severity=IssueSeverity.ERROR,
                        category=IssueCategory.TRACE,
                        code="user_story_uc_mismatch",
                        message=(
                            f"User story {user_story.id} points to "
                            f"{user_story.use_case_id}, not {uc.id}"
                        ),
                        element_ids=[uc.id, user_story.id, user_story.use_case_id],
                    )
                )
                seq += 1
        for system_story in uc.system_stories:
            if system_story.use_case_id != uc.id:
                issues.append(
                    _issue(
                        seq=seq,
                        severity=IssueSeverity.ERROR,
                        category=IssueCategory.TRACE,
                        code="system_story_uc_mismatch",
                        message=(
                            f"System story {system_story.id} points to "
                            f"{system_story.use_case_id}, not {uc.id}"
                        ),
                        element_ids=[uc.id, system_story.id, system_story.use_case_id],
                    )
                )
                seq += 1
        for step in iter_use_case_steps(uc):
            unknown_step_sources = sorted(set(step.source_fr_ids) - set(uc.source_fr_ids))
            if unknown_step_sources:
                issues.append(
                    _issue(
                        seq=seq,
                        severity=IssueSeverity.ERROR,
                        category=IssueCategory.TRACE,
                        code="step_fr_outside_uc_scope",
                        message=(
                            f"Step {step.id} references FRs outside {uc.id}: "
                            f"{', '.join(unknown_step_sources)}"
                        ),
                        element_ids=[uc.id, step.id, *unknown_step_sources],
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
                        message=(f"Missing TraceManifest FR_TO_UC link for {fr_id} → {uc.id}"),
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


_TRACE_ENDPOINT_TYPES: dict[
    TraceLinkType,
    tuple[ElementRefType, ElementRefType],
] = {
    TraceLinkType.FR_TO_ATOM: (ElementRefType.FR, ElementRefType.FR_ATOM),
    TraceLinkType.ATOM_TO_UC: (ElementRefType.FR_ATOM, ElementRefType.UC),
    TraceLinkType.ATOM_TO_STEP: (ElementRefType.FR_ATOM, ElementRefType.STEP),
    TraceLinkType.FR_TO_UC: (ElementRefType.FR, ElementRefType.UC),
    TraceLinkType.FR_TO_STEP: (ElementRefType.FR, ElementRefType.STEP),
    TraceLinkType.UC_TO_US: (ElementRefType.UC, ElementRefType.US),
    TraceLinkType.UC_TO_SS: (ElementRefType.UC, ElementRefType.SS),
    TraceLinkType.STEP_TO_ACTIVITY_NODE: (
        ElementRefType.STEP,
        ElementRefType.ACTIVITY_NODE,
    ),
    TraceLinkType.STEP_TO_ACTIVITY_EDGE: (
        ElementRefType.STEP,
        ElementRefType.ACTIVITY_EDGE,
    ),
    TraceLinkType.UC_TO_ACTIVITY: (ElementRefType.UC, ElementRefType.ACTIVITY),
    TraceLinkType.NFR_TO_UC: (ElementRefType.NFR, ElementRefType.UC),
}


def validate_requirement_atomization(request: SpecificationRequest) -> ValidationReport:
    """Every FR must have stable, non-empty atoms that point back to that FR."""

    issues: list[ValidationIssue] = []
    seq = 1
    atom_ids: list[str] = []
    for requirement in request.functional_requirements:
        if not requirement.atoms:
            issues.append(
                _issue(
                    seq=seq,
                    severity=IssueSeverity.ERROR,
                    category=IssueCategory.TRACE,
                    code="fr_without_atoms",
                    message=f"Functional requirement {requirement.id} has no traceable atoms",
                    element_ids=[requirement.id],
                )
            )
            seq += 1
        for atom in requirement.atoms:
            atom_ids.append(atom.id)
            if atom.parent_fr_id != requirement.id:
                issues.append(
                    _issue(
                        seq=seq,
                        severity=IssueSeverity.ERROR,
                        category=IssueCategory.TRACE,
                        code="atom_parent_mismatch",
                        message=(
                            f"Atom {atom.id} declares parent {atom.parent_fr_id}, "
                            f"but is nested under {requirement.id}"
                        ),
                        element_ids=[requirement.id, atom.id, atom.parent_fr_id],
                    )
                )
                seq += 1
    for atom_id, count in sorted((item, atom_ids.count(item)) for item in set(atom_ids)):
        if count > 1:
            issues.append(
                _issue(
                    seq=seq,
                    severity=IssueSeverity.ERROR,
                    category=IssueCategory.STRUCTURAL,
                    code="duplicate_atom_id",
                    message=f"Requirement atom ID {atom_id} appears {count} times",
                    element_ids=[atom_id],
                )
            )
            seq += 1
    return _report(
        "requirement_atomization",
        issues,
        details={"fr_count": len(request.functional_requirements), "atom_count": len(atom_ids)},
    )


def validate_trace_link_contracts(trace: TraceManifest) -> ValidationReport:
    """Check link-type endpoint types, duplicate relations and unsupported rationale."""

    issues: list[ValidationIssue] = []
    seq = 1
    seen: set[tuple[TraceLinkType, str, str]] = set()
    for link in trace.links:
        relation_key = (link.link_type, link.source_id, link.target_id)
        if relation_key in seen:
            issues.append(
                _issue(
                    seq=seq,
                    severity=IssueSeverity.ERROR,
                    category=IssueCategory.TRACE,
                    code="duplicate_trace_relation",
                    message=(
                        f"Trace relation {link.link_type.value} "
                        f"{link.source_id} → {link.target_id} is duplicated"
                    ),
                    element_ids=[link.id, link.source_id, link.target_id],
                )
            )
            seq += 1
        seen.add(relation_key)
        expected = _TRACE_ENDPOINT_TYPES.get(link.link_type)
        if expected is not None and (link.source_type, link.target_type) != expected:
            issues.append(
                _issue(
                    seq=seq,
                    severity=IssueSeverity.ERROR,
                    category=IssueCategory.TRACE,
                    code="trace_endpoint_type_mismatch",
                    message=(
                        f"{link.link_type.value} requires {expected[0].value} → "
                        f"{expected[1].value}, got {link.source_type.value} → "
                        f"{link.target_type.value}"
                    ),
                    element_ids=[link.id],
                )
            )
            seq += 1
        if link.link_type == TraceLinkType.UNSUPPORTED and not (link.rationale or "").strip():
            issues.append(
                _issue(
                    seq=seq,
                    severity=IssueSeverity.ERROR,
                    category=IssueCategory.TRACE,
                    code="unsupported_without_rationale",
                    message=f"Unsupported trace {link.id} requires a rationale",
                    element_ids=[link.id],
                )
            )
            seq += 1
    return _report("trace_link_contracts", issues)


def validate_declared_trace_bidirectionality(
    request: SpecificationRequest,
    use_case_set: UseCaseSet,
    diagrams: Iterable[ActivityDiagram],
    trace: TraceManifest,
) -> ValidationReport:
    """Compare typed forward declarations with reverse manifest lookups.

    The check is called bidirectional because it detects both missing manifest
    links for declared references and extra manifest links unsupported by typed
    artifacts. ``UNSUPPORTED`` links are the explicit exception.
    """

    expected = {
        (item.link_type, item.source_id, item.target_id)
        for item in declared_relations(request, use_case_set, diagrams)
    }
    actual = {
        (link.link_type, link.source_id, link.target_id)
        for link in trace.links
        if link.link_type != TraceLinkType.UNSUPPORTED
    }
    issues: list[ValidationIssue] = []
    seq = 1
    for link_type, source_id, target_id in sorted(
        expected - actual,
        key=lambda item: (item[0].value, item[1], item[2]),
    ):
        issues.append(
            _issue(
                seq=seq,
                severity=IssueSeverity.ERROR,
                category=IssueCategory.TRACE,
                code="missing_declared_trace",
                message=(
                    f"Declared relation {link_type.value} {source_id} → {target_id} "
                    "is absent from TraceManifest"
                ),
                element_ids=[source_id, target_id],
            )
        )
        seq += 1
    for link_type, source_id, target_id in sorted(
        actual - expected,
        key=lambda item: (item[0].value, item[1], item[2]),
    ):
        issues.append(
            _issue(
                seq=seq,
                severity=IssueSeverity.ERROR,
                category=IssueCategory.TRACE,
                code="undeclared_reverse_trace",
                message=(
                    f"TraceManifest relation {link_type.value} {source_id} → {target_id} "
                    "has no matching typed declaration"
                ),
                element_ids=[source_id, target_id],
            )
        )
        seq += 1
    return _report(
        "declared_trace_bidirectionality",
        issues,
        details={"expected_relations": len(expected), "actual_relations": len(actual)},
    )


def validate_trace_coverage_thresholds(
    use_case_set: UseCaseSet,
    diagrams: Iterable[ActivityDiagram],
) -> ValidationReport:
    """Enforce 95% UC-element and 100% activity-element provenance targets."""

    uc_total = 0
    uc_supported = 0
    diagram_total = 0
    diagram_supported = 0
    for use_case in use_case_set.use_cases:
        uc_total += 1
        uc_supported += int(bool(use_case.source_fr_ids))
        for user_story in use_case.user_stories:
            uc_total += 1
            uc_supported += int(
                user_story.use_case_id == use_case.id and bool(use_case.source_fr_ids)
            )
        for system_story in use_case.system_stories:
            uc_total += 1
            uc_supported += int(
                system_story.use_case_id == use_case.id and bool(use_case.source_fr_ids)
            )
        for step in iter_use_case_steps(use_case):
            uc_total += 1
            uc_supported += int(bool(step.source_fr_ids))

    for diagram in diagrams:
        diagram_total += 1
        diagram_supported += int(bool(diagram.use_case_id))
        for node in diagram.nodes:
            diagram_total += 1
            structural = node.kind in {
                ActivityNodeKind.INITIAL,
                ActivityNodeKind.FINAL,
                ActivityNodeKind.MERGE,
                ActivityNodeKind.FORK,
                ActivityNodeKind.JOIN,
            }
            diagram_supported += int(bool(node.related_step_ids) or node.unsupported or structural)
        for edge in diagram.edges:
            diagram_total += 1
            diagram_supported += int(bool(edge.related_step_ids) or edge.unsupported)

    uc_ratio = uc_supported / uc_total if uc_total else 0.0
    diagram_ratio = diagram_supported / diagram_total if diagram_total else 1.0
    issues: list[ValidationIssue] = []
    if uc_ratio < 0.95:
        issues.append(
            _issue(
                seq=1,
                severity=IssueSeverity.ERROR,
                category=IssueCategory.TRACE,
                code="uc_trace_coverage_below_threshold",
                message=f"UC element trace coverage {uc_ratio:.3f} is below 0.95",
            )
        )
    if diagram_ratio < 1.0:
        issues.append(
            _issue(
                seq=len(issues) + 1,
                severity=IssueSeverity.ERROR,
                category=IssueCategory.TRACE,
                code="activity_trace_coverage_below_threshold",
                message=f"Activity element trace coverage {diagram_ratio:.3f} is below 1.00",
            )
        )
    return _report(
        "trace_coverage_thresholds",
        issues,
        details={
            "uc_supported": uc_supported,
            "uc_total": uc_total,
            "uc_ratio": uc_ratio,
            "activity_supported": diagram_supported,
            "activity_total": diagram_total,
            "activity_ratio": diagram_ratio,
        },
    )


def validate_activity_structure(diagram: ActivityDiagram) -> ValidationReport:
    issues: list[ValidationIssue] = []
    seq = 1
    nodes = {node.id: node for node in diagram.nodes}
    partition_ids = {partition.id for partition in diagram.partitions}
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
        if not edge.related_step_ids and not edge.unsupported:
            issues.append(
                _issue(
                    seq=seq,
                    severity=IssueSeverity.ERROR,
                    category=IssueCategory.TRACE,
                    code="activity_edge_untraced",
                    message=f"Edge {edge.id} must link to UC step(s) or be marked unsupported",
                    element_ids=[edge.id],
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
        if node.partition_id is not None and node.partition_id not in partition_ids:
            issues.append(
                _issue(
                    seq=seq,
                    severity=IssueSeverity.ERROR,
                    category=IssueCategory.STRUCTURAL,
                    code="unknown_node_partition",
                    message=f"Node {node.id} references unknown partition {node.partition_id}",
                    element_ids=[node.id, node.partition_id],
                )
            )
            seq += 1
        if node.kind in {ActivityNodeKind.ACTION, ActivityNodeKind.DECISION} and not (
            node.related_step_ids or node.unsupported
        ):
            issues.append(
                _issue(
                    seq=seq,
                    severity=IssueSeverity.ERROR,
                    category=IssueCategory.TRACE,
                    code="activity_node_untraced",
                    message=(f"Node {node.id} must link to UC step(s) or be marked unsupported"),
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
    request: SpecificationRequest,
    trace: TraceManifest,
) -> ValidationReport:
    """Aggregate deterministic UC checks into one report."""
    fr_id_list = [item.id for item in request.functional_requirements]
    atom_ids = {
        atom.id for requirement in request.functional_requirements for atom in requirement.atoms
    }
    reports = [
        validate_requirement_atomization(request),
        validate_unique_ids(use_case_set, trace=trace),
        validate_use_case_structure(use_case_set),
        validate_uc_fr_references(use_case_set, fr_id_list),
        validate_fr_coverage(fr_id_list, use_case_set),
        validate_fr_to_uc_trace_links(use_case_set, trace),
        validate_trace_link_contracts(trace),
        validate_declared_trace_bidirectionality(request, use_case_set, (), trace),
        validate_trace_coverage_thresholds(use_case_set, ()),
        validate_trace_integrity(
            set(collect_ids(use_case_set))
            | set(fr_id_list)
            | atom_ids
            | {item.id for item in request.non_functional_requirements},
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
    issues: list[ValidationIssue] = []
    if diagram.use_case_id != use_case.id:
        issues.append(
            _issue(
                seq=1,
                severity=IssueSeverity.ERROR,
                category=IssueCategory.TRACE,
                code="activity_use_case_mismatch",
                message=(
                    f"Diagram {diagram.id} points to {diagram.use_case_id}, expected {use_case.id}"
                ),
                element_ids=[diagram.id, diagram.use_case_id, use_case.id],
            )
        )
    step_ids = {step.id for step in use_case.main_success_scenario.steps}
    for scenario in use_case.alternative_scenarios + use_case.exception_scenarios:
        step_ids.update(step.id for step in scenario.steps)

    issues.extend(validate_activity_structure(diagram).issues)
    issues = [
        issue.model_copy(update={"id": f"VI-{index:03d}"}) for index, issue in enumerate(issues, 1)
    ]
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
    for edge in diagram.edges:
        for step_id in edge.related_step_ids:
            if step_id not in step_ids:
                issues.append(
                    _issue(
                        seq=seq,
                        severity=IssueSeverity.ERROR,
                        category=IssueCategory.TRACE,
                        code="activity_edge_step_missing",
                        message=f"Edge {edge.id} references unknown step {step_id}",
                        element_ids=[edge.id, step_id],
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
    known.update(
        atom.id
        for requirement in spec.request.functional_requirements
        for atom in requirement.atoms
    )
    known.update(nfr.id for nfr in spec.request.non_functional_requirements)
    reports = [
        validate_requirement_atomization(spec.request),
        validate_unique_ids(spec.use_case_set, diagrams, spec.trace_manifest),
        validate_fr_coverage(fr_ids, spec.use_case_set),
        validate_trace_link_contracts(spec.trace_manifest),
        validate_declared_trace_bidirectionality(
            spec.request,
            spec.use_case_set,
            diagrams,
            spec.trace_manifest,
        ),
        validate_trace_coverage_thresholds(spec.use_case_set, diagrams),
        validate_trace_integrity(known, spec.trace_manifest),
    ]
    merged: list[ValidationIssue] = []
    seq = 1
    for report in reports:
        for issue in report.issues:
            merged.append(issue.model_copy(update={"id": f"VI-{seq:03d}"}))
            seq += 1
    return _report(
        "e2e_trace",
        merged,
        details={
            report.validator_name: {"passed": report.passed, **report.details} for report in reports
        },
    )


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
