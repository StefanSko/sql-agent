# Visual field guide

These are self-contained HTML artifacts with no runtime or external asset dependency:

- [`architecture.html`](architecture.html) — system boundaries and the motivation behind each major choice.
- [`call-stack.html`](call-stack.html) — request/return call path, interface types, and direct source links.
- [`benchmarks.html`](benchmarks.html) — experiment design, ranking, statistics, interpretation, and limitations.
- [`protocols.html`](protocols.html) — handshake-era versus sessionless MCP plus FastMCP 4, direct tools, deferred discovery, Code Mode, CLI, and Agent Skills options for this in-memory agent.
- [`verdict.html`](verdict.html) — motivated keep/replace decisions and visual, reversible improvement paths.
- [`validation/index.html`](validation/index.html) — five creative, falsifiable experiment options for validating or overturning the verdict.

Open them locally:

```bash
open artifacts/architecture.html
open artifacts/call-stack.html
open artifacts/benchmarks.html
open artifacts/protocols.html
open artifacts/verdict.html
open artifacts/validation/index.html
```

Code links are pinned to implementation commit `b3072c2`; local `data-code-ref` annotations are checked against repository paths and line counts by the test suite.
