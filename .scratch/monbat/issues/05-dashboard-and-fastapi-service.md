# 05 FastAPI dashboard endpoints and minimalist UI architecture

Type: prototype
Status: resolved
Blocked by: 04

## Question

How should the FastAPI application, lifespan Poller coroutine, self-contained HTML and CSS, and client-side auto-refresh be structured to display current status for both batteries with zero framework bloat?

## Answer

The Dashboard layout and auto-refresh were prototyped in
[prototype_dashboard.py](../../src/monbat/prototype_dashboard.py). The
implementation contract below also defines how `/api/latest` represents
batteries that have no stored reading.

1. **FastAPI Lifespan Management**:
   - `serve()` creates one configured `TelemetryRepository` and injects it into
     the app factory. FastAPI's `@asynccontextmanager` lifespan initializes that
     instance and passes it to `run_poller_task`; routes use the same instance.
   - On server shutdown, the background task is cancelled cleanly and awaited with `asyncio.CancelledError` handling.

2. **Endpoints**:
   - `GET /`: Returns the full responsive HTML Dashboard page with dark-mode styling and initial render.
   - `GET /api/latest`: Returns one entry for every configured battery ID; the
     value is `null` when that battery has no reading.
   - `GET /api/history?hours=24`: Returns time-series data for historical
     analysis; the graph UI is planned for Iteration 2.

3. **100% Offline-Ready Minimalist UI**:
   - Zero external CDN dependencies (fonts, frameworks, or scripts) ensuring complete offline usability on the offgrid Linux laptop.
   - Self-contained modern CSS grid & dark theme (< 120 lines):
     - Responsive cards per battery (battery name, Bleak device address, status badge: `charging` / `discharging` / `offline`).
     - Dynamic SOC percentage with color-coded progress fill bar.
     - Key metrics grid: Voltage (V), Current (A, signed with charge/discharge colors), Power (W), Remaining & Total Capacity (Ah), Cell & BMS temperatures (°C).
     - Cell voltages block: individual cell voltages (e.g. `C1: 3.325V`, etc.) and cell delta ($\Delta V$).
   - Vanilla JS auto-refresh loop (`setInterval(updateDashboard, 10000)`) fetching `/api/latest` without external JS dependencies.
