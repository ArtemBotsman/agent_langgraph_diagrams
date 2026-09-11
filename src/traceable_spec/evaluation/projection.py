"""Provider-neutral projections shared by experiment runners."""

from __future__ import annotations

from typing import Any

from traceable_spec.entities import GeneratedSpecification


def semantic_projection(specification: GeneratedSpecification) -> dict[str, Any]:
    """Project a full result onto the semantic slots used by the benchmark."""

    use_case_set = specification.use_case_set
    if use_case_set is None:
        return {"actors": [], "use_cases": []}
    return {
        "actors": [actor.name for actor in use_case_set.actors],
        "use_cases": [
            {
                "name": use_case.name,
                "source_fr_ids": list(use_case.source_fr_ids),
                "milestones": [
                    step.action
                    for scenario in [
                        use_case.main_success_scenario,
                        *use_case.alternative_scenarios,
                        *use_case.exception_scenarios,
                    ]
                    for step in scenario.steps
                ],
                "branches": [
                    {
                        "condition": scenario.name,
                        "outcomes": [step.action for step in scenario.steps],
                    }
                    for scenario in [
                        *use_case.alternative_scenarios,
                        *use_case.exception_scenarios,
                    ]
                ],
            }
            for use_case in use_case_set.use_cases
        ],
    }


def automatic_metrics(specification: GeneratedSpecification) -> dict[str, Any]:
    """Return the pipeline's deterministic metric report as a flat mapping."""

    report = specification.evaluation_report
    if report is None:
        return {}
    return {metric.name: metric.value for metric in report.metrics}
