# Hand-rolled control (immutable)

The original pre-repository control could not be recovered from Git history (`b39e2c4`
contains only `Agents.md` and `plan.md`). M0 therefore reconstructed this minimal
OpenAI-compatible tool loop and raw-SSE UI as the concrete P1/P4 comparison.

It deliberately uses the same canonical in-process FastMCP server and database safety
path as the Pydantic AI variant. The changing variable is the agent loop and event
protocol: `agent.py` is a direct request/tool loop and `app.py` emits five raw event
kinds rather than AG-UI.

Run it with the same required `SQL_AGENT_*` environment as the main app:

```bash
uv run uvicorn baseline.hand_rolled.app:create_app --factory --port 8001
```

The control is pinned to source revision **M0 reconstruction, 2026-08-27**. Do not
revise it to track later framework behavior; comparison notes belong in
`notes/probelog.md` and `notes/verdict.md`.
