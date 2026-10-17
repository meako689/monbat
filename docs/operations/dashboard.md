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
`concurrency` limits simultaneous status requests, independently of how many
BLE connections remain open. Background passes connect, read, and disconnect.
Failures retain previous readings and retry with 10/20/40/60-second backoff,
subject to the current collection cadence. Healthy Batteries continue updating.

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
