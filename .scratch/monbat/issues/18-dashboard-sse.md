# Implement SSE for Dashboard updates

Type: task
Status: resolved
Triage: ready-for-agent

## Scope

Push persisted Telemetry changes to the Dashboard through a server-sent event stream. Resolve initial snapshot, refresh scheduling, freshness transitions, and reconnect behavior before implementation.

## Acceptance criteria

New persisted readings appear without waiting for the current 30-second timer. Preserve freshness and Battery Bank behavior, support reconnect and multiple tabs, and verify with API and browser tests.

## Comments

- 2026-10-17: Requested by the user. Design decisions pending grilling; scope is provisional.

## Decisions from grilling

- Implement server-sent events using the browser's native EventSource and existing vanilla JavaScript rendering. No frontend framework is required.
- Server scheduling replaces Dashboard-triggered BLE refresh requests. Collection continues without connected browsers.
- Send an initial stored snapshot and publish updates after successful persistence.
- Update freshness and Battery Bank availability when readings expire even if no new Telemetry arrives.
- Support automatic reconnect and multiple tabs without creating additional BLE workers.
- SSE is delivery only; the 10-second collection cadence and concurrency belong to ticket 16.

- 2026-10-17: User answered grilling rounds 1 and 2. Final shared-understanding confirmation pending.

## Browser-aware scheduling decisions

- First SSE subscriber triggers an immediate collection and enables the active interval (default 10 seconds). Hidden tabs count; multiple tabs share one schedule.
- Last subscriber disconnect starts a 30-second grace period; then return to the configured background interval (default 600 seconds).
- Concurrent open connections and simultaneous status requests are separate capabilities. The read-concurrency setting must not prevent retaining both clients. Final naming/confirmation pending.

## Hardware validation — 2026-10-17

On the current macOS host, shared 10-second discovery found both configured Batteries. Both BLE connections and notification subscriptions remained open for one sequential round and three concurrent rounds spaced 10 seconds apart. All eight status responses passed parser frame/checksum validation. Setup took 0.889 and 0.801 seconds; sequential requests took 0.249 and 0.234 seconds; concurrent rounds took 0.277, 0.326, and 0.284 seconds. Both clients disconnected cleanly. This short smoke test establishes dual-connection operation here, not Linux compatibility or long-run reliability. Script: `/private/tmp/monbat_ble_check.py`.

## Approved final scope

User approved implementation of all tasks. Active SSE subscribers enable 10-second scheduled collection; no subscribers uses the existing configured background interval (new discovery default 600 seconds). Grace period is 30 seconds. Persistent connections default enabled during active collection and close afterward. Concurrency limits requests, not open clients; default 1. Discovery automatically saves hardware-tested concurrency.

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
