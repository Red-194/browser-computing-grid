# Validation Report

**Scope:** the current typed job/aggregator architecture (discriminated-union `JobSubmission`, dynamic splitter/aggregator loading, generic `aggregator.get_result()`/`result_type` result API) — Mandelbrot is the only implemented workload.

## Summary

| Category | Result | Basis |
|---|---|---|
| Python unit tests (`pytest tests/`) — Mandelbrot splitter + aggregator | PASS | Automated test suite |
| Rust unit tests (`cargo test`, `runtime/`) — Mandelbrot kernel | PASS | Automated test suite |
| WASM release build (`cargo build --release --target wasm32-unknown-unknown`) | PASS | Build validation |
| `wasm-bindgen` browser-artifact generation from the release binary | PASS | Build validation |
| Single-worker Mandelbrot job, end-to-end | PASS | Manual observation |
| Three-worker Mandelbrot job (laptop, phone, Raspberry Pi 5), end-to-end | PASS | Manual observation |

This report distinguishes three levels of confidence, used consistently below:

- **Automated test** — an automated test exists and passes.
- **Build validation** — the corresponding build/toolchain step completed successfully.
- **Manual observation** — a person ran the system and directly observed the described behavior.

Anything not covered by one of these three categories is *not* claimed as validated in this document.

---

## 1. Automated tests

### Python (`pytest tests/`)

`tests/test_splitter.py` and `tests/test_aggregator.py` cover the Mandelbrot workload:

- `test_mandelbrot_splitter` — submits a 256×256 job with 128×128 tiles, verifies the splitter produces exactly 4 tasks with correct `row_block`/`col_block` coordinates and sequential `task_id`s.
- `test_mandelbrot_aggregator` — feeds four 128×128 tiles into `MandelbrotAggregator`, verifies `is_complete()` after all four, and verifies `get_result()` returns bytes with a valid PNG signature.

**Result: PASS.**

### Rust (`cargo test`, run from `runtime/`)

`runtime/tests/kernel_tests.rs` covers the Mandelbrot kernel with three cases: a full 10×10 tile, a mid-grid 10×10 tile within a larger image, and a partial 5×5 edge tile (25×25 image, tile size 10, so the last tile is clipped).

**Result: PASS.**

---

## 2. Build validation

The WASM runtime is built directly with `wasm-bindgen`, not `wasm-pack`:

```bash
cd runtime
cargo build --release --target wasm32-unknown-unknown
wasm-bindgen --target web --out-dir pkg --out-name runtime \
  target/wasm32-unknown-unknown/release/runtime.wasm
```

- `cargo build --release --target wasm32-unknown-unknown` — **PASS**, produces `target/wasm32-unknown-unknown/release/runtime.wasm`.
- `wasm-bindgen` against that binary — **PASS**, produces the browser-facing glue checked into `runtime/pkg/` (`runtime.js`, `runtime_bg.wasm`, `runtime.d.ts`, `runtime_bg.wasm.d.ts`), which the controller mounts at `/runtime` and `worker.js` imports directly.

See [commands.md](commands.md) for the full command reference.

---

## 3. Manual end-to-end validation

### Single-worker Mandelbrot job

A Mandelbrot job was submitted with a single worker connected and ran to completion: the job was split into tasks, the worker executed them in the WASM runtime, task results were aggregated, and the final image was retrieved via `GET /jobs/{id}/result`.

**Result: PASS.**

### Three-worker Mandelbrot job

A single Mandelbrot job was distributed across three simultaneously connected, heterogeneous workers:

- a laptop
- a phone
- a Raspberry Pi 5

Job parameters: a 2048×2048 image split into 128×128 tiles, producing **256 tasks**. All 256 task results were received by the controller, aggregation completed (`is_complete()` became true), and the final 2048×2048 image was successfully generated and retrieved through `GET /jobs/{id}/result`.

**Result: PASS.**

This confirms, for at least this one run:
- the Round Robin scheduler correctly distributed 256 tasks across three heterogeneous, concurrently connected workers,
- each worker's WASM runtime executed its assigned Mandelbrot tiles correctly regardless of device class (laptop / phone / Raspberry Pi 5),
- the controller correctly aggregated results arriving from multiple independent workers into one coherent final image.

No per-worker task counts, timings, or worker→task mappings are recorded here beyond what's stated above, since none were established by the available logs.

---

## 4. What this report does not claim

- No benchmark numbers (throughput, latency distributions, makespan, etc.) are reported — none were measured in a way that could be included here without fabrication.
- No claim is made about behavior under worker failure, disconnect-mid-task, or heavier concurrent job load — these have not been manually tested.
- No claim is made about any workload other than `mandelbrot` — no other workload exists in the codebase to test.
- Live HTTP/WebSocket/SSE endpoints beyond the job flows described above (e.g. `GET /jobs`, `GET /jobs/{id}`, `DELETE /jobs/{id}`, the dashboard's disconnect/remove flow) are code-verified in [architecture.md](architecture.md) and [protocol.md](protocol.md) but are not separately re-validated in this report.

---

## 5. Known limitations (not bugs — see [architecture.md](architecture.md) and [README.md](../README.md))

| Item | Description |
|---|---|
| Single workload | Only `mandelbrot` is implemented; the architecture supports adding more but none exist yet |
| `WorkerStates.BUSY` unused | Scheduler can assign further tasks to a worker that already has one in flight |
| No task reassignment on worker disconnect | A task lost mid-flight is never retried; its job never completes |
| Plain `ws://` | No TLS; fine for LAN/dev, not production |
| In-memory registry / job state | Lost on controller restart; expected at this stage |
| `GET /jobs`, `GET /jobs/{id}`, `DELETE /jobs/{id}` | Documented placeholders — static responses, no job store lookup |

---

## 6. Reproducing this validation

```bash
# Python unit tests
pytest tests/

# Rust unit tests
cd runtime && cargo test

# WASM release build + browser artifacts
cd runtime
cargo build --release --target wasm32-unknown-unknown
wasm-bindgen --target web --out-dir pkg --out-name runtime \
  target/wasm32-unknown-unknown/release/runtime.wasm

# Live integration (requires a browser + two terminals)
uvicorn app.main:app --host 127.0.0.1 --port 8000
# then open /dashboard and /worker as described in README.md, and:
curl -X POST http://127.0.0.1:8000/jobs -H "Content-Type: application/json" -d '{...mandelbrot config...}'
curl http://127.0.0.1:8000/jobs/<job_id>/result --output result.png
```

## 7. Conclusion

The controller lifecycle (registration, heartbeat, latency, disconnect/remove, dashboard) and the full Mandelbrot job pipeline (submit → typed validation → split → schedule → dispatch → WASM execution → aggregate → generic result retrieval) are validated by a combination of automated tests, successful builds, and direct manual observation, including a real multi-device (laptop/phone/Raspberry Pi 5), 256-task run. No other workload is implemented, so no other workload's end-to-end behavior is claimed here.
