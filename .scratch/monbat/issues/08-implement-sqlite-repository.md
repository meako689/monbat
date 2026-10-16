# 08 Implement: SQLite Telemetry Repository (`src/monbat/db.py`)

Type: task
Status: ready-for-agent
Blocked by: 07

## Goal

Implement `src/monbat/db.py` — the persistent telemetry store used by the
Poller to record every battery reading and by the Dashboard API to serve
latest values and history.

All design decisions are resolved in
[issue 04](04-sqlite-telemetry-storage-schema.md).

---

## Scope

### Files to create / modify

| Path | Action |
|---|---|
| `src/monbat/db.py` | **Create** — full repository implementation |
| `tests/test_db.py` | **Create** — unit tests (in-memory SQLite, no disk I/O) |

### Out of scope

- Poller, FastAPI app, Dashboard (ticket 09).
- No migration tooling — single `CREATE TABLE IF NOT EXISTS` is sufficient.

---

## Implementation

### `src/monbat/db.py`

Module layout (top-to-bottom):

```
db.py
├── _CREATE_TABLE_SQL   # module-level constant
├── _CREATE_INDEX_SQL   # module-level constant
├── TelemetryRepository
│   ├── __init__(self, db_path: str) -> None
│   ├── init_db(self) -> None              # CREATE TABLE + INDEX; safe to call repeatedly
│   ├── save_telemetry(battery_id, telemetry) -> None   # async via asyncio.to_thread
│   ├── get_latest_telemetry(battery_id) -> BatteryTelemetry | None   # async
│   └── get_history(battery_id, since_timestamp) -> list[BatteryTelemetry]  # async
```

#### Design constraints (from spec §4.3 + issue 04)

- **`sqlite3` stdlib only** — no SQLAlchemy, no third-party ORM.
- **WAL mode PRAGMAs** applied once in `init_db()`:
  ```sql
  PRAGMA journal_mode = WAL;
  PRAGMA synchronous = NORMAL;
  PRAGMA busy_timeout = 5000;
  ```
- **`cell_voltages_json`** stored as `json.dumps(list(telemetry.cell_voltages_v))`
  and round-tripped back via `json.loads()` → `tuple[float, ...]`.
- **`asyncio.to_thread`** wraps every `sqlite3` call so the event loop stays
  unblocked; each async method opens and closes its own `sqlite3.connect()`.
- **`soc_percent`** is not stored directly — it is re-derived on read from
  `remaining_ah / capacity_ah` (matches `parse_bms_payload` logic).
  **Alternative**: store it directly to avoid recalculation. Pick the simpler
  path and document the choice in code.
- Guard clause: `get_latest_telemetry` returns `None` when no rows exist.
- All dataclass fields map 1:1 to columns; `timestamp` is a `REAL`.

#### Table schema (from spec)

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

### `tests/test_db.py`

Use `":memory:"` as `db_path` so no files are created on disk.

- `test_init_db_idempotent` — call `init_db()` twice; no error.
- `test_save_and_get_latest` — save one reading, assert `get_latest_telemetry`
  returns it with all fields intact.
- `test_get_latest_returns_none_when_empty` — assert `None` on empty DB.
- `test_get_latest_returns_newest` — save two readings with different timestamps;
  assert latest is returned.
- `test_get_history_filters_by_time` — save three readings at t=100, t=200, t=300;
  assert `get_history(since=150)` returns exactly the t=200 and t=300 rows.
- `test_get_history_empty` — assert empty list when no rows match.
- `test_cell_voltages_round_trip` — save a telemetry with 8 cell voltages; assert
  `cell_voltages_v` round-trips back as a tuple of 8 floats with correct values.

---

## Acceptance criteria

1. `uv run pytest tests/test_db.py -v` passes fully offline (no Bluetooth, no
   disk files).
2. `TelemetryRepository` uses `asyncio.to_thread` for all SQLite calls.
3. `cell_voltages_v` round-trips correctly through JSON serialization.
4. Strict typing, `frozen=True` / `slots=True` where dataclasses are used,
   no `Any`, shallow control flow.

## Comments

## Answer
