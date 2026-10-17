# Dashboard

Open <http://localhost:8000> after starting the service. The Dashboard works
without external scripts, fonts, or network services.

Battery names and addresses render as literal text, including quotes and
HTML-looking labels.

## Refresh and freshness

Page load and the 30-second update timer request an asynchronous BLE pass and
read stored Telemetry immediately. New readings appear on a later update.
One sequential Poller handles background polling and page requests.

Requests during an active or scheduled pass, or within 30 seconds of the last
pass starting, are skipped without a queued retry. This applies across tabs.
An accepted request wakes the Poller early; the configured background delay
restarts after the pass finishes. Background polling continues with no page open.

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
