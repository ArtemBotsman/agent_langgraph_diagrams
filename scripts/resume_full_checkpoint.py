"""Resume an interrupted FULL root-graph run from a copied SQLite checkpoint.

The source evidence is never modified. The script copies its checkpoint into a
new output directory, resumes the pending LangGraph node with the same thread
ID, and writes a complete result bundle plus telemetry for only the new calls.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from traceable_spec.evaluation.projection import automatic_metrics
from traceable_spec.exporting import write_specification_bundle
from traceable_spec.llm.openai_compatible import (
    OpenAICompatibleConfig,
    OpenAICompatibleLLMClient,
)
from traceable_spec.orchestration.persistence import (
    open_sqlite_checkpointer,
    thread_config,
)
from traceable_spec.orchestration.pipeline import compile_live_pipeline

ROOT = Path(__file__).resolve().parents[1]


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
    parser.add_argument("--source-run-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--thread-id", required=True)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--max-live-calls", type=int, default=30)
    parser.add_argument("--max-live-tokens", type=int, default=200_000)
    parser.add_argument("--max-estimated-cost-usd", type=float, default=0.25)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    source_checkpoint = args.source_run_dir / "checkpoints.sqlite"
    if not source_checkpoint.exists():
        raise SystemExit(f"Checkpoint not found: {source_checkpoint}")
    if args.output_dir.exists():
        raise SystemExit(f"Output directory already exists: {args.output_dir}")

    args.output_dir.mkdir(parents=True)
    checkpoint_path = args.output_dir / "checkpoints.sqlite"
    shutil.copy2(source_checkpoint, checkpoint_path)
    prior_calls = args.source_run_dir / "calls.jsonl"
    if prior_calls.exists():
        shutil.copy2(prior_calls, args.output_dir / "prior_calls.jsonl")

    _load_local_env(args.env_file)
    config = replace(
        OpenAICompatibleConfig.from_env(),
        telemetry_path=args.output_dir / "calls.jsonl",
        raw_capture_dir=None,
        max_calls_per_process=args.max_live_calls,
        max_total_tokens_per_process=args.max_live_tokens,
        max_estimated_cost_usd=args.max_estimated_cost_usd,
    )
    client = OpenAICompatibleLLMClient(config)
    config_for_thread = thread_config(args.thread_id)

    with open_sqlite_checkpointer(checkpoint_path) as checkpointer:
        graph = compile_live_pipeline(client, checkpointer=checkpointer)
        before = graph.get_state(config_for_thread)
        if not before.values:
            raise SystemExit(f"Thread not found in checkpoint: {args.thread_id}")
        if not before.next:
            raise SystemExit("Checkpoint already reached a terminal state")
        state = graph.invoke(None, config=config_for_thread)

    specification = state["specification"]
    run_manifest: dict[str, Any] = {
        "experiment_type": "checkpoint_recovery",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "thread_id": args.thread_id,
        "pending_nodes_before_resume": list(before.next),
        "next_activity_index_before_resume": before.values.get("next_activity_index"),
        "activity_results_before_resume": len(before.values.get("activity_results") or []),
        "provider": config.provider,
        "api_base": config.api_base,
        "model": config.model,
        "new_llm_calls": len(client.calls),
        "new_total_tokens": client.total_tokens,
        "new_estimated_cost_usd": client.total_cost_usd,
    }
    write_specification_bundle(
        args.output_dir,
        specification.request.model_dump(mode="json"),
        specification,
        run_manifest,
    )
    summary = {
        **run_manifest,
        **automatic_metrics(specification),
        "status": specification.status.value,
        "use_case_count": (
            len(specification.use_case_set.use_cases) if specification.use_case_set else 0
        ),
        "activity_diagram_count": sum(
            item.activity_diagram is not None for item in specification.activity_results
        ),
    }
    (args.output_dir / "recovery_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
