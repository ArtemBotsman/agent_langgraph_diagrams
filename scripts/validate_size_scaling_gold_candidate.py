"""Validate coverage and referential integrity of size-scaling Gold labels."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BENCHMARK = ROOT / "benchmark" / "size_scaling_v1"


def validate(benchmark_dir: Path, gold_path: Path) -> dict[str, Any]:
    manifest = json.loads((benchmark_dir / "manifest.json").read_text(encoding="utf-8"))
    labels = json.loads(gold_path.read_text(encoding="utf-8"))
    by_id = {item.get("case_id"): item for item in labels}
    errors: list[str] = []
    if len(labels) != manifest["case_count"] or len(by_id) != len(labels):
        errors.append("Gold candidate must contain one unique record per benchmark case")

    counts: Counter[str] = Counter()
    for case in manifest["cases"]:
        case_id = case["case_id"]
        record = by_id.get(case_id)
        if record is None:
            errors.append(f"{case_id}: missing Gold record")
            continue
        request = json.loads(
            (benchmark_dir / "inputs" / case["file"]).read_text(encoding="utf-8")
        )
        valid_frs = {
            f"FR-{index:03d}"
            for index in range(1, len(request["functional_requirements"]) + 1)
        }
        gold = record.get("gold", {})
        actors = gold.get("actor_slots", [])
        actor_names = {item.get("canonical") for item in actors}
        if not actors or None in actor_names or len(actor_names) != len(actors):
            errors.append(f"{case_id}: invalid actor slots")
        use_cases = gold.get("use_case_slots", [])
        slot_ids = {item.get("slot_id") for item in use_cases}
        if not use_cases or None in slot_ids or len(slot_ids) != len(use_cases):
            errors.append(f"{case_id}: invalid use-case slots")
        covered = {fr_id for item in use_cases for fr_id in item.get("source_fr_ids", [])}
        if covered != valid_frs:
            errors.append(f"{case_id}: UC source_fr_ids must cover every FR exactly by ID set")
        if set(gold.get("fr_coverage", {})) != valid_frs:
            errors.append(f"{case_id}: fr_coverage must enumerate every FR")
        if any(item.get("primary_actor") not in actor_names for item in use_cases):
            errors.append(f"{case_id}: primary_actor must reference actor_slots")
        if any(not item.get("required_milestones") for item in use_cases):
            errors.append(f"{case_id}: every UC needs required milestones")
        trace_items = gold.get("trace_expectations", [])
        if {item.get("source_fr_id") for item in trace_items} != valid_frs:
            errors.append(f"{case_id}: trace expectations must enumerate every FR")
        if any(
            not set(item.get("allowed_target_uc_slots", [])).issubset(slot_ids)
            or not item.get("allowed_target_uc_slots")
            for item in trace_items
        ):
            errors.append(f"{case_id}: invalid trace expectation targets")
        expected_nfrs = {
            f"NFR-{index:03d}"
            for index in range(1, len(request["non_functional_requirements"]) + 1)
        }
        if set(gold.get("nfr_expectations", {})) != expected_nfrs:
            errors.append(f"{case_id}: nfr_expectations must enumerate every NFR")
        counts[case["size_group"]] += 1

    return {
        "passed": not errors,
        "case_count": len(labels),
        "group_counts": dict(counts),
        "gold_candidate_sha256": hashlib.sha256(gold_path.read_bytes()).hexdigest(),
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark-dir", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument("--gold-path", type=Path)
    args = parser.parse_args()
    gold_path = args.gold_path or args.benchmark_dir / "gold_candidate.json"
    result = validate(args.benchmark_dir, gold_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
