# 09 Implement: FastAPI App, Background Poller & Dashboard (`src/monbat/app.py`)

Type: task
Status: open
Triage: ready-for-agent
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
| `pyproject.toml` | **Modify** — add `fastapi` and `uvicorn` runtime dependencies; `httpx` is already in the dev group for `TestClient` |
| `tests/test_app.py` | **Create** — unit tests for API endpoints using `httpx` + `TestClient` |

### Out of scope

- Historical charting UI (Iteration 2; the `/api/history` endpoint remains in scope).
- Systemd service unit (Iteration 3).

---

## Implementation

### `src/monbat/app.py`

Module layout (top-to-bottom):

```
app.py
├── _load_config(path: str) -> AppConfig         # reads config.toml via tomllib
├── AppConfig (frozen dataclass)                  # poller + server + batteries
├── BatteryConfig (frozen dataclass)              # id, name, address (Bleak identifier)
├── run_poller_task(config, repo) -> None         # async infinite loop
├── build_app(config, repo, *, start_poller=True) -> FastAPI
│                                                # same injected repo used by lifespan and routes
├── lifespan(app)                                 # @asynccontextmanager, starts Poller
├── async route: GET /                             # self-contained HTML dashboard
├── async route: GET /api/latest                   # JSON dict of latest snapshots
└── async route: GET /api/history?hours=24         # JSON list of time-series rows
```

#### Config compatibility

At the config parsing boundary, normalize each battery identifier by preferring
`address` and falling back to legacy `mac_address`. Store only the normalized
value in `BatteryConfig.address`.

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
  - One card per configured battery, joining the API result to its configured
    ID and name; show voltage, current (signed + color-coded), power (W), SOC
    bar (%), remaining / total Ah, cell temp, and BMS temp when telemetry exists.
  - If a configured battery's latest value is `null`, show its configured name
    and a `No reading yet` state; do not access telemetry fields for that value.
  - Cell voltage chips per battery (one `<span>` per cell).
  - Delta imbalance: `max(cells) − min(cells)` in mV.
  - `setInterval(updateDashboard, 10_000)` polling `/api/latest` via `fetch()`.
  - Zero external CDNs, zero web fonts, zero JS libraries.
- Async `GET /api/latest` — awaits the repository and returns one entry for
  every configured battery ID, with `null` when a battery has no reading;
  serialize non-null `BatteryTelemetry` values with `dataclasses.asdict` and
  leave missing readings as `None` for FastAPI to encode as JSON `null`.
- Async `GET /api/history?hours=24` — `since_timestamp = time.time() − hours * 3600`;
  returns `dict[str, list[dict]]` keyed by `battery_id`.

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
  to `null` when the repo has no data.
- `test_latest_returns_data` — stub repo returns a pre-built `BatteryTelemetry`;
  assert JSON keys and values.
- `test_history_returns_list` — stub repo returns two rows; assert list length.
- `test_dashboard_html` — `GET /` returns 200 and `Content-Type: text/html`.

---

## Acceptance criteria

1. `uv run monbat serve` (or bare `uv run monbat`) starts the FastAPI server,
   runs the Poller, and the dashboard is reachable at `http://localhost:8000`.
2. `uv run pytest tests/test_app.py -v` passes offline (no BLE, no disk, stub repo).
3. Dashboard HTML is self-contained — `curl http://localhost:8000/` has no
   external URLs.
4. Poller exceptions are caught per-battery and logged; the loop never crashes.
5. The dashboard handles `null` latest values by showing `No reading yet`
   without raising a client-side error.
6. Strict typing, no `Any`, shallow control flow.

## Comments

- 2026-10-16: Use `httpx` as a dev dependency for `TestClient`. Treat
  `poll_interval_seconds` as the delay after a complete sequential poll pass.

## Answer
