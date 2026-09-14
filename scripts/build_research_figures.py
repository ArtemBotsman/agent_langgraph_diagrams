"""Build reproducible presentation figures from saved experiment JSON files."""

# Long inline SVG fragments are intentionally kept readable and reproducible.
# ruff: noqa: E501

from __future__ import annotations

import csv
import hashlib
import json
import random
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPEATED_RESULT = (
    ROOT / "artifacts" / "benchmark_runs" / "repeated-b0-b1-full-dev001-2026-09-09" / "results.json"
)
B0_DEV_RESULT = (
    ROOT / "artifacts" / "benchmark_runs" / "b0-dev20-r3-2026-09-09" / "results.json"
)
OUTPUT_DIR = ROOT / "artifacts" / "research_summary_2026-09-09"


def _condition_rows(result: dict[str, Any], condition: str) -> list[dict[str, Any]]:
    return [row for row in result["rows"] if row["condition"] == condition]


def _condition_summary(result: dict[str, Any], condition: str) -> dict[str, Any]:
    rows = _condition_rows(result, condition)
    return {
        "condition": condition,
        "repeats": len(rows),
        "e2e_success_rate": mean(float(row["end_to_end_success"]) for row in rows),
        "semantic_composite": mean(float(row["semantic_composite"]) for row in rows),
        "activity_trace_coverage": mean(
            float(row["activity_element_trace_coverage"]) for row in rows
        ),
        "hallucination_rate": mean(float(row["hallucination_rate"]) for row in rows),
        "latency_ms": mean(float(row["latency_ms"]) for row in rows),
        "tokens": mean(float(row["total_tokens"]) for row in rows),
        "repairs": mean(float(row["repair_attempts"]) for row in rows),
        "score_stability": rows[0].get("stability_multi_run"),
    }


def _bar(x: float, y: float, width: float, value: float, color: str) -> str:
    height = 180 * value
    return (
        f'<rect x="{x}" y="{y + 180 - height:.1f}" width="{width}" '
        f'height="{height:.1f}" rx="4" fill="{color}"/>'
    )


