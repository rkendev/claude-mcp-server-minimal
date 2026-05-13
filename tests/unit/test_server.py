"""Tests for the MCP server entry point (T001 ``describe_schema`` + T002 ``echo_toolcall``).

These exercise the registered tools via the FastMCP instance directly
(no transport, no subprocess). The async helpers (``list_tools``,
``call_tool``) are the same surface a real MCP client would see over
stdio, so observing them here is sufficient evidence that each tool's
schema and return shape match the contract.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, cast

import pytest
from mcp.types import Tool as MCPTool

from claude_mcp_server_minimal.server import SCHEMA_VERSION, EchoInput, mcp


def _list_tools() -> list[MCPTool]:
    return asyncio.run(mcp.list_tools())


def _call_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    # FastMCP's call_tool returns (content_blocks, structured_output) at
    # runtime; the type stub on the public method is broader, so we narrow
    # locally. The structured-output branch is the dict we returned; we
    # also assert the JSON in the TextContent block agrees with it, so an
    # SDK change that diverges them surfaces here.
    raw = asyncio.run(mcp.call_tool(name, args))
    blocks, structured = cast(tuple[list[Any], dict[str, Any]], raw)
    text_payload: dict[str, Any] = json.loads(blocks[0].text)
    assert text_payload == structured
    return structured


def _call_describe_schema() -> dict[str, Any]:
    return _call_tool("describe_schema", {})


# ---------------------------------------------------------------------------
# describe_schema (T001) — updated to assert the new envelope shape.
# ---------------------------------------------------------------------------


def test_describe_schema_returns_schema_version_v1() -> None:
    payload = _call_describe_schema()
    assert payload["success"] is True
    assert payload["data"]["schema_version"] == "v1"
    assert SCHEMA_VERSION == "v1"


def test_describe_schema_advertises_itself() -> None:
    payload = _call_describe_schema()
    names = [t["name"] for t in payload["data"]["tools"]]
    assert "describe_schema" in names
    assert "echo_toolcall" in names
    assert "subagent_query" in names


def test_describe_schema_input_schema_is_strict() -> None:
    tool = next(t for t in _list_tools() if t.name == "describe_schema")
    assert tool.inputSchema["additionalProperties"] is False
    assert tool.inputSchema["required"] == []


def test_describe_schema_returns_exact_v1_shape() -> None:
    # Pin the entire wire shape. The implementation introspects
    # `mcp.list_tools()` at call time, so an SDK change that reshapes
    # the dict (renames keys, reorders fields, drops a property) breaks
    # this test instead of silently changing the published schema.
    # T002 wrapped the payload in the canonical success envelope and
    # added the `echo_toolcall` entry; the dict branch of `echo_toolcall`'s
    # `anyOf` is sourced from `EchoInput.model_json_schema()` so trivial
    # Pydantic-side reorderings stay green.
    expected = {
        "success": True,
        "data": {
            "schema_version": "v1",
            "server": "claude-mcp-server-minimal",
            "tools": [
                {
                    "name": "describe_schema",
                    "description": (
                        "Return this server's schema version and the tools it advertises."
                    ),
                    "input_schema": {
                        "properties": {},
                        "title": "describe_schemaArguments",
                        "type": "object",
                        "additionalProperties": False,
                        "required": [],
                    },
                },
                {
                    "name": "echo_toolcall",
                    "description": (
                        "Echo ``input`` back, wrapped in the canonical success envelope."
                    ),
                    "input_schema": {
                        "properties": {
                            "input": {
                                "anyOf": [
                                    {"type": "string"},
                                    EchoInput.model_json_schema(),
                                ],
                                "title": "Input",
                            }
                        },
                        "required": ["input"],
                        "title": "echo_toolcallArguments",
                        "type": "object",
                    },
                },
                {
                    "name": "subagent_query",
                    "description": (
                        "Dispatch ``question`` to a sub-agent and return "
                        "its one-turn trajectory."
                    ),
                    "input_schema": {
                        "properties": {
                            "question": {"title": "Question", "type": "string"},
                        },
                        "required": ["question"],
                        "title": "subagent_queryArguments",
                        "type": "object",
                    },
                },
            ],
        },
    }
    assert _call_describe_schema() == expected


# ---------------------------------------------------------------------------
# echo_toolcall (T002).
# ---------------------------------------------------------------------------


def test_echo_toolcall_string_input_returns_success_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_API_KEY", "present")
    payload = _call_tool("echo_toolcall", {"input": "hello"})
    assert payload["success"] is True
    data = payload["data"]
    assert data["echoed"] == "hello"
    assert isinstance(data["received_at"], str) and data["received_at"]
    # Parseable as ISO-8601 (the implementation uses datetime.isoformat()).
    datetime.fromisoformat(data["received_at"])


def test_echo_toolcall_object_input_with_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_API_KEY", "present")
    payload = _call_tool(
        "echo_toolcall",
        {"input": {"message": "hi", "metadata": {"trace_id": "abc"}}},
    )
    assert payload["success"] is True
    data = payload["data"]
    assert data["echoed"] == "hi"
    assert data["metadata"] == {"trace_id": "abc"}
    datetime.fromisoformat(data["received_at"])


def test_echo_toolcall_object_input_missing_message_returns_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_API_KEY", "present")
    payload = _call_tool("echo_toolcall", {"input": {"foo": "bar"}})
    assert payload["success"] is False
    err = payload["error"]
    assert err["errorCategory"] == "validation"
    assert err["isRetryable"] is False
    assert err["message"]
    assert err["details"] is not None
    assert "errors" in err["details"]


def test_echo_toolcall_empty_api_key_returns_permission_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_API_KEY", "")
    payload = _call_tool("echo_toolcall", {"input": "hello"})
    assert payload["success"] is False
    err = payload["error"]
    assert err["errorCategory"] == "permission"
    assert err["isRetryable"] is False
    assert "MCP_API_KEY" in err["message"]


def test_echo_toolcall_input_schema_has_anyOf() -> None:
    # This is the explicit code-level assertion the T002 prompt requires:
    # FastMCP must publish an `anyOf` for the `input` parameter, and the
    # object branch must reflect EchoInput's strict contract
    # (additionalProperties:false + required:["message"]). A schema-
    # generation regression — in either FastMCP or our private-API
    # override — surfaces here, not in production.
    tool = next(t for t in _list_tools() if t.name == "echo_toolcall")
    input_prop = tool.inputSchema["properties"]["input"]
    assert "anyOf" in input_prop, "echo_toolcall must publish an anyOf for `input`"
    branches = input_prop["anyOf"]
    assert len(branches) == 2
    types = {b.get("type") for b in branches}
    assert "string" in types
    object_branch = next(b for b in branches if b.get("type") == "object")
    assert object_branch["additionalProperties"] is False
    assert object_branch["required"] == ["message"]


# ---------------------------------------------------------------------------
# subagent_query (T003) — stub: empty trajectory, dispatch lands in T004.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def vcr_config() -> dict[str, Any]:
    """Redact auth headers from any VCR cassette this module records."""
    return {
        "filter_headers": [
            ("authorization", "REDACTED"),
            ("x-api-key", "REDACTED"),
        ],
    }


@pytest.mark.vcr
def test_subagent_query_real_dispatch_returns_trajectory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T004: real second-Claude call returns a one-turn trajectory.

    Cassette-backed: first run with a real ``ANTHROPIC_API_KEY`` records;
    subsequent runs replay offline with the dummy key. The SDK validates
    ``api_key`` at constructor time before VCR intercepts, so the test
    sets a non-empty placeholder value rather than relying on the
    cassette to short-circuit the auth check.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setenv("MCP_API_KEY", "test-key")
    payload = _call_tool("subagent_query", {"question": "What is 2+2?"})

    assert payload["success"] is True
    data = payload["data"]
    assert data["question"] == "What is 2+2?"
    assert len(data["trajectory"]) == 1
    turn = data["trajectory"][0]
    assert turn["role"] == "assistant"
    assert turn["stop_reason"] == "end_turn"
    assert turn["model"].startswith("claude-haiku-4-5")
    assert "input_tokens" in turn["usage"]
    assert "output_tokens" in turn["usage"]
    assert isinstance(turn["content"], list) and turn["content"]


def test_subagent_query_missing_anthropic_api_key_returns_permission_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing ANTHROPIC_API_KEY surfaces as the canonical permission envelope."""
    monkeypatch.setenv("MCP_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    payload = _call_tool("subagent_query", {"question": "ping"})

    assert payload["success"] is False
    err = payload["error"]
    assert err["errorCategory"] == "permission"
    assert err["isRetryable"] is False
    assert "ANTHROPIC_API_KEY" in err["message"]
