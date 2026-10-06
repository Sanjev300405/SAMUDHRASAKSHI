# synth.run_experiments results

N = 100 synthetic twins (100 produced at least one M5-surviving candidate).

| Metric | Value |
|---|---|
| **Top-1 attribution hit-rate** | **37.0%** |
| Top-3 attribution hit-rate | 79.0% |
| Origin recovery error (mean) | 7.161 km |
| Origin recovery error (median) | 6.594 km |
| True release inside high-prob region | 4.0% |
| Mean latency per case | 3.52 s |

## Ablation — does M6 earn its 0.35 weight?

| Ranking method | Top-1 hit-rate |
|---|---|
| Proximity-only (spatial S alone) | 60.0% |
| Full fusion (A, all 5 factors) | 37.0% |
| Fusion with drift term removed | 32.0% |
