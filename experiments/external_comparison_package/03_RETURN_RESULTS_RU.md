# Файлы результата

## Claude

Исходные JSON-ответы разместить так:

```text
responses/
├── B1-DEV-002/
│   ├── r01.json
│   ├── r02.json
│   └── r03.json
├── B1-DEV-010/
│   ├── r01.json
│   ├── r02.json
│   └── r03.json
└── B1-DEV-020/
    ├── r01.json
    ├── r02.json
    └── r03.json
```

Если доступны технические данные, рядом с ответом добавить, например,
`r01.meta.json`:

```json
{
  "provider": "Anthropic",
  "model_label": "Claude Opus 5",
  "model_id": "точное значение из интерфейса или API",
  "latency_ms": null,
  "prompt_tokens": null,
  "completion_tokens": null,
  "total_tokens": null,
  "provider_reported_cost_usd": null
}
```

Неизвестные значения остаются `null`, а не заменяются нулём.

## Импорт Claude

После помещения файлов в `responses/` команда запускается из корня
репозитория:

```bash
poetry run python scripts/evaluate_external_model_outputs.py \
  --model-label claude-opus-5 \
  --package-dir experiments/external_comparison_package \
  --semantic-backend multilingual \
  --experiment-id external-claude-opus-5-dev3-r3
```

Результат появится в:

`artifacts/external_model_runs/external-claude-opus-5-dev3-r3/`.

## GPT внутри pipeline

Нужно вернуть каталог:

`artifacts/benchmark_runs/external-gpt-dev3-r3/`.

В нём должны сохраниться `results.json`, `results.csv`, конфигурации каждого
запуска, сгенерированные спецификации, трассировка, Mermaid и отчёты проверок.

## Общие сведения

Для каждого способа зафиксировать:

- точное отображаемое название модели;
- точный model ID, если он доступен;
- дату запуска;
- использованный интерфейс или API;
- известные ограничения контекста и выходного ответа;
- информацию о том, были ли показаны токены, задержка и стоимость.

Секретные ключи и `.env` возвращать нельзя.
