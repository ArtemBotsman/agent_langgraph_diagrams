# Выбор LLM, логирование и план экспериментов

Дата проверки: 2026-09-08.

Документ относится к текущей НИР: генерации структурированных Use Cases и
activity-диаграмм из `SpecificationReq`. Старый проект полного SDLC в scope не
входит.

Обозначения:

- `VERIFIED` — подтверждено кодом, тестом, исходным документом или официальной
  документацией;
- `INFERRED` — осторожный вывод из расшифровки;
- `PROPOSED` — рекомендация, которую ещё нужно реализовать или согласовать.

## 1. Короткий ответ по выбору модели

### Для разработки и pilot study

`PROPOSED`: использовать **`qwen/qwen3.8-27b` через Groq Free Plan**.

Почему этот вариант подходит:

- в созвоне упоминалось семейство Qwen, хотя точная версия распознана
  ненадёжно;
- Groq предоставляет OpenAI-совместимый endpoint, близкий к текущему
  `LLMClient` Protocol;
- модель поддерживает строгий structured output по JSON Schema;
- на дату проверки официальный Free Plan указывает 30 RPM, 1000 RPD, 8000 TPM
  и 200000 TPD;
- одного API достаточно для generator, critic и repair.

Ограничение: бесплатной квоты достаточно для разработки и небольшого пилота,
но не гарантированно для полной матрицы из 30 кейсов, нескольких конфигураций и
повторных прогонов.

### Для финального эксперимента

`PROPOSED`: сначала получить лабораторный доступ, который руководитель
упоминала в созвоне 2026-08-21. В расшифровке слышно, что доступ запрашивался в
проекте МАС и отправлялся в личные сообщения. Распознанное слово «Лайтолам» с
высокой вероятностью означает **LiteLLM** — единый gateway/SDK, а не название
конкретной модели.

У руководителя нужно уточнить четыре значения:

1. `API_BASE` лабораторного gateway;
2. имя переменной или формат API key;
3. точный `MODEL_ID`;
4. квоты, политика хранения запросов и разрешение использовать доступ в
   benchmark.

Точное имя Qwen-модели и endpoint из аудио восстановить нельзя. Их нельзя
угадывать и фиксировать как факт.

### Baseline и fallback

Для сравнения рекомендуется добавить:

- `openai/gpt-oss-120b` или `openai/gpt-oss-20b` через Groq как второй
  OpenAI-compatible one-shot baseline;
- `gemini-3.7-flash` через Gemini API как baseline другого провайдера;
- `openrouter/free` использовать только для ручной разведки. Случайный выбор
  бесплатной модели делает его плохим основным baseline для воспроизводимого
  эксперимента.

Gemini поддерживает JSON Schema/Pydantic structured output и бесплатный tier,
но активные rate limits зависят от проекта и проверяются в AI Studio. В
бесплатном tier данные могут использоваться провайдером для улучшения продуктов;
не отправлять закрытые или персональные требования.

## 2. Как получить API key

### Groq

1. Открыть `https://console.groq.com/` и войти в аккаунт.
2. Создать отдельный project для НИР.
3. Открыть API Keys и создать ключ.
4. Скопировать ключ один раз и сохранить только локально.
5. Не присылать ключ в рабочий чат, не вставлять в исходники, Markdown,
   notebook outputs или Git history.

Рекомендуемые локальные переменные:

```dotenv
GROQ_API_KEY=<local-secret>
LLM_API_BASE=https://api.groq.com/openai/v1
LLM_MODEL=qwen/qwen3.8-27b
LLM_TEMPERATURE=0
```

Файл `.env` должен быть в `.gitignore`. В репозитории допустим только
`.env.example` без значения ключа.

### Лабораторный LiteLLM gateway

