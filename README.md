# Browser Computing Grid

A zero-install, browser-native distributed computing system. Browser tabs volunteer CPU as **workers**; a FastAPI **controller** splits a submitted job into tasks, schedules them across connected workers, collects the results, and reassembles a final answer. Each task executes inside a WebAssembly **runtime** compiled from Rust, running directly in the worker's browser tab — no native install, no drivers, no client software.

## What problem it solves

Distributed / volunteer computing normally requires installing a client (BOINC, Folding@home-style agents, etc.), which limits who can participate and adds administrative friction. Browser Computing Grid removes that barrier: a device joins the grid by opening a webpage at `/worker` and stays a worker for as long as that tab is open. Work runs sandboxed inside the browser's WASM engine — nothing is installed, and nothing outlives the tab.

## How it works, at a glance

```
Client              Controller (FastAPI)                Worker (browser tab)
  │                        │                                    │
  │   POST /jobs           │                                    │
  ├───────────────────────►│                                    │
  │                        │  job → splitter → tasks             │
  │                        │  tasks → scheduler → assignments    │
  │                        │                                    │
  │                        │──── task (WebSocket /ws) ──────────►│
  │                        │                                    │  WASM runtime
  │                        │                                    │  executes kernel
  │                        │◄─── task_result (WebSocket) ────────│
  │                        │                                    │
  │                        │  aggregator.add_result(...)        │
  │                        │  (repeats until job complete)       │
  │                        │                                    │
  │   GET /jobs/{id}/result│                                    │
  ├───────────────────────►│                                    │
  │◄─── final result ──────┤                                    │
```

A **dashboard** at `/dashboard` (localhost only) watches the worker registry live over Server-Sent Events.

## What makes this different from just running a local program

The computation is decomposed into many small, independent tasks and physically executed across whichever browser tabs happen to be connected at the time — potentially many separate, heterogeneous machines — rather than on one process on one machine. Workers can join and leave (tab closed, network drop) without the controller process going down; the registry just marks them offline. None of this requires the participating devices to trust or install anything beyond a browser tab.

## Major components

| Component | Where | Role |
|---|---|---|
| **Controller** | `app/` (FastAPI) | Registers workers, accepts job submissions, runs the splitter/scheduler/aggregator pipeline, serves the dashboard feed |
| **Worker** | `app/static/js/worker.js` + `app/templates/worker.html` | Browser tab: registers over WebSocket, receives tasks, runs them in WASM, reports results |
| **Runtime** | `runtime/` (Rust → WASM, via `wasm-bindgen`) | Sandboxed compute engine loaded into the worker tab; exposes `execute_task(workload, config)`, dispatching to a per-workload **kernel** |
| **Dashboard** | `app/templates/dashboard.html` + `app/static/js/dashboard.js` | Localhost-only live view of connected workers over SSE |

See [docs/architecture.md](docs/architecture.md) for the full breakdown of every module.

## Current workloads

The job/task pipeline is designed to be workload-agnostic: a job carries a typed, workload-specific config; a **splitter** turns a job into tasks; a WASM **kernel** executes each task; and an **aggregator** combines task results back into a final job result. All three are resolved dynamically by workload name (`app/services/loader.py`).

Mandelbrot is the visual reference workload. SAT is a distributed CNF search
workload: the controller partitions the first `split_depth` variables into
independent assignments, sends each assignment cube to a worker, and returns
the first satisfying model found (or UNSAT once every cube fails).

| Workload | Job/task config | Splitter | WASM kernel | Aggregator | Status |
|---|---|---|---|---|---|
| `mandelbrot` | ✅ (`MandelbrotConfig` / `MandelbrotTaskConfig`) | ✅ | ✅ | ✅ | **Fully working end-to-end** |
| `sat` | ✅ (`SATConfig` / `SATTaskConfig`) | ✅ | ✅ | ✅ | **Requires rebuilt WASM runtime** |
| `sat_batch` | ✅ (`SATBatchConfig`; tasks reuse `SATTaskConfig`) | ✅ | ✅ (reuses `sat`) | ✅ | **Python only; same WASM as `sat`** |
| `compression` | ✅ (`CompressionConfig` / `CompressionTaskConfig`) | ✅ | ✅ (LZ4, Zstandard) | ✅ | **Requires rebuilt WASM runtime** |
| `regex` | ✅ (`RegexConfig` / `RegexTaskConfig`) | ✅ | ✅ (`fancy-regex`) | ✅ | **Requires rebuilt WASM runtime** |
| `nqueens` | ✅ (`NQueensConfig` / `NQueensTaskConfig`) | ✅ | ✅ | ✅ | **Requires rebuilt WASM runtime** |

Other workloads (e.g. Monte Carlo, matrix multiplication) are **not currently implemented**. The extension points that would let a future workload be added without redesigning the pipeline are described in [docs/architecture.md](docs/architecture.md).

## Scheduler

Tasks are handed out as workers have free slots, and a scheduler decides which task goes to which worker. Five algorithms are built in, in `app/services/scheduler/`:

