# Recover Battery connections after laptop sleep/resume

Type: task
Status: claimed
Triage: ready-for-agent

## Problem

On the Linux laptop, a reproduced service-discovery timeout followed by EBADF
disconnect errors leaves an unusable client blocking Battery recovery. Stale
BlueZ objects also consume alternate background collection slots, producing
roughly hourly readings with a configured 30-minute interval. The application
failure paths are established; the original transport failure cause is not.

## Implementation specification

The [recovery specification](../../monbat-recovery/spec.md) is the authoritative
implementation and testing scope. It supersedes the original investigation
scope below where they differ. It requires OS-confirmed release before client
replacement, prompt per-Battery background retry scheduling, concise recovery
logs, offline regressions, and physical Linux validation. Ticket 27 owns this
work; ticket 26 remains resolved, with its cleanup/retry contract revised by
the new spec. No new blocking dependency is required.

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

- [Next debugging session handoff](../../../HANDOFF-ticket27-debugging.md)
- [Primary physical validation result](../validation/27-20261028-cycle1/report.md)
- [Post-ticket-26 validation plan](../plans/27-sleep-resume-validation.md)
- [Collection cadence specification](../spec.md#update-speed-revision--2026-10-17)
- [Dashboard operations](../../../docs/operations/dashboard.md)
- [Poller](../../../src/monbat/poller.py)
- [BLE driver](../../../src/monbat/bms.py)
- [Cached-device recovery task](26-reconnect-with-cached-ble-devices.md)

## Comments

- 2026-11-01: User approved shared background discovery and Dashboard connection
  reuse. [Ticket 28](28-shared-background-discovery.md) is implemented and resolved
  locally: one fresh scan per background pass, reuse for newly eligible recovery,
  and discovery-candidate release at the background boundary. All 133 offline
  tests and both original diagnostic cases pass. The unchanged replay fails
  against the pristine pre-change Poller. No deployment or physical validation
  performed; ticket 27 remains claimed for the Linux sleep/resume retest.

- 2026-11-01: Read-only SSH diagnosis of `/tmp/monbat-log-1nov.log` confirms
  prompt background retries are deployed, but all 38 post-startup scheduled
  background passes first fail on missing cached BlueZ objects. Median retry
  completion is 24s for bat-1 and 39s for bat-2. Deterministic replays show
  avoidable cached-attempt/backoff overhead and a second shared-discovery defect:
  millisecond retry-deadline drift can split two Batteries into separate scans.
  Discovery-first and deadline-batching causal probes pass. Recommend shared
  discovery after long Linux idle gaps and batched recovery while preserving
  current cleanup safety. [Evidence, limitations, and runnable diagnostics](../validation/27-20261101-cache-diagnosis/report.md).
  Existing recovery/driver checks: 80 passed, two live tests deselected. No
  production change, deployment, adapter action, or physical retest performed;
  status remains claimed.

- 2026-10-31: Published the [recovery specification](../../monbat-recovery/spec.md)
  using to-spec, synthesizing both October 30 investigations and the earlier
  physical evidence. Triage is ready-for-agent; status remains claimed.
  Proposed the existing Poller/scheduler behavior boundary with external
  BLE/BlueZ fakes and a physical Linux retest for the user's seam check.
  The spec rejects blanket OSError retirement and fixed-count force-discard,
  and requires confirmed OS connection release before replacement. No production
  implementation, deployment, or new hardware validation performed.

- 2026-10-31: Diagnosed the October 30 `/tmp/monbat.log` through read-only SSH,
  OS journals, read-only SQLite, and deterministic offline reproductions.
  Ticket 26's stale cached BlueZ objects defer discovery by one background
  slot, producing typical hourly saves with a configured 30-minute interval.
  A service-resolution timeout followed by permanent EBADF cleanup retains
  bat-1's unusable client and blocks replacement indefinitely. Ticket 27 only
  added instrumentation. Recommend targeted cache/retry and cleanup revisions;
  the actual older Poller lets setup-cleanup EBADF escape the pass, so full
  rollback is not a reliable recovery fix. [Evidence and diagnostic harness](../validation/27-20261030-diagnosis/report.md)
  record failing cases and successful causal probes. No production code,
  configuration, remote process, or adapter state changed. Keep claimed;
  production fix and physical retest remain outstanding.

- 2026-10-28: At the user's request, moved the next-session debugging handoff
  from the OS temporary directory into the project root as
  `HANDOFF-ticket27-debugging.md`. It links the validation evidence, records
  working state and authorization, and outlines the next debugging steps.

- 2026-10-28: Primary physical cycle failed with ticket 26 deployed. Dashboard
  closed and BLE clients released before 96 seconds of deep sleep. Resume at
  22:30:51 +0200; Dashboard subscription at 22:31:04 immediately woke collection.
  Both cached devices failed with device-not-found; shared rediscovery found
  both. Bat-2 resumed saving at 22:31:49 and continued updating. Bat-1 timed out
  waiting for Bleak service discovery, then cleanup repeatedly raised EBADF
  from the dbus-fast writer/asyncio selector. Failed cleanup retained the client
  and blocked replacement. Five-minute evaluation: bat-1 zero new readings,
  bat-2 26 observed distinct new readings; FAIL. User loaded, waited, and reloaded
  the page once. Same service PID and boot ID; no manual recovery or config
  change. Evidence and repeatable check linked above. Keep claimed, defer other
  scenarios, and diagnose/simulate this failing boundary before selecting a fix.

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
  using `remote-user@host.example`, `$HOME/code/monbat`, the service in screen,
  and its Dashboard on port 8000. Claimed for validation preparation. Plan
  records deployment verification, timestamped evidence, active/background
  physical sleep/resume cycles and decision criteria. No remote inspection,
  deployment, restart or sleep/resume experiment has started. Triage remains
  needs-info until the affected platform and live evidence are confirmed.

- 2026-10-27: User requested a debugging and fixing task for Battery connections
  failing after laptop resume, with simulation and debugging together with
  the user. Task creation only. Live reproduction details remain to be gathered.

- 2026-10-31: Implemented ticket 27's recovery correction while preserving
  ticket 26's cache, healthy-read ordering, shared discovery, persistence
  handling, and client ownership. Failed client cleanup now uses a fresh,
  bounded Linux system-D-Bus connection to inspect BlueZ Device1 state. It
  retires the client only after object absence or disconnected state is
  confirmed; a connected object receives an independent bounded disconnect
  request followed by another state query. Connected/unavailable states retain
  ownership and back off. Background recovery now wakes at eligible per-Battery
  retry deadlines and runs only failed Batteries without changing the regular
  background start cadence. INFO summaries report persisted, failed, and
  deferred Battery IDs; expected cache misses are concise and DEBUG stage logs
  remain. The timeout → EBADF transport cause remains unproven.

  Before the fix, the preserved diagnostic harness reproduced both failures:
  the dead-client case had one client, zero saved readings, and cleanup pending
  after four retries; stale-cache background passes saved `[2, 0, 2, 0, 2]`.
  The older-Poller comparison also showed cleanup EBADF escaping its pass.
  Permanent Poller/scheduler regressions now cover disconnected, absent,
  connected, and unavailable OS states, failed independent disconnect, later
  release confirmation, fresh subscription/read persistence, healthy-Battery
  isolation, the 1800-second background interval, regular cadence, logging,
  backoff, persistence errors, request serialization, and bounded shutdown.

  Validation: `uv run --group dev pytest -m 'not integration' -q` passed with
  130 passed and two integration cases deselected. Focused recovery/collection
  checks passed (47 tests); `git diff --check` passed. Physical Linux sleep/resume
  remains pending. Read-only preflight on `remote-user@host.example` found the old
  checkout at `9751e3a`, screen session `723191.pts-2.remote-laptop`,
  server PID `723196`, and HTTP 200 from `/api/latest`. Installed Bleak 3.0.2,
  dbus-fast 5.2.0 and `/usr/bin/bluetoothctl`; config remains 1800-second
  background, 10-second active, 10-second timeout, concurrency 1, persistent
  enabled, Batteries `bat-1` and `bat-2`. No remote source, service, config,
  adapter, or Battery state was changed. The post-fix retest is prepared in the
  validation plan, but requires authorization before deploying/restarting the
  remote service and an agreed user sleep/wake window. Keep claimed until the
  physical retest passes.
