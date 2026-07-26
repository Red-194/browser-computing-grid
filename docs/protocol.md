# Communication Protocol

This document specifies the wire protocol used between the three parties in the system:

- **Worker** (`worker.js`) — a browser tab that volunteers compute resources
- **Controller** (`main.py` / FastAPI backend) — the central coordinator
- **Dashboard** (`dashboard.js`) — a browser tab that monitors the grid

There are two transports:

| Channel | Transport | Direction |
|---|---|---|
| Worker ↔ Controller | WebSocket (`/ws`) | Bidirectional |
| Controller → Dashboard | Server-Sent Events (`/events`) | One-way push |
| Dashboard → Controller | HTTP POST (`/disconnect/{worker_uuid}`) | Request/response |

All WebSocket and SSE payloads are JSON. Every message carries a `type` discriminator field.

---

## 1. Worker ↔ Controller (WebSocket, `/ws`)

### 1.1 Connection lifecycle

```
Worker                                     Controller
  │                                             │
  │────── WebSocket Connect (/ws) ─────────────►│
  │────── register ────────────────────────────►│
  │◄──────────────────────── register_ack ──────│
  │                                             │
  │══════════════ Registered ═══════════════════│
  │                                             │
  │────── heartbeat ───────────────────────────►│
  │◄────────────────────────────── ping ────────│
  │────── pong ────────────────────────────────►│
  │                                             │
  │          (repeats every 5 seconds)          │
  │                                             │
  │────── Connection closes ───────────────────►│
  │                                             │
  │          WebSocketDisconnect                │
```

The controller assigns each worker a UUID during registration. No protocol messages are exchanged until registration has completed successfully.

---

### 1.2 Messages: Worker → Controller

#### **`register`**

Sent once, immediately after the WebSocket connection is established.

| Field | Type | Description |
|---|---|---|
| `type` | `Literal["register"]` | Message discriminator |
| `cores` | `int` | `navigator.hardwareConcurrency` |
| `memory` | `int` | Approximate device memory reported by `navigator.deviceMemory` (GB), or `0` if unavailable |
| `os` | `str` | `navigator.platform` |
| `browser` | `str` | `navigator.userAgent` |

```json
{
  "type": "register",
  "cores": 8,
  "memory": 8,
  "os": "Win32",
  "browser": "Mozilla/5.0 ..."
}
```

**Server behavior**

- Generates a new UUID.
- Creates a `Worker` record.
- Stores the worker in the registry.
- Notifies all connected dashboards.
- Responds with `register_ack`.

> **Note:** `RegisterMessage.memory` is typed as `int`, while `Worker.memory` is stored as `float`. This is an intentional widening of the value after validation.

---

#### **`heartbeat`**

Sent every **5000 ms** (`HEARTBEAT_INTERVAL` in `worker.js`) while connected.

| Field | Type | Description |
|---|---|---|
| `type` | `Literal["heartbeat"]` | Message discriminator |

```json
{
  "type": "heartbeat"
}
```

**Server behavior**

Updates the worker's heartbeat timestamp.

Heartbeats received before successful registration are ignored.

---

#### **`pong`**

Sent immediately in response to a controller `ping`.

| Field | Type | Description |
|---|---|---|
| `type` | `Literal["pong"]` | Message discriminator |
| `timestamp` | `float` | Echoed unchanged from the corresponding `ping` |

```json
{
  "type": "pong",
  "timestamp": 1234.567
}
```

**Server behavior**

Computes

```
latency = (now - timestamp) × 1000 ms
```

using `time.perf_counter()`, stores the measured latency for the worker, and notifies all dashboards.

---

### 1.3 Messages: Controller → Worker

#### **`register_ack`**

Sent once in response to a successful `register`.

| Field | Type | Description |
|---|---|---|
| `type` | `Literal["register_ack"]` | Message discriminator |
| `uuid` | `str` | UUID assigned by the controller |

```json
{
  "type": "register_ack",
  "uuid": "b3f1..."
}
```

**Worker behavior**

- Stores the assigned UUID.
- Updates its status to **Connected • Idle**.
- Starts the heartbeat timer.

---

#### **`ping`**

Broadcast to every registered worker every **5 seconds** by the `ping_workers` background task.

| Field | Type | Description |
|---|---|---|
| `type` | `Literal["ping"]` | Message discriminator |
| `timestamp` | `float` | `time.perf_counter()` value when the ping was sent |

```json
{
  "type": "ping",
  "timestamp": 1234.500
}
```

**Worker behavior**

Immediately replies with a `pong`, echoing the same timestamp.

Failures sending a ping to one worker (for example, if the socket is already closing) are handled independently so that other workers continue to receive pings.

---

### 1.4 Disconnection

A worker may disconnect in one of three ways.

#### **Server-detected**

A `WebSocketDisconnect` event occurs.

The worker is removed from the registry and all dashboards receive an updated worker snapshot.

#### **Heartbeat timeout**

`monitor_heartbeats` runs every second.

If a worker has not sent a heartbeat within **15 seconds** (`HEARTBEAT_TIMEOUT`), the controller closes its WebSocket connection, triggering the normal `WebSocketDisconnect` cleanup path.

#### **Explicit disconnect**

A dashboard issues

```
POST /disconnect/{worker_uuid}
```

which closes the worker's socket and follows the same cleanup path.

---

## 2. Controller → Dashboard (SSE, `/events`)

Each dashboard opens a long-lived

```
GET /events
```

connection using `EventSource`.

Every dashboard connection registers its own `asyncio.Queue` in the global subscriber list.

### Event format

Each Server-Sent Event contains a complete snapshot of all currently connected workers.

```
data: <JSON array>\n\n
```

Each worker snapshot contains:

| Field | Type | Source |
|---|---|---|
| `uuid` | `str` | `worker.uuid` |
| `ip` | `str` | `worker.ip` |
| `status` | `str` | `worker.status` |
| `cores` | `int` | `worker.cores` |
| `memory` | `float` | `worker.memory` |
| `latency` | `int` | `worker.latency` |

Example:

```json
[
  {
    "uuid": "b3f1...",
    "ip": "127.0.0.1",
    "status": "idle",
    "cores": 8,
    "memory": 8,
    "latency": 12
  }
]
```

### When events are sent

`notify_dashboards()` broadcasts a fresh **complete snapshot** (not a diff) whenever:

- A worker registers.
- A worker reports a new latency measurement (`pong`).
- A worker disconnects.
- A dashboard initially connects.

The dashboard treats every event as the authoritative state of the grid and rebuilds its worker table from scratch.

---

## 3. Dashboard → Controller (REST)

### **`POST /disconnect/{worker_uuid}`**

| | |
|---|---|
| Request body | None |
| Success | `{ "success": true }` |
| Worker not found | `{ "success": false }` |

Closing the worker's socket triggers the standard `WebSocketDisconnect` cleanup path, which removes the worker from the registry and automatically pushes an updated snapshot to every connected dashboard.

> **Deployment note:** This endpoint is currently not restricted to localhost. If the controller is deployed outside a trusted environment, authentication or authorization should be added before exposing it.

---

## 4. Timing Summary

| Parameter | Value | Defined in |
|---|---|---|
| Worker heartbeat interval | 5000 ms | `worker.js` (`HEARTBEAT_INTERVAL`) |
| Controller ping interval | 5 s | `monitoring.py` (`ping_workers`) |
| Heartbeat timeout | 15 s | `monitoring.py` (`HEARTBEAT_TIMEOUT`) |
| Heartbeat monitor frequency | 1 s | `monitoring.py` (`monitor_heartbeats`) |