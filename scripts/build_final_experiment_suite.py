"""Build the presentation-ready experiment suite from saved live runs.

The script never calls an LLM. It aggregates previously saved DeepSeek,
OpenAI and Anthropic runs, writes machine-readable tables, and renders figures
in a formal scientific style suitable for the report and presentation.
"""

# ruff: noqa: E501

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "final_experiment_suite_2026-09-16"

BLUE = "#0072B2"
ORANGE = "#E66101"
GREEN = "#009E73"
MAGENTA = "#CC79A7"
PURPLE = "#7B61A8"
RED = "#D62728"
YELLOW = "#F0E442"
GRAY = "#6B7280"
LIGHT_GRAY = "#E5E7EB"

SIZE_CASES = ("SCALE-001", "SCALE-010", "SCALE-015", "SCALE-020")
SIZE_LABELS = {
    "SCALE-001": "6 ФТ",
    "SCALE-010": "19 ФТ",
    "SCALE-015": "48 ФТ",
    "SCALE-020": "74 ФТ",
}
METHOD_LABELS = {
    "B1_ONESHOT": "Один вызов",
    "FULL_NO_REPAIR": "Без исправления",
    "FULL_NO_CRITIC": "Без критика",
    "FULL": "Полный граф",
}


def _configure_matplotlib() -> None:
    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": ["Times New Roman", "DejaVu Serif"],
            "font.size": 12,
            "axes.titlesize": 14,
            "axes.labelsize": 12,
            "axes.edgecolor": "#111111",
            "axes.linewidth": 0.8,
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
            "legend.fontsize": 10,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
            "savefig.dpi": 220,
        }
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"Expected a JSON object in {path}")
    return value


