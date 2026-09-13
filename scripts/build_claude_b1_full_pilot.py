"""Build the saved Claude B1 versus FULL pilot summary and visual evidence."""

# Long inline SVG and Markdown fragments are kept readable and reproducible.
# ruff: noqa: E501

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "claude_b1_full_pilot_2026-09-13"
VAULT_ASSET = ROOT / "docs" / "obsidian_vault" / "assets" / "31_claude_b1_full_pilot.svg"

SOURCES = [
    {
        "case_id": "B1-DEV-002",
        "complexity": "simple",
        "method": "B1_ONESHOT",
        "path": ROOT
        / "artifacts/external_model_runs/external-claude-opus5-oneshot-dev002-r3-2026-09-13/results.json",
    },
    {
        "case_id": "B1-DEV-002",
        "complexity": "simple",
        "method": "FULL",
        "path": ROOT
        / "artifacts/benchmark_runs/full-claude-opus5-dev002-r3-combined-2026-09-13/results.json",
    },
    {
        "case_id": "B1-DEV-010",
        "complexity": "medium",
        "method": "B1_ONESHOT",
        "path": ROOT
        / "artifacts/external_model_runs/external-claude-opus5-oneshot-dev010-r3-2026-09-13/results.json",
    },
    {
        "case_id": "B1-DEV-010",
        "complexity": "medium",
        "method": "FULL",
        "path": ROOT
        / "artifacts/benchmark_runs/full-claude-opus5-dev010-r3-combined-2026-09-13/results.json",
    },
]

METRICS = (
    "actor_f1",
    "uc_f1",
    "milestone_f1",
    "branch_f1",
    "trace_f1",
    "semantic_composite",
    "hallucination_rate",
    "end_to_end_success",
    "latency_ms",
    "total_tokens",
    "estimated_cost_usd",
    "llm_calls",
    "repair_attempts",
)


def _value(row: dict[str, Any], key: str) -> float:
    value = row.get(key)
    return float(value) if value is not None else 0.0


def _collect() -> dict[str, Any]:
    rows_out: list[dict[str, Any]] = []
    for source in SOURCES:
        source_path = source["path"]
        if not isinstance(source_path, Path):
            raise TypeError("Pilot source path must be a pathlib.Path")
        data = json.loads(source_path.read_text(encoding="utf-8"))
        rows = [row for row in data["rows"] if row.get("case_id") == source["case_id"]]
        if not rows:
            raise ValueError(f"No rows found for {source['case_id']} in {source['path']}")
        item: dict[str, Any] = {
            "case_id": source["case_id"],
            "complexity": source["complexity"],
            "method": source["method"],
            "repeats": len(rows),
            "source_results": source_path.relative_to(ROOT).as_posix(),
        }
        for metric in METRICS:
            values = [_value(row, metric) for row in rows]
            item[f"mean_{metric}"] = mean(values)
            item[f"stddev_{metric}"] = pstdev(values) if len(values) > 1 else None
        stability = [_value(row, "stability_multi_run") for row in rows]
        item["mean_stability_multi_run"] = mean(stability) if len(rows) > 1 else None
        rows_out.append(item)
    return {
        "experiment": "Claude Opus 5: B1_ONESHOT versus FULL",
        "model": "claude-opus-5",
        "created_from_saved_results": True,
        "rows": rows_out,
        "decision": (
            "Do not start the full paid benchmark yet. The simple case favors FULL, "
            "and the medium repeated series strongly favors FULL on E2E reliability. "
            "Do not scale to the full paid benchmark before preregistering its budget."
        ),
    }


