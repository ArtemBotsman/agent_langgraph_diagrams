"""Lossless, input-only context shared by generation, review and repair.

Do not serialize the entire request: metadata may contain evaluation-only data.
This context supplies evidence, not a guarantee that an LLM will use it correctly.
"""

from __future__ import annotations

from typing import Any

from traceable_spec.entities import SpecificationRequest

SOURCE_CONTEXT_VERSION = "original-requirements-v1"
SOURCE_REVIEW_VERSION = "source-review-v2"

SOURCE_RULES = (
    "Original requirements are authoritative; a generated Use Case or diagram is not evidence "
    "for a new requirement. Preserve exact return values, public interfaces, state changes, "
    "ordering, boundary conditions and the distinction between printing and returning when "
    "they are stated. Examples illustrate behavior; do not turn an example into an exclusive "
    "precondition or replace a general rule with that example. Do not invent validation, "
    "exceptions, defaults or edge-case policies that the source does not specify. In Use Cases "
    "record genuinely unspecified decisions in missing_information, and label inferred "
    "assumptions explicitly. A semantic defect must cite the source ID (or "
    "project_description/project_goal) and the relevant source wording, not just a preference. "
    "Source review policy source-review-v2: necessity or plausibility alone does not make an "
    "assumption justified. Use justified=true only with explicit supporting source wording "
    "in its description; otherwise keep justified=false and the decision in missing_information. "
    "Do not promote an unresolved assumption into a mandatory scenario rule. Reviewers must "
    "check its evidence even when an earlier generator set justified=true. Check each stated "
    "input/output example against the general rule and scenario outcome; preserve both. "
    "If they conflict, report the conflict rather than silently choosing one. A worked example "
    "is an acceptance example, not the entire main scenario: describe behavior for the stated "
    "input domain without hardcoding its sample values. Do not supply implementation formulas "
    "or algorithms beyond the requested behavior as if they were source requirements. "
)


def source_context(request: SpecificationRequest) -> dict[str, Any]:
    """Keep every input FR/NFR and project text; exclude metadata, gold and results."""
    return {
        "source_context_version": SOURCE_CONTEXT_VERSION,
        "project_task": request.project_task,
        "project_name": request.project_name,
        "project_goal": request.project_goal,
        "project_description": request.project_description,
        "functional_requirements": [
            {"id": item.id, "text": item.text} for item in request.functional_requirements
        ],
        "non_functional_requirements": [
            {"id": item.id, "text": item.text} for item in request.non_functional_requirements
        ],
    }
