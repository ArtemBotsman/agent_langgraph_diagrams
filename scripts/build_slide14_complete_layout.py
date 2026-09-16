#!/usr/bin/env python3
"""Build a complete 16:9 slide image for one-shot versus FULL results."""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "artifacts/explainable_experiment_results_2026-09-15/dev20_metric_summary.csv"
OUTPUT_DIR = ROOT / "artifacts/presentation_figures_2026-09-16"
PNG_PATH = OUTPUT_DIR / "slide14_complete_16x9.png"
SVG_PATH = OUTPUT_DIR / "slide14_complete_16x9.svg"

METRICS = [
    ("actor_f1", "Акторы"),
    ("uc_f1", "Use Cases"),
    ("milestone_f1", "Этапы"),
    ("branch_f1", "Ветвления"),
    ("trace_f1", "Трассировка"),
    ("end_to_end_success", "E2E"),
]

COLORS = {
    "ONE_SHOT": "#1677C8",
    "FULL": "#F06400",
    "TEXT": "#111827",
    "MUTED": "#667085",
    "GRID": "#E5E7EB",
}


def load_rows() -> dict[tuple[str, str], dict[str, float]]:
    rows: dict[tuple[str, str], dict[str, float]] = {}
    with SOURCE.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            rows[(row["method"], row["metric"])] = {
                "mean": float(row["project_macro_mean"]),
                "low": float(row["ci_95_low"]),
                "high": float(row["ci_95_high"]),
            }
    return rows


