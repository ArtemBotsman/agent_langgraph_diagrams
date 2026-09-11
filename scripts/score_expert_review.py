"""Validate two completed expert packets and compute transparent agreement metrics."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

SCORE_FIELDS = [
    "domain_plausibility_1_5",
    "actor_uc_boundaries_1_5",
    "scenario_completeness_1_5",
    "branch_correctness_1_5",
    "trace_correctness_1_5",
    "assumption_discipline_1_5",
]


def _load(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return {row["case_id"]: row for row in rows}


def _weighted_kappa(left: list[int], right: list[int]) -> float:
    """Linear weighted Cohen kappa for ordinal categories 1..5."""

    count = len(left)
    if count == 0:
        raise ValueError("No paired ratings")
    observed_disagreement = sum(abs(a - b) / 4 for a, b in zip(left, right, strict=True))
    observed_disagreement /= count
    left_counts = Counter(left)
    right_counts = Counter(right)
    expected_disagreement = sum(
        (left_counts[a] / count) * (right_counts[b] / count) * abs(a - b) / 4
        for a in range(1, 6)
        for b in range(1, 6)
    )
    if expected_disagreement == 0:
        return 1.0 if observed_disagreement == 0 else 0.0
    return 1.0 - observed_disagreement / expected_disagreement


def score(left_path: Path, right_path: Path) -> dict[str, Any]:
    left_rows = _load(left_path)
    right_rows = _load(right_path)
    if set(left_rows) != set(right_rows):
        raise ValueError("Expert packets contain different case IDs")
    errors: list[str] = []
    dimensions: dict[str, Any] = {}
    for field in SCORE_FIELDS:
        left_scores: list[int] = []
        right_scores: list[int] = []
        for case_id in sorted(left_rows):
            try:
                left_score = int(left_rows[case_id][field])
                right_score = int(right_rows[case_id][field])
            except (KeyError, TypeError, ValueError):
                errors.append(f"{case_id}: missing integer score for {field}")
                continue
            if left_score not in range(1, 6) or right_score not in range(1, 6):
                errors.append(f"{case_id}: {field} must be 1..5")
                continue
            left_scores.append(left_score)
            right_scores.append(right_score)
        if left_scores and len(left_scores) == len(left_rows):
            dimensions[field] = {
                "weighted_cohen_kappa": _weighted_kappa(left_scores, right_scores),
                "exact_agreement": mean(
                    a == b for a, b in zip(left_scores, right_scores, strict=True)
                ),
                "within_one_agreement": mean(
                    abs(a - b) <= 1 for a, b in zip(left_scores, right_scores, strict=True)
                ),
                "expert_1_mean": mean(left_scores),
                "expert_2_mean": mean(right_scores),
            }
    for case_id in sorted(left_rows):
        for label, row in (("expert_1", left_rows[case_id]), ("expert_2", right_rows[case_id])):
            if row.get("decision") not in {"approve", "revise"}:
                errors.append(f"{case_id}: {label} decision must be approve or revise")
            if not row.get("expert_id", "").strip():
                errors.append(f"{case_id}: {label} expert_id is blank")
    return {
        "complete": not errors,
        "case_count": len(left_rows),
        "dimensions": dimensions,
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("expert_1", type=Path)
    parser.add_argument("expert_2", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = score(args.expert_1, args.expert_2)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    raise SystemExit(0 if result["complete"] else 2)


if __name__ == "__main__":
    main()
