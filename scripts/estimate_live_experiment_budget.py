"""Estimate staged DEV live budgets from the saved DEV-001 pilot."""

from __future__ import annotations

import json
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PILOT = (
    ROOT
    / "artifacts"
    / "benchmark_runs"
    / "repeated-b0-b1-full-dev001-2026-09-09"
    / "results.json"
)
CASES = ROOT / "benchmark" / "v1_0_synthetic" / "cases.json"
OUTPUT = ROOT / "artifacts" / "research_summary_2026-09-09"

# DeepSeek Flash peak, cache-miss prices verified on 2026-09-11.
# This deliberately ignores cache discounts and is therefore conservative.
INPUT_PRICE = 0.30
OUTPUT_PRICE = 1.20


def _means(rows: list[dict[str, Any]], condition: str) -> dict[str, float]:
    current = [row for row in rows if row["condition"] == condition]
    return {
        key: mean(float(row[key]) for row in current)
        for key in ("prompt_tokens", "completion_tokens", "total_tokens", "llm_calls")
    }


def _projection(
    observed: dict[str, float], *, cases: int, repeats: int, complexity_factor: float
) -> dict[str, float]:
    prompt = observed["prompt_tokens"] * cases * repeats * complexity_factor
    completion = observed["completion_tokens"] * cases * repeats * complexity_factor
    calls = observed["llm_calls"] * cases * repeats * complexity_factor
    peak_cost = (prompt * INPUT_PRICE + completion * OUTPUT_PRICE) / 1_000_000
    return {
        "estimated_prompt_tokens": round(prompt),
        "estimated_completion_tokens": round(completion),
        "estimated_total_tokens": round(prompt + completion),
        "estimated_calls": round(calls),
        "estimated_peak_cost_usd": round(peak_cost, 4),
        "estimated_off_peak_cost_usd": round(peak_cost / 2, 4),
    }


