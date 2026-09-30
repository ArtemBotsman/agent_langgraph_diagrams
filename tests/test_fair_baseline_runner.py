"""No paid API: check experiment safeguards with an injected transport."""

from __future__ import annotations

import importlib.util
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from traceable_spec.entities import OneShotGenerationArtifact
from traceable_spec.llm.openai_compatible import OpenAICompatibleConfig, OpenAICompatibleLLMClient
from traceable_spec.testing.fixtures import (
    sample_activity_diagram,
    sample_request,
    sample_use_case_set,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def runner():
    spec = importlib.util.spec_from_file_location(
        "fair_runner", ROOT / "scripts/run_fair_baseline_experiment.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def config(**overrides):
    return OpenAICompatibleConfig(
        provider="offline",
        api_base="https://example.invalid/v1",
        model="offline",
        api_key="test-only",
        max_retries=0,
        max_output_tokens=1000,
        max_total_tokens_per_process=400000,
        input_price_usd_per_million=0.3,
        output_price_usd_per_million=1.2,
        **overrides,
    )


def fake_transport(content, finish="stop", observed=None):
    def transport(url, headers, body, timeout):
        if observed is not None:
            observed.append(json.loads(body))
        return 200, json.dumps(
            {
                "model": "offline",
                "choices": [{"message": {"content": content}, "finish_reason": finish}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            }
        ).encode()

    return transport


def test_budget_reservations_and_crash_accounting(runner, tmp_path):
    budget = runner.ExperimentBudget(tmp_path, 1)
    budget.reserve("first", 0.4)
    budget.settle("first", 0.1)
    budget.reserve("unknown", 0.5)
    budget.settle("unknown", None)
    restored = runner.ExperimentBudget(tmp_path, 1)
    assert restored.spent == pytest.approx(0.6)
    with pytest.raises(runner.ExperimentCostCeiling):
        restored.reserve("second", 0.5)
    assert restored.reservations == {}


def test_unsettled_call_is_not_forgotten_after_restart(runner, tmp_path):
    budget = runner.ExperimentBudget(tmp_path, 1)
    budget.reserve("uncertain", 0.7)
    restored = runner.ExperimentBudget(tmp_path, 1)
    assert restored.reservations == {"uncertain": 0.7}


def test_unknown_usage_keeps_money_and_durable_pause(runner, tmp_path):
    def transport(*args):
        return 200, json.dumps(
            {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]}
        ).encode()

    budget = runner.ExperimentBudget(tmp_path, 1)
    capped = runner.CappedClient(
        OpenAICompatibleLLMClient(config(), transport=transport), budget, "r"
    )
    assert capped.complete(messages=[{"role": "user", "content": "JSON"}]) == "{}"
    reserved = json.loads(budget.path.read_text().splitlines()[0])["usd"]
    assert budget.spent == reserved > 0
    assert budget.exhausted
    restored = runner.ExperimentBudget(tmp_path, 1)
    assert restored.exhausted and restored.spent == reserved
    with pytest.raises(runner.ExperimentPaused, match="Unknown API usage"):
        restored.reserve("another", 0.01)
    assert len(capped.client.calls) == 1


@pytest.mark.parametrize(
    "role",
    [
        "one_shot",
        "validator_feedback_repair",
        "use_case_generator",
        "use_case_critic",
        "use_case_repair",
        "activity_generator",
        "activity_critic",
        "activity_repair",
    ],
)
@pytest.mark.parametrize("temperature", [0, 0.2, 0.7])
def test_frozen_temperature_overrides_each_node_default(runner, tmp_path, role, temperature):
    observed = []
    raw = OpenAICompatibleLLMClient(config(), transport=fake_transport("{}", observed=observed))
    capped = runner.CappedClient(
        raw, runner.ExperimentBudget(tmp_path, 1), "r", temperature=temperature
    )
    capped.complete(messages=[{"role": "system", "content": role}], temperature=0)
    assert observed[0]["temperature"] == temperature
    assert raw.calls[0]["effective_temperature"] == temperature


def test_completed_candidate_with_unknown_usage_is_saved_not_regenerated(
    runner, monkeypatch, tmp_path
):
    response = OneShotGenerationArtifact(
        use_case_set=sample_use_case_set(), activity_diagrams=[sample_activity_diagram()]
    ).model_dump_json()
    observed = []

    def transport(*args):
        observed.append(1)
        return 200, json.dumps(
            {"choices": [{"message": {"content": response}, "finish_reason": "stop"}]}
        ).encode()

    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(
        runner,
        "OpenAICompatibleLLMClient",
        lambda cfg: OpenAICompatibleLLMClient(cfg, transport=transport),
    )
    task = {"case_id": "OFFLINE-001", "repeat_id": 1, "method": "B1_ONESHOT"}
    cases = {"OFFLINE-001": {"specification_req": sample_request()}}
    plan = {"full_repair_limit_per_artifact": 2, "temperature": 0.2}
    budget = runner.ExperimentBudget(tmp_path, 1)
    row = runner.run_task(task, plan, cases, config(), budget, tmp_path)
    assert row["common_formal_success"] == 1
    assert row["estimated_cost_usd"] is None and row["total_tokens"] is None
    assert budget.exhausted
    assert runner.run_task(task, plan, cases, config(), budget, tmp_path) == row
    assert len(observed) == 1


def test_size_pilot_is_private_and_does_not_load_gold(runner, monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    folder = tmp_path / "benchmark/size_scaling_v1"
    (folder / "inputs").mkdir(parents=True)
    (folder / "manifest.json").write_text(
        json.dumps({"cases": [{"case_id": "SCALE-001", "file": "one.json"}]})
    )
    request = sample_request()
    external = {
        name: getattr(request, name)
        for name in ("project_task", "project_name", "project_goal", "project_description")
    }
    external["functional_requirements"] = [fr.text for fr in request.functional_requirements]
    external["non_functional_requirements"] = [
        nfr.text for nfr in request.non_functional_requirements
    ]
    (folder / "inputs/one.json").write_text(json.dumps(external))
    (folder / "gold_candidate.json").write_text("MUST NOT BE READ")
    monkeypatch.setattr(runner, "source_hashes", lambda: {})
    args = SimpleNamespace(
        budget_usd=1,
        dataset="size_inputs",
        temperature=0.2,
        case_id=["SCALE-001"],
        repeats=1,
        max_output_tokens=131072,
        directory=tmp_path / "public",
    )
    with pytest.raises(SystemExit, match="private_evidence"):
        runner.prepare(args)
    args.directory = tmp_path / ".private_evidence/pilot"
    runner.prepare(args)
    plan = json.loads((args.directory / "plan.json").read_text())
    assert plan["temperature"] == 0.2 and len(plan["tasks"]) == 4
    assert plan["gold_status"] == "not used"
    assert plan["study_kind"] == "input_only_pilot"
    assert plan["max_run_tokens"] == 2_000_000 and plan["max_run_calls"] == 512


@pytest.mark.parametrize("token_cap,allowed", [(400000, False), (2000000, True)])
def test_long_feedback_reservation_has_explicit_headroom(runner, tmp_path, token_cap, allowed):
    observed = []
    cfg = replace(config(), max_output_tokens=131072, max_total_tokens_per_process=token_cap)
    raw = OpenAICompatibleLLMClient(cfg, transport=fake_transport("{}", observed=observed))
    raw.total_tokens = 144257
    capped = runner.CappedClient(raw, runner.ExperimentBudget(tmp_path, 1), "long")
    messages = [{"role": "user", "content": "JSON " + "требование " * 20000}]
    if allowed:
        assert capped.complete(messages=messages) == "{}"
        assert len(observed) == 1
    else:
        with pytest.raises(runner.LLMBudgetExceededError, match="observed=144257"):
            capped.complete(messages=messages)
        assert observed == []


@pytest.mark.parametrize("call_cap,allowed", [(64, False), (512, True)])
def test_64_uc_decomposition_needs_generation_plus_64_diagrams(runner, tmp_path, call_cap, allowed):
    observed = []
    raw = OpenAICompatibleLLMClient(
        replace(config(), max_calls_per_process=call_cap),
        transport=fake_transport("{}", observed=observed),
    )
    raw.calls = [{"usage_complete": True}] * 64
    capped = runner.CappedClient(raw, runner.ExperimentBudget(tmp_path, 1), "last_diagram")
    if allowed:
        assert capped.complete(messages=[{"role": "user", "content": "JSON"}]) == "{}"
        assert len(observed) == 1 and len(raw.calls) == 65
    else:
        with pytest.raises(runner.LLMBudgetExceededError, match="calls=64"):
            capped.complete(messages=[{"role": "user", "content": "JSON"}])
        assert observed == []


def test_budget_denial_happens_before_transport(runner, tmp_path):
    observed = []
    client = OpenAICompatibleLLMClient(config(), transport=fake_transport("{}", observed=observed))
    capped = runner.CappedClient(client, runner.ExperimentBudget(tmp_path, 0.000001), "r")
    with pytest.raises(runner.ExperimentCostCeiling):
        capped.complete(messages=[{"role": "user", "content": "JSON"}])
    assert observed == []
    assert client.calls == []


def test_telemetry_captures_requested_limit_temperature_and_truncation(runner, tmp_path):
    client = OpenAICompatibleLLMClient(config(), transport=fake_transport("cut", "length"))
    budget = runner.ExperimentBudget(tmp_path, 1)
    capped = runner.CappedClient(client, budget, "r")
    with pytest.raises(runner.LLMOutputTruncatedError):
        capped.complete(messages=[{"role": "user", "content": "JSON"}], temperature=0)
    call = client.calls[0]
    assert call["requested_max_output_tokens"] == 1000
    assert call["requested_temperature"] == call["effective_temperature"] == 0
    assert call["finish_reason"] == "length"
    assert budget.spent == pytest.approx(client.total_cost_usd)
    assert budget.reservations == {}


@pytest.mark.parametrize("needs_repair", [False, True])
def test_no_critic_runner_preserves_v2_and_repair_without_critic_calls(
    runner, tmp_path, needs_repair
):
    from test_live_contract_v2 import Client, boundary_artifact, scripts

    from traceable_spec.evaluation.contracts import V2, evaluate_contract

    artifact = boundary_artifact()
    script = scripts(artifact)
    if needs_repair:
        bad = artifact.model_copy(deep=True)
        bad.use_case_set.use_cases[0].source_nfr_ids = ["NFR-999"]
        script["use_case_generator"] = scripts(bad)["use_case_generator"]
    del script["use_case_critic"]
    del script["activity_critic"]
    client = Client(script)
    result = runner.execute_method(
        "NO_CRITIC", sample_request(), client, tmp_path, contract_version=V2
    )
    assert evaluate_contract(result, V2).passed
    expected = ["use_case_generator"]
    if needs_repair:
        expected.append("use_case_repair")
    assert [c["role"] for c in client.calls] == [*expected, "activity_generator"]
    assert all(V2 in m[0]["content"] for m in client.messages)


@pytest.mark.parametrize("methods", [["FULL", "FULL"], ["invented"]])
def test_prepare_rejects_duplicate_or_unknown_methods(runner, methods):
    with pytest.raises(SystemExit, match="known and unique"):
        runner.prepare(SimpleNamespace(budget_usd=1, method=methods))


def test_run_requires_explicit_live_switch_before_reading_files(runner, tmp_path):
    with pytest.raises(SystemExit, match="allow-live"):
        runner.run(SimpleNamespace(allow_live=False, directory=tmp_path))


@pytest.mark.parametrize(
    "response,finish,success",
    [("bad", "stop", 0), ("bad", "length", 0), ("valid", "length", 0), ("valid", "stop", 1)],
)
def test_terminal_runs_are_saved_once_with_missing_quality_not_zero(
    runner,
    monkeypatch,
    tmp_path,
    response,
    finish,
    success,
):
    if response == "valid":
        response = OneShotGenerationArtifact(
            use_case_set=sample_use_case_set(), activity_diagrams=[sample_activity_diagram()]
        ).model_dump_json()
    observed = []
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(
        runner,
        "OpenAICompatibleLLMClient",
        lambda cfg: OpenAICompatibleLLMClient(
            cfg, transport=fake_transport(response, finish, observed)
        ),
    )
    task = {"case_id": "OFFLINE-001", "repeat_id": 1, "method": "B1_ONESHOT"}
    cases = {"OFFLINE-001": {"specification_req": sample_request()}}
    plan = {"full_repair_limit_per_artifact": 2}
    budget = runner.ExperimentBudget(tmp_path, 1)
    first = runner.run_task(task, plan, cases, config(), budget, tmp_path)
    second = runner.run_task(task, plan, cases, config(), budget, tmp_path)
    assert first == second
    assert len(observed) == 1
    assert first["common_formal_success"] == success
    assert first["uc_output_available"] == bool(success)
    assert "milestone_f1" not in first  # Scored separately; no fake zero in runtime evidence.
    if finish == "length":
        assert first["output_truncated"] is True
        assert first["exception_type"] == "LLMOutputTruncatedError"
        assert first["failure_category"] == "output_truncated"
        assert first["resource_limit_reached"] is False
        assert first["total_tokens"] == 15


@pytest.mark.parametrize("limit", [0, 131073, 393216, True, 1.5])
def test_prepare_rejects_unsupported_output_profile_before_loading_cases(runner, tmp_path, limit):
    with pytest.raises(SystemExit, match="131072"):
        runner.prepare(SimpleNamespace(budget_usd=1, max_output_tokens=limit))
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("limit", [1, 8000, 65536, 131072])
def test_profile_output_boundaries_are_explicit(runner, limit):
    assert runner.validate_output_limit(limit) == limit


@pytest.mark.parametrize("kind", ["token", "call"])
def test_resource_admission_is_not_output_truncation(runner, monkeypatch, tmp_path, kind):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    observed = []
    monkeypatch.setattr(
        runner,
        "OpenAICompatibleLLMClient",
        lambda cfg: OpenAICompatibleLLMClient(
            cfg, transport=fake_transport("{}", observed=observed)
        ),
    )
    cfg = replace(
        config(),
        **(
            {"max_total_tokens_per_process": 1} if kind == "token" else {"max_calls_per_process": 0}
        ),
    )
    task = {"case_id": "OFFLINE-001", "repeat_id": 1, "method": "B1_ONESHOT"}
    row = runner.run_task(
        task,
        {"full_repair_limit_per_artifact": 2},
        {"OFFLINE-001": {"specification_req": sample_request()}},
        cfg,
        runner.ExperimentBudget(tmp_path, 1),
        tmp_path,
    )
    assert observed == []
    assert row["failure_category"] == f"run_{kind}_limit"
    assert row["resource_limit_reached"] is True
    assert row["output_truncated"] is False
    assert row["llm_calls"] == 0


def test_unknown_usage_is_not_mislabeled_as_output_truncation(runner):
    assert runner.failure_category(runner.LLMBudgetExceededError("usage unknown")) == (
        "client_budget_or_accounting"
    )


def test_global_budget_pause_is_not_terminal_model_failure(runner, monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    task = {"case_id": "OFFLINE-001", "repeat_id": 1, "method": "B1_ONESHOT"}
    cases = {"OFFLINE-001": {"specification_req": sample_request()}}
    paused = runner.run_task(
        task,
        {"full_repair_limit_per_artifact": 2},
        cases,
        config(),
        runner.ExperimentBudget(tmp_path, 0.000001),
        tmp_path,
    )
    assert paused["experiment_paused"]
    assert not list(tmp_path.rglob("terminal.json"))
    assert list(tmp_path.rglob("paused.json"))


def test_interrupted_run_is_not_automatically_duplicated(runner, tmp_path):
    task = {"case_id": "OFFLINE-001", "repeat_id": 1, "method": "B1_ONESHOT"}
    (tmp_path / "runs/OFFLINE-001__B1_ONESHOT__r01").mkdir(parents=True)
    with pytest.raises(RuntimeError, match="Interrupted"):
        runner.run_task(task, {}, {}, config(), runner.ExperimentBudget(tmp_path, 1), tmp_path)


@pytest.mark.parametrize("status", [401, 402])
def test_account_problem_pauses_allocation_not_a_model_quality_failure(runner, tmp_path, status):
    attempts = []

    def transport(*args):
        attempts.append(1)
        return status, b"{}"

    budget = runner.ExperimentBudget(tmp_path, 1)
    client = runner.CappedClient(
        OpenAICompatibleLLMClient(config(), transport=transport), budget, "r"
    )
    for _ in range(2):
        with pytest.raises(runner.ExperimentPaused, match=f"HTTP {status}"):
            client.complete(messages=[{"role": "user", "content": "JSON"}])
    assert len(attempts) == 1
    assert budget.exhausted
    assert not budget.reservations
