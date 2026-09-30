"""Opt-in evidence-consistency-v2: v1 prompts plus a terminal-flow guard.

The original default and evidence-consistency-v1 remain unchanged. This profile
adds no extra unconditional calls and does not increase repair limits. Actual
repair/critic call counts can change when the new guard finds a defect:
boundary failures use the existing bounded repair route and skip the paid critic.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from traceable_spec.entities import ActivityGraphState, ValidationReport
from traceable_spec.evaluation.contracts import V2
from traceable_spec.evaluation.terminal_flow import validate_terminal_flow
from traceable_spec.llm.protocol import LLMClient
from traceable_spec.orchestration.evidence_consistency import evidence_consistency_deps
from traceable_spec.orchestration.pipeline import PipelineDeps
from traceable_spec.prompts.use_cases import detect_llm_role

PROFILE = "evidence-consistency-v2"
TERMINAL_RULES = (
    f"Review profile: {PROFILE} (extends evidence-consistency-v1).\n"
    "Activity initial nodes are sources: no incoming edges. Final nodes are sinks: "
    "no outgoing edges, including guarded or labeled edges. Every activity node must "
    "be reachable from initial and have a path to final without leaving any final "
    "or entering initial again. Do not place later actions after a final; preserve "
    "the supported action and its trace by correcting the control flow. Distinct "
    "triggers and alternatives must retain their source-supported meaning. "
    "Return the existing artifact schema; add no output fields."
)


class TerminalConsistencyClient:
    """Pure prompt enrichment with one unchanged underlying completion call."""

    def __init__(self, client: LLMClient):
        self.client = client

    def complete(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        enriched = [dict(message) for message in messages]
        if detect_llm_role(enriched) in {
            "use_case_generator",
            "use_case_critic",
            "use_case_repair",
            "activity_generator",
            "activity_critic",
            "activity_repair",
        }:
            for message in enriched:
                if message.get("role") == "system":
                    message["content"] += "\n" + TERMINAL_RULES
                    break
        return self.client.complete(
            messages=enriched,
            model=model,
            temperature=temperature,
            response_format=response_format,
        )


def terminal_consistency_deps(client: LLMClient, *, contract_version: str = V2) -> PipelineDeps:
    """Build the new profile explicitly; retain v1 history and feedback behavior."""
    deps = evidence_consistency_deps(
        TerminalConsistencyClient(client), contract_version=contract_version
    )
    base_validator = deps.activity_nodes.validate_activity_deterministic

    def validate(state: ActivityGraphState) -> dict[str, Any]:
        result = base_validator(state)
        diagram = state.get("activity_diagram")
        if diagram is None:
            return result  # Existing schema/deterministic failures handle this.
        guard = validate_terminal_flow(diagram)
        original = result["deterministic_report"]
        merged_issues = [
            issue.model_copy(update={"id": f"VI-{index:03d}"})
            for index, issue in enumerate([*original.issues, *guard.issues], 1)
        ]
        combined = ValidationReport(
            passed=original.passed and guard.passed,
            issues=merged_issues,
            validator_name="activity_deterministic_terminal_consistency",
            details={
                **original.details,
                "profile": PROFILE,
                "base_validator": original.validator_name,
                "terminal_report": guard.model_dump(mode="json"),
            },
        )
        return {
            **result,
            "deterministic_report": combined,
            # Keep both component reports once for repair and durable history.
            "validation_reports": [*result["validation_reports"], guard],
        }

    return replace(
        deps,
        activity_nodes=replace(deps.activity_nodes, validate_activity_deterministic=validate),
    )
