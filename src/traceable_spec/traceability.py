"""Deterministic materialization of trace links from typed artifact references.

The LLM chooses semantic references (for example ``UseCase.source_fr_ids`` and
``ActivityNode.related_step_ids``). Python turns those references into one
canonical ``TraceManifest``. This avoids asking a model to duplicate the same
relationship in two independently editable places.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from traceable_spec.entities import (
    ActivityDiagram,
    ElementRefType,
    ScenarioStep,
    SpecificationRequest,
    TraceLink,
    TraceLinkType,
    TraceManifest,
    TraceOrigin,
    UseCase,
    UseCaseSet,
)


@dataclass(frozen=True, order=True)
class DeclaredRelation:
    link_type: TraceLinkType
    source_type: ElementRefType
    source_id: str
    target_type: ElementRefType
    target_id: str
    rationale: str


def iter_use_case_steps(use_case: UseCase) -> Iterable[ScenarioStep]:
    """Yield every main, alternative and exception scenario step."""

    yield from use_case.main_success_scenario.steps
    for scenario in use_case.alternative_scenarios + use_case.exception_scenarios:
        yield from scenario.steps


def inherit_step_sources(use_case_set: UseCaseSet) -> UseCaseSet:
    """Fill absent step-level FR references from the containing UC scope.

    This is a conservative fallback. The rationale in the generated trace link
    records that the mapping is inherited rather than explicitly selected by a
    model or a human reviewer.
    """

    for use_case in use_case_set.use_cases:
        for step in iter_use_case_steps(use_case):
            if not step.source_fr_ids:
                step.source_fr_ids = list(use_case.source_fr_ids)
    return use_case_set


def declared_relations(
    request: SpecificationRequest,
    use_case_set: UseCaseSet,
    diagrams: Iterable[ActivityDiagram] = (),
) -> list[DeclaredRelation]:
    """Return all trace relationships declared by the typed artifacts."""

    relations: set[DeclaredRelation] = set()
    atom_ids_by_fr = {
        requirement.id: [atom.id for atom in requirement.atoms]
        for requirement in request.functional_requirements
    }
    for requirement in request.functional_requirements:
        for atom in requirement.atoms:
            relations.add(
                DeclaredRelation(
                    TraceLinkType.FR_TO_ATOM,
                    ElementRefType.FR,
                    requirement.id,
                    ElementRefType.FR_ATOM,
                    atom.id,
                    "Atom extracted conservatively from its parent functional requirement.",
                )
            )

    for use_case in use_case_set.use_cases:
        for fr_id in use_case.source_fr_ids:
            relations.add(
                DeclaredRelation(
                    TraceLinkType.FR_TO_UC,
                    ElementRefType.FR,
                    fr_id,
                    ElementRefType.UC,
                    use_case.id,
                    "Use Case explicitly declares this functional requirement as a source.",
                )
            )
            for atom_id in atom_ids_by_fr.get(fr_id, []):
                relations.add(
                    DeclaredRelation(
                        TraceLinkType.ATOM_TO_UC,
                        ElementRefType.FR_ATOM,
                        atom_id,
                        ElementRefType.UC,
                        use_case.id,
                        "Requirement atom inherits the explicit FR-to-UC assignment.",
                    )
                )
        for nfr_id in use_case.source_nfr_ids:
            relations.add(
                DeclaredRelation(
                    TraceLinkType.NFR_TO_UC,
                    ElementRefType.NFR,
                    nfr_id,
                    ElementRefType.UC,
                    use_case.id,
                    "Use Case explicitly declares this non-functional requirement as a source.",
                )
            )
        for user_story in use_case.user_stories:
            relations.add(
                DeclaredRelation(
                    TraceLinkType.UC_TO_US,
                    ElementRefType.UC,
                    use_case.id,
                    ElementRefType.US,
                    user_story.id,
                    "User story belongs to the Use Case declared in its contract.",
                )
            )
        for system_story in use_case.system_stories:
            relations.add(
                DeclaredRelation(
                    TraceLinkType.UC_TO_SS,
                    ElementRefType.UC,
                    use_case.id,
                    ElementRefType.SS,
                    system_story.id,
                    "System story belongs to the Use Case declared in its contract.",
                )
            )
        for step in iter_use_case_steps(use_case):
            inherited = not step.source_fr_ids
            step_fr_ids = step.source_fr_ids or use_case.source_fr_ids
            rationale_suffix = "inherited from the containing UC" if inherited else "explicit"
            for fr_id in step_fr_ids:
                relations.add(
                    DeclaredRelation(
                        TraceLinkType.FR_TO_STEP,
                        ElementRefType.FR,
                        fr_id,
                        ElementRefType.STEP,
                        step.id,
                        f"Step-level requirement source is {rationale_suffix}.",
                    )
                )
                for atom_id in atom_ids_by_fr.get(fr_id, []):
                    relations.add(
                        DeclaredRelation(
                            TraceLinkType.ATOM_TO_STEP,
                            ElementRefType.FR_ATOM,
                            atom_id,
                            ElementRefType.STEP,
                            step.id,
                            f"Atomic step source is {rationale_suffix}.",
                        )
                    )

    use_case_ids = {use_case.id for use_case in use_case_set.use_cases}
    for diagram in diagrams:
        if diagram.use_case_id in use_case_ids:
            relations.add(
                DeclaredRelation(
                    TraceLinkType.UC_TO_ACTIVITY,
                    ElementRefType.UC,
                    diagram.use_case_id,
                    ElementRefType.ACTIVITY,
                    diagram.id,
                    "Activity diagram declares its source Use Case.",
                )
            )
        for node in diagram.nodes:
            for step_id in node.related_step_ids:
                relations.add(
                    DeclaredRelation(
                        TraceLinkType.STEP_TO_ACTIVITY_NODE,
                        ElementRefType.STEP,
                        step_id,
                        ElementRefType.ACTIVITY_NODE,
                        node.id,
                        "Activity node explicitly references a scenario step.",
                    )
                )
        for edge in diagram.edges:
            for step_id in edge.related_step_ids:
                relations.add(
                    DeclaredRelation(
                        TraceLinkType.STEP_TO_ACTIVITY_EDGE,
                        ElementRefType.STEP,
                        step_id,
                        ElementRefType.ACTIVITY_EDGE,
                        edge.id,
                        "Activity edge explicitly references a scenario step.",
                    )
                )
    return sorted(relations)


def materialize_trace_manifest(
    request: SpecificationRequest,
    use_case_set: UseCaseSet,
    diagrams: Iterable[ActivityDiagram] = (),
    *,
    existing: TraceManifest | None = None,
) -> TraceManifest:
    """Build one stable manifest while retaining explicit unsupported links.

    Typed artifact references are authoritative. Existing ``UNSUPPORTED`` links
    are retained because they carry explicit provenance that cannot be inferred
    from the normal typed references.
    """

    diagram_items = list(diagrams)
    declared = declared_relations(request, use_case_set, diagram_items)
    links: list[TraceLink] = [
        TraceLink(
            id=f"TL-{index:03d}",
            source_type=relation.source_type,
            source_id=relation.source_id,
            target_type=relation.target_type,
            target_id=relation.target_id,
            link_type=relation.link_type,
            origin=TraceOrigin.DETERMINISTIC,
            rationale=relation.rationale,
        )
        for index, relation in enumerate(declared, start=1)
    ]
    known_by_type: dict[ElementRefType, set[str]] = {
        ElementRefType.FR: {item.id for item in request.functional_requirements},
        ElementRefType.FR_ATOM: {
            atom.id
            for requirement in request.functional_requirements
            for atom in requirement.atoms
        },
        ElementRefType.NFR: {item.id for item in request.non_functional_requirements},
        ElementRefType.ACTOR: {item.id for item in use_case_set.actors},
        ElementRefType.UC: {item.id for item in use_case_set.use_cases},
        ElementRefType.US: {
            item.id for use_case in use_case_set.use_cases for item in use_case.user_stories
        },
        ElementRefType.SS: {
            item.id for use_case in use_case_set.use_cases for item in use_case.system_stories
        },
        ElementRefType.STEP: {
            item.id for use_case in use_case_set.use_cases for item in iter_use_case_steps(use_case)
        },
        ElementRefType.PRECONDITION: {
            item.id for use_case in use_case_set.use_cases for item in use_case.preconditions
        },
        ElementRefType.POSTCONDITION: {
            item.id
            for use_case in use_case_set.use_cases
            for item in [*use_case.success_postconditions, *use_case.failure_postconditions]
        },
        ElementRefType.ACTIVITY: {item.id for item in diagram_items},
        ElementRefType.ACTIVITY_NODE: {
            node.id for item in diagram_items for node in item.nodes
        },
        ElementRefType.ACTIVITY_EDGE: {
            edge.id for item in diagram_items for edge in item.edges
        },
    }
    unsupported = [
        link
        for link in (existing or TraceManifest()).links
        if link.link_type == TraceLinkType.UNSUPPORTED
        and link.source_id in known_by_type.get(link.source_type, set())
        and link.target_id in known_by_type.get(link.target_type, set())
    ]
    for link in unsupported:
        links.append(link.model_copy(update={"id": f"TL-{len(links) + 1:03d}"}))
    return TraceManifest(links=links)
