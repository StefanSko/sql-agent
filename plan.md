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
| P1 | Is the typed core (validated outputs, typed tools) worth the dependency vs a hand-rolled loop? | M1/M2 |
| P2 | How leaky is the MCP client integration — does the toolset feel native or bolted on? | M1–M3 |
| P3 | Does `AGUIAdapter.dispatch_request` stay a one-line front door once we need real behavior (per-request deps, errors mid-stream)? | M4 |
| P4 | Does AG-UI's event vocabulary (tool-call events, state) buy a better UI than our own minimal SSE format would? | M4/M6 |
| P5 | Where does the black box hurt? Every time we read framework source to understand behavior, that's a data point. Log it. | all |
| P6 | Stateless-by-protocol: is resending full history per run acceptable, and what does the framework offer when it isn't? | M4/M6 |
| P7 | Does the abstraction survive contact with a mid-size local model (`gemma4:12b-it-q4_K_M`), or is it designed for frontier-model tool-calling? | M1/M2/M5 |
| P8 | Which MCP tool-exposure shape minimizes model round trips and latency without losing correctness or schema generality? | M3/M5/M6 |

Method: keep a running `notes/probelog.md`. Every friction point, every
source-dive (P5), every "this was easier than expected" gets one dated
line. M6 distills it. Without the log the verdict will be vibes — the thing
this repo exists to avoid.

## Architecture

```
browser (chat UI)
   │  AG-UI events (SSE)                    ← probe surface: P3, P4, P6
   ▼
agent-api process ───────────────► ollama :11434 (OpenAI-compatible API)
   │                                  agent loop itself: P1, P5, P7
   │  MCPToolset, in-memory transport       ← probe surface: P2
   ▼
db-mcp module (FastMCP server object)
   │  asyncpg
   ▼
postgres  ──or──  PGlite socket (local tests)
```

The MCP boundary is deliberately logical, not a process boundary: `agent-api`
constructs the FastMCP server and passes it directly to `MCPToolset`. This
still exercises MCP discovery, schemas, calls, and errors while excluding
transport and deployment complexity that P2 does not need to answer. The
AG-UI and Ollama boundaries remain network protocols.

- **agent-api** — Starlette/FastAPI app. Static chat UI at `/`; AG-UI
  endpoint at `/agui` via `AGUIAdapter.dispatch_request(request, agent=agent)`.
- **db-mcp** — FastMCP server object inside `agent-api`, owning ALL database
  access: `list_tables()`, `describe_table(name)`, `get_catalog()`, and
  `run_query(sql)` (read-only, row-capped, single-statement).
- **model** — Ollama serving `gemma4:12b-it-q4_K_M` via its OpenAI-compatible
  endpoint (`OpenAIChatModel` + `OpenAIProvider(base_url=...)`); all
  names/URLs come from `pydantic-settings`.
- **db** — real Postgres in prod; PGlite behind a TCP socket
  (`@electric-sql/pglite-socket` via `pglite_manager.js`) for tests, so the
  asyncpg wire path is real without a Postgres install.

Control comparison for P1/P4: M0 must preserve the previous hand-rolled
agent/raw-SSE variant under `baseline/hand_rolled/` with its source revision
and run instructions. M1/M2 run the same agent journeys through it; M4 runs
the same UI journey and records comparable events. If that artifact cannot be
recovered, M0 must replace this claim with a checked-in minimal control before
comparative work starts. The verdict never compares against an imagined ideal.

## Mock domain: bike-share trips

Seeded from CSVs in `data/seed/`: `stations.csv` (station_id, name,
district, capacity, lat, lon), `riders.csv` (rider_id, signup_date, plan
member|casual, home_district), `trips.csv` (trip_id, rider_id,
start_station_id, end_station_id, started_at, ended_at, distance_km).
Join-heavy and aggregation-friendly — enough to force multi-step tool use,
which is what P2/P4/P7/P8 need. The domain itself is throwaway. Production
agent instructions and tool descriptions must not contain bike-share table or
column names: schema knowledge enters only through MCP. A second tiny held-out
schema with unrelated names verifies that exposure strategies are generic; it
is test data, not another supported domain.

## Safety (read-only by construction)

- `run_query` runs in a `READ ONLY` transaction with a statement timeout.
- Single statement per call; multi-statement input rejected.
- Row cap (default 200) with an explicit truncation flag in the result type.
- Non-query statement families and privileged server-file/admin functions are
  rejected before execution; composed Postgres uses a `NOSUPERUSER`, SELECT-only
  application role rather than its bootstrap owner.
- The process necessarily holds the DSN because db-mcp is in-process, but it
  is confined to db-mcp construction/database code and never exposed in MCP
  tool arguments, results, prompts, or model-visible agent dependencies.

## Delivery and test strategy

M1–M5 are vertical slices: start with an acceptance scenario at the outermost
boundary available in that milestone, write the smallest deterministic RED
test, and make the path work through Pydantic AI, in-process MCP, and PGlite.
Unit tests may isolate a boundary, but an implementation milestone is not
complete with disconnected layers. M6 consumes the accepted slice evidence;
it does not add another runtime path.

