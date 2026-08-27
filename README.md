# sql-agent

A schema-generic natural-language-to-SQL application used to probe Pydantic AI,
in-process MCP, and AG-UI against a concrete hand-rolled control. The normative
scope and experiment rules are in [`plan.md`](plan.md); conclusions are in
[`notes/verdict.md`](notes/verdict.md).

## Setup

```bash
uv sync --all-groups
npm ci
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