def _number(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    return float(value)


def _optional_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _quality_value(row: dict[str, Any], field: str, *, output_available: bool) -> float | None:
    """Do not report a technical failure as a measured zero-quality artifact."""
    if not output_available:
        return None
    return _optional_number(row.get(field))


def _format_metric_pair(left_row: dict[str, Any], right_row: dict[str, Any], metric: str) -> str:
    left = "—" if left_row[metric] is None else f"{left_row[metric]:.3f}"
    right = "—" if right_row[metric] is None else f"{right_row[metric]:.3f}"
    return f"{left} / {right}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _save_figure(fig: plt.Figure, stem: str) -> None:
    for suffix in ("png", "svg"):
        fig.savefig(OUTPUT / f"{stem}.{suffix}", bbox_inches="tight")
    plt.close(fig)


def _caption(fig: plt.Figure, number: int, text: str, source: str) -> None:
    fig.text(0.5, 0.045, f"Рисунок {number} — {text}", ha="center", fontsize=12)
    fig.text(0.5, 0.018, f"Источник: {source}", ha="center", fontsize=9, color=GRAY)


def _prepare_size_rows() -> list[dict[str, Any]]:
    source_paths = [
        ROOT
        / "artifacts/size_scaling_runs/size-scaling-gold-preflight-scale001-2026-09-15/results.csv",
        ROOT
        / "artifacts/size_scaling_runs/size-scaling-gold-preflight-mixed-2026-09-15/results.csv",
    ]
    raw = [row for path in source_paths for row in _read_csv(path)]
    selected = [
        row
        for row in raw
        if row.get("case_id") in SIZE_CASES and row.get("condition") in {"B1_ONESHOT", "FULL"}
    ]
    by_key = {(row["case_id"], row["condition"]): row for row in selected}
    if len(by_key) != 8:
        raise ValueError(f"Expected 8 size preflight rows, found {len(by_key)}")

    prepared: list[dict[str, Any]] = []
    for case_id in SIZE_CASES:
        for condition in ("B1_ONESHOT", "FULL"):
            row = by_key[(case_id, condition)]
            error_type = row.get("error_type", "")
            e2e = _number(row.get("end_to_end_success"))
            output_available = row.get("milestone_f1") not in (None, "")
            if e2e == 1:
                status = "E2E пройден"
                status_code = "pass"
            elif error_type == "LLMOutputTruncatedError":
                status = "Ответ обрезан"
                status_code = "fail"
            elif error_type:
                status = "Сбой API"
                status_code = "fail"
            elif output_available:
                status = "Артефакты созданы;\nфинальная проверка не пройдена"
                status_code = "partial"
            else:
                status = "E2E не пройден"
                status_code = "fail"

            prepared.append(
                {
                    "case_id": case_id,
                    "fr_count": int(row["fr_count"]),
                    "condition": condition,
                    "method_ru": METHOD_LABELS[condition],
                    "status": status.replace("\n", " "),
                    "status_code": status_code,
                    "e2e_success": e2e,
                    "actor_f1": _quality_value(row, "actor_f1", output_available=output_available),
                    "uc_f1": _quality_value(row, "uc_f1", output_available=output_available),
                    "milestone_f1": _quality_value(
                        row, "milestone_f1", output_available=output_available
                    ),
                    "branch_f1": _quality_value(
                        row, "branch_f1", output_available=output_available
                    ),
                    "trace_f1": _quality_value(row, "trace_f1", output_available=output_available),
                    "fr_activity_coverage": (
                        _optional_number(row.get("fr_activity_coverage") or row.get("fr_coverage"))
                        if output_available
                        else None
                    ),
                    "activity_element_trace_coverage": (
                        _quality_value(
                            row,
                            "activity_element_trace_coverage",
                            output_available=output_available,
                        )
                    ),
                    "activity_structural_validity": _quality_value(
                        row,
                        "activity_structural_validity",
                        output_available=output_available,
                    ),
                    "llm_calls": int(_number(row.get("llm_calls"))),
                    "total_tokens": int(_number(row.get("total_tokens"))),
                    "latency_seconds": _number(row.get("latency_ms")) / 1000,
                    "estimated_cost_usd": _number(row.get("estimated_cost_usd")),
                    "error_type": error_type,
                    "repeat_id": int(row.get("repeat_id") or 1),
                }
            )
    return prepared


def _prepare_component_rows() -> list[dict[str, Any]]:
    pilot_path = (
        ROOT
        / "artifacts/benchmark_runs/component-comparison-dev3-deepseek-flash-2026-09-11/results.csv"
    )
    corrected_full_path = (
        ROOT / "artifacts/benchmark_runs/full-critic-v2-dev3-deepseek-flash-2026-09-11/results.csv"
    )
    pilot = [row for row in _read_csv(pilot_path) if row["condition"] != "FULL"]
    corrected_full = _read_csv(corrected_full_path)
    rows = pilot + corrected_full
    metrics = (
        "actor_f1",
        "uc_f1",
        "milestone_f1",
        "branch_f1",
        "trace_f1",
        "fr_coverage",
        "activity_element_trace_coverage",
        "activity_structural_validity",
        "schema_validity",
        "end_to_end_success",
        "llm_calls",
        "repair_attempts",
        "total_tokens",
        "latency_ms",
        "estimated_cost_usd",
    )
    prepared: list[dict[str, Any]] = []
    for condition in ("B1_ONESHOT", "FULL_NO_REPAIR", "FULL_NO_CRITIC", "FULL"):
        group = [row for row in rows if row["condition"] == condition]
        if len(group) != 3:
            raise ValueError(f"Expected 3 rows for {condition}, found {len(group)}")
        item: dict[str, Any] = {
            "condition": condition,
            "method_ru": METHOD_LABELS[condition],
            "projects": 3,
            "repeats_per_project": 1,
            "case_ids": ", ".join(row["case_id"] for row in group),
        }
        for metric in metrics:
            item[metric] = mean(_number(row.get(metric)) for row in group)
        item["latency_seconds"] = item.pop("latency_ms") / 1000
        prepared.append(item)
    return prepared


def _prepare_cross_model_rows() -> list[dict[str, Any]]:
    sources = [
        (
            "DeepSeek",
            "deepseek-flash",
            "B1_ONESHOT",
            ROOT / "artifacts/benchmark_runs/b1-dev20-r3-deepseek-flash-2026-09-13/results.json",
        ),
        (
            "DeepSeek",
            "deepseek-flash",
            "FULL",
            ROOT / "artifacts/benchmark_runs/full-dev20-r3-deepseek-flash-2026-09-13/results.json",
        ),
        (
            "OpenAI",
            "gpt-5.5-2026-04-23",
            "B1_ONESHOT",
            ROOT
            / "artifacts/external_model_runs/external-gpt55-oneshot-dev002-r3-2026-09-13/results.json",
        ),
        (
            "OpenAI",
            "gpt-5.5-2026-04-23",
            "FULL",
            ROOT / "artifacts/benchmark_runs/full-gpt55-dev002-r3-combined-2026-09-13/results.json",
        ),
        (
            "Anthropic",
            "claude-opus-5",
            "B1_ONESHOT",
            ROOT
            / "artifacts/external_model_runs/external-claude-opus5-oneshot-dev002-r3-2026-09-13/results.json",
        ),
        (
            "Anthropic",
            "claude-opus-5",
            "FULL",
            ROOT
            / "artifacts/benchmark_runs/full-claude-opus5-dev002-r3-combined-2026-09-13/results.json",
        ),
    ]
    metric_names = (
        "actor_f1",
        "uc_f1",
        "milestone_f1",
        "branch_f1",
        "trace_f1",
        "fr_coverage",
        "activity_element_trace_coverage",
        "activity_structural_validity",
        "end_to_end_success",
        "latency_ms",
        "total_tokens",
        "estimated_cost_usd",
        "llm_calls",
        "repair_attempts",
    )
    prepared: list[dict[str, Any]] = []
    for provider, model, condition, path in sources:
        rows = [row for row in _read_json(path)["rows"] if row.get("case_id") == "B1-DEV-002"]
        if len(rows) != 3:
            raise ValueError(f"Expected 3 B1-DEV-002 rows in {path}, found {len(rows)}")
        item: dict[str, Any] = {
            "provider": provider,
            "model": model,
            "condition": condition,
            "method_ru": METHOD_LABELS[condition],
            "case_id": "B1-DEV-002",
            "repeats": 3,
            "source_sha256": _sha256(path),
        }
        for metric in metric_names:
            values = [_number(row.get(metric)) for row in rows]
            item[f"mean_{metric}"] = mean(values)
            item[f"sd_{metric}"] = pstdev(values)
        item["mean_latency_seconds"] = item.pop("mean_latency_ms") / 1000
        item["sd_latency_seconds"] = item.pop("sd_latency_ms") / 1000
        prepared.append(item)
    return prepared


def _plot_size_status(rows: list[dict[str, Any]]) -> None:
    by_key = {(row["case_id"], row["condition"]): row for row in rows}
    fig, ax = plt.subplots(figsize=(11.5, 6.6))
    fig.subplots_adjust(top=0.84, bottom=0.19, left=0.19, right=0.97)
    ax.set_xlim(0, 2)
    ax.set_ylim(0, 4)
    ax.axis("off")
    colors = {"pass": GREEN, "partial": ORANGE, "fail": RED}
    short = {
        ("SCALE-001", "B1_ONESHOT"): "E2E 1/1",
        ("SCALE-001", "FULL"): "E2E 1/1",
        ("SCALE-010", "B1_ONESHOT"): "Невалидная\nActivity",
        ("SCALE-010", "FULL"): "Сбой передачи",
        ("SCALE-015", "B1_ONESHOT"): "Ответ обрезан",
        ("SCALE-015", "FULL"): "Артефакты созданы;\nфинальный gate не пройден",
        ("SCALE-020", "B1_ONESHOT"): "Ответ обрезан",
        ("SCALE-020", "FULL"): "Артефакты созданы;\nфинальный gate не пройден",
    }
    for y, case_id in enumerate(reversed(SIZE_CASES)):
        for x, condition in enumerate(("B1_ONESHOT", "FULL")):
            row = by_key[(case_id, condition)]
            color = colors[row["status_code"]]
            ax.add_patch(
                Rectangle(
                    (x + 0.04, y + 0.07),
                    0.92,
                    0.86,
                    facecolor=color,
                    edgecolor="black",
                    linewidth=0.8,
                )
            )
            ax.text(
                x + 0.5,
                y + 0.5,
                short[(case_id, condition)],
                ha="center",
                va="center",
                color="white",
                fontsize=11,
                fontweight="bold",
            )
        ax.text(-0.05, y + 0.5, SIZE_LABELS[case_id], ha="right", va="center", fontsize=12)
    ax.text(0.5, 4.05, "Один вызов LLM", ha="center", va="bottom", fontsize=13, fontweight="bold")
    ax.text(1.5, 4.05, "Полный граф", ha="center", va="bottom", fontsize=13, fontweight="bold")
    fig.suptitle(
        "Завершение конвейера при росте числа требований", fontsize=18, fontweight="bold", y=0.96
    )
    fig.text(
        0.5,
        0.885,
        "DeepSeek deepseek-flash · по одному диагностическому запуску на размер",
        ha="center",
        fontsize=11,
        color=GRAY,
    )
    _caption(
        fig,
        1,
        "Статус обработки проектов с 6, 19, 48 и 74 функциональными требованиями",
        "сохранённые live-прогоны 15.09.2026; n = 1 на ячейку",
    )
    _save_figure(fig, "01_size_status_gost")


def _plot_size_quality(rows: list[dict[str, Any]]) -> None:
    by_method: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_method[row["condition"]].append(row)
    for group in by_method.values():
        group.sort(key=lambda row: row["fr_count"])
    metrics = [
        ("milestone_f1", "Milestone F1\n(ключевые этапы)"),
        ("branch_f1", "Branch F1\n(альтернативные ветви)"),
        ("trace_f1", "Trace F1\n(связи требований и UC)"),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(14, 5.8), sharex=True, sharey=True)
    fig.subplots_adjust(top=0.68, bottom=0.23, left=0.07, right=0.985, wspace=0.16)
    method_colors = {"B1_ONESHOT": BLUE, "FULL": ORANGE}
    for ax, (metric, title) in zip(axes, metrics, strict=True):
        for condition in ("B1_ONESHOT", "FULL"):
            group = by_method[condition]
            xs = [row["fr_count"] for row in group]
            ys = [row[metric] if row[metric] is not None else np.nan for row in group]
            ax.plot(
                xs,
                ys,
                color=method_colors[condition],
                marker="o",
                linewidth=2.3,
                markersize=7,
                label=METHOD_LABELS[condition],
            )
            for row in group:
                value = row[metric]
                if value is None:
                    ax.scatter(
                        row["fr_count"],
                        1.06,
                        marker="x",
                        s=70,
                        color=method_colors[condition],
                        linewidth=2,
                    )
                else:
                    ax.annotate(
                        f"{value:.2f}",
                        (row["fr_count"], value),
                        xytext=(0, 8),
                        textcoords="offset points",
                        ha="center",
                        fontsize=8,
                        color=method_colors[condition],
                    )
        ax.set_title(title, fontweight="bold")
        ax.set_xlabel("Число функциональных требований, шт.")
        ax.set_xticks([6, 19, 48, 74])
        ax.set_ylim(-0.03, 1.12)
        ax.set_yticks(np.linspace(0, 1, 6))
        ax.grid(axis="y", color=LIGHT_GRAY, linewidth=0.7)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel("Значение метрики, 0–1")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="upper center",
        ncol=2,
        frameon=False,
        bbox_to_anchor=(0.5, 0.815),
    )
    fig.suptitle("Содержание и трассировка при росте входа", fontsize=18, fontweight="bold", y=0.96)
    fig.text(
        0.5,
        0.885,
        "× означает отсутствие результата; цвет показывает режим; это не нулевой F1",
        ha="center",
        fontsize=10,
        color=GRAY,
    )
    _caption(
        fig,
        2,
        "Диагностические F1 по четырём размерам входа",
        "candidate Gold из входных требований; требуется независимая экспертная проверка; n = 1",
    )
    _save_figure(fig, "02_size_quality_gost")


