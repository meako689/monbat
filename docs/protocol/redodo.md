# Redodo BMS protocol

For framing, the full status layout, commands, captures, and conflicting
reference interpretations, read the [local wire-protocol specification](redodo-wire-spec.md).
This page describes the current Monbat implementation.

The wire spec derives authority from pinned external sources. Current Monbat
behavior is descriptive here and does not override that contract. Planned
conformance work is in [tickets 21–25](../../.scratch/monbat/map.md#protocol-reimplementation).

The driver uses the read-only `0x13` status request over GATT service `FFE0`,
notifications `FFE1`, and writes `FFE2`. It uses shared discovery and configurable request concurrency. During active
Dashboard collection it can retain connections and notification subscriptions;
background passes disconnect after reading. Each request collects and validates
a separate complete response.

The Poller uses one shared scan per background pass and reuses its fresh
`BLEDevice` results for all eligible new connections. Background objects are
discarded after client release. Active Dashboard collection reuses healthy
connections and recent discovery candidates, including during the grace period.
It cleans up failed clients before replacement, then connects, subscribes, and
collects a fresh response. Failed active cached attempts defer shared rediscovery
until after backoff; active scan misses keep recent candidates.
On Linux a missing BlueZ Device1 object is a recoverable connection failure,
not evidence of a surviving radio link. See [BLE recovery](../operations/dashboard.md#ble-recovery)
for retry ordering and bounded cleanup/shutdown.

Frames are realigned to the status header and collected using their declared
length. Header, length, required field coverage, and checksum are validated
before Telemetry is stored. The final checksum byte is the sum of preceding
frame bytes modulo 256, verified against the referenced 105-byte capture.

## Telemetry

The driver exposes pack voltage, signed current/power, cell voltages,
remaining/full capacity, temperatures, BMS state, protection flags, SOC, SOH,
and cycle count. Pack voltage is uint16 and full capacity is uint32.

Valid reported SOC (including 0%) supplies effective SOC. Unavailable reported
SOC uses the bounded remaining/full-capacity calculation and records the
source. Unavailable SOC/SOH are retained as null in their reported fields.

Active protections cover overcharge, over-discharge, charge/discharge
overcurrent, high/low temperature, and short circuit. Unknown protection bits
and BMS states remain explicit. Reading freshness and communication failures
are separate from BMS-reported protection state. Telemetry now retains populated cells as immutable `CellReading(slot, voltage_v)`
values with original 1-based slots. The compact `cell_voltages_v` compatibility
array is derived from these readings; zero-voltage slots are omitted.

All five signed temperature slots are retained, including 0 °C. Slots 1/2
remain the named cell/BMS temperatures; additional sensor identities are unknown.
The complete u64 problem region is preserved, with existing low-word protection
labels and an explicitly unknown upper word. The u32 balancing mask is preserved;
bits 0–15 derive candidate cell slots 1–16, even without voltage readings.
Bits 16–31 remain unknown. These candidates follow L/E's reference interpretation
and do not establish physical balancing on the user's Batteries.

`raw_response` holds immutable bytes of the validated declared frame, including
unknown regions and checksum, excluding stale prefixes and trailing bytes.
The repository persists it with each successful Telemetry row. Latest/SSE omit
these bytes; history returns lowercase `raw_response_hex`. Problem flags use
16-digit lowercase hex in JSON to preserve u64 precision. Storage/API boundaries validate these fields. The Dashboard displays
named temperatures/protections and original cell slot numbers. Additional
protocol fields remain available through storage/APIs for investigation.

## Reference and validation

The implementation follows [mkeguy106/bmsmon's current decoder and captured
response tests](https://github.com/mkeguy106/bmsmon/tree/4534382d00702e14199e2a2aaab50180cf0878ac/android/app/src),
pinned to commit `4534382d00702e14199e2a2aaab50180cf0878ac`.
Use the current Android decoder rather than its legacy CLI.

The captured fixture is from a 12 V/4S Battery; the parser also supports
24 V/8S measurements. Synthetic protection fixtures verify decoding, not
physical protection behavior. The user validated ticket 13 on 2026-10-17.

Field offsets and masks are in [spec section 4.2](../../.scratch/monbat/spec.md#42-ble-bms-protocol--driver-srcmonbatbmspy).