Найти сообщение руководителя около упомянутой даты «21 апреля» в проекте/чате
МАС либо попросить переслать доступ ещё раз. Для gateway нужны `API_BASE`, key и
model alias. Сам LiteLLM бесплатен как библиотека, но стоимость и квота зависят
от подключённого провайдера или лабораторного бюджета.

### Gemini

1. Открыть Google AI Studio.
2. Создать или импортировать Google Cloud project.
3. На странице API Keys создать ключ.
4. Сохранить его локально как `GEMINI_API_KEY`.

Google отдельно рекомендует переменную окружения и запрещает раскрывать ключ в
client-side коде или репозитории.

## 3. Что фактически используется сейчас

`VERIFIED`: внешняя LLM в проекте **не подключена**.

- `src/traceable_spec/llm/protocol.py` задаёт только интерфейс `LLMClient`.
- `src/traceable_spec/llm/scripted.py` содержит `ScriptedLLMClient`.
- `ScriptedLLMClient` не обращается в сеть и возвращает заранее подготовленный
  JSON из очереди.
- UC-подграф умеет вызывать этот интерфейс для generator, critic и repair.
- Activity-подграф использует sample/stub generator, critic и repair.
- Корневой pipeline по умолчанию собирается со stub-зависимостями.
- `pyproject.toml` пока не содержит `litellm`, `openai`, `groq`, `google-genai`
  или отдельной HTTP-библиотеки для real adapter.

Следовательно, сейчас невозможно честно ответить, «сколько проект тратит
токенов»: он тратит **0 API tokens**, потому что live API не вызывается.
Поля `latency_ms`, `token_usage` и `cost_usd` в evaluator равны `None`.

## 4. Как работают текущие графы

### Корневой LangGraph pipeline

1. `normalize_requirements` принимает внешний `SpecificationReq` и создаёт
   стабильные `FR-###`/`NFR-###`.
2. `run_use_cases` запускает UC-подграф.
3. `run_activities` последовательно запускает Activity-подграф для каждого UC.
4. `validate_e2e_trace` проверяет итоговую трассировку.
5. `run_evaluator` рассчитывает автоматические метрики.
6. `finalize_pipeline` формирует `GeneratedSpecification`.

### UC-подграф

```text
prepare
  → generate
  → schema validation
  → deterministic validation
  → LLM critic
  → decide
      → finalize
      → repair → schema validation
      → controlled failure
```

При успешном проходе без repair выполняются два LLM-вызова: generator и critic.
Каждый repair добавляет ещё два вызова: repair и повторный critic.

### Activity-подграф

Структура аналогична UC-подграфу, затем типизированная `ActivityDiagram`
детерминированно преобразуется в Mermaid. На 2026-09-08 его LLM-узлы не
реализованы.

Для `U` Use Cases и одного repair с вероятностью `p` на каждой генеративной
стадии ожидаемое число вызовов полного pipeline приблизительно:

```text
calls_per_run = 2 × (1 + U) × (1 + p)
```

Пример: `U=3`, `p=0.25` даёт около 10 LLM-вызовов на один входной кейс.

## 5. Какие логи есть сейчас

`VERIFIED`:

- `ScriptedLLMClient.calls` сохраняет только роль, model, temperature,
  response format и число сообщений;
- `validation_reports` сохраняют результаты schema-, structural-, trace- и
  semantic-проверок внутри состояния;
- `TraceManifest` хранит происхождение продуктовых элементов. Это не runtime
  tracing и не журнал LLM-вызовов;
- стандартного structured logging, raw output persistence, latency/token/cost
  telemetry, LangSmith tracing и checkpointer/resume пока нет.

В проверенном scripted demo было четыре вызова:

```text
generator → critic → repair → critic
```

Pipeline успешно завершился после одного repair и сохранил 12 validation
reports. Это подтверждает маршрутизацию ошибок, но не качество модели.

## 6. Какие логи нужно реализовать

`PROPOSED`: локальный JSON/JSONL является источником истины. Внешний
observability-сервис можно подключить дополнительно, но воспроизводимость не
должна от него зависеть.

