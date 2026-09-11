"""Create JSON and Markdown error analysis from a saved experiment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from traceable_spec.evaluation.error_analysis import analyze_saved_experiment


def _markdown(report: dict[str, object]) -> str:
    lines = [
        f"# Error analysis: {report['experiment_id']}",
        "",
        "Automatic thresholds: semantic composite below 0.5 and hallucination rate above 0.4.",
        "These categories support diagnosis and do not replace independent expert review.",
        "",
    ]
    by_condition = report["by_condition"]
    assert isinstance(by_condition, dict)
    for condition, raw in by_condition.items():
        item = raw
        assert isinstance(item, dict)
        lines.extend(
            [
                f"## {condition}",
                "",
                f"- Runs: {item['run_count']}",
                f"- Exceptions: {item['exception_failure_count']}",
                f"- Controlled pipeline failures: {item['controlled_pipeline_failure_count']}",
                f"- E2E failures: {item['end_to_end_failure_count']}",
                f"- Low semantic runs: {item['low_semantic_below_0_5_count']}",
                f"- High hallucination runs: {item['high_hallucination_above_0_4_count']}",
                "- Unresolved blocking issues: "
                f"`{json.dumps(item['unresolved_blocking_issue_counts'], ensure_ascii=False)}`",
                "- Detected and repaired issues: "
                f"`{json.dumps(item['detected_then_repaired_issue_counts'], ensure_ascii=False)}`",
                "",
            ]
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("experiment_dir", type=Path)
    parser.add_argument("--write-report", action="store_true")
    args = parser.parse_args()
    report = analyze_saved_experiment(args.experiment_dir)
    if args.write_report:
        (args.experiment_dir / "error_analysis.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (args.experiment_dir / "error_analysis.md").write_text(
            _markdown(report) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
