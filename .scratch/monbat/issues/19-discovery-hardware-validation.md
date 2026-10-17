# Discovery hardware validation and configuration reuse

Type: task
Status: resolved
Triage: ready-for-agent

## Scope

Reuse existing Battery IDs/names and settings on rediscovery. Default selection to previously configured Batteries found in the scan. Test retained connections with three sequential and three concurrent request rounds, automatically saving the validated read concurrency (up to 2), or 1 on failure. Keep overwrite confirmation.

## Comments

- 2026-10-17: User approved automatic tested concurrency and existing configuration reuse.

## Answer

Implemented in `src/monbat/poller.py`, `bms.py`, `app.py`, and `discover.py`.
Server-owned browser-aware scheduling uses active SSE subscribers and a
30-second grace period; optional retained connections default enabled during
active collection. Request concurrency is independent of retained clients.
SSE sends initial snapshots and detects stored updates and freshness expiry
within one second; EventSource handles reconnection. Rediscovery preserves
existing settings and known Battery IDs/names, defaults selection to discovered
configured Batteries, and automatically writes the hardware-tested request limit.

Validation: 88 offline tests passed, 2 standalone live integration cases excluded.
The implemented discovery probe was separately run against both current macOS
Batteries without writing config: three sequential rounds averaged 0.482 seconds;
three concurrent rounds averaged 0.282 seconds, with all responses valid.
Tested concurrency was 2. Existing config.toml was not changed. Linux and extended
reliability testing remain outside this hardware validation. `git diff --check`
passed. Tests cover retained clients/read limits, browser cadence/grace/shutdown,
SSE initial snapshots/freshness, real-browser rendering and stream recovery,
configuration preservation, and BLE frame/error cleanup.
