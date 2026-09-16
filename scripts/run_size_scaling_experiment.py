"""Run input-only scalability experiments across four FR-count bands."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from traceable_spec.entities import (
    GeneratedSpecification,
    PipelineStatus,
    SpecificationReq,
    normalize_specification_req,
)
from traceable_spec.evaluation.benchmark import evaluate_semantic_projection
from traceable_spec.evaluation.projection import automatic_metrics, semantic_projection
from traceable_spec.evaluation.scaling import artifact_counts, summarize_scaling_rows
from traceable_spec.evaluation.similarity import MultilingualSentenceSimilarity
from traceable_spec.exporting import write_specification_bundle
from traceable_spec.llm.openai_compatible import OpenAICompatibleConfig, OpenAICompatibleLLMClient
from traceable_spec.orchestration.component_variants import (
    live_pipeline_deps_without_critics,
    live_pipeline_deps_without_rule_feedback,
)
from traceable_spec.orchestration.persistence import open_sqlite_checkpointer, thread_config
from traceable_spec.orchestration.pipeline import compile_live_pipeline, compile_pipeline
from traceable_spec.reference_methods import run_one_shot_baseline, run_rule_based_baseline

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BENCHMARK = ROOT / "benchmark" / "size_scaling_v1"
DEFAULT_OUTPUT_ROOT = ROOT / "artifacts" / "size_scaling_runs"
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
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() and name.strip() not in os.environ:
            os.environ[name.strip()] = value.strip().strip('"').strip("'")


def _git_value(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _canonical_sha256(specification: GeneratedSpecification) -> str:
    payload = json.dumps(
        specification.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _run_condition(
    condition: str,
    request: SpecificationReq,
    case_id: str,
    repeat_id: int,
    run_dir: Path,
    client: OpenAICompatibleLLMClient | None,
) -> tuple[GeneratedSpecification, dict[str, Any]]:
    call_start = len(client.calls) if client is not None else 0
    token_start = client.total_tokens if client is not None else 0
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
        graph_request: Any = request
        if condition in {"FULL_NO_REPAIR", "FULL_REPAIR_1"}:
            graph_request = normalize_specification_req(request).model_copy(
                update={"max_repair_attempts": 0 if condition == "FULL_NO_REPAIR" else 1}
            )
        with open_sqlite_checkpointer(run_dir / "checkpoints.sqlite") as checkpointer:
            if condition == "FULL_NO_CRITIC":
                graph = compile_pipeline(
                    live_pipeline_deps_without_critics(client), checkpointer=checkpointer
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
                config=thread_config(f"{case_id}-{condition}-r{repeat_id:02d}"),
            )
        specification = state["specification"]
    else:
        raise ValueError(f"Unknown condition: {condition}")

    calls = [] if client is None else client.calls[call_start:]
    runtime = {
        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        "llm_calls": len(calls),
        "prompt_tokens": sum(int(call.get("prompt_tokens") or 0) for call in calls),
        "completion_tokens": sum(int(call.get("completion_tokens") or 0) for call in calls),
        "total_tokens": 0 if client is None else client.total_tokens - token_start,
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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark-dir", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument("--condition", action="append", choices=CONDITIONS)
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--size-group", action="append")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--max-live-calls", type=int)
    parser.add_argument("--max-live-tokens", type=int)
    parser.add_argument("--max-output-tokens", type=int)
    parser.add_argument("--max-estimated-cost-usd", type=float)
    parser.add_argument("--capture-raw-private-dir", type=Path)
    parser.add_argument("--gold-path", type=Path)
    parser.add_argument(
        "--allow-gold-candidate",
        action="store_true",
        help="Use author-level Gold candidate before independent expert approval.",
    )
    parser.add_argument(
        "--semantic-backend",
        choices=SEMANTIC_BACKENDS,
        default="lexical",
    )
    parser.add_argument("--allow-model-download", action="store_true")
    parser.add_argument("--experiment-id")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if not 1 <= args.repeats <= 10:
        raise SystemExit("--repeats must be between 1 and 10")
    conditions = args.condition or ["B0_RULE"]
    live_requested = any(condition != "B0_RULE" for condition in conditions)
    if live_requested and not args.allow_live:
        raise SystemExit("Live conditions require explicit --allow-live")
    if args.capture_raw_private_dir is not None and not live_requested:
        raise SystemExit("Raw capture is only available for live conditions")

    manifest = json.loads((args.benchmark_dir / "manifest.json").read_text(encoding="utf-8"))
    gold_path = args.gold_path or args.benchmark_dir / "gold_candidate.json"
    gold_by_case: dict[str, dict[str, Any]] = {}
    if gold_path.exists():
        if not args.allow_gold_candidate:
            raise SystemExit(
                "Gold candidate requires explicit --allow-gold-candidate because expert "
                "review is incomplete"
            )
        gold_records = json.loads(gold_path.read_text(encoding="utf-8"))
        gold_by_case = {str(item["case_id"]): item["gold"] for item in gold_records}
    similarity = None
    similarity_name = "lexical_sequence_candidate"
    if args.semantic_backend == "multilingual":
        similarity = MultilingualSentenceSimilarity(
            local_files_only=not args.allow_model_download
        )
        similarity_name = similarity.name
    selected = list(manifest["cases"])
    if args.case_id:
        wanted = set(args.case_id)
        selected = [case for case in selected if case["case_id"] in wanted]
        missing = wanted - {case["case_id"] for case in selected}
        if missing:
            raise SystemExit(f"Unknown case IDs: {sorted(missing)}")
    if args.size_group:
        groups = set(args.size_group)
        selected = [case for case in selected if case["size_group"] in groups]
    if not selected:
        raise SystemExit("No cases selected")

    experiment_id = args.experiment_id or datetime.now(UTC).strftime("size-%Y%m%dT%H%M%SZ")
    experiment_dir = args.output_root / experiment_id
    experiment_dir.mkdir(parents=True, exist_ok=False)

    client: OpenAICompatibleLLMClient | None = None
    if live_requested:
        _load_local_env(args.env_file)
        config = OpenAICompatibleConfig.from_env()
        config = replace(
            config,
            telemetry_path=experiment_dir / "all_calls.jsonl",
            max_calls_per_process=args.max_live_calls or config.max_calls_per_process,
            max_total_tokens_per_process=args.max_live_tokens
            or config.max_total_tokens_per_process,
            max_output_tokens=args.max_output_tokens or config.max_output_tokens,
            max_estimated_cost_usd=(
                args.max_estimated_cost_usd
                if args.max_estimated_cost_usd is not None
                else config.max_estimated_cost_usd
            ),
            raw_capture_dir=(
                args.capture_raw_private_dir.resolve() / experiment_id
                if args.capture_raw_private_dir is not None
                else None
            ),
        )
        client = OpenAICompatibleLLMClient(config)

    rows: list[dict[str, Any]] = []
    for condition in conditions:
        for case in selected:
            input_path = args.benchmark_dir / "inputs" / case["file"]
            request = cast(
                SpecificationReq,
                json.loads(input_path.read_text(encoding="utf-8")),
            )
            for repeat_id in range(1, args.repeats + 1):
                run_dir = experiment_dir / condition / case["case_id"] / f"r{repeat_id:02d}"
                run_dir.mkdir(parents=True, exist_ok=True)
                started = time.perf_counter()
                call_start = len(client.calls) if client is not None else 0
                token_start = client.total_tokens if client is not None else 0
                cost_start = client.total_cost_usd if client is not None else 0.0
                try:
                    specification, runtime = _run_condition(
                        condition, request, case["case_id"], repeat_id, run_dir, client
                    )
                    counts = artifact_counts(specification)
                    generated = json.dumps(
                        specification.model_dump(mode="json"), ensure_ascii=False
                    ).encode("utf-8")
                    metrics = {
                        **automatic_metrics(specification),
                        **(
                            evaluate_semantic_projection(
                                semantic_projection(specification),
                                gold_by_case[case["case_id"]],
                                similarity=similarity,
                                similarity_name=similarity_name,
                            )
                            if case["case_id"] in gold_by_case
                            else {}
                        ),
                        **runtime,
                        **counts,
                        "output_bytes": len(generated),
                        "output_sha256": _canonical_sha256(specification),
                    }
                    run_manifest = {
                        "experiment_id": experiment_id,
                        "condition": condition,
                        "case_id": case["case_id"],
                        "repeat_id": repeat_id,
                        "benchmark_id": manifest["benchmark_id"],
                        "benchmark_manifest_sha256": hashlib.sha256(
                            (args.benchmark_dir / "manifest.json").read_bytes()
                        ).hexdigest(),
                        "git_commit": _git_value("rev-parse", "HEAD"),
                        "git_dirty": bool(_git_value("status", "--porcelain")),
                        "provider": None if client is None else client.config.provider,
                        "api_base": None if client is None else client.config.api_base,
                        "model": None if client is None else client.config.model,
                    }
                    write_specification_bundle(
                        run_dir,
                        cast(dict[str, Any], request),
                        specification,
                        run_manifest,
                    )
                    (run_dir / "scaling_metrics.json").write_text(
                        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    row = {
                        "condition": condition,
                        "case_id": case["case_id"],
                        "project_name": case["project_name"],
                        "size_group": case["size_group"],
                        "size_label_ru": case["size_label_ru"],
                        "fr_count": case["fr_count"],
                        "nfr_count": case["nfr_count"],
                        "repeat_id": repeat_id,
                        "run_status": specification.status.value,
                        **metrics,
                    }
                except Exception as exc:
                    failure_calls = [] if client is None else client.calls[call_start:]
                    if failure_calls:
                        with (run_dir / "calls.jsonl").open("w", encoding="utf-8") as handle:
                            for call in failure_calls:
                                handle.write(
                                    json.dumps(call, ensure_ascii=False, sort_keys=True) + "\n"
                                )
                    failure = {"error_type": type(exc).__name__, "message": str(exc)}
                    (run_dir / "failure.json").write_text(
                        json.dumps(failure, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    row = {
                        "condition": condition,
                        "case_id": case["case_id"],
                        "project_name": case["project_name"],
                        "size_group": case["size_group"],
                        "size_label_ru": case["size_label_ru"],
                        "fr_count": case["fr_count"],
                        "nfr_count": case["nfr_count"],
                        "repeat_id": repeat_id,
                        "run_status": PipelineStatus.FAILED.value,
                        "end_to_end_success": 0.0,
                        "actor_f1": 0.0 if gold_by_case else None,
                        "uc_f1": 0.0 if gold_by_case else None,
                        "milestone_recall": 0.0 if gold_by_case else None,
                        "branch_recall": 0.0 if gold_by_case else None,
                        "trace_f1": 0.0 if gold_by_case else None,
                        "semantic_composite": 0.0 if gold_by_case else None,
                        "hallucination_rate": 1.0 if gold_by_case else None,
                        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                        "llm_calls": len(failure_calls),
                        "prompt_tokens": sum(
                            int(call.get("prompt_tokens") or 0) for call in failure_calls
                        ),
                        "completion_tokens": sum(
                            int(call.get("completion_tokens") or 0) for call in failure_calls
                        ),
                        "total_tokens": (
                            0 if client is None else client.total_tokens - token_start
                        ),
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
                        **failure,
                    }
                rows.append(row)
                print(json.dumps(row, ensure_ascii=False))

    summary = summarize_scaling_rows(rows)
    result = {
        "experiment_id": experiment_id,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "benchmark_id": manifest["benchmark_id"],
        "conditions": conditions,
        "repeats": args.repeats,
        "gold_available": bool(gold_by_case),
        "gold_status": (
            "author_candidate_requires_two_independent_reviews"
            if gold_by_case
            else "not_available"
        ),
        "gold_candidate_sha256": (
            hashlib.sha256(gold_path.read_bytes()).hexdigest() if gold_by_case else None
        ),
        "semantic_similarity_backend": similarity_name if gold_by_case else None,
        "claim_limit": (
            "Semantic metrics are preliminary until two independent experts approve Gold."
            if gold_by_case
            else manifest["claim_limit"]
        ),
        "summary": summary,
        "rows": rows,
    }
    (experiment_dir / "results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for filename, data in (("results.csv", rows), ("summary.csv", summary)):
        if data:
            fields = sorted({key for item in data for key in item})
            with (experiment_dir / filename).open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(data)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
