from __future__ import annotations

from traceable_spec.agents.activity.graph import default_activity_nodes
from traceable_spec.llm.scripted import ScriptedLLMClient
from traceable_spec.orchestration.component_variants import live_pipeline_deps_without_critics
from traceable_spec.testing.fixtures import sample_use_case_set


def test_no_critic_component_variant_is_explicit_and_makes_no_llm_calls() -> None:
    client = ScriptedLLMClient({})
    deps = live_pipeline_deps_without_critics(client)

    uc_result = deps.use_case_nodes.criticize_use_case_set({"validation_reports": []})
    activity_result = deps.activity_nodes.criticize_activity_model(
        {"use_case": sample_use_case_set().use_cases[0], "validation_reports": []}
    )

    assert uc_result["critic_report"].validator_name == (
        "uc_critic_component_variant_disabled"
    )
    assert activity_result["critic_report"].validator_name == (
        "activity_critic_component_variant_disabled"
    )
    assert client.calls == []


def test_activity_preparation_preserves_zero_repair_limit() -> None:
    prepare = default_activity_nodes().prepare_use_case

    result = prepare(
        {
            "use_case": sample_use_case_set().use_cases[0],
            "max_repair_attempts": 0,
        }
    )

    assert result["max_repair_attempts"] == 0
