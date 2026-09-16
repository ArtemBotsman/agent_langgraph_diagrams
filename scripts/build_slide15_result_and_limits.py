#!/usr/bin/env python3
"""Build the complete 16:9 result-and-limitations slide."""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "artifacts/final_experiment_evidence_2026-09-16/size_group_summary_ci95.csv"
OUTPUT_DIR = ROOT / "artifacts/presentation_figures_2026-09-16"
PNG_PATH = OUTPUT_DIR / "slide15_result_and_limits_16x9.png"
SVG_PATH = OUTPUT_DIR / "slide15_result_and_limits_16x9.svg"

GROUP_ORDER = ["G1_SMALL", "G2_GROWING", "G3_MEDIUM", "G4_LARGE"]
GROUP_LABELS = ["6–10 ФТ", "12–19 ФТ", "24–48 ФТ", "54–74 ФТ"]
CONDITIONS = ["B1_ONESHOT", "FULL"]
COLORS = {
    "B1_ONESHOT": "#1677C8",
    "FULL": "#F06400",
    "TEXT": "#111827",
    "MUTED": "#667085",
    "GRID": "#E5E7EB",
    "RED": "#C83E3E",
}


def load_rows() -> dict[tuple[str, str], dict[str, float]]:
    rows: dict[tuple[str, str], dict[str, float]] = {}
    with SOURCE.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            rows[(row["size_group"], row["condition"])] = {
                "rate": float(row["e2e_rate"]),
                "passes": float(row["e2e_passes"]),
                "attempted": float(row["projects_attempted"]),
            }
    return rows


def draw_e2e_chart(ax: plt.Axes, rows: dict[tuple[str, str], dict[str, float]]) -> None:
    x = np.arange(len(GROUP_ORDER), dtype=float)
    width = 0.34
    labels = {"B1_ONESHOT": "Один вызов LLM", "FULL": "Полный граф"}
    offsets = {"B1_ONESHOT": -width / 2, "FULL": width / 2}

    for condition in CONDITIONS:
        rates = [rows[(group, condition)]["rate"] * 100 for group in GROUP_ORDER]
        bars = ax.bar(
            x + offsets[condition],
            rates,
            width=width,
            color=COLORS[condition],
            label=labels[condition],
            zorder=3,
        )
        for bar, group in zip(bars, GROUP_ORDER, strict=True):
            passes = int(rows[(group, condition)]["passes"])
            attempted = int(rows[(group, condition)]["attempted"])
            height = bar.get_height()
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                height + 2.2,
                f"{passes}/{attempted}",
                ha="center",
                va="bottom",
                fontsize=11,
                fontweight="bold",
                color=COLORS[condition],
            )

    ax.set_xticks(x, GROUP_LABELS)
    ax.set_ylim(0, 112)
    ax.set_yticks(np.arange(0, 101, 20))
    ax.set_yticklabels([f"{value}%" for value in np.arange(0, 101, 20)])
    ax.set_ylabel("E2E-принимаемость проектов", fontsize=11)
    ax.set_xlabel("Размер проекта по числу функциональных требований", fontsize=11)
    ax.tick_params(axis="x", labelsize=10.5)
    ax.tick_params(axis="y", labelsize=9.5)
    ax.grid(axis="y", color=COLORS["GRID"], linewidth=0.9, zorder=0)
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
    draw_e2e_chart(ax, rows)

    fig.text(
        0.045,
        0.93,
        "Результат: проверяемый этап устойчивее к росту входа",
        fontsize=25,
        fontweight="bold",
        color=COLORS["TEXT"],
        ha="left",
    )
    fig.text(
        0.047,
        0.885,
        "20 проектов руководителя · 4 группы · 6–74 ФТ · DeepSeek deepseek-flash",
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

    fig.text(
        0.75,
        0.82,
        "Полученный результат",
        fontsize=14,
        fontweight="bold",
        color=COLORS["TEXT"],
    )
    fig.text(0.75, 0.755, "19/20", fontsize=27, fontweight="bold", color=COLORS["FULL"])
    fig.text(0.84, 0.762, "FULL E2E", fontsize=12, fontweight="bold", color=COLORS["TEXT"])
    fig.text(0.75, 0.71, "против 9/20 у одного вызова", fontsize=10.5, color=COLORS["MUTED"])

    fig.text(0.75, 0.64, "DEV20 × 3", fontsize=11.5, fontweight="bold", color=COLORS["MUTED"])
    fig.text(0.75, 0.595, "60/60 E2E", fontsize=20, fontweight="bold", color=COLORS["FULL"])
    fig.text(0.75, 0.555, "Trace F1 = 96,3%", fontsize=12, fontweight="bold", color=COLORS["TEXT"])

    fig.text(
        0.75,
        0.485,
        "Итоговый комплект",
        fontsize=12.5,
        fontweight="bold",
        color=COLORS["TEXT"],
    )
    fig.text(
        0.75,
        0.445,
        "ФТ/НФТ → Use Cases → Activity\n→ Mermaid → TraceManifest → отчёт",
        fontsize=10.5,
        color=COLORS["TEXT"],
        linespacing=1.5,
    )

    fig.text(0.75, 0.34, "Ограничения", fontsize=13.5, fontweight="bold", color=COLORS["TEXT"])
    limitations = [
        "Gold-кандидат ожидает проверки 2 экспертами",
        "size benchmark: 1 запуск на проект",
        "SCALE-018: контролируемое отклонение",
        "hidden-набор не использован",
    ]
    y_pos = 0.295
    for item in limitations:
        fig.text(0.75, y_pos, "•", fontsize=12, color=COLORS["RED"], fontweight="bold")
        fig.text(0.765, y_pos, item, fontsize=9.5, color=COLORS["TEXT"])
        y_pos -= 0.037

    fig.text(
        0.05,
        0.115,
        "Вывод: при росте входа прямой вызов перестаёт проходить E2E, "
        "а полный граф сохраняет 19/20 принимаемых комплектов.",
        fontsize=13.5,
        fontweight="bold",
        color=COLORS["TEXT"],
        ha="left",
    )
    fig.text(
        0.05,
        0.065,
        "Парный эффект FULL по E2E: +50 п.п.; 95% ДИ [+30; +70]; "
        "точный двусторонний p = 0,001953. Смысловые выводы предварительны "
        "до экспертной проверки Gold.",
        fontsize=9.5,
        color=COLORS["MUTED"],
        ha="left",
    )

    fig.savefig(PNG_PATH, facecolor="white")
    fig.savefig(SVG_PATH, facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    build()
