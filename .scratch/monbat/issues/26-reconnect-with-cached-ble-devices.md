# Reconnect Batteries using cached BLE devices

Type: task
Status: resolved
Triage: ready-for-agent

## Problem

The Poller requires a fresh discovery result whenever it creates a Battery
connection, including after a failed read. A Battery missing from that scan
never receives a connection attempt, even if the running service previously
discovered it. Passing its configured address directly to BleakClient does
not bypass discovery: the installed macOS and Linux backends scan when given
an address instead of a BLEDevice.

This task removes the fresh-discovery gate for known Batteries. The previously
reported bat-2 incident no longer applies and is not a validation target.

## Scope

- Cache each configured Battery's discovered BLEDevice in the Poller for the
  lifetime of the running service. Use it for all connections, including
  background polling. Keep it when closing a connection or when a scan misses
  the Battery; replace it when discovery finds a new BLEDevice.
- On Linux, a cached BLEDevice depends on its BlueZ Device1 object still
  existing. A missing object is a failed cached attempt, not proof that the
  BMS is connected. Follow the deferred rediscovery path; do not fabricate
  device paths or retry with a string address that triggers implicit scanning.
- Read healthy connected Batteries before attempting recovery. Recovery may
  delay the following pass; independent scheduling is outside this ticket.
- After a read or connection failure, disconnect the old client before
  creating a replacement. Bound each cleanup attempt by the configured
  timeout. If cleanup fails or times out, retain the client and retry cleanup
  after backoff. Create a replacement only after cleanup succeeds.
- Try a new BatteryConnection with the cached BLEDevice. Recovery includes
  connection, notification subscription, and a successful status read.
- A failed cached connection, subscription, or status read schedules shared
  rediscovery on the next eligible retry, after backoff. Do not scan and make
  a second connection attempt in the same pass.
- On the discovery retry, refresh cache entries for configured Batteries and
  attempt connection for eligible missing Batteries found by that scan. A
  scan miss or discovery failure keeps the cache; after backoff, try the
  cached device directly again. Alternate direct attempts and rediscovery
  after failures. Batteries without a cache continue using discovery.
- Bound recovery attempts and retain the existing 10/20/40/60-second backoff.
  Count a failed recovery cycle once per Battery; cleanup failure must not
  double-count the original failure. Reset backoff after valid Telemetry is
  saved. Database save failures use polling/persistence retries without
  triggering rediscovery or invalidating the device cache.
- Preserve request serialization, configured concurrency, browser cadence,
  retained-connection behavior, and background disconnects.
- Track clients created during recovery, including failed setup and pending
  cleanup. On shutdown, make one final disconnect attempt per retained client,
  bounded by the configured timeout. Log failures and let shutdown finish;
  release of an OS or BMS connection cannot be guaranteed.
- Update the focused operational/protocol documentation to describe recovery
  and the cache's lifetime.

Automatic Bluetooth adapter resets and BMS resets are outside scope.

## Acceptance criteria

- A previously discovered Battery can reconnect and save Telemetry using its
  cached BLEDevice without a new scan, including when it would be absent from
  fresh discovery results. Background connection attempts use the cache too.
- A failed read closes the old client before a replacement connects. The
  replacement subscribes to notifications and collects a separate response.
- A failed cached connection, subscription, or status read enters backoff;
  shared discovery happens on the next eligible retry. A refreshed BLEDevice
  replaces the cached entry and is used for that retry's connection attempt.
- Scan misses and discovery failures retain cached devices. Subsequent
  retries alternate direct cached attempts and shared rediscovery. A database
  save failure does not schedule rediscovery.
- A stale Linux BLEDevice whose BlueZ object has disappeared follows the
  same bounded failure/backoff and deferred rediscovery path. A fresh scan
  result replaces the stale entry; preserving a Python object must not be
  mistaken for preserving BlueZ state.
