# Architecture

This document describes the current system design as implemented in the codebase. For wire-level message formats see [protocol.md](protocol.md). For the longer-term research plan see [scope_updated.md](scope_updated.md).

## System overview

The grid has three runtime parties:

| Party | Implementation | Role |
|-------|----------------|------|
| **Worker** | `app/templates/worker.html` + `app/static/js/worker.js` + `runtime/pkg` (WASM) | Browser tab that registers compute capacity, executes assigned tasks in WASM, and reports results |
| **Controller** | FastAPI backend under `app/` | Central coordinator: registry, monitoring, job pipeline, API surface |
| **Dashboard** | `app/templates/dashboard.html` + `app/static/js/dashboard.js` | Localhost-only admin view of connected workers |

There is no peer-to-peer communication. All worker traffic flows through the controller.

## Request & channel map

```
Browser worker                Controller (FastAPI)              Browser dashboard
     │                              │                                  │
     │──── WebSocket /ws ──────────►│                                  │
     │◄─── register_ack, ping ──────│                                  │
     │──── heartbeat, pong ────────►│                                  │
     │◄─── task ────────────────────│                                  │
     │──── task_result ────────────►│                                  │
     │                              │──── SSE /events ────────────────►│
     │                              │◄─── POST /disconnect/{uuid} ─────│
     │                              │                                  │
     │                       POST /jobs, GET /jobs/{id}/result (REST clients) │
```

## Application bootstrap

`app/main.py` creates the FastAPI application with a lifespan context manager that starts two background asyncio tasks:

1. **`ping_workers()`** — every 5 s, sends a `ping` to every worker with an active WebSocket.
2. **`monitor_heartbeats()`** — every 1 s, force-closes connections whose last heartbeat exceeds 15 s.

Both tasks are cancelled cleanly on shutdown.

`app/main.py` also mounts two static directories: `app/static` at `/static` (dashboard/worker CSS and JS), and `runtime/pkg` at `/runtime` (the compiled WASM runtime and its `wasm-bindgen` JS glue, imported by `worker.js`).

Routers mounted:

| Router | Prefix / path | Module |
|--------|---------------|--------|
| Page routes | `/`, `/dashboard`, `/worker`, `/disconnect/{uuid}` | `routes.py` |
| WebSocket | `/ws` | `websocket.py` |
| SSE | `/events` | `events.py` |
| Jobs REST | `/jobs` | `jobs.py` |

## Core modules

### Worker registry (`registry.py`)

Four process-local, in-memory structures hold all mutable server state — there is no database and no persistence; restarting the controller clears everything:

```python
workers: dict[str, Worker]        # keyed by client-generated worker UUID
aggregators: dict[str, object]    # keyed by str(job_id); one aggregator instance per submitted job
task_counts: dict[str, int]       # keyed by str(job_id); total tasks the job was split into
completed_jobs: set[str]          # str(job_id) of jobs whose aggregator reports complete
```

### Worker model (`models/worker.py`)

```python
WorkerStates: IDLE | BUSY | OFFLINE

Worker:
  uuid, ip, cores, memory
  state, latency, last_heartbeat
  websocket (optional, not serialized)
  metadata (browser, os)
```

`BUSY` is defined but never assigned — nothing in the task-dispatch path (`jobs.py`, `websocket.py`) transitions a worker's state when it is handed a task, so a busy worker remains eligible for further round-robin assignments until it disconnects.

### WebSocket handler (`websocket.py`)

Handles the worker connection lifecycle and task-result reporting:

1. **`register`** — upsert worker by UUID; update socket, capabilities, metadata; set state to `IDLE`; notify dashboards; reply with `register_ack`.
2. **`heartbeat`** — refresh `last_heartbeat` timestamp.
3. **`pong`** — compute round-trip latency from echoed `timestamp`; notify dashboards.
4. **`task_result`** — look up the job's aggregator by `job_id`, call `aggregator.add_result(result)`, then check `aggregator.is_complete(task_counts[job_id])`; if complete, add the job to `completed_jobs`. If no aggregator is registered for the `job_id`, the result is logged and dropped.
5. **`WebSocketDisconnect`** — set `websocket = None`, `state = OFFLINE`, `latency = 0`; keep the worker record in the registry.

Unregistered messages (heartbeat/pong/task_result before register) are silently dropped or ignored.

`send_task(worker, task)` (also in this module) pushes a `task` message down a specific worker's socket and is called by the jobs router at dispatch time; it returns `False` (and logs) on send failure rather than raising.

