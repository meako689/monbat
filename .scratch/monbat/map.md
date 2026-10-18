## Destination

Technical architecture and implementation specification for `monbat`: an offgrid battery monitoring service primarily for Linux Mint, also supporting macOS, tracking 2 Redodo LiFePO4 batteries over BLE via FastAPI and SQLite, with an interactive discovery script, a live dashboard, and historical graphing planned for Iteration 2.

## Notes

- **Domain**: Battery monitoring for offgrid LiFePO4 Redodo batteries. Always use canonical vocabulary defined in [GLOSSARY.md](../../GLOSSARY.md).
- **Reference Protocol**: LiTime/Redodo BLE GATT protocol (service `0xFFE0`, TX notify `0xFFE1`, RX write `0xFFE2`, request payload `0x000004011355AA17`).
- **Platform**: Linux Mint deployment target and macOS support, each with a compatible Bluetooth Low Energy adapter and required OS permissions.
- **Coding Standards**: YAGNI, minimal abstractions, modern Python typing, specific types, shallow control flow with guard clauses and early returns.
- **Skills to Consult**: `grilling`, `domain-modeling`, `prototype`, `research`.

## Decisions so far

- **[20 Local comprehensive protocol specification](issues/20-local-protocol-spec.md)**:
  Resolved: [wire spec](../../docs/protocol/redodo-wire-spec.md) and
  [source comparison](../../docs/research/redodo-protocol-sources.md) cover
  five pinned implementations, framing, fields, commands, captures, conflicts,
  and unknowns. Capture length/checksum and local links verified. Disabled
  matches bmsmon; calledit describes charge disabled on studied LiTime Batteries.

- **[01 Python and uv environment](issues/01-python-315-and-uv-environment.md)**: Project requires Python 3.15 and uses `uv`; `uv sync` created the macOS ARM environment. Linux remains the primary deployment, with macOS support through Bleak and opaque platform-specific device addresses.
- **[02 Redodo BMS BLE protocol and bleak driver design](issues/02-ble-protocol-and-bms-driver.md)**: Validated little-endian 66-byte packet parsing (`<I`, `<16H`, `<i`, `<h`, `<h`, `<H`, `<H`) and BleakClient single-poll connect-notify-write-disconnect cycle via executable prototype.
- **[03 Interactive BLE discovery CLI and TOML configuration schema](issues/03-discovery-cli-and-config-schema.md)**: Specified `monbat discover` CLI scan and alias flow, zero-dependency TOML serialization, and `config.toml` structure.
- **[04 SQLite telemetry storage schema and connection management](issues/04-sqlite-telemetry-storage-schema.md)**: Established WAL mode, telemetry table schema with JSON cell voltages, `(battery_id, timestamp DESC)` indexing, and an async `TelemetryRepository` interface over stdlib `sqlite3`.
- **[05 FastAPI dashboard endpoints and minimalist UI architecture](issues/05-dashboard-and-fastapi-service.md)**: Validated FastAPI lifespan poller lifecycle, responsive dark-mode dashboard cards, offline vanilla JS auto-refresh, config-enriched latest views with age-based offline status, and a chronological plain-list history API.
- **[06 Implement discovery script](issues/06-implement-discovery-script.md)**: Implementation plan for `monbat discover` — files, module layout, async flow, TOML serializer, CLI wiring, and acceptance criteria.
- **[07 Implement Bleak BMS driver](issues/07-implement-bms-driver.md)**: Production `src/monbat/bms.py` — `BatteryTelemetry`, `parse_bms_payload()`, `poll_battery()`. Validated on live 8S Redodo packs (~26 V). 11/11 tests pass (9 offline + 2 live integration parametrised from `config.toml`).
- **[08 Implement SQLite telemetry repository](issues/08-implement-sqlite-repository.md)**: `src/monbat/db.py` — async `TelemetryRepository` with WAL mode, `asyncio.to_thread` operations, direct SOC persistence, and temporary-file unit tests. `Status: resolved`; 9 tests pass.
- **[09 Implement FastAPI app, Poller & Dashboard](issues/09-implement-fastapi-app-and-poller.md)**: Implemented `src/monbat/app.py` with FastAPI lifespan Poller, config-enriched `/api/latest`, chronological plain-list `/api/history`, and the self-contained Dashboard; wired `serve`, updated dependencies/lockfile and README. `Status: resolved`; `uv run pytest tests/test_app.py -v` passed (17 tests). Ticket 10 is now unblocked.

