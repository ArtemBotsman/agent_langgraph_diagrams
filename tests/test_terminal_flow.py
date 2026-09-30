"""Offline sensitivity/repair controls; no live-model quality claim."""

import copy
import json

import pytest

from traceable_spec.entities import ActivityDiagram, ActivityGenerationArtifact
from traceable_spec.evaluation.chain_audit import audit_chain
from traceable_spec.evaluation.contracts import V2
from traceable_spec.evaluation.terminal_flow import audit_terminal_flow, validate_terminal_flow
from traceable_spec.llm.scripted import ScriptedLLMClient
from traceable_spec.orchestration.evidence_consistency import evidence_consistency_deps
from traceable_spec.orchestration.pipeline import compile_pipeline
from traceable_spec.orchestration.terminal_consistency import (
    PROFILE,
    TerminalConsistencyClient,
    terminal_consistency_deps,
)
from traceable_spec.testing.fixtures import (
    sample_activity_diagram,
    sample_request,
    sample_use_case_set,
)
from traceable_spec.validators import validate_activity_structure


def example():
    def node(number, kind):
        return {
            "id": f"ADN-UC001-{number:03d}",
            "kind": kind,
            "name": kind,
            "related_step_ids": ["STEP-UC001-001"] if kind == "action" else [],
        }

    def edge(number, source, target):
        return {
            "id": f"ADE-UC001-{number:03d}",
            "source_node_id": f"ADN-UC001-{source:03d}",
            "target_node_id": f"ADN-UC001-{target:03d}",
            "related_step_ids": ["STEP-UC001-001"],
        }

    return {
        "request": {"functional_requirements": [{"id": "FR-001", "text": "Perform action"}]},
        "use_case_set": {
            "use_cases": [
                {
                    "id": "UC-001",
                    "name": "Perform",
                    "source_fr_ids": ["FR-001"],
                    "main_success_scenario": {
                        "steps": [
                            {
                                "id": "STEP-UC001-001",
                                "action": "Perform action",
                                "source_fr_ids": ["FR-001"],
                            }
                        ]
                    },
                }
            ]
        },
        "activity_results": [
            {
                "activity_diagram": {
                    "id": "AD-UC001",
                    "use_case_id": "UC-001",
                    "name": "Perform",
                    "nodes": [node(1, "initial"), node(2, "action"), node(3, "final")],
                    "edges": [edge(1, 1, 2), edge(2, 2, 3)],
                }
            }
        ],
    }


def diagram_of(spec):
    return spec["activity_results"][0]["activity_diagram"]


def after_final(spec):
    diagram = diagram_of(spec)
    diagram["nodes"].append({"id": "ADN-UC001-004", "kind": "final", "name": "Early end"})
    diagram["edges"][0]["target_node_id"] = "ADN-UC001-004"
    diagram["edges"].append(
        {
            "id": "ADE-UC001-003",
            "source_node_id": "ADN-UC001-004",
            "target_node_id": "ADN-UC001-002",
            "label": "Illegal continuation",
            "related_step_ids": ["STEP-UC001-001"],
        }
    )


def test_valid_graph_preserves_legacy_and_never_mutates_input():
    spec = example()
    before = copy.deepcopy(spec)
    result = audit_terminal_flow(spec)
    assert spec == before
    assert result["legacy_audit"] == audit_chain(spec)
    assert (
        result["legacy_fr_with_action_chain"] == result["terminal_safe_fr_with_action_chain"] == 1
    )
    assert result["terminal_safe_chains"] == result["legacy_audit"]["chains"]
    assert result["lost_fr_ids"] == result["violations"] == []
    assert result["sensitivity_only"] and not result["official_metric_replacement"]
    assert not result["semantic_truth_verified"]


def test_action_after_final_is_false_legacy_coverage():
    spec = example()
    after_final(spec)
    before = copy.deepcopy(spec)
    result = audit_terminal_flow(spec)
    assert result["legacy_fr_with_action_chain"] == 1
    assert result["terminal_safe_fr_with_action_chain"] == 0
    assert result["lost_fr_ids"] == ["FR-001"]
    assert result["illegal_boundary_edges"][0]["edge_id"] == "ADE-UC001-003"
    assert any(v["code"] == "terminal_unreachable_from_initial" for v in result["violations"])
    assert spec == before
    # Confirm this regression represents a real gap in the old structural validator.
    typed = ActivityDiagram.model_validate(diagram_of(spec))
    assert validate_activity_structure(typed).passed
    assert not validate_terminal_flow(typed).passed


