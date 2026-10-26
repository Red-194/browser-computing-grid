# Adaptive scheduler: results and status

Measured on 2026-10-26. Raw data: [`scheduler_comparison.csv`](scheduler_comparison.csv) (40 rows). To add runs:
`scripts/bench_scheduler.py`. Design and history: [`../project_context.md`](../project_context.md), section 5.

## Verdict

**The adaptive scheduler works.** On a job whose tasks differ greatly in size, run on two devices that differ greatly in
speed, the adaptive algorithms (`fastest_first`, `boinc`, `ucb`) finish in about **13 s against 28 s for `random`**, a
**2.2x speedup**, with low run-to-run spread (sd 0.5 s against 3.5 s). The mechanisms behind it (speed learning, finish-time
assignment, adaptive queue sizes, timeouts, reallocation, quarantine, work stealing) are each covered by unit tests and
have been seen working on real devices.

**It is not yet shown to help everywhere.** There is no measured gain on N-Queens, none when the devices are equally fast,
and the effect of work stealing on its own is not measurable in these runs. Only two devices were used. Details below.

## Setup

| | |
|---|---|
| Devices (sessions S2, S3) | Laptop Chrome tab (up to 8 compute threads, CPU priority lowered with `nice 5`) and a phone browser tab. The phone is about 50x slower per unit of work on Mandelbrot by the tracker's own measurement (6.3e-6 s/unit against 1.2e-7 s/unit). |
| Devices (session S1) | Laptop Firefox and Chrome tabs, Chrome slowed about 3x with 14 busy-loop processes. This was before the thread pool and before the sampled Mandelbrot cost. |
| Job | Mandelbrot, whole set (x -2.0..0.6, y -1.2..1.2), 800x600, tile 50, 192 tasks. S2 and S3: 300,000 iterations. S1: 100,000. About 70% of tiles finish in under 1 ms; about 25% take around 1 s (S1 measurement of per-task times). |
| Scheduler options | `GRID_SCHEDULER` / `PUT /scheduler`; stealing switched with `{"stealing": ...}`. |
| Metric | Wall-clock seconds from submitting the job until the job reports done (polled every 0.2 s), so precision is about 0.2 s. |
| Controls | Same job, same two devices, same server process, runs interleaved by configuration. The first run of each session (untrained scheduler) is recorded as `learning` and excluded from the statistics. |

Sessions: **S1** before the thread pool, with the old equal-cost Mandelbrot model. **S2** with the sampled Mandelbrot cost
model but before the avoid-rule fix (commit `3ca44a3`). **S3** after that fix.

## Main result (Chrome + phone, Mandelbrot 300k iterations, S2 and S3 pooled)

One S2 run (63.4 s) is excluded as a known bug, explained below; every other run is included.

| scheduler | stealing | runs | mean s | sd s | min | max | speedup vs random |
|---|---|---|---|---|---|---|---|
| random | n/a | 5 | 27.8 | 3.5 | 25.1 | 31.9 | 1.00x |
| round_robin | n/a | 2 | 29.5 | 0.0 | 29.5 | 29.5 | 0.94x |
| fastest_first | off | 2 | 13.2 | 0.9 | 12.5 | 13.8 | 2.12x |
| fastest_first | on | 5 | 13.1 | 0.5 | 12.6 | 13.6 | 2.13x |
| **boinc** | off | 2 | 12.8 | 0.0 | 12.8 | 12.8 | 2.17x |
| **boinc** | on | 5 | **12.6** | 0.5 | 12.2 | 13.4 | **2.20x** |
| ucb | on | 4 | 13.0 | 0.7 | 12.2 | 13.8 | 2.14x |

Pooled: the 18 adaptive runs average **12.9 s (sd 0.5)** against **27.8 s (sd 3.5)** for 5 `random` runs, a ratio of **2.16x**.

S3 alone (cleanest: all after the fix, 3 runs each): boinc 12.4 s, fastest_first 13.2 s, ucb 13.3 s, random 27.6 s.

Notes on reading this:
- `boinc` was the most consistent (sd 0.2 s in S3) and the fastest in every comparison, but the gap to `fastest_first` and
  `ucb` (about 0.5 to 0.9 s) is within the spread, so the three adaptive algorithms are not separated by these data.
- `round_robin` and `random` are blind to speed, so the phone receives about the same number of tasks as Chrome and its
  share of heavy tiles sets the finish time. The adaptive ones give the phone mostly the near-empty tiles.
