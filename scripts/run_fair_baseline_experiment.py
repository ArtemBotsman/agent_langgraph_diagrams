"""Frozen DEV-only comparison; common final checks and equal per-run resource caps.

Prepare is offline. Run requires --allow-live and a frozen cost ceiling. Saved
terminal runs, including failures, are never regenerated. An interrupted run
needs explicit review; it is never silently rerun or omitted from the matrix.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from traceable_spec.entities import (
    GeneratedSpecification,
    PipelineStatus,
    normalize_specification_req,
)
from traceable_spec.evaluation.contracts import CONTRACTS, V1, evaluate_contract, require_contract
from traceable_spec.evaluation.experiment_cases import load_experiment_cases
from traceable_spec.llm.anthropic import AnthropicConfig, AnthropicLLMClient
from traceable_spec.llm.openai_compatible import (
    LLMBudgetExceededError,
    LLMOutputTruncatedError,
    OpenAICompatibleConfig,
    OpenAICompatibleLLMClient,
)
from traceable_spec.orchestration.component_variants import live_pipeline_deps_without_critics
from traceable_spec.orchestration.critic_budget import (
    formal_repair_diagnostics,
    live_pipeline_deps_with_critic_budget,
)
from traceable_spec.orchestration.persistence import open_sqlite_checkpointer, thread_config
from traceable_spec.orchestration.pipeline import compile_live_pipeline, compile_pipeline
from traceable_spec.reference_methods import (
    run_decomposed_baseline,
    run_one_shot_baseline,
    run_validator_feedback_baseline,
)

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "benchmark/v1_0_synthetic/cases.json"
METHODS = ("B1_ONESHOT", "B1_FEEDBACK_1", "DECOMPOSED", "FULL")
CRITIC_METHODS = tuple(f"CRITIC_{n}" for n in range(4))
AVAILABLE_METHODS = (*METHODS, "NO_CRITIC", *CRITIC_METHODS)
VERSION = "fair-baselines-v6-2026-09-28"
# An experimentally exercised profile ceiling, NOT a universal provider limit.
PROFILE_MAX_OUTPUT_TOKENS = 131072


def validate_output_limit(value: int) -> int:
    if type(value) is not int or not 1 <= value <= PROFILE_MAX_OUTPUT_TOKENS:
        raise ValueError(
            f"max-output-tokens must be in [1, {PROFILE_MAX_OUTPUT_TOKENS}] "
            "for this experiment profile"
        )
    return value


class RunResourceLimitError(LLMBudgetExceededError):
    """Pre-call admission failure, distinct from a provider-truncated response."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.limit_kind = kind


def failure_category(exc: Exception) -> str:
    if isinstance(exc, LLMOutputTruncatedError):
        return "output_truncated"
    if isinstance(exc, RunResourceLimitError):
        return f"run_{exc.limit_kind}_limit"
    if isinstance(exc, LLMBudgetExceededError):
        return "client_budget_or_accounting"
    return "execution_error"


class ExperimentPaused(RuntimeError):
    """Stop allocation without mislabeling an incomplete experiment as failure."""


class ExperimentCostCeiling(ExperimentPaused):
    """Pause the experiment; do not count an unallocated budget as model failure."""


