"""Build a reviewable Gold candidate for the 20 size-scaling inputs.

The annotation prompt sees only the source SpecificationReq. It never reads
B0, B1 or FULL outputs. The produced labels remain an author-level candidate
until two independent reviewers approve them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from traceable_spec.llm.factory import create_instrumented_client, provider_config_from_env

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BENCHMARK = ROOT / "benchmark" / "size_scaling_v1"
DEFAULT_OUTPUT = DEFAULT_BENCHMARK / "gold_candidate.json"
DEFAULT_PRIVATE_DIR = ROOT / ".private_evidence" / "size_scaling_gold_candidate"
JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", flags=re.IGNORECASE)


SYSTEM_PROMPT = """Ты размечаешь эталон для оценки генерации Use Cases из требований.
Работай только с переданным SpecificationReq. Не добавляй функции, которых нет во входе.
Выделяй Use Case по цели внешнего участника или целостному системному процессу, а не по
экрану и не по каждому полю формы. Все FR обязаны входить хотя бы в один Use Case.
Допускай несколько корректных декомпозиций: имена и границы будут проверяться с учётом
синонимов и поддержанного split/merge. Верни только один JSON-объект без Markdown.
"""


def _load_local_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() and name.strip() not in os.environ:
            os.environ[name.strip()] = value.strip().strip('"').strip("'")


def _canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _extract_json(text: str) -> dict[str, Any]:
    stripped = JSON_FENCE_RE.sub("", text.strip())
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("annotation response does not contain a complete JSON object")
    value = json.loads(stripped[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("annotation response must be a JSON object")
    return value


def _annotation_prompt(case: dict[str, Any], request: dict[str, Any]) -> str:
    numbered_frs = [
        {"id": f"FR-{index:03d}", "text": text}
        for index, text in enumerate(request["functional_requirements"], start=1)
    ]
    payload = {
        "case_id": case["case_id"],
        "project_name": request["project_name"],
        "project_goal": request["project_goal"],
        "project_description": request["project_description"],
        "functional_requirements": numbered_frs,
    }
    return f"""Подготовь Gold-кандидат для следующего проекта.

Правила:
1. actor_slots содержит внешние роли и явно действующие системные роли. Объединяй
   грамматические варианты одной роли и перечисляй их в any_of.
2. use_case_slots группирует FR в целостные цели. Каждый FR должен присутствовать хотя
   бы в одном source_fr_ids. Избегай одного огромного UC и искусственного UC на каждое поле.
3. Для каждого UC задай 1–6 required_milestones: короткие наблюдаемые действия или
   результаты, прямо подтверждённые его FR.
4. required_branches добавляй только для явно заданных условий, альтернатив, отказов,
   согласований, нехватки ресурса или изменения статуса. Укажи condition и 1–4 outcomes.
5. primary_actor должен совпадать с canonical одного actor_slots.
6. forbidden_assumptions перечисляет 2–6 правдоподобных, но отсутствующих во входе функций.
7. known_ambiguity перечисляет только реальные неоднозначности входа; допустим пустой список.
8. Все тексты разметки пиши по-русски. Не включай NFR в source_fr_ids.

Точный формат:
{{
  "actor_slots": [{{"canonical": "роль", "any_of": ["синоним"]}}],
  "use_case_slots": [
    {{
      "name": "цель процесса",
      "name_aliases": ["допустимое название"],
      "primary_actor": "роль из actor_slots",
      "source_fr_ids": ["FR-001"],
      "required_milestones": ["обязательный этап"],
      "required_branches": [
        {{"condition": "условие", "required_outcomes": ["исход"]}}
      ]
    }}
  ],
  "known_ambiguity": ["неоднозначность"],
  "forbidden_assumptions": ["неподтверждённая функция"]
}}

