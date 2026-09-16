"""Build corrected scaling evidence and a preregistered final experiment plan.

The script does not call an LLM.  It preserves the original diagnostic runs,
revalidates saved FULL artifacts with the current trace contract, joins the
checkpoint recovery for SCALE-010, and writes a new evidence directory.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt  # type: ignore[import-not-found]
from matplotlib.patches import Rectangle  # type: ignore[import-not-found]

from traceable_spec.entities import GeneratedSpecification, PipelineStatus, TraceLinkType
from traceable_spec.evaluation.benchmark import evaluate_semantic_projection
from traceable_spec.evaluation.evaluator import evaluate_specification
from traceable_spec.evaluation.projection import automatic_metrics, semantic_projection
from traceable_spec.evaluation.similarity import MultilingualSentenceSimilarity
from traceable_spec.traceability import materialize_trace_manifest
from traceable_spec.validators import validate_end_to_end_trace

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "statistical_readiness_2026-09-16"
BENCHMARK = ROOT / "benchmark" / "size_scaling_v1"
MIXED = (
    ROOT
    / "artifacts"
    / "size_scaling_runs"
    / "size-scaling-gold-preflight-mixed-2026-09-15"
)
SMALL = (
    ROOT
    / "artifacts"
    / "size_scaling_runs"
    / "size-scaling-gold-preflight-scale001-2026-09-15"
)
RECOVERY = (
    ROOT
    / "artifacts"
    / "size_scaling_runs"
    / "scale010-full-checkpoint-recovery-2026-09-16"
)

CASES = ("SCALE-001", "SCALE-010", "SCALE-015", "SCALE-020")
FR_COUNTS = {"SCALE-001": 6, "SCALE-010": 19, "SCALE-015": 48, "SCALE-020": 74}
PROJECTS = {
    "SCALE-001": "Запись на услуги салона",
    "SCALE-010": "Портал записи на корпоративное обучение",
    "SCALE-015": "Операционный портал коворкинга",
    "SCALE-020": "Управление сетью фитнес-клубов",
}

BLUE = "#0067B1"
ORANGE = "#F05A00"
GREEN = "#009E73"
RED = "#D62828"
GRAY = "#667085"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _revalidate_saved_spec(path: Path) -> tuple[GeneratedSpecification, int]:
    original = GeneratedSpecification.model_validate_json(path.read_text(encoding="utf-8"))
    if original.use_case_set is None:
        raise ValueError(f"No UseCaseSet in {path}")
    diagrams = [
        result.activity_diagram
        for result in original.activity_results
        if result.activity_diagram is not None
    ]
    old_unsupported = sum(
        link.link_type == TraceLinkType.UNSUPPORTED for link in original.trace_manifest.links
    )
    trace = materialize_trace_manifest(
        original.request,
        original.use_case_set,
        diagrams,
        existing=original.trace_manifest,
    )
    new_unsupported = sum(link.link_type == TraceLinkType.UNSUPPORTED for link in trace.links)
    reports = [
        report for report in original.validation_reports if report.validator_name != "e2e_trace"
    ]
    provisional = original.model_copy(
        update={
            "trace_manifest": trace,
            "validation_reports": reports,
            "status": PipelineStatus.SUCCESS,
            "failure_reason": None,
        }
    )
    e2e = validate_end_to_end_trace(provisional)
    status = PipelineStatus.SUCCESS if e2e.passed else PipelineStatus.FAILED
    corrected = provisional.model_copy(
        update={"validation_reports": [*reports, e2e], "status": status}
    )
    corrected = corrected.model_copy(
        update={"evaluation_report": evaluate_specification(corrected)}
    )
    return corrected, old_unsupported - new_unsupported


def _metric_row(
    case_id: str,
    condition: str,
    specification: GeneratedSpecification,
    gold: dict[str, Any],
    similarity: MultilingualSentenceSimilarity,
    *,
    llm_calls: int,
    total_tokens: int,
    cost_usd: float,
    latency_seconds: float | None,
    source: Path,
    correction: str,
) -> dict[str, Any]:
    semantic = evaluate_semantic_projection(
        semantic_projection(specification),
        gold,
        similarity=similarity,
        similarity_name=similarity.name,
    )
    automatic = automatic_metrics(specification)
    return {
        "case_id": case_id,
        "project_name": PROJECTS[case_id],
        "fr_count": FR_COUNTS[case_id],
        "condition": condition,
        "e2e_success": automatic.get("end_to_end_success"),
        "actor_f1": semantic["actor_f1"],
        "uc_f1": semantic["uc_f1"],
        "milestone_f1": semantic["milestone_f1"],
        "branch_f1": semantic["branch_f1"],
        "trace_f1": semantic["trace_f1"],
        "fr_activity_coverage": automatic.get("fr_activity_coverage"),
        "activity_element_trace_coverage": automatic.get(
            "activity_element_trace_coverage"
        ),
        "activity_structural_validity": automatic.get("activity_structural_validity"),
        "llm_calls": llm_calls,
        "total_tokens": total_tokens,
        "latency_seconds": latency_seconds,
        "estimated_cost_usd": cost_usd,
        "semantic_similarity_backend": similarity.name,
        "gold_status": "author_candidate_requires_two_independent_reviews",
        "source_path": str(source.relative_to(ROOT)),
        "source_sha256": _sha256(source),
        "correction": correction,
    }


def _load_old_rows() -> dict[tuple[str, str], dict[str, str]]:
    rows = _read_csv(SMALL / "results.csv") + _read_csv(MIXED / "results.csv")
    return {
        (row["case_id"], row["condition"]): row
        for row in rows
        if row["case_id"] in CASES and row["condition"] in {"B1_ONESHOT", "FULL"}
    }


def _prepare_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    old = _load_old_rows()
    gold_records = json.loads((BENCHMARK / "gold_candidate.json").read_text(encoding="utf-8"))
    gold = {item["case_id"]: item["gold"] for item in gold_records}
    similarity = MultilingualSentenceSimilarity(local_files_only=True)
    rows: list[dict[str, Any]] = []
    corrections: list[dict[str, Any]] = []

    for case_id in CASES:
        baseline = old[(case_id, "B1_ONESHOT")]
        output_available = baseline.get("milestone_f1") not in (None, "")
        rows.append(
            {
                "case_id": case_id,
                "project_name": PROJECTS[case_id],
                "fr_count": FR_COUNTS[case_id],
                "condition": "B1_ONESHOT",
                "e2e_success": float(baseline.get("end_to_end_success") or 0),
                "actor_f1": float(baseline["actor_f1"]) if output_available else None,
                "uc_f1": float(baseline["uc_f1"]) if output_available else None,
                "milestone_f1": (
                    float(baseline["milestone_f1"]) if output_available else None
                ),
                "branch_f1": float(baseline["branch_f1"]) if output_available else None,
                "trace_f1": float(baseline["trace_f1"]) if output_available else None,
                "fr_activity_coverage": (
                    float(
                        baseline.get("fr_activity_coverage")
                        or baseline.get("fr_coverage")
                        or 0
                    )
                    if output_available
                    else None
                ),
                "activity_element_trace_coverage": (
                    float(baseline.get("activity_element_trace_coverage") or 0)
                    if output_available
                    else None
                ),
                "activity_structural_validity": (
                    float(baseline.get("activity_structural_validity") or 0)
                    if output_available
                    else None
                ),
                "llm_calls": int(float(baseline["llm_calls"])),
                "total_tokens": int(float(baseline["total_tokens"])),
                "latency_seconds": float(baseline["latency_ms"]) / 1000,
                "estimated_cost_usd": float(baseline["estimated_cost_usd"]),
                "error_type": baseline.get("error_type") or "",
                "semantic_similarity_backend": baseline.get("semantic_similarity_backend") or "",
                "gold_status": "author_candidate_requires_two_independent_reviews",
                "source_path": str(
                    (
                        SMALL / "results.csv"
                        if case_id == "SCALE-001"
                        else MIXED / "results.csv"
                    ).relative_to(ROOT)
                ),
                "correction": "none",
            }
        )

    source_by_case = {
        "SCALE-001": SMALL / "FULL" / "SCALE-001" / "r01" / "generated_specification.json",
        "SCALE-010": RECOVERY / "generated_specification.json",
        "SCALE-015": MIXED / "FULL" / "SCALE-015" / "r01" / "generated_specification.json",
        "SCALE-020": MIXED / "FULL" / "SCALE-020" / "r01" / "generated_specification.json",
    }
    for case_id in CASES:
        source = source_by_case[case_id]
        corrected, stale_links = _revalidate_saved_spec(source)
        old_row = old[(case_id, "FULL")]
        if case_id == "SCALE-010":
            recovery = json.loads((RECOVERY / "recovery_summary.json").read_text(encoding="utf-8"))
            calls = int(float(old_row["llm_calls"])) + int(recovery["new_llm_calls"])
            tokens = int(float(old_row["total_tokens"])) + int(recovery["new_total_tokens"])
            cost = float(old_row["estimated_cost_usd"]) + float(
                recovery["new_estimated_cost_usd"]
            )
            latency = None
            correction = "checkpoint_resume_after_IncompleteRead"
        else:
            calls = int(float(old_row["llm_calls"]))
            tokens = int(float(old_row["total_tokens"]))
            cost = float(old_row["estimated_cost_usd"])
            latency = float(old_row["latency_ms"]) / 1000
            correction = (
                "none" if case_id == "SCALE-001" else "drop_stale_unsupported_trace_links"
            )
        rows.append(
            _metric_row(
                case_id,
                "FULL",
                corrected,
                gold[case_id],
                similarity,
                llm_calls=calls,
                total_tokens=tokens,
                cost_usd=cost,
                latency_seconds=latency,
                source=source,
                correction=correction,
            )
        )
        corrected_path = OUTPUT / "revalidated" / case_id / "generated_specification.json"
        corrected_path.parent.mkdir(parents=True, exist_ok=True)
        corrected_path.write_text(
            corrected.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        corrections.append(
            {
                "case_id": case_id,
                "fr_count": FR_COUNTS[case_id],
                "old_e2e": float(old_row.get("end_to_end_success") or 0),
                "new_e2e": automatic_metrics(corrected).get("end_to_end_success"),
                "stale_unsupported_links_removed": stale_links,
                "correction": correction,
                "original_preserved": True,
            }
        )
    rows.sort(key=lambda item: (item["fr_count"], item["condition"]))
    return rows, corrections


def _status_text(row: dict[str, Any]) -> tuple[str, str]:
    if row["e2e_success"] == 1:
        return "E2E пройден", GREEN
    if row["condition"] == "B1_ONESHOT" and row.get("error_type") == "LLMOutputTruncatedError":
        return "Ответ обрезан\n65 536 токенов", RED
    return "Activity не прошла\nпроверку связей", ORANGE


def _plot_corrected_status(rows: list[dict[str, Any]]) -> None:
    by_key = {(row["case_id"], row["condition"]): row for row in rows}
    fig, ax = plt.subplots(figsize=(10.8, 6.4))
    fig.subplots_adjust(top=0.82, bottom=0.20, left=0.19, right=0.97)
    ax.set_xlim(0, 2)
    ax.set_ylim(0, 4)
    ax.axis("off")
    for y, case_id in enumerate(reversed(CASES)):
        for x, condition in enumerate(("B1_ONESHOT", "FULL")):
            label, color = _status_text(by_key[(case_id, condition)])
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
                label,
                ha="center",
                va="center",
                color="white",
                fontsize=11,
                fontweight="bold",
            )
        ax.text(
            -0.05,
            y + 0.5,
            f"{FR_COUNTS[case_id]} ФТ",
            ha="right",
            va="center",
            fontsize=12,
        )
    ax.text(0.5, 4.05, "Один вызов LLM", ha="center", va="bottom", fontsize=13, fontweight="bold")
    ax.text(1.5, 4.05, "Полный граф", ha="center", va="bottom", fontsize=13, fontweight="bold")
    fig.suptitle(
        "Инженерная проверка масштабирования после исправлений",
        fontsize=18,
        fontweight="bold",
        y=0.96,
    )
    fig.text(
        0.5,
        0.88,
        "DeepSeek deepseek-flash · один заранее выбранный проект на размер · n = 1",
        ha="center",
        fontsize=10,
        color=GRAY,
    )
    fig.text(
        0.5,
        0.075,
        "Рисунок 1 — FULL завершил 6/19/48/74 ФТ; one-shot ограничен структурой и длиной ответа",
        ha="center",
        fontsize=11,
    )
    fig.text(
        0.5,
        0.035,
        "Это технический preflight, а не статистическое доказательство качества",
        ha="center",
        fontsize=9,
        color=GRAY,
    )
    for suffix in ("png", "svg"):
        fig.savefig(OUTPUT / f"01_corrected_scaling_status.{suffix}", dpi=220, bbox_inches="tight")
    plt.close(fig)


def _plot_final_design() -> None:
    fig, ax = plt.subplots(figsize=(12.2, 6.4))
    fig.subplots_adjust(top=0.83, bottom=0.18, left=0.04, right=0.98)
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 6)
    ax.axis("off")
    boxes = [
        (0.2, 3.4, 2.1, 1.4, "20 проектов\n4 группы × 5", BLUE),
        (2.8, 3.4, 2.1, 1.4, "Gold\n2 эксперта", ORANGE),
        (5.4, 3.4, 2.1, 1.4, "One-shot и FULL\nпо 3 повтора", GREEN),
        (8.0, 3.4, 1.7, 1.4, "120\nзапусков", BLUE),
        (10.2, 3.4, 1.6, 1.4, "Парные\nразницы", ORANGE),
    ]
    for x, y, w, h, label, color in boxes:
        ax.add_patch(Rectangle((x, y), w, h, facecolor="white", edgecolor=color, linewidth=2))
        ax.text(
            x + w / 2,
            y + h / 2,
            label,
            ha="center",
            va="center",
            fontsize=11,
            fontweight="bold",
        )
    for start, end in ((2.3, 2.8), (4.9, 5.4), (7.5, 8.0), (9.7, 10.2)):
        ax.annotate(
            "",
            xy=(end, 4.1),
            xytext=(start, 4.1),
            arrowprops={"arrowstyle": "->", "lw": 1.8},
        )
    metrics = [
        "Основная: E2E success",
        "Содержание: Actor / UC / Milestone / Branch F1",
        "Трассировка: Trace F1 и покрытия",
        "Цена: время · токены · стоимость",
        "Эксперты: полнота · корректность · читаемость",
    ]
    ax.text(0.4, 2.75, "Что сравнивается", fontsize=13, fontweight="bold")
    for index, label in enumerate(metrics):
        ax.text(0.6, 2.3 - index * 0.42, f"• {label}", fontsize=10.5)
    ax.text(7.0, 2.75, "Критерий вывода", fontsize=13, fontweight="bold")
    ax.text(7.2, 2.25, "95% CI разницы не включает 0", fontsize=10.5)
    ax.text(7.2, 1.8, "точный парный тест + поправка Holm", fontsize=10.5)
    ax.text(7.2, 1.35, "проект — единица анализа, не API-вызов", fontsize=10.5)
    ax.text(7.2, 0.9, "по группам размеров — эффект и 95% CI", fontsize=10.5)
    fig.suptitle(
        "Протокол итогового статистического сравнения",
        fontsize=18,
        fontweight="bold",
        y=0.96,
    )
    fig.text(
        0.5,
        0.045,
        "Gold фиксируется до запуска; незавершённый результат учитывается "
        "как E2E = 0 и не получает F1",
        ha="center",
        fontsize=9.5,
        color=GRAY,
    )
    for suffix in ("png", "svg"):
        fig.savefig(OUTPUT / f"02_final_experiment_design.{suffix}", dpi=220, bbox_inches="tight")
    plt.close(fig)


def _write_protocol(rows: list[dict[str, Any]], corrections: list[dict[str, Any]]) -> None:
    protocol = """# Итоговый протокол статистического сравнения

