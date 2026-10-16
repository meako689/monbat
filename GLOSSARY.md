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
A single point-in-time measurement snapshot from a Battery, including pack voltage, current, power in watts, state of charge (SOC), temperatures, and individual cell voltages.
_Avoid_: Metrics, stats, data point, sample

**Poller**:
The background coroutine that connects to each Battery sequentially to request
and persist Telemetry, then waits the configured delay (default 30 seconds)
before the next polling pass.
_Avoid_: Collector, scraper, monitor worker

**Discovery Script**:
A standalone interactive CLI utility used once to scan for BLE batteries, assign human-readable aliases, and generate configuration.
_Avoid_: Setup wizard, pairing agent, scanner

**Dashboard**:
The minimalist web interface served by FastAPI displaying current Battery
status. Historical charge/discharge graphs are planned for Iteration 2.
_Avoid_: Frontend, web portal, control panel