def digest(data: Any) -> str:
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def dump_new(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def source_hashes() -> dict[str, str]:
    paths = [
        *sorted((ROOT / "src/traceable_spec").rglob("*.py")),
        Path(__file__),
        ROOT / "scripts/analyze_fair_baseline_experiment.py",
    ]
    paths.extend([ROOT / "pyproject.toml", ROOT / "poetry.lock"])
    return {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
    }


def dev_cases() -> list[dict[str, Any]]:
    return [case for case in json.loads(CASES.read_text()) if case["split"] == "development"]


def prepare(args: argparse.Namespace) -> None:
    if args.budget_usd is None or not 0 < args.budget_usd <= 100:
        raise SystemExit("prepare requires an explicit --budget-usd in (0, 100]")
    dataset = getattr(args, "dataset", "dev20")
    methods = tuple(getattr(args, "method", None) or METHODS)
    if len(set(methods)) != len(methods) or any(m not in AVAILABLE_METHODS for m in methods):
        raise SystemExit("Methods must be known and unique")
    temperature = getattr(args, "temperature", 0.2)
    if not math.isfinite(temperature) or not 0 <= temperature <= 2:
        raise SystemExit("temperature must be finite and in [0, 2]")
    max_run_tokens = getattr(args, "max_run_tokens", 2_000_000)
    max_run_calls = getattr(args, "max_run_calls", 512)
    try:
        validate_output_limit(args.max_output_tokens)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    if max_run_tokens < args.max_output_tokens + 1024 or max_run_calls < 1:
        raise SystemExit("Run limits must allow a response plus framing and at least one call")
    selected = load_experiment_cases(ROOT, dataset, args.case_id)
    if dataset == "size_inputs" and not args.directory.resolve().is_relative_to(
        (ROOT / ".private_evidence").resolve()
    ):
        raise SystemExit("Size inputs require a directory under .private_evidence")
    for case in selected:
        normalize_specification_req(case["specification_req"])
    tasks = [
        {"case_id": case["case_id"], "repeat_id": repeat, "method": method}
        for case in selected
        for repeat in range(1, args.repeats + 1)
        for method in methods
    ]
    random.Random(20260925).shuffle(tasks)
    plan = {
        "version": VERSION,
        "prepared_at": datetime.now(UTC).isoformat(),
        "cases": [case["case_id"] for case in selected],
        "cases_hash": digest(selected),
        "dataset": dataset,
        "study_kind": "input_only_pilot" if dataset == "size_inputs" else "development",
        "case_fr_counts": {
            case["case_id"]: len(
                normalize_specification_req(case["specification_req"]).functional_requirements
            )
            for case in selected
        },
        "source_hashes": source_hashes(),
        "methods": methods,
        "repeats": args.repeats,
        "tasks": tasks,
        "provider": "deepseek",
        "api_base": "https://api.deepseek.com",
        "model": "deepseek-flash",
        "temperature": temperature,
        "temperature_policy": "same explicit override on every role and method",
        "thinking_enabled": False,
        "max_output_tokens": args.max_output_tokens,
        "max_run_tokens": max_run_tokens,
        "max_run_calls": max_run_calls,
        "resource_policy": (
            "explicit equal ceilings; reserve UTF-8 input upper bound and full response"
        ),
        "full_repair_limit_per_artifact": 2,
        "critic_call_limits_per_artifact": {m: int(m[-1]) for m in methods if m in CRITIC_METHODS},
        "critic_budget_exhaustion": "formal-only finalization; not semantic approval",
        "direct_feedback_repair_limit": 1,
        "http_retries": 0,
        "timeout_seconds": 600,
        "budget_usd": args.budget_usd,
        "input_usd_per_million_upper": 0.30,
        "output_usd_per_million_upper": 1.20,
        "pricing_source": "https://api-docs.deepseek.com/quick_start/pricing/",
        "pricing_policy": "conservative peak uncached rates, not provider invoice",
        "formal_evaluator": require_contract(getattr(args, "contract_version", V1)),
        "primary_metric": "common_formal_success",
        "secondary_metrics": [
            "actor_f1",
            "uc_f1",
            "milestone_f1",
            "branch_f1",
            "trace_f1",
            "unmatched_element_rate",
            "latency_ms",
            "total_tokens",
            "estimated_cost_usd",
        ],
        "gold_status": "not used"
        if dataset == "size_inputs"
        else "existing synthetic candidate; no new human assessment",
        "missing_scores": "null when no usable UC output; partial UC scores explicitly flagged",
        "statistical_unit": "project; repeats averaged within each project",
        "statistical_analysis": {
            "bootstrap_resamples": 50000,
            "seed": 20260925,
            "confidence": 0.95,
            "contrasts": [f"FULL - {m}" for m in methods if m != "FULL"]
            if "FULL" in methods
            else [],
            "primary_test": (
                "two-sided exact project-level paired sign-flip; Holm over planned contrasts"
            ),
            "semantic_analysis": "descriptive paired complete projects; report missingness",
        },
        "stop_rule": "fixed tasks; no outcome-dependent repeats; global budget stops matrix",
        "scope": "DEV engineering comparison; not hidden/generalization/ambiguity evidence",
    }
    args.directory.mkdir(parents=True, exist_ok=False)
    dump_new(args.directory / "plan.json", plan)
    print(json.dumps({"prepared_tasks": len(tasks), "plan_sha256": digest(plan)}, indent=2))


class ExperimentBudget:
    """Thread-safe conservative reservations, with durable failure accounting."""

    def __init__(self, directory: Path, ceiling: float):
        self.path = directory / "budget_ledger.jsonl"
        self.ceiling = ceiling
        self.lock = threading.Lock()
        self.condition = threading.Condition(self.lock)
        self.exhausted = False
        self.pause_reason: str | None = None
        self.spent = 0.0
        self.reservations: dict[str, float] = {}
        self.pause_path = directory / "budget_pause.json"
        if self.pause_path.exists():
            self.pause_reason = json.loads(self.pause_path.read_text())["reason"]
            self.exhausted = True
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                event = json.loads(line)
                if event["event"] == "reserve":
                    self.reservations[event["id"]] = event["usd"]
                else:
                    self.reservations.pop(event["id"], None)
                    self.spent += event["usd"]
        # Unsettled calls stay reserved until a separate evidence-backed reconciliation.

    def event(self, kind: str, key: str, value: float) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"event": kind, "id": key, "usd": value}) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def reserve(self, key: str, value: float) -> None:
        with self.condition:
            if key in self.reservations:
                raise RuntimeError("Duplicate budget reservation")
            if self.pause_reason:
                raise ExperimentPaused(self.pause_reason)
            if self.exhausted:
                raise ExperimentCostCeiling("Experiment-wide cost ceiling reached")
            while self.spent + sum(self.reservations.values()) + value > self.ceiling:
                if self.pause_reason:
                    raise ExperimentPaused(self.pause_reason)
                if self.exhausted or self.spent + value > self.ceiling or not self.reservations:
                    self.exhausted = True
                    self.condition.notify_all()
                    raise ExperimentCostCeiling("Experiment-wide cost ceiling reached")
                self.condition.wait(timeout=10)
            if self.pause_reason:
                raise ExperimentPaused(self.pause_reason)
            self.event("reserve", key, value)
            self.reservations[key] = value

    def pause(self, reason: str) -> None:
        with self.condition:
            if self.pause_reason:
                return
            if not self.pause_path.exists():
                dump_new(self.pause_path, {"reason": reason, "time": datetime.now(UTC).isoformat()})
            self.exhausted = True
            self.pause_reason = reason
            self.condition.notify_all()

    def settle(self, key: str, value: float | None) -> None:
        with self.condition:
            reserved = self.reservations[key]
            charged = reserved if value is None else value
            self.event("settle", key, charged)
            self.reservations.pop(key)
            self.spent += charged
            self.condition.notify_all()


