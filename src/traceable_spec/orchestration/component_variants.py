"""Explicit, testable component variants for the DEV experiment."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from traceable_spec.entities import ActivityGraphState, UseCaseGraphState, ValidationReport
from traceable_spec.llm.protocol import LLMClient
from traceable_spec.orchestration.pipeline import PipelineDeps, live_pipeline_deps


def _skip_use_case_critic(state: UseCaseGraphState) -> dict[str, Any]:
    report = ValidationReport(
        passed=True,
        validator_name="uc_critic_component_variant_disabled",
        details={"component_variant": "critic_disabled"},
    )
    return {
        "critic_report": report,
        "validation_reports": [*(state.get("validation_reports") or []), report],
    }


def _skip_activity_critic(state: ActivityGraphState) -> dict[str, Any]:
    report = ValidationReport(
        passed=True,
        validator_name="activity_critic_component_variant_disabled",
        details={"component_variant": "critic_disabled"},
    )
    return {
        "critic_report": report,
        "validation_reports": [*(state.get("validation_reports") or []), report],
    }


def _skip_use_case_rule_feedback(state: UseCaseGraphState) -> dict[str, Any]:
    report = ValidationReport(
        passed=True,
        validator_name="uc_rule_feedback_component_variant_disabled",
        details={"component_variant": "rule_feedback_disabled"},
    )
    return {
        "deterministic_report": report,
        "validation_reports": [*(state.get("validation_reports") or []), report],
    }


def _skip_activity_rule_feedback(state: ActivityGraphState) -> dict[str, Any]:
    report = ValidationReport(
        passed=True,
        validator_name="activity_rule_feedback_component_variant_disabled",
        details={"component_variant": "rule_feedback_disabled"},
    )
    return {
        "deterministic_report": report,
        "validation_reports": [*(state.get("validation_reports") or []), report],
    }


def live_pipeline_deps_without_critics(client: LLMClient) -> PipelineDeps:
    """Keep generators, validators and repair but remove semantic critic calls."""

    deps = live_pipeline_deps(client)
    return PipelineDeps(
        use_case_nodes=replace(
            deps.use_case_nodes,
            criticize_use_case_set=_skip_use_case_critic,
        ),
        activity_nodes=replace(
            deps.activity_nodes,
            criticize_activity_model=_skip_activity_critic,
        ),
    )


def live_pipeline_deps_without_rule_feedback(client: LLMClient) -> PipelineDeps:
    """Disable rule-based repair feedback but retain post-hoc final validation.

    Schema parsing remains enabled because otherwise no typed artifact can enter
    the graph. The root end-to-end validator is also retained as a measurement,
    but its findings are not fed back into generation or repair.
    """

    deps = live_pipeline_deps(client)
    return PipelineDeps(
        use_case_nodes=replace(
            deps.use_case_nodes,
            validate_uc_deterministic=_skip_use_case_rule_feedback,
        ),
        activity_nodes=replace(
            deps.activity_nodes,
            validate_activity_deterministic=_skip_activity_rule_feedback,
        ),
    )
