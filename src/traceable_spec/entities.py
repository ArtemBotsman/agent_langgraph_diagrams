"""Domain contracts: Pydantic input/output models and LangGraph TypedDict states.

Source of truth for activity diagrams is ActivityDiagram; Mermaid is a derived view.
Trace links live only in TraceManifest; forward/reverse indexes are derived.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Literal, Required, TypedDict, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    """Base for key pipeline contracts: reject unknown fields."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class RequirementCoverageStatus(str, Enum):
    COVERED = "covered"
    PARTIALLY_COVERED = "partially_covered"
    UNCOVERED = "uncovered"
    OUT_OF_SCOPE = "out_of_scope"
    CONFLICTING = "conflicting"


class ScenarioKind(str, Enum):
    MAIN = "main"
    ALTERNATIVE = "alternative"
    EXCEPTION = "exception"


class ActivityNodeKind(str, Enum):
    INITIAL = "initial"
    FINAL = "final"
    ACTION = "action"
    DECISION = "decision"
    MERGE = "merge"
    FORK = "fork"
    JOIN = "join"
    OBJECT = "object"


class TraceOrigin(str, Enum):
    LLM = "llm"
    DETERMINISTIC = "deterministic"
    HUMAN = "human"
    REPAIR = "repair"


class TraceLinkType(str, Enum):
    FR_TO_ATOM = "fr_to_atom"
    ATOM_TO_UC = "atom_to_uc"
    ATOM_TO_STEP = "atom_to_step"
    FR_TO_UC = "fr_to_uc"
    FR_TO_STEP = "fr_to_step"
    UC_TO_US = "uc_to_us"
    UC_TO_SS = "uc_to_ss"
    STEP_TO_ACTIVITY_NODE = "step_to_activity_node"
    STEP_TO_ACTIVITY_EDGE = "step_to_activity_edge"
    UC_TO_ACTIVITY = "uc_to_activity"
    NFR_TO_UC = "nfr_to_uc"
    UNSUPPORTED = "unsupported"


class IssueSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class IssueCategory(str, Enum):
    SCHEMA = "schema"
    STRUCTURAL = "structural"
    TRACE = "trace"
    SEMANTIC = "semantic"
    REPAIR = "repair"
    POLICY = "policy"


class PipelineStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class ElementRefType(str, Enum):
    FR = "fr"
    FR_ATOM = "fr_atom"
    NFR = "nfr"
    UC = "uc"
    US = "us"
    SS = "ss"
    STEP = "step"
    ACTOR = "actor"
    ACTIVITY = "activity"
    ACTIVITY_NODE = "activity_node"
    ACTIVITY_EDGE = "activity_edge"
    PRECONDITION = "precondition"
    POSTCONDITION = "postcondition"


# ---------------------------------------------------------------------------
# Requirements / request
# ---------------------------------------------------------------------------


class FunctionalRequirementAtom(StrictModel):
    """Smallest conservatively extracted, independently traceable FR clause."""

    id: str = Field(pattern=r"^FRA-\d{3,}-\d{3,}$")
    parent_fr_id: str = Field(pattern=r"^FR-\d{3,}$")
    text: str = Field(min_length=1)
    extraction_rule: Literal["whole_requirement", "semicolon", "line_or_list"]


class FunctionalRequirement(StrictModel):
    id: str = Field(pattern=r"^FR-\d{3,}$")
    text: str = Field(min_length=1)
    priority: str | None = None
    tags: list[str] = Field(default_factory=list)
    atoms: list[FunctionalRequirementAtom] = Field(default_factory=list)


class NonFunctionalRequirement(StrictModel):
    id: str = Field(pattern=r"^NFR-\d{3,}$")
    text: str = Field(min_length=1)
    category: str | None = None
    tags: list[str] = Field(default_factory=list)


class SpecificationReq(TypedDict):
    """External pipeline input agreed with the research supervisor.

    This boundary contract mirrors the JSON supplied by the supervisor. The
    pipeline normalizes its string requirements into stable FR/NFR entities
    before any generation node runs.
    """

    project_task: str
    project_name: str
    project_goal: str
    project_description: str
    functional_requirements: list[str]
    non_functional_requirements: list[str]


