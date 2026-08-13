# Browser Computing Grid

A zero-install, browser-native distributed computing grid. Browser tabs volunteer CPU and memory as worker nodes; a FastAPI controller coordinates registration, health monitoring, and (planned) workload dispatch; an admin dashboard observes the live grid over Server-Sent Events.

This repository implements **Phase 1** of a final-year project — worker lifecycle management, heartbeat monitoring, latency measurement, and job payload validation. Task dispatch, scheduling, WebAssembly execution, and fault recovery are planned in later phases. See [docs/scope.md](docs/scope.md) for the full roadmap.

## Features (implemented)

| Area | Status |
|------|--------|
| Worker registration & reconnect (UUID upsert) | Done |
| Heartbeat monitoring & timeout (15 s) | Done |
| Latency measurement (ping/pong) | Done |
| Live dashboard (SSE) | Done |
| Worker disconnect / remove | Done |
| Job submission API (validation only) | Partial |
| Task decomposition (splitters) | Code present, not wired |
| Scheduler & worker task execution | Not started |

## Quick start

### Prerequisites

- Python 3.12+
- A modern browser (Chrome, Firefox, Edge)

### Install & run

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Use the grid

1. **Dashboard** (localhost only): open [http://127.0.0.1:8000/dashboard](http://127.0.0.1:8000/dashboard)
2. **Worker** (any device on the network): open [http://&lt;controller-ip&gt;:8000/worker](http://127.0.0.1:8000/worker)
3. Workers appear in the dashboard table within a few seconds (after ping/pong completes).

Remote clients hitting `/` or `/dashboard` are redirected to `/worker`. The dashboard is restricted to `127.0.0.1` / `::1` via `is_localhost()`.

## Project layout

```
browser-computing-grid/
├── app/
│   ├── main.py              # FastAPI app, lifespan, static mount
│   ├── routes.py            # Page routes + worker disconnect
│   ├── websocket.py         # Worker WebSocket handler
│   ├── events.py            # SSE fan-out to dashboards
│   ├── monitoring.py        # Ping loop + heartbeat timeout
│   ├── jobs.py              # REST job endpoints (placeholders)
│   ├── registry.py          # In-memory worker store
│   ├── models/
│   │   ├── worker.py        # Worker dataclass & states
│   │   ├── protocol.py      # WebSocket message schemas
│   │   ├── jobs.py          # Job submission schemas
│   │   └── tasks.py         # Decomposed task schemas
│   ├── workloads/
│   │   ├── monte_carlo/splitter.py
│   │   ├── matrix/splitter.py
│   │   └── mandelbrot/splitter.py
│   ├── services/request_utils.py
│   ├── templates/           # Jinja2 HTML (dashboard, worker)
│   └── static/              # CSS + client JS
├── docs/
│   ├── architecture.md      # System design & module map
│   ├── protocol.md          # Wire protocol specification
│   ├── scope.md             # Project scope & timeline
│   └── validation.md        # Validation report
├── requirements.txt
└── LICENSE
```

## API overview

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Redirect: localhost → dashboard, else → worker |
| `/dashboard` | GET | Admin dashboard (localhost only) |
| `/worker` | GET | Worker node page |
| `/ws` | WebSocket | Worker registration, heartbeat, ping/pong |
| `/events` | GET (SSE) | Live worker snapshot stream |
| `/disconnect/{uuid}` | POST | Disconnect online worker or remove offline row |
| `/jobs` | POST | Submit a job (validates payload, no dispatch yet) |
| `/jobs` | GET | List jobs (placeholder) |
| `/jobs/{id}` | GET | Get job status (placeholder) |
| `/jobs/{id}/result` | GET | Get job result (placeholder) |
| `/jobs/{id}` | DELETE | Cancel job (placeholder) |

Full message schemas and timing constants are documented in [docs/protocol.md](docs/protocol.md).

### Example job submission

```bash
curl -X POST http://127.0.0.1:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "workload": "monte_carlo",
    "config": { "samples": 1000000, "seed": 42 }
  }'
```

Supported workloads: `monte_carlo`, `matrix_multiply`, `mandelbrot`.

## Architecture (summary)

```
┌─────────────┐   WebSocket (/ws)    ┌──────────────────┐   SSE (/events)   ┌─────────────┐
│   Worker    │◄────────────────────►│    Controller    │──────────────────►│  Dashboard  │
│ (worker.js) │  register, heartbeat │  (FastAPI app)   │  worker snapshots │(dashboard.js)│
└─────────────┘  ping/pong           └────────┬─────────┘                   └──────┬──────┘
                                              │ POST /disconnect                      │
                                              └───────────────────────────────────────┘
                                              POST /jobs (REST, not yet dispatched)
```

See [docs/architecture.md](docs/architecture.md) for module responsibilities, state machine, and background tasks.

## Development status

Aligned with the project timeline in [docs/scope.md](docs/scope.md):

- **Phase 1 (Controller)** — largely complete: registration, states, disconnect, heartbeat timeout.
- **Phase 2 (Distributed execution)** — job models and splitters exist; dispatch and aggregation not wired.
- **Phases 3–8** — schedulers, WASM runtime, fault tolerance, evaluation — not started.

A validation run on 2026-07-29 confirms all Phase 1 runtime paths pass. Splitters and job listing endpoints have known gaps — see [docs/validation.md](docs/validation.md).

## License

MIT — see [LICENSE](LICENSE).