def _write_comparison_svg(rows: list[dict[str, Any]], path: Path) -> None:
    colors = ["#475569", "#d97706", "#0f766e"]
    labels = ["B0 rules", "B1 one-shot", "FULL graph"]
    groups = [
        ("E2E success", "e2e_success_rate"),
        ("Semantic", "semantic_composite"),
        ("Activity trace", "activity_trace_coverage"),
    ]
    fragments: list[str] = []
    for group_idx, (group_label, key) in enumerate(groups):
        group_x = 90 + group_idx * 330
        fragments.append(
            f'<text x="{group_x + 85}" y="330" text-anchor="middle" '
            f'font-family="Arial" font-size="15" fill="#334155">{group_label}</text>'
        )
        for row_idx, row in enumerate(rows):
            value = float(row[key])
            x = group_x + row_idx * 62
            fragments.append(_bar(x, 110, 46, value, colors[row_idx]))
            fragments.append(
                f'<text x="{x + 23}" y="{277 - 180 * value:.1f}" text-anchor="middle" '
                f'font-family="Arial" font-size="13" font-weight="700" '
                f'fill="#0f172a">{value:.0%}</text>'
            )
    legend = "".join(
        f'<rect x="{790 + idx * 120}" y="35" width="14" height="14" fill="{color}"/>'
        f'<text x="{810 + idx * 120}" y="48" font-family="Arial" font-size="13" '
        f'fill="#334155">{label}</text>'
        for idx, (color, label) in enumerate(zip(colors, labels, strict=True))
    )
    details = "".join(
        f'<text x="70" y="{378 + idx * 34}" font-family="Arial" font-size="16" '
        f'fill="#0f172a"><tspan font-weight="700">{labels[idx]}:</tspan> '
        f"{row['latency_ms'] / 1000:.2f} s; {row['tokens']:.0f} tokens; "
        f"{row['repairs']:.0f} repairs; hallucination proxy {row['hallucination_rate']:.1%}</text>"
        for idx, row in enumerate(rows)
    )
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1120" height="530">
<rect width="1120" height="530" fill="#ffffff"/>
<text x="55" y="48" font-family="Arial" font-size="25" font-weight="700" fill="#0f172a">B0 / B1 / FULL — repeated DEV-001 pilot</text>
<text x="55" y="73" font-family="Arial" font-size="14" fill="#64748b">2 repeats per condition; DeepSeek V4 Flash for B1/FULL; hidden tests untouched</text>
{legend}
<line x1="55" y1="290" x2="1055" y2="290" stroke="#cbd5e1" stroke-width="1"/>
{"".join(fragments)}
{details}
<text x="70" y="504" font-family="Arial" font-size="13" fill="#64748b">Semantic metric is a candidate local multilingual slot matcher; expert review is still required.</text>
</svg>"""
    path.write_text(svg, encoding="utf-8")


def _case_means(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["case_id"]), []).append(row)
    result: list[dict[str, Any]] = []
    for case_id, current in sorted(grouped.items()):
        first = current[0]
        result.append(
            {
                "case_id": case_id,
                "complexity": first["complexity"],
                "language": first["language"],
                "repeats": len(current),
                **{
                    metric: mean(float(row[metric]) for row in current)
                    for metric in (
                        "end_to_end_success",
                        "semantic_composite",
                        "actor_f1",
                        "uc_f1",
                        "milestone_f1",
                        "branch_f1",
                        "trace_f1",
                        "hallucination_rate",
                        "latency_ms",
                        "total_tokens",
                        "repair_attempts",
                        "stability_multi_run",
                    )
                },
            }
        )
    return result


def _mean_sd(values: list[float]) -> tuple[float, float]:
    return mean(values), pstdev(values) if len(values) > 1 else 0.0


def _bootstrap_mean_ci(
    values: list[float], seed_label: str, *, resamples: int = 10_000
) -> tuple[float, float]:
    """Deterministic percentile bootstrap CI over independent benchmark cases."""

    if len(values) == 1 or len(set(values)) == 1:
        return values[0], values[0]
    seed = int.from_bytes(hashlib.sha256(seed_label.encode("utf-8")).digest()[:8], "big")
    rng = random.Random(seed)
    estimates = sorted(
        mean(rng.choice(values) for _ in range(len(values))) for _ in range(resamples)
    )
    return estimates[int(0.025 * resamples)], estimates[int(0.975 * resamples) - 1]


def _write_b0_dev_svg(case_rows: list[dict[str, Any]], path: Path) -> None:
    component_keys = [
        ("Actor F1", "actor_f1"),
        ("Use Case F1", "uc_f1"),
        ("Milestone F1", "milestone_f1"),
        ("Branch F1", "branch_f1"),
        ("Trace F1", "trace_f1"),
        ("Composite", "semantic_composite"),
    ]
    colors = ["#315a7d", "#347f75", "#8a6d3b", "#a24d4d", "#6b5b95", "#0f766e"]
    fragments: list[str] = []
    for index, ((label, key), color) in enumerate(zip(component_keys, colors, strict=True)):
        value = mean(float(row[key]) for row in case_rows)
        x = 80 + index * 150
        fragments.append(_bar(x, 115, 80, value, color))
        fragments.append(
            f'<text x="{x + 40}" y="{287 - 180 * value:.1f}" text-anchor="middle" '
            f'font-family="Arial" font-size="15" font-weight="700" fill="#0f172a">{value:.1%}</text>'
        )
        fragments.append(
            f'<text x="{x + 40}" y="326" text-anchor="middle" '
            f'font-family="Arial" font-size="14" fill="#334155">{label}</text>'
        )
    complexity_lines: list[str] = []
    for index, complexity in enumerate(("simple", "medium", "hard")):
        current = [row for row in case_rows if row["complexity"] == complexity]
        semantic = mean(float(row["semantic_composite"]) for row in current)
        hallucination = mean(float(row["hallucination_rate"]) for row in current)
        complexity_lines.append(
            f'<text x="85" y="{402 + index * 33}" font-family="Arial" font-size="16" '
            f'fill="#0f172a"><tspan font-weight="700">{complexity} (n={len(current)}):</tspan> '
            f'semantic {semantic:.1%}; hallucination proxy {hallucination:.1%}</text>'
        )
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1040" height="540">
<rect width="1040" height="540" fill="#ffffff"/>
<text x="55" y="48" font-family="Arial" font-size="25" font-weight="700" fill="#0f172a">B0 deterministic baseline — full DEV20</text>
<text x="55" y="76" font-family="Arial" font-size="14" fill="#64748b">20 cases × 3 identical repeats; 60/60 completed; 0 LLM tokens; hidden tests untouched</text>
<line x1="55" y1="295" x2="980" y2="295" stroke="#cbd5e1" stroke-width="1"/>
{"".join(fragments)}
<text x="55" y="367" font-family="Arial" font-size="18" font-weight="700" fill="#0f172a">Quality by case complexity</text>
{"".join(complexity_lines)}
<text x="55" y="518" font-family="Arial" font-size="13" fill="#64748b">Conclusion: deterministic construction is reproducible and structurally valid, but not semantically sufficient.</text>
</svg>"""
    path.write_text(svg, encoding="utf-8")