- **Default suite:** `TestModel`/`FunctionModel`, PGlite, and in-process MCP;
  deterministic, no Ollama or Docker. This is the red → green loop. Register
  `e2e` in pytest and configure `uv run pytest` to deselect it by default;
  bare pytest must not execute e2e tests, while `uv run pytest -m e2e ...`
  explicitly selects them. Marker filtering happens after collection, so e2e
  modules must remain import-safe when Ollama is absent.
- **Early Ollama slice:** an opt-in `@pytest.mark.e2e` test runs the real
  Pydantic AI agent against local Ollama with the configured model and
  in-process MCP. M1 first proves a `list_tables` call and final response; M2
  extends it to safe NL→SQL. Run this smoke at each milestone exit from M1
  onward when model/provider wiring, agent instructions, or MCP schemas
  changed, and before M5/M6:
  `uv run pytest -m e2e tests/e2e/test_ollama_smoke.py`.
- **Exposure experiment:** benchmark only coherent variants against the same
  versioned typed workload and model settings. Each `WorkloadCase` carries a
  deterministic expected-result oracle over captured typed query results and
  final structured output; no LLM judges correctness. Warm the model, use a
  fresh conversation and reset database snapshot per run, rotate variant order
  per repetition, and run each case at least three measured times per variant.
  A repetition counts as correct only when its oracle passes and its metric
  record is complete. A timeout, missing/incomplete record, retry exhaustion,
  or wrong result is a failed repetition, never silently discarded. Record
  run order/seed (when supported), median wall time, time to first event,
  model request count, MCP call sequence/count, token usage, retries, and
  correctness. Eligibility requires every safety and
  held-out-schema check plus at least two correct repetitions for every case.
  The small sample is comparative evidence, not a general performance claim.
- **Full e2e:** M5 adds the composed app and representative NL→SQL journeys.
  It remains opt-in and never blocks the normal red → green loop.

## Milestones (each = red → green, see Agents.md)

**M0 — Executable foundation.** `uv init`; add Pydantic AI core (not
`pydantic-ai-harness`), FastMCP, app/test dependencies, ruff, and ty. Configure
pytest so `e2e` is registered and excluded from bare `uv run pytest`; CI proves
the default suite does not execute an import-safe e2e sentinel while an
explicit `-m e2e` invocation does. Add typed environment settings (required
DSN, Ollama base URL, and model name), the PGlite package scaffolding,
`notes/probelog.md`, and the immutable hand-rolled baseline/control required by
P1/P4.

**M1 — Walking skeleton: prompt → real model → MCP → DB. [P1, P2, P7]** Add
the PGlite fixture, schema/seed loading, an in-process FastMCP server with
`list_tables`, and the smallest Pydantic AI agent. First make a deterministic
`FunctionModel` acceptance test observe the MCP call and final response. Then
run the opt-in real-Ollama version with `gemma4:12b-it-q4_K_M`. This milestone
is complete only when one prompt crosses the real provider and MCP boundaries,
reads PGlite, and returns an answer. Use a sentinel DSN and assert it is absent
from MCP definitions/results and provider-facing messages. Log first
impressions immediately rather than postponing them to a framework-complete
layer.

**M2 — Safe useful query slice. [P1, P2, P7]** Add typed `TableSchema` and
query-result variants plus `describe_table`, `get_catalog`, and `run_query`.
Drive the slice from an NL aggregation/join prompt through the agent and MCP;
assert the database result, not merely generated SQL. Pin read-only
transactions, timeout, row cap/truncation, and single-statement rejection with
focused tests. Exercise a database/tool failure and assert the sentinel DSN is
absent from model-visible history and errors. Run the real-Ollama smoke again
with one safe NL→SQL scenario. At exit, write provisional P1/P2 observations;
do not wait for M6.

**M3 — MCP exposure experiment. [P2, P8]** Keep one canonical FastMCP server
and compare three model-facing shapes using Pydantic AI's native toolset
composition where possible:

1. **Granular discovery:** expose `list_tables`, `describe_table`, and
   `run_query`.
2. **Catalog tool:** expose `get_catalog` and `run_query`.
3. **Prefetched catalog:** fetch `get_catalog` through MCP before the run,
   inject its typed result as per-run instructions, and expose only
   `run_query` to the model.

Represent the choice with one typed `ExposureMode` and one toolset/instruction
builder—no plugin framework or parallel agent implementations. All variants
must use the same MCP result types, safety path, model settings, and workload.
The end-to-end measurement clock starts before any catalog prefetch, and no
variant gets an unreported schema cache. Add a deterministic alternate-schema
test and reject any agent instruction, tool description, or production module
that depends on bike-share names.

