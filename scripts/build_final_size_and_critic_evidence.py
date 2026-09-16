"""Build presentation-ready evidence for size scaling and critic contribution.

The script is offline: it reads preserved experiment results, calculates
project-clustered confidence intervals, and writes CSV/JSON/Markdown plus
high-resolution PNG and SVG figures.  Missing model outputs are never silently
converted into semantic F1=0; they are reported as technical failures.
"""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt  # type: ignore[import-not-found]
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "final_experiment_evidence_2026-09-16"
SIZE_RUNS = [
    ROOT / "artifacts" / "size_scaling_runs" / f"size-final-g{group}-b1-full-r1-2026-09-16"
    for group in range(1, 5)
]
FULL_DEV20 = (
    ROOT
    / "artifacts"
    / "benchmark_runs"
    / "full-dev20-r3-deepseek-flash-2026-09-13"
    / "results.json"
)
NO_CRITIC_DEV20 = (
    ROOT
    / "artifacts"
    / "benchmark_runs"
    / "no-critic-dev20-r3-deepseek-flash-2026-09-16-resumed"
    / "results.json"
)

GROUPS = ["G1_SMALL", "G2_GROWING", "G3_MEDIUM", "G4_LARGE"]
GROUP_LABELS = {
    "G1_SMALL": "6–10 ФТ",
    "G2_GROWING": "12–19 ФТ",
    "G3_MEDIUM": "24–48 ФТ",
    "G4_LARGE": "54–74 ФТ",
}
CONDITION_LABELS = {
    "B1_ONESHOT": "Один вызов LLM",
    "FULL": "Полный граф",
    "FULL_NO_CRITIC": "Без критика",
}
BLUE = "#0067B1"
ORANGE = "#F05A00"
GREEN = "#009E73"
RED = "#D62828"
PURPLE = "#7B2CBF"
GRAY = "#667085"


def _read_json(path: Path) -> dict[str, Any]:
    document: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise TypeError(f"Expected a JSON object in {path}")
    return document


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _finite(value: Any) -> float | None:
    if value is None or value == "":
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _semantic_available(row: dict[str, Any]) -> bool:
    return not row.get("error_type") and _finite(row.get("milestone_f1")) is not None


def _bootstrap_ci(
    values: Iterable[float], *, iterations: int = 50_000, seed: int = 20260916
) -> tuple[float, float, float]:
    array = np.asarray(list(values), dtype=float)
    if array.size == 0:
        return math.nan, math.nan, math.nan
    mean = float(array.mean())
    if array.size == 1:
        return mean, math.nan, math.nan
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, array.size, size=(iterations, array.size))
    means = array[indices].mean(axis=1)
    quantiles = np.asarray(np.quantile(means, [0.025, 0.975]), dtype=float).tolist()
    return mean, float(quantiles[0]), float(quantiles[1])


def _load_size_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run in SIZE_RUNS:
        document = _read_json(run / "results.json")
        for source in document["rows"]:
            row = dict(source)
            row["semantic_output_available"] = int(_semantic_available(row))
            row["technical_failure"] = int(bool(row.get("error_type")))
            row["source_results"] = str((run / "results.json").relative_to(ROOT))
            rows.append(row)
    return rows


def _size_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    metrics = ["actor_f1", "uc_f1", "milestone_f1", "branch_f1", "trace_f1"]
    for group in GROUPS:
        for condition in ("B1_ONESHOT", "FULL"):
            subset = [
                row for row in rows if row["size_group"] == group and row["condition"] == condition
            ]
            semantic = [row for row in subset if row["semantic_output_available"]]
            item: dict[str, Any] = {
                "size_group": group,
                "size_label": GROUP_LABELS[group],
                "condition": condition,
                "projects_attempted": len(subset),
                "semantic_outputs": len(semantic),
                "technical_failures": sum(int(row["technical_failure"]) for row in subset),
                "e2e_passes": sum(float(row.get("end_to_end_success") or 0) == 1 for row in subset),
                "e2e_rate": sum(float(row.get("end_to_end_success") or 0) == 1 for row in subset)
                / max(len(subset), 1),
                "mean_cost_usd": float(
                    np.mean([float(row.get("estimated_cost_usd") or 0) for row in subset])
                ),
                "mean_latency_seconds": float(
                    np.mean([float(row.get("latency_ms") or 0) / 1000 for row in subset])
                ),
            }
            for metric in metrics:
                values = [float(row[metric]) for row in semantic]
                mean, low, high = _bootstrap_ci(values)
                item[f"{metric}_mean"] = mean
                item[f"{metric}_ci95_low"] = low
                item[f"{metric}_ci95_high"] = high
            result.append(item)
    return result


