"""Read approved development or input-only cases; never select the hidden split."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_experiment_cases(
    root: Path, dataset: str = "dev20", case_ids: list[str] | None = None
) -> list[dict[str, Any]]:
    if dataset == "dev20":
        records = [
            case
            for case in json.loads((root / "benchmark/v1_0_synthetic/cases.json").read_text())
            if case["split"] == "development"
        ]
    elif dataset == "size_inputs":
        folder = root / "benchmark/size_scaling_v1"
        manifest = json.loads((folder / "manifest.json").read_text())
        selected = [
            item for item in manifest["cases"] if not case_ids or item["case_id"] in case_ids
        ]
        records = [
            {
                "case_id": item["case_id"],
                "split": "input_only_pilot",
                "specification_req": json.loads((folder / "inputs" / item["file"]).read_text()),
                "gold": None,
            }
            for item in selected
        ]
    else:
        raise ValueError("Supported datasets are dev20 and size_inputs")
    if case_ids:
        records = [case for case in records if case["case_id"] in case_ids]
        if set(case_ids) != {case["case_id"] for case in records}:
            raise ValueError("Unknown case IDs; hidden cases cannot be selected")
    return records
