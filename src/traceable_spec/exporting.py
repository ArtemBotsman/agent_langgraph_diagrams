"""Write a complete, reviewable pipeline result bundle to disk."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from traceable_spec.entities import GeneratedSpecification
from traceable_spec.mermaid import render_mermaid
from traceable_spec.rendering import render_use_case_text


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _safe_manifest(value: dict[str, Any]) -> dict[str, Any]:
    """Reject likely secret fields before a run manifest reaches disk."""

    forbidden_fragments = ("api_key", "apikey", "secret", "password", "token_value")
    unsafe = [
        key
        for key in value
        if any(fragment in key.casefold() for fragment in forbidden_fragments)
    ]
    if unsafe:
        raise ValueError(f"run manifest contains forbidden secret-like fields: {sorted(unsafe)}")
    return value


def write_specification_bundle(
    output_dir: Path,
    raw_input: dict[str, Any],
    specification: GeneratedSpecification,
    run_manifest: dict[str, Any],
) -> list[Path]:
    """Persist all required project artifacts and return their paths.

    The caller owns output-directory collision policy. Raw LLM prompts and
    responses are intentionally excluded; provider telemetry is sanitized by
    the LLM adapter separately.
    """

    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    def write_json(relative: str, value: Any) -> None:
        path = output_dir / relative
        _write_json(path, value)
        written.append(path)

    write_json("input.json", raw_input)
    write_json(
        "generated_specification.json",
        specification.model_dump(mode="json"),
    )
    write_json("trace_manifest.json", specification.trace_manifest.model_dump(mode="json"))
    write_json(
        "validation_reports.json",
        [report.model_dump(mode="json") for report in specification.validation_reports],
    )
    write_json(
        "evaluation_report.json",
        (
            None
            if specification.evaluation_report is None
            else specification.evaluation_report.model_dump(mode="json")
        ),
    )

    normalized_input = specification.request.model_dump(mode="json")
    canonical_input = json.dumps(
        normalized_input,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    complete_manifest = {
        **_safe_manifest(run_manifest),
        "normalized_input_sha256": hashlib.sha256(canonical_input).hexdigest(),
        "pipeline_status": specification.status.value,
        "failure_reason": specification.failure_reason,
        "raw_prompts_or_responses_persisted": False,
        "artifact_contract_version": "1.0",
    }
    write_json("run_manifest.json", complete_manifest)

    user_stories: list[dict[str, Any]] = []
    system_stories: list[dict[str, Any]] = []
    if specification.use_case_set is not None:
        for use_case in specification.use_case_set.use_cases:
            text_path = output_dir / "use_cases" / f"{use_case.id}.md"
            text_path.parent.mkdir(parents=True, exist_ok=True)
            text_path.write_text(
                use_case.human_readable_text or render_use_case_text(use_case),
                encoding="utf-8",
            )
            written.append(text_path)
            user_stories.extend(story.model_dump(mode="json") for story in use_case.user_stories)
            system_stories.extend(
                story.model_dump(mode="json") for story in use_case.system_stories
            )
    write_json("stories/user_stories.json", user_stories)
    write_json("stories/system_stories.json", system_stories)

    for result in specification.activity_results:
        diagram = result.activity_diagram
        if diagram is None:
            continue
        source = diagram.mermaid_source or render_mermaid(diagram)
        diagram_path = output_dir / "activity_diagrams" / f"{diagram.id}.mmd"
        diagram_path.parent.mkdir(parents=True, exist_ok=True)
        diagram_path.write_text(source, encoding="utf-8")
        written.append(diagram_path)

    blocking = [
        issue
        for report in specification.validation_reports
        for issue in report.issues
        if issue.blocking
    ]
    metrics = (
        [] if specification.evaluation_report is None else specification.evaluation_report.metrics
    )
    quality_lines = [
        "# Quality report (отчёт о качестве)",
        "",
        f"- Pipeline status (статус): `{specification.status.value}`",
        f"- Blocking issues (блокирующие ошибки): {len(blocking)}",
        f"- UC repair attempts (попытки исправления UC): "
        f"{specification.uc_repair_attempts_used}",
        f"- Activity repair attempts (попытки исправления Activity): "
        f"{sum(item.repair_attempts_used for item in specification.activity_results)}",
        "",
        "## Automatic metrics (автоматические метрики)",
        "",
    ]
    quality_lines.extend(
        f"- `{metric.name}`: {metric.value}"
        + (f" {metric.unit}" if metric.unit else "")
        for metric in metrics
    )
    if blocking:
        quality_lines.extend(["", "## Blocking issues (блокирующие ошибки)", ""])
        quality_lines.extend(
            f"- `{issue.code}`: {issue.message}" for issue in blocking
        )
    quality_path = output_dir / "quality_report.md"
    quality_path.write_text("\n".join(quality_lines) + "\n", encoding="utf-8")
    written.append(quality_path)
    return written
