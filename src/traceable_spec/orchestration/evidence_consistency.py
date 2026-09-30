"""Opt-in evidence-consistency profile; old FULL and its prompts stay reproducible.

Changes information supplied to generation/review/repair, not model answers or
the common acceptance metric. A tested feedback fix is not proof of LLM gain.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from traceable_spec.agents.activity.graph import activity_nodes_with_llm
from traceable_spec.entities import ValidationReport
from traceable_spec.evaluation.contracts import V2
from traceable_spec.llm.protocol import LLMClient
from traceable_spec.orchestration.pipeline import PipelineDeps, live_pipeline_deps
from traceable_spec.prompts.use_cases import detect_llm_role

PROFILE = "evidence-consistency-v1"
CONSISTENCY_RULES = (
    f"Review profile: {PROFILE}. Preserve the user's business meaning, not just IDs.\n"
    "- Compare each referenced FR with BOTH step.action and step.expected_result, the UC "
    "conditions and the linked Activity action; an existing ID is not semantic evidence.\n"
    "- actor_id denotes who performs the action, not the primary actor of every step. "
    "For actions performed by the system itself use null, or its explicit system actor "
    "if modeled. A human actor ID must not silently stand for the system. Match diagram "
    "partitions to the same responsibility; keep external service actors when justified.\n"
    "- Check every missing_information question against the complete original source. "
    "Do not ask who performs an action if the source already names that role. Preserve "
    "genuinely unspecified details; do not invent answers or hide uncertainty.\n"
    "- Preserve conditions, thresholds, recipients and outcomes. Distinct triggering "
    "events must not accidentally become consecutive mandatory actions. UC scenarios "
    "and diagram branches must express the same alternatives. A validation/eligibility "
    "guard must precede its controlled effect unless the source explicitly defines a "
    "compensating workflow. Do not silently repair a contradictory UC only in its diagram.\n"
    "- Keep all supported obligations during repair; do not delete steps, FR references, "
    "open questions or assumptions merely to make a check pass. Distinguish a supported "
    "business rule, an explicitly open requirement and an unsupported new rule.\n"
    "- Critics: for a blocking issue quote the relevant original source, identify its "
    "FR/NFR or project_description and affected artifact IDs, and explain the contradiction "
    "or omission. A possible inconsistency without evidence is a warning, not proof. "
    "Use the existing CriticVerdict schema and allowed issue codes; no new output fields.\n"
    "- Repair feedback concerns the CURRENT draft. Re-check it against the source, fix "
    "only supported defects and return the complete artifact, not a patch or discussion."
)


class EvidenceConsistencyClient:
    """Stateless prompt enrichment. No hidden Gold, response editing or extra calls."""

    def __init__(self, client: LLMClient, *, actors=None):
        self.client = client
        self.actors = actors

    def complete(self, *, messages, model=None, temperature=None, response_format=None):
        enriched = [dict(message) for message in messages]
        role = detect_llm_role(enriched)
        if role in {
            "use_case_generator",
            "use_case_critic",
            "use_case_repair",
            "activity_generator",
            "activity_critic",
            "activity_repair",
        }:
            for message in enriched:
                if message.get("role") == "system":
                    message["content"] += "\n" + CONSISTENCY_RULES
                    break
            if self.actors is not None and role in {"activity_critic", "activity_repair"}:
                # Those legacy builders contain the UC but not the actor dictionary.
                # Add the actual per-invocation state, never a previous UC's cached actors.
                for message in enriched:
                    if message.get("role") == "user":
                        payload = json.loads(message["content"])
                        payload["actors"] = [a.model_dump(mode="json") for a in self.actors]
                        message["content"] = json.dumps(payload, ensure_ascii=False, indent=2)
                        break
        return self.client.complete(
            messages=enriched, model=model, temperature=temperature, response_format=response_format
        )


def current_attempt_reports(reports: list[ValidationReport], kind: str):
    """A fresh parse starts an attempt even if parsing failed; keep that failure.

    Without a known boundary retain all reports (fail conservative). Never infer
    that an issue has been fixed just from its ID or from the presence of new text.
    """
    if kind not in {"uc", "activity"}:
        raise ValueError("Unknown artifact kind")
    names = {f"{kind}_generator_parse", f"{kind}_repair_parse"}
    starts = [i for i, report in enumerate(reports) if report.validator_name in names]
    return list(reports[starts[-1] :] if starts else reports)


def current_feedback_only(node, kind: str):
    """Keep the audit trail, but do not ask the repairer to fix obsolete drafts."""

    def repair(state: dict[str, Any]):
        history = list(state.get("validation_reports") or [])
        active = current_attempt_reports(history, kind)
        result = node({**state, "validation_reports": active})
        emitted = list(result.get("validation_reports") or [])
        if emitted[: len(active)] != active:
            raise ValueError("Repair node changed validation history unexpectedly")
        result["validation_reports"] = history + emitted[len(active) :]
        return result

    return repair


def evidence_consistency_deps(client: LLMClient, *, contract_version: str = V2) -> PipelineDeps:
    """Explicit new FULL profile. Same graph topology, limits and common validator."""
    deps = live_pipeline_deps(EvidenceConsistencyClient(client), contract_version=contract_version)

    def activity_node(name):
        def invoke(state):
            actor_client = EvidenceConsistencyClient(client, actors=list(state.get("actors") or []))
            nodes = activity_nodes_with_llm(actor_client, contract_version=contract_version)
            return getattr(nodes, name)(state)

        return invoke

    return replace(
        deps,
        use_case_nodes=replace(
            deps.use_case_nodes,
            repair_use_case_set=current_feedback_only(
                deps.use_case_nodes.repair_use_case_set, "uc"
            ),
        ),
        activity_nodes=replace(
            deps.activity_nodes,
            criticize_activity_model=activity_node("criticize_activity_model"),
            repair_activity_model=current_feedback_only(
                activity_node("repair_activity_model"), "activity"
            ),
        ),
    )
