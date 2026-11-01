# Research Findings and Fix Plan: Sleep/Resume Cleanup and Recovery

- Date: 2026-10-30
- Target: Laptop `remote-laptop` (Linux Mint / BlueZ / Bleak / monbat)
- Related tickets: [Ticket 26](../issues/26-reconnect-with-cached-ble-devices.md), [Ticket 27](../issues/27-recover-battery-connections-after-laptop-resume.md)

---

## 1. Executive Summary

- **Verdict on Tickets 26 & 27**: **Do not revert or ditch the improvements.**
  The core mechanism of Ticket 26 (service-lifetime caching of `BLEDevice` + deferred discovery fallback) was proven to work reliably for both batteries in active collection (Dashboard open) and in hourly background recovery all day.
- **Why it appeared broken**:
  1. **Logging blindspot**: Successful background reads log only at `DEBUG`. Because the service was run at `INFO` level, all successful collections were completely silent in stdout.
  2. **Expected cache-miss tracebacks**: Cached attempts repeatedly found no matching BlueZ Device1 object after long background gaps, then discovery succeeded on a later collection pass. This pattern is consistent with stale BlueZ objects after inactivity, but the exact eviction mechanism and lifetime are not established. The cache miss logged a full `WARNING` traceback, creating the impression of continuous failure.
- **The recovery policy defect**:
  In the captured resume sequence, service discovery timed out and a later
  `connection.close()` raised `OSError: [Errno 9] Bad file descriptor` from
  dbus-fast's writer path. Ticket 26 retains the client while cleanup fails, so
  the Poller never admits that Battery to replacement or rediscovery. This
  explains the application deadlock. The evidence does not establish why the
  D-Bus descriptor became unusable; the controller and Bluetooth service events
  around resume are temporal context, not a proven transport cause.

---

## 2. Research Findings & Diagnostic Evidence

### A. Background Collection Health in SQLite (`monbat.db`)
Direct query of the SQLite database revealed that telemetry was successfully collected and persisted for both `bat-1` and `bat-2` every hour at `:28`:
- `13:28:24` (bat-1), `13:28:28` (bat-2)
- `14:28:24` (bat-1), `14:28:28` (bat-2)
- `15:28:24` (bat-1), `15:28:28` (bat-2)
- `16:28:24` (bat-1), `16:28:28` (bat-2)
- `17:28:24` (bat-1), `17:28:28` (bat-2)
- `18:28:24` (bat-1), `18:28:28` (bat-2)
- `19:28:24` (bat-1), `19:28:28` (bat-2)

Furthermore, during active Dashboard sessions (e.g. 07:17–07:28, 19:48–20:19), persistent connections connected within 10–30 seconds and streamed 10-second updates normally.

### B. Analysis of `/tmp/monbat.log`
The 1,065 lines of stdout logs contained 53 tracebacks, which fell into three recurring error patterns:
1. **`BleakError: device 'dev_...' not found` (45 occurrences)**:
   - Raised by `bleak.backends.bluezdbus.manager._check_device(device_path)` when attempting a cached connect.
   - The captured failures are consistent with a missing cached Device1 object after prolonged inactivity. The evidence does not establish the precise eviction mechanism or lifetime.
2. **`BleakError: failed to discover services, device disconnected` (2 occurrences)**:
   - Transient BLE disconnect during GATT service resolution. Handled cleanly by backoff.
3. **`OSError: [Errno 9] Bad file descriptor` (2 occurrences)**:
   - Raised from `dbus_fast.aio.message_bus` / `asyncio.selector_events.add_writer` during `connection.close()` after the recorded resume.
   - The captured order establishes that the error followed resume, but not why or when the descriptor became invalid.

### C. Kernel & System Sleep Sequence (`journalctl`)
```text
жов 30 21:02:53 kernel: PM: suspend entry (deep)
жов 30 21:04:12 kernel: ACPI: PM: Waking up from system sleep state S3
жов 30 21:04:12 kernel: Bluetooth: hci0: Found device firmware: intel/ibt-12-16.sfi
жов 30 21:04:12 systemd[1]: Stopped target Bluetooth Support.
жов 30 21:04:12 systemd[1]: Reached target Bluetooth Support.
```
The logs record Bluetooth firmware loading and service-target transitions after
wake. They do not establish that the controller reset closed Bleak's D-Bus
descriptor or caused the later EBADF. The transport failure mechanism remains
unresolved.