class CappedClient:
    """Equal run caps and pre-call cost reservation around the real API adapter."""

    def __init__(
        self,
        client: OpenAICompatibleLLMClient,
        budget: ExperimentBudget,
        run_id: str,
        *,
        temperature: float | None = None,
    ):
        if temperature is not None and (
            not math.isfinite(temperature) or not 0 <= temperature <= 2
        ):
            raise ValueError("temperature must be finite and in [0, 2]")
        self.client = client
        self.budget = budget
        self.run_id = run_id
        self.temperature = temperature

    def complete(self, *, messages, model=None, temperature=None, response_format=None):
        config = self.client.config
        # UTF-8 bytes conservatively bound BPE tokens for text; include role/framing overhead.
        input_upper = len(json.dumps(messages, ensure_ascii=False).encode()) + 1024
        maximum_tokens = input_upper + config.max_output_tokens
        if self.client.total_tokens + maximum_tokens > config.max_total_tokens_per_process:
            raise RunResourceLimitError(
                "token",
                "Per-run token cap cannot reserve a full next response: "
                f"observed={self.client.total_tokens}, input_upper={input_upper}, "
                f"output_reserved={config.max_output_tokens}, "
                f"cap={config.max_total_tokens_per_process}",
            )
        if len(self.client.calls) >= config.max_calls_per_process:
            raise RunResourceLimitError(
                "call",
                f"Per-run call cap reached: calls={len(self.client.calls)}, "
                f"cap={config.max_calls_per_process}",
            )
        upper_usd = (
            input_upper * config.input_price_usd_per_million
            + config.max_output_tokens * config.output_price_usd_per_million
        ) / 1_000_000
        key = f"{self.run_id}:call-{len(self.client.calls) + 1}"
        self.budget.reserve(key, upper_usd)
        start = len(self.client.calls)
        try:
            return self.client.complete(
                messages=messages,
                model=model,
                temperature=temperature if self.temperature is None else self.temperature,
                response_format=response_format,
            )
        except Exception as exc:
            recent = self.client.calls[start:]
            if recent and recent[-1].get("http_status") in {401, 402}:
                status = recent[-1]["http_status"]
                reason = f"Provider account unavailable: HTTP {status}; manual review required"
                self.budget.pause(reason)
                raise ExperimentPaused(reason) from exc
            raise
        finally:
            calls = self.client.calls[start:]
            known_cost = None
            if calls and all(call.get("estimated_cost_usd") is not None for call in calls):
                known_cost = sum(call["estimated_cost_usd"] for call in calls)
            self.budget.settle(key, known_cost)
            if known_cost is None:
                self.budget.pause(
                    "Unknown API usage/cost; conservative reservation retained; review required"
                )