### Monitoring (`monitoring.py`)

| Constant | Value | Effect |
|----------|-------|--------|
| Ping interval | 5 s | Latency probe frequency |
| Heartbeat timeout | 15 s | Stale worker detection |
| Timeout check interval | 1 s | How often timeouts are evaluated |

On timeout the controller closes the socket, which triggers the disconnect handler above.

### Event fan-out (`events.py`)

Dashboards subscribe via `GET /events`. Each subscriber gets an `asyncio.Queue`. On connect and on every state change (`notify_dashboards()`), a JSON array of all workers is pushed to every queue. The payload is a **full snapshot**, not a diff.

### Page routes (`routes.py`)

- **Access control**: `is_localhost()` gates `/` and `/dashboard` to loopback addresses only.
- **Disconnect**: `POST /disconnect/{uuid}` — if online, closes the WebSocket (→ offline); if already offline, removes the worker from the registry.

### Jobs API (`jobs.py`) — the job pipeline

`POST /jobs` is the entry point for the whole distributed-execution flow:

```
JobSubmission → get_splitter(job.workload) → splitter.split(job) → list[Task]
                                                                        │
                                 scheduler.schedule(tasks, workers) ◄──┘
                                           │
                                list[(Task, Worker)] assignments
                                           │
                          send_task(worker, task) for each assignment (over /ws)
```

`JobSubmission` is validated and parsed by FastAPI/Pydantic directly from the request body (see "Data models" below) before the handler runs, so a malformed or unknown-workload submission is rejected before splitting begins.

At the same time, `get_aggregator(job.workload, job.config)` constructs the workload's aggregator, and both the aggregator and the task count are stored in the registry keyed by `job_id` so that `websocket.py` can find them later when task results arrive.

`GET /jobs/{id}/result` reads `completed_jobs`/`aggregators` and, once the job is complete, returns the aggregator's own result directly:

```python
return Response(
    content=aggregator.get_result(),
    media_type=aggregator.result_type,
)
```

The endpoint does not know what kind of result it is returning — no image dimensions, no encoding logic, nothing workload-specific. That is deliberate: `aggregator.get_result()` and `aggregator.result_type` are the generic contract every aggregator is expected to implement, and `MandelbrotAggregator` is simply the one implementation of it that exists today (see "Generic result abstraction" below). `GET /jobs`, `GET /jobs/{id}`, and `DELETE /jobs/{id}` remain placeholder endpoints (static responses, no job store lookup).

### Dynamic workload loading (`services/loader.py`)

```python
def _get_class(workload: str, component: str):
    module = import_module(f"app.services.{component}s.{workload}")
    class_name = "".join(w.capitalize() for w in workload.split("_")) + component.capitalize()
    return getattr(module, class_name)
```

Given a workload name like `mandelbrot` and a component kind (`splitter` or `aggregator`), this imports `app.services.<component>s.<workload>` and looks up a class named `<Workload>Splitter` / `<Workload>Aggregator` by convention (e.g. `mandelbrot` → `MandelbrotSplitter` in `app/services/splitters/mandelbrot.py`). `get_splitter(workload)` instantiates with no arguments; `get_aggregator(workload, config)` passes the job's typed config object to the constructor.

**Why this indirection exists:** splitting a job into tasks and combining task results back into a result are inherently workload-specific operations (a Mandelbrot job tiles an image; a different workload would partition its own input differently) — so that logic lives in per-workload modules, resolved dynamically by the workload name in the submitted job rather than through a fixed registry or a large `if/elif` chain in `jobs.py`. Adding a new workload means adding a splitter and aggregator module with the expected class name, plus the corresponding job/task config models (see "Workload extension points" below) — no changes to `jobs.py` or the loader itself.

Currently `mandelbrot` is the only workload with a splitter and aggregator implementation; `app/services/splitters/` and `app/services/aggregators/` contain no other workload modules.

### Scheduler (`services/scheduler/round_robin.py`)

`RoundRobinScheduler.schedule(tasks, workers)` filters to `IDLE` workers, then assigns tasks to them in round-robin order via a persistent `self.index` counter (so consecutive job submissions continue rotating rather than always starting from worker 0). If there are no idle workers, it returns an empty assignment list and the tasks are simply never sent — there is no queueing or retry.

This is the only scheduler implemented. Capability-aware and adaptive/bandit scheduling are planned research work — see [scope_updated.md](scope_updated.md) — not present in the codebase.

