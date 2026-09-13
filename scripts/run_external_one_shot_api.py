"""Run bounded parallel one-shot repeats through OpenAI or Anthropic APIs."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from traceable_spec.entities import normalize_specification_req
from traceable_spec.llm.anthropic import AnthropicConfig, AnthropicLLMClient
from traceable_spec.llm.openai_compatible import (
    OpenAICompatibleConfig,
    OpenAICompatibleLLMClient,
)
from traceable_spec.prompts.one_shot import build_one_shot_messages

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PACKAGE = ROOT / "experiments" / "external_models"
SAFE_LABEL = re.compile(r"[^a-zA-Z0-9._-]+")


def _load_local_env(path: Path) -> None:
    if not path.exists():
        raise SystemExit(f"Environment file does not exist: {path}")
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() and name.strip() not in os.environ:
            os.environ[name.strip()] = value.strip().strip('"').strip("'")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--package-dir", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--parallel-workers", type=int, default=3)
    parser.add_argument("--max-estimated-cost-usd", type=float, required=True)
    parser.add_argument("--responses-dir", type=Path)
    parser.add_argument("--experiment-id")
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def _configuration() -> AnthropicConfig | OpenAICompatibleConfig:
    provider = os.environ.get("LLM_PROVIDER", "").casefold()
    if provider == "anthropic":
        return AnthropicConfig.from_env()
    return OpenAICompatibleConfig.from_env()


def _estimated_worst_case_cost(
    config: AnthropicConfig | OpenAICompatibleConfig,
    messages: list[dict[str, str]],
) -> float:
    if (
        config.input_price_usd_per_million is None
        or config.output_price_usd_per_million is None
    ):
        raise SystemExit("Both input and output prices are required for the live pilot")
    # One UTF-8 byte per token is deliberately conservative for the preflight guard.
    input_upper_bound = sum(len(item["content"].encode("utf-8")) for item in messages)
    return (
        input_upper_bound * config.input_price_usd_per_million
        + config.max_output_tokens * config.output_price_usd_per_million
    ) / 1_000_000


def _new_client(
    config: AnthropicConfig | OpenAICompatibleConfig,
    raw_dir: Path,
) -> AnthropicLLMClient | OpenAICompatibleLLMClient:
    per_call_config = replace(
        config,
        max_calls_per_process=1,
        max_total_tokens_per_process=max(
            config.max_total_tokens_per_process,
            config.max_output_tokens * 2,
        ),
        raw_capture_dir=raw_dir,
        telemetry_path=None,
    )
    if isinstance(per_call_config, AnthropicConfig):
        return AnthropicLLMClient(per_call_config)
    return OpenAICompatibleLLMClient(per_call_config)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> None:
    args = _parse_args()
    if not args.allow_live:
        raise SystemExit("External API calls require explicit --allow-live")
    if not 1 <= args.repeats <= 5:
        raise SystemExit("--repeats must be between 1 and 5")
    if not 1 <= args.parallel_workers <= 3:
        raise SystemExit("--parallel-workers must be between 1 and 3")
    if args.max_estimated_cost_usd <= 0:
        raise SystemExit("--max-estimated-cost-usd must be positive")

    _load_local_env(args.env_file)
    config = _configuration()
    manifest = json.loads(
        (args.package_dir / "package_manifest.json").read_text(encoding="utf-8")
    )
    available = set(manifest["case_ids"])
    selected_ids = list(dict.fromkeys(args.case_id or ["B1-DEV-002"]))
    missing = set(selected_ids) - available
    if missing:
        raise SystemExit(f"Unknown package case IDs: {sorted(missing)}")

    messages_by_case: dict[str, list[dict[str, str]]] = {}
    for case_id in selected_ids:
        input_path = args.package_dir / "inputs" / "pilot_dev3" / f"{case_id}.json"
        request = json.loads(input_path.read_text(encoding="utf-8"))
        messages_by_case[case_id] = build_one_shot_messages(
            normalize_specification_req(request)
        )

    tasks = [(case_id, repeat) for case_id in selected_ids for repeat in range(1, args.repeats + 1)]
    worst_case = sum(
        _estimated_worst_case_cost(config, messages_by_case[case_id])
        for case_id, _ in tasks
    )
    if worst_case > args.max_estimated_cost_usd:
        raise SystemExit(
            "Configured cost guard is below the conservative worst-case estimate: "
            f"guard={args.max_estimated_cost_usd:.2f}, estimate={worst_case:.2f} USD"
        )

    model_label = SAFE_LABEL.sub("-", config.model).strip("-").lower()
    response_root = args.responses_dir or (
        args.package_dir / "responses" / model_label
    )
    experiment_id = args.experiment_id or (
        f"external-{model_label}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    )
    private_root = ROOT / ".private_experiment_evidence" / "external_one_shot" / experiment_id

    pending: list[tuple[str, int]] = []
    for case_id, repeat in tasks:
        response_path = response_root / case_id / f"r{repeat:02d}.json"
        if response_path.exists():
            if args.resume:
                continue
            raise SystemExit(f"Refusing to overwrite existing response: {response_path}")
        pending.append((case_id, repeat))
    if not pending:
        raise SystemExit("No calls required: all requested responses already exist")

    def run_one(case_id: str, repeat: int) -> dict[str, Any]:
        response_path = response_root / case_id / f"r{repeat:02d}.json"
        meta_path = response_root / case_id / f"r{repeat:02d}.meta.json"
        failure_path = response_root / case_id / f"r{repeat:02d}.failure.json"
        client = _new_client(config, private_root / case_id / f"r{repeat:02d}")
        started = time.perf_counter()
        try:
            content = client.complete(
                messages=messages_by_case[case_id],
                temperature=0,
                response_format={"type": "json_object"},
            )
            response_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = response_path.with_name(f".{response_path.name}.tmp")
            temporary.write_text(content.rstrip() + "\n", encoding="utf-8")
            temporary.replace(response_path)
            call = client.calls[-1]
            meta = {
                "experiment_id": experiment_id,
                "provider": call.get("provider"),
                "model": call.get("resolved_model") or config.model,
                "requested_model": config.model,
                "requested_temperature": call.get("requested_temperature", 0),
                "effective_temperature": call.get("effective_temperature", 0),
                "temperature_omitted_for_compatibility": call.get(
                    "temperature_omitted_for_compatibility", False
                ),
                "reasoning_effort": config.reasoning_effort,
                "prompt_tokens": call.get("prompt_tokens"),
                "completion_tokens": call.get("completion_tokens"),
                "reasoning_tokens": call.get("reasoning_tokens"),
                "total_tokens": call.get("total_tokens"),
                "latency_ms": call.get("latency_ms"),
                "provider_reported_cost_usd": call.get("estimated_cost_usd"),
                "finish_reason": call.get("finish_reason") or call.get("stop_reason"),
                "response_sha256": call.get("response_sha256"),
                "raw_response_saved_without_manual_edits": True,
            }
            _write_json(meta_path, meta)
            return {"case_id": case_id, "repeat": repeat, "status": "success", **meta}
        except Exception as exc:
            last_call = client.calls[-1] if client.calls else {}
            failure = {
                "experiment_id": experiment_id,
                "case_id": case_id,
                "repeat": repeat,
                "provider": config.provider,
                "requested_model": config.model,
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                "error_type": type(exc).__name__,
                "message": str(exc),
                "provider_error_type": last_call.get("error_type"),
                "http_status": last_call.get("http_status"),
                "attempts": last_call.get("attempts"),
            }
            _write_json(failure_path, failure)
            return {"case_id": case_id, "repeat": repeat, "status": "failed", **failure}

    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(args.parallel_workers, len(pending))) as executor:
        futures = {executor.submit(run_one, *task): task for task in pending}
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False))

    rows.sort(key=lambda item: (item["case_id"], item["repeat"]))
    summary = {
        "experiment_id": experiment_id,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "provider": config.provider,
        "model": config.model,
        "case_ids": selected_ids,
        "repeats": args.repeats,
        "parallel_workers": min(args.parallel_workers, len(pending)),
        "successful_calls": sum(row["status"] == "success" for row in rows),
        "failed_calls": sum(row["status"] != "success" for row in rows),
        "actual_estimated_cost_usd": sum(
            float(row.get("provider_reported_cost_usd") or 0) for row in rows
        ),
        "conservative_preflight_cost_usd": worst_case,
        "configured_cost_guard_usd": args.max_estimated_cost_usd,
        "response_root": str(response_root.resolve()),
        "rows": rows,
    }
    _write_json(response_root / f"{experiment_id}.summary.json", summary)
    if summary["failed_calls"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
