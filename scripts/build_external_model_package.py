"""Build the supervisor handoff package for strong external-model baselines."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from traceable_spec.entities import OneShotGenerationArtifact

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "benchmark" / "v1_0_synthetic" / "cases.json"
DEFAULT_OUTPUT = ROOT / "experiments" / "external_models"
DEFAULT_CASE_IDS = ("B1-DEV-002", "B1-DEV-010", "B1-DEV-020")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _prompt(schema: dict[str, Any]) -> str:
    schema_json = json.dumps(schema, ensure_ascii=False, indent=2)
    return f"""# Prompt для прямой генерации полного набора артефактов

Ты выполняешь задачу системного анализа требований. На вход тебе передан один
JSON-файл `SpecificationReq`. По нему сформируй полный набор Use Cases, User
Stories, System Stories и одну activity-диаграмму для каждого Use Case.

Верни только один JSON-объект без Markdown, пояснений и блоков ```.

Правила:

1. Присвой функциональным требованиям ID `FR-001`, `FR-002`, ... по порядку во
   входном массиве. Нефункциональным требованиям присвой `NFR-001`, ... .
2. Не теряй требования и не добавляй бизнес-правила, которых нет во входе.
3. Выдели акторов и Use Cases по бизнес-целям, а не по словам предложения.
4. Для каждого Use Case сформируй основной, альтернативные и исключительные
   сценарии, если они следуют из требований.
5. Каждый Use Case обязан содержать `source_fr_ids`. Каждый шаг сценария обязан
   содержать `source_fr_ids`.
6. Для каждого Use Case создай ровно одну `ActivityDiagram`. Каждый action и
   decision node обязан иметь `related_step_ids`. Каждое ребро обязано иметь
   `related_step_ids` на тот шаг, переход к которому оно выражает.
7. Диаграмма обязана иметь ровно один initial node, достижимый final node и
   guard на исходящих рёбрах decision node.
8. Идентификаторы должны точно соответствовать шаблонам JSON Schema:
   `ACT-001`, `UC-001`, `STEP-UC001-001`, `AD-UC001`, `ADN-UC001-001`,
   `ADE-UC001-001`, `PART-UC001-001`.
9. Поле `mermaid_source` оставь `null`: Mermaid будет построен единым
   детерминированным renderer после проверки структуры.
10. Поле `trace_manifest.links` верни пустым массивом. Полная двусторонняя
    трассировка будет построена единым детерминированным алгоритмом из
    `source_fr_ids`, `source_nfr_ids`, `use_case_id` и `related_step_ids`.
11. Если информации недостаточно, запиши это в `missing_information`. Не
    подменяй неизвестные данные предположениями.
12. Ответ должен пройти приложенную JSON Schema без дополнительных полей.

JSON Schema результата:

```json
{schema_json}
```
"""


def _runbook(prompt_text: str, case_count: int) -> str:
    return f"""# Эксперимент Claude Opus 5: инструкция и точный prompt

## Цель

Проверить, как Claude Opus 5 справляется с той же задачей, которую
решает AgentLangGraph: из одного `SpecificationReq` сформировать Use Cases
(варианты использования), User Stories (пользовательские истории), System
Stories (системные истории), Activity Diagrams (диаграммы активности) и
исходные связи для полной трассировки.

В пакете находятся {case_count} development-кейсов. Gold-эталоны, hidden-кейсы и
API-ключи в пакет не входят.

## Что этот пакет запускает

Пакет задаёт воспроизводимый протокол прямого запуска внешней модели: точный
prompt, входы, JSON Schema результата и правила сохранения ответов. Способ
обращения к Claude (веб-интерфейс, внутренний сервис лаборатории или API) выбирает
исполнитель, потому что адрес сервиса и учётные данные в пакет намеренно не
включены. Для самой генерации установка AgentLangGraph не требуется.

Для автоматического расчёта общих метрик нужен основной репозиторий
AgentLangGraph: в нём находится скрипт импорта сохранённых ответов.

## Что передать Claude для одного запуска

1. Один файл `inputs/B1-DEV-XXX.json`.
2. Весь раздел «Точный prompt» из этого файла.

Каждый кейс и каждый повтор запускаются в новом диалоге без истории. Текст
prompt и входной JSON между повторами не меняются. Если интерфейс позволяет,
устанавливается `temperature=0`; иначе фиксируется, что параметр не был доступен.

## Сколько запусков делать

1. Сначала pilot (пилот): `B1-DEV-002`, `B1-DEV-010`, `B1-DEV-020`, по три повтора.
   Получится 9 ответов. Этот этап проверяет совместимость формата.
2. После успешного импорта pilot запустить все {case_count} development-кейсов по три
   повтора. Для DEV20 это 60 ответов.
3. Hidden-часть на этапе разработки не запускать.

## Как сохранить ответы

Сохраняется исходный JSON без ручной коррекции:

```text
responses/B1-DEV-001/r01.json
responses/B1-DEV-001/r02.json
responses/B1-DEV-001/r03.json
...
```

Если ответ не соответствует JSON Schema (схеме JSON), он всё равно сохраняется как
результат запуска. Нельзя вручную менять ID, трассировку или содержание. Рядом
можно сохранить `r01.meta.json` с точным model ID (идентификатором модели), токенами,
задержкой и стоимостью, если они доступны.

## Где находятся скрипты

- запуск AgentLangGraph на GPT: `scripts/run_benchmark_experiment.py`;
- импорт и оценка ответов Claude: `scripts/evaluate_external_model_outputs.py`.

Оба скрипта запускаются из корня клонированного репозитория AgentLangGraph.
Для GPT-5.5 нужен OpenAI-compatible endpoint (совместимая точка API). Локальный
`.env` на сервере заполняется без передачи ключа в репозиторий:

```dotenv
LLM_PROVIDER=gpt-5.5
LLM_API_BASE=<адрес OpenAI-compatible API>
LLM_MODEL=<точный ID модели>
LLM_API_KEY_ENV=GPT55_API_KEY
GPT55_API_KEY=<секретный ключ>
```

Сначала выполняется пилот на трёх кейсах:

```bash
poetry install --with evaluation
poetry run python scripts/run_benchmark_experiment.py \\
  --condition B1_ONESHOT \\
  --condition FULL \\
  --split development \\
  --case-id B1-DEV-002 \\
  --case-id B1-DEV-010 \\
  --case-id B1-DEV-020 \\
  --repeats 3 \\
  --allow-live \\
  --semantic-backend multilingual \\
  --allow-model-download \\
  --max-live-calls 180 \\
  --max-live-tokens 1600000 \\
  --experiment-id external-gpt-5-5-dev3-r3
