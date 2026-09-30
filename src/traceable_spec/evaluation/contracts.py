"""Explicit run-wide validation profile; legacy artifacts and prompts remain reproducible.

V2 uses the existing typed output schema. Optional NFR-to-step review sidecars
remain the separate TraceCandidateV2 envelope; generators do not invent them.
"""

from __future__ import annotations

from collections import Counter

from traceable_spec.entities import (
    ActivityDiagram,
    GeneratedSpecification,
    IssueCategory,
    IssueSeverity,
    PipelineStatus,
    SpecificationRequest,
    TraceManifest,
    UseCase,
    UseCaseSet,
    ValidationIssue,
    ValidationReport,
)
from traceable_spec.evaluation.formal import FORMAL_CONTRACT_VERSION, evaluate_final_formal
from traceable_spec.evaluation.trace_contract_v2 import (
    TraceCandidateV2,
    evaluate_trace_candidate_v2,
)
from traceable_spec.llm.protocol import LLMClient
from traceable_spec.validators import (
    validate_activity_deterministic,
    validate_use_case_set_deterministic,
)

V1 = FORMAL_CONTRACT_VERSION
V2 = "common-final-v2-live-2026-09-28"
CONTRACTS = (V1, V2)
V2_RULES = (
    "Trace contract: " + V2 + ". "
    "A service edge may have empty related_step_ids ONLY when both endpoints exist, "
    "it has no guard and no label, its source is not a decision, and its source is "
    "initial or its target is final. All other edges and action/decision nodes "
    "need UC step references, or unsupported=true only for genuinely inferred content. "
    "Do not mark supported content unsupported merely to pass validation. "
    "IDs must be unique; references must exist; decisions need guarded branches and "
    "nodes must be reachable. Each step source_fr_ids must be within its UC source_fr_ids "
    "and contain only FR IDs, never NFR IDs. Put applicable NFR IDs in UC source_nfr_ids; "
    "these must exist in the input. Do not put NFRs into source_fr_ids. "
    "NFR-to-step annotations are an optional separate review envelope, not fields in "
    "this JSON schema. A trace link does not prove NFR satisfaction. "
    "Apply this same contract when generating, reviewing and repairing."
)


def require_contract(contract: str) -> str:
    if contract not in CONTRACTS:
        raise ValueError(f"Unknown formal contract: {contract}")
    return contract


def contract_messages(messages: list[dict[str, str]], contract: str) -> list[dict[str, str]]:
    require_contract(contract)
    if contract == V1:
        return messages
    replacements = {
        "each action/decision node and each edge must list related_step_ids from the UC": (
            "each action/decision node and each non-service edge must list "
            "related_step_ids from the UC"
        ),
        "related_step_ids on every activity action/decision and edge": (
            "related_step_ids on every activity action/decision and non-service edge"
        ),
        "related_step_ids on activity actions, decisions and edges": (
            "related_step_ids on activity actions, decisions and non-service edges"
        ),
    }
    result = []
    for message in messages:
        current = dict(message)
        if current["role"] == "system":
            for old, new in replacements.items():
                current["content"] = current["content"].replace(old, new)
            current["content"] += "\n" + V2_RULES
        result.append(current)
    return result


class ContractClient:
    def __init__(self, client: LLMClient, contract: str):
        self.client, self.contract = client, require_contract(contract)

    def complete(self, *, messages, model=None, temperature=None, response_format=None) -> str:
        return self.client.complete(
            messages=contract_messages(messages, self.contract),
            model=model,
            temperature=temperature,
            response_format=response_format,
        )


def contract_client(client: LLMClient, contract: str) -> LLMClient:
    require_contract(contract)
    if isinstance(client, ContractClient):
        if client.contract != contract:
            raise ValueError("Cannot mix validation contracts in one client")
        return client
    return client if contract == V1 else ContractClient(client, contract)


def evaluate_contract(spec: GeneratedSpecification, contract: str = V1) -> ValidationReport:
    require_contract(contract)
    if contract == V1:
        return evaluate_final_formal(spec)
    report = evaluate_trace_candidate_v2(TraceCandidateV2(specification=spec))
    return report.model_copy(
        update={
            "validator_name": V2,
            "details": {
                **report.details,
                "generation_profile_available": True,
                "generation_loops_migrated": True,
                "nfr_step_sidecar_generation": False,
            },
        }
    )


def with_contract_validation(spec: GeneratedSpecification, contract: str = V1):
    # Preserve the exact legacy report/serialization path for existing evidence.
    if require_contract(contract) == V1:
        from traceable_spec.evaluation.formal import with_common_final_validation

        return with_common_final_validation(spec)
    report = evaluate_contract(spec, contract)
    return spec.model_copy(
        update={
            "status": PipelineStatus.SUCCESS if report.passed else PipelineStatus.FAILED,
            "failure_reason": None if report.passed else "Common final v2 validation failed",
            "validation_reports": [*spec.validation_reports, report],
            "evaluation_report": None,
        }
    )


def validate_activity_contract(diagram: ActivityDiagram, uc: UseCase, contract: str = V1):
    report = validate_activity_deterministic(diagram, uc)
    if require_contract(contract) == V1:
        return report
    nodes = {n.id: n for n in diagram.nodes}
    ids = [diagram.id, *[n.id for n in diagram.nodes], *[e.id for e in diagram.edges]]
    duplicates = {i for i, n in Counter(ids).items() if n > 1}
    eligible = {
        e.id
        for e in diagram.edges
        if e.source_node_id in nodes
        and e.target_node_id in nodes
        and not e.guard
        and not e.label
        and nodes[e.source_node_id].kind.value != "decision"
        and (
            nodes[e.source_node_id].kind.value == "initial"
            or nodes[e.target_node_id].kind.value == "final"
        )
        and e.id not in duplicates
    }
    issues = [
        i
        for i in report.issues
        if not (
            i.code == "activity_edge_untraced" and i.element_ids and set(i.element_ids) <= eligible
        )
    ]
    if duplicates:
        issues.append(
            ValidationIssue(
                id="VI-001",
                severity=IssueSeverity.ERROR,
                category=IssueCategory.TRACE,
                code="v2_duplicate_activity_id",
                message="Activity identifiers must be unambiguous",
                element_ids=sorted(duplicates),
            )
        )
    return ValidationReport(
        passed=not any(i.blocking for i in issues),
        issues=issues,
        validator_name="activity_deterministic_v2",
        details={"contract_version": V2},
    )


def validate_uc_contract(
    ucs: UseCaseSet, request: SpecificationRequest, trace: TraceManifest, contract: str = V1
):
    report = validate_use_case_set_deterministic(ucs, request, trace)
    if require_contract(contract) == V1:
        return report
    known = {n.id for n in request.non_functional_requirements}
    issues = list(report.issues)
    for uc in ucs.use_cases:
        unknown = sorted(set(uc.source_nfr_ids) - known)
        if unknown:
            issues.append(
                ValidationIssue(
                    id=f"VI-{len(issues) + 1:03d}",
                    severity=IssueSeverity.ERROR,
                    category=IssueCategory.TRACE,
                    code="v2_unknown_uc_nfr",
                    message="UC references unknown NFRs",
                    element_ids=[uc.id, *unknown],
                )
            )
    return ValidationReport(
        passed=not any(i.blocking for i in issues),
        issues=issues,
        validator_name="uc_deterministic_v2",
        details={"contract_version": V2},
    )
