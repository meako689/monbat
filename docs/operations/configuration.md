# Configuration and database setup

`uv run monbat discover` scans for Batteries, assigns names, and writes
`config.toml` in the current directory. Review it, then start the service with
`uv run monbat serve`. `uv sync` provisions the runtime and local `.venv`.

## Poller settings

```toml
[poller]
poll_interval_seconds = 600
timeout_seconds = 10.0
freshness_seconds = 60
sqlite_path = "monbat-health.db"
```

`poll_interval_seconds` is the background delay after each sequential BLE pass.
Discovery defaults to 30 seconds; 600 seconds gives a 10-minute background
interval. Dashboard requests can wake the Poller early.

`timeout_seconds` controls the BLE connection and response timeouts.
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
