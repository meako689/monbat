# 05 FastAPI dashboard endpoints and minimalist UI architecture

Type: prototype
Status: resolved
Blocked by: 04

## Question

How should the FastAPI application, lifespan Poller coroutine, Jinja2 template structure, minimalist CSS, and client-side auto-refresh (HTMX or fetch polling) be structured to display current status for both batteries with zero framework bloat?

## Answer

Validated through prototype [prototype_dashboard.py](../../src/monbat/prototype_dashboard.py):

1. **FastAPI Lifespan Management**:
   - Single entry point: FastAPI `@asynccontextmanager async def lifespan(app: FastAPI)` initializes the `TelemetryRepository` and spawns `run_poller_task` via `asyncio.create_task()`.
   - On server shutdown, the background task is cancelled cleanly and awaited with `asyncio.CancelledError` handling.

2. **Endpoints**:
   - `GET /`: Returns the full responsive HTML Dashboard page with dark-mode styling and initial render.
   - `GET /api/latest`: Returns a JSON dictionary of the latest telemetry snapshots for all configured batteries.
   - `GET /api/history?hours=24`: Returns time-series data for historical analysis and follow-up charting.

3. **100% Offline-Ready Minimalist UI**:
   - Zero external CDN dependencies (fonts, frameworks, or scripts) ensuring complete offline usability on the offgrid Linux laptop.
   - Self-contained modern CSS grid & dark theme (< 120 lines):
     - Responsive cards per battery (battery name, Bleak device address, status badge: `charging` / `discharging` / `offline`).
     - Dynamic SOC percentage with color-coded progress fill bar.
     - Key metrics grid: Voltage (V), Current (A, signed with charge/discharge colors), Power (W), Remaining & Total Capacity (Ah), Cell & BMS temperatures (°C).
     - Cell voltages block: individual cell voltages (e.g. `C1: 3.325V`, etc.) and cell delta ($\Delta V$).
   - Vanilla JS auto-refresh loop (`setInterval(updateDashboard, 10000)`) fetching `/api/latest` without external JS dependencies.
