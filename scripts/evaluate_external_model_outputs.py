"""Import externally generated JSON and score it with the project evaluator."""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from traceable_spec.evaluation.aggregation import attach_repeat_stability, summarize_rows
from traceable_spec.evaluation.benchmark import evaluate_semantic_projection
from traceable_spec.evaluation.projection import automatic_metrics, semantic_projection
from traceable_spec.evaluation.similarity import MultilingualSentenceSimilarity
from traceable_spec.reference_methods import run_one_shot_baseline

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "benchmark" / "v1_0_synthetic" / "cases.json"
DEFAULT_PACKAGE = ROOT / "experiments" / "external_models"
DEFAULT_OUTPUT_ROOT = ROOT / "artifacts" / "external_model_runs"
REPEAT_RE = re.compile(r"^r(\d{2})\.json$")


@dataclass
class StoredResponseClient:
    """Minimal LLMClient implementation returning one saved model response."""

    response: str

    def complete(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        del messages, model, temperature, response_format
        return self.response


def _meta_for(response_path: Path) -> dict[str, Any]:
    meta_path = response_path.with_name(f"{response_path.stem}.meta.json")
    if not meta_path.exists():
        return {}
    value = json.loads(meta_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Metadata must be a JSON object: {meta_path}")
    return value


def _write_bundle(
    run_dir: Path,
    case: dict[str, Any],
    model_label: str,
    response_path: Path,
    specification: Any,
    metrics: dict[str, Any],
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    values = {
        "input.json": case["specification_req"],
        "generated_specification.json": specification.model_dump(mode="json"),
        "trace_manifest.json": specification.trace_manifest.model_dump(mode="json"),
        "validation_reports.json": [
            report.model_dump(mode="json") for report in specification.validation_reports
        ],
        "metrics.json": metrics,
        "config.json": {
            "condition": f"EXTERNAL_ONESHOT_{model_label}",
            "model_label": model_label,
            "case_id": case["case_id"],
            "source_response": str(response_path),
            "postprocessing": "same B1 parser, validators, trace builder and renderer",
        },
    }
    for name, value in values.items():
        (run_dir / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    diagrams = run_dir / "diagrams"
    for result in specification.activity_results:
        diagram = result.activity_diagram
        if diagram is None or not diagram.mermaid_source:
            continue
        diagrams.mkdir(parents=True, exist_ok=True)
        (diagrams / f"{diagram.id}.mmd").write_text(
            diagram.mermaid_source,
            encoding="utf-8",
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-label", required=True)
    parser.add_argument("--package-dir", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--responses-dir", type=Path)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--experiment-id")
    parser.add_argument(
        "--semantic-backend",
        choices=("lexical", "multilingual"),
        default="multilingual",
    )
    parser.add_argument("--allow-model-download", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    responses = args.responses_dir or args.package_dir / "responses"
    manifest = json.loads(
        (args.package_dir / "package_manifest.json").read_text(encoding="utf-8")
    )
    case_ids = list(manifest["case_ids"])
    all_cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    cases = {case["case_id"]: case for case in all_cases if case["case_id"] in case_ids}
    if set(cases) != set(case_ids):
        raise SystemExit("The local benchmark does not contain every package case")

    similarity = None
    similarity_name = "lexical_sequence_candidate"
    if args.semantic_backend == "multilingual":
        similarity = MultilingualSentenceSimilarity(
            local_files_only=not args.allow_model_download
        )
        similarity_name = similarity.name

    experiment_id = args.experiment_id or (
        f"external-{args.model_label}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    )
    experiment_dir = args.output_root / experiment_id
    experiment_dir.mkdir(parents=True, exist_ok=False)
    condition = f"EXTERNAL_ONESHOT_{args.model_label}"
    rows: list[dict[str, Any]] = []

    for case_id in case_ids:
        case_dir = responses / case_id
        response_paths = sorted(
            path for path in case_dir.glob("r??.json") if REPEAT_RE.match(path.name)
        )
        if not response_paths:
            raise SystemExit(f"No responses found for {case_id} in {case_dir}")
        for response_path in response_paths:
            match = REPEAT_RE.match(response_path.name)
            assert match is not None
            repeat_id = int(match.group(1))
            specification = run_one_shot_baseline(
                cases[case_id]["specification_req"],
                StoredResponseClient(response_path.read_text(encoding="utf-8")),
            )
            meta = _meta_for(response_path)
            semantic = evaluate_semantic_projection(
                semantic_projection(specification),
                cases[case_id]["gold"],
                similarity=similarity,
                similarity_name=similarity_name,
            )
            runtime = {
                "latency_ms": meta.get("latency_ms"),
                "llm_calls": 1,
                "prompt_tokens": meta.get("prompt_tokens"),
                "completion_tokens": meta.get("completion_tokens"),
                "total_tokens": meta.get("total_tokens"),
                "estimated_cost_usd": meta.get("provider_reported_cost_usd"),
                "repair_attempts": 0,
            }
            metrics = {**automatic_metrics(specification), **semantic, **runtime}
            row = {
                "condition": condition,
                "case_id": case_id,
                "split": cases[case_id]["split"],
                "complexity": cases[case_id]["complexity"],
                "language": cases[case_id]["language"],
                "repeat_id": repeat_id,
                "run_status": specification.status.value,
                **metrics,
            }
            rows.append(row)
            _write_bundle(
                experiment_dir / condition / case_id / f"r{repeat_id:02d}",
                cases[case_id],
                args.model_label,
                response_path,
                specification,
                metrics,
            )
            print(json.dumps(row, ensure_ascii=False))

    attach_repeat_stability(rows)
    summary = summarize_rows(rows)
    if all(row.get("total_tokens") is None for row in rows):
        for item in summary:
            item["total_llm_tokens"] = None
    result = {
        "experiment_id": experiment_id,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "condition": condition,
        "model_label": args.model_label,
        "case_ids": case_ids,
        "semantic_similarity_backend": similarity_name,
        "postprocessing": "same B1 parser, validators, trace builder and renderer",
        "summary": summary,
        "rows": rows,
    }
    (experiment_dir / "results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    fields = sorted({key for row in rows for key in row})
    with (experiment_dir / "results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
