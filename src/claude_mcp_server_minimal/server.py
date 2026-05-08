"""Minimal MCP server (stdio transport) — Artifact A, Day 2 (T001).

Exposes one tool, ``describe_schema``, which returns this server's
self-description: its schema version and the metadata of every tool it
advertises. The tool reflects on the registered MCP tools at call time
(via ``mcp.list_tools()``) rather than returning hardcoded metadata, so
adding a tool with ``@mcp.tool()`` automatically surfaces it here. The
exact wire shape is pinned by ``test_describe_schema_returns_exact_v1_shape``
so an SDK upgrade that quietly reshapes the dict breaks tests instead of
silently changing the published schema.

The tool takes no arguments; its ``input_schema`` carries the strict-mode
signal (``additionalProperties: False`` and ``required: []``) so a strict
MCP client can refuse calls with extra keys without first round-tripping
a validation error.
"""

from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP

SCHEMA_VERSION = "v1"
SERVER_NAME = "claude-mcp-server-minimal"

mcp = FastMCP(SERVER_NAME)


@mcp.tool()  # type: ignore[misc, unused-ignore]  # mcp SDK has no py.typed marker (1.27.0); revisit when SDK ships types
async def describe_schema() -> dict[str, Any]:
    """Return this server's schema version and the tools it advertises."""
    tools = await mcp.list_tools()
    return {
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


# FastMCP's auto-generated schema for a no-arg tool omits both keys; we
# inject them so `tools/list` shows the strictness explicitly. The dict
# on `Tool.parameters` is returned verbatim as `inputSchema`
# (fastmcp/server.py L323).
# TODO(mcp>=2): switch to a public Tool.parameters API if/when one is
# added. Tracking https://github.com/modelcontextprotocol/python-sdk
# for an official entry point. Until then, the explicit injection
# below is the only way to get additionalProperties:false to surface
# in tools/list output.
_describe_schema_tool = mcp._tool_manager._tools["describe_schema"]
_describe_schema_tool.parameters["additionalProperties"] = False
_describe_schema_tool.parameters["required"] = []


def main() -> None:
    """Stdio entry point. Reads MCP_API_KEY but does not validate it (T002)."""
    _ = os.environ.get("MCP_API_KEY")
    mcp.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = ["SCHEMA_VERSION", "SERVER_NAME", "main", "mcp"]