def _plot_size_resources(rows: list[dict[str, Any]]) -> None:
    by_method: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_method[row["condition"]].append(row)
    for group in by_method.values():
        group.sort(key=lambda row: row["fr_count"])
    panels = [
        ("llm_calls", "Вызовы LLM, шт.", 1.0),
        ("total_tokens", "Токены, тыс.", 1000.0),
        ("latency_seconds", "Время, мин", 60.0),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(14, 5.8), sharex=True)
    fig.subplots_adjust(top=0.78, bottom=0.23, left=0.07, right=0.985, wspace=0.22)
    colors = {"B1_ONESHOT": BLUE, "FULL": ORANGE}
    for ax, (metric, ylabel, divisor) in zip(axes, panels, strict=True):
        for condition in ("B1_ONESHOT", "FULL"):
            group = by_method[condition]
            xs = [row["fr_count"] for row in group]
            ys = [row[metric] / divisor for row in group]
            ax.plot(
                xs,
                ys,
                color=colors[condition],
                marker="o",
                linewidth=2.4,
                markersize=7,
                label=METHOD_LABELS[condition],
            )
            for x, y in zip(xs, ys, strict=True):
                label = f"{y:.1f}" if y < 100 else f"{y:.0f}"
                ax.annotate(
                    label,
                    (x, y),
                    xytext=(0, 8),
                    textcoords="offset points",
                    ha="center",
                    fontsize=8,
                )
        ax.set_xlabel("Число функциональных требований, шт.")
        ax.set_ylabel(ylabel)
        ax.set_xticks([6, 19, 48, 74])
        ax.grid(axis="y", color=LIGHT_GRAY, linewidth=0.7)
        ax.spines[["top", "right"]].set_visible(False)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles, labels, loc="upper center", ncol=2, frameon=False, bbox_to_anchor=(0.5, 0.84)
    )
    fig.suptitle(
        "Ресурсы полного графа растут вместе с объёмом требований",
        fontsize=18,
        fontweight="bold",
        y=0.96,
    )
    fig.text(
        0.5,
        0.885,
        "Для FULL линейная аппроксимация: R² = 0,996 по вызовам; 0,989 по токенам; 0,988 по времени",
        ha="center",
        fontsize=10,
        color=GRAY,
    )
    _caption(
        fig,
        3,
        "Операционные затраты для проектов разного размера",
        "сохранённые live-прогоны DeepSeek; значения включают неуспешные попытки; n = 1",
    )
    _save_figure(fig, "03_size_resources_gost")