## Что уже исправлено и подтверждено технически

- `SCALE-010` продолжен из контрольной точки после `IncompleteRead`: добавлено 8
  вызовов, повторная генерация первых 14 диаграмм не выполнялась, итоговый E2E = 1.
- В `SCALE-015` удалена одна, а в `SCALE-020` — четыре устаревшие ссылки типа
  `UNSUPPORTED`, указывавшие на элементы до исправления Activity. После повторной
  материализации TraceManifest оба сохранённых результата проходят E2E.
- Исходные результаты не перезаписаны. Исправленные копии находятся в `revalidated/`.

Таким образом, инженерный preflight теперь даёт FULL E2E = 4/4 для 6, 19, 48
и 74 ФТ. Это ещё не статистическое превосходство: на каждый размер был один
заранее выбранный проект и один запуск.

## Подтверждающий эксперимент

**Экспериментальная единица:** проект. Три стохастических повтора сначала
усредняются внутри проекта; их нельзя считать 60 независимыми проектами.

**Данные:** все 20 проектов руководителя — по 5 в четырёх группах размеров.

**Основное парное сравнение:** `B1_ONESHOT` и `FULL` на одной модели, с одинаковыми
входами, температурой, лимитами, output schema и evaluator; 3 повтора.
Всего 20 × 2 × 3 = 120 запусков.

