"""Create blank review packets for two independent benchmark experts."""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "benchmark" / "v1_0_synthetic" / "cases.json"
OUTPUT_DIR = ROOT / "benchmark" / "expert_review"
FIELDS = [
    "case_id",
    "expert_id",
    "domain_plausibility_1_5",
    "actor_uc_boundaries_1_5",
    "scenario_completeness_1_5",
    "branch_correctness_1_5",
    "trace_correctness_1_5",
    "assumption_discipline_1_5",
    "decision",
    "comments",
]


def main() -> None:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for packet_name in ("expert_1_blank.csv", "expert_2_blank.csv"):
        with (OUTPUT_DIR / packet_name).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            for case in cases:
                writer.writerow({"case_id": case["case_id"]})


if __name__ == "__main__":
    main()