def _paired_size_effects(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {(row["case_id"], row["condition"]): row for row in rows}
    result: list[dict[str, Any]] = []
    metrics = ["actor_f1", "uc_f1", "milestone_f1", "branch_f1", "trace_f1"]
    for metric in metrics:
        diffs = []
        for case_id in sorted({row["case_id"] for row in rows}):
            direct = by_key[(case_id, "B1_ONESHOT")]
            full = by_key[(case_id, "FULL")]
            if _semantic_available(direct) and _semantic_available(full):
                diffs.append(float(full[metric]) - float(direct[metric]))
        mean, low, high = _bootstrap_ci(diffs)
        result.append(
            {
                "metric": metric,
                "paired_projects": len(diffs),
                "mean_full_minus_one_shot": mean,
                "ci95_low": low,
                "ci95_high": high,
            }
        )
    e2e_diffs = []
    discordant_full = 0
    discordant_direct = 0
    for case_id in sorted({row["case_id"] for row in rows}):
        direct = by_key[(case_id, "B1_ONESHOT")]
        full = by_key[(case_id, "FULL")]
        direct_value = float(direct.get("end_to_end_success") or 0)
        full_value = float(full.get("end_to_end_success") or 0)
        e2e_diffs.append(full_value - direct_value)
        discordant_full += int(full_value == 1 and direct_value == 0)
        discordant_direct += int(full_value == 0 and direct_value == 1)
    mean, low, high = _bootstrap_ci(e2e_diffs)
    discordant = discordant_full + discordant_direct
    exact_p = (
        min(
            1.0,
            2
            * sum(
                math.comb(discordant, i)
                for i in range(0, min(discordant_full, discordant_direct) + 1)
            )
            / (2**discordant),
        )
        if discordant
        else 1.0
    )
    result.append(
        {
            "metric": "end_to_end_success",
            "paired_projects": len(e2e_diffs),
            "mean_full_minus_one_shot": mean,
            "ci95_low": low,
            "ci95_high": high,
            "discordant_full_only": discordant_full,
            "discordant_one_shot_only": discordant_direct,
            "mcnemar_exact_two_sided_p": exact_p,
        }
    )
    return result


def _style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Serif",
            "font.size": 11,
            "axes.titlesize": 13,
            "axes.labelsize": 11,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
        }
    )


def _save(fig: Any, stem: str) -> None:
    fig.savefig(OUTPUT / f"{stem}.png", dpi=300, bbox_inches="tight")
    fig.savefig(OUTPUT / f"{stem}.svg", bbox_inches="tight")
    plt.close(fig)


