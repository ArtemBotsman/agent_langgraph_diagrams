"""Independent per-artifact semantic-critic budget for an explicit ablation.

The formal repair limit stays unchanged. Exhausting this budget permits formal
finalization without a new semantic verdict; it never means critic approval.
Counts are stored in the graph reports, not a shared mutable closure.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from traceable_spec.entities import ValidationReport
from traceable_spec.evaluation.contracts import V1
from traceable_spec.llm.protocol import LLMClient
from traceable_spec.orchestration.pipeline import PipelineDeps, live_pipeline_deps

NodeFn = Callable[[Any], dict[str, Any]]


def record_formal_snapshot(node: NodeFn, kind: str) -> NodeFn:
    """Record formal error identities at each attempt without changing routing."""

    def recorded(state: dict[str, Any]) -> dict[str, Any]:
        result = node(state)
        reports = [state.get("schema_report"), result.get("deterministic_report")]
        errors = sorted(
            {
                (report.validator_name, issue.code, tuple(sorted(issue.element_ids)))
                for report in reports
                if report is not None
                for issue in report.issues
                if issue.blocking
            }
        )
        artifact = "uc_set" if kind == "uc" else "activity:" + state["use_case"].id
        snapshot = ValidationReport(
            passed=not errors,
            validator_name="repair_diagnostic_snapshot",
            details={
                "artifact": artifact,
                "attempt": state.get("repair_attempt", 0),
                "formal_error_keys": [list(key) for key in errors],
            },
        )
        result["validation_reports"] = [*result["validation_reports"], snapshot]
        return result

    return recorded


def formal_repair_diagnostics(reports: list[ValidationReport]) -> dict[str, Any] | None:
    """Disappearing validator keys are a proxy, not proof of semantic correction."""
    snapshots: dict[tuple[str, int], set[tuple[str, str, tuple[str, ...]]]] = {}
    for report in reports:
        if report.validator_name != "repair_diagnostic_snapshot":
            continue
        info = report.details
        key = info["artifact"], info["attempt"]
        errors = {(v, c, tuple(ids)) for v, c, ids in info["formal_error_keys"]}
        if key in snapshots and snapshots[key] != errors:
            raise ValueError("Conflicting snapshots for one artifact attempt")
        snapshots[key] = errors
    if not snapshots:
        return None
    transitions: list[dict[str, Any]] = []
    for (artifact, attempt), after in sorted(snapshots.items()):
        before = snapshots.get((artifact, attempt - 1))
        if before is not None:
            transitions.append(
                {
                    "artifact": artifact,
                    "attempt": attempt,
                    "removed_error_keys": len(before - after),
                    "introduced_error_keys": len(after - before),
                }
            )
    return {
        "definition": "consecutive formal validator error keys; not human-confirmed fixes",
        "transitions": transitions,
        "removed_error_keys": sum(t["removed_error_keys"] for t in transitions),
        "introduced_error_keys": sum(t["introduced_error_keys"] for t in transitions),
        "caveat": "ID changes can change keys; semantic fixes require separate assessment",
    }


def limit_critic(node: NodeFn, limit: int, kind: str) -> NodeFn:
    if type(limit) is not int or limit not in range(4):
        raise ValueError("Critic limit must be an integer from 0 to 3")
    if kind not in {"uc", "activity"}:
        raise ValueError("Unknown artifact kind")

    def bounded(state: dict[str, Any]) -> dict[str, Any]:
        reports = list(state.get("validation_reports") or [])
        used = sum(
            bool(r.details.get("critic_budget_call"))
            for r in reports
            if r.details.get("critic_budget_kind") == kind
        )
        if used >= limit:
            skipped = ValidationReport(
                passed=True,
                validator_name=f"{kind}_critic_budget_skipped",
                details={
                    "critic_budget_kind": kind,
                    "critic_budget_limit": limit,
                    "critic_budget_used": used,
                    "semantic_assessed": False,
                    "critic_approval": None,
                    "reason": "not assessed after critic budget; formal checks still required",
                },
            )
            return {"critic_report": skipped, "validation_reports": [*reports, skipped]}
        result = node(state)
        report = result["critic_report"]
        # The graph routes here only for an existing, formally valid artifact.
        # The parse report is produced once per actual critic API response.
        called = any(
            r.validator_name == f"{kind}_critic_parse"
            for r in result.get("validation_reports", [])[len(reports) :]
        )
        marked = report.model_copy(
            update={
                "details": {
                    **report.details,
                    "critic_budget_kind": kind,
                    "critic_budget_limit": limit,
                    "critic_budget_call": called,
                    "critic_budget_used": used + int(called),
                    "semantic_assessed": called,
                }
            }
        )
        result["critic_report"] = marked
        result["validation_reports"] = [
            marked if r is report else r for r in result["validation_reports"]
        ]
        return result

    return bounded


def live_pipeline_deps_with_critic_budget(
    client: LLMClient, limit: int, *, contract_version: str = V1
) -> PipelineDeps:
    deps = live_pipeline_deps(client, contract_version=contract_version)
    return replace(
        deps,
        use_case_nodes=replace(
            deps.use_case_nodes,
            validate_uc_deterministic=record_formal_snapshot(
                deps.use_case_nodes.validate_uc_deterministic, "uc"
            ),
            criticize_use_case_set=limit_critic(
                deps.use_case_nodes.criticize_use_case_set, limit, "uc"
            ),
        ),
        activity_nodes=replace(
            deps.activity_nodes,
            validate_activity_deterministic=record_formal_snapshot(
                deps.activity_nodes.validate_activity_deterministic, "activity"
            ),
            criticize_activity_model=limit_critic(
                deps.activity_nodes.criticize_activity_model, limit, "activity"
            ),
        ),
    )
