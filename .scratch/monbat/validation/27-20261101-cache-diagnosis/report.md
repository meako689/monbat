# November 1 diagnosis: cached Linux background connections

Implementation follow-up: the user approved these changes, now implemented
locally in [ticket 28](../../issues/28-shared-background-discovery.md). The
investigation below records the pre-change deployment. Post-fix evidence is
recorded at the end of this report; the Linux deployment has not been updated
in this session.

Use shared discovery before Linux background connections after long idle gaps.
Keep retained active connections, bounded cleanup with OS release confirmation,
and prompt background retries. Cached BLEDevice reuse has no demonstrated benefit
at this host's 30-minute background cadence: every post-startup scheduled pass
in this capture first fails on missing BlueZ objects.

No production source, remote configuration, process, or Bluetooth state was
changed. The requested outcome is diagnosis and recommendations; implementation,
deployment, and physical comparison remain separate work. Ticket 27's physical
sleep/resume acceptance remains outstanding.

## Environment and evidence

Read-only SSH succeeded before investigation. Captured the supplied
`/tmp/monbat-log-1nov.log`, redacting network addresses, local usernames, Battery
names, and BLE addresses. The ignored `service-captured.log` beside this report
contains the redacted capture. Its timestamps cover October 31, 08:25:54, through
November 1, 08:54:43, at UTC+02:00.

Local and remote HEAD are `9ab8035`. SHA-256 matches for all relevant source:

| File | SHA-256 |
| --- | --- |
| `src/monbat/poller.py` | `e2408cbd91f1642a213e2008564562ef088e80744fcf5c9f765429a8f9fead2f` |
| `src/monbat/bms.py` | `6243853754481cb030fd617024a1e10b928157f0a93bc5ac68de312932fc77e1` |
| `src/monbat/bluez.py` | `419560c5c889ffcc91d1945a7fe783493791227fc69bcb1d75be9932e4721d13` |

Python 3.15.0, Linux 5.15.0-198-generic, BlueZ 5.64, Bleak 3.0.2,
dbus-fast 5.2.0. Two configured Batteries; background interval 1800s, active
interval 10s, timeout 10s, concurrency 1, retained connections enabled,
Freshness 60s. A fresh, read-only BlueZ query reported both Device1 objects
absent during inspection. That query does not establish BMS availability.

### What the new log proves

- 39 normal background pass summaries: startup saved both Batteries; the
  remaining 38 saved nothing and deferred both after missing-object errors.
  Thus all 76 scheduled cached candidates after startup failed.
- 78 retry-only pass summaries: 33 saved only bat-1, 32 only bat-2, five saved
  both, and eight saved neither. Recovery is usually split across passes.
- For 37 complete background recovery episodes, failed-pass-to-successful-retry
  summary times were bat-1 **24s median, 24–30s range**; bat-2 **39s median,
  28–116s range**. One additional failed normal pass was interrupted by active
  Dashboard collection and is excluded from these background timing samples.
- Background saves resume around the 30-minute cadence. The previous defect
  that delayed rediscovery by another 30 minutes is corrected in this version.
- There are 109 first missing-object messages, eight repeated missing-object
  warnings, one service-discovery disconnect traceback, and **no EBADF**.
  The earlier permanent cleanup failure is not reproduced in this capture.
- Cold startup saved both Batteries 18s after server startup. This is a useful
  reference, not a controlled hardware comparison with the cached policy.

Timing above measures INFO summary timestamps, after cleanup. It is not an
instrumented breakdown of scan, connection, status read, and persistence.

Reproduce the summary:

```sh
python3 .scratch/monbat/validation/27-20261101-cache-diagnosis/analyze_log.py \
  .scratch/monbat/validation/27-20261101-cache-diagnosis/service-captured.log
```

## Reproduction and causal probes

The [diagnostic replay](diagnostic_repro.py) drives the actual Poller. The
first case also uses the actual BatteryConnection, real validated status bytes,
and fake external BleakClient/scanner boundaries. It primes one background
read, removes the backend object, then advances controlled time 1800 seconds.
Discovery still returns the available Battery. No eviction cause or lifetime
is assumed: absence at the next poll is an observed input.

```sh
PYTHONPATH=tests uv run --group dev pytest -c pyproject.toml \
  .scratch/monbat/validation/27-20261101-cache-diagnosis/diagnostic_repro.py \
  -q -s --tb=no
```

Repeated runs fail deterministically in about 0.2s:

```text
saved_at_due=0 scans=2 connection_attempts=3 retry_delay=10s saved_after_retry=1
retry_offsets=[10.001, 10.002] recovery_scans=2 both_saved_after=38.001s
2 failed
```

The first failure remains with only two passes when
`MONBAT_DIAGNOSTIC_MINIMAL=1` and `-k available_battery` are added. The third
pass in the full replay confirms availability and automatic recovery.
Removing object expiry with `MONBAT_DIAGNOSTIC_PROBE=object-preserved` makes
that case pass with one scan total. Removing the priming pass would instead
exercise cold discovery, not stale-cache reuse.

Ranked hypotheses were presented before causal probes:

1. **Cached Python identity outlives the BlueZ object. Confirmed.** A
   `MONBAT_DIAGNOSTIC_PROBE=scan-first` run with `-k available_battery` passes:
   two scans and two connection attempts across both collection cycles, zero
   retry delay. Current policy needs the same scans plus a failed cached attempt
   and backoff. Installed Bleak accepts the cached Device1 path without fresh
   discovery; its manager raises `device ... not found` when that path is absent.
   Keeping a BLEDevice in Python does not keep the backend object alive.
