# ADR-003: Mermaid flowchart TD для MVP

- **Дата:** 2026-08-21
- **Статус:** Accepted

## Контекст
Нужен человекочитаемый экспорт activity-модели. Сравнивались `flowchart` и `stateDiagram-v2`.

## Сравнение

| Критерий | flowchart | stateDiagram-v2 |
|----------|-----------|-----------------|
| Action nodes | Да (прямоугольники) | Состояния, семантика другая |
| Decision + guard | Да (`{}` + edge labels) | Ограниченнее для activity |
| Merge / fork-join | Эмулируется | Слабее для concurrency activity |
| Start/end | Да | Да |
| Swimlanes / partitions | `subgraph` | Нет нативного аналога |
| Близость к UML Activity | Частичная | Ближе к state machine |

## Решение
MVP: **flowchart TD** + subgraph partitions. Источник истины — `ActivityDiagram`.

## Ограничения Mermaid vs UML 2.5.1 Activity
Нет полной семантики object flows, interruptible regions, токенов; fork/join — условная нотация. Это фиксируется как threat to validity.
