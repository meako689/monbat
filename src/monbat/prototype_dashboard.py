"""PROTOTYPE: FastAPI Dashboard & UI Architecture.

Throwaway prototype validating the Dashboard HTML/CSS layout, offline auto-refresh,
FastAPI lifespan poller pattern, and lightweight endpoints.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
import json
import sys
import time
from typing import Any

# ==============================================================================
# Domain Models & In-Memory State
# ==============================================================================

@dataclass(frozen=True, slots=True)
class BatteryConfig:
    id: str
    name: str
    mac_address: str


@dataclass(frozen=True, slots=True)
class BatteryState:
    config: BatteryConfig
    voltage_v: float
    current_a: float
    power_w: float
    soc_percent: float
    remaining_ah: float
    capacity_ah: float
    cell_temp_c: int
    bms_temp_c: int
    cell_voltages: tuple[float, ...]
    last_updated: float
    status: str  # "charging" | "discharging" | "idle" | "offline"


# Sample mock data simulating 2 Redodo LiFePO4 batteries
MOCK_BATTERIES: dict[str, BatteryState] = {
    "bat-1": BatteryState(
        config=BatteryConfig(id="bat-1", name="Redodo 100Ah (Bank 1)", mac_address="AA:BB:CC:11:22:33"),
        voltage_v=13.310,
        current_a=14.250,
        power_w=189.67,
        soc_percent=86.5,
        remaining_ah=86.5,
        capacity_ah=100.0,
        cell_temp_c=22,
        bms_temp_c=25,
        cell_voltages=(3.328, 3.327, 3.328, 3.327),
        last_updated=time.time(),
        status="charging",
    ),
    "bat-2": BatteryState(
        config=BatteryConfig(id="bat-2", name="Redodo 100Ah (Bank 2)", mac_address="AA:BB:CC:44:55:66"),
        voltage_v=13.295,
        current_a=14.180,
        power_w=188.52,
        soc_percent=85.8,
        remaining_ah=85.8,
        capacity_ah=100.0,
        cell_temp_c=23,
        bms_temp_c=26,
        cell_voltages=(3.324, 3.325, 3.323, 3.323),
        last_updated=time.time(),
        status="charging",
    ),
}

# ==============================================================================
# HTML & CSS: Completely Self-Contained, 100% Offline Ready (Zero CDN Calls)
# ==============================================================================

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>monbat &bull; Offgrid Battery Monitor</title>
  <style>
    :root {
      --bg: #121418;
      --card-bg: #1c2026;
      --border: #2e3540;
      --text: #e6edf3;
      --text-muted: #8b949e;
      --accent: #58a6ff;
      --green: #3fb950;
      --amber: #d29922;
      --red: #f85149;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background-color: var(--bg);
      color: var(--text);
      padding: 1.5rem;
      max-width: 1200px;
      margin: 0 auto;
    }
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 1.5rem;
      border-bottom: 1px solid var(--border);
      padding-bottom: 1rem;
    }
    h1 { font-size: 1.5rem; display: flex; align-items: center; gap: 0.5rem; }
    .pulse-dot {
      width: 10px; height: 10px; border-radius: 50%; background: var(--green);
      box-shadow: 0 0 8px var(--green);
    }
    .meta-status { font-size: 0.85rem; color: var(--text-muted); }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
      gap: 1.5rem;
      margin-bottom: 1.5rem;
    }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 1.25rem;
      display: flex;
      flex-direction: column;
      gap: 1rem;
    }
    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
    }
    .card-title { font-size: 1.15rem; font-weight: 600; }
    .mac-sub { font-size: 0.75rem; color: var(--text-muted); font-family: monospace; }
    .badge {
      font-size: 0.75rem;
      padding: 0.2rem 0.5rem;
      border-radius: 12px;
      font-weight: 600;
      text-transform: uppercase;
    }
    .badge.charging { background: rgba(63, 185, 80, 0.2); color: var(--green); border: 1px solid var(--green); }
    .badge.discharging { background: rgba(210, 153, 34, 0.2); color: var(--amber); border: 1px solid var(--amber); }
    .badge.offline { background: rgba(248, 81, 73, 0.2); color: var(--red); border: 1px solid var(--red); }
    
    .soc-container { display: flex; flex-direction: column; gap: 0.4rem; }
    .soc-label-row { display: flex; justify-content: space-between; font-weight: bold; font-size: 1.25rem; }
    .progress-bar {
      height: 12px;
      background: #2b313a;
      border-radius: 6px;
      overflow: hidden;
    }
    .progress-fill {
      height: 100%;
      background: var(--green);
      transition: width 0.3s ease;
    }

    .metrics-grid {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 0.75rem;
      background: #15181c;
      padding: 0.75rem;
      border-radius: 6px;
    }
    .metric-item { display: flex; flex-direction: column; gap: 0.15rem; }
    .metric-label { font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; }
    .metric-value { font-size: 1.1rem; font-weight: 600; font-feature-settings: "tnum"; }
    .metric-value.charge { color: var(--green); }
    .metric-value.discharge { color: var(--amber); }

    .cells-block {
      background: #15181c;
      padding: 0.75rem;
      border-radius: 6px;
      font-size: 0.8rem;
    }
    .cells-header { display: flex; justify-content: space-between; margin-bottom: 0.4rem; color: var(--text-muted); }
    .cells-chips { display: flex; gap: 0.5rem; flex-wrap: wrap; }
    .cell-chip {
      background: #21262d;
      padding: 0.2rem 0.4rem;
      border-radius: 4px;
      font-family: monospace;
      font-size: 0.85rem;
    }
  </style>
</head>
<body>
  <header>
    <h1><div class="pulse-dot"></div> monbat</h1>
    <div class="meta-status">
      Interval: 30s &bull; Auto-refreshes every 10s &bull; <span id="clock">Syncing...</span>
    </div>
  </header>

  <div class="grid" id="batteries-grid">
    <!-- Populated by server render or client auto-refresh -->
  </div>

  <script>
    // 100% Offline Vanilla JS refresh loop: Zero external libraries/CDNs
    async function updateDashboard() {
      try {
        const res = await fetch('/api/latest');
        if (!res.ok) return;
        const data = await res.json();
        renderBatteries(data);
        document.getElementById('clock').textContent = 'Updated ' + new Date().toLocaleTimeString();
      } catch (err) {
        document.getElementById('clock').textContent = 'Connection paused';
      }
    }

    function renderBatteries(batteries) {
      const container = document.getElementById('batteries-grid');
      container.innerHTML = Object.values(batteries).map(b => {
        const delta = (Math.max(...b.cell_voltages) - Math.min(...b.cell_voltages)).toFixed(3);
        const currentClass = b.current_a > 0 ? 'charge' : (b.current_a < 0 ? 'discharge' : '');
        const currentSign = b.current_a > 0 ? '+' : '';
        const powerSign = b.power_w > 0 ? '+' : '';

        return `
          <div class="card">
            <div class="card-header">
              <div>
                <div class="card-title">${b.config.name}</div>
                <div class="mac-sub">${b.config.mac_address}</div>
              </div>
              <span class="badge ${b.status}">${b.status}</span>
            </div>

            <div class="soc-container">
              <div class="soc-label-row">
                <span>State of Charge</span>
                <span>${b.soc_percent.toFixed(1)}%</span>
              </div>
              <div class="progress-bar">
                <div class="progress-fill" style="width: ${Math.min(100, Math.max(0, b.soc_percent))}%"></div>
              </div>
            </div>

            <div class="metrics-grid">
              <div class="metric-item">
                <span class="metric-label">Voltage</span>
                <span class="metric-value">${b.voltage_v.toFixed(2)} V</span>
              </div>
              <div class="metric-item">
                <span class="metric-label">Current</span>
                <span class="metric-value ${currentClass}">${currentSign}${b.current_a.toFixed(2)} A</span>
              </div>
              <div class="metric-item">
                <span class="metric-label">Power</span>
                <span class="metric-value ${currentClass}">${powerSign}${b.power_w.toFixed(0)} W</span>
              </div>
              <div class="metric-item">
                <span class="metric-label">Capacity</span>
                <span class="metric-value">${b.remaining_ah.toFixed(1)} / ${b.capacity_ah.toFixed(0)} Ah</span>
              </div>
              <div class="metric-item">
                <span class="metric-label">Cell Temp</span>
                <span class="metric-value">${b.cell_temp_c} &deg;C</span>
              </div>
              <div class="metric-item">
                <span class="metric-label">BMS Temp</span>
                <span class="metric-value">${b.bms_temp_c} &deg;C</span>
              </div>
            </div>

            <div class="cells-block">
              <div class="cells-header">
                <span>Cell Voltages (${b.cell_voltages.length}S)</span>
                <span>&Delta; ${delta} V</span>
              </div>
              <div class="cells-chips">
                ${b.cell_voltages.map((cv, i) => `<span class="cell-chip">C${i+1}: ${cv.toFixed(3)}V</span>`).join('')}
              </div>
            </div>
          </div>
        `;
      }).join('');
    }

    // Initial tick & recurring 10s poll
    updateDashboard();
    setInterval(updateDashboard, 10000);
  </script>
</body>
</html>
"""