- An uncached Battery still uses discovery. Discovery errors, absent Batteries,
  and failed recovery attempts enter backoff without an immediate retry loop
  or duplicate failure counts.
- Healthy connected Batteries are read before recovery starts. No Battery
  receives overlapping requests. The next pass may be delayed by recovery.
- Failed or timed-out cleanup retains the old client and prevents replacement
  until cleanup succeeds on a later retry. Cleanup failures are logged.
- Cancellation and shutdown account for all clients created during recovery,
  including clients whose connection or subscription setup fails. Final
  disconnect attempts are bounded; failures are logged and shutdown finishes.
- Cache entries remain in memory only. Restarting Monbat requires discovery
  again; no BLEDevice details are written to configuration or storage.

## Validation plan

Require behavior-focused offline coverage at the Poller boundary for cached
recovery in active and background collection, deferred rediscovery, cache
retention and refresh, uncached discovery, backoff and failure counting,
database failure handling, healthy Battery read ordering, cleanup failures and
timeouts, cancellation, and bounded shutdown. Validate a normal
disconnect/reconnect on the remote Linux host and record the platform and
limitations. The previous bat-2 incident is outside the current validation scope.
Include a cached-connect failure representing BlueZ's `device ... not found`
and verify deferred discovery and replacement with a fresh BLEDevice. Record
whether the hardware reconnect test uses Linux/BlueZ or macOS/CoreBluetooth;
the latter does not validate Linux object lifetime. A macOS check may supplement
the required Linux reconnect check.

## Implementation plan

See [the implementation plan](../plans/26-cached-ble-recovery.md) for code
changes, retry transitions, offline coverage, and remote Linux validation.

## References

- [Persistent connection lifecycle](17-persistent-ble-connections.md)
- [Poller](../../../src/monbat/poller.py)
- [BLE driver](../../../src/monbat/bms.py)
- [Dashboard operations](../../../docs/operations/dashboard.md)
- [Current protocol implementation](../../../docs/protocol/redodo.md)
- [Linux direct-reconnect research and hardware observations](../../../docs/research/ble-ghost-connection.md)
- [Redodo reset research and model applicability limits](../../../docs/research/redodo-bluetooth-reset.md)

## Answer

Implemented on 2026-10-28. The Poller owns typed per-Battery cache, connection,
cleanup, and retry state. Healthy retained reads finish before recovery.
Active/background reconnects use cached BLEDevice objects; failed direct
attempts defer shared rediscovery and alternate retries without discarding
cache entries. BLE setup/read errors and database failures have separate
handling. Failed cleanup retains clients, blocks replacement, and respects
backoff. Driver setup and disconnects are bounded; shutdown accounts for
partially initialized clients. Focused operational/protocol docs and the spec
describe the behavior.

Validation:

- `uv run --group dev pytest -m 'not integration' -q`: 118 passed, two live
  tests deselected. Thirty new recovery cases cover identity/cache behavior,
  retry/backoff, BlueZ missing-object failures, real-driver response isolation,
  database errors, request ordering, cleanup timeouts, cancellation, grace
  transitions, and shutdown. Browser checks pass outside the macOS sandbox;
  the sandbox denied Chromium's MachPort launch on one run.
- `git diff --check`: passed after the user restored Git.
- Linux hardware check on `tira@192.168.88.144`, existing checkout
  `/home/tira/code/monbat` at `2aa9274`, candidate source under
  `/tmp/monbat-ticket26.JDeENX`: Linux 5.15.0-198-generic, BlueZ 5.64,
  Bleak 3.0.2, Python 3.15.0, Intel USB adapter `8087:0a2b`.
- Both configured Batteries were available. One shared discovery supplied
  cached devices. A controlled bat-1 disconnect caused a failed read and old
  client cleanup. Bat-2 saved valid Telemetry before that cleanup and before
  bat-1 replacement setup. After the 10-second backoff, the replacement
  subscribed and saved newer Telemetry using the identical cached device;
  no additional scan occurred. Both background reconnects also used the cache.
  Nine Telemetry rows were saved (bat-1: four; bat-2: five).