def execute_method(method, request, client, run_dir, *, contract_version=V1):
    require_contract(contract_version)

    def save_stage(record):
        with (run_dir / "stages.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    if method == "B1_ONESHOT":
        return run_one_shot_baseline(
            request, client, common_final_validation=True, contract_version=contract_version
        )
    if method == "B1_FEEDBACK_1":
        return run_validator_feedback_baseline(
            request,
            client,
            max_repair_attempts=1,
            common_final_validation=True,
            contract_version=contract_version,
            on_attempt=lambda attempt: save_stage(attempt.to_record()),
        ).specification
    if method == "DECOMPOSED":
        return run_decomposed_baseline(
            request, client, on_stage=save_stage, contract_version=contract_version
        )
    if method in {"FULL", "NO_CRITIC", *CRITIC_METHODS}:
        with open_sqlite_checkpointer(run_dir / "checkpoints.sqlite") as checkpointer:
            if method == "FULL":
                graph = compile_live_pipeline(
                    client, checkpointer=checkpointer, contract_version=contract_version
                )
            elif method == "NO_CRITIC":
                graph = compile_pipeline(
                    live_pipeline_deps_without_critics(client, contract_version=contract_version),
                    checkpointer=checkpointer,
                )
            else:
                graph = compile_pipeline(
                    live_pipeline_deps_with_critic_budget(
                        client, int(method[-1]), contract_version=contract_version
                    ),
                    checkpointer=checkpointer,
                )
            config = thread_config(run_dir.name)
            try:
                state = graph.invoke({"request": request}, config=config)
            except Exception:
                values = graph.get_state(config).values
                partial = GeneratedSpecification(
                    request=request,
                    use_case_set=values.get("use_case_set"),
                    activity_results=values.get("activity_results") or [],
                    trace_manifest=values.get("trace_manifest") or {"links": []},
                    status=PipelineStatus.PARTIAL,
                )
                save_stage(
                    {
                        "phase": "interrupted_full_checkpoint",
                        "generated_specification": partial.model_dump(mode="json"),
                    }
                )
                raise
            return state["specification"]
    raise ValueError(method)


def run_task(task, plan, cases, config, budget, directory):
    run_id = f"{task['case_id']}__{task['method']}__r{task['repeat_id']:02d}"
    run_dir = directory / "runs" / run_id
    terminal = run_dir / "terminal.json"
    if terminal.exists():
        return json.loads(terminal.read_text())
    if budget.exhausted:
        return {**task, "experiment_paused": True, "started": False}
    if run_dir.exists():
        raise RuntimeError(f"Interrupted nonterminal run needs review, not rerun: {run_id}")
    run_dir.mkdir(parents=True)
    request = normalize_specification_req(cases[task["case_id"]]["specification_req"])
    request.max_repair_attempts = plan["full_repair_limit_per_artifact"]
    dump_new(run_dir / "input.json", request.model_dump(mode="json"))
    dump_new(
        run_dir / "started.json",
        {**task, "plan_sha256": digest(plan), "time": datetime.now(UTC).isoformat()},
    )
    raw_namespace = directory.name + "-" + digest(plan)[:12]
    raw_dir = ROOT / ".private_evidence/fair_baselines" / raw_namespace / run_id
    client_class = (
        AnthropicLLMClient if isinstance(config, AnthropicConfig) else OpenAICompatibleLLMClient
    )
    client = client_class(
        replace(config, telemetry_path=run_dir / "calls.jsonl", raw_capture_dir=raw_dir)
    )
    capped = CappedClient(client, budget, run_id, temperature=plan.get("temperature", 0))
    started = time.perf_counter()
    specification = None
    exception = None
    try:
        specification = execute_method(
            task["method"],
            request,
            capped,
            run_dir,
            contract_version=plan.get("formal_evaluator", V1),
        )
    except ExperimentPaused as exc:
        paused = {**task, "experiment_paused": True, "reason": str(exc)}
        dump_new(run_dir / "paused.json", paused)
        return paused
    except Exception as exc:
        # Keep exceptions explicit; never impute semantic zeros or retry a finished failure.
        exception = {
            "type": type(exc).__name__,
            "message": str(exc),
            "category": failure_category(exc),
        }
        dump_new(run_dir / "failure.json", exception)
    latency_ms = (time.perf_counter() - started) * 1000
    partial = False
    if specification is None and (run_dir / "stages.jsonl").exists():
        stages = (run_dir / "stages.jsonl").read_text().splitlines()
        if stages:
            specification = GeneratedSpecification.model_validate(
                json.loads(stages[-1])["generated_specification"]
            )
            partial = True
    if specification is None:
        specification = GeneratedSpecification(request=request, status=PipelineStatus.FAILED)
    if specification.use_case_set is not None:
        expected_ucs = {uc.id for uc in specification.use_case_set.use_cases}
        available_ucs = {
            item.use_case_id
            for item in specification.activity_results
            if item.activity_diagram is not None
        }
        partial = partial or not expected_ucs <= available_ucs
    formal = evaluate_contract(specification, plan.get("formal_evaluator", V1))
    # An interrupted call cannot deliver a complete successful run even if old data pass.
    success = formal.passed and exception is None
    dump_new(run_dir / "generated_specification.json", specification.model_dump(mode="json"))
    dump_new(run_dir / "common_formal_report.json", formal.model_dump(mode="json"))
    token_complete = all(call.get("total_tokens") is not None for call in client.calls)
    row = {
        **task,
        "run_id": run_id,
        "common_formal_success": int(success),
        "artifact_formal_pass": formal.passed,
        "pipeline_status": specification.status.value,
        "exception_type": None if exception is None else exception["type"],
        "failure_category": exception["category"]
        if exception
        else (None if formal.passed else "formal_rejection"),
        "resource_limit_reached": bool(
            exception and exception["category"] in {"run_token_limit", "run_call_limit"}
        ),
        "output_truncated": bool(
            exception and exception["type"] == LLMOutputTruncatedError.__name__
        ),
        "partial_output": partial,
        "uc_output_available": specification.use_case_set is not None,
        "use_case_count": 0
        if specification.use_case_set is None
        else len(specification.use_case_set.use_cases),
        "activity_count": sum(
            item.activity_diagram is not None for item in specification.activity_results
        ),
        "latency_ms": latency_ms,
        "llm_calls": len(client.calls),
        "critic_calls": sum("critic" in (call.get("llm_role") or "") for call in client.calls),
        "repair_calls": sum("repair" in (call.get("llm_role") or "") for call in client.calls),
        "formal_repair_diagnostics": formal_repair_diagnostics(specification.validation_reports),
        "http_attempts": sum(int(call.get("attempts", 0)) for call in client.calls),
        "total_tokens": client.total_tokens if token_complete else None,
        "observed_tokens": client.total_tokens,
        "estimated_cost_usd": client.total_cost_usd if token_complete else None,
        "observed_estimated_cost_usd": client.total_cost_usd,
        "resolved_models": sorted(
            {str(call.get("resolved_model")) for call in client.calls if call.get("resolved_model")}
        ),
        "response_hashes": [call.get("response_sha256") for call in client.calls],
        "artifact_file_sha256": hashlib.sha256(
            (run_dir / "generated_specification.json").read_bytes()
        ).hexdigest(),
        "plan_sha256": digest(plan),
    }
    dump_new(terminal, row)
    print(
        json.dumps(
            {k: row[k] for k in ["run_id", "common_formal_success", "llm_calls", "exception_type"]}
        ),
        flush=True,
    )
    return row


def run(args: argparse.Namespace) -> None:
    if not args.allow_live:
        raise SystemExit("run requires explicit --allow-live")
    plan = json.loads((args.directory / "plan.json").read_text())
    if plan["source_hashes"] != source_hashes():
        raise SystemExit("Source changed after prepare; create a new experiment plan")
    selected = load_experiment_cases(ROOT, plan.get("dataset", "dev20"), plan["cases"])
    if plan["cases_hash"] != digest(selected):
        raise SystemExit("DEV data/Gold changed after prepare")
    # Read only the required secret; model/settings come from the frozen plan, not .env.
    env = {}
    if args.env_file.exists():
        for raw in args.env_file.read_text().splitlines():
            if raw.strip() and not raw.lstrip().startswith("#") and "=" in raw:
                key, value = raw.split("=", 1)
                env[key.strip()] = value.strip().strip('"').strip("'")
    api_key = os.environ.get("DEEPSEEK_API_KEY") or env.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise SystemExit("Missing DEEPSEEK_API_KEY; secret value not printed")
    config = OpenAICompatibleConfig(
        provider=plan["provider"],
        api_base=plan["api_base"],
        model=plan["model"],
        api_key=api_key,
        max_output_tokens=plan["max_output_tokens"],
        max_calls_per_process=plan["max_run_calls"],
        max_total_tokens_per_process=plan["max_run_tokens"],
        max_retries=plan["http_retries"],
        timeout_seconds=plan["timeout_seconds"],
        thinking_enabled=plan["thinking_enabled"],
        input_price_usd_per_million=plan["input_usd_per_million_upper"],
        output_price_usd_per_million=plan["output_usd_per_million_upper"],
    )
    with (args.directory / "process.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("This experiment already has a running process") from None
        budget = ExperimentBudget(args.directory, plan["budget_usd"])
        if budget.reservations:
            raise SystemExit("Unsettled API reservations need evidence-backed reconciliation")
        cases = {case["case_id"]: case for case in selected}
        tasks = plan["tasks"]
        if args.max_tasks:
            tasks = tasks[: args.max_tasks]
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            rows = list(
                pool.map(
                    lambda task: run_task(task, plan, cases, config, budget, args.directory), tasks
                )
            )
        print(
            json.dumps(
                {
                    "terminal_runs": sum(not row.get("experiment_paused") for row in rows),
                    "budget_accounted_usd": budget.spent,
                    "matrix_complete": len(rows) == len(plan["tasks"])
                    and not any(row.get("experiment_paused") for row in rows),
                }
            ),
            flush=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "run"])
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--budget-usd", type=float)
    parser.add_argument("--repeats", type=int, choices=[1, 2, 3], default=3)
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--dataset", choices=["dev20", "size_inputs"], default="dev20")
    parser.add_argument("--method", action="append", choices=AVAILABLE_METHODS)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--contract-version", choices=CONTRACTS, default=V1)
    parser.add_argument("--max-output-tokens", type=int, default=PROFILE_MAX_OUTPUT_TOKENS)
    parser.add_argument("--max-run-tokens", type=int, default=2_000_000)
    parser.add_argument("--max-run-calls", type=int, default=512)
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--workers", type=int, choices=[1, 2, 3, 4], default=3)
    parser.add_argument("--max-tasks", type=int)
    args = parser.parse_args()
    try:
        validate_output_limit(args.max_output_tokens)
    except ValueError as exc:
        parser.error(str(exc))
    if args.max_tasks is not None and args.max_tasks < 1:
        raise SystemExit("max-tasks must be positive")
    (prepare if args.action == "prepare" else run)(args)


if __name__ == "__main__":
    main()
