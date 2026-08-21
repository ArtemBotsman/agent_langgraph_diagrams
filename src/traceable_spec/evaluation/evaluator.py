"""Automatic evaluator contracts and metric calculations (no LLM-as-a-judge)."""

from __future__ import annotations

from collections import Counter

from traceable_spec.entities import (
    EvaluationReport,
    GeneratedSpecification,
    MetricResult,
    PipelineStatus,
)


def _metric(
    name: str,
    value: float | int | bool | str | None,
    *,
    higher_is_better: bool | None,
    unit: str | None = None,
    notes: str | None = None,
) -> MetricResult:
    return MetricResult(
        name=name,
        value=value,
        higher_is_better=higher_is_better,
        unit=unit,
        notes=notes,
    )


def evaluate_specification(spec: GeneratedSpecification) -> EvaluationReport:
    """Compute automatic structural/trace metrics from GeneratedSpecification."""
    metrics: list[MetricResult] = []

    schema_ok = all(
        report.validator_name.endswith("schema") is False or report.passed
        for report in spec.validation_reports
    )
    # Prefer explicit schema reports
    schema_reports = [r for r in spec.validation_reports if "schema" in r.validator_name]
    if schema_reports:
        schema_ok = all(r.passed for r in schema_reports)
    metrics.append(
        _metric(
            "schema_validity",
            1.0 if schema_ok else 0.0,
            higher_is_better=True,
            notes="Share of schema validators that passed",
        )
    )

    fr_ids = [fr.id for fr in spec.request.functional_requirements]
    covered: set[str] = set()
    if spec.use_case_set is not None:
        for uc in spec.use_case_set.use_cases:
            covered.update(uc.source_fr_ids)
    coverage = (len(covered & set(fr_ids)) / len(fr_ids)) if fr_ids else 0.0
    metrics.append(
        _metric(
            "fr_coverage",
            coverage,
            higher_is_better=True,
            unit="ratio",
            notes="|FRs referenced by ≥1 UC| / |FRs|",
        )
    )

    orphan_uc = 0
    duplicate_names = 0
    if spec.use_case_set is not None:
        names = [uc.name.strip().lower() for uc in spec.use_case_set.use_cases]
        duplicate_names = sum(1 for _, c in Counter(names).items() if c > 1)
        orphan_uc = sum(1 for uc in spec.use_case_set.use_cases if not uc.source_fr_ids)
        uc_count = max(len(spec.use_case_set.use_cases), 1)
        metrics.append(
            _metric(
                "orphan_uc_rate",
                orphan_uc / uc_count,
                higher_is_better=False,
                unit="ratio",
            )
        )
        metrics.append(
            _metric(
                "duplicate_uc_rate",
                duplicate_names / uc_count,
                higher_is_better=False,
                unit="ratio",
            )
        )
    else:
        metrics.append(_metric("orphan_uc_rate", 1.0, higher_is_better=False, unit="ratio"))
        metrics.append(_metric("duplicate_uc_rate", 0.0, higher_is_better=False, unit="ratio"))

    dangling = sum(
        1
        for report in spec.validation_reports
        for issue in report.issues
        if issue.code in {"dangling_trace_source", "dangling_trace_target"}
    )
    link_count = max(len(spec.trace_manifest.links), 1)
    metrics.append(
        _metric(
            "trace_reference_integrity",
            1.0 - (dangling / link_count),
            higher_is_better=True,
            unit="ratio",
            notes="1 - dangling_links / max(links,1) (approx from validation issues)",
        )
    )

    expected_links = len(fr_ids)
    actual_fr_links = sum(
        1 for link in spec.trace_manifest.links if link.source_id.startswith("FR-")
    )
    metrics.append(
        _metric(
            "trace_completeness",
            min(actual_fr_links / expected_links, 1.0) if expected_links else 0.0,
            higher_is_better=True,
            unit="ratio",
        )
    )

    activity_ok = 0
    mermaid_ok = 0
    for result in spec.activity_results:
        if result.status == PipelineStatus.SUCCESS and result.activity_diagram is not None:
            activity_ok += 1
            if result.activity_diagram.mermaid_source:
                mermaid_ok += 1
    total_ad = max(len(spec.activity_results), 1)
    metrics.append(
        _metric(
            "activity_structural_validity",
            activity_ok / total_ad,
            higher_is_better=True,
            unit="ratio",
        )
    )
    metrics.append(
        _metric(
            "mermaid_generation_success",
            mermaid_ok / total_ad,
            higher_is_better=True,
            unit="ratio",
        )
    )

    e2e = spec.status == PipelineStatus.SUCCESS
    metrics.append(_metric("end_to_end_success", 1.0 if e2e else 0.0, higher_is_better=True))

    repair_sum = sum(r.repair_attempts_used for r in spec.activity_results)
    metrics.append(
        _metric(
            "repair_attempts",
            repair_sum,
            higher_is_better=False,
            unit="count",
            notes="Sum of activity repair attempts; UC repairs tracked in validation details",
        )
    )

    # Placeholders for future multi-run / cost metrics
    metrics.append(
        _metric(
            "stability_multi_run",
            None,
            higher_is_better=True,
            notes="Requires ≥2 seeded runs; not computed in scaffold",
        )
    )
    metrics.append(
        _metric(
            "latency_ms",
            None,
            higher_is_better=False,
            unit="ms",
            notes="Filled when LLM nodes are wired",
        )
    )
    metrics.append(
        _metric(
            "token_usage",
            None,
            higher_is_better=False,
            unit="tokens",
            notes="Filled when LLM nodes are wired",
        )
    )
    metrics.append(
        _metric(
            "cost_usd",
            None,
            higher_is_better=False,
            unit="usd",
            notes="Filled when LLM nodes are wired",
        )
    )

    return EvaluationReport(
        metrics=metrics,
        automatic_only=True,
        notes="Automatic metrics only; LLM-as-a-judge and expert scores are separate tracks",
    )
