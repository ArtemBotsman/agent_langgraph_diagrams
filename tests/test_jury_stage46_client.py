"""Offline transport/budget tests; no provider calls."""

import copy
import json
import sys
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from jury_opencode_multimodel_v2 import RunResourceStop
from jury_stage46_client import (
    MODEL,
    CacheAwareFullClient,
    Stage46ResponseError,
)
from run_fair_baseline_experiment import (
    ExperimentBudget,
    ExperimentCostCeiling,
    ExperimentPaused,
    execute_method,
)

from traceable_spec.entities import ActivityGenerationArtifact, UseCaseGenerationArtifact
from traceable_spec.evaluation.contracts import V2
from traceable_spec.llm.openai_compatible import LLMOutputTruncatedError
from traceable_spec.prompts.use_cases import detect_llm_role
from traceable_spec.testing.fixtures import (
    sample_activity_diagram,
    sample_request,
    sample_use_case_set,
)


def response(content=' {"answer": "kept exactly"} ', finish="stop", **message_fields):
    return json.dumps(
        {
            "id": "offline",
            "model": MODEL,
            "created": 1790701200,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content, **message_fields},
                    "finish_reason": finish,
                }
            ],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 10,
                "total_tokens": 110,
                "prompt_cache_hit_tokens": 90,
                "prompt_cache_miss_tokens": 10,
            },
        }
    ).encode()


@pytest.fixture
def make_client(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        pytest.fail("Provider network calls are forbidden in adapter tests")

    monkeypatch.setattr("urllib.request.urlopen", no_network)
    with ExitStack() as stack:
        counter = 0

        def make(transport=lambda _: response(), ceiling=1):
            nonlocal counter
            counter += 1
            root = tmp_path / str(counter)
            root.mkdir()
            budget = ExperimentBudget(root, ceiling)
            return stack.enter_context(
                CacheAwareFullClient(
                    budget, root / "gateway", f"test-{counter}", transport=transport
                )
            )

        yield make


def test_exact_payload_response_cache_cost_and_pretransmission_reservation(make_client):
    captured = []
    client = None

    def transport(payload):
        assert client.budget.reservations  # Reservation exists before transmission.
        captured.append(copy.deepcopy(payload))
        return response()

    client = make_client(transport)
    messages = [
        {"role": "system", "content": "[[llm_role:activity_generator]] Return JSON."},
        {"role": "user", "content": "Исходный текст"},
    ]
    before = copy.deepcopy(messages)
    content = client.complete(messages=messages, temperature=0, metadata={"case_id": "SCALE-017"})
    assert content == ' {"answer": "kept exactly"} ' and messages == before
    assert captured[0]["messages"] == messages
    assert captured[0]["model"] == MODEL and captured[0]["temperature"] == 0.2
    assert captured[0]["max_tokens"] == 131072
    assert captured[0]["thinking"] == {"type": "disabled"}
    assert captured[0]["response_format"] == {"type": "json_object"}
    assert captured[0]["stream"] is False and "metadata" not in captured[0]
    assert client.gateway.max_run_calls == 512 and client.gateway.max_run_tokens is None
    record = client.call_records[0]
    assert record["llm_role"] == "activity_generator"
    assert record["requested_temperature"] == 0 and record["effective_temperature"] == 0.2
    assert record["metadata"] == {"case_id": "SCALE-017"}
    assert record["http_retries"] == 0 and record["attempts"] == 1
    assert record["estimated_cost_usd"] == pytest.approx(client.budget.spent)
    assert record["estimated_cost_usd"] < record["old_uncached_peak_upper_usd"]
    assert not client.budget.reservations
    assert client.total_tokens == 110 and client.total_cost_usd == client.budget.spent
    assert (client.folder / "0001-native-response.bin").read_bytes() == response()
    assert json.loads((client.folder / "0001-upstream-request.json").read_text()) == captured[0]
    record["metadata"]["case_id"] = "mutated copy"
    assert client.call_records[0]["metadata"]["case_id"] == "SCALE-017"


def test_no_cumulative_token_ceiling(make_client):
    client = make_client()
    client.gateway.max_run_tokens = 1  # Stage41 call intentionally ignores the old token cap.
    for _ in range(2):
        client.complete(messages=[])
    assert len(client.calls) == 2 and client.total_tokens == 220
    admissions = [
        json.loads(s) for s in (client.folder / "admissions.jsonl").read_text().splitlines()
    ]
    assert all(a["cumulative_token_ceiling"] is None for a in admissions)


def test_budget_stops_before_transport_and_does_not_count_denied_call(make_client):
    client = make_client(lambda _: pytest.fail("No paid request allowed"), ceiling=0.01)
    with pytest.raises(ExperimentCostCeiling):
        client.complete(messages=[])
    assert client.calls == [] and client.budget.spent == 0
    with pytest.raises(ExperimentPaused):
        client.complete(messages=[])


def test_unknown_usage_keeps_reservation_and_stops_without_retry(make_client):
    transmissions = []

    def transport(payload):
        transmissions.append(payload)
        return b"{}"

    client = make_client(transport)
    with pytest.raises(KeyError):
        client.complete(messages=[])
    assert len(transmissions) == 1 and client.budget.pause_reason
    record = client.calls[0]
    assert not record["usage_complete"] and record["total_tokens"] is None
    assert 0 < record["estimated_cost_usd"] == client.budget.spent <= 1
    with pytest.raises(ExperimentPaused):
        client.complete(messages=[])
    assert len(transmissions) == 1


def test_transport_failure_has_one_attempt_and_durable_conservative_cost(make_client):
    sent = []

    def transport(payload):
        sent.append(payload)
        raise TimeoutError("Offline timeout")

    client = make_client(transport)
    with pytest.raises(TimeoutError):
        client.complete(messages=[])
    assert len(sent) == 1 and len(client.call_records) == 1
    assert client.call_records[0]["error_type"] == "TimeoutError"
    assert (client.folder / "0001-full-call-record.json").exists()
    assert client.budget.spent == client.total_cost_usd > 0


def test_call_cap_stops_before_transport(make_client):
    client = make_client(lambda _: pytest.fail("No paid request allowed"))
    client.gateway.max_run_calls = 0
    with pytest.raises(RunResourceStop):
        client.complete(messages=[])
    assert client.calls == [] and client.budget.spent == 0


@pytest.mark.parametrize("content", [None, [], {}, "", "   "])
def test_nontext_or_empty_content_is_not_stringified(make_client, content):
    client = make_client(lambda _: response(content))
    with pytest.raises(Stage46ResponseError):
        client.complete(messages=[])
    assert client.call_records[0]["usage_complete"]
    assert client.call_records[0]["status"] == "error"
    assert client.budget.spent > 0  # Known usage is still paid/recorded.


def test_truncation_is_reported_after_known_usage_settlement(make_client):
    client = make_client(lambda _: response('{"partial":', finish="length"))
    with pytest.raises(LLMOutputTruncatedError):
        client.complete(messages=[])
    assert client.calls[0]["status"] == "truncated" and client.calls[0]["output_truncated"]
    assert client.calls[0]["estimated_cost_usd"] == client.budget.spent


def test_invalid_json_text_passes_unchanged_to_existing_artifact_parser(make_client):
    client = make_client(lambda _: response("This is not JSON"))
    assert client.complete(messages=[]) == "This is not JSON"


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ('```json\n{"answer": 1}\n```', '{"answer": 1}'),
        ('```\n {"answer": 1} \n```', ' {"answer": 1} '),
        ("```json\n[1, 2]\n```", "```json\n[1, 2]\n```"),
        ('```json\n{"broken":\n```', '```json\n{"broken":\n```'),
        ("```json\n{}\n```\n```json\n{}\n```", "```json\n{}\n```\n```json\n{}\n```"),
    ],
)
def test_historical_json_envelope_policy_preserves_raw_response(make_client, content, expected):
    raw = response(content)
    client = make_client(lambda _: raw)
    assert client.complete(messages=[]) == expected
    assert (client.folder / "0001-native-response.bin").read_bytes() == raw
    assert client.calls[0]["response_envelope_policy"] == "run_jury_stage15.json_object"


