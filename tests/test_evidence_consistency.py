"""Offline information-flow controls; NOT live model performance measurements."""

import copy
import json

import pytest

from traceable_spec.entities import (
    ActivityGenerationArtifact,
    UseCaseGenerationArtifact,
    ValidationIssue,
    ValidationReport,
)
from traceable_spec.evaluation.contracts import V2
from traceable_spec.llm.scripted import ScriptedLLMClient
from traceable_spec.orchestration.evidence_consistency import (
    PROFILE,
    EvidenceConsistencyClient,
    current_attempt_reports,
    current_feedback_only,
    evidence_consistency_deps,
)
from traceable_spec.orchestration.pipeline import compile_pipeline, live_pipeline_deps
from traceable_spec.testing.fixtures import (
    sample_activity_diagram,
    sample_request,
    sample_use_case_set,
)


class Recorder(ScriptedLLMClient):
    def __init__(self):
        u = UseCaseGenerationArtifact(use_case_set=sample_use_case_set()).model_dump_json()
        a = ActivityGenerationArtifact(activity_diagram=sample_activity_diagram()).model_dump_json()
        super().__init__(
            {
                "use_case_generator": [u],
                "use_case_repair": [u, u],
                "use_case_critic": ['{"decision":"accept"}'],
                "activity_generator": [a],
                "activity_repair": [a, a],
                "activity_critic": ['{"decision":"accept"}'],
            }
        )
        self.requests = []

    def complete(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        return super().complete(**kwargs)


def report(name, code=None, passed=True):
    return ValidationReport(
        validator_name=name,
        passed=passed,
        issues=[]
        if code is None
        else [
            ValidationIssue(
                id="VI-001",
                code=code,
                severity="error",
                category="semantic",
                message=code,
                element_ids=["FR-001"],
                blocking=True,
            )
        ],
    )


@pytest.mark.parametrize("kind", ["uc", "activity"])
def test_current_feedback_keeps_history_but_not_obsolete_issues(kind):
    history = [
        report(kind + "_generator_parse"),
        report("det", "OBSOLETE", False),
        report(kind + "_repair_parse"),
        report("det", "CURRENT", False),
    ]
    before = copy.deepcopy(history)
    captured = []
    new_parse = report(kind + "_repair_parse")

    def node(state):
        captured.extend(state["validation_reports"])
        return {"validation_reports": state["validation_reports"] + [new_parse]}

    result = current_feedback_only(node, kind)({"validation_reports": history})
    assert [i.code for r in captured for i in r.issues] == ["CURRENT"]
    assert history == before
    assert result["validation_reports"] == history + [new_parse]


@pytest.mark.parametrize("kind", ["uc", "activity"])
def test_real_repair_builder_receives_only_current_feedback(kind):
    h = [
        report(kind + "_generator_parse"),
        report("det", "OBSOLETE", False),
        report(kind + "_repair_parse"),
        report("det", "CURRENT", False),
    ]
    state = {
        "request": sample_request(),
        "use_case_set": sample_use_case_set(),
        "use_case": sample_use_case_set().use_cases[0],
        "activity_diagram": sample_activity_diagram(),
        "actors": sample_use_case_set().actors,
        "validation_reports": h,
        "repair_attempt": 1,
    }
    old, new = Recorder(), Recorder()
    deps0, deps1 = live_pipeline_deps(old, contract_version=V2), evidence_consistency_deps(new)
    for deps in (deps0, deps1):
        (
            deps.use_case_nodes.repair_use_case_set
            if kind == "uc"
            else deps.activity_nodes.repair_activity_model
        )(state)
    old_payload, new_payload = [
        json.loads(c.requests[0]["messages"][1]["content"]) for c in (old, new)
    ]
    assert [i["code"] for i in old_payload["issues_to_fix"]] == ["OBSOLETE", "CURRENT"]
    assert [i["code"] for i in new_payload["issues_to_fix"]] == ["CURRENT"]


def test_parse_failure_is_kept_and_boundary_absence_is_conservative():
    failed = report("uc_repair_parse", "INVALID_JSON", False)
    history = [report("uc_generator_parse"), report("det", "OLD", False), failed]
    assert current_attempt_reports(history, "uc") == [failed]
    assert current_attempt_reports(history[1:2], "uc") == history[1:2]
    with pytest.raises(ValueError):
        current_attempt_reports(history, "unknown")


def test_history_replacement_by_node_fails_closed():
    with pytest.raises(ValueError):
        current_feedback_only(lambda state: {"validation_reports": []}, "uc")(
            {"validation_reports": [report("det")]}
        )


def test_persistent_issue_is_not_suppressed_as_a_duplicate():
    history = [
        report("uc_generator_parse"),
        report("det", "PERSISTS", False),
        report("uc_repair_parse"),
        report("det", "PERSISTS", False),
    ]
    active = current_attempt_reports(history, "uc")
    assert [issue.code for r in active for issue in r.issues] == ["PERSISTS"]


@pytest.mark.parametrize(
    "role",
    [
        "use_case_generator",
        "use_case_critic",
        "use_case_repair",
        "activity_generator",
        "activity_critic",
        "activity_repair",
    ],
)
def test_six_roles_have_rules_and_unchanged_payload_and_settings(role):
    class Echo:
        def complete(self, **kwargs):
            self.kwargs = kwargs
            return "EXACT_RESPONSE"

    raw = Echo()
    messages = [
        {"role": "system", "content": "[[llm_role:" + role + "]]"},
        {"role": "user", "content": '{"original":"SOURCE"}'},
    ]
    before = copy.deepcopy(messages)
    result = EvidenceConsistencyClient(raw).complete(
        messages=messages, temperature=0.7, model="test"
    )
    assert result == "EXACT_RESPONSE" and messages == before
    assert PROFILE in raw.kwargs["messages"][0]["content"]
    assert raw.kwargs["messages"][1] == messages[1]
    assert raw.kwargs["temperature"] == 0.7 and raw.kwargs["model"] == "test"


def test_opt_in_root_works_and_metadata_is_not_sent():
    raw = Recorder()
    request = sample_request()
    request.metadata = {"gold": "SECRET_EVALUATION_ANSWER"}
    result = compile_pipeline(evidence_consistency_deps(raw)).invoke({"request": request})
    assert result["specification"].status.value == "success"
    assert len(raw.requests) == 4  # no extra hidden calls
    assert "SECRET_EVALUATION_ANSWER" not in json.dumps(raw.requests)
    for call in raw.requests:
        assert PROFILE in call["messages"][0]["content"]
    critic = json.loads(raw.requests[-1]["messages"][1]["content"])
    assert critic["actors"][0]["name"] == "Patron"


def test_activity_reviewer_and_repair_get_actual_actor_dictionary_without_cache():
    raw = Recorder()
    nodes = evidence_consistency_deps(raw).activity_nodes
    actors = sample_use_case_set().actors
    state = {
        "request": sample_request(),
        "use_case": sample_use_case_set().use_cases[0],
        "activity_diagram": sample_activity_diagram(),
        "actors": actors,
    }
    nodes.criticize_activity_model(state)
    changed = actors[0].model_copy(update={"name": "A different actor"})
    nodes.repair_activity_model({**state, "actors": [changed]})
    payloads = [json.loads(c["messages"][1]["content"]) for c in raw.requests]
    assert payloads[0]["actors"][0]["name"] == "Patron"
    assert payloads[1]["actors"][0]["name"] == "A different actor"
    assert actors[0].name == "Patron"


def test_legacy_profile_unchanged_and_no_new_acceptance_rule():
    raw = Recorder()
    result = compile_pipeline(live_pipeline_deps(raw, contract_version=V2)).invoke(
        {"request": sample_request()}
    )
    assert result["specification"].status.value == "success"
    assert PROFILE not in json.dumps(raw.requests)