2. **Retry scheduling adds delay. Partly confirmed.** Long-interval starvation
   is fixed, but near-identical retry deadlines fragment shared discovery.
   `_failed` sets each Battery's deadline from a separate monotonic reading;
   `_pass` snapshots eligibility before scanning. A Battery becoming eligible
   during another Battery's scan is not included. Even though that scan refreshes
   its cache, its `rediscover` flag still forces another scan next pass.
   The minimal second replay uses two Batteries and only 1ms deadline drift.
   `MONBAT_DIAGNOSTIC_PROBE=batch-deadlines` with `-k simultaneous` changes only
   those deadlines and passes: **one recovery scan, 28.002s for both**.
   The INFO log's split saves and roughly 14s gap fit this mechanism; exact live
   scan counts and deadline drift are not observable at INFO.
3. **Slow scan/connection work dominates the remaining time. Supported as a
   cost, not established as a new transport regression.** Discovery deliberately
   waits the configured 10s, and connection concurrency is one. With simulated
   4s setup/read costs, the existing split path takes 38s, a shared recovery scan
   28s, and discovery first 18s. These are controlled model timings, not measured
   hardware A/B results. Increasing concurrency would leave the policy waste.
4. **BMS intermittently unavailable. Not the explanation for routine misses.**
   Discovery commonly restores valid readings after cache failure. One actual
   service-resolution disconnect and slower outliers remain. Missing Device1
   objects alone do not prove a nonadvertising or unavailable BMS. The precise
   BlueZ removal mechanism and short-gap object lifetime remain unproven.

## Recommended changes

1. **Make long-idle Linux background collection discover first.** Use one
   shared scan for eligible disconnected Batteries, then connect with the fresh
   BLEDevice results. Keep cached candidates for recent reconnects where their
   backend objects still exist. Keep healthy retained reads first. This changes
   ticket 26's requirement to use cached objects for every background connection;
   amend that contract before implementation. Do not invent a cache TTL from
   this single 30-minute observation.
2. **Batch recovery discovery.** Align deadlines for failures from the same
   recovery batch without shortening backoff, or include newly eligible cleanup-
   clear Batteries when shared discovery finishes. Verify each deadline before
   connection and prevent duplicate attempts. A regression must cover both
   Batteries failing nearly simultaneously; the existing scheduler test expires
   only bat-1 and therefore misses this pattern.
3. **Distinguish cache absence from Battery failure.** Route a known absent
   object to discovery. Keep backoff for real connection/setup/read failures
   and discovery misses/errors. A missing cached object is insufficient evidence
   for the warning that a Battery "remains unavailable."
4. **Preserve the useful recovery work.** Retained Dashboard connections,
   client ownership, confirmed OS release before replacement, bounded cleanup,
   healthy reads first, persistence isolation, prompt retry wakes, and concise
   success logs remain valuable. A wholesale rollback is unnecessary.

Before claiming a performance improvement, compare these policies on Linux
at the actual background interval and on Dashboard opening. Measure time to
valid saved Telemetry for both Batteries, cache hit rate, scans per collection,
connection attempts, and failed recovery cycles. Capture targeted DEBUG stage
timings and BlueZ object-removal events if investigating removal itself.
Current evidence does not justify adapter/BMS resets, dependency changes,
timeout increases, or an automatic full rollback.

## Validation and scope

- Primary replay: repeated red; minimal prefix red; object-preserved and
  discovery-first controls green. Deadline-batching probe green.
- `uv run --group dev pytest tests/test_recovery.py tests/test_bms.py
  -m 'not integration' -q`: **80 passed, two live tests deselected**.
- The two diagnostic expectations intentionally remain failing against current
  policy, outside the normal test directory. No production fix or permanent
  passing regression test is claimed. Fix and physical verification phases are
  deferred because this task requests diagnosis and recommendations.
- No new DEBUG instrumentation or remote Bluetooth operations were added.
  Existing ticket-27 DEBUG instrumentation was preserved. Replay artifacts are
  explicitly marked diagnostics; `.env.local`, `config.toml`, and captured logs
  remain ignored by Git.

## Implementation follow-up — November 1

Background passes now share fresh discovery results and discard disconnected
candidates. A failed Battery whose deadline matures during a background scan
uses the same results when cleanup is clear. Active Dashboard collection and
its grace period preserve retained clients and recent reconnect candidates;
opening the Dashboard after background idle starts with discovery.

The permanent missing-object regression uses the real Poller/driver, two
Batteries, and four 1800-second-gap collection cycles. Each cycle saves both
with one scan and two connection attempts. Separate cases cover a retry
maturing during discovery, a retry still in backoff, and Dashboard connection
reuse after initial discovery. Before the production change, the new cases
reported three failures and one passing future-deadline control.

The second diagnostic replay now counts discovery for the entire post-idle
collection plus any recovery passes, because the corrected normal pass itself
performs the required scan. The identical updated harness was run against a
temporary copy with `poller.py` restored from pristine HEAD: both cases still
fail, with 10s backoff and two recovery scans finishing in 38.001 simulated
seconds. Against the working source:

```text
saved_at_due=1 scans=2 connection_attempts=2 retry_delay=0s saved_after_retry=1
retry_offsets=[] recovery_scans=1 both_saved_after=18.000s
2 passed in 0.21s
```

`uv run --group dev pytest -m 'not integration' -q` passes all 133 offline
checks, with two live cases deselected. No new debug instrumentation was added;
existing stage diagnostics remain. These results validate the policy and its
regressions, not physical timing or sleep/resume recovery. Ticket 28 is resolved
for local implementation; deployment and ticket 27's Linux retest are pending.
