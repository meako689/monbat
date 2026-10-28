# Recover Battery connections after laptop sleep/resume

Type: task
Status: claimed
Triage: needs-info

## Problem

The user reports that after the laptop sleeps and resumes, Monbat does not
reconnect to the Batteries. The affected platform, failure mechanism, and
duration of failed recovery are not yet confirmed.

## Scope

- Debug the failure with the user on the affected laptop. Arrange a live
  sleep/resume reproduction session; the user performs sleep and wake actions.
- Record the OS, Bluetooth backend, Monbat/Bleak versions, relevant polling
  configuration, Dashboard subscriber state, and which Batteries are affected.
- Capture timestamped service logs and successful Telemetry before sleep,
  sleep/wake times, connection/read failures after resume, retry timing, and
  whether the Poller and Dashboard event stream continue running. Collect
  Bluetooth backend evidence where needed to distinguish application state
  from adapter/device availability.
- Compare active collection with retained BLE connections against background
  collection with the Dashboard closed. Reproduce more than one cycle when
  practical and record sleep duration and any recovery action taken.
- Identify the failing boundary before selecting a fix: scheduling/backoff,
  suspended reads or cleanup, stale BLE clients/devices, notification setup,
  Bluetooth readiness, or subscriber lifecycle. These are hypotheses, not
  established causes.
- Implement the smallest fix supported by the evidence. Coordinate with
  [ticket 26](26-reconnect-with-cached-ble-devices.md) where recovery overlaps;
  do not assume device caching alone fixes resume behavior. Add a dependency
  only if diagnosis establishes one.
- Simulate the observed interruption and recovery at the Poller boundary in
  offline regression tests, including backend failures or stalled operations
  identified during diagnosis. Use controlled time where scheduling matters.
- Repeat the physical sleep/resume process with the user after the fix and
  update the focused operational documentation with verified behavior and
  limitations.

Automatic adapter resets, BMS resets, and Battery control writes are outside
scope. Creating this ticket does not start a sleep/resume experiment.

## Acceptance criteria

- The ticket records a reproducible sequence, platform, relevant logs, and
  an evidence-supported cause; uncertainty and unreproduced cases are explicit.
- On the affected laptop, after Bluetooth becomes available following resume,
  Monbat automatically reconnects, subscribes, reads, and saves new Telemetry
  for each available configured Battery without restarting the service or
  requiring manual rediscovery. Record the observed recovery time and its
  relationship to configured cadence and retry backoff.
- An unavailable Battery enters bounded retries while healthy Batteries
  continue updating. No overlapping requests, duplicate clients, tight retry
  loops, or indefinitely blocked cleanup are introduced.
- Failed recovery preserves previous readings and timestamps; Dashboard
  freshness remains accurate and successful new readings appear after recovery.
- Regression tests reproduce the diagnosed failure and pass with the fix.
  Relevant existing tests pass. Offline simulation alone does not count as
  verification of physical sleep/resume recovery.
- The post-fix user session verifies active and background collection where
  practical. Any untested platform or scenario is recorded as a limitation.

## References

- [Post-ticket-26 validation plan](../plans/27-sleep-resume-validation.md)
- [Collection cadence specification](../spec.md#update-speed-revision--2026-10-17)
- [Dashboard operations](../../../docs/operations/dashboard.md)
- [Poller](../../../src/monbat/poller.py)
- [BLE driver](../../../src/monbat/bms.py)
- [Cached-device recovery task](26-reconnect-with-cached-ble-devices.md)

## Comments

- 2026-10-28: Logging commit `a70a336` pushed and fast-forward pulled on Linux.
  Old server stopped gracefully; restarted at DEBUG in screen `619728.monbat`
  with PID `619732`. Output `/tmp/monbat-debug-a70a336.screen.log` flushes every
  second. Startup discovery, subscription, reads, saves and cleanup succeeded
  for both Batteries; Dashboard HTTP 200 verified from the laptop. Configuration
  unchanged. Mac Python direct HTTP failed with `No route to host` even outside
  the sandbox; SSH remains available. Deployment evidence recorded in the plan.
  Physical sleep/resume validation has not started; ticket remains claimed.

- 2026-10-28: User authorized DEBUG instrumentation in main code with no
  collection/recovery logic change, commit/push, remote pull and restart at
  DEBUG. Implemented subscriber/scheduler/retry, BLE stage, Telemetry save and
  SSE snapshot logs, plus `monbat serve --log-level debug`; INFO stays default.
  Final offline suite: 118 passed, two hardware cases deselected. A sandboxed
  run blocked three Chromium launches; the complete rerun outside the sandbox
  passed. Focused startup checks verified DEBUG routing and the INFO default. Physical validation
  remains outstanding; ticket stays claimed.

- 2026-10-28: Read-only remote logging assessment found timestamped screen
  output at `/tmp/monbat-c3ce892.screen.log` and background interval 1800 seconds.
  Existing failures have tracebacks, but subscriber/scheduler/retry and operation
  progress are not logged sufficiently to distinguish a silent stall. Plan
  records targeted instrumentation recommended before the physical pass; no
  source/configuration changes, restart or sleep/resume test were performed.

- 2026-10-28: User confirms ticket 26 is deployed. Primary validation is now
  Dashboard closed before/during sleep, wake, then opening the Dashboard to
  wake collection and Battery connections. Other scenarios follow after the
  primary verdict. User authorizes temporarily shortening the background
  interval to speed testing; record and restore the setting, with any required
  restart outside the measured sleep/recovery cycle. Validation plan revised;
  no remote changes or physical test have started.

- 2026-10-28: User requested a validation plan after ticket 26 implementation,
  using `tira@192.168.88.144`, `/home/tira/code/monbat`, the service in screen,
  and its Dashboard on port 8000. Claimed for validation preparation. Plan
  records deployment verification, timestamped evidence, active/background
  physical sleep/resume cycles and decision criteria. No remote inspection,
  deployment, restart or sleep/resume experiment has started. Triage remains
  needs-info until the affected platform and live evidence are confirmed.

- 2026-10-27: User requested a debugging and fixing task for Battery connections
  failing after laptop resume, with simulation and debugging together with
  the user. Task creation only. Live reproduction details remain to be gathered.
