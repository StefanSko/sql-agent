# Demo SQL execution benchmark

Dataset: demo-v1; split: development
Model: gemma4:12b-it-q4_K_M (4eb23ef187e2c5462566d6a1d3bbbc2f1346d0b4327cbb66d58fffbcc9b2b05c)

This scores complete final query results, not natural-language answer correctness.
Column names, row order, duplicates and prescribed rounding are part of the contract.
Timeouts/errors count as failures. Latency includes all attempts and cold starts.

| Difficulty | Correct / attempted | Accuracy | Median latency |
|---|---:|---:|---:|
| easy | 1/1 | 100.0% | 8.26s |
| hard | 1/1 | 100.0% | 24.38s |
| expert | 0/1 | 0.0% | 90.01s |
| all | 2/3 | 66.7% | 24.38s |
