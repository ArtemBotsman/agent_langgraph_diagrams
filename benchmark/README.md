# Benchmark scaffold for Agent NIR

Каркас benchmark для оценки трассируемого pipeline генерации Use Cases и
activity-диаграмм. **Полноценный набор из ~30 кейсов пока не утверждён** —
здесь только инфраструктура и один синтетический development-пример.

Дата фиксации каркаса: **2026-08-21**.

## Структура

```
benchmark/
  README.md                 # этот файл
  manifest.json             # реестр кейсов и split policy
  FREEZE_POLICY.md          # правила заморозки
  cases/
    development/
      library_desk_v1/      # один synthetic example
        case.json
        expected_notes.md
    hidden/                 # пусто до появления согласованных кейсов
      .gitkeep
```

## Формат benchmark case (`case.json`)

Минимальные поля:

| Поле | Тип | Описание |
|------|-----|----------|
| `case_id` | string | Стабильный ID, например `DEV-001` |
| `split` | `development` \| `hidden` | Split policy |
| `complexity` | enum | `simple`, `medium`, `hard`, `many_frs`, `branching`, `incomplete_conflict` |
| `title` | string | Краткое название |
| `specification_request` | object | Соответствует `SpecificationRequest` |
| `notes` | string | Необязательные комментарии для разработчика |
| `gold` | object \| null | Опциональные эталонные артефакты (UC IDs, coverage map); может отсутствовать на ранних этапах |

В `specification_request` обязательно сохраняется исходный `project_task`.

## Split policy

- **development** — открытые кейсы для отладки pipeline, валидаторов и метрик.
- **hidden** — скрытые кейсы для финальной оценки. **Запрещено** настраивать систему
  по hidden-результатам после freeze (см. `FREEZE_POLICY.md`).

## Уровни сложности

1. `simple` — 1–3 ФТ, один основной сценарий.
2. `medium` — несколько UC, альтернативы.
3. `hard` — исключения, несколько акторов, НФТ.
4. `many_frs` — большое число ФТ, риск orphan/duplicate UC.
5. `branching` — decision/merge/fork в activity.
6. `incomplete_conflict` — намеренно неполные или конфликтующие требования.

## Заморозка

Целевой freeze **benchmark v1.0**: до **2026-08-26**. До freeze состав кейсов
может меняться; после freeze — только bugfix формата без изменения семантики
gold/hidden.
