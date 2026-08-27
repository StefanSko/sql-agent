# Full-history resend experiment

- Model: `gemma4:12b-it-q4_K_M`
- Context limit: 262144
- Assessment: **acceptable**

| turn | request bytes | input tokens | latency | correct |
|---:|---:|---:|---:|---:|
| 1 | 312 | 1315 | 6.747s | yes |
| 5 | 4720 | 2495 | 8.970s | yes |
| 10 | 11025 | 4223 | 12.867s | yes |

## ProcessHistory comparison

- Custom processor: 34 source lines; framework wiring: `pydantic_ai.capabilities.ProcessHistory`.
- Serialized model history: 28584 → 11957 bytes.
- Turn-10 input tokens: 4223 → 4771 (548 more).
- Compacted run correct: yes; context retention: preserved.
- Compacted failure: none.
