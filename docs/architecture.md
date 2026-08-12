# Architecture

This document describes the current system design as implemented in the codebase. For wire-level message formats see [protocol.md](protocol.md). For planned future work see [scope.md](scope.md).

## System overview

The grid has three runtime parties:

| Party | Implementation | Role |
|-------|----------------|------|
| **Worker** | `app/templates/worker.html` + `app/static/js/worker.js` | Browser tab that registers compute capacity and responds to health probes |
| **Controller** | FastAPI backend under `app/` | Central coordinator: registry, monitoring, API surface |
| **Dashboard** | `app/templates/dashboard.html` + `app/static/js/dashboard.js` | Localhost-only admin view of connected workers |

There is no peer-to-peer communication. All worker traffic flows through the controller.

## Request & channel map

```
Browser worker                Controller (FastAPI)              Browser dashboard
     │                              │                                  │
     │──── WebSocket /ws ──────────►│                                  │
     │◄─── register_ack, ping ──────│                                  │
     │──── heartbeat, pong ────────►│                                  │
     │                              │──── SSE /events ────────────────►│
     │                              │◄─── POST /disconnect/{uuid} ─────│
     │                              │                                  │
     │                         POST /jobs (REST clients)                 │
```

## Application bootstrap

`app/main.py` creates the FastAPI application with a lifespan context manager that starts two background asyncio tasks:

1. **`ping_workers()`** — every 5 s, sends a `ping` to every worker with an active WebSocket.
2. **`monitor_heartbeats()`** — every 1 s, force-closes connections whose last heartbeat exceeds 15 s.

Both tasks are cancelled cleanly on shutdown.

Routers mounted:

| Router | Prefix / path | Module |
|--------|---------------|--------|
| Page routes | `/`, `/dashboard`, `/worker`, `/disconnect/{uuid}` | `routes.py` |
| WebSocket | `/ws` | `websocket.py` |
| SSE | `/events` | `events.py` |
| Jobs REST | `/jobs` | `jobs.py` |

Static assets are served from `app/static` at `/static`.

## Core modules

### Worker registry (`registry.py`)

A process-local `dict[str, Worker]` holds all known workers keyed by client-generated UUID. There is no persistence — restarting the controller clears the registry.

### Worker model (`models/worker.py`)

```python
WorkerStates: IDLE | BUSY | OFFLINE

Worker:
  uuid, ip, cores, memory
  state, latency, last_heartbeat
  websocket (optional, not serialized)
  metadata (browser, os)
```

`BUSY` is defined but not yet assigned anywhere — reserved for Phase 2 task dispatch.

### WebSocket handler (`websocket.py`)

Handles the worker connection lifecycle:

1. **`register`** — upsert worker by UUID; update socket, capabilities, metadata; set state to `IDLE`; notify dashboards; reply with `register_ack`.
2. **`heartbeat`** — refresh `last_heartbeat` timestamp.
3. **`pong`** — compute round-trip latency from echoed `timestamp`; notify dashboards.
4. **`WebSocketDisconnect`** — set `websocket = None`, `state = OFFLINE`, `latency = 0`; keep record in registry.

Unregistered messages (heartbeat/pong before register) are silently dropped.

### Monitoring (`monitoring.py`)

| Constant | Value | Effect |
|----------|-------|--------|
| Ping interval | 5 s | Latency probe frequency |
| Heartbeat timeout | 15 s | Stale worker detection |
| Timeout check interval | 1 s | How often timeouts are evaluated |

On timeout the controller closes the socket, which triggers the disconnect handler above.

### Event fan-out (`events.py`)

Dashboards subscribe via `GET /events`. Each subscriber gets an `asyncio.Queue`. On connect and on every state change (`notify_dashboards()`), a JSON array of all workers is pushed to every queue.

The payload is a **full snapshot**, not a diff. The dashboard re-renders the entire table on each event.

### Page routes (`routes.py`)

- **Access control**: `is_localhost()` gates `/` and `/dashboard` to loopback addresses only.
- **Disconnect**: `POST /disconnect/{uuid}` — if online, closes WebSocket (→ offline); if already offline, removes from registry.

### Jobs API (`jobs.py`)

Currently stub endpoints. `POST /jobs` validates the discriminated union in `models/jobs.py` and echoes the payload. No job store, no task splitting invocation, no WebSocket dispatch.

### Workload splitters (`workloads/*/splitter.py`)

Task decomposition logic exists for three embarrassingly-parallel workloads:

| Splitter | Strategy |
|----------|----------|
| `MonteCarloSplitter` | Divide `samples` evenly across `num_tasks`; unique per-task seed |
| `MatrixMultiplySplitter` | Tile matrix into `block_size` chunks (row × col blocks) |
| `MandelbrotSplitter` | Tile image into `tile_size` pixel regions |

Output type is `Task` (`models/tasks.py`). These splitters are **not called** by the jobs router yet.

## Client-side behavior

### Worker (`worker.js`)

1. Read or generate UUID from `localStorage` (`worker-id`).
2. Open WebSocket to `ws://<host>/ws`.
3. On open, send `register` with `navigator.hardwareConcurrency`, `navigator.deviceMemory`, etc.
4. On `register_ack`, start 5 s heartbeat interval.
5. On `ping`, immediately reply with `pong` echoing `timestamp`.

WebSocket URL uses `ws://` (not `wss://`) — suitable for local development only.

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
    ┌─────────┐   task dispatch (planned)  ┌────────┐
    │  IDLE   │ ─────────────────────────► │  BUSY  │
    └────┬────┘                            └───┬────┘
         │                                     │
         │ WebSocketDisconnect                 │ task complete (planned)
         │ heartbeat timeout                   │
         │ POST /disconnect (online)             │
         ▼                                     ▼
    ┌──────────┐ ◄─────────────────────────────┘
    │ OFFLINE  │
    └────┬─────┘
         │ POST /disconnect (offline) → removed from registry
         │ register / reconnect → IDLE
         ▼
      (removed)
```

## Data models

### Job submission (`models/jobs.py`)

Discriminated union on `workload`:

- `monte_carlo` → `{ samples, seed? }`
- `matrix_multiply` → `{ rows, cols, block_size, random? }`
- `mandelbrot` → `{ width, height, x_min, x_max, y_min, y_max, max_iterations, tile_size }`

### Task (`models/tasks.py`)

A decomposed unit of work sent to a single worker. Includes `job_id`, `task_id`, `workload`, and workload-specific config with block coordinates where applicable.

### Protocol messages (`models/protocol.py`)

Pydantic models for WebSocket JSON: `RegisterMessage`, `RegisterAckMessage`, `HeartbeatMessage`, `PingMessage`, `PongMessage`.

## Planned extensions (not yet in code)

Per [scope.md](scope.md):

- Scheduler interface with Round Robin, capability-aware, and multi-armed bandit strategies
- WebSocket task dispatch and result collection on workers
- WebAssembly compute runtime with JS fallback
- Checkpointing and task reassignment on worker failure
- Optional native monitor for richer device metrics

## Design constraints & notes

- **In-memory only** — no database; all state is lost on controller restart.
- **Single process** — no horizontal scaling of the controller without shared state.
- **Localhost dashboard** — intentional; remote admin would need auth and relaxed gating.
- **No TLS** — worker WebSocket uses plain `ws://`; production would require reverse proxy + `wss://`.