def _write_csv(result: dict[str, Any]) -> None:
    fields = sorted({key for row in result["rows"] for key in row})
    with (OUTPUT / "comparison.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(result["rows"])


def _write_report(result: dict[str, Any]) -> None:
    lines = [
        "# Claude Opus 5: B1_ONESHOT и FULL",
        "",
        "Все значения рассчитаны одним evaluator по сохранённым результатам без ручного исправления ответов.",
        "",
        "| Кейс | Сложность | Метод | n | E2E | Semantic | Actor F1 | UC F1 | Milestone F1 | Branch F1 | Trace F1 | Лишние элементы | Токены | Цена | Время |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in result["rows"]:
        semantic_sd = row["stddev_semantic_composite"]
        semantic = f"{row['mean_semantic_composite']:.3f}"
        if semantic_sd is not None:
            semantic += f" ± {semantic_sd:.3f}"
        lines.append(
            f"| {row['case_id']} | {row['complexity']} | {row['method']} | {row['repeats']} | "
            f"{row['mean_end_to_end_success']:.0%} | {semantic} | "
            f"{row['mean_actor_f1']:.3f} | {row['mean_uc_f1']:.3f} | "
            f"{row['mean_milestone_f1']:.3f} | {row['mean_branch_f1']:.3f} | "
            f"{row['mean_trace_f1']:.3f} | {row['mean_hallucination_rate']:.3f} | "
            f"{row['mean_total_tokens']:.0f} | ${row['mean_estimated_cost_usd']:.3f} | "
            f"{row['mean_latency_ms'] / 1000:.1f} s |"
        )
    lines.extend(
        [
            "",
            "## Интерпретация",
            "",
            "- На простом B1-DEV-002 FULL повысил semantic с 0,668 до 0,719, главным образом за счёт Milestone F1.",
            "- На среднем B1-DEV-010 one-shot прошёл E2E только 1/3, FULL — 3/3; semantic составил 0,700 против 0,749.",
            "- FULL повысил stability с 0,869 до 0,994 и уменьшил proxy лишних элементов с 0,511 до 0,389, но потребовал больше вызовов и токенов.",
            "- Средняя серия завершена. Полный платный benchmark запускается только после предварительной фиксации выборки, бюджета и правила остановки.",
            "",
            "![Claude B1 и FULL](../../docs/obsidian_vault/assets/31_claude_b1_full_pilot.svg)",
            "",
        ]
    )
    (OUTPUT / "REPORT_RU.md").write_text("\n".join(lines), encoding="utf-8")


def _svg(result: dict[str, Any]) -> str:
    width, height = 1440, 820
    rows = result["rows"]
    row_ys = [245, 345, 505, 605]
    left, right = 530, 1050
    colors = {"B1_ONESHOT": "#6574C4", "FULL": "#D9772F"}
    chunks = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="1440" height="820" fill="#ffffff"/>',
        '<style>text{font-family:Arial,sans-serif;fill:#172433}.title{font-size:35px;font-weight:700}.sub{font-size:18px;fill:#5c6876}.section{font-size:22px;font-weight:700}.label{font-size:19px;font-weight:700}.small{font-size:14px;fill:#64717e}.value{font-size:17px;font-weight:700}.take{font-size:18px;font-weight:700}</style>',
        '<text x="65" y="58" class="title">Claude Opus 5: один вызов и полный граф</text>',
        '<text x="65" y="94" class="sub">Одинаковые вход, контракт и evaluator · по три независимых повтора каждого режима</text>',
        '<circle cx="70" cy="137" r="8" fill="#6574C4"/><text x="90" y="144" class="sub">B1 — один прямой вызов</text>',
        '<circle cx="330" cy="137" r="8" fill="#D9772F"/><text x="350" y="144" class="sub">FULL — полный граф</text>',
        '<text x="790" y="144" text-anchor="middle" class="sub">Semantic composite (смысловой балл)</text>',
        '<text x="1150" y="144" text-anchor="middle" class="sub">E2E / Milestone F1</text>',
        '<text x="65" y="195" class="section">B1-DEV-002 · простой</text>',
        '<text x="65" y="455" class="section">B1-DEV-010 LabSlot · средний</text>',
    ]
    for value in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
        x = left + (right - left) * value
        chunks.extend(
            [
                f'<line x1="{x:.1f}" y1="175" x2="{x:.1f}" y2="650" stroke="#e5e9ed"/>',
                f'<text x="{x:.1f}" y="168" text-anchor="middle" class="small">{value:.1f}</text>',
            ]
        )
    for row, y in zip(rows, row_ys, strict=True):
        method = str(row["method"])
        color = colors[method]
        label = "B1 — один вызов" if method == "B1_ONESHOT" else "FULL — полный граф"
        score = float(row["mean_semantic_composite"])
        x = left + (right - left) * score
        n = int(row["repeats"])
        sd = row["stddev_semantic_composite"]
        score_text = f"{score:.3f}" if sd is None else f"{score:.3f} ± {float(sd):.3f}"
        e2e = float(row["mean_end_to_end_success"])
        milestone = float(row["mean_milestone_f1"])
        chunks.extend(
            [
                f'<text x="65" y="{y - 5}" class="label">{html.escape(label)}</text>',
                f'<text x="65" y="{y + 22}" class="small">n={n} · {float(row["mean_llm_calls"]):.1f} выз. · ${float(row["mean_estimated_cost_usd"]):.3f}/запуск</text>',
                f'<line x1="{left}" y1="{y}" x2="{right}" y2="{y}" stroke="#cfd6dd" stroke-width="3"/>',
                f'<circle cx="{x:.1f}" cy="{y}" r="11" fill="{color}" stroke="#ffffff" stroke-width="3"/>',
                f'<text x="{x + 18:.1f}" y="{y + 6}" class="value">{score_text}</text>',
                f'<text x="1085" y="{y - 3}" class="small">E2E {e2e:.0%}</text>',
                f'<text x="1085" y="{y + 22}" class="small">Milestone {milestone:.3f}</text>',
            ]
        )
    chunks.extend(
        [
            '<line x1="65" y1="700" x2="1375" y2="700" stroke="#cbd2d9"/>',
            '<text x="65" y="741" class="take">Вывод: эффект FULL не универсален — он зависит от модели и сложности конкретного входа.</text>',
            '<text x="65" y="775" class="sub">На среднем кейсе B1 прошёл E2E 1/3, FULL — 3/3; полный платный benchmark требует отдельной фиксации бюджета.</text>',
            '</svg>',
        ]
    )
    return "\n".join(chunks) + "\n"


def main() -> None:
    result = _collect()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "comparison.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _write_csv(result)
    _write_report(result)
    svg = _svg(result)
    (OUTPUT / "claude_b1_full_pilot.svg").write_text(svg, encoding="utf-8")
    VAULT_ASSET.parent.mkdir(parents=True, exist_ok=True)
    VAULT_ASSET.write_text(svg, encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
