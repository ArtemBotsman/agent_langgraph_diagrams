"""Safe structured parsing of LLM text into Pydantic models."""

from __future__ import annotations

import hashlib
import json
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from traceable_spec.entities import (
    IssueCategory,
    IssueSeverity,
    ValidationIssue,
    ValidationReport,
)

ModelT = TypeVar("ModelT", bound=BaseModel)


def _issue(
    seq: int,
    *,
    code: str,
    message: str,
    category: IssueCategory = IssueCategory.SCHEMA,
) -> ValidationIssue:
    return ValidationIssue(
        id=f"VI-{seq:03d}",
        severity=IssueSeverity.ERROR,
        category=category,
        code=code,
        message=message,
    )


def parse_json_model(
    model_type: type[ModelT],
    text: str,
    *,
    validator_name: str = "llm_json_parse",
) -> tuple[ModelT | None, ValidationReport]:
    """Parse JSON text into a Pydantic model; never raises for bad LLM output."""
    issues: list[ValidationIssue] = []
    try:
        data: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        issues.append(
            _issue(
                1,
                code="invalid_json",
                message=f"Response is not valid JSON: {exc.msg} (line {exc.lineno})",
            )
        )
        return None, ValidationReport(
            passed=False,
            issues=issues,
            validator_name=validator_name,
            details={
                "raw_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "raw_char_count": len(text),
            },
        )

    if not isinstance(data, dict):
        issues.append(
            _issue(
                1,
                code="json_not_object",
                message=f"Expected a JSON object, got {type(data).__name__}",
            )
        )
        return None, ValidationReport(
            passed=False,
            issues=issues,
            validator_name=validator_name,
        )

    try:
        model = model_type.model_validate(data)
    except ValidationError as exc:
        for idx, err in enumerate(exc.errors(), start=1):
            loc = ".".join(str(part) for part in err.get("loc", ()))
            issues.append(
                _issue(
                    idx,
                    code="schema_validation_error",
                    message=f"{loc}: {err.get('msg')}" if loc else str(err.get("msg")),
                )
            )
        return None, ValidationReport(
            passed=False,
            issues=issues,
            validator_name=validator_name,
            details={"error_count": len(issues)},
        )

    return model, ValidationReport(
        passed=True,
        issues=[],
        validator_name=validator_name,
    )
