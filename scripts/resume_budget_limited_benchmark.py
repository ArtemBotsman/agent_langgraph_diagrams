"""Resume only benchmark runs stopped by the process-wide LLM budget.

The source experiment is immutable. Each pending LangGraph checkpoint is copied
to a new experiment directory and resumed with the original thread identifier.
Completed source rows are referenced, not executed again. The resulting
``results.json`` contains the original completed rows plus the resumed rows.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from run_benchmark_experiment import _load_local_env, _write_run_artifacts

from traceable_spec.entities import PipelineStatus
from traceable_spec.evaluation.aggregation import attach_repeat_stability, summarize_rows
from traceable_spec.evaluation.benchmark import evaluate_semantic_projection
from traceable_spec.evaluation.projection import automatic_metrics, semantic_projection
from traceable_spec.evaluation.similarity import MultilingualSentenceSimilarity
from traceable_spec.llm.factory import create_instrumented_client, provider_config_from_env
from traceable_spec.orchestration.component_variants import live_pipeline_deps_without_critics
from traceable_spec.orchestration.persistence import open_sqlite_checkpointer, thread_config
from traceable_spec.orchestration.pipeline import compile_pipeline

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "benchmark" / "v1_0_synthetic" / "cases.json"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-experiment-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--max-live-calls", type=int, default=450)
    parser.add_argument("--max-live-tokens", type=int, default=2_300_000)
    parser.add_argument("--max-estimated-cost-usd", type=float, default=1.60)
    return parser.parse_args()


def _git_value(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _row_cost(
    row: dict[str, Any],
    input_price: float | None,
    output_price: float | None,
) -> float | None:
    if input_price is None or output_price is None:
        return None
    return (
        int(row.get("prompt_tokens") or 0) * input_price
        + int(row.get("completion_tokens") or 0) * output_price
    ) / 1_000_000


def main() -> None:
    args = _parse_args()
    source_dir = args.source_experiment_dir.resolve()
    output_dir = args.output_dir.resolve()
    if output_dir.exists():
        raise SystemExit(f"Output directory already exists: {output_dir}")

    source_path = source_dir / "results.json"
    source_result = json.loads(source_path.read_text(encoding="utf-8"))
    source_rows: list[dict[str, Any]] = source_result["rows"]
    pending = [
        row for row in source_rows if row.get("error_type") == "LLMBudgetExceededError"
    ]
    if not pending:
        raise SystemExit("No LLMBudgetExceededError rows to resume")
    if {row["condition"] for row in pending} != {"FULL_NO_CRITIC"}:
        raise SystemExit("This recovery script only supports FULL_NO_CRITIC")

    cases = {
        case["case_id"]: case
        for case in json.loads(CASES_PATH.read_text(encoding="utf-8"))
    }
    output_dir.mkdir(parents=True)
    _load_local_env(args.env_file)
    llm_config = replace(
        provider_config_from_env(),
        telemetry_path=output_dir / "all_calls.jsonl",
        raw_capture_dir=None,
        max_calls_per_process=args.max_live_calls,
        max_total_tokens_per_process=args.max_live_tokens,
        max_estimated_cost_usd=args.max_estimated_cost_usd,
    )
    client = create_instrumented_client(llm_config)
    similarity = MultilingualSentenceSimilarity(local_files_only=True)

    completed_by_key = {
        (row["condition"], row["case_id"], int(row["repeat_id"])): dict(row)
        for row in source_rows
        if row.get("error_type") != "LLMBudgetExceededError"
    }
    resumed_by_key: dict[tuple[str, str, int], dict[str, Any]] = {}

    for original in pending:
        condition = original["condition"]
        case_id = original["case_id"]
        repeat_id = int(original["repeat_id"])
        case = cases[case_id]
        key = (condition, case_id, repeat_id)
        source_run = source_dir / condition / case_id / f"r{repeat_id:02d}"
        output_run = output_dir / condition / case_id / f"r{repeat_id:02d}"
        output_run.mkdir(parents=True)
        source_checkpoint = source_run / "checkpoints.sqlite"
        if not source_checkpoint.exists():
            raise SystemExit(f"Checkpoint not found: {source_checkpoint}")
        checkpoint_path = output_run / "checkpoints.sqlite"
        shutil.copy2(source_checkpoint, checkpoint_path)
        source_failure = source_run / "failure.json"
        if source_failure.exists():
            shutil.copy2(source_failure, output_run / "source_failure.json")

        run_config = {
            "experiment_id": output_dir.name,
            "source_experiment_id": source_result["experiment_id"],
            "resumed_from_checkpoint": str(source_checkpoint.relative_to(ROOT)),
            "condition": condition,
            "case_id": case_id,
            "split": case["split"],
            "repeat_id": repeat_id,
            "benchmark_version": source_result["benchmark_version"],
            "cases_sha256": source_result["cases_sha256"],
            "git_commit": _git_value("rev-parse", "HEAD"),
            "git_dirty": bool(_git_value("status", "--porcelain")),
            "provider": llm_config.provider,
            "api_base": llm_config.api_base,
            "model": llm_config.model,
            "requested_temperature": 0,
            "effective_temperature": 0,
            "prompt_version": "2026-09-09-v1",
            "schema_version": "0.2.0",
            "semantic_similarity_backend": similarity.name,
            "raw_prompts_or_responses_persisted": False,
            "raw_evidence_policy": "hashes_only",
            "max_calls_per_process": llm_config.max_calls_per_process,
            "max_total_tokens_per_process": llm_config.max_total_tokens_per_process,
            "max_estimated_cost_usd": llm_config.max_estimated_cost_usd,
        }

        call_start = len(client.calls)
        tokens_start = client.total_tokens
        cost_start = client.total_cost_usd
        started = time.perf_counter()
        try:
            with open_sqlite_checkpointer(checkpoint_path) as checkpointer:
                graph = compile_pipeline(
                    live_pipeline_deps_without_critics(client), checkpointer=checkpointer
                )
                config = thread_config(f"{case_id}-{condition}-r{repeat_id:02d}")
                before = graph.get_state(config)
                if not before.values:
                    raise RuntimeError("Checkpoint thread has no state")
                if not before.next:
                    raise RuntimeError("Checkpoint is already terminal")
                state = graph.invoke(None, config=config)
            specification = state["specification"]
            new_calls = client.calls[call_start:]
            new_prompt_tokens = sum(int(call.get("prompt_tokens") or 0) for call in new_calls)
            new_completion_tokens = sum(
                int(call.get("completion_tokens") or 0) for call in new_calls
            )
            prior_cost = _row_cost(
                original,
                llm_config.input_price_usd_per_million,
                llm_config.output_price_usd_per_million,
            )
            new_cost = client.total_cost_usd - cost_start
            runtime = {
                "latency_ms": round(
                    float(original.get("latency_ms") or 0)
                    + (time.perf_counter() - started) * 1000,
                    3,
                ),
                "llm_calls": int(original.get("llm_calls") or 0) + len(new_calls),
                "prompt_tokens": int(original.get("prompt_tokens") or 0)
                + new_prompt_tokens,
                "completion_tokens": int(original.get("completion_tokens") or 0)
                + new_completion_tokens,
                "total_tokens": int(original.get("total_tokens") or 0)
                + (client.total_tokens - tokens_start),
                "estimated_cost_usd": (
                    None if prior_cost is None else prior_cost + new_cost
                ),
                "repair_attempts": specification.uc_repair_attempts_used
                + sum(
                    item.repair_attempts_used for item in specification.activity_results
                ),
            }
            semantic = evaluate_semantic_projection(
                semantic_projection(specification),
                case["gold"],
                similarity=similarity,
                similarity_name=similarity.name,
            )
            metrics = {**automatic_metrics(specification), **semantic, **runtime}
            _write_run_artifacts(output_run, case, run_config, specification, metrics)
            if new_calls:
                with (output_run / "calls.jsonl").open("w", encoding="utf-8") as handle:
                    for call in new_calls:
                        handle.write(json.dumps(call, ensure_ascii=False, sort_keys=True) + "\n")
            row = {
                "condition": condition,
                "case_id": case_id,
                "split": case["split"],
                "complexity": case["complexity"],
                "language": case["language"],
                "repeat_id": repeat_id,
                "run_status": specification.status.value,
                "resumed_from_checkpoint": True,
                "prior_budget_guard_calls": int(original.get("llm_calls") or 0),
                **metrics,
            }
        except Exception as exc:
            new_calls = client.calls[call_start:]
            failure = {"error_type": type(exc).__name__, "message": str(exc)}
            (output_run / "failure.json").write_text(
                json.dumps(failure, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            row = {
                "condition": condition,
                "case_id": case_id,
                "split": case["split"],
                "complexity": case["complexity"],
                "language": case["language"],
                "repeat_id": repeat_id,
                "run_status": PipelineStatus.FAILED.value,
                "end_to_end_success": 0.0,
                "semantic_composite": 0.0,
                "actor_f1": 0.0,
                "uc_f1": 0.0,
                "milestone_f1": 0.0,
                "branch_f1": 0.0,
                "trace_f1": 0.0,
                "hallucination_rate": 1.0,
                "latency_ms": round(
                    float(original.get("latency_ms") or 0)
                    + (time.perf_counter() - started) * 1000,
                    3,
                ),
                "llm_calls": int(original.get("llm_calls") or 0) + len(new_calls),
                "prompt_tokens": int(original.get("prompt_tokens") or 0)
                + sum(int(call.get("prompt_tokens") or 0) for call in new_calls),
                "completion_tokens": int(original.get("completion_tokens") or 0)
                + sum(int(call.get("completion_tokens") or 0) for call in new_calls),
                "total_tokens": int(original.get("total_tokens") or 0)
                + (client.total_tokens - tokens_start),
                "estimated_cost_usd": None,
                "repair_attempts": 0,
                "resumed_from_checkpoint": True,
                **failure,
            }
        resumed_by_key[key] = row
        print(json.dumps(row, ensure_ascii=False))

    combined_rows: list[dict[str, Any]] = []
    for original in source_rows:
        key = (original["condition"], original["case_id"], int(original["repeat_id"]))
        if key in resumed_by_key:
            row = resumed_by_key[key]
            row["artifact_run_dir"] = str(
                (output_dir / key[0] / key[1] / f"r{key[2]:02d}").relative_to(ROOT)
            )
        else:
            row = completed_by_key[key]
            row["artifact_run_dir"] = str(
                (source_dir / key[0] / key[1] / f"r{key[2]:02d}").relative_to(ROOT)
            )
        combined_rows.append(row)

    attach_repeat_stability(combined_rows)
    result = {
        **{key: value for key, value in source_result.items() if key not in {"rows", "summary"}},
        "experiment_id": output_dir.name,
        "source_experiment_id": source_result["experiment_id"],
        "created_at_utc": datetime.now(UTC).isoformat(),
        "resume_policy": (
            "Only LLMBudgetExceededError checkpoints were resumed; completed rows were not rerun."
        ),
        "resumed_run_count": len(resumed_by_key),
        "summary": summarize_rows(combined_rows),
        "rows": combined_rows,
    }
    (output_dir / "results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "resume_manifest.json").write_text(
        json.dumps(
            {
                "source_results": str(source_path.relative_to(ROOT)),
                "source_results_sha256": __import__("hashlib").sha256(
                    source_path.read_bytes()
                ).hexdigest(),
                "resumed_keys": [
                    {"condition": key[0], "case_id": key[1], "repeat_id": key[2]}
                    for key in resumed_by_key
                ],
                "provider": llm_config.provider,
                "api_base": llm_config.api_base,
                "model": llm_config.model,
                "max_calls_per_process": llm_config.max_calls_per_process,
                "max_total_tokens_per_process": llm_config.max_total_tokens_per_process,
                "max_estimated_cost_usd": llm_config.max_estimated_cost_usd,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