- All five created hardware clients disconnected; final connected-client list
  was empty. Monbat was stopped before and after the test. Validation used a
  temporary database and source snapshot; the existing deployment was not
  updated. No adapter reset or Battery control was performed.
- Source SHA-256 matched local and remote files: Poller
  `8aeaa651988ea6542630bb4dc5068610ff2b7676b20b0aa78e1f777785e5ec74`,
  driver `f272b4796836ec37d2faeb0a73c224169d610741fc6206fff39d9083d4d15cef`.

Reproducible harness: [26-linux-reconnect.py](../validation/26-linux-reconnect.py).
Run with candidate `src` on `PYTHONPATH`, then pass the existing config path
and a fresh temporary SQLite path. Captured evidence:
[26-linux-reconnect.log](../validation/26-linux-reconnect.log).
Hardware command:

```sh
cd /tmp/monbat-ticket26.JDeENX
PYTHONPATH=/tmp/monbat-ticket26.JDeENX/src \
  /home/tira/code/monbat/.venv/bin/python \
  .scratch/monbat/validation/26-linux-reconnect.py \
  /home/tira/code/monbat/config.toml \
  /tmp/monbat-ticket26.JDeENX/telemetry.db
```

The missing BlueZ Device1 path, cleanup failures/timeouts, and shutdown
cancellation were validated offline, not reproduced on hardware. This short
Linux test does not establish long-run reliability or sleep/resume recovery
(ticket 27). The historical bat-2 incident is no longer a validation target.

## Comments

- 2026-10-18: User requested a separate ticket for caching discovered BLEDevice
  objects and trying them before rediscovery. Ticket creation only;
  implementation is deferred. No automatic Bluetooth adapter reset or BMS
  reset is included.
- 2026-10-18: Grilling completed and shared understanding confirmed by the
  user. Scope and acceptance criteria above record all eight decisions:
  cache use in all modes, deferred rediscovery, healthy reads first, cache
  retention after scan misses, bounded cleanup before replacement, offline
  and hardware validation, BLE versus persistence failure handling, and
  bounded final shutdown cleanup. Implementation remains deferred.
- 2026-10-19: Linux investigation with Monbat stopped: BlueZ 5.64, Bleak
  3.0.2, Intel Bluetooth 4.2 adapter. Bat-2 (`B00734`,
  `C8:47:80:3F:91:B1`) had neither a cached BlueZ object nor an established
  local connection. Two 12-second scans saw bat-1 but not bat-2. Direct
  public-address ATT connections with gatttool timed out at 18 seconds and,
  after 35 seconds with the adapter powered off, at 40 seconds. The same
  read-only service query connected to bat-1 immediately. No physical BMS
  lockup recovery was achieved; caching cannot force a nonadvertising BMS
  to connect. Bat-1's supplied `device ... not found` traceback illustrates
  the separate stale BlueZ object failure that this ticket must handle.
- 2026-10-19: User identifies bat-2 as a Redodo 24 V 100 Ah Bluetooth Battery
  produced in 2024; firmware may be 1.1.0 or 1.0.1 and is unconfirmed.
  User stopped further remote recovery and requested research only.
  Automatic adapter/BMS resets remain outside this implementation. Ticket
  stays open and ready-for-agent; these are specification updates, not a
  completed implementation.
- 2026-10-28: User confirmed the bat-2 issue no longer applies and requested
  an implementation plan with approval. Plan recorded; production code has not
  changed. Earlier bat-2 observations remain historical, not acceptance targets.
- 2026-10-28: User authorized implementation. Ticket claimed; Git is unavailable
  on the local machine. Implement and validate without Git commands.
- 2026-10-28: User supplied Linux SSH access and then restored Git. Implementation,
  all 118 offline tests, and Linux active/background reconnect validation passed.
  Ticket resolved; result and evidence linked from the map.
