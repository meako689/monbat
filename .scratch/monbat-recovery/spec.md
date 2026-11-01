# Restore Battery recovery after failed BLE cleanup and stale Linux discovery

Status: open
Triage: ready-for-agent

## Problem Statement

Monbat can leave an available Battery offline indefinitely after the Linux
laptop resumes. In the reproduced sequence, service discovery times out,
disconnect raises `Bad file descriptor`, and the Poller keeps retrying cleanup
on the same unusable client. Replacement and rediscovery never happen for that
Battery, although the other Battery continues saving Telemetry.

Background recovery also takes longer than configured. With a 30-minute
collection interval, a cached BLEDevice whose BlueZ object has disappeared
consumes one pass. Rediscovery waits another 30 minutes, producing roughly
hourly saved Telemetry. Opening the Dashboard can likewise incur a failed
cached attempt and delayed rediscovery before readings resume.

At INFO level, successful background collection is silent while expected cache
misses produce warning tracebacks. The user cannot easily distinguish successful
recovery, an unavailable Battery, and recovery blocked by cleanup.

## Solution

Revise the existing recovery behavior without reverting tickets 26 and 27.
An available Battery should recover automatically when the old OS connection
is released, even if the original client cannot disconnect. Recovery retries
must respect backoff without waiting for an entire background collection
interval. Healthy Batteries must continue their normal collection cadence.

Keep cached discovery where useful, healthy reads before recovery, bounded
operations, separate persistence failure handling, and DEBUG instrumentation.
Provide concise INFO evidence of successful background collection and recovery
progress. Preserve stored readings and accurate Dashboard freshness throughout
failures. Verify the result on the affected Linux laptop after offline tests.

## User Stories

1. As a Battery owner, I want Monbat to recover after laptop resume, so that I do not have to restart the service to restore readings.
2. As a Battery owner, I want an available Battery to receive another connection attempt after failed setup, so that one timeout does not permanently abandon it.
3. As a Battery owner, I want recovery to continue when the original client transport is unusable, so that repeatedly failing disconnect calls do not block monitoring forever.
4. As a Battery owner, I want Monbat to confirm that the old OS connection is released before replacement, so that recovery does not create competing live clients.
5. As a Battery owner, I want a missing BlueZ object to lead to rediscovery, so that a stale Python object does not prevent new readings.
6. As a Battery owner, I want background recovery to retry after backoff, so that a cache miss does not add another 30-minute wait.
7. As a Battery owner, I want healthy background collection to retain its configured cadence, so that retries for another Battery do not cause frequent unnecessary BLE work.
8. As a Dashboard user, I want opening the Dashboard to wake collection promptly, so that I can see new readings without manual rediscovery.
9. As a Dashboard user, I want healthy Batteries to update while another Battery recovers, so that one failure does not unnecessarily interrupt all monitoring.
10. As a Dashboard user, I want failed collection to retain the last successful reading and timestamp, so that old data is never presented as newly collected.
11. As a Dashboard user, I want unavailable or stale readings to remain offline, so that connection attempts alone do not imply fresh Telemetry.
12. As a Dashboard user, I want Battery Bank totals to follow existing Freshness rules, so that a failed Battery does not produce misleading totals.
13. As a Battery owner, I want shared discovery for Batteries needing recovery, so that simultaneous failures do not start competing scans.
14. As a Battery owner, I want retry backoff during prolonged unavailability, so that Monbat does not enter a tight loop.
15. As a Battery owner, I want temporary cleanup failures to recover safely, so that an arbitrary retry count does not discard a still-connected client.
16. As a Battery owner, I want unavailable OS connection state to trigger another bounded check, so that uncertainty does not cause unsafe replacement or stop healthy monitoring.
17. As a Battery owner, I want a new connection to subscribe and receive its own validated response, so that old notification data cannot masquerade as recovery.
18. As a service operator, I want successful background collection visible at INFO, so that silent success does not look like continuous failure.
19. As a service operator, I want expected cache misses logged concisely, so that routine rediscovery does not bury actual faults in tracebacks.
20. As a service operator, I want unresolved cleanup and backend failures to remain visible, so that reduced log noise does not hide a real outage.
21. As a service operator, I want database failures handled separately from BLE failures, so that storage errors do not trigger needless scans or connection replacement.
22. As a service operator, I want shutdown and cancellation to finish within bounded cleanup attempts, so that partially initialized clients do not hang the service.
23. As a macOS user, I want the existing supported recovery behavior preserved, so that a Linux-specific fix does not assume BlueZ on other platforms.
24. As a maintainer, I want deterministic tests for the captured failure sequence, so that recovery regressions are caught before deployment.
25. As a maintainer, I want a physical Linux sleep/resume retest, so that simulated recovery is not mistaken for verified hardware behavior.
26. As a maintainer, I want evidence separated from hypotheses, so that an unproven socket failure mechanism does not determine the fix.

