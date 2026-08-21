# Модель трассируемости

Дата: **2026-08-21**

## Принцип

Единственное хранилище связей — `TraceManifest.links: list[TraceLink]`.  
Прямой и обратный индексы **вычисляются** (`forward_index()`, `reverse_index()`), а не редактируются вручную в обе стороны.

## Элемент связи `TraceLink`

| Поле | Смысл |
|------|--------|
| `source_type` / `source_id` | Тип и ID источника |
| `target_type` / `target_id` | Тип и ID назначения |
| `link_type` | Тип связи (`fr_to_uc`, `step_to_activity_node`, …) |
| `origin` | `llm` \| `deterministic` \| `human` \| `repair` |
| `rationale` | Опциональное обоснование |

## Схема стабильных ID

| Сущность | Пример |
|----------|--------|
| Functional requirement | `FR-001` |
| Non-functional requirement | `NFR-001` |
| Use Case | `UC-001` |
| User Story | `US-001` |
| System Story | `SS-001` |
| Scenario step | `STEP-UC001-001` |
| Activity node / edge | `ADN-UC001-001` / `ADE-UC001-001` |
| Activity diagram | `AD-UC001` |
| Trace link | `TL-001` |

## Обязательные правила

1. Каждый UC ссылается минимум на один FR (`source_fr_ids` + links `fr_to_uc`).
2. Непокрытый FR либо покрыт UC, либо явно помечен в `fr_coverage` (`uncovered` / `out_of_scope` / `conflicting`).
3. Концы каждого `TraceLink` существуют в объединённом пространстве ID артефактов этапа.
4. Activity action/decision узлы связаны со step UC **или** помечены `unsupported=true`.
5. Mermaid **не** источник трассировки.

## Этапность манифеста

1. После UC-графа: FR/NFR ↔ UC, UC ↔ US/SS, при необходимости FR ↔ STEP.
2. После activity-графа: STEP ↔ ADN/ADE, UC ↔ AD.
3. E2E validator проверяет полный манифест.

## Альтернативы (отклонённые)

| Альтернатива | Почему нет |
|--------------|------------|
| Двусторонние списки `uc.traced_frs` + `fr.traced_ucs` | Рассинхрон, сложный merge при repair |
| Только текстовые упоминания ID в prose | Не валидируется детерминированно |
| Embed trace только в Mermaid comments | Mermaid — derived view |