def _plot_size_quality(rows: list[dict[str, Any]], summary: list[dict[str, Any]]) -> None:
    rng = np.random.default_rng(20260916)
    metrics = [
        ("milestone_f1", "Milestone F1\nобязательные этапы"),
        ("branch_f1", "Branch F1\nальтернативные ветви"),
        ("trace_f1", "Trace F1\nсвязи ФТ → Use Case"),
    ]
    colors = {"B1_ONESHOT": BLUE, "FULL": ORANGE}
    offsets = {"B1_ONESHOT": -0.16, "FULL": 0.16}
    fig, axes = plt.subplots(1, 3, figsize=(15.6, 5.6), sharey=True)
    for ax, (metric, title) in zip(axes, metrics, strict=True):
        for group_index, group in enumerate(GROUPS):
            for condition in ("B1_ONESHOT", "FULL"):
                subset = [
                    row
                    for row in rows
                    if row["size_group"] == group
                    and row["condition"] == condition
                    and row["semantic_output_available"]
                ]
                x = group_index + offsets[condition]
                for row in subset:
                    filled = float(row.get("end_to_end_success") or 0) == 1
                    jitter = float(rng.uniform(-0.035, 0.035))
                    ax.scatter(
                        x + jitter,
                        float(row[metric]),
                        s=32,
                        facecolors=colors[condition] if filled else "white",
                        edgecolors=colors[condition],
                        linewidths=1.2,
                        alpha=0.85,
                        zorder=3,
                    )
                item = next(
                    row
                    for row in summary
                    if row["size_group"] == group and row["condition"] == condition
                )
                mean = float(item[f"{metric}_mean"])
                low = float(item[f"{metric}_ci95_low"])
                high = float(item[f"{metric}_ci95_high"])
                if math.isfinite(mean):
                    yerr = None
                    if math.isfinite(low) and math.isfinite(high):
                        yerr = [[mean - low], [high - mean]]
                    ax.errorbar(
                        [x],
                        [mean],
                        yerr=yerr,
                        fmt="D",
                        markersize=6,
                        color=colors[condition],
                        capsize=4,
                        linewidth=1.8,
                        zorder=4,
                    )
                missing = int(item["projects_attempted"]) - int(item["semantic_outputs"])
                if missing:
                    ax.text(
                        x,
                        1.055,
                        f"×{missing}",
                        ha="center",
                        va="center",
                        color=RED,
                        fontweight="bold",
                        fontsize=10,
                    )
        ax.set_title(title, fontweight="bold")
        ax.set_xticks(range(4), [GROUP_LABELS[group] for group in GROUPS], rotation=18)
        ax.set_ylim(-0.03, 1.10)
        ax.grid(axis="y", color="#D9DEE7", linewidth=0.8)
    axes[0].set_ylabel("F1, от 0 до 1")
    handles = [
        plt.Line2D([0], [0], color=BLUE, marker="D", linestyle="", label="Один вызов LLM"),
        plt.Line2D([0], [0], color=ORANGE, marker="D", linestyle="", label="Полный граф"),
        plt.Line2D(
            [0],
            [0],
            color=GRAY,
            marker="o",
            markerfacecolor="white",
            linestyle="",
            label="Есть результат, но E2E не пройден",
        ),
        plt.Line2D([0], [0], color=RED, marker="x", linestyle="", label="Нет результата для F1"),
    ]
    fig.legend(
        handles=handles, loc="upper center", ncol=4, frameon=False, bbox_to_anchor=(0.5, 1.01)
    )
    fig.suptitle(
        "Качество содержания и трассировки при росте входа", fontsize=18, fontweight="bold", y=1.10
    )
    fig.text(
        0.5,
        -0.01,
        "Точки — проекты; ромб — среднее; отрезок — 95% bootstrap CI. "
        "Предварительная авторская Gold-разметка, ожидается проверка двумя экспертами.",
        ha="center",
        color=GRAY,
        fontsize=9.5,
    )
    fig.tight_layout(rect=(0, 0.04, 1, 0.95))
    _save(fig, "01_size_quality_points_ci")


