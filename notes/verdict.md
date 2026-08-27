# Verdict — Pydantic AI + MCP + AG-UI SQL-agent probe

## Executive decision

| layer | decision | why |
|---|---|---|
| Pydantic AI core | **Keep** | Typed outputs, retries, usage, tool execution, model/provider wiring, and history hooks removed risky loop code and made failure assertions precise. |
| In-process MCP | **Strip down unless interoperability is a real next step** | It composes naturally as an agent toolset, but an in-process-only application pays protocol/client/schema friction without gaining deployment isolation. A direct typed Pydantic toolset would preserve most value. |
| AG-UI | **Replace with minimal SSE for this UI; keep only for ecosystem compatibility** | Its vocabulary gives standard tool/run lifecycle events, but correct full-history reconstruction and structured-output bridging made the browser much larger than the raw control. |
| Exposure mode | **Use prefetched catalog; retain granular as control** | All variants were eligible and 6/6 correct; prefetched won every ranked efficiency criterion after correctness. |

The stack works with the configured local model and the resulting app is useful. The
probe does **not** justify all three abstraction layers for this deliberately local,
in-process deployment. Pydantic AI earns its dependency. MCP and AG-UI need an
interoperability requirement beyond this app to earn theirs.

## Evidence boundary

Primary artifacts:

- `experiments/records/latest.json` and `experiments/summaries/latest.md`: real
  `gemma4:12b-it-q4_K_M`, digest
  `4eb23ef187e2c5462566d6a1d3bbbc2f1346d0b4327cbb66d58fffbcc9b2b05c`,
  workload v1, three repetitions, rotated variant order, fresh conversation and
  database reset per run, 18/18 typed-oracle successes.
- `experiments/ui/latest.json`: one real comparable AG-UI/raw-SSE journey.
- `experiments/multiturn/latest.json`: ten real AG-UI turns plus the
  `ProcessHistory` comparison.
- The deterministic suite covers PGlite over asyncpg, in-process FastMCP,
  Pydantic AI, AG-UI, history pairing, ranking, held-out schema, and the frozen
  control. The opt-in local suite crossed real Ollama and the built containerized
  agent/seeded-Postgres path.

This is small-sample comparative evidence, not a general model or latency benchmark.
The checked-in Compose stack was statically validated and the agent image built. The
installed Docker CLI lacked Compose, and pulling the Ollama container image stalled;
the accepted container path therefore used containerized agent + Postgres against the
exact host Ollama model. That is **not** evidence that the full Compose topology was
executed.

## P1 — Is the typed core worth it?

**Yes: keep it.** `AgentAnswer`, schema values, and explicit query-result variants
made output, truncation, rejection, and oracle checks ordinary typed assertions. The
framework owns output validation/retries, provider messages, usage, streaming model
events, tool dispatch, and tool-result reinsertion.

The frozen control is concrete rather than hypothetical. Its loop must construct wire
messages, serialize arguments, enforce request limits, dispatch calls, and stream its
own events. A real-provider test found an arguments-as-object bug that deterministic
model doubles tolerated; the OpenAI wire requires a JSON string. Pydantic AI already
owns that boundary.

The code-count result is not a simplistic win: the current core agent is 120 nonblank
lines versus 111 for the control loop, before comparing every adapter/helper. The
value is the behavior those lines delegate and validate, not fewer lines at any cost.
For this safety-sensitive tool loop, that value justifies the dependency.

## P2 — Does MCP feel native or bolted on?

**Both, at different seams.** `MCPToolset(FastMCP)` and `FilteredToolset` behave like
native Pydantic AI toolsets. One canonical server supplied discovery, schemas, calls,
errors, and all three exposure shapes. No separate MCP transport process or alternate
agent implementation was needed.

The leaks are concrete:

- the slim MCP extra installs a client but not in-process FastMCP server support;
- direct FastMCP union results are wrapped under a structured `result` root and need
  typed unwrapping;
- prefetched mode needs a second FastMCP client lifecycle before the agent run;
- database exceptions still need application-owned sanitization, as they should.

The final safety path is not only transaction read-only: it rejects non-query
statement families and privileged server-file/admin functions before execution, and
the Compose app uses a dedicated `NOSUPERUSER` SELECT-only role rather than the
bootstrap owner. Application routes also disable the otherwise useful experiment call
trace so query rows are not retained for the process lifetime.

If a remote/shared MCP server is likely, keep this integration. Under the stated
in-process-only architecture, replace it after the probe with a direct typed toolset;
the safety path and domain result types can remain unchanged.

## P3 — Did `dispatch_request` remain a clean front door?

**Mostly.** `/agui` still ends in one `AGUIAdapter.dispatch_request` call. Real
behavior did not require replacing or subclassing the adapter. It did require the
route to prepare the per-request exposure, pass request-ID deps, pass model settings,
attach the filtered toolset, and bridge structured completion to visible text and a
server-side usage sink.

