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
- `backend/src/sql_agent/agent.py` defines the agent and its fixed database tool surface:
  `get_catalog` and `run_query`.
- `backend/src/sql_agent/mcp/server.py` owns all database access and SQL safety.
- FastMCP 4 negotiates modern MCP v2 (`server/discover`) in stateless mode; no protocol session is
  retained between runs and no sidecar process is required.
- `frontend/` is the small AG-UI browser client.

Benchmark machinery is isolated under `backend/src/sql_agent/benchmark/`. It can
compare historical granular, catalog, and prefetched tool surfaces, but none of those
modes leak into application settings or request handling.

## Setup and run

```bash
uv sync --all-groups
npm --prefix backend ci
cp .env.example .env  # configure the database and Ollama
uv run sql-agent
```

Open <http://127.0.0.1:8000>.

## Configuration

Required:

- `SQL_AGENT_DSN`
- `SQL_AGENT_OLLAMA_BASE_URL`
- `SQL_AGENT_MODEL_NAME`
- `SQL_AGENT_OLLAMA_API_KEY`

Optional:

- `SQL_AGENT_ROW_CAP` (default `200`)
- `SQL_AGENT_STATEMENT_TIMEOUT_MS` (default `5000`)
- `SQL_AGENT_AGUI_MODEL_THINKING` (default `false`)

## Validation

```bash
uv run ruff format . && uv run ruff check . && uv run ty check && uv run pytest
```

The default suite uses PGlite and model doubles. The real-model smoke test is opt-in:

```bash
set -a; source .env.e2e; set +a
uv run pytest -m e2e tests/e2e/test_ollama_smoke.py
```

## Benchmark

The benchmark is development tooling, not a second application path:

```bash
uv run sql-agent-benchmark run --repetitions 3
uv run sql-agent-benchmark summarize benchmarks/records/latest.json
```

Its versioned workloads and historical records live in `data/workloads/` and
`benchmarks/`.
