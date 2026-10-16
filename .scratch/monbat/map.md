## Destination

Technical architecture and implementation specification for `monbat`: an offgrid battery monitoring service for Linux Mint tracking 2 Redodo LiFePO4 batteries over BLE via FastAPI and SQLite, with an interactive discovery script, live dashboard, and planned charge/discharge graphing.

## Notes

- **Domain**: Battery monitoring for offgrid LiFePO4 Redodo batteries. Always use canonical vocabulary defined in [GLOSSARY.md](../../GLOSSARY.md).
- **Reference Protocol**: LiTime/Redodo BLE GATT protocol (service `0xFFE0`, TX notify `0xFFE1`, RX write `0xFFE2`, request payload `0x000004011355AA17`).
- **Platform**: Linux Mint laptop with Bluetooth Low Energy adapter.
- **Coding Standards**: YAGNI, minimal abstractions, modern Python typing, specific types, shallow control flow with guard clauses and early returns.
- **Skills to Consult**: `grilling`, `domain-modeling`, `prototype`, `research`.

## Decisions so far

- **[01 Python 3.13 and uv](issues/01-python-313-and-uv-environment.md)**: Adopting Python 3.15 via `uv` standalone CPython; all core dependencies (`bleak`, `fastapi`, `uvicorn`, `jinja2`) run cleanly, with Linux Mint 21.3 glibc 2.35 and BlueZ 5.64 fully compliant.
- **[02 Redodo BMS BLE protocol and bleak driver design](issues/02-ble-protocol-and-bms-driver.md)**: Validated little-endian 66-byte packet parsing (`<I`, `<16H`, `<i`, `<h`, `<h`, `<H`, `<H`) and BleakClient single-poll connect-notify-write-disconnect cycle via executable prototype.
- **[03 Interactive BLE discovery CLI and TOML configuration schema](issues/03-discovery-cli-and-config-schema.md)**: Specified `monbat discover` CLI scan and alias flow, zero-dependency TOML serialization, and `config.toml` structure.
- **[04 SQLite telemetry storage schema and connection management](issues/04-sqlite-telemetry-storage-schema.md)**: Established WAL mode, telemetry table schema with JSON cell voltages, `(battery_id, timestamp DESC)` indexing, and `TelemetryRepository` interface using stdlib `sqlite3`.
- **[05 FastAPI dashboard endpoints and minimalist UI architecture](issues/05-dashboard-and-fastapi-service.md)**: Validated FastAPI lifespan poller lifecycle, responsive dark-mode dashboard cards, and 100% offline vanilla JS auto-refresh via executable prototype.
- **[06 Implement discovery script](issues/06-implement-discovery-script.md)**: Implementation plan for `monbat discover` — files, module layout, async flow, TOML serializer, CLI wiring, and acceptance criteria.

## Not yet specified

- **Historical charge/discharge graphing UI**: Aggregation and downsampling queries over recorded SQLite telemetry, and visual charting presentation (lightweight client-side Chart.js/uPlot vs server-rendered SVG).
- **Multi-battery aggregate bank state**: Algorithms for combining metrics across both batteries (total bank power in watts, net current, aggregate SOC %, combined capacity, time-to-empty / time-to-full estimates).
- **Alerts & health thresholds**: Rules and notification hooks for low SOC, cell voltage delta/imbalance, high/low temperature cutoffs, or consecutive BLE read timeouts.
- **Service daemonization**: Systemd user service unit configuration for headless background execution on Linux Mint laptop boot.

## Out of scope

- Cloud synchronization, remote MQTT brokers, or Home Assistant integration (ruled out: strictly local personal service).
- Inverter or Solar Charge Controller (MPPT) communication (ruled out: strictly Redodo battery BMS).
- BMS parameter writing, cell balancing overrides, or firmware modifications (ruled out: strictly read-only telemetry monitoring).