## Implementation Decisions

- Modify the existing Poller scheduler, recovery lifecycle, and BLE driver
  boundary. Keep a single scheduling owner and typed per-Battery state. Keep
  Linux OS connection details inside the driver/backend boundary rather than
  teaching the Poller D-Bus paths or Bleak private fields.
- Keep discovery caching in memory for the service lifetime. A cached
  BLEDevice is a connection candidate, not proof of a live BlueZ object or
  established radio connection. Fresh discovery replaces matching cache
  entries; scan misses and errors do not erase useful cached candidates.
- Preserve deferred shared discovery after a failed cached attempt. Do not
  make a second connection attempt for the same Battery in the same pass.
  Make the deferred retry eligible through the scheduler after backoff instead
  of waiting for the next background collection slot.
- Distinguish normal collection deadlines from per-Battery recovery deadlines.
  In background mode, wake for the earliest eligible retry or normal pass.
  A retry-only wake operates on eligible failed Batteries; it must not read
  healthy Batteries early or rebase their normal collection schedule. Batch
  eligible recovery work and share any required discovery.
- Preserve the active scheduled-start cadence and skipped-slot behavior.
  Retry eligibility cannot cause overlapping passes or requests. Recovery may
  still delay a following pass within bounded work budgets; independent
  per-Battery workers are not required.
- Retain 10/20/40/60-second backoff. Apply it to recovery, failed cleanup, and
  unavailable OS checks without immediate repeated attempts. Count an original
  failed recovery cycle once; cleanup failures do not count it again. Only
  successful Telemetry persistence clears the failure/backoff state.
- Continue normal bounded cleanup first. If it cannot release the original
  client, use an independent, bounded Linux OS control path to establish
  whether the Battery's Device1 object is absent, disconnected, connected, or
  unavailable to inspect. This path must not reuse the broken client transport.
- Absence or confirmed OS disconnection permits retirement of the unusable
  client and later replacement. If OS state is connected, request a bounded
  Device1 disconnect and confirm release before replacement. This is connection
  cleanup, not an adapter reset or Battery control command.
- A socket error, Bleak's cached connected flag, or a fixed cleanup-attempt
  count alone does not prove release. Do not catch every OSError as success or
  force-discard after two arbitrary failures. If OS state cannot be established
  or disconnection fails, preserve ownership, report the unresolved cleanup,
  and retry verification after backoff. Once OS release becomes observable,
  recovery must progress without a service restart.
- Bound each driver operation and the overall recovery/cleanup work. Inspect
  the installed Bleak and dbus-fast timeout cleanup behavior before selecting
  a workaround or dependency change. Do not assert that increasing the timeout
  alone solves the dead-client policy failure.
- Preserve ownership of clients before asynchronous setup begins, including
  failed connection or subscription setup. Prevent replacement until the old
  OS connection is released. Cancellation and shutdown account for every owned
  client and make bounded final cleanup attempts without reconnecting.
- Read healthy retained connections before recovery work on a normal pass.
  Keep configured request concurrency independent of retained-client count.
  A replacement must subscribe and collect a separate validated response.
- Keep persistence retries separate from discovery decisions. A save failure
  does not invalidate a healthy active connection or discovery cache. Background
  clients still close after reads. A retry-only background wake may retry failed
  persistence collection, but it must not refresh unrelated healthy Batteries.
- Add one concise INFO summary for background collection attempts, identifying
  successful Batteries and failures/deferred cleanup. Distinguish successful
  persistence from connection setup. Keep frequent active saves at DEBUG.
  Log expected missing-object fallback concisely; preserve actionable warnings
  for unresolved cleanup, scan/backend failures, and continued unavailability.
  Existing DEBUG operation-stage evidence remains available.
- Keep the existing configuration, HTTP/SSE response contracts, SQLite schema,
  and Freshness rules. Update focused operational documentation when the new
  retry and cleanup behavior is implemented and verified.
- This spec supersedes ticket 26's requirement that replacement always requires
  success from the original client's disconnect method, and its restriction
  that background retries wait for the regular collection cadence. It retains
  the underlying requirement to release the old OS connection before replacement.

## Testing Decisions

- Prefer the existing Poller and scheduler as the primary behavior-test
  boundary. Run real scheduling, recovery, and persistence orchestration with
  controlled time; fake only external BLE/BlueZ operations and storage failures.
  Assert saved Telemetry, timing, ordering, live-client exclusion, and observable
  outcomes rather than names of private state flags.
- Reuse the existing recovery rig and collection scheduler tests. Promote the
  diagnostic timeout/dead-client and stale-background scenarios into permanent
  regressions at their real call sites. Use the real BatteryConnection with a
  fake external BleakClient where response or cancellation behavior matters.