def _plot_component_contribution(rows: list[dict[str, Any]]) -> None:
    labels = [row["method_ru"] for row in rows]
    x = np.arange(len(rows))
    width = 0.24
    fig, axes = plt.subplots(1, 2, figsize=(14, 6.2))
    fig.subplots_adjust(top=0.78, bottom=0.29, left=0.07, right=0.985, wspace=0.18)
    left_metrics = [
        ("milestone_f1", "Milestone F1", BLUE),
        ("branch_f1", "Branch F1", ORANGE),
        ("trace_f1", "Trace F1", GREEN),
    ]
    for index, (metric, label, color) in enumerate(left_metrics):
        values = [row[metric] for row in rows]
        bars = axes[0].bar(
            x + (index - 1) * width,
            values,
            width,
            label=label,
            color=color,
            edgecolor="black",
            linewidth=0.5,
        )
        axes[0].bar_label(bars, fmt="%.2f", fontsize=8, padding=2)
    axes[0].set_title("Содержание и трассировка", fontweight="bold")
    axes[0].set_ylabel("Среднее значение, 0–1")
    axes[0].set_ylim(0, 1.13)
    axes[0].legend(frameon=False, loc="upper left")

    right_metrics = [
        ("activity_structural_validity", "Структура Activity", MAGENTA),
        ("activity_element_trace_coverage", "Трассировка Activity", BLUE),
        ("end_to_end_success", "E2E", GREEN),
    ]
    for index, (metric, label, color) in enumerate(right_metrics):
        values = [row[metric] for row in rows]
        bars = axes[1].bar(
            x + (index - 1) * width,
            values,
            width,
            label=label,
            color=color,
            edgecolor="black",
            linewidth=0.5,
        )
        axes[1].bar_label(bars, fmt="%.2f", fontsize=8, padding=2)
    axes[1].set_title("Формальная надёжность", fontweight="bold")
    axes[1].set_ylabel("Доля успешных проектов, 0–1")
    axes[1].set_ylim(0, 1.13)
    axes[1].legend(frameon=False, loc="upper left")
    for ax in axes:
        ax.set_xticks(x, labels, rotation=18, ha="right")
        ax.grid(axis="y", color=LIGHT_GRAY, linewidth=0.7)
        ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("Вклад этапов проверки и исправления", fontsize=18, fontweight="bold", y=0.96)
    fig.text(
        0.5,
        0.87,
        "DeepSeek · DEV-002/010/020 · один запуск на проект: описательный пилот, не итоговая статистика",
        ha="center",
        fontsize=10,
        color=GRAY,
    )
    _caption(
        fig,
        4,
        "Сравнение one-shot, варианта без исправления, без критика и полного графа",
        "сохранённые live-прогоны; технический провал учитывается как 0; N = 3 проекта",
    )
    _save_figure(fig, "04_component_contribution_gost")


