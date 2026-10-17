# 02 Redodo BMS BLE protocol and bleak driver design

Type: prototype
Status: resolved
Blocked by: 01

## Question

How should the Redodo/LiTime BLE GATT communication (service `0xFFE0`, TX notify `0xFFE1`, RX write `0xFFE2`, 8-byte request packet `0x000004011355AA17`) be implemented in Python using `bleak`, with explicit dataclasses, specific typing, and shallow control flow for reliable connect-read-disconnect polling?

## Answer

Validated through prototype [prototype_bms_driver.py](https://github.com/meako689/monbat/blob/66148347d2ecb08324bd2e2299ddcc49f6705c3b/src/monbat/prototype_bms_driver.py):

1. **Protocol & GATT UUIDs**:
   - Service: `0000ffe0-0000-1000-8000-00805f9b34fb` (or short `"ffe0"`)
   - TX (Notifications): `0000ffe1-0000-1000-8000-00805f9b34fb`
   - RX (Write without response): `0000ffe2-0000-1000-8000-00805f9b34fb`
   - Request payload: `b"\x00\x00\x04\x01\x13\x55\xAA\x17"` (8 bytes)

2. **Payload Parsing (< 66 bytes)**:
   - Packets use little-endian byte ordering (`<`).
   - Offset 12 (`<I`): Pack voltage (mV / 1000.0).
   - Offset 16..47 (`<16H`): Up to 16 individual cell voltages (mV / 1000.0). Filter zeros for actual cell count (e.g. 4S or 8S).
   - Offset 48 (`<i`): Net current (mA / 1000.0, signed: positive = charging, negative = discharging).
   - Offset 52 (`<h`): Cell temperature (°C).
   - Offset 54 (`<h`): BMS temperature (°C).
   - Offset 62 (`<H`): Remaining capacity (centi-Ah / 100.0).
   - Offset 64 (`<H`): Total capacity (centi-Ah / 100.0).

3. **Driver Control Flow**:
   - `BleakClient` manages single-poll lifecycle: connect -> `start_notify` -> `write_gatt_char(response=False)` -> await notification event -> `stop_notify` -> disconnect.
   - Buffer chunks: Accumulates notification fragments in a `bytearray` to reliably handle MTU fragmentation across BLE packets.
   - Shallow control flow: Guard clauses handle timeouts, short payloads, and zero-capacity divide-by-zero checks cleanly. Output stored in immutable `BatteryTelemetry` dataclass (`slots=True, frozen=True`).

## Comments

- 2026-10-17: Retired the redundant prototype in ticket 15. The link above
  preserves its last version. Current protocol behavior is in spec section
  4.2, `src/monbat/bms.py`, and `tests/test_bms.py`.
