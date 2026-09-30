"""Common final assessment and plain decomposition must not favor graph status."""

from __future__ import annotations

import json

import pytest

from traceable_spec.entities import (
    ActivityGenerationArtifact,
    OneShotGenerationArtifact,
    PipelineStatus,
    UseCaseGenerationArtifact,
    ValidationReport,
)
from traceable_spec.evaluation.formal import evaluate_final_formal
from traceable_spec.llm.scripted import ScriptedLLMClient
from traceable_spec.prompts.activities import (
    ROLE_ACTIVITY_GENERATOR,
    build_activity_generator_messages,
)
from traceable_spec.prompts.one_shot import ROLE_ONE_SHOT, ROLE_VALIDATOR_FEEDBACK_REPAIR
from traceable_spec.prompts.use_cases import ROLE_GENERATOR, build_use_case_generator_messages
from traceable_spec.reference_methods import (
    run_decomposed_baseline,
    run_one_shot_baseline,
    run_validator_feedback_baseline,
)
from traceable_spec.testing.fixtures import (
    sample_activity_diagram,
    sample_request,
    sample_use_case_set,
)


def artifact() -> OneShotGenerationArtifact:
    return OneShotGenerationArtifact(
        use_case_set=sample_use_case_set(), activity_diagrams=[sample_activity_diagram()]
    )


def generated():
    return run_one_shot_baseline(
        sample_request(), ScriptedLLMClient({ROLE_ONE_SHOT: [artifact().model_dump_json()]})
    )


@pytest.mark.parametrize("status", list(PipelineStatus))
def test_final_verdict_ignores_internal_status_and_history(status):
    spec = generated()
    spec.status = status
    spec.validation_reports = [ValidationReport(passed=False, validator_name="old_failure")]
    before = spec.model_dump_json()
    assert evaluate_final_formal(spec).passed
    assert spec.model_dump_json() == before


@pytest.mark.parametrize(
    "mutation",
    [
        "no_uc",
        "empty_uc",
        "unknown_actor",
        "empty_goal",
        "step_order",
        "no_activity",
        "empty_diagram",
        "duplicate_activity",
        "unknown_activity_uc",
        "wrong_diagram_uc",
        "bad_step_ref",
        "bad_fr_ref",
        "missing_trace",
    ],
)
def test_final_checker_rejects_defects_even_when_pipeline_claims_success(mutation):
    spec = generated()
    uc = spec.use_case_set.use_cases[0]
    result = spec.activity_results[0]
    if mutation == "no_uc":
        spec.use_case_set = None
    elif mutation == "empty_uc":
        spec.use_case_set.use_cases = []
    elif mutation == "unknown_actor":
        uc.primary_actor_id = "ACT-999"
    elif mutation == "empty_goal":
        uc.goal = " "
    elif mutation == "step_order":
        uc.main_success_scenario.steps.reverse()
    elif mutation == "no_activity":
        spec.activity_results = []
    elif mutation == "empty_diagram":
        result.activity_diagram = None
    elif mutation == "duplicate_activity":
        spec.activity_results.append(result.model_copy(deep=True))
    elif mutation == "unknown_activity_uc":
        result.use_case_id = "UC-999"
    elif mutation == "wrong_diagram_uc":
        result.activity_diagram.use_case_id = "UC-999"
    elif mutation == "bad_step_ref":
        result.activity_diagram.nodes[1].related_step_ids = ["STEP-UC001-999"]
    elif mutation == "bad_fr_ref":
        uc.source_fr_ids.append("FR-999")
    elif mutation == "missing_trace":
        spec.trace_manifest.links = []
    spec.status = PipelineStatus.SUCCESS
    assert not evaluate_final_formal(spec).passed


def test_feedback_uses_common_uc_checks_when_enabled():
    bad = artifact()
    bad.use_case_set.use_cases[0].primary_actor_id = "ACT-999"
    client = ScriptedLLMClient(
        {
            ROLE_ONE_SHOT: [bad.model_dump_json()],
            ROLE_VALIDATOR_FEEDBACK_REPAIR: [artifact().model_dump_json()],
        }
    )
    result = run_validator_feedback_baseline(sample_request(), client, common_final_validation=True)
    assert len(client.calls) == 2
    assert result.specification.status == PipelineStatus.SUCCESS
    assert any(
        issue.code == "unknown_primary_actor"
        for report in result.attempts[0].specification.validation_reports
        for issue in report.issues
    )


