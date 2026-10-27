# Live ray-tracing scheduler comparison ? repeat batch, 2026-10-27

Three runs per scheduler, interleaved in randomized scheduler order, on three connected browser workers. Adaptive schedulers used work stealing.

## Configuration

- 1600?1200 image, 200-pixel tiles (48 tasks), 8 samples per pixel, 4 bounces.

## Timing matrix

| Scheduler | Runs (s) | Mean ? SD (s) | Speedup vs random |
|---|---|---:|---:|
| random | 30.92, 38.23, 3.44 | 24.20 ? 18.34 | 1.00? |
| round_robin | 48.33, 52.48, 57.04 | 52.62 ? 4.36 | 0.46? |
| fastest_first | 4.42, 7.94, 3.21 | 5.19 ? 2.45 | 4.66? |
| boinc | 4.03, 5.52, 4.09 | 4.55 ? 0.84 | 5.32? |
| ucb | 4.92, 6.40, 5.15 | 5.49 ? 0.80 | 4.41? |

## Correctness

All 15 jobs completed all 48 tiles with zero failures and valid PNGs: **True**. The PNG SHA-256 is identical across all schedulers and runs in this batch (unique hashes: 1). A decoded RGB comparison also found identical pixels across all 15 images.

Timing spread is large for random and round-robin, and this is a three-run sample. Treat the measured speedups as an early result for these workers and this configuration, not a general performance guarantee.

Raw rows: `raytracing_scheduler_repeat_2026-10-27.csv`. Per-tile counters and assignments: `raytracing_scheduler_repeat_details_2026-10-27.csv`.
