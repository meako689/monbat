# 07 Implement: Bleak BMS Driver (`src/monbat/bms.py`)

Type: task
Status: resolved
Blocked by: 02, 06

## Goal

Graduate the validated prototype (`prototype_bms_driver.py`) into the production
`src/monbat/bms.py` module used by the Poller, and add a test suite covering
both offline payload parsing and a live-hardware integration smoke-test driven
from `config.toml`.

---

## Scope

### Files to create / modify

| Path | Action |
|---|---|
| `src/monbat/bms.py` | **Create** — production BMS driver |
| `tests/test_bms.py` | **Create** — unit + integration tests |
| `.scratch/monbat/issues/07-implement-bms-driver.md` | This ticket |

### Out of scope

- Poller task, DB, Dashboard (separate tasks).
- No changes to `prototype_bms_driver.py` (preserved as-is).

---

## Implementation

### `src/monbat/bms.py`

- Module-level constants: `SERVICE_UUID`, `TX_NOTIFY_UUID`, `RX_WRITE_UUID`,
  `REQUEST_PAYLOAD`, `MIN_PAYLOAD_LEN`.
- `BatteryTelemetry` — `@dataclass(frozen=True, slots=True)`.
- `parse_bms_payload(data: bytes, timestamp: float | None = None) -> BatteryTelemetry`
  — pure function, no I/O, fully unit-testable offline.
- `poll_battery(address: str, timeout_sec: float = 10.0) -> BatteryTelemetry`
  — async, single connect-notify-write-await-disconnect cycle via BleakClient.
  Raises `ConnectionError` on failed connect; `TimeoutError` on no response.
- No `build_synthetic_payload` in production module (lives in tests only).

### `tests/test_bms.py`

- `test_parse_round_trip` — builds a synthetic 66-byte payload, asserts every
  field round-trips correctly (offline).
- `test_parse_too_short` — asserts `ValueError` on short buffer.
- `test_parse_discharge_negative_current` — verifies signed current and negative power.
- `test_parse_soc_zero_capacity` — verifies SOC is 0.0 when capacity == 0.
- `test_live_bat1` / `test_live_bat2` — `pytest.mark.integration`, reads Bleak device addresses
  from `config.toml` via `tomllib`, calls `asyncio.run(poll_battery(...))`.
  Skipped with `pytest.skip` if Bluetooth is unavailable.

---

## Acceptance criteria

1. `uv run pytest tests/test_bms.py -k "not integration"` passes offline.
2. `parse_bms_payload` is a pure function with no bleak import at module level.
3. All code uses `frozen=True, slots=True` dataclasses, specific types, no `Any`,
   shallow control flow.
4. `bms.py` exports only the public API; no prototype simulation helpers.

## Comments

## Answer

Implemented in:
- `src/monbat/bms.py` — production BMS driver: `BatteryTelemetry` dataclass,
  `parse_bms_payload()` pure parser, `poll_battery()` async BleakClient single-poll.
  No simulation helpers; `bleak` imported only inside `poll_battery()`.
- `tests/test_bms.py` — 9 offline unit tests + 2 live integration tests
  parametrised from `config.toml` device addresses. Mark `integration` registered in
  `pyproject.toml`.

Live results from real hardware (16-10-2026):
- **C01163** (`C8:47:80:78:33:FB`): 26.264 V | −2.247 A | 38.1 % SOC | 8S cells
  (3.282–3.284 V) | T_cell=25°C T_bms=24°C
- **B00734** (`C8:47:80:3F:91:B1`): 26.256 V | 0.0 A | 40.1 % SOC | 8S cells
  (3.280–3.283 V) | T_cell=24°C T_bms=24°C

All 11 tests passed (`uv run pytest tests/test_bms.py -v --tb=short -s`).
Note: batteries are 8S packs (~26 V nominal), not 4S.
