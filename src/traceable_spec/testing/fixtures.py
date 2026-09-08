"""Shared sample builders for stubs and tests (not production fixtures)."""

from __future__ import annotations

from traceable_spec.entities import (
    ActivityDiagram,
    ActivityEdge,
    ActivityNode,
    ActivityNodeKind,
    ActivityPartition,
    Actor,
    ElementRefType,
    FunctionalRequirement,
    NonFunctionalRequirement,
    Postcondition,
    Precondition,
    RequirementCoverageStatus,
    Scenario,
    ScenarioKind,
    ScenarioStep,
    SpecificationRequest,
    SystemStory,
    TraceLink,
    TraceLinkType,
    TraceManifest,
    TraceOrigin,
    UseCase,
    UseCaseSet,
    UserStory,
)


def sample_request() -> SpecificationRequest:
    return SpecificationRequest(
        project_task="Create a small system for searching and borrowing library books.",
        project_name="Library Desk",
        project_goal="Allow patrons to borrow books",
        project_description="A small library circulation desk system.",
        functional_requirements=[
            FunctionalRequirement(id="FR-001", text="Patron can search the catalog by title"),
            FunctionalRequirement(id="FR-002", text="Patron can borrow an available book"),
        ],
        non_functional_requirements=[
            NonFunctionalRequirement(
                id="NFR-001",
                text="Borrow confirmation must complete within 3 seconds",
                category="performance",
            )
        ],
        max_repair_attempts=2,
    )


def sample_use_case_set() -> UseCaseSet:
    actor = Actor(id="ACT-001", name="Patron", is_primary=True)
    steps = [
        ScenarioStep(
            id="STEP-UC001-001",
            order=1,
            actor_id="ACT-001",
            action="Enter book title",
            expected_result="Search form accepted",
        ),
        ScenarioStep(
            id="STEP-UC001-002",
            order=2,
            actor_id="ACT-001",
            action="Select available copy and confirm borrow",
            expected_result="Loan recorded",
        ),
    ]
    uc = UseCase(
        id="UC-001",
        name="Borrow book",
        goal="Borrow an available book from the catalog",
        primary_actor_id="ACT-001",
        trigger="Patron chooses to borrow a book",
        preconditions=[
            Precondition(id="PRE-UC001-001", text="Patron is authenticated"),
        ],
        success_postconditions=[
            Postcondition(
                id="POST-UC001-001",
                text="Loan record exists",
                outcome="success",
            )
        ],
        failure_postconditions=[
            Postcondition(
                id="POST-UC001-002",
                text="No loan created",
                outcome="failure",
            )
        ],
        main_success_scenario=Scenario(
            id="SCN-UC001-MAIN-001",
            kind=ScenarioKind.MAIN,
            name="Happy path",
            steps=steps,
        ),
        alternative_scenarios=[],
        exception_scenarios=[
            Scenario(
                id="SCN-UC001-EXC-001",
                kind=ScenarioKind.EXCEPTION,
                name="Copy unavailable",
                steps=[
                    ScenarioStep(
                        id="STEP-UC001-003",
                        order=1,
                        actor_id="ACT-001",
                        action="System reports copy unavailable",
                    )
                ],
                start_from_step_id="STEP-UC001-002",
            )
        ],
        user_stories=[
            UserStory(
                id="US-001",
                role="Patron",
                capability="borrow an available book",
                benefit="I can read it off-site",
                use_case_id="UC-001",
            )
        ],
        system_stories=[
            SystemStory(
                id="SS-001",
                system_action="Create loan record",
                responsibility="Persist loan and mark copy as borrowed",
                use_case_id="UC-001",
            )
        ],
        source_fr_ids=["FR-001", "FR-002"],
        source_nfr_ids=["NFR-001"],
    )
    return UseCaseSet(
        actors=[actor],
        use_cases=[uc],
        fr_coverage={
            "FR-001": RequirementCoverageStatus.COVERED,
            "FR-002": RequirementCoverageStatus.COVERED,
        },
    )


