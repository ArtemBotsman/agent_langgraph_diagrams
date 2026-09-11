# Benchmark v1.0 candidate

Канонический benchmark (тестовый набор) текущей НИР находится в
`v1_0_synthetic/`. Старые `manifest.json` и `cases/development/library_desk_v1/`
сохранены как исторический G0-scaffold и не используются финальным evaluator.

## Состав

```text
benchmark/
├── v1_0_synthetic/
│   ├── cases.json              # 30 SpecificationReq + author gold
│   ├── development_cases.json  # 20 открытых DEV-кейсов
│   ├── hidden_inputs.json      # 10 hidden-входов без gold
│   ├── sealed_hidden_gold.json # отделённый hidden gold
│   ├── manifest.json           # версия, распределения и source hash
│   └── freeze_record.json      # контрольные SHA-256
├── expert_review/
│   ├── RUBRIC.md
│   ├── expert_1_blank.csv
│   └── expert_2_blank.csv
├── CHANGELOG.md
└── FREEZE_POLICY.md
```

Набор содержит 20 development и 10 hidden cases, 8 simple / 13 medium / 9 hard,
13 русских / 17 английских. Каждый `specification_req` имеет шесть полей,
включая `project_task`, ФТ и НФТ.

## Gold и несколько правильных ответов

Gold (эталон) задаёт не координаты пикселей и не единственный Mermaid-текст, а
семантические slots (ожидаемые элементы): акторы, цели UC, обязательные
milestones, ветвления, связи FR→UC, сохранение NFR и запрещённые предположения.
`equivalence_policy` разрешает переименование, эквивалентное split/merge UC и
линейных activity nodes, если сохраняется смысл.

## Split policy

- `development` разрешён для отладки pipeline, prompts и метрик до scientific
  freeze.
- `hidden_inputs.json` не содержит gold и не должен использоваться для
  настройки.
- `sealed_hidden_gold.json` открывается только для финального однократного
  расчёта после согласования руководителя и scientific freeze.

## Текущий freeze

`freeze_record.json` фиксирует author technical freeze: байты и split защищены
SHA-256, но экспертная проверка и approval руководителя ещё не завершены. Это
не следует называть утверждённым научным benchmark.

Проверка без изменения файлов:

```bash
poetry run python scripts/validate_synthetic_benchmark.py
poetry run python scripts/freeze_synthetic_benchmark.py
```

Намеренное обновление author freeze допускается только после документированного
изменения benchmark и выполняется с `--force`. Все изменения фиксируются в
`CHANGELOG.md`.
