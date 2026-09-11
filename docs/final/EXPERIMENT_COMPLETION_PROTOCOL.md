# Протокол завершения эксперимента

## 1. До платного запуска

1. Получить письменное подтверждение основного MODEL_ID/API_BASE и профиля
   Mermaid/UML.
2. Получить явное разрешение пользователя на лимит расходов.
3. Не изменять hidden gold и не использовать hidden для выбора prompt.
4. Проверить `poetry run pytest`, freeze и mutation-suite.

## 2. Representative DEV pilot

Сначала выполнить B1 и FULL на DEV-002, DEV-010 и DEV-020 с одним повтором.
Рекомендуемые guards: 60 calls, 450 000 tokens и 0.40 USD. Если одновременно
запускаются FULL_NO_CRITIC и FULL_NO_REPAIR, использовать 160 calls, 1 200 000
tokens и 0.90 USD.

Для строгого протокола raw evidence сохранять только в private storage:

```bash
poetry run python scripts/run_benchmark_experiment.py \
  --condition B1_ONESHOT --condition FULL \
  --case-id B1-DEV-002 --case-id B1-DEV-010 --case-id B1-DEV-020 \
  --repeats 1 --allow-live --semantic-backend multilingual \
  --max-live-calls 60 --max-live-tokens 450000 \
  --max-estimated-cost-usd 0.40 \
  --capture-raw-private-dir .private_experiment_evidence
```

## 3. Full DEV

После анализа representative pilot пересчитать бюджет. Выполнить FULL и две
варианты без отдельных компонентов на 20 DEV минимум с тремя повторами, если позволяет утверждённый бюджет.
Не исправлять outputs вручную.

Для каждого запуска сохранить config, generated specification, calls,
validation, trace, metrics, checkpoints и private raw evidence. Затем выполнить:

```bash
poetry run python scripts/verify_saved_experiment.py <experiment_dir> --write-report
poetry run python scripts/analyze_saved_experiment.py <experiment_dir> --write-report
```

## 4. Expert review и scientific freeze

Два эксперта независимо заполняют формы. После расчёта agreement допускаются
только протоколированные исправления DEV/gold. Затем фиксируются commit и tag.

## 5. Hidden

Hidden запускается один раз после freeze. Результаты не используются для
настройки. Любая ошибка сохраняется и входит в итоговый анализ.
