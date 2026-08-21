# Agent NIR — Traceable Use Case & Activity Diagram Pipeline

Исследовательский каркас (Python 3.11+, LangGraph, Pydantic v2) для генерации
структурированных Use Cases и activity-диаграмм по функциональным требованиям
с проверяемой трассировкой и ограниченным repair-loop.

> **Статус (2026-08-21):** каркас моделей, графов, детерминированных валидаторов,
> Mermaid-renderer и benchmark/evaluator. Реальные LLM-промпты и эксперименты
> **не** реализованы.

## Быстрый старт

```bash
cd Agent
poetry install
poetry run pytest
poetry run python -c "from traceable_spec.graph import compile_pipeline; compile_pipeline(); print('ok')"
```

## Структура

| Путь | Назначение |
|------|------------|
| `src/traceable_spec/entities.py` | Pydantic-контракты и TypedDict State |
| `src/traceable_spec/use_cases_graph.py` | Подграф генерации Use Cases |
| `src/traceable_spec/activity_diagram_graph.py` | Подграф activity model + Mermaid |
| `src/traceable_spec/graph.py` | Корневой pipeline |
| `src/traceable_spec/validators/` | Детерминированные проверки |
| `src/traceable_spec/mermaid/` | Детерминированный рендер Mermaid |
| `benchmark/` | Формат кейсов и development-пример |
| `docs/` | Постановка, план, архитектура, ADR |

## Границы этапа

- Нет реальных вызовов LLM / платных моделей.
- LLM-узлы — stub/fake через dependency injection.
- Соседний проект `AppFactory-agents` **не** переиспользуется.

## Документация

См. `docs/research/WEEK_1_ANALYSIS.md` и `docs/architecture/SYSTEM_DESIGN_V0_1.md`.
