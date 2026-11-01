# 09 Implement: FastAPI App, Background Poller & Dashboard (`src/monbat/app.py`)

Type: task
Status: resolved
Blocked by: 07, 08

## Goal

Implement `src/monbat/app.py` — the single-process FastAPI service that runs the
background Poller (which calls `poll_battery()` + `save_telemetry()` on a
configurable interval) and serves the real-time offline Dashboard.

Wire the `monbat serve` (or bare `monbat`) subcommand into `__init__.py`.

All design decisions are resolved in
[issue 05](05-dashboard-and-fastapi-service.md).

---

## Scope

### Files to create / modify

| Path | Action |
|---|---|
| `src/monbat/app.py` | **Create** — FastAPI app, Poller coroutine, HTML dashboard, API endpoints |
| `src/monbat/__init__.py` | **Modify** — add `serve` / default subcommand routing |
| `pyproject.toml` | **Modify** — add `fastapi` and `uvicorn` runtime dependencies and `httpx2` for `TestClient` |
| `uv.lock` | **Update** — regenerate to include the new runtime dependencies |
| `README.md` | **Modify** — document `monbat serve` and the local Dashboard URL |
| `tests/test_app.py` | **Create** — unit tests for API endpoints using `httpx2` + `TestClient` |

### Out of scope

- Historical charting UI (Iteration 2; the `/api/history` endpoint remains in scope).
- Systemd service unit (Iteration 3).
- Safe rendering hardening for config-provided Dashboard labels is tracked in [issue 10](10-safe-dashboard-config-rendering.md) as a low-priority follow-up.

---

## Implementation

### `src/monbat/app.py`

Module layout (top-to-bottom):

```
app.py
├── _load_config(path: str) -> AppConfig         # reads config.toml via tomllib
├── AppConfig (frozen, slots dataclass)            # PollerConfig + ServerConfig + batteries
├── PollerConfig (frozen, slots dataclass)         # poll interval, timeout, SQLite path
├── ServerConfig (frozen, slots dataclass)         # host and port
├── BatteryConfig (frozen, slots dataclass)        # id, name, address (Bleak identifier)
├── BatteryStatus = Literal[...]                   # no-reading-yet/offline/charging/discharging/idle
├── BatteryLatestView (frozen, slots dataclass)    # config metadata + optional telemetry + view fields
├── run_poller_task(config, repo) -> None         # async infinite loop
├── build_app(config, repo, *, start_poller=True) -> FastAPI
│                                                # same injected repo used by lifespan and routes
├── lifespan(app)                                 # @asynccontextmanager, starts Poller
├── async route: GET /                             # self-contained HTML dashboard
├── async route: GET /api/latest                   # JSON dict of latest snapshots
└── async route: GET /api/history?hours=24         # plain JSON list of time-series rows
```

#### Config compatibility

At the config parsing boundary, normalize each battery identifier by preferring
`address` and falling back to legacy `mac_address`. Store only the normalized
value in `BatteryConfig.address`. Validate parsed TOML values before constructing
typed config dataclasses: require a positive poll interval and timeout, a valid
server port, and batteries with non-empty unique IDs and non-empty names and
addresses. Keep `tomllib`'s untyped mapping values at this boundary; do not let
`Any` leak into the application models. Report missing or malformed `config.toml`
as a clear startup error.

#### Poller coroutine (`run_poller_task`)

```python
async def run_poller_task(config: AppConfig, repo: TelemetryRepository) -> None:
    while True:
        for bat in config.batteries:
            try:
                t = await poll_battery(bat.address, config.poller.timeout_seconds)
                await repo.save_telemetry(bat.id, t)
            except Exception as exc:
                # log warning, continue to next battery
                ...
        await asyncio.sleep(config.poller.poll_interval_seconds)
```

- Guard clause: exceptions are caught per-battery; one failure must not abort
  the entire poll cycle or kill the loop.
- Log to `logging.getLogger(__name__)`.
- `poll_interval_seconds` is the delay after a complete sequential polling pass.

#### FastAPI lifespan pattern (from spec §4.4)

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    await repo.init_db()
    poller_task: asyncio.Task[None] | None = None
    if start_poller:
        poller_task = asyncio.create_task(run_poller_task(config, repo))
    try:
        yield
    finally:
        if poller_task is not None:
            poller_task.cancel()
            try:
                await poller_task
            except asyncio.CancelledError:
                pass