class SpecificationRequest(StrictModel):
    """Normalized internal request with stable requirement identifiers."""

    project_task: str = Field(min_length=1)
    project_name: str = Field(min_length=1)
    project_goal: str = Field(min_length=1)
    project_description: str = Field(min_length=1)
    functional_requirements: list[FunctionalRequirement] = Field(min_length=1)
    non_functional_requirements: list[NonFunctionalRequirement] = Field(default_factory=list)
    max_repair_attempts: int = Field(default=2, ge=0, le=10)
    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("functional_requirements")
    @classmethod
    def unique_fr_ids(cls, value: list[FunctionalRequirement]) -> list[FunctionalRequirement]:
        ids = [item.id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("functional requirement IDs must be unique")
        return value

    @field_validator("non_functional_requirements")
    @classmethod
    def unique_nfr_ids(
        cls, value: list[NonFunctionalRequirement]
    ) -> list[NonFunctionalRequirement]:
        ids = [item.id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("non-functional requirement IDs must be unique")
        return value


SpecificationInput = SpecificationReq | SpecificationRequest


_LIST_MARKER_RE = re.compile(r"(?:^|\n)\s*(?:[-*•]|\d+[.)])\s+")


def atomize_functional_requirement(
    requirement: FunctionalRequirement,
) -> FunctionalRequirement:
    """Conservatively split an FR only at explicit list/line or semicolon boundaries.

    Coordinating words such as ``and`` / ``и`` are intentionally not split: doing
    that without a parser can change business meaning. A requirement that has no
    explicit boundary remains one atom, so every FR is still traceable.
    """

    if requirement.atoms:
        return requirement
    text = requirement.text.strip()
    extraction_rule: Literal["whole_requirement", "semicolon", "line_or_list"]
    if "\n" in text or _LIST_MARKER_RE.search(text):
        normalized = _LIST_MARKER_RE.sub("\n", text)
        parts = [part.strip(" \t\r\n-•") for part in normalized.splitlines() if part.strip()]
        extraction_rule = "line_or_list"
    elif ";" in text:
        parts = [part.strip() for part in text.split(";") if part.strip()]
        extraction_rule = "semicolon"
    else:
        parts = [text]
        extraction_rule = "whole_requirement"
    fr_number = requirement.id.removeprefix("FR-")
    atoms = [
        FunctionalRequirementAtom(
            id=f"FRA-{fr_number}-{index:03d}",
            parent_fr_id=requirement.id,
            text=part,
            extraction_rule=extraction_rule,
        )
        for index, part in enumerate(parts, start=1)
    ]
    return requirement.model_copy(update={"atoms": atoms})


def ensure_requirement_atoms(request: SpecificationRequest) -> SpecificationRequest:
    """Return a request in which every functional requirement has ≥1 atom."""

    return request.model_copy(
        update={
            "functional_requirements": [
                atomize_functional_requirement(requirement)
                for requirement in request.functional_requirements
            ]
        }
    )


def normalize_specification_req(value: SpecificationInput) -> SpecificationRequest:
    """Convert the supervisor-facing ``SpecificationReq`` into the internal model.

    The external JSON deliberately contains plain strings. Stable identifiers
    are assigned deterministically by list order so identical inputs normalize
    to identical contracts.
    """

    if isinstance(value, SpecificationRequest):
        return ensure_requirement_atoms(value)
    if not isinstance(value, dict):
        raise TypeError("SpecificationReq must be a mapping or SpecificationRequest")
    raw = cast(dict[str, object], value)

    expected_fields = {
        "project_task",
        "project_name",
        "project_goal",
        "project_description",
        "functional_requirements",
        "non_functional_requirements",
    }
    actual_fields = set(raw)
    missing_fields = sorted(expected_fields - actual_fields)
    unexpected_fields = sorted(actual_fields - expected_fields)
    if missing_fields:
        raise ValueError(f"SpecificationReq is missing fields: {', '.join(missing_fields)}")
    if unexpected_fields:
        raise ValueError(f"SpecificationReq has unexpected fields: {', '.join(unexpected_fields)}")

    text_fields = (
        "project_task",
        "project_name",
        "project_goal",
        "project_description",
    )
    normalized_text: dict[str, str] = {}
    for field_name in text_fields:
        field_value = raw[field_name]
        if not isinstance(field_value, str) or not field_value.strip():
            raise ValueError(f"SpecificationReq.{field_name} must be a non-empty string")
        normalized_text[field_name] = field_value.strip()

    def normalize_requirement_list(field_name: str) -> list[str]:
        items = raw[field_name]
        if not isinstance(items, list) or any(
            not isinstance(item, str) or not item.strip() for item in items
        ):
            raise ValueError(f"SpecificationReq.{field_name} must be a list of strings")
        return [item.strip() for item in items]

    functional_requirements = normalize_requirement_list("functional_requirements")
    non_functional_requirements = normalize_requirement_list("non_functional_requirements")

    request = SpecificationRequest(
        project_task=normalized_text["project_task"],
        project_name=normalized_text["project_name"],
        project_goal=normalized_text["project_goal"],
        project_description=normalized_text["project_description"],
        functional_requirements=[
            FunctionalRequirement(id=f"FR-{index:03d}", text=text)
            for index, text in enumerate(functional_requirements, start=1)
        ],
        non_functional_requirements=[
            NonFunctionalRequirement(id=f"NFR-{index:03d}", text=text)
            for index, text in enumerate(non_functional_requirements, start=1)
        ],
        metadata={"source_contract": "SpecificationReq"},
    )
    return ensure_requirement_atoms(request)


# ---------------------------------------------------------------------------
# Use Case building blocks
# ---------------------------------------------------------------------------


class Actor(StrictModel):
    id: str = Field(pattern=r"^ACT-\d{3,}$")
    name: str
    description: str | None = None
    is_primary: bool = False


class Precondition(StrictModel):
    id: str = Field(pattern=r"^PRE-[A-Z0-9]+-\d{3,}$")
    text: str


class Postcondition(StrictModel):
    id: str = Field(pattern=r"^POST-[A-Z0-9]+-\d{3,}$")
    text: str
    outcome: Literal["success", "failure"]


class UserStory(StrictModel):
    """Actor-facing need: As a <role>, I want <capability>, so that <benefit>.

    Not a scenario step. Links to a Use Case via TraceManifest (uc_to_us).
    """

    id: str = Field(pattern=r"^US-\d{3,}$")
    role: str
    capability: str
    benefit: str
    use_case_id: str = Field(pattern=r"^UC-\d{3,}$")


class SystemStory(StrictModel):
    """System-side responsibility that realizes part of a Use Case.

    Not a scenario step. Distinct from UserStory: focuses on system behaviour,
    not stakeholder phrasing.
    """

    id: str = Field(pattern=r"^SS-\d{3,}$")
    system_action: str
    responsibility: str
    use_case_id: str = Field(pattern=r"^UC-\d{3,}$")


class ScenarioStep(StrictModel):
    id: str = Field(pattern=r"^STEP-UC\d{3,}-\d{3,}$")
    order: int = Field(ge=1)
    actor_id: str | None = None
    action: str
    expected_result: str | None = None
    source_fr_ids: list[str] = Field(default_factory=list)


class Scenario(StrictModel):
    id: str = Field(pattern=r"^SCN-UC\d{3,}-[A-Z]+-\d{3,}$")
    kind: ScenarioKind
    name: str
    steps: list[ScenarioStep] = Field(min_length=1)
    start_from_step_id: str | None = None
    rejoins_step_id: str | None = None


class MissingInformation(StrictModel):
    id: str = Field(pattern=r"^MI-\d{3,}$")
    description: str
    related_element_ids: list[str] = Field(default_factory=list)
    blocks_generation: bool = False


class UnsupportedAssumption(StrictModel):
    id: str = Field(pattern=r"^UA-\d{3,}$")
    description: str
    related_element_ids: list[str] = Field(default_factory=list)
    justified: bool = False


class UseCase(StrictModel):
    id: str = Field(pattern=r"^UC-\d{3,}$")
    name: str
    goal: str
    primary_actor_id: str
    secondary_actor_ids: list[str] = Field(default_factory=list)
    trigger: str
    preconditions: list[Precondition] = Field(default_factory=list)
    success_postconditions: list[Postcondition] = Field(default_factory=list)
    failure_postconditions: list[Postcondition] = Field(default_factory=list)
    main_success_scenario: Scenario
    alternative_scenarios: list[Scenario] = Field(default_factory=list)
    exception_scenarios: list[Scenario] = Field(default_factory=list)
    user_stories: list[UserStory] = Field(default_factory=list)
    system_stories: list[SystemStory] = Field(default_factory=list)
    source_fr_ids: list[str] = Field(min_length=1)
    source_nfr_ids: list[str] = Field(default_factory=list)
    missing_information: list[MissingInformation] = Field(default_factory=list)
    unsupported_assumptions: list[UnsupportedAssumption] = Field(default_factory=list)
    human_readable_text: str | None = None

    @field_validator("main_success_scenario")
    @classmethod
    def main_must_be_main(cls, value: Scenario) -> Scenario:
        if value.kind != ScenarioKind.MAIN:
            raise ValueError("main_success_scenario.kind must be 'main'")
        return value


class UseCaseSet(StrictModel):
    actors: list[Actor] = Field(default_factory=list)
    use_cases: list[UseCase] = Field(default_factory=list)
    fr_coverage: dict[str, RequirementCoverageStatus] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Activity diagram
# ---------------------------------------------------------------------------


class ActivityPartition(StrictModel):
    id: str = Field(pattern=r"^PART-UC\d{3,}-\d{3,}$")
    name: str
    actor_id: str | None = None


class ActivityNode(StrictModel):
    id: str = Field(pattern=r"^ADN-UC\d{3,}-\d{3,}$")
    kind: ActivityNodeKind
    name: str
    partition_id: str | None = None
    related_step_ids: list[str] = Field(default_factory=list)
    unsupported: bool = False


class ActivityEdge(StrictModel):
    id: str = Field(pattern=r"^ADE-UC\d{3,}-\d{3,}$")
    source_node_id: str
    target_node_id: str
    guard: str | None = None
    label: str | None = None
    related_step_ids: list[str] = Field(default_factory=list)
    unsupported: bool = False


class ActivityDiagram(StrictModel):
    id: str = Field(pattern=r"^AD-UC\d{3,}$")
    use_case_id: str = Field(pattern=r"^UC-\d{3,}$")
    name: str
    partitions: list[ActivityPartition] = Field(default_factory=list)
    nodes: list[ActivityNode] = Field(min_length=2)
    edges: list[ActivityEdge] = Field(default_factory=list)
    mermaid_source: str | None = None


# ---------------------------------------------------------------------------
# Traceability
# ---------------------------------------------------------------------------


class TraceLink(StrictModel):
    id: str = Field(pattern=r"^TL-\d{3,}$")
    source_type: ElementRefType
    source_id: str
    target_type: ElementRefType
    target_id: str
    link_type: TraceLinkType
    origin: TraceOrigin
    rationale: str | None = None


class TraceManifest(StrictModel):
    """Single store for trace links. Indexes are derived, not duplicated."""

    links: list[TraceLink] = Field(default_factory=list)

    def forward_index(self) -> dict[str, list[TraceLink]]:
        index: dict[str, list[TraceLink]] = {}
        for link in self.links:
            index.setdefault(link.source_id, []).append(link)
        return index

    def reverse_index(self) -> dict[str, list[TraceLink]]:
        index: dict[str, list[TraceLink]] = {}
        for link in self.links:
            index.setdefault(link.target_id, []).append(link)
        return index


# ---------------------------------------------------------------------------
# Validation / evaluation
# ---------------------------------------------------------------------------


class ValidationIssue(StrictModel):
    id: str = Field(pattern=r"^VI-\d{3,}$")
    severity: IssueSeverity
    category: IssueCategory
    code: str
    message: str
    element_ids: list[str] = Field(default_factory=list)
    blocking: bool = True


class ValidationReport(StrictModel):
    passed: bool
    issues: list[ValidationIssue] = Field(default_factory=list)
    validator_name: str
    details: dict[str, Any] = Field(default_factory=dict)

    @property
    def blocking_issues(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.blocking]


class MetricResult(StrictModel):
    name: str
    value: float | int | bool | str | None
    higher_is_better: bool | None = None
    unit: str | None = None
    notes: str | None = None


class EvaluationReport(StrictModel):
    metrics: list[MetricResult] = Field(default_factory=list)
    automatic_only: bool = True
    notes: str | None = None


# ---------------------------------------------------------------------------
# Pipeline outputs
# ---------------------------------------------------------------------------


class ActivityGenerationResult(StrictModel):
    use_case_id: str
    activity_diagram: ActivityDiagram | None = None
    status: PipelineStatus
    validation_reports: list[ValidationReport] = Field(default_factory=list)
    repair_attempts_used: int = 0
    failure_reason: str | None = None


class GeneratedSpecification(StrictModel):
    request: SpecificationRequest
    use_case_set: UseCaseSet | None = None
    activity_results: list[ActivityGenerationResult] = Field(default_factory=list)
    trace_manifest: TraceManifest = Field(default_factory=TraceManifest)
    validation_reports: list[ValidationReport] = Field(default_factory=list)
    evaluation_report: EvaluationReport | None = None
    uc_repair_attempts_used: int = 0
    status: PipelineStatus = PipelineStatus.FAILED
    failure_reason: str | None = None


# ---------------------------------------------------------------------------
# Graph I/O schemas (Pydantic) and State (TypedDict)
# ---------------------------------------------------------------------------


class UseCaseGenerationArtifact(StrictModel):
    """Structured generator/repair JSON payload (UseCaseSet + TraceManifest)."""

    use_case_set: UseCaseSet
    trace_manifest: TraceManifest = Field(default_factory=TraceManifest)


class ActivityGenerationArtifact(StrictModel):
    """Structured generator/repair payload for one activity diagram."""

    activity_diagram: ActivityDiagram
    trace_manifest: TraceManifest = Field(default_factory=TraceManifest)


class OneShotGenerationArtifact(StrictModel):
    """B1 payload: complete semantic artifacts returned by exactly one LLM call."""

    use_case_set: UseCaseSet
    activity_diagrams: list[ActivityDiagram]
    trace_manifest: TraceManifest = Field(default_factory=TraceManifest)


class CriticVerdict(StrictModel):
    """Structured critic response. Critic ≠ deterministic validator."""

    decision: Literal["accept", "repair"]
    issues: list[ValidationIssue] = Field(default_factory=list)
    summary: str | None = None


class UseCaseGraphInput(StrictModel):
    request: SpecificationRequest


class UseCaseGraphOutput(StrictModel):
    use_case_set: UseCaseSet | None = None
    trace_manifest: TraceManifest = Field(default_factory=TraceManifest)
    validation_reports: list[ValidationReport] = Field(default_factory=list)
    status: PipelineStatus
    repair_attempts_used: int = 0
    failure_reason: str | None = None


class ActivityGraphInput(StrictModel):
    use_case: UseCase
    actors: list[Actor] = Field(default_factory=list)
    max_repair_attempts: int = Field(default=2, ge=0, le=10)
    existing_trace: TraceManifest = Field(default_factory=TraceManifest)


class ActivityGraphOutput(StrictModel):
    result: ActivityGenerationResult
    trace_manifest: TraceManifest = Field(default_factory=TraceManifest)


class PipelineGraphInput(StrictModel):
    request: SpecificationRequest


class PipelineGraphOutput(StrictModel):
    specification: GeneratedSpecification


class UseCaseGraphState(TypedDict, total=False):
    request: Required[SpecificationRequest]
    normalized_frs: list[FunctionalRequirement]
    normalized_nfrs: list[NonFunctionalRequirement]
    use_case_set: UseCaseSet | None
    trace_manifest: TraceManifest
    schema_report: ValidationReport | None
    deterministic_report: ValidationReport | None
    critic_report: ValidationReport | None
    validation_reports: list[ValidationReport]
    repair_attempt: int
    max_repair_attempts: int
    decision: Literal["finalize", "repair", "fail"]
    status: PipelineStatus
    failure_reason: str | None


class ActivityGraphState(TypedDict, total=False):
    use_case: Required[UseCase]
    actors: list[Actor]
    activity_diagram: ActivityDiagram | None
    trace_manifest: TraceManifest
    schema_report: ValidationReport | None
    deterministic_report: ValidationReport | None
    critic_report: ValidationReport | None
    validation_reports: list[ValidationReport]
    repair_attempt: int
    max_repair_attempts: int
    decision: Literal["finalize", "repair", "fail"]
    mermaid_source: str | None
    status: PipelineStatus
    failure_reason: str | None


class PipelineGraphState(TypedDict, total=False):
    request: Required[SpecificationInput]
    normalized_frs: list[FunctionalRequirement]
    normalized_nfrs: list[NonFunctionalRequirement]
    use_case_set: UseCaseSet | None
    activity_results: list[ActivityGenerationResult]
    trace_manifest: TraceManifest
    validation_reports: list[ValidationReport]
    evaluation_report: EvaluationReport | None
    specification: GeneratedSpecification | None
    status: PipelineStatus
    failure_reason: str | None
    max_repair_attempts: int
    uc_repair_attempts_used: int
