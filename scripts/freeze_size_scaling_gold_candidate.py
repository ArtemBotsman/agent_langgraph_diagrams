"""Freeze the local size-scaling Gold candidate without claiming expert approval."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BENCHMARK = ROOT / "benchmark" / "size_scaling_v1"


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark-dir", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    manifest_path = args.benchmark_dir / "manifest.json"
    gold_path = args.benchmark_dir / "gold_candidate.json"
    freeze_path = args.benchmark_dir / "gold_freeze_record.json"
    if freeze_path.exists() and not args.force:
        record = json.loads(freeze_path.read_text(encoding="utf-8"))
        current = _sha256(gold_path)
        if record.get("gold_candidate_sha256") != current:
            raise SystemExit("Gold changed after freeze; use --force only for a reviewed revision")
        verified = {**record, "verification": "ok_no_files_changed"}
        print(json.dumps(verified, ensure_ascii=False, indent=2))
        return

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    labels = json.loads(gold_path.read_text(encoding="utf-8"))
    case_ids = [str(item["case_id"]) for item in labels]
    expected_ids = [str(item["case_id"]) for item in manifest["cases"]]
    if case_ids != expected_ids:
        raise SystemExit("Gold case order or membership differs from benchmark manifest")
    frozen_at = datetime.now(UTC).isoformat()
    record = {
        "freeze_level": "author_gold_candidate_freeze",
        "frozen_at_utc": frozen_at,
        "benchmark_id": manifest["benchmark_id"],
        "case_count": len(labels),
        "input_manifest_sha256": _sha256(manifest_path),
        "gold_candidate_sha256": _sha256(gold_path),
        "annotation_source": "SpecificationReq inputs only",
        "system_outputs_used_for_annotation": False,
        "expert_reviews_complete": False,
        "supervisor_approved": False,
        "scientific_frozen": False,
        "claim_limit": (
            "The author candidate bytes are fixed before B1/FULL evaluation. "
            "Scientific claims require two independent expert reviews."
        ),
    }
    freeze_path.write_bytes(_bytes(record))
    manifest.update(
        {
            "gold_candidate_available_local": True,
            "gold_candidate_sha256": record["gold_candidate_sha256"],
            "gold_candidate_frozen_at_utc": frozen_at,
            "gold_candidate_status": "author_candidate_requires_two_independent_reviews",
            "gold_available": False,
            "scientific_frozen": False,
        }
    )
    manifest_path.write_bytes(_bytes(manifest))
    print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