def _plot_cross_model(rows: list[dict[str, Any]]) -> None:
    providers = ("DeepSeek", "OpenAI", "Anthropic")
    provider_labels = {"DeepSeek": "DeepSeek", "OpenAI": "GPT-5.5", "Anthropic": "Claude Opus 5"}
    metrics = [
        ("mean_milestone_f1", "Milestone F1"),
        ("mean_branch_f1", "Branch F1"),
        ("mean_activity_structural_validity", "Структура Activity"),
        ("mean_end_to_end_success", "E2E success"),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(15, 6.2), sharey=True)
    fig.subplots_adjust(top=0.77, bottom=0.27, left=0.06, right=0.985, wspace=0.12)
    x = np.arange(len(metrics))
    width = 0.35
    for ax, provider in zip(axes, providers, strict=True):
        provider_rows = {row["condition"]: row for row in rows if row["provider"] == provider}
        one_shot = [provider_rows["B1_ONESHOT"][metric] for metric, _ in metrics]
        full = [provider_rows["FULL"][metric] for metric, _ in metrics]
        bars1 = ax.bar(
            x - width / 2,
            one_shot,
            width,
            label="Один вызов",
            color=BLUE,
            edgecolor="black",
            linewidth=0.5,
        )
        bars2 = ax.bar(
            x + width / 2,
            full,
            width,
            label="Полный граф",
            color=ORANGE,
            edgecolor="black",
            linewidth=0.5,
        )
        ax.bar_label(bars1, fmt="%.2f", fontsize=8, padding=2)
        ax.bar_label(bars2, fmt="%.2f", fontsize=8, padding=2)
        ax.set_title(provider_labels[provider], fontweight="bold")
        ax.set_xticks(x, [label for _, label in metrics], rotation=25, ha="right")
        ax.set_ylim(0, 1.16)
        ax.grid(axis="y", color=LIGHT_GRAY, linewidth=0.7)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel("Среднее значение, 0–1")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles, labels, loc="upper center", ncol=2, frameon=False, bbox_to_anchor=(0.5, 0.84)
    )
    fig.suptitle("Один и тот же кейс на трёх моделях", fontsize=18, fontweight="bold", y=0.96)
    fig.text(
        0.5,
        0.875,
        "B1-DEV-002 · одинаковые вход, схема результата и evaluator · 3 независимых повтора",
        ha="center",
        fontsize=10,
        color=GRAY,
    )
    _caption(
        fig,
        5,
        "Сравнение one-shot и полного графа на DeepSeek, GPT-5.5 и Claude Opus 5",
        "сохранённые live-прогоны 13.09.2026; n = 3 на конфигурацию",
    )
    _save_figure(fig, "05_cross_model_quality_gost")


