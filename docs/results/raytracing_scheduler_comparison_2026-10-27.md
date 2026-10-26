# Live ray-tracing scheduler comparison — 2026-10-27

Compared Round Robin with BOINC, the adaptive scheduler, on the live browser grid.
Each job used the same deterministic scene and config: **4000×4000**, 512-pixel
tiles (64 tasks), 64 samples per pixel, and 8 reflection bounces. The configs
were interleaved for three runs each: Round Robin, BOINC, then repeat. Both
workers were online for all six jobs; every job completed with 64/64 tiles and
zero failed tasks. BOINC had work stealing enabled. The workers had speed data
from the preceding completed ray-tracing job.

| Run | Round Robin | BOINC | BOINC change |
|---:|---:|---:|---:|
| 1 | 31.3 s | 31.3 s | 0.0 s |
| 2 | 32.9 s | 18.1 s | −14.8 s |
| 3 | 47.0 s | 49.4 s | +2.4 s |
| **Mean** | **37.1 s** | **32.9 s** | **−11.1%** |
| Median | 32.9 s | 31.3 s | — |

The average favored BOINC, but the three paired runs do not establish a reliable
winner: BOINC was much faster in run 2, tied in run 1, and slower in run 3. Run
time varied substantially between repeats, so treat the 11.1% mean difference as
an early signal rather than a general performance claim.

## Worker assignments

Counts are final task owners, with Android first and local Firefox second:

| Scheduler | Run 1 | Run 2 | Run 3 |
|---|---:|---:|---:|
| Round Robin | 14 / 50 | 7 / 57 | 14 / 50 |
| BOINC | 19 / 45 | 12 / 52 | 29 / 35 |

The local Firefox worker was faster per task in this session. Round Robin gave
it more tasks as it freed slots sooner. BOINC shifted the split between runs,
though it did not consistently concentrate assignments on the faster worker.

## Cost-estimator check

The detailed CSV contains **384 tile rows** (64 tiles × 6 jobs), including
estimated cost, actual ray/intersection work, execution time, and worker UUID.
Across those rows, estimated cost ranked actual work closely (Spearman **0.993**;
Pearson **0.998**). Actual work versus execution time had Spearman **0.535** when
both devices were combined, reflecting their different speeds; within each
worker the correlations were **0.878** on Android and **0.977** on Firefox.

## Artifacts

- Summary timings and assignments: `raytracing_scheduler_comparison_2026-10-27.csv`
- Per-tile estimates, work counters, timings, assignments, and job IDs:
  `raytracing_scheduler_details_2026-10-27.csv`

The benchmark ran live through the normal controller and browser workers. No
scheduler simulator was used.
