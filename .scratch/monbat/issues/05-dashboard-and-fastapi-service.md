# 05 FastAPI dashboard endpoints and minimalist UI architecture

Type: prototype
Status: resolved
Blocked by: 04

## Question

How should the FastAPI application, lifespan Poller coroutine, self-contained HTML and CSS, and client-side auto-refresh be structured to display current status for both batteries with zero framework bloat?

## Answer

The Dashboard layout and auto-refresh were prototyped in
[prototype_dashboard.py](https://github.com/<user>689/monbat/blob/6c99208320fdfb2a008e10648f16b657a5c01f9c/src/monbat/prototype_dashboard.py). The
implementation contract below also defines how `/api/latest` represents
batteries that have no stored reading.

1. **FastAPI Lifespan Management**:
   - `serve()` creates one configured `TelemetryRepository` and injects it into
     the app factory. FastAPI's `@asynccontextmanager` lifespan initializes that
     instance and passes it to `run_poller_task`; routes use the same instance.
   - On server shutdown, the background task is cancelled cleanly and awaited with `asyncio.CancelledError` handling.

2. **Endpoints**:
   - `GET /`: Returns the full responsive HTML Dashboard page with dark-mode styling and initial render.
   - `GET /api/latest`: Returns one entry for every configured battery ID. Each
     value includes configured name and address, optional Telemetry, status,
     and cell delta. The API view matches the configured battery ID to stored
     `battery_id`; a missing reading keeps the view and sets Telemetry to null.
     A missing reading has `no-reading-yet` status; a stored reading is
     `offline` after twice the configured poll interval, otherwise its status
     is derived from the current sign (`charging`, `discharging`, or `idle`).
     Cell delta is returned in mV, or null when no cells are available.
   - `GET /api/history?hours=24`: Returns a plain chronological list of rows,
     each tagged with battery ID, configured name and address, and Telemetry;
     the graph UI is planned for Iteration 2.

3. **100% Offline-Ready Minimalist UI**:
   - Zero external CDN dependencies (fonts, frameworks, or scripts) ensuring complete offline usability on the offgrid Linux laptop.
   - Self-contained modern CSS grid & dark theme (< 120 lines):
     - Responsive cards per battery (battery name, Bleak device address, and status badge: `no-reading-yet` / `charging` / `discharging` / `idle` / `offline`). Mark the last reading offline when its timestamp is older than twice the configured poll interval.
     - Dynamic SOC percentage with color-coded progress fill bar.
     - Key metrics grid: Voltage (V), Current (A, signed with charge/discharge colors), Power (W), Remaining & Total Capacity (Ah), Cell & BMS temperatures (°C).
     - Cell voltages block: individual cell voltages (e.g. `C1: 3.325V`, etc.) and cell delta ($\Delta V$).
   - Vanilla JS auto-refresh loop (`setInterval(updateDashboard, 10000)`) fetching `/api/latest` without external JS dependencies.

## Comments

- 2026-10-17: Retired the superseded prototype in ticket 15. The link above
  preserves its last version. Current Dashboard behavior is specified in
  spec sections 4.4–4.6 and implemented in `src/monbat/app.py`.

- 2026-10-16: Updated the API view contract to include configured battery
  metadata, derive status from current sign and telemetry age, and return
  history as a plain chronological list. A missing reading retains its config
  view with `telemetry: null` and `no-reading-yet` status. Cell delta is an API
  view field in mV and is null for an empty cell list.
