# 11 Dashboard-triggered BLE refresh and configurable freshness

Type: task
Status: resolved
Triage: ready-for-agent

## Goal

Refresh Battery Telemetry while the Dashboard is open, even when background
polling is configured for 10 minutes. Serve stored readings immediately and
let the single Poller perform BLE work asynchronously.

## Scope

- `src/monbat/app.py`: Poller coordination, refresh endpoint, freshness config,
  offline status, and Dashboard timer.
- `src/monbat/discover.py`: emit the new freshness setting in generated config.
- `README.md`: document background polling, page-triggered polling, and freshness.

The behavior contract is in [spec section 4.5](../spec.md#45-dashboard-triggered-refresh-and-freshness).
Keep the configured background interval; a 600-second interval is supported.
The existing default background delay remains 30 seconds.

## Acceptance criteria

1. Page load and each 30-second Dashboard update request an asynchronous pass
   through `POST /api/refresh`, and fetch `/api/latest` without awaiting BLE.
   Saved results appear on a later Dashboard update.
2. Exactly one lifespan-owned Poller connects to Batteries sequentially.
   Background and HTTP requests cannot create overlapping BLE passes.
3. Requests received during a pass, or less than 30 seconds after the previous
   pass started, are skipped without queuing a later pass. Multiple tabs cannot
   bypass that limit. Use monotonic time for scheduling.
4. An eligible request wakes the Poller from its background wait. After the
   resulting pass finishes, the configured background delay starts again.
   Background polling continues with no open Dashboard.
5. The refresh response returns promptly with an `accepted`, `skipped`, or
   `disabled` outcome. `accepted` means scheduled, not successfully collected.
   `GET /api/latest` remains a read of stored Telemetry.
6. `[poller].freshness_seconds` is a finite positive number, defaults to 60
   when omitted, and is emitted by discovery. A reading is offline only when
   its age exceeds that setting; replace the old `2 * poll_interval_seconds`
   rule everywhere. Missing Telemetry retains `no-reading-yet`.
7. Failed polls keep the last successful reading and its original timestamp.
   API errors leave existing cards visible and indicate connection failure.
8. Shutdown cancels and awaits the Poller. With `start_poller=False`, refresh
   requests report `disabled` and perform no BLE work.

## Validation for implementation

Cover scheduling through the app boundary with a controlled clock and BLE
dependency: sleeping wake-up, concurrent requests, active-pass skips, exact
30-second eligibility, failure recovery, background operation, and shutdown.
Cover missing/invalid freshness config and the exact freshness boundary.

## Comments

- 2026-10-17: User confirmed one Poller, immediate stored responses, a 30-second
  page cadence, and one independent configurable freshness rule for all scenarios.


## Answer

Implemented a lifespan-owned Poller with shared atomic refresh admission and
an event that wakes its background wait. `POST /api/refresh` returns accepted,
skipped, or disabled without waiting for BLE. Requests during active/reserved
passes or within 30 seconds of the last start are skipped without a retry queue.
The background delay restarts after each completed pass. Cancellation clears
admission state and awaits Poller shutdown.

Dashboard load and the 30-second timer concurrently request a refresh and read
stored Telemetry. Failed HTTP requests leave existing cards visible. Added
positive finite `freshness_seconds` config, default 60, emitted by discovery;
offline status now uses it independently of background timing. README updated.

Validation: `uv run pytest -m 'not integration'` — 77 passed, 2 live cases
excluded. Covers app refresh while BLE is active, sleeping wake-up, exact
30-second boundary, atomic duplicate admission, one active BLE call, shutdown
cancellation, background operation without refreshes, Poller failure recovery,
invalid/default freshness, discovery output, and freshness boundary with a
600-second background interval. `git diff --check` passed. Browser rendering
and live hardware were not exercised for this ticket.
