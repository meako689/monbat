# 04 SQLite telemetry storage schema and connection management

Type: grilling
Status: resolved
Blocked by: 

## Question

What exact SQLite table schema (columns for timestamp, battery ID, pack voltage, current, watts, remaining Ah, capacity Ah, SOC %, cell temperatures, BMS temperature, cell voltages), indexing strategy, and connection concurrency configuration (WAL mode, busy timeout) best satisfy fast time-series writes and concurrent dashboard reads?

## Answer

1. **Concurrency & PRAGMAs**:
   - `PRAGMA journal_mode = WAL;` (enables non-blocking concurrent reads while background poller writes).
   - `PRAGMA synchronous = NORMAL;` (durable, high write performance).
   - `PRAGMA busy_timeout = 5000;` (prevents lock exceptions during transient write contention).

2. **Table Schema (`telemetry`)**:
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
   ```

3. **Indexing Strategy**:
   - Composite index for both latest-record lookups and time-series range queries:
     ```sql
     CREATE INDEX IF NOT EXISTS idx_telemetry_battery_time 
     ON telemetry (battery_id, timestamp DESC);
     ```

4. **Encapsulation via `TelemetryRepository`**:
   - Encapsulated in a focused repository class (`TelemetryRepository` in `src/monbat/db.py`) using Python standard library `sqlite3`.
   - Methods:
     - `init_db() -> None`
     - `save_telemetry(battery_id: str, telemetry: BatteryTelemetry) -> None`
     - `get_latest_telemetry(battery_id: str) -> BatteryTelemetry | None`
     - `get_history(battery_id: str, since_timestamp: float) -> list[BatteryTelemetry]`
   - Async execution via `asyncio.to_thread` to keep the FastAPI event loop unblocked.

5. **Retention Policy**:
   - Raw time-series records retained by default without automated purging or downsampling in Iteration 1 (~500 KB/day for 2 batteries polled every 30s). Purging and compaction deferred to future maintenance.
