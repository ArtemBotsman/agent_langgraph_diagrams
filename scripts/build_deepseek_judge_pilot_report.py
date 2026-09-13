"""Build the reproducible B0/B1/FULL DeepSeek judge pilot summary."""

# ruff: noqa: E501 -- long SVG and Markdown table rows are generated verbatim.

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "artifacts" / "deepseek_judge_pilot_2026-09-13"
DOC_PATH = ROOT / "docs" / "research" / "DEEPSEEK_LLM_JUDGE_PILOT_2026_09_13.md"

GENERATION_SOURCES = {
    "B0_RULE": ROOT
    / "artifacts/size_scaling_runs/size-scaling-b0-r3-2026-09-13/results.json",
    "B1_ONESHOT": ROOT
    / "artifacts/size_scaling_runs/deepseek-b1-size003-32k-r1-2026-09-13/results.json",
    "FULL": ROOT
    / "artifacts/size_scaling_runs/deepseek-b1-full-size-pilot-r1-2026-09-13/results.json",
}
JUDGE_SOURCES = {
    "B0_RULE": ROOT
    / "artifacts/llm_judge_runs/deepseek-b0-size-pilot-r2-v2-2026-09-13/results.json",
    "B1_ONESHOT": ROOT
    / "artifacts/llm_judge_runs/deepseek-b1-size003-judge-r2-2026-09-13/results.json",
    "FULL": ROOT
    / "artifacts/llm_judge_runs/deepseek-full-size003-judge-r2-v2-2026-09-13/results.json",
}
DIMENSIONS = (
    "requirements_coverage",
    "actor_uc_boundaries",
    "scenario_completeness",
    "branch_correctness",
    "trace_correctness",
    "assumption_discipline",
    "diagram_readability",
)


def _load_generation(method: str) -> dict[str, Any]:
    data = json.loads(GENERATION_SOURCES[method].read_text(encoding="utf-8"))
    return next(
        row
        for row in data["rows"]
        if row["condition"] == method
        and row["case_id"] == "SCALE-003"
        and row["repeat_id"] == 1
    )


def _load_judge(method: str) -> tuple[dict[str, Any], dict[str, Any]]:
    data = json.loads(JUDGE_SOURCES[method].read_text(encoding="utf-8"))
    return data["summary"][0], data["config"]


def _fmt_percent(value: Any) -> str:
    return "—" if value is None else f"{float(value) * 100:.1f}%"


