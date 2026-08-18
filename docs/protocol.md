# Communication Protocol

> See also: [architecture.md](architecture.md) · [validation.md](validation.md)

This document specifies the wire protocol used between the three parties in the system:

- **Worker** (`worker.js`) — a browser tab that volunteers compute resources
- **Controller** (FastAPI backend: `websocket.py`, `monitoring.py`, `events.py`, `routes.py`, `jobs.py`) — the central coordinator
- **Dashboard** (`dashboard.js`) — a browser tab that monitors the grid

| Channel | Transport | Direction |
|---|---|---|
| Worker ↔ Controller | WebSocket (`/ws`) | bidirectional |
| Controller → Dashboard | Server-Sent Events (`/events`) | one-way push |
| Dashboard → Controller | HTTP POST (`/disconnect/{worker_uuid}`) | request/response |
| Client → Controller | HTTP REST (`/jobs`) | request/response |

All WebSocket and SSE payloads are JSON. Every WebSocket message carries a `type` discriminator field.

---

## 1. Worker identity

Workers generate and persist their own identity client-side:

```js
let uuid = localStorage.getItem("worker-id");
if (!uuid) {
    uuid = crypto.randomUUID();
    localStorage.setItem("worker-id", uuid);
}
```

This UUID is stable across page reloads and reconnects, and is sent as part of `register`. Server-side, `register` is an **upsert** keyed on this UUID (`workers.get(message.uuid)`):

- **Known UUID** → the existing `Worker` record is updated in place (websocket, ip, cores, memory, metadata, `last_heartbeat`, `state = Idle`). Latency is not reset on this path and holds its last known value until the next `pong`.
- **Unknown UUID** → a new `Worker` record is created.

A worker that reconnects (page refresh, dropped connection) resumes the same identity in the registry rather than appearing as a new entry.

---

## 2. Worker ↔ Controller (WebSocket, `/ws`)

### 2.1 Connection lifecycle

```
Worker                                Controller
  |----- WS connect (/ws) ------------->|
  |----- register (with own UUID) ----->|
  |<---- register_ack (uuid, state) -----|
  |                                      |
  |----- heartbeat (every 5s) --------->|
  |<---- ping (every 5s) ----------------|
  |----- pong ------------------------->|
  |                                      |
  |  (connection closes / drops)         |
  |----- WebSocketDisconnect ----------->| (server-side; worker marked Offline, kept in registry)
```

### 2.2 Messages: Worker → Controller

**`register`**

| Field | Type | Description |
|---|---|---|
| `type` | `Literal["register"]` | discriminator |
| `uuid` | `str` | client-generated, persisted in `localStorage` |
| `cores` | `int` | `navigator.hardwareConcurrency` |
| `memory` | `float` | `navigator.deviceMemory` (GB), `0` if unavailable |
| `os` | `str` | `navigator.platform` |
| `browser` | `str` | `navigator.userAgent` |

```json
{ "type": "register", "uuid": "b3f1...", "cores": 8, "memory": 8, "os": "Win32", "browser": "Mozilla/5.0 ..." }
```

Server behavior: upserts the `Worker` record as described in §1, sets `state = WorkerStates.IDLE`, notifies all dashboards, and replies with `register_ack`.

**`heartbeat`**

| Field | Type | Description |
|---|---|---|
| `type` | `Literal["heartbeat"]` | discriminator |

Server behavior: updates `worker.last_heartbeat = now()` for the sender. If the connection hasn't registered yet, the message is dropped.

**`pong`**

| Field | Type | Description |
|---|---|---|
| `type` | `Literal["pong"]` | discriminator |
| `timestamp` | `float` | echoed back unchanged from the triggering `ping` |

Server behavior: computes latency as `(now - timestamp) * 1000` ms via `time.perf_counter()`, rounds it **up** to the nearest whole millisecond (`math.ceil`), stores it as `worker.latency: int`, and notifies dashboards.

### 2.3 Messages: Controller → Worker

**`register_ack`**

| Field | Type | Description |
|---|---|---|
| `type` | `Literal["register_ack"]` | discriminator |
| `uuid` | `str` | echoes the worker's own UUID back |
| `state` | `str` | the worker's current state (`Idle` / `Busy` / `Offline`) |