def _plot_e2e(summary: list[dict[str, Any]]) -> None:
    fig, ax = plt.subplots(figsize=(10.8, 6.0))
    x = np.arange(4)
    width = 0.34
    for index, (condition, color) in enumerate((("B1_ONESHOT", BLUE), ("FULL", ORANGE))):
        items = [
            next(
                row
                for row in summary
                if row["size_group"] == group and row["condition"] == condition
            )
            for group in GROUPS
        ]
        values = [100 * float(item["e2e_rate"]) for item in items]
        bars = ax.bar(
            x + (-0.5 + index) * width,
            values,
            width,
            color=color,
            label=CONDITION_LABELS[condition],
        )
        for bar, item in zip(bars, items, strict=True):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 2,
                f"{item['e2e_passes']}/{item['projects_attempted']}",
                ha="center",
                fontweight="bold",
                color=color,
            )
    ax.set_xticks(x, [GROUP_LABELS[group] for group in GROUPS])
    ax.set_ylim(0, 110)
    ax.set_ylabel("E2E success, % проектов")
    ax.set_title(
        "Полный граф чаще возвращает автоматически принимаемый комплект",
        fontsize=17,
        fontweight="bold",
    )
    ax.grid(axis="y", color="#D9DEE7", linewidth=0.8)
    ax.legend(frameon=False, loc="lower left")
    fig.text(
        0.5,
        0.01,
        "E2E = пройдены схема данных, структура Activity и трассировка "
        "всего комплекта. N = 5 проектов в группе.",
        ha="center",
        color=GRAY,
        fontsize=9.5,
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    _save(fig, "02_e2e_success_by_size")


def _plot_cost_latency(summary: list[dict[str, Any]]) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.7))
    colors = {"B1_ONESHOT": BLUE, "FULL": ORANGE}
    for condition in ("B1_ONESHOT", "FULL"):
        items = [
            next(
                row
                for row in summary
                if row["size_group"] == group and row["condition"] == condition
            )
            for group in GROUPS
        ]
        axes[0].plot(
            range(4),
            [float(item["mean_latency_seconds"]) for item in items],
            "o-",
            color=colors[condition],
            linewidth=2,
            label=CONDITION_LABELS[condition],
        )
        axes[1].plot(
            range(4),
            [float(item["mean_cost_usd"]) for item in items],
            "o-",
            color=colors[condition],
            linewidth=2,
            label=CONDITION_LABELS[condition],
        )
    axes[0].set_title("Среднее время попытки", fontweight="bold")
    axes[0].set_ylabel("Секунды")
    axes[1].set_title("Средняя оценочная стоимость попытки", fontweight="bold")
    axes[1].set_ylabel("Доллары США")
    for ax in axes:
        ax.set_xticks(range(4), [GROUP_LABELS[group] for group in GROUPS], rotation=15)
        ax.grid(axis="y", color="#D9DEE7", linewidth=0.8)
        ax.legend(frameon=False)
    fig.suptitle("Цена надёжности при росте числа требований", fontsize=17, fontweight="bold")
    fig.text(
        0.5,
        0.01,
        "Стоимость рассчитана по зафиксированным токенам и тарифам "
        "конфигурации; технически неудачные попытки также учитываются.",
        ha="center",
        color=GRAY,
        fontsize=9.5,
    )
    fig.tight_layout(rect=(0, 0.05, 1, 0.96))
    _save(fig, "03_cost_latency_by_size")


def _plot_size_effects(effects: list[dict[str, Any]]) -> None:
    labels = {
        "actor_f1": "Actor F1",
        "uc_f1": "Use Case F1",
        "milestone_f1": "Milestone F1",
        "branch_f1": "Branch F1",
        "trace_f1": "Trace F1",
        "end_to_end_success": "E2E success",
    }
    ordered = [
        "actor_f1",
        "uc_f1",
        "milestone_f1",
        "branch_f1",
        "trace_f1",
        "end_to_end_success",
    ]
    by_metric = {row["metric"]: row for row in effects}
    fig, ax = plt.subplots(figsize=(10.5, 6.2))
    y = np.arange(len(ordered))
    means = [float(by_metric[m]["mean_full_minus_one_shot"]) for m in ordered]
    lows = [float(by_metric[m]["ci95_low"]) for m in ordered]
    highs = [float(by_metric[m]["ci95_high"]) for m in ordered]
    colors = [
        GREEN if low > 0 else RED if high < 0 else GRAY
        for low, high in zip(lows, highs, strict=False)
    ]
    for mean, low, high, y_value, color in zip(means, lows, highs, y, colors, strict=True):
        ax.errorbar(
            [mean],
            [y_value],
            xerr=[[mean - low], [high - mean]],
            fmt="D",
            color=color,
            capsize=5,
            linewidth=2,
            markersize=7,
        )
    ax.axvline(0, color="black", linewidth=1)
    ax.set_yticks(y, [f"{labels[m]}  (n={by_metric[m]['paired_projects']})" for m in ordered])
    ax.set_xlabel("Разность: полный граф − один вызов")
    ax.set_title("Эффект полного графа на одинаковых проектах", fontsize=17, fontweight="bold")
    ax.grid(axis="x", color="#D9DEE7", linewidth=0.8)
    ax.invert_yaxis()
    fig.text(
        0.5,
        0.01,
        "Для F1 включены только пары с завершённым типизированным "
        "результатом; E2E включает все 20 проектов. "
        "Интервалы — project bootstrap, 50 000 выборок.",
        ha="center",
        color=GRAY,
        fontsize=9.3,
    )
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    _save(fig, "04_paired_full_minus_one_shot")


