# Configuration and database setup

`uv run monbat discover` scans for Batteries, assigns names, and writes
`config.toml` in the current directory. Review it, then start the service with
`uv run monbat serve`. `uv sync` provisions the runtime and local `.venv`.

## Poller settings

```toml
[poller]
poll_interval_seconds = 600
active_interval_seconds = 10
concurrency = 1
persistent_connections = true
timeout_seconds = 10.0
freshness_seconds = 60
sqlite_path = "monbat-health.db"
```

`poll_interval_seconds` is the background scheduled-start interval with no
Dashboard subscribers. Discovery defaults to 600 seconds; existing values are
preserved. Active subscribers use `active_interval_seconds` (default 10).
Missed scheduled slots are skipped. `concurrency` caps simultaneous status
requests, not retained connections. `persistent_connections` defaults to true
and retains clients only during active collection and its 30-second grace period.

Rediscovery reads existing configuration, offers the discovered configured
Batteries as the default selection, and reuses their IDs, names, and settings.
New Batteries prompt for names. A shared scan supplies BLEDevice objects.
Discovery holds selected connections open and tests three sequential and three
concurrent rounds (up to two simultaneous requests), then saves the tested
concurrency automatically. Failed validation saves 1 and reports the failure.
This short test does not establish long-run or cross-platform reliability.
Existing configuration still requires overwrite confirmation.

`timeout_seconds` bounds connection/notification setup, each response, and
each disconnect attempt. Poller recovery uses one timeout budget for setup
and the first response together; cleanup has a separate budget. Shared scans
collect advertisements for that duration, with an additional timeout budget
for scanner startup/shutdown. Database saves are outside the BLE timeout.
Discovered BLE devices are cached in memory until service restart; no cache
setting or stored device details are required. See [BLE recovery](dashboard.md#ble-recovery).
`freshness_seconds` sets the maximum reading age for online status and bank
totals. It defaults to 60 when omitted and is independent of polling timing.
Timing values must be finite and positive.

Server host/port and Battery IDs, names, and addresses are also stored in
`config.toml`. Addresses are opaque host-specific Bleak identifiers. Discovery
asks before overwriting an existing configuration.

## Fresh database for the health Telemetry schema

Previous Telemetry databases are not migrated. Stop the old service and set
`sqlite_path` to a new file before running this schema. Keep your existing
polling, server, and Battery settings. The service creates the new SQLite
schema in WAL mode and preserves the old file. An old schema cannot be used
with the updated service.