Структура одного запуска:

```text
runs/<experiment_id>/<condition>/<case_id>/<repeat_id>/
  input.json
  config.json
  calls.jsonl
  prompts/
  raw_responses/
  generated_specification.json
  validation_reports.json
  trace_manifest.json
  metrics.json
  diagrams/*.mmd
  diagrams/*.svg
```

Каждая строка `calls.jsonl` должна содержать:

- `run_id`, `case_id`, `condition`, `repeat_id`, `call_id`;
- имя graph/node и роль `generator|critic|repair`;
- номер repair-attempt;
- requested/resolved provider и model;
- model revision или `system_fingerprint`, если провайдер возвращает;
- prompt version и schema version;
- UTC start/end, `latency_ms`, HTTP status и retry count;
- `prompt_tokens`, `completion_tokens`, `reasoning_tokens`, `cached_tokens`,
  `total_tokens`;
- finish reason и нормализованный тип ошибки;
- SHA-256 prompt/raw response либо относительные пути к ним.

`config.json` должен фиксировать commit SHA, dirty flag, Python version,
dependency lock hash, temperature, seed, max output tokens, repair limit и
provider limits. Секреты и полное значение API key не сохраняются.

## 7. Фактические автоматические тесты

`VERIFIED`: явный запуск `python3.11 -m pytest` даёт **23 passed**.

Проверяются:

- валидация и round-trip Pydantic-моделей;
- принятие финального шестиполевого `SpecificationReq`;
- стабильная нумерация FR/NFR;
- отклонение неизвестных полей;
- дубликаты ID, неизвестные акторы, непокрытые FR и dangling links;
- некорректные activity edges и недостижимый final node;
- bounded repair;
- компиляция UC, Activity и root graphs;
- детерминированность Mermaid-renderer;
- scripted UC: accept, обнаружение trace error, успешный repair, исчерпание
  лимита, invalid JSON и output contract.

Ограничения проверки:

- тесты offline и не измеряют качество настоящей LLM;
- Ruff сейчас сообщает 9 правил `UP042` для `str, Enum`;
- Poetry создал Python 3.13 env без установленных project dependencies;
  `poetry run python examples/run_uc_scripted_pipeline.py` падает из-за
  отсутствующего Pydantic;
- `poetry run pytest` на этой машине подхватывает внешний
  `/opt/homebrew/bin/pytest`, поэтому clean-environment reproducibility пока не
  доказана;
- mypy не установлен в активный Poetry env.

Это нужно исправить до слайда «воспроизводимость» и проверить установку из
чистого окружения отдельной командой/CI job.

## 8. Исследовательские вопросы

### RQ1 — качество

Повышает ли многостадийный traceable pipeline качество UC/activity artifacts по
сравнению с one-shot генерацией при одинаковых input, модели и output contract?

### RQ2 — вклад компонентов

Какой вклад дают deterministic validators, LLM critic и bounded repair?

### RQ3 — трассировка

Повышает ли явная типизированная модель трассировки полноту и ссылочную
целостность без увеличения числа неподтверждённых элементов?

### RQ4 — устойчивость и цена

Как меняются качество, стабильность, latency и token usage с ростом сложности и
числа требований?

## 9. Benchmark

Формальный план требует около 30 кейсов. Сейчас в репозитории есть только один
synthetic development case `DEV-001`. JSON регистрации мероприятия является
вторым реальным входом, но ещё не включён в benchmark manifest.

`PROPOSED` состав benchmark v1.0:

- 30 кейсов всего;
- 12 development и 18 hidden;
- по пять кейсов на каждый основной класс сложности: `simple`, `medium`,
  `hard`, `many_frs`, `branching`, `incomplete_conflict`;
- размер от 2–3 до 50+ атомарных ФТ;
- русский и английский язык учитывать как отдельный фактор либо зафиксировать
  только русский для основной НИР;
