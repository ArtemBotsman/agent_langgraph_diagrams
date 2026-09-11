# Benchmark и система метрик v1.0 candidate

Дата актуализации: 09.09.2026.

## Состав набора

Источник: `benchmark/v1_0_synthetic/cases.json`.

- 30 синтетических `SpecificationReq`: 20 development и 10 hidden;
- 8 simple, 13 medium, 9 hard;
- 13 русских и 17 английских;
- gold actors/UC, milestones, branches, FR→UC и запрещённые предположения;
- equivalence policy для синонимов, безопасного action split/merge и явно
  разрешённого UC split/merge;
- hidden inputs отделены от `sealed_hidden_gold.json`.

Техническая author freeze зафиксирована в `freeze_record.json`. Она защищает
файлы SHA-256 и запрещает настройку по hidden, но не подменяет review двух
экспертов и согласование руководителя. Рекомендованный Git tag создаётся только
после коммита и scientific freeze.

## Три экспериментальных условия

1. `B0_RULE` — детерминированный baseline без LLM.
2. `B1_ONESHOT` — один вызов той же LLM, без critic/repair.
3. `FULL` — два LangGraph-агента, validation gates и bounded repair.

Pyreverse хранится отдельно как adjacent baseline: он получает код, а не
требования, поэтому не входит в прямое сравнение качества B0/B1/FULL.

## Автоматические метрики

Структура и исполнение:

- `schema_validity` — прошли ли schema validators;
- `activity_structural_validity` — доля успешно принятых activity-моделей;
- `mermaid_generation_success` — доля диаграмм с детерминированным Mermaid;
- `end_to_end_success` — итоговый status равен success;
- `repair_attempts` и observed blocking classes — нагрузка и обнаруженные
  классы дефектов.

Трассировка:

- `fr_coverage = |FR, связанных хотя бы с одним UC| / |FR|`;
- `trace_reference_integrity = 1 - dangling links / max(links, 1)`;
- `trace_completeness = |уникальные FR в FR_TO_UC| / |FR|`;
- `uc_element_trace_coverage` с порогом не ниже 0,95;
- `activity_element_trace_coverage` с обязательным порогом 1,00;
- `unsupported_trace_rate` — доля явно неподтверждённых элементов.

Семантические слоты:

- actor, UC, milestone, branch и trace precision/recall/F1;
- `hallucination_rate` — unmatched predicted slots / all predicted slots;
- `semantic_composite = 0.15 actor F1 + 0.25 UC F1 + 0.25 milestone F1 +
  0.15 branch F1 + 0.20 trace F1`.

Composite применяется только в dashboard. Научный вывод обязан показывать все
измерения отдельно. Для RU/EN используется опциональный локальный multilingual
sentence similarity; threshold является candidate до экспертной калибровки на
DEV.

Стоимость и устойчивость:

- latency, prompt/completion/total tokens, calls, retries;
- стоимость только при зафиксированных тарифах, иначе `null`;
- repeat score stability `1 - (max composite - min composite)`;
- дополнительно среднее и population standard deviation по повторам.

## Экспертная оценка

Два эксперта независимо оценивают 30 кейсов по шкале 1–5 и шести измерениям,
описанным в `benchmark/expert_review/RUBRIC.md`. Скрипт
`scripts/score_expert_review.py` считает linearly weighted Cohen's kappa,
exact agreement, agreement within one point и средние. Пустые формы намеренно
не позволяют получить вымышленный результат.

## Проверка evaluator и validators

- Offline semantic sanity: контролируемые профили oracle/incomplete/
  hallucinated/wrong-trace меняют ожидаемые метрики в правильном направлении.
- Mutation suite: 15/15 заранее определённых structural/trace поломок
  обнаружены. Вывод ограничен этими 15 классами и не доказывает семантику.
- Автоматические тесты: 41 passed на 09.09.2026.

## Live evidence

Repeated DEV-001 pilot, два повтора на условие:

- B0: E2E 100%, semantic 0,633, activity trace 100%, 0 токенов;
- B1: E2E 0%, semantic 0,724, activity trace 88,1%, 8 969 токенов в среднем;
- FULL: E2E 100%, semantic 0,670, activity trace 100%, 33 445 токенов и два
  repair в среднем.

Источник: `artifacts/benchmark_runs/repeated-b0-b1-full-dev001-2026-09-09/`.
Ограничение: один DEV-кейс не доказывает порог ≥90% на всём development-наборе.

## Остаток до scientific freeze

- две реальные экспертные формы и agreement;
- исправление gold только по зафиксированному review protocol;
- письменное согласование руководителя;
- Git commit/tag scientific freeze;
- FULL на всех 20 DEV и проверка порога ≥90%;
- один финальный прогон sealed hidden без последующей настройки.

Подробная интерпретация и источники 2025–2026:
`docs/research/BASELINES_AND_LIVE_EVIDENCE_2026_09_09.md` и
`docs/research/literature_2025_2026/SOURCE_MANIFEST.md`.