### D. The Application Recovery Deadlock in Code (`src/monbat/poller.py`)
In `_close()`:
```python
try:
    async with asyncio.timeout(self._config.poller.timeout_seconds):
        await connection.close()
except Exception:
    state.failures = max(1, state.failures)
    self._backoff(state)
    logger.warning("Disconnect failed for %s", battery_id, exc_info=True)
    return False  # <--- Does NOT clear state.connection or cleanup_pending
```
And in `_pass()`:
```python
for battery in recovering:
    state = self._batteries[battery.id]
    if state.cleanup_pending and not await self._close(battery.id):
        continue  # <--- Skips battery completely! Never reaches direct or discovery!
    ready.append(battery)
```
When `connection.close()` repeatedly fails with `[Errno 9]`, the Poller keeps
the same client in `cleanup_pending` and skips replacement. This code path
explains why recovery stops regardless of the unresolved reason for the D-Bus
error.

---

## 3. Historical Fix Plan (superseded)

The [recovery specification](../../monbat-recovery/spec.md), published on
2026-10-31, supersedes this proposal. A socket error or fixed cleanup-attempt
count does not permit client retirement; the Poller must confirm BlueZ object
absence or disconnection independently. The D-Bus failure cause remains
unresolved. Do not use the deployment or restart steps below without separate
authorization; the user performs any physical sleep/wake actions.

### Step 1: Write an Offline Regression Test (Red Phase)
- **Location**: `tests/test_recovery.py`
- **Scenario**:
  1. Initialize Poller with a connected mock battery.
  2. Simulate an `OSError(errno.EBADF, "Bad file descriptor")` on `connection.close()`.
  3. Run `_pass()`.
  4. Assert that `cleanup_pending` does not permanently deadlock the battery, and that on subsequent retry, the battery is admitted into `ready` and can discover/reconnect with a fresh client.
- **Verification**: Run test against current code to confirm it fails (RED).

### Step 2: Implement Bounded Cleanup in `src/monbat/poller.py` (Green Phase)
1. **Differentiate fatal transport / socket errors in `_close()`**:
   - If `connection.close()` fails with `OSError` (e.g. `EBADF`, `ENOTCONN`, `ECONNRESET`), or if Bleak signals an already-disconnected backend, log the warning but consider the client discarded:
     ```python
     except OSError:
         logger.warning("Transport error during disconnect for %s; discarding client", battery_id, exc_info=True)
         state.connection = None
         state.cleanup_pending = False
         return True
     ```
2. **Bound cleanup retries**:
   - Even for non-socket exceptions, add a maximum cleanup retry count (e.g. 2 attempts). If cleanup cannot complete after 2 backoff cycles, force-discard `state.connection = None` and clear `cleanup_pending = False` so the battery is not permanently abandoned.

### Step 3: Align Background Polling and Discovery
1. **Prompt Rediscovery in Background Mode**:
   - When a cached attempt fails in background mode, currently `retry_at` is set to `now + 10s`, but the scheduler sleeps for `poll_interval_seconds` (1800s).
   - Allow the background scheduler to wake at `min(due, next_retry_at)` when any battery has an active retry deadline pending discovery. This eliminates the 60-minute gap and maintains the 30-minute collection cadence.
2. **Log Visibility at INFO Level**:
   - Add `logger.info("Saved telemetry for battery %s", battery_id)` on successful background saves, or record collection pass summaries at `INFO` (e.g. `logger.info("Collection pass completed: %d/%d batteries updated", len(healthy), len(self._config.batteries))`).
   - Demote expected first-attempt cache misses before rediscovery to `DEBUG` or a concise one-line `INFO` without the full scary traceback.

### Step 4: Verification & Validation
1. **Offline Test Suite**:
   - Run `pytest` across all 118+ tests to guarantee zero regressions in request serialization, concurrency, SSE streams, or normal backoff.
2. **Physical Sleep/Resume Validation**:
   - Restart Monbat service under `screen` on the Linux host.
   - Perform a live sleep and resume cycle.
   - Confirm in logs and SQLite that:
     1. Socket disconnection errors are caught and clients discarded cleanly.
     2. Poller performs discovery and successfully reconnects both batteries.
     3. Telemetry rows continue to be saved without restarting Monbat.