Capture each run as a frozen typed record containing outcome and latency/token/
call metrics. Run the versioned workload against **all three modes on real
Ollama in M3**, using the ordering, reset, failure, oracle, repetition, and
eligibility rules above; a deterministic matrix test must reproduce the same
eligible set and winner from recorded runs, including timeout, incomplete
metric, multi-case, and exact-tie fixtures. Rank eligible variants
lexicographically by: (1) highest total correct repetitions; then the lowest
macro-medians (the median of per-case medians over complete correct
repetitions only) for (2) model-request count, (3) end-to-end latency, and
(4) input tokens. The matrix test pins each comparison direction. Failed
repetitions affect criterion 1 and never enter metric medians with invented
values. An exact tie is reported as a tie and resolved for M4 by fixed
`ExposureMode` declaration order, with granular first; the tiebreak is not
reported as evidence of superiority. Keep the granular variant as the control
even if another becomes the provisional M4 default.

**M4 — UI vertical slice. [P3, P4, P6]** Add `/agui` and a minimal chat UI on
top of M3's provisionally selected exposure mode, rendering both text and
tool-call events. Start with a TestClient event-sequence RED test that crosses
AG-UI, the agent, MCP, and PGlite. Then add per-request deps (for example
request ID), full history resend, and a mid-stream failure. Run the same
opt-in real-Ollama journey through `/agui` and the checked-in hand-rolled SSE
baseline; compare observable events and implementation surface.

For P6, add a versioned multi-turn journey and measure turns 1, 5, and 10:
serialized AG-UI request bytes, model input tokens, end-to-end latency,
correctness, and context-limit behavior. Declare full resend acceptable for
this probe only if the tenth turn remains correct, below 25% of the model's
advertised context, and no more than 2× the warmed single-turn latency. Also
exercise Pydantic AI core's `ProcessHistory` hook with an immutable processor
that removes old tool results while preserving valid tool-call pairs; record
what code the framework saves, payload/token reduction, and any lost context.
The ready-made Harness compaction package remains outside scope, but its
existence belongs in the P6 verdict.

**M5 — Composed e2e experiment. [P7, P8]** Add docker-compose with
`agent-api`, unexposed `ollama`, a one-shot model-pull/init service, and a
Postgres profile; db-mcp remains inside `agent-api`. Health checks must prove
Ollama is serving and the configured exact tag is present before agent tests
start. Run the versioned workload across all eligible exposure modes, including
the held-out schema, after one warm-up and at least three measured repetitions.
Record Ollama/model digest and metadata, model settings, raw typed run metrics,
and summary medians. Evaluate tool-loop reliability and graceful failure, not
just mean latency. If Gemma 4 cannot drive the loop, record the SQL-only
fallback and its framework cost rather than hiding the failure.

**M6 — Verdict. [all]** Distill `probelog.md` and experiment records into
`notes/verdict.md`: answer P1–P8, recommend keep/replace/strip-down for each
layer, state which exposure mode won under the eligibility rule, and compare
with the concrete hand-rolled alternative. Treat local-model NL→SQL quality
and small-sample latency as bounded evidence, not a general benchmark.

## Execution status (2026-08-27)

M0–M4 and M6 have accepted deterministic and real-provider evidence. M5's
compose files, exact-tag init gate, health checks, image build, and composed-app
test are implemented. This machine could only accept the agent + seeded
Postgres containers against the exact host Ollama: its Docker CLI has no Compose
plugin, the official Ollama image pull did not complete in two bounded attempts,
and the 3.8 GB Docker VM cannot hold the installed 7.0 GB model. The full
Compose topology is therefore explicitly **unexecuted**, not silently treated
as accepted; `experiments/composed/` and `notes/verdict.md` bound the evidence.

## Decisions made before implementation

- **No `pydantic-ai-harness`.** Its capabilities target richer, long-running
  agents (filesystem, planning, memory, subagents, durable execution). The
  typed loop, MCP integration, model providers, and AG-UI adapter needed here
  are Pydantic AI core features. Adding the Harness would widen P1 without
  answering any probe question.
- **In-process MCP only.** Construct one FastMCP server object and pass it to
  `MCPToolset(server_instance)` in tests and the app. Do not add stdio,
  Streamable HTTP, or a db-mcp container: process isolation and shared MCP
  service deployment are outside this probe. P2 therefore judges MCP
  discovery, typing, invocation, error, and toolset-composition behavior—not
  network transport quality.
- **Experiment at the exposure seam, not in domain code.** The canonical MCP
  tools and typed results stay stable; exposure modes only select tools and
  decide whether catalog context is model-pulled or application-prefetched.
  This makes model-round-trip reduction measurable without creating three
  agents or specializing query behavior to the seed dataset.
- **Ollama model tag: `gemma4:12b-it-q4_K_M`.** Keep it required
  configuration rather than a code default, set this exact value in
  example/e2e configuration, and capture the resolved digest/metadata in M5
  results. Pre-implementation verification on 2026-08-27 confirmed that this
  installed tag answers Ollama's `/v1/chat/completions` API with a valid
  `list_tables` function call; the M1 walking-skeleton test will verify the
  complete Pydantic AI → MCP path rather than only Ollama itself.

## Non-goals

Write access, auth/multi-user, conversation persistence beyond what P6
requires to evaluate, query optimization, non-Postgres backends, optimizing
in-memory MCP transport itself, benchmark-grade performance claims, and —
importantly — polishing the app beyond what the probe questions need.
