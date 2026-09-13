# Запуск GPT внутри AgentLangGraph

## Где находится скрипт

Путь от корня репозитория:

`scripts/run_benchmark_experiment.py`

Репозиторий:
[agent_langgraph_diagrams](https://github.com/ArtemBotsman/agent_langgraph_diagrams)

Прямая ссылка после публикации текущей версии:
[run_benchmark_experiment.py](https://github.com/ArtemBotsman/agent_langgraph_diagrams/blob/main/scripts/run_benchmark_experiment.py)

## Что делает скрипт

На трёх одинаковых development-кейсах выполняются два режима:

- `B1_ONESHOT` — один запрос к GPT сразу формирует весь результат;
- `FULL` — тот же GPT используется внутри двух агентов, после генерации
  выполняются детерминированные проверки, смысловая критика и ограниченное
  исправление.

Каждый режим повторяется три раза. Скрипт сохраняет входы, конфигурацию,
структурированные результаты, трассировку, Mermaid, отчёты проверок, метрики,
токены, задержку и стоимость при наличии тарифных данных.

## Настройка модели

В локальном `.env` должны быть заданы параметры доступного OpenAI-compatible
endpoint. Точные значения endpoint и model ID берутся из используемого
провайдера:

```dotenv
LLM_PROVIDER=<provider>
LLM_API_BASE=<OpenAI-compatible API base>
LLM_MODEL=<точный model ID>
LLM_API_KEY_ENV=<имя переменной с ключом>
<имя переменной с ключом>=<секретный ключ>
LLM_MAX_OUTPUT_TOKENS=8000
```

`.env` и ключ не добавляются в Git и не включаются в возвращаемый архив.

## Команда

Команда запускается из корня репозитория:

```bash
poetry install

poetry run python scripts/run_benchmark_experiment.py \
  --condition B1_ONESHOT \
  --condition FULL \
  --case-id B1-DEV-002 \
  --case-id B1-DEV-010 \
  --case-id B1-DEV-020 \
  --repeats 3 \
  --allow-live \
  --semantic-backend multilingual \
  --max-live-calls 400 \
  --max-live-tokens 6000000 \
  --experiment-id external-gpt-dev3-r3 \
  --capture-raw-private-dir .private_experiment_evidence/external-gpt-dev3-r3
```

Если multilingual-модель оценки ещё не установлена, добавить один раз
`--allow-model-download`. После загрузки повторные запуски выполняются без этого
флага.

## Где появляется результат

Основной каталог:

`artifacts/benchmark_runs/external-gpt-dev3-r3/`

Нужны:

- `results.json`;
- `results.csv`;
- все каталоги режимов `B1_ONESHOT/` и `FULL/`;
- точное название модели и model ID;
- приватные raw request/response — только если их разрешено передавать.

API-ключ передавать нельзя.
