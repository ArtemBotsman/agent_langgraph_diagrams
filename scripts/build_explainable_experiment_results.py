"""Build presentation evidence without B0, composite scores or LLM judges.

The report uses the frozen DEV20 runs already saved by the experiment runner.
Failed attempts remain in the denominator and receive zero task-level quality,
while a separate parsed-output sensitivity table shows content quality only for
responses that could be read. The independent statistical unit is a project:
three repeats are averaged inside each project before confidence intervals and
paired tests are calculated.
"""

# ruff: noqa: E501 -- long SVG fragments and generated Markdown rows are intentional.

from __future__ import annotations

import csv
import hashlib
import html
import json
import shutil
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "artifacts" / "explainable_experiment_results_2026-09-15"
DOC_PATH = ROOT / "docs" / "research" / "EXPLAINABLE_EXPERIMENT_RESULTS_2026_09_15.md"
OBSIDIAN_ASSET_DIR = ROOT / "docs" / "obsidian_vault" / "assets"

RUNS = {
    "ONE_SHOT": ROOT
    / "artifacts"
    / "benchmark_runs"
    / "b1-dev20-r3-deepseek-flash-2026-09-13",
    "FULL": ROOT
    / "artifacts"
    / "benchmark_runs"
    / "full-dev20-r3-deepseek-flash-2026-09-13",
}
CONDITION_DIR = {"ONE_SHOT": "B1_ONESHOT", "FULL": "FULL"}
LABELS = {"ONE_SHOT": "Один вызов LLM", "FULL": "Полный граф"}
COLORS = {"ONE_SHOT": "#8f6f32", "FULL": "#24796f"}
CONTENT_METRICS = (
    ("actor_f1", "Actor F1"),
    ("uc_f1", "Use Case F1"),
    ("milestone_f1", "Milestone F1"),
    ("branch_f1", "Branch F1"),
)
TRACE_METRICS = (
    ("trace_f1", "Trace F1"),
    ("fr_coverage", "FR→UC coverage"),
    ("fr_activity_coverage", "FR→Activity coverage"),
    ("activity_element_trace_coverage", "Activity trace coverage"),
    ("activity_structural_validity", "Activity validity"),
    ("end_to_end_success", "E2E success"),
)
ALL_TEST_METRICS = tuple(key for key, _ in (*CONTENT_METRICS, *TRACE_METRICS))
BOOTSTRAP_SEED = 20260915
BOOTSTRAP_RESAMPLES = 50_000


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _number(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    return float(value)


def _percentile(values: list[float], q: float) -> float:
    return float(np.quantile(np.asarray(values, dtype=float), q)) if values else 0.0


def _fr_activity_coverage(specification: dict[str, Any]) -> float:
    fr_ids = {
        str(requirement["id"])
        for requirement in specification["request"]["functional_requirements"]
    }
    if not fr_ids:
        return 0.0
    steps_by_fr: dict[str, set[str]] = {fr_id: set() for fr_id in fr_ids}
    activity_step_ids: set[str] = set()
    for link in specification.get("trace_manifest", {}).get("links", []):
        link_type = str(link.get("link_type", ""))
        if link_type == "fr_to_step" and str(link.get("source_id")) in steps_by_fr:
            steps_by_fr[str(link["source_id"])].add(str(link["target_id"]))
        elif link_type in {"step_to_activity_node", "step_to_activity_edge"}:
            activity_step_ids.add(str(link.get("source_id")))
    covered = sum(bool(step_ids & activity_step_ids) for step_ids in steps_by_fr.values())
    return covered / len(fr_ids)


def _trace_manifest_validity(specification: dict[str, Any]) -> float:
    reports = [
        report
        for report in specification.get("validation_reports", [])
        if report.get("validator_name") == "e2e_trace"
    ]
    return 1.0 if reports and bool(reports[-1].get("passed")) else 0.0


def _load_rows() -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    result: dict[str, list[dict[str, Any]]] = {}
    metadata: dict[str, Any] = {"source_sha256": {}}
    expected_pairs: set[tuple[str, int]] | None = None
    benchmark_hash: str | None = None
    for method, run_dir in RUNS.items():
        csv_path = run_dir / "results.csv"
        json_path = run_dir / "results.json"
        rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
        if len(rows) != 60:
            raise ValueError(f"{method}: expected 60 attempts, got {len(rows)}")
        pairs = {(str(row["case_id"]), int(row["repeat_id"])) for row in rows}
        if len(pairs) != 60 or len({case_id for case_id, _ in pairs}) != 20:
            raise ValueError(f"{method}: expected 20 projects x 3 unique repeats")
        run_metadata = json.loads(json_path.read_text(encoding="utf-8"))
        current_hash = str(run_metadata["cases_sha256"])
        if expected_pairs is None:
            expected_pairs = pairs
            benchmark_hash = current_hash
        elif pairs != expected_pairs or current_hash != benchmark_hash:
            raise ValueError("The compared methods do not use the same projects and repeats")

        condition_dir = run_dir / CONDITION_DIR[method]
        for row in rows:
            output_path = (
                condition_dir
                / str(row["case_id"])
                / f"r{int(row['repeat_id']):02d}"
                / "generated_specification.json"
            )
            if output_path.exists():
                specification = json.loads(output_path.read_text(encoding="utf-8"))
                row["fr_activity_coverage"] = _fr_activity_coverage(specification)
                row["trace_manifest_validity"] = _trace_manifest_validity(specification)
                row["parsed_output"] = True
            else:
                row["fr_activity_coverage"] = 0.0
                row["trace_manifest_validity"] = 0.0
                row["parsed_output"] = False
        result[method] = rows
        metadata["source_sha256"][method] = _sha256(json_path)
    metadata.update(
        {
            "benchmark_cases_sha256": benchmark_hash,
            "project_count": 20,
            "repeats_per_project": 3,
            "attempts_per_method": 60,
            "bootstrap_seed": BOOTSTRAP_SEED,
            "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
            "failure_policy": "failed attempt remains in denominator; missing task metrics = 0",
        }
    )
    return result, metadata


def _case_means(rows: list[dict[str, Any]], metric: str) -> dict[str, float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        grouped[str(row["case_id"])].append(_number(row.get(metric)))
    return {case_id: mean(values) for case_id, values in grouped.items()}


def _bootstrap_ci(values: list[float], *, seed_offset: int = 0) -> tuple[float, float]:
    array = np.asarray(values, dtype=float)
    rng = np.random.default_rng(BOOTSTRAP_SEED + seed_offset)
    indices = rng.integers(0, len(array), size=(BOOTSTRAP_RESAMPLES, len(array)))
    samples = array[indices].mean(axis=1)
    low, high = np.quantile(samples, [0.025, 0.975])
    return float(low), float(high)


def _exact_sign_flip_pvalue(differences: list[float]) -> float:
    values = np.asarray(differences, dtype=float)
    nonzero = values[np.abs(values) > 1e-12]
    if len(nonzero) == 0:
        return 1.0
    observed = abs(float(values.mean()))
    total = 1 << len(nonzero)
    extreme = 0
    bit_positions = np.arange(len(nonzero), dtype=np.uint64)
    for start in range(0, total, 65_536):
        masks = np.arange(start, min(start + 65_536, total), dtype=np.uint64)
        bits = ((masks[:, None] >> bit_positions) & 1).astype(float)
        signed_sums = ((bits * 2.0 - 1.0) * nonzero).sum(axis=1)
        permuted = np.abs(signed_sums / len(values))
        extreme += int(np.count_nonzero(permuted >= observed - 1e-15))
    return extreme / total


def _holm_adjust(records: list[dict[str, Any]]) -> None:
    ordered = sorted(records, key=lambda item: float(item["p_value"]))
    running = 0.0
    total = len(ordered)
    for index, record in enumerate(ordered):
        running = max(running, min(1.0, (total - index) * float(record["p_value"])))
        record["holm_adjusted_p_value"] = running


def _metric_summary(
    all_rows: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    summary: list[dict[str, Any]] = []
    statistics: list[dict[str, Any]] = []
    for metric_index, metric in enumerate(ALL_TEST_METRICS):
        for method in ("ONE_SHOT", "FULL"):
            case_values = _case_means(all_rows[method], metric)
            values = [case_values[case_id] for case_id in sorted(case_values)]
            low, high = _bootstrap_ci(values, seed_offset=metric_index)
            summary.append(
                {
                    "method": method,
                    "method_ru": LABELS[method],
                    "metric": metric,
                    "project_macro_mean": mean(values),
                    "ci_95_low": low,
                    "ci_95_high": high,
                    "project_count": len(values),
                    "attempt_count": len(all_rows[method]),
                }
            )
        one_shot = _case_means(all_rows["ONE_SHOT"], metric)
        full = _case_means(all_rows["FULL"], metric)
        case_ids = sorted(one_shot)
        differences = [full[case_id] - one_shot[case_id] for case_id in case_ids]
        low, high = _bootstrap_ci(differences, seed_offset=100 + metric_index)
        statistics.append(
            {
                "metric": metric,
                "full_minus_one_shot": mean(differences),
                "ci_95_low": low,
                "ci_95_high": high,
                "p_value": _exact_sign_flip_pvalue(differences),
                "full_better_projects": sum(value > 1e-12 for value in differences),
                "one_shot_better_projects": sum(value < -1e-12 for value in differences),
                "ties": sum(abs(value) <= 1e-12 for value in differences),
                "project_count": len(case_ids),
            }
        )
    _holm_adjust(statistics)
    return summary, statistics


def _parsed_sensitivity(rows: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for method, method_rows in rows.items():
        parsed = [row for row in method_rows if bool(row["parsed_output"])]
        for metric, _ in CONTENT_METRICS:
            result.append(
                {
                    "method": method,
                    "method_ru": LABELS[method],
                    "metric": metric,
                    "parsed_attempts": len(parsed),
                    "mean": mean(_number(row.get(metric)) for row in parsed) if parsed else 0.0,
                }
            )
    return result


def _classify_attempt(row: dict[str, Any]) -> str:
    error = str(row.get("error_type") or "")
    if error == "LLMOutputTruncatedError":
        return "Ответ обрезан по лимиту"
    if error:
        return "Сетевая/транспортная ошибка"
    if _number(row.get("schema_validity")) < 1.0:
        return "Ошибка схемы данных"
    if _number(row.get("activity_structural_validity")) < 1.0:
        return "Некорректная структура Activity"
    if _number(row.get("trace_manifest_validity")) < 1.0:
        return "Ошибка сквозной трассировки"
    if _number(row.get("end_to_end_success")) < 1.0:
        return "Прочий E2E-провал"
    return "Полностью успешный запуск"


def _error_analysis(rows: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    categories = (
        "Полностью успешный запуск",
        "Ответ обрезан по лимиту",
        "Сетевая/транспортная ошибка",
        "Ошибка схемы данных",
        "Некорректная структура Activity",
        "Ошибка сквозной трассировки",
        "Прочий E2E-провал",
    )
    output: list[dict[str, Any]] = []
    for method, method_rows in rows.items():
        counts = Counter(_classify_attempt(row) for row in method_rows)
        for category in categories:
            output.append(
                {
                    "method": method,
                    "method_ru": LABELS[method],
                    "category": category,
                    "count": counts[category],
                    "share": counts[category] / len(method_rows),
                    "attempt_count": len(method_rows),
                }
            )
    return output


def _operations(rows: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for method, method_rows in rows.items():
        latency = [_number(row.get("latency_ms")) / 1000 for row in method_rows]
        tokens = [_number(row.get("total_tokens")) for row in method_rows]
        costs = [_number(row.get("estimated_cost_usd")) for row in method_rows]
        calls = [_number(row.get("llm_calls")) for row in method_rows]
        output.append(
            {
                "method": method,
                "method_ru": LABELS[method],
                "median_latency_seconds": median(latency),
                "p95_latency_seconds": _percentile(latency, 0.95),
                "mean_tokens": mean(tokens),
                "mean_llm_calls": mean(calls),
                "total_cost_usd": sum(costs),
                "mean_cost_usd": mean(costs),
            }
        )
    return output


def _dataset_passport() -> list[dict[str, Any]]:
    cases = json.loads(
        (ROOT / "benchmark" / "v1_0_synthetic" / "cases.json").read_text(encoding="utf-8")
    )
    dev = [case for case in cases if case["split"] == "development"]
    output: list[dict[str, Any]] = []
    for complexity in ("simple", "medium", "hard"):
        selected = [case for case in dev if case["complexity"] == complexity]
        fr_counts = [len(case["specification_req"]["functional_requirements"]) for case in selected]
        uc_counts = [len(case["gold"]["use_case_slots"]) for case in selected]
        milestone_counts = [
            sum(len(uc["required_milestones"]) for uc in case["gold"]["use_case_slots"])
            for case in selected
        ]
        branch_counts = [
            sum(len(uc["required_branches"]) for uc in case["gold"]["use_case_slots"])
            for case in selected
        ]
        trace_counts = [
            sum(len(uc["source_fr_ids"]) for uc in case["gold"]["use_case_slots"])
            for case in selected
        ]
        output.append(
            {
                "complexity": complexity,
                "projects": len(selected),
                "fr_min": min(fr_counts),
                "fr_max": max(fr_counts),
                "gold_uc_median": median(uc_counts),
                "gold_milestones": sum(milestone_counts),
                "gold_branches": sum(branch_counts),
                "gold_trace_links": sum(trace_counts),
            }
        )
    return output


def _size_preflight() -> list[dict[str, Any]]:
    paths = (
        ROOT
        / "artifacts"
        / "size_scaling_runs"
        / "size-scaling-gold-preflight-scale001-2026-09-15"
        / "results.csv",
        ROOT
        / "artifacts"
        / "size_scaling_runs"
        / "size-scaling-gold-preflight-mixed-2026-09-15"
        / "results.csv",
    )
    result: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists():
            continue
        for row in csv.DictReader(path.open(encoding="utf-8")):
            error = str(row.get("error_type") or "")
            if error == "LLMOutputTruncatedError":
                outcome = "ответ обрезан"
            elif error:
                outcome = "транспортная ошибка"
            elif _number(row.get("end_to_end_success")) == 1.0:
                outcome = "E2E успешно"
            elif _number(row.get("activity_structural_validity")) == 1.0:
                outcome = "артефакты созданы; финальная проверка не пройдена"
            else:
                outcome = "формальный провал"
            result.append(
                {
                    "case_id": row["case_id"],
                    "size_group": row["size_group"],
                    "fr_count": int(row["fr_count"]),
                    "condition": row["condition"],
                    "e2e_success": _number(row.get("end_to_end_success")),
                    "milestone_f1": _number(row.get("milestone_f1")),
                    "branch_f1": _number(row.get("branch_f1")),
                    "trace_f1": _number(row.get("trace_f1")),
                    "fr_coverage": _number(row.get("fr_coverage")),
                    "activity_element_trace_coverage": _number(
                        row.get("activity_element_trace_coverage")
                    ),
                    "llm_calls": int(_number(row.get("llm_calls"))),
                    "total_tokens": int(_number(row.get("total_tokens"))),
                    "latency_seconds": _number(row.get("latency_ms")) / 1000,
                    "estimated_cost_usd": _number(row.get("estimated_cost_usd")),
                    "outcome": outcome,
                }
            )
    return sorted(result, key=lambda item: (item["fr_count"], item["condition"]))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _lookup(summary: list[dict[str, Any]], method: str, metric: str) -> dict[str, Any]:
    return next(row for row in summary if row["method"] == method and row["metric"] == metric)


def _bar_chart_svg(
    summary: list[dict[str, Any]],
    metrics: tuple[tuple[str, str], ...],
    *,
    title: str,
    subtitle: str,
    filename: str,
    takeaway: str,
) -> None:
    width, height = 1600, 900
    left, right, top, bottom = 110, 1540, 190, 680
    plot_height = bottom - top
    group_width = (right - left) / len(metrics)
    bar_width = min(90, group_width * 0.25)
    chunks = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        "<style>text{font-family:Arial,sans-serif;fill:#182536}.title{font-size:38px;font-weight:700}.sub{font-size:19px;fill:#5c6877}.axis{font-size:15px;fill:#687586}.label{font-size:17px;font-weight:700}.value{font-size:17px;font-weight:700}.legend{font-size:18px;font-weight:700}.take{font-size:23px;font-weight:700}.note{font-size:15px;fill:#687586}</style>",
        f'<text x="70" y="62" class="title">{html.escape(title)}</text>',
        f'<text x="70" y="98" class="sub">{html.escape(subtitle)}</text>',
    ]
    legend_x = 1030
    for index, method in enumerate(("ONE_SHOT", "FULL")):
        x = legend_x + index * 250
        chunks.extend(
            [
                f'<rect x="{x}" y="125" width="24" height="24" rx="4" fill="{COLORS[method]}"/>',
                f'<text x="{x + 36}" y="144" class="legend">{html.escape(LABELS[method])}</text>',
            ]
        )
    for tick in range(0, 11, 2):
        value = tick / 10
        y = bottom - value * plot_height
        chunks.extend(
            [
                f'<line x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" stroke="#e3e8ee"/>',
                f'<text x="{left - 18}" y="{y + 5:.1f}" text-anchor="end" class="axis">{value:.1f}</text>',
            ]
        )
    for metric_index, (metric, label) in enumerate(metrics):
        center = left + group_width * (metric_index + 0.5)
        for method_index, method in enumerate(("ONE_SHOT", "FULL")):
            row = _lookup(summary, method, metric)
            value = float(row["project_macro_mean"])
            low = float(row["ci_95_low"])
            high = float(row["ci_95_high"])
            x = center + (method_index - 0.5) * (bar_width + 18) - bar_width / 2
            y = bottom - value * plot_height
            bar_height = value * plot_height
            ci_low_y = bottom - low * plot_height
            ci_high_y = bottom - high * plot_height
            chunks.extend(
                [
                    f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" height="{bar_height:.1f}" rx="5" fill="{COLORS[method]}"/>',
                    f'<line x1="{x + bar_width / 2:.1f}" y1="{ci_high_y:.1f}" x2="{x + bar_width / 2:.1f}" y2="{ci_low_y:.1f}" stroke="#162536" stroke-width="2"/>',
                    f'<line x1="{x + bar_width / 2 - 8:.1f}" y1="{ci_high_y:.1f}" x2="{x + bar_width / 2 + 8:.1f}" y2="{ci_high_y:.1f}" stroke="#162536" stroke-width="2"/>',
                    f'<line x1="{x + bar_width / 2 - 8:.1f}" y1="{ci_low_y:.1f}" x2="{x + bar_width / 2 + 8:.1f}" y2="{ci_low_y:.1f}" stroke="#162536" stroke-width="2"/>',
                    f'<text x="{x + bar_width / 2:.1f}" y="{max(y - 14, 175):.1f}" text-anchor="middle" class="value">{value:.3f}</text>',
                ]
            )
        chunks.append(
            f'<text x="{center:.1f}" y="724" text-anchor="middle" class="label">{html.escape(label)}</text>'
        )
    chunks.extend(
        [
            '<line x1="70" y1="770" x2="1530" y2="770" stroke="#c9d2dc"/>',
            f'<text x="70" y="816" class="take">{html.escape(takeaway)}</text>',
            '<text x="70" y="854" class="note">Среднее по 20 проектам; три повтора усреднены внутри проекта; планки — кластерный bootstrap 95% CI. Технический провал остаётся в знаменателе и получает 0.</text>',
            "</svg>",
        ]
    )
    svg_path = OUTPUT_DIR / filename
    svg_path.write_text("".join(chunks), encoding="utf-8")
    png_path = svg_path.with_suffix(".png")
    subprocess.run(
        ["sips", "-s", "format", "png", str(svg_path), "--out", str(png_path)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _format_p(value: float) -> str:
    return "<0.0001" if value < 0.0001 else f"{value:.4f}"


def _markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def _build_document(
    summary: list[dict[str, Any]],
    statistics: list[dict[str, Any]],
    sensitivity: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    operations: list[dict[str, Any]],
    passport: list[dict[str, Any]],
    size_preflight: list[dict[str, Any]],
    metadata: dict[str, Any],
) -> str:
    def value(method: str, metric: str) -> float:
        return float(_lookup(summary, method, metric)["project_macro_mean"])

    def stat(metric: str) -> dict[str, Any]:
        return next(row for row in statistics if row["metric"] == metric)

    content_rows = []
    for metric, label in CONTENT_METRICS:
        item = stat(metric)
        content_rows.append(
            [
                label,
                f"{value('ONE_SHOT', metric):.3f}",
                f"{value('FULL', metric):.3f}",
                f"{item['full_minus_one_shot']:+.3f}",
                f"[{item['ci_95_low']:+.3f}; {item['ci_95_high']:+.3f}]",
                _format_p(float(item["holm_adjusted_p_value"])),
            ]
        )
    trace_rows = []
    for metric, label in TRACE_METRICS:
        item = stat(metric)
        trace_rows.append(
            [
                label,
                f"{value('ONE_SHOT', metric):.1%}",
                f"{value('FULL', metric):.1%}",
                f"{item['full_minus_one_shot']:+.1%}",
                f"[{item['ci_95_low']:+.1%}; {item['ci_95_high']:+.1%}]",
                _format_p(float(item["holm_adjusted_p_value"])),
            ]
        )
    error_rows = []
    for category in dict.fromkeys(row["category"] for row in errors):
        one = next(row for row in errors if row["method"] == "ONE_SHOT" and row["category"] == category)
        full = next(row for row in errors if row["method"] == "FULL" and row["category"] == category)
        error_rows.append(
            [
                category,
                f"{one['count']} / 60 ({one['share']:.1%})",
                f"{full['count']} / 60 ({full['share']:.1%})",
            ]
        )
    sensitivity_rows = []
    for metric, label in CONTENT_METRICS:
        one = next(row for row in sensitivity if row["method"] == "ONE_SHOT" and row["metric"] == metric)
        full = next(row for row in sensitivity if row["method"] == "FULL" and row["metric"] == metric)
        sensitivity_rows.append(
            [label, f"{one['mean']:.3f} (n={one['parsed_attempts']})", f"{full['mean']:.3f} (n={full['parsed_attempts']})"]
        )
    operation_rows = [
        [
            row["method_ru"],
            f"{row['median_latency_seconds']:.1f}",
            f"{row['p95_latency_seconds']:.1f}",
            f"{row['mean_tokens']:,.0f}",
            f"{row['mean_llm_calls']:.1f}",
            f"${row['mean_cost_usd']:.4f}",
        ]
        for row in operations
    ]
    passport_rows = [
        [
            row["complexity"],
            str(row["projects"]),
            f"{row['fr_min']}–{row['fr_max']}",
            f"{row['gold_uc_median']:.1f}",
            str(row["gold_milestones"]),
            str(row["gold_branches"]),
            str(row["gold_trace_links"]),
        ]
        for row in passport
    ]
    size_rows = [
        [
            row["case_id"],
            str(row["fr_count"]),
            "Один вызов" if row["condition"] == "B1_ONESHOT" else "Полный граф",
            row["outcome"],
            f"{row['trace_f1']:.3f}",
            f"{row['llm_calls']}",
            f"{row['latency_seconds']:.1f}",
        ]
        for row in size_preflight
    ]
    return f"""# Результаты объяснимого эксперимента: One-shot против полного графа

## Что считается доказательством

Основной эксперимент сравнивает два способа генерации на одной версии
`DeepSeek deepseek-flash`, одинаковых входах, одной конечной схеме и одном
evaluator:

1. **Один вызов LLM** — модель должна за один ответ вернуть полный комплект артефактов.
2. **Полный граф** — Use Case и Activity формируются специализированными этапами,
   проходят детерминированную проверку, критику и ограниченное исправление.

В основном анализе нет `B0_RULE`, интегрального `Semantic composite` и
LLM-судьи. Смысл сравнивается по отдельным F1 относительно эталонных слотов,
а техническая надёжность — отдельными проверяемыми долями.

## Паспорт DEV20

{_markdown_table(['Сложность', 'Проектов', 'ФТ', 'Медиана UC', 'Gold milestones', 'Gold branches', 'Gold FR→UC'], passport_rows)}

- 20 development-проектов, по 3 повтора на способ: 60 попыток для каждого метода;
- hidden-часть не открывалась;
- эталон — frozen author annotation candidate, а не подтверждённый консенсус
  двух независимых экспертов;
- ошибки формата не исключались: неуспешный task result остаётся в знаменателе.

## Таблица 1. Содержание Use Case

{_markdown_table(['Метрика', 'Один вызов', 'Полный граф', 'Разница', '95% CI разницы', 'Holm p'], content_rows)}

Главный содержательный выигрыш полного графа на этом наборе наблюдается по
`Branch F1`: {value('ONE_SHOT', 'branch_f1'):.3f} →
{value('FULL', 'branch_f1'):.3f}. Для `Milestone F1` разница мала:
{value('ONE_SHOT', 'milestone_f1'):.3f} → {value('FULL', 'milestone_f1'):.3f};
нельзя утверждать, что граф улучшает каждую смысловую метрику.

![Сравнение содержания](../../artifacts/explainable_experiment_results_2026-09-15/dev20_content_f1.png)

## Таблица 2. Трассировка, структура и полный запуск

{_markdown_table(['Метрика', 'Один вызов', 'Полный граф', 'Разница', '95% CI разницы', 'Holm p'], trace_rows)}

`FR→Activity coverage` рассчитана отдельно: требование считается дошедшим до
Activity, если существует цепочка `FR → ScenarioStep → ActivityNode/Edge`.
Она не подменяется метрикой доли подписанных элементов диаграммы.

Полный граф завершил и прошёл все обязательные проверки в 60 из 60 попыток;
one-shot — в 2 из 60. Это доказательство технической надёжности, а не
автоматически доказательство идеальной бизнес-семантики.

![Трассировка и надёжность](../../artifacts/explainable_experiment_results_2026-09-15/dev20_trace_reliability.png)

## Таблица 3. Почему one-shot не прошёл E2E

{_markdown_table(['Исход попытки', 'Один вызов LLM', 'Полный граф'], error_rows)}

Классы в таблице взаимоисключающие. Сначала учитывается техническая ошибка,
затем ошибка схемы, структуры Activity, трассировки и только потом прочий E2E.
Так один запуск не завышает сразу несколько строк.

## Проверка чувствительности: только разобранные ответы

{_markdown_table(['Метрика', 'Один вызов', 'Полный граф'], sensitivity_rows)}

Эта таблица нужна, чтобы отделить две причины результата. Если смотреть только
на 51 читаемый one-shot-ответ, `Actor/UC/Trace F1` уже высоки. Поэтому основной
эффект графа — гарантированно довести полный комплект до схемы, структуры и
трассировки; содержательный выигрыш наиболее заметен по ветвлениям.

## Операционные показатели — резервный слайд

{_markdown_table(['Способ', 'Медиана, с', 'p95, с', 'Токенов/проект', 'Вызовов/проект', 'Стоимость/проект'], operation_rows)}

Операционные показатели не смешиваются с качеством. Они показывают цену
надёжности: полный граф требует больше вызовов и токенов.

## Предварительный прогон набора руководителя по размеру

{_markdown_table(['Проект', 'ФТ', 'Способ', 'Исход', 'Trace F1', 'Вызовов', 'Время, с'], size_rows)}

Это диагностический preflight по одному проекту из каждой размерной группы, а
не финальный эксперимент по 20 проектам. На 48 и 74 ФТ one-shot упёрся в лимит
длины ответа. Полный граф сформировал структурированные артефакты, но финальный
gate выявил несогласованные ссылки и структурные дефекты. Следовательно,
пакетная декомпозиция масштабируется лучше монолитного ответа по объёму, но
текущая версия ещё не доказала требуемую E2E-надёжность на больших входах.

Научно корректный следующий шаг: две независимые проверки Gold для этих 20
проектов, freeze, исправление общих классов контрактных ошибок на development,
затем одинаковые повторные запуски One-shot и Full по четырём группам.

## Что вынести на основные слайды

1. График `dev20_content_f1.png` — четыре раздельные F1 без общего балла.
2. График `dev20_trace_reliability.png` — трассировка, структура и E2E.
3. Короткий анализ ошибок: 9 обрезанных one-shot-ответов, 49 структурных
   провалов среди остальных и 60/60 успешных полных запусков.
4. Один честный вывод: **полный граф резко повышает техническую принимаемость и
   сохранение ветвлений, но стоит дороже; улучшение каждого смыслового аспекта
   на DEV20 не подтверждено**.

## Воспроизводимость

- benchmark SHA-256: `{metadata['benchmark_cases_sha256']}`;
- one-shot results SHA-256: `{metadata['source_sha256']['ONE_SHOT']}`;
- full results SHA-256: `{metadata['source_sha256']['FULL']}`;
- bootstrap: {metadata['bootstrap_resamples']} выборок, seed
  `{metadata['bootstrap_seed']}`;
- скрипт: `scripts/build_explainable_experiment_results.py`;
- машинные таблицы: `artifacts/explainable_experiment_results_2026-09-15/`.
"""


def main() -> None:
    rows, metadata = _load_rows()
    summary, statistics = _metric_summary(rows)
    sensitivity = _parsed_sensitivity(rows)
    errors = _error_analysis(rows)
    operations = _operations(rows)
    passport = _dataset_passport()
    size_preflight = _size_preflight()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_csv(OUTPUT_DIR / "dev20_metric_summary.csv", summary)
    _write_csv(OUTPUT_DIR / "dev20_paired_statistics.csv", statistics)
    _write_csv(OUTPUT_DIR / "dev20_parsed_output_sensitivity.csv", sensitivity)
    _write_csv(OUTPUT_DIR / "dev20_error_analysis.csv", errors)
    _write_csv(OUTPUT_DIR / "dev20_operational_metrics.csv", operations)
    _write_csv(OUTPUT_DIR / "dev20_dataset_passport.csv", passport)
    _write_csv(OUTPUT_DIR / "size_benchmark_preflight.csv", size_preflight)

    machine_result = {
        "scope": "frozen DEV20; hidden unopened",
        "methods": LABELS,
        "metadata": metadata,
        "metric_summary": summary,
        "paired_statistics": statistics,
        "parsed_output_sensitivity": sensitivity,
        "error_analysis": errors,
        "operational_metrics": operations,
        "dataset_passport": passport,
        "size_benchmark_preflight": size_preflight,
    }
    (OUTPUT_DIR / "results.json").write_text(
        json.dumps(machine_result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    _bar_chart_svg(
        summary,
        CONTENT_METRICS,
        title="Качество Use Case: один вызов LLM и полный граф",
        subtitle="Frozen DEV20 · 20 проектов × 3 повтора · отдельные F1 относительно эталонной разметки",
        filename="dev20_content_f1.svg",
        takeaway="Полный граф заметнее всего сохраняет границы процессов и альтернативные ветви.",
    )
    _bar_chart_svg(
        summary,
        TRACE_METRICS,
        title="Трассировка и надёжность полного результата",
        subtitle="Все показатели показаны отдельно; интегральный смысловой балл и LLM-судья не используются",
        filename="dev20_trace_reliability.svg",
        takeaway="Главный эффект полного графа — 60/60 E2E против 2/60 и полная трассировка Activity.",
    )
    for filename in (
        "dev20_content_f1.svg",
        "dev20_content_f1.png",
        "dev20_trace_reliability.svg",
        "dev20_trace_reliability.png",
    ):
        source = OUTPUT_DIR / filename
        if source.exists():
            shutil.copy2(source, OBSIDIAN_ASSET_DIR / f"41_{filename}")

    document = _build_document(
        summary,
        statistics,
        sensitivity,
        errors,
        operations,
        passport,
        size_preflight,
        metadata,
    )
    DOC_PATH.write_text(document, encoding="utf-8")
    (OUTPUT_DIR / "ANALYSIS_RU.md").write_text(document, encoding="utf-8")
    print(json.dumps(machine_result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
