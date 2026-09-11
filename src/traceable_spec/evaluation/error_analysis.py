"""Deterministic error classification for saved benchmark experiments."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


def analyze_saved_experiment(experiment_dir: Path) -> dict[str, Any]:
    """Classify technical, validation and semantic risks from saved evidence."""

    data = json.loads((experiment_dir / "results.json").read_text(encoding="utf-8"))
    by_condition: dict[str, dict[str, Any]] = {}
    global_codes: Counter[str] = Counter()

    for condition in data["conditions"]:
        current = [row for row in data["rows"] if row["condition"] == condition]
        codes: Counter[str] = Counter()
        unresolved_codes: Counter[str] = Counter()
        repaired_codes: Counter[str] = Counter()
        exception_failures = 0
        controlled_failures = 0
        e2e_failures = 0
        low_semantic = 0
        high_hallucination = 0
        examples: list[dict[str, Any]] = []
        for row in current:
            has_exception = bool(row.get("error_type"))
            if has_exception:
                exception_failures += 1
            if row.get("run_status") != "success" and not has_exception:
                controlled_failures += 1
            if float(row.get("end_to_end_success") or 0.0) < 1.0:
                e2e_failures += 1
            if float(row.get("semantic_composite") or 0.0) < 0.5:
                low_semantic += 1
            if float(row.get("hallucination_rate") or 0.0) > 0.4:
                high_hallucination += 1

            run_dir = (
                experiment_dir
                / str(condition)
                / str(row["case_id"])
                / f"r{int(row['repeat_id']):02d}"
            )
            report_path = run_dir / "validation_reports.json"
            row_codes: list[str] = []
            if report_path.exists():
                reports = json.loads(report_path.read_text(encoding="utf-8"))
                for report in reports:
                    for issue in report.get("issues", []):
                        if issue.get("blocking"):
                            code = str(issue.get("code") or "unknown_blocking_issue")
                            codes[code] += 1
                            row_codes.append(code)
            if float(row.get("end_to_end_success") or 0.0) < 1.0:
                unresolved_codes.update(row_codes)
                global_codes.update(row_codes)
                examples.append(
                    {
                        "case_id": row["case_id"],
                        "repeat_id": row["repeat_id"],
                        "blocking_codes": sorted(set(row_codes)),
                        "semantic_composite": row.get("semantic_composite"),
                        "hallucination_rate": row.get("hallucination_rate"),
                    }
                )
            else:
                repaired_codes.update(row_codes)

        by_condition[str(condition)] = {
            "run_count": len(current),
            "exception_failure_count": exception_failures,
            "controlled_pipeline_failure_count": controlled_failures,
            "end_to_end_failure_count": e2e_failures,
            "low_semantic_below_0_5_count": low_semantic,
            "high_hallucination_above_0_4_count": high_hallucination,
            "all_detected_blocking_issue_counts": dict(codes.most_common()),
            "unresolved_blocking_issue_counts": dict(unresolved_codes.most_common()),
            "detected_then_repaired_issue_counts": dict(repaired_codes.most_common()),
            "representative_failures": examples[:10],
        }

    return {
        "experiment_id": data["experiment_id"],
        "thresholds": {
            "low_semantic_composite": 0.5,
            "high_hallucination_rate": 0.4,
        },
        "by_condition": by_condition,
        "global_unresolved_blocking_issue_counts": dict(global_codes.most_common()),
        "interpretation_limit": (
            "Automatic categories diagnose saved runs; semantic correctness still requires "
            "independent expert review."
        ),
    }
