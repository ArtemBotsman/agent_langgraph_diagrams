# Внешние one-shot ответы для size-scaling benchmark

Эта папка предназначена для ответов Claude/GPT, полученных в
режиме одного прямого вызова. Входы берутся из
`benchmark/size_scaling_v1/inputs/`, а prompt и схема ответа остаются
теми же, что в `experiments/claude_opus_5_dev20/`.

## Структура возврата

Для каждого из 20 кейсов нужны три независимых ответа:

```text
responses/
  <case_id>/
    r01.json
    r01.meta.json
    r02.json
    r02.meta.json
    r03.json
    r03.meta.json
```

`rXX.json` содержит только JSON-результат по заданной схеме, без
ручных исправлений. `rXX.meta.json` фиксирует фактические метаданные:

```json
{
  "provider": "provider name",
  "model_id": "exact model id",
  "temperature": 0,
  "prompt_tokens": null,
  "completion_tokens": null,
  "total_tokens": null,
  "latency_ms": null,
  "cost_usd": null,
  "finish_reason": null
}
```

Если провайдер не возвращает показатель, оставляется `null`, а не
выдумывается ноль.

## Единая оценка

После копирования ответов:

```bash
poetry run python scripts/evaluate_size_scaling_outputs.py \
  --responses-dir experiments/size_scaling_external/responses \
  --experiment-id claude-oneshot-size-scaling-r3
```

Скрипт применяет те же Pydantic-схемы, детерминированные
валидаторы, TraceManifest и Mermaid renderer, что и основной
pipeline. Это делает сравнение технически сопоставимым.

Raw responses локально исключены из Git, пока не согласованы условия
хранения и публикации.
