"""Deterministic human-readable Use Case text renderer."""

from __future__ import annotations

from traceable_spec.entities import UseCase


def render_use_case_text(use_case: UseCase) -> str:
    lines = [
        f"Use Case: {use_case.id} — {use_case.name}",
        f"Goal: {use_case.goal}",
        f"Primary actor: {use_case.primary_actor_id}",
        f"Trigger: {use_case.trigger}",
        "Preconditions:",
    ]
    for pre in use_case.preconditions:
        lines.append(f"  - {pre.id}: {pre.text}")
    lines.append("Main success scenario:")
    for step in sorted(use_case.main_success_scenario.steps, key=lambda s: s.order):
        lines.append(f"  {step.order}. [{step.id}] {step.action}")
    if use_case.alternative_scenarios:
        lines.append("Alternative scenarios:")
        for scenario in use_case.alternative_scenarios:
            lines.append(f"  - {scenario.id}: {scenario.name}")
    if use_case.exception_scenarios:
        lines.append("Exception scenarios:")
        for scenario in use_case.exception_scenarios:
            lines.append(f"  - {scenario.id}: {scenario.name}")
    lines.append(f"Source FRs: {', '.join(use_case.source_fr_ids)}")
    return "\n".join(lines) + "\n"
