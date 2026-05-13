# Changelog

All notable changes to this project are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
`[Unreleased]` collects changes landing on `main` ahead of the next tagged
release; each tagged version carries its release date and a stable anchor.

> Scaffolded from [roy-ai-template@v0.5.0](https://github.com/rkendev/roy-ai-template/releases/tag/v0.5.0); MCP server logic is original. See README.md for the full scaffold disclosure.

## [Unreleased]

## [0.2.0] — 2026-05-13

### Added

- **Prompt caching on `subagent_query`** (A_T005) — mounts a ~4,345-token
  `SUBAGENT_SYSTEM_PROMPT` on every call with `cache_control: ephemeral`.
  First call writes the cache, subsequent calls within the 5-minute TTL
  read from it. `usage` in the trajectory surfaces `cache_creation_input_tokens`
  / `cache_read_input_tokens` (T004 already future-proofed the schema via
  `getattr`). New `scripts/measure_cache.py` runs two back-to-back calls
  and prints a markdown table of input/cache tokens, output tokens, and
  latency for each. README first 200 words now include the measured cache-hit
  ratio, latency delta, and token-cost reduction.
- **Empirical Haiku 4.5 cache minimum: ~4,096 tokens.** The Anthropic docs
  cite 2,048 tokens for Haiku; empirical probing against
  `claude-haiku-4-5-20251001` (`anthropic==0.100.0`) shows a 3,999-token
  prompt does NOT cache while a 4,202-token prompt does. The system prompt
  is sized at ~4,345 tokens with safety margin. See
  `src/claude_mcp_server_minimal/system_prompts.py` module docstring.
- **`subagent_query` real dispatch** (A_T004) — wires `subagent_query` to a
  single Anthropic `messages.create` call against `claude-haiku-4-5` and
  captures the response as a one-turn trajectory (`role`, `stop_reason`,
  `content`, `model`, `usage`). `usage` conditionally surfaces
  `cache_creation_input_tokens` / `cache_read_input_tokens` via `getattr`
  so T005 can populate them without re-shaping the schema. Cassette-backed
  test (`tests/unit/cassettes/test_server/`) replays offline; auth headers
  redacted via the module-scoped `vcr_config` fixture.
- **`subagent_query` MCP tool stub** (A_T003) — registers the tool with a
  `{question: str}` input schema and returns `{"question": ..., "trajectory": []}`
  via the canonical success envelope. Dispatch logic lands in T004; this
  commit proves the tool surface and CI gate.

## [0.1.0] — 2026-05-08

First release of Artifact A (Minimal MCP Server) for a small-projects
portfolio exploring Claude's tool-use and MCP fundamentals. Demonstrates these
fundamentals: `.mcp.json` env-var expansion, strict tool input schemas,
and the canonical flat error envelope (`errorCategory` / `isRetryable` / `message`).

### Added

- **`describe_schema` MCP tool** (T001 + T001b) — returns the server's
  tool catalogue with strict input schemas (`additionalProperties: false`).
  Audit findings from T001b addressed: 3 major + 3 minor.
- **`echo_toolcall` MCP tool** (T002) — accepts an `anyOf` parameter shape
  (string OR `EchoInput` object); validates `MCP_API_KEY` at call time and
  raises the canonical flat error envelope (`errorCategory` /
  `isRetryable` / `message`) on auth failure.
- **`.mcp.json`** with `${MCP_API_KEY}` env-var expansion — the standard
  Claude Code wiring for connecting an MCP server.
- **README.md** rewritten for hiring legibility — includes the Artifact A
  framing, scaffold disclosure (`roy-ai-template@v0.5.0`, MCP server logic
  original), and the trimmed-template-changelog note.
- 228 unit + contract tests passing; CI + Smoke green on every push to `main`.

### Inherited (unchanged)

The three-tier LLM adapter scaffolding from the template
(`src/claude_mcp_server_minimal/{domain,application,infrastructure}/`) is
preserved unchanged. Whether to strip it or integrate it into the MCP
surface is a Wk3 polish decision, not a v0.1.0 blocker.

[Unreleased]: https://github.com/rkendev/claude-mcp-server-minimal/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/rkendev/claude-mcp-server-minimal/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/rkendev/claude-mcp-server-minimal/releases/tag/v0.1.0
