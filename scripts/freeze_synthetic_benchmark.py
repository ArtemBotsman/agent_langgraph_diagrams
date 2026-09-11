"""Create a reproducible author-level freeze without fabricating expert approval."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = ROOT / "benchmark" / "v1_0_synthetic"
CASES_PATH = BENCHMARK_DIR / "cases.json"
MANIFEST_PATH = BENCHMARK_DIR / "manifest.json"
FREEZE_RECORD_PATH = BENCHMARK_DIR / "freeze_record.json"


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _derived_files(cases: list[dict[str, Any]]) -> dict[str, bytes]:
    development = [case for case in cases if case["split"] == "development"]
    hidden = [case for case in cases if case["split"] == "hidden"]
    hidden_inputs = [
        {key: value for key, value in case.items() if key != "gold"} for case in hidden
    ]
    hidden_gold = [{"case_id": case["case_id"], "gold": case["gold"]} for case in hidden]
    return {
        "development_cases.json": _json_bytes(development),
        "hidden_inputs.json": _json_bytes(hidden_inputs),
        "sealed_hidden_gold.json": _json_bytes(hidden_gold),
    }


def _verify_existing_freeze(
    *,
    record: dict[str, Any],
    cases_bytes: bytes,
    files: dict[str, bytes],
    manifest: dict[str, Any],
) -> None:
    expected = {
        "cases_sha256": _sha256(cases_bytes),
        "development_cases_sha256": _sha256(files["development_cases.json"]),
        "hidden_inputs_sha256": _sha256(files["hidden_inputs.json"]),
        "sealed_hidden_gold_sha256": _sha256(files["sealed_hidden_gold.json"]),
    }
    mismatches = [
        f"{name}: recorded={record.get(name)!r}, actual={digest!r}"
        for name, digest in expected.items()
        if record.get(name) != digest
    ]
    for filename, expected_bytes in files.items():
        path = BENCHMARK_DIR / filename
        if not path.exists() or path.read_bytes() != expected_bytes:
            mismatches.append(f"{filename}: derived file is missing or differs")
    if manifest.get("technical_frozen_at_utc") != record.get("frozen_at_utc"):
        mismatches.append("manifest timestamp differs from freeze record")
    if manifest.get("cases_sha256") != expected["cases_sha256"]:
        mismatches.append("manifest cases_sha256 differs from current cases.json")
    if mismatches:
        details = "\n- ".join(mismatches)
        raise SystemExit(
            "Technical freeze verification failed. Use --force only after an "
            f"intentional benchmark revision.\n- {details}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Create an author-level benchmark freeze, or verify the existing freeze "
            "without rewriting it."
        )
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="intentionally replace the existing technical freeze after a revision",
    )
    args = parser.parse_args()

    cases_bytes = CASES_PATH.read_bytes()
    cases = json.loads(cases_bytes)
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    development = [case for case in cases if case["split"] == "development"]
    hidden = [case for case in cases if case["split"] == "hidden"]
    files = _derived_files(cases)

    if FREEZE_RECORD_PATH.exists() and not args.force:
        freeze_record = json.loads(FREEZE_RECORD_PATH.read_text(encoding="utf-8"))
        _verify_existing_freeze(
            record=freeze_record,
            cases_bytes=cases_bytes,
            files=files,
            manifest=manifest,
        )
        print(
            json.dumps(
                {**freeze_record, "verification": "ok_no_files_changed"},
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    for filename, content in files.items():
        (BENCHMARK_DIR / filename).write_bytes(content)

    frozen_at = datetime.now(UTC).isoformat()
    freeze_record = {
        "freeze_level": "author_technical_freeze",
        "frozen_at_utc": frozen_at,
        "benchmark_version": "1.0.0-synthetic-author-freeze",
        "cases_sha256": _sha256(cases_bytes),
        "development_cases_sha256": _sha256(files["development_cases.json"]),
        "hidden_inputs_sha256": _sha256(files["hidden_inputs.json"]),
        "sealed_hidden_gold_sha256": _sha256(files["sealed_hidden_gold.json"]),
        "development_count": len(development),
        "hidden_count": len(hidden),
        "hidden_tuning_allowed": False,
        "expert_reviews_complete": False,
        "supervisor_approved": False,
        "recommended_git_tag": "benchmark-v1.0.0-synthetic-author-freeze",
        "claim_limit": (
            "The bytes and split are frozen by the author. Scientific approval remains "
            "pending until two experts and the supervisor sign off."
        ),
    }
    FREEZE_RECORD_PATH.write_bytes(_json_bytes(freeze_record))
    manifest.update(
        {
            "benchmark_version": freeze_record["benchmark_version"],
            "technical_frozen": True,
            "technical_frozen_at_utc": frozen_at,
            "frozen": False,
            "scientific_frozen": False,
            "cases_sha256": freeze_record["cases_sha256"],
            "freeze_record": "freeze_record.json",
            "recommended_git_tag": freeze_record["recommended_git_tag"],
            "freeze_blocker": (
                "Two independent expert reviews and written supervisor approval are required "
                "for scientific freeze."
            ),
        }
    )
    MANIFEST_PATH.write_bytes(_json_bytes(manifest))
    print(json.dumps(freeze_record, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
