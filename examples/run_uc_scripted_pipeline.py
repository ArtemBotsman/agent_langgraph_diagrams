#!/usr/bin/env python3
"""Offline demo of the UC graph with ScriptedLLMClient (FAKE — not a real AI call).

Run from the Agent project root:

    poetry run python examples/run_uc_scripted_pipeline.py

Demonstrates: successful generation, validator failure, one repair, then success.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from traceable_spec.llm.scripted import ScriptedLLMClient  # noqa: E402
from traceable_spec.prompts.use_cases import (  # noqa: E402
    ROLE_CRITIC,
    ROLE_GENERATOR,
    ROLE_REPAIR,
)
from traceable_spec.testing.fixtures import sample_request  # noqa: E402
from traceable_spec.testing.scripted_uc_responses import (  # noqa: E402
    broken_trace_uc_artifact_json,
    critic_accept_json,
    critic_repair_json,
    valid_uc_artifact_json,
)
from traceable_spec.use_cases_graph import (  # noqa: E402
    compile_use_cases_graph,
    use_case_graph_output_from_state,
    use_case_nodes_with_llm,
)


def main() -> None:
    print("=== Scripted/fake UC pipeline demo (NOT a live LLM) ===\n")

    client = ScriptedLLMClient(
        {
            ROLE_GENERATOR: [broken_trace_uc_artifact_json()],
            ROLE_CRITIC: [
                critic_repair_json(
                    code="missing_trace",
                    message="FR→UC links missing; request repair",
                ),
                critic_accept_json("Accept after repair"),
            ],
            ROLE_REPAIR: [valid_uc_artifact_json()],
        }
    )
    request = sample_request().model_copy(update={"max_repair_attempts": 2})
    graph = compile_use_cases_graph(use_case_nodes_with_llm(client))
    state = graph.invoke({"request": request})
    output = use_case_graph_output_from_state(state)

    uc_ids = (
        [uc.id for uc in output.use_case_set.use_cases] if output.use_case_set else []
    )
    print(f"status: {output.status.value}")
    print(f"repair_attempts_used: {output.repair_attempts_used}")
    print(f"use_cases: {uc_ids}")
    print(f"scripted client calls: {[c['role'] for c in client.calls]}")
    print(f"validation reports: {len(output.validation_reports)}")
    blocking = [
        issue.code
        for report in output.validation_reports
        for issue in report.issues
        if issue.blocking
    ]
    print(f"blocking issue codes seen: {sorted(set(blocking))}")
    if output.status.value != "success":
        raise SystemExit(1)
    print("\nDemo finished successfully (scripted/fake client only).")


if __name__ == "__main__":
    main()
