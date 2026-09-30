"""Method-blind final checks of delivered artifacts, without repair or Gold access.

This is a common formal contract, not an independent human semantic assessment.
Internal pipeline verdicts and historical failures are deliberately not inputs
to the verdict. The delivered artifact itself is checked again.
"""

from __future__ import annotations

from collections import Counter

from traceable_spec.entities import (
    GeneratedSpecification,
    IssueCategory,
    IssueSeverity,
    PipelineStatus,
    ValidationIssue,
    ValidationReport,
)
from traceable_spec.validators import (
    validate_activity_deterministic,
    validate_end_to_end_trace,
    validate_fr_to_uc_trace_links,
    validate_pydantic_model,
    validate_uc_fr_references,
    validate_use_case_structure,
)

FORMAL_CONTRACT_VERSION = "common-final-v1-2026-09-25"


def evaluate_final_formal(specification: GeneratedSpecification) -> ValidationReport:
    """Check the final package without trusting status, old reports or critic votes."""
    # Reparse because model_copy can bypass validation. Do not modify the input.
    schema = validate_pydantic_model(GeneratedSpecification, specification.model_dump(mode="json"))
    reports = [schema]
    coverage_issues: list[ValidationIssue] = []

    def issue(code: str, message: str, ids: list[str]) -> None:
        coverage_issues.append(
            ValidationIssue(
                id=f"VI-{len(coverage_issues) + 1:03d}",
                severity=IssueSeverity.ERROR,
                category=IssueCategory.STRUCTURAL,
                code=code,
                message=message,
                element_ids=ids,
            )
        )

    if schema.passed:
        use_case_set = specification.use_case_set
        if use_case_set is None:
            issue("final_missing_uc", "Final package has no UseCaseSet", [])
        else:
            reports.extend(
                [
                    validate_use_case_structure(use_case_set),
                    validate_uc_fr_references(
                        use_case_set,
                        [fr.id for fr in specification.request.functional_requirements],
                    ),
                    validate_fr_to_uc_trace_links(use_case_set, specification.trace_manifest),
                    validate_end_to_end_trace(specification),
                ]
            )
            use_cases = {uc.id: uc for uc in use_case_set.use_cases}
            counts: Counter[str] = Counter()
            for result in specification.activity_results:
                counts[result.use_case_id] += 1
                diagram = result.activity_diagram
                if result.use_case_id not in use_cases:
                    issue(
                        "final_unknown_activity_uc",
                        "Activity result refers to unknown UC",
                        [result.use_case_id],
                    )
                if diagram is None:
                    issue(
                        "final_missing_activity",
                        "Activity result has no diagram",
                        [result.use_case_id],
                    )
                elif result.use_case_id in use_cases:
                    reports.append(
                        validate_activity_deterministic(diagram, use_cases[result.use_case_id])
                    )
            for use_case_id in use_cases:
                if counts[use_case_id] != 1:
                    issue(
                        "final_activity_cardinality",
                        f"Expected exactly one Activity result for {use_case_id}, "
                        f"found {counts[use_case_id]}",
                        [use_case_id],
                    )
    reports.append(
        ValidationReport(
            passed=not coverage_issues,
            issues=coverage_issues,
            validator_name="final_artifact_completeness",
        )
    )
    merged = [item for report in reports for item in report.issues]
    return ValidationReport(
        passed=all(report.passed for report in reports),
        issues=[
            item.model_copy(update={"id": f"VI-{index:03d}"})
            for index, item in enumerate(merged, 1)
        ],
        validator_name=FORMAL_CONTRACT_VERSION,
        details={
            "checks": [
                {"validator_name": report.validator_name, "passed": report.passed}
                for report in reports
            ],
            "uses_internal_status": False,
            "uses_gold": False,
        },
    )


def with_common_final_validation(specification: GeneratedSpecification) -> GeneratedSpecification:
    """Opt-in acceptance for new baselines, preserving the legacy default path."""
    report = evaluate_final_formal(specification)
    return specification.model_copy(
        update={
            "status": PipelineStatus.SUCCESS if report.passed else PipelineStatus.FAILED,
            "validation_reports": [*specification.validation_reports, report],
            "failure_reason": None if report.passed else "Common final contract failed",
            # Legacy automatic metrics depend on internal statuses and old reports.
            # The new experiment calculates metrics separately from final artifacts.
            "evaluation_report": None,
        }
    )
