# Validation Report

**Date:** 2026-07-29  
**Environment:** Python 3.12, FastAPI + Uvicorn, Linux  
**Controller:** `uvicorn app.main:app --host 127.0.0.1 --port 8765`

## Summary

| Category | Result |
|----------|--------|
| Python compilation | All modules compile without syntax errors |
| Phase 1 runtime (HTTP, WebSocket, SSE) | **17 / 17 passed** |
| Job API validation | **4 / 4 passed** |
| Workload splitters | **0 / 3 functional** (blocked by missing `job_id`) |
| Splitter input validation | **4 / 4 passed** (correct `ValueError` on bad input) |

The controller's worker lifecycle, monitoring, and dashboard pipeline are functional. Task decomposition code exists but cannot run until job models expose a shared `job_id`. Job listing, dispatch, and result endpoints remain placeholders.

---

## 1. Static checks

### Module compilation

```
python -m py_compile app/main.py app/routes.py app/websocket.py ...
```

**Result:** PASS — no syntax errors across all application modules.

### Import smoke test

```
from app.main import app
from app.models.jobs import MonteCarloJob, MatrixMultiplyJob, MandelbrotJob
from app.workloads.*.splitter import *
```

**Result:** PASS — all imports resolve. No `__init__.py` files are present; Python 3.12 namespace packages handle this, but explicit `__init__.py` files would improve tooling compatibility.

---

## 2. Integration tests (live server)

### HTTP routes

| Test | Result | Notes |
|------|--------|-------|
| `GET /` from localhost | PASS | 307 → `/dashboard` |
| `GET /dashboard` | PASS | Returns dashboard HTML |
| `GET /worker` | PASS | Returns worker HTML |
| `POST /disconnect/{unknown}` | PASS | `{ "success": false }` |

### Jobs API

| Test | Result | Notes |
|------|--------|-------|
| `POST /jobs` monte_carlo | PASS | Validates and echoes payload |
| `POST /jobs` matrix_multiply | PASS | Validates and echoes payload |
| `POST /jobs` mandelbrot | PASS | Validates and echoes payload |
| `POST /jobs` invalid workload | PASS | 422 Unprocessable Entity |
| `GET /jobs` | PASS | Placeholder response (no listing) |
| `GET /jobs/{id}` | PASS | Placeholder response |

### WebSocket (`/ws`)

| Test | Result | Notes |
|------|--------|-------|
| Register → register_ack | PASS | UUID echoed, state `Idle` |
| Heartbeat | PASS | Accepted without error |
| Ping → pong | PASS | Latency computed and stored |

### Server-Sent Events (`/events`)

| Test | Result | Notes |
|------|--------|-------|
| SSE stream opens | PASS | 200, `text/event-stream` |
| Initial worker snapshot | PASS | JSON array with registered worker |

### Disconnect flow

| Test | Result | Notes |
|------|--------|-------|
| Disconnect while online | PASS | Closes socket → worker marked offline |
| Remove while offline | PASS | Record removed from registry |

---

## 3. Workload splitter tests

Splitters are not invoked by the running application. They were tested in isolation:

### Happy path

| Splitter | Result | Error |
|----------|--------|-------|
| `MonteCarloSplitter.split(job, 4)` | **FAIL** | `'MonteCarloJob' object has no attribute 'job_id'` |
| `MatrixMultiplySplitter.split(job)` | **FAIL** | `'MatrixMultiplyJob' object has no attribute 'job_id'` |
| `MandelbrotSplitter.split(job)` | **FAIL** | `'MandelbrotJob' object has no attribute 'job_id'` |

**Root cause:** All three splitters pass `job_id=job.job_id` when constructing `Task` objects, but `MonteCarloJob`, `MatrixMultiplyJob`, and `MandelbrotJob` in `models/jobs.py` do not define a `job_id` field. The `Task` model has `job_id: UUID = Field(default_factory=uuid4)`, so each task would get a random ID even if the attribute access were fixed without adding a shared job-level ID.

**Recommended fix:**

```python
# models/jobs.py — add to each job class or a shared base:
job_id: UUID = Field(default_factory=uuid4)
```

Then ensure all tasks from one submission share the same `job_id`.

### Input validation (error paths)

| Test | Result |
|------|--------|
| Monte Carlo: `num_tasks=0` | PASS — raises `ValueError` |
| Monte Carlo: `samples=0` | PASS — raises `ValueError` |
| Matrix: `block_size=0` | PASS — raises `ValueError` |
| Mandelbrot: `tile_size=0` | PASS — raises `ValueError` |

---

## 4. Protocol & timing verification

Cross-checked implementation against [protocol.md](protocol.md):

| Parameter | Documented | Code location | Match |
|-----------|------------|---------------|-------|
| Worker heartbeat interval | 5000 ms | `worker.js` `HEARTBEAT_INTERVAL` | Yes |
| Controller ping interval | 5 s | `monitoring.py` `ping_workers` | Yes |
| Heartbeat timeout | 15 s | `monitoring.py` `HEARTBEAT_TIMEOUT` | Yes |
| Timeout check frequency | 1 s | `monitoring.py` `monitor_heartbeats` | Yes |
| Register upsert by UUID | Yes | `websocket.py` | Yes |
| Offline workers kept in registry | Yes | `websocket.py` disconnect handler | Yes |
| Dashboard snapshot (not diff) | Yes | `events.py` + `dashboard.js` | Yes |
| Disconnect / Remove two-step | Yes | `routes.py` + `dashboard.js` | Yes |

---

## 5. Known gaps & risks

| Item | Severity | Description |
|------|----------|-------------|
| Missing `job_id` on job models | **High** | Blocks all splitter usage and Phase 2 |
| Jobs API placeholders | Medium | No store, dispatch, or results |
| `WorkerStates.BUSY` unused | Low | Expected — Phase 2 |
| Plain `ws://` in worker.js | Low | No TLS; fine for dev, not production |
| In-memory registry | Low | State lost on restart; expected for Phase 1 |
| No automated test suite | Low | Validation was manual/scripted this run |
| Dashboard colspan mismatch | Cosmetic | Empty-state row uses `colspan="6"` in JS but table has 7 columns |

---

## 6. Reproducing this validation

Start the controller:

```bash
source venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8765
```

Install test dependency and run integration checks:

```bash
pip install httpx websockets
# Run the validation script used during this report (or use curl + browser manually)
```

Manual browser check:

1. Open `http://127.0.0.1:8765/dashboard`
2. Open `http://127.0.0.1:8765/worker` in another tab
3. Confirm worker appears with state `Idle`, cores, memory, and latency within ~10 s
4. Click **Disconnect** → state becomes `Offline`
5. Click **Remove** → row disappears

---

## 7. Conclusion

**Phase 1 is validated and working.** The controller reliably registers workers, measures latency, detects stale connections, streams live updates to the dashboard, and handles disconnect/remove flows.

**Phase 2 prerequisites need attention:** add `job_id` to job models, wire splitters into `POST /jobs`, implement task dispatch over WebSocket, and replace placeholder job endpoints with a real job store.
