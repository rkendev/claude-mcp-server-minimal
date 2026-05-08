"""Canonical CCA-F D2 error struct shared by every MCP tool in this server.

Every tool failure surfaces as a structured envelope rather than a raw
exception or an MCP-protocol-level ``isError`` flag (the latter is
reserved for true transport / unhandled-exception faults). The struct
mirrors the CCA-F D2 vocabulary so downstream consumers can triage
failures by ``errorCategory`` and avoid burning retry budget when
``isRetryable`` is ``False``.

This module deliberately lives next to ``server.py`` rather than under
``domain/`` — ``domain/`` is inherited template scaffolding (see
``CLAUDE.md``) and is out of scope for Artifact A.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

ErrorCategory = Literal["transient", "validation", "permission", "business"]


class ToolError(BaseModel):
    """CCA-F D2 canonical tool-error shape.

    Attributes:
        errorCategory: One of the four canonical categories.
        isRetryable: ``False`` for ``validation`` / ``permission`` (and most
            ``business``) failures — clients must not retry these.
        message: Human-readable explanation specific to this failure.
        details: Optional structured context (e.g. Pydantic ``errors()``).
    """

    # mixedCase field names are mandated by the CCA-F D2 canonical
    # error-struct vocabulary — do not rename to snake_case.
    errorCategory: ErrorCategory  # noqa: N815
    isRetryable: bool  # noqa: N815
    message: str
    details: dict[str, Any] | None = None

    model_config = {"frozen": True}


def error_envelope(
    *,
    category: ErrorCategory,
    is_retryable: bool,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a ``{"success": False, "error": {...}}`` envelope."""
    return {
        "success": False,
        "error": ToolError(
            errorCategory=category,
            isRetryable=is_retryable,
            message=message,
            details=details,
        ).model_dump(),
    }


def success_envelope(data: dict[str, Any]) -> dict[str, Any]:
    """Build a ``{"success": True, "data": {...}}`` envelope."""
    return {"success": True, "data": data}


__all__ = ["ErrorCategory", "ToolError", "error_envelope", "success_envelope"]