def _case_cluster_effects(
    reference_rows: list[dict[str, Any]], comparison_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    metrics = [
        "actor_f1",
        "uc_f1",
        "milestone_f1",
        "branch_f1",
        "trace_f1",
        "end_to_end_success",
    ]
    ref_by = defaultdict(list)
    cmp_by = defaultdict(list)
    for row in reference_rows:
        ref_by[row["case_id"]].append(row)
    for row in comparison_rows:
        cmp_by[row["case_id"]].append(row)
    common = sorted(set(ref_by) & set(cmp_by))
    result: list[dict[str, Any]] = []
    for metric in metrics:
        case_diffs = []
        for case_id in common:
            ref_values = [float(row[metric]) for row in ref_by[case_id]]
            cmp_values = [float(row[metric]) for row in cmp_by[case_id]]
            case_diffs.append(float(np.mean(ref_values) - np.mean(cmp_values)))
        mean, low, high = _bootstrap_ci(case_diffs)
        result.append(
            {
                "metric": metric,
                "projects": len(common),
                "repeats_per_project": 3,
                "mean_full_minus_no_critic": mean,
                "ci95_low": low,
                "ci95_high": high,
            }
        )
    return result


def _plot_critic_effects(effects: list[dict[str, Any]]) -> None:
    labels = {
        "actor_f1": "Actor F1",
        "uc_f1": "Use Case F1",
        "milestone_f1": "Milestone F1",
        "branch_f1": "Branch F1",
        "trace_f1": "Trace F1",
        "end_to_end_success": "E2E success",
    }
    fig, ax = plt.subplots(figsize=(10.5, 6.2))
    y = np.arange(len(effects))
    means = [float(row["mean_full_minus_no_critic"]) for row in effects]
    lows = [float(row["ci95_low"]) for row in effects]
    highs = [float(row["ci95_high"]) for row in effects]
    colors = [
        GREEN if low > 0 else RED if high < 0 else GRAY
        for low, high in zip(lows, highs, strict=False)
    ]
    for mean, low, high, y_value, color in zip(means, lows, highs, y, colors, strict=True):
        ax.errorbar(
            [mean],
            [y_value],
            xerr=[[mean - low], [high - mean]],
            fmt="D",
            color=color,
            capsize=5,
            linewidth=2,
            markersize=7,
        )
    ax.axvline(0, color="black", linewidth=1)
    ax.set_yticks(y, [labels[row["metric"]] for row in effects])
    ax.set_xlabel("Разность: полный граф − граф без критика")
    ax.set_title("Вклад LLM-критика: DEV20 × 3 повтора", fontsize=17, fontweight="bold")
    ax.grid(axis="x", color="#D9DEE7", linewidth=0.8)
    ax.invert_yaxis()
    fig.text(
        0.5,
        0.01,
        "Единица статистического анализа — проект: три повтора усреднены "
        "внутри каждого из 20 проектов; "
        "95% project-cluster bootstrap CI.",
        ha="center",
        color=GRAY,
        fontsize=9.3,
    )
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    _save(fig, "05_critic_contribution_dev20_r3")


def _report(
    size_rows: list[dict[str, Any]],
    summary: list[dict[str, Any]],
    size_effects: list[dict[str, Any]],
    critic_effects: list[dict[str, Any]] | None,
    critic_summary: list[dict[str, Any]] | None,
) -> str:
    e2e = {row["condition"]: 0 for row in size_rows}
    counts = {row["condition"]: 0 for row in size_rows}
    for row in size_rows:
        e2e[row["condition"]] += int(float(row.get("end_to_end_success") or 0) == 1)
        counts[row["condition"]] += 1
    e2e_effect = next(row for row in size_effects if row["metric"] == "end_to_end_success")
    lines = [
        "# Итоговый эксперимент по размеру входа и вкладу критика",
        "",
        "## Что измерено",
        "",
        "- 20 проектов руководителя: четыре группы по пять проектов, 6–74 ФТ.",
        "- Для каждого проекта: один прямой вызов DeepSeek и один запуск полного графа.",
        "- Семантические F1 считаются только при наличии целого типизированного "
        "результата; технический провал показывается отдельно.",
        "- Gold имеет статус авторского кандидата и требует двух независимых экспертных проверок.",
        "",
        "## Главный результат",
        "",
        (
            f"- E2E: один вызов {e2e.get('B1_ONESHOT', 0)}/"
            f"{counts.get('B1_ONESHOT', 0)}, полный граф "
            f"{e2e.get('FULL', 0)}/{counts.get('FULL', 0)}."
        ),
        (
            f"- Парная разность E2E: "
            f"{e2e_effect['mean_full_minus_one_shot']:+.3f}; 95% CI "
            f"[{e2e_effect['ci95_low']:+.3f}; "
            f"{e2e_effect['ci95_high']:+.3f}]."
        ),
        (
            "- Точный двусторонний McNemar/binomial p = "
            f"{e2e_effect.get('mcnemar_exact_two_sided_p', math.nan):.6f}."
        ),
        (
            "- Это доказывает рост формальной принимаемости на данном наборе, "
            "но не универсальное улучшение каждой смысловой F1."
        ),
        "",
        "## Интерпретация отказа FULL на SCALE-018",
        "",
        (
            "Полный граф создал 44 Activity-артефакта, но одна диаграмма после "
            "двух разрешённых исправлений сохранила неподтверждённую ветвь и "
            "структурный дефект решения. Конечный gate корректно отклонил весь "
            "комплект. Это контролируемый содержательный отказ, а не потеря "
            "ответа или висячая ссылка TraceManifest."
        ),
        "",
        "## Файлы",
        "",
        "- `01_size_quality_points_ci.png` — точки проектов, средние и 95% CI.",
        "- `02_e2e_success_by_size.png` — E2E по четырём группам.",
        "- `03_cost_latency_by_size.png` — время и стоимость.",
        "- `04_paired_full_minus_one_shot.png` — парные эффекты FULL − one-shot.",
    ]
    if critic_effects is not None:
        critic_by_condition = {
            row["condition"]: row for row in (critic_summary or [])
        }
        full = critic_by_condition.get("FULL", {})
        no_critic = critic_by_condition.get("FULL_NO_CRITIC", {})
        branch_effect = next(
            row for row in critic_effects if row["metric"] == "branch_f1"
        )
        lines.extend(
            [
                "- `05_critic_contribution_dev20_r3.png` — вклад критика на DEV20 ×3.",
                "",
                "## Результат анализа вклада критика",
                "",
                (
                    "- Оба режима завершили 60/60 запусков; преимущества критика "
                    "по E2E на DEV20 не обнаружено."
                ),
                (
                    "- Наибольшая наблюдаемая разность — Branch F1: "
                    f"{branch_effect['mean_full_minus_no_critic']:+.3f}; 95% CI "
                    f"[{branch_effect['ci95_low']:+.3f}; "
                    f"{branch_effect['ci95_high']:+.3f}]. Интервал включает ноль."
                ),
                (
                    "- Среднее число LLM-вызовов: FULL "
                    f"{float(full.get('mean_llm_calls', math.nan)):.2f}, без критика "
                    f"{float(no_critic.get('mean_llm_calls', math.nan)):.2f}; "
                    "средние токены: "
                    f"{float(full.get('mean_total_tokens', math.nan)):.0f} против "
                    f"{float(no_critic.get('mean_total_tokens', math.nan)):.0f}."
                ),
                (
                    "- На этом DEV20 постоянный вызов критика не доказал "
                    "статистически надёжного прироста качества, но увеличил расход. "
                    "Практический вывод — запускать критика условно для сложных или "
                    "не прошедших детерминированные проверки случаев."
                ),
                "",
                "## Ограничения",
                "",
                (
                    "- На size benchmark выполнен один запуск на проект; CI "
                    "отражает разброс между проектами, а не повторяемость генерации."
                ),
                "- Смысловые выводы предварительны до согласования Gold двумя экспертами.",
                "- Сравнение критика использует синтетический DEV20; hidden-набор не вскрывался.",
                (
                    "- FULL и FULL_NO_CRITIC сохранены из разных программных ревизий; "
                    "между ними менялась checkpoint-организация корневого графа. "
                    "Промпты, схема, модель и benchmark совпадают, однако причинный "
                    "вывод именно о критике остаётся предварительным."
                ),
            ]
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    _style()
    size_rows = _load_size_rows()
    summary = _size_summary(size_rows)
    size_effects = _paired_size_effects(size_rows)
    _write_csv(OUTPUT / "size_project_rows.csv", size_rows)
    _write_csv(OUTPUT / "size_group_summary_ci95.csv", summary)
    _write_csv(OUTPUT / "size_paired_effects_ci95.csv", size_effects)
    _plot_size_quality(size_rows, summary)
    _plot_e2e(summary)
    _plot_cost_latency(summary)
    _plot_size_effects(size_effects)

    critic_effects: list[dict[str, Any]] | None = None
    critic_summary: list[dict[str, Any]] | None = None
    if FULL_DEV20.exists() and NO_CRITIC_DEV20.exists():
        full_document = _read_json(FULL_DEV20)
        no_critic_document = _read_json(NO_CRITIC_DEV20)
        full_rows = full_document["rows"]
        no_critic_rows = no_critic_document["rows"]
        critic_effects = _case_cluster_effects(full_rows, no_critic_rows)
        critic_summary = [full_document["summary"][0], no_critic_document["summary"][0]]
        _write_csv(OUTPUT / "critic_paired_effects_ci95.csv", critic_effects)
        _write_csv(OUTPUT / "critic_condition_summary.csv", critic_summary)
        _plot_critic_effects(critic_effects)

    (OUTPUT / "REPORT_RU.md").write_text(
        _report(size_rows, summary, size_effects, critic_effects, critic_summary),
        encoding="utf-8",
    )
    manifest = {
        "size_sources": [str((path / "results.json").relative_to(ROOT)) for path in SIZE_RUNS],
        "full_dev20_source": str(FULL_DEV20.relative_to(ROOT)),
        "no_critic_source": (
            str(NO_CRITIC_DEV20.relative_to(ROOT)) if NO_CRITIC_DEV20.exists() else None
        ),
        "gold_status": "author_candidate_requires_two_independent_reviews",
        "hidden_test_used": False,
        "bootstrap_iterations": 50_000,
        "semantic_failure_policy": "missing output is reported separately, not converted to F1=0",
        "critic_comparison_limit": (
            "FULL and FULL_NO_CRITIC use the same benchmark/model/prompts/schema but were "
            "preserved from different code revisions; causal attribution is preliminary."
        ),
    }
    (OUTPUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(OUTPUT)


if __name__ == "__main__":
    main()