```

После успешного пилота параметры `--case-id` заменяются на `--all-cases`, а
лимиты увеличиваются с учётом квот используемого сервиса. Точное имя провайдера,
model ID, фактические токены, задержка и стоимость сохраняются вместе с
результатами.

Команда импорта запускается из корня репозитория:

```bash
poetry run python scripts/evaluate_external_model_outputs.py \\
  --model-label claude-opus-5 \\
  --package-dir experiments/claude_opus_5_dev20 \\
  --semantic-backend multilingual \\
  --allow-model-download \\
  --experiment-id external-claude-opus-5-dev20-r3
```

## Что будет сравниваться

Ответы Claude проходят тот же parser (разборщик), Pydantic-схемы, детерминированные
валидаторы, TraceManifest (манифест трассировки), Mermaid renderer (рендерер) и
evaluator (оценщик), что и `B1_ONESHOT`. Это делает формат и метрики сопоставимыми.

Фиксируются `E2E success` (сквозной успех), Actor/Use Case/Milestone/Branch/Trace
F1, доля неподтверждённых элементов, стабильность повторов, токены, задержка и
стоимость. Невалидный или обрезанный ответ учитывается как неудачный запуск.

---

## Точный prompt

{prompt_text}
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--case-id", action="append")
    selection.add_argument(
        "--all-development",
        action="store_true",
        help="Export every development case without gold labels.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    wanted = (
        tuple(case["case_id"] for case in cases if case["split"] == "development")
        if args.all_development
        else tuple(args.case_id or DEFAULT_CASE_IDS)
    )
    selected = [case for case in cases if case["case_id"] in wanted]
    selected_by_id = {case["case_id"]: case for case in selected}
    missing = sorted(set(wanted) - set(selected_by_id))
    if missing:
        raise SystemExit(f"Unknown case IDs: {missing}")
    if any(case["split"] != "development" for case in selected):
        raise SystemExit("External handoff package may contain development cases only")

    output = args.output_dir
    input_dir = output / "inputs"
    prompt_dir = output / "prompt"
    schema_dir = output / "schema"
    response_dir = output / "responses"
    for directory in (input_dir, prompt_dir, schema_dir, response_dir):
        directory.mkdir(parents=True, exist_ok=True)

    ordered = [selected_by_id[case_id] for case_id in wanted]
    for case in ordered:
        _write_json(input_dir / f"{case['case_id']}.json", case["specification_req"])
        (response_dir / case["case_id"]).mkdir(parents=True, exist_ok=True)

    _write_json(
        input_dir / "development_inputs.json",
        [
            {
                "case_id": case["case_id"],
                "title": case["title"],
                "complexity": case["complexity"],
                "language": case["language"],
                "specification_req": case["specification_req"],
            }
            for case in ordered
        ],
    )
    schema = OneShotGenerationArtifact.model_json_schema()
    _write_json(schema_dir / "one_shot_generation_artifact.schema.json", schema)
    prompt_text = _prompt(schema)
    (prompt_dir / "CLAUDE_OR_GPT_ONESHOT_PROMPT_RU.md").write_text(
        prompt_text,
        encoding="utf-8",
    )
    (output / "00_CLAUDE_OPUS_5_RUNBOOK_AND_PROMPT_RU.md").write_text(
        _runbook(prompt_text, len(wanted)),
        encoding="utf-8",
    )
    example_case = wanted[0]
    (response_dir / "README.md").write_text(
        f"""# Куда положить ответы модели

В пакете {len(wanted)} development-кейсов. Для каждого кейса выполните три независимых
запуска в новых диалогах и сохраните
только JSON-ответы:

```text
responses/
  {example_case}/r01.json
  {example_case}/r02.json
  {example_case}/r03.json
  ...
```

Если доступны токены и задержка, рядом можно сохранить `r01.meta.json`:

```json
{{
  "model": "точное название или ID модели",
  "prompt_tokens": null,
  "completion_tokens": null,
  "total_tokens": null,
  "latency_ms": null,
  "provider_reported_cost_usd": null
}}
```
""",
        encoding="utf-8",
    )

    files = sorted(path for path in output.rglob("*") if path.is_file())
    manifest = {
        "package_version": "1.0.0",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "case_ids": list(wanted),
        "split": "development",
        "recommended_repeats": 3,
        "execution_rule": "one fresh conversation per case and repeat",
        "output_contract": "OneShotGenerationArtifact",
        "hidden_included": False,
        "gold_included": False,
        "api_keys_included": False,
        "files": [
            {
                "path": str(path.relative_to(output)),
                "sha256": _sha256(path),
            }
            for path in files
            if path.name != "package_manifest.json"
        ],
    }
    _write_json(output / "package_manifest.json", manifest)
    print(output)


if __name__ == "__main__":
    main()
