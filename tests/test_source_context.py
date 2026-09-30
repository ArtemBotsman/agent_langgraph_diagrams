"""Information-flow regression tests; scripted answers are not quality evidence."""

import json

import pytest

from traceable_spec.agents.activity.graph import activity_nodes_with_llm
from traceable_spec.agents.use_case.graph import use_case_nodes_with_llm
from traceable_spec.entities import (
    ActivityGenerationArtifact,
    UseCaseGenerationArtifact,
    ValidationIssue,
    ValidationReport,
)
from traceable_spec.evaluation.contracts import V2
from traceable_spec.llm.scripted import ScriptedLLMClient
from traceable_spec.orchestration.pipeline import compile_live_pipeline
from traceable_spec.prompts.activities import (
    build_activity_critic_messages,
    build_activity_generator_messages,
    build_activity_repair_messages,
)
from traceable_spec.prompts.source_context import SOURCE_CONTEXT_VERSION, source_context
from traceable_spec.prompts.use_cases import (
    build_use_case_critic_messages,
    build_use_case_generator_messages,
    build_use_case_repair_messages,
)
from traceable_spec.reference_methods import run_decomposed_baseline
from traceable_spec.testing.fixtures import (
    sample_activity_diagram,
    sample_request,
    sample_use_case_set,
)


class RecordingClient(ScriptedLLMClient):
    def __init__(self):
        uc = UseCaseGenerationArtifact(use_case_set=sample_use_case_set()).model_dump_json()
        ad = ActivityGenerationArtifact(
            activity_diagram=sample_activity_diagram()
        ).model_dump_json()
        super().__init__(
            {
                "use_case_generator": [uc],
                "use_case_repair": [uc],
                "use_case_critic": ['{"decision":"accept"}'],
                "activity_generator": [ad],
                "activity_repair": [ad],
                "activity_critic": ['{"decision":"accept"}'],
            }
        )
        self.messages = []

    def complete(self, **kwargs):
        self.messages.append(kwargs["messages"])
        return super().complete(**kwargs)


def request():
    r = sample_request()
    r.project_description = 'Exact interface and constructor facts; "return" is not "print".'
    r.metadata = {"gold": "SECRET_EVALUATOR_VALUE", "answer": "DO_NOT_SEND"}
    return r


def assert_context(messages):
    text = messages[1]["content"]
    r = request()
    for source in [
        r.project_description,
        *[x.text for x in r.functional_requirements],
        *[x.text for x in r.non_functional_requirements],
    ]:
        assert json.dumps(source, ensure_ascii=False)[1:-1] in text
    assert SOURCE_CONTEXT_VERSION in text
    assert "SECRET_EVALUATOR_VALUE" not in text and "DO_NOT_SEND" not in text


@pytest.mark.parametrize("role", range(6))
def test_all_six_roles_receive_original_input_without_metadata(role):
    r, ucs, diagram = request(), sample_use_case_set(), sample_activity_diagram()
    uc = ucs.use_cases[0]
    builders = [
        lambda: build_use_case_generator_messages(r),
        lambda: build_use_case_critic_messages(r, ucs, []),
        lambda: build_use_case_repair_messages(r, ucs, [], 1),
        lambda: build_activity_generator_messages(uc, ucs.actors, request=r),
        lambda: build_activity_critic_messages(uc, diagram, [], request=r),
        lambda: build_activity_repair_messages(uc, diagram, [], 1, request=r),
    ]
    messages = builders[role]()
    assert_context(messages)
    assert "source-review-v2" in messages[0]["content"]
    assert "necessity or plausibility alone" in messages[0]["content"]
    assert "not the entire main scenario" in messages[0]["content"]


@pytest.mark.parametrize("method", ["full", "decomposed"])
def test_root_and_plain_decomposition_pass_identical_sources(method):
    client = RecordingClient()
    if method == "full":
        result = compile_live_pipeline(client, contract_version=V2).invoke({"request": request()})
        assert result["specification"].status.value == "success"
    else:
        result = run_decomposed_baseline(request(), client, contract_version=V2)
        assert result.status.value == "success"
    assert len(client.messages) == (4 if method == "full" else 2)
    for messages in client.messages:
        assert_context(messages)


def test_repair_nodes_keep_context():
    client = RecordingClient()
    uc_nodes, ad_nodes = use_case_nodes_with_llm(client), activity_nodes_with_llm(client)
    uc_nodes.repair_use_case_set({"request": request(), "use_case_set": sample_use_case_set()})
    ad_nodes.repair_activity_model(
        {"request": request(), "use_case": sample_use_case_set().use_cases[0]}
    )
    assert len(client.messages) == 2
    for messages in client.messages:
        assert_context(messages)


def test_activity_without_request_remains_backwards_compatible():
    ucs = sample_use_case_set()
    messages = build_activity_generator_messages(ucs.use_cases[0], ucs.actors)
    assert "original_specification" not in json.loads(messages[1]["content"])


