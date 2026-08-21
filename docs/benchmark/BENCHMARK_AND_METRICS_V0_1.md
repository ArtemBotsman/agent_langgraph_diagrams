# Benchmark и метрики v0.1

Дата: **2026-08-21**

Инфраструктура: `benchmark/`. Полноценный набор из 30 кейсов **не выдуман** — в манифесте один synthetic development-кейс `DEV-001`.

## Разделение видов оценки

| Вид | Где | Смешивать? |
|-----|-----|------------|
| Автоматические метрики | `evaluate_specification` | Нет |
| LLM-as-a-judge | будущий модуль | Нет |
| Экспертная оценка | протокол вручную | Нет |

## Метрики (автоматические)

### schema_validity
- **Назначение:** доля schema-валидаторов без ошибок.
- **Формула:** `1` если все schema reports passed, иначе `0` (MVP; позже — доля).
- **Диапазон:** `[0, 1]`; выше — лучше.
- **Данные:** `validation_reports` с `*schema*`.
- **Ограничения:** не ловит семантику.

### fr_coverage
- **Назначение:** покрытие ФТ ссылками UC.
- **Формула:** `|FRs referenced by ≥1 UC| / |FRs|`.
- **Диапазон:** `[0, 1]`; выше — лучше.
- **Данные:** `use_case_set`, `request.functional_requirements`.
- **Ограничения:** не доказывает корректность покрытия.

### orphan_uc_rate
- **Назначение:** доля UC без FR.
- **Формула:** `|UC without source_fr_ids| / |UC|`.
- **Диапазон:** `[0, 1]`; ниже — лучше.

### duplicate_uc_rate
- **Назначение:** дубликаты по нормализованному имени.
- **Формула:** `|names with count>1| / |UC|` (MVP-прокси).
- **Диапазон:** `[0, 1]`; ниже — лучше.
- **Ограничения:** не semantic near-duplicate.

### trace_completeness
- **Назначение:** наличие FR→… связей в манифесте.
- **Формула:** `min(|links with FR source| / |FRs|, 1)`.
- **Диапазон:** `[0, 1]`; выше — лучше.

### trace_reference_integrity
- **Назначение:** отсутствие висячих ссылок.
- **Формула:** `1 - dangling_issues / max(|links|, 1)` (из validation issues).
- **Диапазон:** примерно `[0, 1]`; выше — лучше.

### activity_structural_validity
- **Назначение:** доля успешно завершённых activity результатов.
- **Формула:** `|activity SUCCESS with diagram| / max(|activity_results|, 1)`.
- **Диапазон:** `[0, 1]`; выше — лучше.

### mermaid_generation_success
- **Назначение:** наличие `mermaid_source`.
- **Формула:** `|diagrams with mermaid_source| / max(|activity_results|, 1)`.
- **Диапазон:** `[0, 1]`; выше — лучше.

### end_to_end_success
- **Назначение:** pipeline status == success.
- **Формула:** `1` или `0`; выше — лучше.

### repair_attempts
- **Назначение:** стоимость/нагрузка repair.
- **Формула:** сумма `repair_attempts_used` по activity (+ позже UC).
- **Диапазон:** `[0, ∞)`; ниже — лучше (при сопоставимом качестве).

### stability_multi_run / latency_ms / token_usage / cost_usd
- **Назначение:** устойчивость и стоимость.
- **Формула:** TBD при реальных LLM; в scaffold = `null`.
- **Ограничения:** требуют инструментирования клиента.

## Политика freeze

См. `benchmark/FREEZE_POLICY.md`. Целевая дата freeze v1.0: **2026-08-26**.
