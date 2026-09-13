"""Merge independently executed one-case runs into one repeated experiment bundle."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from traceable_spec.evaluation.aggregation import attach_repeat_stability, summarize_rows

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_ROOT = ROOT / "artifacts" / "benchmark_runs"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-run", action="append", required=True)
    parser.add_argument("--condition", required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_INPUT_ROOT)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    output_dir = args.output_root / args.experiment_id
    output_dir.mkdir(parents=True, exist_ok=False)
    rows: list[dict[str, Any]] = []
    source_runs: list[str] = []

    for repeat, run_name in enumerate(args.input_run, start=1):
        source_dir = args.input_root / run_name
        result = json.loads((source_dir / "results.json").read_text(encoding="utf-8"))
        matches = [
            row
            for row in result["rows"]
            if row["condition"] == args.condition and row["case_id"] == args.case_id
        ]
        if len(matches) != 1:
            raise SystemExit(
                f"Expected one {args.condition}/{args.case_id} row in {source_dir}, "
                f"found {len(matches)}"
            )
        row = {**matches[0], "repeat_id": repeat, "source_experiment_id": run_name}
        rows.append(row)
        source_bundle = source_dir / args.condition / args.case_id / "r01"
        target_bundle = output_dir / args.condition / args.case_id / f"r{repeat:02d}"
        shutil.copytree(source_bundle, target_bundle)
        source_runs.append(run_name)

    attach_repeat_stability(rows)
    summary = summarize_rows(rows)
    combined = {
        "experiment_id": args.experiment_id,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "condition": args.condition,
        "case_id": args.case_id,
        "repeats": len(rows),
        "source_experiment_ids": source_runs,
        "merge_policy": "Exact saved bundles; no model output or metric was edited.",
        "summary": summary,
        "rows": rows,
    }
    (output_dir / "results.json").write_text(
        json.dumps(combined, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    fields = sorted({key for row in rows for key in row})
    with (output_dir / "results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
