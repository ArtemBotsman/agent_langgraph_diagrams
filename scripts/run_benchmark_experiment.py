"""Run reproducible baselines, FULL and controlled component variants."""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from traceable_spec.entities import (
    GeneratedSpecification,
    PipelineStatus,
    normalize_specification_req,
)
from traceable_spec.evaluation.aggregation import attach_repeat_stability, summarize_rows
from traceable_spec.evaluation.benchmark import evaluate_semantic_projection
from traceable_spec.evaluation.projection import automatic_metrics, semantic_projection
from traceable_spec.evaluation.similarity import MultilingualSentenceSimilarity
from traceable_spec.llm.factory import (
    InstrumentedLLMClient,
    create_instrumented_client,
    provider_config_from_env,
)
from traceable_spec.orchestration.component_variants import (
    live_pipeline_deps_without_critics,
    live_pipeline_deps_without_rule_feedback,
)
from traceable_spec.orchestration.persistence import open_sqlite_checkpointer, thread_config
from traceable_spec.orchestration.pipeline import compile_live_pipeline, compile_pipeline
from traceable_spec.reference_methods import run_one_shot_baseline, run_rule_based_baseline

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "benchmark" / "v1_0_synthetic" / "cases.json"
MANIFEST_PATH = ROOT / "benchmark" / "v1_0_synthetic" / "manifest.json"
DEFAULT_OUTPUT_ROOT = ROOT / "artifacts" / "benchmark_runs"
CONDITIONS = (
    "B0_RULE",
    "B1_ONESHOT",
    "FULL",
    "FULL_NO_CRITIC",
    "FULL_NO_REPAIR",
    "FULL_REPAIR_1",
    "FULL_NO_RULE_FEEDBACK",
)
SEMANTIC_BACKENDS = ("lexical", "multilingual")


def _load_local_env(path: Path) -> None:
    """Load simple KEY=VALUE pairs without printing or persisting secret values."""

    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if name and name not in os.environ:
            os.environ[name] = value