def _plot_cross_model_cost(rows: list[dict[str, Any]]) -> None:
    labels = [
        f"{('GPT-5.5' if row['provider'] == 'OpenAI' else 'Claude' if row['provider'] == 'Anthropic' else 'DeepSeek')}\n{row['method_ru']}"
        for row in rows
    ]
    x = np.arange(len(rows))
    costs = [row["mean_estimated_cost_usd"] for row in rows]
    times = [row["mean_latency_seconds"] for row in rows]
    tokens = [row["mean_total_tokens"] / 1000 for row in rows]
    colors = [BLUE if row["condition"] == "B1_ONESHOT" else ORANGE for row in rows]
    fig, axes = plt.subplots(1, 3, figsize=(15, 6.2))
    fig.subplots_adjust(top=0.78, bottom=0.31, left=0.06, right=0.985, wspace=0.22)
    for ax, values, title, fmt in (
        (axes[0], costs, "Стоимость одного запуска, USD", "%.3f"),
        (axes[1], times, "Среднее время, с", "%.1f"),
        (axes[2], tokens, "Среднее число токенов, тыс.", "%.1f"),
    ):
        bars = ax.bar(x, values, color=colors, edgecolor="black", linewidth=0.5)
        ax.bar_label(bars, fmt=fmt, fontsize=8, padding=2)
        ax.set_title(title, fontweight="bold")
        ax.set_xticks(x, labels, rotation=25, ha="right")
        ax.grid(axis="y", color=LIGHT_GRAY, linewidth=0.7)
        ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle(
        "Цена поэтапной проверки зависит от провайдера", fontsize=18, fontweight="bold", y=0.96
    )
    fig.text(
        0.5,
        0.88,
        "Операционные показатели не являются качеством; их используют для оценки компромисса",
        ha="center",
        fontsize=10,
        color=GRAY,
    )
    _caption(
        fig,
        6,
        "Время, токены и расчётная стоимость на общем простом кейсе",
        "provider telemetry; B1-DEV-002; n = 3 на конфигурацию",
    )
    _save_figure(fig, "06_cross_model_cost_gost")