# ==============================================================================
# FastAPI Architecture Specification (Target Implementation)
# ==============================================================================

def create_fastapi_app_spec() -> str:
    """Returns the code structure to be implemented in src/monbat/app.py."""
    return '''
from contextlib import asynccontextmanager
import asyncio
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from monbat.db import TelemetryRepository
from monbat.poller import run_poller_task

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize DB and spawn poller task
    repo = TelemetryRepository("monbat.db")
    repo.init_db()
    poller_task = asyncio.create_task(run_poller_task(repo))
    yield
    # Shutdown: Cancel background poller
    poller_task.cancel()
    try:
        await poller_task
    except asyncio.CancelledError:
        pass

app = FastAPI(title="monbat", lifespan=lifespan)

@app.get("/", response_class=HTMLResponse)
async def dashboard_page():
    return HTML_TEMPLATE

@app.get("/api/latest")
async def get_latest_telemetry():
    # Returns latest snapshot for both batteries as JSON
    ...

@app.get("/api/history")
async def get_telemetry_history(hours: int = 24):
    # Returns downsampled history for charting
    ...
'''

# ==============================================================================
# Runnable Prototype Webserver (Standard Library Fallback)
# ==============================================================================

def run_prototype_server(port: int = 8088) -> None:
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class PrototypeHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/" or self.path == "/index.html":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(HTML_TEMPLATE.encode("utf-8"))
            elif self.path == "/api/latest":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                payload = {k: asdict(v) for k, v in MOCK_BATTERIES.items()}
                self.wfile.write(json.dumps(payload).encode("utf-8"))
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            sys.stderr.write(f"HTTP log: {format % args}\n")

    import threading
    import urllib.request

    server = HTTPServer(("127.0.0.1", port), PrototypeHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    print(f"Prototype server running at http://127.0.0.1:{port}/")
    print("Testing GET / request...")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f"http://127.0.0.1:{port}/") as req:
        print(f"HTTP GET / status: {req.status}, Content-Length: {len(req.read())} bytes")

    with opener.open(f"http://127.0.0.1:{port}/api/latest") as api_req:
        api_data = json.loads(api_req.read().decode())
        print(f"HTTP GET /api/latest status: {api_req.status}, Batteries returned: {list(api_data.keys())}")

    server.shutdown()
    server.server_close()
    print("Self-test completed successfully.")


def main() -> None:
    print("=== monbat Dashboard & UI Prototype ===")
    print("Target FastAPI Lifespan Architecture:")
    print(create_fastapi_app_spec())
    print("\nRunning self-contained HTTP verification test...")
    run_prototype_server()


if __name__ == "__main__":
    main()