Вход:
{json.dumps(payload, ensure_ascii=False, indent=2)}
"""


def _clean_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item).strip()
        if text and text not in result:
            result.append(text)
    return result


def _normalize_gold(
    annotation: dict[str, Any],
    request: dict[str, Any],
) -> dict[str, Any]:
    valid_frs = {
        f"FR-{index:03d}" for index in range(1, len(request["functional_requirements"]) + 1)
    }
    actors: list[dict[str, Any]] = []
    canonical_roles: set[str] = set()
    for raw_actor in annotation.get("actor_slots", []):
        if not isinstance(raw_actor, dict):
            continue
        canonical = str(raw_actor.get("canonical", "")).strip()
        if not canonical or canonical.casefold() in {item.casefold() for item in canonical_roles}:
            continue
        canonical_roles.add(canonical)
        actors.append({"canonical": canonical, "any_of": _clean_strings(raw_actor.get("any_of"))})

    use_cases: list[dict[str, Any]] = []
    for index, raw_uc in enumerate(annotation.get("use_case_slots", []), start=1):
        if not isinstance(raw_uc, dict):
            continue
        name = str(raw_uc.get("name", "")).strip()
        primary_actor = str(raw_uc.get("primary_actor", "")).strip()
        source_frs = [
            item for item in _clean_strings(raw_uc.get("source_fr_ids")) if item in valid_frs
        ]
        milestones = _clean_strings(raw_uc.get("required_milestones"))
        if not name or not primary_actor or not source_frs or not milestones:
            continue
        if primary_actor not in canonical_roles:
            actors.append({"canonical": primary_actor, "any_of": []})
            canonical_roles.add(primary_actor)
        branches: list[dict[str, Any]] = []
        for raw_branch in raw_uc.get("required_branches", []):
            if not isinstance(raw_branch, dict):
                continue
            condition = str(raw_branch.get("condition", "")).strip()
            outcomes = _clean_strings(raw_branch.get("required_outcomes"))
            if condition and outcomes:
                branches.append({"condition": condition, "required_outcomes": outcomes})
        use_cases.append(
            {
                "slot_id": f"GUC-{index:03d}",
                "name": name,
                "name_aliases": _clean_strings(raw_uc.get("name_aliases")),
                "primary_actor": primary_actor,
                "required_milestones": milestones,
                "required_branches": branches,
                "source_fr_ids": source_frs,
            }
        )

    covered = {fr_id for use_case in use_cases for fr_id in use_case["source_fr_ids"]}
    missing = sorted(valid_frs - covered)
    if missing:
        raise ValueError(f"annotation omitted functional requirements: {missing}")
    if not actors or not use_cases:
        raise ValueError("annotation must contain actors and use cases")

    trace_expectations = []
    for fr_id in sorted(valid_frs):
        allowed = [
            use_case["slot_id"] for use_case in use_cases if fr_id in use_case["source_fr_ids"]
        ]
        trace_expectations.append(
            {"source_fr_id": fr_id, "allowed_target_uc_slots": allowed}
        )
    nfr_expectations = {
        f"NFR-{index:03d}": "preserve"
        for index in range(1, len(request["non_functional_requirements"]) + 1)
    }
    return {
        "actor_slots": actors,
        "use_case_slots": use_cases,
        "fr_coverage": {fr_id: "expected_covered" for fr_id in sorted(valid_frs)},
        "trace_expectations": trace_expectations,
        "nfr_expectations": nfr_expectations,
        "known_ambiguity": _clean_strings(annotation.get("known_ambiguity")),
        "forbidden_assumptions": _clean_strings(annotation.get("forbidden_assumptions")),
        "equivalence_policy": {
            "allow_synonyms": True,
            "allow_uc_split_merge": True,
            "allow_linear_node_split_merge": True,
            "allow_additional_supported_detail": True,
            "require_same_business_semantics": True,
            "ignore_pixel_layout": True,
        },
        "review_status": "llm_assisted_author_draft",
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark-dir", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--private-dir", type=Path, default=DEFAULT_PRIVATE_DIR)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-output-tokens", type=int, default=24000)
    parser.add_argument("--max-total-tokens", type=int, default=2_000_000)
    parser.add_argument("--max-estimated-cost-usd", type=float, default=0.90)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    _load_local_env(args.env_file)
    manifest = json.loads((args.benchmark_dir / "manifest.json").read_text(encoding="utf-8"))
    selected = list(manifest["cases"])
    if args.case_id:
        wanted = set(args.case_id)
        selected = [case for case in selected if case["case_id"] in wanted]
        missing = wanted - {case["case_id"] for case in selected}
        if missing:
            raise SystemExit(f"Unknown case IDs: {sorted(missing)}")

    existing: dict[str, dict[str, Any]] = {}
    if args.resume and args.output.exists():
        for item in json.loads(args.output.read_text(encoding="utf-8")):
            existing[str(item["case_id"])] = item

    config = provider_config_from_env()
    config = replace(
        config,
        max_output_tokens=args.max_output_tokens,
        max_calls_per_process=max(len(selected) + 2, config.max_calls_per_process),
        max_total_tokens_per_process=args.max_total_tokens,
        max_estimated_cost_usd=args.max_estimated_cost_usd,
        telemetry_path=args.private_dir / "calls.jsonl",
        raw_capture_dir=args.private_dir / "raw",
    )
    client = create_instrumented_client(config)
    args.private_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(args.private_dir, 0o700)

    records = existing
    for case in selected:
        case_id = str(case["case_id"])
        if case_id in records:
            continue
        request = json.loads(
            (args.benchmark_dir / "inputs" / case["file"]).read_text(encoding="utf-8")
        )
        response = client.complete(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _annotation_prompt(case, request)},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        annotation = _extract_json(response)
        gold = _normalize_gold(annotation, request)
        records[case_id] = {
            "case_id": case_id,
            "project_name": case["project_name"],
            "size_group": case["size_group"],
            "fr_count": case["fr_count"],
            "input_sha256": case["sha256"],
            "gold": gold,
        }
        ordered = [
            records[item["case_id"]]
            for item in manifest["cases"]
            if item["case_id"] in records
        ]
        args.output.write_bytes(_canonical_bytes(ordered))
        print(json.dumps({"case_id": case_id, "status": "saved"}, ensure_ascii=False))

    output_bytes = args.output.read_bytes()
    metadata = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "benchmark_id": manifest["benchmark_id"],
        "case_count": len(records),
        "annotation_provider": config.provider,
        "annotation_model": config.model,
        "gold_candidate_sha256": _sha256(output_bytes),
        "total_tokens": client.total_tokens,
        "estimated_cost_usd": client.total_cost_usd,
        "review_status": "author_candidate_requires_two_independent_reviews",
        "independence_rule": "Annotation prompt consumed only SpecificationReq inputs.",
    }
    (args.private_dir / "build_metadata.json").write_bytes(_canonical_bytes(metadata))
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
