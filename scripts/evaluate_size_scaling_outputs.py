"""Import external one-shot responses for the input-only scaling benchmark."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from traceable_spec.entities import SpecificationReq
from traceable_spec.evaluation.projection import automatic_metrics
from traceable_spec.evaluation.scaling import artifact_counts, summarize_scaling_rows
from traceable_spec.exporting import write_specification_bundle
from traceable_spec.reference_methods import run_one_shot_baseline

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BENCHMARK = ROOT / "benchmark" / "size_scaling_v1"
DEFAULT_RESPONSES = ROOT / "experiments" / "size_scaling_external" / "responses"
DEFAULT_OUTPUT = ROOT / "artifacts" / "size_scaling_external_runs"
LABEL_RE = re.compile(r"^[A-Z0-9_-]+$")
REPEAT_RE = re.compile(r"^r(?P<repeat>\d{2})\.json$")


class ReplayClient:
    """Minimal client returning one exact previously saved model response."""

    def __init__(self, response: str) -> None:
        self.response = response

    def complete(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = 0,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        del messages, model, temperature, response_format
        return self.response


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(payload).hexdigest()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--condition-label", required=True)
    parser.add_argument("--benchmark-dir", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument("--responses-dir", type=Path, default=DEFAULT_RESPONSES)
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument("--experiment-id")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if not LABEL_RE.fullmatch(args.condition_label):
        raise SystemExit("--condition-label must contain only A-Z, 0-9, _ or -")
    manifest = json.loads((args.benchmark_dir / "manifest.json").read_text(encoding="utf-8"))
    selected = list(manifest["cases"])
    if args.case_id:
        wanted = set(args.case_id)
        selected = [case for case in selected if case["case_id"] in wanted]
        missing = wanted - {case["case_id"] for case in selected}
        if missing:
            raise SystemExit(f"Unknown case IDs: {sorted(missing)}")

    experiment_id = args.experiment_id or (
        f"external-size-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    )
    experiment_dir = args.output_root / experiment_id
    experiment_dir.mkdir(parents=True, exist_ok=False)
    rows: list[dict[str, Any]] = []
    missing_responses: list[str] = []

    for case in selected:
        case_dir = args.responses_dir / case["case_id"]
        response_files = sorted(
            path for path in case_dir.glob("r??.json") if REPEAT_RE.fullmatch(path.name)
        )
        if not response_files:
            missing_responses.append(case["case_id"])
            continue
        request = cast(
            SpecificationReq,
            json.loads((args.benchmark_dir / "inputs" / case["file"]).read_text(encoding="utf-8")),
        )
        for response_path in response_files:
            match = REPEAT_RE.fullmatch(response_path.name)
            assert match is not None
            repeat_id = int(match.group("repeat"))
            raw_response = response_path.read_text(encoding="utf-8")
            specification = run_one_shot_baseline(request, ReplayClient(raw_response))
            meta_path = response_path.with_suffix(".meta.json")
            meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
            metrics = {
                **automatic_metrics(specification),
                **artifact_counts(specification),
                "latency_ms": meta.get("latency_ms"),
                "llm_calls": 1,
                "prompt_tokens": meta.get("prompt_tokens"),
                "completion_tokens": meta.get("completion_tokens"),
                "total_tokens": meta.get("total_tokens"),
                "estimated_cost_usd": meta.get("provider_reported_cost_usd"),
                "repair_attempts": 0,
                "output_bytes": len(raw_response.encode("utf-8")),
                "output_sha256": _canonical_sha256(specification.model_dump(mode="json")),
            }
            run_dir = experiment_dir / args.condition_label / case["case_id"] / f"r{repeat_id:02d}"
            run_manifest = {
                "experiment_id": experiment_id,
                "condition": args.condition_label,
                "case_id": case["case_id"],
                "repeat_id": repeat_id,
                "benchmark_id": manifest["benchmark_id"],
                "external_model": meta.get("model"),
                "raw_response_sha256": hashlib.sha256(raw_response.encode("utf-8")).hexdigest(),
            }
            write_specification_bundle(
                run_dir,
                cast(dict[str, Any], request),
                specification,
                run_manifest,
            )
            (run_dir / "scaling_metrics.json").write_text(
                json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            rows.append(
                {
                    "condition": args.condition_label,
                    "case_id": case["case_id"],
                    "project_name": case["project_name"],
                    "size_group": case["size_group"],
                    "size_label_ru": case["size_label_ru"],
                    "fr_count": case["fr_count"],
                    "nfr_count": case["nfr_count"],
                    "repeat_id": repeat_id,
                    "run_status": specification.status.value,
                    **metrics,
                }
            )

    if args.require_complete and missing_responses:
        raise SystemExit(f"Missing responses for: {missing_responses}")
    if not rows:
        raise SystemExit("No response files found")

    summary = summarize_scaling_rows(rows)
    result = {
        "experiment_id": experiment_id,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "benchmark_id": manifest["benchmark_id"],
        "condition": args.condition_label,
        "gold_available": False,
        "missing_response_case_ids": missing_responses,
        "claim_limit": manifest["claim_limit"],
        "summary": summary,
        "rows": rows,
    }
    (experiment_dir / "results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for filename, values in (("results.csv", rows), ("summary.csv", summary)):
        fields = sorted({key for item in values for key in item})
        with (experiment_dir / filename).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(values)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
