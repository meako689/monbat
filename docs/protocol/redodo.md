# Redodo BMS protocol

The driver uses the read-only `0x13` status request over GATT service `FFE0`,
notifications `FFE1`, and writes `FFE2`. It connects to Batteries sequentially,
collects a complete response, and disconnects.

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
are separate from BMS-reported protection state. No separate balancing-state
field is established.

## Reference and validation

The implementation follows [mkeguy106/bmsmon's current decoder and captured
response tests](https://github.com/mkeguy106/bmsmon/tree/4534382d00702e14199e2a2aaab50180cf0878ac/android/app/src),
pinned to commit `4534382d00702e14199e2a2aaab50180cf0878ac`.
Use the current Android decoder rather than its legacy CLI.

The captured fixture is from a 12 V/4S Battery; the parser also supports
24 V/8S measurements. Synthetic protection fixtures verify decoding, not
physical protection behavior. The user validated ticket 13 on 2026-10-17.

Field offsets and masks are in [spec section 4.2](../../.scratch/monbat/spec.md#42-ble-bms-protocol--driver-srcmonbatbmspy).
