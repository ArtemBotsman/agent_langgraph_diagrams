"""Build auditable tables and figures for the technological-project presentation."""

# SVG templates are intentionally kept as readable, single-line XML elements.
# ruff: noqa: E501

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "technology_project_evidence_2026-09-11"

BEFORE_PATH = (
    ROOT
    / "artifacts"
    / "benchmark_runs"
    / "component-comparison-dev3-deepseek-flash-2026-09-11"
    / "results.json"
)
AFTER_FULL_PATH = (
    ROOT
    / "artifacts"
    / "benchmark_runs"
    / "full-critic-v2-dev3-deepseek-flash-2026-09-11"
    / "results.json"
)
B0_PATH = (
    ROOT
    / "artifacts"
    / "benchmark_runs"
    / "b0-dev3-comparison-2026-09-11"
    / "results.json"
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _rows(data: dict[str, Any], condition: str) -> list[dict[str, Any]]:
    return [row for row in data["rows"] if row["condition"] == condition]


def _summarize(label: str, rows: list[dict[str, Any]], note: str) -> dict[str, Any]:
    def avg(key: str) -> float:
        return mean(float(row.get(key) or 0.0) for row in rows)

    return {
        "method": label,
        "case_count": len({str(row["case_id"]) for row in rows}),
        "run_count": len(rows),
        "e2e_success": avg("end_to_end_success"),
        "semantic_composite": avg("semantic_composite"),
        "actor_f1": avg("actor_f1"),
        "uc_f1": avg("uc_f1"),
        "milestone_f1": avg("milestone_f1"),
        "branch_f1": avg("branch_f1"),
        "trace_f1": avg("trace_f1"),
        "hallucination_rate": avg("hallucination_rate"),
        "mean_latency_seconds": avg("latency_ms") / 1000,
        "mean_llm_calls": avg("llm_calls"),
        "mean_tokens": avg("total_tokens"),
        "mean_cost_usd": avg("estimated_cost_usd"),
        "mean_repairs": avg("repair_attempts"),
        "note": note,
    }


def _bar(x: float, y: float, w: float, value: float, color: str) -> str:
    height = 205 * max(0.0, min(1.0, value))
    return (
        f'<rect x="{x}" y="{y + 205 - height:.1f}" width="{w}" '
        f'height="{height:.1f}" rx="5" fill="{color}"/>'
    )


def _write_quality_svg(rows: list[dict[str, Any]], path: Path) -> None:
    colors = ["#6b7280", "#e7792b", "#169873", "#3a67b1", "#9f4c6d"]
    short = ["B0", "B1", "FULL", "без критика", "без исправления"]
    groups = [
        ("Завершение E2E", "e2e_success"),
        ("Содержание", "semantic_composite"),
        ("Ветвления F1", "branch_f1"),
        ("Трассировка F1", "trace_f1"),
    ]
    items: list[str] = []
    for group_index, (title, key) in enumerate(groups):
        gx = 78 + group_index * 285
        items.append(
            f'<text x="{gx + 112}" y="342" text-anchor="middle" '
            f'font-family="Arial" font-size="15" fill="#23313f">{title}</text>'
        )
        for index, row in enumerate(rows):
            value = float(row[key])
            x = gx + index * 45
            items.append(_bar(x, 102, 33, value, colors[index]))
            items.append(
                f'<text x="{x + 16.5}" y="{296 - value * 205:.1f}" '
                f'text-anchor="middle" font-family="Arial" font-size="10" '
                f'font-weight="700" fill="#17212b">{value:.0%}</text>'
            )
    legend = "".join(
        f'<rect x="{80 + index * 210}" y="58" width="14" height="14" rx="2" '
        f'fill="{colors[index]}"/><text x="{101 + index * 210}" y="70" '
        f'font-family="Arial" font-size="13" fill="#344250">{label}</text>'
        for index, label in enumerate(short)
    )
    details = "".join(
        f'<text x="80" y="{395 + index * 26}" font-family="Arial" font-size="14" '
        f'fill="#23313f"><tspan font-weight="700">{short[index]}:</tspan> '
        f'{row["mean_llm_calls"]:.1f} выз.; {row["mean_tokens"]:.0f} ток.; '
        f'{row["mean_latency_seconds"]:.1f} с; ${row["mean_cost_usd"]:.4f}/запуск</text>'
        for index, row in enumerate(rows)
    )
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1240" height="560">
<rect width="1240" height="560" fill="#ffffff"/>
<text x="58" y="34" font-family="Arial" font-size="24" font-weight="700" fill="#17212b">Сравнение методов на трёх DEV-кейсах</text>
{legend}
<line x1="58" y1="310" x2="1190" y2="310" stroke="#d4dae0"/>
{"".join(items)}
{details}
<text x="790" y="500" font-family="Arial" font-size="13" fill="#556372">Один запуск на кейс; hidden не использовался.</text>
<text x="790" y="523" font-family="Arial" font-size="13" fill="#556372">FULL — после уточнения доказательного контракта критика.</text>
<text x="790" y="546" font-family="Arial" font-size="13" fill="#556372">Итоговые выводы потребуют повторов и экспертной оценки.</text>
</svg>'''
    path.write_text(svg, encoding="utf-8")


def _write_before_after_svg(before: dict[str, Any], after: dict[str, Any], path: Path) -> None:
    metrics = [
        ("E2E", "e2e_success"),
        ("Содержание", "semantic_composite"),
        ("Ветвления F1", "branch_f1"),
        ("Трассировка F1", "trace_f1"),
    ]
    items: list[str] = []
    for index, (title, key) in enumerate(metrics):
        gx = 115 + index * 240
        for j, (row, color) in enumerate(((before, "#b0b8c2"), (after, "#169873"))):
            value = float(row[key])
            x = gx + j * 74
            items.append(_bar(x, 115, 54, value, color))
            items.append(
                f'<text x="{x + 27}" y="{309 - value * 205:.1f}" text-anchor="middle" '
                f'font-family="Arial" font-size="13" font-weight="700" fill="#17212b">{value:.0%}</text>'
            )
        items.append(
            f'<text x="{gx + 64}" y="348" text-anchor="middle" font-family="Arial" '
            f'font-size="15" fill="#23313f">{title}</text>'
        )
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="500">
<rect width="1080" height="500" fill="#ffffff"/>
<text x="55" y="42" font-family="Arial" font-size="24" font-weight="700" fill="#17212b">Контракт критика: до и после уточнения</text>
<rect x="62" y="68" width="14" height="14" fill="#b0b8c2"/><text x="85" y="80" font-family="Arial" font-size="14" fill="#344250">до</text>
<rect x="132" y="68" width="14" height="14" fill="#169873"/><text x="155" y="80" font-family="Arial" font-size="14" fill="#344250">после</text>
<line x1="60" y1="320" x2="1020" y2="320" stroke="#d4dae0"/>
{"".join(items)}
<text x="64" y="403" font-family="Arial" font-size="16" fill="#23313f">До: 1/3 завершений, 6,3 вызова и 41 636 токенов на запуск.</text>
<text x="64" y="432" font-family="Arial" font-size="16" fill="#23313f">После: 3/3 завершений, 10,3 вызова и 52 947 токенов на запуск.</text>
<text x="64" y="466" font-family="Arial" font-size="13" fill="#556372">Результат показывает устранение блокирующей ошибки, но рост цены; n=3, без статистического вывода.</text>
</svg>'''
    path.write_text(svg, encoding="utf-8")


def _blocking_codes(experiment_dir: Path, condition: str) -> Counter[str]:
    codes: Counter[str] = Counter()
    for path in experiment_dir.glob(f"{condition}/*/r*/validation_reports.json"):
        reports = json.loads(path.read_text(encoding="utf-8"))
        for report in reports:
            for issue in report.get("issues", []):
                if issue.get("blocking"):
                    codes[str(issue.get("code") or "unknown")] += 1
    return codes


def main() -> None:
    before_data = _load(BEFORE_PATH)
    after_data = _load(AFTER_FULL_PATH)
    b0_data = _load(B0_PATH)
    rows = [
        _summarize("B0_RULE", _rows(b0_data, "B0_RULE"), "rules; no LLM"),
        _summarize(
            "B1_ONESHOT",
            _rows(before_data, "B1_ONESHOT"),
            "one model request; no review or repair",
        ),
        _summarize(
            "FULL",
            _rows(after_data, "FULL"),
            "two agents; validators; evidence-grounded critic; bounded repair",
        ),
        _summarize(
            "FULL_NO_CRITIC",
            _rows(before_data, "FULL_NO_CRITIC"),
            "same pipeline without semantic critic",
        ),
        _summarize(
            "FULL_NO_REPAIR",
            _rows(before_data, "FULL_NO_REPAIR"),
            "same pipeline with zero repair attempts",
        ),
    ]
    before_full = _summarize(
        "FULL_BEFORE_CRITIC_CONTRACT_FIX",
        _rows(before_data, "FULL"),
        "original open-ended critic contract",
    )
    after_full = rows[2]

    OUTPUT.mkdir(parents=True, exist_ok=True)
    with (OUTPUT / "method_comparison_dev3.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    before_codes = _blocking_codes(BEFORE_PATH.parent, "FULL")
    after_codes = _blocking_codes(AFTER_FULL_PATH.parent, "FULL")
    payload = {
        "date": "2026-09-11",
        "case_ids": ["B1-DEV-002", "B1-DEV-010", "B1-DEV-020"],
        "case_profile": "simple RU; medium RU; hard EN",
        "repeats_per_case": 1,
        "hidden_used": False,
        "model": "deepseek-flash",
        "rows": rows,
        "critic_contract_before": before_full,
        "critic_contract_after": after_full,
        "blocking_issue_counts_before": dict(before_codes.most_common()),
        "blocking_issue_counts_after": dict(after_codes.most_common()),
        "claim_limit": (
            "A diagnostic DEV pilot, not a final statistical comparison. "
            "Independent expert review and repeated full-DEV runs remain required."
        ),
    }
    (OUTPUT / "technology_project_experiment_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_quality_svg(rows, OUTPUT / "method_comparison_dev3.svg")
    _write_before_after_svg(before_full, after_full, OUTPUT / "critic_before_after.svg")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
