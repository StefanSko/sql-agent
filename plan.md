# sql-agent — Application plan

## Goal

Ship one understandable schema-generic SQL agent rather than preserve multiple probe
implementations. The supported stack is Pydantic AI, AG-UI, and FastMCP 4 using modern,
stateless MCP v2.

## Runtime

```text
assistant-ui (React) -> AG-UI endpoint -> Pydantic AI agent -> FastMCP database tools -> PostgreSQL
                                  |
                                  -> configured model provider
```

The production contract is deliberately narrow:

1. The application prefetches `get_catalog()` through MCP for each run.
2. The typed catalog is injected into that run's instructions.
3. The model sees only `run_query(sql)`, which executes one bounded read-only statement.
4. The agent returns a typed `AgentAnswer`.
5. AG-UI streams database-tool lifecycle events and publishes only the final validated answer;
   rejected model prose, internal output-tool calls, and failed partial text stay server-side.

FastMCP retains the granular schema tools for interoperability and offline benchmark
comparisons, but exposure selection is not an application setting.

## Invariants

- The DSN remains inside database construction and never enters prompts, tool schemas,
  results, or model-visible dependencies.
- SQL is single-statement and read-only, runs in a read-only transaction with a timeout,
  and reads at most `row_cap + 1` rows to detect truncation.
- Query outcomes are explicit typed variants: success, truncation, or safe rejection.
- Every MCP client uses FastMCP 4 modern protocol negotiation. MCP v2 has no initialize
  handshake or retained protocol session.
- assistant-ui's AG-UI runtime owns transport, cancellation, and full history resend,
  including tool call/result pairing; application UI code does not parse SSE or assemble history.
- Each browser page owns one in-memory conversation; reload creates a fresh thread.
  The server does not own conversation persistence.

## Frontend and deployment

- React + Vite, `@assistant-ui/react`, `@assistant-ui/react-ag-ui`, and
  `@assistant-ui/react-markdown` replace the hand-written browser client.
- The UI composes assistant-ui thread/composer/message primitives with a small
  expandable tool renderer. No browser tools, persistence, or multi-thread sidebar.
- Vite builds `frontend/dist`; FastAPI serves `/` and `/assets` alongside `/agui`
  and `/health`. There is no catch-all route that could hide API/static-file errors.
- Docker builds assets in a Node stage; the runtime image only needs Python.
  Local development uses Vite hot reload and a configurable `/agui` proxy.

## Module boundaries

- `sql_agent.agent`, `app`, `mcp`, `settings`, and `types` are application runtime.
- `sql_agent.benchmark` owns workload loading, PGlite setup, exposure comparisons,
  tracing, metrics, ranking, and benchmark CLI behavior.
- Benchmark code may depend on runtime code. Runtime code must not import benchmark code.
- `sql_agent.benchmark.demo` owns a separate deterministic large demo and execution-accuracy
  runner; `demo_workload` parses versioned questions/gold and compares full query results.
  `data/demo/v1` holds the frozen schema, SQL generator, development/held-out questions,
  reference SQL, and checksummed expected rows. These never enter production prompts or
  database tables. The small smoke fixture and historical exposure benchmark stay unchanged.
- `sql-agent-demo serve` is development orchestration: it owns a disposable PGlite instance
  and starts the normal FastAPI application, never resetting the configured external DSN.

## Validation

Changes follow red → green and finish with:

```bash
uv run ruff format . && uv run ruff check . && uv run ty check && uv run pytest
```

The default acceptance path crosses AG-UI, Pydantic AI, modern MCP v2, FastMCP, and
PGlite. Default Chromium tests additionally build the frontend and exercise that path
from a real browser, including multi-turn history, cancellation, errors, validated-only
answers, and safe Markdown/mobile rendering. Setup requires `npm --prefix frontend ci`
and `uv run playwright install --with-deps chromium`; frontend checks use
`npm --prefix frontend run check`.
Default large-dataset checks independently calculate all 16 reference answers in Python,
verify the SQL through MCP, pin dataset invariants/determinism, and test complete-result
scoring, held-out opt-in, checksum drift, timeout recording, and oracle-context isolation.
The runner clears PGlite's shared prepared-statement cache after reference verification so
reference SQL is not queryable by the model through database session metadata.
Real Ollama and composed deployment checks remain opt-in e2e tests.

## Current status

The original architecture probe is complete. Its useful exposure benchmark records are
retained under `benchmarks/`; hand-rolled controls, UI comparison experiments,
multi-turn probe runners, and generated visual artifacts have been removed from the
maintained application.
