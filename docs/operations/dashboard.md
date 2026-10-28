# Dashboard

Open <http://localhost:8000> after starting the service. The Dashboard works
without external scripts, fonts, or network services.

Battery names and addresses render as literal text, including quotes and
HTML-looking labels.

## Refresh and freshness

The Dashboard opens `/api/events` through native JavaScript `EventSource`.
The stream sends an initial stored snapshot and checks for saved Telemetry and
freshness transitions every second. Reconnection is automatic; multiple tabs
share one Poller. Hidden tabs count as connected subscribers.

The first subscriber wakes collection immediately. While subscribed, collection
uses `active_interval_seconds` (default 10), measured between scheduled starts.
Missed slots are skipped; requests to one Battery never overlap. After the last
subscriber disconnects, a 30-second grace period allows reloads/reconnections.
Then BLE clients close and the long background cadence resumes.

Persistent connections are enabled by default during active collection.
The service logs each persistent connection start and successful finish at INFO
level with the Battery ID. Disconnect failures are logged at WARNING level.
Service and HTTP access logs include the local server timestamp.
`concurrency` limits simultaneous status requests, independently of how many
BLE connections remain open. Background passes connect, read, and disconnect.
Failures retain previous readings and retry with 10/20/40/60-second backoff,
subject to the current collection cadence. Healthy Batteries continue updating.
Each Battery card shows its last Telemetry timestamp in the browser's local time
as `YYYY-MM-DD HH:mm:ss`.

## BLE recovery

For sleep/resume diagnosis, start `uv run monbat serve --log-level debug`.
The default level remains INFO. Logs tagged `[DEBUG-resume]` report subscriber counts and grace,
scheduler wakes and pass timing, deferred Batteries and retry deadlines,
cached/discovered recovery, BLE connect/notification/write/read/disconnect
stages, and saved Telemetry timestamps. Monotonic deadlines describe scheduling;
log timestamps describe wall-clock time. An operation start without its
completion, followed by a failure traceback, identifies the interrupted stage.
The driver logs response sizes, without dumping payloads or changing BLE work.
SSE snapshot logs show when an updated snapshot is yielded; browser receipt
must still be confirmed through the Dashboard or a stream capture.
DEBUG does not enable Bleak-wide tracing. Preserve output, for example with
screen's `-L -Logfile` options, and capture OS suspend/resume and Bluetooth
journal evidence separately. Use INFO again after the validation session.

The Poller caches each configured Battery's discovered `BLEDevice` in memory
for the service lifetime. Active and background connections use that cache.
Closing a connection, a scan miss, or a scan error keeps the cached object;
a new matching discovery result replaces it. Restarting requires discovery
again. Device details are never written to configuration or SQLite.

Each pass finishes healthy retained reads before recovery. A failed read
enters backoff and closes its old client before a replacement can connect on
a later eligible pass. A failed or timed-out disconnect retains the client
and blocks replacement until cleanup succeeds after backoff.

Recovery connects with the cached object, subscribes to notifications, and
reads a fresh validated response. A failed direct attempt schedules one shared
rediscovery for the next eligible retry. A discovery attempt, scan miss, or
scan error then returns to direct cached recovery after backoff. Uncached
Batteries keep using discovery. There is no second attempt for the same Battery
in one pass. Recovery can delay the following pass; scheduling remains shared.

On Linux, the cached object requires its BlueZ Device1 object to exist. A
`device ... not found` failure follows the same deferred rediscovery path;
the cache does not preserve BlueZ state. The Poller does not retry with a string
address that would cause Bleak to scan implicitly.

Only successful Telemetry persistence clears backoff. Database errors retain
the BLE cache and healthy active connection, using polling retries without
rediscovery. Background clients still disconnect after each read.

Shutdown attempts one final bounded disconnect for every retained client,
including failed setup and pending cleanup. Failures are logged and shutdown
finishes; release of the OS or BMS connection cannot be guaranteed. Recovery
does not reset the adapter or the BMS.

Readings older than `freshness_seconds` are offline; equality is still fresh.
Failed polls retain the last successful reading and its original timestamp.
HTTP failures retain Battery cards and report connection failure.
Each update handles refresh/latest and summary outcomes together. A summary
failure hides bank totals while successful Battery readings still update.

## Parallel Battery Bank

The section above Battery cards combines all configured Batteries connected
in parallel at the same nominal voltage. SOC is weighted by each Battery's
full charge capacity. Each Battery contributes BMS-reported SOC when available,
otherwise its capacity estimate. Net power sums signed watts: positive means
charging, negative means discharging, and zero means idle.

Totals disappear when any Battery has missing/stale readings or nonpositive
full charge capacity. Individual cards retain their last readings. A summary
request failure also hides the totals.

## API

| Endpoint | Behavior |
|---|---|
| `GET /api/events` | SSE snapshots containing `latest` and `summary`; subscriber presence controls active collection |
| `GET /api/latest` | Stored readings keyed by configured Battery ID, with reading status and cell delta |
| `POST /api/refresh` | Returns `accepted`, `skipped`, or `disabled`; acceptance schedules a pass without waiting for BLE |
| `GET /api/summary` | Availability, capacity-weighted SOC, signed net watts, and unavailable reason |
| `GET /api/history?hours=24` | Chronological Telemetry rows; hours must be positive |

## Browser regression tests

Install Chromium once after syncing development dependencies:

```sh
uv run playwright install chromium
uv run pytest -m 'not integration'
```

On Linux, `uv run playwright install --with-deps chromium` also installs the
browser's system dependencies. Playwright is used only for tests. Tests route
browser requests through the test app and require no Bluetooth connection.
