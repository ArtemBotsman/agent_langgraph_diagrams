"""Automatic evaluator contracts and metric calculations (no LLM-as-a-judge)."""

from __future__ import annotations

from collections import Counter

from traceable_spec.entities import (
    EvaluationReport,
    GeneratedSpecification,
    MetricResult,
    PipelineStatus,
    TraceLinkType,
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

    # Measure the final bundle, not failed intermediate attempts that were later
    # repaired. Historical validation reports remain available for error analysis.
    expected_activity_ids = (
        {item.id for item in spec.use_case_set.use_cases} if spec.use_case_set else set()
    )
    final_activity_ids = {
        item.use_case_id
        for item in spec.activity_results
        if item.activity_diagram is not None
    }
    schema_ok = spec.use_case_set is not None and expected_activity_ids == final_activity_ids
    metrics.append(
        _metric(
            "schema_validity",
            1.0 if schema_ok else 0.0,
            higher_is_better=True,
            notes=(
                "1 if the final typed bundle contains a UseCaseSet and one typed Activity "
                "artifact for every final Use Case; repaired intermediate parse failures "
                "do not invalidate the final bundle"
            ),
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

    dangling_link_ids = {
        issue.element_ids[0]
        for report in spec.validation_reports
        for issue in report.issues
        if issue.code in {"dangling_trace_source", "dangling_trace_target"} and issue.element_ids
    }
    link_count = max(len(spec.trace_manifest.links), 1)
    metrics.append(
        _metric(
            "trace_reference_integrity",
            max(0.0, 1.0 - (len(dangling_link_ids) / link_count)),
            higher_is_better=True,
            unit="ratio",
            notes="1 - dangling_links / max(links,1) (approx from validation issues)",
        )
    )

    expected_links = len(fr_ids)
    traced_fr_ids = {
        link.source_id
        for link in spec.trace_manifest.links
        if link.link_type == TraceLinkType.FR_TO_UC
    }
    metrics.append(
        _metric(
            "trace_completeness",
            len(traced_fr_ids & set(fr_ids)) / expected_links if expected_links else 0.0,
            higher_is_better=True,
            unit="ratio",
        )
    )

    step_ids_by_fr: dict[str, set[str]] = {fr_id: set() for fr_id in fr_ids}
    activity_step_ids: set[str] = set()
    for link in spec.trace_manifest.links:
        if link.link_type == TraceLinkType.FR_TO_STEP and link.source_id in step_ids_by_fr:
            step_ids_by_fr[link.source_id].add(link.target_id)
        elif link.link_type in {
            TraceLinkType.STEP_TO_ACTIVITY_NODE,
            TraceLinkType.STEP_TO_ACTIVITY_EDGE,
        }:
            activity_step_ids.add(link.source_id)
    frs_reaching_activity = {
        fr_id
        for fr_id, step_ids in step_ids_by_fr.items()
        if step_ids & activity_step_ids
    }
    metrics.append(
        _metric(
            "fr_activity_coverage",
            len(frs_reaching_activity) / len(fr_ids) if fr_ids else 0.0,
            higher_is_better=True,
            unit="ratio",
            notes=(
                "|FRs connected to at least one Activity node or edge through a scenario "
                "step| / |FRs|"
            ),
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

    repair_sum = spec.uc_repair_attempts_used + sum(
        r.repair_attempts_used for r in spec.activity_results
    )
    metrics.append(
        _metric(
            "repair_attempts",
            repair_sum,
            higher_is_better=False,
            unit="count",
            notes="Use Case repair attempts plus all Activity repair attempts",
        )
    )

    coverage_reports = [
        report for report in spec.validation_reports if report.validator_name == "e2e_trace"
    ]
    e2e_details = coverage_reports[-1].details if coverage_reports else {}
    trace_manifest_validity = bool(coverage_reports and coverage_reports[-1].passed)
    metrics.append(
        _metric(
            "trace_manifest_validity",
            1.0 if trace_manifest_validity else 0.0,
            higher_is_better=True,
            notes="1 if the final end-to-end trace validator passed, otherwise 0",
        )
    )
    for metric_name, detail_name in (
        ("uc_element_trace_coverage", "uc_ratio"),
        ("activity_element_trace_coverage", "activity_ratio"),
    ):
        value = e2e_details.get("trace_coverage_thresholds", {}).get(detail_name)
        metrics.append(
            _metric(
                metric_name,
                value,
                higher_is_better=True,
                unit="ratio",
                notes="Computed by the end-to-end trace coverage validator",
            )
        )

    unsupported_count = sum(
        1 for link in spec.trace_manifest.links if link.link_type == TraceLinkType.UNSUPPORTED
    )
    metrics.append(
        _metric(
            "unsupported_trace_rate",
            unsupported_count / link_count,
            higher_is_better=False,
            unit="ratio",
        )
    )
    # Intermediate failures are repair evidence, not unresolved final defects.
    # Successful bundles therefore have zero remaining blocking classes. For a
    # failed bundle retain all recorded classes to support diagnosis.
    blocking_issue_codes = (
        set()
        if spec.status == PipelineStatus.SUCCESS
        else {
            issue.code
            for report in spec.validation_reports
            for issue in report.issues
            if issue.blocking
        }
    )
    metrics.append(
        _metric(
            "blocking_error_classes",
            len(blocking_issue_codes),
            higher_is_better=False,
            unit="count",
            notes="Unresolved blocking classes in the final bundle; repaired history excluded",
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