- Reproduce setup timeout followed by permanent EBADF cleanup. Verify recovery
  when the OS object is absent or disconnected, including a fresh subscription
  and saved response. Confirm another Battery continues updating. The old
  client must not receive endlessly repeated unusable-transport cleanup when
  independent verification already establishes release.
- Cover OS state still connected, successful independent disconnect, failed or
  timed-out disconnect, and unavailable OS inspection. Assert that no replacement
  connects until release is confirmed; later successful verification permits
  recovery. Cover transient original-client cleanup without force-discard.
- At the scheduler boundary, simulate BlueZ expiry between background passes.
  With a configured 1800-second interval, verify deferred rediscovery runs at
  the eligible retry deadline plus bounded work, not 1800 seconds later. Verify
  retry-only wakes do not read healthy Batteries early, reset regular cadence,
  overlap requests, or repeat already completed work at a stale deadline.
- Cover 10/20/40/60-second retries, shared discovery, scan errors/misses,
  persistent/background modes, grace transitions, and first-subscriber wakes.
  Cover transitions between background retries and active collection so that
  deadlines and subscribers do not create extra overlapping passes.
- Preserve response isolation, persistence failure handling, cleanup failure
  accounting, and bounded cancellation/shutdown cases. Cover shutdown while an
  OS verification or independent disconnect is pending. Run relevant existing
  recovery, collection, driver, API/SSE, and Dashboard regression checks.
- Capture logs at INFO and DEBUG to verify concise background success/failure
  evidence, routine cache-miss treatment, actionable unresolved cleanup, and
  retained stage diagnostics. Do not assert incidental traceback formatting.
- Add a focused backend-boundary test only if the OS cleanup mechanism cannot
  be exercised meaningfully through the Poller. Keep it about connection-state
  outcomes, with D-Bus as the external dependency. Do not introduce a new
  generic abstraction solely to make a shallow test possible.
- Validate on the affected Linux laptop with real saved Telemetry and Dashboard
  freshness. Repeat the primary scenario: close Dashboard, wait for grace and
  cleanup, sleep, wake, then open Dashboard without reload or manual recovery.
  Record platform/dependency versions, process identity, sleep/wake times,
  backend availability, retry timing, and first/new saved readings per Battery.
- Require at least three new readings for each available Battery and fresh
  status within the recorded five-minute post-subscription evaluation window.
  Report unavailable backend/Battery conditions explicitly rather than treating
  absence as evidence of a fixed recovery path. Verify background recovery too,
  without an SSE subscriber; any temporary interval changes must be recorded,
  restored, and applied outside the measured cycle.
- Offline tests do not establish physical sleep/resume recovery. Resolve ticket
  27 only after the agreed hardware retest passes; record any untested scenario
  or platform limitation.

## Out of Scope

- Reverting all ticket 26/27 changes or deleting DEBUG instrumentation.
- Automatic Bluetooth adapter resets, BMS resets, charge/discharge controls,
  pairing changes, or attempts to force a nonadvertising Battery to connect.
- A guarantee that an unavailable adapter or Battery will become reachable.
- Treating sleep/resume as the proven cause of the closed D-Bus descriptor, or
  assigning an upstream library/firmware defect without additional evidence.
- Independent Battery worker scheduling, a generic recovery framework, new
  Dashboard controls, history charts, or service packaging.
- Configuration, API, or storage schema redesign; deployment is separate from
  publishing this spec.

## Further Notes

The affected deployment uses Linux Mint/BlueZ 5.64, Bleak 3.0.2, dbus-fast 5.2.0,
Python 3.15.0, concurrency 1, a 10-second timeout and active interval, a 1800-second
background interval, and 60-second Freshness. These are observed settings, not
new defaults. No precise BlueZ eviction lifetime has been established.

The physical evidence establishes resume, service-resolution timeout, EBADF
cleanup, and the resulting application deadlock. It does not establish exactly
when or why the D-Bus descriptor became invalid. The independent investigation's
blanket-discard proposal and claimed socket cause are not adopted here.

The deterministic diagnostic checks reproduce both policy failures. A temporary
retirement probe restores readings and a scan-first probe removes skipped slots;
the retirement probe omits OS verification and is not production-ready. Replaying
failed setup cleanup against the pre-ticket-26 Poller lets the disconnect error
escape collection, so a full rollback is not a verified remedy.

Sources:

- [Ticket 27](../monbat/issues/27-recover-battery-connections-after-laptop-resume.md)
- [Ticket 26](../monbat/issues/26-reconnect-with-cached-ble-devices.md)
- [Physical sleep/resume evidence](../monbat/validation/27-20261028-cycle1/report.md)
- [October 30 diagnosis and diagnostic harness](../monbat/validation/27-20261030-diagnosis/report.md)
- [Independent investigation and fix plan](../monbat/plans/27-sleep-resume-cleanup-findings-and-plan.md)

This is a ready-for-agent specification, not a completed implementation or
hardware verification. Ticket 27 remains the implementation/validation owner.
