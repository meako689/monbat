# monbat Technical Architecture & Implementation Specification

## 1. Executive Summary & Purpose

`monbat` is a lightweight, local battery monitoring service for a home offgrid power bank composed of two (2) Bluetooth-enabled Redodo LiFePO4 batteries. Linux Mint is the primary deployment target; macOS is also supported for development and operation through Bleak's CoreBluetooth backend. Both platforms require a compatible BLE adapter and operating-system permissions.

The system uses one sequential BLE Poller with a configurable background delay
(30 seconds by default; the user's deployment uses 10 minutes). Dashboard
updates every 30 seconds can wake that Poller asynchronously. It stores
Telemetry in SQLite WAL mode and serves an offline Dashboard with a parallel
Battery Bank summary.

This spec includes implemented work in tickets 11–13. Earlier resolved tickets record the previous
implementation.

---

## 2. Platform & Toolchain Standards

* **Primary Operating System**: Linux Mint 21.3+ (Ubuntu 22.04 LTS / glibc 2.35, BlueZ 5.64).
* **Also Supported**: macOS through Bleak's CoreBluetooth backend. BLE adapter access and permissions are managed by the host OS; live hardware operation must be confirmed on each host.
* **Python Runtime**: **Python 3.15** managed cleanly in user-space via Astral's `uv` standalone CPython.
* **Package Management**: `uv` (`pyproject.toml` with `requires-python = ">=3.15"`).
* **Coding Standards**:
  * **YAGNI & Minimal Abstractions**: Zero heavy ORMs, zero frontend bundlers, zero external CSS/JS framework dependencies.
  * **Modern Typing**: Specific types, `slots=True, frozen=True` dataclasses, strict typing without `Any`.
  * **Shallow Control Flow**: Guard clauses and early returns; no deeply nested conditional trees.

---

## 3. Domain Model

Domain language follows the project [GLOSSARY.md](../../GLOSSARY.md):

* **Battery**: A physical offgrid LiFePO4 battery pack equipped with an internal BLE BMS.
* **BMS**: Battery Management System communicating via GATT service `0xFFE0`.
* **Telemetry**: Immutable snapshot of measurements, effective SOC and its source,
  BMS state, protection flags, SOH, and cycle count.
* **Poller**: One async task querying Batteries sequentially on a background
  schedule or an eligible Dashboard refresh request.
* **Battery Bank**: Every configured Battery connected in parallel at the same
  nominal voltage; summary SOC is capacity-weighted and power is net signed watts.
* **Freshness**: Maximum age of Telemetry for online status and available totals,
  configured independently of polling intervals.
* **Discovery Script**: Interactive one-off CLI (`monbat discover`) to scan, select, and assign friendly aliases.
* **Dashboard**: Web UI served by FastAPI displaying real-time metrics. Historical charge/discharge graphs are planned for Iteration 2.

---

## 4. Subsystems & Technical Architecture

### 4.1 CLI & Configuration Management

* **Entry Point**: A single unified command in `pyproject.toml`:
  ```toml
  [project.scripts]
  monbat = "monbat:main"
  ```
  * `uv run monbat discover`: Runs the interactive BLE scanner and saves `./config.toml`.
  * `uv run monbat` (or `monbat serve`): Starts the FastAPI web server and background Poller.

* **Configuration Schema (`config.toml`)**:
  ```toml
  [poller]
  poll_interval_seconds = 30
  timeout_seconds = 10.0
  freshness_seconds = 60
  sqlite_path = "monbat.db"

  [server]
  host = "0.0.0.0"
  port = 8000

  [[batteries]]
  id = "bat-1"
  name = "Battery 1 (Upper)"
  address = "AA:BB:CC:11:22:33" # Bleak device address; format depends on host OS

  [[batteries]]
  id = "bat-2"
  name = "Battery 2 (Lower)"
  address = "AA:BB:CC:44:55:66"
  ```
  `poll_interval_seconds` is the background delay after a complete sequential
  polling pass. Preserve configured values, including 600 seconds.
  `freshness_seconds` defaults to 60 when absent and must be finite and positive.
  It applies to every scenario; Dashboard cadence is fixed at 30 seconds.
* **Parsing & Writing**:
  * Read via Python standard library `tomllib`.
  * Written via a lightweight internal serializer without external YAML/TOML writer dependencies.
  * Prompts for user confirmation before overwriting an existing `config.toml`.

---

### 4.2 BLE BMS Protocol & Driver (`src/monbat/bms.py`)

The [external-source wire specification](../../docs/protocol/redodo-wire-spec.md)
is authoritative for protocol framing, widths, fields, and evidence limits.
Its pinned GitHub sources take precedence over current Monbat code and prior
implementation tickets. The [source comparison](../../docs/research/redodo-protocol-sources.md)
records unresolved disagreements; current behavior does not resolve them.

Reimplementation is planned in [tickets 21–25](map.md#protocol-reimplementation).
The [implementation handoff](../../docs/protocol/implementation-handoff.md)
fixes typed field names, API/schema representations, file touchpoints, and
validation for the confirmed scope.
After grilling, the approved target adds balancing cell slots, all five
temperature slots, and the complete problem/failure region. Preserve original
cell-slot numbers throughout typed readings, storage, APIs, and Dashboard.
Persist useful fields and each complete validated BLE response in a fresh
database; do not migrate historical rows. Store the exact realigned declared
frame, including checksum and unknown bytes, as a BLOB alongside its Telemetry
row. History output includes response hex for later retrieval; latest/SSE and
Dashboard use typed fields without repeatedly transmitting full responses. Expose balancing and extra temperatures in Battery
details, keep named protections prominent, and show unknown failure data
as hex. Balancing remains a reference-derived interpretation.

Keep the exact read-only 0x13 query and current ATT write mode unchanged.
Defer heater/control interpretation, second voltage, balance memory, and
discharged-capacity count. Charge/discharge controls are Phase3 roadmap work
in ticket24; they are not authorized for current implementation or execution.

Application policies remain separate from the wire protocol: valid reported
SOC takes precedence, capacity-derived SOC is the bounded fallback, SOH is
nullable outside 0–100, power retains current sign, and freshness/scheduling
follow section 4.4 and operational docs. Existing policy is not evidence for
manufacturer sentinel values. Tickets 21–23 define implementation changes;
ticket 25 retains unresolved semantic questions until external evidence exists.

The earlier ticket 13 balancing exclusion applied to that implementation's
scope. The user's 2026-10-17 request for external-source conformance now
includes preservation of externally documented balancing regions; physical
semantics remain qualified. Historical completed tickets remain historical.


### 4.3 SQLite Telemetry Storage (`src/monbat/db.py`)

* **Database Mode**: Local SQLite database at `monbat.db` (configurable).
* **PRAGMAs**:
  * During database initialization, set `PRAGMA journal_mode = WAL;`.
  * On every connection, set `PRAGMA synchronous = NORMAL;` and
    `PRAGMA busy_timeout = 5000;`.
* **Table Schema**:
  ```sql
  CREATE TABLE IF NOT EXISTS telemetry (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      battery_id TEXT NOT NULL,
      timestamp REAL NOT NULL,
      voltage_v REAL NOT NULL,
      current_a REAL NOT NULL,
      power_w REAL NOT NULL,
      soc_percent REAL NOT NULL,
      remaining_ah REAL NOT NULL,
      capacity_ah REAL NOT NULL,
      cell_temp_c INTEGER NOT NULL,
      bms_temp_c INTEGER NOT NULL,
      cell_voltages_json TEXT NOT NULL,
      reported_soc_percent REAL,
      soc_source TEXT NOT NULL,
      soh_percent REAL,
      cycle_count INTEGER NOT NULL,
      bms_state_raw INTEGER NOT NULL,
      bms_state TEXT NOT NULL,
      protection_flags INTEGER NOT NULL,
      active_protections_json TEXT NOT NULL
  );

  CREATE INDEX IF NOT EXISTS idx_telemetry_battery_time 
  ON telemetry (battery_id, timestamp DESC);
  ```
* **Repository Interface (`TelemetryRepository`)**:
  * `async def init_db() -> None`
  * `async def save_telemetry(battery_id: str, telemetry: BatteryTelemetry) -> None`
  * `async def get_latest_telemetry(battery_id: str) -> BatteryTelemetry | None`
  * `async def get_history(battery_id: str, since_timestamp: float) -> list[BatteryTelemetry]`
  * Each public method runs its complete synchronous `sqlite3` operation inside
    `asyncio.to_thread`; the worker opens and closes its own connection.
  * Persist `BatteryTelemetry.soc_percent` exactly as provided. The repository
    does not derive, normalize, or otherwise transform it on save or read.
  * Start with a fresh schema for ticket 13; historical migrations and old schema
    compatibility are waived. Document a fresh database path. Startup must not
    silently delete an existing database. Persist and read every new field.

---

### 4.4 Web Service & Dashboard (`src/monbat/app.py`)

* **Framework**: FastAPI with lifespan background Poller task.
* **App Construction and Lifespan**: `serve()` creates the configured
  `TelemetryRepository` and passes it to `build_app(config, repo)`. The lifespan,
  Poller, and request handlers use that same repository. The lifespan keeps
  the active Poller reference for refresh requests and clears it before
  cancellation. The abbreviated construction example below omits routes.
  ```python
  def build_app(
      config: AppConfig,
      repo: TelemetryRepository,
      *,
      start_poller: bool = True,
  ) -> FastAPI:
      @asynccontextmanager
      async def lifespan(app: FastAPI):
          await repo.init_db()
          poller_task: asyncio.Task[None] | None = None
          if start_poller:
              poller = Poller(config, repo)
              poller_task = asyncio.create_task(poller.run())
          try:
              yield
          finally:
              if poller_task is not None:
                  poller_task.cancel()
                  try:
                      await poller_task
                  except asyncio.CancelledError:
                      pass
      return FastAPI(lifespan=lifespan)
  ```
* **HTTP Endpoints**:
  * `GET /`: Renders self-contained dark-mode dashboard HTML. A configured
    battery with no reading shows `No reading yet` without telemetry fields.
  * `GET /api/latest`: Returns a JSON dictionary keyed by every configured
    battery ID. Each value includes the configured name and address, an
    optional Telemetry object, a status, and optional cell delta. Match each
    configured battery ID to the database `battery_id`. When no reading exists,
    retain the view object with `telemetry: null` and `no-reading-yet` status.
    Mark a reading `offline` when its age exceeds `freshness_seconds`;
    otherwise derive `charging`, `discharging`, or
    `idle` from current. Calculate cell delta in mV from the cell voltage
    extrema, with `null` when no cell values exist. These status and delta
    fields belong to the API view and are not persisted. Serialize Telemetry
    with `dataclasses.asdict`. Display explicit BMS state separately, including
    Disabled/Unknown, plus active protections and secondary SOH/cycle count.
  * `POST /api/refresh`: Requests a Poller pass; see section 4.5.
  * `GET /api/summary`: Returns the parallel Battery Bank summary; see section 4.6.
  * `GET /api/history?hours=24`: Returns a plain chronological JSON list of
    time-series rows, each tagged with battery ID, configured name and address,
    and Telemetry fields. `hours` must be positive. This is part of the
    Iteration 1 API; the visual graph UI is planned for Iteration 2.
* **Offgrid-Ready UI Architecture**:
  * **100% Offline**: Zero external CDNs, zero web fonts, zero third-party script tags.
  * **Literal Battery Labels**: Escape configured names and addresses as text
    in one shared card header for empty and populated Telemetry views.
  * **Pure CSS Grid Theme**: Responsive multi-card layout with state-of-charge bars, color-coded charge/discharge metrics, cell voltage chips, and delta imbalance indicators.
  * **Vanilla JavaScript Refresh**: On load and every 30 seconds, request a
    refresh and fetch stored latest/summary views using native `fetch()`.
    One update flow settles all three requests and handles their outcomes;
    refresh/latest failures retain cards, while summary failures hide totals.

### 4.5 Dashboard-triggered refresh and freshness

The Poller module in `src/monbat/poller.py` owns refresh admission, the wake
event, and private scheduling state. Its interface is `run()` and
`request_refresh()`. Configuration types and parsing remain in `app.py`;
the lifespan creates, cancels, and awaits one Poller task. Request handlers
never mutate Poller state. A Poller instance reserves its startup pass at
construction and runs once; each lifespan creates a new instance.

One lifespan-owned Poller performs all BLE passes sequentially. It polls on
startup, then waits the configured background delay after each pass. An eligible
Dashboard request wakes it early; finishing that pass restarts the background
delay. Background collection continues with no Dashboard open.

`POST /api/refresh` returns promptly with an `outcome` of `accepted`, `skipped`,
or `disabled`. Acceptance schedules work; it does not promise a successful
reading. Skip requests during a pass, while a pass is already scheduled, or when
less than 30 seconds have elapsed since the last pass started. Skip without a
pending retry. Use monotonic time and atomic admission so multiple tabs cannot
schedule duplicates. With `start_poller=False`, report `disabled`.

Page load and each 30-second update send the refresh request and fetch stored
Telemetry without waiting for BLE completion. New readings appear on a later
update. A failed request retains the cards and reports a connection failure.
No endpoint creates its own BLE task. Shutdown cancels and awaits the Poller.

Freshness uses Telemetry timestamps and wall time: `age > freshness_seconds`
means offline; equality is still fresh. Use the same configured setting for
Battery views and Battery Bank summaries, independently of background timing.
Failed polls retain the original timestamp of the last successful Telemetry.

### 4.6 Parallel Battery Bank summary

Treat every configured Battery as part of one parallel Battery Bank at the same
nominal voltage. The Dashboard section above Battery cards shows one SOC charge
bar and one signed net power value with Charging/Discharging/Idle labeling.

- SOC = `sum(soc_percent * capacity_ah) / sum(capacity_ah)`, using effective SOC
  chosen by the driver and full charge capacity as the weight.
- Power = `sum(power_w)`; positive means charging, negative means discharging,
  zero means idle. Round for display only.
- Require fresh Telemetry and positive capacity from every configured Battery.
  Otherwise display an unavailable summary with no numeric totals or filled
  charge bar. Individual cards retain their last readings.

`GET /api/summary` returns `available`, nullable `soc_percent` and `power_w`,
and nullable `reason`. Missing readings take precedence over stale readings,
then invalid capacity: `missing-reading`, `stale-reading`, `invalid-capacity`.
When unavailable both totals are null. This endpoint reads stored Telemetry;
the Dashboard uses its existing 30-second update cycle, with no additional BLE
timer. A summary fetch failure shows unavailable totals.

---

## 5. Phased Roadmap

1. **Iteration 1 (Core Deliverable)**:
   * Discovery CLI tool (`monbat discover`) saving `config.toml`.
   * Bleak BMS driver with little-endian parsing.
   * SQLite repository with WAL mode.
   * Single-process FastAPI app with background Poller and real-time offline Dashboard.
   * Approved follow-up: Dashboard-triggered refresh and independent freshness
     (11), parallel SOC/net watts (12), and complete protocol/health fields (13).
2. **Iteration 2 (Visual Charting)**:
   * Historical charge/discharge graphs (client-side SVG / uPlot / Chart.js embedded locally) utilizing the `/api/history` endpoint.
3. **Iteration 3 (Additional Bank Metrics & Alerts)**:
   * Net current and optional time-to-empty/time-to-full calculations.
   * System health alerts (low cell voltage, high temperature cutoffs).
   * Linux systemd user service packaging (`monbat.service`).

## Update speed revision — 2026-10-17

This revision supersedes sequential-only polling, Dashboard-triggered passes,
and the fixed 30-second browser update timer above. See tickets 16–19.

SSE `/api/events` delivers initial `latest`/`summary` snapshots and checks saved
readings/freshness each second. First subscriber wakes collection immediately;
subscribers (including hidden tabs) share a 10-second active start cadence.
Last disconnect allows 30 seconds of grace, then closes clients and resumes the
configured long background start interval (new discovery default 600 seconds).
Missed slots are skipped. Persistent connections default enabled during active
collection. Read concurrency defaults to 1, without limiting retained clients.
Failure backoff is 10/20/40/60 seconds, subject to collection cadence. Each Battery
request has a fresh bounded response buffer; shutdown disconnects retained clients.
Discovery reuses existing configuration and known Battery labels, tests sequential
and concurrency-2 retained-client reads, and automatically saves tested concurrency.