## Approved tasks — 2026-10-17

The user confirmed this scope after grilling. The [spec](spec.md) includes
the approved behavior; implementation is still pending.

- **[11 Dashboard-triggered refresh and freshness](issues/11-dashboard-triggered-refresh-and-freshness.md)**:
  One sequential Poller, async page requests every 30 seconds, no duplicate
  queued passes, configured background timing retained, and independent
  `freshness_seconds` (default 60) for all scenarios. Resolved: refresh endpoint,
  event-driven Poller, Dashboard cadence, config and discovery implemented;
  77 offline tests pass.
- **[13 Complete protocol and health Telemetry](issues/13-complete-bms-protocol-and-health-telemetry.md)**:
  Apply the pinned public decoder's frame handling and field widths; include
  protections, BMS state, SOC, SOH, and cycle count through storage/API/UI.
  Reported SOC wins; capacity-derived SOC is a fallback. Fresh schema with no
  historical migration. Resolved: driver, fresh schema, API, Dashboard, and
  prototype updated; 65 offline tests pass. Live hardware remains unverified.
- **[12 Parallel Battery Bank summary](issues/12-parallel-battery-bank-summary.md)**:
  Capacity-weighted effective SOC and one signed net watts value. Hide totals
  when any Battery has missing/stale readings or invalid capacity. Resolved:
  summary API and Dashboard section implemented; 84 offline tests pass.

- **[14 Poller state ownership](issues/14-poller-state-ownership.md)**:
  Resolved: `poller.py` owns admission and private scheduling state; `app.py`
  retains configuration and task lifecycle. Behavior unchanged; 85 offline
  tests pass, including concurrent requests and background delay restart.

- **[15 Prototype retirement and unused code](issues/15-retire-prototypes-and-unused-code.md)**:
  Resolved: removed superseded Dashboard/BMS prototypes, an unused import,
  and an unused constant (525 source lines). Historical links preserved;
  remaining entry points and callers checked; 85 offline tests pass.

- **[10 Dashboard rendering and update locality](issues/10-safe-dashboard-config-rendering.md)**:
  Resolved: one safely escaped Battery header and one update flow; 11
  real-browser regression cases. All 96 offline tests pass.

## Not yet specified

- **Iteration 2 historical graphing UI**: Aggregation and downsampling queries over recorded SQLite telemetry, and visual charting presentation (lightweight client-side Chart.js/uPlot vs server-rendered SVG).
- **Additional Battery Bank metrics**: Net current, combined capacity display,
  and time-to-empty/time-to-full estimates. Parallel SOC and net watts are
  specified in ticket 12.
- **Alerts & health thresholds**: Rules and notification hooks for low SOC, cell voltage delta/imbalance, high/low temperature cutoffs, or consecutive BLE read timeouts.
- **Service daemonization**: Linux systemd user service unit configuration for headless background execution on Linux Mint laptop boot.

## Out of scope

- Cloud synchronization, remote MQTT brokers, or Home Assistant integration (ruled out: strictly local personal service).
- Inverter or Solar Charge Controller (MPPT) communication (ruled out: strictly Redodo battery BMS).
- BMS parameter writing, cell balancing overrides, or firmware modifications (ruled out: strictly read-only telemetry monitoring).
- Earlier ticket 13 omitted balancing. The later external-source protocol
  request supersedes that exclusion for preserving and qualifying the
  externally documented status regions; controls remain out of scope.

## Protocol reimplementation

Start with the [implementation handoff](../../docs/protocol/implementation-handoff.md).
It contains the final contracts, current-code touchpoints, and validation plan.