Worker behavior: renders `Connected • {state}` and starts its heartbeat timer.

**`ping`**

| Field | Type | Description |
|---|---|---|
| `type` | `Literal["ping"]` | discriminator |
| `timestamp` | `float` | `time.perf_counter()` value at send time |

Worker behavior: immediately replies with `pong`, echoing the same `timestamp`. Broadcast to every worker with a live socket every 5 seconds; a send failure for one worker is caught and logged without interrupting the broadcast to others.

**`task`**

| Field | Type | Description |
|---|---|---|
| `type` | `Literal["task"]` | discriminator |
| `task` | object | a serialized `Task` (`job_id`, `task_id`, `workload`, `config`) — see [architecture.md](architecture.md#data-models) |

Sent by `send_task()` (`websocket.py`) to a single assigned worker when a job is submitted (§4). Worker behavior: calls `execute_task(task.workload, task.config)` in the WASM runtime and replies with `task_result`. A send failure is caught and logged server-side; it does not raise or retry.

### 2.4 Messages: Worker → Controller (continued)

**`task_result`**

| Field | Type | Description |
|---|---|---|
| `type` | `Literal["task_result"]` | discriminator |
| `job_id` | `str` | the task's `job_id`, used to look up the job's aggregator |
| `task_id` | `int` | the task's `task_id` |
| `result` | object | `{ row_block, col_block, pixel_buffer }`, taken directly from the WASM kernel's output |
| `execution_time_ms` | `float` | wall-clock time for `execute_task()`, measured client-side |

```json
{ "type": "task_result", "job_id": "e29b...", "task_id": 3, "result": { "row_block": 1, "col_block": 0, "pixel_buffer": [ ... ] }, "execution_time_ms": 42.1 }
```

Server behavior: looks up `aggregators[job_id]`; if none exists, logs and drops the message. Otherwise calls `aggregator.add_result(result)`, then checks `aggregator.is_complete(task_counts[job_id])` — if true, adds `job_id` to `completed_jobs`.

This message shape is not validated against a Pydantic model — it's read directly from the raw WebSocket JSON in `websocket.py`. Since `mandelbrot` is currently the only workload, `result`'s `{ row_block, col_block, pixel_buffer }` shape always matches what the kernel actually returned.

### 2.5 Disconnection

- **Server-detected (`WebSocketDisconnect`):** the worker record is **not removed** from the registry. `websocket = None`, `latency = 0`, `state = WorkerStates.OFFLINE`, and dashboards are notified. The worker remains visible on the dashboard as offline until it reconnects with the same UUID or is explicitly removed (§5).
- **Timeout-based:** `monitor_heartbeats` runs every second, skips workers that are already offline (`websocket is None`), and force-closes the socket of any remaining worker whose `last_heartbeat` exceeds `HEARTBEAT_TIMEOUT` (15s) — which then triggers the path above.
- **Explicit:** `POST /disconnect/{worker_uuid}` (§5) either closes the socket (if online) or removes the record entirely (if already offline).

---

## 3. Controller → Dashboard (SSE, `/events`)

A dashboard opens a single long-lived `GET /events` connection. Each connection registers its own `asyncio.Queue` in the global `subscribers` list.

**Payload** — full snapshot of every worker currently in the registry, pushed on every state change and once immediately on dashboard connect:

| Field | Type | Source |
|---|---|---|
| `uuid` | `str` | `worker.uuid` |
| `ip` | `str` | `worker.ip` |
| `state` | `str` | `worker.state` (`Idle` / `Busy` / `Offline`) |
| `cores` | `int` | `worker.cores` |
| `memory` | `float` | `worker.memory` |
| `latency` | `int` | `worker.latency` (`0` while offline) |

```json
[
  { "uuid": "b3f1...", "ip": "127.0.0.1", "state": "Idle", "cores": 8, "memory": 8, "latency": 12 }
]
```

The dashboard fully re-renders its table on every push (`table.innerHTML = ""` then rebuild) — each event is a complete snapshot, not a diff. Offline workers stay in this list until removed (§5), and the dashboard's action button switches its own label to `Remove` for `Offline` rows and `Disconnect` otherwise — both map to the same `/disconnect/{worker_uuid}` call, whose effect differs based on current state.

---

## 4. Job submission (`/jobs`)

`JobSubmission` is a discriminated union on `workload`, currently containing one variant, `MandelbrotJob` (`{ job_id, workload: "mandelbrot", config: MandelbrotConfig }`). The request body is validated by FastAPI/Pydantic against that typed shape before the handler runs — an unknown `workload` value or a malformed `config` is rejected at submission time.

| Workload | `config` fields | End-to-end status |
|---|---|---|
| `mandelbrot` | `width`, `height`, `x_min`, `x_max`, `y_min`, `y_max`, `max_iterations`, `tile_size` (all required, typed) | Fully working |

No other workload is currently defined; `mandelbrot` is the only value accepted for `workload`.

| Endpoint | Behavior as implemented |
|---|---|
| `POST /jobs` | Assigns `job_id`, runs `get_splitter(job.workload).split(job)` to produce tasks, constructs the workload's aggregator via `get_aggregator(job.workload, job.config)` and registers it (keyed by `job_id`) alongside the task count, runs `RoundRobinScheduler.schedule(tasks, workers)` against currently `IDLE` workers, and sends each assigned task over that worker's WebSocket (§2.3 `task`). Returns the job, task count, and the task→worker assignments made. If no workers are `IDLE`, tasks are produced and an aggregator is registered, but nothing is sent — the job silently never receives results. |
| `GET /jobs` | Placeholder — returns a static message, no listing logic. |
| `GET /jobs/{job_id}` | Placeholder — returns the `job_id` with a static message. |
| `GET /jobs/{job_id}/result` | If `job_id` has no registered aggregator, returns a "not found" message. If registered but not yet in `completed_jobs`, returns a "still processing" message. Once complete, returns `aggregator.get_result()` as the response body with media type `aggregator.result_type`. This is generic — the endpoint has no workload-specific logic; for `mandelbrot` the aggregator's `get_result()` happens to build and encode a PNG internally, but the endpoint itself doesn't know that. |
| `DELETE /jobs/{job_id}` | Placeholder — returns the `job_id` with a static message. |

There is still no persistent job store — `aggregators`, `task_counts`, and `completed_jobs` are the only record of a job's existence, and all three live only in `registry.py`'s in-memory dicts.

---

## 5. Dashboard → Controller (REST)

**`POST /disconnect/{worker_uuid}`**

Behavior depends on the worker's current state:

| Worker state | Action | Response |
|---|---|---|
| Not found | none | `{ "success": false }` |
| Online (`websocket` set) | closes the socket — this triggers the `WebSocketDisconnect` path in §2.5, transitioning the worker to `Offline` (record kept) | `{ "success": true }` |
| Offline (`websocket is None`) | removes the worker record from the registry entirely and notifies dashboards directly | `{ "success": true }` |

So a worker takes two explicit clicks to fully clear from the dashboard once it's gone: one to disconnect it, one to remove the resulting offline row. This matches the `Disconnect`/`Remove` label toggle in `dashboard.js`.

`is_localhost()` (`request.client.host in ("127.0.0.1", "::1")`) gates `/dashboard` and `/`, but not this endpoint.

---

## 6. Timing summary

| Parameter | Value | Defined in |
|---|---|---|
| Worker heartbeat interval | 5000 ms | `worker.js` (`HEARTBEAT_INTERVAL`) |
| Controller ping interval | 5 s | `monitoring.py` (`ping_workers`) |
| Heartbeat timeout (worker marked offline) | 15 s | `monitoring.py` (`HEARTBEAT_TIMEOUT`) |
| Heartbeat-timeout check frequency | 1 s | `monitoring.py` (`monitor_heartbeats`) |

---

## 7. Open items

- No persistent job store — job existence is only tracked implicitly via `aggregators`/`task_counts`/`completed_jobs` (§4).
- No worker `state` transition to `Busy` on task dispatch — `RoundRobinScheduler` can assign further tasks to a worker that already has one in flight (§4, [architecture.md](architecture.md)).
- No task reassignment on worker disconnect — a task in flight to a worker that drops is simply lost, and its job never completes.
- Only one workload (`mandelbrot`) exists, so the discriminated-union validation on `JobSubmission` and the extension points described in [architecture.md](architecture.md#workload-extension-points) are currently exercised by a single case.
