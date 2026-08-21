"""Contract tests for models, validators, graphs, and Mermaid renderer.

All tests are offline: no network and no LLM calls.
"""

from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from traceable_spec.activity_diagram_graph import compile_activity_diagram_graph
from traceable_spec.entities import (
    ActivityDiagram,
    ActivityEdge,
    ActivityNode,
    ActivityNodeKind,
    ElementRefType,
    FunctionalRequirement,
    SpecificationRequest,
    TraceLink,
    TraceLinkType,
    TraceManifest,
    TraceOrigin,
    UseCase,
)
from traceable_spec.graph import compile_pipeline
from traceable_spec.mermaid import render_mermaid
from traceable_spec.testing.fixtures import (
    sample_activity_diagram,
    sample_request,
    sample_uc_trace_manifest,
    sample_use_case_set,
)
from traceable_spec.use_cases_graph import compile_use_cases_graph
from traceable_spec.validators import (
    validate_activity_structure,
    validate_fr_coverage,
    validate_repair_limit,
    validate_trace_integrity,
    validate_unique_ids,
    validate_use_case_structure,
)


def test_specification_request_valid() -> None:
    req = sample_request()
    assert req.project_name == "Library Desk"
    assert len(req.functional_requirements) == 2


def test_specification_request_rejects_unknown_fields() -> None:
    data = sample_request().model_dump()
    data["unexpected_field"] = "nope"
    with pytest.raises(ValidationError):
        SpecificationRequest.model_validate(data)


def test_pydantic_roundtrip() -> None:
    req = sample_request()
    restored = SpecificationRequest.model_validate(req.model_dump())
    assert restored == req
    uc_set = sample_use_case_set()
    assert UseCase.model_validate(uc_set.use_cases[0].model_dump()).id == "UC-001"
    diagram = sample_activity_diagram()
    assert ActivityDiagram.model_validate(diagram.model_dump()).id == "AD-UC001"


def test_duplicate_ids_detected() -> None:
    uc_set = sample_use_case_set()
    # Duplicate actor id via second actor clone
    uc_set.actors.append(uc_set.actors[0].model_copy())
    report = validate_unique_ids(uc_set)
    assert not report.passed
    assert any(issue.code == "duplicate_id" for issue in report.issues)


def test_dangling_trace_links() -> None:
    report = validate_trace_integrity(
        known_ids={"FR-001", "UC-001"},
        trace=TraceManifest(
            links=[
                TraceLink(
                    id="TL-099",
                    source_type=ElementRefType.FR,
                    source_id="FR-001",
                    target_type=ElementRefType.UC,
                    target_id="UC-999",
                    link_type=TraceLinkType.FR_TO_UC,
                    origin=TraceOrigin.LLM,
                )
            ]
        ),
    )
    assert not report.passed
    assert any(issue.code == "dangling_trace_target" for issue in report.issues)


def test_uncovered_fr() -> None:
    uc_set = sample_use_case_set()
    report = validate_fr_coverage(["FR-001", "FR-002", "FR-003"], uc_set)
    assert not report.passed
    assert any(
        issue.code == "fr_uncovered" and "FR-003" in issue.message
        for issue in report.issues
    )


def test_uc_without_fr_source() -> None:
    uc_set = sample_use_case_set()
    broken = uc_set.use_cases[0].model_copy(update={"source_fr_ids": ["FR-001"]})
    # Bypass pydantic min_length by constructing via model_copy then clearing through object
    object.__setattr__(broken, "source_fr_ids", [])
    uc_set = uc_set.model_copy(update={"use_cases": [broken]})
    report = validate_use_case_structure(uc_set)
    assert not report.passed
    assert any(issue.code == "uc_without_fr" for issue in report.issues)


def test_activity_edge_unknown_node() -> None:
    diagram = sample_activity_diagram()
    bad_edge = ActivityEdge(
        id="ADE-UC001-099",
        source_node_id="ADN-UC001-001",
        target_node_id="ADN-UC001-999",
    )
    diagram = diagram.model_copy(update={"edges": [*diagram.edges, bad_edge]})
    report = validate_activity_structure(diagram)
    assert not report.passed
    assert any(issue.code == "unknown_edge_target" for issue in report.issues)


def test_unreachable_final_node() -> None:
    diagram = ActivityDiagram(
        id="AD-UC001",
        use_case_id="UC-001",
        name="Broken",
        nodes=[
            ActivityNode(id="ADN-UC001-001", kind=ActivityNodeKind.INITIAL, name="start"),
            ActivityNode(
                id="ADN-UC001-002",
                kind=ActivityNodeKind.ACTION,
                name="Do",
                related_step_ids=["STEP-UC001-001"],
            ),
            ActivityNode(id="ADN-UC001-003", kind=ActivityNodeKind.FINAL, name="end"),
        ],
        edges=[
            ActivityEdge(
                id="ADE-UC001-001",
                source_node_id="ADN-UC001-001",
                target_node_id="ADN-UC001-002",
            ),
            # final not connected
        ],
    )
    report = validate_activity_structure(diagram)
    assert not report.passed
    assert any(issue.code == "final_unreachable" for issue in report.issues)


def test_repair_limit_exceeded() -> None:
    report = validate_repair_limit(attempt=3, max_attempts=2)
    assert not report.passed
    assert any(issue.code == "repair_limit_exceeded" for issue in report.issues)


def test_compile_use_cases_graph_with_stubs() -> None:
    graph = compile_use_cases_graph()
    assert graph is not None
    result = graph.invoke({"request": sample_request()})
    assert result["status"].value == "success"
    assert result["use_case_set"] is not None


def test_compile_activity_graph_with_stubs() -> None:
    uc_set = sample_use_case_set()
    graph = compile_activity_diagram_graph()
    result = graph.invoke(
        {
            "use_case": uc_set.use_cases[0],
            "actors": uc_set.actors,
            "max_repair_attempts": 2,
            "trace_manifest": sample_uc_trace_manifest(),
        }
    )
    assert result["status"].value == "success"
    assert result["activity_diagram"] is not None
    assert result["mermaid_source"]
    assert result["mermaid_source"].startswith("flowchart TD")


def test_compile_pipeline_graph() -> None:
    graph = compile_pipeline()
    result = graph.invoke({"request": sample_request()})
    spec = result["specification"]
    assert spec is not None
    assert spec.use_case_set is not None
    assert len(spec.activity_results) == 1
    assert spec.evaluation_report is not None


def test_mermaid_renderer_deterministic() -> None:
    diagram = sample_activity_diagram()
    first = render_mermaid(diagram)
    second = render_mermaid(copy.deepcopy(diagram))
    assert first == second
    assert "flowchart TD" in first
    assert "ADN-UC001-003" in first


def test_functional_requirement_id_pattern() -> None:
    with pytest.raises(ValidationError):
        FunctionalRequirement(id="F-1", text="bad id")
