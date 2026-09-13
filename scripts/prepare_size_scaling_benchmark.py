"""Validate and materialize a supervisor-provided input-only size benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from traceable_spec.entities import SpecificationReq, normalize_specification_req
from traceable_spec.evaluation.scaling import SIZE_BANDS, classify_fr_count

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "benchmark" / "size_scaling_v1"
EXPECTED_FIELDS = {
    "project_task",
    "project_name",
    "project_goal",
    "project_description",
    "functional_requirements",
    "non_functional_requirements",
}


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_sources(path: Path) -> list[tuple[str, bytes]]:
    if path.is_dir():
        return [(item.name, item.read_bytes()) for item in sorted(path.glob("*.json"))]
    if path.suffix.lower() != ".zip":
        raise SystemExit("Source must be a ZIP archive or a directory of JSON files")
    with zipfile.ZipFile(path) as archive:
        names = sorted(
            name
            for name in archive.namelist()
            if name.lower().endswith(".json") and not name.startswith("__MACOSX/")
        )
        return [(Path(name).name, archive.read(name)) for name in names]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    sources = _read_sources(args.source)
    if len(sources) != 20:
        raise SystemExit(f"Expected 20 JSON inputs, found {len(sources)}")

    input_dir = args.output_dir / "inputs"
    input_dir.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    expected_names = {name for name, _ in sources}
    stale = {path.name for path in input_dir.glob("*.json")} - expected_names
    if stale:
        raise SystemExit(f"Refusing to remove stale inputs: {sorted(stale)}")

    for index, (name, payload) in enumerate(sources, start=1):
        try:
            raw = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SystemExit(f"Invalid JSON in {name}: {exc}") from exc
        if not isinstance(raw, dict) or set(raw) != EXPECTED_FIELDS:
            raise SystemExit(f"{name} must contain exactly the six SpecificationReq fields")
        normalized = normalize_specification_req(cast(SpecificationReq, raw))
        fr_count = len(normalized.functional_requirements)
        nfr_count = len(normalized.non_functional_requirements)
        band = classify_fr_count(fr_count)
        (input_dir / name).write_bytes(payload)
        entries.append(
            {
                "case_id": f"SCALE-{index:03d}",
                "file": name,
                "project_name": normalized.project_name,
                "size_group": band.id,
                "size_label_ru": band.label_ru,
                "fr_count": fr_count,
                "nfr_count": nfr_count,
                "input_bytes": len(payload),
                "project_task_chars": len(normalized.project_task),
                "rough_input_tokens_chars_div_4": round(len(payload.decode("utf-8")) / 4),
                "sha256": _sha256(payload),
            }
        )

    distribution = Counter(entry["size_group"] for entry in entries)
    expected_distribution = {band.id: 5 for band in SIZE_BANDS}
    if dict(distribution) != expected_distribution:
        raise SystemExit(f"Expected five cases per size group, observed {dict(distribution)}")

    source_bytes = args.source.read_bytes() if args.source.is_file() else None
    manifest = {
        "benchmark_id": "size_scaling_v1",
        "benchmark_kind": "input_only_scalability",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "input_contract": "SpecificationReq/6 fields",
        "case_count": len(entries),
        "group_distribution": expected_distribution,
        "size_bands": [
            {
                "id": band.id,
                "label_ru": band.label_ru,
                "minimum_fr": band.minimum_fr,
                "maximum_fr": band.maximum_fr,
            }
            for band in SIZE_BANDS
        ],
        "source_archive_name": args.source.name if args.source.is_file() else None,
        "source_archive_sha256": _sha256(source_bytes) if source_bytes is not None else None,
        "publication_status": "permission_not_recorded",
        "gold_available": False,
        "claim_limit": (
            "Supports scalability, structural, traceability and cost measurements. "
            "Semantic superiority requires gold labels or independent expert review."
        ),
        "cases": entries,
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"output": str(args.output_dir), **distribution}, ensure_ascii=False))


if __name__ == "__main__":
    main()
