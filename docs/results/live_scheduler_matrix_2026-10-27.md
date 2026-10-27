# Live scheduler comparison — 2026-10-27

Recorded 45 completed jobs across 3 live worker(s).
Adaptive schedulers use work stealing. Random and round-robin do not support it.

## Workers

| Worker | State | Cores | Latency (ms) |
|---|---|---:|---:|
| `51a0-c72e-1bfe-b6c3` | Idle | 7 | 75 |
| `4d80-f908-07c9-9bd2` | Idle | 7 | 113 |
| `90fc5cb5-4159-4612-bb4f-085dd7656638` | Idle | 8 | 1 |

## Timing matrix (mean seconds; standard deviation)

| Workload | Random | Round robin | Fastest first | BOINC | UCB |
|---|---:|---:|---:|---:|---:|
| mandelbrot_800x600_tile50_iter300k | 55.42 ± 3.15 | 49.07 ± 17.15 | 30.47 ± 1.74 | 33.06 ± 6.30 | 26.42 ± 2.76 |
| raytracing_1600x1200_tile200_spp8_b4 | 27.54 ± 16.89 | 35.67 ± 24.22 | 4.74 ± 1.77 | 4.14 ± 0.75 | 5.21 ± 0.65 |

## Speedup versus random

| Workload | Scheduler | Mean speedup |
|---|---|---:|
| mandelbrot_800x600_tile50_iter300k | random | 1.000x |
| mandelbrot_800x600_tile50_iter300k | round_robin | 1.129x |
| mandelbrot_800x600_tile50_iter300k | fastest_first | 1.819x |
| mandelbrot_800x600_tile50_iter300k | boinc | 1.676x |
| mandelbrot_800x600_tile50_iter300k | ucb | 2.098x |
| raytracing_1600x1200_tile200_spp8_b4 | random | 1.000x |
| raytracing_1600x1200_tile200_spp8_b4 | round_robin | 0.772x |
| raytracing_1600x1200_tile200_spp8_b4 | fastest_first | 5.810x |
| raytracing_1600x1200_tile200_spp8_b4 | boinc | 6.647x |
| raytracing_1600x1200_tile200_spp8_b4 | ucb | 5.283x |

## Output correctness

| Workload | Runs | Completed tasks | Failed tasks | PNG checks | PNG hashes per session |
|---|---:|---:|---:|---|---|
| mandelbrot_800x600_tile50_iter300k | 15 | 2880 | 0 | 15/15 valid | 1 each (1 sessions) |
| raytracing_1600x1200_tile200_spp8_b4 | 30 | 1440 | 0 | 30/30 valid | 1 each (2 sessions) |

PNG hashes are compared within each benchmark session. The two ray-tracing sessions used different controller processes, and their encoded PNG hashes differ across sessions. A separate decoded-RGB check of all 15 images in the repeat session found identical pixels across schedulers. The first session retained PNG hashes only, so cross-session pixel equality is not asserted.
This checks scheduler-independent output consistency for these runs; it does not prove the renderer against an external golden image.
Performance claims are limited to this worker mix and these configurations. Review raw rows and per-tile metrics in the companion CSV files.

## Oversized ray-tracing trial (excluded from the matrix)

An initial 4000×4000, 64-sample, 8-bounce run under round-robin took 204.09 s and did not complete: 46/64 tiles completed, 4 failed after three heartbeat-timeout retries, 11 remained assigned, and 3 remained pending. The controller was restarted and the comparison was rerun with the smaller ray-tracing configuration below. The failed trial is excluded from timing and hash summaries; its per-tile rows remain in the details CSV under job `2022870d-bcd3-4b3b-ab66-0557f2d2473f`.

## Workloads

- Mandelbrot: 800×600, tile 50, 300,000 maximum iterations.
- Ray tracing: 1600×1200, tile 200, 8 samples per pixel, 4 bounces.
