"""UC graph vertical slice with ScriptedLLMClient (fake — not a live model)."""

from __future__ import annotations

from traceable_spec.entities import PipelineStatus, SpecificationRequest
from traceable_spec.llm.scripted import ScriptedLLMClient
from traceable_spec.prompts.use_cases import ROLE_CRITIC, ROLE_GENERATOR, ROLE_REPAIR
from traceable_spec.testing.fixtures import sample_request
from traceable_spec.testing.scripted_uc_responses import (
    broken_trace_uc_artifact_json,
    critic_accept_json,
    critic_repair_json,
    invalid_json_text,
    valid_uc_artifact_json,
)
from traceable_spec.use_cases_graph import (
    compile_use_cases_graph,
    use_case_graph_output_from_state,
    use_case_nodes_with_llm,
)
from traceable_spec.validators import validate_fr_to_uc_trace_links


def _run(client: ScriptedLLMClient, request: SpecificationRequest | None = None):
    graph = compile_use_cases_graph(use_case_nodes_with_llm(client))
    state = graph.invoke({"request": request or sample_request()})
    return use_case_graph_output_from_state(state), state


def test_scripted_uc_accept_without_repair() -> None:
    client = ScriptedLLMClient(
        {
            ROLE_GENERATOR: [valid_uc_artifact_json()],
            ROLE_CRITIC: [critic_accept_json()],
        }
    )
    output, _ = _run(client)
    assert output.status == PipelineStatus.SUCCESS
    assert output.use_case_set is not None
    assert output.repair_attempts_used == 0
    assert output.failure_reason is None
    assert any(c["role"] == ROLE_GENERATOR for c in client.calls)
    assert any(c["role"] == ROLE_CRITIC for c in client.calls)
    assert not any(c["role"] == ROLE_REPAIR for c in client.calls)


def test_scripted_uc_trace_error_detected() -> None:
    from traceable_spec.entities import TraceManifest
    from traceable_spec.testing.fixtures import sample_use_case_set

    report = validate_fr_to_uc_trace_links(sample_use_case_set(), TraceManifest(links=[]))
    assert not report.passed
    assert any(issue.code == "missing_fr_to_uc_link" for issue in report.issues)

    client = ScriptedLLMClient(
        {
            ROLE_GENERATOR: [broken_trace_uc_artifact_json()],
            ROLE_CRITIC: [critic_repair_json(), critic_accept_json("fixed")],
            ROLE_REPAIR: [valid_uc_artifact_json()],
        }
    )
    request = sample_request().model_copy(update={"max_repair_attempts": 1})
    output, state = _run(client, request)
    assert any(
        issue.code == "missing_fr_to_uc_link"
        for report in state["validation_reports"]
        for issue in report.issues
    )
    assert output.status == PipelineStatus.SUCCESS


def test_scripted_uc_repair_then_success() -> None:
    client = ScriptedLLMClient(
        {
            ROLE_GENERATOR: [broken_trace_uc_artifact_json()],
            ROLE_CRITIC: [critic_repair_json(), critic_accept_json("ok after repair")],
            ROLE_REPAIR: [valid_uc_artifact_json()],
        }
    )
    request = sample_request().model_copy(update={"max_repair_attempts": 2})
    output, _ = _run(client, request)
    assert output.status == PipelineStatus.SUCCESS
    assert output.repair_attempts_used == 1
    assert output.use_case_set is not None
    assert any(c["role"] == ROLE_REPAIR for c in client.calls)


def test_scripted_uc_repair_limit_exhausted() -> None:
    client = ScriptedLLMClient(
        {
            ROLE_GENERATOR: [broken_trace_uc_artifact_json()],
            ROLE_CRITIC: [
                critic_repair_json(),
                critic_repair_json(),
                critic_repair_json(),
            ],
            ROLE_REPAIR: [
                broken_trace_uc_artifact_json(),
                broken_trace_uc_artifact_json(),
            ],
        }
    )
    request = sample_request().model_copy(update={"max_repair_attempts": 1})
    output, _ = _run(client, request)
    assert output.status == PipelineStatus.FAILED
    assert output.repair_attempts_used == 1
    assert output.failure_reason is not None
    assert "repair_attempt=1" in (output.failure_reason or "")


def test_scripted_uc_invalid_json_does_not_crash() -> None:
    client = ScriptedLLMClient(
        {
            ROLE_GENERATOR: [invalid_json_text()],
            ROLE_CRITIC: [],  # critic skipped when artifact missing
        }
    )
    request = sample_request().model_copy(update={"max_repair_attempts": 0})
    output, state = _run(client, request)
    assert output.status == PipelineStatus.FAILED
    assert output.use_case_set is None
    assert any(
        issue.code == "invalid_json"
        for report in state["validation_reports"]
        for issue in report.issues
    )


def test_scripted_uc_output_contract() -> None:
    client = ScriptedLLMClient(
        {
            ROLE_GENERATOR: [valid_uc_artifact_json()],
            ROLE_CRITIC: [critic_accept_json()],
        }
    )
    output, _ = _run(client)
    dumped = output.model_dump()
    assert set(dumped.keys()) >= {
        "use_case_set",
        "trace_manifest",
        "validation_reports",
        "status",
        "repair_attempts_used",
        "failure_reason",
    }
    assert output.status == PipelineStatus.SUCCESS
