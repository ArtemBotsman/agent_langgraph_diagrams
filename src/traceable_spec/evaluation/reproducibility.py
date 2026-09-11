"""Offline verification of saved experiment aggregation and run bundles."""

from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from traceable_spec.evaluation.aggregation import attach_repeat_stability, summarize_rows


def _same(left: Any, right: Any) -> bool:
    if isinstance(left, float) and isinstance(right, int | float):
        return math.isclose(left, float(right), rel_tol=1e-12, abs_tol=1e-12)
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_same(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _same(a, b) for a, b in zip(left, right, strict=True)
        )
    return bool(left == right)


def _same_saved_summary(saved: list[dict[str, Any]], current: list[dict[str, Any]]) -> bool:
    current_by_condition = {str(item["condition"]): item for item in current}
    for saved_item in saved:
        candidate = current_by_condition.get(str(saved_item["condition"]))
        if candidate is None:
            return False
        for key, value in saved_item.items():
            if key not in candidate or not _same(value, candidate[key]):
                return False
    return True


def verify_saved_experiment(experiment_dir: Path) -> dict[str, Any]:
    """Recompute summaries and verify the expected saved artifacts without an LLM call."""

    results_path = experiment_dir / "results.json"
    data = json.loads(results_path.read_text(encoding="utf-8"))
    rows = copy.deepcopy(data["rows"])
    attach_repeat_stability(rows)
    recomputed_summary = summarize_rows(rows)
    issues: list[str] = []

    saved_summary_identical = _same_saved_summary(data["summary"], recomputed_summary)
    if not saved_summary_identical:
        issues.append("summary_mismatch")
    saved_stability = [row.get("stability_multi_run") for row in data["rows"]]
    recomputed_stability = [row.get("stability_multi_run") for row in rows]
    if not _same(saved_stability, recomputed_stability):
        issues.append("stability_mismatch")

    expected_rows = (
        len(data["conditions"]) * len(data["selected_case_ids"]) * int(data["repeats"])
    )
    if len(rows) != expected_rows:
        issues.append(f"row_count:{len(rows)}!={expected_rows}")

    csv_path = experiment_dir / "results.csv"
    if not csv_path.exists():
        issues.append("results_csv_missing")
    else:
        with csv_path.open(encoding="utf-8", newline="") as handle:
            csv_count = sum(1 for _ in csv.DictReader(handle))
        if csv_count != len(rows):
            issues.append(f"csv_row_count:{csv_count}!={len(rows)}")

    complete_bundles = 0
    failed_bundles = 0
    for row in rows:
        run_dir = (
            experiment_dir
            / str(row["condition"])
            / str(row["case_id"])
            / f"r{int(row['repeat_id']):02d}"
        )
        if (run_dir / "failure.json").exists():
            failed_bundles += 1
            continue
        required = (
            "input.json",
            "config.json",
            "generated_specification.json",
            "trace_manifest.json",
            "validation_reports.json",
            "metrics.json",
        )
        missing = [name for name in required if not (run_dir / name).exists()]
        if missing:
            issues.append(f"missing_bundle:{row['condition']}:{row['case_id']}:{missing}")
            continue
        complete_bundles += 1
        metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
        for name, value in metrics.items():
            if name == "stability_multi_run":
                continue
            if name in row and not _same(row[name], value):
                issues.append(
                    f"metric_mismatch:{row['condition']}:{row['case_id']}:{name}"
                )

    saved_summary_keys = {
        str(item["condition"]): sorted(item.keys()) for item in data["summary"]
    }
    additional_fields: dict[str, list[str]] = {}
    for item in recomputed_summary:
        condition = str(item["condition"])
        fields = sorted(set(item) - set(saved_summary_keys.get(condition, [])))
        if fields:
            additional_fields[condition] = fields
    return {
        "experiment_id": data["experiment_id"],
        "passed": not issues,
        "results_sha256": hashlib.sha256(results_path.read_bytes()).hexdigest(),
        "saved_row_count": len(rows),
        "expected_row_count": expected_rows,
        "complete_run_bundles": complete_bundles,
        "failure_only_bundles": failed_bundles,
        "summary_recalculation_identical": saved_summary_identical,
        "stability_recalculation_identical": _same(saved_stability, recomputed_stability),
        "additional_recomputed_fields": additional_fields,
        "issues": issues,
    }