**Основная метрика:** E2E success — доля повторов, в которых весь комплект прошёл
схему, структуру Activity и трассировку. Она отвечает на практический вопрос:
можно ли передать результат пользователю и следующему агенту без ручного ремонта.

**Содержательные метрики:** Actor F1, UC F1, Milestone F1, Branch F1.
**Трассировка:** Trace F1, FR→UC coverage, FR→Activity coverage, доля элементов
Activity со ссылкой на шаг Use Case. **Цена:** время, токены, стоимость.

**Статистика:** для каждой метрики считается проектная разница `FULL − one-shot`.
Показываются средняя разница и 95% кластерный bootstrap CI по проектам (50 000
выборок, заранее фиксированный seed), точный двусторонний sign-flip test и
поправка Holm. Статистическое преимущество по основной метрике заявляется,
только если 95% CI полностью выше нуля и скорректированное p < 0,05.

**График для основного вывода:** forest plot парных разниц с 95% CI и вертикальной
линией нулевого эффекта. Дополнительно — paired-dot plot по 20 проектам,
групповой эффект с CI для четырёх размеров и график E2E–стоимость.

## Экспертная проверка

Gold-кандидат должен быть независимо проверен двумя экспертами до финальных
запусков. Экспертам не показываются названия условий и ответы систем. После
фиксации Gold два эксперта вслепую оценивают результаты по полноте,
корректности и читаемости; порядок пар рандомизируется. Согласованность оценок
показывается взвешенной κ Коэна (порядковые шкалы) и долей совпадений.

