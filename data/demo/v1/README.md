# Large demo / SQL benchmark v1

A reproducible **synthetic**, not real-world, bike-share dataset:

- **100 stations**, five districts, varied capacities and coordinates.
- **2,000 riders**, signup cohorts across January–November 2025, member/casual plans.
- **100,000 trips** covering all twelve months of **2025**.
- Summer preference, weekday rush hours, directional commute patterns **with counterflow/noise**.
- Short-lived and longer-lived activity, **100 inactive riders**, **two unused stations**.
- Zero-distance journeys and **10 intentionally implausible-speed records**.
- Trips never precede signup; durations are positive. Timestamps are naive local time.

This is an analytics challenge, not a calibrated mobility simulator. For example, distances
are generated independently of station coordinates; don't use it to validate routing/geospatial
models. The small `data/seed` fixture remains unchanged for fast tests.

## Try it in the UI

From the repository root, after normal dependency/frontend setup and configuring the model in `.env`:

```bash
uv run sql-agent-demo serve
```

Open <http://127.0.0.1:8000>. Stop another server on port 8000 first, or use `--port 8001`.
This command generates a fresh isolated PGlite database, verifies the frozen results, and
starts the existing FastAPI/assistant-ui application. **It ignores `SQL_AGENT_DSN` and never
resets your configured database.** Model configuration still uses `SQL_AGENT_OLLAMA_BASE_URL`,
`SQL_AGENT_MODEL_NAME`, and `SQL_AGENT_OLLAMA_API_KEY`. Ctrl+C stops and removes the temporary DB.

To use your own empty PostgreSQL database instead, apply `schema.sql` followed by `seed.sql`
from this directory using your database admin tooling, then configure the normal application
with a SELECT-only role. Do not run these bootstrap files against an existing application schema.

## Questions (easy → expert)

Print exact copy/paste prompts, without SQL or answers:

```bash
uv run sql-agent-demo questions
uv run sql-agent-demo questions --split heldout
```

The authoritative wording and output contract are in [`questions.json`](questions.json).
In particular, use its date boundaries, denominator definitions, tie-breakers, column aliases,
and rounding rules for a scored run. The table below is just an overview.

| Development case | Level | Question / skill |
|---|---|---|
| d01-total | easy | Total trips in the year — aggregation |
| d02-plan-share | easy | Trip counts and percentage share by plan |
| d03-popular-origins | medium | Five busiest departure stations — join, top-k, tie-breaking |
| d04-monthly-volume | medium | Monthly counts including zero months — date spine / left join |
| d05-morning-imbalance | hard | Weekday morning departures minus arrivals — conditional aggregation without join fanout |
| d06-latest-distance-change | hard | Latest versus previous distance per rider — windows and deterministic ordering |
| d07-cohort-retention | expert | Next-calendar-month signup cohort retention, including inactive riders in denominators |
| d08-speed-anomalies | medium | Implied speeds above 80 km/h — interval arithmetic and anomaly detection |

| Held-out case | Level | Question / skill |
|---|---|---|
| h01-inactive | easy | Registered riders with no trips — anti-join |
| h02-unused-stations | medium | Stations with neither departures nor arrivals |
| h03-plan-averages | medium | Average duration and distance by plan, including outliers |
| h04-cross-district | medium | Percentage of trips crossing station districts — two joins to the same table |
| h05-district-growth | hard | Largest November→December district growth — conditional counts / safe division |
| h06-consecutive-days | expert | Longest consecutive active-day streaks — deduplication / gaps and islands |
| h07-busiest-week | hard | Busiest trailing seven-calendar-day window — date spine / rolling sum |
| h08-duration-percentile | expert | July continuous p90 duration by district — interpolated percentile |

## Ground truth and verification

- [`reference/`](reference/) contains reviewed PostgreSQL reference queries, one per case.
- [`golden.json`](golden.json) contains **all expected rows**, not just a single expected number.
  It binds schema, generator, question wording, and reference SQL with SHA-256 checksums.
