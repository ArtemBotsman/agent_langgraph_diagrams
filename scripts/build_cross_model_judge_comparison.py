"""Build a minimal DeepSeek vs GPT-5.5 judge comparison for SCALE-003."""

from __future__ import annotations

import html
import json
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "artifacts" / "llm_judge_runs"
OUTPUT = ROOT / "artifacts" / "cross_model_judge_comparison_2026-09-13"

RUNS_BY_METHOD = {
    "B0_RULE": {
        "DeepSeek": "deepseek-b0-size-pilot-r2-v2-2026-09-13",
        "GPT-5.5": "gpt55-b0-size003-low-r1-v2-2026-09-13",
    },
    "B1_ONESHOT": {
        "DeepSeek": "deepseek-b1-size003-judge-r2-2026-09-13",
        "GPT-5.5": "gpt55-b1-size003-low-r1-v2-2026-09-13",
    },
    "FULL": {
        "DeepSeek": "deepseek-full-size003-judge-r2-v2-2026-09-13",
        "GPT-5.5": "gpt55-full-size003-low-r1-v2-2026-09-13",
    },
}
E2E = {"B0_RULE": True, "B1_ONESHOT": False, "FULL": True}
COLORS = {"DeepSeek": "#287A78", "GPT-5.5": "#6256A5"}


