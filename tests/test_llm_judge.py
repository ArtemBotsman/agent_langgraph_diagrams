from __future__ import annotations

import pytest
from pydantic import ValidationError

from traceable_spec.evaluation.llm_judge import (
    RUBRIC_VERSION,
    JudgeDimension,
    PointwiseJudgeVerdict,
    build_blind_projection,
    build_pointwise_judge_messages,
    weighted_score,
)


def _dimension(score: int) -> JudgeDimension:
    return JudgeDimension(score=score, rationale="evidence", evidence_ids=["FR-001"])


def _verdict(score: int, decision: str = "approve") -> PointwiseJudgeVerdict:
    return PointwiseJudgeVerdict.model_validate(
        {
            "rubric_version": RUBRIC_VERSION,
            "requirements_coverage": _dimension(score).model_dump(),
            "actor_uc_boundaries": _dimension(score).model_dump(),
            "scenario_completeness": _dimension(score).model_dump(),
            "branch_correctness": _dimension(score).model_dump(),
            "trace_correctness": _dimension(score).model_dump(),
            "assumption_discipline": _dimension(score).model_dump(),
            "diagram_readability": _dimension(score).model_dump(),
            "decision": decision,
            "confidence": 0.8,
            "critical_issues": [],
            "limitations": [],
        }
    )


def test_weighted_score_endpoints() -> None:
    assert weighted_score(_verdict(5)) == pytest.approx(1.0)
    assert weighted_score(_verdict(1, "revise")) == pytest.approx(0.0)


def test_low_score_requires_revision() -> None:
    with pytest.raises(ValidationError):
        _verdict(2, "approve")


def test_dimension_rejects_out_of_range_score() -> None:
    with pytest.raises(ValidationError):
        JudgeDimension(score=6, rationale="bad")


def test_projection_is_blind_and_omits_large_duplicate_fields() -> None:
    request = {
        "project_task": "task",
        "project_name": "name",
        "project_goal": "goal",
        "project_description": "description",
        "functional_requirements": ["requirement"],
        "non_functional_requirements": ["nfr"],
    }
    generated = {
        "use_case_set": {
            "actors": [
                {
                    "id": "ACT-001",
                    "name": "User",
                    "description": "rule-based baseline",
                    "is_primary": True,
                }
            ],
            "use_cases": [
                {
                    "id": "UC-001",
                    "name": "Process",
                    "goal": "Goal",
                    "primary_actor_id": "ACT-001",
                    "main_success_scenario": {"steps": []},
                    "human_readable_text": "large duplicate",
                }
            ],
        },
        "activity_results": [
            {
                "activity_diagram": {
                    "id": "AD-001",
                    "name": "rule-based activity",
                    "mermaid_source": "flowchart TD",
                    "nodes": [],
                    "edges": [],
                    "partitions": [],
                }
            }
        ],
        "trace_manifest": {"links": ["large duplicate"]},
    }
    projection = build_blind_projection(request, generated)
    text = str(projection)
    assert "rule-based" not in text
    assert "mermaid_source" not in text
    assert "human_readable_text" not in text
    assert "trace_manifest" not in text


def test_prompt_does_not_reveal_condition_or_provider() -> None:
    projection = {"input": {}, "candidate": {}, "candidate_sha256": "abc"}
    messages = build_pointwise_judge_messages(projection)
    joined = "\n".join(message["content"] for message in messages)
    assert "B0_RULE" not in joined
    assert "DeepSeek" not in joined
    assert "size-scaling-llm-judge-v1" in joined


def test_single_limitation_text_is_normalized() -> None:
    payload = _verdict(5).model_dump(mode="json")
    payload["limitations"] = "Only the supplied artifact was reviewed"
    verdict = PointwiseJudgeVerdict.model_validate(payload)
    assert verdict.limitations == ["Only the supplied artifact was reviewed"]


def test_unambiguous_decision_alias_is_normalized() -> None:
    payload = _verdict(5).model_dump(mode="json")
    payload["decision"] = "accept"
    verdict = PointwiseJudgeVerdict.model_validate(payload)
    assert verdict.decision == "approve"
