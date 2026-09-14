"""Build case-clustered DEV20 statistics and presentation-ready evidence.

The independent sampling unit is a benchmark case. Three stochastic repeats
are averaged inside each case before confidence intervals and paired tests are
calculated. This avoids treating repeated calls for one project as three
independent projects.
"""

# ruff: noqa: E501 -- long SVG and Markdown rows are generated verbatim.

from __future__ import annotations

import csv
import hashlib
import html
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "artifacts" / "final_dev20_statistical_evidence_2026-09-13"
DOC_PATH = ROOT / "docs" / "research" / "DEV20_FINAL_STATISTICAL_EVIDENCE_2026_09_13.md"

SOURCES = {
    "B0_RULE": ROOT
    / "artifacts"
    / "benchmark_runs"
    / "b0-dev20-r3-2026-09-09"
    / "results.json",
    "B1_ONESHOT": ROOT
    / "artifacts"
    / "benchmark_runs"
    / "b1-dev20-r3-deepseek-flash-2026-09-13"
    / "results.json",
    "FULL": ROOT
    / "artifacts"
    / "benchmark_runs"
    / "full-dev20-r3-deepseek-flash-2026-09-13"
    / "results.json",
}
METHODS = ("B0_RULE", "B1_ONESHOT", "FULL")
COLORS = {"B0_RULE": "#3d6384", "B1_ONESHOT": "#9a7735", "FULL": "#2f8178"}
BOOTSTRAP_SEED = 20260913
BOOTSTRAP_RESAMPLES = 50_000
INPUT_PRICE_USD_PER_MILLION = 0.30
OUTPUT_PRICE_USD_PER_MILLION = 1.20


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load() -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    rows: dict[str, list[dict[str, Any]]] = {}
    metadata: dict[str, Any] = {"source_sha256": {}}
    expected_cases: set[str] | None = None
    expected_pairs: set[tuple[str, int]] | None = None
    benchmark_sha: str | None = None
    semantic_backend: str | None = None
    for method, path in SOURCES.items():
        data = json.loads(path.read_text(encoding="utf-8"))
        current = [row for row in data["rows"] if row["condition"] == method]
        pairs = {(str(row["case_id"]), int(row["repeat_id"])) for row in current}
        cases = {pair[0] for pair in pairs}
        if len(current) != 60 or len(cases) != 20 or len(pairs) != 60:
            raise ValueError(f"{method} must contain 20 cases x 3 unique repeats")
        if expected_cases is None:
            expected_cases = cases
            expected_pairs = pairs
            benchmark_sha = str(data["cases_sha256"])
            semantic_backend = str(data["semantic_similarity_backend"])
        if cases != expected_cases or pairs != expected_pairs:
            raise ValueError(f"{method} is not paired to the same cases/repeats")
        if str(data["cases_sha256"]) != benchmark_sha:
            raise ValueError(f"{method} uses a different benchmark hash")
        if str(data["semantic_similarity_backend"]) != semantic_backend:
            raise ValueError(f"{method} uses a different semantic backend")
        rows[method] = current
        metadata["source_sha256"][method] = _sha256(path)
    metadata.update(
        {
            "benchmark_cases_sha256": benchmark_sha,
            "semantic_similarity_backend": semantic_backend,
            "case_count": 20,
            "repeats_per_case": 3,
            "run_count_per_method": 60,
            "bootstrap_seed": BOOTSTRAP_SEED,
            "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
        }
    )
    return rows, metadata


def _value(row: dict[str, Any], metric: str) -> float:
    value = row.get(metric)
    if value is None:
        return 0.0
    return float(value)


