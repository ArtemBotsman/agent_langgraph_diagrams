# Эксперимент с GPT-5.5 и Claude Opus 5

## Готовый пакет Claude

Переносимый ZIP-архив для передачи:

[`AgentLangGraph_claude_opus_5_DEV20_2026-09-11.zip`](../final/deliverables/AgentLangGraph_claude_opus_5_DEV20_2026-09-11.zip)

Основная единая инструкция находится в:

`experiments/claude_opus_5_dev20/00_CLAUDE_OPUS_5_RUNBOOK_AND_PROMPT_RU.md`

В этом одном файле находятся порядок запуска, правила сравнения, схема
сохранения ответов и полный prompt (инструкция для модели) вместе с JSON Schema
(схемой выхода).

Для одного обращения к Claude передаются только два материала:

1. указанный выше файл с prompt;
2. один `SpecificationReq` из
   `experiments/claude_opus_5_dev20/inputs/`.

## Связь с benchmark из 30 кейсов

Да, эксперимент основан на наших 30 тестовых `SpecificationReq`, но использует их
поэтапно:

1. `DEV3` (пилот): простой `B1-DEV-002`, средний `B1-DEV-010` и сложный
   `B1-DEV-020`. По три повтора, всего 9 ответов.
2. `DEV20` (основной development-эксперимент): все 20 открытых DEV-кейсов по три
   повтора, всего 60 ответов.
3. Оставшиеся 10 кейсов не используются для настройки. Финальный test-run (тестовый
   запуск) выполняется однократно после фиксации метода.

Пакет Claude содержит только DEV20. В нём нет gold-разметки, hidden-входов и
ключей.

## Запуск GPT-5.5 внутри pipeline

Экспериментальный скрипт:

`scripts/run_benchmark_experiment.py`

Путь в репозитории:

[scripts/run_benchmark_experiment.py](../../scripts/run_benchmark_experiment.py)

Скрипт запускает два сопоставимых условия:

- `B1_ONESHOT` (один запрос): GPT-5.5 за один вызов формирует весь комплект артефактов;
- `FULL` (полный pipeline): GPT-5.5 работает внутри двух агентов с валидацией,
  критикой и ограниченным исправлением.

Команда DEV20 из корня репозитория:

```bash
poetry install --with evaluation

poetry run python scripts/run_benchmark_experiment.py \
  --condition B1_ONESHOT \
  --condition FULL \
  --split development \
  --all-cases \
  --repeats 3 \
  --allow-live \
  --semantic-backend multilingual \
  --allow-model-download \
  --max-live-calls 900 \
  --max-live-tokens 8000000 \
  --experiment-id external-gpt-5-5-dev20-r3 \
  --capture-raw-private-dir .private_experiment_evidence/external-gpt-5-5-dev20-r3
```

Перед полным запуском нужно задать в локальном `.env` точные `LLM_API_BASE`,
`LLM_MODEL`, `LLM_API_KEY_ENV` и секретный ключ в переменной, имя которой указано
в `LLM_API_KEY_ENV`. При необходимости также задаётся `LLM_PROVIDER`. Файл `.env`
не передаётся и не публикуется.

## Прямой запуск Claude Opus 5

Для каждого входа создаётся новый диалог. В него передаются один `SpecificationReq` и точный
prompt из пакета. Модель возвращает:

1. типизированный набор Use Cases;
2. User Stories и System Stories;
3. одну Activity Diagram для каждого Use Case;
4. `source_fr_ids` для Use Cases и шагов;
5. `related_step_ids` для узлов и рёбер диаграммы.

По этим ссылкам тот же детерминированный алгоритм строит полный `TraceManifest` и
Mermaid-код. Поэтому Claude и AgentLangGraph оцениваются одинаковым evaluator (оценщиком).

Ответы сохраняются без ручной правки. Невалидный JSON или обрезанный ответ учитывается как
неудачный запуск, а не исправляется вручную.

## Импорт и оценка Claude

После получения ответов они размещаются в:

`experiments/claude_opus_5_dev20/responses/<CASE_ID>/r01.json`

Скрипт оценки:

`scripts/evaluate_external_model_outputs.py`

Команда:

```bash
poetry run python scripts/evaluate_external_model_outputs.py \
  --model-label claude-opus-5 \
  --package-dir experiments/claude_opus_5_dev20 \
  --semantic-backend multilingual \
  --allow-model-download \
  --experiment-id external-claude-opus-5-dev20-r3
```

В итоге сохраняются исходные ответы, разобранные артефакты, валидация, `TraceManifest`,
Mermaid, метрики и агрегированная таблица.

## Что требуется на сервере

Для прямой генерации Claude достаточно распаковать ZIP и иметь доступ к Claude
Opus 5 любым доступным в лаборатории способом. Для каждого запуска передаются
точный prompt из runbook и один JSON-файл `SpecificationReq`; исходный JSON-ответ
сохраняется в указанную папку без ручной коррекции.

Для запуска GPT-5.5 внутри AgentLangGraph и для автоматической оценки ответов
Claude требуется клонированный репозиторий, Python 3.11+, Poetry и доступ в сеть
для LLM API и однократной загрузки модели семантической оценки. Ключи задаются
только в локальном `.env` на сервере.

## Условия сопоставимости

- одинаковые DEV-входы;
- неизменный prompt и выходной контракт;
- три независимых повтора;
- нулевая температура, если она доступна;
- никакой ручной коррекции ответов;
- одинаковые parser, validators, renderer и evaluator;
- точное название и model ID модели;
- токены, задержка и стоимость, если провайдер их показывает.

Основная таблица будет сопоставлять `B0_RULE`, `B1_ONESHOT`, `FULL`, `FULL_NO_CRITIC`,
`FULL_NO_REPAIR`, GPT-5.5 one-shot, GPT-5.5 FULL и Claude Opus 5 one-shot.

## Важное ограничение hidden-части

Текущие 10 кейсов с меткой `HID` уже присутствовали в публичном `cases.json`. Их можно
использовать как фиксированную test-часть, но нельзя называть строго секретной. Для
строгого hidden-эксперимента нужны новые 10 кейсов, которые хранятся отдельно и не
попадают в открытый репозиторий до финальной оценки.