That is a clean framework boundary, but no longer a one-line feature. The answer is
“one call remains the front door; substantial request policy lives immediately around
it.” Mid-stream exceptions become `RUN_ERROR` events without replacing the endpoint.

## P4 — Does AG-UI buy a better UI protocol?

**It buys vocabulary; it did not buy simplicity here.** The accepted real journey
produced 23 AG-UI events across 9 observed types, including standard run, text,
tool-call, argument, and tool-result lifecycles. The raw control produced 12 events
across 4 observed types. AG-UI made tool progress and run state semantically explicit
instead of inventing names locally.

The browser cost was larger: 140 nonblank lines versus 27 in the deliberately minimal
raw client. Some difference is capability, but much is protocol bookkeeping. Valid
resend required grouping calls by parent assistant message, accumulating argument
deltas, echoing call/results, and preserving encrypted continuity events. One missed
existing-assistant case made the next request invalid.

For this single client and no persistence/interchange requirement, use the raw SSE
control shape. If CopilotKit/AG-UI clients, resumability, or cross-implementation event
compatibility become requirements, the standard vocabulary can justify retaining the
adapter.

## P5 — Where did the black box hurt?

Source/signature inspection was needed to establish:

1. moved imports (`pydantic_ai.mcp`, `pydantic_ai.ui.ag_ui`);
2. the separate FastMCP server extra;
3. current `AgentRunResult.usage` shape;
4. AG-UI call/result and encrypted history continuity;
5. output-tool event behavior and completion callbacks;
6. `ProcessHistory`'s capability API;
7. the reasoning stream-state failure and Ollama's effective
   `reasoning_effort: none` switch.

The running log in `notes/probelog.md` contains the dated evidence. Most friction was
at framework/protocol seams, not in the typed query core.

## P6 — Is full-history resend acceptable?

**Acceptable under the plan's exact turn-10 rule, with reliability warnings.** At the
three declared checkpoints:

| turn | AG-UI request | input tokens | latency | correct |
|---:|---:|---:|---:|---:|
| 1 | 312 bytes | 1,315 | 6.747s | yes |
| 5 | 4,720 bytes | 2,495 | 8.970s | yes |
| 10 | 11,025 bytes | 4,223 | 12.867s | yes |

Turn 10 used 1.61% of the advertised 262,144-token context and took 1.91× the warmed
turn-1 latency, below the required 25% and no-more-than-2× bounds. It remained
correct. The artifact therefore reports `acceptable`.

That narrow verdict hides useful reliability evidence: turn 2 emitted a failure and
turn 8 took 105.87s, while later turns recovered. Do not interpret the threshold pass
as production conversation reliability.

The immutable 34-line tool-pair processor exercised Pydantic AI's `ProcessHistory`
hook. It reduced serialized model history from 28,584 to 11,957 bytes and preserved
the required answer. It did not improve this run's cost: total input rose from 4,223
to 4,771 tokens and latency reached 132.5s because the model needed more work. The
hook saves custom lifecycle plumbing and can reduce payload, but compaction policy
still belongs to the application. The ready-made Harness compaction package exists,
but remained outside this core-only probe.

## P7 — Does the abstraction survive the local model?

**Yes, with prompt and reasoning-stream sensitivity.** The final M3 matrix was 18/18
correct across two schemas and three exposure modes. Core Ollama smoke, AG-UI,
raw-control, and containerized-agent journeys also succeeded. No SQL-only fallback
was needed, so no fallback framework cost is claimed.

The model often used redundant discovery or query calls. An early semantically
looser workload prompt repeatedly timed out where the concrete prompt succeeded.
Gemma reasoning also triggered an AG-UI stream-state error; Ollama's OpenAI endpoint
ignored `think:false`, while `reasoning_effort: none` produced the accepted UI path.
Observed latency outliers and one flaky composed-journey attempt are evidence against
calling the loop uniformly reliable.

## P8 — Which MCP exposure shape won?

All modes passed safety and held-out-schema checks and had at least two correct runs
per case. The final lexicographic scores were:

| mode | correct | model-request macro-median | latency macro-median | input-token macro-median |
|---|---:|---:|---:|---:|
| granular | 6 | 5.5 | 20.872s | 3,720.0 |
| catalog | 6 | 3.5 | 15.629s | 2,197.5 |
| **prefetched** | **6** | **2.5** | **14.229s** | **1,654.5** |

Correctness tied, so lower model-request count decided the ranking before latency or
tokens were needed. Prefetched also had the best latter metrics. Its end-to-end clock
included MCP catalog prefetch and its call sequence records `get_catalog`; it did not
receive an unreported cache. Use prefetched for the app and retain granular first in
declaration order as the control/tie resolver.

## Final recommendation

Keep the typed Pydantic AI core and the schema-generic safety/result model. Use the
prefetched-catalog shape. For the product represented by this probe, replace
in-process MCP with direct typed tools and replace AG-UI with the checked-in minimal
SSE vocabulary. Reverse either replacement only when a concrete interoperability
consumer—not an abstract standards preference—needs that layer.