def test_alternate_valid_path_keeps_action_but_filters_illegal_edge_chain():
    spec = example()
    after_final(spec)
    diagram_of(spec)["edges"].append(
        {
            "id": "ADE-UC001-004",
            "source_node_id": "ADN-UC001-001",
            "target_node_id": "ADN-UC001-002",
            "related_step_ids": ["STEP-UC001-001"],
        }
    )
    result = audit_terminal_flow(spec)
    assert result["terminal_safe_fr_with_action_chain"] == 1
    assert result["lost_fr_ids"] == []
    assert any(c["element_id"] == "ADE-UC001-003" for c in result["discarded_chains"])
    assert all(c["element_id"] != "ADE-UC001-003" for c in result["terminal_safe_chains"])
    assert not validate_terminal_flow(ActivityDiagram.model_validate(diagram_of(spec))).passed


@pytest.mark.parametrize("same_fr", [True, False])
def test_fr_recoverage_is_global_across_distinct_diagrams(same_fr):
    spec = example()
    after_final(spec)
    other = json.loads(json.dumps(example()).replace("UC001", "UC002").replace("UC-001", "UC-002"))
    if not same_fr:
        other = json.loads(json.dumps(other).replace("FR-001", "FR-002"))
        spec["request"]["functional_requirements"].extend(
            other["request"]["functional_requirements"]
        )
    spec["use_case_set"]["use_cases"].extend(other["use_case_set"]["use_cases"])
    spec["activity_results"].extend(other["activity_results"])
    result = audit_terminal_flow(spec)
    assert result["terminal_safe_fr_with_action_chain"] == 1
    assert result["lost_fr_ids"] == ([] if same_fr else ["FR-001"])
    assert {c["uc_id"] for c in result["terminal_safe_chains"]} == {"UC-002"}


def test_incoming_initial_cannot_supply_return_path_to_final():
    spec = example()
    diagram = diagram_of(spec)
    diagram["edges"][1]["target_node_id"] = "ADN-UC001-001"
    diagram["edges"].append(
        {
            "id": "ADE-UC001-003",
            "source_node_id": "ADN-UC001-001",
            "target_node_id": "ADN-UC001-003",
            "related_step_ids": ["STEP-UC001-001"],
        }
    )
    result = audit_terminal_flow(spec)
    assert result["legacy_fr_with_action_chain"] == 1
    assert result["terminal_safe_fr_with_action_chain"] == 0
    assert {v["code"] for v in result["violations"]} == {
        "incoming_initial_edge",
        "terminal_cannot_reach_final",
    }


def test_both_boundaries_and_unreachable_object_are_validated():
    spec = example()
    diagram = ActivityDiagram.model_validate(diagram_of(spec))
    raw = diagram.model_dump(mode="json")
    raw["nodes"].append({"id": "ADN-UC001-004", "kind": "object", "name": "Detached object"})
    raw["edges"].append(
        {
            "id": "ADE-UC001-003",
            "source_node_id": "ADN-UC001-003",
            "target_node_id": "ADN-UC001-001",
        }
    )
    diagram = ActivityDiagram.model_validate(raw)
    before = diagram.model_dump()
    report = validate_terminal_flow(diagram)
    assert not report.passed
    assert {issue.code for issue in report.issues} == {
        "outgoing_final_edge",
        "incoming_initial_edge",
        "terminal_unreachable_from_initial",
        "terminal_cannot_reach_final",
    }
    assert all(issue.blocking for issue in report.issues)
    assert diagram.model_dump() == before
    spec["activity_results"][0]["activity_diagram"] = raw
    audit = audit_terminal_flow(spec)
    assert len(audit["illegal_boundary_edges"]) == 1
    assert set(audit["illegal_boundary_edges"][0]["codes"]) == {
        "outgoing_final_edge",
        "incoming_initial_edge",
    }


@pytest.mark.parametrize("defect", ["dangling", "duplicate_node", "duplicate_edge", "no_final"])
def test_malformed_references_are_safe_and_fail_closed(defect):
    spec = example()
    diagram = diagram_of(spec)
    if defect == "dangling":
        diagram["edges"][1]["target_node_id"] = "unknown"
    elif defect == "duplicate_node":
        diagram["nodes"].append(copy.deepcopy(diagram["nodes"][0]))
    elif defect == "duplicate_edge":
        diagram["edges"].append(copy.deepcopy(diagram["edges"][0]))
    else:
        diagram["nodes"][-1]["kind"] = "action"
    assert audit_terminal_flow(spec)["terminal_safe_fr_with_action_chain"] == 0
    assert not validate_terminal_flow(ActivityDiagram.model_validate(diagram)).passed


def test_empty_saved_package_has_null_rates():
    spec = {"request": {"functional_requirements": []}}
    result = audit_terminal_flow(spec)
    assert result["terminal_safe_fr_action_chain_coverage"] is None
    assert result["legacy_fr_action_chain_coverage"] is None
    assert result["terminal_safe_chains"] == []


