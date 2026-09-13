"""Blind pointwise LLM-judge contracts for generated specification artifacts.

LLM judgments are deliberately kept separate from deterministic validation and
human expert review.  The judge sees a method-neutral projection, not the
condition name, provider, model, or implementation metadata.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RUBRIC_VERSION = "size-scaling-llm-judge-v1"
DIMENSION_WEIGHTS: dict[str, float] = {
    "requirements_coverage": 0.20,
    "actor_uc_boundaries": 0.15,
    "scenario_completeness": 0.20,
    "branch_correctness": 0.15,
    "trace_correctness": 0.10,
    "assumption_discipline": 0.10,
    "diagram_readability": 0.10,
}


class JudgeDimension(BaseModel):
    """One ordinal score with concise, auditable evidence."""

    model_config = ConfigDict(extra="forbid")

    score: int = Field(ge=1, le=5)
    rationale: str = Field(min_length=1, max_length=1200)
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)


class PointwiseJudgeVerdict(BaseModel):
    """Strict output of one blind pointwise judge call."""

    model_config = ConfigDict(extra="forbid")

    rubric_version: Literal["size-scaling-llm-judge-v1"]
    requirements_coverage: JudgeDimension
    actor_uc_boundaries: JudgeDimension
    scenario_completeness: JudgeDimension
    branch_correctness: JudgeDimension
    trace_correctness: JudgeDimension
    assumption_discipline: JudgeDimension
    diagram_readability: JudgeDimension
    decision: Literal["approve", "revise"]
    confidence: float = Field(ge=0.0, le=1.0)
    critical_issues: list[str] = Field(default_factory=list, max_length=12)
    limitations: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("decision", mode="before")
    @classmethod
    def normalize_decision_alias(cls, value: Any) -> Any:
        """Normalize unambiguous provider aliases documented by the runner."""

        if not isinstance(value, str):
            return value
        normalized = value.strip().casefold().replace("-", "_").replace(" ", "_")
        if normalized in {"accept", "accepted", "approved"}:
            return "approve"
        if normalized in {
            "reject",
            "rejected",
            "revision",
            "needs_revision",
            "conditionally_approve",
            "approve_with_changes",
        }:
            return "revise"
        return value

    @field_validator("critical_issues", "limitations", mode="before")
    @classmethod
    def accept_single_text_as_list(cls, value: Any) -> Any:
        """Tolerate a frequent provider deviation without changing score content."""

        if isinstance(value, str):
            return [value]
        return value

    @model_validator(mode="after")
    def low_scores_require_revision(self) -> PointwiseJudgeVerdict:
        if any(score <= 2 for score in dimension_scores(self).values()):
            if self.decision != "revise":
                raise ValueError("Any score 1-2 requires decision=revise")
        return self


def dimension_scores(verdict: PointwiseJudgeVerdict) -> dict[str, int]:
    """Return fixed rubric scores without relying on dynamic model internals."""

    return {
        name: getattr(verdict, name).score
        for name in DIMENSION_WEIGHTS
    }


def weighted_score(verdict: PointwiseJudgeVerdict) -> float:
    """Map weighted ordinal scores from 1..5 to an interpretable 0..1 scale."""

    scores = dimension_scores(verdict)
    weighted_ordinal = sum(scores[name] * weight for name, weight in DIMENSION_WEIGHTS.items())
    return (weighted_ordinal - 1.0) / 4.0


def _compact_use_case(use_case: dict[str, Any]) -> dict[str, Any]:
    main = use_case.get("main_success_scenario") or {}
    return {
        "id": use_case.get("id"),
        "name": use_case.get("name"),
        "goal": use_case.get("goal"),
        "primary_actor_id": use_case.get("primary_actor_id"),
        "secondary_actor_ids": use_case.get("secondary_actor_ids", []),
        "trigger": use_case.get("trigger"),
        "preconditions": use_case.get("preconditions", []),
        "success_postconditions": use_case.get("success_postconditions", []),
        "failure_postconditions": use_case.get("failure_postconditions", []),
        "source_fr_ids": use_case.get("source_fr_ids", []),
        "source_nfr_ids": use_case.get("source_nfr_ids", []),
        "main_steps": [
            {
                "id": step.get("id"),
                "actor_id": step.get("actor_id"),
                "action": step.get("action"),
                "expected_result": step.get("expected_result"),
                "source_fr_ids": step.get("source_fr_ids", []),
            }
            for step in main.get("steps", [])
        ],
        "alternative_scenarios": use_case.get("alternative_scenarios", []),
        "exception_scenarios": use_case.get("exception_scenarios", []),
        "unsupported_assumptions": use_case.get("unsupported_assumptions", []),
        "missing_information": use_case.get("missing_information", []),
    }


def build_blind_projection(
    specification_req: dict[str, Any],
    generated_specification: dict[str, Any],
) -> dict[str, Any]:
    """Build a compact candidate projection with method-identifying metadata removed."""

    use_case_set = generated_specification.get("use_case_set") or {}
    activities: list[dict[str, Any]] = []
    for result in generated_specification.get("activity_results", []):
        diagram = result.get("activity_diagram") or {}
        activities.append(
            {
                "id": diagram.get("id"),
                "use_case_id": diagram.get("use_case_id"),
                "partitions": [
                    {
                        "id": item.get("id"),
                        "name": item.get("name"),
                        "actor_id": item.get("actor_id"),
                    }
                    for item in diagram.get("partitions", [])
                ],
                "nodes": [
                    {
                        "id": item.get("id"),
                        "kind": item.get("kind"),
                        "name": item.get("name"),
                        "partition_id": item.get("partition_id"),
                        "related_step_ids": item.get("related_step_ids", []),
                        "unsupported": item.get("unsupported", False),
                    }
                    for item in diagram.get("nodes", [])
                ],
                "edges": [
                    {
                        "id": item.get("id"),
                        "source_node_id": item.get("source_node_id"),
                        "target_node_id": item.get("target_node_id"),
                        "guard": item.get("guard"),
                        "label": item.get("label"),
                        "related_step_ids": item.get("related_step_ids", []),
                        "unsupported": item.get("unsupported", False),
                    }
                    for item in diagram.get("edges", [])
                ],
            }
        )
    projection: dict[str, Any] = {
        "input": specification_req,
        "candidate": {
            "actors": [
                {
                    "id": actor.get("id"),
                    "name": actor.get("name"),
                    "is_primary": actor.get("is_primary"),
                }
                for actor in use_case_set.get("actors", [])
            ],
            "use_cases": [
                _compact_use_case(use_case)
                for use_case in use_case_set.get("use_cases", [])
            ],
            "activity_diagrams": activities,
        },
    }
    canonical = json.dumps(
        projection,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    projection["candidate_sha256"] = hashlib.sha256(canonical).hexdigest()
    return projection


def build_pointwise_judge_messages(projection: dict[str, Any]) -> list[dict[str, str]]:
    """Create a method-blind prompt that allows multiple valid decompositions."""

    system = """Ты независимый оценщик артефактов анализа требований.