def _write_b0_dev_results(result: dict[str, Any]) -> None:
    case_rows = _case_means(_condition_rows(result, "B0_RULE"))
    metrics = (
        "end_to_end_success",
        "semantic_composite",
        "actor_f1",
        "uc_f1",
        "milestone_f1",
        "branch_f1",
        "trace_f1",
        "hallucination_rate",
        "latency_ms",
        "total_tokens",
        "repair_attempts",
        "stability_multi_run",
    )
    groups = [("all", "all", case_rows)]
    groups.extend(
        ("complexity", value, [row for row in case_rows if row["complexity"] == value])
        for value in ("simple", "medium", "hard")
    )
    groups.extend(
        ("language", value, [row for row in case_rows if row["language"] == value])
        for value in ("ru", "en")
    )
    summaries: list[dict[str, Any]] = []
    for group_type, group_value, current in groups:
        for metric in metrics:
            values = [float(row[metric]) for row in current]
            metric_mean, metric_sd = _mean_sd(values)
            ci_low, ci_high = _bootstrap_mean_ci(
                values,
                f"{result['experiment_id']}:{group_type}:{group_value}:{metric}",
            )
            summaries.append(
                {
                    "group_type": group_type,
                    "group_value": group_value,
                    "case_count": len(current),
                    "run_count": sum(int(row["repeats"]) for row in current),
                    "metric": metric,
                    "mean": metric_mean,
                    "stddev_between_cases": metric_sd,
                    "ci95_bootstrap_low": ci_low,
                    "ci95_bootstrap_high": ci_high,
                    "bootstrap_resamples": 10_000,
                }
            )
    with (OUTPUT_DIR / "b0_dev20_case_means.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(case_rows[0]))
        writer.writeheader()
        writer.writerows(case_rows)
    with (OUTPUT_DIR / "b0_dev20_summary.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)
    (OUTPUT_DIR / "b0_dev20_summary.json").write_text(
        json.dumps(
            {
                "experiment_id": result["experiment_id"],
                "case_count": len(case_rows),
                "run_count": len(result["rows"]),
                "claim_limit": result["claim_limit"],
                "summaries": summaries,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    _write_b0_dev_svg(case_rows, OUTPUT_DIR / "b0_dev20_quality.svg")


def main() -> None:
    result = json.loads(REPEATED_RESULT.read_text(encoding="utf-8"))
    rows = [
        _condition_summary(result, condition) for condition in ("B0_RULE", "B1_ONESHOT", "FULL")
    ]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUTPUT_DIR / "baseline_comparison.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (OUTPUT_DIR / "baseline_comparison.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_comparison_svg(rows, OUTPUT_DIR / "baseline_comparison.svg")
    if B0_DEV_RESULT.exists():
        _write_b0_dev_results(json.loads(B0_DEV_RESULT.read_text(encoding="utf-8")))
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
