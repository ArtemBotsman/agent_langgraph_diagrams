from __future__ import annotations

import json
from typing import Any

from traceable_spec.entities import OneShotGenerationArtifact, PipelineStatus, TraceManifest
from traceable_spec.evaluation.projection import semantic_projection
from traceable_spec.reference_methods import run_one_shot_baseline
from traceable_spec.testing.fixtures import (
    sample_activity_diagram,
    sample_request,
    sample_use_case_set,
)


class StoredResponseClient:
    def __init__(self, response: str) -> None:
        self.response = response

    def complete(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        del messages, model, temperature, response_format
        return self.response


def test_saved_external_response_uses_the_same_b1_postprocessing() -> None:
    artifact = OneShotGenerationArtifact(
        use_case_set=sample_use_case_set(),
        activity_diagrams=[sample_activity_diagram()],
        trace_manifest=TraceManifest(),
    )
    client = StoredResponseClient(json.dumps(artifact.model_dump(mode="json")))

    result = run_one_shot_baseline(sample_request(), client)

    assert result.status == PipelineStatus.SUCCESS
    assert result.trace_manifest.links
    assert result.activity_results[0].activity_diagram is not None
    assert result.activity_results[0].activity_diagram.mermaid_source
    projection = semantic_projection(result)
    assert projection["actors"] == ["Patron"]
    assert projection["use_cases"][0]["name"] == "Borrow book"
