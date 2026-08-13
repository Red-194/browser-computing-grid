# Helpful Commands

Here is a list of useful commands for managing and debugging the Browser Computing Grid.

## Server Commands

### Start the Python Server
Run this from the root directory of the project to start the server:
```powershell
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
pkill -f python
```

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
