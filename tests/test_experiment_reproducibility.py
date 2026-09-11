from __future__ import annotations

import csv
import json
from pathlib import Path

from traceable_spec.evaluation.aggregation import attach_repeat_stability, summarize_rows
from traceable_spec.evaluation.error_analysis import analyze_saved_experiment
from traceable_spec.evaluation.reproducibility import verify_saved_experiment


def _write_example_experiment(root: Path) -> Path:
    experiment = root / "exp"
    rows = [
        {
            "condition": "B0_RULE",
            "case_id": "DEV-001",
            "repeat_id": repeat,
            "run_status": "success",
            "end_to_end_success": 1.0,
            "semantic_composite": 0.4,
            "actor_f1": 0.2,
            "uc_f1": 0.8,
            "milestone_f1": 0.2,
            "branch_f1": 0.0,
            "trace_f1": 0.8,
            "hallucination_rate": 0.5,
            "latency_ms": 1.0,
            "llm_calls": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "repair_attempts": 0,
        }
        for repeat in (1, 2)
    ]
    attach_repeat_stability(rows)
    experiment.mkdir()
    data = {
        "experiment_id": "exp",
        "conditions": ["B0_RULE"],
        "selected_case_ids": ["DEV-001"],
        "repeats": 2,
        "summary": summarize_rows(rows),
        "rows": rows,
    }
    (experiment / "results.json").write_text(json.dumps(data), encoding="utf-8")
    with (experiment / "results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    for row in rows:
        run_dir = experiment / "B0_RULE" / "DEV-001" / f"r{row['repeat_id']:02d}"
        run_dir.mkdir(parents=True)
        for name, value in {
            "input.json": {},
            "config.json": {},
            "generated_specification.json": {},
            "trace_manifest.json": {},
            "validation_reports.json": [],
            "metrics.json": {"semantic_composite": 0.4},
        }.items():
            (run_dir / name).write_text(json.dumps(value), encoding="utf-8")
    return experiment


def test_saved_experiment_recalculates_identically(tmp_path: Path) -> None:
    report = verify_saved_experiment(_write_example_experiment(tmp_path))
    assert report["passed"] is True
    assert report["summary_recalculation_identical"] is True
    assert report["complete_run_bundles"] == 2


def test_error_analysis_flags_quality_thresholds(tmp_path: Path) -> None:
    report = analyze_saved_experiment(_write_example_experiment(tmp_path))
    condition = report["by_condition"]["B0_RULE"]
    assert condition["end_to_end_failure_count"] == 0
    assert condition["exception_failure_count"] == 0
    assert condition["low_semantic_below_0_5_count"] == 2
    assert condition["high_hallucination_above_0_4_count"] == 2
