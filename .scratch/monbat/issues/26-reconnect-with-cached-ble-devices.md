# Reconnect Batteries using cached BLE devices

Type: task
Status: open
Triage: ready-for-agent

## Problem

The Poller requires a fresh discovery result whenever it creates a Battery
connection, including after a failed read. A Battery missing from that scan
never receives a connection attempt, even if the running service previously
discovered it. Passing its configured address directly to BleakClient does
not bypass discovery: the installed macOS and Linux backends scan when given
an address instead of a BLEDevice.

The user reported a Battery that may believe it is still connected. That
cause is unconfirmed. This task removes the fresh-discovery gate for known
Batteries; it cannot force a BMS that refuses connections to accept one.

## Scope

- Cache each configured Battery's discovered BLEDevice in the Poller for the
  lifetime of the running service. Use it for all connections, including
  background polling. Keep it when closing a connection or when a scan misses
  the Battery; replace it when discovery finds a new BLEDevice.
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
disconnect/reconnect on available hardware and record the platform and
limitations. Recovery from the reported physical BMS lockup remains unverified
unless reproduced and tested; offline coverage must not claim to resolve it.

## References

- [Persistent connection lifecycle](17-persistent-ble-connections.md)
- [Poller](../../../src/monbat/poller.py)
- [BLE driver](../../../src/monbat/bms.py)
- [Dashboard operations](../../../docs/operations/dashboard.md)
- [Current protocol implementation](../../../docs/protocol/redodo.md)

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
