"""Run a bounded, method-blind LLM judge over saved generated artifacts."""

from __future__ import annotations

import argparse
import csv
import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

from traceable_spec.evaluation.llm_judge import (
    DIMENSION_WEIGHTS,
    PointwiseJudgeVerdict,
    build_blind_projection,
    build_pointwise_judge_messages,
    dimension_scores,
    weighted_score,
)
from traceable_spec.llm.openai_compatible import OpenAICompatibleConfig, OpenAICompatibleLLMClient
from traceable_spec.llm.parsing import parse_json_model

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "benchmark" / "size_scaling_v1" / "manifest.json"
DEFAULT_RUN_ROOT = (
    ROOT / "artifacts" / "size_scaling_runs" / "size-scaling-b0-r3-2026-09-13"
)
DEFAULT_OUTPUT_ROOT = ROOT / "artifacts" / "llm_judge_runs"


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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--condition", default="B0_RULE")
    parser.add_argument("--source-repeat", type=int, default=1)
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--judge-repeats", type=int, default=1)
    parser.add_argument("--judge-max-output-tokens", type=int, default=2400)
    parser.add_argument(
        "--reasoning-effort",
        choices=("none", "low", "medium", "high", "xhigh"),
    )
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--max-live-calls", type=int, required=True)
    parser.add_argument("--max-live-tokens", type=int, required=True)
    parser.add_argument("--max-estimated-cost-usd", type=float, required=True)
    parser.add_argument("--experiment-id")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--capture-raw-private-dir",
        type=Path,
        default=ROOT / ".private_experiment_evidence" / "llm_judge",
    )
    return parser.parse_args()


def _summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["size_group"]), []).append(row)
    summary: list[dict[str, Any]] = []
    for group, items in sorted(grouped.items()):
        valid = [item for item in items if item["status"] == "success"]
        record: dict[str, Any] = {
            "size_group": group,
            "case_count": len({item["case_id"] for item in items}),
            "run_count": len(items),
            "successful_judgments": len(valid),
            "success_rate": len(valid) / len(items),
        }
        if valid:
            record.update(
                {
                    "mean_overall_score_0_1": mean(item["overall_score_0_1"] for item in valid),
                    "sd_overall_score_0_1": pstdev(
                        item["overall_score_0_1"] for item in valid
                    ),
                    "approve_rate": mean(item["decision"] == "approve" for item in valid),
                    "mean_confidence": mean(item["confidence"] for item in valid),
                    "mean_total_tokens": mean(item["total_tokens"] for item in valid),
                    "mean_latency_ms": mean(item["latency_ms"] for item in valid),
                    **{
                        f"mean_{dimension}_1_5": mean(item[dimension] for item in valid)
                        for dimension in DIMENSION_WEIGHTS
                    },
                }
            )
        summary.append(record)
    return summary