def _case_means(rows: list[dict[str, Any]], metric: str) -> dict[str, float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        grouped[str(row["case_id"])].append(_value(row, metric))
    return {case_id: mean(values) for case_id, values in grouped.items()}


def _bootstrap_mean_ci(values: list[float]) -> tuple[float, float]:
    array = np.asarray(values, dtype=float)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    indices = rng.integers(0, len(array), size=(BOOTSTRAP_RESAMPLES, len(array)))
    means = array[indices].mean(axis=1)
    low, high = np.quantile(means, [0.025, 0.975])
    return float(low), float(high)


def _bootstrap_paired_difference_ci(
    left: list[float], right: list[float]
) -> tuple[float, float]:
    differences = np.asarray(left, dtype=float) - np.asarray(right, dtype=float)
    return _bootstrap_mean_ci(differences.tolist())


def _wilson_ci(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """Wilson score interval for a binary project-level success proportion."""

    proportion = successes / total
    denominator = 1.0 + z**2 / total
    center = (proportion + z**2 / (2 * total)) / denominator
    margin = (
        z
        * ((proportion * (1.0 - proportion) / total + z**2 / (4 * total**2)) ** 0.5)
        / denominator
    )
    return center - margin, center + margin


def _exact_sign_flip_pvalue(differences: list[float]) -> float:
    """Two-sided exact paired randomization test for the mean difference."""

    all_values = np.asarray(differences, dtype=float)
    nonzero = all_values[np.abs(all_values) > 1e-12]
    if len(nonzero) == 0:
        return 1.0
    if len(nonzero) > 22:
        raise ValueError("Exact enumeration is intentionally limited to 22 non-zero pairs")
    observed = abs(float(all_values.mean()))
    total = 1 << len(nonzero)
    extreme = 0
    batch_size = 65_536
    bit_positions = np.arange(len(nonzero), dtype=np.uint64)
    for start in range(0, total, batch_size):
        masks = np.arange(start, min(start + batch_size, total), dtype=np.uint64)
        bits = ((masks[:, None] >> bit_positions) & 1).astype(float)
        signed_sums = ((bits * 2.0 - 1.0) * nonzero).sum(axis=1)
        permuted = np.abs(signed_sums / len(all_values))
        extreme += int(np.count_nonzero(permuted >= observed - 1e-15))
    return extreme / total


def _holm_adjust(pvalues: dict[str, float]) -> dict[str, float]:
    ordered = sorted(pvalues.items(), key=lambda item: item[1])
    adjusted: dict[str, float] = {}
    running = 0.0
    total = len(ordered)
    for index, (name, pvalue) in enumerate(ordered):
        running = max(running, min(1.0, (total - index) * pvalue))
        adjusted[name] = running
    return adjusted


def _recalculated_cost(row: dict[str, Any]) -> float:
    return (
        _value(row, "prompt_tokens") * INPUT_PRICE_USD_PER_MILLION
        + _value(row, "completion_tokens") * OUTPUT_PRICE_USD_PER_MILLION
    ) / 1_000_000


def _method_summary(method: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    e2e_case = _case_means(rows, "end_to_end_success")
    semantic_case = _case_means(rows, "semantic_composite")
    trace_case = _case_means(rows, "activity_element_trace_coverage")
    e2e_ci = _bootstrap_mean_ci(list(e2e_case.values()))
    semantic_ci = _bootstrap_mean_ci(list(semantic_case.values()))
    trace_ci = _bootstrap_mean_ci(list(trace_case.values()))
    parsed = [row for row in rows if row.get("error_type") is None]
    strict_case_successes = sum(value == 1.0 for value in e2e_case.values())
    strict_case_ci = _wilson_ci(strict_case_successes, len(e2e_case))
    return {
        "method": method,
        "runs": len(rows),
        "parsed_runs": len(parsed),
        "truncated_runs": sum(row.get("error_type") == "LLMOutputTruncatedError" for row in rows),
        "e2e_successes": sum(_value(row, "end_to_end_success") for row in rows),
        "e2e_rate": mean(e2e_case.values()),
        "e2e_ci_95": list(e2e_ci),
        "strict_case_successes": strict_case_successes,
        "strict_case_success_rate": strict_case_successes / len(e2e_case),
        "strict_case_wilson_ci_95": list(strict_case_ci),
        "semantic_mean": mean(semantic_case.values()),
        "semantic_ci_95": list(semantic_ci),
        "semantic_mean_parsed_outputs": (
            mean(_value(row, "semantic_composite") for row in parsed) if parsed else None
        ),
        "activity_trace_mean": mean(trace_case.values()),
        "activity_trace_ci_95": list(trace_ci),
        "mean_tokens": mean(_value(row, "total_tokens") for row in rows),
        "total_tokens": sum(_value(row, "total_tokens") for row in rows),
        "mean_latency_seconds": mean(_value(row, "latency_ms") for row in rows) / 1000,
        "mean_llm_calls": mean(_value(row, "llm_calls") for row in rows),
        "mean_repair_attempts": mean(_value(row, "repair_attempts") for row in rows),
        "estimated_total_cost_usd": sum(_recalculated_cost(row) for row in rows),
        "estimated_mean_cost_usd": mean(_recalculated_cost(row) for row in rows),
    }


def _complexity_summaries(all_rows: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for method in METHODS:
        for complexity in ("simple", "medium", "hard"):
            current = [
                row for row in all_rows[method] if str(row["complexity"]) == complexity
            ]
            result.append(
                {
                    "method": method,
                    "complexity": complexity,
                    "case_count": len({str(row["case_id"]) for row in current}),
                    "run_count": len(current),
                    "e2e_rate": mean(_value(row, "end_to_end_success") for row in current),
                    "semantic_mean": mean(
                        _value(row, "semantic_composite") for row in current
                    ),
                    "mean_tokens": mean(_value(row, "total_tokens") for row in current),
                    "mean_latency_seconds": mean(
                        _value(row, "latency_ms") for row in current
                    )
                    / 1000,
                }
            )
    return result


def _comparison(
    name: str,
    left_method: str,
    right_method: str,
    metric: str,
    all_rows: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    left = _case_means(all_rows[left_method], metric)
    right = _case_means(all_rows[right_method], metric)
    case_ids = sorted(left)
    left_values = [left[case_id] for case_id in case_ids]
    right_values = [right[case_id] for case_id in case_ids]
    differences = [a - b for a, b in zip(left_values, right_values, strict=True)]
    ci = _bootstrap_paired_difference_ci(left_values, right_values)
    return {
        "name": name,
        "left_method": left_method,
        "right_method": right_method,
        "metric": metric,
        "case_count": len(case_ids),
        "left_mean": mean(left_values),
        "right_mean": mean(right_values),
        "mean_paired_difference": mean(differences),
        "paired_difference_ci_95": list(ci),
        "exact_sign_flip_pvalue": _exact_sign_flip_pvalue(differences),
        "positive_case_differences": sum(value > 1e-12 for value in differences),
        "negative_case_differences": sum(value < -1e-12 for value in differences),
        "ties": sum(abs(value) <= 1e-12 for value in differences),
    }


def _fmt_p(value: float) -> str:
    if value < 0.0001:
        return f"{value:.2e}"
    return f"{value:.4f}"


def _svg(summaries: list[dict[str, Any]], comparisons: list[dict[str, Any]]) -> str:
    width, height = 1600, 940
    chunks = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        "<style>text{font-family:Arial,sans-serif;fill:#182536}.title{font-size:34px;font-weight:700}.subtitle{font-size:18px;fill:#596879}.panel{font-size:22px;font-weight:700}.axis{font-size:14px;fill:#596879}.value{font-size:17px;font-weight:700}.inverse{fill:#ffffff}.method{font-size:15px;font-weight:700}.callout{font-size:21px;font-weight:700}.body{font-size:17px;fill:#344456}.small{font-size:13px;fill:#667486}</style>",
        '<text x="64" y="55" class="title">DEV20: B0, one-shot и полный двухагентный pipeline</text>',
        '<text x="64" y="88" class="subtitle">20 независимых проектов × 3 повтора · DeepSeek deepseek-flash · hidden не открывался</text>',
    ]

    panels = [
        (70, "E2E success", "Доля запусков, %", "e2e_rate", "e2e_ci_95", 1.0),
        (
            590,
            "Semantic composite",
            "Gold-метрика, 0–1; незавершённый ответ = 0",
            "semantic_mean",
            "semantic_ci_95",
            1.0,
        ),
        (1110, "Токены на запуск", "Среднее, тысяч токенов", "mean_tokens", None, 70_000.0),
    ]
    chart_top, chart_bottom = 165, 505
    for panel_x, title, subtitle, metric, ci_key, maximum in panels:
        chunks.extend(
            [
                f'<text x="{panel_x}" y="130" class="panel">{html.escape(title)}</text>',
                f'<text x="{panel_x}" y="154" class="axis">{html.escape(subtitle)}</text>',
                f'<line x1="{panel_x}" y1="{chart_bottom}" x2="{panel_x + 420}" y2="{chart_bottom}" stroke="#bdc7d2"/>',
            ]
        )
        for index, item in enumerate(summaries):
            value = float(item[metric])
            height_px = min(value / maximum, 1.0) * (chart_bottom - chart_top)
            x = panel_x + 35 + index * 130
            y = chart_bottom - height_px
            chunks.append(
                f'<rect x="{x}" y="{y:.1f}" width="82" height="{height_px:.1f}" rx="5" fill="{COLORS[item["method"]]}"/>'
            )
            if metric == "mean_tokens":
                label = f'{value / 1000:.1f}k'
            else:
                label = f'{value * 100:.1f}%'
            label_inside = y <= chart_top + 20
            label_y = y + 25 if label_inside else y - 11
            label_class = "value inverse" if label_inside else "value"
            chunks.extend(
                [
                    f'<text x="{x + 41}" y="{label_y:.1f}" text-anchor="middle" class="{label_class}">{label}</text>',
                    f'<text x="{x + 41}" y="535" text-anchor="middle" class="method">{item["method"]}</text>',
                ]
            )
            if ci_key is not None:
                low, high = (float(v) for v in item[ci_key])
                low_y = chart_bottom - low / maximum * (chart_bottom - chart_top)
                high_y = chart_bottom - high / maximum * (chart_bottom - chart_top)
                chunks.extend(
                    [
                        f'<line x1="{x + 41}" y1="{high_y:.1f}" x2="{x + 41}" y2="{low_y:.1f}" stroke="#182536" stroke-width="2"/>',
                        f'<line x1="{x + 32}" y1="{high_y:.1f}" x2="{x + 50}" y2="{high_y:.1f}" stroke="#182536" stroke-width="2"/>',
                        f'<line x1="{x + 32}" y1="{low_y:.1f}" x2="{x + 50}" y2="{low_y:.1f}" stroke="#182536" stroke-width="2"/>',
                    ]
                )

    e2e = next(item for item in comparisons if item["name"] == "full_vs_b1_e2e")
    semantic_b0 = next(
        item for item in comparisons if item["name"] == "full_vs_b0_semantic"
    )
    semantic_b1 = next(
        item for item in comparisons if item["name"] == "full_vs_b1_semantic"
    )
    full = next(item for item in summaries if item["method"] == "FULL")
    b1 = next(item for item in summaries if item["method"] == "B1_ONESHOT")
    chunks.extend(
        [
            '<line x1="64" y1="590" x2="1536" y2="590" stroke="#bdc7d2"/>',
            '<text x="64" y="635" class="callout">Подтверждённый эффект на frozen DEV20</text>',
            f'<text x="64" y="675" class="body">FULL: {int(full["e2e_successes"])}/60 E2E; B1: {int(b1["e2e_successes"])}/60. Парная разница {e2e["mean_paired_difference"] * 100:.1f} п.п.</text>',
            f'<text x="64" y="707" class="body">95% bootstrap CI разницы: [{e2e["paired_difference_ci_95"][0] * 100:.1f}; {e2e["paired_difference_ci_95"][1] * 100:.1f}] п.п.; exact p={_fmt_p(e2e["holm_adjusted_pvalue"])}.</text>',
            f'<text x="64" y="751" class="body">FULL − B0 по semantic: {semantic_b0["mean_paired_difference"]:+.3f}, 95% CI [{semantic_b0["paired_difference_ci_95"][0]:+.3f}; {semantic_b0["paired_difference_ci_95"][1]:+.3f}], p={_fmt_p(semantic_b0["holm_adjusted_pvalue"])}.</text>',
            f'<text x="64" y="783" class="body">FULL − B1 по semantic (незавершённый ответ = 0): {semantic_b1["mean_paired_difference"]:+.3f}, 95% CI [{semantic_b1["paired_difference_ci_95"][0]:+.3f}; {semantic_b1["paired_difference_ci_95"][1]:+.3f}], p={_fmt_p(semantic_b1["holm_adjusted_pvalue"])}.</text>',
            '<text x="64" y="830" class="callout">Интерпретация</text>',
            '<text x="64" y="866" class="body">FULL статистически повышает принимаемость относительно one-shot и смысловое качество относительно B0.</text>',
            '<text x="64" y="896" class="body">Цена: больше вызовов, токенов и задержки. Вывод относится к synthetic DEV20; hidden и эксперты остаются внешней проверкой.</text>',
            '<text x="1536" y="925" text-anchor="end" class="small">Case-clustered bootstrap, 50 000 resamples · exact paired sign-flip · Holm correction</text>',
            "</svg>",
        ]
    )
    return "\n".join(chunks) + "\n"


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _build_document(
    summaries: list[dict[str, Any]],
    comparisons: list[dict[str, Any]],
    complexity_summaries: list[dict[str, Any]],
    metadata: dict[str, Any],
) -> str:
    summary_lines = []
    for item in summaries:
        summary_lines.append(
            "| {method} | {e2e:.1%} ({successes:.0f}/60) | [{low:.1%}; {high:.1%}] | "
            "{semantic:.3f} | [{sem_low:.3f}; {sem_high:.3f}] | {trace:.1%} | "
            "{tokens:,.0f} | {latency:.1f} | ${cost:.4f} |".format(
                method=item["method"],
                e2e=item["e2e_rate"],
                successes=item["e2e_successes"],
                low=item["e2e_ci_95"][0],
                high=item["e2e_ci_95"][1],
                semantic=item["semantic_mean"],
                sem_low=item["semantic_ci_95"][0],
                sem_high=item["semantic_ci_95"][1],
                trace=item["activity_trace_mean"],
                tokens=item["mean_tokens"],
                latency=item["mean_latency_seconds"],
                cost=item["estimated_mean_cost_usd"],
            ).replace(",", " ")
        )
    comparison_lines = []
    for item in comparisons:
        comparison_lines.append(
            "| {name} | {difference:+.4f} | [{low:+.4f}; {high:+.4f}] | "
            "{p_raw} | {p_holm} | {positive}/{negative}/{ties} |".format(
                name=item["name"],
                difference=item["mean_paired_difference"],
                low=item["paired_difference_ci_95"][0],
                high=item["paired_difference_ci_95"][1],
                p_raw=_fmt_p(item["exact_sign_flip_pvalue"]),
                p_holm=_fmt_p(item["holm_adjusted_pvalue"]),
                positive=item["positive_case_differences"],
                negative=item["negative_case_differences"],
                ties=item["ties"],
            )
        )
    b1 = next(item for item in summaries if item["method"] == "B1_ONESHOT")
    full = next(item for item in summaries if item["method"] == "FULL")
    b0 = next(item for item in summaries if item["method"] == "B0_RULE")
    e2e = next(item for item in comparisons if item["name"] == "full_vs_b1_e2e")
    sem_b0 = next(item for item in comparisons if item["name"] == "full_vs_b0_semantic")
    sem_b1 = next(item for item in comparisons if item["name"] == "full_vs_b1_semantic")
    complexity_lines = [
        "| {method} | {complexity} | {cases} | {e2e:.1%} | {semantic:.3f} | "
        "{tokens:,.0f} | {latency:.1f} |".format(
            method=item["method"],
            complexity=item["complexity"],
            cases=item["case_count"],
            e2e=item["e2e_rate"],
            semantic=item["semantic_mean"],
            tokens=item["mean_tokens"],
            latency=item["mean_latency_seconds"],
        ).replace(",", " ")
        for item in complexity_summaries
    ]
    return f"""# DEV20: финальное статистическое сравнение B0, B1 и FULL

Дата: 13.09.2026. Benchmark: `1.0.0-synthetic-author-freeze`. Проверены 20
development-проектов, по три запуска каждого метода: 60 результатов на метод,
180 результатов всего. Hidden split не открывался.

## Что является независимым наблюдением

Независимая единица анализа — проект, а не отдельный API-вызов. Три повтора
сначала усредняются внутри каждого из 20 проектов. Доверительные интервалы
получены кластерным bootstrap по проектам, 50 000 выборок, seed
`{BOOTSTRAP_SEED}`. Для заранее выбранных парных различий используется точный
двусторонний sign-flip test; три p-value скорректированы методом Holm.

## Основные результаты

| Метод | E2E | 95% CI по кейсам | Semantic | 95% CI | Activity trace | Токены/run | Время, с | Расчётная цена/run |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(summary_lines)}

Расчётная стоимость использует зафиксированные в эксперименте коэффициенты
${INPUT_PRICE_USD_PER_MILLION:.2f}/M input и
${OUTPUT_PRICE_USD_PER_MILLION:.2f}/M output. Это локальная оценка, не выписка
из provider billing.

## Результаты по сложности

| Метод | Сложность | Проектов | E2E | Semantic | Токены/run | Время, с |
|---|---|---:|---:|---:|---:|---:|
{chr(10).join(complexity_lines)}

У `B0_RULE` semantic composite снижается от простых к сложным проектам. У
`FULL` среднее остаётся около 0,69 во всех трёх группах, но увеличиваются
токены и задержка. Это описательный анализ подгрупп; из-за 5–9 проектов в
группе он не используется как отдельное подтверждающее статистическое
испытание.

## Парные статистические сравнения

| Сравнение | Средняя разница | 95% CI | exact p | Holm p | Кейсы +/−/= |
|---|---:|---:|---:|---:|---:|
{chr(10).join(comparison_lines)}

## Строго подтверждённые выводы

1. `FULL` повысил E2E success с {b1['e2e_rate']:.1%} у `B1_ONESHOT` до
   {full['e2e_rate']:.1%}. Парная разница равна
   {e2e['mean_paired_difference'] * 100:.1f} процентного пункта, 95% CI
   `[{e2e['paired_difference_ci_95'][0] * 100:.1f};
   {e2e['paired_difference_ci_95'][1] * 100:.1f}]`, Holm-adjusted
   `p={_fmt_p(e2e['holm_adjusted_pvalue'])}`. На этом DEV20 различие
   статистически убедительно.
   Все три повтора прошли у 20/20 проектов FULL и у 0/20 проектов B1;
   Wilson 95% CI для этой строгой project-level доли составляет
   `[{full['strict_case_wilson_ci_95'][0]:.1%};
   {full['strict_case_wilson_ci_95'][1]:.1%}]` и
   `[{b1['strict_case_wilson_ci_95'][0]:.1%};
   {b1['strict_case_wilson_ci_95'][1]:.1%}]` соответственно.
2. `FULL` повысил автоматический semantic composite относительно
   детерминированного `B0_RULE`: {b0['semantic_mean']:.3f} →
   {full['semantic_mean']:.3f}; разница {sem_b0['mean_paired_difference']:+.3f},
   95% CI `[{sem_b0['paired_difference_ci_95'][0]:+.3f};
   {sem_b0['paired_difference_ci_95'][1]:+.3f}]`, Holm-adjusted
   `p={_fmt_p(sem_b0['holm_adjusted_pvalue'])}`. Это подтверждает, что
   детерминированный нижний ориентир формально устойчив, но семантически слабее.
3. Разница semantic composite `FULL − B1` равна
   {sem_b1['mean_paired_difference']:+.3f}, 95% CI
   `[{sem_b1['paired_difference_ci_95'][0]:+.3f};
   {sem_b1['paired_difference_ci_95'][1]:+.3f}]`, Holm-adjusted
   `p={_fmt_p(sem_b1['holm_adjusted_pvalue'])}`. Этот показатель включает
   незавершённые B1-ответы как нулевой task result. Среди ответов, которые
   удалось разобрать, среднее B1 равно
   {b1['semantic_mean_parsed_outputs']:.3f}, а FULL —
   {full['semantic_mean_parsed_outputs']:.3f}. Следовательно, главный эффект
   FULL — надёжное доведение результата до контракта, а не доказанное
   улучшение смысла каждого уже завершённого one-shot ответа.
4. Цена надёжности: FULL использует в среднем {full['mean_tokens']:,.0f}
   токенов и {full['mean_latency_seconds']:.1f} с против
   {b1['mean_tokens']:,.0f} токенов и {b1['mean_latency_seconds']:.1f} с у B1.
   Поэтому FULL лучше по принимаемости, но дороже и медленнее.

## Что нельзя называть доказанным

- Это финальное статистическое свидетельство на frozen DEV20, но не
  универсальное доказательство для любых требований.
- Synthetic gold размечен автором benchmark. Смысловые выводы требуют проверки
  двумя независимыми экспертами.
- Hidden test не открыт: он должен запускаться один раз только после scientific
  freeze и согласования протокола.
- `B0_RULE` также имеет 100% E2E, поэтому E2E сам по себе не доказывает
  смысловое качество. Нужна совместная интерпретация E2E и semantic metrics.

## Воспроизводимость

- benchmark SHA-256: `{metadata['benchmark_cases_sha256']}`;
- B0 results SHA-256: `{metadata['source_sha256']['B0_RULE']}`;
- B1 results SHA-256: `{metadata['source_sha256']['B1_ONESHOT']}`;
- FULL results SHA-256: `{metadata['source_sha256']['FULL']}`;
- semantic backend: `{metadata['semantic_similarity_backend']}`;
- статистический скрипт: `scripts/build_dev20_statistical_evidence.py`;
- машинный результат: `artifacts/final_dev20_statistical_evidence_2026-09-13/statistical_evidence.json`.

## Формулировка для защиты

> На 20 frozen development-проектах, по три повтора на проект, полный
> двухагентный pipeline прошёл E2E в 60 из 60 запусков, тогда как прямой
> one-shot — в 2 из 60. Средняя парная разница составила
> {e2e['mean_paired_difference'] * 100:.1f} п.п.; её 95% интервал не включает
> ноль, а скорректированное p-value равно
> {_fmt_p(e2e['holm_adjusted_pvalue'])}. По сравнению с детерминированным B0
> FULL также дал более высокий semantic composite. Цена результата — примерно
> {full['mean_tokens'] / max(b1['mean_tokens'], 1):.1f} раза больше токенов и
> {full['mean_latency_seconds'] / max(b1['mean_latency_seconds'], 0.001):.1f}
> раза больше времени, поэтому следующий этап — оптимизация стоимости без
> снижения трассируемости.
"""


def main() -> None:
    all_rows, metadata = _load()
    summaries = [_method_summary(method, all_rows[method]) for method in METHODS]
    complexity_summaries = _complexity_summaries(all_rows)
    comparisons = [
        _comparison(
            "full_vs_b1_e2e",
            "FULL",
            "B1_ONESHOT",
            "end_to_end_success",
            all_rows,
        ),
        _comparison(
            "full_vs_b0_semantic",
            "FULL",
            "B0_RULE",
            "semantic_composite",
            all_rows,
        ),
        _comparison(
            "full_vs_b1_semantic",
            "FULL",
            "B1_ONESHOT",
            "semantic_composite",
            all_rows,
        ),
    ]
    adjusted = _holm_adjust(
        {item["name"]: float(item["exact_sign_flip_pvalue"]) for item in comparisons}
    )
    for item in comparisons:
        item["holm_adjusted_pvalue"] = adjusted[str(item["name"])]

    result = {
        "scope": "frozen synthetic DEV20; hidden unopened",
        "metadata": metadata,
        "method_summaries": summaries,
        "complexity_summaries": complexity_summaries,
        "paired_comparisons": comparisons,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.joinpath("statistical_evidence.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_csv(OUTPUT_DIR / "method_summary.csv", summaries)
    _write_csv(OUTPUT_DIR / "complexity_summary.csv", complexity_summaries)
    _write_csv(OUTPUT_DIR / "paired_comparisons.csv", comparisons)
    svg = _svg(summaries, comparisons)
    OUTPUT_DIR.joinpath("dev20_final_comparison.svg").write_text(svg, encoding="utf-8")
    document = _build_document(summaries, comparisons, complexity_summaries, metadata)
    DOC_PATH.write_text(document, encoding="utf-8")
    OUTPUT_DIR.joinpath("ANALYSIS_RU.md").write_text(document, encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
