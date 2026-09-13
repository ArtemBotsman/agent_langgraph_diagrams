"""Command-line entry point for one reproducible SpecificationReq run."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from traceable_spec.entities import PipelineStatus, SpecificationReq
from traceable_spec.exporting import write_specification_bundle
from traceable_spec.llm.factory import (
    create_instrumented_client,
    provider_config_from_env,
)
from traceable_spec.orchestration.persistence import open_sqlite_checkpointer, thread_config
from traceable_spec.orchestration.pipeline import compile_live_pipeline
from traceable_spec.reference_methods import run_rule_based_baseline


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name and name not in os.environ:
            os.environ[name] = value.strip().strip('"').strip("'")


def _git_value(root: Path, *args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=root, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate UC, stories, Activity Mermaid, trace and quality artifacts."
    )
    parser.add_argument("input", type=Path, help="SpecificationReq JSON")
    parser.add_argument("output_dir", type=Path, help="New or empty result directory")
    parser.add_argument("--mode", choices=("B0_RULE", "FULL"), default="FULL")
    parser.add_argument(
        "--allow-live",
        action="store_true",
        help="Required safety acknowledgement for paid/network LLM calls.",
    )
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--thread-id", default="single-specification-run")
    return parser.parse_args()


def _read_request(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("SpecificationReq JSON root must be an object")
    return value


def main() -> None:
    args = _parse_args()
    if args.mode == "FULL" and not args.allow_live:
        raise SystemExit("FULL mode requires explicit --allow-live")
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise SystemExit(f"Output directory is not empty: {args.output_dir}")
    root = Path(__file__).resolve().parents[2]
    raw_request = _read_request(args.input)
    request = cast(SpecificationReq, raw_request)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    provider: str | None = None
    api_base: str | None = None
    model: str | None = None

    try:
        if args.mode == "B0_RULE":
            specification = run_rule_based_baseline(request)
        else:
            _load_env(args.env_file)
            config = provider_config_from_env()
            config = replace(
                config,
                telemetry_path=args.output_dir / "llm_calls.sanitized.jsonl",
            )
            client = create_instrumented_client(config)
            provider, api_base, model = config.provider, config.api_base, config.model
            with open_sqlite_checkpointer(
                args.output_dir / "checkpoints.sqlite"
            ) as checkpointer:
                graph = compile_live_pipeline(client, checkpointer=checkpointer)
                state = graph.invoke(
                    {"request": request},
                    config=thread_config(args.thread_id),
                )
            specification = state["specification"]
    except Exception as exc:
        failure = {
            "created_at_utc": datetime.now(UTC).isoformat(),
            "mode": args.mode,
            "error_type": type(exc).__name__,
            "message": str(exc),
            "raw_prompts_or_responses_persisted": False,
        }
        (args.output_dir / "failure.json").write_text(
            json.dumps(failure, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(failure, ensure_ascii=False))
        raise SystemExit(2) from exc

    run_manifest = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "mode": args.mode,
        "provider": provider,
        "api_base": api_base,
        "model": model,
        "requested_temperature": 0 if args.mode == "FULL" else None,
        "effective_temperature": (
            None if provider == "anthropic" else (0 if args.mode == "FULL" else None)
        ),
        "git_commit": _git_value(root, "rev-parse", "HEAD"),
        "git_dirty": bool(_git_value(root, "status", "--porcelain")),
        "thread_id": args.thread_id,
    }
    written = write_specification_bundle(
        args.output_dir,
        raw_request,
        specification,
        run_manifest,
    )
    print(
        json.dumps(
            {
                "status": specification.status.value,
                "output_dir": str(args.output_dir.resolve()),
                "artifacts_written": len(written),
                "failure_reason": specification.failure_reason,
            },
            ensure_ascii=False,
        )
    )
    if specification.status != PipelineStatus.SUCCESS:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