| Name | What it does |
|---|---|
| `random` | Baseline: a random worker with a free slot (the default) |
| `round_robin` | Baseline: the workers in turn |
| `fastest_first` | The worker that would finish the task soonest, from measured speed |
| `boinc` | Adaptive, in the style of BOINC: biggest tasks first to the fastest workers, retried tasks only to reliable workers |
| `ucb` | `fastest_first` plus a bonus for workers it has little data on |

The adaptive ones learn each worker's speed per workload from the time every result reports, size each worker's queue from that speed, and leave out a worker that keeps timing out. A background monitor also takes tasks back from a worker that stays connected but stops answering, and a task taken back waits for a different worker instead of returning to the one it left. **Work stealing:** near the end of a job, a worker that has gone idle also runs a task that is still running elsewhere, and the first answer wins (it is on for `fastest_first`, `boinc` and `ucb`, off for the two baselines). Choose the algorithm at start-up with the `GRID_SCHEDULER` environment variable (for example `GRID_SCHEDULER=boinc`), or switch it while the server runs:

```bash
curl http://127.0.0.1:8000/scheduler                       # active and available
curl -X PUT http://127.0.0.1:8000/scheduler -H "Content-Type: application/json" -d '{"name": "boinc"}'
curl -X PUT http://127.0.0.1:8000/scheduler -H "Content-Type: application/json" -d '{"stealing": false}'   # work stealing on or off
curl http://127.0.0.1:8000/scheduler/stats                 # what has been measured per worker
python scripts/simulate_schedulers.py                      # compare them on a simulated grid
```

See [docs/project_context.md](docs/project_context.md) for the design, the simulation results and the open items, and [docs/results/scheduler_results.md](docs/results/scheduler_results.md) for the measured comparison (adaptive about 2.2x faster than `random` on Mandelbrot with a laptop and a phone; no gain shown yet on N-Queens).

## Result model

A job's result is retrieved generically: the controller looks up the job's aggregator and returns `aggregator.get_result()` with media type `aggregator.result_type`. The controller does not know or care that the current aggregator happens to produce a PNG — that logic (pixel-buffer reconstruction and PNG encoding) lives entirely inside `MandelbrotAggregator`. A future workload's aggregator would return a different result type without any change to the result endpoint.

## Install & run

### Prerequisites

- Python 3.12+
- Rust + `wasm-bindgen`, only if you need to rebuild the runtime (a prebuilt `runtime/pkg/` is already checked in and is what the app serves)
- A modern browser (Chrome, Firefox, Edge)

### Install dependencies

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Start the controller

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Connect a browser worker