- hidden-разметку не использовать для prompt tuning после freeze.

Если руководитель не передаст обещанные 30 кейсов, нужно согласовать уменьшенный
benchmark письменно. Самостоятельно выдавать синтетические 30 кейсов за
предоставленный набор нельзя.

Gold-разметка каждого кейса должна включать:

- атомарные части ФТ и ожидаемый coverage status;
- допустимые границы и набор UC;
- акторов, основные/альтернативные/ошибочные сценарии;
- обязательные scenario milestones и branches;
- ожидаемые FR→UC, FR→step, UC→story и step→activity links;
- известные конфликты, missing information и допустимые assumptions;
- правила эквивалентности, когда возможно несколько корректных декомпозиций.

## 10. Конфигурации эксперимента

Основную модель, входы, schema version, prompt version, temperature, output
limit и repeat IDs нужно фиксировать.

Минимальная матрица:

1. `FULL_QWEN`: полный pipeline с deterministic validators, critic и repair.
2. `NO_DETERMINISTIC`: отключены бизнес/trace validators; schema validation
   остаётся обязательной для безопасного parsing.
3. `NO_CRITIC`: deterministic validators и repair работают без LLM critic.
4. `ONESHOT_QWEN`: один запрос той же Qwen-модели с тем же входом и итоговой
   схемой; изолирует эффект pipeline от качества модели.
5. `ONESHOT_GPT_OSS`: one-shot сильной модели другого семейства через Groq.
6. `ONESHOT_GEMINI`: one-shot `gemini-3.7-flash` с тем же контрактом.

Дополнительная абляция, если хватает квоты:

- `NO_REPAIR`: generator + validators + critic, но без повторной генерации.

DeepWiki-Open, GitDiagram, Pyreverse, Mermaid CLI и другие code/model-to-diagram
инструменты не получают тот же вход и не должны попадать в одну количественную
таблицу как прямые baseline. Их показывают на отдельном слайде как смежные
подходы.

## 11. Протокол запусков

### Pilot

- 6 development-кейсов: по одному на класс сложности;
- 3 повторных запуска;
- сначала `FULL_QWEN`, `NO_DETERMINISTIC`, `NO_CRITIC`, `ONESHOT_QWEN`;
- затем один внешний baseline;
- цель: проверить pipeline, evaluator, logging, runtime и размер квоты.

### Final

- все hidden cases после freeze;
- минимум 3 повторных запуска, 5 — если позволяет бюджет;
- все шесть обязательных конфигураций;
- порядок конфигураций и кейсов рандомизировать;
- не редактировать raw output вручную;
- одинаковые лимиты и timeout;
- сохранить даже failed/429/timeout runs;
- evaluator пересчитать отдельно по сохранённым outputs и убедиться, что
  повторный расчёт идентичен.

Основное сравнение рекомендуется проводить при `temperature=0`. Отдельный
robustness subset можно прогнать при `temperature=0`, `0.3` и `0.7`.

## 12. Метрики

### Валидность и успешность

- `schema_valid_rate`;
- `end_to_end_success_rate`;
- `controlled_failure_rate`;
- `mermaid_parse_rate` и `mermaid_render_rate`;
- доля запусков без ручного вмешательства.

### Покрытие и качество UC

- precision/recall/F1 покрытия **атомарных частей ФТ**;
- UC matching precision/recall/F1 с учётом допустимых вариантов gold;
- actor precision/recall/F1;
- обязательные main/alternative/exception scenarios coverage;
- scenario step coverage и order consistency;
- duplicate/near-duplicate UC rate;
- unsupported assumption и hallucinated element rate;
- доля корректно обнаруженных conflicts/missing information.

Текущий `fr_coverage` по наличию `source_fr_ids` является только структурным
proxy и не доказывает смысловую корректность покрытия.

### Activity diagrams

