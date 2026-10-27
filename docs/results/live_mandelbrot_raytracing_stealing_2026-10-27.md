# Live Mandelbrot and ray-tracing stress test — 2026-10-27

Ran 3 jobs per workload through the live browser controller with **boinc** scheduling and work stealing **true**.

## Configuration

- Mandelbrot: 1024×768, 64-pixel tiles (192 tasks), 300,000 maximum iterations.
- Ray tracing: 2000×2000, 250-pixel tiles (64 tasks), 32 samples per pixel, 6 bounces.
- Online worker snapshot: `[{"uuid":"20c3-4744-5ac8-b8f8","ip":"10.109.43.248","state":"Idle","cores":7,"memory":0.0,"latency":0}]`

## Results

| # | Workload | Job ID | Wall time | Tasks complete | Failed | PNG | Worker IDs |
|---:|---|---|---:|---:|---:|---|---|
| 1 | mandelbrot | `d54ba309-5376-4549-aa3d-dde603ffb78a` | 58.51s | 192/192 | 0 | valid, 2,073 bytes | 20c3-4744-5ac8-b8f8 |
| 2 | raytracing | `09dac961-654b-41d9-9b5c-3d261b82022e` | 42.03s | 64/64 | 0 | valid, 590,926 bytes | 20c3-4744-5ac8-b8f8 |
| 3 | mandelbrot | `e9fd0112-682f-44e4-a312-77df824def7c` | 69.52s | 192/192 | 0 | valid, 2,073 bytes | 20c3-4744-5ac8-b8f8 |
| 4 | raytracing | `94531e25-0aa8-4b12-a069-61e0f6e96282` | 45.41s | 64/64 | 0 | valid, 590,926 bytes | 20c3-4744-5ac8-b8f8 |
| 5 | mandelbrot | `eb7fd9e7-5fb7-4664-b585-0d1adbb14b2c` | 95.19s | 192/192 | 0 | valid, 2,073 bytes | 20c3-4744-5ac8-b8f8 |
| 6 | raytracing | `9864b6d7-abd5-4d1c-ae32-bbe1986f9482` | 37.96s | 64/64 | 0 | valid, 590,926 bytes | 20c3-4744-5ac8-b8f8 |

## Timing summary

- mandelbrot: mean 74.41s, median 69.52s, runs 58.51, 69.52, 95.19s.
- raytracing: mean 41.80s, median 42.03s, runs 42.03, 45.41, 37.96s.

## Ray-tracing work counters

| # | Primary rays | Total rays | Sphere tests | Shadow rays | Reflection rays |
|---:|---:|---:|---:|---:|---:|
| 2 | 128,000,000 | 922,463,134 | 4,748,358,267 | 442,863,981 | 259,818,276 |
| 4 | 128,000,000 | 922,463,134 | 4,748,358,267 | 442,863,981 | 259,818,276 |
| 6 | 128,000,000 | 922,463,134 | 4,748,358,267 | 442,863,981 | 259,818,276 |

## Work-stealing coverage

The controller reported work stealing `true` for scheduler `boinc` during these runs.
The live worker snapshot contained 1 online worker(s). Work stealing requires an idle worker to duplicate a task held by another worker; with fewer than two online workers, the cross-worker stealing path cannot activate. These runs validate the workloads and scheduler configuration, not the multi-worker steal path.

All six jobs reported done, all tiles completed without failures, and each returned a PNG with a valid signature.
