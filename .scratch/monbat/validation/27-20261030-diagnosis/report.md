# Ticket 26/27 regression diagnosis

Recommend a targeted revision of ticket 26, not a full rollback. Remove the
Linux stale-cache delay and replace the indefinite cleanup gate with recovery
that can retire an unusable transport after establishing OS disconnection.
Keep healthy reads first, bounded operations, persistence error separation,
client ownership, and DEBUG logging. No production fix or deployment was made.

## Evidence

Read-only SSH inspection on 2026-10-30 used `remote-user@host.example`, the deployed
checkout `$HOME/code/monbat` at `9751e3a`, `/tmp/monbat.log`, SQLite in
read-only mode, and system journals. Bleak 3.0.2, dbus-fast 5.2.0. Process
620555 started on October 28 at 22:39:26 and was still running. Configuration:
background interval 1800s, active interval 10s, timeout 10s, concurrency 1,
persistent connections enabled. This process was running at INFO; the captured
log contains no DEBUG stage evidence. Its missing DEBUG lines are not proof
that operations did not run.

1. **Stale Linux cache halves background collection frequency.** BlueZ Device1
   objects are repeatedly missing when Monbat uses cached BLEDevice objects.
   Ticket 26 defers rediscovery to the next collection pass. Background retries
   therefore wait 30 minutes rather than the 10–60s backoff. The database shows
   successful saves at 08:28, 09:28, 11:28, 12:28, through 19:28 for both
   Batteries, and bat-2 at 10:28. Failed direct attempts occur around xx:58.
   Typical successful background cadence is now 60 minutes. In active mode,
   several page openings show missing-object failures followed by connections
   about 32–34s later. At inspection time `bluetoothctl info` reported both
   objects unavailable; this does not establish whether Batteries advertise.

2. **A dead client blocks bat-1 recovery indefinitely.** The system resumed at
   21:04:12, with Intel Bluetooth firmware reloaded. At 21:21:10 bat-1 timed out
   waiting for Bleak service discovery. Subsequent disconnect raises EBADF from
   dbus-fast's writer through asyncio's selector. It fails again at 21:50:48.
   `Poller._close` retains the client and sets cleanup_pending on every error;
   `_pass` skips replacement until close succeeds. Retrying a permanently
   unusable transport cannot satisfy this condition. Bat-1's last saved reading
   was 20:19:26; bat-2 later saved at 22:21:00. The scheduler and persistence
   therefore continue; this is not a total Poller stall.

3. **Ticket 27 is instrumentation, not a recovery optimization.** Commit
   `a70a336` added DEBUG logs and log-level selection. It did not change the
   recovery decisions. Ticket 27 remains claimed and unfixed.

4. **A full rollback is not a reliable cure.** Pre-ticket-26 `_pass` awaits
   `connection.close()` without an exception guard after setup failure.
   Replaying setup timeout plus EBADF with that actual older Poller lets EBADF
   escape the collection pass; `run()` has no catch for it. A rollback removes
   the new cleanup deadlock but restores this failure path and the original
   discovery gate. This is an offline comparison, not a hardware rollback test.

## Reproductions and causal probes

The preserved [diagnostic harness](diagnostic_repro.py) drove the Poller version
present during the October 30 diagnosis. Its timeout/dead-bus case also uses
the real BatteryConnection with a fake external BleakClient. The second case
simulates BlueZ object expiry after background disconnection. It uses controlled
monotonic time and no hardware.
Run from the repository root:

```sh
PYTHONPATH=tests uv run --group dev pytest -c pyproject.toml \
  .scratch/monbat/validation/27-20261030-diagnosis/diagnostic_repro.py \
  -q -s --tb=no
```

Observed in 0.43s: **2 failed, 1 passed**. Dead-client case: one client, zero
saved readings, cleanup_pending=True after four eligible retries. Background
case: saved counts `[2, 0, 2, 0, 2]`. Older-Poller test confirms the escaping
cleanup error. These intentionally failing diagnostic checks are not part of
the normal test directory and are not a completed production regression suite.

Two isolated probes passed against the temporary copy of the same harness:

- `MONBAT_DIAGNOSTIC_PROBE=retire-dead-client`, selecting `-k dead_bus`:
  two clients, four saved readings, cleanup_pending=False.
- `MONBAT_DIAGNOSTIC_PROBE=scan-first`, selecting `-k background`:
  saved counts `[2, 2, 2, 2, 2]`.

The probe implementations remain in the diagnostic harness for replay. The
first deliberately discards the failed client without OS verification. It
demonstrates causality only and is **not a safe production implementation**.
No probe changed production source or the remote process.

## Post-fix interpretation — 2026-10-31

The two failing results above are historical and were captured before the
recovery correction. The harness defaults its fake OS inspection to
`UNAVAILABLE`; under the corrected contract, retaining that client is the safe
expected outcome, so the old dead-client assertion is not a post-fix recovery
test. The permanent Poller regressions now exercise `DISCONNECTED` and `ABSENT`
release, plus `CONNECTED` and `UNAVAILABLE` retention, and the scheduler test
verifies retry timing against a long background interval.

## Proposed fix and limits

- On Linux, discover before background reconnection, or verify that the cached
  BlueZ object exists before choosing direct recovery. Missing-object failures
  should not consume an entire collection slot. Keep caching where it helps,
  especially on supported backends whose object lifetime differs.
- Distinguish transient cleanup failures from an unusable client transport.
  Use a fresh OS-level control path to confirm Device1 is disconnected or gone;
  if connected, request a bounded disconnect before retiring the old client.
  Do not interpret EBADF or Bleak's cached connected flag alone as proof of
  physical disconnection. Keep prevention of overlapping live clients.
- A read-only source review of the installed Bleak 3.0.2 and dbus-fast 5.2.0
  was completed on 2026-10-31. Bleak's BlueZ connect path wraps connection and
  service discovery in a timeout; on setup failure, its `AsyncExitStack` tries
  `Device1.Disconnect` over that client's bus before cleaning up and closing
  it. Normal client disconnect also uses the same bus. dbus-fast's synchronous
  `MessageBus.disconnect()` marks the bus as user-disconnected and shuts down
  its socket; the asyncio backend unregisters the file descriptor during
  finalization. This confirms cleanup is tied to the client bus. It does not
  establish why the descriptor became invalid or why service resolution
  stalled. No timeout-only workaround or dependency change is justified.
- Keep ticket 27 logging. Validate corrected behavior with offline cases for
  permanently broken cleanup and stale background objects, followed by an
  actual Linux sleep/resume session. No claim of hardware recovery is made.

The raw captured service log is beside this report as `service-captured.log`.
It is ignored by the repository's existing `*.log` rule. Existing uncommitted
ticket-27 evidence and unrelated research files were preserved.