- The tasks-per-worker counts in the CSV are task counts, not amounts of work: most of the phone's tasks are tiles that
  finish instantly. Do not read them as load shares.

## Cost model: before and after (the reason for the result above)

| | Cost model | Setup | random | fastest_first | speedup |
|---|---|---|---|---|---|
| S1 | every tile costs the same (`tile_size^2 * max_iterations`) | Firefox + slowed Chrome | 30.8 s | 34.0 s (stealing off), 31.4 s (on) | 0.90x to 0.98x |
| S2/S3 | sampled from a 4x4 grid of pixels per tile | Chrome + phone | 27.8 s | 13.1 s | 2.13x |

With the equal-cost model the adaptive scheduler could not tell the heavy tiles from the empty ones and did no better than
`random` (slightly worse). The sampled estimate ranks 48 test tiles against their true iteration counts with a rank
correlation of **0.995**, totals within **11%** of the true total, and takes **0.28 s for 20,000 tiles** on the controller.
(S1 and S2/S3 differ in devices and in thread pool, so the two rows show the direction, not a controlled single-variable
comparison.)

## Work stealing

- The mechanism works: copies are sent to an idle worker, the first answer wins, the losing copy's slot is freed, results
  stayed correct. Unit tests: `tests/test_work_stealing.py`.
- **Its benefit is not measurable in these data.** `fastest_first`: 13.1 s with stealing (5 runs) against 13.2 s without
  (2 runs). `boinc`: 12.6 s against 12.8 s. These differences are far below the spread.
- Earlier, on two equally fast devices, stealing fired a few times at the end of a job and the original always won.
- What would show a benefit: a job whose tail is one huge task held by a slow device while a fast one idles, with the queue
  empty. The Mandelbrot job here rarely reaches that state.

## Defect found and fixed during this testing

One `ucb` run took **63.4 s** instead of about 13 s (CSV row marked OUTLIER). Cause: the rule that keeps a task taken back
from a worker from returning straight to it held the heaviest tile for the phone, about 50x slower, while the fast Chrome
tab sat idle. Stealing could not help, because a waiting task disables it. Fix (`3ca44a3`): hold a task for another
worker only if that worker is at most 3x slower for it. After the fix, the 9 adaptive Mandelbrot runs of S3 (three each for
`fastest_first`, `boinc` and `ucb`) showed no outlier.

## N-Queens (same devices, single runs)

| job | random | boinc + stealing |
|---|---|---|
| n=16, depth 4: 19,688 tiny tasks | 2.3 s | 2.3 s |
| n=17, depth 1: 17 big tasks | 10.1 s | 12.7 s |

No gain. The tiny-task job is limited by message handling, not by which worker gets which task. The 17-task result favours
`random` by 2.6 s from one run each, so it may be noise or may be a real cost of the adaptive path on a few big tasks;
it was not repeated.

## Related performance changes (same session, not scheduler-specific)

Measured on the laptop Firefox and Chrome tabs, same jobs before and after:

| job | start of session | after |
|---|---|---|
| N-Queens n=16, depth 4 (19,688 tiny tasks) | 182 s | 2.5 s |
| Mandelbrot whole set, 100k iterations | 23.3 s | 3.3 to 4.3 s |
| N-Queens n=17, depth 1 (17 big tasks) | 55 to 60 s | 8 to 12 s |

Causes: one compute thread per tab became a pool, queue sizes counted per thread, tasks and results are batched, and the
controller stopped recomputing every waiting task's cost on each dispatch (quadratic in job size).

## Recovery (tested live)

Closing a worker mid-job (N-Queens n=17, 2,786 tasks), twice: the job finished with the correct answer
(95,815,104 solutions) in 100.6 s and 104.5 s, against 53 s with both workers. The second run logged
"requeueing 8 running task(s)"; the first predates that log line.

## What is verified, and how

| Capability | Evidence |
|---|---|
| Per-worker, per-workload speed learning | `tests/test_scheduler_stats.py`; live `GET /scheduler/stats` |
| Finish-time assignment, hold-back, size matching (`boinc`) | `tests/test_scheduler_algorithms.py`; the Mandelbrot runs above |
| Adaptive queue sizes (per thread) | `tests/test_scheduler_stats.py`; live capacity values |
| Timeouts, reallocation, quarantine | simulator and `tests/test_scheduler_integration.py`; seen live (task timeouts requeued) |
| Work stealing, attempt handling | `tests/test_work_stealing.py`; seen live |
| Recovery from a lost worker | `tests/test_reconnect_and_failed_job.py`; two live runs |
| Whole suite | 246 tests pass |