def _load_rows(run_name: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    data = json.loads((RUNS / run_name / "results.json").read_text(encoding="utf-8"))
    rows = [row for row in data["rows"] if row.get("case_id") == "SCALE-003"]
    if not rows:
        raise ValueError(f"SCALE-003 is absent in {run_name}")
    return data["config"], rows


def _collect() -> dict[str, Any]:
    methods: list[dict[str, Any]] = []
    for method, judge_runs in RUNS_BY_METHOD.items():
        item: dict[str, Any] = {"method": method, "formal_e2e": E2E[method]}
        candidate_hashes: set[str] = set()
        for judge, run_name in judge_runs.items():
            config, rows = _load_rows(run_name)
            valid = [row for row in rows if row.get("status") == "success"]
            if not valid:
                raise ValueError(f"No valid judgments in {run_name}")
            candidate_hashes.update(str(row["candidate_sha256"]) for row in valid)
            item[judge] = {
                "score": mean(float(row["overall_score_0_1"]) for row in valid),
                "repeats": len(valid),
                "model": str(config["judge_model"]),
                "run": run_name,
            }
        if len(candidate_hashes) != 1:
            raise ValueError(f"Judges did not receive the same {method} candidate")
        item["candidate_sha256"] = next(iter(candidate_hashes))
        methods.append(item)

    rank_deepseek = sorted(methods, key=lambda item: item["DeepSeek"]["score"])
    rank_gpt = sorted(methods, key=lambda item: item["GPT-5.5"]["score"])
    same_order = [item["method"] for item in rank_deepseek] == [item["method"] for item in rank_gpt]
    mean_abs_difference = mean(
        abs(item["DeepSeek"]["score"] - item["GPT-5.5"]["score"]) for item in methods
    )
    return {
        "scope": "SCALE-003; same saved candidates; method-blinded pointwise judging",
        "methods": methods,
        "same_method_order": same_order,
        "mean_absolute_score_difference": mean_abs_difference,
        "claim_limit": (
            "One case, DeepSeek n=2 and GPT-5.5 n=1 per candidate; descriptive "
            "cross-judge pilot, not a generator comparison or final statistic."
        ),
    }


def _svg(result: dict[str, Any]) -> str:
    width, height = 1400, 790
    chart_left, chart_right = 315, 1060
    row_y = {"B0_RULE": 235, "B1_ONESHOT": 365, "FULL": 495}
    chunks = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
            f'height="{height}" viewBox="0 0 {width} {height}">'
        ),
        '<rect width="1400" height="790" fill="#ffffff"/>',
        "<style>text{font-family:Arial,sans-serif;fill:#172433}.title{font-size:34px;font-weight:700}.sub{font-size:18px;fill:#5b6877}.method{font-size:19px;font-weight:700}.axis{font-size:14px;fill:#6a7684}.value{font-size:16px;font-weight:700}.legend{font-size:16px}.gate{font-size:16px;font-weight:700}.take{font-size:22px;font-weight:700}.body{font-size:17px;fill:#334252}.small{font-size:14px;fill:#677483}</style>",
        '<text x="64" y="58" class="title">Один результат — два независимых LLM-судьи</text>',
        (
            '<text x="64" y="91" class="sub">SCALE-003 · одинаковые '
            "B0/B1/FULL-кандидаты · шкала смыслового качества 0–1</text>"
        ),
        '<circle cx="69" cy="133" r="8" fill="#287A78"/>',
        '<text x="87" y="139" class="legend">DeepSeek deepseek-flash · 2 повтора</text>',
        '<circle cx="398" cy="133" r="8" fill="#6256A5"/>',
        '<text x="416" y="139" class="legend">GPT-5.5-2026-04-23 · 1 повтор</text>',
        '<text x="1165" y="139" text-anchor="middle" class="legend">Формальный E2E</text>',
        f'<line x1="{chart_left}" y1="180" x2="{chart_right}" y2="180" stroke="#c8d0d8"/>',
    ]

    for tick in range(0, 11, 2):
        value = tick / 10
        x = chart_left + (chart_right - chart_left) * value
        chunks.extend(
            [
                f'<line x1="{x:.1f}" y1="180" x2="{x:.1f}" y2="545" stroke="#e6eaee"/>',
                f'<text x="{x:.1f}" y="170" text-anchor="middle" class="axis">{value:.1f}</text>',
            ]
        )

    for item in result["methods"]:
        method = str(item["method"])
        y = row_y[method]
        chunks.extend(
            [
                f'<text x="64" y="{y + 6}" class="method">{html.escape(method)}</text>',
                (
                    f'<line x1="{chart_left}" y1="{y}" x2="{chart_right}" '
                    f'y2="{y}" stroke="#cfd6dd" stroke-width="3"/>'
                ),
            ]
        )
        for judge, offset in (("DeepSeek", -14), ("GPT-5.5", 14)):
            score = float(item[judge]["score"])
            x = chart_left + (chart_right - chart_left) * score
            chunks.extend(
                [
                    f'<circle cx="{x:.1f}" cy="{y + offset}" r="9" fill="{COLORS[judge]}"/>',
                    f'<text x="{x + 17:.1f}" y="{y + offset + 6}" class="value">{score:.3f}</text>',
                ]
            )
        passed = bool(item["formal_e2e"])
        gate_color = "#2F7D5A" if passed else "#B34C4C"
        gate_text = "PASS" if passed else "FAIL"
        chunks.extend(
            [
                f'<rect x="1112" y="{y - 21}" width="106" height="42" rx="6" fill="{gate_color}"/>',
                (
                    f'<text x="1165" y="{y + 6}" text-anchor="middle" '
                    'fill="#ffffff" style="font:700 16px Arial,sans-serif">'
                    f"{gate_text}</text>"
                ),
            ]
        )

    chunks.extend(
        [
            '<line x1="64" y1="600" x2="1336" y2="600" stroke="#c8d0d8"/>',
            (
                '<text x="64" y="644" class="take">Обе модели согласились с '
                "порядком: B0 &lt; B1 &lt; FULL</text>"
            ),
            (
                '<text x="64" y="680" class="body">Только FULL одновременно '
                "получил высокий смысловой балл и прошёл "
                "schema/structure/trace gate.</text>"
            ),
            (
                '<text x="64" y="713" class="body">B1 выглядит содержательно '
                "сильным, но формально отклонён: неполная трассировка и "
                "структурный дефект Activity.</text>"
            ),
            (
                '<text x="64" y="758" class="small">Ограничение: один проект; '
                "это сравнение судей, а не генерации DeepSeek против GPT-5.5. "
                "Среднее |расхождение| оценок = 0,044.</text>"
            ),
            "</svg>",
        ]
    )
    return "\n".join(chunks) + "\n"


def main() -> None:
    result = _collect()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    OUTPUT.joinpath("comparison.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    svg = _svg(result)
    OUTPUT.joinpath("deepseek_gpt55_judge_comparison.svg").write_text(svg, encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