Оценивай только соответствие входному SpecificationReq. Имя метода, модели и
провайдера скрыты. Не пытайся их определить. Допускай несколько корректных
декомпозиций, если каждая сохраняет смысл требований.

Шкала каждого критерия:
1 — критически неверно или непригодно;
2 — крупные содержательные ошибки, нужна существенная переработка;
3 — частично пригодно, нужны содержательные правки;
4 — корректно, нужны только небольшие правки;
5 — корректно и полно, содержательная правка не требуется.

Критерии:
- requirements_coverage: смысл ФТ не потерян; НФТ учтены там, где это уместно,
  но не требуй изображать каждый НФТ отдельным activity-узлом;
- actor_uc_boundaries: реальные роли и независимые пользовательские цели
  разделены на разумные Use Cases;
- scenario_completeness: есть логичный trigger, предусловия, основной поток,
  результаты и существенные альтернативы/ошибки;
- branch_correctness: развилки и исключения отражены как условия и исходы, а не
  превращены в безусловную линейную последовательность;
- trace_correctness: ссылки FR→UC→step→activity подтверждены смыслом, а не
  только наличием идентификаторов;
- assumption_discipline: нет неподтверждённых деталей либо они явно помечены;
- diagram_readability: диаграммы обозримы, связны и пригодны для согласования.

Не награждай кандидата только за валидный JSON или 100% формальных ссылок.
Один UC, объединяющий независимые цели и акторов, должен снижать оценку границ.
Большая линейная диаграмма без ветвлений должна снижать branch_correctness и
diagram_readability. Любая оценка 1–2 требует decision=revise.

Верни только JSON-объект ровно с ключами:
rubric_version, requirements_coverage, actor_uc_boundaries,
scenario_completeness, branch_correctness, trace_correctness,
assumption_discipline, diagram_readability, decision, confidence,
critical_issues, limitations.
rubric_version должен быть size-scaling-llm-judge-v1. Каждый критерий — объект
{score, rationale, evidence_ids}. critical_issues и limitations всегда являются
JSON-массивами строк, даже если элемент один. Проверь закрытие всех скобок.
Не добавляй другие ключи."""
    user = "Проведи слепую оценку следующего входа и кандидата:\n" + json.dumps(
        projection,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
