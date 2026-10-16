# 08 Implement: SQLite Telemetry Repository (`src/monbat/db.py`)

Type: task
Status: resolved
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
| `tests/test_db.py` | **Create** — unit tests using a temporary SQLite file per test |

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
│   ├── async def init_db(self) -> None
│   ├── async def save_telemetry(self, battery_id, telemetry) -> None
│   ├── async def get_latest_telemetry(self, battery_id) -> BatteryTelemetry | None
│   └── async def get_history(self, battery_id, since_timestamp) -> list[BatteryTelemetry]
```

#### Design constraints (from spec §4.3 + issue 04)

- **`sqlite3` stdlib only** — no SQLAlchemy, no third-party ORM.
- **Connection lifecycle**: Each public method delegates its complete
  synchronous `sqlite3` operation to `asyncio.to_thread`. The worker opens and
  closes its own connection.
- **PRAGMAs**: Set `journal_mode = WAL` once in `init_db()`. Set
  `synchronous = NORMAL` and `busy_timeout = 5000` on every connection.
- **`cell_voltages_json`** stored as `json.dumps(list(telemetry.cell_voltages_v))`
  and round-tripped back via `json.loads()` → `tuple[float, ...]`.
- **`asyncio.to_thread`** wraps every SQLite operation, including database
  initialization, so the event loop stays unblocked.
- **`soc_percent`** is stored exactly as provided by `BatteryTelemetry`.
  Do not recalculate, normalize, clamp, or otherwise transform it on save or
  read.
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

Use pytest's `tmp_path` fixture and a temporary database file per test. This
exercises the same separate-connection behavior as production and leaves no
database files in the repository.

Use regular pytest test functions and `asyncio.run()` to call the async
repository methods; no async pytest plugin is needed.

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

1. `uv run pytest tests/test_db.py -v` passes fully offline using only temporary
   database files under pytest's `tmp_path`.
2. All public `TelemetryRepository` methods, including `init_db()`, run their
   SQLite work through `asyncio.to_thread`.
3. `cell_voltages_v` round-trips correctly through JSON serialization.
4. Strict typing, `frozen=True` / `slots=True` where dataclasses are used,
   no `Any`, shallow control flow.

## Comments

- 2026-10-16: Agreed to use temporary file databases for tests, set WAL during
  initialization and connection-specific PRAGMAs on every connection, and make
  all repository methods async wrappers around `asyncio.to_thread`. Persist
  `soc_percent` as provided without repository-side transformation.

## Answer

Implemented in:
- `src/monbat/db.py` — async repository methods delegate each complete SQLite
  operation to `asyncio.to_thread`; each worker opens and closes its connection.
- `tests/test_db.py` — temporary-file tests for schema setup, WAL, CRUD,
  timestamp filtering, SOC preservation, and cell-voltage JSON round trips.

Connection settings match the agreed plan: initialization enables WAL;
`synchronous=NORMAL` and `busy_timeout=5000` are set on each connection. SOC is
persisted as provided by `BatteryTelemetry`.

Verification: `uv run pytest tests/test_db.py -v` — 9 passed.
