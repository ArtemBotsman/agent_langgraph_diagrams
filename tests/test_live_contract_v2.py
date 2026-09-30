"""Run every method and every LLM role through an explicit trace contract."""

import json

import pytest

from traceable_spec.agents.activity.graph import (
    activity_nodes_with_llm,
    build_activity_diagram_graph,
)
from traceable_spec.agents.use_case.graph import build_use_cases_graph, use_case_nodes_with_llm
from traceable_spec.entities import (
    ActivityGenerationArtifact,
    OneShotGenerationArtifact,
    UseCaseGenerationArtifact,
)
from traceable_spec.evaluation.contracts import (
    V1,
    V2,
    contract_client,
    evaluate_contract,
    validate_activity_contract,
)
from traceable_spec.evaluation.trace_contract_v2 import (
    TraceCandidateV2,
    evaluate_trace_candidate_v2,
)
from traceable_spec.llm.scripted import ScriptedLLMClient
from traceable_spec.orchestration.pipeline import compile_live_pipeline
from traceable_spec.reference_methods import (
    run_decomposed_baseline,
    run_one_shot_baseline,
    run_validator_feedback_baseline,
)
from traceable_spec.testing.fixtures import (
    sample_activity_diagram,
    sample_request,
    sample_use_case_set,
)


class Client(ScriptedLLMClient):
    def __init__(self, scripts):
        super().__init__(scripts)
        self.messages = []

    def complete(self, **kwargs):
        self.messages.append(kwargs["messages"])
        return super().complete(**kwargs)


def boundary_artifact():
    diagram = sample_activity_diagram()
    initial = next(n.id for n in diagram.nodes if n.kind.value == "initial")
    edge = next(e for e in diagram.edges if e.source_node_id == initial)
    edge.related_step_ids, edge.guard, edge.label = [], None, None
    return OneShotGenerationArtifact(
        use_case_set=sample_use_case_set(), activity_diagrams=[diagram]
    )


def scripts(a):
    return {
        "one_shot_generator": [a.model_dump_json()],
        "one_shot_validator_feedback_repair": [a.model_dump_json()] * 2,
        "use_case_generator": [
            UseCaseGenerationArtifact(use_case_set=a.use_case_set).model_dump_json()
        ],
        "use_case_critic": ['{"decision":"accept"}'] * 3,
        "use_case_repair": [
            UseCaseGenerationArtifact(use_case_set=a.use_case_set).model_dump_json()
        ]
        * 2,
        "activity_generator": [
            ActivityGenerationArtifact(activity_diagram=a.activity_diagrams[0]).model_dump_json()
        ],
        "activity_critic": ['{"decision":"accept"}'] * 3,
        "activity_repair": [
            ActivityGenerationArtifact(activity_diagram=a.activity_diagrams[0]).model_dump_json()
        ]
        * 2,
    }


@pytest.mark.parametrize("method", ["oneshot", "feedback1", "feedback2", "decomposed", "full"])
@pytest.mark.parametrize("contract", [V1, V2])
def test_boundary_rule_in_all_methods(method, contract):
    a = boundary_artifact()
    client = Client(scripts(a))
    kw = {"contract_version": contract}
    if method == "oneshot":
        spec = run_one_shot_baseline(sample_request(), client, common_final_validation=True, **kw)
    elif method.startswith("feedback"):
        result = run_validator_feedback_baseline(
            sample_request(),
            client,
            max_repair_attempts=int(method[-1]),
            common_final_validation=True,
            **kw,
        )
        spec = result.specification
        assert len(result.attempts) == (1 if contract == V2 else 1 + int(method[-1]))
    elif method == "decomposed":
        spec = run_decomposed_baseline(sample_request(), client, **kw)
        assert len(client.calls) == 2
    else:
        state = compile_live_pipeline(client, **kw).invoke({"request": sample_request()})
        assert state["formal_contract"] == contract
        spec = state["specification"]
        if contract == V2:
            assert spec.activity_results[0].repair_attempts_used == 0
            assert len(client.calls) == 4
    assert evaluate_contract(spec, contract).passed == (contract == V2)
    for messages in client.messages:
        assert (V2 in messages[0]["content"]) == (contract == V2)
    if contract == V2:
        assert evaluate_trace_candidate_v2(TraceCandidateV2(specification=spec)).passed


