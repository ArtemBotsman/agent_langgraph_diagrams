# Куда положить ответы модели

В пакете 20 development-кейсов. Для каждого кейса выполните три независимых
запуска в новых диалогах и сохраните
только JSON-ответы:

```text
responses/
  B1-DEV-001/r01.json
  B1-DEV-001/r02.json
  B1-DEV-001/r03.json
  ...
```

Если доступны токены и задержка, рядом можно сохранить `r01.meta.json`:

```json
{
  "model": "точное название или ID модели",
  "prompt_tokens": null,
  "completion_tokens": null,
  "total_tokens": null,
  "latency_ms": null,
  "provider_reported_cost_usd": null
}
```
