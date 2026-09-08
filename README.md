# sql-agent

A small schema-generic natural-language-to-SQL application built on Pydantic AI,
AG-UI, and FastMCP 4.

## Architecture

```text
browser ──AG-UI/SSE──> FastAPI ──> Pydantic AI ──MCP v2──> FastMCP ──> PostgreSQL
                                      │
                                      └──────────────> Ollama
```

The application has one runtime path:

- `backend/src/sql_agent/app.py` exposes the UI and `/agui` endpoint.
- `backend/src/sql_agent/agent.py` prefetches `get_catalog` through MCP for every run,
  injects the typed catalog into instructions, and exposes only `run_query` to the model.
- `backend/src/sql_agent/mcp/server.py` owns all database access and SQL safety.
- FastMCP 4 negotiates modern MCP v2 (`server/discover`) in stateless mode; no protocol session is
  retained between runs and no sidecar process is required.
- `frontend/` is a React/Vite app using assistant-ui primitives and its AG-UI runtime.
  The framework owns SSE transport, conversation history, tool events, and cancellation;
  application UI code only composes the thread, composer, Markdown, and tool display.

Benchmark machinery is isolated under `backend/src/sql_agent/benchmark/`. It can
compare historical granular, catalog, and prefetched tool surfaces, but none of those
modes leak into application settings or request handling.

## Setup and run

```bash
uv sync --all-groups
npm --prefix backend ci
npm --prefix frontend ci
npm --prefix frontend run build
cp .env.example .env  # configure the database and Ollama
uv run sql-agent
```

Open <http://127.0.0.1:8000>. Use Node.js 24 for frontend builds.
FastAPI serves `frontend/dist` at `/` and `/assets`, with `/agui` on the same origin.
Node is needed only to build the UI, not to serve it. The Dockerfile builds the UI in
its own Node stage and copies only the static output into the Python runtime image.
Without a frontend build, `/` returns an actionable 503; the API remains usable.

### Frontend development

Run `uv run sql-agent` in one terminal and `npm --prefix frontend run dev` in another.
Open the Vite URL (normally <http://127.0.0.1:5173>) for hot reload. Vite proxies `/agui`
to FastAPI; set `SQL_AGENT_DEV_API_URL` in the root `.env` if the API is elsewhere.
This proxy setting is development-only and is not embedded in the browser bundle.
Rebuild the UI to see changes when visiting FastAPI directly.

The UI supports one in-memory conversation, expandable SQL tool arguments/results,
Markdown answers, progress, Stop, and recoverable errors. Reloading starts a new
conversation; there is no persistence, thread sidebar, or client-side tool execution.

## Configuration

Required:

- `SQL_AGENT_DSN`
- `SQL_AGENT_OLLAMA_BASE_URL`
- `SQL_AGENT_MODEL_NAME`
- `SQL_AGENT_OLLAMA_API_KEY`

Optional:

- `SQL_AGENT_ROW_CAP` (default `200`)
- `SQL_AGENT_STATEMENT_TIMEOUT_MS` (default `5000`)
- `SQL_AGENT_MAX_OUTPUT_TOKENS` (default `512`)
- `SQL_AGENT_AGUI_MODEL_THINKING` (default `false`)

## Validation

After installing the backend and frontend dependencies above:

```bash
uv run playwright install --with-deps chromium  # once per environment
npm --prefix frontend run check
uv run ruff format . && uv run ruff check . && uv run ty check && uv run pytest
```

The default suite uses PGlite and model doubles. Its Chromium integration tests build
the frontend and drive the actual UI through a live FastAPI → AG-UI → Pydantic AI →
MCP → PGlite path. They cover multi-turn tool history, validated answers, HTTP/run
errors, cancellation, safe Markdown, mobile layout, and the Vite development proxy.
No Ollama or Docker required.
Run just those checks with `uv run pytest tests/integration/test_browser.py`.

The real-model smoke test is opt-in:

```bash
set -a; source .env.e2e; set +a
uv run pytest -m e2e tests/e2e/test_ollama_smoke.py
```

## Larger demo and reference benchmark

The tiny default fixture is for smoke tests. For **100 stations, 2,000 riders, and
100,000 trips over a year**, with realistic variation and deliberate edge cases:

```bash
uv run sql-agent-demo serve  # same UI at :8000; owns an isolated temporary database
uv run sql-agent-demo questions  # copy/paste development prompts, no answers
uv run sql-agent-demo verify     # verify all 16 frozen answer keys, no model required
uv run sql-agent-demo benchmark --repetitions 3
uv run sql-agent-demo benchmark --split heldout --repetitions 3 --timeout 180
```

Stop the existing server first or use `serve --port 8001`. Model settings come from
`.env`, but the demo never resets or uses your configured `SQL_AGENT_DSN`.

See **[the dataset and benchmark guide](data/demo/v1/README.md)** for all 16 questions,
easy→expert difficulty levels, reference SQL, complete expected results, split policy,
and scoring. The eight held-out questions are opt-in. SQL result accuracy is scored
separately from natural-language answer quality; the gold is not fed to the model.

## Historical exposure benchmark

The original benchmark remains development tooling, not a second application path:

```bash
uv run sql-agent-benchmark run --repetitions 3
uv run sql-agent-benchmark summarize benchmarks/records/latest.json
```

Its versioned workloads and historical records live in `data/workloads/` and
`benchmarks/`.
