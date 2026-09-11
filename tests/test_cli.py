from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from traceable_spec.cli import main


def _request() -> dict[str, object]:
    return {
        "project_task": "Generate analysis artifacts",
        "project_name": "CLI Test",
        "project_goal": "Verify one-command packaging",
        "project_description": "An offline command-line test",
        "functional_requirements": ["A user can submit an item."],
        "non_functional_requirements": ["The result must be auditable."],
    }


def test_cli_writes_complete_b0_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output"
    input_path.write_text(json.dumps(_request()), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["traceable-spec", str(input_path), str(output_path), "--mode", "B0_RULE"],
    )

    main()

    assert (output_path / "generated_specification.json").exists()
    assert (output_path / "quality_report.md").exists()


def test_cli_requires_live_acknowledgement_before_creating_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output"
    input_path.write_text(json.dumps(_request()), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["traceable-spec", str(input_path), str(output_path), "--mode", "FULL"],
    )

    with pytest.raises(SystemExit, match="explicit --allow-live"):
        main()

    assert not output_path.exists()
