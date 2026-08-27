# Agents.md

Working agreement for agents (and humans) contributing to this repo.

## Toolchain — astral stack, no exceptions

- **uv** for everything: `uv add`, `uv run`, `uv sync`. Never bare `pip`.
- **ruff** for lint + format: `uv run ruff format . && uv run ruff check --fix .`
- **ty** for type checking: `uv run ty check`
- **pytest** for tests: `uv run pytest`

Definition of done, in order:

```bash
uv run ruff format . && uv run ruff check . && uv run ty check && uv run pytest
```

All four green or the change does not exist.

## Workflow — red → green

1. **Red.** Write the smallest failing test that pins the behavior you want.
   Run it. Watch it fail for the *right reason* (assertion, not ImportError).
2. **Green.** Write the minimum code to pass. Resist generality.
3. **Refactor.** Only now. Tests stay green throughout.
4. Commit at green, message states behavior not implementation
   ("run_query rejects multi-statement input", not "add regex").

Never write implementation before its test. Never fix a bug without first
adding the test that reproduces it. e2e tests (`@pytest.mark.e2e`, need
Ollama/docker) are excluded from the default run and are not part of the
red→green loop.

## Code principles (rust-style python)

- **Type hints are not optional.** Every signature, every attribute.
  Modern syntax: `list[T]`, `dict[K, V]`, `X | None` — never `List`,
  `Optional`, `Union`.
- **Dataclasses over tuples and dicts.** Structured data gets a frozen
  `@dataclass` (`TableSchema`, `QueryResult`), never an anonymous dict.
- **Make illegal states unrepresentable.** Model variants as tagged unions
  (`QueryOk | QueryTruncated | QueryRejected`) and `match` over them with
  `assert_never` for exhaustiveness — not booleans and status strings.
- **NewType for domain ids and secrets:** `StationId = NewType("StationId", int)`,
  `Dsn = NewType("Dsn", str)`. The type checker, not discipline, prevents
  mixing them.
- **Named constructors** (`Settings.from_env()`, `QueryResult.from_records()`)
  over clever `__init__` overloads.
- **Parse, don't validate:** raw input (CSV rows, MCP payloads, model output)
  is converted to typed objects at the boundary once; everything inside
  works with types only.

## Repo conventions

- Config via `pydantic-settings` from env; no hardcoded URLs, model names,
  or DSNs. Because db-mcp is in-process, `agent-api` holds the DSN only for
  db-mcp construction; never put it in model-visible dependencies, prompts,
  MCP arguments, or results.
- All DB access goes through the in-process MCP server object, including in
  tests above M1.
- Tests that need a database use the PGlite fixture; no test requires a
  local Postgres install.
- Follow plan.md milestones in order; if reality contradicts plan.md,
  update plan.md in the same commit. For M1–M5, a milestone is complete only
  when its vertical acceptance path crosses every implemented boundary; unit
  tests alone do not complete a slice. M6 synthesizes accepted evidence.
- Keep production agent instructions, tool descriptions, and exposure logic
  schema-generic. Bike-share and held-out-domain names belong only in seed
  data, workload fixtures, and expected test results.
- This repo's purpose is probing the Pydantic AI + AG-UI design (see
  plan.md). Any framework friction, workaround, or source-dive gets a
  dated one-liner in `notes/probelog.md` in the same commit — the M6
  verdict is built from that log, not from memory.
