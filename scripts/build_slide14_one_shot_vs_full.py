#!/usr/bin/env python3
"""Build the presentation figure for DEV20 one-shot versus FULL results."""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "artifacts/explainable_experiment_results_2026-09-15/dev20_metric_summary.csv"
OUTPUT_DIR = ROOT / "artifacts/presentation_figures_2026-09-16"
PNG_PATH = OUTPUT_DIR / "slide14_one_shot_vs_full_dev20.png"
SVG_PATH = OUTPUT_DIR / "slide14_one_shot_vs_full_dev20.svg"

METRICS = [
    ("actor_f1", "Акторы"),
    ("uc_f1", "Use Cases"),
    ("milestone_f1", "Этапы\nсценария"),
    ("branch_f1", "Ветвления"),
    ("trace_f1", "Трассировка"),
    ("end_to_end_success", "E2E\nпринимаемость"),
]

COLORS = {
    "ONE_SHOT": "#1677C8",
    "FULL": "#F06400",
}


def load_rows() -> dict[tuple[str, str], dict[str, float]]:
    rows: dict[tuple[str, str], dict[str, float]] = {}
    with SOURCE.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            key = (row["method"], row["metric"])
            rows[key] = {
                "mean": float(row["project_macro_mean"]),
                "low": float(row["ci_95_low"]),
                "high": float(row["ci_95_high"]),
            }
    return rows


def add_value_labels(ax: plt.Axes, xs: np.ndarray, values: np.ndarray, color: str) -> None:
    for x, value in zip(xs, values, strict=True):
        ax.text(
            x,
            min(value + 0.048, 1.075),
            f"{value * 100:.1f}%".replace(".", ","),
            ha="center",
            va="bottom",
            color=color,
            fontsize=12,
            fontweight="bold",
        )


def build() -> None:
    rows = load_rows()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "axes.titleweight": "bold",
            "axes.labelsize": 13,
            "xtick.labelsize": 12,
            "ytick.labelsize": 11,
        }
    )

    fig, ax = plt.subplots(figsize=(16, 8.5), dpi=180)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

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
            markersize=11,
            markeredgecolor="white",
            markeredgewidth=1.4,
            color=COLORS[method],
            ecolor=COLORS[method],
            elinewidth=2.2,
            capsize=5,
            capthick=2.2,
            label=labels[method],
            zorder=3,
        )
        add_value_labels(ax, xs, values, COLORS[method])

    for index in range(len(METRICS)):
        left = rows[("ONE_SHOT", METRICS[index][0])]["mean"]
        right = rows[("FULL", METRICS[index][0])]["mean"]
        ax.plot(
            [x[index] + offsets["ONE_SHOT"], x[index] + offsets["FULL"]],
            [left, right],
            color="#C8CDD4",
            linewidth=1.8,
            zorder=1,
        )

    ax.set_title(
        "Полный граф повышает принимаемость и трассируемость",
        fontsize=23,
        pad=34,
    )
    ax.text(
        0.5,
        1.035,
        "DeepSeek deepseek-flash · DEV20 × 3 повтора · среднее по проектам и 95% bootstrap CI",
        transform=ax.transAxes,
        ha="center",
        va="bottom",
        fontsize=12.5,
        color="#5F6B7A",
    )

    ax.set_xticks(x, [label for _, label in METRICS])
    ax.set_ylabel("Значение метрики")
    ax.set_ylim(-0.02, 1.14)
    ax.set_yticks(np.linspace(0, 1, 6))
    ax.set_yticklabels([f"{int(value * 100)}%" for value in np.linspace(0, 1, 6)])
    ax.grid(axis="y", color="#E4E8ED", linewidth=1)
    ax.grid(axis="x", visible=False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#8A95A3")
    ax.spines["bottom"].set_color("#8A95A3")
    ax.legend(
        loc="upper left",
        bbox_to_anchor=(0.0, 1.005),
        ncol=2,
        frameon=False,
        fontsize=13,
        handletextpad=0.6,
        columnspacing=1.8,
    )

    fig.text(
        0.5,
        0.025,
        "E2E: +96,7 п.п.; 95% CI [+91,7; +100,0]; точный парный p < 0,001. "
        "Gold — авторский кандидат; hidden-набор не использован.",
        ha="center",
        va="bottom",
        fontsize=11.5,
        color="#5F6B7A",
    )

    fig.subplots_adjust(left=0.075, right=0.985, top=0.82, bottom=0.18)
    fig.savefig(PNG_PATH, bbox_inches="tight", facecolor="white")
    fig.savefig(SVG_PATH, bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    build()