- node/edge structural validity;
- start/final reachability;
- decision/merge/fork/join correctness;
- scenario milestone coverage;
- branch coverage;
- step order consistency;
- actor partition consistency;
- Mermaid parse/render success.

Текущий `mermaid_generation_success` проверяет лишь непустую строку. Для
эксперимента нужен фактический parse/render.

### Трассировка

- link precision/recall/F1 отдельно для каждого `TraceLinkType`;
- dangling source/target rate;
- forward coverage: FR→UC→step→activity;
- reverse provenance coverage: доля activity nodes/edges с допустимым UC
  source;
- unsupported trace element rate;
- полнота UC→user story и UC→system story.

### Repair

- repair trigger rate;
- repair success/recovery rate;
- среднее и p95 числа repair attempts;
- regression rate: доля ранее корректных свойств, сломанных repair;
- доля controlled failures после исчерпания лимита.

### Устойчивость

- success rate по повторным запускам;
- pairwise Jaccard для trace edges;
- устойчивость FR→UC partition, например Adjusted Rand Index;
- среднее и standard deviation ключевых quality metrics;
- variation rate набора UC, акторов и branches;
- чувствительность к permutation порядка ФТ;
- чувствительность к перефразированию требований.

### Эффективность

- LLM calls per run;
- prompt/completion/reasoning/cached/total tokens;
- latency per call и end-to-end latency: median, p95;
- retries, 429 и timeout rate;
- tokens per successful case;
- tokens per quality point и quality gain per extra 1000 tokens;
- фактическая стоимость и reference paid-equivalent cost.

На бесплатном tier `cost_usd=0` не заменяет token accounting: вычислительная
нагрузка всё равно сравнивается по токенам и вызовам.

### Экспертная оценка

Два независимых эксперта вслепую оценивают по шкале 1–5:

- корректность акторов и границ UC;
- полноту сценариев;
- соответствие требованиям;
- корректность activity-flow;
- пригодность результата для раннего согласования пользователем.

Показывать межэкспертное согласие: weighted Cohen's kappa или ICC. LLM-as-a-
judge, если используется, хранить отдельной дорожкой и не смешивать с экспертной
оценкой.

## 13. Статистический анализ

- Для каждой метрики показывать число кейсов и число запусков.
- Для rates показывать долю и 95% bootstrap confidence interval.
- Для continuous metrics показывать median, IQR, mean и standard deviation.
- Сравнения проводить попарно на одних и тех же case/repeat IDs.
- Для бинарного success использовать McNemar test.
- Для непараметрических continuous metrics использовать Wilcoxon signed-rank
  либо paired bootstrap difference.
- Показывать effect size, а не только p-value.
- Для множественных сравнений использовать Holm correction.
- Не выдавать plan thresholds из XLSX за экспериментальные результаты.

## 14. Оценка нагрузки

Для расчёта использовать фактические server-side token counts из API response,
а не символы или приблизительный tokenizer другого семейства.

Пример **оценки**, не результата:

- `U=3` UC на кейс;
- вероятность одного repair на стадии `p=0.25`;
- 6 условий;
- `FULL` и `NO_DETERMINISTIC`: примерно по 10 calls;
- `NO_CRITIC`: примерно 5 calls;
- три one-shot baseline: по 1 call;
- итого около 28 calls на один `case × repeat`.

Pilot `6 cases × 3 repeats` требует около 504 calls. При условных 2500 total
tokens на вызов это около 1.26 млн tokens. Qwen/Groq-часть при free limit 200000
TPD потребуется распределить примерно на неделю; реальный срок зависит от
размера JSON output и текущей квоты проекта.

Final `18 hidden × 3 repeats` при той же матрице — около 1512 calls. Это ещё до
повторов из-за 429/timeout. Поэтому финальный эксперимент лучше выполнять на
лабораторном gateway или после отдельного согласования бюджета.

