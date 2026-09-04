# sql-agent — Application plan

## Goal

Ship one understandable schema-generic SQL agent rather than preserve multiple probe
implementations. The supported stack is Pydantic AI, AG-UI, and FastMCP 4 using modern,
stateless MCP v2.

## Runtime

```text
browser -> AG-UI endpoint -> Pydantic AI agent -> FastMCP database tools -> PostgreSQL
                                  |
                                  -> configured model provider
```

The production contract is deliberately narrow:

1. `get_catalog()` returns the database schema.
2. `run_query(sql)` executes one bounded read-only statement.
3. The agent returns a typed `AgentAnswer`.
4. AG-UI streams text, tool lifecycle, completion, and error events.

The model sees only `get_catalog` and `run_query`. FastMCP also retains the granular
schema tools for interoperability and offline benchmark comparisons, but exposure
selection is not an application setting.

## Invariants

- The DSN remains inside database construction and never enters prompts, tool schemas,
  results, or model-visible dependencies.
- SQL is single-statement and read-only, runs in a read-only transaction with a timeout,
  and reads at most `row_cap + 1` rows to detect truncation.
- Query outcomes are explicit typed variants: success, truncation, or safe rejection.
- Every MCP client uses FastMCP 4 modern protocol negotiation. MCP v2 has no initialize
  handshake or retained protocol session.
- The browser resends AG-UI history; the server does not own conversation persistence.

## Module boundaries

- `sql_agent.agent`, `app`, `mcp`, `settings`, and `types` are application runtime.
- `sql_agent.benchmark` owns workload loading, PGlite setup, exposure comparisons,
  tracing, metrics, ranking, and benchmark CLI behavior.
- Benchmark code may depend on runtime code. Runtime code must not import benchmark code.

## Validation

Changes follow red → green and finish with:

```bash
uv run ruff format . && uv run ruff check . && uv run ty check && uv run pytest
```

The default acceptance path crosses AG-UI, Pydantic AI, modern MCP v2, FastMCP, and
PGlite. Real Ollama and composed deployment checks remain opt-in e2e tests.

## Current status

The original architecture probe is complete. Its useful exposure benchmark records are
retained under `benchmarks/`; hand-rolled controls, UI comparison experiments,
multi-turn probe runners, and generated visual artifacts have been removed from the
maintained application.
