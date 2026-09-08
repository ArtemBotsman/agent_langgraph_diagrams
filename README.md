# Agent NIR — Traceable Use Case & Activity Diagram Pipeline

Проект НИР — трассируемый конвейер вариантов использования и диаграмм активности.

Исследовательский каркас (Python 3.11+, LangGraph, Pydantic v2) для генерации
структурированных Use Cases и activity-диаграмм по функциональным требованиям
с проверяемой трассировкой и ограниченным repair-loop.

> **Статус (2026-09-09):** в системе два агента: `Use Case Agent` (агент
> вариантов использования) и `Activity Diagram Agent` (агент диаграмм
> активности). Реализованы модели, графы, валидаторы, Mermaid-renderer
> (рендерер диаграмм), benchmark/evaluator (тестовый набор и оценщик) и
> OpenAI-compatible adapter (совместимый клиент LLM). Живой Activity-путь и
> repeated LLM experiment (эксперимент с повторами) ещё не выполнены. Ключ и
> `deepseek-v4-flash` прошли минимальный smoke test (проверку соединения).

## С чего начать

Для первого знакомства откройте
[`docs/obsidian_vault/00_НАЧАТЬ_ЗДЕСЬ.md`](docs/obsidian_vault/00_НАЧАТЬ_ЗДЕСЬ.md).
Папку `docs/obsidian_vault/` можно открыть отдельно в Obsidian (программе для
связанных заметок): там есть карта каталогов, схемы агентов, индекс всех 30
входов, вопросы для защиты, правила DeepSeek и план будущей презентации.
Полная развиваемая версия описания находится в
[`10_ГЛАВНЫЙ_ДОКУМЕНТ_ПРОЕКТА.md`](docs/obsidian_vault/10_ГЛАВНЫЙ_ДОКУМЕНТ_ПРОЕКТА.md);
исходный подробный текст не сокращён.

## Входной контракт

Внешний вход pipeline согласован с научным руководителем и представлен
`SpecificationReq` (`TypedDict`):

```python
class SpecificationReq(TypedDict):
    project_task: str
    project_name: str
    project_goal: str
    project_description: str
    functional_requirements: list[str]
    non_functional_requirements: list[str]
```

Первый узел корневого LangGraph детерминированно преобразует строки требований
в внутренний `SpecificationRequest`: `FR-001`, `FR-002`, ... и `NFR-001`, ... .
Поле `project_task` сохраняется и передаётся в UC generator/critic/repair prompts.

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
| `scripts/run_static_analysis_baseline.sh` | Локальный code-to-UML baseline на Pyreverse |
| `docs/` | Постановка, план, архитектура, ADR |

## Границы этапа

- Выполнен только минимальный DeepSeek smoke test: 91 токен, без оценки качества
  агентов и без массового запуска benchmark.
- UC-путь проверен через `ScriptedLLMClient` (тестовый клиент); Activity-путь
  пока использует `stub` (заглушки).
- Старые проекты используются только как архитектурный reference (ориентир),
  их код не копируется без проверки лицензии.

## Документация

См. `docs/research/WEEK_1_ANALYSIS.md` и `docs/architecture/SYSTEM_DESIGN_V0_1.md`.
