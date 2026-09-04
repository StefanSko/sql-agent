# sql-agent

A schema-generic natural-language-to-SQL application used to probe Pydantic AI,
in-process MCP, and AG-UI against a concrete hand-rolled control. The normative
scope and experiment rules are in [`plan.md`](plan.md); conclusions are in
[`notes/verdict.md`](notes/verdict.md).

## Repository layout

- `backend/src/sql_agent/` — FastAPI and Pydantic AI application runtime
- `backend/src/sql_agent/mcp/` — in-process MCP server, client decoding, and exposure policy
- `frontend/` — standalone browser client served by the backend
- `backend/pglite_manager.js` — backend test-database process
- `tests/` — unit, integration, and opt-in end-to-end coverage
- `data/` — shared schemas, seeds, and experiment workloads

Python project metadata remains at the root so all backend and cross-boundary
commands continue to use a single `uv` environment.

## Setup

```bash
uv sync --all-groups
npm --prefix backend ci
cp .env.example .env  # then set the required values
```

Run the app:

```bash
uv run sql-agent
# http://127.0.0.1:8000
```

## Validation

```bash
uv run ruff format . && uv run ruff check . && uv run ty check && uv run pytest
```

The default suite starts PGlite over a local TCP socket and does not need Ollama,
Docker, or PostgreSQL. Real-provider tests are explicit:

```bash
set -a; source .env.e2e; set +a
uv run pytest -m e2e tests/e2e/test_ollama_smoke.py
```

Run the exposure experiment after starting Ollama:

```bash
uv run sql-agent-experiment run --repetitions 3
uv run sql-agent-experiment summarize experiments/records/latest.json
uv run sql-agent-multiturn
uv run python -m sql_agent.ui_comparison
```

The composed topology is defined in `docker-compose.yml`:

```bash
docker compose --profile postgres up --build --wait
SQL_AGENT_COMPOSED_URL=http://127.0.0.1:8000 \
  uv run pytest -m e2e tests/e2e/test_composed_app.py
```

`notes/verdict.md` and `experiments/composed/` state the execution limits of the
current machine; they do not claim that the full topology ran here.

The reconstructed immutable control and its run instructions are under
[`baseline/hand_rolled/`](baseline/hand_rolled/).

## Visual field guide

Standalone visual artifacts are under [`artifacts/`](artifacts/):

- [Architecture and decision motivation](artifacts/architecture.html)
- [Call stack and interface type journey](artifacts/call-stack.html)
- [Benchmark design, statistics, and result](artifacts/benchmarks.html)
- [Motivated verdict and visual improvement paths](artifacts/verdict.html)
- [Five proposed experiments to validate or overturn the verdict](artifacts/validation/index.html)
