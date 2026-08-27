# AG-UI versus raw-SSE journey

- Model: `gemma4:12b-it-q4_K_M`
- AG-UI: 23 events across 9 event types; success=yes; latency=7.200s.
- Raw SSE: 12 events across 4 event types; success=yes; latency=19.142s.

| variant | Python nonblank lines | browser nonblank lines |
|---|---:|---:|
| Pydantic AI + AG-UI | 199 | 140 |
| hand-rolled + raw SSE | 151 | 27 |

AG-UI supplies standard run, text, tool-call, tool-result, and usage lifecycle events. The raw control supplies only the five event kinds its UI currently needs.
