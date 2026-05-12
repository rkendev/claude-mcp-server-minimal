# Changelog

All notable changes to this project are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
`[Unreleased]` collects changes landing on `main` ahead of the next tagged
release; each tagged version carries its release date and a stable anchor.

> Scaffolded from [roy-ai-template@v0.5.0](https://github.com/rkendev/roy-ai-template/releases/tag/v0.5.0); MCP server logic is original. See README.md for the full scaffold disclosure.

## [Unreleased]

## [0.1.0] — 2026-05-08

First release of Artifact A (Minimal MCP Server) for a small-projects
portfolio exploring Claude's tool-use and MCP fundamentals. Demonstrates D2
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

[Unreleased]: https://github.com/rkendev/claude-mcp-server-minimal/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/rkendev/claude-mcp-server-minimal/releases/tag/v0.1.0
