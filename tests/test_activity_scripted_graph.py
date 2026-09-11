from __future__ import annotations

import json

from traceable_spec.activity_diagram_graph import (
    activity_nodes_with_llm,
    activity_result_from_state,
    compile_activity_diagram_graph,
)
from traceable_spec.entities import ActivityGenerationArtifact, PipelineStatus, TraceManifest
from traceable_spec.llm.scripted import ScriptedLLMClient
from traceable_spec.prompts.activities import (
    ROLE_ACTIVITY_CRITIC,
    ROLE_ACTIVITY_GENERATOR,
    ROLE_ACTIVITY_REPAIR,
)
from traceable_spec.testing.fixtures import (
    sample_activity_diagram,
    sample_request,
    sample_uc_trace_manifest,
    sample_use_case_set,
)
from traceable_spec.testing.scripted_uc_responses import critic_accept_json


def _artifact_json(*, broken: bool = False) -> str:
    diagram = sample_activity_diagram()
    if broken:
        diagram = diagram.model_copy(update={"edges": []})
    artifact = ActivityGenerationArtifact(
        activity_diagram=diagram,
        trace_manifest=TraceManifest(),
    )
    return json.dumps(artifact.model_dump(mode="json"))


def _run(client: ScriptedLLMClient, *, max_repairs: int = 1):
    use_case_set = sample_use_case_set()
    graph = compile_activity_diagram_graph(activity_nodes_with_llm(client))
    state = graph.invoke(
        {
            "use_case": use_case_set.use_cases[0],
            "actors": use_case_set.actors,
            "max_repair_attempts": max_repairs,
            "trace_manifest": sample_uc_trace_manifest(),
            "request": sample_request(),
        }
    )
    return activity_result_from_state(state), state


def test_live_activity_roles_accept_valid_artifact() -> None:
    client = ScriptedLLMClient(
        {
            ROLE_ACTIVITY_GENERATOR: [_artifact_json()],
            ROLE_ACTIVITY_CRITIC: [critic_accept_json()],
        }
    )
    result, _ = _run(client)
    assert result.status == PipelineStatus.SUCCESS
    assert result.activity_diagram is not None
    assert result.activity_diagram.mermaid_source
    assert [call["role"] for call in client.calls] == [
        ROLE_ACTIVITY_GENERATOR,
        ROLE_ACTIVITY_CRITIC,
    ]


def test_formal_failure_short_circuits_critic_before_repair() -> None:
    client = ScriptedLLMClient(
        {
            ROLE_ACTIVITY_GENERATOR: [_artifact_json(broken=True)],
            ROLE_ACTIVITY_REPAIR: [_artifact_json()],
            ROLE_ACTIVITY_CRITIC: [critic_accept_json()],
        }
    )
    result, state = _run(client)
    assert result.status == PipelineStatus.SUCCESS
    assert [call["role"] for call in client.calls] == [
        ROLE_ACTIVITY_GENERATOR,
        ROLE_ACTIVITY_REPAIR,
        ROLE_ACTIVITY_CRITIC,
    ]
    assert any(
        issue.code == "unreachable_from_initial"
        for report in state["validation_reports"]
        for issue in report.issues
    )
