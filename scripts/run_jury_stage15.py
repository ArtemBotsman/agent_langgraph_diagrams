"""Frozen downstream-code experiment; generation never reads reference tests/solutions."""

from __future__ import annotations

import argparse
import ast
import fcntl
import hashlib
import json
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import run_fair_baseline_experiment as fair
import run_jury_stage13 as stage13
from jury_opencode_gateway import CLI
from jury_stage13_providers import PROFILES, ROOT, credential, preflight

from traceable_spec.evaluation.contracts import V2
from traceable_spec.llm.openai_compatible import OpenAICompatibleConfig, OpenAICompatibleLLMClient
from traceable_spec.reference_methods.baselines import run_one_shot_baseline
from traceable_spec.reference_methods.opencode_plan import parse_event_log

DIRECTORY = ROOT / ".private_evidence/jury_stage15_codegen"
INPUTS = ROOT / ".private_evidence/jury_stage14_external_tests/calibration_v1/model_inputs"
METHODS = ("RAW", "B1_FEEDBACK_1", "FULL", "OPENCODE_PLAN_CONTRACT")
CODE_SYSTEM = (
    "Implement the supplied Python class as a complete executable Python module. "
    "Preserve the public class name, signatures, constructor, attributes, exact return "
    "values and error behavior stated in the original task. Include required imports. "
    "Original requirements are authoritative. An optional auxiliary specification may "
    "help, but can contain mistakes and must not override the original task. "
    "Return only Python source, without Markdown, tests, commentary or placeholders. "
    "Use only the Python standard library. Do not inspect files, network, runtime tests "
    "or the evaluation environment. Implement task behavior, not evaluator manipulation."
)