def test_upstream_conflict_does_not_trigger_irrelevant_activity_repairs():
    nodes = activity_nodes_with_llm(RecordingClient())
    issue = ValidationIssue(
        id="VI-001",
        severity="error",
        category="semantic",
        code="SOURCE_UC_CONFLICT",
        message="FR-001 contradicts the UC step",
        element_ids=["FR-001", "STEP-UC001-001"],
        blocking=True,
    )
    state = {
        "request": request(),
        "critic_report": ValidationReport(
            passed=False, issues=[issue], validator_name="activity_llm_critic"
        ),
        "max_repair_attempts": 2,
    }
    decision = nodes.decide_activity_result(state)
    assert decision["decision"] == "fail"
    failure = nodes.fail_activity_generation({**state, **decision})
    assert "Upstream Use Case" in failure["failure_reason"]


def test_context_is_exact_input_only_and_does_not_mutate_request():
    r = request()
    before = r.model_dump_json()
    c = source_context(r)
    assert c["project_description"] == r.project_description
    assert len(c["functional_requirements"]) == 2
    assert len(c["non_functional_requirements"]) == 1
    assert r.model_dump_json() == before


class SequenceRecordingClient(ScriptedLLMClient):
    def __init__(self, scripts):
        super().__init__(scripts)
        self.messages = []

    def complete(self, **kwargs):
        self.messages.append(kwargs["messages"])
        return super().complete(**kwargs)


@pytest.mark.parametrize("kind", ["use_case", "activity"])
def test_critic_receives_latest_artifact_and_original_source_after_repair(kind):
    ucs, diagram = sample_use_case_set(), sample_activity_diagram()
    state = {"request": request(), "use_case": ucs.use_cases[0], "actors": ucs.actors}
    if kind == "use_case":
        before = UseCaseGenerationArtifact(use_case_set=ucs)
        after = before.model_copy(deep=True)
        after.use_case_set.use_cases[0].name = "Updated UC after repair"
        field = "use_case_set"
    else:
        before = ActivityGenerationArtifact(activity_diagram=diagram)
        after = before.model_copy(deep=True)
        after.activity_diagram.name = "Updated Activity after repair"
        field = "activity_diagram"
    client = SequenceRecordingClient(
        {
            kind + "_generator": [before.model_dump_json()],
            kind + "_repair": [after.model_dump_json()],
            kind + "_critic": ['{"decision":"accept"}', '{"decision":"accept"}'],
        }
    )
    nodes = (
        use_case_nodes_with_llm(client) if kind == "use_case" else activity_nodes_with_llm(client)
    )
    if kind == "use_case":
        generate, criticize, repair = (
            nodes.generate_use_case_set,
            nodes.criticize_use_case_set,
            nodes.repair_use_case_set,
        )
    else:
        generate, criticize, repair = (
            nodes.generate_activity_model,
            nodes.criticize_activity_model,
            nodes.repair_activity_model,
        )
    state.update(generate(state))
    first = state[field].model_dump(mode="json")
    state.update(criticize(state))
    state.update(repair(state))
    latest = state[field].model_dump(mode="json")
    state.update(criticize(state))
    assert first != latest
    assert json.loads(client.messages[1][1]["content"])[field] == first
    assert json.loads(client.messages[2][1]["content"])["current_" + field] == first
    final_payload = json.loads(client.messages[3][1]["content"])
    assert final_payload[field] == latest
    assert final_payload["review_round"] == 1
    for messages in client.messages:
        assert_context(messages)


@pytest.mark.parametrize("kind", ["use_case", "activity"])
def test_missing_artifact_skips_paid_critic_and_never_accepts(kind):
    client = SequenceRecordingClient({})
    state = {"request": request(), "use_case": sample_use_case_set().use_cases[0]}
    if kind == "use_case":
        result = use_case_nodes_with_llm(client).criticize_use_case_set(state)
    else:
        result = activity_nodes_with_llm(client).criticize_activity_model(state)
    assert not result["critic_report"].passed
    assert result["critic_report"].details["decision"] == "repair"
    assert client.messages == []


def test_root_hands_repaired_uc_to_both_activity_roles_with_original_source():
    first = UseCaseGenerationArtifact(use_case_set=sample_use_case_set())
    latest = first.model_copy(deep=True)
    latest.use_case_set.use_cases[0].name = "Latest repaired Use Case"
    issue = ValidationIssue(
        id="VI-001",
        severity="error",
        category="semantic",
        code="FR_CONTRADICTION",
        message="FR-001 requires source review",
        element_ids=["FR-001", "UC-001"],
        blocking=True,
    )
    reject = json.dumps({"decision": "repair", "issues": [issue.model_dump(mode="json")]})
    client = SequenceRecordingClient(
        {
            "use_case_generator": [first.model_dump_json()],
            "use_case_repair": [latest.model_dump_json()],
            "use_case_critic": [reject, '{"decision":"accept"}'],
            "activity_generator": [
                ActivityGenerationArtifact(
                    activity_diagram=sample_activity_diagram()
                ).model_dump_json()
            ],
            "activity_critic": ['{"decision":"accept"}'],
        }
    )
    result = compile_live_pipeline(client, contract_version=V2).invoke({"request": request()})
    assert result["specification"].status.value == "success"
    assert len(client.messages) == 6
    expected = result["specification"].use_case_set.use_cases[0].model_dump(mode="json")
    for index in (4, 5):
        payload = json.loads(client.messages[index][1]["content"])
        assert payload["use_case"] == expected
        assert payload["use_case"]["name"] == "Latest repaired Use Case"
    for messages in client.messages:
        assert_context(messages)
