"""Minimal MCP server (stdio transport) — Artifact A, Wk1 (T001 + T002).

Exposes two tools over stdio:

* ``describe_schema`` (T001) — returns this server's self-description: its
  schema version (``v1``), server name, and the metadata of every tool it
  advertises. The tool reflects on the registered MCP tools at call time
  (via ``mcp.list_tools()``) rather than returning hardcoded metadata, so
  adding a tool with ``@mcp.tool()`` automatically surfaces it here.
* ``echo_toolcall`` (T002) — echoes its ``input`` back, where ``input`` is
  ``str | EchoInput`` (an ``anyOf`` parameter shape). Validates
  ``MCP_API_KEY`` at call time.

Every tool result is wrapped in the canonical envelope from
``server_errors``: ``{"success": True, "data": ...}`` on success and
``{"success": False, "error": {"errorCategory": ..., "isRetryable": ...,
"message": ...}}`` on failure. The MCP-protocol-level ``isError`` flag is
deliberately *not* used for tool-domain failures — it is reserved for
true transport / unhandled-exception faults.

The exact wire shape of ``describe_schema`` is pinned by
``test_describe_schema_returns_exact_v1_shape`` so an SDK upgrade that
quietly reshapes the dict breaks tests instead of silently changing the
published schema.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from anthropic import Anthropic
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ValidationError

from claude_mcp_server_minimal.server_errors import error_envelope, success_envelope
from claude_mcp_server_minimal.system_prompts import SUBAGENT_SYSTEM_PROMPT

SCHEMA_VERSION = "v1"
SERVER_NAME = "claude-mcp-server-minimal"
MODEL_DEFAULT = "claude-haiku-4-5-20251001"
MAX_TOKENS = 1024

mcp = FastMCP(SERVER_NAME)


class EchoInput(BaseModel):
    """Structured branch of ``echo_toolcall``'s ``anyOf`` input."""

    message: str
    metadata: dict[str, Any] | None = None

    model_config = {"extra": "forbid"}


# Result is wrapped in the canonical success envelope:
# ``{"success": True, "data": {"schema_version": ..., "server": ..., "tools": [...]}}``.
@mcp.tool()  # type: ignore[misc, unused-ignore]  # mcp SDK has no py.typed marker (1.27.0); revisit when SDK ships types
async def describe_schema() -> dict[str, Any]:
    """Return this server's schema version and the tools it advertises."""
    tools = await mcp.list_tools()
    return success_envelope(
        {
            "schema_version": SCHEMA_VERSION,
            "server": SERVER_NAME,
            "tools": [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.inputSchema,
                }
                for t in tools
            ],
        }
    )


# ``input`` is published as an ``anyOf`` of a bare string OR an
# ``EchoInput`` object (``message: str``, optional ``metadata``).
# Failures surface as ``{"success": False, "error": {...}}``; the
# MCP-protocol-level ``isError`` flag is *not* used for tool-domain
# failures — it is reserved for true transport / unhandled-exception
# faults.
#
# Branches (in order): permission check → string fast-path → dict
# validation via ``EchoInput.model_validate`` → success.
#
# The runtime parameter type is ``str | dict[str, Any]`` (not
# ``str | EchoInput``) so that invalid object input reaches this
# function and returns a structured envelope rather than being rejected
# at the FastMCP / Pydantic boundary as a raw ``ToolError``. The
# *published* ``inputSchema`` for the dict branch is overridden below
# to advertise the strict ``EchoInput`` shape; clients see the
# contract, the function enforces it explicitly.
@mcp.tool()  # type: ignore[misc, unused-ignore]  # mcp SDK has no py.typed marker (1.27.0); revisit when SDK ships types
async def echo_toolcall(input: str | dict[str, Any]) -> dict[str, Any]:
    """Echo ``input`` back, wrapped in the canonical success envelope."""
    if not os.environ.get("MCP_API_KEY", ""):
        return error_envelope(
            category="permission",
            is_retryable=False,
            message="MCP_API_KEY is not set; echo_toolcall requires it at call time",
        )

    if isinstance(input, str):
        return success_envelope(
            {
                "echoed": input,
                "received_at": datetime.now(UTC).isoformat(),
            }
        )

    try:
        parsed = EchoInput.model_validate(input)
    except ValidationError as e:
        return error_envelope(
            category="validation",
            is_retryable=False,
            message="echo_toolcall input failed validation against EchoInput",
            details={"errors": e.errors(include_url=False)},
        )

    data: dict[str, Any] = {
        "echoed": parsed.message,
        "received_at": datetime.now(UTC).isoformat(),
    }
    if parsed.metadata is not None:
        data["metadata"] = parsed.metadata
    return success_envelope(data)


