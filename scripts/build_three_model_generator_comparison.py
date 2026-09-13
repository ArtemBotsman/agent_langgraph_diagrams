"""Build a reproducible three-model comparison for the shared DEV case."""

# Long inline SVG fragments are intentionally kept readable and reproducible.
# ruff: noqa: E501

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "three_model_generator_comparison_2026-09-13"
VAULT_ASSET = (
    ROOT
    / "docs"
    / "obsidian_vault"
    / "assets"
    / "30_three_model_generator_comparison.svg"
)
CASE_ID = "B1-DEV-002"

SOURCES = [
    {
        "provider": "DeepSeek",
        "model": "deepseek-flash",
        "method": "B1_ONESHOT",
        "path": ROOT
        / "artifacts"
        / "benchmark_runs"
        / "b1-dev20-r3-deepseek-flash-2026-09-13"
        / "results.json",
    },
    {
        "provider": "DeepSeek",
        "model": "deepseek-flash",
        "method": "FULL",
        "path": ROOT
        / "artifacts"
        / "benchmark_runs"
        / "full-dev20-r3-deepseek-flash-2026-09-13"
        / "results.json",
    },
    {
        "provider": "OpenAI",
        "model": "gpt-5.5-2026-04-23",
        "method": "B1_ONESHOT",
        "path": ROOT
        / "artifacts"
        / "external_model_runs"
        / "external-gpt55-oneshot-dev002-r3-2026-09-13"
        / "results.json",
    },
    {
        "provider": "OpenAI",
        "model": "gpt-5.5-2026-04-23",
        "method": "FULL",
        "path": ROOT
        / "artifacts"
        / "benchmark_runs"
        / "full-gpt55-dev002-r3-combined-2026-09-13"
        / "results.json",
    },
    {
        "provider": "Anthropic",
        "model": "claude-opus-5",
        "method": "B1_ONESHOT",
        "path": ROOT
        / "artifacts"
        / "external_model_runs"
        / "external-claude-opus5-oneshot-dev002-r3-2026-09-13"
        / "results.json",
    },
    {
        "provider": "Anthropic",
        "model": "claude-opus-5",
        "method": "FULL",
        "path": ROOT
        / "artifacts"
        / "benchmark_runs"
        / "full-claude-opus5-dev002-r3-combined-2026-09-13"
        / "results.json",
    },
]

COLORS = {"DeepSeek": "#23847C", "OpenAI": "#6256A5", "Anthropic": "#D9772F"}


def _number(row: dict[str, Any], key: str) -> float:
    value = row.get(key)
    return float(value) if value is not None else 0.0


def _collect() -> dict[str, Any]:
    configurations: list[dict[str, Any]] = []
    for source in SOURCES:
        source_path = source["path"]
        if not isinstance(source_path, Path):
            raise TypeError("Comparison source path must be a pathlib.Path")
        data = json.loads(source_path.read_text(encoding="utf-8"))
        rows = [
            row
            for row in data["rows"]
            if row.get("case_id") == CASE_ID
            and str(row.get("condition", "")).endswith(str(source["method"]))
        ]
        if source["method"] == "B1_ONESHOT" and not rows:
            rows = [
                row
                for row in data["rows"]
                if row.get("case_id") == CASE_ID
                and "ONESHOT" in str(row.get("condition", ""))
            ]
        if len(rows) != 3:
            raise ValueError(
                f"Expected exactly three {CASE_ID} rows for {source['provider']} "
                f"{source['method']}, found {len(rows)}"
            )
        semantic = [_number(row, "semantic_composite") for row in rows]
        e2e = [_number(row, "end_to_end_success") for row in rows]
        item = {
            "provider": source["provider"],
            "model": source["model"],
            "method": source["method"],
            "case_id": CASE_ID,
            "repeats": len(rows),
            "semantic_values": semantic,
            "semantic_mean": mean(semantic),
            "semantic_stddev": pstdev(semantic),
            "formal_e2e_passes": int(sum(e2e)),
            "formal_e2e_rate": mean(e2e),
            "stability": mean(_number(row, "stability_multi_run") for row in rows),
            "mean_latency_seconds": mean(_number(row, "latency_ms") for row in rows)
            / 1000,
            "total_tokens": int(sum(_number(row, "total_tokens") for row in rows)),
            "total_estimated_cost_usd": sum(
                _number(row, "estimated_cost_usd") for row in rows
            ),
            "mean_llm_calls": mean(_number(row, "llm_calls") for row in rows),
            "mean_repairs": mean(_number(row, "repair_attempts") for row in rows),
            "source_results": source_path.relative_to(ROOT).as_posix(),
        }
        configurations.append(item)
    return {
        "experiment_scope": (
            "Generator comparison on the same simple development case B1-DEV-002; "
            "three independent repeats per displayed configuration"
        ),
        "case_id": CASE_ID,
        "configurations": configurations,
        "interpretation": [
            "All three direct-model variants are compared under the same prompt, schema, input and evaluator.",
            "DeepSeek B1 is semantically competitive but fails the formal E2E gate; DeepSeek FULL repairs the contract and passes 3/3.",
            "GPT-5.5 B1 passes 3/3 and has the highest semantic mean on this simple case; its FULL graph is slower and more expensive without a semantic gain here.",
            "Claude Opus 5 passes 3/3 in both modes; FULL raises the semantic mean mainly through better milestone coverage while preserving high stability.",
        ],
        "claim_limit": (
            "Descriptive pilot on one simple DEV case, not final statistical evidence. "
            "The result motivates the next preregistered comparison on a medium DEV case."
        ),
    }


