# claude-mcp-server-minimal

[![CI](https://github.com/rkendev/claude-mcp-server-minimal/actions/workflows/ci.yml/badge.svg)](https://github.com/rkendev/claude-mcp-server-minimal/actions/workflows/ci.yml)

Minimal MCP server demonstrating Claude tool-use and MCP fundamentals —
`.mcp.json` env-var expansion, structured error handling, strict tool
input schemas. Built as Artifact A of a small-projects portfolio
exploring Claude's tool-use and MCP fundamentals.

> Repo bootstrapped from my own `roy-ai-template@v0.5.0` starter;
> MCP server logic is original.

## Quick start

```bash
# Copy .env.example and fill in any keys you want to exercise.
cp .env.example .env
$EDITOR .env

# Install dependencies (including dev extras — ruff, mypy, pytest, etc.).
uv sync --all-extras

# Install pre-commit's git hook so trailing-whitespace / EOF / line-ending
# auto-fixes fire at commit time. Skipping this means CI catches drift
# (auto-fix hooks aren't part of `make check`).
uv run pre-commit install

# Run the full quality gate: lint + type + security + unit + contract tests.
make check
```

Need offline Ollama backing for the inherited template scaffolding?
`./scripts/smoke.sh` brings up a digest-pinned Ollama container and
verifies it's healthy.

## Prompt caching

The `subagent_query` tool mounts a ~4,345-token system prompt with
`cache_control: ephemeral`. The first call writes the cache; subsequent
calls within the 5-minute TTL read from it, billed at 10% of the
normal input rate.

| Call      | input_tokens | cache_creation | cache_read | output_tokens | latency_ms |
|-----------|-------------:|---------------:|-----------:|--------------:|-----------:|
| 1 (cold)  |           13 |          4,338 |          0 |             6 |        930 |
| 2 (warm)  |           13 |              0 |      4,338 |             6 |        756 |

**Cache-hit ratio (call 2): 99.7%.** **Latency delta: 19% faster.**
**Token-cost reduction (call 2 input): 90%.**
Reproducer: `MCP_API_KEY=... ANTHROPIC_API_KEY=... uv run python scripts/measure_cache.py`.

Empirical note: Anthropic documents a 2,048-token cache minimum for
Haiku, but `claude-haiku-4-5-20251001` (`anthropic==0.100.0`)
silently disables caching below ~4,096 tokens — verified by probing
3,999-token (`cache_create=0`) vs 4,202-token (`cache_create=4,202`)
prompts. The system prompt is sized at ~4,345 tokens with safety margin;
see `src/claude_mcp_server_minimal/system_prompts.py`.

## MCP Server

`.mcp.json` at the repo root declares this project as an MCP server an
MCP-aware client (Claude Desktop, Claude Code, Cursor, …) can launch
over stdio:

```json
{
  "mcpServers": {
    "claude-mcp-server-minimal": {
      "command": "uv",
      "args": ["run", "python", "-m", "claude_mcp_server_minimal.server"],
      "env": { "MCP_API_KEY": "${MCP_API_KEY}" }
    }
  }
}
```

`${MCP_API_KEY}` is shell-style env-var expansion: the client substitutes
the value from its environment at launch time, so the secret never lives
in the JSON.

The server exposes two tools.

- **`describe_schema`** returns the schema version (`v1`), server name,
  and metadata of every advertised tool. Its input schema is strict:
  `additionalProperties: false` and `required: []`, so a strict client
  refuses calls with extra keys without a round-trip.
- **`echo_toolcall`** echoes its `input` back. `input` is published as
  an `anyOf` of either a bare string or a structured `EchoInput` object
  (`message: str`, optional `metadata: dict`) — a real-world MCP shape
  for a tool that accepts either a primitive or a structured payload.
  The tool validates `MCP_API_KEY` at call time; missing or empty
  surfaces a `permission` error envelope (the tool itself doesn't talk
  to any real API yet — that's Wk3+).

Every tool result is wrapped in a canonical envelope:
`{"success": True, "data": ...}` on success and
`{"success": False, "error": {"errorCategory": ..., "isRetryable": ..., "message": ...}}`
on failure. `errorCategory` is one of `transient` / `validation` /
`permission` / `business`; `isRetryable` is critical because retrying a
`validation` or `permission` failure burns budget on a request the
server will reject again. The MCP-protocol-level `isError` flag is
deliberately unused for tool-domain failures — it's reserved for true
transport / unhandled-exception faults.

Run the server directly (mostly useful for debugging — production clients
spawn it themselves):

```bash
uv run python -m claude_mcp_server_minimal.server
```

Verify the published config from anywhere:

```bash
curl https://raw.githubusercontent.com/rkendev/claude-mcp-server-minimal/main/.mcp.json | jq
```

## Inherited template scaffolding (background)

The repository was scaffolded from `roy-ai-template@v0.5.0`, which ships
a three-tier LLM adapter, a parametrized contract suite, and a Docker
healthcheck for offline Ollama. That code still lives in `src/` while
Artifact A is being built; whether to strip or integrate it is a Wk3
decision, not an Artifact A concern.

A shaped starting point, not a framework. Three layers with a strict
dependency rule (see [`ARCHITECTURE.md`](ARCHITECTURE.md)):

- **`domain/`** — types, invariants, errors. Pure Python; Pydantic is
  the only third-party import allowed.
- **`application/`** — ports (`LLMPort`, `ConfigPort`, `LoggerPort`)
  and the `FallbackModel` orchestrator. Depends on `domain/` only.
- **`infrastructure/`** — SDK adapters (Anthropic, OpenAI, Ollama) and
  the `pydantic-settings` loader. Only layer that imports vendor SDKs
  or reads the environment.
- **`main.py`** — the single composition root. `build_llm(settings)`
  wires a single adapter or a `FallbackModel` stack depending on
  `LLM_TIER`.

The 32-case contract suite in `tests/contract/` is the architectural
drift detector: any new adapter registered with
`tests/contract/conftest.py::LLM_ADAPTERS` inherits eight behavioural
assertions automatically — vendor-tagged failures
(`test_returns_response[anthropic]`) pinpoint which implementation
drifted, not which test broke.

### Example usage (template-era)

Three runnable scripts in `examples/` show the composition root from the
outside:

```bash
# Single adapter (Claude Haiku) — needs ANTHROPIC_API_KEY.
uv run python examples/01_single_adapter.py

# Fallback stack — uses whichever tier's credentials are present.
uv run python examples/02_fallback_demo.py

# Custom stack — secondary (OpenAI) only; demonstrates how to wire a
# subset of tiers manually.
uv run python examples/03_custom_stack.py
```

Each script prints the completion on stdout and a `[tier=... model=... ]`
metadata line on stderr so pipelines can consume `.text` cleanly.

Offline-only? Force the tertiary tier:

```bash
LLM_TIER=tertiary uv run python -m claude_mcp_server_minimal.main \
  "Say hi in one sentence."
```

No API key required; runs entirely against local Ollama.

## Make targets

Run `make help` for the full list. The core surface:

| Target | What it does |
| --- | --- |
| `check` | ruff + ruff-format + mypy + bandit + unit + contract tests. The default quality gate. |
| `fmt` | Auto-fix formatting with ruff. |
| `lint` | ruff lint only (no format pass). |
| `typecheck` | mypy strict on `src/` + `tests/`. |
| `security` | bandit -ll on `src/`. |
| `test` | pytest unit + contract, with coverage. |
| `integration` | pytest -m integration (requires docker-compose; skips if empty). |
| `smoke` | `./scripts/smoke.sh` — docker compose up + healthcheck for Ollama. |
| `build` | `uv build` — sdist + wheel. |
| `parity` | `scripts/check_version_parity.py` — asserts ruff/mypy/bandit pins match between `pyproject.toml` and `.pre-commit-config.yaml`. |

## Configuration

All runtime configuration lives in `.env` (loaded by
`infrastructure/settings.py`). Variables:

| Var | Default | Purpose |
| --- | --- | --- |
| `LLM_TIER` | `fallback` | `primary` / `secondary` / `tertiary` / `fallback`. |
| `ANTHROPIC_API_KEY` | (unset) | Enables primary tier. |
| `ANTHROPIC_MODEL` | `claude-haiku-4-5-20251001` | Override model. |
| `OPENAI_API_KEY` | (unset) | Enables secondary tier. |
| `OPENAI_MODEL` | `gpt-4o-mini` | Override model. |
| `OLLAMA_HOST` | `http://localhost:11434` | Where to find Ollama. |
| `OLLAMA_MODEL` | `llama3.2:3b` | Override model. |

Empty strings coerce to `None` so a `.env` placeholder doesn't silently
become a zero-length API key.

## Verification

Every architectural claim is paired with a runnable command in
[`VERIFICATION.md`](VERIFICATION.md). OT-2 (`LLMPort` contract
conformance), OT-3 (pre-commit parity), OT-4 (Docker healthcheck), OT-7
(offline Ollama), OT-8 (all three tiers end-to-end), OT-9 (wheel build),
and OT-10 (bandit clean) each take one line to re-verify.

## Architecture

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the Mermaid dependency
graph and the extension recipes (adding a tier, adding an unrelated
port). The short version: `domain/` knows nothing; `application/` knows
`domain/`; `infrastructure/` knows both; `main.py` knows all three and
is the only place allowed to wire them together.

## Changelog

See [`CHANGELOG.md`](CHANGELOG.md) — Keep-a-Changelog 1.1.0 format. The
template's own release notes (`v0.1.0`, `v0.2.0`) are trimmed from the
fork's changelog so `[Unreleased]` is what you edit.

## License

MIT — see [`LICENSE`](LICENSE).
