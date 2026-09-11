"""Prompt builders owned by the Use Case Agent."""

from __future__ import annotations

from traceable_spec.prompts.use_cases import (
    ROLE_CRITIC,
    ROLE_GENERATOR,
    ROLE_REPAIR,
    build_use_case_critic_messages,
    build_use_case_generator_messages,
    build_use_case_repair_messages,
    detect_llm_role,
)

__all__ = [
    "ROLE_CRITIC",
    "ROLE_GENERATOR",
    "ROLE_REPAIR",
    "build_use_case_critic_messages",
    "build_use_case_generator_messages",
    "build_use_case_repair_messages",
    "detect_llm_role",
]
