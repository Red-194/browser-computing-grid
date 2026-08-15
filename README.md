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

## Current workload: Mandelbrot

The job/task pipeline is designed to be workload-agnostic: a job carries a typed, workload-specific config; a **splitter** turns a job into tasks; a WASM **kernel** executes each task; and an **aggregator** combines task results back into a final job result. All three are resolved dynamically by workload name (`app/services/loader.py`).

Today, **Mandelbrot is the only implemented workload**, and it is the reference/demo workload for the whole pipeline:

| Workload | Job/task config | Splitter | WASM kernel | Aggregator | Status |
|---|---|---|---|---|---|
| `mandelbrot` | ✅ (`MandelbrotConfig` / `MandelbrotTaskConfig`) | ✅ | ✅ | ✅ | **Fully working end-to-end** |

Other workloads (e.g. Monte Carlo, matrix multiplication) are **not currently implemented** — there is no job model, splitter, kernel, or aggregator for them in this codebase. The extension points that would let a future workload be added without redesigning the pipeline are described in [docs/architecture.md](docs/architecture.md).

## Scheduler

The controller currently ships one scheduler: **Round Robin**, which assigns tasks to `IDLE` workers in rotation. Capability-aware and adaptive (multi-armed-bandit) scheduling are researched and planned — see [docs/scope_updated.md](docs/scope_updated.md) — but are not implemented yet.

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

The response includes the generated `job_id` and the task→worker assignments made at submission time.

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

- **Controller lifecycle** (worker registration, heartbeat, latency, disconnect/remove, dashboard) — complete and working.
- **Job pipeline** (submit → validate → split → schedule → dispatch → execute → aggregate → generic result) — complete and working for `mandelbrot`.
- **Scheduler** — Round Robin only; capability-aware and adaptive/bandit scheduling described in [docs/scope_updated.md](docs/scope_updated.md) are research/roadmap items, not implemented.
- **Additional workloads** — not implemented; the architecture is designed to support them (see [docs/architecture.md](docs/architecture.md)) but no second workload exists in the codebase today.

Validated with a single-worker Mandelbrot run and a three-worker run across a laptop, phone, and Raspberry Pi 5 (2048×2048 image, 128×128 tiles, 256 tasks, all results aggregated into a final image). See [docs/validation.md](docs/validation.md) for details.

## Known limitations

- Only `mandelbrot` is a complete, runnable workload.
- No fault tolerance — a worker that disconnects mid-task does not have its task reassigned; the job simply never completes.
- `WorkerStates.BUSY` is defined but never assigned — the scheduler does not mark a worker busy during task execution, so a worker can in principle be handed more tasks than it can run concurrently.
- Plain `ws://` (no TLS) — fine for LAN/dev use, not for production.
- In-memory-only state — the controller's registry, aggregators, and job tracking are lost on restart.

See [docs/architecture.md](docs/architecture.md), [docs/protocol.md](docs/protocol.md), and [docs/validation.md](docs/validation.md) for details, and [docs/scope_updated.md](docs/scope_updated.md) for the longer-term research plan this project sits inside.

## License

MIT — see [LICENSE](LICENSE).
