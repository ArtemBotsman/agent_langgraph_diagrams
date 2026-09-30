"""Counterexamples, not a model-quality experiment."""

import pytest

from traceable_spec.entities import ActivityNodeKind, OneShotGenerationArtifact, PipelineStatus
from traceable_spec.evaluation.formal import evaluate_final_formal
from traceable_spec.evaluation.trace_contract_v2 import (
    StepNFRSources,
    TraceCandidateV2,
    evaluate_trace_candidate_v2,
    materialize_nfr_step_links,
)
from traceable_spec.llm.scripted import ScriptedLLMClient
from traceable_spec.prompts.one_shot import ROLE_ONE_SHOT
from traceable_spec.reference_methods import run_one_shot_baseline
from traceable_spec.testing.fixtures import (
    sample_activity_diagram,
    sample_request,
    sample_use_case_set,
)
from traceable_spec.traceability import materialize_trace_manifest


def candidate():
    artifact = OneShotGenerationArtifact(
        use_case_set=sample_use_case_set(), activity_diagrams=[sample_activity_diagram()]
    )
    spec = run_one_shot_baseline(
        sample_request(), ScriptedLLMClient({ROLE_ONE_SHOT: [artifact.model_dump_json()]})
    )
    return TraceCandidateV2(specification=spec)


def refresh(c):
    spec = c.specification
    spec.trace_manifest = materialize_trace_manifest(
        spec.request,
        spec.use_case_set,
        [r.activity_diagram for r in spec.activity_results if r.activity_diagram],
    )


def codes(c):
    return {i.code for i in evaluate_trace_candidate_v2(c).issues if i.blocking}


def untrace_entry(c):
    diagram = c.specification.activity_results[0].activity_diagram
    entry = next(n.id for n in diagram.nodes if n.kind.value == "initial")
    edge = next(e for e in diagram.edges if e.source_node_id == entry)
    edge.related_step_ids = []
    edge.guard = None
    edge.label = None
    refresh(c)
    return edge


def test_boundary_exception_preserves_v1_and_input():
    c = candidate()
    untrace_entry(c)
    before = c.model_dump_json()
    old = evaluate_final_formal(c.specification).model_dump_json()
    assert not evaluate_final_formal(c.specification).passed
    assert evaluate_trace_candidate_v2(c).passed
    assert c.model_dump_json() == before
    assert evaluate_final_formal(c.specification).model_dump_json() == old


@pytest.mark.parametrize("mutation", ["guard", "label", "endpoint", "reference", "duplicate"])
def test_exception_cannot_hide_other_errors(mutation):
    c = candidate()
    e = untrace_entry(c)
    if mutation == "guard":
        e.guard = "approved"
    elif mutation == "label":
        e.label = "cancel"
    elif mutation == "endpoint":
        e.target_node_id = "ADN-UC001-999"
    elif mutation == "reference":
        e.related_step_ids = ["STEP-UC001-999"]
    else:
        c.specification.activity_results[0].activity_diagram.edges.append(e.model_copy(deep=True))
    refresh(c)
    assert not evaluate_trace_candidate_v2(c).passed


def test_internal_edge_still_requires_a_step():
    c = candidate()
    diagram = c.specification.activity_results[0].activity_diagram
    nodes = {n.id: n for n in diagram.nodes}
    e = next(
        e
        for e in diagram.edges
        if nodes[e.source_node_id].kind.value == "action"
        and nodes[e.target_node_id].kind.value != "final"
    )
    e.related_step_ids = []
    refresh(c)
    assert "activity_edge_untraced" in codes(c)


def test_decision_to_final_is_not_a_service_edge():
    c = candidate()
    d = c.specification.activity_results[0].activity_diagram
    e = untrace_entry(c)
    source = next(n for n in d.nodes if n.id == e.source_node_id)
    source.kind = ActivityNodeKind.DECISION
    e.target_node_id = next(n.id for n in d.nodes if n.kind.value == "final")
    refresh(c)
    assert "activity_edge_untraced" in codes(c)


def add_nfr(c):
    uc = c.specification.use_case_set.use_cases[0]
    uc.source_nfr_ids = ["NFR-001"]
    c.step_nfr_sources = [
        StepNFRSources(
            use_case_id=uc.id,
            step_id=uc.main_success_scenario.steps[-1].id,
            source_nfr_ids=["NFR-001"],
            rationale="Confirmation timing applies to this step.",
        )
    ]
    c.nfr_step_links = materialize_nfr_step_links(c.step_nfr_sources)
    refresh(c)


def test_typed_nfr_link_valid_but_does_not_prove_performance():
    c = candidate()
    add_nfr(c)
    report = evaluate_trace_candidate_v2(c)
    assert report.passed
    assert report.details["nfr_step_link_count"] == 1
    assert report.details["nfr_satisfaction_measured"] is False


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("unknown", "v2_unknown_step_nfr"),
        ("scope", "v2_step_nfr_outside_uc_scope"),
        ("step", "v2_unknown_nfr_target"),
        ("uc", "v2_unknown_nfr_target"),
        ("missing_link", "v2_nfr_links_mismatch"),
        ("duplicate", "v2_duplicate_step_nfr_assignment"),
        ("rationale", "v2_schema_invalid"),
        ("wrong_fr_type", "step_fr_outside_uc_scope"),
    ],
)
def test_nfr_errors_remain_blocking(mutation, code):
    c = candidate()
    add_nfr(c)
    s = c.step_nfr_sources[0]
    if mutation == "unknown":
        s.source_nfr_ids = ["NFR-999"]
    elif mutation == "scope":
        c.specification.use_case_set.use_cases[0].source_nfr_ids = []
    elif mutation == "step":
        s.step_id = "STEP-UC001-999"
    elif mutation == "uc":
        s.use_case_id = "UC-999"
    elif mutation == "missing_link":
        c.nfr_step_links = []
    elif mutation == "duplicate":
        c.step_nfr_sources.append(s.model_copy(deep=True))
    elif mutation == "rationale":
        s.rationale = " "
    else:
        c.specification.use_case_set.use_cases[0].main_success_scenario.steps[
            0
        ].source_fr_ids.append("NFR-001")
    refresh(c)
    assert code in codes(c)


@pytest.mark.parametrize("status", ["success", "failed", "partial"])
def test_internal_status_is_irrelevant(status):
    c = candidate()
    c.specification.status = PipelineStatus(status)
    assert evaluate_trace_candidate_v2(c).passed