def sample_activity_diagram() -> ActivityDiagram:
    return ActivityDiagram(
        id="AD-UC001",
        use_case_id="UC-001",
        name="Borrow book flow",
        partitions=[
            ActivityPartition(id="PART-UC001-001", name="Patron", actor_id="ACT-001"),
            ActivityPartition(id="PART-UC001-002", name="System", actor_id=None),
        ],
        nodes=[
            ActivityNode(
                id="ADN-UC001-001",
                kind=ActivityNodeKind.INITIAL,
                name="start",
                partition_id="PART-UC001-001",
            ),
            ActivityNode(
                id="ADN-UC001-002",
                kind=ActivityNodeKind.ACTION,
                name="Enter title",
                partition_id="PART-UC001-001",
                related_step_ids=["STEP-UC001-001"],
            ),
            ActivityNode(
                id="ADN-UC001-003",
                kind=ActivityNodeKind.DECISION,
                name="Copy available?",
                partition_id="PART-UC001-002",
                related_step_ids=["STEP-UC001-002"],
            ),
            ActivityNode(
                id="ADN-UC001-004",
                kind=ActivityNodeKind.ACTION,
                name="Create loan",
                partition_id="PART-UC001-002",
                related_step_ids=["STEP-UC001-002"],
            ),
            ActivityNode(
                id="ADN-UC001-005",
                kind=ActivityNodeKind.ACTION,
                name="Report unavailable",
                partition_id="PART-UC001-002",
                related_step_ids=["STEP-UC001-003"],
            ),
            ActivityNode(
                id="ADN-UC001-006",
                kind=ActivityNodeKind.FINAL,
                name="end",
                partition_id="PART-UC001-002",
            ),
        ],
        edges=[
            ActivityEdge(
                id="ADE-UC001-001",
                source_node_id="ADN-UC001-001",
                target_node_id="ADN-UC001-002",
            ),
            ActivityEdge(
                id="ADE-UC001-002",
                source_node_id="ADN-UC001-002",
                target_node_id="ADN-UC001-003",
            ),
            ActivityEdge(
                id="ADE-UC001-003",
                source_node_id="ADN-UC001-003",
                target_node_id="ADN-UC001-004",
                guard="yes",
            ),
            ActivityEdge(
                id="ADE-UC001-004",
                source_node_id="ADN-UC001-003",
                target_node_id="ADN-UC001-005",
                guard="no",
            ),
            ActivityEdge(
                id="ADE-UC001-005",
                source_node_id="ADN-UC001-004",
                target_node_id="ADN-UC001-006",
            ),
            ActivityEdge(
                id="ADE-UC001-006",
                source_node_id="ADN-UC001-005",
                target_node_id="ADN-UC001-006",
            ),
        ],
    )


def sample_uc_trace_manifest() -> TraceManifest:
    """Trace links available after Use Case stage (no activity endpoints yet)."""
    return TraceManifest(
        links=[
            TraceLink(
                id="TL-001",
                source_type=ElementRefType.FR,
                source_id="FR-001",
                target_type=ElementRefType.UC,
                target_id="UC-001",
                link_type=TraceLinkType.FR_TO_UC,
                origin=TraceOrigin.DETERMINISTIC,
            ),
            TraceLink(
                id="TL-002",
                source_type=ElementRefType.FR,
                source_id="FR-002",
                target_type=ElementRefType.UC,
                target_id="UC-001",
                link_type=TraceLinkType.FR_TO_UC,
                origin=TraceOrigin.DETERMINISTIC,
            ),
            TraceLink(
                id="TL-003",
                source_type=ElementRefType.UC,
                source_id="UC-001",
                target_type=ElementRefType.US,
                target_id="US-001",
                link_type=TraceLinkType.UC_TO_US,
                origin=TraceOrigin.DETERMINISTIC,
            ),
            TraceLink(
                id="TL-004",
                source_type=ElementRefType.UC,
                source_id="UC-001",
                target_type=ElementRefType.SS,
                target_id="SS-001",
                link_type=TraceLinkType.UC_TO_SS,
                origin=TraceOrigin.DETERMINISTIC,
            ),
        ]
    )


def sample_activity_trace_links() -> list[TraceLink]:
    return [
        TraceLink(
            id="TL-010",
            source_type=ElementRefType.STEP,
            source_id="STEP-UC001-001",
            target_type=ElementRefType.ACTIVITY_NODE,
            target_id="ADN-UC001-002",
            link_type=TraceLinkType.STEP_TO_ACTIVITY_NODE,
            origin=TraceOrigin.DETERMINISTIC,
        ),
        TraceLink(
            id="TL-011",
            source_type=ElementRefType.UC,
            source_id="UC-001",
            target_type=ElementRefType.ACTIVITY,
            target_id="AD-UC001",
            link_type=TraceLinkType.UC_TO_ACTIVITY,
            origin=TraceOrigin.DETERMINISTIC,
        ),
    ]


def sample_trace_manifest() -> TraceManifest:
    """Full sample trace after UC + activity stages."""
    base = sample_uc_trace_manifest()
    return TraceManifest(links=[*base.links, *sample_activity_trace_links()])