## SAT (2026-10-27)

Raw rows are in `scheduler_comparison.csv` (sessions S6, S6b, S7, c90b, P1, P2). Task prices come from the SAT cost model (see
`project_context.md`, "SAT cost model"): a closed-form model for whole instances and Knuth tree-size estimates for cubes.

**Does the price match the browser?** Per-task `execution_time_ms` was recorded and compared with the price (Spearman rank
correlation, 2 headless Chrome tabs):

| Check | Spearman |
|---|---|
| Solver clause visits (Python port) against browser ms, 100 instances | 1.00 |
| Closed-form price against browser ms, 100 mixed-size instances | 0.78 (variable count alone also 0.78) |
| Closed-form price, 96 instances of 50 variables at ratios 3.0 to 6.0 | 0.67 (clause count alone 0.41) |
| Knuth price (8 dives) against browser ms, 64 cubes of a 90-variable formula | 0.78 |

**Scheduler comparison.** Median seconds (range) on 100 mixed instances of 60 to 85 variables, 5 to 6 runs each:

| Setup | random | round_robin | fastest_first | boinc (stealing on / off) | ucb |
|---|---|---|---|---|---|
| 4-thread tab + 1-thread tab, one CPU | 4.0 (3.4 to 6.7) | 5.6 (4.1 to 8.4) | 3.7 (3.1 to 10.1) | 7.1 (3.1 to 9.8) / 5.4 (3.2 to 8.8) | 4.6 (3.4 to 8.8) |
| 4-thread tab + phone (about 5x slower per task) | 3.2 (2.8 to 4.4) | 3.7 (2.6 to 4.4) | 3.3 (2.8 to 4.0) | 3.3 (2.8 to 4.2) / 3.5 (2.6 to 4.5) | 3.8 (3.5 to 3.9) |

- **No scheduler beats `random` on SAT.** The spread of one scheduler (3 s to 10 s) is larger than any gap between them.
  Instances of the same size differ up to 30x in work, so the finish time is set by who gets the rare very hard instance.
- Cube jobs (90 variables, depth 6) are about 0.4 s of compute and finish in about 0.9 s for every scheduler, so they
  cannot separate the schedulers.
- A fix made on the way: `finish_time` treated a 4-thread tab as running one task at a time, which gave a 1-thread tab half
  the work; it now divides the queue by the thread count.
- Pricing cost: Knuth dives run on the controller at submit. 8 dives on a 64-cube, 90-variable job took 3 s end to end (about
  1 s of it pricing); 3 dives take 0.9 s.
- Caveats: random 3-SAT only; the first setup shares one CPU between the tabs; the phone setup has one phone.

## Limitations (read before citing these numbers)

1. **Two devices only**, one of them 50x slower. The project target is up to 10 devices.
2. **Small samples**: 2 to 5 runs per configuration. The adaptive-versus-random gap is large compared with the spread, but the
   differences among `fastest_first`, `boinc` and `ucb`, and the effect of stealing, are not resolved.
3. **One workload shows the gain.** Mandelbrot is where task sizes can be estimated. N-Queens (a fitted curve) and SAT (a model of
   the solver's work, see the SAT section) can only be estimated roughly, and there the result is a tie or worse.
4. The Chrome tab ran with lowered CPU priority throughout S2 and S3, so absolute times are slower than they would otherwise be.
   All configurations share this, so comparisons are fair, but absolute seconds should not be quoted as the system's speed.
5. The phone is a consumer device on Wi-Fi; its connection dropped once (screen lock) after the S2 runs.
6. The default scheduler is still `random`. Choosing a default is an open decision.
7. Timing resolution is about 0.2 s (job-status polling).

## Reproduce

```bash
GRID_SCHEDULER=boinc uvicorn app.main:app --host 0.0.0.0 --port 8000      # then open /worker on each device
python scripts/bench_scheduler.py job.json --session S4 --workload mandelbrot_whole_set_300k \
    --configs random round_robin fastest_first:off fastest_first:on boinc:on ucb:on --runs 3
```

The job file for the main result is the Mandelbrot config above (`width 800, height 600, tile_size 50,
x -2.0..0.6, y -1.2..1.2, max_iterations 300000`). Run one untrained job first so the scheduler has speed data.
