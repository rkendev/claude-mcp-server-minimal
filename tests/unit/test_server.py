"""Tests for the MCP server entry point (T001 — `describe_schema`).

These exercise the registered tool via the FastMCP instance directly
(no transport, no subprocess). The async helpers (`list_tools`,
`call_tool`) are the same surface a real MCP client would see over
stdio, so observing them here is sufficient evidence that the tool's
schema and return shape match the contract.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, cast

from mcp.types import Tool as MCPTool

from claude_mcp_server_minimal.server import SCHEMA_VERSION, mcp


def _list_tools() -> list[MCPTool]:
    return asyncio.run(mcp.list_tools())


def _call_describe_schema() -> dict[str, Any]:
    # FastMCP's call_tool returns (content_blocks, structured_output) at
    # runtime; the type stub on the public method is broader, so we narrow
    # locally. The structured-output branch is the dict we returned; we
    # also assert the JSON in the TextContent block agrees with it, so an
    # SDK change that diverges them surfaces here.
    raw = asyncio.run(mcp.call_tool("describe_schema", {}))
    blocks, structured = cast(tuple[list[Any], dict[str, Any]], raw)
    text_payload: dict[str, Any] = json.loads(blocks[0].text)
    assert text_payload == structured
    return structured


def test_describe_schema_returns_schema_version_v1() -> None:
    payload = _call_describe_schema()
    assert payload["schema_version"] == "v1"
    assert SCHEMA_VERSION == "v1"


def test_describe_schema_advertises_itself() -> None:
    payload = _call_describe_schema()
    names = [t["name"] for t in payload["tools"]]
    assert "describe_schema" in names


def test_describe_schema_input_schema_is_strict() -> None:
    tool = next(t for t in _list_tools() if t.name == "describe_schema")
    assert tool.inputSchema["additionalProperties"] is False
    assert tool.inputSchema["required"] == []


def test_describe_schema_returns_exact_v1_shape() -> None:
    # Pin the entire wire shape. The implementation introspects
    # `mcp.list_tools()` at call time, so an SDK change that reshapes
    # the dict (renames keys, reorders fields, drops a property) breaks
    # this test instead of silently changing the published schema.
    # When T002 lands `echo_toolcall`, this expected literal must grow
    # by one entry in `tools` — that's the point.
    expected = {
        "schema_version": "v1",
        "server": "claude-mcp-server-minimal",
        "tools": [
            {
                "name": "describe_schema",
                "description": "Return this server's schema version and the tools it advertises.",
                "input_schema": {
                    "properties": {},
                    "title": "describe_schemaArguments",
                    "type": "object",
                    "additionalProperties": False,
                    "required": [],
                },
            }
        ],
    }
    assert _call_describe_schema() == expected