```

`build_app` closes over the injected repository. `serve()` creates the configured
`TelemetryRepository` and passes that same instance to `build_app`; the lifespan
does not construct a second repository.

#### HTTP endpoints

- Async `GET /` — returns a self-contained HTML string (dark-mode dashboard).
  Includes:
  - One card per configured battery using the API view keyed by the same battery
    ID used to query the repository. Show the configured name and address,
    voltage, signed/color-coded current, power, SOC bar, remaining / total Ah,
    cell temperature, and BMS temperature when telemetry exists.
  - If `telemetry` is `null`, show the configured name and `No reading yet`
    without reading telemetry fields.
  - Show a status badge: `no-reading-yet` when no row exists, `offline` when
    the last telemetry timestamp is older than twice the configured poll
    interval, and otherwise `charging`, `discharging`, or `idle` from the sign
    of `current_a`.
  - Cell voltage chips per battery (one `<span>` per cell).
  - Delta imbalance in mV, computed in the API view when cells are present and
    `null` when no cell voltages are available.
  - An immediate first `updateDashboard()` call, then
    `setInterval(updateDashboard, 10_000)` polling `/api/latest` via `fetch()`.
  - Zero external CDNs, zero web fonts, zero JS libraries.
- Async `GET /api/latest` — awaits the repository and returns one entry for
  every configured battery ID. Each value is a `BatteryLatestView` containing
  configured `name` and `address`, `telemetry: BatteryTelemetry | None`, a
  `status`, and `cell_delta_mv: float | None`. The view is matched by
  `BatteryConfig.id` to the database `battery_id`. Serialize the view and its
  non-null telemetry with `dataclasses.asdict`; when no reading exists, keep
  the view object and set `telemetry` to `None` so config details remain
  available to the Dashboard.
- `BatteryLatestView.status` is `no-reading-yet` when no row exists, `offline`
  when `time.time() - telemetry.timestamp > 2 * poll_interval_seconds`, and
  otherwise `charging`, `discharging`, or `idle` based on `current_a`.
  `cell_delta_mv` is `(max(cell_voltages_v) - min(cell_voltages_v)) * 1000`,
  rounded to one decimal place; use `None` for an empty cell tuple. These fields
  are API-view calculations and are not persisted.
- Async `GET /api/history?hours=24` — query each configured `battery_id` from
  `since_timestamp = time.time() - hours * 3600` and return one plain JSON list
  sorted by timestamp ascending across batteries. Each row includes
  `battery_id`, configured `name` and `address`, and the `BatteryTelemetry`
  fields serialized with `dataclasses.asdict`. Require `hours > 0`.

#### `__init__.py` update

```python
match sys.argv[1:]:
    case ["discover"]:
        from monbat.discover import run_discover
        asyncio.run(run_discover())
    case ["serve"] | []:
        from monbat.app import serve
        serve()          # loads config.toml, creates app, calls uvicorn.run()
    case _:
        print("Usage: monbat [discover|serve]")
```

### `tests/test_app.py`

Use `fastapi.testclient.TestClient` (sync) with a stub `TelemetryRepository`
injected via `build_app(config, repo, start_poller=False)`. The stub's
`init_db()` is a no-op, so tests use no disk database and start no BLE polling.

- `test_latest_empty` — `/api/latest` returns every configured battery ID mapped
  to a view with configured name/address, `telemetry: null`, and
  `status: "no-reading-yet"` when the repo has no data.
- `test_latest_returns_data` — stub repo returns a pre-built `BatteryTelemetry`;
  assert the view includes config metadata, nested telemetry fields, status,
  and cell delta.
- `test_latest_marks_stale_reading_offline` — a row older than twice the poll
  interval is marked offline; a current row's charge/discharge/idle state is
  derived from `current_a`.
- `test_history_returns_plain_list` — assert a plain chronological list with
  `battery_id`, configured name/address, and telemetry fields; no matching rows
  returns `[]`.
- `test_config_loads_address_and_legacy_mac_address` — cover the current field,
  legacy fallback, and `address` precedence if both are present.
- `test_poller_continues_after_battery_failure` — make one poll fail and verify
  the next configured battery is still polled and its telemetry is saved.
- `test_dashboard_html` — `GET /` returns 200 and `Content-Type: text/html`.

Manual browser smoke check: open the Dashboard with an empty database and
confirm the first render shows every configured battery with its name, address,
and `No reading yet`; then confirm a saved reading appears on refresh and an
aged reading shows `offline` after the 2x interval threshold.

---

## Acceptance criteria

1. `uv run monbat serve` (or bare `uv run monbat`) starts the FastAPI server,
   runs the Poller, and the dashboard is reachable at `http://localhost:8000`.
2. `uv run pytest tests/test_app.py -v` passes offline (no BLE, no disk, stub repo).
3. Dashboard HTML is self-contained — `curl http://localhost:8000/` has no
   external URLs.
4. Poller exceptions are caught per-battery and logged; the loop never crashes.
5. A battery with no stored telemetry still appears with its configured name
   and address, `No reading yet`, and no telemetry fields.
6. A reading older than twice the configured interval is shown as offline;
   current readings use charging, discharging, or idle status.
7. `/api/history` returns a chronological plain list with battery identity on
   each row.
8. Strict typing, frozen/slots dataclasses, no `Any`, shallow control flow.

## Comments

- 2026-10-16: Use `httpx2` as a dev dependency for `TestClient` with current
  Starlette releases. Treat
  `poll_interval_seconds` as the delay after a complete sequential poll pass.
- 2026-10-16: Include config metadata in latest/history API views, derive status
  from current sign and telemetry age (offline after 2x the poll interval),
  and return history as a plain chronological list.

## Answer

Implemented:

- `src/monbat/app.py` — validated TOML config models, sequential background
  Poller, FastAPI lifespan, config-enriched `/api/latest`, chronological flat
  `/api/history`, and the self-contained responsive Dashboard.
- `src/monbat/__init__.py` — routes `monbat serve` and bare `monbat` to Uvicorn.
- `pyproject.toml` and `uv.lock` — added FastAPI and Uvicorn runtime dependencies
  and `httpx2` for the current Starlette TestClient.
- `README.md` — documented discovery, serving, and the local Dashboard URL.
- `tests/test_app.py` — offline API, config, status, history, and Poller tests.

The latest API matches configured battery IDs to repository records and includes
name/address metadata. It derives `no-reading-yet`, `offline` (older than twice
the poll interval), charging, discharging, or idle status, plus cell delta in
mV. History is a chronological flat list with battery identity on each row.

Verification: `uv run pytest tests/test_app.py -v` — 17 passed. The existing
`config.toml` parsed with two configured batteries. Tests use a stub repository
and do not connect to BLE hardware.
