# Composed-path evidence

The checked-in topology contains `agent-api`, private `ollama`, one-shot
`ollama-init`, and profiled seeded Postgres. The agent image built as
`sha256:c9be2d059947…`; the seeded Postgres + agent containers completed the
representative AG-UI NL→SQL acceptance against the exact host Ollama model and digest.
One prior run emitted `RUN_ERROR`, then the accepted run passed; this is reliability
evidence, not discarded benchmark data.

The **full Compose topology was not executed** in this environment. The installed
Docker CLI has no Compose plugin, the official ARM Ollama image's 2.64 GB layer did
not finish pulling in two bounded attempts, and the Docker VM has 3.8 GB RAM versus
the installed model's 7.0 GB footprint. `experiments/composed/latest.json` records the
exact boundary and image metadata. The complete real-Ollama all-mode workload remains
the PGlite/in-process artifact in `experiments/records/latest.json`; it must not be
mislabelled as a fully containerized run.
