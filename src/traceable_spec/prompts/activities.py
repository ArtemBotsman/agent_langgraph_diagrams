"""Prompt contracts for the Activity Diagram agent roles."""

from __future__ import annotations

import json
from typing import Any

from traceable_spec.entities import (
    ActivityDiagram,
    ActivityGenerationArtifact,
    Actor,
    CriticVerdict,
    UseCase,
    ValidationReport,
)

ROLE_ACTIVITY_GENERATOR = "activity_generator"
ROLE_ACTIVITY_CRITIC = "activity_critic"
ROLE_ACTIVITY_REPAIR = "activity_repair"


def _system(role: str, body: str) -> dict[str, str]:
    return {"role": "system", "content": f"[[llm_role:{role}]]\n{body}"}


def _contract() -> str:
    return json.dumps(ActivityGenerationArtifact.model_json_schema(), ensure_ascii=False)


def build_activity_generator_messages(
    use_case: UseCase,
    actors: list[Actor],
) -> list[dict[str, str]]:
    system = (
        "Generate one typed ActivityDiagram for the supplied Use Case. "
        "Return ONLY a valid JSON object with keys activity_diagram and trace_manifest.\n"
        "Use these rules:\n"
        "- diagram id is AD-UC### and use_case_id is UC-###;\n"
        "- exactly one initial node and at least one reachable final node;\n"
        "- represent alternative and exception scenarios with decisions and guarded edges;\n"
        "- each action/decision node and each edge must list related_step_ids from the UC, "
        "or set unsupported=true only for genuinely inferred material;\n"
        "- do not invent actors, steps, business rules, or external services;\n"
        "- Mermaid is not generated here; Python renders it after validation.\n"
        f"JSON Schema: {_contract()}"
    )
    payload = {
        "use_case": use_case.model_dump(mode="json"),
        "actors": [actor.model_dump(mode="json") for actor in actors],
    }
    return [
        _system(ROLE_ACTIVITY_GENERATOR, system),
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
    ]


def build_activity_critic_messages(
    use_case: UseCase,
    diagram: ActivityDiagram,
    reports: list[ValidationReport],
    review_round: int = 0,
) -> list[dict[str, str]]:
    system = (
        "You are an Activity Diagram semantic critic, not a syntax validator. "
        "Check whether the diagram preserves the UC's main, alternative, and exception "
        "behavior without unsupported business assumptions. Return ONLY JSON matching the "
        "CriticVerdict schema. Use only enum values declared by the schema; severity is error, "
        "warning, or info. Use a conservative, evidence-grounded gate. Choose repair only "
        "when a supplied UC step is omitted or contradicted, or when the diagram adds an "
        "unsupported business action. A blocking issue MUST have severity=error, blocking=true, "
        "element_ids containing both the UC step id and affected activity element id, and one of "
        "these codes: UC_STEP_OMITTED, UC_BRANCH_OUTCOME_MISSING, "
        "UNSUPPORTED_ACTIVITY_ACTION, ACTIVITY_ORDER_CONTRADICTION. Treat layout, wording, "
        "equivalent control-flow decomposition, and style preferences as non-blocking warnings "
        "and choose accept. Return at most three issues. On a repeated review, do not introduce "
        "a new blocking criterion unless it proves a direct step-level contradiction or omission. "
        "Choose accept whenever no evidence-grounded blocking issue remains. "
        "JSON Schema: "
        f"{json.dumps(CriticVerdict.model_json_schema(), ensure_ascii=False)}"
    )
    payload: dict[str, Any] = {
        "review_round": review_round,
        "use_case": use_case.model_dump(mode="json"),
        "activity_diagram": diagram.model_dump(mode="json"),
        "formal_validation": [
            {
                "validator_name": report.validator_name,
                "passed": report.passed,
                "issues": [issue.model_dump(mode="json") for issue in report.issues],
            }
            for report in reports
        ],
    }
    return [
        _system(ROLE_ACTIVITY_CRITIC, system),
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
    ]


def build_activity_repair_messages(
    use_case: UseCase,
    diagram: ActivityDiagram | None,
    issues: list[dict[str, Any]],
    repair_attempt: int,
) -> list[dict[str, str]]:
    system = (
        "Repair one ActivityGenerationArtifact. Return ONLY valid JSON with keys "
        "activity_diagram and trace_manifest. Fix every blocking issue, retain supported "
        "behavior, use only supplied UC step IDs, and do not output Mermaid. Set "
        'trace_manifest to {"links": []}; Python rebuilds trace links. '
        f"JSON Schema: {_contract()}"
    )
    payload = {
        "repair_attempt": repair_attempt,
        "use_case": use_case.model_dump(mode="json"),
        "current_activity_diagram": (None if diagram is None else diagram.model_dump(mode="json")),
        "issues_to_fix": issues,
    }
    return [
        _system(ROLE_ACTIVITY_REPAIR, system),
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
    ]