Open `http://<controller-ip>:8000/worker` in any browser on the network (the controller's own machine can use `127.0.0.1`). The tab registers itself over `/ws`, and appears in the dashboard within a few seconds.

### Watch the grid

Open `http://127.0.0.1:8000/dashboard` (localhost only — remote requests to `/` or `/dashboard` are redirected to `/worker` instead).

### Submit a job

```bash
curl -X POST http://127.0.0.1:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "workload": "mandelbrot",
    "config": {
      "width": 256, "height": 256,
      "x_min": -2.5, "x_max": 1.0,
      "y_min": -1.0, "y_max": 1.0,
      "max_iterations": 500,
      "tile_size": 128
    }
  }'
```

### Submit a SAT job

Clauses use standard DIMACS literals: `1` means variable 1, `-1` means its
negation, and each inner array is OR-ed while clauses are AND-ed. `split_depth`
creates `2^split_depth` independent worker tasks.

```bash
curl -X POST http://127.0.0.1:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "workload": "sat",
    "config": {
      "num_variables": 3,
      "clauses": [[1, 2], [-1, 3], [-2, -3]],
      "split_depth": 2
    }
  }'
```

Once complete, `GET /jobs/<job_id>/result` returns JSON such as
`{"satisfiable":true,"model":[1,-2,3]}`. Rebuild `runtime/pkg/` after pulling
the SAT kernel source so browser workers can execute it.

The response includes the generated `job_id` and the task→worker assignments made at submission time.

### More workloads

All of these use the same `POST /jobs` call and the same `GET /jobs/<job_id>/result`
(they all return JSON). Rebuild `runtime/pkg/` first (see `docs/commands.md`).

**`sat_batch`** - many independent SAT instances, one task each. Give `instances`,
or let the controller make random 3-SAT formulas (about 4.26 clauses per variable
is the hardest region, so run times vary the most):

```bash
curl -X POST http://127.0.0.1:8000/jobs -H "Content-Type: application/json" -d '{
  "workload": "sat_batch",
  "config": {"random_3sat": {"count": 200, "num_variables": 40, "num_clauses": 170, "seed": 1}}
}'
```

**`compression`** - cuts the data into `chunk_size` pieces and tries every
variant (`lz4`, `zstd-fastest`) on every piece. Use
`synthetic_size` for made-up test data (max 64 MiB) or `data_base64` for your own.
The result has size ratio, speed and round-trip checks per variant:

```bash
curl -X POST http://127.0.0.1:8000/jobs -H "Content-Type: application/json" -d '{
  "workload": "compression",
  "config": {"synthetic_size": 8000000, "chunk_size": 262144,
             "variants": ["lz4", "zstd-fastest"]}
}'
```

To compress a **real file** (max 64 MiB), upload it instead of using `synthetic_size`.
Each chunk is sent to a worker, compressed with every variant, decompressed again to
check it round-trips, and the sizes and speeds are totalled per variant:

```bash
curl -X POST http://127.0.0.1:8000/jobs/compression/upload   -F "file=@/path/to/your/file" -F "variants=lz4,zstd-fastest" -F "chunk_size=262144"
# or, with polling and printing the result:
python scripts/compress_file.py /path/to/your/file
```

**`regex`** - every pattern against every batch of `texts_per_task` texts.
`mode` is `match` (does it match?) or `scan` (count every match). A bad pattern
is reported as `compile_error`, and `limit_hits` counts texts where the engine hit
`backtrack_limit`:

```bash
curl -X POST http://127.0.0.1:8000/jobs -H "Content-Type: application/json" -d '{
  "workload": "regex",
  "config": {"patterns": ["[a-f]+z", "(a+)\\1b"],
             "synthetic_texts": {"count": 5000, "min_length": 20, "max_length": 400, "seed": 1},
             "texts_per_task": 250, "mode": "scan", "backtrack_limit": 100000}
}'
```

**`nqueens`** - counts all solutions. `split_depth` fixes the queens on the first
rows, giving one task per safe prefix. Tasks are very uneven, which is the point.
`n=8` has 92 solutions and `n=12` has 14200. Try `n` up to about 15 for a demo:

```bash
curl -X POST http://127.0.0.1:8000/jobs -H "Content-Type: application/json" -d '{
  "workload": "nqueens",
  "config": {"n": 13, "split_depth": 3}
}'
```

Every result also shows execution times, which come from the worker's own
`execution_time_ms`.

### Retrieve the result

```bash
curl http://127.0.0.1:8000/jobs/<job_id>/result --output result.png
```

Returns the aggregator's result (`image/png` for Mandelbrot) once the job is complete; otherwise returns a "still processing" message.

### Run tests

```bash
# Python: splitter + aggregator unit tests
pytest tests/

# Rust: WASM kernel unit tests
cd runtime
cargo test
```

See [docs/commands.md](docs/commands.md) for the full command reference, including rebuilding the WASM runtime.

## Project status

- **Controller lifecycle** (worker registration, heartbeat, latency, disconnect/remove, dashboard) — complete and working. `POST /disconnect/{uuid}` tells the tab not to reconnect (add `?reconnect=true` for a blip that reconnects).
- **Job pipeline** (submit → validate → split → schedule → dispatch → execute → aggregate → generic result) — working for all six workloads (Mandelbrot, SAT, `sat_batch`, compression, regex, N-Queens).
- **Fault tolerance** — numbered task attempts, requeue when a worker disconnects, misses its heartbeat, times out or reports an error, and stale answers kept for comparison. Tested live by closing a worker mid-job.
- **Scheduler** — five algorithms (`random`, `round_robin`, `fastest_first`, `boinc`, `ucb`) chosen at start-up or switched live, with measured per-worker speed, adaptive queue sizes, adaptive timeouts and work stealing. The default is still `random`. See [docs/project_context.md](docs/project_context.md) for the live results and open items.
- **Speed** — each tab runs a pool of compute threads (`min(cores − 1, 8)`; open `/worker?threads=N` to change it), and tasks and results travel in batches. On the test jobs this was roughly 5× to 70× faster than a single-thread tab with one message per task.
- **Logging** — set `GRID_LOG_LEVEL` (for example `INFO`) to change the level; the default is `DEBUG`.

Validated with a single-worker Mandelbrot run and a three-worker run across a laptop, phone, and Raspberry Pi 5 (2048×2048 image, 128×128 tiles, 256 tasks, all results aggregated into a final image). See [docs/validation.md](docs/validation.md) for details.

## Known limitations

- SAT workers require `runtime/pkg/` to be rebuilt from the included Rust
  source; the existing checked-in WASM binary predates this workload.
- Tested with at most three devices; the demo target is ten.
- A losing work-stealing copy keeps computing until it finishes (there is no cancel message); its answer is then ignored.
- A task that loses its worker or times out three times fails the whole job (the retry limit counts losses).
- The Mandelbrot cost estimate treats every tile as equal cost, which limits how well the adaptive schedulers can place its very uneven tiles.
- Workers are untrusted browsers, and the only check on their answers is comparing duplicates; the API has no authentication.
- Plain `ws://` (no TLS) — fine for LAN/dev use, not for production.
- In-memory-only state — the controller's registry, aggregators, and job tracking are lost on restart (running jobs are lost; workers reconnect by themselves).

See [docs/architecture.md](docs/architecture.md), [docs/protocol.md](docs/protocol.md), and [docs/validation.md](docs/validation.md) for details, and [docs/scope_updated.md](docs/scope_updated.md) for the longer-term research plan this project sits inside.

## License

MIT — see [LICENSE](LICENSE).
