"""Prompt builders for Use Case generator, critic, and repair (no live LLM)."""

from __future__ import annotations

import json
import re
from typing import Any

from traceable_spec.entities import (
    CriticVerdict,
    SpecificationRequest,
    UseCaseGenerationArtifact,
    UseCaseSet,
    ValidationReport,
)
from traceable_spec.prompts.source_context import SOURCE_RULES, source_context

ROLE_GENERATOR = "use_case_generator"
ROLE_CRITIC = "use_case_critic"
ROLE_REPAIR = "use_case_repair"

_ROLE_MARKER = "[[llm_role:{role}]]"


def _role_system(role: str, body: str) -> dict[str, str]:
    return {"role": "system", "content": f"{_ROLE_MARKER.format(role=role)}\n{body}"}


def detect_llm_role(messages: list[dict[str, str]]) -> str | None:
    """Extract any project role marker from the first matching system message."""
    for message in messages:
        if message.get("role") != "system":
            continue
        content = message.get("content") or ""
        match = re.search(r"\[\[llm_role:([a-z0-9_]+)\]\]", content)
        if match:
            return match.group(1)
    return None


def build_use_case_generator_messages(request: SpecificationRequest) -> list[dict[str, str]]:
    payload = source_context(request)
    system = (
        "You generate a UseCaseSet and TraceManifest as a single JSON object.\n"
        "Schema keys: use_case_set, trace_manifest.\n"
        "Rules:\n"
        "- Output ONLY valid JSON (no markdown).\n"
        "- Every Use Case must list source_fr_ids for one or more given FRs.\n"
        "- Every scenario step should list the specific source_fr_ids it realizes.\n"
        "- TraceManifest may be empty: Python materializes links from typed references.\n"
        "- Do not invent requirements; mark unsupported assumptions explicitly "
        "with UnsupportedAssumption; necessity is not evidence of justification.\n"
        "- Uncovered FRs must appear in fr_coverage as uncovered/out_of_scope/"
        "conflicting.\n"
        f"{SOURCE_RULES}\n"
        "JSON Schema: "
        f"{json.dumps(UseCaseGenerationArtifact.model_json_schema(), ensure_ascii=False)}"
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
    review_round: int = 0,
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
        "Return ONLY JSON matching the supplied CriticVerdict schema.\n"
        "Use only enum values declared by the schema; severity is error, warning, or info.\n"
        "Use a conservative, evidence-grounded gate. Choose repair only when at least one "
        "concrete blocking defect is directly proved by the supplied original source text. "
        "Review project_description and NFRs too, not only the FR list. A blocking "
        "issue MUST have severity=error, blocking=true, non-empty element_ids, and a message "
        "that names the violated FR/NFR id or project_description. "
        "Allowed blocking codes are FR_OMISSION, "
        "FR_CONTRADICTION, UNSUPPORTED_BUSINESS_RULE, SCENARIO_OUTCOME_MISSING, and "
        "ACTOR_RESPONSIBILITY_CONTRADICTION, NFR_OMISSION, NFR_CONTRADICTION and "
        "SOURCE_CONTRADICTION. Treat wording, optional decomposition, actor "
        "generalization, and modeling preferences as non-blocking warnings and choose accept. "
        "Do not invent a missing requirement. Return at most three issues. On a repeated review, "
        "do not introduce a new blocking criterion unless it proves a direct FR contradiction or "
        "omission. Choose accept whenever no evidence-grounded blocking issue remains.\n"
        f"{SOURCE_RULES}\n"
        "JSON Schema: "
        f"{json.dumps(CriticVerdict.model_json_schema(), ensure_ascii=False)}"
    )
    user = {
        "review_round": review_round,
        "specification": source_context(request),
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
        "Output ONLY JSON with exactly the keys use_case_set and trace_manifest.\n"
        'trace_manifest must be {"links": []}; Python rebuilds all trace links from '
        "typed references. Never emit a traces key.\n"
        "Every scenario step source_fr_ids must be a subset of the containing Use Case "
        "source_fr_ids. If a step legitimately depends on an FR, add that FR to the Use Case; "
        "otherwise remove it from the step.\n"
        "Fix the listed issues; keep valid FR references; do not invent FRs.\n"
        f"{SOURCE_RULES}\n"
        "JSON Schema: "
        f"{json.dumps(UseCaseGenerationArtifact.model_json_schema(), ensure_ascii=False)}"
    )
    user = {
        "repair_attempt": repair_attempt,
        **source_context(request),
        "current_use_case_set": (
            None if use_case_set is None else use_case_set.model_dump(mode="json")
        ),
        "issues_to_fix": issues,
    }
    return [
        _role_system(ROLE_REPAIR, system),
        {"role": "user", "content": json.dumps(user, ensure_ascii=False, indent=2)},
    ]
