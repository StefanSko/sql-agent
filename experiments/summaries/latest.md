# Exposure experiment summary

- Executed: 2026-08-27T11:36:06.679542+00:00
- Model: `gemma4:12b-it-q4_K_M` (`4eb23ef187e2c5462566d6a1d3bbbc2f1346d0b4327cbb66d58fffbcc9b2b05c`)
- Workload: v1
- Repetitions: 3

| mode | eligible | correct | request macro-median | latency macro-median | input-token macro-median |
|---|---:|---:|---:|---:|---:|
| granular | yes | 6 | 5.50 | 20.872s | 3720.00 |
| catalog | yes | 6 | 3.50 | 15.629s | 2197.50 |
| prefetched | yes | 6 | 2.50 | 14.229s | 1654.50 |

- Evidence winner(s): **prefetched**
- Provisional application mode: **prefetched**
- Exact tie: **no**

Failed repetitions count against correctness and are excluded from metric medians.