def draw_metric_chart(ax: plt.Axes, rows: dict[tuple[str, str], dict[str, float]]) -> None:
    x = np.arange(len(METRICS), dtype=float)
    offsets = {"ONE_SHOT": -0.13, "FULL": 0.13}
    labels = {"ONE_SHOT": "Один вызов LLM", "FULL": "Полный граф"}

    for method in ("ONE_SHOT", "FULL"):
        values = np.array([rows[(method, metric)]["mean"] for metric, _ in METRICS])
        lows = np.array([rows[(method, metric)]["low"] for metric, _ in METRICS])
        highs = np.array([rows[(method, metric)]["high"] for metric, _ in METRICS])
        xs = x + offsets[method]
        errors = np.vstack([values - lows, highs - values])
        ax.errorbar(
            xs,
            values,
            yerr=errors,
            fmt="o",
            markersize=9,
            markeredgecolor="white",
            markeredgewidth=1.2,
            color=COLORS[method],
            ecolor=COLORS[method],
            elinewidth=1.8,
            capsize=4,
            capthick=1.8,
            label=labels[method],
            zorder=3,
        )
        for x_value, value in zip(xs, values, strict=True):
            ax.text(
                x_value,
                min(value + 0.05, 1.075),
                f"{value * 100:.1f}%".replace(".", ","),
                ha="center",
                va="bottom",
                color=COLORS[method],
                fontsize=9.5,
                fontweight="bold",
            )

    for index, (metric, _) in enumerate(METRICS):
        left = rows[("ONE_SHOT", metric)]["mean"]
        right = rows[("FULL", metric)]["mean"]
        ax.plot(
            [x[index] + offsets["ONE_SHOT"], x[index] + offsets["FULL"]],
            [left, right],
            color="#CBD1D8",
            linewidth=1.5,
            zorder=1,
        )

    ax.set_xticks(x, [label for _, label in METRICS])
    ax.set_ylim(-0.02, 1.13)
    ax.set_yticks(np.linspace(0, 1, 6))
    ax.set_yticklabels([f"{int(value * 100)}%" for value in np.linspace(0, 1, 6)])
    ax.set_ylabel("Значение метрики", fontsize=11)
    ax.tick_params(axis="x", labelsize=9.5)
    ax.tick_params(axis="y", labelsize=9.5)
    ax.grid(axis="y", color=COLORS["GRID"], linewidth=0.9)
    ax.grid(axis="x", visible=False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#98A2B3")
    ax.spines["bottom"].set_color("#98A2B3")
    ax.legend(
        loc="upper left",
        bbox_to_anchor=(0.0, 1.02),
        ncol=2,
        frameon=False,
        fontsize=10.5,
        columnspacing=1.4,
    )


def build() -> None:
    rows = load_rows()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans"})

    fig = plt.figure(figsize=(16, 9), dpi=180, facecolor="white")
    ax = fig.add_axes([0.055, 0.23, 0.64, 0.62])
    draw_metric_chart(ax, rows)

    fig.text(
        0.045,
        0.93,
        "Полный граф повышает принимаемость и трассируемость",
        fontsize=25,
        fontweight="bold",
        color=COLORS["TEXT"],
        ha="left",
    )
    fig.text(
        0.047,
        0.885,
        "DeepSeek deepseek-flash · DEV20 × 3 повтора · одинаковые входы, "
        "схема результата и evaluator",
        fontsize=11.5,
        color=COLORS["MUTED"],
        ha="left",
    )

    fig.add_artist(
        plt.Line2D(
            [0.72, 0.72],
            [0.20, 0.84],
            transform=fig.transFigure,
            color="#D0D5DD",
            linewidth=1.2,
        )
    )

    fig.text(0.75, 0.82, "Ключевой результат", fontsize=14, fontweight="bold", color=COLORS["TEXT"])

    result_blocks = [
        (0.74, "E2E", "3,3% → 100%", "2/60 → 60/60 принятых результатов"),
        (0.61, "Trace F1", "83,5% → 96,3%", "правильность связей требований и UC"),
        (0.48, "Branch F1", "31,4% → 45,2%", "альтернативные и ошибочные пути"),
    ]
    for y_pos, metric, value, description in result_blocks:
        fig.text(0.75, y_pos, metric, fontsize=11.5, fontweight="bold", color=COLORS["MUTED"])
        fig.text(0.75, y_pos - 0.045, value, fontsize=22, fontweight="bold", color=COLORS["FULL"])
        fig.text(0.75, y_pos - 0.078, description, fontsize=9.3, color=COLORS["TEXT"])

    fig.text(0.75, 0.335, "Цена надёжности", fontsize=13, fontweight="bold", color=COLORS["TEXT"])
    fig.text(0.75, 0.29, "Время", fontsize=10, fontweight="bold", color=COLORS["MUTED"])
    fig.text(0.84, 0.29, "16,1 → 56,3 с", fontsize=11.5, fontweight="bold", color=COLORS["TEXT"])
    fig.text(0.75, 0.25, "Токены", fontsize=10, fontweight="bold", color=COLORS["MUTED"])
    fig.text(0.84, 0.25, "10,6 → 62,0 тыс.", fontsize=11.5, fontweight="bold", color=COLORS["TEXT"])
    fig.text(0.75, 0.21, "LLM-вызовы", fontsize=10, fontweight="bold", color=COLORS["MUTED"])
    fig.text(0.84, 0.21, "1,0 → 11,8", fontsize=11.5, fontweight="bold", color=COLORS["TEXT"])

    fig.text(
        0.05,
        0.115,
        "Вывод: граф не гарантирует рост каждой F1, но существенно повышает "
        "вероятность получить полный, проверяемый результат.",
        fontsize=13.5,
        fontweight="bold",
        color=COLORS["TEXT"],
        ha="left",
    )
    fig.text(
        0.05,
        0.065,
        "E2E: +96,7 п.п.; 95% ДИ [+91,7; +100,0]; точный парный p < 0,001. "
        "Gold — авторский кандидат; hidden-набор не использован.",
        fontsize=9.5,
        color=COLORS["MUTED"],
        ha="left",
    )

    fig.savefig(PNG_PATH, facecolor="white")
    fig.savefig(SVG_PATH, facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    build()