### WASM runtime (`runtime/`)

A Rust crate (`runtime/src/lib.rs`) compiled to WebAssembly via `wasm-bindgen`, exposing a single entry point:

```rust
pub fn execute_task(task_type: &str, payload: JsValue) -> Result<JsValue, JsValue>
```

`execute_task` matches `task_type` against implemented **kernels** in `runtime/src/kernels/`:

| Kernel | File | Implements |
|---|---|---|
| `mandelbrot` | `kernels/mandelbrot.rs` | Escape-time Mandelbrot rendering for one image tile |

Any other `task_type` (e.g. a future workload's name) falls through to an `Err("Unknown task type: ...")` result. There is currently only the one kernel; `runtime/src/kernels/mod.rs` only re-exports `mandelbrot`. Compiled output (`runtime/pkg/*.wasm`, `.js`, `.d.ts`) is checked in as a required distributable artifact and is what the controller actually serves at `/runtime`; it is regenerated from `runtime/src` via `cargo build --release --target wasm32-unknown-unknown` followed by `wasm-bindgen` — see [commands.md](commands.md) for the exact invocation.

## Workload extension points

Mandelbrot is the current, only implemented workload. The pipeline is structured so that a future workload can be added by extending these points, without redesigning the job/task/dispatch/result flow:

| Extension point | What it does | Current (`mandelbrot`) implementation |
|---|---|---|
| **Job config** (`models/jobs.py`) | Typed shape of a job's `config` for one workload | `MandelbrotConfig` |
| **Job submission variant** (`models/jobs.py`) | Adds the workload to the `JobSubmission` discriminated union | `MandelbrotJob` (`workload: Literal["mandelbrot"]`) |
| **Task config** (`models/tasks.py`) | Typed shape of a single task's `config` | `MandelbrotTaskConfig` |
| **Splitter** (`app/services/splitters/<workload>.py`) | Turns one job into a list of `Task`s | `MandelbrotSplitter` |
| **WASM kernel** (`runtime/src/kernels/<workload>.rs`) | Executes one task inside the browser | `mandelbrot` kernel |
| **Aggregator** (`app/services/aggregators/<workload>.py`) | Accumulates task results and produces the final result | `MandelbrotAggregator` |
| **Scheduler** (`app/services/scheduler/`) | Assigns tasks to workers — workload-independent | `RoundRobinScheduler` (used for every workload) |

Adding a workload does not require touching `jobs.py`, `websocket.py`, `loader.py`, or the result endpoint — only the modules above, plus registering the new job variant in the `JobSubmission` union.

## Generic result abstraction

The result API is intentionally workload-agnostic. Every aggregator is expected to expose:

```python
aggregator.get_result()    # bytes of the final result, in whatever encoding the workload produces
aggregator.result_type     # a media type string, e.g. "image/png"
```

`GET /jobs/{id}/result` simply returns `Response(content=aggregator.get_result(), media_type=aggregator.result_type)` once the job is complete. For Mandelbrot, `MandelbrotAggregator.get_result()` reconstructs the full image from accumulated tiles and encodes it as a PNG via Pillow internally — the jobs router has no knowledge of pixels, image dimensions, or PNG encoding. A future workload's aggregator could return, for example, JSON or a different binary format via the same two-method contract, with no change to `jobs.py`.

## Client-side behavior

### Worker (`worker.js`)

1. Read or generate UUID from `localStorage` (`worker-id`).
2. Open WebSocket to `ws://<host>/ws`, `import init, { execute_task } from "/runtime/runtime.js"`, and initialize the WASM module.
3. On open, send `register` with `navigator.hardwareConcurrency`, `navigator.deviceMemory`, etc.
4. On `register_ack`, start a 5 s heartbeat interval.
5. On `ping`, immediately reply with `pong` echoing `timestamp`.
6. On `task`, call `execute_task(task.workload, task.config)` and send a `task_result` back containing `row_block`, `col_block`, and `pixel_buffer` from the kernel's output, plus `execution_time_ms`.

`worker.js` reads the WASM kernel's output as `{ row_block, col_block, pixel_buffer }` — the shape produced by the `mandelbrot` kernel, which is the only kernel that currently exists.

WebSocket URL uses `ws://` (not `wss://`) — suitable for local/LAN use only.

### Dashboard (`dashboard.js`)

1. Open `EventSource("/events")`.
2. On each message, parse JSON array and rebuild worker table.
3. Action button label toggles: `Disconnect` (online) / `Remove` (offline).
4. Both call `POST /disconnect/{uuid}`.

## Worker state machine

```
                    register / reconnect
         ┌──────────────────────────────────────┐
         ▼                                      │
    ┌─────────┐   task dispatch (not tracked) ┌────────┐
    │  IDLE   │ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─►│  BUSY  │
    └────┬────┘                               └───┬────┘
         │                                        │
         │ WebSocketDisconnect                    │ (no transition implemented)
         │ heartbeat timeout                      │
         │ POST /disconnect (online)              │
         ▼                                        ▼
    ┌──────────┐ ◄────────────────────────────────┘
    │ OFFLINE  │
    └────┬─────┘
         │ POST /disconnect (offline) → removed from registry
         │ register / reconnect → IDLE
         ▼
      (removed)
```

`IDLE → BUSY` is drawn dashed because nothing in the codebase currently performs that transition; `WorkerStates.BUSY` exists but is unused. A worker's state today only ever moves between `IDLE` and `OFFLINE`.

## Data models

### Job submission (`models/jobs.py`)

```python
class MandelbrotConfig(BaseModel):
    width: int
    height: int
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    max_iterations: int
    tile_size: int

class MandelbrotJob(BaseModel):
    job_id: UUID | None = None
    workload: Literal["mandelbrot"]
    config: MandelbrotConfig

JobSubmission = Annotated[
    MandelbrotJob,
    Field(discriminator="workload"),
]
```

`JobSubmission` is a Pydantic discriminated union keyed on the `workload` field. `MandelbrotJob` is currently the only variant, so today the union has exactly one member — but the shape is a union by design, so that a future workload can be added by defining its own `<Workload>Job` model (with its own typed `config`) and adding it to the `JobSubmission` annotation, without weakening validation for the workloads that already exist. `job_id` is set server-side in `jobs.py` on submission, not by the client. Unlike an earlier, untyped `config: dict` design, request bodies are now validated against `MandelbrotConfig`'s field types by FastAPI/Pydantic before the handler runs.

### Task (`models/tasks.py`)

```python
class MandelbrotTaskConfig(BaseModel):
    width: int
    height: int
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    max_iterations: int
    tile_size: int
    row_block: int
    col_block: int

TaskConfig = Annotated[
    MandelbrotTaskConfig,
    Field(discriminator=None),
]

class Task(BaseModel):
    job_id: UUID = Field(default_factory=uuid4)
    task_id: int
    workload: Literal["mandelbrot"]
    config: TaskConfig
```

A decomposed unit of work sent to a single worker. `TaskConfig` is written as an `Annotated`/discriminated type to leave room for a real discriminated union once a second workload's task config exists; with only `MandelbrotTaskConfig` present, `discriminator=None` and Pydantic falls back to its default single-type matching behavior. `MandelbrotTaskConfig` extends the job-level config shape with `row_block`/`col_block` tile coordinates specific to a single task.

### Protocol messages (`models/protocol.py`)

Pydantic models for WebSocket JSON: `RegisterMessage`, `RegisterAckMessage`, `HeartbeatMessage`, `PingMessage`, `PongMessage`. `task` and `task_result` messages are handled directly against raw dicts in `websocket.py` and `worker.js` rather than through a Pydantic model in this file — see [protocol.md](protocol.md) for their field-level documentation.

## Planned extensions (not yet in code)

Per [scope_updated.md](scope_updated.md):

- Capability-aware and adaptive multi-armed-bandit schedulers (only Round Robin exists today)
- Fault tolerance: failure detection beyond heartbeat timeout, task reassignment, checkpointing
- Additional workloads beyond Mandelbrot — the research-scope workload suite is SAT/SMT solving, lossless compression, and regex/text processing (see [scope_updated.md](scope_updated.md) §14); none of these are implemented, and no second workload of any kind currently exists in the codebase
- Optional native monitor for richer device metrics

## Design constraints & notes

- **In-memory only** — no database; all state is lost on controller restart.
- **Single process** — no horizontal scaling of the controller without shared state.
- **Localhost dashboard** — intentional; remote admin would need auth and relaxed gating.
- **No TLS** — worker WebSocket uses plain `ws://`; production would require reverse proxy + `wss://`.
- **No task reassignment** — if a worker disconnects mid-task, that task's result never arrives and the job simply never completes; nothing detects or retries it.
