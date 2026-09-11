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

Ты выступаешь как системный аналитик и архитектор ПО. На вход тебе передан один
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    wanted = tuple(args.case_id or DEFAULT_CASE_IDS)
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    selected = [case for case in cases if case["case_id"] in wanted]
    selected_by_id = {case["case_id"]: case for case in selected}
    missing = sorted(set(wanted) - set(selected_by_id))
    if missing:
        raise SystemExit(f"Unknown case IDs: {missing}")
    if any(case["split"] != "development" for case in selected):
        raise SystemExit("External handoff package may contain development cases only")

    output = args.output_dir
    input_dir = output / "inputs" / "pilot_dev3"
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
        input_dir / "pilot_dev3_inputs.json",
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
    (prompt_dir / "CLAUDE_OR_GPT_ONESHOT_PROMPT_RU.md").write_text(
        _prompt(schema),
        encoding="utf-8",
    )
    (response_dir / "README.md").write_text(
        """# Куда положить ответы модели

Для каждого кейса выполните три независимых запуска в новых диалогах и сохраните
только JSON-ответы:

```text
responses/
  B1-DEV-002/r01.json
  B1-DEV-002/r02.json
  B1-DEV-002/r03.json
  B1-DEV-010/r01.json
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
