"""Helpers for scripted UC graph responses (fake LLM payloads only)."""

from __future__ import annotations

import json

from traceable_spec.entities import (
    CriticVerdict,
    IssueCategory,
    IssueSeverity,
    TraceManifest,
    UseCaseGenerationArtifact,
    UseCaseSet,
    ValidationIssue,
)
from traceable_spec.testing.fixtures import sample_uc_trace_manifest, sample_use_case_set


def valid_uc_artifact_json() -> str:
    artifact = UseCaseGenerationArtifact(
        use_case_set=sample_use_case_set(),
        trace_manifest=sample_uc_trace_manifest(),
    )
    return artifact.model_dump_json()


def broken_trace_uc_artifact_json() -> str:
    """Valid UseCaseSet but TraceManifest missing FR_TO_UC links."""
    artifact = UseCaseGenerationArtifact(
        use_case_set=sample_use_case_set(),
        trace_manifest=TraceManifest(links=[]),
    )
    return artifact.model_dump_json()


def critic_accept_json(summary: str = "Looks good") -> str:
    return CriticVerdict(decision="accept", issues=[], summary=summary).model_dump_json()


def critic_repair_json(*, code: str = "needs_repair", message: str = "Needs repair") -> str:
    return CriticVerdict(
        decision="repair",
        issues=[
            ValidationIssue(
                id="VI-001",
                severity=IssueSeverity.ERROR,
                category=IssueCategory.SEMANTIC,
                code=code,
                message=message,
            )
        ],
        summary=message,
    ).model_dump_json()


def invalid_json_text() -> str:
    return "{not-valid-json"


def dump_use_case_set(use_case_set: UseCaseSet) -> str:
    return json.dumps(use_case_set.model_dump(mode="json"))