def _svg(result: dict[str, Any]) -> str:
    width, height = 1500, 900
    left, right = 550, 1120
    rows = result["configurations"]
    row_ys = [240, 330, 420, 510, 600, 690]
    chunks = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="1500" height="900" fill="#ffffff"/>',
        '<style>text{font-family:Arial,sans-serif;fill:#172433}.title{font-size:36px;font-weight:700}.sub{font-size:18px;fill:#5c6876}.label{font-size:20px;font-weight:700}.model{font-size:15px;fill:#657282}.axis{font-size:14px;fill:#6b7683}.value{font-size:17px;font-weight:700}.small{font-size:14px;fill:#657282}.take{font-size:19px;font-weight:700}</style>',
        '<text x="70" y="62" class="title">DeepSeek / GPT-5.5 / Claude — три повтора генерации</text>',
        '<text x="70" y="98" class="sub">B1-DEV-002 · одинаковый SpecificationReq, prompt, JSON Schema и evaluator</text>',
        '<circle cx="75" cy="144" r="8" fill="#23847C"/><text x="94" y="151" class="sub">DeepSeek</text>',
        '<circle cx="245" cy="144" r="8" fill="#6256A5"/><text x="264" y="151" class="sub">GPT-5.5</text>',
        '<circle cx="405" cy="144" r="8" fill="#D9772F"/><text x="424" y="151" class="sub">Claude Opus 5</text>',
        '<text x="835" y="151" text-anchor="middle" class="sub">Semantic composite (смысловой балл)</text>',
        '<text x="1235" y="151" text-anchor="middle" class="sub">Formal E2E</text>',
        '<text x="1395" y="151" text-anchor="middle" class="sub">Время / цена</text>',
    ]
    for value in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
        x = left + (right - left) * value
        chunks.extend(
            [
                f'<line x1="{x:.1f}" y1="175" x2="{x:.1f}" y2="720" stroke="#e6eaee"/>',
                f'<text x="{x:.1f}" y="178" text-anchor="middle" class="axis">{value:.1f}</text>',
            ]
        )
    for item, y in zip(rows, row_ys, strict=True):
        provider = str(item["provider"])
        color = COLORS[provider]
        method_label = "B1 — один вызов" if item["method"] == "B1_ONESHOT" else "FULL — полный граф"
        label = f"{provider} · {method_label}"
        chunks.extend(
            [
                f'<text x="70" y="{y - 4}" class="label">{html.escape(label)}</text>',
                f'<text x="70" y="{y + 22}" class="model">{html.escape(str(item["model"]))} · n=3</text>',
                f'<line x1="{left}" y1="{y}" x2="{right}" y2="{y}" stroke="#cfd6dd" stroke-width="3"/>',
            ]
        )
        values = [float(value) for value in item["semantic_values"]]
        for idx, value in enumerate(values):
            x = left + (right - left) * value
            chunks.append(
                f'<circle cx="{x:.1f}" cy="{y + (idx - 1) * 13}" r="5" fill="{color}" opacity="0.48"/>'
            )
        score = float(item["semantic_mean"])
        score_x = left + (right - left) * score
        chunks.extend(
            [
                f'<circle cx="{score_x:.1f}" cy="{y}" r="10" fill="{color}" stroke="#ffffff" stroke-width="3"/>',
                f'<text x="{score_x + 18:.1f}" y="{y + 6}" class="value">{score:.3f} ± {float(item["semantic_stddev"]):.3f}</text>',
            ]
        )
        passed = int(item["formal_e2e_passes"])
        badge = "#2F7D5A" if passed == 3 else "#B34C4C"
        chunks.extend(
            [
                f'<rect x="1185" y="{y - 22}" width="100" height="44" rx="7" fill="{badge}"/>',
                f'<text x="1235" y="{y + 7}" text-anchor="middle" fill="#ffffff" style="font:700 18px Arial,sans-serif">{passed}/3</text>',
                f'<text x="1320" y="{y - 3}" class="small">{float(item["mean_latency_seconds"]):.1f} s</text>',
                f'<text x="1320" y="{y + 21}" class="small">${float(item["total_estimated_cost_usd"]):.3f} / 3</text>',
            ]
        )
    chunks.extend(
        [
            '<line x1="70" y1="755" x2="1430" y2="755" stroke="#c8d0d8"/>',
            '<text x="70" y="797" class="take">Вывод пилота: эффект полного графа зависит от модели даже на одном и том же простом входе.</text>',
            '<text x="70" y="832" class="sub">FULL исправляет E2E у DeepSeek, улучшает смысловой балл Claude и не даёт выигрыша GPT-5.5 на этом кейсе.</text>',
            '<text x="70" y="869" class="small">Ограничение: один простой DEV-кейс. Это генерации ×3, а не старое сравнение LLM-судей 2×/1×.</text>',
            "</svg>",
        ]
    )
    return "\n".join(chunks) + "\n"