def _svg(rows: list[dict[str, Any]]) -> str:
    colors = {"B0_RULE": "#395d7f", "B1_ONESHOT": "#9a7a38", "FULL": "#368779"}
    bars: list[str] = []
    for index, row in enumerate(rows):
        x = 165 + index * 300
        semantic = float(row["judge_score_0_1"])
        e2e = float(row["end_to_end_success"])
        semantic_height = semantic * 260
        e2e_height = e2e * 260
        bars.extend(
            [
                f'<rect x="{x}" y="{370 - semantic_height:.1f}" width="90" '
                f'height="{semantic_height:.1f}" fill="{colors[row["method"]]}" rx="8"/>',
                f'<rect x="{x + 105}" y="{370 - e2e_height:.1f}" width="90" '
                f'height="{e2e_height:.1f}" fill="#9ca8b5" rx="8"/>',
                f'<text x="{x + 45}" y="{354 - semantic_height:.1f}" text-anchor="middle" '
                f'class="value">{semantic * 100:.1f}%</text>',
                f'<text x="{x + 150}" y="{354 - e2e_height:.1f}" text-anchor="middle" '
                f'class="value">{e2e * 100:.0f}%</text>',
                f'<text x="{x + 98}" y="410" text-anchor="middle" class="label">'
                f'{row["method"]}</text>',
            ]
        )
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="560" viewBox="0 0 1100 560">
<style>
  .title {{ font: 700 30px Arial, sans-serif; fill: #172433; }}
  .subtitle {{ font: 18px Arial, sans-serif; fill: #566575; }}
  .axis {{ font: 15px Arial, sans-serif; fill: #566575; }}
  .label {{ font: 700 17px Arial, sans-serif; fill: #172433; }}
  .value {{ font: 700 17px Arial, sans-serif; fill: #172433; }}
  .legend {{ font: 16px Arial, sans-serif; fill: #344455; }}
</style>
<rect width="1100" height="560" fill="#ffffff"/>
<text x="60" y="55" class="title">DeepSeek pilot: смысловая оценка и формальный E2E</text>
<text x="60" y="86" class="subtitle">SCALE-003 · 8 ФТ · один generation run · два blind judge repeats</text>
<line x1="95" y1="110" x2="95" y2="370" stroke="#b7c0ca"/>
<line x1="95" y1="370" x2="1015" y2="370" stroke="#b7c0ca"/>
<text x="74" y="375" text-anchor="end" class="axis">0%</text>
<text x="74" y="245" text-anchor="end" class="axis">50%</text>
<text x="74" y="116" text-anchor="end" class="axis">100%</text>
<line x1="95" y1="240" x2="1015" y2="240" stroke="#e2e6ea"/>
{''.join(bars)}
<rect x="250" y="470" width="22" height="22" fill="#368779" rx="4"/>
<text x="283" y="487" class="legend">LLM-judge score (цвет метода)</text>
<rect x="610" y="470" width="22" height="22" fill="#9ca8b5" rx="4"/>
<text x="643" y="487" class="legend">формальный E2E gate</text>
<text x="550" y="535" text-anchor="middle" class="subtitle">Высокая LLM-оценка не заменяет schema/trace/structure validation</text>
</svg>'''


def main() -> None:
    rows: list[dict[str, Any]] = []
    for method in ("B0_RULE", "B1_ONESHOT", "FULL"):
        generation = _load_generation(method)
        judge, judge_config = _load_judge(method)
        rows.append(
            {
                "method": method,
                "generation_status": generation["run_status"],
                "end_to_end_success": generation["end_to_end_success"],
                "schema_validity": generation.get("schema_validity"),
                "activity_trace_coverage": generation.get(
                    "activity_element_trace_coverage"
                ),
                "activity_structural_validity": generation.get(
                    "activity_structural_validity"
                ),
                "use_case_count": generation.get("use_case_count"),
                "activity_diagram_count": generation.get("activity_diagram_count"),
                "generation_llm_calls": generation["llm_calls"],
                "generation_tokens": generation["total_tokens"],
                "generation_latency_ms": generation["latency_ms"],
                "generation_estimated_cost_usd": generation.get("estimated_cost_usd"),
                "judge_model": judge_config["judge_model"],
                "judge_valid_runs": judge["successful_judgments"],
                "judge_runs": judge["run_count"],
                "judge_score_0_1": judge["mean_overall_score_0_1"],
                "judge_score_sd": judge["sd_overall_score_0_1"],
                "judge_approve_rate": judge["approve_rate"],
                **{
                    f"judge_{dimension}_1_5": judge[f"mean_{dimension}_1_5"]
                    for dimension in DIMENSIONS
                },
            }
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps({"case_id": "SCALE-003", "rows": rows}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    fields = list(rows[0])
    with (OUTPUT_DIR / "summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    (OUTPUT_DIR / "deepseek_judge_pilot.svg").write_text(_svg(rows), encoding="utf-8")

    table = "\n".join(
        "| {method} | {e2e} | {schema} | {trace} | {ucs} | {diagrams} | "
        "{calls} | {tokens:,} | {latency:.1f} | {judge:.3f} | {valid}/{total} |".format(
            method=row["method"],
            e2e=_fmt_percent(row["end_to_end_success"]),
            schema=_fmt_percent(row["schema_validity"]),
            trace=_fmt_percent(row["activity_trace_coverage"]),
            ucs=row["use_case_count"],
            diagrams=row["activity_diagram_count"],
            calls=row["generation_llm_calls"],
            tokens=int(row["generation_tokens"]),
            latency=float(row["generation_latency_ms"]) / 1000,
            judge=float(row["judge_score_0_1"]),
            valid=row["judge_valid_runs"],
            total=row["judge_runs"],
        ).replace(",", " ")
        for row in rows
    )
    dimensions = "\n".join(
        "| {method} | {coverage:.1f} | {actors:.1f} | {scenario:.1f} | "
        "{branches:.1f} | {trace:.1f} | {assumptions:.1f} | {readability:.1f} |".format(
            method=row["method"],
            coverage=row["judge_requirements_coverage_1_5"],
            actors=row["judge_actor_uc_boundaries_1_5"],
            scenario=row["judge_scenario_completeness_1_5"],
            branches=row["judge_branch_correctness_1_5"],
            trace=row["judge_trace_correctness_1_5"],
            assumptions=row["judge_assumption_discipline_1_5"],
            readability=row["judge_diagram_readability_1_5"],
        )
        for row in rows
    )
    b0_size_data = json.loads(JUDGE_SOURCES["B0_RULE"].read_text(encoding="utf-8"))
    b0_size_table = "\n".join(
        "| {group} | {score:.3f} | {approve:.0%} | {valid}/{total} |".format(
            group=row["size_group"],
            score=row["mean_overall_score_0_1"],
            approve=row["approve_rate"],
            valid=row["successful_judgments"],
            total=row["run_count"],
        )
        for row in b0_size_data["summary"]
    )
    document = f"""# DeepSeek как слепой LLM-судья: диагностический пилот

Дата: 13.09.2026. Кейс: `SCALE-003`, предзаказ и самовывоз из кафе, 8 ФТ и
13 НФТ. Генератор и судья: `deepseek-flash`. Судья не видел имя метода,
провайдера или модели. Для каждого сохранённого кандидата сделано два повтора
оценки при temperature=0.

## Почему LLM-судья используется только вместе с валидаторами

Детерминированные проверки отвечают на формальные вопросы: прошла ли схема,
существуют ли цели ссылок, покрыты ли элементы диаграммы трассировкой и
корректен ли граф. LLM-судья оценивает смысл: акторов, границы UC, полноту
сценариев, ветвления, правдоподобие трассировки и читаемость.

Ни один слой не заменяет другой. LLM может одобрить правдоподобный результат с
формальным дефектом, а детерминированный B0 может иметь 100% ссылок, оставаясь
плохой смысловой декомпозицией.

## Основная таблица

| Метод | E2E | Schema | Activity trace | UC | Диаграмм | LLM calls | Tokens | Время, с | Judge 0–1 | Валидных оценок |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
{table}

## Детализация LLM-оценки, шкала 1–5

| Метод | Покрытие | Акторы/границы UC | Сценарии | Ветвления | Трассировка | Предположения | Читаемость |
|---|---:|---:|---:|---:|---:|---:|---:|
{dimensions}

## Проверка B0 по четырём размерам

| Группа | Judge 0–1 | Approve rate | Валидных оценок |
|---|---:|---:|---:|
{b0_size_table}

По одному репрезентативному B0 из каждой группы и двум повторам судьи оценки
остались в диапазоне 0,100–0,125. Это усиливает диагностический вывод о слабой
смысловой декомпозиции B0, но четыре проекта всё ещё не заменяют экспертную
оценку всего набора.

## Интерпретация

1. `B0_RULE` формально проходит E2E, но получает только 0,100: один абстрактный
   актор, один UC и линейная диаграмма не отражают независимые цели и ошибки.
2. `B1_ONESHOT` получает 0,775 и оба раза одобряется LLM-судьёй, однако
   детерминированный gate отклоняет результат: structural validity = 0%,
   Activity trace = 94,0%. Найдены восемь рёбер без ссылки на шаг UC и одно
   нарушение порога 100% — девять блокирующих замечаний двух классов. Это
   прямое доказательство, что LLM-судью нельзя использовать вместо валидаторов.
3. `FULL` получает 0,781 в среднем и одновременно проходит E2E, schema и trace
   на 100%. На этом одном кейсе он является единственным методом, сочетающим
   высокую смысловую оценку и формальную пригодность.
4. Разница LLM-score между B1 и FULL мала — 0,006. На одном кейсе нельзя
   утверждать статистическое превосходство FULL по смыслу. Проверяемое
   преимущество здесь — исправление формальных дефектов ценой 8 вызовов и
   69 510 токенов вместо одного вызова и 24 610 токенов.

## Отдельный size stress-test

При 16 ФТ `B1_ONESHOT` был обрезан даже при лимите 32 000 output tokens:
40 128 total tokens. `FULL` сформировал 12 UC, но остановился по локальному
лимиту после 29 вызовов и 215 697 токенов. Это не победа FULL: текущая
реализация должна сохранять прогресс activity по каждому UC и поддерживать
пакетную декомпозицию крупных наборов ФТ.

## Токены и стоимость диагностического цикла

Все запуски настройки и проверки вместе: 68 API calls, 518 075 input tokens,
из них 218 108 cache-hit, и 222 163 output tokens; всего 740 238. Локальный
budget guard консервативно оценил расход в $0,422018, считая весь input по
обычной peak-цене. По опубликованной 13.09.2026 формуле DeepSeek и фактическому
Sunday off-peak режиму оценка с учётом cache-hit составляет около $0,178947.
Обе суммы являются расчётом; фактическое списание проверяется в dashboard.

## Ограничения

- один generation case и два judge repeats;
- DeepSeek оценивает результаты DeepSeek, поэтому возможна self-preference;
- шкала LLM-судьи ещё не откалибрована двумя людьми;
- решение для крупных проектов пока не прошло E2E;
- результаты являются диагностическим pilot, а не финальным выводом НИР.

## Следующий протокол

После исправления масштабирования выполнить одинаковые B0/B1/FULL на G1–G4,
по три повтора. Те же сохранённые кандидаты независимо оценивают DeepSeek,
выбранная GPT-модель и два человека. Имена методов рандомизируются. Основной
вывод строится по пересечению formal E2E, слепой смысловой оценки, устойчивости,
токенов, задержки и стоимости.
"""
    DOC_PATH.write_text(document, encoding="utf-8")
    (OUTPUT_DIR / "ANALYSIS_RU.md").write_text(document, encoding="utf-8")


if __name__ == "__main__":
    main()
