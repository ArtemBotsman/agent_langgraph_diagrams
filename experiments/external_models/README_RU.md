# Сравнение с сильными внешними моделями

Эта папка содержит пакет, который можно передать научному руководителю для
запуска GPT и Claude на тех же входах, что использовались в диагностическом
эксперименте AgentLangGraph.

## Что сравнивается

1. `FULL + GPT` — тот же двухагентный LangGraph pipeline, но с сильной внешней
   моделью. Этот вариант показывает, как замена LLM влияет на результат при
   неизменной архитектуре.
2. `B1_ONESHOT + GPT` — та же модель и тот же итоговый контракт, но один запрос
   без критика и исправления. Сравнение с `FULL + GPT` измеряет вклад графа.
3. `Claude one-shot` — прямое решение той же задачи по одному общему prompt.
   Ответ проходит тот же Pydantic parser, deterministic validators, renderer,
   trace builder и evaluator.

## Входы

Используются только три development-кейса, уже применявшиеся в пилоте:

- `B1-DEV-002` — простой русскоязычный кейс;
- `B1-DEV-010` — средний русскоязычный кейс;
- `B1-DEV-020` — сложный англоязычный кейс.

Gold-разметка в передаваемый пакет не включена. Рекомендуется выполнить по три
независимых запуска каждого условия. Каждый повтор Claude должен выполняться в
новом диалоге без истории предыдущих ответов.

## Запуск GPT внутри AgentLangGraph

В локальном `.env` задаются OpenAI-compatible endpoint, точный model ID и имя
переменной с ключом. Ключ нельзя добавлять в Git.

```dotenv
LLM_PROVIDER=<provider>
LLM_API_BASE=<openai-compatible API base>
LLM_MODEL=<точный model ID>
LLM_API_KEY_ENV=<имя переменной ключа>
<имя переменной ключа>=<секрет>
LLM_MAX_OUTPUT_TOKENS=8000
```

Экспериментальный runner:

```bash
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
  --experiment-id external-gpt-dev3-r3
```

## Запуск Claude по готовому prompt

Для каждого входа из `inputs/pilot_dev3/`:

1. открыть новый диалог;
2. приложить один JSON-файл `SpecificationReq`;
3. отправить текст из `prompt/CLAUDE_OR_GPT_ONESHOT_PROMPT_RU.md`;
4. сохранить только JSON-ответ в `responses/<case-id>/r01.json`;
5. повторить в новых диалогах для `r02.json` и `r03.json`;
6. зафиксировать точное название модели и, если интерфейс показывает, токены и
   задержку в соседнем `r01.meta.json`.

## Локальная оценка возвращённых ответов

```bash
poetry run python scripts/evaluate_external_model_outputs.py \
  --model-label claude-opus-5 \
  --package-dir experiments/external_models \
  --semantic-backend multilingual \
  --experiment-id external-claude-opus-5-dev3-r3
```

Скрипт сохраняет стандартные `results.json`, `results.csv`, сгенерированные
Mermaid-файлы, трассировку и отчёты в `artifacts/external_model_runs/`. Ответы
оцениваются без ручного исправления.

## Почему сравнение сопоставимо

- одинаковые входы и порядок ID требований;
- один выходной Pydantic-контракт;
- один алгоритм построения TraceManifest и Mermaid;
- одинаковые structural, trace и E2E validators;
- один semantic evaluator и одинаковая gold-разметка;
- неуспешные JSON и E2E-отказы остаются в результатах;
- точные model ID, число запусков, токены и задержка сохраняются.

Сравнивать следует E2E success, actor/UC/milestone/branch/trace F1,
hallucination proxy, stability, latency, токены и стоимость. Одного
`semantic_composite` недостаточно для вывода.
