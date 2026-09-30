"""Offline behavioral checks, not evidence of live-model quality."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from traceable_spec.entities import (
    OneShotGenerationArtifact,
    PipelineStatus,
    normalize_specification_req,
)
from traceable_spec.llm.openai_compatible import (
    LLMBudgetExceededError,
    LLMOutputTruncatedError,
    OpenAICompatibleConfig,
    OpenAICompatibleLLMClient,
)
from traceable_spec.llm.scripted import ScriptedLLMClient
from traceable_spec.prompts.one_shot import (
    ROLE_ONE_SHOT,
    ROLE_VALIDATOR_FEEDBACK_REPAIR,
    build_one_shot_messages,
)
from traceable_spec.reference_methods import (
    FeedbackAttempt,
    run_one_shot_baseline,
    run_validator_feedback_baseline,
)
from traceable_spec.testing.fixtures import (
    sample_activity_diagram,
    sample_request,
    sample_use_case_set,
)

ROOT = Path(__file__).resolve().parents[1]


def _artifact() -> OneShotGenerationArtifact:
    return OneShotGenerationArtifact(
        use_case_set=sample_use_case_set(),
        activity_diagrams=[sample_activity_diagram()],
    )


class RecordingClient(ScriptedLLMClient):
    def __init__(self, responses: list[str]) -> None:
        super().__init__(
            {
                ROLE_ONE_SHOT: responses[:1],
                ROLE_VALIDATOR_FEEDBACK_REPAIR: responses[1:],
            }
        )
        self.messages: list[list[dict[str, str]]] = []

    def complete(self, **kwargs: Any) -> str:
        self.messages.append(kwargs["messages"])
        return super().complete(**kwargs)


@pytest.mark.parametrize("limit", [0, 1, 2])
def test_valid_initial_response_stops_after_one_call(limit: int) -> None:
    client = RecordingClient([_artifact().model_dump_json()])
    result = run_validator_feedback_baseline(sample_request(), client, max_repair_attempts=limit)
    assert result.specification.status == PipelineStatus.SUCCESS
    assert result.repair_attempts_used == 0
    assert len(result.attempts) == len(client.calls) == 1
    normalized = normalize_specification_req(sample_request())
    assert client.messages[0] == build_one_shot_messages(normalized)


@pytest.mark.parametrize("limit", [0, 1, 2])
def test_repeated_invalid_response_exhausts_exact_budget(limit: int) -> None:
    client = RecordingClient(["broken"] * (limit + 1))
    observed: list[FeedbackAttempt] = []
    result = run_validator_feedback_baseline(
        sample_request(), client, max_repair_attempts=limit, on_attempt=observed.append
    )
    assert result.specification.status == PipelineStatus.FAILED
    assert result.repair_attempts_used == limit
    assert len(client.calls) == limit + 1
    assert [item.index for item in observed] == list(range(limit + 1))
    assert all(item.response_sha256 == hashlib.sha256(b"broken").hexdigest() for item in observed)
    assert all("critic" not in call["role"] for call in client.calls)


@pytest.mark.parametrize("bad_response", ["not JSON", "{}", "[]"])
def test_parse_or_schema_failure_can_be_repaired(bad_response: str) -> None:
    client = RecordingClient([bad_response, _artifact().model_dump_json()])
    result = run_validator_feedback_baseline(sample_request(), client)
    assert result.specification.status == PipelineStatus.SUCCESS
    assert [item.specification.status for item in result.attempts] == [
        PipelineStatus.FAILED,
        PipelineStatus.SUCCESS,
    ]
    assert result.repair_attempts_used == 1
    assert all(report.passed for report in result.specification.validation_reports)
    payload = json.loads(client.messages[1][1]["content"])
    assert payload["previous_response"] == bad_response
    normalized = normalize_specification_req(sample_request())
    assert payload["request"] == normalized.model_dump(mode="json")
    assert payload["validator_feedback"][0]["validator_name"] == "one_shot_parse"
    assert payload["repair_attempt"] == 1
    assert "Do not use critique or iterative repair" not in client.messages[1][0]["content"]


def test_second_repair_uses_latest_candidate_and_latest_diagnostics() -> None:
    broken = _artifact()
    broken.activity_diagrams[0].nodes[1].related_step_ids = ["STEP-UC001-999"]
    client = RecordingClient(["bad JSON", broken.model_dump_json(), _artifact().model_dump_json()])
    result = run_validator_feedback_baseline(sample_request(), client, max_repair_attempts=2)
    assert result.specification.status == PipelineStatus.SUCCESS
    assert result.repair_attempts_used == 2
    payload = json.loads(client.messages[2][1]["content"])
    assert payload["previous_response"] == broken.model_dump_json()
    issues = [issue for report in payload["validator_feedback"] for issue in report["issues"]]
    assert any(issue["code"] == "activity_step_missing" for issue in issues)
    assert any("STEP-UC001-999" in issue["element_ids"] for issue in issues)
    assert all(issue["code"] != "invalid_json" for issue in issues)
    assert payload["repair_attempt"] == 2


def test_missing_diagram_is_reported_and_repair_preserves_trace_and_mermaid() -> None:
    broken = _artifact()
    broken.activity_diagrams = []
    client = RecordingClient([broken.model_dump_json(), _artifact().model_dump_json()])
    result = run_validator_feedback_baseline(sample_request(), client)
    payload = json.loads(client.messages[1][1]["content"])
    assert "one_shot_missing_activity" in json.dumps(payload["validator_feedback"])
    assert result.specification.status == PipelineStatus.SUCCESS
    assert result.specification.trace_manifest.links
    assert result.specification.activity_results[0].activity_diagram.mermaid_source


@pytest.mark.parametrize("text", ["invalid", "valid"])
def test_zero_repairs_is_identical_to_existing_one_shot(text: str) -> None:
    response = _artifact().model_dump_json() if text == "valid" else text
    direct = run_one_shot_baseline(sample_request(), RecordingClient([response]))
    feedback = run_validator_feedback_baseline(
        sample_request(), RecordingClient([response]), max_repair_attempts=0
    )
    assert feedback.specification.model_dump() == direct.model_dump()


@pytest.mark.parametrize("limit", [-1, 3, 1.5, True, "1", None])
def test_invalid_limit_rejected_before_any_call(limit: Any) -> None:
    client = RecordingClient([])
    with pytest.raises(ValueError, match="max_repair_attempts"):
        run_validator_feedback_baseline(sample_request(), client, max_repair_attempts=limit)
    assert not client.calls


def _instrumented(
    responses: list[tuple[str, str]],
    *,
    observed_messages: list[Any] | None = None,
    **overrides: Any,
) -> OpenAICompatibleLLMClient:
    queued = iter(responses)

    def transport(*_: Any) -> tuple[int, bytes]:
        if observed_messages is not None:
            observed_messages.append(json.loads(_[2])["messages"])
        text, reason = next(queued)
        return 200, json.dumps(
            {
                "model": "offline-model",
                "choices": [{"message": {"content": text}, "finish_reason": reason}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            }
        ).encode()

    return OpenAICompatibleLLMClient(
        OpenAICompatibleConfig(
            provider="offline",
            api_base="https://example.invalid/v1",
            model="offline-model",
            api_key="offline-only",
            max_retries=0,
            **overrides,
        ),
        transport=transport,
    )


def test_truncation_is_not_disguised_as_validation_repair() -> None:
    client = _instrumented([("cut off", "length")])
    with pytest.raises(LLMOutputTruncatedError):
        run_validator_feedback_baseline(sample_request(), client, max_repair_attempts=2)
    assert len(client.calls) == 1


def test_client_budget_is_not_reset_to_force_acceptance() -> None:
    client = _instrumented([("bad", "stop")], max_calls_per_process=1)
    completed: list[FeedbackAttempt] = []
    with pytest.raises(LLMBudgetExceededError):
        run_validator_feedback_baseline(sample_request(), client, on_attempt=completed.append)
    assert len(client.calls) == len(completed) == 1
    assert completed[0].specification.status == PipelineStatus.FAILED


def _runner(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("runner_name", ["run_benchmark_experiment", "run_size_scaling_experiment"])
@pytest.mark.parametrize("limit", [1, 2])
def test_runners_persist_attempts_and_count_feedback_calls(
    runner_name: str, limit: int, tmp_path: Path
) -> None:
    runner = _runner(runner_name)
    observed_messages: list[Any] = []
    client = _instrumented(
        [("bad", "stop")] * limit + [(_artifact().model_dump_json(), "stop")],
        observed_messages=observed_messages,
    )
    condition = f"B1_FEEDBACK_{limit}"
    assert condition in runner.CONDITIONS
    if runner_name == "run_benchmark_experiment":
        case = {
            "case_id": "OFFLINE-001",
            "specification_req": sample_request(),
            "gold_annotation": {"secret_sentinel": "GOLD_MUST_NOT_REACH_MODEL"},
        }
        result, runtime = runner._run_condition(condition, case, 1, tmp_path, client)
    else:
        result, runtime = runner._run_condition(
            condition, sample_request(), "OFFLINE-001", 1, tmp_path, client
        )
    assert result.status == PipelineStatus.SUCCESS
    assert runtime["llm_calls"] == limit + 1
    assert runtime["repair_attempts"] == limit
    assert runtime["total_tokens"] == 15 * (limit + 1)
    records = [
        json.loads(line) for line in (tmp_path / "feedback_attempts.jsonl").read_text().splitlines()
    ]
    assert len(records) == limit + 1
    assert records[0]["status"] == "failed"
    assert records[-1]["status"] == "success"
    assert records[-1]["generated_specification"]["trace_manifest"]["links"]
    assert len((tmp_path / "calls.jsonl").read_text().splitlines()) == limit + 1
    assert "GOLD_MUST_NOT_REACH_MODEL" not in (tmp_path / "feedback_attempts.jsonl").read_text()
    assert "GOLD_MUST_NOT_REACH_MODEL" not in json.dumps(observed_messages)
    assert "offline-only" not in (tmp_path / "calls.jsonl").read_text()


@pytest.mark.parametrize("runner_name", ["run_benchmark_experiment", "run_size_scaling_experiment"])
def test_runner_keeps_completed_attempt_if_next_call_hits_budget(
    runner_name: str, tmp_path: Path
) -> None:
    runner = _runner(runner_name)
    client = _instrumented([("bad", "stop")], max_calls_per_process=1)
    with pytest.raises(LLMBudgetExceededError):
        if runner_name == "run_benchmark_experiment":
            runner._run_condition(
                "B1_FEEDBACK_1", {"specification_req": sample_request()}, 1, tmp_path, client
            )
        else:
            runner._run_condition("B1_FEEDBACK_1", sample_request(), "OFFLINE", 1, tmp_path, client)
    records = (tmp_path / "feedback_attempts.jsonl").read_text().splitlines()
    assert len(records) == 1 and json.loads(records[0])["status"] == "failed"


@pytest.mark.parametrize("runner_name", ["run_benchmark_experiment", "run_size_scaling_experiment"])
def test_live_guard_still_required_for_new_conditions(runner_name: str) -> None:
    process = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / f"{runner_name}.py"),
            "--condition",
            "B1_FEEDBACK_1",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode != 0
    assert "--allow-live" in process.stderr
