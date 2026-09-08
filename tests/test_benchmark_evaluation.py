from __future__ import annotations

import json
from pathlib import Path

from traceable_spec.evaluation.benchmark import evaluate_semantic_projection

ROOT = Path(__file__).resolve().parents[1]


def _first_case() -> dict:
    cases = json.loads(
        (ROOT / "benchmark" / "v1_0_synthetic" / "cases.json").read_text(encoding="utf-8")
    )
    return cases[0]


def _oracle_projection(case: dict) -> dict:
    gold = case["gold"]
    return {
        "actors": [slot["canonical"] for slot in gold["actor_slots"]],
        "use_cases": [
            {
                "name": uc["name"],
                "source_fr_ids": uc["source_fr_ids"],
                "milestones": uc["required_milestones"],
                "branches": [
                    {
                        "condition": item["condition"],
                        "outcomes": item["required_outcomes"],
                    }
                    for item in uc["required_branches"]
                ],
            }
            for uc in gold["use_case_slots"]
        ],
    }


def test_semantic_benchmark_oracle_scores_one() -> None:
    case = _first_case()
    metrics = evaluate_semantic_projection(_oracle_projection(case), case["gold"])
    assert metrics["semantic_composite"] == 1.0
    assert metrics["hallucination_rate"] == 0.0


def test_semantic_benchmark_penalizes_missing_milestones() -> None:
    case = _first_case()
    prediction = _oracle_projection(case)
    prediction["use_cases"][0]["milestones"] = []
    metrics = evaluate_semantic_projection(prediction, case["gold"])
    assert metrics["milestone_recall"] == 0.0
    assert metrics["semantic_composite"] < 1.0


def test_semantic_benchmark_penalizes_hallucinated_elements() -> None:
    case = _first_case()
    prediction = _oracle_projection(case)
    prediction["actors"].append("Invented regulator")
    metrics = evaluate_semantic_projection(prediction, case["gold"])
    assert metrics["actor_precision"] < 1.0
    assert metrics["hallucination_rate"] > 0.0