# Private-API overrides on the FastMCP tool registry. T001 already does
# this for `describe_schema` (additionalProperties:false + required:[]);
# T002 adds two more entries on `echo_toolcall`'s parameters dict so the
# published `inputSchema` reflects the strict EchoInput contract for
# the dict branch of the anyOf.
# TODO(mcp>=2): replace with a public Tool.parameters API once the SDK
# adds one. Until then, this is the only way to influence what
# `tools/list` returns. Tracking
# https://github.com/modelcontextprotocol/python-sdk for an entry point.
_describe_schema_tool = mcp._tool_manager._tools["describe_schema"]
_describe_schema_tool.parameters["additionalProperties"] = False
_describe_schema_tool.parameters["required"] = []

_echo_toolcall_tool = mcp._tool_manager._tools["echo_toolcall"]
_echo_toolcall_tool.parameters["properties"]["input"]["anyOf"][1] = (  # type: ignore[misc, unused-ignore]
    EchoInput.model_json_schema()
)


class SubagentQueryInput(BaseModel):
    """Strict input schema for ``subagent_query`` (used by T004 dispatch)."""

    question: str

    model_config = {"extra": "forbid"}


# Single-turn sub-agent dispatch (T004). Multi-turn iteration and sub-agent
# tool-use are out of scope; the trajectory captures one assistant turn so
# T005 can layer cache_control on top without re-shaping.
@mcp.tool()  # type: ignore[misc, unused-ignore]  # mcp SDK has no py.typed marker (1.27.0); revisit when SDK ships types
async def subagent_query(question: str) -> dict[str, Any]:
    """Dispatch ``question`` to a sub-agent and return its one-turn trajectory."""
    if not os.environ.get("MCP_API_KEY", ""):
        return error_envelope(
            category="permission",
            is_retryable=False,
            message="MCP_API_KEY is not set; subagent_query requires it at call time",
        )

    # The Anthropic SDK validates ``api_key`` at constructor time, before
    # VCR can intercept the network call — so pass it through explicitly
    # rather than relying on the SDK's env-var fallback.
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return error_envelope(
            category="permission",
            is_retryable=False,
            message=("ANTHROPIC_API_KEY is not set; subagent_query requires it at call time"),
        )

    client = Anthropic(api_key=api_key)
    # Mount the system prompt as a single cache-controlled block. Haiku 4.5
    # requires ~4,096 input tokens to cache (empirical, NOT the 2,048 figure
    # documented for earlier Haiku generations); ``SUBAGENT_SYSTEM_PROMPT``
    # is sized at ~4,345 tokens with safety margin. See
    # ``system_prompts.py`` module docstring for the verification trail.
    response = client.messages.create(
        model=MODEL_DEFAULT,
        max_tokens=MAX_TOKENS,
        system=[
            {
                "type": "text",
                "text": SUBAGENT_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": question}],
    )

    # Cache-usage fields ship in T005; surface conditionally so the schema
    # is stable across the two PRs.
    usage: dict[str, Any] = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }
    cache_creation = getattr(response.usage, "cache_creation_input_tokens", None)
    if cache_creation is not None:
        usage["cache_creation_input_tokens"] = cache_creation
    cache_read = getattr(response.usage, "cache_read_input_tokens", None)
    if cache_read is not None:
        usage["cache_read_input_tokens"] = cache_read

    trajectory = [
        {
            "role": "assistant",
            "stop_reason": response.stop_reason,
            "content": [block.model_dump() for block in response.content],
            "model": response.model,
            "usage": usage,
        }
    ]
    return success_envelope({"question": question, "trajectory": trajectory})


def main() -> None:
    """Stdio entry point. ``MCP_API_KEY`` is validated per-tool, not here."""
    mcp.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = [
    "SCHEMA_VERSION",
    "SERVER_NAME",
    "EchoInput",
    "SubagentQueryInput",
    "main",
    "mcp",
]
