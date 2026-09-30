"""Opt-in candidate contract. V1 generation, models and frozen scores stay intact.

The envelope adds typed NFR-to-step assignments without changing the legacy
ScenarioStep schema. It does not migrate or repair incorrectly typed FR fields.
This evaluator is not yet wired into every graph's generation/repair loop.
"""

from __future__ import annotations

from collections import Counter
from typing import Literal

from pydantic import Field, ValidationError

from traceable_spec.entities import (
    GeneratedSpecification,
    IssueCategory,
    IssueSeverity,
    StrictModel,
    ValidationIssue,
    ValidationReport,
)
from traceable_spec.evaluation.formal import evaluate_final_formal
from traceable_spec.traceability import iter_use_case_steps

CONTRACT_VERSION: Literal["common-final-v2-candidate-2026-09-28"] = (
    "common-final-v2-candidate-2026-09-28"
)


class StepNFRSources(StrictModel):
    use_case_id: str = Field(pattern=r"^UC-\d{3,}$")
    step_id: str = Field(pattern=r"^STEP-UC\d{3,}-\d{3,}$")
    source_nfr_ids: list[str] = Field(min_length=1)
    rationale: str = Field(min_length=1)


class NFRStepLink(StrictModel):
    link_type: Literal["nfr_to_step"] = "nfr_to_step"
    source_id: str
    use_case_id: str
    target_id: str


class TraceCandidateV2(StrictModel):
    contract_version: Literal["common-final-v2-candidate-2026-09-28"] = CONTRACT_VERSION
    specification: GeneratedSpecification
    step_nfr_sources: list[StepNFRSources] = Field(default_factory=list)
    nfr_step_links: list[NFRStepLink] = Field(default_factory=list)


def materialize_nfr_step_links(sources: list[StepNFRSources]) -> list[NFRStepLink]:
    """Materialize declared assignments only; existence/scope are checked below."""
    return [
        NFRStepLink(source_id=nfr, use_case_id=uc, target_id=step)
        for nfr, uc, step in sorted(
            {(nfr, s.use_case_id, s.step_id) for s in sources for nfr in s.source_nfr_ids}
        )
    ]