def main() -> None:
    args = _parse_args()
    if not args.allow_live:
        raise SystemExit("LLM judge requires explicit --allow-live")
    if not 1 <= args.judge_repeats <= 5:
        raise SystemExit("--judge-repeats must be between 1 and 5")
    if not 256 <= args.judge_max_output_tokens <= 32000:
        raise SystemExit("--judge-max-output-tokens must be between 256 and 32000")
    expected_calls = (len(args.case_id) if args.case_id else 20) * args.judge_repeats
    if args.max_live_calls < expected_calls:
        raise SystemExit(
            f"--max-live-calls={args.max_live_calls} is below expected {expected_calls} calls"
        )

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    cases = list(manifest["cases"])
    if args.case_id:
        wanted = set(args.case_id)
        cases = [case for case in cases if case["case_id"] in wanted]
        missing = wanted - {case["case_id"] for case in cases}
        if missing:
            raise SystemExit(f"Unknown case IDs: {sorted(missing)}")

    experiment_id = args.experiment_id or datetime.now(UTC).strftime(
        "llm-judge-%Y%m%dT%H%M%SZ"
    )
    output_dir = args.output_root / experiment_id
    output_dir.mkdir(parents=True, exist_ok=False)
    _load_local_env(args.env_file)
    config = OpenAICompatibleConfig.from_env()
    config = replace(
        config,
        max_calls_per_process=args.max_live_calls,
        max_total_tokens_per_process=args.max_live_tokens,
        max_estimated_cost_usd=args.max_estimated_cost_usd,
        max_output_tokens=min(config.max_output_tokens, args.judge_max_output_tokens),
        reasoning_effort=args.reasoning_effort or config.reasoning_effort,
        telemetry_path=output_dir / "calls.jsonl",
        raw_capture_dir=args.capture_raw_private_dir.resolve() / experiment_id,
    )
    client = OpenAICompatibleLLMClient(config)
    judge_temperature = None if config.provider.casefold() == "openai" else 0
    public_config = {
        "experiment_id": experiment_id,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "judge_provider": config.provider,
        "judge_api_base": config.api_base,
        "judge_model": config.model,
        "judge_temperature": judge_temperature,
        "judge_reasoning_effort": config.reasoning_effort,
        "judge_max_output_tokens": config.max_output_tokens,
        "method_blinded": True,
        "condition": args.condition,
        "source_repeat": args.source_repeat,
        "judge_repeats": args.judge_repeats,
        "max_live_calls": args.max_live_calls,
        "max_live_tokens": args.max_live_tokens,
        "max_estimated_cost_usd": args.max_estimated_cost_usd,
        "dimension_weights": DIMENSION_WEIGHTS,
        "raw_capture_persisted_privately": True,
    }
    (output_dir / "config.json").write_text(
        json.dumps(public_config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    rows: list[dict[str, Any]] = []
    judgments: list[dict[str, Any]] = []
    for case in cases:
        bundle_dir = (
            args.run_root
            / args.condition
            / case["case_id"]
            / f"r{args.source_repeat:02d}"
        )
        input_data = json.loads((bundle_dir / "input.json").read_text(encoding="utf-8"))
        generated = json.loads(
            (bundle_dir / "generated_specification.json").read_text(encoding="utf-8")
        )
        projection = build_blind_projection(input_data, generated)
        messages = build_pointwise_judge_messages(projection)
        for judge_repeat in range(1, args.judge_repeats + 1):
            call_start = len(client.calls)
            call_error: Exception | None = None
            raw = ""
            try:
                raw = client.complete(
                    messages=messages,
                    temperature=judge_temperature,
                    response_format={"type": "json_object"},
                )
            except Exception as exc:  # keep a failed paid call in the evidence table
                call_error = exc
            call = client.calls[call_start] if len(client.calls) > call_start else {}
            base = {
                "case_id": case["case_id"],
                "project_name": case["project_name"],
                "size_group": case["size_group"],
                "fr_count": case["fr_count"],
                "nfr_count": case["nfr_count"],
                "judge_repeat": judge_repeat,
                "candidate_sha256": projection["candidate_sha256"],
                "latency_ms": call.get("latency_ms"),
                "prompt_tokens": call.get("prompt_tokens"),
                "completion_tokens": call.get("completion_tokens"),
                "total_tokens": call.get("total_tokens"),
                "estimated_cost_usd": call.get("estimated_cost_usd"),
                "resolved_model": call.get("resolved_model"),
            }
            if call_error is not None:
                row = {
                    **base,
                    "status": "judge_call_failed",
                    "error_type": type(call_error).__name__,
                }
                rows.append(row)
                judgments.append(row)
                print(json.dumps(row, ensure_ascii=False))
                continue
            verdict, report = parse_json_model(
                PointwiseJudgeVerdict,
                raw,
                validator_name="pointwise_llm_judge_schema",
            )
            if verdict is None:
                row = {
                    **base,
                    "status": "invalid_judgment",
                    "validation_issues": len(report.issues),
                }
                judgment = {
                    **row,
                    "validation_report": report.model_dump(mode="json"),
                }
            else:
                scores = dimension_scores(verdict)
                row = {
                    **base,
                    "status": "success",
                    **scores,
                    "overall_score_0_1": weighted_score(verdict),
                    "decision": verdict.decision,
                    "confidence": verdict.confidence,
                    "critical_issue_count": len(verdict.critical_issues),
                }
                judgment = {
                    **row,
                    "verdict": verdict.model_dump(mode="json"),
                }
            rows.append(row)
            judgments.append(judgment)
            print(json.dumps(row, ensure_ascii=False))

    summary = _summarize(rows)
    result = {
        "config": public_config,
        "claim_limit": (
            "LLM-judge is a separate candidate signal, not human ground truth; "
            "same-family self-preference and prompt sensitivity remain possible."
        ),
        "summary": summary,
        "rows": rows,
        "judgments": judgments,
    }
    (output_dir / "results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for filename, data in (("results.csv", rows), ("summary.csv", summary)):
        if not data:
            continue
        fields = sorted({key for item in data for key in item})
        with (output_dir / filename).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(data)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
