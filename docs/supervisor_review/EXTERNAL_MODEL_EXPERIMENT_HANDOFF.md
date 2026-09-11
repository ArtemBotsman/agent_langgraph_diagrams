# Пакет эксперимента для научного руководителя

Рекомендуемый архив для передачи:
`docs/final/deliverables/AgentLangGraph_external_comparison_DEV3_portable_2026-09-11.zip`.
После распаковки работа начинается с `00_START_HERE_RU.md`. В архиве нет
ключей, hidden-кейсов и gold-разметки.

## Что можно отправить

1. `experiments/external_comparison_package/prompt/CLAUDE_PROMPT_RU.md` —
   единый prompt для прямой генерации.
2. Три JSON из `experiments/external_comparison_package/inputs/` — одинаковые
   входы простого, среднего и сложного уровня.
3. `experiments/external_comparison_package/schema/OUTPUT_SCHEMA.json`
   — машиночитаемый выходной контракт, уже включённый в prompt.
4. `experiments/external_comparison_package/00_START_HERE_RU.md` — порядок
   запуска и переходы к отдельным инструкциям GPT/Claude.

После запуска следует вернуть исходные JSON-ответы без ручного исправления,
точное название и model ID, а также доступные значения tokens, latency и cost.
API-ключ передавать не нужно.

## Какой скрипт запускать

Для GPT внутри разработанного pipeline:

`scripts/run_benchmark_experiment.py`

Он запускает `B1_ONESHOT` и `FULL` на одинаковых кейсах, сохраняет настройки,
исходные результаты, ошибки, токены, задержку, трассировку и метрики.

Для ответов Claude, полученных вручную или через другой интерфейс:

`scripts/evaluate_external_model_outputs.py`

Он применяет к возвращённому JSON тот же parser, валидаторы, построение
TraceManifest, Mermaid renderer и evaluator, что используются для B1.

## Экспериментальный вопрос

Сравнение отвечает сразу на два вопроса:

1. Улучшает ли сильная модель результат внутри неизменного AgentLangGraph?
2. Даёт ли многошаговый граф преимущество относительно одного запроса той же
   модели и прямой генерации Claude?

Основной результат нельзя определять только по красоте диаграммы. Для каждого
условия учитываются сквозной успех, смысловые F1, трассировка, устойчивость,
токены, задержка и стоимость.
