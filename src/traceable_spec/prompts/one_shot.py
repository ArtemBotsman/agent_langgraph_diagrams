"""Single-call baseline prompt using the same typed output concepts as FULL."""

from __future__ import annotations

import json

from traceable_spec.entities import OneShotGenerationArtifact, SpecificationRequest

ROLE_ONE_SHOT = "one_shot_generator"


def build_one_shot_messages(request: SpecificationRequest) -> list[dict[str, str]]:
    """Ask one model call for Use Cases and activity models without feedback loops."""

    system = (
        f"[[llm_role:{ROLE_ONE_SHOT}]]\n"
        "Generate complete Use Cases and one ActivityDiagram per Use Case. Return ONLY "
        "valid JSON. Do not use critique or iterative repair. Preserve every FR/NFR, do not "
        "invent business rules, put source_fr_ids on every UC and scenario step, and put "
        "related_step_ids on every activity action/decision and edge. Each diagram needs "
        "exactly one initial node, a reachable final node, and guarded decision branches. "
        "TraceManifest may be empty because Python materializes it from typed references. "
        "Do not generate Mermaid.\n"
        "JSON Schema: "
        f"{json.dumps(OneShotGenerationArtifact.model_json_schema(), ensure_ascii=False)}"
    )
    payload = request.model_dump(mode="json")
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
    ]
