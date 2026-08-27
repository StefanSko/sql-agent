# sql-agent — Plan

## What this repo is actually for

**Probing the Pydantic AI + AG-UI design.** The SQL agent is the vehicle,
not the destination: a realistic-enough app (NL queries → Postgres via MCP,
local Ollama model) chosen to stress the parts of the stack we're skeptical
about. The deliverable is a grounded verdict on whether these abstractions
earn their keep — written down in `notes/verdict.md` — with a working app
as the evidence.

The questions we want answered, each pinned to the milestone that answers it:

| # | Question | Answered in |
|---|----------|-------------|
| P1 | Is the typed core (validated outputs, typed tools) worth the dependency vs a hand-rolled loop? | M3 |
| P2 | How leaky is the MCP client integration — does the toolset feel native or bolted on? | M2/M3 |
| P3 | Does `AGUIAdapter.dispatch_request` stay a one-line front door once we need real behavior (per-request deps, errors mid-stream)? | M4 |
| P4 | Does AG-UI's event vocabulary (tool-call events, state) buy a better UI than our own minimal SSE format would? | M4/M6 |
| P5 | Where does the black box hurt? Every time we read framework source to understand behavior, that's a data point. Log it. | all |
| P6 | Stateless-by-protocol: is resending full history per run acceptable, and what does the framework offer when it isn't? | M4/M6 |
| P7 | Does the abstraction survive contact with a mid-size local model (`gemma4-12b`), or is it designed for frontier-model tool-calling? | M5 |

Method: keep a running `notes/probelog.md`. Every friction point, every
source-dive (P5), every "this was easier than expected" gets one dated
line. M6 distills it. Without the log the verdict will be vibes — the thing
this repo exists to avoid.

## Architecture

```
browser (chat UI)
   │  AG-UI events (SSE)          ← probe surface: P3, P4, P6
   ▼
agent-api ──────────────► ollama :11434   (OpenAI-compatible API)
   │  MCP client                  ← probe surface: P2
   ▼                               agent loop itself: P1, P5, P7
db-mcp (FastMCP server)
   │  asyncpg
   ▼
postgres  ──or──  PGlite socket (local tests)
```

Boxes are processes; protocols live on arrows. Both protocol arrows are the
thing under test; the boxes are kept deliberately boring so friction is
attributable to the stack, not to our cleverness.

- **agent-api** — Starlette/FastAPI app. Static chat UI at `/`; AG-UI
  endpoint at `/agui` via `AGUIAdapter.dispatch_request(request, agent=agent)`.
- **db-mcp** — FastMCP server owning ALL database access:
  `list_tables()`, `describe_table(name)`, `run_query(sql)` (read-only,
  row-capped, single-statement).
- **model** — Ollama serving `gemma4-12b` via OpenAI-compatible endpoint
  (`OpenAIChatModel` + `OpenAIProvider(base_url=...)`); all names/URLs from
  `pydantic-settings`.
- **db** — real Postgres in prod; PGlite behind a TCP socket
  (`@electric-sql/pglite-socket` via `pglite_manager.js`) for tests, so the
  asyncpg wire path is real without a Postgres install.

Control comparison for P1/P4: the previous hand-rolled variant (raw SSE,
~80-line vanilla client) is the baseline we compare against. When judging
"was AG-UI worth it", the alternative is that concrete artifact, not an
imagined ideal.

## Mock domain: bike-share trips

Seeded from CSVs in `data/seed/`: `stations.csv` (station_id, name,
district, capacity, lat, lon), `riders.csv` (rider_id, signup_date, plan
member|casual, home_district), `trips.csv` (trip_id, rider_id,
start_station_id, end_station_id, started_at, ended_at, distance_km).
Join-heavy and aggregation-friendly — enough to force multi-step tool use,
which is what P2/P4/P7 need. The domain itself is throwaway.

## Safety (read-only by construction)

- `run_query` runs in a `READ ONLY` transaction with a statement timeout.
- Single statement per call; multi-statement input rejected.
- Row cap (default 200) with an explicit truncation flag in the result type.
- Only db-mcp holds credentials; the agent never sees a DSN.

## Milestones (each = red → green, see Agents.md)

**M0 — Skeleton.** `uv init`, pyproject with the dependency set, ruff + ty,
CI stub, `package.json` for py-pglite-env. Create `notes/probelog.md`.

**M1 — Test DB harness.** Fixture that starts/stops the PGlite socket
server, applies `schema.sql`, loads seed CSVs. Pure plumbing — no probe
questions here; keep it boring.

**M2 — MCP server.** FastMCP server, typed dataclass results, wired
in-process via `MCPToolset(server)` and tested against
the M1 fixture (read-only enforced, row cap, single-statement). *Probe
starts:* first impressions of FastMCP's tool typing go in the log (P2).

**M3 — Agent core. [P1, P2]** Pydantic AI agent over the MCP toolset.
Tests with `TestModel`/`FunctionModel` — no Ollama. This is where P1 gets
its answer: how much code did the typed loop save vs the baseline, and did
the MCP toolset behave like a native one (P2)? Explicitly test one ugly
path: a tool raising mid-run — how does the framework surface it?

**M4 — AG-UI endpoint. [P3, P4, P6]** `/agui` route + minimal chat UI
consuming AG-UI events — including rendering tool-call events, because P4
is only testable if we use the vocabulary beyond text deltas. Then push on
P3: add per-request deps (e.g. a request-id into the agent) and a
mid-stream failure; does `dispatch_request` stay clean or start fighting?
TestClient tests assert the event sequences.

**M5 — Ollama e2e. [P7]** docker-compose (`agent-api`, unexposed `ollama`,
profile for Postgres + db-mcp). `@pytest.mark.e2e`, excluded by default.
The P7 question: does gemma4-12b drive the tool loop reliably, and how
gracefully does the stack degrade if not? Fallback to record, not to hide:
constraining output to SQL-only and executing it harness-side — and what
that fallback costs us in framework value.

**M6 — Verdict. [all]** Distill `probelog.md` into `notes/verdict.md`:
per-question answers, keep/replace/strip-down recommendation for each layer
(Pydantic AI core, MCP integration, AG-UI), and what the hand-rolled
alternative would have cost instead. NL→SQL quality of the model gets a
section too, but as a footnote — it's not what's on trial.

## Open questions (decide before M5)

- `pydantic-ai-harness`: confirm the package's current API and role before
  wiring it in; candidate for P5 log entries.
- MCP transport is a ladder, same FastMCP server object on every rung:
  (1) **in-process** — `MCPToolset(server_instance)`, in-memory transport;
  default for M2/M3 tests and dev. Full MCP protocol, zero infra; isolates
  protocol cost from transport cost for P2. (2) **stdio subprocess** — one
  dedicated test to exercise a real process boundary. (3) **streamable
  HTTP** — only if the probe tests the shared-service claim (P2).
- Exact Ollama tag for `gemma4-12b`: config, verify at M5.

## Non-goals

Write access, auth/multi-user, conversation persistence beyond what P6
requires to evaluate, query optimization, non-Postgres backends, and —
importantly — polishing the app beyond what the probe questions need.