def main() -> None:
    pilot = json.loads(PILOT.read_text(encoding="utf-8"))
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    development = [case for case in cases if case["split"] == "development"]
    pilot_fr_count = len(development[0]["specification_req"]["functional_requirements"])
    average_fr_count = mean(
        len(case["specification_req"]["functional_requirements"]) for case in development
    )
    conditions = {
        condition: _means(pilot["rows"], condition)
        for condition in ("B1_ONESHOT", "FULL")
    }
    estimate_sources = {
        "B1_ONESHOT": conditions["B1_ONESHOT"],
        "FULL": conditions["FULL"],
        # Until measured, each component variant conservatively inherits FULL usage.
        "FULL_NO_CRITIC": conditions["FULL"],
        "FULL_NO_REPAIR": conditions["FULL"],
    }
    stage_specs = [
        {
            "stage": "representative_3_cases_once",
            "conditions": ["B1_ONESHOT", "FULL"],
            "case_ids": ["B1-DEV-002", "B1-DEV-010", "B1-DEV-020"],
            "case_count": 3,
            "repeats": 1,
            "average_fr_count": 5.0,
            "recommended_max_calls": 60,
            "recommended_max_tokens": 450_000,
            "recommended_max_estimated_cost_usd": 0.40,
        },
        {
            "stage": "full_dev20_once",
            "conditions": ["B1_ONESHOT", "FULL"],
            "case_ids": "all development",
            "case_count": 20,
            "repeats": 1,
            "average_fr_count": average_fr_count,
            "recommended_max_calls": 350,
            "recommended_max_tokens": 3_000_000,
            "recommended_max_estimated_cost_usd": 2.20,
        },
        {
            "stage": "full_dev20_three_repeats",
            "conditions": ["B1_ONESHOT", "FULL"],
            "case_ids": "all development",
            "case_count": 20,
            "repeats": 3,
            "average_fr_count": average_fr_count,
            "recommended_max_calls": 1_000,
            "recommended_max_tokens": 9_000_000,
            "recommended_max_estimated_cost_usd": 7.00,
        },
        {
            "stage": "representative_3_cases_all_live_conditions_once",
            "conditions": [
                "B1_ONESHOT",
                "FULL",
                "FULL_NO_CRITIC",
                "FULL_NO_REPAIR",
            ],
            "case_ids": ["B1-DEV-002", "B1-DEV-010", "B1-DEV-020"],
            "case_count": 3,
            "repeats": 1,
            "average_fr_count": 5.0,
            "recommended_max_calls": 160,
            "recommended_max_tokens": 1_200_000,
            "recommended_max_estimated_cost_usd": 0.90,
        },
    ]
    stages: list[dict[str, Any]] = []
    for stage in stage_specs:
        factor = float(stage["average_fr_count"]) / pilot_fr_count
        projections = {
            condition: _projection(
                observed,
                cases=int(stage["case_count"]),
                repeats=int(stage["repeats"]),
                complexity_factor=factor,
            )
            for condition, observed in estimate_sources.items()
            if condition in stage["conditions"]
        }
        total_tokens = sum(item["estimated_total_tokens"] for item in projections.values())
        total_calls = sum(item["estimated_calls"] for item in projections.values())
        peak_cost = sum(item["estimated_peak_cost_usd"] for item in projections.values())
        stages.append(
            {
                **stage,
                "complexity_factor_vs_dev001": round(factor, 4),
                "conditions": projections,
                "combined_estimate": {
                    "total_tokens": total_tokens,
                    "calls": total_calls,
                    "peak_cost_usd": round(peak_cost, 4),
                    "off_peak_cost_usd": round(peak_cost / 2, 4),
                },
            }
        )
    report = {
        "basis": {
            "pilot_experiment_id": pilot["experiment_id"],
            "pilot_case": "B1-DEV-001",
            "pilot_repeats": pilot["repeats"],
            "pilot_fr_count": pilot_fr_count,
            "development_average_fr_count": average_fr_count,
            "price_source": "https://api-docs.deepseek.com/quick_start/pricing/",
            "price_checked": "2026-09-11",
            "peak_cache_miss_input_usd_per_million": INPUT_PRICE,
            "peak_output_usd_per_million": OUTPUT_PRICE,
        },
        "method": (
            "Observed mean prompt/output tokens and calls per DEV-001 run, multiplied by "
            "case count, repeats and the ratio of mean FR count to DEV-001 FR count. "
            "Recommended hard guards are rounded above the estimate."
        ),
        "limitations": [
            "Only one pilot case is available; generated UC counts and repair rates may differ.",
            "Provider prices and cache behavior may change.",
            "The cost threshold is a soft stop checked before the next call and can "
            "overshoot by one call.",
        ],
        "stages": stages,
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "live_dev20_budget_estimate.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# Live DEV20 budget estimate",
        "",
        "This is planning evidence, not a provider quote. Prices were checked on 2026-09-09.",
        "",
    ]
    for stage in stages:
        combined = stage["combined_estimate"]
        lines.extend(
            [
                f"## {stage['stage']}",
                "",
                f"- projected calls: {combined['calls']}",
                f"- projected tokens: {combined['total_tokens']}",
                f"- projected peak/off-peak cost: ${combined['peak_cost_usd']:.2f} / "
                f"${combined['off_peak_cost_usd']:.2f}",
                f"- recommended guards: calls {stage['recommended_max_calls']}, tokens "
                f"{stage['recommended_max_tokens']}, cost "
                f"${stage['recommended_max_estimated_cost_usd']:.2f}",
                "",
            ]
        )
    lines.extend(
        [
            "## Important limitation",
            "",
            "The estimate extrapolates one simple case. Run the representative "
            "three-case stage first, "
            "then recalculate before DEV20. Hidden remains sealed.",
        ]
    )
    (OUTPUT / "live_dev20_budget_estimate.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
