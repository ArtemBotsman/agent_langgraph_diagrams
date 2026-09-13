"""Build a presentation-ready Markdown and SVG report from scaling results."""

# ruff: noqa: E501 -- long SVG/Markdown literals stay readable as complete lines.

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from statistics import mean
from typing import Any


def _linear_fit(points: list[tuple[float, float]]) -> tuple[float, float, float]:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    x_mean = mean(xs)
    y_mean = mean(ys)
    denominator = sum((value - x_mean) ** 2 for value in xs)
    slope = sum((x - x_mean) * (y - y_mean) for x, y in points) / denominator
    intercept = y_mean - slope * x_mean
    residual = sum((y - (intercept + slope * x)) ** 2 for x, y in points)
    total = sum((y - y_mean) ** 2 for y in ys)
    return slope, intercept, 1.0 - residual / total


def _case_means(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["case_id"]), []).append(row)
    result = []
    for case_id, current in grouped.items():
        first = current[0]
        result.append(
            {
                "case_id": case_id,
                "fr_count": int(first["fr_count"]),
                "latency_ms": mean(float(item["latency_ms"]) for item in current),
            }
        )
    return sorted(result, key=lambda item: item["fr_count"])


def _svg(summary: list[dict[str, Any]], case_means: list[dict[str, Any]]) -> str:
    width, height = 1280, 720
    left_x, left_y, chart_w, chart_h = 90, 155, 480, 330
    right_x = 710
    max_fr = max(float(item["mean_fr_count"]) for item in summary)
    max_latency = max(float(item["latency_ms"]) for item in case_means)
    labels = ["5–10 ФТ", "11–20 ФТ", "21–50 ФТ", "51–75 ФТ"]
    colors = ["#2667a8", "#2f7d75", "#8a6d2f", "#874c62"]
    chunks = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="1280" height="720" fill="#ffffff"/>',
        "<style>text{font-family:Arial,sans-serif;fill:#172033}.title{font-size:28px;font-weight:700}.sub{font-size:15px;fill:#586174}.axis{font-size:13px;fill:#586174}.value{font-size:14px;font-weight:700}.call{font-size:20px;font-weight:700}</style>",
        '<text x="64" y="60" class="title">Benchmark масштабируемости: 20 проектов, 6–74 ФТ</text>',
        '<text x="64" y="92" class="sub">B0_RULE · 3 повтора на проект · 60/60 завершений · 0 LLM-токенов</text>',
        '<text x="90" y="132" class="value">Средний размер входа по группам</text>',
        '<text x="710" y="132" class="value">Время B0 в зависимости от числа ФТ</text>',
        f'<line x1="{left_x}" y1="{left_y + chart_h}" x2="{left_x + chart_w}" y2="{left_y + chart_h}" stroke="#cad1dc"/>',
        f'<line x1="{right_x}" y1="{left_y + chart_h}" x2="{right_x + chart_w}" y2="{left_y + chart_h}" stroke="#cad1dc"/>',
        f'<line x1="{right_x}" y1="{left_y}" x2="{right_x}" y2="{left_y + chart_h}" stroke="#cad1dc"/>',
    ]
    bar_width = 74
    gap = 42
    for index, item in enumerate(summary):
        fr_value = float(item["mean_fr_count"])
        nfr_value = float(item["mean_nfr_count"])
        bar_height = fr_value / max_fr * (chart_h - 35)
        x = left_x + 28 + index * (bar_width + gap)
        y = left_y + chart_h - bar_height
        chunks.extend(
            [
                f'<rect x="{x}" y="{y:.1f}" width="{bar_width}" height="{bar_height:.1f}" rx="4" fill="{colors[index]}"/>',
                f'<text x="{x + bar_width / 2:.1f}" y="{y - 10:.1f}" text-anchor="middle" class="value">{fr_value:.1f} ФТ</text>',
                f'<text x="{x + bar_width / 2:.1f}" y="{left_y + chart_h + 28}" text-anchor="middle" class="axis">{labels[index]}</text>',
                f'<text x="{x + bar_width / 2:.1f}" y="{left_y + chart_h + 49}" text-anchor="middle" class="axis">{nfr_value:.1f} НФТ</text>',
            ]
        )
    points = []
    for item in case_means:
        x = right_x + float(item["fr_count"]) / 75 * chart_w
        y = left_y + chart_h - float(item["latency_ms"]) / max_latency * (chart_h - 25)
        points.append((x, y))
    chunks.append(
        '<polyline points="'
        + " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
        + '" fill="none" stroke="#2667a8" stroke-width="3"/>'
    )
    chunks.extend(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="#2667a8"/>' for x, y in points)
    for tick in (0, 25, 50, 75):
        x = right_x + tick / 75 * chart_w
        chunks.append(
            f'<text x="{x:.1f}" y="{left_y + chart_h + 28}" text-anchor="middle" class="axis">{tick}</text>'
        )
    for tick in range(0, int(max_latency) + 2, 2):
        y = left_y + chart_h - tick / max_latency * (chart_h - 25)
        chunks.extend(
            [
                f'<line x1="{right_x - 5}" y1="{y:.1f}" x2="{right_x + chart_w}" y2="{y:.1f}" stroke="#edf0f5"/>',
                f'<text x="{right_x - 12}" y="{y + 5:.1f}" text-anchor="end" class="axis">{tick} мс</text>',
            ]
        )
    chunks.extend(
        [
            f'<text x="{right_x + chart_w / 2}" y="{left_y + chart_h + 54}" text-anchor="middle" class="axis">Количество функциональных требований</text>',
            '<line x1="64" y1="555" x2="1216" y2="555" stroke="#cad1dc"/>',
            '<text x="64" y="602" class="call">Структурно успешно, но семантически это только нижний ориентир</text>',
            '<text x="64" y="636" class="sub">B0 всегда создаёт один Use Case и одну линейную диаграмму, даже для 74 ФТ.</text>',
            '<text x="64" y="664" class="sub">Преимущество FULL над Claude one-shot проверяется отдельно на той же модели и с экспертной оценкой.</text>',
            '<text x="1216" y="696" text-anchor="end" class="axis">Источник: size_scaling_v1 · запуск 2026-09-13</text>',
            "</svg>",
        ]
    )
    return "\n".join(chunks) + "\n"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", type=Path)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    data = json.loads(args.results.read_text(encoding="utf-8"))
    summary = data["summary"]
    case_means = _case_means(data["rows"])
    latency_slope, _, latency_r2 = _linear_fit(
        [(float(item["fr_count"]), float(item["latency_ms"])) for item in case_means]
    )
    byte_slope, _, byte_r2 = _linear_fit(
        [(float(row["fr_count"]), float(row["output_bytes"])) for row in data["rows"]]
    )
    output_dir = args.results.parent
    (output_dir / "size_scaling_b0.svg").write_text(_svg(summary, case_means), encoding="utf-8")

    lines = [
        "# Анализ benchmark масштабируемости",
        "",
        "Дата запуска: 2026-09-13. Метод: `B0_RULE`. Выполнено 20 проектов × 3 повтора.",
        "",
        "| Группа | Проектов | Среднее ФТ | Среднее НФТ | E2E | Трассировка | Среднее время, мс | Средний размер результата, КБ |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in summary:
        lines.append(
            "| {label} | {cases} | {fr:.1f} | {nfr:.1f} | {e2e:.0%} | {trace:.0%} | {latency:.3f} | {size:.1f} |".format(
                label=html.escape(str(item["size_label_ru"])),
                cases=item["case_count"],
                fr=item["mean_fr_count"],
                nfr=item["mean_nfr_count"],
                e2e=item["e2e_success_rate"],
                trace=item["activity_element_trace_coverage"],
                latency=item["mean_latency_ms"],
                size=item["mean_output_bytes"] / 1024,
            )
        )
    lines.extend(
        [
            "",
            "## Проверенные выводы",
            "",
            "- Все 60 запусков завершились; schema validity, покрытие ФТ и activity trace coverage равны 100%.",
            "- Все три повтора каждого входа дали идентичный результат; LLM-вызовов и токенов не было.",
            f"- Время B0 росло примерно на {latency_slope:.3f} мс на одно ФТ; линейная модель описывает наблюдения с R²={latency_r2:.3f}.",
            f"- Размер результата рос примерно на {byte_slope / 1024:.2f} КБ на одно ФТ; R²={byte_r2:.3f}.",
            "",
            "## Главная интерпретация",
            "",
            "B0 показывает, что инфраструктура принимает все четыре размера и строит формально валидные артефакты. Но B0 всегда объединяет все требования в один Use Case и одну линейную диаграмму. Поэтому 100% трассировки здесь не означает высокое смысловое качество: для большого проекта получается одна диаграмма в среднем с 66 узлами.",
            "",
            "## Следующий эксперимент",
            "",
            "Сравнивать нужно `CLAUDE_ONESHOT` и `CLAUDE_FULL` на одном точном model ID. Основной показатель масштабирования — изменение E2E success, trace coverage, экспертной полноты и читаемости от G1 к G4. Токены, задержка и стоимость показываются как цена качества. До получения этих результатов нельзя утверждать, что FULL лучше на больших проектах.",
        ]
    )
    (output_dir / "ANALYSIS_RU.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(output_dir / "ANALYSIS_RU.md")


if __name__ == "__main__":
    main()