def _write_csv(result: dict[str, Any]) -> None:
    fields = [
        "provider",
        "model",
        "method",
        "case_id",
        "repeats",
        "semantic_mean",
        "semantic_stddev",
        "formal_e2e_passes",
        "formal_e2e_rate",
        "stability",
        "mean_latency_seconds",
        "total_tokens",
        "total_estimated_cost_usd",
        "mean_llm_calls",
        "mean_repairs",
        "source_results",
    ]
    with (OUTPUT / "comparison.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in result["configurations"]:
            writer.writerow({field: item[field] for field in fields})


def _write_markdown(result: dict[str, Any]) -> None:
    lines = [
        "# Сравнение DeepSeek, GPT-5.5 и Claude Opus 5",
        "",
        "Все строки относятся к одному простому кейсу `B1-DEV-002`. Для каждой показанной конфигурации выполнено ровно три независимых запуска.",
        "",
        "| Модель и режим | Повторы | Formal E2E | Semantic, mean ± SD | Stability | Среднее время | Токены, всего | Цена, всего |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in result["configurations"]:
        lines.append(
            "| "
            f"{item['provider']} {item['model']} · {item['method']} | "
            f"{item['repeats']} | {item['formal_e2e_passes']}/3 | "
            f"{item['semantic_mean']:.3f} ± {item['semantic_stddev']:.3f} | "
            f"{item['stability']:.3f} | {item['mean_latency_seconds']:.1f} s | "
            f"{item['total_tokens']:,} | ${item['total_estimated_cost_usd']:.3f} |"
        )
    lines.extend(
        [
            "",
            "## Как читать результат",
            "",
            "- `B1_ONESHOT` (один прямой вызов): одна модель сразу формирует весь комплект артефактов.",
            "- `FULL` (полный граф): два агентных подграфа, детерминированные проверки и ограниченное исправление.",
            "- `Formal E2E` (формальное сквозное прохождение): схема, структура Activity, Mermaid и трассировка одновременно прошли обязательные проверки.",
            "- `Semantic` (смысловой балл): соответствие gold-разметке по акторам, UC, этапам сценария, ветвлениям и трассировке.",
            "- `Stability` (устойчивость): сходство трёх повторов между собой; ближе к 1 — меньше разброс.",
            "",
            "## Вывод",
            "",
            "На этом простом кейсе GPT-5.5 B1 имеет наибольший средний смысловой балл и проходит E2E 3/3. Claude проходит 3/3 в обоих режимах, а FULL повышает его смысловой балл с 0,668 до 0,719 главным образом за счёт более полного сценария. DeepSeek B1 получает близкий смысловой балл, но не проходит формальный gate; FULL устраняет дефекты и даёт 3/3. Для GPT-5.5 FULL не дал выигрыша качества на простом входе, зато потребовал больше вызовов, токенов и времени. Это аргумент исследовать зависимость пользы графа от модели и сложности проекта, а не утверждение, что один метод всегда лучше.",
            "",
            "## Почему старый рисунок показывал 2 и 1",
            "",
            "Старый рисунок `29_deepseek_gpt55_judge_comparison` относится к другому эксперименту: один сохранённый результат оценивали два раза DeepSeek и один раз GPT-5.5 как LLM-судьи. Он не измерял три независимые генерации. Новый рисунок ниже относится именно к генерациям и показывает `n=3` у каждой строки.",
            "",
            "## Ограничение",
            "",
            result["claim_limit"],
            "",
            "![Три модели — три повтора](../../docs/obsidian_vault/assets/30_three_model_generator_comparison.svg)",
            "",
        ]
    )
    (OUTPUT / "REPORT_RU.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    result = _collect()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    OUTPUT.joinpath("comparison.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _write_csv(result)
    _write_markdown(result)
    svg = _svg(result)
    OUTPUT.joinpath("three_model_generator_comparison.svg").write_text(
        svg, encoding="utf-8"
    )
    VAULT_ASSET.parent.mkdir(parents=True, exist_ok=True)
    VAULT_ASSET.write_text(svg, encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
