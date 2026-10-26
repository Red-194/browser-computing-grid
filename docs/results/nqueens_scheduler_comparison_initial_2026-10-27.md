# Live N-Queens scheduler comparison

Initial live run, measured on 2026-10-27. Raw per-run data: [`nqueens_scheduler_live_initial_2026-10-27.csv`](nqueens_scheduler_live_initial_2026-10-27.csv).

## Setup

- Workload: N-Queens `n=17`, `split_depth=1` (17 uneven search tasks).
- Workers: two browser workers, one with 7 compute threads and one with 8.
- Algorithms: random, round robin, fastest-first, BOINC, and UCB; 3 runs per setting. For adaptive algorithms, stealing was tested both off and on, for 24 timed jobs total.
- Timing: from job submission until the controller reported a terminal status, polled every 0.2 seconds. Each algorithm's runs were sequential and grouped; the first random run may include warm-up effects.
- The controller retained its existing worker speed history throughout the run.
- The controller's N-Queens sample count increased by exactly 408 during the 24 jobs (24 × 17), with no recorded worker failures. A separate correctness run completed all 17 tasks and returned the known `n=17` count of 95,815,104 solutions.

## Live results

| Scheduler | Stealing | Runs | Mean s | Median s | SD s | Range s | Mean vs round robin |
|---|---:|---:|---:|---:|---:|---:|---:|
| Random | n/a | 3 | 17.13 | 14.1 | 5.60 | 13.7–23.6 | +22.1% |
| Round robin | n/a | 3 | 14.03 | 13.9 | 0.42 | 13.7–14.5 | baseline |
| Fastest-first | off | 3 | 14.13 | 14.2 | 0.21 | 13.9–14.3 | +0.7% |
| BOINC | off | 3 | 17.03 | 17.0 | 0.35 | 16.7–17.4 | +21.4% |
| UCB | off | 3 | 18.17 | 17.4 | 1.59 | 17.1–20.0 | +29.5% |
| Fastest-first | on | 3 | 17.13 | 17.2 | 0.31 | 16.8–17.4 | +22.1% |
| BOINC | on | 3 | 15.93 | 16.0 | 0.31 | 15.6–16.2 | +13.5% |
| UCB | on | 3 | 17.33 | 17.2 | 0.23 | 17.2–17.6 | +23.5% |

Random's mean is pulled up by its first 23.6-second run; its other two runs were 13.7 and 14.1 seconds, close to round robin. Fastest-first without stealing also tied round robin. No adaptive setting beat round robin in these measurements. BOINC with stealing was about 6.5% faster than BOINC without stealing, but still slower than round robin.

The sample is small and the configurations were not interleaved, so these results are specific to this run and worker pair. They do not establish that adaptive schedulers are generally slower. The 17-task job gives each algorithm limited opportunity to rebalance work, and small task-count differences can leave one expensive subtree on a slower worker.

## Simulation cross-check

The real scheduler classes were also run in the simulator for 30 seeds on its `uneven_tasks` scenario: 120 heavy-tailed tasks, with four simulated workers at 1x, 1x, 2x, and 4x speed. Task sizes were hidden from the scheduler, as they are for N-Queens. These are simulated seconds, not device measurements.

| Scheduler | Completed | Mean makespan s | Range s | Mean efficiency |
|---|---:|---:|---:|---:|
| Random | 30/30 | 28.82 | 23.52–38.52 | 0.81 |
| Round robin | 30/30 | 28.84 | 23.47–42.93 | 0.82 |
| Fastest-first | 30/30 | 28.92 | 23.13–41.53 | 0.81 |
| BOINC | 30/30 | 27.16 | 23.61–41.44 | 0.86 |
| UCB | 30/30 | 28.80 | 23.13–39.16 | 0.81 |

In this model BOINC is about 5.8% faster than random and round robin on average, but run-to-run ranges overlap widely. The live run did not reproduce a clear BOINC gain.

## Test fix

The N-Queens cost-growth unit test had used `[0] * depth`, which repeats the same queen column and creates invalid prefixes. The estimator correctly assigned those invalid states its floor cost, making the growth assertion fail. The fixture now takes prefixes from a legal odd-columns-then-even-columns solution for the tested board sizes. `tests/test_scheduler_stats.py` passes (29 tests).
