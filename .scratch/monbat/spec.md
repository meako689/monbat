# monbat Technical Architecture & Implementation Specification

## 1. Executive Summary & Purpose

`monbat` is a lightweight, local battery monitoring service designed to run on a Linux Mint laptop to monitor a home offgrid power bank composed of two (2) Bluetooth-enabled Redodo LiFePO4 batteries.

The system connects over Bluetooth Low Energy (BLE), queries real-time battery management system (BMS) telemetry every 30 seconds (configurable), stores time-series readings in a local SQLite database in Write-Ahead Logging (WAL) mode, and serves an offgrid-ready, zero-dependency web dashboard via FastAPI.

---

## 2. Platform & Toolchain Standards

* **Operating System**: Linux Mint 21.3+ (Ubuntu 22.04 LTS / glibc 2.35, BlueZ 5.64).
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
* **Telemetry**: Immutable point-in-time snapshot of battery metrics (pack voltage, net current, power, SOC %, remaining/total Ah, temperatures, cell voltages).
* **Poller**: Async background task querying each Battery sequentially every 30 seconds.
* **Discovery Script**: Interactive one-off CLI (`monbat discover`) to scan, select, and assign friendly aliases.
* **Dashboard**: Web UI served by FastAPI displaying real-time metrics and historical graphs.

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
  sqlite_path = "monbat.db"

  [server]
  host = "0.0.0.0"
  port = 8000

  [[batteries]]
  id = "bat-1"
  name = "Battery 1 (Upper)"
  mac_address = "AA:BB:CC:11:22:33"

  [[batteries]]
  id = "bat-2"
  name = "Battery 2 (Lower)"
  mac_address = "AA:BB:CC:44:55:66"
  ```
* **Parsing & Writing**:
  * Read via Python standard library `tomllib`.
  * Written via a lightweight internal serializer without external YAML/TOML writer dependencies.
  * Prompts for user confirmation before overwriting an existing `config.toml`.

---

### 4.2 BLE BMS Protocol & Driver (`src/monbat/bms.py`)

* **GATT Protocol**:
  * Service UUID: `0000ffe0-0000-1000-8000-00805f9b34fb` (or short `"ffe0"`)
  * TX Characteristic (Notify): `0000ffe1-0000-1000-8000-00805f9b34fb` (or short `"ffe1"`)
  * RX Characteristic (Write without response): `0000ffe2-0000-1000-8000-00805f9b34fb` (or short `"ffe2"`)
  * Request packet: `bytes([0x00, 0x00, 0x04, 0x01, 0x13, 0x55, 0xAA, 0x17])` (8 bytes)

* **Polling Lifecycle**:
  1. Sequential poll-and-disconnect: Connects to Battery 1, registers notifications on `TX`, writes 8-byte request to `RX`, awaits 66-byte payload, unregisters notifications, and disconnects. Repeats for Battery 2.
  2. Protects against Linux BlueZ adapter lockups and multi-connection limits.
  3. Chunk buffer: Gathers notification chunks into a `bytearray` to guard against BLE MTU fragmentation.

* **Payload Layout (Little-Endian `<`)**:
  * Byte 12 (`<I`): Pack voltage (mV / 1000.0)
  * Bytes 16..47 (`<16H`): Up to 16 individual cell voltages (mV / 1000.0; non-zero entries kept)
  * Byte 48 (`<i`): Net current (mA / 1000.0; positive = charge, negative = discharge)
  * Byte 52 (`<h`): Cell temperature (°C)
  * Byte 54 (`<h`): BMS internal temperature (°C)
  * Byte 62 (`<H`): Remaining capacity (centi-Ah / 100.0)
  * Byte 64 (`<H`): Total capacity (centi-Ah / 100.0)

* **Telemetry Dataclass**:
  ```python
  @dataclass(frozen=True, slots=True)
  class BatteryTelemetry:
      timestamp: float
      voltage_v: float
      current_a: float
      power_w: float
      soc_percent: float
      remaining_ah: float
      capacity_ah: float
      cell_temp_c: int
      bms_temp_c: int
      cell_voltages_v: tuple[float, ...]
  ```

---

### 4.3 SQLite Telemetry Storage (`src/monbat/db.py`)

* **Database Mode**: Local SQLite database at `monbat.db` (configurable).
* **PRAGMAs**:
  ```sql
  PRAGMA journal_mode = WAL;
  PRAGMA synchronous = NORMAL;
  PRAGMA busy_timeout = 5000;
  ```
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
      cell_voltages_json TEXT NOT NULL
  );

  CREATE INDEX IF NOT EXISTS idx_telemetry_battery_time 
  ON telemetry (battery_id, timestamp DESC);
  ```
* **Repository Interface (`TelemetryRepository`)**:
  * `save_telemetry(battery_id: str, telemetry: BatteryTelemetry) -> None`
  * `get_latest_telemetry(battery_id: str) -> BatteryTelemetry | None`
  * `get_history(battery_id: str, since_timestamp: float) -> list[BatteryTelemetry]`
  * Async execution: queries run inside `asyncio.to_thread` to maintain unblocked event loop concurrency.

---

### 4.4 Web Service & Dashboard (`src/monbat/app.py`)

* **Framework**: FastAPI with lifespan background Poller task.
* **Lifespan Pattern**:
  ```python
  @asynccontextmanager
  async def lifespan(app: FastAPI):
      repo = TelemetryRepository(config.sqlite_path)
      repo.init_db()
      poller_task = asyncio.create_task(run_poller_task(config, repo))
      yield
      poller_task.cancel()
      try:
          await poller_task
      except asyncio.CancelledError:
          pass
  ```
* **HTTP Endpoints**:
  * `GET /`: Renders self-contained dark-mode dashboard HTML.
  * `GET /api/latest`: Returns JSON dictionary of latest snapshots for all batteries.
  * `GET /api/history?hours=24`: Returns time-series readings for charting.
* **Offgrid-Ready UI Architecture**:
  * **100% Offline**: Zero external CDNs, zero web fonts, zero third-party script tags.
  * **Pure CSS Grid Theme**: Responsive multi-card layout with state-of-charge bars, color-coded charge/discharge metrics, cell voltage chips, and delta imbalance indicators.
  * **Vanilla JavaScript Refresh**: `setInterval(updateDashboard, 10000)` polling `/api/latest` via native `fetch()`.

---

## 5. Phased Roadmap

1. **Iteration 1 (Core Deliverable)**:
   * Discovery CLI tool (`monbat discover`) saving `config.toml`.
   * Bleak BMS driver with little-endian parsing.
   * SQLite repository with WAL mode.
   * Single-process FastAPI app with background Poller and real-time offline Dashboard.
2. **Iteration 2 (Visual Charting)**:
   * Historical charge/discharge graphs (client-side SVG / uPlot / Chart.js embedded locally) utilizing the `/api/history` endpoint.
3. **Iteration 3 (Bank Aggregation & Alerts)**:
   * Combined battery bank power, aggregate SOC, and net current calculations.
   * System health alerts (low cell voltage, high temperature cutoffs).
   * Systemd user service packaging (`monbat.service`).
