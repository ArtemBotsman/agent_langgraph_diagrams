"""Prompt builders for Use Case generator, critic, and repair (no live LLM)."""

from __future__ import annotations

import json
from typing import Any

from traceable_spec.entities import (
    SpecificationRequest,
    UseCaseSet,
    ValidationReport,
)

ROLE_GENERATOR = "use_case_generator"
ROLE_CRITIC = "use_case_critic"
ROLE_REPAIR = "use_case_repair"

_ROLE_MARKER = "[[llm_role:{role}]]"


def _role_system(role: str, body: str) -> dict[str, str]:
    return {"role": "system", "content": f"{_ROLE_MARKER.format(role=role)}\n{body}"}


def detect_llm_role(messages: list[dict[str, str]]) -> str | None:
    """Extract role marker from scripted/real prompts (first matching system message)."""
    for message in messages:
        if message.get("role") != "system":
            continue
        content = message.get("content") or ""
        for role in (ROLE_GENERATOR, ROLE_CRITIC, ROLE_REPAIR):
            if _ROLE_MARKER.format(role=role) in content:
                return role
    return None


def build_use_case_generator_messages(request: SpecificationRequest) -> list[dict[str, str]]:
    frs = [{"id": fr.id, "text": fr.text} for fr in request.functional_requirements]
    nfrs = [{"id": nfr.id, "text": nfr.text} for nfr in request.non_functional_requirements]
    payload = {
        "project_name": request.project_name,
        "project_goal": request.project_goal,
        "project_description": request.project_description,
        "functional_requirements": frs,
        "non_functional_requirements": nfrs,
    }
    system = (
        "You generate a UseCaseSet and TraceManifest as a single JSON object.\n"
        "Schema keys: use_case_set, trace_manifest.\n"
        "Rules:\n"
        "- Output ONLY valid JSON (no markdown).\n"
        "- Every Use Case must list source_fr_ids for one or more given FRs.\n"
        "- Include TraceManifest FR_TO_UC links for each FR→UC pair.\n"
        "- Do not invent requirements; mark unsupported assumptions explicitly "
        "with UnsupportedAssumption and justified=true only when necessary.\n"
        "- Uncovered FRs must appear in fr_coverage as uncovered/out_of_scope/"
        "conflicting."
    )
    user = (
        "Generate structured Use Cases for this specification:\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )
    return [
        _role_system(ROLE_GENERATOR, system),
        {"role": "user", "content": user},
    ]


def build_use_case_critic_messages(
    request: SpecificationRequest,
    use_case_set: UseCaseSet,
    deterministic_reports: list[ValidationReport],
) -> list[dict[str, str]]:
    reports_payload: list[dict[str, Any]] = [
        {
            "validator_name": report.validator_name,
            "passed": report.passed,
            "issues": [issue.model_dump(mode="json") for issue in report.issues],
        }
        for report in deterministic_reports
    ]
    system = (
        "You are a Use Case critic (semantic review), NOT a deterministic validator.\n"
        "Return ONLY JSON: {\"decision\": \"accept\"|\"repair\", \"issues\": [...], "
        "\"summary\": string|null}.\n"
        "Each issue must match ValidationIssue fields "
        "(id VI-###, severity, category, code, message, element_ids, blocking).\n"
        "Choose repair if blocking problems remain; otherwise accept."
    )
    user = {
        "specification": {
            "project_name": request.project_name,
            "project_goal": request.project_goal,
            "functional_requirements": [
                {"id": fr.id, "text": fr.text} for fr in request.functional_requirements
            ],
        },
        "use_case_set": use_case_set.model_dump(mode="json"),
        "deterministic_validation": reports_payload,
    }
    return [
        _role_system(ROLE_CRITIC, system),
        {"role": "user", "content": json.dumps(user, ensure_ascii=False, indent=2)},
    ]


def build_use_case_repair_messages(
    request: SpecificationRequest,
    use_case_set: UseCaseSet | None,
    issues: list[dict[str, Any]],
    repair_attempt: int,
) -> list[dict[str, str]]:
    system = (
        "You repair a UseCaseSet and TraceManifest.\n"
        "Output ONLY JSON with keys use_case_set and trace_manifest.\n"
        "Fix the listed issues; keep valid FR→UC trace links; do not invent FRs."
    )
    user = {
        "repair_attempt": repair_attempt,
        "project_name": request.project_name,
        "project_goal": request.project_goal,
        "functional_requirements": [
            {"id": fr.id, "text": fr.text} for fr in request.functional_requirements
        ],
        "current_use_case_set": (
            None if use_case_set is None else use_case_set.model_dump(mode="json")
        ),
        "issues_to_fix": issues,
    }
    return [
        _role_system(ROLE_REPAIR, system),
        {"role": "user", "content": json.dumps(user, ensure_ascii=False, indent=2)},
    ]
