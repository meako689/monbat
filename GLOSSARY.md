# monbat

Local off-grid battery monitoring service for Redodo LiFePO4 batteries over Bluetooth Low Energy (BLE). Linux Mint is the primary deployment target, and macOS is also supported through Bleak.

## Language

**Battery**:
A physical off-grid LiFePO4 battery pack equipped with an internal Bluetooth-enabled Battery Management System (BMS).
_Avoid_: Device, unit, accumulator

**BMS (Battery Management System)**:
The internal protection and telemetry module inside each Battery, accessible via BLE GATT service `0xFFE0`.
_Avoid_: Controller, firmware, hardware

**Telemetry**:
A single point-in-time snapshot from a Battery, including measurements, effective
SOC and its source, BMS state, protection flags, SOH, and cycle count.
_Avoid_: Metrics, stats, data point, sample

**Poller**:
The single coroutine that connects to each Battery sequentially to request and
persist Telemetry. It follows a configured background delay and can wake early
for eligible Dashboard refresh requests.
_Avoid_: Collector, scraper, monitor worker

**Battery Bank**:
All configured Batteries connected in parallel at the same nominal voltage.
Its summary shows capacity-weighted SOC and signed net power when every Battery
has fresh Telemetry.

**Freshness**:
The configured maximum Telemetry age for online status and available Battery
Bank totals, independent of polling intervals.

**Discovery Script**:
A standalone interactive CLI utility used once to scan for BLE batteries, assign human-readable aliases, and generate configuration.
_Avoid_: Setup wizard, pairing agent, scanner

**Dashboard**:
The minimalist web interface served by FastAPI displaying current Battery
status. Historical charge/discharge graphs are planned for Iteration 2.
_Avoid_: Frontend, web portal, control panel