- Verification never regenerates expected values. Changed inputs invalidate the frozen key.
- All **16 cases** are cross-checked against independent standard-library Python calculations
  in `tests/support/demo_oracle.py`, as well as execution of the reference SQL through MCP.
- Answers and reference queries are never passed to the agent. Only the question, ordinary
  schema, and the agent's own query results are model-visible. No gold tables are seeded.
  The verifier clears PGlite's shared prepared-statement cache before handing off the DB.

```bash
uv run sql-agent-demo verify  # no model, Ollama, or Docker required
uv run pytest tests/integration/test_demo_dataset.py tests/integration/test_demo_benchmark.py
```

**Held-out means a question split on this same dataset**, not an unseen database schema or
secret test data. Use development cases for prompt/model tuning. Run held-out cases only at
release gates; if you tune against those results, they are no longer a meaningful holdout.
The historical `data/workloads/heldout.sql` schema-generalization test remains separate.

## Benchmark

```bash
# Default: development only. Three repetitions are recommended for comparisons.
uv run sql-agent-demo benchmark --repetitions 3

# A quicker targeted run:
uv run sql-agent-demo benchmark --case d01-total --case d05-morning-imbalance --timeout 90

# Explicit final gate; never silently included in development runs:
uv run sql-agent-demo benchmark --split heldout --repetitions 3 --timeout 180
```

Every benchmark invocation uses a new isolated seeded DB, fresh conversation per case, and the application's
prefetched `get_catalog` / `run_query` tool surface and typed `AgentAnswer` contract. It benchmarks
the agent/MCP path, **not browser rendering or AG-UI transport**. No LLM judge is used.

### What the score means

**SQL execution accuracy**: the last query of a completed agent run must return the exact
complete reference result. All columns, rows, duplicate multiplicity, ordering, and prescribed
rounding matter; numeric SQL representations like `1` and `1.0` are equivalent. Truncated results,
timeouts, malformed output/retry exhaustion, and execution errors fail. A correct intermediate
query followed by an incorrect final query does not pass. The score does **not** establish
semantic equivalence on every possible database or grade the final natural-language prose.

JSON and Markdown reports default to `benchmarks/records/demo-<split>.json` / `.md` (overwritten
on subsequent runs; use `--output` to retain comparisons). Records include generated SQL and
results, answers, calls, retries, tokens/request counts for completed runs, and latency/failure
kind for every attempt. Reports capture model digest, seeds, limits, framework versions, and
the gold checksum. JSON is checkpointed after each attempt; summaries count attempted runs,
not unattempted work if you interrupt. There is no explicit model warmup; model loading, if
needed, is included in the first attempt. Database seeding and reference verification occur
before case timing (so database caches may already be warm).

Use identical model settings, dataset version, case selection, repetitions, and time limits
for comparisons. The default output cap is inherited from `SQL_AGENT_MAX_OUTPUT_TOKENS` (512),
which may be restrictive on expert tasks; changing it is a benchmark configuration change,
not an invisible retry. Keep row caps at least 12 to accommodate the largest reference table.

A first development-only [smoke report](../../../benchmarks/records/demo-development-smoke.md)
records 2/3 correct with the local Gemma model: total count and morning imbalance passed;
cohort retention exceeded 90 seconds. This is a three-case smoke check, not an all-case,
repeated, or held-out benchmark result.

### Maintaining a future version

Do not silently rewrite v1 answers when a model fails. For a deliberate new dataset/workload
version, review the SQL, extend the independent oracle, and create a **new** gold file explicitly:

```bash
uv run sql-agent-demo freeze --output /tmp/candidate-golden.json
```

`freeze` refuses to overwrite an existing file. The independently verified, reviewed snapshot
is what gets versioned; `verify` and `benchmark` always read it, never derive answers on the fly.
