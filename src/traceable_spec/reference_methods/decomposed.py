"""Plain UC-then-Activity decomposition with no critic and no repair.

Uses exactly the production generator prompts. Formal checks do not gate the
next generation. Schema parsing is needed to supply typed UCs to the next call;
an invalid Activity does not prevent generation for the remaining UCs.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

from traceable_spec.entities import (
    ActivityGenerationArtifact,
    ActivityGenerationResult,
    GeneratedSpecification,
    PipelineStatus,
    SpecificationInput,
    TraceManifest,
    UseCaseGenerationArtifact,
    normalize_specification_req,
)
from traceable_spec.evaluation.contracts import V1, contract_client, with_contract_validation
from traceable_spec.llm.parsing import parse_json_model
from traceable_spec.llm.protocol import LLMClient
from traceable_spec.mermaid import render_mermaid
from traceable_spec.prompts.activities import build_activity_generator_messages
from traceable_spec.prompts.use_cases import build_use_case_generator_messages
from traceable_spec.rendering.use_case_text import render_use_case_text
from traceable_spec.traceability import inherit_step_sources, materialize_trace_manifest


def run_decomposed_baseline(
    value: SpecificationInput,
    client: LLMClient,
    *,
    on_stage: Callable[[dict[str, Any]], None] | None = None,
    contract_version: str = V1,
) -> GeneratedSpecification:
    """One UC-set call plus one Activity call per UC, never critic or repair."""
    client = contract_client(client, contract_version)
    request = normalize_specification_req(value)
    specification = GeneratedSpecification(request=request, status=PipelineStatus.PARTIAL)

    def save(phase: str, response: str, current: GeneratedSpecification) -> None:
        if on_stage is not None:
            on_stage(
                {
                    "phase": phase,
                    "response_sha256": hashlib.sha256(response.encode()).hexdigest(),
                    "generated_specification": current.model_dump(mode="json"),
                }
            )

    text = client.complete(
        messages=build_use_case_generator_messages(request),
        temperature=0,
        response_format={"type": "json_object"},
    )
    artifact, report = parse_json_model(
        UseCaseGenerationArtifact, text, validator_name="decomposed_uc_parse"
    )
    if artifact is None:
        specification.validation_reports = [report]
        specification = with_contract_validation(specification, contract_version)
        save("use_case_generator", text, specification)
        return specification
    use_case_set = inherit_step_sources(artifact.use_case_set)
    for use_case in use_case_set.use_cases:
        if not use_case.human_readable_text:
            use_case.human_readable_text = render_use_case_text(use_case)
    trace = materialize_trace_manifest(request, use_case_set, existing=artifact.trace_manifest)
    specification = specification.model_copy(
        update={
            "use_case_set": use_case_set,
            "trace_manifest": trace,
            "validation_reports": [report],
        }
    )
    save("use_case_generator", text, specification)
    for use_case in use_case_set.use_cases:
        text = client.complete(
            messages=build_activity_generator_messages(
                use_case, use_case_set.actors, request=request
            ),
            temperature=0,
            response_format={"type": "json_object"},
        )
        activity, parse_report = parse_json_model(
            ActivityGenerationArtifact, text, validator_name="decomposed_activity_parse"
        )
        diagram = None if activity is None else activity.activity_diagram
        if diagram is not None:
            diagram = diagram.model_copy(update={"mermaid_source": render_mermaid(diagram)})
        result = ActivityGenerationResult(
            use_case_id=use_case.id,
            activity_diagram=diagram,
            status=PipelineStatus.PARTIAL if diagram is not None else PipelineStatus.FAILED,
            validation_reports=[parse_report],
        )
        results = [*specification.activity_results, result]
        diagrams = [item.activity_diagram for item in results if item.activity_diagram is not None]
        links = list(specification.trace_manifest.links)
        if activity is not None:
            links.extend(activity.trace_manifest.links)
        specification = specification.model_copy(
            update={
                "activity_results": results,
                "validation_reports": [*specification.validation_reports, parse_report],
                "trace_manifest": materialize_trace_manifest(
                    request, use_case_set, diagrams, existing=TraceManifest(links=links)
                ),
            }
        )
        save(f"activity_generator:{use_case.id}", text, specification)
    return with_contract_validation(specification, contract_version)
