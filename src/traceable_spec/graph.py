"""Compatibility import for the root orchestrator.

New code should import :mod:`traceable_spec.orchestration.pipeline`.
"""

from __future__ import annotations

from traceable_spec.orchestration.pipeline import (
    PipelineDeps,
    build_pipeline_graph,
    compile_live_pipeline,
    compile_pipeline,
    default_pipeline_deps,
    live_pipeline_deps,
)

__all__ = [
    "PipelineDeps",
    "build_pipeline_graph",
    "compile_live_pipeline",
    "compile_pipeline",
    "default_pipeline_deps",
    "live_pipeline_deps",
]
