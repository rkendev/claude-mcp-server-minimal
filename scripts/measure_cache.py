#!/usr/bin/env python3
"""Measure prompt-caching impact on ``subagent_query`` (A_T005).

Runs two back-to-back calls against the registered MCP tool, captures
token usage and wall-clock latency for each, and prints a markdown table
the README can paste verbatim. The first call is a cold cache (the
``SUBAGENT_SYSTEM_PROMPT`` is written), the second is a cache hit
(read from the ephemeral cache).

Usage:
    MCP_API_KEY=... ANTHROPIC_API_KEY=... uv run python scripts/measure_cache.py

Exit codes:
    0  measurement produced (table printed to stdout).
    1  required env var missing OR caching did not activate on call 2.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

from claude_mcp_server_minimal.server import subagent_query


def _require_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        sys.stderr.write(f"ERROR: ${name} is not set.\n")
        sys.exit(1)
    return value


async def _one_call(question: str) -> tuple[dict[str, int], float]:
    t0 = time.perf_counter()
    payload = await subagent_query(question=question)
    dt_ms = (time.perf_counter() - t0) * 1000
    if not payload["success"]:
        sys.stderr.write(f"ERROR: subagent_query returned an error envelope: {payload}\n")
        sys.exit(1)
    usage: dict[str, int] = payload["data"]["trajectory"][0]["usage"]
    return usage, dt_ms


async def _main() -> None:
    _require_env("MCP_API_KEY")
    _require_env("ANTHROPIC_API_KEY")

    usage1, ms1 = await _one_call("What is 2+2?")
    usage2, ms2 = await _one_call("What is 3+3?")

    cc1 = usage1.get("cache_creation_input_tokens", 0)
    cr1 = usage1.get("cache_read_input_tokens", 0)
    cc2 = usage2.get("cache_creation_input_tokens", 0)
    cr2 = usage2.get("cache_read_input_tokens", 0)

    if cr2 == 0:
        sys.stderr.write(
            "ERROR: call 2 did not hit cache (cache_read_input_tokens == 0). "
            "The system prompt may be below Haiku 4.5's ~4,096-token cache "
            "minimum, or the cache TTL elapsed between calls.\n"
        )
        sys.exit(1)

    input_total2 = cr2 + usage2["input_tokens"]
    cache_hit_ratio = cr2 / input_total2 if input_total2 else 0
    latency_delta = (ms1 - ms2) / ms1 if ms1 else 0
    # cache-read tokens are billed at 10% of normal input rate -> 90% discount
    # on the cached fraction of call 2's input.
    cost_reduction = (cr2 * 0.9) / input_total2 if input_total2 else 0

    print("| Call      | input_tokens | cache_creation | cache_read | output_tokens | latency_ms |")
    print("|-----------|-------------:|---------------:|-----------:|--------------:|-----------:|")
    print(
        f"| 1 (cold)  | {usage1['input_tokens']:>12,} | {cc1:>14,} | {cr1:>10,} "
        f"| {usage1['output_tokens']:>13,} | {ms1:>10,.0f} |"
    )
    print(
        f"| 2 (warm)  | {usage2['input_tokens']:>12,} | {cc2:>14,} | {cr2:>10,} "
        f"| {usage2['output_tokens']:>13,} | {ms2:>10,.0f} |"
    )
    print()
    print(f"Cache-hit ratio (call 2): {cache_hit_ratio:.1%}")
    print(f"Latency delta: {latency_delta:.0%} faster")
    print(
        f"Token-cost reduction (call 2 input): {cost_reduction:.0%} "
        "(cache_read priced at 10% of input)"
    )


if __name__ == "__main__":
    asyncio.run(_main())
