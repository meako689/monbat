# Ticket 27: primary sleep/resume cycle 1

The primary test failed after ticket 26. Bat-2 recovered; bat-1 remained
blocked by failed BLE cleanup throughout five minutes after Dashboard opening.
The observer recorded zero new readings for bat-1 and 26 distinct new readings
for bat-2. No fix or manual recovery was applied. The observer is now stopped;
Monbat continues running at DEBUG with the original polling configuration.
The history API independently confirms zero saved post-open rows for bat-1 and
27 for bat-2 within five minutes; the polling observer missed one early row.

## Setup and sequence

- Linux laptop `remote-user@host.example`, `$HOME/code/monbat`, source `a70a336`
  with documentation commit `9751e3a`. Server PID `619732` stayed unchanged.
- Linux 5.15.0-198-generic; BlueZ 5.64, Bleak 3.0.2, dbus-fast 5.2.0,
  Python 3.15.0. Config: background 1800 seconds, active 10 seconds,
  timeout 10 seconds, freshness 60 seconds, concurrency 1, persistent enabled.
- Both Batteries updated before Dashboard closure. Subscriber count reached
  zero, grace expired, and BLE cleanup completed at 22:25:42 +0200.
- The external curl observer uses only latest/summary GETs. No SSE observer,
  manual discovery, adapter reset, BMS reset or service restart was performed.
- User reported around two minutes asleep, then loading the Dashboard, waiting,
  and reloading the browser page. There was no Monbat refresh POST in the
  captured sequence. Browser reload must be recorded as part of this cycle.

All times below are 2026-10-28 in the laptop's +0200 timezone.

| Time | Evidence |
|---|---|
| 22:29:15 | systemd and kernel: deep suspend starts |
| 22:30:51 | systemd/kernel: resume; same boot ID |
| 22:30:52 | Bluetooth firmware finishes loading; kernel reports supported-features failure (-16) |
| 22:30:54 | Ethernet link returns |
| 22:31:04 | First Dashboard subscriber; scheduler wakes immediately and starts an active pass |
| 22:31:04 | Both cached connects fail with BlueZ device-not-found; cleanup succeeds; rediscovery scheduled |
| 22:31:14 | Scheduled pass precedes retry deadlines by milliseconds; both Batteries deferred |
| 22:31:24 | Next eligible pass starts shared discovery |
| 22:31:35 | Discovery finds both; bat-1 connection setup starts |
| 22:31:43 | Browser reload replaces the SSE subscription while the recovery pass is already running |
| 22:31:47 | Bat-1 times out waiting for BLE service discovery; its cleanup fails with EBADF |
| 22:31:47 | Bat-2 connection setup starts in the same pass |
| 22:31:49 | Bat-2 connects, subscribes, reads and saves fresh Telemetry |
| 22:32:09 onward | Bat-1 cleanup repeatedly fails; replacement setup is blocked; bat-2 continues saving |

The initial Dashboard subscription correctly woke collection, without waiting
for the 1800-second background interval. The browser reload occurred during an
already-running recovery pass; this evidence does not establish that reloading
was necessary for bat-2 to recover.

## Failing boundary

Bat-1's refreshed-device connection times out in Bleak
`BlueZDBusClient._get_services` → `_wait_for_services_discovery`. Cleanup then
fails in `dbus_fast`'s D-Bus writer → asyncio selector registration with
`OSError: [Errno 9] Bad file descriptor`. Repeated cleanup attempts retain this
client and prohibit replacement, as ticket 26 specifies for failed cleanup.
Retries remain bounded; this is not an inactive Poller or a missing Dashboard
wake. The reason the D-Bus transport became unusable has not been established.

Backend state captured at 22:32:57: adapter powered; bat-2 connected;
bat-1 Device1 not available. That later state does not prove bat-1 was never
available after resume: shared discovery found it at 22:31:35.

Bat-1 keeps its pre-sleep timestamp `1793219137.5525982` and is offline.
Bat-2's first post-resume saved timestamp is `1793219509.490633`, approximately
58.5 seconds after resume and 45.5 seconds after the first Dashboard subscription.
API and SSE evidence agree with the user's report of one live and one stale.

## Evidence and repeatable check

- [Preflight](preflight.txt), [versions](versions.txt), [backend/journal](backend-after.txt)
- [Baseline readings](latest-before.json), [HTTP series](http.jsonl), [user reports](user-events.jsonl)
- [Final readings](latest-after.json), [summary](summary-after.json), [saved history](history-after.json), [verdict](verdict.txt)
- [Service before sleep](service-before.log), [service after resume](service-after.log)
- [Human steps](../27-sleep-resume-loop.sh), [non-subscribing observer](../27-http-observer.py)

The recorded cycle was evaluated with:

```sh
python3 .scratch/monbat/validation/27-check-recovery.py \
  .scratch/monbat/validation/27-20261028-cycle1
```

This script checks for at least three new readings from each baseline Battery
and fresh status by the end of five minutes after Dashboard subscription. It
returns INCOMPLETE before the window ends, FAIL for missing recovery, and PASS
for recovery. It only evaluates captured evidence and cannot trigger collection.
Result: exit 1, `FAIL: not every Battery resumed fresh saved Telemetry`.
This is one reproduced physical cycle, not a measured reproduction rate or a
validated fix. Other scenarios are deferred until this failure is addressed.

## Decision

Keep ticket 27 claimed and defer further sleep scenarios. The next work is to
reproduce the service-discovery timeout followed by unusable-transport cleanup
at the Poller/Bleak boundary and establish safe cleanup/replacement behavior.
Do not simply discard a client on arbitrary disconnect errors: ticket 26's
protection against overlapping clients still applies. The precise transport
failure mechanism and a validated fix remain outstanding. Repeat this primary
physical cycle after the regression and fix, avoiding browser reload if possible.