@pytest.mark.parametrize(
    ("utc_hour", "period", "multiplier"), [(2, "peak", 1), (12, "off_peak", 0.5)]
)
def test_gateway_cost_uses_provider_created_timestamp(make_client, utc_hour, period, multiplier):
    payload = json.loads(response())
    payload["created"] = int(datetime(2026, 9, 29, utc_hour, tzinfo=UTC).timestamp())
    client = make_client(lambda _: json.dumps(payload).encode())
    client.complete(messages=[])
    record = client.calls[0]
    expected = (90 * 0.006 + 10 * 0.30 + 10 * 1.20) * multiplier / 1e6
    assert record["rate_period"] == period
    assert record["estimated_cost_usd"] == pytest.approx(expected)
    assert client.budget.spent == pytest.approx(expected)


@pytest.mark.parametrize("field", [{"tool_calls": [{"id": "tool"}]}, {"refusal": "refused"}])
def test_tools_or_refusal_are_not_accepted_as_artifact_text(make_client, field):
    client = make_client(lambda _: response("{}", **field))
    with pytest.raises(Stage46ResponseError):
        client.complete(messages=[])


def test_unsupported_settings_fail_before_transport(make_client):
    client = make_client(lambda _: pytest.fail("No transmission"))
    with pytest.raises(ValueError):
        client.complete(messages=[], model="another-model")
    with pytest.raises(ValueError):
        client.complete(messages=[], response_format={"type": "text"})
    assert client.calls == [] and client.budget.spent == 0


@pytest.mark.parametrize("cap", [0, -1, 1.01, 3, float("inf"), float("nan")])
def test_method_cap_cannot_exceed_one_dollar(tmp_path, cap):
    with pytest.raises(ValueError):
        CacheAwareFullClient(ExperimentBudget(tmp_path, cap), tmp_path / "gateway", "invalid")


def test_old_evidence_directory_is_never_reused(tmp_path):
    folder = tmp_path / "gateway"
    folder.mkdir()
    marker = folder / "old.json"
    marker.write_text('{"old": true}')
    with pytest.raises(FileExistsError):
        CacheAwareFullClient(ExperimentBudget(tmp_path, 1), folder, "new")
    assert marker.read_text() == '{"old": true}'


def test_fair_execute_full_uses_unchanged_interface_with_fake_gateway(make_client, tmp_path):
    use_cases = UseCaseGenerationArtifact(use_case_set=sample_use_case_set()).model_dump_json()
    activity = ActivityGenerationArtifact(
        activity_diagram=sample_activity_diagram()
    ).model_dump_json()

    def transport(payload):
        role = detect_llm_role(payload["messages"])
        text = {"use_case_generator": use_cases, "activity_generator": activity}.get(
            role, '{"decision":"accept"}'
        )
        return response(text)

    client = make_client(transport)
    run_dir = tmp_path / "fair-run"
    run_dir.mkdir()
    result = execute_method("FULL", sample_request(), client, run_dir, contract_version=V2)
    assert result.status.value == "success"
    assert len(client.call_records) == 4
    assert {r["effective_temperature"] for r in client.call_records} == {0.2}
    assert client.total_cost_usd == pytest.approx(client.budget.spent)
