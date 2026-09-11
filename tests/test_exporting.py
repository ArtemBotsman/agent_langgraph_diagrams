from __future__ import annotations

import json
from pathlib import Path

import pytest

from traceable_spec.exporting import write_specification_bundle
from traceable_spec.reference_methods import run_rule_based_baseline
from traceable_spec.testing.fixtures import sample_request


def test_write_specification_bundle_contains_required_artifacts(tmp_path: Path) -> None:
    specification = run_rule_based_baseline(sample_request())

    written = write_specification_bundle(
        tmp_path,
        {"source": "test"},
        specification,
        {"mode": "B0_RULE", "provider": None},
    )

    relative = {path.relative_to(tmp_path).as_posix() for path in written}
    assert "generated_specification.json" in relative
    assert "trace_manifest.json" in relative
    assert "validation_reports.json" in relative
    assert "evaluation_report.json" in relative
    assert "stories/user_stories.json" in relative
    assert "stories/system_stories.json" in relative
    assert "quality_report.md" in relative
    assert any(path.startswith("use_cases/") for path in relative)
    assert any(path.startswith("activity_diagrams/") for path in relative)
    manifest = json.loads((tmp_path / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["raw_prompts_or_responses_persisted"] is False
    assert len(manifest["normalized_input_sha256"]) == 64


def test_write_specification_bundle_rejects_secret_manifest_fields(tmp_path: Path) -> None:
    specification = run_rule_based_baseline(sample_request())

    with pytest.raises(ValueError, match="forbidden secret-like"):
        write_specification_bundle(
            tmp_path,
            {"source": "test"},
            specification,
            {"api_key": "must-not-be-written"},
        )