The [wire spec](../../docs/protocol/redodo-wire-spec.md) derives authority from
pinned external documentation and reference implementations. Monbat's current
code and earlier completed tasks do not define protocol facts.

| Ticket | Work | Readiness | Dependencies |
|---|---|---|---|
| [21](issues/21-preserve-complete-status-regions.md) | Decode balancing, temperatures, full problem region, original cell slots | ready-for-agent | None |
| [22](issues/22-round-trip-protocol-evidence.md) | Useful fields and complete-response BLOBs in a fresh database | ready-for-agent | 21 |
| [23](issues/23-display-protocol-fields-without-overclaiming.md) | Qualified balancing/temperature details, unknown failure data, slot numbering | ready-for-agent | 22 |
| [24](issues/24-phase-3-charge-discharge-controls.md) | Phase3 charge/discharge control investigation | needs-triage | Future phase |
| [25](issues/25-resolve-external-protocol-disagreements.md) | Resolve disputed physical meanings with external evidence | needs-info | Does not block21–23 |

Grilling confirmed by the user on 2026-10-17. Tickets21–23 are open and
implementation has not started. The user subsequently revised the storage
choice: preserve complete validated BLE responses as SQLite BLOBs alongside
useful typed fields, with history hex retrieval. Start fresh without deleting
or migrating old databases. Keep
read-only status polling and current ATT mode unchanged. B1 governs the
Redodo baseline; other sources fill gaps and identify unresolved disagreements.

## Phase 3 roadmap

Investigate charge/discharge switches in [ticket24](issues/24-phase-3-charge-discharge-controls.md).
Establish verified commands, readback behavior, and per-action confirmation
before implementation. Shutdown, configuration writes, and firmware changes
remain outside the initial scope. Current roadmap approval does not authorize
sending controls to Batteries.


## Update speed tasks — 2026-10-17

Requested scope; design decisions pending grilling.

- **[Poll two Batteries concurrently](issues/16-concurrent-battery-polling.md)**: Open; provisional scope and validation recorded in the ticket.
- **[Keep BLE connections open](issues/17-persistent-ble-connections.md)**: Open; provisional scope and validation recorded in the ticket.
- **[Implement SSE for Dashboard updates](issues/18-dashboard-sse.md)**: Open; provisional scope and validation recorded in the ticket.

Grilling decisions: 10-second scheduled collection independent of tabs; configurable concurrency default 1; optional connection reuse default disabled; reconnect backoff 10/20/40/60 seconds; SSE replaces browser refresh requests. User answered both rounds; final shared-understanding confirmation pending.

Updated browser-aware design: active SSE subscribers enable 10-second collection; no subscribers uses long background polling (default 600 seconds), after a 30-second grace period. Persistent connections default enabled during active collection and close afterward. Current macOS dual-connection smoke test passed: sequential reads and three concurrent rounds, eight valid responses total. Read concurrency and retained connection count must be separate.

Tickets [16](issues/16-concurrent-battery-polling.md),
[17](issues/17-persistent-ble-connections.md),
[18](issues/18-dashboard-sse.md), and
[19](issues/19-discovery-hardware-validation.md) resolved: browser-aware polling,
retained clients, SSE, and rediscovery reuse/automatic hardware validation.
88 offline tests pass. Implemented live probe: sequential average 0.482s,
concurrent average 0.282s across three rounds each on current macOS hardware.
Existing configuration retained; rediscovery will save tested concurrency 2 here.

## Connection recovery — 2026-10-18

- **[26 Reconnect Batteries using cached BLE devices](issues/26-reconnect-with-cached-ble-devices.md)**:
  Open, ready-for-agent. Keep discovered BLEDevice objects in memory and try
  them for active and background connections. Grilling confirmed: read healthy
  connected Batteries first, defer rediscovery until the next retry, retain
  cache entries after scan misses, and require bounded cleanup before
  replacement. Preserve backoff; database failures do not trigger rediscovery.
  Require offline coverage and a normal hardware reconnect check, with bounded
  shutdown cleanup. Physical BMS lockup recovery is unconfirmed. Shared
  understanding approved by the user; implementation is deferred.