def _write_report(
    size_rows: list[dict[str, Any]],
    component_rows: list[dict[str, Any]],
    cross_model_rows: list[dict[str, Any]],
) -> None:
    size_by_key = {(row["case_id"], row["condition"]): row for row in size_rows}
    component_by = {row["condition"]: row for row in component_rows}
    cross_by = {(row["provider"], row["condition"]): row for row in cross_model_rows}
    lines = [
        "# Эксперименты: масштабирование, вклад компонентов и переносимость между моделями",
        "",
        "Дата сборки: 2026-09-16. Все числа восстановлены из сохранённых live-прогонов; новых платных вызовов скрипт не выполняет.",
        "",
        "## Короткий итог",
        "",
        "1. На frozen DEV20 полный граф DeepSeek дал 60/60 E2E против 2/60 у одного вызова. Наиболее доказанный эффект — формальная надёжность и трассировка, а не универсальный рост каждого содержательного F1.",
        "2. В размерном preflight один вызов прошёл при 6 ФТ, получил невалидную Activity при 19 ФТ и был обрезан при 48/74 ФТ. FULL создал большие комплекты при 48/74 ФТ, но финальный E2E gate ещё не прошёл.",
        "3. В компонентном пилоте вариант без исправления дал 0/3 E2E, а варианты с исправлением — 3/3. Отдельный вклад критика пока статистически не доказан: без критика тоже 3/3, хотя Branch F1 ниже.",
        "4. На общем простом кейсе FULL исправляет формальный провал DeepSeek, улучшает Milestone F1 Claude, но не улучшает GPT-5.5. Эффект архитектуры зависит от модели и сложности входа.",
        "",
        "## Что означает каждая метрика",
        "",
        "Все метрики качества находятся в диапазоне 0–1: `1` — полное совпадение с проверенным эталоном по данному аспекту, `0` — совпадений нет. `Precision = TP / (TP + FP)`, `Recall = TP / (TP + FN)`, `F1 = 2PR / (P + R)`. Здесь TP — подтверждённое совпадение, FP — лишний неподтверждённый элемент, FN — пропущенный ожидаемый элемент.",
        "",
        "- **Actor F1** — совпадение ролей процесса с эталоном. Низкое значение означает пропущенных либо лишних участников.",
        "- **UC F1** — совпадение набора Use Cases и их границ. Штрафует пропуск процесса, лишний процесс, ошибочное объединение или дробление.",
        "- **Milestone F1** — совпадение обязательных ключевых этапов сценария. Учитывает и пропуски, и лишнюю детализацию.",
        "- **Branch F1** — совпадение условий и результатов альтернативных/ошибочных путей.",
        "- **Trace F1** — правильность конкретных связей `FR → UC`: Precision штрафует лишние связи, Recall — потерянные.",
        "- **FR → Activity coverage** — доля функциональных требований, которые дошли через шаг Use Case хотя бы до одного узла или ребра Activity.",
        "- **Activity structural validity** — доля диаграмм, прошедших детерминированные инварианты: начало/конец, достижимость, допустимые переходы, ветвления и уникальные ID.",
        "- **E2E success** — бинарный результат проекта: все обязательные артефакты созданы и одновременно прошли схемы, структуру и трассировку.",
        "- **Latency, tokens, cost** — операционные показатели цены результата; они не заменяют метрики качества.",
        "",
        "## 1. Масштабирование: 6, 19, 48 и 74 ФТ",
        "",
        "| ФТ | Один вызов | FULL | Milestone F1: one-shot / FULL | Branch F1: one-shot / FULL | Trace F1: one-shot / FULL |",
        "|---:|---|---|---:|---:|---:|",
    ]
    for case_id in SIZE_CASES:
        b1 = size_by_key[(case_id, "B1_ONESHOT")]
        full = size_by_key[(case_id, "FULL")]

        lines.append(
            f"| {b1['fr_count']} | {b1['status']} | {full['status']} | "
            f"{_format_metric_pair(b1, full, 'milestone_f1')} | "
            f"{_format_metric_pair(b1, full, 'branch_f1')} | "
            f"{_format_metric_pair(b1, full, 'trace_f1')} |"
        )
    lines.extend(
        [
            "",
            "**Что показывают рисунки 1–3.** Рисунок 1 отвечает только на вопрос завершения. Рисунок 2 показывает содержательные F1 там, где результат вообще удалось получить; крест — отсутствие результата, его цвет показывает режим, и это не значение 0. Рисунок 3 показывает цену масштабирования: для FULL число вызовов, токены и время в этом четырёхточечном пилоте растут почти линейно с числом ФТ (`R² = 0,996 / 0,989 / 0,988`). Это свидетельство предсказуемого роста затрат, но не доказательство качества.",
            "",
            "![Статус по размерам](01_size_status_gost.png)",
            "",
            "![F1 по размерам](02_size_quality_gost.png)",
            "",
            "![Ресурсы по размерам](03_size_resources_gost.png)",
            "",
            "**Ограничение.** Здесь по одному проекту и одному запуску на размер, а Gold пока является candidate-разметкой, построенной только из входных требований. Эти данные пригодны как инженерный preflight; финальный вывод по качеству требует независимой проверки Gold и повторов.",
            "",
            "## 2. Анализ вклада компонентов",
            "",
            "| Конфигурация | Milestone F1 | Branch F1 | Trace F1 | Activity valid | E2E | Вызовы | Токены |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for condition in ("B1_ONESHOT", "FULL_NO_REPAIR", "FULL_NO_CRITIC", "FULL"):
        row = component_by[condition]
        lines.append(
            f"| {row['method_ru']} | {row['milestone_f1']:.3f} | {row['branch_f1']:.3f} | "
            f"{row['trace_f1']:.3f} | {row['activity_structural_validity']:.0%} | "
            f"{row['end_to_end_success']:.0%} | {row['llm_calls']:.1f} | {row['total_tokens']:.0f} |"
        )
    lines.extend(
        [
            "",
            "![Вклад компонентов](04_component_contribution_gost.png)",
            "",
            "Главный наблюдаемый эффект — необходимость ограниченного исправления: без него формальные дефекты остаются и E2E равен 0/3. Вариант без критика прошёл 3/3, как и FULL, поэтому утверждать, что критик сам по себе повышает E2E, нельзя. В этом пилоте критик связан с ростом Branch F1 с 0,500 до 0,690, но N = 3 и один повтор не позволяют считать различие доказанным.",
            "",
            "## 3. DeepSeek, GPT-5.5 и Claude Opus 5",
            "",
            "Общий кейс: `B1-DEV-002`; три независимых повтора каждого режима; одинаковые вход, целевая схема и evaluator.",
            "",
            "| Модель | Режим | Actor F1 | UC F1 | Milestone F1 | Branch F1 | Trace F1 | Activity valid | E2E | Цена/запуск |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for provider in ("DeepSeek", "OpenAI", "Anthropic"):
        for condition in ("B1_ONESHOT", "FULL"):
            row = cross_by[(provider, condition)]
            display_model = (
                "GPT-5.5"
                if provider == "OpenAI"
                else "Claude Opus 5"
                if provider == "Anthropic"
                else "DeepSeek"
            )
            lines.append(
                f"| {display_model} | {row['method_ru']} | {row['mean_actor_f1']:.3f} | "
                f"{row['mean_uc_f1']:.3f} | {row['mean_milestone_f1']:.3f} | "
                f"{row['mean_branch_f1']:.3f} | {row['mean_trace_f1']:.3f} | "
                f"{row['mean_activity_structural_validity']:.0%} | "
                f"{row['mean_end_to_end_success']:.0%} | ${row['mean_estimated_cost_usd']:.3f} |"
            )
    lines.extend(
        [
            "",
            "![Модели и режимы](05_cross_model_quality_gost.png)",
            "",
            "![Стоимость моделей](06_cross_model_cost_gost.png)",
            "",
            "**Интерпретация.** Полный граф не обязан повышать каждый F1 у уже сильной модели на простом кейсе. Его техническая ценность — контролируемая декомпозиция, явные связи, детерминированные gates и исправление конкретных дефектов. На DeepSeek это изменило E2E с 0/3 на 3/3; у GPT-5.5 оба режима дали 3/3, а Milestone F1 one-shot оказался выше; у Claude FULL повысил Milestone F1. Поэтому сильное заявление должно быть: граф повышает надёжность слабее контролируемых ответов и предоставляет проверяемую трассировку, но его содержательное преимущество зависит от модели и входа.",
            "",
            "## 4. Что ещё сравнивать",
            "",
            "1. **Основное доказательство:** one-shot и FULL одной модели на frozen DEV20 — уже выполнено для DeepSeek ×3.",
            "2. **Масштабирование:** после экспертной проверки candidate Gold выполнить одинаковые one-shot/FULL ×3 во всех четырёх группах. До этого не тратить бюджет на полный запуск.",
            "3. **Экспертная принимаемость:** два независимых эксперта вслепую оценивают полноту, корректность и читаемость; это нельзя заменить выдуманными числами или LLM-судьёй.",
            "4. **Валидаторы:** mutation-suite уже проверяет заранее внесённые структурные дефекты; это отдельное доказательство, что formal gates обнаруживают заявленные классы ошибок.",
            "5. **Pyreverse, GitDiagram, DeepWiki:** оставить в обзоре аналогов как системы с другим входом (`код/репозиторий → диаграмма`). Они не являются честным количественным baseline для задачи `требования → сценарии → Activity до кода`.",
            "",
            "### Как показать результаты на защите",
            "",
            "- На основной слайд: рисунок 4 (вклад компонентов) и одна крупная цифра `E2E: 0/3 без исправления → 3/3 с исправлением`.",
            "- Следующий слайд: рисунок 5 (три модели), чтобы показать переносимость и отсутствие заранее заданного победителя.",
            "- В резерв: рисунок 1 как матрицу завершения по 6/19/48/74 ФТ и рисунок 3 как цену масштабирования.",
            "- Рисунок 2 пока помечать как диагностический: размерный Gold ещё требует независимой экспертной проверки.",
            "",
            "## 5. Промпт и воспроизведение Claude",
            "",
            "- Полная инструкция и неизменяемый prompt: `experiments/claude_opus_5_dev20/00_CLAUDE_OPUS_5_RUNBOOK_AND_PROMPT_RU.md`.",
            "- Запуск собственного pipeline: `scripts/run_benchmark_experiment.py`.",
            "- Импорт и оценка внешних ответов Claude: `scripts/evaluate_external_model_outputs.py`.",
            "- Все три модели уже имеют реальные сохранённые one-shot и FULL прогоны на общем кейсе; повторный платный запуск этого же кейса не добавит нового доказательства.",
            "",
            "## 6. Методологическое основание",
            "",
            "- Zhang et al. (2026), *Large language models in model-driven engineering: a systematic mapping study*: рекомендуются явные baseline, версии моделей, prompts, логи, стоимость, воспроизводимость и artifact-sensitive criteria — полнота, согласованность, корректность, трассируемость и взаимодействие.",
            "- Ferrari, Abualhaija, Arora (2024): диаграммы из требований могут быть понятными и синтаксически корректными, но часто страдают по полноте и корректности, особенно при неоднозначных требованиях.",
            "- Giannouris, Ananiadou (2025), NOMAD: разделение генерации UML между специализированными агентами полезно для интерпретируемости и адресной проверки, но эффект verification может быть неоднозначным — поэтому компоненты нужно измерять отдельно.",
            "- Query2Diagram (2026): отделяет структурированное JSON-представление от рендера и оценивает структурные дефекты отдельно от смысловой релевантности; это поддерживает наш принцип typed model → validator → Mermaid, но задача статьи начинается с кода и запроса разработчика.",
            "",
            "## Файлы-источники",
            "",
            "- `artifacts/benchmark_runs/b1-dev20-r3-deepseek-flash-2026-09-13/results.json`",
            "- `artifacts/benchmark_runs/full-dev20-r3-deepseek-flash-2026-09-13/results.json`",
            "- `artifacts/benchmark_runs/component-comparison-dev3-deepseek-flash-2026-09-11/results.csv`",
            "- `artifacts/benchmark_runs/full-critic-v2-dev3-deepseek-flash-2026-09-11/results.csv`",
            "- `artifacts/three_model_generator_comparison_2026-09-13/`",
            "- `artifacts/claude_b1_full_pilot_2026-09-13/`",
            "- `artifacts/size_scaling_runs/size-scaling-gold-preflight-*`",
            "",
        ]
    )
    (OUTPUT / "ANALYSIS_RU.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    _configure_matplotlib()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    size_rows = _prepare_size_rows()
    component_rows = _prepare_component_rows()
    cross_model_rows = _prepare_cross_model_rows()
    _write_csv(OUTPUT / "size_scaling_6_19_48_74.csv", size_rows)
    _write_csv(OUTPUT / "component_contribution.csv", component_rows)
    _write_csv(OUTPUT / "cross_model_comparison.csv", cross_model_rows)
    _plot_size_status(size_rows)
    _plot_size_quality(size_rows)
    _plot_size_resources(size_rows)
    _plot_component_contribution(component_rows)
    _plot_cross_model(cross_model_rows)
    _plot_cross_model_cost(cross_model_rows)
    _write_report(size_rows, component_rows, cross_model_rows)
    manifest = {
        "created_from_saved_results": True,
        "paid_llm_calls_performed_by_builder": 0,
        "excluded_from_main_analysis": [
            "B0_RULE",
            "semantic_composite",
            "LLM-as-a-judge",
            "Pyreverse as a direct baseline",
        ],
        "files": sorted(path.name for path in OUTPUT.iterdir()),
    }
    (OUTPUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