class RecordingClient(ScriptedLLMClient):
    def __init__(self, scripts):
        super().__init__(scripts)
        self.messages = []

    def complete(self, **kwargs):
        self.messages.append(kwargs["messages"])
        return super().complete(**kwargs)


def test_decomposed_uses_production_generator_prompts_and_two_calls_for_one_uc():
    client = RecordingClient(
        {
            ROLE_GENERATOR: [
                UseCaseGenerationArtifact(use_case_set=sample_use_case_set()).model_dump_json()
            ],
            ROLE_ACTIVITY_GENERATOR: [
                ActivityGenerationArtifact(
                    activity_diagram=sample_activity_diagram()
                ).model_dump_json()
            ],
        }
    )
    stages = []
    result = run_decomposed_baseline(sample_request(), client, on_stage=stages.append)
    assert evaluate_final_formal(result).passed
    assert [call["role"] for call in client.calls] == [ROLE_GENERATOR, ROLE_ACTIVITY_GENERATOR]
    assert client.messages[0] == build_use_case_generator_messages(result.request)
    assert client.messages[1] == build_activity_generator_messages(
        result.use_case_set.use_cases[0], result.use_case_set.actors, request=result.request
    )
    assert len(stages) == 2
    assert result.trace_manifest.links
    assert result.activity_results[0].activity_diagram.mermaid_source


@pytest.mark.parametrize(
    "bad_stage", ["uc_schema", "uc_formal", "activity_schema", "activity_formal"]
)
def test_decomposed_never_repairs_or_calls_critic(bad_stage):
    uc_artifact = UseCaseGenerationArtifact(use_case_set=sample_use_case_set())
    activity_artifact = ActivityGenerationArtifact(activity_diagram=sample_activity_diagram())
    if bad_stage == "uc_formal":
        uc_artifact.use_case_set.use_cases[0].primary_actor_id = "ACT-999"
    if bad_stage == "activity_formal":
        activity_artifact.activity_diagram.nodes[1].related_step_ids = ["STEP-UC001-999"]
    client = ScriptedLLMClient(
        {
            ROLE_GENERATOR: ["{}" if bad_stage == "uc_schema" else uc_artifact.model_dump_json()],
            ROLE_ACTIVITY_GENERATOR: [
                "{}" if bad_stage == "activity_schema" else activity_artifact.model_dump_json()
            ],
        }
    )
    result = run_decomposed_baseline(sample_request(), client)
    assert not evaluate_final_formal(result).passed
    assert len(client.calls) == (1 if bad_stage == "uc_schema" else 2)
    assert all(call["role"] in {ROLE_GENERATOR, ROLE_ACTIVITY_GENERATOR} for call in client.calls)


def test_decomposed_continues_other_ucs_after_invalid_activity():
    ucs = sample_use_case_set()
    second = json.loads(
        ucs.use_cases[0].model_dump_json().replace("UC001", "UC002").replace("UC-001", "UC-002")
    )
    ucs.use_cases.append(type(ucs.use_cases[0]).model_validate(second))
    second_activity = (
        sample_activity_diagram()
        .model_dump_json()
        .replace("UC001", "UC002")
        .replace("UC-001", "UC-002")
    )
    activity = ActivityGenerationArtifact.model_validate(
        {"activity_diagram": json.loads(second_activity)}
    )
    client = ScriptedLLMClient(
        {
            ROLE_GENERATOR: [UseCaseGenerationArtifact(use_case_set=ucs).model_dump_json()],
            ROLE_ACTIVITY_GENERATOR: ["bad", activity.model_dump_json()],
        }
    )
    result = run_decomposed_baseline(sample_request(), client)
    assert len(client.calls) == 3
    assert len(result.activity_results) == 2
    assert result.activity_results[0].activity_diagram is None
    assert result.activity_results[1].activity_diagram is not None
    assert not evaluate_final_formal(result).passed
