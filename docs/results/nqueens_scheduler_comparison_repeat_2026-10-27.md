# Repeated live N-Queens scheduler comparison

Repeated the initial run on 2026-10-27. Per-run data: [`nqueens_scheduler_live_repeat_2026-10-27.csv`](nqueens_scheduler_live_repeat_2026-10-27.csv). Initial run: [`nqueens_scheduler_comparison_initial_2026-10-27.md`](nqueens_scheduler_comparison_initial_2026-10-27.md) and [`nqueens_scheduler_live_initial_2026-10-27.csv`](nqueens_scheduler_live_initial_2026-10-27.csv).

## Setup

- Workload: N-Queens `n=17`, `split_depth=1`, 17 tasks.
- Same two workers: UUIDs beginning `f8f25802` (8 compute threads) and `39c3-d0c7` (7 compute threads).
- 3 runs each: random, round robin, fastest-first, BOINC, and UCB. Each adaptive algorithm was run with stealing off and on. Total: 24 jobs.
- Timing is from submission until a terminal job status, polled every 0.2 seconds. Configurations were run in fixed blocks, not interleaved. Worker speed history was retained during this batch.
- The restarted server began with an empty tracker; its final N-Queens tracker recorded 408 successful task samples (24 × 17) and zero worker failures. In this batch every run's task assignments split 10/7 between the workers.
- The timed script records wall time and task assignments, but does not fetch and verify each run's aggregate solution count. A separate correctness run in the initial session returned 95,815,104 solutions for n=17.

## Results

| Scheduler | Stealing | Runs | Mean s | Median s | SD s | Range s | Mean vs round robin |
|---|---:|---:|---:|---:|---:|---:|---:|
| Random | n/a | 3 | 15.77 | 15.6 | 1.46 | 14.4–17.3 | −9.7% |
| Round robin | n/a | 3 | 17.47 | 17.4 | 0.12 | 17.4–17.6 | baseline |
| Fastest-first | off | 3 | 17.47 | 17.4 | 0.12 | 17.4–17.6 | 0.0% |
| BOINC | off | 3 | 16.93 | 17.0 | 0.12 | 16.8–17.0 | −3.1% |
| UCB | off | 3 | 17.53 | 17.5 | 0.06 | 17.5–17.6 | +0.4% |
| Fastest-first | on | 3 | 18.57 | 19.1 | 1.29 | 17.1–19.5 | +6.3% |
| BOINC | on | 3 | 18.40 | 18.4 | 0.10 | 18.3–18.5 | +5.3% |
| UCB | on | 3 | 17.63 | 17.5 | 0.42 | 17.3–18.1 | +1.0% |

In this batch BOINC without stealing was slightly faster than round robin; fastest-first tied it. The other adaptive settings were similar or slower. Random's times climbed across its three sequential runs (14.4, 15.6, 17.3 s), so its lower mean is confounded by run order or changing worker speed. Every setting assigned 10 tasks to one worker and 7 to the other; the observed differences came from task identity/order and run conditions, not a different task-count split.

## Comparison with the initial batch

| Scheduler | Initial mean s | Repeat mean s |
|---|---:|---:|
| Random | 17.13 | 15.77 |
| Round robin | 14.03 | 17.47 |
| Fastest-first, off | 14.13 | 17.47 |
| BOINC, off | 17.03 | 16.93 |
| UCB, off | 18.17 | 17.53 |
| Fastest-first, on | 17.13 | 18.57 |
| BOINC, on | 15.93 | 18.40 |
| UCB, on | 17.33 | 17.63 |

These batches are **not a controlled before/after comparison**. The server was restarted between them, which cleared the speed tracker; the initial batch started with historical worker measurements, while this repeat started cold. The runs were sequential and grouped by scheduler, and timings shifted materially across batches. With three runs per setting, the small differences should be treated as inconclusive, not as evidence that one algorithm is generally faster.
