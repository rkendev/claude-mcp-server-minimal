# claude-mcp-server-minimal: a 60-minute walkthrough

*Author: Roy. Audience: tech leads and senior engineers screening Senior AI Engineer candidates. Time budget: 60 minutes presented, 15 minutes if you'd rather just read.*

---

## Why this doc exists

I built `claude-mcp-server-minimal` to demonstrate three things in a single repo small enough that a reviewer can finish reading it in one sitting.

The first is a real MCP server you can mount via `claude mcp add`. Not a tutorial fork, an actual stdio-protocol server with a canonical D2 error envelope. The second is a logged sub-agent dispatch trajectory, the artifact a multi-step agent system needs at the bottom of its stack. The third is a measurable prompt-caching demo: a 99.7% cache-hit ratio with the cost and latency table in the README's first 200 words, and an empirical finding that Anthropic's documented Haiku threshold is silently 4× too low for the current Haiku 4.5 model.

The repo is at [github.com/rkendev/claude-mcp-server-minimal](https://github.com/rkendev/claude-mcp-server-minimal). The current release is [v0.2.0](https://github.com/rkendev/claude-mcp-server-minimal/releases/tag/v0.2.0). The CI badge is green. 231 tests pass offline against committed VCR cassettes; no `ANTHROPIC_API_KEY` is required to run the suite.

This walkthrough is what I'd say if you handed me a screen-share and asked me to walk you through a favourite project.

---

## Section 1: Intro and motivation (≈5 min)

I wanted one repo small enough to read in one sitting, that proves three things to a hiring manager during a 30-second skim: a working MCP server I can ship as a dependency, a sub-agent dispatch with a logged trajectory, and a measurable prompt-caching demo with the numbers in the README's first 200 words. Not four tutorial repos with the same scaffold renamed three times.

The thesis is that a minimal MCP server is the right shape for the bottom of an agent stack. Supervisors, routers, sub-agents, caching, observability all resolve into messages and tool calls flowing through some protocol surface. If that surface is wrong, everything above it is wrong. If it's right, other projects can mount it as a real dependency.

The repo refuses to be a framework. Three tools, no fewer, no more. It refuses to survey the MCP spec or the Claude API; it ships one of each primitive end-to-end with tests. Every tool is registered, schema-pinned, error-enveloped, and tested through the canonical access path. If a tool couldn't survive a real Claude Code session, it isn't in this repo.

Every API claim has a probe behind it. The prompt-caching demo started because I followed the published threshold and the cache silently didn't activate, so the README quotes only numbers I measured myself. Strict input schemas with `additionalProperties: false`. Strict output envelopes. A pinned `describe_schema` test that breaks if the SDK quietly reshapes the published surface. Every test that touches the live API has a VCR cassette next to it, and `make check` runs the full suite in 5 seconds without a network.

The last point matters most. The test suite is what a hiring manager runs in 60 seconds before deciding whether to spend an hour reading code.

---

## Section 2: Architecture overview (≈10 min)

The repo has two layers of architecture: an inherited template scaffold, and the MCP server I wrote on top of it. Both are visible. Both are disclosed.

### The inherited scaffold

The repo was bootstrapped from my own `roy-ai-template@v0.5.0` starter. The template provides a ports-and-adapters layout I've validated across several other projects:

```
src/claude_mcp_server_minimal/
├── domain/           # types, errors, invariants. Pure Python plus Pydantic.
├── application/      # ports (LLMPort, ConfigPort, LoggerPort) plus Fallback orchestrator.
├── infrastructure/   # SDK adapters (Anthropic, OpenAI, Ollama) plus pydantic-settings.
└── main.py           # the single composition root.
```

The dependency rule is strict. `domain/` knows nothing. `application/` knows `domain/` only. `infrastructure/` knows both. `main.py` is the only place that wires all three together. A 32-case contract suite parametrised over every registered `LLMPort` implementation catches architectural drift; if a new adapter does not satisfy the contract, the vendor-tagged test name (`test_returns_response[anthropic]`) names exactly which adapter broke.

I'm disclosing the scaffold because hiring managers should be able to tell at a glance what's original. The `CHANGELOG.md` opens with a blockquote: *"Scaffolded from roy-ai-template@v0.5.0; MCP server logic is original."* The first commits in the inherited tree are visible. The original work, what I'd want you to read, is the MCP server surface, not the LLM-tier scaffolding.

### The MCP server I built

Three files contain everything original to this repo's thesis:

| File | LOC | Purpose |
|---|---:|---|
| `src/claude_mcp_server_minimal/server.py` | ~140 | FastMCP server registration; three tool decorators; lazy Anthropic client |
| `src/claude_mcp_server_minimal/server_errors.py` | ~60 | Canonical D2 error envelope (`category` / `is_retryable` / `message`) with camelCase wire mapping |
| `src/claude_mcp_server_minimal/system_prompts.py` | ~380 | `SUBAGENT_SYSTEM_PROMPT` constant plus a verification trail in the module docstring |

`.mcp.json` at the repo root declares the server so a Claude-aware client can launch it over stdio:

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

`${MCP_API_KEY}` is shell-style env-var expansion. The secret never lives in the JSON; the client substitutes from its environment at launch time. That pattern is the canonical CCA-F D2 envelope discipline applied to configuration: secrets at the boundary, not in the artifact.

### Why three tools and not five

Each tool exists because it pins a specific design constraint. `describe_schema` covers the case of a parameter-less tool with a strict input schema. `echo_toolcall` covers an `anyOf` input shape (string or structured object) plus per-call auth validation. `subagent_query` covers real sub-agent dispatch with logged trajectories and prompt caching. A fetch tool, a summarise tool, or a sub-agent router would not pin a new constraint. The repo is the smallest set of demonstrations that covers the space I want it to cover. Smallest is the operative word.

---

## Section 3: Tools tour (≈15 min)

### `describe_schema`: self-description with a strict-pin test

The first tool reflects on the server's own registered tools and returns its schema version plus a list of tool metadata.

```python
@mcp.tool()
async def describe_schema() -> dict[str, Any]:
    """Return this server's schema version and the tools it advertises."""
    tools = await mcp.list_tools()
    return success_envelope({
        "schema_version": SCHEMA_VERSION,
        "server": SERVER_NAME,
        "tools": [
            {"name": t.name, "description": t.description, "input_schema": t.inputSchema}
            for t in tools
        ],
    })
```

The tool reflects on the registered tools at call time (`mcp.list_tools()`) rather than returning a hardcoded list. Adding a new `@mcp.tool()`-decorated function automatically surfaces it here without code changes. The input schema has `additionalProperties: false` and `required: []`, so a strict client refuses calls with extra keys without a round-trip, which is useful when an LLM hallucinates a parameter that doesn't exist.

The most useful thing about this tool is the pinned test that travels with it. `test_describe_schema_returns_exact_v1_shape` asserts the exact wire output. If an SDK upgrade quietly reshapes the published surface, this test breaks rather than silently changing what consumers see. The pin has caught two SDK shape drifts so far, including the addition of FastMCP-synthesised input-schema titles like `subagent_queryArguments`.

### `echo_toolcall`: `anyOf` input plus auth-at-call-time

The second tool demonstrates a real-world MCP input shape: an `anyOf` of either a bare string or a structured object with optional metadata.

```python
class EchoInput(BaseModel):
    message: str
    metadata: dict[str, Any] | None = None
    model_config = {"extra": "forbid"}

@mcp.tool()
async def echo_toolcall(input: str | EchoInput) -> dict[str, Any]:
    if not os.environ.get("MCP_API_KEY", ""):
        return error_envelope(
            category="permission",
            is_retryable=False,
            message="MCP_API_KEY required at call time",
        )
    # ... echoes input back through the canonical envelope
```

`model_config = {"extra": "forbid"}` makes Pydantic reject unknown keys, the same defence-in-depth as the strict input schema on `describe_schema`. `MCP_API_KEY` is validated at call time rather than at server launch. Launch-time auth would mean a misconfigured client never receives the canonical permission-error envelope, which is the wire shape consumers should see when they call without credentials.

The error envelope's snake_case Python API (`category=`, `is_retryable=`) maps to camelCase wire keys (`errorCategory`, `isRetryable`) inside `server_errors.py`. Python conventions stay Pythonic; wire formats stay protocol-compliant; the conversion lives in exactly one place.

### `subagent_query`: real sub-agent dispatch with logged trajectory

The third tool is the headline. It makes a real call to a sub-agent and returns a structured trajectory.

```python
@mcp.tool()
async def subagent_query(question: str) -> dict[str, Any]:
    """Dispatch question to a sub-agent and return its one-turn trajectory."""
    if not os.environ.get("MCP_API_KEY", ""):
        return error_envelope(category="permission", is_retryable=False,
                              message="MCP_API_KEY required")
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return error_envelope(category="permission", is_retryable=False,
                              message="ANTHROPIC_API_KEY required")

    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=MODEL_DEFAULT,
        max_tokens=MAX_TOKENS,
        system=[{"type": "text",
                 "text": SUBAGENT_SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": question}],
    )

    usage = {"input_tokens": response.usage.input_tokens,
             "output_tokens": response.usage.output_tokens}
    cache_creation = getattr(response.usage, "cache_creation_input_tokens", None)
    if cache_creation is not None:
        usage["cache_creation_input_tokens"] = cache_creation
    cache_read = getattr(response.usage, "cache_read_input_tokens", None)
    if cache_read is not None:
        usage["cache_read_input_tokens"] = cache_read

    trajectory = [{
        "role": "assistant",
        "stop_reason": response.stop_reason,
        "content": [block.model_dump() for block in response.content],
        "model": response.model,
        "usage": usage,
    }]
    return success_envelope({"question": question, "trajectory": trajectory})
```

The whole body is roughly 30 lines.

The Anthropic client is constructed inside the function, not at module load. The SDK validates `api_key` at constructor time, before any VCR cassette can intercept; constructing at import would force the test suite to set a non-empty key in the environment even for offline replay. Lazy construction makes a missing key surface as the canonical permission envelope, in the same shape as a missing `MCP_API_KEY`.

The `usage` block uses `getattr` to surface cache fields conditionally. When this code shipped in T004 (before T005 added caching), the cache fields were absent and the dict simply did not include them. T005 added the system block with `cache_control` and the fields started populating, with no schema change. The trajectory contract was forward-compatible by construction.

The trajectory itself is a list, not a single dict, even though this tool currently returns one turn. Multi-turn dispatch is the next iteration: tool_use blocks, tool-result turns, all recorded in the same list. Consumers that iterate `data["trajectory"]` today keep iterating tomorrow.

---

## Section 4: Prompt caching deep-dive (≈15 min)

### The setup

`SUBAGENT_SYSTEM_PROMPT` in `system_prompts.py` is roughly 4,345 tokens of behavioural guidance for the sub-agent: how to answer with rigour, how to ask clarifying questions, how to handle ambiguity, how to format. A serious sub-agent persona would carry a prompt this size. It's mounted on every `subagent_query` call with `cache_control: {"type": "ephemeral"}`.

Per Anthropic's published documentation, a prompt this size should write the cache on the first call and read from it on subsequent calls within the 5-minute TTL.

### What actually happens

```
| Call     | input_tokens | cache_creation | cache_read | output_tokens | latency_ms |
|----------|-------------:|---------------:|-----------:|--------------:|-----------:|
| 1 (cold) |           13 |          4,338 |          0 |             6 |        930 |
| 2 (warm) |           13 |              0 |      4,338 |             6 |        756 |
```

Cache-hit ratio on call 2: 99.7%. Latency delta: 19% faster. Token-cost reduction on input: 90%, since cache-read is priced at 10% of normal input.

The table is reproducible with one command:

```bash
MCP_API_KEY=... ANTHROPIC_API_KEY=... uv run python scripts/measure_cache.py
```

The script makes two back-to-back calls with the same system prompt but different user questions, captures latency with `time.perf_counter`, and emits the markdown table above. The numbers in the table are the actual measured values, not a hypothetical.

### Why the latency delta is only 19%

A reasonable question: 90% input-cost reduction but only 19% latency improvement seems off. The answer is in the cost shape of a Claude call. For short outputs (here, 6 output tokens), wall-clock time is dominated by output generation, not input processing. Cache savings show up cleanly in the input dimension, the cost dimension, but not as dramatically in latency.

Where this matters more: long-context workloads where input dominates. A real RAG pipeline with 4K of cached system prompt plus 10K of retrieved context per call would see the latency benefit far more than this minimal demo does. The 99.7% / 90% / 19% triple is honest about the regime where the demo lives.

### The empirical finding

When I first wired `cache_control` exactly as the Anthropic docs specify, against a 3,000-token system prompt, the cache silently didn't activate. `cache_creation_input_tokens` came back as `0`. No error, no warning, full input billed at normal rate.

I extended the prompt. 3,500 tokens, still nothing. 3,999 tokens, still nothing. 4,202 tokens, cached at 4,202 tokens.

The probe trail:

```
target=3000  input_tokens=3005   cache_create=0    -> NOT CACHED
target=3500  input_tokens=3509   cache_create=0    -> NOT CACHED
target=4000  input_tokens=3999   cache_create=0    -> NOT CACHED
target=4200  input_tokens=7      cache_create=4202 -> CACHED
```

The empirical minimum for `claude-haiku-4-5-20251001` is approximately 4,096 tokens. The Anthropic course teaches 1,024. The public docs cite 2,048 for the Haiku family specifically. Both numbers are stale for Haiku 4.5, though they remain correct for `claude-sonnet-4-6`: a 2,399-token prompt cached cleanly on Sonnet during the same probe.

The system prompt is sized at roughly 4,345 tokens with safety margin, and the module docstring captures the verification trail so anyone reading the file knows why it's that size. Probing before deploying is the entire point. Cache documentation drifts with model versions, and the only honest cite is the measurement.

### The `cache_control` placement

The cache breakpoint is on the system block, not on the message content. The access pattern drives the choice: the same sub-agent persona dispatches every question, so the system prompt is what's shared across calls. User questions vary; caching the user content would invalidate the cache on every call. Caching the system block survives across calls and only invalidates when the persona itself changes.

When a future iteration of this tool adds tool definitions (for sub-agents that need to dispatch their own tools), there will be a second cache breakpoint on the tool list. The Anthropic API supports multiple breakpoints in a single request. That's a v0.3.0 conversation, not a v0.2.0 concern.

---

## Section 5: Testing posture (≈10 min)

231 tests pass. The full suite runs in under 5 seconds with no `ANTHROPIC_API_KEY` in the environment.

### What the test pyramid looks like

```
tests/
├── contract/         # 32 vendor-tagged port contracts (parametrised LLMPort)
├── integration/      # placeholder (no Docker-required tests yet)
├── live/             # placeholder (real-API tests, gated)
└── unit/
    ├── application/  # fallback and ports
    ├── domain/       # type and error invariants
    ├── infrastructure/ # adapter-level tests with mocks
    ├── test_main.py
    └── test_server.py    # MCP server surface (test_subagent_query_* family)
```

The MCP-specific tests live in `tests/unit/test_server.py`. There are roughly 12 of them, covering the three tools' happy paths, error envelopes, schema pins, and the cache demonstration.

### The `_call_tool` helper

Every MCP tool test goes through the same helper, defined at the top of `test_server.py`:

```python
def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Invoke an MCP tool through the canonical list_tools + call_tool path."""
    # ... uses mcp.list_tools() and mcp.call_tool() to round-trip through FastMCP
    ...
```

`@mcp.tool()` in `mcp==1.27.0` returns the original callable unchanged. There's no `.fn` accessor, no decorator-attached attribute, no obvious way to reach the function body from a test. The canonical access path is the public `mcp.call_tool()` API, which is what real clients use. The helper standardises that path so tests don't accidentally test through a private channel that doesn't match what consumers see.

### The VCR cassette pattern

Two tests in `test_server.py` touch the live Anthropic API: the real-dispatch test (T004) and the caching test (T005). Both use pytest-recording to commit a YAML cassette next to the test file:

```
tests/unit/cassettes/test_server/
├── test_subagent_query_caches_system_prompt.yaml
└── test_subagent_query_real_dispatch_returns_trajectory.yaml
```

A `vcr_config` fixture redacts `authorization` and `x-api-key` headers before writing the cassette:

```python
@pytest.fixture(scope="module")
def vcr_config() -> dict[str, Any]:
    return {
        "filter_headers": [
            ("authorization", "REDACTED"),
            ("x-api-key", "REDACTED"),
        ],
    }
```

Combined with `monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")` in the test bodies, the cassettes replay cleanly without any secret in either the file or the test environment. `make check` runs the whole suite offline. The README claims "no `ANTHROPIC_API_KEY` needed for CI" and that claim is empirically true; verified by running `env -u ANTHROPIC_API_KEY make check`.

### The recording footgun

There's a non-obvious failure mode in this setup that bit me during T004. The SDK accepts `Anthropic(api_key="dummy")` at constructor time. If you're recording a fresh cassette, the dummy key gets sent to the real API, which returns 401 Unauthorized, and vcrpy faithfully caches the 401 as a "valid" cassette. Subsequent replays pass (they replay the 401), but the test assertions on response shape fail downstream in confusing ways.

The recording workflow that avoids this:

1. Comment out the `monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")` line before recording.
2. Confirm `$ANTHROPIC_API_KEY` is exported with a real key.
3. Delete any prior bad cassette.
4. Run with `--record-mode=once`.
5. Grep the saved cassette for leaked secrets (`grep -iE "sk-ant|Bearer\s+sk"`); should return zero matches because `filter_headers` redacts the saved file.
6. Restore the monkeypatch.
7. Verify offline replay: `env -u ANTHROPIC_API_KEY make check`.

The cache test has an additional wrinkle: cache-demo cassettes need to capture a cold-to-warm transition. If a prior live call in the same session warmed the cache, the recording shows `cache_creation_input_tokens=0` on what should be the cold call and the assertion fails. The recipe includes a 5-minute TTL wait before recording. None of this is reflected in the cassette file itself; it's process discipline around the cassette.

### The quality gate

`make check` runs the canonical pre-push gate:

```
$ make check
ruff..................................................................................................Passed
ruff-format...........................................................................................Passed
mypy..................................................................................................Passed
bandit................................................................................................Passed
pin parity (ruff/mypy/bandit across pyproject.toml <-> .pre-commit-config.yaml).......................Passed
============================= 231 passed in 4.51s ==============================
```

The `pin-parity` check is worth pointing out separately. It asserts that the ruff, mypy, and bandit version pins in `pyproject.toml` match the corresponding pre-commit hook versions. Without this, the local quality gate (`make check`) and CI's pre-commit (`pre-commit run --all-files`) can drift apart: same tool, different versions, surprises in CI. The parity check pins them together.

One caveat from T005: `make check` lints `src` and `tests` only; CI's pre-commit covers the entire tree. If a task adds files outside those two directories (like `scripts/measure_cache.py`), `make check` is necessary but not sufficient as a pre-push gate. The discipline is to run `uv run pre-commit run --all-files` locally before push when cross-tree files change.

---

## Section 6: Forward work (≈5 min)

The most useful thing I can tell a reviewer is what is NOT done, because that is the conversation about engineering judgment rather than which tickets I closed.

The next release will add multi-turn dispatch. Today `subagent_query` makes one call and returns one turn. A real sub-agent agent needs `tool_use` to `tool_result` round-trip handling inside the loop. The trajectory schema is already shape-compatible; the body needs to grow. The same release will add an MCP Resource for the sub-agent's tool catalog, so clients can introspect what the sub-agent can do without firing a call. That's useful for orchestration layers above this one. A second `cache_control` breakpoint on the tool list arrives at the same time, since tool definitions become the second cache target.

A release further out wires this server into a downstream nl2sql project as a real `.mcp.json` dependency. That turns C2 from a standalone demo into installable infrastructure. The plan is to expose the SQL tool surface through this server, which means a hiring manager can `claude mcp add` the server and immediately query against the nl2sql backend. That's a Wk5 task on the project plan, intentionally after this walkthrough exists.

A cache-invalidation demonstration is on the same shelf but lower priority. The Anthropic course teaches that changing any content before a breakpoint invalidates the cache. A 30-minute script demonstrating this would round out the caching story. It is useful for documentation; it is not load-bearing for v0.2.0.

What I would never add to this repo: a web UI, a custom tool dispatcher, a framework wrapper. The repo's discipline is to stay small. There are framework-shaped repos for that work. Five tools instead of three is padding. Six tools is worse padding. The Medium post that goes alongside this release leans into the empirical finding (4,096 vs 1,024 token threshold); the post that goes alongside v0.3.0 will lean into multi-turn dispatch. Each release earns one piece of public writing, and no more.

---

## Appendix A: file map cheat sheet

```
claude-mcp-server-minimal/
├── .mcp.json                                    # stdio server declaration
├── README.md                                    # quant table in first 200 words
├── CHANGELOG.md                                 # Keep-a-Changelog format
├── ARCHITECTURE.md                              # ports-and-adapters dependency rule
├── VERIFICATION.md                              # one-line repro per architectural claim
├── pyproject.toml                               # uv-locked, ruff/mypy/bandit pins
├── Makefile                                     # make check is the inner-loop gate
├── scripts/
│   ├── check_version_parity.py                  # pin-parity enforcement
│   ├── measure_cache.py                         # the 99.7% demo
│   └── smoke.sh                                 # offline Ollama healthcheck
├── src/claude_mcp_server_minimal/
│   ├── server.py                                # 3 tools plus lazy Anthropic client
│   ├── server_errors.py                         # canonical D2 envelope
│   ├── system_prompts.py                        # 4,345-token SUBAGENT_SYSTEM_PROMPT
│   ├── main.py                                  # composition root
│   ├── domain/                                  # types and invariants (template)
│   ├── application/                             # ports and fallback (template)
│   └── infrastructure/                          # SDK adapters (template)
└── tests/
    ├── contract/                                # 32 LLMPort contracts (parametrised)
    └── unit/
        ├── test_server.py                       # MCP surface tests
        └── cassettes/test_server/               # VCR cassettes (secrets redacted)
```

## Appendix B: commands cheat sheet

```bash
# Install dependencies
uv sync --all-extras

# Install pre-commit hook (catches whitespace and EOL drift before CI does)
uv run pre-commit install

# Run the full quality gate, offline, no API keys needed
make check

# Run the prompt-caching measurement script (needs both keys set)
MCP_API_KEY=... ANTHROPIC_API_KEY=... uv run python scripts/measure_cache.py

# Run the server directly (clients normally launch it themselves over stdio)
uv run python -m claude_mcp_server_minimal.server

# Verify the published .mcp.json from anywhere
curl https://raw.githubusercontent.com/rkendev/claude-mcp-server-minimal/main/.mcp.json | jq
```

## Appendix C: links

- Repo: <https://github.com/rkendev/claude-mcp-server-minimal>
- v0.2.0 release: <https://github.com/rkendev/claude-mcp-server-minimal/releases/tag/v0.2.0>
- CI workflow: <https://github.com/rkendev/claude-mcp-server-minimal/actions>
- Architecture diagram: [`ARCHITECTURE.md`](https://github.com/rkendev/claude-mcp-server-minimal/blob/main/ARCHITECTURE.md)

---

*The commit history tells the same story chronologically: A_T003 (stub), A_T004 (real dispatch), A_T005 (caching), v0.2.0 release. Each commit closes one design constraint cleanly. That is the artifact I am happiest with: not because it is complete, but because every step earned its place.*
