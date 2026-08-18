# Helpful Commands

Useful commands for running, testing, and debugging the Browser Computing Grid.

## Setup

### Install Python dependencies
```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

`requirements.txt` currently pulls in `fastapi`, `uvicorn[standard]`, `jinja2`, `pydantic`, and `Pillow` (used by `MandelbrotAggregator` to encode the final PNG).

### Build the WASM runtime (only needed if you change `runtime/src`)

The runtime is built directly with Rust's WASM target plus `wasm-bindgen` — this project does **not** use `wasm-pack`.

```bash
cd runtime
cargo build --release --target wasm32-unknown-unknown
wasm-bindgen --target web --out-dir pkg --out-name runtime \
  target/wasm32-unknown-unknown/release/runtime.wasm
```

- `cargo build --release --target wasm32-unknown-unknown` compiles the crate to `target/wasm32-unknown-unknown/release/runtime.wasm`.
- `wasm-bindgen` then generates the browser-facing glue in `runtime/pkg/`: `runtime.js`, `runtime_bg.wasm`, `runtime.d.ts`, `runtime_bg.wasm.d.ts`.

`runtime/pkg/` is what the controller mounts at `/runtime` and what `worker.js` imports (`import init, { execute_task } from "/runtime/runtime.js"`) — it must exist for a worker page to load. A prebuilt `runtime/pkg/` is already checked into the repository, so this step is optional unless you're modifying a kernel. `runtime/target/` (Cargo's own build output directory) is a build artifact and should not be committed or packaged.

## Server Commands

### Start the Python Server
Run this from the root directory of the project to start the server:
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Force Kill All Python Servers
If your server gets stuck, hangs on connecting, or tells you the port is already in use, you likely have "ghost" Python servers running in the background.

**Windows (PowerShell):**
```powershell
Stop-Process -Name "python", "uvicorn" -Force -ErrorAction SilentlyContinue
```

**macOS / Linux:**
```bash
pkill -f uvicorn
```

## Testing

### Python unit tests (splitter, aggregator)
```bash
pytest tests/
```

### Rust unit tests (WASM kernel)
```bash
cd runtime
cargo test
```

## Using the grid

### Submit a job
`mandelbrot` is the only currently supported workload — see [../README.md](../README.md#current-workload-mandelbrot).
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

### Retrieve a job's result
```bash
curl http://127.0.0.1:8000/jobs/<job_id>/result --output result.png
```
Returns a "still processing" message until the job's aggregator reports complete, then the aggregator's result — `image/png` for `mandelbrot`.

## Network & Connectivity

### Find Your Local IP Address
To find the IP address that your other devices need to connect to:

**Windows (PowerShell):**
```powershell
ipconfig
```
*(Look for the `IPv4 Address` under your active Wi-Fi or Ethernet adapter)*

**macOS / Linux:**
```bash
ifconfig | grep "inet " | grep -v 127.0.0.1
```

### Allow Port 8000 through Windows Firewall
If other devices on your network are timing out or unable to reach the server, Windows Defender Firewall might be blocking incoming connections.

Open **PowerShell as Administrator** and run:
```powershell
New-NetFirewallRule -DisplayName "Browser Grid Port 8000" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow
```

*(Note: If you are using a mobile hotspot, also ensure your Network Profile is set to "Private" in Windows Wi-Fi settings).*