class Recorder(ScriptedLLMClient):
    def __init__(self, generated, repaired=None):
        from traceable_spec.entities import UseCaseGenerationArtifact

        use_cases = UseCaseGenerationArtifact(use_case_set=sample_use_case_set()).model_dump_json()
        artifact = ActivityGenerationArtifact(activity_diagram=generated).model_dump_json()
        repair = ActivityGenerationArtifact(
            activity_diagram=repaired or generated
        ).model_dump_json()
        super().__init__(
            {
                "use_case_generator": [use_cases],
                "use_case_critic": ['{"decision":"accept"}'],
                "activity_generator": [artifact],
                "activity_repair": [repair],
                "activity_critic": ['{"decision":"accept"}'],
            }
        )
        self.requests = []

    def complete(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        return super().complete(**kwargs)


def malformed_sample():
    diagram = sample_activity_diagram().model_dump(mode="json")
    diagram["nodes"].append({"id": "ADN-UC001-007", "kind": "final", "name": "Early end"})
    diagram["edges"][0]["target_node_id"] = "ADN-UC001-007"
    diagram["edges"].append(
        {
            "id": "ADE-UC001-007",
            "source_node_id": "ADN-UC001-007",
            "target_node_id": "ADN-UC001-002",
            "related_step_ids": ["STEP-UC001-001"],
        }
    )
    return ActivityDiagram.model_validate(diagram)


def test_opt_in_guard_routes_to_repair_before_critic_and_keeps_history():
    raw = Recorder(malformed_sample(), sample_activity_diagram())
    request = sample_request().model_copy(update={"max_repair_attempts": 1})
    result = compile_pipeline(terminal_consistency_deps(raw)).invoke({"request": request})
    assert result["specification"].status.value == "success"
    roles = [call["role"] for call in raw.calls]
    assert roles == [
        "use_case_generator",
        "use_case_critic",
        "activity_generator",
        "activity_repair",
        "activity_critic",
    ]
    activity = result["specification"].activity_results[0]
    assert activity.repair_attempts_used == 1
    terminal_reports = [
        r for r in activity.validation_reports if r.validator_name == "activity_terminal_flow"
    ]
    assert [r.passed for r in terminal_reports] == [False, True]
    payload = json.loads(raw.requests[3]["messages"][1]["content"])
    assert "outgoing_final_edge" in {i["code"] for i in payload["issues_to_fix"]}
    assert payload["actors"][0]["name"] == "Patron"  # v1 enrichment retained
    assert all(PROFILE in c["messages"][0]["content"] for c in raw.requests)
    assert audit_terminal_flow(result["specification"])["terminal_safe_fr_with_action_chain"] == 2


def test_zero_repair_limit_blocks_without_calling_critic_or_repair():
    raw = Recorder(malformed_sample())
    request = sample_request().model_copy(update={"max_repair_attempts": 0})
    result = compile_pipeline(terminal_consistency_deps(raw)).invoke({"request": request})
    assert result["specification"].status.value != "success"
    assert [c["role"] for c in raw.calls] == [
        "use_case_generator",
        "use_case_critic",
        "activity_generator",
    ]


def test_valid_profile_adds_no_completion_and_v1_remains_unchanged():
    valid = Recorder(sample_activity_diagram())
    result = compile_pipeline(terminal_consistency_deps(valid)).invoke(
        {"request": sample_request()}
    )
    assert result["specification"].status.value == "success" and len(valid.calls) == 4
    old = Recorder(malformed_sample())
    result = compile_pipeline(evidence_consistency_deps(old, contract_version=V2)).invoke(
        {"request": sample_request()}
    )
    assert result["specification"].status.value == "success" and len(old.calls) == 4
    assert PROFILE not in json.dumps(old.requests)


def test_prompt_wrapper_preserves_arguments_response_and_input():
    class Echo:
        def complete(self, **kwargs):
            self.kwargs = kwargs
            return "EXACT ORIGINAL RESPONSE"

    raw = Echo()
    messages = [
        {"role": "system", "content": "[[llm_role:activity_generator]]"},
        {"role": "user", "content": "SOURCE"},
    ]
    before = copy.deepcopy(messages)
    response = TerminalConsistencyClient(raw).complete(
        messages=messages, model="test", temperature=0.6, response_format={"type": "json_object"}
    )
    assert response == "EXACT ORIGINAL RESPONSE" and messages == before
    assert raw.kwargs["messages"][1] == messages[1]
    assert raw.kwargs["model"] == "test" and raw.kwargs["temperature"] == 0.6
    assert raw.kwargs["response_format"] == {"type": "json_object"}