## 15. Итоговые таблицы для отчёта и презентации

Формировать таблицы автоматически из `metrics.json`/`calls.jsonl`.

Обязательные таблицы:

1. **Main comparison** — condition, model, cases, repeats, success rate, FR F1,
   UC F1, trace F1, activity score, hallucination rate, tokens, latency.
2. **Ablation deltas** — отличие каждого ablation от `FULL_QWEN` с 95% CI.
3. **Complexity breakdown** — показатели по шести классам сложности.
4. **Stability** — mean, SD, min/max, trace Jaccard и partition ARI.
5. **Efficiency** — calls, prompt/output/total tokens, latency p50/p95, retries,
   429, cost.
6. **Error analysis** — классы ошибок, частота, стадия обнаружения, repair
   recovery.
7. **Validator mutation test** — внесённые дефекты, expected detection,
   observed detection, false positives.
8. **Expert evaluation** — blinded score и agreement.

В строках с failed run нельзя подставлять нули в недоступные semantic metrics.
Хранить `n.a.` и отдельно учитывать failure rate, иначе неуспешная система может
получить искусственно хороший средний показатель.

## 16. Дашборд для демонстрации

### Страница 1 — Executive comparison

- KPI: cases, runs, E2E success, FR F1, trace F1, total tokens;
- grouped bars по quality metrics;
- quality-versus-token scatter;
- подпись: experiment ID, benchmark version, commit и дата.

### Страница 2 — Ablations

- delta bars относительно `FULL_QWEN`;
- quality gain и дополнительное число calls/tokens;
- confidence intervals.

### Страница 3 — Robustness

- распределение метрик по repeats;
- trace Jaccard и FR→UC partition stability;
- результаты permutation/paraphrase tests.

### Страница 4 — Error analysis

- stacked bars по schema/structural/trace/semantic/policy errors;
- repair recovery funnel;
- список representative failures с case/run IDs.

### Страница 5 — Trace example

- один понятный путь `FR atom → UC → scenario step → activity node/edge`;
- рядом исходное требование, фрагмент UC и Mermaid/SVG;
- этот слайд объясняет практическую ценность лучше абстрактного графа.

### Страница 6 — Run explorer

- фильтры по condition, model, complexity, case и repeat;
- raw/normalized output, validation issues, token usage и latency;
- ссылки только на сохранённые локальные артефакты без секретов.

## 17. Порядок реализации

1. Исправить clean Poetry install/CI и подтвердить `python=3.11`.
2. Добавить event-signup JSON как development case.
3. Реализовать provider-agnostic LiteLLM/OpenAI-compatible adapter.
4. Расширить `LLMClient` так, чтобы он возвращал текст и usage metadata, а не
   только `str`.
5. Добавить локальное run logging и сохранение raw outputs.
6. Реализовать Activity prompts/live nodes.
7. Усилить trace validators и реальный Mermaid parse/render.
8. Добавить mutation tests для каждого заявленного validator class.
9. Провести pilot и откалибровать evaluator.
10. Заморозить benchmark/prompts/schema/config.
11. Провести final repeated experiment.
12. Сгенерировать таблицы, графики и presentation-ready examples только из
    сохранённых результатов.

## Официальные источники, проверенные 2026-09-08

- Groq rate limits: https://console.groq.com/docs/rate-limits
- Groq structured outputs: https://console.groq.com/docs/structured-outputs
- Groq OpenAI compatibility: https://console.groq.com/docs/openai
- Groq API reference/usage: https://console.groq.com/docs/api-reference
- LiteLLM: https://docs.litellm.ai/
- Gemini API keys: https://ai.google.dev/gemini-api/docs/api-key
- Gemini structured output: https://ai.google.dev/gemini-api/docs/structured-output
- Gemini pricing: https://ai.google.dev/gemini-api/docs/pricing
- Gemini rate limits: https://ai.google.dev/gemini-api/docs/rate-limits