def h(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_object(text):
    """Predeclared shared envelope policy, independent of validation outcome."""
    fences = re.findall(r"(?m)^[ \t]*```[^\r\n]*$", text)
    if len(fences) != 2:
        return text
    match = re.search(
        r"(?ms)^[ \t]*```(?:json)?[ \t]*\r?\n(.*?)\r?\n[ \t]*```[ \t]*(?=\r?\n|\Z)", text
    )
    if match:
        try:
            if isinstance(json.loads(match.group(1)), dict):
                return match.group(1)
        except json.JSONDecodeError:
            pass
    return text


class PlanClient(fair.CappedClient):
    def complete(self, **kwargs):
        return json_object(super().complete(**kwargs))


def import_external(request, raw):
    parsed = parse_event_log(raw)

    class Answer:
        def complete(self, **kwargs):
            return json_object(parsed["text"])

    return run_one_shot_baseline(
        request, Answer(), common_final_validation=True, contract_version=V2
    ), parsed


def extract_code(text):
    match = re.fullmatch(r"\s*```(?:python|py)?[ \t]*\r?\n(.*?)\r?\n```\s*", text, re.S | re.I)
    source = match.group(1) if match else text
    ast.parse(source)  # Syntax check only; never execute generated code on host.
    return source.strip() + "\n"


def code_messages(visible, specification):
    allowed = {
        k: visible[k]
        for k in (
            "task_id",
            "class_name",
            "class_description",
            "skeleton",
            "import_statement",
            "class_constructor",
            "fields",
        )
    }
    allowed["methods"] = [
        {k: m[k] for k in ("method_name", "method_description")} for m in visible["methods"]
    ]
    return [
        {"role": "system", "content": CODE_SYSTEM},
        {
            "role": "user",
            "content": json.dumps(
                {"original_task": allowed, "auxiliary_specification": specification},
                ensure_ascii=False,
            ),
        },
    ]


def sources():
    result = fair.source_hashes()
    for name in (
        "run_jury_stage15.py",
        "run_jury_stage13.py",
        "jury_stage13_providers.py",
        "jury_opencode_gateway.py",
        "run_classeval_calibration.py",
        "classeval_worker.py",
    ):
        p = ROOT / "scripts" / name
        result[str(p.relative_to(ROOT))] = h(p)
    result["opencode-binary"] = h(CLI.resolve())
    return result


def prepare(directory):
    visible = {p.stem: json.loads(p.read_text()) for p in sorted(INPUTS.glob("*.json"))}
    if len(visible) != 10:
        raise ValueError("Expected frozen ten input-only tasks")
    availability = preflight()
    if not all(x["available"] for x in availability if x["provider"] in {"openai", "deepseek"}):
        raise ValueError("Required primary model unavailable")
    tasks = [
        {"case_id": c, "method": m, "repeat_id": r, "temperature": 0.2}
        for r in range(1, 4)
        for c in visible
        for m in METHODS
    ]
    random.Random(151028).shuffle(tasks)
    plan = {
        "version": "stage15-external-code-v1",
        "budget_usd": 10.0,
        "planning_cap_usd": 5.5,
        "authorization": (
            "Additional USD10 authorized in latest user message; separate from stage13 USD15."
        ),
        "temperature": 0.2,
        "formal_evaluator": V2,
        "full_repair_limit_per_artifact": 2,
        "max_output_tokens": 64000,
        "max_run_tokens": 2000000,
        "max_run_calls": 512,
        "code_max_output_tokens": 16384,
        "http_retries": 0,
        "planner_provider": "deepseek",
        "code_providers": ["openai", "deepseek"],
        "profiles": {k: PROFILES[k] for k in ("deepseek", "openai")},
        "source_hashes": sources(),
        "visible_inputs_digest": fair.digest(visible),
        "input_hashes": {p.name: h(p) for p in sorted(INPUTS.glob("*.json"))},
        "tasks": tasks,
        "code_system": CODE_SYSTEM,
        "planning_envelope": (
            "one JSON object or exactly one JSON fence, optional surrounding prose; "
            "same for every role/method"
        ),
        "code_envelope": "raw Python or one whole Python fence; AST parse, no repair",
        "phase_order": (
            "all planning; GPT5.1 code; DeepSeek code if primary complete and >=USD0.5 remains; "
            "seal; external tests"
        ),
        "budget_projection_usd": {
            "planning": [2, 5.5],
            "primary_code": [1, 3],
            "secondary_code": [0.2, 0.8],
        },
        "projection_is_not_guarantee": True,
        "outcomes": (
            "Primary all external class tests pass; secondary macro per-class test fraction. "
            "No test-based repair/selection."
        ),
        "upstream_policy": (
            "Forward UC and Activity content even if own formal checks fail. "
            "No usable UC => upstream failure, no RAW fallback."
        ),
        "incomplete_policy": (
            "Budget-paused/unstarted is missing, not functional failure; "
            "incomplete paired contrasts descriptive only."
        ),
        "statistics": (
            "10 fixed tasks, mean of 3 repeats per task. Paired task bootstrap 95% CI; "
            "exact sign-flip, Holm 3 FULL contrasts per code backend. "
            "Nonrandom sample limits inference."
        ),
        "limitations": (
            "Convenience ClassEval subset, public data contamination possible; "
            "not supervisor projects, not ambiguity measurement. "
            "Planner backend fixed; code backend varied."
        ),
    }
    directory.mkdir(parents=True, exist_ok=False)
    fair.dump_new(directory / "plan.json", plan)
    fair.dump_new(directory / "availability.json", availability)
    fair.dump_new(directory / "visible_inputs.json", visible)
    print(
        json.dumps(
            {
                "frozen_tasks": len(tasks),
                "planning_tasks": 90,
                "budget_usd": 10,
                "plan_sha256": fair.digest(plan),
            }
        ),
        flush=True,
    )


def config(provider, output):
    p = PROFILES[provider]
    return OpenAICompatibleConfig(
        provider=provider,
        model=p["model"],
        api_base=p["api_base"],
        api_key=credential(p),
        max_output_tokens=output,
        max_retries=0,
        timeout_seconds=600,
        max_calls_per_process=512,
        max_total_tokens_per_process=2000000,
        thinking_enabled=False,
        reasoning_effort=p["reasoning_effort"],
        streaming=provider == "openai",
        input_price_usd_per_million=p["input_price"],
        output_price_usd_per_million=p["output_price"],
    )


def run_id(task):
    return f"{task['case_id']}__{task['method']}__r{task['repeat_id']:02d}"


def auxiliary(directory, task):
    if task["method"] == "RAW":
        return None
    p = directory / "planning/runs" / run_id(task) / "generated_specification.json"
    if not p.exists():
        raise ValueError("No upstream specification")
    d = json.loads(p.read_text())
    if not d.get("use_case_set") or not d["use_case_set"].get("use_cases"):
        raise ValueError("No usable upstream UC")
    return {
        "use_case_set": d["use_case_set"],
        "activities": [
            {k: v for k, v in a.items() if k in {"use_case_id", "activity_diagram"}}
            for a in d.get("activity_results", [])
        ],
    }


def generate_code(directory, task, provider, plan, visible, budget):
    rid = run_id(task)
    folder = directory / "code" / provider / rid
    if (folder / "terminal.json").exists():
        return json.loads((folder / "terminal.json").read_text())
    if folder.exists():
        raise ValueError("Interrupted code run requires review, never automatic retry")
    if budget.exhausted:
        return {"missing": True}
    folder.mkdir(parents=True)
    fair.dump_new(
        folder / "started.json", {**task, "provider": provider, "plan_sha256": fair.digest(plan)}
    )
    row = {**task, "provider": provider, "run_id": rid, "status": "pending"}
    started = time.monotonic()
    try:
        spec = auxiliary(directory, task)
    except ValueError:
        row["status"] = "upstream_failure"
    else:
        messages = code_messages(visible[task["case_id"]], spec)
        fair.dump_new(folder / "messages.json", messages)
        client = OpenAICompatibleLLMClient(
            replace(
                config(provider, plan["code_max_output_tokens"]),
                raw_capture_dir=folder / "raw",
                telemetry_path=folder / "calls.jsonl",
            )
        )
        capped = fair.CappedClient(client, budget, f"code:{provider}:{rid}", temperature=0.2)
        try:
            text = capped.complete(messages=messages)
            (folder / "answer.txt").write_text(text)
            source = extract_code(text)
            (folder / "candidate.py").write_text(source)
            row.update(status="generated", candidate_sha256=h(folder / "candidate.py"))
        except (fair.ExperimentPaused, fair.ExperimentCostCeiling) as exc:
            fair.dump_new(folder / "paused.json", {"error_type": type(exc).__name__})
            return {**row, "missing": True}
        except Exception as exc:
            row.update(status="generation_or_format_failure", error_type=type(exc).__name__)
        row["calls"] = client.calls
        row["estimated_cost_usd"] = client.total_cost_usd
        row["output_truncated"] = any(c.get("output_truncated") for c in client.calls)
    row["latency_ms"] = 1000 * (time.monotonic() - started)
    fair.dump_new(folder / "terminal.json", row)
    print(
        json.dumps(
            {"code": provider, "run": rid, "status": row["status"], "spent_upper": budget.spent}
        ),
        flush=True,
    )
    return row


def run(directory, phase, workers):
    plan = json.loads((directory / "plan.json").read_text())
    if plan["source_hashes"] != sources() or any(
        h(INPUTS / k) != v for k, v in plan["input_hashes"].items()
    ):
        raise ValueError("Frozen source/input mismatch")
    if (directory / "generation_seal.json").exists():
        raise ValueError("Generation already sealed; no more paid outputs")
    with (directory / "process.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        budget = fair.ExperimentBudget(
            directory, plan["planning_cap_usd"] if phase == "planning" else 10.0
        )
        if budget.reservations or budget.pause_reason:
            raise ValueError("Budget needs reconciliation")
        visible = json.loads((directory / "visible_inputs.json").read_text())
        if fair.digest(visible) != plan["visible_inputs_digest"]:
            raise ValueError("Copied input data changed")
        cases = {k: {"specification_req": v["specification_req"]} for k, v in visible.items()}
        tasks = plan["tasks"]
        if phase == "planning":
            fair.CappedClient = PlanClient
            stage13.import_final_package = import_external
            cfg = config("deepseek", 64000)
            folder = directory / "planning"
            folder.mkdir(exist_ok=True)
            tasks = [t for t in tasks if t["method"] != "RAW"]

            def execute(t):
                if budget.exhausted:
                    return {"missing": True}
                if t["method"] == "OPENCODE_PLAN_CONTRACT":
                    return stage13.external_task(t, plan, cases[t["case_id"]], budget, folder)
                return fair.run_task(t, plan, cases, cfg, budget, folder)
        else:
            if not all(
                (directory / "planning/runs" / run_id(t) / "terminal.json").exists()
                for t in tasks
                if t["method"] != "RAW"
            ):
                raise ValueError(
                    "Complete or explicitly adjudicate planning before code generation"
                )
            if phase == "deepseek":
                if not all(
                    (directory / "code/openai" / run_id(t) / "terminal.json").exists()
                    for t in tasks
                ):
                    raise ValueError("Primary code phase incomplete")
                if 10.0 - budget.spent < 0.5:
                    raise ValueError("Secondary phase admission requires USD0.5 remaining")

            def execute(t):
                return generate_code(directory, t, phase, plan, visible, budget)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(execute, tasks))
        print(
            json.dumps(
                {
                    "phase": phase,
                    "rows": len(rows),
                    "spent_upper": budget.spent,
                    "open_reservations": budget.reservations,
                    "paused": budget.pause_reason,
                }
            ),
            flush=True,
        )


def seal(directory):
    files = {
        str(p.relative_to(directory)): h(p)
        for p in directory.rglob("*")
        if p.is_file() and p.name != "process.lock" and p.suffix not in {"-wal", "-shm"}
    }
    fair.dump_new(directory / "generation_seal.json", {"files": files, "outcomes_observed": False})
    print(json.dumps({"sealed_files": len(files)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "planning", "openai", "deepseek", "seal"])
    parser.add_argument("--directory", type=Path, default=DIRECTORY)
    parser.add_argument("--workers", type=int, choices=[1, 2, 3, 4], default=3)
    parser.add_argument("--allow-live", action="store_true")
    a = parser.parse_args()
    if a.action == "prepare":
        prepare(a.directory)
    elif a.action == "seal":
        seal(a.directory)
    elif a.allow_live:
        run(a.directory, a.action, a.workers)
    else:
        parser.error("Paid phases require --allow-live")


if __name__ == "__main__":
    main()