def evaluate_trace_candidate_v2(candidate: TraceCandidateV2) -> ValidationReport:
    """Re-evaluate a copy; no Gold, method name, migration or repair is involved."""
    try:
        candidate = TraceCandidateV2.model_validate(candidate.model_dump(mode="json"))
    except ValidationError as exc:
        return ValidationReport(
            passed=False,
            validator_name=CONTRACT_VERSION,
            issues=[
                ValidationIssue(
                    id="VI-001",
                    severity=IssueSeverity.ERROR,
                    category=IssueCategory.SCHEMA,
                    code="v2_schema_invalid",
                    message=str(exc),
                    element_ids=[],
                )
            ],
        )
    spec = candidate.specification
    legacy = evaluate_final_formal(spec)
    issues: list[ValidationIssue] = []

    def error(code: str, message: str, ids: list[str]) -> None:
        issues.append(
            ValidationIssue(
                id="VI-001",
                severity=IssueSeverity.ERROR,
                category=IssueCategory.TRACE,
                code=code,
                message=message,
                element_ids=ids,
            )
        )

    # Ambiguous IDs cannot be used to suppress an edge-local issue from v1.
    identifiers: list[str] = []
    eligible_ids: set[str] = set()
    service_edges: list[dict[str, str]] = []
    activity_total = activity_supported = 0
    structural_nodes = {"initial", "final", "merge", "fork", "join"}
    for result in spec.activity_results:
        diagram = result.activity_diagram
        if diagram is None:
            continue
        identifiers.extend(
            [diagram.id, *[n.id for n in diagram.nodes], *[e.id for e in diagram.edges]]
        )
        nodes = {node.id: node for node in diagram.nodes}
        activity_total += 1
        activity_supported += bool(diagram.use_case_id)
        for node in diagram.nodes:
            activity_total += 1
            activity_supported += bool(
                node.related_step_ids or node.unsupported or node.kind.value in structural_nodes
            )
        for edge in diagram.edges:
            source_node, target_node = (
                nodes.get(edge.source_node_id),
                nodes.get(edge.target_node_id),
            )
            structural = bool(
                source_node is not None
                and target_node is not None
                and not edge.guard
                and not edge.label
                and source_node.kind.value != "decision"
                and (source_node.kind.value == "initial" or target_node.kind.value == "final")
            )
            if structural:
                eligible_ids.add(edge.id)
                service_edges.append({"diagram_id": diagram.id, "edge_id": edge.id})
            activity_total += 1
            activity_supported += bool(edge.related_step_ids or edge.unsupported or structural)
    duplicates = sorted(k for k, n in Counter(identifiers).items() if n > 1)
    if duplicates:
        error("v2_duplicate_activity_id", "Activity identifiers must be unambiguous", duplicates)
        eligible_ids.difference_update(duplicates)

    waived = []
    for issue in legacy.issues:
        is_boundary = (
            issue.code == "activity_edge_untraced"
            and bool(issue.element_ids)
            and set(issue.element_ids) <= eligible_ids
        )
        complete = (
            issue.code == "activity_trace_coverage_below_threshold"
            and activity_total == activity_supported
            and not duplicates
        )
        if is_boundary or complete:
            waived.append(issue.model_dump(mode="json"))
        else:
            issues.append(issue)

    known_nfrs = {nfr.id for nfr in spec.request.non_functional_requirements}
    use_cases = {} if spec.use_case_set is None else {u.id: u for u in spec.use_case_set.use_cases}
    step_sets = {u.id: {s.id for s in iter_use_case_steps(u)} for u in use_cases.values()}
    for uc in use_cases.values():
        unknown = sorted(set(uc.source_nfr_ids) - known_nfrs)
        if unknown:
            error("v2_unknown_uc_nfr", "UC references unknown NFRs", [uc.id, *unknown])
    seen: set[tuple[str, str]] = set()
    for source in candidate.step_nfr_sources:
        key = source.use_case_id, source.step_id
        if key in seen:
            error("v2_duplicate_step_nfr_assignment", "Duplicate step assignment", list(key))
        seen.add(key)
        if not source.rationale.strip():
            error("v2_empty_nfr_rationale", "NFR assignment requires a rationale", list(key))
        if len(source.source_nfr_ids) != len(set(source.source_nfr_ids)):
            error("v2_duplicate_nfr_reference", "Repeated NFR reference", list(key))
        if source.use_case_id not in use_cases or source.step_id not in step_sets.get(
            source.use_case_id, set()
        ):
            error(
                "v2_unknown_nfr_target", "NFR target must be a step in the declared UC", list(key)
            )
            continue
        unknown = sorted(set(source.source_nfr_ids) - known_nfrs)
        outside = sorted(
            set(source.source_nfr_ids) - set(use_cases[source.use_case_id].source_nfr_ids)
        )
        if unknown:
            error("v2_unknown_step_nfr", "Step references unknown NFRs", [*key, *unknown])
        if outside:
            error(
                "v2_step_nfr_outside_uc_scope", "Step NFR is outside its UC scope", [*key, *outside]
            )
    expected = {x.model_dump_json() for x in materialize_nfr_step_links(candidate.step_nfr_sources)}
    actual = {x.model_dump_json() for x in candidate.nfr_step_links}
    if expected != actual:
        error("v2_nfr_links_mismatch", "NFR links differ from declared step assignments", [])
    if len(actual) != len(candidate.nfr_step_links):
        error("v2_duplicate_nfr_link", "Duplicate NFR link", [])
    return ValidationReport(
        passed=not any(i.blocking for i in issues),
        issues=[i.model_copy(update={"id": f"VI-{n:03d}"}) for n, i in enumerate(issues, 1)],
        validator_name=CONTRACT_VERSION,
        details={
            "uses_gold": False,
            "uses_internal_status": False,
            "repairs_input": False,
            "legacy_passed": legacy.passed,
            "superseded_v1_issues": waived,
            "service_edges": service_edges,
            "activity_supported": activity_supported,
            "activity_total": activity_total,
            "nfr_step_link_count": len(actual),
            "nfr_satisfaction_measured": False,
            "generation_loops_migrated": False,
        },
    )
