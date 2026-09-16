from __future__ import annotations

from pathlib import Path

from traceable_spec.baselines import run_rule_based_baseline
from traceable_spec.entities import PipelineStatus
from traceable_spec.graph import compile_pipeline
from traceable_spec.persistence import open_sqlite_checkpointer, thread_config
from traceable_spec.testing.fixtures import sample_request


def test_rule_based_baseline_is_reproducible_and_traceable() -> None:
    first = run_rule_based_baseline(sample_request())
    second = run_rule_based_baseline(sample_request())
    assert first.status == PipelineStatus.SUCCESS
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.activity_results[0].activity_diagram is not None
    assert first.activity_results[0].activity_diagram.mermaid_source
    coverage = next(
        metric for metric in first.evaluation_report.metrics if metric.name == "fr_coverage"
    )
    assert coverage.value == 1.0
    fr_activity_coverage = next(
        metric
        for metric in first.evaluation_report.metrics
        if metric.name == "fr_activity_coverage"
    )
    assert fr_activity_coverage.value == 1.0
    trace_manifest_validity = next(
        metric
        for metric in first.evaluation_report.metrics
        if metric.name == "trace_manifest_validity"
    )
    assert trace_manifest_validity.value == 1.0


def test_sqlite_checkpointer_recovers_pipeline_state(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "pipeline.sqlite"
    config = thread_config("persisted-test-run")
    with open_sqlite_checkpointer(checkpoint_path) as checkpointer:
        graph = compile_pipeline(checkpointer=checkpointer)
        graph.invoke({"request": sample_request()}, config=config)
        snapshot = graph.get_state(config)
        assert snapshot.values["specification"].status == PipelineStatus.SUCCESS
        assert snapshot.values["next_activity_index"] == 1
        history = list(graph.get_state_history(config))
        assert len(history) >= 2
        assert any(
            state.values.get("next_activity_index") == 1
            and len(state.values.get("activity_results") or []) == 1
            for state in history
        )
    assert checkpoint_path.exists()
