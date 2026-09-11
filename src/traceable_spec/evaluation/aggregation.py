"""Deterministic aggregation shared by experiment execution and verification."""

from __future__ import annotations

from statistics import mean, pstdev
from typing import Any

DEFAULT_CONDITION_ORDER = (
    "B0_RULE",
    "B1_ONESHOT",
    "FULL",
    "FULL_NO_CRITIC",
    "FULL_NO_REPAIR",
)

NUMERIC_METRICS = (
    "end_to_end_success",
    "semantic_composite",
    "actor_f1",
    "uc_f1",
    "milestone_f1",
    "branch_f1",
    "trace_f1",
    "hallucination_rate",
    "latency_ms",
    "llm_calls",
    "total_tokens",
    "estimated_cost_usd",
    "repair_attempts",
    "stability_multi_run",
)


def attach_repeat_stability(rows: list[dict[str, Any]]) -> None:
    """Attach score-range stability for each condition/case repeated at least twice."""

    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((str(row["condition"]), str(row["case_id"])), []).append(row)
    for current in groups.values():
        values = [float(row["semantic_composite"]) for row in current]
        stability = None if len(values) < 2 else max(0.0, 1.0 - (max(values) - min(values)))
        for row in current:
            row["stability_multi_run"] = stability


def summarize_rows(
    rows: list[dict[str, Any]],
    *,
    condition_order: tuple[str, ...] = DEFAULT_CONDITION_ORDER,
) -> list[dict[str, Any]]:
    """Calculate the stable condition-level summary used in research artifacts."""

    result: list[dict[str, Any]] = []
    observed = {str(row["condition"]) for row in rows}
    ordered = [*condition_order, *sorted(observed - set(condition_order))]
    for condition in ordered:
        current = [row for row in rows if row["condition"] == condition]
        if not current:
            continue
        metric_summary: dict[str, float | None] = {}
        for metric in NUMERIC_METRICS:
            values = [float(row[metric]) for row in current if row.get(metric) is not None]
            metric_summary[f"mean_{metric}"] = mean(values) if values else None
            if metric in {"semantic_composite", "total_tokens", "latency_ms"}:
                metric_summary[f"stddev_{metric}"] = pstdev(values) if len(values) > 1 else None
        result.append(
            {
                "condition": condition,
                "run_count": len(current),
                "total_llm_tokens": sum(int(row.get("total_tokens") or 0) for row in current),
                **metric_summary,
            }
        )
    return result
