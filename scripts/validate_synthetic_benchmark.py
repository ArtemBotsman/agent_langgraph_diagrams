"""Validate the 30-case benchmark candidate and its gold coverage."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = ROOT / "benchmark" / "v1_0_synthetic"
INPUT_FIELDS = {
    "project_task",
    "project_name",
    "project_goal",
    "project_description",
    "functional_requirements",
    "non_functional_requirements",
}


def validate() -> dict[str, Any]:
    cases_path = BENCHMARK_DIR / "cases.json"
    manifest_path = BENCHMARK_DIR / "manifest.json"
    cases_text = cases_path.read_text(encoding="utf-8")
    cases = json.loads(cases_text)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors: list[str] = []

    if len(cases) != 30:
        errors.append(f"case_count={len(cases)}, expected 30")
    if len({case["case_id"] for case in cases}) != len(cases):
        errors.append("case_id values are not unique")
    if Counter(case["split"] for case in cases) != Counter({"development": 20, "hidden": 10}):
        errors.append("split must be development=20, hidden=10")
    if set(case["complexity"] for case in cases) != {"simple", "medium", "hard"}:
        errors.append("both splits together must cover simple/medium/hard")
    if set(case["language"] for case in cases) != {"ru", "en"}:
        errors.append("benchmark must contain ru and en cases")

    for case in cases:
        prefix = case["case_id"]
        request = case.get("specification_req", {})
        if set(request) != INPUT_FIELDS:
            errors.append(f"{prefix}: invalid SpecificationReq fields")
        for field in INPUT_FIELDS - {"functional_requirements", "non_functional_requirements"}:
            if not isinstance(request.get(field), str) or not request[field].strip():
                errors.append(f"{prefix}: {field} must be non-empty text")
        frs = request.get("functional_requirements", [])
        nfrs = request.get("non_functional_requirements", [])
        if not frs or not all(isinstance(item, str) and item.strip() for item in frs):
            errors.append(f"{prefix}: functional_requirements invalid")
        if not all(isinstance(item, str) and item.strip() for item in nfrs):
            errors.append(f"{prefix}: non_functional_requirements invalid")

        gold = case.get("gold", {})
        expected_frs = {f"FR-{idx:03d}" for idx in range(1, len(frs) + 1)}
        if set(gold.get("fr_coverage", {})) != expected_frs:
            errors.append(f"{prefix}: fr_coverage does not cover every FR")
        uc_slots = gold.get("use_case_slots", [])
        slot_ids = {uc.get("slot_id") for uc in uc_slots}
        if not uc_slots or None in slot_ids or len(slot_ids) != len(uc_slots):
            errors.append(f"{prefix}: invalid or duplicate UC slots")
        traced_frs = {fr_id for uc in uc_slots for fr_id in uc.get("source_fr_ids", [])}
        if traced_frs != expected_frs:
            errors.append(f"{prefix}: UC source_fr_ids do not cover every FR")
        if any(not uc.get("required_milestones") for uc in uc_slots):
            errors.append(f"{prefix}: each UC needs scenario milestones")
        trace_sources = {item.get("source_fr_id") for item in gold.get("trace_expectations", [])}
        if trace_sources != expected_frs:
            errors.append(f"{prefix}: trace expectations do not cover every FR")

    digest = hashlib.sha256(cases_text.encode("utf-8")).hexdigest()
    if digest != manifest.get("cases_sha256"):
        errors.append("cases_sha256 differs from manifest")
    if manifest.get("frozen") is not False:
        errors.append("synthetic candidate must remain unfrozen until external approval")

    result = {
        "passed": not errors,
        "case_count": len(cases),
        "split_counts": dict(Counter(case["split"] for case in cases)),
        "complexity_counts": dict(Counter(case["complexity"] for case in cases)),
        "language_counts": dict(Counter(case["language"] for case in cases)),
        "errors": errors,
    }
    return result


if __name__ == "__main__":
    outcome = validate()
    print(json.dumps(outcome, ensure_ascii=False, indent=2))
    raise SystemExit(0 if outcome["passed"] else 1)