## Анализ вклада компонентов

Он выполняется отдельно от основного сравнения и не смешивает смену модели со
сменой архитектуры:

1. `FULL_REPAIR_0` — исправления запрещены.
2. `FULL_REPAIR_1` — не более одного исправления на артефакт.
3. `FULL_REPAIR_2` — основной FULL, не более двух исправлений.
4. `FULL_NO_CRITIC` — без LLM-критика.
5. `FULL_NO_RULE_FEEDBACK` — формальные правила не возвращаются генератору как
   обратная связь; типизированный парсинг и итоговый evaluator сохраняются.

Название `NO_DETERMINISTIC` не используется: полностью убрать типизированный
парсинг невозможно без изменения самой задачи и формата результата.

## Переносимость между моделями

После основного DeepSeek-сравнения один и тот же замороженный поднабор запускается
как one-shot и FULL на GPT-5.5 и Claude Opus 5. Это вторичный анализ: он проверяет
переносимость вывода, но не подменяет основной парный эксперимент. `GPT-OSS`
добавляется только при фиксированных точных MODEL_ID, endpoint и лимитах.

## Текущий научный gate

Финальный платный запуск по всем 20 проектам нельзя честно считать завершённым,
пока два реальных эксперта не проверили Gold. Формы и обезличенные пакеты
подготовлены; экспертные оценки не имитируются.
"""
    (OUTPUT / "STATISTICAL_PROTOCOL_RU.md").write_text(protocol, encoding="utf-8")
    _write_csv(OUTPUT / "corrected_size_preflight.csv", rows)
    _write_csv(OUTPUT / "corrections.csv", corrections)
    matrix = [
        {
            "track": "primary",
            "condition": "B1_ONESHOT",
            "purpose": "прямой вызов той же модели",
            "projects": 20,
            "repeats": 3,
        },
        {
            "track": "primary",
            "condition": "FULL_REPAIR_2",
            "purpose": "полный граф",
            "projects": 20,
            "repeats": 3,
        },
        {
            "track": "component",
            "condition": "FULL_REPAIR_0",
            "purpose": "вклад исправления: 0 попыток",
            "projects": 20,
            "repeats": 3,
        },
        {
            "track": "component",
            "condition": "FULL_REPAIR_1",
            "purpose": "вклад исправления: 1 попытка",
            "projects": 20,
            "repeats": 3,
        },
        {
            "track": "component",
            "condition": "FULL_NO_CRITIC",
            "purpose": "вклад LLM-критика",
            "projects": 20,
            "repeats": 3,
        },
        {
            "track": "component",
            "condition": "FULL_NO_RULE_FEEDBACK",
            "purpose": "вклад обратной связи формальных правил",
            "projects": 20,
            "repeats": 3,
        },
        {
            "track": "robustness",
            "condition": "ONE_SHOT_AND_FULL_GPT55_CLAUDE",
            "purpose": "переносимость между моделями на замороженном поднаборе",
            "projects": "fixed_subset",
            "repeats": 3,
        },
    ]
    _write_csv(OUTPUT / "experiment_matrix.csv", matrix)


def main() -> None:
    rows, corrections = _prepare_rows()
    _plot_corrected_status(rows)
    _plot_final_design()
    _write_protocol(rows, corrections)
    manifest = {
        "suite": "statistical_readiness_2026-09-16",
        "llm_calls_performed_by_builder": 0,
        "gold_status": "author_candidate_requires_two_independent_reviews",
        "corrected_preflight_sha256": _sha256(OUTPUT / "corrected_size_preflight.csv"),
        "protocol_sha256": _sha256(OUTPUT / "STATISTICAL_PROTOCOL_RU.md"),
    }
    (OUTPUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
