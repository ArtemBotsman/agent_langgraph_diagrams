"""Run evaluator sanity checks without making any LLM/API calls.

The experiment verifies metric direction on controlled gold mutations. It must
not be reported as model quality or as a comparison between LLM systems.
"""

# SVG fragments stay as single strings so the generated artifact is auditable.
# ruff: noqa: E501

from __future__ import annotations

import csv
import json
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from statistics import mean
from typing import Any

from traceable_spec.evaluation.benchmark import evaluate_semantic_projection

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "benchmark" / "v1_0_synthetic" / "cases.json"
OUTPUT_DIR = ROOT / "artifacts" / "offline_methodology_2026-09-08"


def _oracle(gold: dict[str, Any]) -> dict[str, Any]:
    return {
        "actors": [slot["canonical"] for slot in gold["actor_slots"]],
        "use_cases": [
            {
                "name": uc["name"],
                "source_fr_ids": list(uc["source_fr_ids"]),
                "milestones": list(uc["required_milestones"]),
                "branches": [
                    {
                        "condition": item["condition"],
                        "outcomes": list(item["required_outcomes"]),
                    }
                    for item in uc["required_branches"]
                ],
            }
            for uc in gold["use_case_slots"]
        ],
    }


def _mutate(profile: str, prediction: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(prediction)
    if profile == "oracle":
        return result
    if profile == "incomplete":
        for uc in result["use_cases"]:
            uc["milestones"] = uc["milestones"][::2]
            uc["branches"] = []
        return result
    if profile == "hallucinated":
        result["actors"].append("Invented external auditor")
        if result["use_cases"]:
            result["use_cases"][0]["milestones"].append("Send data to an invented service")
            result["use_cases"][0]["branches"].append(
                {"condition": "invented condition", "outcomes": ["invented outcome"]}
            )
        return result
    if profile == "wrong_trace":
        for uc in result["use_cases"]:
            uc["source_fr_ids"] = ["FR-999"]
        return result
    raise ValueError(profile)


def _write_svg(summary: list[dict[str, Any]]) -> None:
    width = 1120
    height = 520
    margin_left = 210
    top = 70
    row_height = 95
    bar_width = 760
    colors = {
        "oracle": "#0F766E",
        "incomplete": "#D97706",
        "hallucinated": "#DC2626",
        "wrong_trace": "#7C3AED",
    }
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="#FFFFFF"/>',
        '<text x="40" y="38" font-family="Arial" font-size="24" font-weight="700" fill="#111827">Offline evaluator sanity experiment</text>',
        '<text x="40" y="61" font-family="Arial" font-size="14" fill="#4B5563">30 synthetic cases; controlled mutations; no LLM calls</text>',
    ]
    for idx, row in enumerate(summary):
        y = top + idx * row_height
        profile = str(row["profile"])
        semantic = float(row["semantic_composite"])
        hallucination = float(row["hallucination_rate"])
        lines.extend(
            [
                f'<text x="40" y="{y + 30}" font-family="Arial" font-size="17" fill="#111827">{profile}</text>',
                f'<rect x="{margin_left}" y="{y + 10}" width="{bar_width}" height="28" rx="4" fill="#E5E7EB"/>',
                f'<rect x="{margin_left}" y="{y + 10}" width="{bar_width * semantic:.1f}" height="28" rx="4" fill="{colors[profile]}"/>',
                f'<text x="{margin_left + bar_width + 18}" y="{y + 31}" font-family="Arial" font-size="15" fill="#111827">score {semantic:.3f}</text>',
                f'<text x="{margin_left}" y="{y + 60}" font-family="Arial" font-size="13" fill="#4B5563">hallucination {hallucination:.3f}; trace F1 {float(row["trace_f1"]):.3f}; milestone F1 {float(row["milestone_f1"]):.3f}</text>',
            ]
        )
    lines.extend(
        [
            '<text x="40" y="485" font-family="Arial" font-size="13" fill="#991B1B">This validates evaluator behaviour only. It is not evidence of LLM quality or pipeline superiority.</text>',
            "</svg>",
        ]
    )
    (OUTPUT_DIR / "metric_sanity_chart.svg").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    profiles = ["oracle", "incomplete", "hallucinated", "wrong_trace"]
    rows: list[dict[str, Any]] = []
    for case in cases:
        base = _oracle(case["gold"])
        for profile in profiles:
            metrics = evaluate_semantic_projection(_mutate(profile, base), case["gold"])
            rows.append(
                {
                    "case_id": case["case_id"],
                    "split": case["split"],
                    "complexity": case["complexity"],
                    "language": case["language"],
                    "profile": profile,
                    **metrics,
                }
            )

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["profile"])].append(row)
    metric_names = [
        "actor_f1",
        "uc_f1",
        "milestone_f1",
        "branch_f1",
        "trace_f1",
        "hallucination_rate",
        "semantic_composite",
    ]
    summary = [
        {
            "profile": profile,
            "case_count": len(grouped[profile]),
            **{
                metric: mean(float(row[metric]) for row in grouped[profile])
                for metric in metric_names
            },
        }
        for profile in profiles
    ]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "results.json").write_text(
        json.dumps(
            {
                "experiment_id": "offline-methodology-sanity-2026-09-08",
                "experiment_type": "evaluator_sanity_mutation_test",
                "llm_calls": 0,
                "claim_limit": "Evaluator behaviour only; not model or pipeline quality.",
                "summary": summary,
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    with (OUTPUT_DIR / "summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)
    _write_svg(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