def _git_value(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _write_run_artifacts(
    run_dir: Path,
    case: dict[str, Any],
    config: dict[str, Any],
    specification: GeneratedSpecification,
    metrics: dict[str, Any],
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "input.json").write_text(
        json.dumps(case["specification_req"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_dir / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_dir / "generated_specification.json").write_text(
        json.dumps(specification.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_dir / "trace_manifest.json").write_text(
        json.dumps(specification.trace_manifest.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    (run_dir / "validation_reports.json").write_text(
        json.dumps(
            [report.model_dump(mode="json") for report in specification.validation_reports],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    diagrams_dir = run_dir / "diagrams"
    for result in specification.activity_results:
        diagram = result.activity_diagram
        if diagram is None or not diagram.mermaid_source:
            continue
        diagrams_dir.mkdir(parents=True, exist_ok=True)
        (diagrams_dir / f"{diagram.id}.mmd").write_text(
            diagram.mermaid_source,
            encoding="utf-8",
        )


def _run_condition(
    condition: str,
    case: dict[str, Any],
    repeat_id: int,
    run_dir: Path,
    client: InstrumentedLLMClient | None,
) -> tuple[GeneratedSpecification, dict[str, Any]]:
    request = case["specification_req"]
    call_start = len(client.calls) if client is not None else 0
    tokens_start = client.total_tokens if client is not None else 0
    cost_start = client.total_cost_usd if client is not None else 0.0
    started = time.perf_counter()
    if condition == "B0_RULE":
        specification = run_rule_based_baseline(request)
    elif condition == "B1_ONESHOT":
        if client is None:
            raise RuntimeError("B1_ONESHOT requires a live client")
        specification = run_one_shot_baseline(request, client)
    elif condition in {
        "FULL",
        "FULL_NO_CRITIC",
        "FULL_NO_REPAIR",
        "FULL_REPAIR_1",
        "FULL_NO_RULE_FEEDBACK",
    }:
        if client is None:
            raise RuntimeError(f"{condition} requires a live client")
        graph_request = request
        if condition in {"FULL_NO_REPAIR", "FULL_REPAIR_1"}:
            graph_request = normalize_specification_req(request).model_copy(
                update={"max_repair_attempts": 0 if condition == "FULL_NO_REPAIR" else 1}
            )
        checkpoint_path = run_dir / "checkpoints.sqlite"
        with open_sqlite_checkpointer(checkpoint_path) as checkpointer:
            if condition == "FULL_NO_CRITIC":
                graph = compile_pipeline(
                    live_pipeline_deps_without_critics(client),
                    checkpointer=checkpointer,
                )
            elif condition == "FULL_NO_RULE_FEEDBACK":
                graph = compile_pipeline(
                    live_pipeline_deps_without_rule_feedback(client),
                    checkpointer=checkpointer,
                )
            else:
                graph = compile_live_pipeline(client, checkpointer=checkpointer)
            state = graph.invoke(
                {"request": graph_request},
                config=thread_config(f"{case['case_id']}-{condition}-r{repeat_id:02d}"),
            )
            specification = state["specification"]
    else:
        raise ValueError(f"Unknown condition: {condition}")
    latency_ms = round((time.perf_counter() - started) * 1000, 3)
    calls = [] if client is None else client.calls[call_start:]
    runtime = {
        "latency_ms": latency_ms,
        "llm_calls": len(calls),
        "prompt_tokens": sum(int(call.get("prompt_tokens") or 0) for call in calls),
        "completion_tokens": sum(int(call.get("completion_tokens") or 0) for call in calls),
        "total_tokens": (0 if client is None else client.total_tokens - tokens_start),
        "estimated_cost_usd": (
            0.0
            if client is None
            else (
                client.total_cost_usd - cost_start
                if client.config.input_price_usd_per_million is not None
                and client.config.output_price_usd_per_million is not None
                else None
            )
        ),
        "repair_attempts": specification.uc_repair_attempts_used
        + sum(item.repair_attempts_used for item in specification.activity_results),
    }
    if calls:
        with (run_dir / "calls.jsonl").open("w", encoding="utf-8") as handle:
            for call in calls:
                handle.write(json.dumps(call, ensure_ascii=False, sort_keys=True) + "\n")
    return specification, runtime


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--condition", action="append", choices=CONDITIONS)
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--split", choices=("development", "hidden", "all"), default="development")
    parser.add_argument("--all-cases", action="store_true")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--allow-hidden", action="store_true")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument(
        "--max-live-calls",
        type=int,
        help="Explicit client-side call budget override for this experiment.",
    )
    parser.add_argument(
        "--max-live-tokens",
        type=int,
        help="Explicit client-side aggregate token budget override.",
    )
    parser.add_argument(
        "--max-estimated-cost-usd",
        type=float,
        help="Soft stop threshold; requires current input/output prices.",
    )
    parser.add_argument("--experiment-id")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--semantic-backend",
        choices=SEMANTIC_BACKENDS,
        default="lexical",
        help="Lexical scorer or local multilingual Sentence Transformers scorer.",
    )
    parser.add_argument(
        "--allow-model-download",
        action="store_true",
        help="Permit the optional multilingual scorer to download model files.",
    )
    parser.add_argument(
        "--capture-raw-private-dir",
        type=Path,
        help=(
            "Opt-in private directory for exact request/response JSON. "
            "The path is never written to public run metadata."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.repeats < 1 or args.repeats > 10:
        raise SystemExit("--repeats must be between 1 and 10")
    for name in ("max_live_calls", "max_live_tokens", "max_estimated_cost_usd"):
        value = getattr(args, name)
        if value is not None and value <= 0:
            raise SystemExit(f"--{name.replace('_', '-')} must be positive")
    conditions = args.condition or ["B0_RULE"]
    live_requested = any(condition != "B0_RULE" for condition in conditions)
    if live_requested and not args.allow_live:
        raise SystemExit("Live conditions require explicit --allow-live")
    if args.split == "hidden" and not args.allow_hidden:
        raise SystemExit("Hidden evaluation requires explicit --allow-hidden")
    if args.capture_raw_private_dir is not None and not live_requested:
        raise SystemExit("Raw capture is only available for live conditions")

    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    selected = [case for case in cases if args.split == "all" or case["split"] == args.split]
    if args.case_id:
        wanted = set(args.case_id)
        selected = [case for case in selected if case["case_id"] in wanted]
        missing = wanted - {case["case_id"] for case in selected}
        if missing:
            raise SystemExit(f"Unknown or out-of-split case IDs: {sorted(missing)}")
    elif not args.all_cases:
        selected = selected[:1]
    if not selected:
        raise SystemExit("No cases selected")

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    experiment_id = args.experiment_id or f"benchmark-{timestamp}"
    experiment_dir = args.output_root / experiment_id
    experiment_dir.mkdir(parents=True, exist_ok=False)
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    similarity = None
    similarity_name = "lexical_sequence_candidate"
    if args.semantic_backend == "multilingual":
        similarity = MultilingualSentenceSimilarity(local_files_only=not args.allow_model_download)
        similarity_name = similarity.name

    client: InstrumentedLLMClient | None = None
    if live_requested:
        _load_local_env(args.env_file)
        llm_config = provider_config_from_env()
        llm_config = replace(
            llm_config,
            telemetry_path=experiment_dir / "all_calls.jsonl",
            max_calls_per_process=(
                args.max_live_calls
                if args.max_live_calls is not None
                else llm_config.max_calls_per_process
            ),
            max_total_tokens_per_process=(
                args.max_live_tokens
                if args.max_live_tokens is not None
                else llm_config.max_total_tokens_per_process
            ),
            max_estimated_cost_usd=(
                args.max_estimated_cost_usd
                if args.max_estimated_cost_usd is not None
                else llm_config.max_estimated_cost_usd
            ),
            raw_capture_dir=(
                args.capture_raw_private_dir.resolve() / experiment_id
                if args.capture_raw_private_dir is not None
                else None
            ),
        )
        client = create_instrumented_client(llm_config)

    rows: list[dict[str, Any]] = []
    for condition in conditions:
        for case in selected:
            for repeat_id in range(1, args.repeats + 1):
                run_dir = experiment_dir / condition / case["case_id"] / f"r{repeat_id:02d}"
                run_dir.mkdir(parents=True, exist_ok=True)
                run_config = {
                    "experiment_id": experiment_id,
                    "condition": condition,
                    "case_id": case["case_id"],
                    "split": case["split"],
                    "repeat_id": repeat_id,
                    "benchmark_version": manifest["benchmark_version"],
                    "cases_sha256": manifest["cases_sha256"],
                    "git_commit": _git_value("rev-parse", "HEAD"),
                    "git_dirty": bool(_git_value("status", "--porcelain")),
                    "provider": None if client is None else client.config.provider,
                    "api_base": None if client is None else client.config.api_base,
                    "model": None if client is None else client.config.model,
                    "requested_temperature": 0,
                    "effective_temperature": (
                        None if client is not None and client.config.provider == "anthropic" else 0
                    ),
                    "prompt_version": "2026-09-09-v1",
                    "schema_version": "0.2.0",
                    "semantic_similarity_backend": similarity_name,
                    "raw_prompts_or_responses_persisted": (
                        client is not None and client.config.raw_capture_dir is not None
                    ),
                    "raw_evidence_policy": (
                        "private_opt_in"
                        if client is not None and client.config.raw_capture_dir
                        else "hashes_only"
                    ),
                    "max_calls_per_process": (
                        None if client is None else client.config.max_calls_per_process
                    ),
                    "max_total_tokens_per_process": (
                        None if client is None else client.config.max_total_tokens_per_process
                    ),
                    "max_estimated_cost_usd": (
                        None if client is None else client.config.max_estimated_cost_usd
                    ),
                }
                failed_started = time.perf_counter()
                failed_call_start = len(client.calls) if client is not None else 0
                failed_tokens_start = client.total_tokens if client is not None else 0
                try:
                    specification, runtime = _run_condition(
                        condition,
                        case,
                        repeat_id,
                        run_dir,
                        client,
                    )
                    semantic = evaluate_semantic_projection(
                        semantic_projection(specification),
                        case["gold"],
                        similarity=similarity,
                        similarity_name=similarity_name,
                    )
                    metrics = {**automatic_metrics(specification), **semantic, **runtime}
                    _write_run_artifacts(run_dir, case, run_config, specification, metrics)
                    row = {
                        "condition": condition,
                        "case_id": case["case_id"],
                        "split": case["split"],
                        "complexity": case["complexity"],
                        "language": case["language"],
                        "repeat_id": repeat_id,
                        "run_status": specification.status.value,
                        **metrics,
                    }
                except Exception as exc:  # experiment runner records failures per run
                    failed_calls = [] if client is None else client.calls[failed_call_start:]
                    failure = {
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    }
                    (run_dir / "failure.json").write_text(
                        json.dumps(failure, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    row = {
                        "condition": condition,
                        "case_id": case["case_id"],
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
                            (time.perf_counter() - failed_started) * 1000,
                            3,
                        ),
                        "llm_calls": len(failed_calls),
                        "prompt_tokens": sum(
                            int(call.get("prompt_tokens") or 0) for call in failed_calls
                        ),
                        "completion_tokens": sum(
                            int(call.get("completion_tokens") or 0) for call in failed_calls
                        ),
                        "total_tokens": (
                            0 if client is None else client.total_tokens - failed_tokens_start
                        ),
                        "estimated_cost_usd": None,
                        "repair_attempts": 0,
                        **failure,
                    }
                rows.append(row)
                print(json.dumps(row, ensure_ascii=False))

    attach_repeat_stability(rows)
    summary = summarize_rows(rows)
    result = {
        "experiment_id": experiment_id,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "benchmark_version": manifest["benchmark_version"],
        "cases_sha256": manifest["cases_sha256"],
        "conditions": conditions,
        "selected_case_ids": [case["case_id"] for case in selected],
        "repeats": args.repeats,
        "semantic_similarity_backend": similarity_name,
        "claim_limit": (
            "Synthetic author-labelled benchmark; final claims require expert review and "
            "a frozen hidden evaluation."
        ),
        "summary": summary,
        "rows": rows,
    }
    (experiment_dir / "results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if rows:
        fieldnames = sorted({key for row in rows for key in row})
        with (experiment_dir / "results.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
