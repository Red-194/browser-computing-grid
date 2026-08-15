# Commands Cheat Sheet

Here are some useful PowerShell commands for managing the `browser-computing-grid` project locally on Windows.

## 🐍 Python Server (FastAPI / Uvicorn)

### Start the server
Starts the controller server on port 8000, listening on all network interfaces (`0.0.0.0`), with live reload enabled.
```powershell
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
*(Note: If you are using a virtual environment, make sure to activate it first with `.\venv\Scripts\activate`)*

### Kill a running server
If you get a `[WinError 10013]` error, the server is already running in the background. Run this one-liner to automatically find and kill the process holding port 8000:
```powershell
Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force }
```
*Or using taskkill:*
```powershell
taskkill /F /PID <PID>
```

---

## 🦀 WebAssembly (Wasm)

### Build the Wasm Benchmark Module
Recompiles the Rust code in `wasm-bench/src` and bundles it for the web.
```powershell
cd wasm-bench
.\build.ps1
```
*(This uses `wasm-pack` and generates the `wasm-bench/harness/pkg` directory).*

### Generate Network Payloads
If you only need to regenerate the `ping.bin` and `payload-*.bin` files without rebuilding Rust.
```powershell
cd wasm-bench
fsutil file createnew harness/ping.bin 1
fsutil file createnew harness/payload-100k.bin 102400
fsutil file createnew harness/payload-500k.bin 512000
```

---

## 🌐 Network & Firewall

### Resolve your Local IP Address
Find your `192.168.x.x` LAN IP to share with other devices.
```powershell
ipconfig | findstr IPv4
```

### Allow Python through Windows Firewall
If other devices can't connect to your Python server on port 8000, open an **Administrator** PowerShell window and run:
```powershell
netsh advfirewall firewall add rule name="Python-Grid-8000" dir=in action=allow protocol=TCP localport=8000
```