@pytest.mark.parametrize(
    "change", ["guard", "label", "unknown_step", "unknown_endpoint", "duplicate", "business_edge"]
)
def test_v2_local_and_final_both_reject_nonservice_defects(change):
    a = boundary_artifact()
    d = a.activity_diagrams[0]
    e = next(e for e in d.edges if not e.related_step_ids)
    if change == "guard":
        e.guard = "approved"
    elif change == "label":
        e.label = "cancel"
    elif change == "unknown_step":
        e.related_step_ids = ["STEP-UC001-999"]
    elif change == "unknown_endpoint":
        e.target_node_id = "ADN-UC001-999"
    elif change == "duplicate":
        d.edges.append(e.model_copy(deep=True))
    else:
        nodes = {n.id: n for n in d.nodes}
        internal = next(
            x
            for x in d.edges
            if nodes[x.source_node_id].kind.value == "action"
            and nodes[x.target_node_id].kind.value != "final"
        )
        internal.related_step_ids = []
    assert not validate_activity_contract(d, a.use_case_set.use_cases[0], V2).passed
    spec = run_one_shot_baseline(sample_request(), Client(scripts(a)), contract_version=V2)
    assert not evaluate_contract(spec, V2).passed


def test_v2_uc_nfr_failure_reaches_repair_and_critic():
    good = boundary_artifact()
    bad = good.model_copy(deep=True)
    bad.use_case_set.use_cases[0].source_nfr_ids = ["NFR-999"]
    script = scripts(good)
    script["use_case_generator"] = scripts(bad)["use_case_generator"]
    client = Client(script)
    out = build_use_cases_graph(use_case_nodes_with_llm(client, contract_version=V2)).invoke(
        {"request": sample_request()}
    )
    assert out["status"].value == "success"
    assert [c["role"] for c in client.calls] == [
        "use_case_generator",
        "use_case_repair",
        "use_case_critic",
    ]
    assert "v2_unknown_uc_nfr" in json.dumps(client.messages[1])
    assert all(V2 in m[0]["content"] for m in client.messages)


def test_v2_activity_repair_uses_v2_feedback_not_boundary_issue():
    good = boundary_artifact()
    bad = good.model_copy(deep=True)
    bad.activity_diagrams[0].nodes[1].related_step_ids = ["STEP-UC001-999"]
    script = scripts(good)
    script["activity_generator"] = scripts(bad)["activity_generator"]
    client = Client(script)
    out = build_activity_diagram_graph(activity_nodes_with_llm(client, contract_version=V2)).invoke(
        {"use_case": good.use_case_set.use_cases[0], "actors": good.use_case_set.actors}
    )
    assert out["status"].value == "success"
    assert [c["role"] for c in client.calls] == [
        "activity_generator",
        "activity_repair",
        "activity_critic",
    ]
    assert "activity_step_missing" in json.dumps(client.messages[1])
    assert "activity_edge_untraced" not in json.dumps(client.messages[1])


def test_v2_feedback_contains_only_current_contract():
    good = boundary_artifact()
    bad = good.model_copy(deep=True)
    bad.use_case_set.use_cases[0].source_nfr_ids = ["NFR-999"]
    script = scripts(good)
    script["one_shot_generator"] = scripts(bad)["one_shot_generator"]
    client = Client(script)
    result = run_validator_feedback_baseline(sample_request(), client, contract_version=V2)
    assert result.specification.status.value == "success"
    feedback = json.loads(client.messages[1][1]["content"])["validator_feedback"]
    assert [r["validator_name"] for r in feedback] == [V2]
    assert any(i["code"] == "v2_unknown_uc_nfr" for i in feedback[0]["issues"])


def test_mixed_contract_rejected_before_call():
    client = Client({})
    with pytest.raises(ValueError):
        contract_client(contract_client(client, V2), V1)
    with pytest.raises(ValueError):
        run_one_shot_baseline(sample_request(), client, contract_version="unknown")
    assert not client.calls


def test_mismatched_checkpoint_contract_rejected():
    client = Client({})
    with pytest.raises(ValueError, match="Checkpoint/input"):
        compile_live_pipeline(client, contract_version=V2).invoke(
            {"request": sample_request(), "formal_contract": V1}
        )
    assert not client.calls
