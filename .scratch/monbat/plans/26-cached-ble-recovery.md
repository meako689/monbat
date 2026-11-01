# Ticket 26 implementation plan

Implement [ticket 26](../issues/26-reconnect-with-cached-ble-devices.md) in the
Poller and BLE lifecycle. Implemented and validated on 2026-10-28; ticket
resolved with [results and evidence](../issues/26-reconnect-with-cached-ble-devices.md#answer).
Claimed before production changes. No dependency on
ticket 27 is established. The previous bat-2 incident is no longer a target.

## 1. Retain devices and own client cleanup

In `src/monbat/poller.py`, use private typed per-Battery state for the cached
`BLEDevice`, current connection, cleanup requirement, next attempt kind,
failure count, retry deadline, and persistent-connection logging state.
Keep scheduling and the public Poller interface unchanged. Keep this state
local to the Poller; no new service layer or public recovery abstraction.

Populate caches from shared discovery results for every configured Battery,
including Batteries not currently eligible for recovery. Replace entries only
when discovery finds a matching address. Scan misses, scan failures,
disconnects, and inactive collection preserve the cache. A new Poller starts
with no cache. Pass only real `BLEDevice` objects to Poller-created clients.

Register a newly constructed connection before awaiting setup. Successful
disconnect removes the client; failed or timed-out disconnect retains it and
marks cleanup required. Replacement is forbidden while cleanup is pending.
Bound each cleanup attempt by `timeout_seconds` and log its failure.

In `src/monbat/bms.py`, remove the unbounded disconnect inside notification
setup failure handling. Give callers explicit lifecycle ownership and review
all callers (`poll_battery`, discovery probes, and Poller) so each still cleans
up failed setup. Bound setup and cleanup for these paths without changing the
status request, parser, response isolation, or ATT write mode.

## 2. Order each pass and implement retry transitions

Snapshot eligible Batteries once per pass. Finish reads and persistence for
healthy retained connections before any recovery cleanup, scan, or connection
attempt. Share the configured request concurrency limit across both phases.
Continue using one scheduling owner and skip missed cadence slots.
Batteries failing in the healthy-read phase enter backoff; do not create a
replacement for them in that pass. Perform their cleanup after healthy reads
finish. Process eligible direct recoveries before the shared discovery phase.

For an eligible Battery needing recovery:

1. If cleanup is pending, attempt it once. Failure defers all further work
   for that Battery until backoff expires. Cleanup must not count the original
   read/setup failure a second time.
2. With a cache and a direct attempt due, connect using that object, subscribe,
   and read valid Telemetry. Bound recovery BLE work by `timeout_seconds`;
   cleanup has its own timeout budget. Persist outside the BLE recovery budget.
3. Without a cache, or with rediscovery due, join one shared scan for the pass.
   Refresh all matching cache entries. Attempt setup/read only for eligible
   Batteries found by this scan. A miss or scan error does not fall back to
   a cached attempt in the same pass.
4. After BLE failure, perform one bounded cleanup attempt. Retain a client
   whose cleanup fails. Schedule the next attempt after backoff.

| Outcome | Next eligible attempt |
|---|---|
| Retained read fails | Direct cached attempt after cleanup |
| Direct cached setup or read fails | Shared rediscovery |
| Rediscovery setup or read fails | Direct cached attempt |
| Scan misses or fails, cache exists | Direct cached attempt |
| Scan misses or fails, no cache | Shared rediscovery |
| Telemetry saved successfully | Clear failure count and retry deadline; next new connection uses cache |
| Database save fails | Persistence/polling retry; preserve BLE cache and attempt kind |

Count each unsuccessful collection/recovery cycle once. Keep the existing
10/20/40/60-second backoff and reset it only after valid Telemetry is saved.
Separate BLE exception handling from repository save handling so a database
error does not invalidate a healthy retained connection or trigger discovery.
Background collection still disconnects after a read; a failed background
disconnect blocks the next connection until cleanup succeeds.

Do not retry pending cleanup on every scheduler wake or inactive-loop
iteration. Retry on an eligible pass after backoff. A shutdown attempt is the
explicit exception.

## 3. Account for cancellation and shutdown

Keep partially connected and partially subscribed clients in Poller state.
Propagate cancellation after lifecycle accounting. In `run()`'s final cleanup,
attempt disconnect once for each retained client, including pending cleanup.
Bound each attempt separately, log failures, and finish shutdown even when a
disconnect fails. Avoid duplicate final cleanup through nested exception paths.
No client may disappear from tracking merely because setup raised or timed out.

## 4. Add behavior-focused offline coverage

Add `tests/test_recovery.py` alongside `tests/test_collection.py` with controlled discovery/client doubles,
an adjustable monotonic clock, and the repository boundary. Assert client
identity, scan counts, saved Telemetry, and operation order. Cover:

- Cached reconnect in active and background modes, including scan absence.
- Healthy reads finishing before recovery, concurrency limits, and no overlap.
- Old disconnect before replacement; fresh subscription and separate response.
- Deferred discovery after connection, subscription, and read failures.
- Cache refresh, scan miss/error retention, retry alternation, and uncached scans.
- A BlueZ `device ... not found` failure followed by a fresh scan object.
- Backoff progression, one failure count per cycle, and reset only after save.
- Database errors without rediscovery or needless active disconnect.
- Cleanup exceptions/timeouts blocking replacement and respecting backoff.
- Cancellation during setup, subscription, read, and cleanup; bounded shutdown
  including clients whose setup never completed.
- Cache surviving grace/background transitions and disappearing on restart.

Use focused `tests/test_bms.py` coverage where needed for caller cleanup and
notification response isolation. Keep existing SSE, cadence, discovery-probe,
and browser regressions passing. Run focused collection/driver checks first,
then `uv run pytest -m 'not integration'`. Hardware tests are separate.

## 5. Validate on remote Linux and document the result

Identify the SSH host, repository path, service manager, and available access
before execution. The repository does not record these connection details.
Record the deployed revision and Linux, BlueZ, Bleak, Python, and adapter
versions. Verify at least one configured Battery is available.

Stop the existing Monbat process during the hardware test. Use an isolated
checkout, temporary configuration, and a temporary SQLite database. Preserve
the existing service configuration and storage. Run the same Poller and driver
as production, with a small harness recording discovery and lifecycle events.

Discover once, save Telemetry, deliberately close the local client, and verify
a subsequent connection with the cached `BLEDevice` subscribes, reads, and
saves newer Telemetry without invoking discovery. Repeat for background
collection. Test a controlled local disconnect during retained collection
and verify recovery with healthy Battery reads occurring first.

Where reproducible, capture a real missing BlueZ Device1 failure and replacement
by rediscovery. Otherwise record that case as offline-only coverage; a normal
Linux reconnect does not prove stale-object recovery on hardware. Avoid
adapter resets and Battery controls. The old bat-2 incident has no required
reproduction or recovery check.

Always finish test-client cleanup and restore the service's prior running
state. Record exact commands, versions, scan/connection counts, Telemetry
timestamps, cleanup outcomes, and limits of the evidence in the ticket.

Update `docs/operations/dashboard.md`, `docs/operations/configuration.md`, and
`docs/protocol/redodo.md` with cache lifetime, retry behavior, timeout scope,
and cleanup/shutdown limits. Resolve the ticket only after required offline
checks and the Linux reconnect validation pass; append the result to the map.
