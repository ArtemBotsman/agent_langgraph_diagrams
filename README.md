# Agent NIR — Traceable Use Case & Activity Diagram Pipeline

Проект НИР — трассируемый конвейер вариантов использования и диаграмм активности.

Исследовательский каркас (Python 3.11+, LangGraph, Pydantic v2) для генерации
структурированных Use Cases и activity-диаграмм по функциональным требованиям
с проверяемой трассировкой и ограниченным repair-loop.

> **Статус (2026-09-11):** в системе два агента: `Use Case Agent` (агент
> вариантов использования) и `Activity Diagram Agent` (агент диаграмм
> активности). Реализованы модели, графы, валидаторы, Mermaid-renderer
> (рендерер диаграмм), benchmark/evaluator (тестовый набор и оценщик) и
> OpenAI-compatible adapter (совместимый клиент LLM), live Activity path,
> bounded repair, SQLite persistence, единый CLI и offline CI. Repeated DEV-001
> pilot выполнен: FULL 2/2 E2E, one-shot 0/2. B0 завершён на DEV20 (60/60).
> На DEV-002/010/020 выполнено прямое сравнение пяти конфигураций; после
> уточнения доказательного контракта критика FULL завершил 3/3, B1 и вариант
> без исправления — 0/3.
> Добавлены offline verification, error analysis и приватное opt-in сохранение
> raw evidence. Полный B1/FULL DEV20, эксперты и hidden ещё не завершены.

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
poetry install --with evaluation
poetry run pytest
poetry run python -c "from traceable_spec.orchestration import compile_pipeline; compile_pipeline(); print('ok')"
```

Один полный offline-запуск с упаковкой всех артефактов:

```bash
poetry run traceable-spec \
  examples/event_signup_specification_req.json \
  artifacts/single_runs/event-signup-b0 \
  --mode B0_RULE
```

Для реального двухагентного пути замените режим на `FULL` и явно добавьте
`--allow-live --env-file .env`. Команда и содержимое result bundle (пакета
результатов) подробно описаны в `docs/release/REPRODUCIBILITY_AND_DEMO.md`.

Полный локальный quality gate (контроль качества), не выполняющий сетевых LLM-
вызовов:

```bash
poetry check --lock
poetry run ruff check .
poetry run mypy src
poetry run pytest
poetry run python scripts/validate_synthetic_benchmark.py
poetry run python scripts/freeze_synthetic_benchmark.py
poetry run python scripts/run_validator_mutation_suite.py --check-existing
poetry run python scripts/verify_saved_experiment.py \
  artifacts/benchmark_runs/b0-dev20-r3-2026-09-09
poetry run python scripts/verify_saved_experiment.py \
  artifacts/benchmark_runs/repeated-b0-b1-full-dev001-2026-09-09
poetry build
```

Тот же набор автоматически выполняется GitHub Actions из
`.github/workflows/ci.yml`. Ключи провайдеров в CI не требуются.

## Структура

```text
src/traceable_spec/
├── agents/
│   ├── use_case/              # Use Case Agent: graph + prompts
│   └── activity/              # Activity Diagram Agent: graph + prompts
├── orchestration/             # root pipeline + SQLite persistence/resume
├── reference_methods/         # B0 rules + B1 one-shot baselines
├── entities.py                # Pydantic contracts + TypedDict state
├── traceability.py            # FR → atom → UC → step → activity trace
├── validators/                # deterministic quality gates
├── evaluation/                # benchmark metrics
├── llm/                       # OpenAI-compatible provider adapter
└── mermaid/                   # deterministic diagram renderer
```

Старые импорты `traceable_spec.graph`, `use_cases_graph`,
`activity_diagram_graph`, `persistence` и `baselines` оставлены как короткий
compatibility layer (слой совместимости). Новую логику нужно искать в папках
`agents/`, `orchestration/` и `reference_methods/`.

На верхнем уровне:

- `benchmark/` — 30 cases (кейсов), DEV20/hidden10, freeze и формы экспертов;
- `configs/providers/` — безопасные примеры DeepSeek и Groq/Qwen без ключей;
- `scripts/` — воспроизводимые эксперименты и построение графиков;
- `artifacts/` — результаты запусков;
- `docs/` — архитектура, исследование, материалы руководителю и Obsidian;
- `tests/` — автоматические проверки.

## Текущая и предлагаемая модель

Новые live-прогоны выполнены с `deepseek-flash` через
`https://api.deepseek.com`; legacy-идентификатор `deepseek-v4-flash`
использовался в первых сохранённых пилотах. Профиль `qwen/qwen3.8-27b` через Groq подготовлен в
`configs/providers/groq-qwen.env.example`, но не запускался: локальный
`GROQ_API_KEY` пока отсутствует. Эти результаты нельзя смешивать в одну группу.

## Границы этапа

- Выполнены repeated pilot на DEV-001 и диагностическое сравнение на трёх
  репрезентативных DEV-кейсах. Они доказывают работу validation/repair, но ещё
  не критерий ≥90% на всём DEV.
- B0 отдельно выполнен на всём DEV20: 60/60 технических завершений, semantic
  0,408 с bootstrap 95% CI `[0,356; 0,463]`, 0 LLM-токенов.
- `semantic_composite` является candidate dashboard metric; внешние expert
  scores и supervisor approval не имитируются.
- Hidden gold отделён и не использовался для live tuning.
- Старые проекты используются только как архитектурный reference (ориентир),
  их код не копируется без проверки лицензии.

## Лицензия

Код проекта опубликован по MIT License, согласованной с полем `license = "MIT"`
в `pyproject.toml`. Возможность публикации синтетического benchmark и hidden-
части всё равно требует отдельного подтверждения научного руководителя.

## Документация

См. `docs/research/TECHNOLOGY_PROJECT_COMPARISON_2026_09_11.md`,
`docs/research/BASELINES_AND_LIVE_EVIDENCE_2026_09_09.md`,
`docs/benchmark/BENCHMARK_AND_METRICS_V0_1.md` и
`docs/architecture/SYSTEM_DESIGN_V0_1.md`. Итоговый текст, доклад и протокол
завершения эксперимента находятся в `docs/final/`. Ссылки на готовые DOCX,
PDF, PPTX и XLSX собраны в
`docs/obsidian_vault/19_ФИНАЛЬНЫЙ_ПАКЕТ_ОТЧЕТ_ПРЕЗЕНТАЦИЯ_И_ЭКСПЕРИМЕНТ.md`.
Публикационные копии доступны прямо в репозитории:

- [рекомендуемая презентация для пересдачи](docs/final/deliverables/AgentLangGraph_technology_project_resit_v2_2026-09-11.pptx);
- [технологический отчёт PDF](docs/final/deliverables/AgentLangGraph_technology_report_final_2026-09-11.pdf);
- [пакет внешнего сравнения](docs/final/deliverables/AgentLangGraph_external_comparison_DEV3_portable_2026-09-11.zip).

Для сопоставимого запуска сильной внешней модели подготовлены
[`SpecificationReq`-входы, точная JSON-схема и единый prompt](experiments/external_comparison_package/00_START_HERE_RU.md).
Ответы GPT/Claude импортируются через тот же контракт, Mermaid renderer и
evaluator; инструкция для руководителя находится в
[`EXTERNAL_MODEL_EXPERIMENT_HANDOFF.md`](docs/supervisor_review/EXTERNAL_MODEL_EXPERIMENT_HANDOFF.md).
