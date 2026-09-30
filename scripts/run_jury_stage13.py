"""Three-project, three-backend sequential pilot under an additional $10 cap."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from jury_opencode_gateway import CLI, run_cli
from jury_stage13_providers import PROFILES, ROOT, credential, preflight
from run_fair_baseline_experiment import (
    CappedClient,
    ExperimentBudget,
    digest,
    dump_new,
    run_task,
    source_hashes,
)

from traceable_spec.entities import normalize_specification_req
from traceable_spec.evaluation.contracts import V2, evaluate_contract
from traceable_spec.evaluation.experiment_cases import load_experiment_cases
from traceable_spec.llm.anthropic import AnthropicConfig, AnthropicLLMClient
from traceable_spec.llm.openai_compatible import OpenAICompatibleConfig, OpenAICompatibleLLMClient
from traceable_spec.reference_methods.opencode_plan import import_final_package, task_contract

DIRECTORY = ROOT / ".private_evidence/jury_stage13_live_v3"
CASES = ["SCALE-001", "SCALE-002", "SCALE-003"]


def frozen_sources():
    hashes = source_hashes()
    for name in ("run_jury_stage13.py", "jury_stage13_providers.py", "jury_opencode_gateway.py"):
        p = ROOT / "scripts" / name
        hashes[str(p.relative_to(ROOT))] = hashlib.sha256(p.read_bytes()).hexdigest()
    hashes["opencode-binary"] = hashlib.sha256(CLI.resolve().read_bytes()).hexdigest()
    return hashes


def prepare(directory):
    selected = load_experiment_cases(ROOT, "size_inputs", CASES)
    available = preflight()
    if not all(x["available"] for x in available):
        raise ValueError("Requested provider model unavailable")
    phases = {"comparison": [], "temperature": [], "critic": []}
    for r in range(1, 4):
        block = []
        for c in CASES:
            for provider in PROFILES:
                for method in ("B1_FEEDBACK_1", "FULL"):
                    block.append(
                        dict(
                            case_id=c,
                            provider=provider,
                            method=method,
                            repeat_id=r,
                            temperature=0.2,
                        )
                    )
            block.append(
                dict(
                    case_id=c,
                    provider="deepseek",
                    method="OPENCODE_PLAN_CONTRACT",
                    repeat_id=r,
                    temperature=0.2,
                )
            )
        random.Random(20260928 + r).shuffle(block)
        phases["comparison"].extend(block)
        for c in CASES:
            for t in (0.0, 0.7):
                for m in ("B1_FEEDBACK_1", "FULL"):
                    phases["temperature"].append(
                        dict(case_id=c, provider="deepseek", method=m, repeat_id=r, temperature=t)
                    )
            for n in range(4):
                phases["critic"].append(
                    dict(
                        case_id=c,
                        provider="deepseek",
                        method=f"CRITIC_{n}",
                        repeat_id=r,
                        temperature=0.2,
                    )
                )
    old = ROOT / ".private_evidence/fresh_supervisor_v2_stage10/runs"
    estimates = {}
    for provider, p in PROFILES.items():
        costs = []
        for method in ("B1_FEEDBACK_1", "FULL"):
            calls = [
                json.loads(line)
                for line in (old / f"SCALE-001__{method}__r01/calls.jsonl").read_text().splitlines()
            ]
            costs.append(
                sum(
                    x["prompt_tokens"] * p["input_price"]
                    + x["completion_tokens"] * p["output_price"]
                    for x in calls
                )
                / 1e6
            )
        estimates[provider] = 9 * sum(costs)
    plan = {
        "version": "stage13-pilot-1",
        "budget_usd": 10.0,
        "authorization": "User explicitly approved additional USD 10 in this task; no overage",
        "historical_spent_upper_usd": 9.1519416,
        "profiles": PROFILES,
        "source_hashes": frozen_sources(),
        "cases": CASES,
        "cases_hash": digest(selected),
        "dataset": "size_inputs",
        "selection": "First three smallest projects, fixed before new outcomes (6,7,8 FR)",
        "formal_evaluator": V2,
        "full_repair_limit_per_artifact": 2,
        "max_output_tokens": 64000,
        "max_run_tokens": 2000000,
        "max_run_calls": 512,
        "http_retries": 0,
        "streaming": {"openai": True, "anthropic": True, "deepseek": False},
        "phases": phases,
        "comparison_cost_projection_from_six_FR": estimates,
        "projection_warning": "Projection only; global pre-call reservations enforce USD10.",
        "phase_admission": (
            "Comparison, temperatures, critic; later phases depend on remaining budget."
        ),
        "statistical_unit": "project, average 3 repeats; 3 projects are an underpowered pilot",
        "gold": None,
        "human_annotations": 0,
        "semantic_metrics": "N/A; no invented Gold or independent annotations",
        "primary_outcome": "common_formal_success",
        "primary_contrasts": [
            "FULL-FB within each model",
            "FULL-OpenCode on DeepSeek",
            "interaction versus DeepSeek",
            "temperature interactions",
            "critic adjacent limits",
        ],
        "external_variant": (
            "Stock OpenCode1.18.33 Plan with shared typed contract; read-only tools; "
            "no shell/network/delegation, no custom system prompt; buffered HTTP transport"
        ),
    }
    directory.mkdir(parents=True, exist_ok=False)
    dump_new(directory / "plan.json", plan)
    dump_new(directory / "availability.json", available)
    previous = ROOT / ".private_evidence/jury_stage13_live_v2"
    carried = ExperimentBudget(previous, 10.0).spent
    budget = ExperimentBudget(directory, 10.0)
    budget.reserve("previous_preflight_upper", carried)
    budget.settle("previous_preflight_upper", carried)
    dump_new(
        directory / "preflight_carry.json",
        {
            "source": str(previous),
            "upper_usd": carried,
            "reason": "Prior transport diagnostics and unknown-cost holds retained. "
            "OpenAI/Claude now use streaming. Earlier failed matrix is preserved separately.",
        },
    )
    print(
        json.dumps(
            {
                "tasks": {k: len(v) for k, v in phases.items()},
                "cost_projection": estimates,
                "plan_sha256": digest(plan),
            }
        ),
        flush=True,
    )


def external_task(task, plan, case, budget, folder):
    run_id = f"{task['case_id']}__{task['method']}__r{task['repeat_id']:02d}"
    run_dir = folder / "runs" / run_id
    if (run_dir / "terminal.json").exists():
        return json.loads((run_dir / "terminal.json").read_text())
    if run_dir.exists():
        raise ValueError("Interrupted external run requires review")
    run_dir.mkdir(parents=True)
    request = normalize_specification_req(case["specification_req"])
    request.max_repair_attempts = 2
    dump_new(run_dir / "input.json", request.model_dump(mode="json"))
    packet = task_contract(request)
    dump_new(run_dir / "task.json", packet)
    dump_new(run_dir / "started.json", {**task, "plan_sha256": digest(plan)})
    start = time.perf_counter()
    calls, code = run_cli(
        packet, run_dir / "cli", budget, folder.name + ":" + run_id, temperature=task["temperature"]
    )
    error, spec, parsed = None, None, None
    try:
        if code != 0:
            raise ValueError("OpenCode process failed")
        spec, parsed = import_final_package(request, (run_dir / "cli/events.jsonl").read_text())
        formal = evaluate_contract(spec, V2)
        dump_new(run_dir / "generated_specification.json", spec.model_dump(mode="json"))
        dump_new(run_dir / "common_formal_report.json", formal.model_dump(mode="json"))
    except Exception as exc:
        error = type(exc).__name__ + ": " + str(exc)
    row = {
        **task,
        "run_id": run_id,
        "plan_sha256": digest(plan),
        "common_formal_success": int(error is None and formal.passed),
        "failure_category": "external_execution_or_format"
        if error
        else (None if formal.passed else "formal_rejection"),
        "error": error,
        "llm_calls": len(calls),
        "total_tokens": sum(c["total_tokens"] for c in calls),
        "estimated_cost_usd": sum(c["estimated_cost_usd"] for c in calls),
        "latency_ms": (time.perf_counter() - start) * 1000,
        "output_truncated": any(c["finish_reason"] == "length" for c in calls),
        "external_step_count": len(parsed["step_finishes"]) if parsed else None,
        "tool_events": sum(
            json.loads(line).get("type") == "tool_use"
            for line in (run_dir / "cli/events.jsonl").read_text().splitlines()
            if line.strip()
        ),
    }
    dump_new(run_dir / "terminal.json", row)
    return row


def run(directory, phase, workers):
    plan = json.loads((directory / "plan.json").read_text())
    if plan["source_hashes"] != frozen_sources():
        raise ValueError("Frozen source mismatch")
    selected = load_experiment_cases(ROOT, "size_inputs", CASES)
    if digest(selected) != plan["cases_hash"]:
        raise ValueError("Dataset changed")
    cases = {c["case_id"]: c for c in selected}
    with (directory / "process.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        budget = ExperimentBudget(directory, 10.0)
        if budget.reservations or budget.pause_reason:
            raise ValueError("Budget needs reconciliation")

        def execute(task):
            if budget.exhausted:
                return {**task, "experiment_paused": True}
            folder = directory / f"{task['provider']}_t{task['temperature']:g}"
            folder.mkdir(exist_ok=True)
            local = {**plan, "temperature": task["temperature"]}
            if task["method"] == "OPENCODE_PLAN_CONTRACT":
                row = external_task(task, local, cases[task["case_id"]], budget, folder)
            else:
                p = PROFILES[task["provider"]]
                cls = AnthropicConfig if task["provider"] == "anthropic" else OpenAICompatibleConfig
                cfg = cls(
                    provider=p["provider"],
                    api_base=p["api_base"],
                    model=p["model"],
                    api_key=credential(p),
                    reasoning_effort=p["reasoning_effort"],
                    max_output_tokens=64000,
                    max_calls_per_process=512,
                    max_total_tokens_per_process=2000000,
                    max_retries=0,
                    timeout_seconds=600,
                    streaming=task["provider"] in {"openai", "anthropic"},
                    input_price_usd_per_million=p["input_price"],
                    output_price_usd_per_million=p["output_price"],
                )

                # Namespace reservation IDs across model/temperature cells.
                class NamespacedBudget:
                    def __getattr__(self, name):
                        return getattr(budget, name)

                    def reserve(self, key, value):
                        return budget.reserve(folder.name + ":" + key, value)

                    def settle(self, key, value):
                        return budget.settle(folder.name + ":" + key, value)

                row = run_task(task, local, cases, cfg, NamespacedBudget(), folder)
            print(
                json.dumps(
                    {
                        "task": task,
                        "success": row.get("common_formal_success"),
                        "calls": row.get("llm_calls"),
                        "cost": row.get("estimated_cost_usd"),
                        "budget_spent": budget.spent,
                        "paused": row.get("experiment_paused", False),
                    }
                ),
                flush=True,
            )
            return row

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(execute, task) for task in plan["phases"][phase]]
            for future in as_completed(futures):
                future.result()
        print(
            json.dumps(
                {
                    "phase": phase,
                    "spent": budget.spent,
                    "reservations": budget.reservations,
                    "pause_reason": budget.pause_reason,
                }
            ),
            flush=True,
        )


def canary(directory):
    plan = json.loads((directory / "plan.json").read_text())
    if plan["source_hashes"] != frozen_sources():
        raise ValueError("Frozen source mismatch")
    budget = ExperimentBudget(directory, 10.0)
    for name, p in PROFILES.items():
        folder = directory / "canary" / name
        folder.mkdir(parents=True, exist_ok=False)
        cls, client_cls = (
            (AnthropicConfig, AnthropicLLMClient)
            if name == "anthropic"
            else (OpenAICompatibleConfig, OpenAICompatibleLLMClient)
        )
        cfg = cls(
            provider=p["provider"],
            api_base=p["api_base"],
            model=p["model"],
            api_key=credential(p),
            reasoning_effort=p["reasoning_effort"],
            max_output_tokens=64000,
            max_retries=0,
            timeout_seconds=600,
            streaming=name in {"openai", "anthropic"},
            max_total_tokens_per_process=2000000,
            input_price_usd_per_million=p["input_price"],
            output_price_usd_per_million=p["output_price"],
            telemetry_path=folder / "calls.jsonl",
            raw_capture_dir=folder / "raw",
        )
        client = client_cls(cfg)
        text = CappedClient(client, budget, "canary-" + name, temperature=0.2).complete(
            messages=[
                {
                    "role": "user",
                    "content": 'Return exactly the JSON object {"ok":true}, with no commentary.',
                }
            ]
        )
        dump_new(folder / "result.json", {"output": text, "cost": client.total_cost_usd})
        print(json.dumps({"canary": name, "cost": client.total_cost_usd, "text": text}), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["prepare", "run", "canary"])
    p.add_argument("--directory", type=Path, default=DIRECTORY)
    p.add_argument("--phase", choices=["comparison", "temperature", "critic"], default="comparison")
    p.add_argument("--allow-live", action="store_true")
    p.add_argument("--workers", type=int, choices=[1, 2, 3], default=3)
    a = p.parse_args()
    if a.action in {"run", "canary"} and not a.allow_live:
        p.error("Explicit --allow-live required")
    if a.action == "prepare":
        prepare(a.directory)
    elif a.action == "canary":
        canary(a.directory)
    else:
        run(a.directory, a.phase, a.workers)
